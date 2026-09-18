#!/usr/bin/env python3
"""Golden tests for the SimpleS3 stack template.

Purpose:
- Stack synthesis from real environment config under `config/<env>/...`.
- Stack synthesis from custom case-local config under `test_data/...`.

Customize:
- Keep the `*_actual` test for environment contracts.
- Add custom cases for new configuration variants.
- Use `--update_golden` only when expected template changes are intentional.
"""

# pylint: disable=duplicate-code
import pytest
from aws_cdk import App, assertions, Environment
from config.settings import get_actual_path
from stack.simple_s3 import SimpleS3Input, SimpleS3Stack
from tests.helper import case_data_path, write_case_json, read_case_json


def _synthesize(input_path, stack_id: str, app: App) -> assertions.Template:
    """Synthesise SimpleS3Stack and return its template."""
    s_input = SimpleS3Input.from_config_directory(input_path, stack_id)
    stk = SimpleS3Stack(
        scope=app,
        cdk_env=Environment(),
        s_input=s_input,
    )
    return assertions.Template.from_stack(stk)


@pytest.mark.unit
@pytest.mark.parametrize(
    "environment,stack_id",
    [
        pytest.param("dev", "models", id="dev_models"),
        pytest.param("dev", "images", id="dev_images"),
    ],
)
def test_simple_s3_stack_actual(request, environment, stack_id, update_golden):
    """Compare SimpleS3 template against golden data for real environments."""
    input_path = get_actual_path(environment)
    data_path = case_data_path(request)

    template = _synthesize(input_path, stack_id, App())

    if update_golden:
        write_case_json(data_path, "expected.json", template.to_json())
    template.template_matches(read_case_json(data_path, "expected.json"))


@pytest.mark.unit
@pytest.mark.parametrize(
    "stack_id",
    [
        pytest.param("models", id="lifecycle_expiration"),
        pytest.param("models", id="retain"),
    ],
)
def test_simple_s3_stack_custom(request, stack_id, update_golden):
    """Compare SimpleS3 template against golden data for custom case config."""
    data_path = case_data_path(request)
    input_path = data_path

    template = _synthesize(input_path, stack_id, App())

    if update_golden:
        write_case_json(data_path, "expected.json", template.to_json())
    template.template_matches(read_case_json(data_path, "expected.json"))
