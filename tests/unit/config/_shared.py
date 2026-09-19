"""Shared fixtures for the config.* CLI-module unit tests.

Purpose:
- config.asg_scale / config.comfyui_client resolve a simple_asg-based
  instance's real AutoScalingGroup via the same config-directory +
  CloudFormation lookup shape, so their tests need the same fake
  environment.json / simple_asg.json / ASG resource payloads.
- config.queue_job resolves an sqs_queue/simple_s3 instance's physical
  name the same way, so it reuses the environment.json writer plus its
  own sqs_queue.json / simple_s3.json writers below.
- config.build_worker_image resolves an ecr_repo instance's physical name
  the same way, reusing its own ecr_repo.json writer below.
"""

import json
from pathlib import Path

ENVIRONMENT_JSON = {
    "admin_team": "Operations",
    "aws_account_name": "Test",
    "aws_account_number": "709310380790",
    "default_fqdn": "test.example.com",
    "default_region": "us-east-1",
    "app_env": "dev",
    "is_release": False,
}


def write_environment_json(data_path: Path) -> None:
    """Write a minimal environment.json under data_path."""
    (data_path / "environment.json").write_text(json.dumps(ENVIRONMENT_JSON))


def write_simple_asg_config(
    data_path: Path,
    stack_id: str,
    min_instances: int = 1,
    max_instances: int = 1,
) -> None:
    """Write a minimal simple_asg.json for one stack_id under data_path."""
    setting_dir = data_path / "simple_asg" / stack_id
    setting_dir.mkdir(parents=True)
    (setting_dir / "simple_asg.json").write_text(
        json.dumps(
            {
                "ami_id": "ami-00000000000000000",
                "min_instances": min_instances,
                "max_instances": max_instances,
            }
        )
    )


def write_sqs_queue_config(
    data_path: Path,
    stack_id: str,
    visibility_timeout_seconds: int = 900,
    max_receive_count: int = 3,
) -> None:
    """Write a minimal sqs_queue.json for one stack_id under data_path."""
    setting_dir = data_path / "sqs_queue" / stack_id
    setting_dir.mkdir(parents=True)
    (setting_dir / "sqs_queue.json").write_text(
        json.dumps(
            {
                "visibility_timeout_seconds": visibility_timeout_seconds,
                "max_receive_count": max_receive_count,
            }
        )
    )


def write_simple_s3_config(data_path: Path, stack_id: str) -> None:
    """Write a minimal simple_s3.json for one stack_id under data_path."""
    setting_dir = data_path / "simple_s3" / stack_id
    setting_dir.mkdir(parents=True)
    (setting_dir / "simple_s3.json").write_text(json.dumps({}))


def write_ecr_repo_config(data_path: Path, stack_id: str) -> None:
    """Write a minimal ecr_repo.json for one stack_id under data_path."""
    setting_dir = data_path / "ecr_repo" / stack_id
    setting_dir.mkdir(parents=True)
    (setting_dir / "ecr_repo.json").write_text(json.dumps({}))


def asg_resources(physical_id: str) -> dict:
    """Return a describe_stack_resources payload with one ASG resource."""
    return {
        "StackResources": [
            {
                "ResourceType": "AWS::AutoScaling::AutoScalingGroup",
                "PhysicalResourceId": physical_id,
            }
        ]
    }
