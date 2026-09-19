"""Tests for config.force_refresh."""

# pylint: disable=redefined-outer-name,duplicate-code
# force_refresh.py deliberately mirrors troubleshoot.py's ASG-resolution
# and SSM-polling shape (see its own module docstring), so these tests
# mirror comfyui_client.py/test_troubleshoot.py's fixture and test shapes
# too -- not accidental duplication to refactor.
from unittest.mock import MagicMock, patch

import pytest
from botocore.exceptions import ClientError

from config.force_refresh import (
    _wait_for_command,
    force_refresh,
    resolve_instance_ids,
)
from tests.unit.config._shared import (
    asg_resources as _asg_resources,
    write_environment_json as _write_environment_json,
    write_simple_asg_config as _write_simple_asg_config,
)


@pytest.fixture
def data_path(tmp_path):
    """Return a tmp data path with environment.json and a comfyui config."""
    _write_environment_json(tmp_path)
    _write_simple_asg_config(tmp_path, "comfyui")
    return tmp_path


@pytest.mark.unit
def test_resolve_instance_ids_returns_every_instance_in_the_asg(data_path):
    """resolve_instance_ids lists every instance currently in the ASG."""
    cfn = MagicMock()
    autoscaling = MagicMock()
    cfn.describe_stack_resources.return_value = _asg_resources("real-asg")
    autoscaling.describe_auto_scaling_groups.return_value = {
        "AutoScalingGroups": [
            {
                "Instances": [
                    {"InstanceId": "i-one"},
                    {"InstanceId": "i-two"},
                ]
            }
        ]
    }

    with patch("config.force_refresh.check_aws_account"), patch(
        "config.force_refresh.get_actual_path", return_value=data_path
    ):
        instance_ids = resolve_instance_ids(
            "dev", cfn_client=cfn, autoscaling_client=autoscaling
        )

    assert instance_ids == ["i-one", "i-two"]


@pytest.mark.unit
def test_resolve_instance_ids_raises_when_no_asg(data_path):
    """resolve_instance_ids raises when the stack has no ASG resource."""
    cfn = MagicMock()
    cfn.describe_stack_resources.return_value = {"StackResources": []}

    with patch("config.force_refresh.check_aws_account"), patch(
        "config.force_refresh.get_actual_path", return_value=data_path
    ), pytest.raises(RuntimeError, match="No deployed AutoScalingGroup"):
        resolve_instance_ids(
            "dev", cfn_client=cfn, autoscaling_client=MagicMock()
        )


@pytest.mark.unit
def test_wait_for_command_returns_the_final_status():
    """_wait_for_command polls until the command finishes, then returns it."""
    ssm = MagicMock()
    ssm.get_command_invocation.return_value = {"Status": "Success"}

    status = _wait_for_command(
        ssm, "cmd-1", "i-one", poll_interval_seconds=0, timeout_seconds=5
    )

    assert status == "Success"


@pytest.mark.unit
def test_wait_for_command_retries_through_invocation_does_not_exist():
    """A transient InvocationDoesNotExist retries instead of failing."""
    ssm = MagicMock()
    not_yet = ClientError(
        {"Error": {"Code": "InvocationDoesNotExist", "Message": "nope"}},
        "GetCommandInvocation",
    )
    ssm.get_command_invocation.side_effect = [not_yet, {"Status": "Success"}]

    status = _wait_for_command(
        ssm, "cmd-1", "i-one", poll_interval_seconds=0, timeout_seconds=5
    )

    assert status == "Success"
    assert ssm.get_command_invocation.call_count == 2


@pytest.mark.unit
def test_wait_for_command_times_out_when_never_finishing():
    """_wait_for_command raises TimeoutError if the command never completes."""
    ssm = MagicMock()
    ssm.get_command_invocation.return_value = {"Status": "InProgress"}

    with pytest.raises(TimeoutError):
        _wait_for_command(
            ssm, "cmd-1", "i-one", poll_interval_seconds=0, timeout_seconds=0
        )


@pytest.mark.unit
def test_force_refresh_sends_the_command_to_every_instance():
    """force_refresh sends one SSM command per instance and collects results."""
    ssm = MagicMock()
    ssm.send_command.side_effect = [
        {"Command": {"CommandId": "cmd-1"}},
        {"Command": {"CommandId": "cmd-2"}},
    ]
    ssm.get_command_invocation.return_value = {"Status": "Success"}

    results = force_refresh(
        "dev",
        ssm_client=ssm,
        poll_interval_seconds=0,
        instance_ids=["i-one", "i-two"],
    )

    assert results == {"i-one": "Success", "i-two": "Success"}
    assert ssm.send_command.call_count == 2
    ssm.send_command.assert_any_call(
        InstanceIds=["i-one"],
        DocumentName="AWS-RunShellScript",
        Parameters={
            "commands": [
                "sudo /opt/comfyui/bin/refresh_worker.sh --force-models"
            ]
        },
    )


@pytest.mark.unit
def test_force_refresh_returns_empty_when_no_instances():
    """No instances in the ASG means nothing to send, not an error."""
    results = force_refresh("dev", ssm_client=MagicMock(), instance_ids=[])

    assert not results
