# SPDX-FileCopyrightText: 2026 Cristiano Carvalho
# SPDX-License-Identifier: Apache-2.0
"""The review screen: how far the review is, each thread's state at a glance, and the file and hunk held at the top
of the diff while their headers are scrolled away."""

from fake_gh import HEAD
from fake_github import FakeGitHub, fixture, load, long_fixture
from morann import core
from morann.views import needs_you, thread_badges
from support import make_app, settle


def test_thread_states():
    with FakeGitHub(fixture()):
        pr = load()
    empty = core.Drafts(pr.repo, pr.number)
    states = {thread.id: thread_badges(thread, empty, "ann") for thread in pr.threads}
    assert states["T1"] == ("open", "yours", "your turn")  # ann started it and sam answered last
    assert "resolved" in states["T2"] and "your turn" not in states["T2"]
    assert states["T3"][:2] == ("open", "outdated")
    drafts = core.Drafts(pr.repo, pr.number)
    drafts.add_reply(pr.thread("T3"), "still?")
    assert thread_badges(pr.thread("T3"), drafts, "")[-1] == "draft" and "yours" not in states["T3"]


async def test_progress_and_the_sticky_header():
    with FakeGitHub(long_fixture()) as github:
        tui = make_app(github)
        async with tui.run_test(size=(100, 30)) as pilot:
            await settle(pilot)
            main = tui.main
            await pilot.press("tab", "4")
            await settle(pilot)
            total = len(main.pr.files)
            assert f"viewed 0/{total}" in main.pr_line(), main.pr_line()
            await pilot.press("V")  # mark the open file viewed
            await settle(pilot)
            assert f"viewed 1/{total}" in main.pr_line() and "1/" in main.query_one("#sidebar").border_title
            sticky = main.query_one("#sticky")
            path = main.pr.files[main.file_index].path
            assert sticky.display and path in str(sticky.content)  # the file, and the hunk at the top of the view
            await pilot.press("G")
            await settle(pilot)
            assert sticky.display and path in str(sticky.content) and "@@" in str(sticky.content), sticky.content
            last_hunk = [row.text for row in main.query_one("#diff").rows if row.kind == "hunk"][-1]
            assert str(sticky.content).endswith(last_hunk), (sticky.content, last_hunk)
            await pilot.press("1")  # only the Files tab has one
            await settle(pilot)
            assert main.mode == "conversation" and not sticky.display


def test_what_needs_you():
    """At the top of the conversation: a review asked of you, failing checks, requested changes, conflicts, threads
    waiting on your reply and your drafts; or that nothing does."""
    with FakeGitHub(fixture()):
        pr = load()
    drafts = core.Drafts(pr.repo, pr.number)
    pr.viewer, pr.asked = "ann", ("ann",)
    pr.review_decision, pr.mergeable = "CHANGES_REQUESTED", "CONFLICTING"
    drafts.add_note("soon")
    lines = needs_you(pr, drafts)
    assert [style for _text, style in lines] == ["accent", "bad", "bad", "bad", "accent", "draft"], lines
    texts = [text for text, _style in lines]
    assert texts[0] == "o your review is requested" and texts[1] == "x 1 failing check: test"
    assert texts[3] == "# conflicts with main" and texts[4] == "o 1 thread wait on your reply"
    assert texts[5] == "* 1 unsent draft: v shows what would be posted"
    pr.checks, pr.asked, pr.review_decision, pr.mergeable, pr.viewer = [], (), "", "MERGEABLE", "zed"
    assert needs_you(pr, core.Drafts(pr.repo, pr.number)) == [("ci:ok nothing waits on you here", "ok")]
    shown = [row.text for row in core.conversation_rows(pr, core.Drafts(pr.repo, pr.number))]
    assert shown[2:4] == ["what needs you", "ci:ok nothing waits on you here"]
    notes = [row for row in core.conversation_rows(pr, drafts) if row.badges in (("approved",), ("changes requested",))]
    assert notes, "a review's verdict is a chip on its card"


def test_the_checks_tab_leads_with_a_tally():
    with FakeGitHub(fixture()):
        pr = load()
    first = core.check_rows(pr)[0]
    assert first.text == "1 failing  1 running  1 passed  1 skipped" and first.style == "bad"


