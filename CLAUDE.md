# CLAUDE.md

This project was bootstrapped from
[cdk-starter](https://github.com/natemarks/cdk-starter), a Python CDK template.
The registry/discovery/inventory pattern is already in place; this document
describes how to extend it and what working standards apply.

See `AGENTS.md` for build commands, code-style rules, and the working agreement.

---

## Design

### Registry: the single customization point

`config/registry.py` — specifically `STACKS_BY_ENV` — is the only file to edit
when adding a stack, adding an instance of an existing stack type, or graduating
a stack to a higher environment. Reading it answers "what does `cdk ls` show for
staging?"

Each entry is a `StackFactory`: a `deploy` callable and an optional `discover`
callable. `Inventory.deploy_stacks` calls each factory in list order; later
factories retrieve dependencies via `_get_deployed`.

**Unique stacks** (one per environment) become module-level constants.
**Multi-stacks** (many instances, each with its own config) become factory
function calls with a `stack_id`. **Graduation** — promoting a stack from dev to
staging or production — is one line: add the `StackFactory` to the target
environment's list and supply the config files for that environment.

### Discovery

`make discover app_env=<env>` calls each factory's `discover` callable and
writes updated JSON files under `config/<env>/`. Run before diff/deploy.

Add new standalone discovery functions in `config/discovery_functions.py` (not
in `discover.py`), then wire them into a `StackFactory` in `registry.py`.

### Stack inputs and config settings

Every stack is constructed from a typed `*Input` dataclass built by
`from_config_directory(data_path)`. Settings classes in `config/settings.py`
inherit `JsonSettingBase` and declare `RELATIVE_PATH_TEMPLATE`.

**Multi-stack** settings include a `stack_id` directory level:
`config/<env>/<type>/<stack_id>/<type>.json`.

### Account validation gotcha

`Inventory.__init__` and `DiscoveryRunner.__init__` call `check_aws_account`,
which makes an STS API call. Unit tests that construct either class must patch
`config.inventory.check_aws_account` (or `config.discover.check_aws_account`)
to a no-op.

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
npm install   # reads the pinned aws-cdk version from package.json
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

**Every new stack requires two test functions** in `tests/unit/stack/test_<name>.py`:

- **`test_<name>_actual`** — one `pytest.param` per real environment that has a
  config file (`config/<env>/`). Loads input via `get_actual_path(environment)`.
  These are environment contracts: a failure here means an unintended template
  change.
- **`test_<name>_custom`** — one `pytest.param` per config combination the actual
  environments do not exercise. Each case carries its own fixture config directory
  under `test_data/unit/stack/test_<name>/test_<name>_custom/<case>/`.

See `tests/unit/stack/test_secure_s3.py` for prior art on both functions.
Generate golden files for a new test file before the first commit:
```bash
source .venv/bin/activate
python3 -m pytest -v tests/unit/stack/test_<name>.py --update_golden
```

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

Update documentation when the project changes in ways a developer would need to
know:

- `README.md` — CDK usage examples and discovery explanation. Update when the
  command interface or discovery workflow changes.
- `DESIGN.md` — rationale and patterns. Update when an architectural pattern
  changes.
- `CONTEXT.md` — domain glossary. Update when a domain term is introduced or
  given a more precise meaning.

Update documentation to explain intent and constraints, not to describe what the
code does.
