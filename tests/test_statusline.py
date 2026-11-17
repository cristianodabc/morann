# SPDX-FileCopyrightText: 2026 Cristiano Carvalho
# SPDX-License-Identifier: Apache-2.0
"""The statusline: its segments from the settings, what is dropped first on a narrow terminal, the separators of each
glyph set, and the mode it shows as you work."""

import pytest

from fake_github import FakeGitHub, fixture
from morann import core, statusline, theme
from support import make_app, settle

Segment = statusline.Segment


def test_the_segments_come_from_the_settings(tmp_path):
    assert statusline.layout({}) == (statusline.LEFT, statusline.RIGHT)
    config = tmp_path / "config"
    config.write_text("statusline_left = mode, where\nstatusline_right = help\n")
    assert statusline.layout({"MORANN_CONFIG": str(config)}) == (("mode", "where"), ("help",))
    env = {"MORANN_CONFIG": str(config), "MORANN_STATUSLINE_LEFT": "mode progress"}
    assert statusline.layout(env) == (("mode", "progress"), ("help",))  # the environment over the config
    with pytest.raises(core.UsageError, match="unknown statusline segment 'clock'; there are: mode, where"):
        statusline.layout({"MORANN_STATUSLINE_RIGHT": "clock"})


def test_what_goes_first_on_a_narrow_terminal():
    left = [
        Segment("mode", "READING", "accent"),
        Segment("where", "acme/app #7"),
        Segment("branch", "json"),
        Segment("progress", "0/5 viewed"),
    ]
    right = [Segment("position", "a.py:3 40%"), Segment("theme", "nord"), Segment("help", "? help")]
    keys = [("c", "comment"), ("n p", "thread"), ("/", "search")]
    kept = statusline.fit(left, right, keys, 200, 3)
    assert kept == (left, right, keys)  # room for everything
    names = lambda result: [seg.name for seg in result[0] + result[1]]  # noqa: E731
    narrow = statusline.fit(left, right, keys, 80, 3)
    assert "theme" not in names(narrow) and "branch" not in names(narrow) and 0 < len(narrow[2]) <= len(keys)
    tighter = statusline.fit(left, right, keys, 60, 3)
    assert names(tighter) == ["mode", "where", "progress", "position", "help"] and len(tighter[2]) < len(keys)
    tiny = statusline.fit(left, right, keys, 30, 3)
    assert names(tiny)[:2] == ["mode", "position"] and tiny[2] == []  # the keys go before the mode and the position


@pytest.mark.parametrize(("glyphs", "edge"), [("nerd", ""), ("unicode", "▌"), ("ascii", "|")])
def test_each_glyph_set_has_its_separators(glyphs, edge):
    ink = theme.Ink(theme.TERMINAL)
    line = statusline.render(
        [Segment("mode", "READING", "accent"), Segment("where", "x")],
        [Segment("help", "? help")],
        [("c", "comment")],
        60,
        ink,
        glyphs,
    )
    assert line.cell_len == 60 and edge in line.plain and line.plain.startswith(" READING ")
    assert "c comment" in line.plain and line.plain.rstrip().endswith("? help")
    mode = line.spans[0].style
    assert mode.reverse and mode.color.name == "cyan"  # the terminal's colors: the mode a reversed pill


def test_a_scheme_fills_the_sections():
    tokens = theme.schemes({})["nord"].tokens
    ink = theme.Ink(tokens)
    line = statusline.render([Segment("mode", "REVIEWING", "local"), Segment("where", "x")], [], [], 40, ink, "nerd")
    mode = line.spans[0].style
    assert mode.bgcolor.triplet.hex == tokens.local and mode.bold
    joint = next(span.style for span in line.spans if line.plain[span.start : span.end] == "")
    assert joint.color.triplet.hex == tokens.local and joint.bgcolor.triplet.hex == tokens.surface  # powerline


def status(main):
    return " ".join(main.query_one("#status").content.plain.split())


async def test_the_mode_follows_what_you_do():
    with FakeGitHub(fixture()) as github:
        tui = make_app(github)
        async with tui.run_test(size=(120, 40)) as pilot:
            await settle(pilot)
            main = tui.main
            assert status(main).startswith("READING | acme/app #7 |") and status(main).endswith("? help")
            await pilot.press("colon")
            assert status(main).startswith("COMMAND")
            await pilot.press("escape", "slash")
            assert status(main).startswith("SEARCH")
            await pilot.press("escape", "2")
            await settle(pilot)
            assert status(main).startswith("PENDING")
            await pilot.press("3", "v")  # a review starts
            await settle(pilot)
            assert status(main).startswith("REVIEWING") and "1/2" in status(main)
            await pilot.press("tab", "4")
            await settle(pilot)
            assert "0/5 viewed" in status(main) and "a.py" in status(main) and "%" in status(main)
