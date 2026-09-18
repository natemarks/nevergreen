"""Tests for config.inventory."""

from unittest.mock import patch

import pytest
from aws_cdk import App, Environment, Stack

from config.helper import APP_NAME
from config.inventory import Inventory

_DEV = f"{APP_NAME}Dev"
_STG = f"{APP_NAME}Staging"
_PRD = f"{APP_NAME}Production"

EXPECTED_STACK_NAMES = {
    "dev": {
        f"{_DEV}AppVpcStack",
        f"{_DEV}SecureS3PhiStack",
        f"{_DEV}SimpleS3ModelsStack",
        f"{_DEV}SimpleS3ImagesStack",
        f"{_DEV}SimpleAsgComfyuiStack",
    },
    "staging": {
        f"{_STG}AppVpcStack",
        f"{_STG}SecureS3PhiStack",
    },
    "production": {
        f"{_PRD}AppVpcStack",
        f"{_PRD}SecureS3PhiStack",
    },
}


@pytest.mark.unit
@pytest.mark.parametrize(
    "app_env,expected",
    [
        pytest.param("dev", EXPECTED_STACK_NAMES["dev"], id="dev"),
        pytest.param("staging", EXPECTED_STACK_NAMES["staging"], id="staging"),
        pytest.param(
            "production",
            EXPECTED_STACK_NAMES["production"],
            id="production",
        ),
    ],
)
def test_deploy_stacks_creates_expected_stacks(app_env, expected):
    """deploy_stacks creates exactly the stacks listed in STACKS_BY_ENV."""
    with patch("config.inventory.check_aws_account"):
        inv = Inventory(app_env)

    app = App()
    inv.deploy_stacks(app, Environment())

    actual = {s.stack_name for s in app.node.children if isinstance(s, Stack)}
    assert actual == expected
