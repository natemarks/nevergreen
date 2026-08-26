# Refactor Suggestions

The project is well-structured. The core patterns — typed settings dataclasses, per-environment config directories, golden file testing, and inventory-driven deployment — are all solid and work together cleanly. Here are the issues found, ranked by impact.

---

## 1. Empty environment subclasses should be eliminated — **RESOLVED**

**Resolved in `refactor` branch.** The `StackFactory` + `STACKS_BY_ENV` registry pattern replaced all three subclasses in both `inventory.py` and `discover.py`. Adding a new environment now requires only `config/template_defaults.json` and the environment config directory — no code changes needed. See `config/registry.py` and `STACK_MANAGEMENT_DESIGN.md`.

---

## 2. `get_logger` accumulates duplicate handlers — **RESOLVED**

**Resolved in `refactor` branch.** Added `if not my_logger.handlers:` guard in `config/helper.py` before `addHandler()`, preventing duplicate handlers on repeated calls with the same module name.

---

## 3. `unique_stacks["app_vpc"]` magic string is a silent failure point — **RESOLVED**

**Resolved in `refactor` branch.** The `unique_stacks` dict was replaced by `_deployed: dict[str, Stack]` with a typed `_get_deployed(stack_name)` accessor in `Inventory`. The magic string `"app_vpc"` is gone; the AppVpc stack is retrieved by its computed CDK stack name, derived deterministically from `APP_NAME` + environment prefix + `"AppVpcStack"`.

---

## 4. `INVENTORY_MAP` has no coverage validation — **RESOLVED**

**Resolved in `refactor` branch.** `INVENTORY_MAP` was deleted along with the environment subclasses. `config/registry.py` validates at module load that every `SUPPORTED_APP_ENVS` entry has a corresponding `STACKS_BY_ENV` entry, raising `RuntimeError` at startup if any is missing.

---

## 5. `APP_ENVS` in test `_shared.py` duplicates `SUPPORTED_APP_ENVS` — **RESOLVED**

**Resolved in `refactor` branch.** `_shared.py` now imports `SUPPORTED_APP_ENVS as APP_ENVS` from `config.project` instead of hardcoding the tuple. Test coverage for new environments is automatic once `template_defaults.json` is updated.

---

## 6. Golden file `FileNotFoundError` gives no guidance — **RESOLVED**

**Resolved in `refactor` branch.** `tests/helper.py` now includes `"Run 'make unit-update_golden' to generate it."` in the `FileNotFoundError` message.

---

## 7. `EnvironmentSetting` is loaded N+2 times per deploy — **RESOLVED**

**Resolved in `refactor` branch.** Both `AppVpcInput.from_config_directory` and `SimpleAsgInput.from_config_directory` now accept an optional `env_setting` parameter. `Inventory._deploy_app_vpc` and `_deploy_simple_asg` pass `self.environment_setting`, so the setting is loaded once per deploy regardless of stack count.

---

## 8. Makefile CDK targets repeat 5 lines of boilerplate — **RESOLVED**

**Resolved in `refactor` branch.** Added `SHELL_PREAMBLE` as a single-line variable holding the pyenv + activate sequence. All `cdk-*` and `discover` targets now expand `$(SHELL_PREAMBLE)` inside their subshell instead of repeating the 4-line block.

---

## Summary

| # | Issue | File | Impact | Status |
|---|-------|------|--------|--------|
| 1 | Empty env subclasses force multi-file changes per new env | `inventory.py`, `discover.py` | High — extensibility | ✅ Resolved |
| 2 | Duplicate `get_logger` handlers cause doubled log output | `config/helper.py:37` | Correctness | ✅ Resolved |
| 3 | Magic string `"app_vpc"` dict key is a silent failure point | `inventory.py` | Reliability | ✅ Resolved |
| 4 | `INVENTORY_MAP` has no coverage assertion | `inventory.py` | Safety | ✅ Resolved |
| 5 | `APP_ENVS` in tests is a duplicate of `SUPPORTED_APP_ENVS` | `tests/unit/config/settings/_shared.py:12` | Correctness | ✅ Resolved |
| 6 | Golden file missing gives no `--update_golden` hint | `tests/helper.py:59` | DX for template users | ✅ Resolved |
| 7 | `EnvironmentSetting` loaded N+2 times per deploy | `inventory.py`, `stack/` | Minor hygiene | ✅ Resolved |
| 8 | CDK Makefile targets repeat 5-line boilerplate | `Makefile` | Minor cleanup | ✅ Resolved |
