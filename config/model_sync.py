#!/usr/bin/env python3
"""Sync model content (HF checkpoints + Ollama LLM) into the models bucket.

Purpose:
- Phase 0's checkpoint download was entirely manual, over an SSM session
  on the gpu_worker instance. Both syncs here run locally instead: they
  need internet + AWS credentials, not GPU compute, so there's no reason
  to pay for gpu_worker uptime just to sync content (wayfinder ticket
  #32).
- Pulling Ollama's model live from its own registry at every instance
  boot depends on that registry being reachable at exactly that moment --
  live UAT hit this directly (10 automated `ollama pull` attempts failed
  in ~1s combined right after boot, while a manual pull moments later on
  the same instance succeeded in seconds -- almost certainly a boot-time
  timing/resource-contention issue, not a persistent block, but the fix
  is the same either way: stop depending on it). The bucket is instead
  the single source of truth for both checkpoints and the Ollama model,
  same as ticket #32 already decided for checkpoints alone.
- The manifest (config/model_manifest.json) is a single small JSON edit
  to add a new checkpoint or Ollama model -- no code change needed.

Flow:
- Parse environment from CLI args.
- sync_checkpoints(): for each manifest checkpoint entry, download via
  huggingface_hub (optionally with an HF_TOKEN read from a gitignored
  .env, for a gated repo -- unset by default), then upload to
  s3://<models bucket>/checkpoints/<filename>.
- sync_ollama_models(): for each manifest Ollama model name, `ollama
  pull` it locally (requires Ollama installed on this machine), then
  `aws s3 sync` the local Ollama models directory to
  s3://<models bucket>/ollama/.

Customize:
- Add/remove entries in config/model_manifest.json.
"""

# pylint: disable=duplicate-code
# Shares the check_app_env/check_aws_account/get_actual_path/EnvironmentSetting
# resolution prologue with config/comfyui_client.py and config/queue_job.py
# by design -- every config.* CLI module resolves its config directory and
# region the same way; not accidental duplication to refactor.
import argparse
import json
import os
import subprocess
from pathlib import Path

import boto3
from huggingface_hub import hf_hub_download

from config.helper import (
    PROJECT_ROOT,
    check_app_env,
    check_aws_account,
    get_logger,
)
from config.project import SUPPORTED_APP_ENVS
from config.settings import EnvironmentSetting, get_actual_path
from stack.simple_s3 import SimpleS3Input

mlog = get_logger(str(__name__))

MANIFEST_PATH = PROJECT_ROOT / "config" / "model_manifest.json"
CHECKPOINTS_S3_PREFIX = "checkpoints"
OLLAMA_S3_PREFIX = "ollama"


def _read_dotenv_value(
    key: str, dotenv_path: Path = PROJECT_ROOT / ".env"
) -> str | None:
    """Return one KEY=VALUE from a local .env file, or None if absent."""
    if not dotenv_path.is_file():
        return None
    for line in dotenv_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        found_key, _, value = line.partition("=")
        if found_key.strip() == key:
            return value.strip().strip('"').strip("'")
    return None


def load_manifest(manifest_path: Path = MANIFEST_PATH) -> dict:
    """Return the manifest dict: {"checkpoints": [...], "ollama_models": [...]}."""
    return json.loads(manifest_path.read_text(encoding="utf-8"))


def _models_bucket_name(app_env: str, env_setting: EnvironmentSetting) -> str:
    """Return the physical name of app_env's models SimpleS3 bucket."""
    data_path = get_actual_path(app_env)
    models_input = SimpleS3Input.from_config_directory(
        data_path, "models", env_setting=env_setting
    )
    return models_input.bucket_name()


def sync_checkpoint(
    repo_id: str,
    filename: str,
    bucket: str,
    hf_token: str | None = None,
    s3_client=None,
) -> str:
    """Download one file from Hugging Face and upload it to the models bucket."""
    s3 = s3_client or boto3.client("s3")
    local_path = hf_hub_download(
        repo_id=repo_id, filename=filename, token=hf_token
    )
    key = f"{CHECKPOINTS_S3_PREFIX}/{filename}"
    mlog.info("Uploading %s to s3://%s/%s", local_path, bucket, key)
    s3.upload_file(local_path, bucket, key)
    return key


def sync_checkpoints(
    app_env: str, manifest_path: Path = MANIFEST_PATH, s3_client=None
) -> list[str]:
    """Sync every manifest checkpoint into app_env's models bucket."""
    check_app_env(app_env)
    check_aws_account(app_env)
    data_path = get_actual_path(app_env)
    env_setting = EnvironmentSetting.from_data_path(data_path)
    bucket = _models_bucket_name(app_env, env_setting)
    hf_token = _read_dotenv_value("HF_TOKEN")

    s3 = s3_client or boto3.client(
        "s3", region_name=env_setting.default_region
    )
    return [
        sync_checkpoint(
            entry["repo_id"],
            entry["filename"],
            bucket,
            hf_token=hf_token,
            s3_client=s3,
        )
        for entry in load_manifest(manifest_path).get("checkpoints", [])
    ]


def local_ollama_models_dir() -> Path:
    """Return this machine's local Ollama models directory.

    Respects the OLLAMA_MODELS env var (same variable Ollama itself
    reads); otherwise Ollama's own default of ~/.ollama/models.
    """
    override = os.environ.get("OLLAMA_MODELS")
    if override:
        return Path(override)
    return Path.home() / ".ollama" / "models"


def sync_ollama_models(
    app_env: str,
    manifest_path: Path = MANIFEST_PATH,
    models_dir: Path | None = None,
    runner=subprocess.run,
) -> list[str]:
    """Pull each manifest Ollama model locally, then sync it all to S3.

    Requires Ollama installed on this machine (`ollama pull` runs here,
    not on any gpu_worker instance) -- see the module docstring for why.
    """
    check_app_env(app_env)
    check_aws_account(app_env)
    env_setting = EnvironmentSetting.from_data_path(get_actual_path(app_env))
    bucket = _models_bucket_name(app_env, env_setting)

    model_names = load_manifest(manifest_path).get("ollama_models", [])
    for model_name in model_names:
        mlog.info("Pulling Ollama model %s locally", model_name)
        runner(["ollama", "pull", model_name], check=True)

    local_dir = models_dir or local_ollama_models_dir()
    destination = f"s3://{bucket}/{OLLAMA_S3_PREFIX}/"
    mlog.info("Syncing %s to %s", local_dir, destination)
    runner(["aws", "s3", "sync", str(local_dir), destination], check=True)
    return model_names


def get_args() -> argparse.Namespace:
    """Parse environment from CLI args."""
    parser = argparse.ArgumentParser(
        description=(
            "Sync HF checkpoints and Ollama models into the models S3 "
            "bucket."
        )
    )
    parser.add_argument("environment", choices=list(SUPPORTED_APP_ENVS))
    return parser.parse_args()


def main() -> None:
    """Sync every manifest entry and print what landed where."""
    args = get_args()
    for key in sync_checkpoints(args.environment):
        print(f"Synced {key}")
    for model_name in sync_ollama_models(args.environment):
        print(f"Synced ollama model {model_name}")


if __name__ == "__main__":
    main()
