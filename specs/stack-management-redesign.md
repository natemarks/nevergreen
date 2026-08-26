# Spec: Stack Management Redesign

**Status:** ready-for-agent  
**Labels:** enhancement

---

## Problem Statement

Developers using this template must edit three files — `config/inventory.py`,
`config/discover.py`, and `config/template_defaults.json` — to add a new environment.
Two of those three edits are mechanical: adding an empty subclass and a map entry that
carry no logic beyond what the config already provides. The same duplication affects
promoting a stack to a new environment. There is no single place to look at to answer
"what stacks deploy in staging?" — the answer is scattered across parallel class
hierarchies in two files. The pattern forces template users to understand and maintain
two parallel structures that should be one.

---

## Solution

Replace the per-environment subclass pattern in `inventory.py` and `discover.py` with a
single `STACKS_BY_ENV` dict of `StackFactory` objects defined in a new
`config/registry.py` module. This dict is the one authoritative place for three concerns:
what `cdk ls` shows per environment, what discovery runs before deployment, and what
changes when a stack graduates to a higher environment. Adding an environment requires
only `template_defaults.json` and a config directory. Promoting a stack requires only one
line in `STACKS_BY_ENV` and the corresponding config files.

---

## User Stories

1. As a template user adding a new environment, I want to touch only `template_defaults.json` and a config directory, so that I am not forced to make mechanical edits to Python files.

2. As a template user promoting a stack from dev to staging, I want to add one entry to `STACKS_BY_ENV` and supply the config files, so that I do not need to find and update a second parallel structure.

3. As a developer reading `STACKS_BY_ENV`, I want to see all three environments side by side in one dict, so that I can answer "what deploys in staging?" at a glance.

4. As a template user, I want discovery to run automatically for every stack that needs it in a given environment, so that I do not need to maintain a separate list of which stacks require discovery.

5. As a template user, I want a new stack type to be eligible only in dev by default, so that work-in-progress stacks do not appear in higher environments until I promote them.

6. As a CI/CD pipeline author, I want `make discover app_env=<env>` to update config for exactly the eligible stacks in that environment, so that I can run it as a self-contained step without knowing each stack's external dependencies.

7. As a pipeline operator, I want to see `cdk diff` output after discovery and before deploying, so that I can approve or reject the specific changes that will be applied.

8. As a pipeline operator, I want an explicit approval gate between diff and deploy for each environment, so that no environment is deployed without human sign-off.

9. As a pipeline operator, I want each environment stage to use its own set of AWS credentials, so that a misconfiguration in one environment cannot affect another.

10. As a developer adding a multi-stack type (e.g. VPC peering connections), I want to declare multiple named instances of the same stack type in `STACKS_BY_ENV`, so that each instance gets its own config directory and appears as a separate CDK stack.

11. As a developer adding a unique stack type (e.g. a shared RDS cluster), I want to declare it once in `STACKS_BY_ENV` per environment, so that it behaves consistently with multi-stack types.

12. As a developer, I want the deployment order within an environment to be expressed by the order of entries in `STACKS_BY_ENV`, so that stack dependencies are visible and auditable without reading method bodies.

13. As a developer, I want a clear runtime error if a factory tries to access a stack that has not yet been deployed, so that dependency ordering mistakes surface immediately.

14. As a developer writing tests, I want to mock AWS account validation so that `Inventory` and `DiscoveryRunner` are constructible in unit tests without AWS credentials.

15. As a template maintainer, I want a test that asserts `STACKS_BY_ENV` covers every environment in `SUPPORTED_APP_ENVS`, so that a new environment added to `template_defaults.json` cannot be silently missed.

---

## Implementation Decisions

### New type: `StackFactory`

A dataclass with two fields:

- `deploy`: a callable `(inv, app, cdk_env) -> Stack`. Called by `Inventory.deploy_stacks`; returns the Stack so it can be registered for dependency access.
- `discover`: an optional callable `(data_path) -> None`. Called by `DiscoveryRunner.run`; `None` means no external data is needed before synthesis.

### Module: `config/registry.py`

New module that owns `StackFactory` and `STACKS_BY_ENV`. Both `inventory.py` and
`discover.py` import from it. Neither imports the other. This avoids a circular import
that would arise if `STACKS_BY_ENV` (which references discovery functions) lived in
`inventory.py` and `discover.py` needed to import it.

### `STACKS_BY_ENV` shape

A `dict[str, list[StackFactory]]` keyed by `app_env`. Each value is an ordered list; list
order is deployment order. Unique stacks appear as module-level `StackFactory` constants.
Multi stacks appear as calls to a factory function (e.g. `simple_asg("aaa")`) that bind
the `stack_id` into the deploy and discover closures. Multiple calls to the same factory
function with different IDs produce independent instances.

### Updated `Inventory` class

