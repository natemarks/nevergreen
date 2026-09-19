"""Tests for config.build_worker_image."""

# pylint: disable=redefined-outer-name
import base64
from unittest.mock import MagicMock, patch

import pytest

from config.build_worker_image import (
    build_and_push,
    docker_login,
    resolve_repository_uri,
)
from tests.unit.config._shared import (
    write_ecr_repo_config as _write_ecr_repo_config,
    write_environment_json as _write_environment_json,
)


@pytest.fixture
def data_path(tmp_path):
    """Return a tmp data path with environment.json and an ecr_repo config."""
    _write_environment_json(tmp_path)
    _write_ecr_repo_config(tmp_path, "worker")
    return tmp_path


@pytest.mark.unit
def test_resolve_repository_uri_returns_the_real_uri(data_path):
    """resolve_repository_uri looks up the deployed repo by its physical name."""
    ecr = MagicMock()
    ecr.describe_repositories.return_value = {
        "repositories": [
            {
                "repositoryUri": (
                    "709310380790.dkr.ecr.us-east-1.amazonaws.com/"
                    "nevergreen-dev-worker"
                )
            }
        ]
    }

    with patch("config.build_worker_image.check_aws_account"), patch(
        "config.build_worker_image.get_actual_path", return_value=data_path
    ):
        uri = resolve_repository_uri("dev", ecr_client=ecr)

    ecr.describe_repositories.assert_called_once_with(
        repositoryNames=["nevergreen-dev-worker"]
    )
    assert uri == (
        "709310380790.dkr.ecr.us-east-1.amazonaws.com/nevergreen-dev-worker"
    )


@pytest.mark.unit
def test_docker_login_pipes_the_decoded_password_over_stdin(data_path):
    """docker_login decodes the ECR auth token and never puts the password
    on the command line."""
    ecr = MagicMock()
    token = base64.b64encode(b"AWS:super-secret-password").decode()
    ecr.get_authorization_token.return_value = {
        "authorizationData": [{"authorizationToken": token}]
    }
    runner = MagicMock()

    with patch("config.build_worker_image.check_aws_account"), patch(
        "config.build_worker_image.get_actual_path", return_value=data_path
    ):
        docker_login(
            "dev",
            "709310380790.dkr.ecr.us-east-1.amazonaws.com/nevergreen-dev-worker",
            ecr_client=ecr,
            runner=runner,
        )

    runner.assert_called_once_with(
        [
            "docker",
            "login",
            "--username",
            "AWS",
            "--password-stdin",
            "709310380790.dkr.ecr.us-east-1.amazonaws.com",
        ],
        input="super-secret-password",
        text=True,
        check=True,
    )


@pytest.mark.unit
def test_build_and_push_builds_then_pushes_the_tagged_image():
    """build_and_push runs docker build then docker push, in order."""
    runner = MagicMock()

    image = build_and_push(
        "709310380790.dkr.ecr.us-east-1.amazonaws.com/nevergreen-dev-worker",
        tag="v1",
        runner=runner,
    )

    assert image == (
        "709310380790.dkr.ecr.us-east-1.amazonaws.com/nevergreen-dev-worker:v1"
    )
    assert runner.call_count == 2
    build_call, push_call = runner.call_args_list
    assert build_call.args[0][:2] == ["docker", "build"]
    assert image in build_call.args[0]
    assert push_call.args[0] == ["docker", "push", image]
