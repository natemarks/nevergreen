# 04: Remove `SIMPLE_ASG_IDS_BY_ENV` and update dependents

**What to build:** Contract phase. Now that `Inventory` and `DiscoveryRunner` both use
`STACKS_BY_ENV`, `SIMPLE_ASG_IDS_BY_ENV` is orphaned. This ticket removes it from
`template_defaults.json` and `config/project.py`, updates the one test that imported
it, and updates `CUSTOMIZE.md` to point template users to `config/registry.py` as the
file to edit when adding or promoting a stack. After this ticket, `make static` passes
clean with no references to `SIMPLE_ASG_IDS_BY_ENV` anywhere.

**Blocked by:**
- 02 — Update `Inventory` to use `STACKS_BY_ENV`
- 03 — Update `DiscoveryRunner` to use `STACKS_BY_ENV`

**Status:** ready-for-agent

- [ ] `simple_asg_ids_by_env` key is removed from `config/template_defaults.json`.
- [ ] The `SIMPLE_ASG_IDS_BY_ENV` constant and its `_require_string_list_map` loader are removed from `config/project.py`.
- [ ] The startup validation loop in `config/project.py` that checked `app_env not in SIMPLE_ASG_IDS_BY_ENV` is removed.
- [ ] `tests/unit/stack/test_simple_asg.py` no longer imports `SIMPLE_ASG_IDS_BY_ENV`. The `test_simple_asg_stack_actual` parametrize list is replaced with explicit `pytest.param` entries (`("dev", "aaa")`, `("staging", "bbb")`, `("production", "ccc")`).
- [ ] `CUSTOMIZE.md` updated to direct template users to `config/registry.py` as the single file to edit when adding a new stack type, adding a new stack instance, or promoting a stack to a higher environment.
- [ ] `grep -r SIMPLE_ASG_IDS_BY_ENV .` (excluding `.git`) returns no matches.
- [ ] `make static` passes.
