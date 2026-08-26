"""Shared config, discovery, and AWS utility helpers.

Purpose:
- Define project constants used in naming and path resolution.
- Provide JSON parsing helpers for config settings modules.
- Validate app environment and caller AWS account alignment.
- Discover latest ECS AMI id values for discovery workflows.

Flow:
- Import project identity and rollout constants from `config.project`.
- Apply shared helpers from app, inventory, and discovery modules.

Customize:
- Update `config/template_defaults.json` for project naming and account mapping.
- Extend helper functions when new discovery or validation behavior is needed.
"""

import logging
from pathlib import Path
import sys
from dataclasses import dataclass
import json
from typing import Any, Dict

import boto3

from config.project import APP_ENV_TO_AWS_ACCOUNT, APP_NAME as _APP_NAME

APP_NAME = _APP_NAME

PROJECT_ROOT = Path(__file__).parent.parent


def get_logger(module_name: str) -> logging.Logger:
    """Return a module logger with repository-standard formatter."""
    my_logger = logging.getLogger(module_name)
    my_logger.setLevel(logging.INFO)

    console_handler = logging.StreamHandler(sys.stdout)

    formatter = logging.Formatter(
        "%(asctime)s - {%(name)s} - {%(filename)s:%(funcName)s:%(lineno)d} - "
        "%(levelname)s - %(message)s"
    )
    console_handler.setFormatter(formatter)

    if not my_logger.handlers:
        my_logger.addHandler(console_handler)
    return my_logger


module_logger = get_logger(str(__name__))


def check_app_env(ae: str):
    """Raise `ValueError` if app environment id is not supported."""
    if ae not in APP_ENV_TO_AWS_ACCOUNT:
        raise ValueError(f"invalid app_env: {ae}")


def ensure_path_exists(path: Path):
    """Ensure the target path (or its parent directory) exists."""
    if not isinstance(path, Path):
        raise TypeError("path must be a pathlib.Path object")

    if path.is_dir() or not path.suffix:
        # Create the directory and all parent directories
        path.mkdir(parents=True, exist_ok=True)
        module_logger.info(
            "Ensured that the directory %s and all parent directories exist.",
            path,
        )
    else:
        # Create all parent directories of the file
        parent_directory = path.parent
        parent_directory.mkdir(parents=True, exist_ok=True)
        module_logger.info(
            "Ensured that all parent directories for the file %s exist.", path
        )


def dict_from_json_string(json_string: str) -> Dict[str, Any]:
    """Parse JSON string and return a dict with string keys."""

    # Parse the JSON string into a dictionary
    def is_dict_with_string_keys(variable: Any) -> bool:
        if not isinstance(variable, dict):
            return False
        return all(isinstance(key, str) for key in variable.keys())

    data = json.loads(json_string)
    if not is_dict_with_string_keys(data):
        raise ValueError(
            "JSON string does not represent a dictionary: " + json_string
        )
    return data


def dict_from_json_file(json_file: Path) -> Any:
    """Load and parse JSON file as a dictionary."""
    with json_file.open() as file:
        return dict_from_json_string(file.read())


@dataclass(frozen=False, kw_only=True)
class AwsCallerIdentity:
    """Typed wrapper for AWS STS caller identity fields."""

    account: str
    arn: str
    user_id: str


def get_caller_identity() -> AwsCallerIdentity:
    """Return caller identity for current AWS credentials."""
    client = boto3.client("sts")
    response = client.get_caller_identity()

    return AwsCallerIdentity(
        **{
            "account": response["Account"],
            "arn": response["Arn"],
            "user_id": response["UserId"],
        }
    )


def check_aws_account(app_env: str):
    """Validate current AWS account for the requested app environment."""
    caller_identity = get_caller_identity()
    if caller_identity.account != APP_ENV_TO_AWS_ACCOUNT[app_env]:
        raise RuntimeError(
            f"Local AWS Account {caller_identity.account} does not match "
            f"{app_env} AWS Account {APP_ENV_TO_AWS_ACCOUNT[app_env]}"
        )
    return caller_identity.account


def latest_ecs_ami_id(aws_region: str) -> str:
    """Return latest ECS-optimized Amazon Linux 2 AMI id in region.

    Filters:
    - name: `amzn2-ami-ecs-hvm-*`
    - virtualization-type: `hvm`
    - architecture: `x86_64`
    """
    ec2 = boto3.client("ec2", region_name=aws_region)
    paginator = ec2.get_paginator("describe_images")

    filters = [
        {"Name": "name", "Values": ["amzn2-ami-ecs-hvm-*"]},
        {"Name": "virtualization-type", "Values": ["hvm"]},
        {"Name": "architecture", "Values": ["x86_64"]},
    ]

    all_images = []

    for page in paginator.paginate(Owners=["amazon"], Filters=filters):
        all_images.extend(page["Images"])

    # Sort all images by CreationDate in descending order
    sorted_images = sorted(
        all_images, key=lambda x: x["CreationDate"], reverse=True
    )

    if not sorted_images:
        raise RuntimeError("No images found")

    # Return the most recent AMI ID, or None if no AMIs match
    return sorted_images[0]["ImageId"]
