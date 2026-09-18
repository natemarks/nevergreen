"""Standalone discovery functions for stack settings.

Purpose:
- Provide module-level functions that fetch external AWS data and write
  results back to config JSON files.
- Imported by `config/registry.py` to attach discover callables to
  StackFactory instances without creating a circular import with
  `config/discover.py`.

Customize:
- Add a function here for each new stack type that requires external data
  before synthesis (e.g. AMI IDs, certificate ARNs, endpoint URLs).
- Each function signature must be `(data_path: Path, *args) -> None`.
"""

import json
from dataclasses import asdict
from pathlib import Path

from config.helper import (
    get_logger,
    latest_ami_from_ssm_parameter,
    latest_ecs_ami_id,
)
from config.settings import EnvironmentSetting, SimpleAsgSetting

mlog = get_logger(str(__name__))

# AWS-published SSM parameter alias for the latest GPU Deep Learning AMI.
# The DLAMI variant naming (and the "latest DLAMI versions" list at
# https://docs.aws.amazon.com/dlami/latest/devguide/) changes over time as
# AWS retires old PyTorch/OS combinations, so this needs occasional review:
# a retired variant name here fails with botocore.errorfactory.ParameterNotFound.
GPU_WORKER_AMI_SSM_PARAMETER = (
    "/aws/service/deeplearning/ami/x86_64/"
    "oss-nvidia-driver-gpu-pytorch-2.7-ubuntu-22.04/latest/ami-id"
)


def write_setting_json(setting_path: Path, setting: SimpleAsgSetting) -> None:
    """Write a settings dataclass to JSON with indentation."""
    setting_path.write_text(
        json.dumps(asdict(setting), indent=2), encoding="utf-8"
    )


def discover_simple_asg(data_path: Path, stack_id: str) -> None:
    """Discover the latest ECS-optimised AMI and persist it for one SimpleAsg."""
    mlog.info("discovering simple_asg: %s", stack_id)
    env_setting = EnvironmentSetting.from_data_path(data_path)
    setting = SimpleAsgSetting.from_data_path(data_path, stack_id)
    setting.ami_id = latest_ecs_ami_id(env_setting.default_region)
    setting_path = SimpleAsgSetting.setting_path(data_path, stack_id)
    write_setting_json(setting_path, setting)


def discover_gpu_worker(data_path: Path, stack_id: str) -> None:
    """Discover the latest GPU Deep Learning AMI and persist it for one worker."""
    mlog.info("discovering gpu_worker: %s", stack_id)
    env_setting = EnvironmentSetting.from_data_path(data_path)
    setting = SimpleAsgSetting.from_data_path(data_path, stack_id)
    setting.ami_id = latest_ami_from_ssm_parameter(
        env_setting.default_region, GPU_WORKER_AMI_SSM_PARAMETER
    )
    setting_path = SimpleAsgSetting.setting_path(data_path, stack_id)
    write_setting_json(setting_path, setting)
