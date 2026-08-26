# CLAUDE.md — cdk-starter

This is a **GitHub Template Repository**: its purpose is to be forked into new
Python CDK projects. The example stacks (`AppVpc`, `SimpleAsg`) are
illustrative — they demonstrate the patterns, not deliver production
infrastructure. A change that improves a pattern has higher value than one that
only touches an example stack.

See `AGENTS.md` for build commands, code-style rules, and the working agreement.

---

## Design

### Registry: the single customization point

`config/registry.py` — specifically `STACKS_BY_ENV` — is the only file a
developer edits to control what deploys in each environment, in what order, and
whether discovery runs before it. Reading that file answers "what does `cdk ls`
show for staging?"

Each entry is a `StackFactory`: a `deploy` callable that creates and returns the
Stack, and an optional `discover` callable that fetches external AWS data before
synthesis. `Inventory.deploy_stacks` calls each factory in list order and
registers the returned Stack in `_deployed` by name; later factories retrieve
dependencies via `_get_deployed`.

**Unique stacks** (one per environment) become module-level `StackFactory`
constants. **Multi-stacks** (many instances per environment, each with its own
config) become factory function calls with a `stack_id`
(e.g. `simple_asg("aaa")`).

**Graduation** — promoting a stack from dev to staging or production — is one
line: add the `StackFactory` to the target environment's list and supply the
config files for that environment.

### Discovery

`make discover app_env=<env>` runs `DiscoveryRunner.run()`, which calls each
factory's `discover` callable and skips `None`. The result is updated JSON files
under `config/<env>/`. Run discovery before diff/deploy so synthesized templates
reflect current external state.

Standalone discovery functions live in `config/discovery_functions.py`, not in
`discover.py`. This breaks a circular import: `registry.py` imports discovery
functions, and `discover.py` imports `STACKS_BY_ENV` from `registry.py`.

### Stack inputs and config settings

Every stack is constructed from a typed `*Input` dataclass built by
`from_config_directory(data_path)`. Settings classes in `config/settings.py`
inherit `JsonSettingBase` and declare `RELATIVE_PATH_TEMPLATE` to locate their
JSON files under `config/<env>/`.

**Multi-stack** settings include a `stack_id` directory level:
`config/<env>/<type>/<stack_id>/<type>.json`. The same stack class with
different `stack_id` values produces independently configurable instances.

### Account validation gotcha

`Inventory.__init__` and `DiscoveryRunner.__init__` call `check_aws_account`,
which makes an STS API call. Unit tests that construct either class must patch
`config.inventory.check_aws_account` (or `config.discover.check_aws_account`)
to a no-op. Forgetting this causes every inventory/runner construction to fail
outside an AWS session.

---

## Pipeline

The per-environment sequence:

```
make discover app_env=<env>
make cdk-diff-all app_env=<env>   # review before approving
make cdk-deploy-all app_env=<env>
```

Run dev → staging → production, each with its own AWS credentials. See
`azure-pipelines.yml` for an ADO example with approval gates.

**CI agents without pyenv:** bypass `make .venv` and `make node_modules`; they
call `pyenv` internally. Instead:

```bash
python -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt
npm install aws-cdk@$(CDK_VERSION)
```

---

## Working standards

**Make targets are the interface.** Use `make` targets for all build, test,
lint, and CDK operations. Reach for direct `pytest`, `pylint`, `black`, or
`cdk` invocations only when no target covers the case (e.g., running a single
test, or checking an untracked file before staging).

### `make static`

Run `make static` whenever code changes. It runs `shellcheck`, `black`
(reformats), `pylint`, and `unit-test`. Done means all four pass with no
unresolved output.

`make static-check` (used in CI) is identical but substitutes `black-check` for
`black` — it fails rather than reformats, protecting the branch.

**Untracked files are invisible to `git ls-files`** and therefore skipped by the
Make targets. Before staging a new Python file, run pylint and black on it
directly:

```bash
source .venv/bin/activate
pylint --max-line-length=90 <file>.py
black --check --line-length=79 <file>.py
```

Suppress pylint findings that cannot be fixed with an inline `# pylint: disable=<code>`
comment. Add a brief explanation when the reason is not obvious from context.

### Golden files

Golden files store expected CloudFormation templates. `test_*_actual` tests
compare synthesized output against them; a mismatch fails the test.

**Intentional template change** (you changed a stack module on purpose):
```bash
make unit-update_golden   # regenerate
make unit-test            # confirm pass
git diff                  # review before committing
```

**Unexpected failure:** do not run `unit-update_golden`. Read the diff in the
test output, trace what changed in the synthesized template back to the code
change that caused it, and fix the code.

### Documentation

Update documentation when the project changes in ways a template consumer would
need to know:

- `CUSTOMIZE.md` — adoption workflow. Update when the list of files to edit
  changes.
- `README.md` — CDK usage examples and discovery explanation. Update when the
  command interface or discovery workflow changes.
- `DESIGN.md` — rationale and patterns. Update when an architectural pattern
  changes.
- `CONTEXT.md` — domain glossary. Update when a domain term is introduced or
  given a more precise meaning.

Update documentation to explain intent and constraints, not to describe what the
code does.
