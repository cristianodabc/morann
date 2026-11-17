# SPDX-FileCopyrightText: 2026 Cristiano Carvalho
# SPDX-License-Identifier: Apache-2.0
"""Which owners Morann lists: --repo, then --owner, then MORANN_OWNERS, then the owners line of the config file."""

import os
import subprocess
import sys
from pathlib import Path

import pytest

from morann import cli, core
from support import MAIN, refused


@pytest.fixture
def bare(tmp_path):
    """An environment with a home and a config folder and nothing else."""
    return {"HOME": str(tmp_path), "XDG_CONFIG_HOME": str(tmp_path / "xdg")}


@pytest.fixture
def config(tmp_path):
    """Where the config file goes; its folder exists, the file does not."""
    path = tmp_path / "xdg/morann/config"
    path.parent.mkdir(parents=True)
    return path


def test_owners_come_from_the_variable_then_the_config_file(tmp_path, bare, config):
    assert core.config_path(bare) == config
    assert core.config_path({**bare, "MORANN_CONFIG": "/elsewhere"}) == Path("/elsewhere")
    with refused(core.UsageError, "--owner OWNER"):  # no flag, no variable, no file
        core.default_owners(bare)
    assert core.default_owners({**bare, "MORANN_OWNERS": "acme, beta"}) == ["acme", "beta"]
    assert core.default_owners({**bare, "MORANN_OWNERS": "acme beta"}) == ["acme", "beta"]
    with refused(core.UsageError, "not an owner"):
        core.default_owners({**bare, "MORANN_OWNERS": "acme/app"})
    config.write_text("# morann settings\nowners = gamma,delta\n")
    assert core.default_owners(bare) == ["gamma", "delta"]
    assert core.default_owners({**bare, "MORANN_OWNERS": " "}) == ["gamma", "delta"]  # a blank variable falls through
    assert core.default_owners({**bare, "MORANN_OWNERS": "acme"}) == ["acme"]  # the variable beats the file
    config.write_text("theme = dark\n")
    with refused(core.UsageError, "MORANN_OWNERS"):
        core.default_owners(bare)
    with refused(core.UsageError, "cannot read"):  # a folder, not a file
        core.default_owners({**bare, "MORANN_CONFIG": str(tmp_path)})


def test_where_drafts_and_state_are_kept(tmp_path, monkeypatch):
    """The cache folder's morann folder, unless MORANN_HOME names another."""
    monkeypatch.delenv("MORANN_HOME", raising=False)
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    assert core.home() == tmp_path / "cache/morann"
    monkeypatch.setenv("MORANN_HOME", "/elsewhere")
    assert core.home() == Path("/elsewhere")


def test_flags_beat_the_variable(monkeypatch):
    monkeypatch.setenv("MORANN_OWNERS", "acme")
    monkeypatch.delenv("MORANN_CONFIG", raising=False)
    assert cli.scope(cli.parse([])) == core.Scope(owners=("acme",))
    assert cli.scope(cli.parse(["--owner", "beta"])) == core.Scope(owners=("beta",))
    assert cli.scope(cli.parse(["--owner", "x", "--repo", "acme/app"])) == core.Scope(repos=("acme/app",))


@pytest.mark.parametrize("arguments", [[], ["update"]])
def test_the_command_says_how_to_name_owners(bare, arguments):
    env = {key: value for key, value in os.environ.items() if not key.startswith("MORANN_")}
    done = subprocess.run(
        [sys.executable, "-B", str(MAIN), *arguments], env={**env, **bare}, capture_output=True, text=True, check=False
    )
    assert done.returncode == 2 and "MORANN_OWNERS" in done.stderr, (done.returncode, done.stderr)
