# AGENTS.md
Guide for autonomous coding agents working in this repository.

Companion files:
- `.opencode/AGENT.md`: orchestration workflow for specialist personas.
- `.opencode/SKILL.md`: persona-specific checklists (Python, CDK v2, pytest, Make, Bash, AWS security).

Note: `.opencode/` now includes a dedicated GitHub Actions subagent persona
(`.opencode/subagents/github-actions-expert.md`) for CI workflow changes.

## Project Snapshot
- Stack: AWS CDK app in Python.
- Entrypoint: `app.py`.
- Main locations: `config/`, `stack/`, `tests/`.
- CDK app command in `cdk.json`: `python3 app.py`.
- Tooling source of truth: `Makefile`, `pyproject.toml`, `requirements.txt`.

## Cursor / Copilot Rules
- No `.cursorrules` file found.
- No `.cursor/rules/` directory found.
- No `.github/copilot-instructions.md` found.
- If any appear later, treat them as highest-priority repo instructions.

## Environment Setup
- Python is configured via `pyenv` in Make targets.
- Expected Python version in `Makefile`: `3.12.13`.
- Virtual environment path: `.venv/`.
- CDK CLI dependency: Node package `aws-cdk`.

Bootstrap:
```bash
make .venv
make node_modules
```

## Build / Lint / Test Commands
Prefer `make` targets over ad-hoc commands.

Setup and dependencies:
```bash
make .venv
make clean-venv
make node_modules
make update_cdk_libs
```

Lint and formatting:
```bash
make black
make black-check
make pylint
make shellcheck
make static
make static-check
```

Test suites:
```bash
make unit-test
make aws-test
make unit-update_golden
make aws-update_golden
```

## Running a Single Test (Important)
There is no dedicated one-test make target; run pytest directly in `.venv`.

Single function:
```bash
source .venv/bin/activate
python3 -m pytest -v tests/unit/stack/test_app_vpc.py::test_app_vpc_stack_actual
```

Single parametrized case by ID:
```bash
source .venv/bin/activate
python3 -m pytest -v tests/unit/stack/test_simple_asg.py::test_simple_asg_stack_actual[dev]
```

Single test with marker + golden update:
```bash
source .venv/bin/activate
python3 -m pytest -v -m unit tests/unit/stack/test_simple_asg.py::test_simple_asg_stack_custom --update_golden
```

## CDK and Discovery Commands
Use Make wrappers instead of raw CDK invocations.
```bash
make cdk-ls app_env=dev
make cdk-diff app_env=dev stack=StarterDevAppVpcStack
make cdk-diff-all app_env=dev
make cdk-deploy app_env=dev stack=StarterDevAppVpcStack
make cdk-deploy-all app_env=dev
make cdk-destroy app_env=dev stack=StarterDevAppVpcStack
make cdk-bootstrap app_env=dev
make discover app_env=dev
```
`make discover` updates tracked config data (for example AMI IDs).

## Code Style Guidelines
Derived from existing code and enforced tooling.

### Formatting
- Run Black with line length 79 (`make black`).
- Keep pylint compatibility (`--max-line-length=90`).
- Use 4-space indentation; no tabs.
- Keep functions focused and readable.

### Imports
- Order imports as standard library, third-party, first-party.
- Avoid wildcard imports.
- Keep imports explicit and deterministic.
- In CDK files, alias service modules (example: `aws_ec2 as ec2`).

### Types and Dataclasses
- Add type hints for parameters and return values.
- Prefer dataclasses for settings and stack input payloads.
- Prefer `@dataclass(kw_only=True)`.
- Use `frozen=True` for immutable config objects unless mutation is needed.
- Use `pathlib.Path` for filesystem paths.
- Match existing typing style when editing nearby code.

### Naming
- Modules/files: `snake_case`.
- Functions/variables: `snake_case`.
- Classes: `PascalCase`.
- Constants: `UPPER_SNAKE_CASE`.
- Tests: `test_*.py` files and `test_*` function names.
- Parametrize IDs should be concise and stable.

### Error Handling and Validation
- Validate external inputs early (env names, account, config paths).
- Raise `ValueError` for invalid user/config input.
- Raise `RuntimeError` for invalid runtime state.
- Avoid silent fallbacks in account/environment-sensitive logic.
- Keep exception text specific and actionable.

### Logging
- Use shared helper `get_logger`.
- Keep INFO as default level unless there is a clear reason to change.
- Prefer logger placeholders (`%s`) over preformatted strings.

### Testing Conventions
- Use only declared pytest markers: `unit`, `aws`.
- Respect strict markers (`--strict-markers` in `pyproject.toml`).
- Golden test artifacts live in `test_data/...`.
- Use `--update_golden` only when intentionally refreshing expectations.
- CDK template checks should follow `aws_cdk.assertions.Template` patterns.

### CDK / Config Patterns
- Build stack inputs via `from_config_directory` constructors.
- Keep per-environment config under `config/<env>/...`.
- Preserve prefix/naming scheme based on `APP_NAME` + environment.
- Keep stack dependencies explicit (SimpleAsg depends on AppVpc).

## Agent Working Agreement
- Make minimal, focused diffs.
- Run relevant checks after edits (typically `make black-check pylint unit-test`).
- Include `make shellcheck` when touching `scripts/*.sh`.
- Do not edit generated `cdk.out/` files unless explicitly requested.
- Never commit secrets or credentials.

## CI Notes
- GitHub workflow `.github/workflows/static-checks.yml` runs `make static-check`.
- Keep local changes passing `make static-check` before opening a PR.
