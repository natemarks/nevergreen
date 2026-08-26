# Customize

This repository is intended to be used as a **GitHub Template Repository**.
Use this guide to create a new project quickly and get to a passing test suite.

## 1) Maintainer setup (one time)

In this repository on GitHub:
- `Settings` -> `General` -> `Template repository` -> enable.

After that, consumers can use `Use this template` from the repo page.

## 2) Create a new project from the template

From GitHub UI:
- Click `Use this template`.
- Choose owner, repository name, and visibility.
- Clone the new repository locally.

Example:

```console
git clone git@github.com:<your-org>/<your-repo>.git
cd <your-repo>
```

## 3) Install prerequisites

You need:
- Python `3.12.13` (managed with `pyenv` in this project)
- `pyenv`
- `python3-venv` support
- Node.js + `npm`
- AWS CDK CLI dependency is installed via `make node_modules`

Sanity check commands:

```console
python3 --version
pyenv --version
npm --version
```

## 4) Bootstrap local tooling

```console
make .venv
make node_modules
```

This creates `.venv/` and installs both Python and CDK Node dependencies.

## 5) Update template-specific project settings

Replace the template CLAUDE.md with the project-specific version:

```console
mv CLAUDE.template.md CLAUDE.md
```

Primary customization file:
- `config/template_defaults.json`

Update at minimum:
- `app_name`
- `iac_project_url`
- `app_env_to_aws_account`

Then update per-environment settings:
- `config/dev/environment.json`
- `config/staging/environment.json`
- `config/production/environment.json`

Common fields to change in each environment JSON:
- `aws_account_name`
- `aws_account_number`
- `default_region`
- `default_fqdn`
- optionally `admin_team`, `is_release`

### Managing which stacks deploy per environment

`config/registry.py` is the single file to edit for all stack eligibility changes:

- **Add a new stack type** — implement a deploy function in a new `stack/` module,
  add a `StackFactory` constant or factory function in `registry.py`, then add it
  to the `STACKS_BY_ENV` lists for the environments where it should deploy.
- **Add a new stack instance** (multi-stack) — call the factory function with a new
  `stack_id` and append it to the appropriate environment list(s). Add the
  corresponding config files under `config/<env>/` before deploying.
- **Graduate a stack to a higher environment** — add its `StackFactory` to the target
  environment's list in `STACKS_BY_ENV`. Ensure config files exist for that env.

## 6) Get the new project running

Run validation in this order:

```console
make black-check
make pylint
make unit-test
```

If tests fail because names/prefixes changed (expected for template adoption):

```console
make unit-update_golden
make unit-test
```

Goal: unit tests pass in the new repository.

## 7) Optional: refresh discovered config data

If you use discovery-managed values (like AMI IDs):

```console
make discover app_env=dev
```

Review and commit changed config files under `config/<env>/...`.

## 8) First commit checklist for template consumers

- `config/template_defaults.json` matches your project
- `config/*/environment.json` matches your accounts/regions/domains
- `make unit-test` passes
- any intentional golden changes are committed
