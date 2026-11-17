# SPDX-FileCopyrightText: 2026 Cristiano Carvalho
# SPDX-License-Identifier: Apache-2.0
"""No colored bar runs down the left edge of a pane, a field or a list: a focused pane, the details panel, the inline
editor, the summary field and the submit bar show focus by their border color, tab underline and cursor row. Also the
header's buttons at every width, and opening a check from the Checks tab."""

import pytest

from fake_github import FakeGitHub, fixture
from morann import core
from support import make_app, settle

BARS = set("▊▋▌▍▎▏▐█┃▕")  # left blocks and the heavy vertical line
THIN = set("│┆")  # a thin vertical line is a bar only on a widget that has no frame of its own


def hue_bar(color):
    """True for a blue or a green shade: the accent and success colors a bar would be painted in."""
    if color is None:
        return False
    red, green, blue = color.get_truecolor()
    return blue > red + 16 or green > red + 16


def left_bars(app):
    """Every (widget id, row, glyph) where a blue or green bar glyph sits in the left edge column of the widget drawn there
    (a child's own frame on its parent's edge is the child's)."""
    strips = app.screen._compositor.render_strips()
    cells = {}
    for y, strip in enumerate(strips):
        x = 0
        for segment in strip:
            for char in segment.text:
                cells[(x, y)] = (char, segment.style.color if segment.style else None)
                x += 1
    found = []
    for widget in app.screen.walk_children():
        region = widget.region
        if not widget.display or not widget.visible or not region.width or not region.height:
            continue
        framed = bool(widget.styles.border_top[0])
        for y in range(region.y, region.bottom):
            char, color = cells.get((region.x, y), (" ", None))
            if (
                (char in BARS or (char in THIN and not framed))
                and hue_bar(color)
                and app.screen.get_widget_at(region.x, y)[0] is widget
            ):
                found.append((widget.id or type(widget).__name__, y, char))
    return found


@pytest.mark.parametrize("width", [70, 100])
async def test_no_colored_bar_on_a_left_edge(width):
    """Render the list, each tab, the tree, the editor, the summary, the submit bar and the popups; none may have a
    blue or green bar in a widget's left edge column."""
    with FakeGitHub(fixture()) as github:
        tui = make_app(github)
        async with tui.run_test(size=(width, 40)) as pilot:
            await settle(pilot)

            async def look(label):
                await settle(pilot)
                assert not left_bars(tui), (width, label, left_bars(tui))

            await look("list")
            await pilot.press("tab")
            await look("diff focused")
            for tab in ("1", "2", "3", "4"):
                await pilot.press(tab)
                await look(f"tab {tab}")
            await pilot.press("e")
            await look("file tree")
            await pilot.press("c")
            await look("inline editor")
            await pilot.press("escape", "m")
            await look("summary")
            await pilot.press("ctrl+s", "a")
            await look("submit bar")
            await pilot.press("escape", "M")
            await look("actions")
            await pilot.press("escape", "s")
            await look("scope")
            await pilot.press("escape", "question_mark")
            await look("help")


@pytest.mark.parametrize("mode", ["terminal", "builtin"])
@pytest.mark.parametrize("width", [70, 80, 100])
async def test_header_buttons_draw_their_labels(mode, width):
    """The pull request's button row on another author's pull request (#7) and on your own (#5), in the terminal's
    colors and in github's: every button shown has a label, is as wide as it, and draws it. A frame forced on a
    one-row button (a disabled Merge in the ANSI themes) left only an empty box."""
    with FakeGitHub(fixture()) as github:
        for tab, own in (("3", False), ("1", True)):
            tui = make_app(github, theme_name=mode)
            async with tui.run_test(size=(width, 40)) as pilot:
                await settle(pilot)
                await pilot.press(tab)
                await settle(pilot)
                main = tui.main
                assert main.pr is not None and main.own_pr() == own, (mode, width, tab)
                assert main.query_one("#merge").display and main.query_one("#merge").disabled != own
                strips = tui.screen._compositor.render_strips()
                for button in main.query("#prbuttons Button, #tree-toggle"):
                    if not button.display:
                        continue
                    label, region = str(button.label), button.region
                    where = (mode, width, "own" if own else "other", button.id, label)
                    assert label.strip() and region.width >= core.width_of(label), (where, region)
                    row = "".join(segment.text for segment in strips[region.y])
                    assert label in row[region.x : region.right], (where, row[region.x : region.right])


async def test_a_check_opens_from_the_checks_tab():
    """On the Checks tab, o and enter open the check under the cursor on GitHub: a failing one from another app at
    GitHub's page for its run, a skipped Actions job at its job page, a status with no run at the Checks tab. The hint
    bar and the header say so, and a failure's reason is on screen."""
    with FakeGitHub(fixture()) as github:
        opened = []
        tui = make_app(github, opener=opened.append)
        async with tui.run_test(size=(100, 40)) as pilot:
            await settle(pilot)
            main = tui.main
            await pilot.press("3", "tab", "3")
            await settle(pilot)
            diff = main.query_one("#diff")
            assert main.mode == "checks" and diff.current().kind == "check", diff.current()
            hints = " ".join(main.query_one("#status").content.plain.split())
            assert "enter open" in hints, hints
            assert "o open check on GitHub" in str(main.query_one("#prline").content)
            screen = "\n".join("".join(s.text for s in strip) for strip in tui.screen._compositor.render_strips())
            assert "failure: 2 tests failed" in screen
            for key in ("o", "enter"):
                diff.go(next(i for i, row in enumerate(diff.rows) if row.kind == "check"))
                for _ in range(4):
                    await pilot.press(key)
                    await settle(pilot)
                    await pilot.press("j")
            assert opened == 2 * [
                "https://github.com/acme/app/pull/7/checks?check_run_id=555",
                "https://github.com/acme/app/pull/7/checks?check_run_id=556",
                "https://github.com/acme/app/pull/7/checks",
                "https://github.com/acme/app/actions/runs/9/job/10",
            ], opened
            await pilot.press("1")  # elsewhere enter folds and o opens the line or the pull request, as before
            await settle(pilot)
            assert not main.check_action("open_check", ())
