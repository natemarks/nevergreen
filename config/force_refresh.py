#!/usr/bin/env python3
"""Force every gpu_worker instance to re-sync models and restart its
container (Phase 2, wayfinder ticket #29).

Purpose:
- Model sync only runs once, at instance/container startup -- models
  change far less often than the worker image, and the operator can
  pre-populate the bucket with everything that might be needed, so there
  is no recurring re-sync to piggyback on. For the rare case new content
  lands in the bucket and a long-running instance needs it before its
  next natural restart, this runs the same "sync models from S3, restart
  the container" script the systemd timer runs on an image-version bump,
  on demand, against every instance currently in the gpu_worker ASG.
- Reuses the `ssm:SendCommand`/`AWS-RunShellScript` primitive
  `config/troubleshoot.py` already established (including its
  `InvocationDoesNotExist` retry handling) rather than a bespoke custom
  SSM Document CDK resource.

Flow:
- Parse environment/stack id from CLI args.
- resolve_instance_ids(): finds every instance currently in the
  gpu_worker's ASG (same CloudFormation/AutoScaling lookup as
  comfyui_client.py/troubleshoot.py).
- force_refresh(): sends one AWS-RunShellScript SSM command, targeted by
  the ASG's own `aws:autoscaling:groupName` tag (every instance an ASG
  launches gets this tag automatically) so it fans out to the whole fleet
  in one call, then waits for each instance's own invocation to finish.

Customize:
- REFRESH_COMMAND below if the on-instance script's path/name changes.
"""

# pylint: disable=duplicate-code
# Shares the check_app_env/check_aws_account/get_actual_path/EnvironmentSetting
# resolution prologue, and the InvocationDoesNotExist-retrying SSM poll
# loop, with config/troubleshoot.py by design -- every config.* CLI module
# resolves its config directory/region the same way, and SSM's
# GetCommandInvocation has the same propagation-delay race everywhere it's
# called; not accidental duplication to refactor.
import argparse
import time

import boto3
from botocore.exceptions import ClientError

from config.helper import (
    asg_physical_name,
    check_app_env,
    check_aws_account,
    get_logger,
)
from config.project import SUPPORTED_APP_ENVS
from config.registry import DEFAULT_GPU_WORKER_STACK_ID
from config.settings import EnvironmentSetting, get_actual_path
from stack.simple_asg import SimpleAsgInput

mlog = get_logger(str(__name__))

REFRESH_COMMAND = ["sudo /opt/comfyui/bin/refresh_worker.sh --force-models"]


def _resolve_asg_name(
    app_env: str,
    stack_id: str = DEFAULT_GPU_WORKER_STACK_ID,
    cfn_client=None,
) -> str:
    """Return the physical AutoScalingGroup name for the gpu_worker stack."""
    check_app_env(app_env)
    check_aws_account(app_env)
    data_path = get_actual_path(app_env)
    env_setting = EnvironmentSetting.from_data_path(data_path)
    cfn = cfn_client or boto3.client(
        "cloudformation", region_name=env_setting.default_region
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
    return asg_name


def resolve_instance_ids(
    app_env: str,
    stack_id: str = DEFAULT_GPU_WORKER_STACK_ID,
    cfn_client=None,
    autoscaling_client=None,
) -> list[str]:
    """Return every instance id currently in the gpu_worker's ASG."""
    env_setting = EnvironmentSetting.from_data_path(get_actual_path(app_env))
    autoscaling = autoscaling_client or boto3.client(
        "autoscaling", region_name=env_setting.default_region
    )
    asg_name = _resolve_asg_name(app_env, stack_id, cfn_client)
    instances = autoscaling.describe_auto_scaling_groups(
        AutoScalingGroupNames=[asg_name]
    )["AutoScalingGroups"][0]["Instances"]
    return [instance["InstanceId"] for instance in instances]


def _wait_for_command(  # pylint: disable=too-many-arguments,too-many-positional-arguments
    ssm_client,
    command_id: str,
    instance_id: str,
    poll_interval_seconds: int,
    timeout_seconds: int,
) -> str:
    """Poll one instance's SSM command invocation until it finishes."""
    deadline = time.monotonic() + timeout_seconds
    invocation = None
    while True:
        try:
            invocation = ssm_client.get_command_invocation(
                CommandId=command_id, InstanceId=instance_id
            )
        except ClientError as exc:
            if exc.response["Error"]["Code"] != "InvocationDoesNotExist":
                raise
        if invocation is not None and invocation["Status"] not in (
            "Pending",
            "InProgress",
            "Delayed",
        ):
            return str(invocation["Status"])
        if time.monotonic() >= deadline:
            raise TimeoutError(
                f"SSM command {command_id} on {instance_id} did not "
                f"finish within {timeout_seconds}s"
            )
        time.sleep(poll_interval_seconds)


def force_refresh(  # pylint: disable=too-many-arguments,too-many-positional-arguments
    app_env: str,
    stack_id: str = DEFAULT_GPU_WORKER_STACK_ID,
    ssm_client=None,
    poll_interval_seconds: int = 3,
    timeout_seconds: int = 120,
    instance_ids: list[str] | None = None,
    asg_name: str | None = None,
) -> dict[str, str]:
    """Run the refresh script on every gpu_worker instance, in one
    SSM command targeted by the ASG's own tag rather than one command
    per instance.

    Returns each instance id's final SSM command status.
    """
    ssm = ssm_client or boto3.client("ssm")
    targets = (
        instance_ids
        if instance_ids is not None
        else resolve_instance_ids(app_env, stack_id)
    )
    if not targets:
        mlog.info("No running instances in the %s ASG to refresh", stack_id)
        return {}

    group_name = (
        asg_name
        if asg_name is not None
        else _resolve_asg_name(app_env, stack_id)
    )
    mlog.info(
        "Sending refresh command to ASG %s (%d instances)",
        group_name,
        len(targets),
    )
    command_id = ssm.send_command(
        Targets=[
            {"Key": "tag:aws:autoscaling:groupName", "Values": [group_name]}
        ],
        DocumentName="AWS-RunShellScript",
        Parameters={"commands": REFRESH_COMMAND},
    )["Command"]["CommandId"]

    return {
        instance_id: _wait_for_command(
            ssm,
            command_id,
            instance_id,
            poll_interval_seconds,
            timeout_seconds,
        )
        for instance_id in targets
    }


def get_args() -> argparse.Namespace:
    """Parse environment/stack id from CLI args."""
    parser = argparse.ArgumentParser(
        description=(
            "Force every gpu_worker instance to re-sync models and "
            "restart its container."
        )
    )
    parser.add_argument("environment", choices=list(SUPPORTED_APP_ENVS))
    parser.add_argument("--stack-id", default=DEFAULT_GPU_WORKER_STACK_ID)
    return parser.parse_args()


def main() -> None:
    """Force-refresh every gpu_worker instance and print each result."""
    args = get_args()
    results = force_refresh(args.environment, args.stack_id)
    for instance_id, status in results.items():
        print(f"{instance_id}: {status}")


if __name__ == "__main__":
    main()
