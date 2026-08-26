#!/usr/bin/env python3
"""Golden tests for the AppVpc stack template.

Purpose:
- Stack synthesis from real environment config under `config/<env>/...`.
- Stack synthesis from custom case-local config under `test_data/...`.

Customize:
- Keep the `*_actual` test for real environment contracts.
- Add or expand `*_custom` cases for edge scenarios.
- Use `--update_golden` only when template changes are intentional.
"""

# pylint: disable=duplicate-code
import pytest
from aws_cdk import App, assertions, Environment
from config.settings import get_actual_path
from stack.app_vpc import AppVpcStack, AppVpcInput
from tests.helper import case_data_path, write_case_json, read_case_json


@pytest.mark.unit
@pytest.mark.parametrize(
    "environment",
    [
        pytest.param("dev", id="dev"),
        pytest.param("staging", id="staging"),
        pytest.param("production", id="production"),
    ],
)
def test_app_vpc_stack_actual(request, environment, update_golden):
    """Compare AppVpc template against golden data for real environments."""
    # use stack input data from actual environments
    input_path = get_actual_path(environment)
    # test_data path for case
    data_path = case_data_path(request)
    s_input = AppVpcInput.from_config_directory(input_path)

    app = App()

    stk = AppVpcStack(
        scope=app,
        cdk_env=Environment(),
        s_input=s_input,
    )
    template = assertions.Template.from_stack(stk)
    if update_golden:
        write_case_json(data_path, "expected.json", template.to_json())

    template.template_matches(read_case_json(data_path, "expected.json"))


@pytest.mark.unit
@pytest.mark.parametrize(
    "",
    [
        pytest.param(id="explore_new_setting"),
    ],
)
def test_app_vpc_stack_custom(request, update_golden):
    """Compare AppVpc template against golden data for custom case config."""
    # test_data path for case
    data_path = case_data_path(request)
    # the custom input files are in the case data
    input_path = data_path
    s_input = AppVpcInput.from_config_directory(input_path)

    app = App()

    stk = AppVpcStack(
        scope=app,
        cdk_env=Environment(),
        s_input=s_input,
    )
    template = assertions.Template.from_stack(stk)
    if update_golden:
        write_case_json(data_path, "expected.json", template.to_json())

    template.template_matches(read_case_json(data_path, "expected.json"))
