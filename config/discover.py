#!/usr/bin/env python3
"""Discovery workflow for external configuration data.

Purpose:
- Query external AWS data required by stacks in each environment.
- Persist updated settings under `config/<env>/...`.

Flow:
- Parse target environment from CLI args.
- Build a DiscoveryRunner for that environment.
- DiscoveryRunner.run iterates STACKS_BY_ENV[app_env] and calls discover
  on each factory that has one.

Customize:
- Add new stack types with discovery by adding a discover callable to their
  StackFactory in config/registry.py.
- Add new standalone discovery functions in config/discovery_functions.py.
"""

import argparse

from config.helper import check_app_env, check_aws_account, get_logger
from config.project import SUPPORTED_APP_ENVS
from config.registry import STACKS_BY_ENV
from config.settings import get_actual_path

mlog = get_logger(str(__name__))


def get_environment_id() -> str:
    """Return environment id from CLI args (`dev|staging|production`)."""
    parser = argparse.ArgumentParser(description="Get the environment ID.")
    parser.add_argument(
        "environment",
        type=str,
        choices=list(SUPPORTED_APP_ENVS),
        help="Environment ID (must be one of: dev, staging, production)",
    )
    args = parser.parse_args()
    return args.environment


class DiscoveryRunner:  # pylint: disable=too-few-public-methods
    """Runs discovery for all eligible stacks in one application environment.

    For each factory in STACKS_BY_ENV[app_env], calls factory.discover if it
    is not None, passing the environment data path. Factories with
    discover=None are silently skipped.
    """

    def __init__(self, app_env: str):
        """Validate environment/account and resolve data path."""
        check_app_env(app_env)
        check_aws_account(app_env)
        self.app_env = app_env
        self.data_path = get_actual_path(app_env)

    def run(self) -> None:
        """Run discover for every eligible stack factory that has one."""
        for factory in STACKS_BY_ENV[self.app_env]:
            if factory.discover is not None:
                factory.discover(self.data_path)


def get_discovery_runner(app_env: str) -> DiscoveryRunner:
    """Return a DiscoveryRunner for the requested application environment."""
    return DiscoveryRunner(app_env)


def main() -> None:
    """Run discovery for the requested environment."""
    get_discovery_runner(get_environment_id()).run()


if __name__ == "__main__":
    main()
