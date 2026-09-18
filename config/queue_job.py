#!/usr/bin/env python3
"""Send an explore-a-queue job for Phase 1 UAT.

Purpose:
- Wraps the two AWS CLI calls from README.md's "Test Phase 1 (UAT)" section
  (`aws sqs get-queue-url` + `aws sqs send-message`) into one python
  invocation, mirroring asg_scale.py/comfyui_client.py's pattern of
  resolving real deployed identifiers from config rather than hardcoding
  them.

Flow:
- Parse environment/seed_prompt/batch_size and options from CLI args.
- send_job() resolves the queue's physical name via SqsQueueInput's own
  queue_name() (deterministic -- no CloudFormation lookup needed, unlike
  the ASG/ComfyUI modules), asks SQS for its URL, and sends the job body.

Customize:
- --stack-id/--images-stack-id if a queue or images bucket other than the
  registry's defaults is targeted.
"""

# pylint: disable=duplicate-code
# Shares the check_app_env/check_aws_account/get_actual_path/EnvironmentSetting
# resolution prologue with config/comfyui_client.py by design (see module
# docstring) — every config.* CLI module resolves its config directory and
# region the same way; not accidental duplication to refactor.
import argparse
import json
import uuid

import boto3

from config.helper import check_app_env, check_aws_account, get_logger
from config.project import SUPPORTED_APP_ENVS
from config.registry import DEFAULT_IMAGES_STACK_ID, DEFAULT_QUEUE_STACK_ID
from config.settings import EnvironmentSetting, get_actual_path
from stack.simple_s3 import SimpleS3Input
from stack.sqs_queue import SqsQueueInput

mlog = get_logger(str(__name__))


def send_job(  # pylint: disable=too-many-arguments,too-many-positional-arguments
    app_env: str,
    seed_prompt: str,
    batch_size: int,
    job_id: str | None = None,
    stack_id: str = DEFAULT_QUEUE_STACK_ID,
    sqs_client=None,
) -> str:
    """Send one explore-a-queue job; return the job_id used."""
    check_app_env(app_env)
    check_aws_account(app_env)
    data_path = get_actual_path(app_env)
    env_setting = EnvironmentSetting.from_data_path(data_path)
    region = env_setting.default_region

    sqs = sqs_client or boto3.client("sqs", region_name=region)

    s_input = SqsQueueInput.from_config_directory(
        data_path, stack_id, env_setting=env_setting
    )
    queue_url = sqs.get_queue_url(QueueName=s_input.queue_name())["QueueUrl"]

    job_id = job_id or str(uuid.uuid4())
    body = json.dumps(
        {
            "seed_prompt": seed_prompt,
            "batch_size": batch_size,
            "job_id": job_id,
        }
    )
    mlog.info("Sending job %s to %s", job_id, queue_url)
    sqs.send_message(QueueUrl=queue_url, MessageBody=body)
    return job_id


def get_args() -> argparse.Namespace:
    """Parse environment/seed_prompt/batch_size and options from CLI args."""
    parser = argparse.ArgumentParser(
        description="Send an explore-a-queue job for Phase 1 UAT."
    )
    parser.add_argument("environment", choices=list(SUPPORTED_APP_ENVS))
    parser.add_argument("seed_prompt")
    parser.add_argument("batch_size", type=int)
    parser.add_argument("--job-id", default=None)
    parser.add_argument("--stack-id", default=DEFAULT_QUEUE_STACK_ID)
    parser.add_argument("--images-stack-id", default=DEFAULT_IMAGES_STACK_ID)
    return parser.parse_args()


def main() -> None:
    """Send the requested job and print where its output will land."""
    args = get_args()
    job_id = send_job(
        args.environment,
        args.seed_prompt,
        args.batch_size,
        job_id=args.job_id,
        stack_id=args.stack_id,
    )
    data_path = get_actual_path(args.environment)
    env_setting = EnvironmentSetting.from_data_path(data_path)
    images_input = SimpleS3Input.from_config_directory(
        data_path, args.images_stack_id, env_setting=env_setting
    )
    print(f"Sent job {job_id}")
    print(
        f"Check s3://{images_input.bucket_name()}/explore/{job_id}/ "
        "for output"
    )


if __name__ == "__main__":
    main()
