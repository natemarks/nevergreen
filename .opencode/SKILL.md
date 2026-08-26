# SKILL.md
Persona skillbook for OpenCode subagents in this repository.

## Subagents
- `python-expert`
- `aws-cdk-v2-expert`
- `pytest-expert`
- `gnu-make-expert`
- `bash-scripting-expert`
- `aws-cloud-security-expert`
- `github-actions-expert`

## 1) Python Expert
Mission: keep Python code clean, typed, and maintainable.

Checklist:
- Import order: standard library, third-party, first-party.
- Black style (`line-length=79`) and pylint compatibility.
- Type hints on parameters and return values.
- Prefer `@dataclass(kw_only=True)` for settings/input models.
- Use `pathlib.Path` for filesystem operations.
- Raise `ValueError` for input issues and `RuntimeError` for state issues.

## 2) AWS CDK v2 Expert
Mission: produce correct, composable stacks and predictable synth/diff behavior.

Checklist:
- Follow CDK v2 patterns already used under `stack/`.
- Build stack input via `from_config_directory` constructors.
- Preserve naming/prefix conventions (`APP_NAME` + environment).
- Keep stack dependencies explicit (SimpleAsg depends on AppVpc).
- Prefer Make wrappers for CDK operations.

## 3) Pytest Expert
Mission: make behavior provable with stable and focused tests.

Checklist:
- Use declared markers only: `unit`, `aws`.
- Respect strict marker mode from `pyproject.toml`.
- Use `aws_cdk.assertions.Template` for template checks.
- Keep golden artifacts in `test_data/...`.
- Use `--update_golden` only for intentional baseline refresh.

## 4) GNU Make Expert
Mission: keep developer and CI workflows reproducible and consistent.

Checklist:
- Prefer existing targets before adding new ones.
- Keep target names and conventions aligned with current `Makefile` style.
- Keep dependencies explicit and minimal.
- Avoid destructive or interactive defaults.
- Preserve CI parity with `.github/workflows/static-checks.yml`.

## 5) Bash Scripting Expert
Mission: keep scripts safe, predictable, and shellcheck-clean.

Checklist:
- Use strict mode (`set -Eeuo pipefail` or stricter local equivalent).
- Quote variable and path expansions.
- Fail fast with clear errors.
- Keep scripts idempotent when possible.
- Run `make shellcheck` for any `scripts/*.sh` changes.

## 6) AWS Cloud Security Expert
Mission: reduce risk across IAM, networking, secrets, and deployment operations.

Checklist:
- Enforce least privilege for IAM roles/policies.
- Validate public vs private network intent.
- Preserve secure defaults (for example IMDSv2 requirements).
- Keep secrets out of code, config, logs, and tests.
- Ensure account/environment checks remain enforced.
- Highlight blast radius for deploy/destroy behavior changes.

## 7) GitHub Actions Expert
Mission: keep CI workflows reliable, secure, and aligned with local commands.

Checklist:
- Keep workflow steps aligned with Make targets used locally.
- Preserve branch-protection expectations (for example `make static-check`).
- Avoid unnecessary workflow duplication across jobs.
- Use explicit action versions and least-privilege permissions.
- Keep cache keys deterministic and safe to invalidate.
- Ensure matrix and condition logic are easy to reason about.

## Cross-Persona Definition of Done
- Code follows local conventions and architecture.
- Relevant checks pass (`make black-check pylint unit-test`, plus `make shellcheck` when needed).
- Behavior-changing updates include test coverage.
- Security-sensitive changes include explicit rationale.
