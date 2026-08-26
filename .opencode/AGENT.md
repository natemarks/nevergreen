# AGENT.md
Operational playbook for OpenCode agents in this repository.

## Purpose
Coordinate specialist subagents so changes are:
- correct for Python and AWS CDK v2,
- testable with pytest,
- reproducible with GNU Make,
- robust in Bash automation,
- reliable in GitHub Actions CI/CD,
- aligned with AWS cloud security best practices.

## Canonical References
- Repo standards and command catalog: `../AGENTS.md`
- Persona definitions and checklists: `SKILL.md`
- MCP setup for live docs: `MCP.md`
- Subagent files: `subagents/*.md`

## Subagent Configuration
Each persona is configured as a dedicated subagent document:

1. `subagents/python-expert.md`
2. `subagents/aws-cdk-v2-expert.md`
3. `subagents/pytest-expert.md`
4. `subagents/gnu-make-expert.md`
5. `subagents/bash-scripting-expert.md`
6. `subagents/aws-cloud-security-expert.md`
7. `subagents/github-actions-expert.md`

Use these subagents for non-trivial workstreams; combine findings in one final patch.

## Orchestration Workflow
1. Scope impacted areas (`config/`, `stack/`, `tests/`, `scripts/`, `Makefile`).
2. Route to relevant subagents by change type.
3. Merge recommendations into a minimal, focused implementation.
4. Run validation commands from `AGENTS.md`.
5. Perform security pass for IAM/network/secrets impacts.
6. Report what changed, what ran, and any residual risk.

## Quality Gates
- Python code: `make black-check pylint unit-test`
- Shell changes: include `make shellcheck`
- Golden updates: targeted pytest with `--update_golden` and diff review
- CDK-sensitive updates: run relevant `make cdk-diff` command when practical

## Done Criteria
- Requested behavior implemented.
- Relevant checks pass.
- Security-sensitive changes explicitly reviewed.
- Final summary includes commands run and tradeoffs.
