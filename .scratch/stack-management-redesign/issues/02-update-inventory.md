# 02: Update `Inventory` to use `STACKS_BY_ENV`

**What to build:** Replace the per-environment `Inventory` subclasses with a single
`Inventory` base class that iterates `STACKS_BY_ENV` from `config/registry.py`.
After this ticket, `cdk ls app_env=dev` shows exactly the stacks listed in
`STACKS_BY_ENV["dev"]`. `DevInventory`, `StagingInventory`, `ProductionInventory`,
and `INVENTORY_MAP` are gone. The new `_deployed` registry lets factory lambdas
access previously deployed stacks to satisfy dependencies.

**Blocked by:** 01 — Add `config/registry.py` and extract standalone discovery functions

**Status:** ready-for-agent

- [ ] `Inventory.__init__` imports `STACKS_BY_ENV` from `config/registry.py` and initialises an empty `_deployed: dict[str, Stack]` registry.
- [ ] `Inventory.deploy_stacks` iterates `STACKS_BY_ENV[self.app_env]`, calls `factory.deploy(self, app, cdk_env)` for each factory, and stores the returned stack in `_deployed` keyed by `stack.stack_name`.
- [ ] `Inventory._get_deployed(stack_name: str)` returns the named stack from `_deployed` or raises `RuntimeError` naming the missing stack and advising the caller to check list order in `STACKS_BY_ENV`.
- [ ] `Inventory._deploy_app_vpc(app, cdk_env)` creates and returns an `AppVpcStack` from the environment config directory.
- [ ] `Inventory._deploy_simple_asg(app, cdk_env, stack_id)` retrieves the AppVpc stack via `_get_deployed`, creates and returns a `SimpleAsgStack`.
- [ ] `DevInventory`, `StagingInventory`, `ProductionInventory`, and `INVENTORY_MAP` are removed from `inventory.py`.
- [ ] `get_inventory(app_env)` validates the environment via `check_app_env` and returns `Inventory(app_env)` directly.
- [ ] New `tests/unit/config/test_inventory.py` (marked `unit`). For each environment, it constructs an `Inventory` with `check_aws_account` patched to a no-op, calls `deploy_stacks` against a real CDK `App`, and asserts that the set of child stack names on the app matches the expected set for that environment. Prior art: `tests/unit/stack/test_app_vpc.py` for how to construct a CDK App and stacks in tests.
- [ ] All existing golden template tests (`make unit-test`) continue to pass.
- [ ] `make pylint` passes.
- [ ] `make black-check` passes.
