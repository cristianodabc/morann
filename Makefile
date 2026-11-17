# SPDX-FileCopyrightText: 2026 Cristiano Carvalho
# SPDX-License-Identifier: Apache-2.0
# The checks, one target each. `make check` runs all of them and is what CI runs, job by job.
#
#   make setup    build .venv from the two locks (exact versions, hashes required)
#   make check    everything below
#   make format   rewrite the code and the shell scripts in the project's style
#   make test PYTEST_ARGS="-n auto"    the tests on every core, a few times faster
#
# The Python tools come from .venv when it exists, else from the python3 on PATH. ShellCheck, shfmt, actionlint and
# gitleaks are separate programs: outside CI a missing one is skipped with a line saying so.

PYTHON ?= $(if $(wildcard .venv/bin/python),.venv/bin/python,python3)
PYTEST_ARGS ?=
SHELL_FILES := bin/mor install.sh
SHFMT := shfmt -i 2 -ci
LOCKS := -r requirements.txt -r requirements-dev.txt

# $(call optional,PROGRAM,COMMAND): run COMMAND when PROGRAM is installed. In CI it has to be.
define optional
	@if command -v $(1) >/dev/null 2>&1; then $(2) && echo "$(1): ok"; \
	elif [ -n "$$CI" ]; then echo "$(1) is not installed" >&2; exit 1; \
	else echo "$(1): skipped, not installed"; fi
endef

.PHONY: check setup format lint types test shell workflows security audit secrets staged-secrets build sbom clean

check: lint types test shell workflows security audit secrets build

setup:
	python3 -m venv .venv
	.venv/bin/python -m pip install --quiet --disable-pip-version-check --require-hashes --only-binary :all: $(LOCKS)

format:
	$(PYTHON) -m ruff check --fix .
	$(PYTHON) -m ruff format .
	$(call optional,shfmt,$(SHFMT) -w $(SHELL_FILES))

lint:
	$(PYTHON) -m ruff check .
	$(PYTHON) -m ruff format --check .

types:
	$(PYTHON) -m mypy

test:
	$(PYTHON) -m pytest --cov --cov-report=term --cov-report=xml $(PYTEST_ARGS)

shell:
	$(call optional,shellcheck,shellcheck $(SHELL_FILES))
	$(call optional,shfmt,$(SHFMT) -d $(SHELL_FILES))

workflows:
	$(call optional,actionlint,actionlint)

security:
	$(PYTHON) -m bandit --quiet --recursive src --configfile pyproject.toml

audit:
	$(PYTHON) -m pip_audit --require-hashes --disable-pip --progress-spinner off $(LOCKS)

secrets:
	$(call optional,gitleaks,gitleaks git --no-banner --redact .)

# What is staged for the next commit, for the pre-commit hook.
staged-secrets:
	$(call optional,gitleaks,gitleaks git --pre-commit --staged --no-banner --redact .)

build:
	rm -rf dist
	$(PYTHON) -m build --outdir dist
	$(PYTHON) -m venv --clear build/wheel-check
	build/wheel-check/bin/python -m pip install --quiet --disable-pip-version-check --require-hashes --only-binary :all: -r requirements.txt
	build/wheel-check/bin/python -m pip install --quiet --disable-pip-version-check --no-deps dist/*.whl
	build/wheel-check/bin/mor --help >/dev/null
	build/wheel-check/bin/mor --version

# A CycloneDX list of what requirements.txt pins, next to the built files.
sbom:
	mkdir -p dist
	$(PYTHON) -m pip_audit --require-hashes --disable-pip --progress-spinner off -r requirements.txt \
		--format cyclonedx-json --output dist/morann.cdx.json

clean:
	rm -rf .venv build dist .coverage coverage.xml .mypy_cache .pytest_cache .ruff_cache
