"""Tests for config.registry."""

import pytest

from config.project import SUPPORTED_APP_ENVS
from config.registry import STACKS_BY_ENV, StackFactory


@pytest.mark.unit
def test_stacks_by_env_covers_all_supported_envs():
    """Every environment in SUPPORTED_APP_ENVS must have an entry in STACKS_BY_ENV."""
    for env in SUPPORTED_APP_ENVS:
        assert (
            env in STACKS_BY_ENV
        ), f"Environment '{env}' is in SUPPORTED_APP_ENVS but missing from STACKS_BY_ENV"


@pytest.mark.unit
def test_stacks_by_env_values_are_stack_factory_lists():
    """Each STACKS_BY_ENV entry must be a non-empty list of StackFactory instances."""
    for env, factories in STACKS_BY_ENV.items():
        assert (
            isinstance(factories, list) and len(factories) > 0
        ), f"STACKS_BY_ENV['{env}'] must be a non-empty list"
        for factory in factories:
            assert isinstance(
                factory, StackFactory
            ), f"STACKS_BY_ENV['{env}'] contains a non-StackFactory item: {factory!r}"


@pytest.mark.unit
def test_stack_factory_deploy_is_callable():
    """Every StackFactory must have a callable deploy field."""
    for env, factories in STACKS_BY_ENV.items():
        for factory in factories:
            assert callable(
                factory.deploy
            ), f"StackFactory in '{env}' has non-callable deploy: {factory!r}"


@pytest.mark.unit
def test_stack_factory_discover_is_callable_or_none():
    """Every StackFactory discover field must be callable or None."""
    for env, factories in STACKS_BY_ENV.items():
        for factory in factories:
            assert factory.discover is None or callable(
                factory.discover
            ), f"StackFactory in '{env}' has invalid discover: {factory!r}"
