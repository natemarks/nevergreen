.DEFAULT_GOAL := help

SHELL := $(shell which bash)
DEFAULT_BRANCH := main
VERSION := 0.0.0
COMMIT := $(shell git rev-parse HEAD)
CDK := node_modules/.bin/cdk

CURRENT_BRANCH := $(shell git rev-parse --abbrev-ref HEAD)
app_env := dev
PYTHON_VERSION := 3.12.13
CDK_VERSION := 2.70.0
SHELL_PREAMBLE = source scripts/enable_pyenv.sh; pyenv local $(PYTHON_VERSION); python --version; source .venv/bin/activate;

help: ## Show this help.
	@fgrep -h "##" $(MAKEFILE_LIST) | fgrep -v fgrep | sed -e 's/\\$$//' | sed -e 's/##//'

clean-venv: ## re-create virtual env
	[[ -e .venv ]] && rm -rf .venv; \
	( \
       source scripts/enable_pyenv.sh; \
       pyenv local $(PYTHON_VERSION); \
       python3 -m venv .venv; \
       source .venv/bin/activate; \
       pip install --upgrade pip setuptools; \
       pip install -r requirements.txt; \
    )

.venv: requirements.txt ## create/update venv if missing or requirements.txt changed
	( \
       source scripts/enable_pyenv.sh; \
       pyenv local $(PYTHON_VERSION); \
       python3 -m venv .venv; \
       source .venv/bin/activate; \
       pip install --upgrade pip setuptools; \
       pip install -r requirements.txt; \
    )
	touch .venv

update_cdk_libs: .venv ## install the latest version of aws cdk node and python packages
	bash scripts/update_cdk_libs.sh
	$(MAKE) clean-venv

black: .venv ## use black to format python files
	( \
       . .venv/bin/activate; \
       git ls-files '*.py' | xargs black --line-length=79; \
    )

black-check: .venv ## fail if there are formatting problems
	( \
       . .venv/bin/activate; \
       git ls-files '*.py' | xargs black --check --line-length=79; \
    )

pylint: .venv ## run pylint on python files
	( \
       . .venv/bin/activate; \
       git ls-files '*.py' | xargs pylint --max-line-length=90; \
    )

mypy: .venv ## type check python files
	( \
       . .venv/bin/activate; \
       python3 -m mypy $(shell git ls-files '*.py'); \
    )

shellcheck: ## check shell scripts
	git ls-files 'scripts/*.sh' | xargs shellcheck --severity=error --format=gcc

unit: .venv ## run tests with no external dependencies
	( \
       source .venv/bin/activate; \
       python3 -m pytest -v -m "unit" tests/; \
    )

unit-test: unit ## alias for unit (backward compat)

unit-update-golden: .venv ## update golden files with latest results
	( \
       source .venv/bin/activate; \
       python3 -m pytest -v -m "unit" tests/ --update_golden; \
    )

unit-update_golden: unit-update-golden ## alias for unit-update-golden (backward compat)

integration: .venv ## run tests that require aws credentials
	( \
       source .venv/bin/activate; \
       python3 -m pytest -v -m "aws" tests/; \
    )

aws-test: integration ## alias for integration (backward compat)

aws-update_golden: .venv ## update golden files with aws test results
	( \
       source .venv/bin/activate; \
       python3 -m pytest -v -m "aws" tests/ --update_golden; \
    )

static: shellcheck black mypy pylint unit ## run all static checks with auto-format

static-check: shellcheck black-check mypy pylint unit ## run all static checks (CI)

test-dependabot-pr: clean-venv ## test a Dependabot PR (install deps + run all checks)
	@echo "=== Installing npm packages from package.json ==="
	npm install
	@echo ""
	@echo "=== Running static checks ==="
	$(MAKE) static-check
	@echo ""
	@echo "✓ All checks passed!"
	@echo ""
	@echo "⚠️  REMINDER: For CDK updates, also check infrastructure changes:"
	@echo "   make cdk-diff-all"
	@echo ""
	@echo "If all looks good, merge the PR:"
	@echo "   gh pr merge <PR#> --squash"
	@echo ""

pre-commit-install: .venv ## install git pre-commit hooks
	( \
       source .venv/bin/activate; \
       pre-commit install; \
    )

clean-cache: ## clean python and pytest cache data
	@find . -type f -name "*.py[co]" -delete -not -path "./.venv/*"
	@find . -type d -name __pycache__ -not -path "./.venv/*" -exec rm -rf {} + 2>/dev/null || true
	@rm -rf .pytest_cache

git-status: ## require status is clean so we can use undo_edits to put things back
	@status=$$(git status --porcelain); \
	if [ ! -z "$${status}" ]; \
	then \
		echo "Error - working directory is dirty. Commit those changes!"; \
		exit 1; \
	fi

undo_edits: ## reset changes to HEAD
	git reset HEAD --hard
	git clean -f

node_modules: ## create node_modules/ if it doesn't exist
	bash scripts/update_cdk_libs.sh $(CDK_VERSION)
	$(MAKE) clean-venv

cdk-ls: node_modules .venv ## run cdk ls
	$(eval CDK := $(shell find . -type f -name cdk))
	( \
	   $(SHELL_PREAMBLE) \
	   $(CDK) ls -c app_env=$(app_env); \
	)

cdk-diff: node_modules .venv ## cdk diff a single stack
	$(eval CDK := $(shell find . -type f -name cdk))
	( \
	   $(SHELL_PREAMBLE) \
	   $(CDK) diff $(stack) -c app_env=$(app_env); \
	)

cdk-diff-all: node_modules .venv ## cdk diff all stacks in the environment
	$(eval CDK := $(shell find . -type f -name cdk))
	( \
	   $(SHELL_PREAMBLE) \
	   $(CDK) diff '*' -c app_env=$(app_env); \
	)

cdk-deploy: node_modules .venv ## cdk deploy a single stack
	$(eval CDK := $(shell find . -type f -name cdk))
	( \
	   $(SHELL_PREAMBLE) \
	   $(CDK) deploy --require-approval never $(stack) -c app_env=$(app_env); \
	)

cdk-deploy-all: node_modules .venv ## cdk deploy all stacks in an environment
	$(eval CDK := $(shell find . -type f -name cdk))
	( \
	   $(SHELL_PREAMBLE) \
	   $(CDK) deploy --all -c app_env=$(app_env); \
	)

cdk-destroy: node_modules .venv ## cdk destroy a single stack
	$(eval CDK := $(shell find . -type f -name cdk))
	( \
	   $(SHELL_PREAMBLE) \
	   $(CDK) destroy --force $(stack) -c app_env=$(app_env); \
	)

cdk-bootstrap: node_modules .venv ## bootstrap the default account and region for an environment
	$(eval CDK := $(shell find . -type f -name cdk))
	( \
	   $(SHELL_PREAMBLE) \
	   $(CDK) $(shell bash scripts/cdk_bootstrap.sh) -c app_env=$(app_env); \
	)

discover: .venv ## update environment config data with discovered information
	( \
	   $(SHELL_PREAMBLE) \
	   PYTHONPATH="." python3 -m config.discover $(app_env); \
	)

.PHONY: help clean-venv update_cdk_libs black black-check pylint mypy shellcheck unit unit-test unit-update-golden unit-update_golden integration aws-test aws-update_golden static static-check test-dependabot-pr pre-commit-install clean-cache git-status undo_edits node_modules cdk-ls cdk-diff cdk-diff-all cdk-deploy cdk-deploy-all cdk-destroy cdk-bootstrap discover
