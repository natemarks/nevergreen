"""Tests for config.asg_scale."""

# pylint: disable=redefined-outer-name
import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from botocore.exceptions import ClientError

from config.asg_scale import AsgScaler

_ENVIRONMENT_JSON = {
    "admin_team": "Operations",
    "aws_account_name": "Test",
    "aws_account_number": "709310380790",
    "default_fqdn": "test.example.com",
    "default_region": "us-east-1",
    "app_env": "dev",
    "is_release": False,
}


def _write_simple_asg_config(
    data_path: Path, stack_id: str, min_instances: int, max_instances: int
) -> None:
    """Write a minimal simple_asg.json for one stack_id under data_path."""
    setting_dir = data_path / "simple_asg" / stack_id
    setting_dir.mkdir(parents=True)
    (setting_dir / "simple_asg.json").write_text(
        json.dumps(
            {
                "ami_id": "ami-00000000000000000",
                "min_instances": min_instances,
                "max_instances": max_instances,
            }
        )
    )


def _asg_resources(physical_id: str) -> dict:
    """Return a describe_stack_resources payload with one ASG resource."""
    return {
        "StackResources": [
            {
                "ResourceType": "AWS::AutoScaling::AutoScalingGroup",
                "PhysicalResourceId": physical_id,
            }
        ]
    }


@pytest.fixture
def scaler(tmp_path):
    """Return an AsgScaler with mocked AWS clients and a tmp data path."""
    (tmp_path / "environment.json").write_text(json.dumps(_ENVIRONMENT_JSON))
    cfn = MagicMock()
    autoscaling = MagicMock()
    with patch("config.asg_scale.check_aws_account"), patch(
        "config.asg_scale.get_actual_path", return_value=tmp_path
    ):
        instance = AsgScaler(
            "dev", cfn_client=cfn, autoscaling_client=autoscaling
        )
    return instance


@pytest.mark.unit
def test_stack_ids_empty_when_no_simple_asg_dir(scaler):
    """stack_ids returns an empty list when no simple_asg dir exists."""
    assert scaler.stack_ids() == []


@pytest.mark.unit
def test_stack_ids_lists_directories_with_simple_asg_json(scaler):
    """stack_ids only lists dirs that actually contain simple_asg.json."""
    _write_simple_asg_config(scaler.data_path, "aaa", 1, 1)
    _write_simple_asg_config(scaler.data_path, "comfyui", 1, 1)
    (scaler.data_path / "simple_asg" / "empty_dir").mkdir(parents=True)

    assert scaler.stack_ids() == ["aaa", "comfyui"]


@pytest.mark.unit
def test_run_down_sets_zero_regardless_of_config(scaler):
    """ "down" sets min/max/desired to 0 even when config says otherwise."""
    _write_simple_asg_config(scaler.data_path, "aaa", 2, 5)
    scaler.cfn.describe_stack_resources.return_value = _asg_resources(
        "real-asg-name"
    )

    scaler.run("down")

    scaler.autoscaling.update_auto_scaling_group.assert_called_once_with(
        AutoScalingGroupName="real-asg-name",
        MinSize=0,
        MaxSize=0,
        DesiredCapacity=0,
    )


@pytest.mark.unit
def test_run_up_uses_config_min_max_and_desired_equals_min(scaler):
    """ "up" uses config min/max; desired reproduces CDK's own default (min)."""
    _write_simple_asg_config(scaler.data_path, "aaa", 2, 5)
    scaler.cfn.describe_stack_resources.return_value = _asg_resources(
        "real-asg-name"
    )

    scaler.run("up")

    scaler.autoscaling.update_auto_scaling_group.assert_called_once_with(
        AutoScalingGroupName="real-asg-name",
        MinSize=2,
        MaxSize=5,
        DesiredCapacity=2,
    )


@pytest.mark.unit
def test_run_skips_stack_not_yet_deployed(scaler):
    """A stack_id whose CFN stack doesn't exist yet is skipped, not fatal."""
    _write_simple_asg_config(scaler.data_path, "aaa", 1, 1)
    scaler.cfn.describe_stack_resources.side_effect = ClientError(
        {"Error": {"Code": "ValidationError", "Message": "does not exist"}},
        "DescribeStackResources",
    )

    scaler.run("down")

    scaler.autoscaling.update_auto_scaling_group.assert_not_called()


@pytest.mark.unit
def test_run_skips_stack_with_no_asg_resource(scaler):
    """A stack with no AutoScalingGroup resource is skipped, not fatal."""
    _write_simple_asg_config(scaler.data_path, "aaa", 1, 1)
    scaler.cfn.describe_stack_resources.return_value = {"StackResources": []}

    scaler.run("down")

    scaler.autoscaling.update_auto_scaling_group.assert_not_called()
