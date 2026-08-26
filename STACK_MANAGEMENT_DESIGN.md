# Stack Management Design

This document is the output of a design session on the Inventory and DiscoveryRunner
pattern. It supersedes the Issue 1 discussion in `REFACTOR_SUGGESTIONS.md`.

## Problem statement

The current `inventory.py` and `discover.py` each contain three environment subclasses
(`DevInventory`, `StagingInventory`, `ProductionInventory` and their DiscoveryRunner
counterparts) that do nothing except assign a class variable already available from
`SIMPLE_ASG_IDS_BY_ENV`. Adding a new environment or a new stack type requires touching
both files with purely mechanical changes. The design below eliminates this by making a
single dict — `STACKS_BY_ENV` — the one authoritative place for all three concerns: what
`cdk ls` shows per environment, what discovery runs before a deployment, and what changes
when a stack graduates to a higher environment.

---

## Core new type: `StackFactory`

```python
from dataclasses import dataclass, field
from typing import Callable, TYPE_CHECKING
from pathlib import Path
from aws_cdk import App, Environment, Stack

if TYPE_CHECKING:
    from config.inventory import Inventory


@dataclass
class StackFactory:
    deploy: Callable[["Inventory", App, Environment], Stack]
    discover: Callable[[Path], None] | None = None
```

- `deploy` — called by `Inventory.deploy_stacks`; receives the Inventory instance (for
  dependency lookup), the CDK App, and the CDK Environment; returns the deployed Stack so
  it can be registered for downstream access.
- `discover` — called by `DiscoveryRunner.run` before synthesis; fetches external data
  and writes it back to config JSON files. `None` means no external data is needed.

`StackFactory` lives in `config/registry.py` alongside `STACKS_BY_ENV` to avoid a
circular import (see Module structure below).

---

## The eligibility list: `STACKS_BY_ENV`

`STACKS_BY_ENV` is a module-level dict in `config/registry.py`. It is the single source
of truth for all three environments.

```python
# config/registry.py

from config.registry_factories import app_vpc, simple_asg, debug

STACKS_BY_ENV: dict[str, list[StackFactory]] = {
    "dev":        [app_vpc, simple_asg("aaa"), debug],
    "staging":    [app_vpc, simple_asg("bbb")],
    "production": [app_vpc, simple_asg("ccc")],
}
```

**Reading the list:**
- Each row answers "what does `cdk ls` show for this environment?"
- List order is deployment and discovery order — put dependencies before the stacks that
  need them.
- A missing stack type in an environment means it does not deploy there.

### Unique stack factory (one per environment)

```python
# in config/registry.py or config/registry_factories.py

app_vpc = StackFactory(
    deploy=lambda inv, app, cdk_env: inv._deploy_app_vpc(app, cdk_env),
    # discover=None  — AppVpc has no external data to fetch
)
```

`app_vpc` is a module-level constant because there is only ever one instance.

### Multi stack factory (N per environment)

```python
def simple_asg(stack_id: str) -> StackFactory:
    """Return a StackFactory bound to a specific SimpleAsg instance."""
    return StackFactory(
        deploy=lambda inv, app, cdk_env: inv._deploy_simple_asg(app, cdk_env, stack_id),
        discover=lambda data_path: discover_simple_asg(data_path, stack_id),
    )
```

`simple_asg("aaa")` and `simple_asg("bbb")` produce two independent `StackFactory`
instances. Each has its own `stack_id` bound into the closures. Config for each lives at
`config/<env>/simple_asg/<stack_id>/simple_asg.json`.

---

## Updated `Inventory` class

