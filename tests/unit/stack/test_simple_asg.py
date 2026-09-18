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
from stack.simple_asg import (
    SimpleAsgInput,
    SimpleAsgStack,
    _build_user_data,
)
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


@pytest.mark.unit
def test_build_user_data_with_no_extra_files_returns_script_unchanged():
    """No extra_files means the script passes through untouched."""
    assert _build_user_data({}, "#!/usr/bin/env bash\necho hi\n") == (
        "#!/usr/bin/env bash\necho hi\n"
    )


@pytest.mark.unit
def test_build_user_data_embeds_file_content_before_script(tmp_path):
    """Each extra_files entry is written via heredoc before the script."""
    local_file = tmp_path / "worker.py"
    local_file.write_text("print('hello')\n", encoding="utf-8")

    result = _build_user_data(
        {"/opt/comfyui/worker.py": local_file}, "echo done\n"
    )

    assert "mkdir -p /opt/comfyui" in result
    assert "cat > /opt/comfyui/worker.py <<'EXTRA_FILE_EOF'" in result
    assert "print('hello')" in result
    assert "EXTRA_FILE_EOF" in result
    # the main script still runs last, after every extra file is written
    assert result.rstrip().endswith("echo done")
    assert result.index("EXTRA_FILE_EOF") < result.index("echo done")


@pytest.mark.unit
def test_simple_asg_stack_embeds_extra_files_in_launch_template_userdata(
    tmp_path,
):
    """extra_files content ends up in the LaunchTemplate's UserData."""
    local_file = tmp_path / "worker.py"
    local_file.write_text("WORKER_MARKER = True\n", encoding="utf-8")

    app = App()
    input_path = get_actual_path("dev")
    av_input = AppVpcInput.from_config_directory(input_path)
    av_stk = AppVpcStack(scope=app, cdk_env=Environment(), s_input=av_input)
    s_input = SimpleAsgInput.from_config_directory(input_path, "comfyui")

    stk = SimpleAsgStack(
        scope=app,
        cdk_env=Environment(),
        s_input=s_input,
        app_vpc_stack=av_stk,
        extra_files={"/opt/comfyui/worker.py": local_file},
    )
    template = assertions.Template.from_stack(stk).to_json()
    launch_templates = [
        resource
        for resource in template["Resources"].values()
        if resource["Type"] == "AWS::EC2::LaunchTemplate"
    ]
    assert len(launch_templates) == 1
    user_data = launch_templates[0]["Properties"]["LaunchTemplateData"][
        "UserData"
    ]
    # CDK renders this as the CloudFormation intrinsic {"Fn::Base64": "..."}
    # -- CloudFormation itself base64-encodes at deploy time, not CDK at
    # synth time -- so the template already holds the plain-text script.
    assert "WORKER_MARKER = True" in user_data["Fn::Base64"]
