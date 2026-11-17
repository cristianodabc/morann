# SPDX-FileCopyrightText: 2026 Cristiano Carvalho
# SPDX-License-Identifier: Apache-2.0
"""Finding things: the fuzzy matcher the pickers rank with, and how a : command line reads and completes."""

import pytest

from morann import commands, core, fuzzy


def test_fuzzy_match_and_rank():
    assert fuzzy.match("", "anything") == (0, ())
    assert fuzzy.match("xyz", "acme/app#7") is None
    score, positions = fuzzy.match("ap7", "acme/app#7 Use json")
    assert positions[0] == 5 and positions[-1] == 9 and score > 0  # the window ends at the last match
    assert fuzzy.match("ab", "a-x-ab")[1] == (4, 5)  # the tightest window, not the first a
    assert fuzzy.match("App", "acme/app") is None and fuzzy.match("App", "acme/App") is not None  # a capital: exact
    assert fuzzy.match("aj", "acme/app use json")[0] < fuzzy.match("aj", "app json")[0]  # shorter gaps score higher
    ranked = fuzzy.rank("lib", [("acme/app#7 Change 7", 7), ("acme/lib#9 Change 9", 9), ("acme/lab#3 lib", 3)])
    assert [value for _score, _positions, value in ranked] == [9, 3]
    assert [value for *_rest, value in fuzzy.rank("", [("b", 1), ("a", 2)])] == [1, 2]  # no query: the order given
    assert fuzzy.rank("a b", [("ab", 1)])[0][2] == 1  # spaces in the query are ignored


def test_commands():
    assert commands.parse("") is None and commands.parse(":  ") is None
    command, arg = commands.parse(":open acme/app#5")
    assert (command.name, arg) == ("open", "acme/app#5")
    assert commands.parse("acme/app#5")[0].name == "open" and commands.parse("#12")[1] == "#12"
    assert commands.parse("https://github.com/acme/app/pull/5")[0].name == "open"
    assert commands.parse("q")[0].name == "quit" and commands.parse("sco acme") == (commands.find("scope"), "acme")
    assert commands.find("c") is None  # conversation, commits, checks: ambiguous
    with pytest.raises(core.UsageError, match="not a command: frob"):
        commands.parse("frob")
    choices = {"scope": ["mine", "personal", "acme"], "tab": ["mine", "review", "all"]}
    assert commands.complete("sc", choices) == ["scope"]
    assert commands.complete("c", choices) == ["conversation", "commits", "checks", "copy"]
    assert commands.complete("scope p", choices) == ["scope personal"]
    assert commands.complete("tab ", choices) == ["tab mine", "tab review", "tab all"]
    assert commands.complete("refresh x", choices) == [] and commands.complete("nope x", choices) == []
    history = commands.remember(["a", "b"], "a")
    assert history == ["b", "a"] and len(commands.remember([str(n) for n in range(80)], "x")) == commands.HISTORY
