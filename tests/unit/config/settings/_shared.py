"""Shared constants and path helpers for config/settings unit tests.

Purpose:
- Keep repeated path conventions in one local test utility module.
- Avoid duplicating environment lists and expected path construction.
"""

from pathlib import Path

from config.helper import PROJECT_ROOT
from config.project import (  # pylint: disable=unused-import
    SUPPORTED_APP_ENVS as APP_ENVS,
)


def expected_config_path(environment: str) -> Path:
    """Return expected repository config directory for an environment."""
    return PROJECT_ROOT / "config" / environment


def expected_test_data_root() -> Path:
    """Return root directory for repository golden/case data."""
    return PROJECT_ROOT / "test_data"


def expected_module_data_root(module_name: str) -> Path:
    """Return `test_data` root for a config/settings test module."""
    return expected_test_data_root() / "unit/config/settings" / module_name
