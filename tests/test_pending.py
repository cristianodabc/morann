# SPDX-FileCopyrightText: 2026 Cristiano Carvalho
# SPDX-License-Identifier: Apache-2.0
"""The Pending tab: every pull request with a review in progress, drafts kept here or a review started on the forge,
the one waiting longest first, with its count on the tab and in the header; enter opens it at its first draft."""

import os
from datetime import timedelta

from fake_github import NOW, FakeGitHub, fixture
from morann import core
from morann.github import parse
from support import make_app, pr_keys, settle


def row(number, repo="acme/app", pending=None):
    return core.PrRow(repo, number, f"Change {number}", "", "sam", False, "", "", "", "", pending=pending)


def test_pending_rows_put_the_longest_waiting_first():
    rows = [row(7), row(9, "acme/lib", (2, "2026-11-01T10:00:00Z")), row(5)]
    local = {"acme/app#7": (1, "2026-11-04T10:00:00Z"), "acme/other#3": (2, "2026-11-02T10:00:00Z")}
    found = core.pending_rows(rows, local, lambda key: row(int(key.rpartition("#")[2]), key.rpartition("#")[0]))
    assert [(item.row.key, item.drafts) for item in found] == [
        ("acme/lib#9", 2),  # the forge's pending review, oldest
        ("acme/other#3", 2),  # drafts on a pull request no list holds
        ("acme/app#7", 1),
    ]
    both = core.pending_rows([row(7, pending=(3, "2026-11-05T00:00:00Z"))], {"acme/app#7": local["acme/app#7"]}, row)
    assert both[0].drafts == 4 and both[0].last == "2026-11-05T00:00:00Z"  # drafts here and there, the newer time


def test_the_forge_pending_review_is_read():
    node = {"pending": {"nodes": [{"updatedAt": "2026-11-03T08:00:00Z", "comments": {"totalCount": 2}}]}}
    assert parse.pending_review(node) == (2, "2026-11-03T08:00:00Z")
    assert parse.pending_review({}) is None and parse.pending_review({"pending": {"nodes": []}}) is None


def test_the_drafts_folder_says_when_drafts_were_kept(tmp_path):
    store = core.DraftStore(tmp_path)
    drafts = store.load("acme/app", 7)
    drafts.add_note("a")
    drafts.summary = "b"
    store.save(drafts)
    os.utime(store.path("acme/app", 7), (0, (NOW - timedelta(days=3)).timestamp()))
    assert store.waiting() == {"acme/app#7": (2, "2026-11-03T12:00:00Z")}


def keep(store, repo, number, days_ago, comment=None):
    drafts = store.load(repo, number)
    if comment:
        drafts.add_comment(*comment)
    else:
        drafts.add_note("unsent")
    store.save(drafts)
    when = (NOW - timedelta(days=days_ago)).timestamp()
    os.utime(store.path(repo, number), (when, when))


async def test_the_pending_tab():
    data = fixture()
    nine = data["search"]["review"][2]
    nine["pending"] = {"nodes": [{"updatedAt": "2026-10-30T12:00:00Z", "comments": {"totalCount": 2}}]}
    with FakeGitHub(data) as github:
        store = core.DraftStore(github.dir / "drafts")
        keep(store, "acme/app", 7, 1, ("lib/a.py", "RIGHT", 3, "why re?"))
        keep(store, "acme/other", 3, 3)
        tui = make_app(github, store=store)
        async with tui.run_test(size=(100, 40)) as pilot:
            await settle(pilot)
            main = tui.main
            tabs = main.query_one("#tabs")
            assert str(tabs.get_tab("pending").label) == "2 Pending [3]" and "3 pending" in str(
                main.query_one("#topinfo").content
            )
            await pilot.press("2")
            await settle(pilot)
            listing = main.query_one("#list")
            assert main.tab == "pending"
            assert pr_keys(listing) == ["acme/lib#9", "acme/other#3", "acme/app#7"], pr_keys(listing)
            assert main.waits == {
                "acme/lib#9": ("1w", "bad"),
                "acme/other#3": ("3d", "wait"),
                "acme/app#7": ("1d", "dim"),
            }
            assert main.row_counts() == {"acme/lib#9": 2, "acme/other#3": 1, "acme/app#7": 1}
            await pilot.press("slash", *"lib", "enter")  # filtered like any tab
            assert pr_keys(listing) == ["acme/lib#9"]
            await pilot.press("slash", "escape")
            await settle(pilot)
            listing.go(next(i for i, r in enumerate(listing.rows) if getattr(r, "key", "") == "acme/app#7"))
            await pilot.press("enter")  # straight to the first draft, in its file
            await settle(pilot)
            current = main.query_one("#diff").current()
            assert main.pr.key == "acme/app#7" and main.mode == "files" and current.draft, current
            assert current.body == "why re?" and main.focus_pane == "diff"
            await pilot.press("colon", *"tab pend", "enter")
            assert main.tab == "pending"


async def test_no_review_in_progress():
    with FakeGitHub(fixture()) as github:
        tui = make_app(github)
        async with tui.run_test(size=(100, 40)) as pilot:
            await settle(pilot)
            await pilot.press("2")
            await settle(pilot)
            assert "no review in progress" in tui.main.empty_note()
            assert "pending" not in str(tui.main.query_one("#topinfo").content)
