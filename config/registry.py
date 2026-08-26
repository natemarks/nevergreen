"""Stack eligibility registry.

Purpose:
- Define the StackFactory dataclass that pairs a deploy callable with an
  optional discover callable.
- Declare STACKS_BY_ENV as the single source of truth for which stacks are
  eligible in each environment and in what deployment order.

Customize:
- To add a new stack type, define app-level deploy/discover functions in the
  relevant stack module, then add a StackFactory constant or factory function
  below.
- To add a new stack instance (multi-stack), call the factory function with
  the new stack_id and append it to the appropriate environment list(s).
- To graduate a stack to a higher environment, add its StackFactory to that
  environment's list. Add the corresponding config files before deploying.
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from config.discovery_functions import discover_simple_asg
from config.project import SUPPORTED_APP_ENVS


@dataclass
class StackFactory:
    """Bundles deploy and discover callables for one logical stack slot.

    deploy: (inv, app, cdk_env) -> Stack — called by Inventory.deploy_stacks
    discover: (data_path) -> None | None — called by DiscoveryRunner.run;
              None means no external discovery is needed for this stack type.
    """

    deploy: Callable
    discover: Callable | None = field(default=None)


def _app_vpc_deploy(inv, app, cdk_env):
    return inv._deploy_app_vpc(  # pylint: disable=protected-access
        app, cdk_env
    )


app_vpc = StackFactory(deploy=_app_vpc_deploy, discover=None)


def simple_asg(stack_id: str) -> StackFactory:
    """Return a StackFactory for one SimpleAsg instance identified by stack_id."""

    def _deploy(inv, app, cdk_env):
        return inv._deploy_simple_asg(  # pylint: disable=protected-access
            app, cdk_env, stack_id
        )

    def _discover(data_path: Path) -> None:
        discover_simple_asg(data_path, stack_id)

    return StackFactory(deploy=_deploy, discover=_discover)


STACKS_BY_ENV: dict[str, list[StackFactory]] = {
    "dev": [app_vpc, simple_asg("aaa")],
    "staging": [app_vpc, simple_asg("bbb")],
    "production": [app_vpc, simple_asg("ccc")],
}

for _env in SUPPORTED_APP_ENVS:
    if _env not in STACKS_BY_ENV:
        raise RuntimeError(
            f"Environment '{_env}' is listed in SUPPORTED_APP_ENVS "
            "but has no entry in STACKS_BY_ENV in config/registry.py"
        )