```python
class Inventory:
    def __init__(self, app_env: str):
        check_app_env(app_env)
        check_aws_account(app_env)
        self.data_path = get_actual_path(app_env)
        self.app_env = app_env
        self.environment_setting = EnvironmentSetting.from_data_path(self.data_path)
        self._deployed: dict[str, Stack] = {}

    def deploy_stacks(self, app: App, cdk_env: Environment) -> None:
        for factory in STACKS_BY_ENV[self.app_env]:
            stack = factory.deploy(self, app, cdk_env)
            self._deployed[stack.stack_name] = stack

    def _get_deployed(self, stack_name: str) -> Stack:
        """Return an already-deployed stack. Used by factory lambdas for dependencies."""
        if stack_name not in self._deployed:
            raise RuntimeError(
                f"Stack '{stack_name}' not yet deployed. "
                f"Check list order in STACKS_BY_ENV for '{self.app_env}'."
            )
        return self._deployed[stack_name]

    def _deploy_app_vpc(self, app: App, cdk_env: Environment) -> AppVpcStack:
        s_input = AppVpcInput.from_config_directory(self.data_path)
        return AppVpcStack(scope=app, cdk_env=cdk_env, s_input=s_input)

    def _deploy_simple_asg(
        self, app: App, cdk_env: Environment, stack_id: str
    ) -> SimpleAsgStack:
        # SimpleAsg depends on AppVpc — AppVpc must be earlier in the list
        app_vpc_stack = self._get_deployed(
            f"Starter{self.environment_setting.prefix()}AppVpcStack"
        )
        s_input = SimpleAsgInput.from_config_directory(self.data_path, stack_id)
        return SimpleAsgStack(
            scope=app, cdk_env=cdk_env, s_input=s_input, app_vpc_stack=app_vpc_stack
        )


def get_inventory(app_env: str) -> Inventory:
    check_app_env(app_env)
    return Inventory(app_env=app_env)
```

**What's gone:** `DevInventory`, `StagingInventory`, `ProductionInventory`, `INVENTORY_MAP`.

---

## Updated `DiscoveryRunner` class

```python
class DiscoveryRunner:
    def __init__(self, app_env: str):
        check_app_env(app_env)
        check_aws_account(app_env)
        self.data_path = get_actual_path(app_env)
        self.app_env = app_env

    def run(self) -> None:
        for factory in STACKS_BY_ENV[self.app_env]:
            if factory.discover is not None:
                factory.discover(self.data_path)


def get_discovery_runner(app_env: str) -> DiscoveryRunner:
    check_app_env(app_env)
    return DiscoveryRunner(app_env=app_env)
```

**What's gone:** `DevDiscoveryRunner`, `StagingDiscoveryRunner`,
`ProductionDiscoveryRunner`, `DISCOVERY_MAP`.

---

## Module structure

`STACKS_BY_ENV` references both stack deploy logic (from `stack/`) and discovery
functions (from `config/discover.py`). To avoid a circular import, `STACKS_BY_ENV` lives
in a dedicated `config/registry.py` that both `inventory.py` and `config/discover.py`
import from:

```
config/registry.py     ← imports from stack/*.py and config/discover.py
                          defines StackFactory and STACKS_BY_ENV

config/inventory.py    ← imports STACKS_BY_ENV, StackFactory from config/registry.py
config/discover.py     ← imports STACKS_BY_ENV, StackFactory from config/registry.py
                          does NOT import from inventory.py
```

---

## Pipeline integration

The make targets map directly to CI pipeline steps. Discovery is an explicit step before
diff so that:
- failures are attributable to the right step
- discovery does not re-run on deploy (the config files already reflect the current
  external state)

```
make discover app_env=<env>       # runs factory.discover() for every eligible stack
make cdk-diff-all app_env=<env>   # synthesizes and diffs — no AWS API calls for discovery
# approval gate
make cdk-deploy-all app_env=<env>
```

See `azure-pipelines.yml` in the repo root for a complete example.

---

## Graduation: promoting a stack to a higher environment

1. Add the factory entry to the target environment's list in `config/registry.py`:
   ```python
   STACKS_BY_ENV = {
       "dev":        [app_vpc, simple_asg("aaa"), debug],
       "staging":    [app_vpc, simple_asg("bbb"), debug],  # ← add here
       "production": [app_vpc, simple_asg("ccc")],
   }
   ```
2. Add config files under `config/<target_env>/<stack_type>/...`
3. Run `make unit-update_golden` to refresh golden files for the new environment

Nothing else changes. Discovery for the newly eligible stack runs automatically in the
next pipeline run.

---

## What gets removed

| Removed                                                          | Replaced by                           |
|------------------------------------------------------------------|---------------------------------------|
| `DevInventory`, `StagingInventory`, `ProductionInventory`        | `Inventory` base class alone          |
| `DevDiscoveryRunner`, `StagingDiscoveryRunner`, `ProductionDiscoveryRunner` | `DiscoveryRunner` base class alone |
| `INVENTORY_MAP`                                                  | `get_inventory` returns `Inventory`   |
| `DISCOVERY_MAP`                                                  | `get_discovery_runner` returns `DiscoveryRunner` |
| `SIMPLE_ASG_IDS_BY_ENV` in `template_defaults.json`             | `STACKS_BY_ENV` in `config/registry.py` |
