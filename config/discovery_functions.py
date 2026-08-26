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

from config.helper import get_logger, latest_ecs_ami_id
from config.settings import EnvironmentSetting, SimpleAsgSetting

mlog = get_logger(str(__name__))


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
