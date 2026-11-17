# SPDX-FileCopyrightText: 2026 Cristiano Carvalho
# SPDX-License-Identifier: Apache-2.0
"""The command and its installer: mor --help and --version, the launcher finding its Python, and install.sh linking
the command from variables alone with an exactly pinned lock."""

import os
import subprocess
import sys
from pathlib import Path

import morann
from fake_github import FakeGitHub, fixture
from morann import cli, core
from morann.app import Morann
from support import MAIN, ROOT

LAUNCHER = ROOT / "bin/mor"
INSTALLER = ROOT / "install.sh"
USAGE = "mor [--owner OWNER]"


def run(command, env=None):
    return subprocess.run([str(part) for part in command], env=env, capture_output=True, text=True, check=False)


def clean_env(**extra):
    """The environment without any Morann setting, plus `extra`."""
    env = {key: value for key, value in os.environ.items() if not key.startswith("MORANN_")}
    return {**env, **extra}


def test_help_version_and_a_bad_argument():
    helped = run([sys.executable, "-B", MAIN, "--help"])
    assert helped.returncode == 0 and USAGE in helped.stdout
    versioned = run([sys.executable, "-B", MAIN, "--version"])
    assert versioned.returncode == 0 and versioned.stdout.strip() == f"mor {morann.__version__}", versioned.stdout
    bad = run([sys.executable, "-B", MAIN, "--repo", "nope"])
    assert bad.returncode == 2 and "not an OWNER/REPO" in bad.stderr


def test_the_command_starts_the_app_with_what_it_was_given(monkeypatch):
    started = []
    monkeypatch.setattr(Morann, "run", lambda app: started.append(app))
    with FakeGitHub(fixture()):
        assert cli.main(["--owner", "acme", "--read-only", "--icons", "nerd", "--theme", "Nord", "acme/app#7"]) == 0
    main = started[0].main
    assert main.scope == core.Scope(owners=("acme",)) and main.forge.read_only
    assert main.opening == ("acme/app", 7) and main.icons is core.NERD and started[0].start_theme == "nord"


def test_the_command_refuses_what_it_cannot_use(capsys):
    assert cli.main(["--owner", "acme", "not a pull request"]) == 2
    assert capsys.readouterr().err.startswith("mor: ")
    assert cli.main(["update", "--repo", "nope"]) == 2
    assert "not an OWNER/REPO" in capsys.readouterr().err
    with FakeGitHub(fixture()):
        assert cli.main(["--owner", "acme", "--theme", "plaid"]) == 2
    assert "no theme named 'plaid'; there are: terminal, " in capsys.readouterr().err


def test_the_launcher_says_how_to_install_a_missing_environment(tmp_path):
    env = clean_env(HOME=str(tmp_path), XDG_DATA_HOME="")
    missing = run(["bash", LAUNCHER], env)
    assert missing.returncode == 1 and f"{tmp_path}/.local/share/morann/venv/bin/python" in missing.stderr, (
        missing.stderr
    )
    assert f"run: {ROOT}/install.sh" in missing.stderr, missing.stderr


def test_the_data_folder_places_the_environment(tmp_path):
    env = clean_env(HOME=str(tmp_path), XDG_DATA_HOME="", MORANN_DATA_DIR=f"{tmp_path}/data")
    elsewhere = run(["bash", LAUNCHER], env)
    assert elsewhere.returncode == 1 and f"{tmp_path}/data/venv/bin/python" in elsewhere.stderr, elsewhere.stderr


def test_the_launcher_runs_through_a_link(tmp_path):
    link = tmp_path / "mor"
    link.symlink_to(LAUNCHER)
    env = clean_env(HOME=str(tmp_path), XDG_DATA_HOME="", MORANN_PYTHON=sys.executable)
    through_link = run([link, "--help"], env)
    assert through_link.returncode == 0 and USAGE in through_link.stdout, through_link.stderr
    assert through_link.stderr == "", through_link.stderr


def test_the_installer_links_the_command_from_the_variables(tmp_path):
    bin_dir, data = tmp_path / "bin", tmp_path / "data"
    env = clean_env(HOME=str(tmp_path), MORANN_BIN_DIR=str(bin_dir), MORANN_DATA_DIR=str(data), MORANN_SKIP_VENV="1")
    done = run(["bash", INSTALLER], env)
    assert done.returncode == 0, done.stderr
    link = bin_dir / "mor"
    assert link.is_symlink() and Path(os.readlink(link)) == LAUNCHER
    assert "Skipping the Morann Python environment" in done.stdout and not data.exists()
    assert not (tmp_path / ".local").exists()  # every path came from the variables
    link.unlink()
    unlinked = run(["bash", INSTALLER, "--no-link"], env)
    assert unlinked.returncode == 0 and not link.exists() and "Linked" not in unlinked.stdout, unlinked.stdout
    assert run(["bash", INSTALLER, "extra"], env).returncode == 2
    helped = run(["bash", INSTALLER, "--help"], env)
    assert helped.returncode == 0 and "MORANN_DATA_DIR" in helped.stdout and not link.exists(), helped.stdout
    assert helped.stdout.rstrip().endswith("only links the command."), helped.stdout  # the whole header,
    assert "set -euo" not in helped.stdout, helped.stdout  # and nothing after it


def test_the_lock_pins_every_package_exactly_with_hashes():
    pins, hashes, name = {}, {}, None
    for line in (ROOT / "requirements.txt").read_text().splitlines():
        line = line.strip().removesuffix("\\").strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("--hash=sha256:"):
            assert len(line.removeprefix("--hash=sha256:")) == 64, line
            hashes[name] = hashes.get(name, 0) + 1
        else:
            name, _, version = line.partition("==")
            assert version and all(ch.isdigit() or ch == "." for ch in version), f"not an exact pin: {line}"
            pins[name] = version
    assert "textual" in pins and set(hashes) == set(pins), (pins, hashes)
