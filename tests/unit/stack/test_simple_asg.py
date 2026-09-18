#!/usr/bin/env python3
"""Golden tests for the SimpleAsg stack template.

Purpose:
- Stack synthesis from real environment config under `config/<env>/...`.
- Stack synthesis from custom case-local config under `test_data/...`.

Customize:
- Keep the `*_actual` test for environment contracts.
- Add custom cases for unusual launch template or ASG requirements.
- Use `--update_golden` only when expected template changes are intentional.
"""

# pylint: disable=duplicate-code
import pytest
from aws_cdk import App, Stack, assertions, Environment
from aws_cdk import aws_iam as iam
from config.settings import get_actual_path
from stack.app_vpc import AppVpcInput, AppVpcStack
from stack.simple_asg import SimpleAsgInput, SimpleAsgStack
from tests.helper import case_data_path, write_case_json, read_case_json


@pytest.mark.unit
@pytest.mark.parametrize(
    "environment,stack_id",
    [
        pytest.param("dev", "comfyui", id="dev_gpu_worker"),
    ],
)
def test_simple_asg_stack_actual(
    request, environment, stack_id, update_golden
):
    """Compare SimpleAsg template against golden data for real environments."""
    # use stack input data from actual environments
    input_path = get_actual_path(environment)
    # test_data path for case
    data_path = case_data_path(request)
    s_input = SimpleAsgInput.from_config_directory(input_path, stack_id)

    app = App()
    av_input = AppVpcInput.from_config_directory(input_path)
    av_stk = AppVpcStack(
        scope=app,
        cdk_env=Environment(),
        s_input=av_input,
    )
    stk = SimpleAsgStack(
        scope=app,
        cdk_env=Environment(),
        s_input=s_input,
        app_vpc_stack=av_stk,
    )
    template = assertions.Template.from_stack(stk)
    if update_golden:
        write_case_json(data_path, "expected.json", template.to_json())

    template.template_matches(read_case_json(data_path, "expected.json"))


@pytest.mark.unit
@pytest.mark.parametrize(
    "stack_id",
    [
        pytest.param("aaa", id="custom_aaa"),
        pytest.param("comfyui", id="custom_gpu_worker"),
    ],
)
def test_simple_asg_stack_custom(request, stack_id, update_golden):
    """Compare SimpleAsg template against golden data for custom case config."""
    # test_data path for case
    data_path = case_data_path(request)
    input_path = data_path
    s_input = SimpleAsgInput.from_config_directory(input_path, stack_id)

    app = App()
    av_input = AppVpcInput.from_config_directory(input_path)
    av_stk = AppVpcStack(
        scope=app,
        cdk_env=Environment(),
        s_input=av_input,
    )
    stk = SimpleAsgStack(
        scope=app,
        cdk_env=Environment(),
        s_input=s_input,
        app_vpc_stack=av_stk,
    )
    template = assertions.Template.from_stack(stk)
    if update_golden:
        write_case_json(data_path, "expected.json", template.to_json())

    template.template_matches(read_case_json(data_path, "expected.json"))


@pytest.mark.unit
def test_simple_asg_stack_attaches_extra_managed_policies():
    """Passing managed_policies attaches them to the ASG instance role."""
    app = App()
    input_path = get_actual_path("dev")
    av_input = AppVpcInput.from_config_directory(input_path)
    av_stk = AppVpcStack(scope=app, cdk_env=Environment(), s_input=av_input)
    s_input = SimpleAsgInput.from_config_directory(input_path, "comfyui")

    policy_stack = Stack(app, "PolicyStack")
    extra_policy = iam.ManagedPolicy(
        policy_stack,
        "ExtraPolicy",
        managed_policy_name="extra-policy",
        statements=[
            iam.PolicyStatement(
                effect=iam.Effect.ALLOW,
                actions=["s3:GetObject"],
                resources=["*"],
            )
        ],
    )

    stk = SimpleAsgStack(
        scope=app,
        cdk_env=Environment(),
        s_input=s_input,
        app_vpc_stack=av_stk,
        managed_policies=[extra_policy],
    )
    template = assertions.Template.from_stack(stk)
    template.has_resource_properties(
        "AWS::IAM::Role",
        {
            "ManagedPolicyArns": assertions.Match.array_with(
                [
                    assertions.Match.object_like(
                        {"Fn::ImportValue": assertions.Match.any_value()}
                    )
                ]
            )
        },
    )
