"""Unit tests for `config.settings` behavior.

Purpose:
- Verify environment config path resolution.
- Verify settings model loading semantics used by stack constructors.
- Verify SecureS3Setting preflight validation raises ValueError for
  incompatible configurations.
"""

import pytest

from config.settings import (
    EnvironmentSetting,
    SecureS3Setting,
    SimpleS3Setting,
    get_actual_path,
)
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


@pytest.mark.unit
@pytest.mark.parametrize(
    "environment,stack_id,expected_removal_policy",
    [
        pytest.param("dev", "phi", "DESTROY", id="dev"),
        pytest.param("staging", "phi", "RETAIN", id="staging"),
        pytest.param("production", "phi", "RETAIN", id="production"),
    ],
)
def test_secure_s3_setting_loads_from_config(
    environment, stack_id, expected_removal_policy
):
    """SecureS3Setting.from_data_path loads config for each real environment."""
    data_path = get_actual_path(environment)
    result = SecureS3Setting.from_data_path(data_path, stack_id)

    assert isinstance(result, SecureS3Setting)
    assert result.removal_policy == expected_removal_policy


@pytest.mark.unit
@pytest.mark.parametrize(
    "stack_id",
    [
        pytest.param("models", id="models"),
        pytest.param("images", id="images"),
    ],
)
def test_simple_s3_setting_loads_from_config(stack_id):
    """SimpleS3Setting.from_data_path loads config for the dev environment."""
    data_path = get_actual_path("dev")
    result = SimpleS3Setting.from_data_path(data_path, stack_id)

    assert isinstance(result, SimpleS3Setting)
    assert result.removal_policy == "DESTROY"


@pytest.mark.unit
@pytest.mark.parametrize(
    "kwargs,match",
    [
        pytest.param(
            {"worm_mode": "INVALID"},
            "worm_mode must be",
            id="bad_worm_mode",
        ),
        pytest.param(
            {"removal_policy": "DELETE"},
            "removal_policy must be",
            id="bad_removal_policy",
        ),
        pytest.param(
            {"rotation_period_days": 30},
            "rotation_period_days must be between",
            id="rotation_too_short",
        ),
        pytest.param(
            {"rotation_period_days": 9999},
            "rotation_period_days must be between",
            id="rotation_too_long",
        ),
        pytest.param(
            {"worm_enabled": True, "worm_retention_days": 0},
            "worm_retention_days must be",
            id="worm_retention_zero",
        ),
        pytest.param(
            {"enable_lifecycle_expiration": True, "deletion_days": 0},
            "deletion_days must be",
            id="deletion_days_zero",
        ),
        pytest.param(
            {
                "enable_lifecycle_expiration": True,
                "worm_enabled": True,
                "deletion_days": 100,
                "worm_retention_days": 200,
            },
            "conflicts with",
            id="lifecycle_worm_conflict",
        ),
    ],
)
def test_secure_s3_setting_preflight_rejects_invalid_config(kwargs, match):
    """SecureS3Setting raises ValueError with a descriptive message."""
    with pytest.raises(ValueError, match=match):
        SecureS3Setting(**kwargs)
