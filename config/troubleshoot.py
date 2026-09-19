#!/usr/bin/env python3
"""Gather Phase 1 diagnostics (SQS state + instance-side systemd/journal
state) into troubleshoot.log.

Purpose:
- Messages stuck in explore-a-queue with an empty explore-worker.service
  journal usually means userdata aborted partway through -- its
  `set -euxo pipefail` kills the whole script on the first failing
  command, so e.g. an Ollama install failure would also silently prevent
  comfyui.service and explore-worker.service from ever being created.
  cloud-init's own userdata output log is the only place that shows where
  it actually stopped.
- Runs one SSM RunShellScript command against the gpu_worker instance
  instead of a manual `aws ssm start-session`, so every relevant signal
  (systemd status/journals for all three services, the userdata output
  log, checkpoint/worker-file presence, Ollama's model list, disk space)
  comes back in one shot.

Flow:
- Parse environment/stack ids from CLI args.
- resolve_instance_id() finds the gpu_worker's current instance via its
  ASG (same CloudFormation/AutoScaling lookup as comfyui_client.py).
- run_diagnostics() sends one AWS-RunShellScript SSM command and polls
  for completion.
- queue_attributes() reads SQS's own message counts directly (no
  instance involved).
- Everything is written to troubleshoot.log (gitignored) and printed.

Customize:
- DIAGNOSTIC_COMMANDS below.
"""

# pylint: disable=duplicate-code
# Shares the check_app_env/check_aws_account/get_actual_path/EnvironmentSetting
# resolution prologue with config/comfyui_client.py and config/queue_job.py
# by design -- every config.* CLI module resolves its config directory and
# region the same way; not accidental duplication to refactor.
import argparse
import time
from pathlib import Path

import boto3
from botocore.exceptions import ClientError

from config.helper import (
    asg_physical_name,
    check_app_env,
    check_aws_account,
    get_logger,
)
from config.project import SUPPORTED_APP_ENVS
from config.registry import DEFAULT_QUEUE_STACK_ID
from config.settings import EnvironmentSetting, get_actual_path
from stack.simple_asg import SimpleAsgInput
from stack.sqs_queue import SqsQueueInput

mlog = get_logger(str(__name__))

LOG_PATH = Path("troubleshoot.log")

DIAGNOSTIC_COMMANDS = [
    "echo '--- systemctl status ---'",
    "sudo systemctl status comfyui.service ollama.service "
    "explore-worker.service --no-pager || true",
    "echo '--- explore-worker journal (last 200 lines) ---'",
    "sudo journalctl -u explore-worker.service -n 200 --no-pager || true",
    "echo '--- comfyui journal (last 100 lines) ---'",
    "sudo journalctl -u comfyui.service -n 100 --no-pager || true",
    "echo '--- ollama journal (last 100 lines) ---'",
    "sudo journalctl -u ollama.service -n 100 --no-pager || true",
    "echo '--- cloud-init userdata output (last 300 lines) ---'",
    "sudo tail -n 300 /var/log/cloud-init-output.log || true",
    "echo '--- checkpoints on disk ---'",
    "ls -la /opt/comfyui/models/checkpoints/ 2>&1 || true",
    "echo '--- worker files on disk ---'",
    "ls -la /opt/comfyui/explore_worker.py /opt/comfyui/workflows/ "
    "/etc/default/explore-worker 2>&1 || true",
    "echo '--- explore-worker env file ---'",
    "cat /etc/default/explore-worker 2>&1 || true",
    "echo '--- ollama models ---'",
    "sudo -u ubuntu ollama list 2>&1 || true",
    "echo '--- disk space ---'",
    "df -h / || true",
]


def resolve_instance_id(
    app_env: str,
    stack_id: str = "comfyui",
    cfn_client=None,
    autoscaling_client=None,
) -> str:
    """Resolve the gpu_worker's current instance id via its ASG."""
    check_app_env(app_env)
    check_aws_account(app_env)
    data_path = get_actual_path(app_env)
    env_setting = EnvironmentSetting.from_data_path(data_path)
    region = env_setting.default_region

    cfn = cfn_client or boto3.client("cloudformation", region_name=region)
    autoscaling = autoscaling_client or boto3.client(
        "autoscaling", region_name=region
    )

    s_input = SimpleAsgInput.from_config_directory(
        data_path, stack_id, env_setting=env_setting
    )
    stack_name = f"{s_input.prefix()}Stack"
    asg_name = asg_physical_name(cfn, stack_name)
    if asg_name is None:
        raise RuntimeError(
            f"No deployed AutoScalingGroup found for stack {stack_name}"
        )

    instances = autoscaling.describe_auto_scaling_groups(
        AutoScalingGroupNames=[asg_name]
    )["AutoScalingGroups"][0]["Instances"]
    if not instances:
        raise RuntimeError(f"No running instances in ASG {asg_name}")
    return instances[0]["InstanceId"]