async def test_unchanged_lines_between_hunks_expand():
    """A gap row stands for the unchanged lines between two hunks; enter reads the file at the head and shows them,
    numbered in both files, highlighted, and taking no comment."""
    data = fixture()
    text = "\n".join(f"line {n}" for n in range(1, 16))
    data["objects"] = {
        f"acme/app@{HEAD}:lib/a.py": {"__typename": "Blob", "text": text, "byteSize": len(text), "oid": "b"}
    }
    with FakeGitHub(data) as github:
        tui = make_app(github)
        async with tui.run_test(size=(100, 40)) as pilot:
            await settle(pilot)
            main = tui.main
            await pilot.press("tab", "4")
            await settle(pilot)
            diff = main.query_one("#diff")
            gap = next(i for i, row in enumerate(diff.rows) if row.kind == "gap")
            assert diff.rows[gap].text.startswith("5 unchanged lines") and diff.rows[gap].counts == (6, 5)
            diff.go(gap)
            await pilot.pause()
            assert main.check_action("expand", ()) and not main.check_action("comment", ())
            await pilot.press("enter")
            await settle(pilot)
            shown = [row for row in diff.rows if row.kind == "more"]
            assert [(row.old, row.new, row.text) for row in shown] == [
                (str(n - 1), str(n), f"line {n}") for n in range(6, 11)
            ], shown
            assert not any(row.kind == "gap" for row in diff.rows) and not github.posts()
            diff.go(diff.rows.index(shown[0]))
            await pilot.pause()
            assert not main.check_action("comment", ())  # a forge takes comments only on the lines of the diff
            await pilot.press("colon", *"expand", "enter")  # nothing left folded
            await settle(pilot)
            assert len([row for row in diff.rows if row.kind == "more"]) == 5


def test_split_rows_pair_removed_with_added_lines():
    with FakeGitHub(fixture()):
        pr = load()
    rows = core.file_rows(pr, 0, core.Drafts(pr.repo, pr.number))
    pairs = core.split_rows(rows)
    lines = [row for row in pairs if row.pair is not None]
    edit = next(row for row in lines if row.pair[0] is not None and row.pair[0].text == "import sys")
    assert edit.pair[1].text == "import json" and edit.anchor == ("lib/a.py", "RIGHT", 2)  # a comment goes on the new
    alone = next(row for row in lines if row.pair[1] is not None and row.pair[1].text == "import re")
    assert alone.pair[0] is None and alone.kind == "add"
    same = next(row for row in lines if row.text == "import os")
    assert same.pair[0] is same.pair[1] and same.kind == "ctx"
    assert [row.kind for row in pairs if row.pair is None][:2] == ["file", "hunk"]  # the rest stays full width
    threads = [i for i, row in enumerate(pairs) if row.kind == "thread"]
    assert threads and pairs[threads[0] - 1].pair is not None  # a run's threads right after its pairs


async def test_side_by_side_where_the_pane_is_wide():
    with FakeGitHub(fixture()) as github:
        tui = make_app(github)
        async with tui.run_test(size=(160, 40)) as pilot:
            await settle(pilot)
            main = tui.main
            await pilot.press("tab", "4")
            await settle(pilot)
            if main.query_one("#sidebar").display:
                await pilot.press("e")
                await settle(pilot)
            await pilot.press("vertical_line")
            await settle(pilot)
            diff = main.query_one("#diff")
            assert main.split_view and any(row.pair for row in diff.rows)
            index = next(
                i for i, row in enumerate(diff.rows) if row.pair and row.pair[0] and row.pair[0].text == "import sys"
            )
            [line] = [strip() if callable(strip) else strip for strip in tui.painter.diff_row(diff.rows[index], 150, 2)]
            text = "".join(segment.text for segment in line)
            assert "import sys" in text and "import json" in text and "│" in text
            assert text.index("import sys") < text.index("│") < text.index("import json")
            await pilot.press("g", "g", "right_square_bracket", "c")  # motions work on the pairs
            await settle(pilot)
            assert diff.current().pair is not None and diff.current().kind in ("add", "del")
            await pilot.resize_terminal(100, 40)  # too narrow: one column again, the choice kept
            await settle(pilot)
            assert main.split_view and not any(row.pair for row in diff.rows)
            await pilot.press("colon", *"unified", "enter")
            await settle(pilot)
            assert not main.split_view
