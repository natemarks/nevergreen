#!/usr/bin/env python3
"""Discover the ComfyUI gpu_worker's URL, wait for it, and POST a workflow.

Purpose:
- Resolve the gpu_worker instance's current public IP the same way
  AsgScaler resolves any simple_asg-based instance: via its
  CloudFormation stack's AutoScalingGroup resource, never by guessing --
  a fresh ASG launch gets a new public IP every time.
- Poll a raw TCP connection to that IP/port until ComfyUI accepts it (a
  fresh launch takes a few minutes to boot + run userdata before
  comfyui.service is listening), instead of failing immediately.
- POST a workflow JSON (already in ComfyUI API format -- exported via
  ComfyUI's "Export (API)", not the plain "Export") to /prompt, wrapped
  under the "prompt" key the endpoint actually expects.

Flow:
- Parse environment/workflow path/stack_id/port/timeout from CLI args.
- discover_url() resolves the instance's public IP via CloudFormation +
  Auto Scaling + EC2.
- wait_for_port() polls a raw socket connection until it succeeds or the
  timeout is hit.
- post_workflow() shells out to curl with the exact invocation verified
  manually during Phase 0's UAT.

Customize:
- --stack-id/--port if a different gpu_worker instance or port is added.
"""

import argparse
import json
import socket
import subprocess
import time
from pathlib import Path

import boto3

from config.helper import (
    asg_physical_name,
    check_app_env,
    check_aws_account,
    get_logger,
)
from config.project import SUPPORTED_APP_ENVS
from config.settings import EnvironmentSetting, get_actual_path
from stack.simple_asg import SimpleAsgInput

mlog = get_logger(str(__name__))


def discover_url(  # pylint: disable=too-many-arguments,too-many-positional-arguments,too-many-locals
    app_env: str,
    stack_id: str = "comfyui",
    port: int = 8188,
    cfn_client=None,
    autoscaling_client=None,
    ec2_client=None,
) -> str:
    """Resolve the gpu_worker instance's current public IP and return its URL."""
    check_app_env(app_env)
    check_aws_account(app_env)
    data_path = get_actual_path(app_env)
    env_setting = EnvironmentSetting.from_data_path(data_path)
    region = env_setting.default_region

    cfn = cfn_client or boto3.client("cloudformation", region_name=region)
    autoscaling = autoscaling_client or boto3.client(
        "autoscaling", region_name=region
    )
    ec2 = ec2_client or boto3.client("ec2", region_name=region)

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
    instance_id = instances[0]["InstanceId"]

    reservations = ec2.describe_instances(InstanceIds=[instance_id])[
        "Reservations"
    ]
    public_ip = reservations[0]["Instances"][0].get("PublicIpAddress")
    if not public_ip:
        raise RuntimeError(f"Instance {instance_id} has no public IP")

    return f"http://{public_ip}:{port}"


def wait_for_port(
    host: str, port: int, timeout: int = 300, interval: int = 5
) -> None:
    """Poll a raw TCP connection to host:port until it succeeds or times out."""
    deadline = time.monotonic() + timeout
    while True:
        try:
            with socket.create_connection((host, port), timeout=5):
                return
        except OSError:
            if time.monotonic() >= deadline:
                raise TimeoutError(
                    f"{host}:{port} did not accept connections within "
                    f"{timeout}s"
                ) from None
            mlog.info("Waiting for %s:%d to accept connections...", host, port)
            time.sleep(interval)


def post_workflow(url: str, workflow_path: Path) -> None:
    """POST an API-format workflow JSON to url/prompt via curl."""
    graph = json.loads(workflow_path.read_text(encoding="utf-8"))
    body = json.dumps({"prompt": graph})
    subprocess.run(
        [
            "curl",
            "-v",
            f"{url}/prompt",
            "-H",
            "Content-Type: application/json",
            "-d",
            body,
        ],
        check=True,
    )


def get_args() -> argparse.Namespace:
    """Parse environment/workflow path and options from CLI args."""
    parser = argparse.ArgumentParser(
        description=(
            "Discover the ComfyUI gpu_worker's URL, wait for it to accept "
            "connections, then POST a workflow to it."
        )
    )
    parser.add_argument("environment", choices=list(SUPPORTED_APP_ENVS))
    parser.add_argument(
        "workflow", type=Path, help="Path to an API-format workflow JSON"
    )
    parser.add_argument("--stack-id", default="comfyui")
    parser.add_argument("--port", type=int, default=8188)
    parser.add_argument(
        "--timeout",
        type=int,
        default=300,
        help="Seconds to wait for the port to accept connections",
    )
    return parser.parse_args()


def main() -> None:
    """Discover the worker's URL, wait for it, and POST the given workflow."""
    args = get_args()
    url = discover_url(args.environment, args.stack_id, args.port)
    print(f"Resolved URL: {url}")
    host = url.split("://", 1)[1].split(":", 1)[0]
    wait_for_port(host, args.port, timeout=args.timeout)
    post_workflow(url, args.workflow)


if __name__ == "__main__":
    main()
