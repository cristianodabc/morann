# Contributing to Morann

Small, focused changes are the easiest to review and to merge.

## Before you start

- For a bug, open an issue with the steps to reproduce it. For a feature, open an issue first so the design can be
  agreed before you write code.
- A security problem goes through the private form described in [SECURITY.md](SECURITY.md), never a public issue.
- By contributing you agree that your contribution is licensed under the Apache License 2.0, the license of the
  project. Everyone taking part follows the [Code of Conduct](CODE_OF_CONDUCT.md).

## Set up

You need Python 3.11 or newer and `make`.

```sh
git clone https://github.com/cristianodabc/morann
cd morann
make setup
```

That builds `.venv` from `requirements.txt` and `requirements-dev.txt`: exact versions, hashes required, wheels
only. To run your checkout: `MORANN_PYTHON=.venv/bin/python bin/mor --owner my-org`.

## Check your change

```sh
make check
```

It runs what CI runs, and each part is its own target:

| Target | What it runs |
| --- | --- |
| `make lint` | ruff: lint rules and formatting |
| `make types` | mypy in strict mode |
| `make test` | pytest with the coverage gate |
| `make shell` | ShellCheck and shfmt on the shell scripts |
| `make workflows` | actionlint on the GitHub Actions workflows |
| `make security` | bandit on the package |
| `make audit` | pip-audit on both locks |
| `make secrets` | gitleaks over the history |
| `make build` | builds the sdist and the wheel, installs the wheel and runs `mor --help` |

`make format` rewrites the code in the project's style. ShellCheck, shfmt, actionlint and gitleaks are separate
programs: a missing one is skipped with a line saying so, and CI runs them all. To run the quick checks before each
commit, install [pre-commit](https://pre-commit.com/) and run `pre-commit install`.

The tests are in `tests/`. They run with a throwaway home and a fake `gh` first on `PATH` (`tests/fake_gh.py`),
so they never read your drafts and never call a forge. The UI tests drive the app with Textual's pilot, which is
why the whole suite takes a few minutes; `make test PYTEST_ARGS="-n auto"` runs it on every core. Run one file or
one test with `.venv/bin/python -m pytest tests/test_drafts.py -k damaged`.

The Textual screen modules (`app`, `widgets`, `vimkeys` and `main_*`) are not fully annotated yet, so mypy checks
them only where a function is annotated. `pyproject.toml` lists them. Every other module is checked in strict
mode, and a module leaves the list once it is annotated.

## What a good change looks like

- **It has a test.** New behavior comes with a test that failed before the change. Test what a user or a caller
  can observe, not private structure. The coverage gate in `pyproject.toml` only goes up.
- **It never posts by itself.** Anything that writes to a forge goes through a plan the user confirmed, checks that
  plan's fingerprint and reads the pull request again before sending.
- **It stays small.** Modules are split by responsibility and stay under 1,000 lines. Public modules and functions
  have a docstring that says what they are for. Comments explain why, not what the next line does.
- **It is written in US English**, in code, comments, messages and documentation.
- **Its dependencies are pinned.** `requirements.txt` holds what Morann runs with and `requirements-dev.txt` the
  tools, both as exact versions with hashes; the header of `requirements-dev.txt` has the command that resolves
  it. Raise a pin only after reviewing the new version, and say in the pull request what you reviewed. Actions in
  the workflows are pinned to a commit.

## Commits and pull requests

- Write commit messages as [Conventional Commits](https://www.conventionalcommits.org/): `type(scope): summary` in
  the imperative, for example `fix(diff): keep the cursor on its row after a refresh`.
- Keep one topic per pull request and fill in the template: what, why, and how you checked it.
- Add user-facing changes to `CHANGELOG.md` under Unreleased.
