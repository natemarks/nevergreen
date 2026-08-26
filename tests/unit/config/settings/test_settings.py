"""Unit tests for `config.settings` behavior.

Purpose:
- Verify environment config path resolution.
- Verify settings model loading semantics used by stack constructors.
"""

import pytest

from config.settings import EnvironmentSetting, get_actual_path
from tests.unit.config.settings._shared import APP_ENVS, expected_config_path


@pytest.mark.unit
@pytest.mark.parametrize(
    "environment",
    [pytest.param(value, id=value) for value in APP_ENVS],
)
def test_get_actual_environment(environment):
    """get_actual_path points at config/<environment>."""
    assert expected_config_path(environment) == get_actual_path(environment)


@pytest.mark.unit
def test_environment_factory_reads_expected_environment():
    """EnvironmentSetting.from_data_path returns the expected model."""
    data_path = get_actual_path("dev")
    result = EnvironmentSetting.from_data_path(data_path)

    assert isinstance(result, EnvironmentSetting)
    assert result.app_env == "dev"
