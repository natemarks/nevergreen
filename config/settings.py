"""Settings models loaded from `config/<environment>/...` JSON files.

Purpose:
- Define typed dataclasses used as stack input settings.
- Map each settings class to a relative JSON path.

Flow:
- `JsonSettingBase.setting_path` resolves the file path.
- `JsonSettingBase.from_data_path` parses JSON into dataclass instances.

Customize:
- Add dataclasses for new stacks.
- Set `RELATIVE_PATH_TEMPLATE` for each settings class.
- Keep `EnvironmentSetting` aligned with account/region/tag strategy.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import ClassVar, Type, TypeVar

from config.helper import get_logger, dict_from_json_file

module_logger = get_logger(str(__name__))

t_json_setting = TypeVar(  # pylint: disable=invalid-name
    "t_json_setting", bound="JsonSettingBase"
)


class JsonSettingBase:
    """Base class for config dataclasses loaded from JSON files.

    Subclasses set `RELATIVE_PATH_TEMPLATE` and inherit shared path and load
    helpers.
    """

    RELATIVE_PATH_TEMPLATE: ClassVar[str] = ""

    @classmethod
    def setting_path(cls, data_path: Path, *path_args: str) -> Path:
        """Return the resolved settings JSON path for this class."""
        if not cls.RELATIVE_PATH_TEMPLATE:
            raise RuntimeError(
                f"{cls.__name__} must define RELATIVE_PATH_TEMPLATE"
            )
        try:
            rel_path = cls.RELATIVE_PATH_TEMPLATE.format(*path_args)
        except IndexError as exc:
            raise ValueError(
                f"Missing path parameter for {cls.__name__}: {exc}"
            ) from exc
        return data_path / rel_path

    @classmethod
    def from_data_path(
        cls: Type[t_json_setting], data_path: Path, *path_args: str
    ) -> t_json_setting:
        """Load a settings dataclass instance from a config directory."""
        return cls(
            **dict_from_json_file(cls.setting_path(data_path, *path_args))
        )


def get_actual_path(environment: str) -> Path:
    """Return the repository path to `config/<environment>`."""
    return Path(__file__).parent.joinpath(environment)


@dataclass(frozen=True, kw_only=True)
class EnvironmentSetting(JsonSettingBase):
    """Environment-level settings shared by all stacks.

    Commonly customized fields:
    - account/region identifiers
    - environment naming and release flags
    - DNS defaults used by stack modules
    """

    RELATIVE_PATH_TEMPLATE: ClassVar[str] = "environment.json"

    admin_team: str  # ex. "Operations"
    aws_account_name: str  # ex. "Daisy Sandbox"
    aws_account_number: str  # ex. "709310380790"
    default_fqdn: str  # ex. "sandbox.daisy.com"
    default_region: str  # ex. "us-east-1"
    app_env: str  # ex. "sandbox"
    is_release: bool  # ex. False

    def prefix(self) -> str:
        """Return the environment name portion used in resource prefixes."""
        return self.app_env.capitalize()


@dataclass(frozen=False, kw_only=True)
class SimpleAsgSetting(JsonSettingBase):
    """Settings for each SimpleAsg stack instance.

    This dataclass is intentionally mutable because discovery workflows may
    update fields such as `ami_id` before deployment.
    """

    RELATIVE_PATH_TEMPLATE: ClassVar[str] = "simple_asg/{0}/simple_asg.json"

    ami_id: str
    instance_type: str = "t3.micro"
    max_instances: int = 1
    min_instances: int = 1
    root_block_device_name: str = "/dev/xvda"
    root_block_device_size: int = 100  # in GB


@dataclass(frozen=True, kw_only=True)
class SecureS3Setting(
    JsonSettingBase
):  # pylint: disable=too-many-instance-attributes
    """Settings for each SecureS3Stack instance.

    Preflight validation in __post_init__ raises ValueError for incompatible
    combinations. All checks run before any CDK construct is created.
    """

    RELATIVE_PATH_TEMPLATE: ClassVar[str] = "secure_s3/{0}/secure_s3.json"

    rotation_period_days: int = 180
    enable_access_logging_bucket: bool = False
    worm_enabled: bool = False
    worm_mode: str = "GOVERNANCE"
    worm_retention_days: int = 2555
    enable_lifecycle_expiration: bool = False
    deletion_days: int = 1095
    removal_policy: str = "DESTROY"

    def __post_init__(self) -> None:
        if self.worm_mode not in {"GOVERNANCE", "COMPLIANCE"}:
            raise ValueError(
                f"worm_mode must be 'GOVERNANCE' or 'COMPLIANCE', "
                f"got '{self.worm_mode}'."
            )
        if self.removal_policy not in {"DESTROY", "RETAIN"}:
            raise ValueError(
                f"removal_policy must be 'DESTROY' or 'RETAIN', "
                f"got '{self.removal_policy}'."
            )
        if not 90 <= self.rotation_period_days <= 2560:
            raise ValueError(
                f"rotation_period_days must be between 90 and 2560, "
                f"got {self.rotation_period_days}."
            )
        if self.worm_enabled and self.worm_retention_days < 1:
            raise ValueError(
                "worm_retention_days must be >= 1 when worm_enabled=True, "
                f"got {self.worm_retention_days}."
            )
        if self.enable_lifecycle_expiration and self.deletion_days < 1:
            raise ValueError(
                "deletion_days must be >= 1 when "
                f"enable_lifecycle_expiration=True, got {self.deletion_days}."
            )
        if (
            self.enable_lifecycle_expiration
            and self.worm_enabled
            and self.deletion_days <= self.worm_retention_days
        ):
            raise ValueError(
                f"enable_lifecycle_expiration=True with "
                f"deletion_days={self.deletion_days} conflicts with "
                f"worm_enabled=True and "
                f"worm_retention_days={self.worm_retention_days}. "
                "The lifecycle rule cannot delete WORM-locked objects before "
                "their retention period expires. Fix: either set "
                "enable_lifecycle_expiration=False, set "
                "deletion_days > worm_retention_days, or set worm_enabled=False."
            )


@dataclass(frozen=True, kw_only=True)
class AppVpcSetting(JsonSettingBase):
    """Settings for the AppVpc stack template.

    Commonly customized fields:
    - CIDR range
    - availability-zone count
    """

    RELATIVE_PATH_TEMPLATE: ClassVar[str] = "app_vpc/app_vpc.json"

    cidr: str
    max_azs: int = 2
