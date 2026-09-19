#!/usr/bin/env python3
"""Build and push the containerized worker image to ECR (Phase 2,
wayfinder ticket #29).

Purpose:
- Deliberately outside `cdk deploy` -- the worker image changes far more
  often than infrastructure, and rebuilding/pushing it on every
  `cdk deploy` would make routine infra changes needlessly slow.
- Resolves the real deployed ECR repository URI via `describe_repositories`
  rather than reconstructing it from account/region strings.

Flow:
- Parse environment/tag from CLI args.
- resolve_repository_uri(): finds the ECR repo's real URI.
- docker_login(): exchanges an ECR authorization token for docker login
  credentials, piped to `docker login` over stdin (never on the command
  line or in an env var another process could read).
- build_and_push(): `docker build` then `docker push` the resolved tag.

Customize:
- --tag to push something other than "latest".
"""

# pylint: disable=duplicate-code
# Shares the check_app_env/check_aws_account/get_actual_path/EnvironmentSetting
# resolution prologue with config/comfyui_client.py and config/queue_job.py
# by design -- every config.* CLI module resolves its config directory and
# region the same way; not accidental duplication to refactor.
import argparse
import base64
import subprocess

import boto3

from config.helper import check_app_env, check_aws_account, get_logger
from config.project import SUPPORTED_APP_ENVS
from config.registry import DEFAULT_ECR_REPO_STACK_ID
from config.settings import EnvironmentSetting, get_actual_path
from stack.ecr_repo import EcrRepoInput

mlog = get_logger(str(__name__))

DOCKERFILE_PATH = "worker/Dockerfile"


def resolve_repository_uri(
    app_env: str,
    stack_id: str = DEFAULT_ECR_REPO_STACK_ID,
    ecr_client=None,
) -> str:
    """Return the real deployed ECR repository's URI."""
    check_app_env(app_env)
    check_aws_account(app_env)
    data_path = get_actual_path(app_env)
    env_setting = EnvironmentSetting.from_data_path(data_path)
    ecr_input = EcrRepoInput.from_config_directory(
        data_path, stack_id, env_setting=env_setting
    )

    ecr = ecr_client or boto3.client(
        "ecr", region_name=env_setting.default_region
    )
    repositories = ecr.describe_repositories(
        repositoryNames=[ecr_input.repository_name()]
    )["repositories"]
    return str(repositories[0]["repositoryUri"])


def docker_login(
    app_env: str,
    repository_uri: str,
    ecr_client=None,
    runner=subprocess.run,
) -> None:
    """Exchange an ECR authorization token for a docker login, over stdin."""
    check_app_env(app_env)
    check_aws_account(app_env)
    env_setting = EnvironmentSetting.from_data_path(get_actual_path(app_env))
    ecr = ecr_client or boto3.client(
        "ecr", region_name=env_setting.default_region
    )

    auth = ecr.get_authorization_token()["authorizationData"][0]
    _, password = (
        base64.b64decode(auth["authorizationToken"]).decode().split(":", 1)
    )
    registry = repository_uri.split("/", 1)[0]
    runner(
        [
            "docker",
            "login",
            "--username",
            "AWS",
            "--password-stdin",
            registry,
        ],
        input=password,
        text=True,
        check=True,
    )


def build_and_push(
    repository_uri: str, tag: str = "latest", runner=subprocess.run
) -> str:
    """Build worker/Dockerfile and push it as repository_uri:tag."""
    image = f"{repository_uri}:{tag}"
    mlog.info("Building %s", image)
    runner(
        ["docker", "build", "-t", image, "-f", DOCKERFILE_PATH, "."],
        check=True,
    )
    mlog.info("Pushing %s", image)
    runner(["docker", "push", image], check=True)
    return image


def get_args() -> argparse.Namespace:
    """Parse environment/tag from CLI args."""
    parser = argparse.ArgumentParser(
        description="Build and push the containerized worker image to ECR."
    )
    parser.add_argument("environment", choices=list(SUPPORTED_APP_ENVS))
    parser.add_argument("--tag", default="latest")
    parser.add_argument("--stack-id", default=DEFAULT_ECR_REPO_STACK_ID)
    return parser.parse_args()


def main() -> None:
    """Resolve the repo, log in, build, and push."""
    args = get_args()
    repository_uri = resolve_repository_uri(args.environment, args.stack_id)
    docker_login(args.environment, repository_uri)
    image = build_and_push(repository_uri, tag=args.tag)
    print(f"Pushed {image}")


if __name__ == "__main__":
    main()
