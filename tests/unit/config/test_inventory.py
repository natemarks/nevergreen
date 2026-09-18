"""Tests for config.inventory."""

import json
from unittest.mock import patch

import pytest
from aws_cdk import App, Environment, Stack, assertions

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
        f"{_DEV}SqsQueueExplore-aStack",
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


@pytest.mark.unit
def test_gpu_worker_gets_images_and_queue_managed_policies():
    """The comfyui instance role gets both the images and queue policies."""
    with patch("config.inventory.check_aws_account"):
        inv = Inventory("dev")

    app = App()
    inv.deploy_stacks(app, Environment())

    gpu_worker_stack = next(
        s
        for s in app.node.children
        if isinstance(s, Stack)
        and s.stack_name == f"{_DEV}SimpleAsgComfyuiStack"
    )
    template = assertions.Template.from_stack(gpu_worker_stack)
    template.has_resource_properties(
        "AWS::IAM::Role",
        {
            "ManagedPolicyArns": assertions.Match.array_with(
                [
                    assertions.Match.object_like(
                        {"Fn::ImportValue": assertions.Match.any_value()}
                    ),
                    assertions.Match.object_like(
                        {"Fn::ImportValue": assertions.Match.any_value()}
                    ),
                ]
            )
        },
    )


@pytest.mark.unit
def test_gpu_worker_userdata_embeds_worker_script_and_env_file():
    """The real dev wiring embeds the worker script, workflow, and env file."""
    with patch("config.inventory.check_aws_account"):
        inv = Inventory("dev")

    app = App()
    inv.deploy_stacks(app, Environment())

    gpu_worker_stack = next(
        s
        for s in app.node.children
        if isinstance(s, Stack)
        and s.stack_name == f"{_DEV}SimpleAsgComfyuiStack"
    )
    template = assertions.Template.from_stack(gpu_worker_stack).to_json()
    launch_templates = [
        resource
        for resource in template["Resources"].values()
        if resource["Type"] == "AWS::EC2::LaunchTemplate"
    ]
    assert len(launch_templates) == 1
    user_data = launch_templates[0]["Properties"]["LaunchTemplateData"][
        "UserData"
    ]["Fn::Base64"]

    # Fn::Base64 nests the resolved parts as an Fn::Join when any embedded
    # value (the queue URL, the bucket name) is a cross-stack token rather
    # than a plain string.
    rendered = json.dumps(user_data)
    assert "/opt/comfyui/explore_worker.py" in rendered
    assert "/opt/comfyui/workflows/txt2img-example.json" in rendered
    assert "/etc/default/explore-worker" in rendered
    assert "QUEUE_URL=" in rendered
    assert "OUTPUT_BUCKET=" in rendered
    assert "AWS_REGION=" in rendered