- No subclasses. No `INVENTORY_MAP`.
- Constructor: validates environment and account, loads `EnvironmentSetting`, initialises an empty `_deployed` registry.
- `deploy_stacks`: iterates `STACKS_BY_ENV[app_env]`, calls `factory.deploy`, registers each returned stack in `_deployed` by stack name.
- `_get_deployed(stack_name)`: returns a previously deployed stack or raises `RuntimeError` with a message naming the out-of-order factory.
- Private deploy methods (e.g. `_deploy_app_vpc`, `_deploy_simple_asg`) are called from factory lambdas via the `inv` reference.
- `get_inventory` is a plain function that validates the environment and returns `Inventory(app_env)`.

### Updated `DiscoveryRunner` class

- No subclasses. No `DISCOVERY_MAP`.
- Constructor: validates environment and account, stores `data_path` and `app_env`.
- `run`: iterates `STACKS_BY_ENV[app_env]`, calls `factory.discover(data_path)` for each factory where `discover` is not `None`.
- Structurally mirrors `Inventory` — same constructor contract, single action method.
- `get_discovery_runner` is a plain function that validates the environment and returns `DiscoveryRunner(app_env)`.

### Removal of `SIMPLE_ASG_IDS_BY_ENV` from `template_defaults.json`

The per-environment stack instance lists move from JSON config into `STACKS_BY_ENV` in
Python. The `simple_asg_ids_by_env` key is removed from `template_defaults.json` and the
corresponding loader in `config/project.py` is removed.

### `TERMINATION_PROTECTION`

Currently `False` on the base `Inventory` class and not overridden by any subclass. It
stays as a class constant on `Inventory` for now. If per-environment values are needed in
future, the pattern is to add a `termination_protection_by_env` map to
`template_defaults.json` and load it in `project.py`.

### Pipeline integration

- `make discover app_env=<env>` runs `DiscoveryRunner.run` for the environment; no other changes needed.
- `make cdk-diff-all` and `make cdk-deploy-all` are unchanged.
- In CI, `make .venv` and `make node_modules` are bypassed because they depend on pyenv and trigger `clean-venv`. Instead the pipeline installs CDK via `npm install aws-cdk@<version>` and creates the venv directly with `python -m venv`.

---

## Testing Decisions

Good tests verify external behaviour through the narrowest interface, not implementation
details. Tests should not assert on private method calls or internal data structures.

### What makes a good test for this change

- Test what `cdk ls` would show (the set of stacks added to the CDK App), not how they were added.
- Test that discovery callables are invoked for the right factories, not how `run` iterates.
- Do not assert on `_deployed` directly — assert on the deployed stack names via the CDK App.

### Seam 1 — `STACKS_BY_ENV` coverage (new, unit)

Location: `tests/unit/config/test_registry.py`

Assert that every environment in `SUPPORTED_APP_ENVS` has an entry in `STACKS_BY_ENV`.
This is a structural sanity test, not a behaviour test. Prior art: the startup assertions
in `config/project.py` that validate `APP_ENV_TO_AWS_ACCOUNT` coverage.

### Seam 2 — `Inventory` dispatch (new, unit)

Location: `tests/unit/config/test_inventory.py`

For each environment, construct an `Inventory` (with `check_aws_account` monkeypatched
to a no-op), call `deploy_stacks` against a real CDK `App`, and assert that the names
of the stacks in `app.node.children` match the expected set for that environment.
Prior art: `test_app_vpc.py` and `test_simple_asg.py` which construct stacks against a
real CDK `App` using `cdk.assertions.Template`.

### Seam 3 — `DiscoveryRunner` dispatch (new, unit)

Location: `tests/unit/config/test_discovery_runner.py`

Construct a `DiscoveryRunner` (with `check_aws_account` monkeypatched) and provide a
test-controlled `STACKS_BY_ENV` that mixes factories with and without `discover`
callables. Assert that only the factories with `discover` had their callable invoked.
Prior art: none — this is the first direct test of the discovery dispatch.

### Seam 4 — Stack template golden tests (existing, unchanged)

`tests/unit/stack/test_app_vpc.py` and `tests/unit/stack/test_simple_asg.py` continue
to test stack template correctness in isolation by constructing stacks directly from Input
classes. No changes to these tests are required.

---

## Out of Scope

- Changes to individual stack modules (`stack/app_vpc.py`, `stack/simple_asg.py`)
- Changes to the config JSON file structure under `config/<env>/`
- Changes to `config/settings.py` or the `JsonSettingBase` loading pattern
- Changes to `app.py`
- Implementation of the ADO pipeline (`azure-pipelines.yml` is provided as an example but wiring it into an actual ADO project is not part of this spec)
- Adding a `venv-ci` Makefile target (flagged as a follow-on improvement)
- Moving `TERMINATION_PROTECTION` to config (no environments currently override it)

---

## Further Notes

- The `check_aws_account` guard makes an STS API call during `Inventory.__init__` and
  `DiscoveryRunner.__init__`. Tests that construct these classes must patch it. Using
  `unittest.mock.patch("config.helper.check_aws_account")` or pytest `monkeypatch` at the
  module level is the standard approach.

- `config/registry.py` is the correct file for template users to edit when adding a new
  stack type or promoting a stack. This should be clearly documented in `CUSTOMIZE.md`.

- The full design including annotated code sketches is in `STACK_MANAGEMENT_DESIGN.md`.
  The ADO pipeline example is in `azure-pipelines.yml`.
