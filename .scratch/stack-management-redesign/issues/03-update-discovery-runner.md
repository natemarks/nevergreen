# 03: Update `DiscoveryRunner` to use `STACKS_BY_ENV`

**What to build:** Replace the per-environment `DiscoveryRunner` subclasses with a
single `DiscoveryRunner` base class that iterates `STACKS_BY_ENV` from
`config/registry.py`. After this ticket, `make discover app_env=dev` runs the
`discover` callable for every eligible stack that has one and skips those that don't.
`DevDiscoveryRunner`, `StagingDiscoveryRunner`, `ProductionDiscoveryRunner`, and
`DISCOVERY_MAP` are gone.

This ticket can be worked in parallel with ticket 02.

**Blocked by:** 01 — Add `config/registry.py` and extract standalone discovery functions

**Status:** ready-for-agent

- [ ] `DiscoveryRunner.__init__` imports `STACKS_BY_ENV` from `config/registry.py`. Constructor signature and validation (`check_app_env`, `check_aws_account`) are unchanged.
- [ ] `DiscoveryRunner.run` iterates `STACKS_BY_ENV[self.app_env]` and calls `factory.discover(self.data_path)` for each factory where `discover` is not `None`. Skips factories with `discover=None` silently.
- [ ] `DevDiscoveryRunner`, `StagingDiscoveryRunner`, `ProductionDiscoveryRunner`, and `DISCOVERY_MAP` are removed from `discover.py`.
- [ ] `get_discovery_runner(app_env)` validates the environment via `check_app_env` and returns `DiscoveryRunner(app_env)` directly.
- [ ] The existing `discover_simple_asg_setting` and `update_simple_asg` methods on `DiscoveryRunner` are removed; the logic now lives in `config/discovery_functions.py` (added in ticket 01) and is invoked via the `StackFactory.discover` callable.
- [ ] New `tests/unit/config/test_discovery_runner.py` (marked `unit`). Constructs a `DiscoveryRunner` with `check_aws_account` patched to a no-op and a test-local list of mock `StackFactory` objects (some with `discover` set to a `MagicMock`, some with `discover=None`). Asserts that only the factories with a non-None `discover` had their callable invoked, and that each was called with the expected `data_path`.
- [ ] `make unit-test` passes.
- [ ] `make pylint` passes.
- [ ] `make black-check` passes.
