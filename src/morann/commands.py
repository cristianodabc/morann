# SPDX-FileCopyrightText: 2026 Cristiano Carvalho
# SPDX-License-Identifier: Apache-2.0
"""The `:` command line's commands: what each is called, what argument it takes, how a typed line reads, and how tab
completes it. Main runs them. Standard library only."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from morann.settings import UsageError
from morann.views import SPLIT_WIDTH

HISTORY = 50  # command lines kept between runs


@dataclass(frozen=True)
class Command:
    name: str
    aliases: tuple[str, ...]
    arg: str  # what the argument completes from: ref, scope, repo, tab, theme, help, text, or "" for none
    text: str  # what it does, for :help and the completions


COMMANDS = (
    Command("open", ("o", "e", "pr"), "ref", "open a pull request: a link, OWNER/REPO#N, #N or N"),
    Command("scope", ("s",), "scope", "show pull requests from: mine, personal, or an organization"),
    Command("repo", ("r",), "repo", "show only the pull requests of OWNER/REPO in the list (empty: all again)"),
    Command("tab", ("t",), "tab", "the list's tab: mine, pending, review or all"),
    Command("filter", ("f",), "text", "filter the list by repo, title or author (empty: clear)"),
    Command("conversation", ("conv",), "", "the Conversation tab"),
    Command("commits", (), "", "the Commits tab"),
    Command("checks", (), "", "the Checks tab"),
    Command("files", (), "", "the Files tab"),
    Command("next", (), "motion", "the next change, hunk, file, thread, unresolved thread, comment or draft"),
    Command(
        "prev", ("previous",), "motion", "the previous change, hunk, file, thread, unresolved thread, comment or draft"
    ),
    Command("expand", (), "", "show every folded run of unchanged lines of the open file"),
    Command("split", (), "", f"the diff side by side, old beside new (the diff needs {SPLIT_WIDTH} columns)"),
    Command("unified", (), "", "the diff in one column"),
    Command("review", ("rv",), "review", "start a review of the open pull request, or show what it would post"),
    Command("edit", (), "", "edit the draft, or your own posted comment, under the cursor"),
    Command("delete", (), "", "delete the draft, or your own posted comment, under the cursor, after a confirmation"),
    Command("link", ("gx",), "", "open a link of the comment or row under the cursor, its address shown first"),
    Command("copy", ("yank", "gy"), "", "copy the address of a link of the row under the cursor"),
    Command("refresh", ("reload",), "", "read the lists and the open pull request again"),
    Command("theme", (), "theme", "switch to a theme by name (terminal, catppuccin-mocha...), or the next one"),
    Command("help", ("h",), "help", "the keys; :help WORDS filters them, :help commands lists these"),
    Command("quit", ("q", "q!", "qa", "quit!", "exit"), "", "quit Morann"),
)

TABS = ("mine", "pending", "review", "all")
REF = re.compile(r"(https?://\S+|[\w.-]+/[\w.-]+#\d+|#?\d+)")  # what a bare line that opens a pull request looks like


def find(word: str) -> Command | None:
    """The command a word names: its name, an alias, or the start of exactly one name."""
    word = word.casefold()
    for command in COMMANDS:
        if word == command.name or word in command.aliases:
            return command
    starts = [command for command in COMMANDS if command.name.startswith(word)]
    return starts[0] if len(starts) == 1 else None


def parse(line: str) -> tuple[Command, str] | None:
    """A typed line as (command, argument), None for an empty line. A bare link or reference opens it; anything else
    that names no command is a UsageError that says so."""
    line = line.strip().removeprefix(":").strip()
    if not line:
        return None
    word, _, rest = line.partition(" ")
    command = find(word)
    if command is not None:
        return command, rest.strip()
    if REF.fullmatch(line):
        return COMMANDS[0], line
    raise UsageError(f"not a command: {word}  (:help commands lists them)")


def complete(line: str, choices: Mapping[str, Sequence[str]]) -> list[str]:
    """The lines tab offers for what was typed: command names while the first word is typed, then the argument's
    choices (from `choices`, by the command's argument kind) that start with what was typed of it."""
    word, space, rest = line.lstrip(":").lstrip().partition(" ")
    if not space:
        return [command.name for command in COMMANDS if command.name.startswith(word.casefold())]
    command = find(word)
    if command is None or not command.arg:
        return []
    typed = rest.strip().casefold()
    return [
        f"{command.name} {choice}" for choice in choices.get(command.arg, ()) if choice.casefold().startswith(typed)
    ]


def remember(history: Sequence[str], line: str) -> list[str]:
    """The history with this line last, once, and no longer than HISTORY."""
    line = line.strip()
    kept = [item for item in history if item != line] + ([line] if line else [])
    return kept[-HISTORY:]
