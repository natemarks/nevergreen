#!/usr/bin/env python3
"""Golden tests for the SqsQueue stack template.

Purpose:
- Stack synthesis from real environment config under `config/<env>/...`.
- Stack synthesis from custom case-local config under `test_data/...`.

Customize:
- Keep the `*_actual` test for environment contracts.
- Add custom cases for new configuration variants.
- Use `--update_golden` only when expected template changes are intentional.
"""

import pytest
from aws_cdk import App, assertions, Environment
from config.settings import get_actual_path
from stack.sqs_queue import SqsQueueInput, SqsQueueStack
from tests.helper import case_data_path, write_case_json, read_case_json


def _synthesize(input_path, stack_id: str, app: App) -> assertions.Template:
    """Synthesise SqsQueueStack and return its template."""
    s_input = SqsQueueInput.from_config_directory(input_path, stack_id)
    stk = SqsQueueStack(
        scope=app,
        cdk_env=Environment(),
        s_input=s_input,
    )
    return assertions.Template.from_stack(stk)


@pytest.mark.unit
@pytest.mark.parametrize(
    "environment,stack_id",
    [
        pytest.param("dev", "explore-a", id="dev_explore_a"),
    ],
)
def test_sqs_queue_stack_actual(request, environment, stack_id, update_golden):
    """Compare SqsQueue template against golden data for real environments."""
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
        pytest.param("explore-a", id="custom_timeout"),
    ],
)
def test_sqs_queue_stack_custom(request, stack_id, update_golden):
    """Compare SqsQueue template against golden data for custom case config."""
    data_path = case_data_path(request)
    input_path = data_path

    template = _synthesize(input_path, stack_id, App())

    if update_golden:
        write_case_json(data_path, "expected.json", template.to_json())
    template.template_matches(read_case_json(data_path, "expected.json"))
