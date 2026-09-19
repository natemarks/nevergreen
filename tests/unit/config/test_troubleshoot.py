"""Tests for config.troubleshoot."""

# pylint: disable=redefined-outer-name
from unittest.mock import MagicMock, patch

import pytest

from config.troubleshoot import (
    queue_attributes,
    resolve_instance_id,
    run_diagnostics,
)
from tests.unit.config._shared import (
    asg_resources as _asg_resources,
    write_environment_json as _write_environment_json,
    write_simple_asg_config as _write_simple_asg_config,
    write_sqs_queue_config as _write_sqs_queue_config,
)


@pytest.fixture
def data_path(tmp_path):
    """Return a tmp data path with environment.json, comfyui, and a queue."""
    _write_environment_json(tmp_path)
    _write_simple_asg_config(tmp_path, "comfyui")
    _write_sqs_queue_config(tmp_path, "explore-a")
    return tmp_path


@pytest.mark.unit
def test_resolve_instance_id_returns_the_running_instance(data_path):
    """resolve_instance_id resolves the gpu_worker's instance via its ASG."""
    cfn = MagicMock()
    autoscaling = MagicMock()
    cfn.describe_stack_resources.return_value = _asg_resources("real-asg")
    autoscaling.describe_auto_scaling_groups.return_value = {
        "AutoScalingGroups": [
            {"Instances": [{"InstanceId": "i-0123456789abcdef0"}]}
        ]
    }

    with patch("config.troubleshoot.check_aws_account"), patch(
        "config.troubleshoot.get_actual_path", return_value=data_path
    ):
        instance_id = resolve_instance_id(
            "dev", cfn_client=cfn, autoscaling_client=autoscaling
        )

    assert instance_id == "i-0123456789abcdef0"


@pytest.mark.unit
def test_resolve_instance_id_raises_when_no_asg(data_path):
    """resolve_instance_id raises when the stack has no ASG resource."""
    cfn = MagicMock()
    cfn.describe_stack_resources.return_value = {"StackResources": []}

    with patch("config.troubleshoot.check_aws_account"), patch(
        "config.troubleshoot.get_actual_path", return_value=data_path
    ), pytest.raises(RuntimeError, match="No deployed AutoScalingGroup"):
        resolve_instance_id(
            "dev", cfn_client=cfn, autoscaling_client=MagicMock()
        )


@pytest.mark.unit
def test_resolve_instance_id_raises_when_no_instances(data_path):
    """resolve_instance_id raises when the ASG has no running instances."""
    cfn = MagicMock()
    autoscaling = MagicMock()
    cfn.describe_stack_resources.return_value = _asg_resources("real-asg")
    autoscaling.describe_auto_scaling_groups.return_value = {
        "AutoScalingGroups": [{"Instances": []}]
    }

    with patch("config.troubleshoot.check_aws_account"), patch(
        "config.troubleshoot.get_actual_path", return_value=data_path
    ), pytest.raises(RuntimeError, match="No running instances"):
        resolve_instance_id(
            "dev", cfn_client=cfn, autoscaling_client=autoscaling
        )


@pytest.mark.unit
def test_run_diagnostics_returns_stdout_once_command_succeeds():
    """run_diagnostics polls until the SSM command finishes, then returns it."""
    ssm = MagicMock()
    ssm.send_command.return_value = {"Command": {"CommandId": "cmd-1"}}
    ssm.get_command_invocation.return_value = {
        "Status": "Success",
        "StandardOutputContent": "ok\n",
        "StandardErrorContent": "",
    }

    result = run_diagnostics(
        "i-123", commands=["echo ok"], ssm_client=ssm, poll_interval_seconds=0
    )

    assert result == "ok\n"
    ssm.send_command.assert_called_once_with(
        InstanceIds=["i-123"],
        DocumentName="AWS-RunShellScript",
        Parameters={"commands": ["echo ok"]},
    )


@pytest.mark.unit
def test_run_diagnostics_appends_stderr_when_present():
    """Non-empty stderr is appended to the returned output."""
    ssm = MagicMock()
    ssm.send_command.return_value = {"Command": {"CommandId": "cmd-1"}}
    ssm.get_command_invocation.return_value = {
        "Status": "Failed",
        "StandardOutputContent": "partial\n",
        "StandardErrorContent": "boom\n",
    }

    result = run_diagnostics(
        "i-123", commands=["false"], ssm_client=ssm, poll_interval_seconds=0
    )

    assert "partial" in result
    assert "--- stderr ---" in result
    assert "boom" in result


@pytest.mark.unit
def test_run_diagnostics_polls_through_in_progress_status():
    """run_diagnostics keeps polling while the command is still running."""
    ssm = MagicMock()
    ssm.send_command.return_value = {"Command": {"CommandId": "cmd-1"}}
    ssm.get_command_invocation.side_effect = [
        {"Status": "InProgress"},
        {
            "Status": "Success",
            "StandardOutputContent": "done\n",
            "StandardErrorContent": "",
        },
    ]

    result = run_diagnostics(
        "i-123", commands=["echo ok"], ssm_client=ssm, poll_interval_seconds=0
    )

    assert result == "done\n"
    assert ssm.get_command_invocation.call_count == 2


@pytest.mark.unit
def test_run_diagnostics_times_out_when_never_finishing():
    """run_diagnostics raises TimeoutError if the command never completes."""
    ssm = MagicMock()
    ssm.send_command.return_value = {"Command": {"CommandId": "cmd-1"}}
    ssm.get_command_invocation.return_value = {"Status": "InProgress"}

    with pytest.raises(TimeoutError):
        run_diagnostics(
            "i-123",
            commands=["echo ok"],
            ssm_client=ssm,
            poll_interval_seconds=0,
            timeout_seconds=0,
        )


@pytest.mark.unit
def test_queue_attributes_returns_queue_and_dlq_counts(data_path):
    """queue_attributes reads message counts for both the queue and its DLQ."""
    sqs = MagicMock()
    sqs.get_queue_url.side_effect = [
        {"QueueUrl": "https://example/explore-a-queue"},
        {"QueueUrl": "https://example/explore-a-queue-dlq"},
    ]
    sqs.get_queue_attributes.side_effect = [
        {
            "Attributes": {
                "ApproximateNumberOfMessages": "2",
                "ApproximateNumberOfMessagesNotVisible": "0",
            }
        },
        {
            "Attributes": {
                "ApproximateNumberOfMessages": "0",
                "ApproximateNumberOfMessagesNotVisible": "0",
            }
        },
    ]

    with patch("config.troubleshoot.check_aws_account"), patch(
        "config.troubleshoot.get_actual_path", return_value=data_path
    ):
        result = queue_attributes("dev", sqs_client=sqs)

    assert result["queue"]["ApproximateNumberOfMessages"] == "2"
    assert result["dead_letter_queue"]["ApproximateNumberOfMessages"] == "0"
    sqs.get_queue_url.assert_any_call(
        QueueName="nevergreen-dev-explore-a-queue"
    )
    sqs.get_queue_url.assert_any_call(
        QueueName="nevergreen-dev-explore-a-queue-dlq"
    )
