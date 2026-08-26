"""Project-level template defaults and customization contract.

Purpose:
- Centralize project-specific values used across app, config, and stacks.
- Provide one metadata file (`template_defaults.json`) for GitHub template users.

Flow:
- Load defaults from `config/template_defaults.json` at import time.
- Expose typed module constants consumed by runtime modules.

Customize:
- For new projects created from the GitHub template, update
  `config/template_defaults.json` first.
- Keep environment keys consistent across account and rollout mappings.
"""

import json
from pathlib import Path
from typing import Any

DEFAULTS_PATH = Path(__file__).with_name("template_defaults.json")


def _load_defaults() -> dict[str, Any]:
    """Load template defaults JSON as a dictionary."""
    with DEFAULTS_PATH.open(encoding="utf-8") as file_obj:
        data = json.load(file_obj)
    if not isinstance(data, dict):
        raise RuntimeError(f"Invalid defaults format in {DEFAULTS_PATH}")
    return data


def _require_string(data: dict[str, Any], key: str) -> str:
    """Return required string value for key or raise runtime error."""
    value = data.get(key)
    if not isinstance(value, str):
        raise RuntimeError(f"Expected string for {key} in {DEFAULTS_PATH}")
    return value


def _require_string_list(data: dict[str, Any], key: str) -> tuple[str, ...]:
    """Return required list of strings for key as tuple."""
    value = data.get(key)
    if not isinstance(value, list) or not all(
        isinstance(item, str) for item in value
    ):
        raise RuntimeError(f"Expected list[str] for {key} in {DEFAULTS_PATH}")
    return tuple(value)


def _require_string_map(data: dict[str, Any], key: str) -> dict[str, str]:
    """Return required mapping[str, str] for key."""
    value = data.get(key)
    if not isinstance(value, dict):
        raise RuntimeError(f"Expected mapping for {key} in {DEFAULTS_PATH}")
    if not all(isinstance(k, str) for k in value.keys()):
        raise RuntimeError(
            f"Expected string keys for {key} in {DEFAULTS_PATH}"
        )
    if not all(isinstance(v, str) for v in value.values()):
        raise RuntimeError(
            f"Expected string values for {key} in {DEFAULTS_PATH}"
        )
    return dict(value)


_DEFAULTS = _load_defaults()

APP_NAME = _require_string(_DEFAULTS, "app_name")
IAC_PROJECT_URL = _require_string(_DEFAULTS, "iac_project_url")
SUPPORTED_APP_ENVS = _require_string_list(_DEFAULTS, "supported_app_envs")
APP_ENV_TO_AWS_ACCOUNT = _require_string_map(
    _DEFAULTS, "app_env_to_aws_account"
)

for app_env in SUPPORTED_APP_ENVS:
    if app_env not in APP_ENV_TO_AWS_ACCOUNT:
        raise RuntimeError(
            "Missing account mapping for environment "
            f"{app_env} in {DEFAULTS_PATH}"
        )
