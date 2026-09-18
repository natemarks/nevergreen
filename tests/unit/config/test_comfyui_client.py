"""Tests for config.comfyui_client."""

# pylint: disable=redefined-outer-name
import json
import socket
from unittest.mock import MagicMock, patch

import pytest

from config.comfyui_client import discover_url, post_workflow, wait_for_port
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
def test_discover_url_returns_public_ip_url(data_path):
    """discover_url resolves the instance's public IP into an http:// URL."""
    cfn = MagicMock()
    autoscaling = MagicMock()
    ec2 = MagicMock()
    cfn.describe_stack_resources.return_value = _asg_resources("real-asg-name")
    autoscaling.describe_auto_scaling_groups.return_value = {
        "AutoScalingGroups": [
            {"Instances": [{"InstanceId": "i-0123456789abcdef0"}]}
        ]
    }
    ec2.describe_instances.return_value = {
        "Reservations": [{"Instances": [{"PublicIpAddress": "203.0.113.5"}]}]
    }

    with patch("config.comfyui_client.check_aws_account"), patch(
        "config.comfyui_client.get_actual_path", return_value=data_path
    ):
        url = discover_url(
            "dev",
            cfn_client=cfn,
            autoscaling_client=autoscaling,
            ec2_client=ec2,
        )

    assert url == "http://203.0.113.5:8188"


@pytest.mark.unit
def test_discover_url_raises_when_no_asg(data_path):
    """discover_url raises when the stack has no AutoScalingGroup resource."""
    cfn = MagicMock()
    cfn.describe_stack_resources.return_value = {"StackResources": []}

    with patch("config.comfyui_client.check_aws_account"), patch(
        "config.comfyui_client.get_actual_path", return_value=data_path
    ), pytest.raises(RuntimeError, match="No deployed AutoScalingGroup"):
        discover_url(
            "dev",
            cfn_client=cfn,
            autoscaling_client=MagicMock(),
            ec2_client=MagicMock(),
        )


@pytest.mark.unit
def test_discover_url_raises_when_no_instances(data_path):
    """discover_url raises when the ASG has no running instances."""
    cfn = MagicMock()
    autoscaling = MagicMock()
    cfn.describe_stack_resources.return_value = _asg_resources("real-asg-name")
    autoscaling.describe_auto_scaling_groups.return_value = {
        "AutoScalingGroups": [{"Instances": []}]
    }

    with patch("config.comfyui_client.check_aws_account"), patch(
        "config.comfyui_client.get_actual_path", return_value=data_path
    ), pytest.raises(RuntimeError, match="No running instances"):
        discover_url(
            "dev",
            cfn_client=cfn,
            autoscaling_client=autoscaling,
            ec2_client=MagicMock(),
        )


@pytest.mark.unit
def test_discover_url_raises_when_no_public_ip(data_path):
    """discover_url raises when the instance has no public IP."""
    cfn = MagicMock()
    autoscaling = MagicMock()
    ec2 = MagicMock()
    cfn.describe_stack_resources.return_value = _asg_resources("real-asg-name")
    autoscaling.describe_auto_scaling_groups.return_value = {
        "AutoScalingGroups": [
            {"Instances": [{"InstanceId": "i-0123456789abcdef0"}]}
        ]
    }
    ec2.describe_instances.return_value = {
        "Reservations": [{"Instances": [{}]}]
    }

    with patch("config.comfyui_client.check_aws_account"), patch(
        "config.comfyui_client.get_actual_path", return_value=data_path
    ), pytest.raises(RuntimeError, match="no public IP"):
        discover_url(
            "dev",
            cfn_client=cfn,
            autoscaling_client=autoscaling,
            ec2_client=ec2,
        )


@pytest.mark.unit
def test_wait_for_port_returns_on_first_success():
    """wait_for_port returns immediately once the connection succeeds."""
    with patch("config.comfyui_client.socket.create_connection") as connect:
        connect.return_value.__enter__ = MagicMock()
        connect.return_value.__exit__ = MagicMock(return_value=False)
        wait_for_port("example.com", 8188, timeout=5, interval=0)
    connect.assert_called_once_with(("example.com", 8188), timeout=5)


@pytest.mark.unit
def test_wait_for_port_times_out():
    """wait_for_port raises TimeoutError if the port never accepts."""
    with patch(
        "config.comfyui_client.socket.create_connection",
        side_effect=OSError("refused"),
    ), pytest.raises(TimeoutError):
        wait_for_port("example.com", 8188, timeout=0, interval=0)


@pytest.mark.unit
def test_wait_for_port_retries_then_succeeds():
    """wait_for_port retries after a failure and returns on success."""
    ok_cm = MagicMock()
    ok_cm.__enter__ = MagicMock()
    ok_cm.__exit__ = MagicMock(return_value=False)
    with patch(
        "config.comfyui_client.socket.create_connection",
        side_effect=[socket.error("refused"), ok_cm],
    ) as connect, patch("config.comfyui_client.time.sleep"):
        wait_for_port("example.com", 8188, timeout=5, interval=0)
    assert connect.call_count == 2


@pytest.mark.unit
def test_post_workflow_wraps_graph_under_prompt_key(tmp_path):
    """post_workflow POSTs the graph JSON wrapped under a "prompt" key."""
    workflow_path = tmp_path / "workflow.json"
    graph = {"2": {"class_type": "CheckpointLoaderSimple", "inputs": {}}}
    workflow_path.write_text(json.dumps(graph))

    with patch("config.comfyui_client.subprocess.run") as run:
        post_workflow("http://203.0.113.5:8188", workflow_path)

    run.assert_called_once()
    (args,), kwargs = run.call_args
    assert args[0] == "curl"
    assert "http://203.0.113.5:8188/prompt" in args
    assert kwargs["check"] is True
    body_index = args.index("-d") + 1
    assert json.loads(args[body_index]) == {"prompt": graph}
