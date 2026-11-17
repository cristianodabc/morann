# SPDX-FileCopyrightText: 2026 Cristiano Carvalho
# SPDX-License-Identifier: Apache-2.0
"""Where Morann keeps its files, how it reads its environment and config file, and which names it accepts."""

from __future__ import annotations

import os
import re
from collections.abc import Mapping
from pathlib import Path

APP = "morann"

NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")  # an owner
REPO_NAME = re.compile(r"[A-Za-z0-9._-]+")  # a repository, for example .github


class UsageError(Exception):
    """Arguments or settings Morann cannot use."""


def setting(name: str, environ: Mapping[str, str] | None = None) -> str:
    """MORANN_<name>, or nothing. A variable set to nothing counts as not set."""
    environ = os.environ if environ is None else environ
    return environ.get(f"{APP.upper()}_{name}") or ""


def home() -> Path:
    """Where Morann keeps drafts, the pull request cache and its UI state: MORANN_HOME, else $XDG_CACHE_HOME/morann
    (~/.cache/morann)."""
    named = setting("HOME")
    if named:
        return Path(named)
    return Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache") / APP


def config_path(environ: Mapping[str, str] | None = None) -> Path:
    """Morann's config file: MORANN_CONFIG, else $XDG_CONFIG_HOME/morann/config (~/.config/morann/config)."""
    environ = os.environ if environ is None else environ
    named = setting("CONFIG", environ)
    if named:
        return Path(named)
    return Path(environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / APP / "config"


def parse_env(text: str) -> dict[str, str]:
    """KEY=value lines as a dict, skipping blank lines and # comments."""
    settings = {}
    for line in text.splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            settings[key.strip()] = value.strip()
    return settings


def config_value(key: str, environ: Mapping[str, str] | None = None) -> str:
    """A `key = value` line of the config file, or "" when the file or the line is not there."""
    path = config_path(environ)
    try:
        return parse_env(path.read_text()).get(key, "")
    except FileNotFoundError:
        return ""
    except (OSError, UnicodeDecodeError) as error:
        raise UsageError(f"cannot read {path}: {error}") from None


OWNERS_HELP = (
    "name the owners to list: --owner OWNER, --repo OWNER/REPO, MORANN_OWNERS=OWNER,OWNER or a line "
    "owners = OWNER, OWNER in ~/.config/morann/config"
)


def default_owners(environ: Mapping[str, str] | None = None) -> list[str]:
    """The owners to list when neither --owner nor --repo is given: MORANN_OWNERS (comma or space separated), else
    the owners line of the config file."""
    environ = os.environ if environ is None else environ
    names = setting("OWNERS", environ)
    if not names.strip():
        names = config_value("owners", environ)
    owners = [check_owner(owner) for owner in re.split(r"[\s,]+", names) if owner]
    if not owners:
        raise UsageError(OWNERS_HELP)
    return owners


def check_owner(owner: str) -> str:
    """An owner's name, or a UsageError: it becomes part of a query and of a path, so it is one plain segment."""
    if not NAME.fullmatch(owner):
        raise UsageError(f"not an owner: {owner!r}")
    return owner


def check_repo(repo: str) -> str:
    """An OWNER/REPO, or a UsageError: it becomes a path under the drafts folder, so it is two plain segments."""
    owner, _, name = repo.partition("/")
    if not (NAME.fullmatch(owner) and REPO_NAME.fullmatch(name)) or name in (".", ".."):
        raise UsageError(f"not an OWNER/REPO: {repo!r}")
    return repo
