#!/usr/bin/env python3
"""Explore-A worker: SQS poll -> Ollama prompt expansion -> ComfyUI batch
generation -> S3 upload -> delete message.

Purpose:
- Consume Character-A explore jobs (`{"seed_prompt": str, "batch_size":
  int, "job_id": str (optional)}`) from explore-a-queue.
- Expand the seed prompt into `batch_size` SD-style prompt variants via a
  local Ollama model (Plush's Advanced Prompt Enhancer pattern -- see
  research/local-llm-image-generation.md).
- Submit one ComfyUI generation per expanded prompt, wait for it to
  finish, and upload the resulting image(s) to
  `s3://<bucket>/explore/{job_id}/{filename}`.
- Delete the SQS message only after every image for the job has uploaded
  -- a failure anywhere in that chain leaves the message for SQS's own
  visibility-timeout-based redelivery (and eventual DLQ) instead of
  silently losing the job.

Flow:
- `main()` reads `WorkerConfig` from the environment and calls
  `poll_queue()`, which loops forever.
- `poll_queue()` receives one message at a time and calls `process_job()`.

Customize:
- `WorkerConfig`'s environment variable names.
- `EXPAND_SYSTEM_PROMPT` for the Ollama prompt-expansion instructions.
"""

import json
import logging
import os
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

import boto3
import requests

LOG = logging.getLogger(__name__)

EXPAND_SYSTEM_PROMPT = (
    "You are a Stable Diffusion prompt writer. Given a character "
    "description, produce a JSON array of {batch_size} image prompts. "
    "Each prompt should vary the setting, lighting, mood, and composition "
    "while keeping the character consistent. Each prompt must be a dense "
    "keyword string in SD style (comma-separated, no sentences). Output "
    'only valid JSON: {{"prompts": ["...", "..."]}}.'
)


@dataclass(frozen=True, kw_only=True)
class WorkerConfig:  # pylint: disable=too-many-instance-attributes
    """Runtime configuration for the explore-a worker, from env vars."""

    queue_url: str
    output_bucket: str
    comfyui_url: str = "http://localhost:8188"
    ollama_url: str = "http://localhost:11434"
    ollama_model: str = "llama3.1"
    comfyui_output_dir: Path = Path("/opt/comfyui/output")
    workflow_template_path: Path = Path(
        "/opt/comfyui/workflows/txt2img-example.json"
    )
    aws_region: str = "us-east-1"
    poll_wait_seconds: int = 20
    comfyui_poll_interval_seconds: int = 5
    comfyui_timeout_seconds: int = 300

    @classmethod
    def from_env(cls, env: Mapping[str, str]) -> "WorkerConfig":
        """Build config from a mapping of environment variables."""
        defaults = cls(queue_url="", output_bucket="")
        return cls(
            queue_url=env["QUEUE_URL"],
            output_bucket=env["OUTPUT_BUCKET"],
            comfyui_url=env.get("COMFYUI_URL", defaults.comfyui_url),
            ollama_url=env.get("OLLAMA_URL", defaults.ollama_url),
            ollama_model=env.get("OLLAMA_MODEL", defaults.ollama_model),
            comfyui_output_dir=Path(
                env.get("COMFYUI_OUTPUT_DIR", str(defaults.comfyui_output_dir))
            ),
            workflow_template_path=Path(
                env.get(
                    "WORKFLOW_TEMPLATE_PATH",
                    str(defaults.workflow_template_path),
                )
            ),
            aws_region=env.get("AWS_REGION", defaults.aws_region),
        )


def find_node_id(workflow: dict, class_type: str) -> str:
    """Return the first node id in a workflow graph with this class_type."""
    for node_id, node in workflow.items():
        if node.get("class_type") == class_type:
            return node_id
    raise ValueError(f"No {class_type} node found in workflow")


def build_workflow(
    template: dict, prompt: str, seed: int, filename_prefix: str
) -> dict:
    """Return a copy of template with the prompt, seed, and prefix set.

    Targets the positive CLIPTextEncode via KSampler's own `positive` link
    (not "the first CLIPTextEncode found") so it's correct regardless of
    node ordering in the template file.
    """
    workflow = json.loads(json.dumps(template))
    sampler_id = find_node_id(workflow, "KSampler")
    positive_node_id = workflow[sampler_id]["inputs"]["positive"][0]
    workflow[positive_node_id]["inputs"]["text"] = prompt
    workflow[sampler_id]["inputs"]["seed"] = seed
    save_id = find_node_id(workflow, "SaveImage")
    workflow[save_id]["inputs"]["filename_prefix"] = filename_prefix
    return workflow


def expand_prompts(
    seed_prompt: str,
    batch_size: int,
    ollama_url: str,
    ollama_model: str,
) -> list[str]:
    """Expand a seed prompt into batch_size SD-style prompt variants."""
    system_prompt = EXPAND_SYSTEM_PROMPT.format(batch_size=batch_size)
    response = requests.post(
        f"{ollama_url}/api/chat",
        json={
            "model": ollama_model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": seed_prompt},
            ],
            "format": {
                "type": "object",
                "properties": {
                    "prompts": {
                        "type": "array",
                        "items": {"type": "string"},
                    }
                },
                "required": ["prompts"],
            },
            "stream": False,
        },
        timeout=120,
    )
    response.raise_for_status()
    content = response.json()["message"]["content"]
    prompts = json.loads(content)["prompts"]
    return list(prompts)


