#!/usr/bin/env python3
"""Sync model checkpoints from Hugging Face into the models S3 bucket.

Purpose:
- Phase 0's model download is entirely manual, over an SSM session on the
  gpu_worker instance. This runs locally instead: downloading a checkpoint
  needs internet + AWS credentials, not GPU compute, so there's no reason
  to pay for gpu_worker uptime just to sync one (wayfinder ticket #32).
- The list of models to sync lives in config/model_manifest.json, so
  adding a new checkpoint is a one-line JSON edit, not a code change.

Flow:
- Parse environment from CLI args.
- Optionally read HF_TOKEN from a local .env (gitignored) for a gated
  repo -- unset by default, since today's checkpoints are all public.
- For each manifest entry, download via huggingface_hub, then upload to
  s3://<models bucket>/checkpoints/<filename>.

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
S3_PREFIX = "checkpoints"


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


def load_manifest(manifest_path: Path = MANIFEST_PATH) -> list[dict]:
    """Return the list of {repo_id, filename} entries to sync."""
    return json.loads(manifest_path.read_text(encoding="utf-8"))


def sync_model(
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
    key = f"{S3_PREFIX}/{filename}"
    mlog.info("Uploading %s to s3://%s/%s", local_path, bucket, key)
    s3.upload_file(local_path, bucket, key)
    return key


def sync_all(
    app_env: str, manifest_path: Path = MANIFEST_PATH, s3_client=None
) -> list[str]:
    """Sync every manifest entry into app_env's models bucket; return S3 keys."""
    check_app_env(app_env)
    check_aws_account(app_env)
    data_path = get_actual_path(app_env)
    env_setting = EnvironmentSetting.from_data_path(data_path)
    models_input = SimpleS3Input.from_config_directory(
        data_path, "models", env_setting=env_setting
    )
    bucket = models_input.bucket_name()
    hf_token = _read_dotenv_value("HF_TOKEN")

    s3 = s3_client or boto3.client(
        "s3", region_name=env_setting.default_region
    )
    return [
        sync_model(
            entry["repo_id"],
            entry["filename"],
            bucket,
            hf_token=hf_token,
            s3_client=s3,
        )
        for entry in load_manifest(manifest_path)
    ]


def get_args() -> argparse.Namespace:
    """Parse environment from CLI args."""
    parser = argparse.ArgumentParser(
        description="Sync HF model checkpoints into the models S3 bucket."
    )
    parser.add_argument("environment", choices=list(SUPPORTED_APP_ENVS))
    return parser.parse_args()


def main() -> None:
    """Sync every manifest entry and print the S3 key it landed at."""
    args = get_args()
    for key in sync_all(args.environment):
        print(f"Synced {key}")


if __name__ == "__main__":
    main()
