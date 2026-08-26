# 01: Add `config/registry.py` and extract standalone discovery functions

**What to build:** A new `config/registry.py` module that defines the `StackFactory`
dataclass and the `STACKS_BY_ENV` eligibility dict. This is the foundation everything
else depends on. After this ticket, the eligibility list is readable in one place.
All existing tests continue to pass because `Inventory` and `DiscoveryRunner` are not
yet changed.

To avoid a circular import (registry imports discover; discover will later import
registry), standalone discovery logic is extracted from `DiscoveryRunner` methods
into a new `config/discovery_functions.py` module. The registry imports from there.
`discover.py` is not changed in this ticket — the old `DiscoveryRunner` methods stay
intact alongside the new standalone functions.

**Blocked by:** None (can start immediately)

**Status:** ready-for-agent

- [ ] New `config/discovery_functions.py` contains a standalone `discover_simple_asg(data_path, stack_id)` function whose logic is extracted from `DiscoveryRunner.discover_simple_asg_setting` / `update_simple_asg`. The existing `DiscoveryRunner` methods in `discover.py` are left in place (they are removed in ticket 04).
- [ ] New `config/registry.py` defines the `StackFactory` dataclass with two fields: `deploy: Callable` and `discover: Callable | None`.
- [ ] `config/registry.py` defines a module-level `app_vpc` constant (a `StackFactory` with `deploy` wired to `inv._deploy_app_vpc` and `discover=None`).
- [ ] `config/registry.py` defines a `simple_asg(stack_id: str) -> StackFactory` function that returns a `StackFactory` whose `deploy` calls `inv._deploy_simple_asg` and whose `discover` calls `discover_simple_asg` from `config/discovery_functions.py`.
- [ ] `config/registry.py` defines `STACKS_BY_ENV: dict[str, list[StackFactory]]` covering `dev`, `staging`, and `production` with the same stack instances currently declared via `SIMPLE_ASG_IDS_BY_ENV`.
- [ ] New `tests/unit/config/test_registry.py` (marked `unit`) asserts that `STACKS_BY_ENV` contains a key for every environment in `SUPPORTED_APP_ENVS`.
- [ ] `make unit-test` passes.
- [ ] `make pylint` passes.
- [ ] `make black-check` passes.