def submit_to_comfyui(workflow: dict, comfyui_url: str) -> str:
    """POST a workflow to ComfyUI and return its prompt_id."""
    response = requests.post(
        f"{comfyui_url}/prompt", json={"prompt": workflow}, timeout=30
    )
    response.raise_for_status()
    body = response.json()
    if body.get("node_errors"):
        raise RuntimeError(f"ComfyUI rejected workflow: {body['node_errors']}")
    return str(body["prompt_id"])


def wait_for_comfyui_job(  # pylint: disable=too-many-arguments,too-many-positional-arguments
    comfyui_url: str,
    prompt_id: str,
    save_node_id: str,
    timeout_seconds: int,
    poll_interval_seconds: int,
) -> list[dict]:
    """Poll ComfyUI's history until prompt_id completes; return image infos."""
    deadline = time.monotonic() + timeout_seconds
    while True:
        response = requests.get(
            f"{comfyui_url}/history/{prompt_id}", timeout=30
        )
        response.raise_for_status()
        history = response.json()
        if prompt_id in history:
            outputs = history[prompt_id].get("outputs", {})
            images = outputs.get(save_node_id, {}).get("images", [])
            if images:
                return images
        if time.monotonic() >= deadline:
            raise TimeoutError(
                f"ComfyUI job {prompt_id} did not finish within "
                f"{timeout_seconds}s"
            )
        time.sleep(poll_interval_seconds)


def upload_images_to_s3(
    images: list[dict],
    output_dir: Path,
    bucket: str,
    job_id: str,
    s3_client,
) -> list[str]:
    """Upload each ComfyUI-reported output image to S3; return the S3 keys."""
    keys = []
    for image in images:
        subfolder = image.get("subfolder", "")
        local_path = output_dir / subfolder / image["filename"]
        key = f"explore/{job_id}/{image['filename']}"
        s3_client.upload_file(str(local_path), bucket, key)
        keys.append(key)
    return keys


def process_job(  # pylint: disable=too-many-locals
    job: dict, config: WorkerConfig, s3_client
) -> list[str]:
    """Expand, generate, and upload every image for one job; return S3 keys."""
    job_id = job.get("job_id") or str(uuid.uuid4())
    seed_prompt = job["seed_prompt"]
    batch_size = int(job["batch_size"])

    template = json.loads(
        config.workflow_template_path.read_text(encoding="utf-8")
    )
    save_node_id = find_node_id(template, "SaveImage")

    prompts = expand_prompts(
        seed_prompt, batch_size, config.ollama_url, config.ollama_model
    )

    all_keys: list[str] = []
    for index, prompt in enumerate(prompts):
        seed = uuid.uuid4().int % (2**53)
        filename_prefix = f"{job_id}_{index}"
        workflow = build_workflow(template, prompt, seed, filename_prefix)
        prompt_id = submit_to_comfyui(workflow, config.comfyui_url)
        images = wait_for_comfyui_job(
            config.comfyui_url,
            prompt_id,
            save_node_id,
            config.comfyui_timeout_seconds,
            config.comfyui_poll_interval_seconds,
        )
        all_keys.extend(
            upload_images_to_s3(
                images,
                config.comfyui_output_dir,
                config.output_bucket,
                job_id,
                s3_client,
            )
        )
    return all_keys


def poll_queue(config: WorkerConfig, sqs_client, s3_client) -> None:
    """Poll the queue forever, processing and deleting one message at a time."""
    LOG.info("Polling %s", config.queue_url)
    while True:
        response = sqs_client.receive_message(
            QueueUrl=config.queue_url,
            MaxNumberOfMessages=1,
            WaitTimeSeconds=config.poll_wait_seconds,
        )
        messages = response.get("Messages", [])
        if not messages:
            continue
        message = messages[0]
        try:
            job = json.loads(message["Body"])
            keys = process_job(job, config, s3_client)
            LOG.info("Job complete, uploaded: %s", keys)
        except Exception:  # pylint: disable=broad-exception-caught
            # Leave the message alone on any failure: SQS's visibility
            # timeout expiring redelivers it (up to the queue's configured
            # max receive count) before it lands in the DLQ, rather than
            # this worker silently losing the job on a transient error.
            LOG.exception(
                "Failed to process message %s; leaving for redelivery",
                message["MessageId"],
            )
            continue
        sqs_client.delete_message(
            QueueUrl=config.queue_url, ReceiptHandle=message["ReceiptHandle"]
        )


def main() -> None:
    """Entry point: build config from the environment and poll forever."""
    logging.basicConfig(level=logging.INFO)
    config = WorkerConfig.from_env(os.environ)
    sqs_client = boto3.client("sqs", region_name=config.aws_region)
    s3_client = boto3.client("s3", region_name=config.aws_region)
    poll_queue(config, sqs_client, s3_client)


if __name__ == "__main__":
    main()