def run_diagnostics(  # pylint: disable=too-many-arguments,too-many-positional-arguments
    instance_id: str,
    commands: list[str] | None = None,
    ssm_client=None,
    poll_interval_seconds: int = 3,
    timeout_seconds: int = 120,
) -> str:
    """Run one SSM RunShellScript command on instance_id; return its output."""
    ssm = ssm_client or boto3.client("ssm")
    command_id = ssm.send_command(
        InstanceIds=[instance_id],
        DocumentName="AWS-RunShellScript",
        Parameters={"commands": commands or DIAGNOSTIC_COMMANDS},
    )["Command"]["CommandId"]

    deadline = time.monotonic() + timeout_seconds
    invocation = None
    while True:
        try:
            invocation = ssm.get_command_invocation(
                CommandId=command_id, InstanceId=instance_id
            )
        except ClientError as exc:
            # SendCommand's invocation record can take a moment to
            # propagate -- GetCommandInvocation returning this right after
            # SendCommand just means "not visible yet", not a failure.
            if exc.response["Error"]["Code"] != "InvocationDoesNotExist":
                raise
        if invocation is not None and invocation["Status"] not in (
            "Pending",
            "InProgress",
            "Delayed",
        ):
            break
        if time.monotonic() >= deadline:
            raise TimeoutError(
                f"SSM command {command_id} did not finish within "
                f"{timeout_seconds}s"
            )
        time.sleep(poll_interval_seconds)

    output = invocation["StandardOutputContent"]
    if invocation["StandardErrorContent"]:
        output += "\n--- stderr ---\n" + invocation["StandardErrorContent"]
    return output


def queue_attributes(
    app_env: str, stack_id: str = DEFAULT_QUEUE_STACK_ID, sqs_client=None
) -> dict:
    """Return this queue's and its DLQ's message-count attributes."""
    check_app_env(app_env)
    check_aws_account(app_env)
    data_path = get_actual_path(app_env)
    env_setting = EnvironmentSetting.from_data_path(data_path)
    sqs = sqs_client or boto3.client(
        "sqs", region_name=env_setting.default_region
    )

    s_input = SqsQueueInput.from_config_directory(
        data_path, stack_id, env_setting=env_setting
    )
    queue_name = s_input.queue_name()
    queue_url = sqs.get_queue_url(QueueName=queue_name)["QueueUrl"]
    dlq_url = sqs.get_queue_url(QueueName=f"{queue_name}-dlq")["QueueUrl"]

    attr_names = [
        "ApproximateNumberOfMessages",
        "ApproximateNumberOfMessagesNotVisible",
    ]
    queue_attrs = sqs.get_queue_attributes(
        QueueUrl=queue_url, AttributeNames=attr_names
    )["Attributes"]
    dlq_attrs = sqs.get_queue_attributes(
        QueueUrl=dlq_url, AttributeNames=attr_names
    )["Attributes"]
    return {"queue": queue_attrs, "dead_letter_queue": dlq_attrs}


def get_args() -> argparse.Namespace:
    """Parse environment/stack ids from CLI args."""
    parser = argparse.ArgumentParser(
        description="Gather Phase 1 diagnostics into troubleshoot.log."
    )
    parser.add_argument("environment", choices=list(SUPPORTED_APP_ENVS))
    parser.add_argument("--stack-id", default="comfyui")
    parser.add_argument("--queue-stack-id", default=DEFAULT_QUEUE_STACK_ID)
    return parser.parse_args()


def main() -> None:
    """Gather every diagnostic and write/print the combined report."""
    args = get_args()
    lines = [f"=== Phase 1 diagnostics: {args.environment} ===\n"]

    instance_id = resolve_instance_id(args.environment, args.stack_id)
    lines.append(f"Instance: {instance_id}\n")

    attrs = queue_attributes(args.environment, args.queue_stack_id)
    lines.append("=== SQS queue attributes ===")
    lines.append(f"explore-a-queue: {attrs['queue']}")
    lines.append(f"explore-a-queue-dlq: {attrs['dead_letter_queue']}\n")

    lines.append("=== Instance-side diagnostics (via SSM) ===")
    lines.append(run_diagnostics(instance_id))

    report = "\n".join(lines)
    LOG_PATH.write_text(report, encoding="utf-8")
    print(report)
    print(f"\nWritten to {LOG_PATH}")


if __name__ == "__main__":
    main()
