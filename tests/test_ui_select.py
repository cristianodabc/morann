# SPDX-FileCopyrightText: 2026 Cristiano Carvalho
# SPDX-License-Identifier: Apache-2.0
"""Both panels agree: after every way the list's rows or cursor change, the lower pane and the details panel show the
pull request selected in the list, or the empty state with its reason; a pull request opened by link, or one kept for
its unsent drafts, stays below while the list shows no selection."""

import pytest

from fake_github import FILES, HEAD, FakeGitHub, pr_node, search_node
from fake_github import fixture as base_fixture
from morann import core
from support import make_app, pr_keys, settle

SIZE = (100, 40)


def fixture():
    """The usual fixture with #9 readable too, so whichever row comes first loads."""
    data = base_fixture()
    data["prs"]["acme/lib#9"] = {"node": pr_node(author="kim"), "heads": [HEAD], "files": FILES[:1]}
    return data


def agree(main, label):
    """The invariant: the open pull request is the list's chosen one; with none chosen, nothing is open (no header
    buttons, file tree or diff of one) unless it is pinned below, and then the list shows no selection."""
    chosen = main.chosen()
    listing = main.query_one("#list")
    details = main.query_one("#details")
    if chosen is not None:
        shown = main.pr.key if main.pr is not None else main.loading_key or main.failed  # a failed read says so below
        assert shown == chosen.key, (label, shown, chosen.key)
        assert not details.display or f"#{chosen.number}" in str(details.border_title), (label, details.border_title)
        return
    assert not details.display, label
    pinned = main.pinned()
    if pinned is not None:
        assert listing.current() is None and main.pr is not None and main.pr.key == pinned, (label, pinned)
        return
    assert main.pr is None and main.loading_key is None, (label, main.pr and main.pr.key, main.loading_key)
    assert not main.query_one("#prbuttons").display and not main.files_tree().root.children, label
    assert "no pull request open" in str(main.query_one("#prline").content), label


def keys(main):
    return pr_keys(main.query_one("#list"))


def lower_text(main):
    return " ".join(row.text for row in main.query_one("#diff").rows)


def no_review():
    data = fixture()
    data["search"]["review"] = []
    return data


def press(*pressed, undo=()):
    """Steps that press keys, and the keys that undo them."""

    async def steps(pilot, _main, _github):
        for key in pressed:
            await pilot.press(key)
            await settle(pilot)
        if not undo:
            return None

        async def back(pilot, _main, _github):
            for key in undo:
                await pilot.press(key)
                await settle(pilot)

        return back

    return steps


async def refresh_none(pilot, _main, github):
    data = github.data()
    saved, data["search"] = data["search"], {"mine": [], "review": []}
    github.write(data)
    await pilot.press("r")
    await settle(pilot)

    async def back(pilot, main, github):
        data = github.data()
        data["search"] = saved
        github.write(data)
        main.last_refresh = 0.0
        await pilot.press("r")

    return back


async def summary_click(_pilot, main, _github):
    main.action_attention("behind")  # what a click on the top bar's count runs

    async def back(_pilot, main, _github):
        main.action_attention("behind")

    return back


async def empty_scope(pilot, main, github):
    data = github.data()
    data["search"] = {"mine": [], "review": []}
    github.write(data)
    main.scope_picked("org:beta")
    await settle(pilot)


ROUTES = {  # each way the list can empty: the steps, the reason shown below, and the fixture it starts from
    "refresh with none": (refresh_none, "nothing waits on your review", fixture),
    "tab with none": (press("1", "3"), "nothing waits on your review", no_review),
    "authors": (press("a", undo=("a", "a", "a")), "none of these are yours  a cycles", fixture),
    "my pull requests only": (press("m", undo=("m",)), "none of these are yours  m shows", fixture),
    "behind only": (press("b", undo=("b",)), "no behind pull requests  b shows all", fixture),
    "summary line": (summary_click, "no behind pull requests", fixture),
    "filter": (press("slash", *"zzz", undo=("backspace",) * 3), 'no match for the filter "zzz"', fixture),
    "filter entered": (press("slash", *"zzz", "enter"), "no match for the filter", fixture),
    "scope with none": (empty_scope, "nothing waits on your review in beta", fixture),
}


@pytest.mark.parametrize("grouped", [True, False], ids=["grouped", "ungrouped"])
@pytest.mark.parametrize("route", ROUTES)
async def test_an_emptied_list_clears_the_lower_pane(route, grouped):
    """Open #7, empty the list by the route's steps, and check the pane is cleared with its reason; then undo and
    check the first row comes back selected and loaded."""
    steps, reason, data = ROUTES[route]
    with FakeGitHub(data()) as github:
        tui = make_app(github)
        async with tui.run_test(size=SIZE) as pilot:
            await settle(pilot)
            main = tui.main
            if not grouped:
                await pilot.press("g")
                await settle(pilot)
            assert main.pr is not None, (main.error, main.loading_key, main.failed, main.tab, main.busy)
            agree(main, "before")
            undo = await steps(pilot, main, github)
            await settle(pilot)
            assert not keys(main), keys(main)
            agree(main, "emptied")
            assert f"No pull requests here: {reason}" in lower_text(main), lower_text(main)
            if undo:
                await undo(pilot, main, github)
                await settle(pilot)
                assert keys(main) and main.selected() is not None
                assert main.selected().key == keys(main)[0] and main.pr.key == keys(main)[0]
                agree(main, "rows back")


async def test_the_pane_follows_the_selection():
    """The selection moves without emptying the list: the pane follows each time."""
    with FakeGitHub(fixture()) as github:
        tui = make_app(github)
        async with tui.run_test(size=SIZE) as pilot:
            await settle(pilot)
            main = tui.main
            listing = main.query_one("#list")
            await pilot.press("j", "j")  # past the acme/lib header to #9
            await settle(pilot)
            assert main.selected().key == "acme/lib#9" and main.pr.key == "acme/lib#9"
            agree(main, "moved to #9")
            data = github.data()
            data["search"]["review"] = [search_node(7)]  # #9 is gone on refresh
            github.write(data)
            await pilot.press("r")
            await settle(pilot)
            assert keys(main) == ["acme/app#7"] and main.pr.key == "acme/app#7"
            agree(main, "refresh dropped the selected one")
            data["search"]["review"] = [search_node(7), search_node(8, repo="acme/web")]
            data["search"]["review"][1]["updatedAt"] = "2026-11-06T11:00:00Z"  # listed first now
            github.write(data)
            main.last_refresh = 0.0
            await pilot.press("r")
            await settle(pilot)
            assert keys(main) == ["acme/web#8", "acme/app#7"] and main.selected().key == "acme/app#7"
            agree(main, "refresh reordered")
            listing.go(
                next(
                    i
                    for i, row in enumerate(listing.rows)
                    if getattr(row, "repo", "") == "acme/app" and isinstance(row, core.GroupRow)
                )
            )
            await settle(pilot)
            agree(main, "cursor on the header of the open one")
            assert main.pr.key == "acme/app#7"  # the header keeps the pull request under it
            await pilot.press("h")  # its repository folds: it is no longer in the list
            await settle(pilot)
            agree(main, "fold hid it")
            assert main.pr is None
            await pilot.press("l", "j")
            await settle(pilot)
            assert main.selected().key == "acme/app#7" and main.pr.key == "acme/app#7"
            await pilot.press("g")  # ungrouped: the same pull request stays selected
            await settle(pilot)
            agree(main, "ungrouped")
            assert main.pr.key == "acme/app#7"
            await pilot.press("1")
            await settle(pilot)
            agree(main, "tab Mine")
            assert main.pr.key == "acme/app#5"


async def test_unsent_drafts_keep_a_pull_request_open():
    """Unsent drafts when the view empties: kept below, and the status line says why."""
    with FakeGitHub(fixture()) as github:
        store = core.DraftStore(github.dir / "drafts")
        kept = store.load("acme/app", 7)
        kept.add_note("unsent")
        store.save(kept)
        tui = make_app(github)
        async with tui.run_test(size=SIZE) as pilot:
            await settle(pilot)
            main = tui.main
            await pilot.press("a")
            await settle(pilot)
            assert not keys(main) and main.pr.key == "acme/app#7" and main.held == "acme/app#7"
            agree(main, "kept for its drafts")
            assert "kept open: acme/app#7 has 1 unsent drafts" in str(main.query_one("#topinfo").content)
            assert "kept open" in main.pr_line() and store.load("acme/app", 7).notes
            await pilot.press("a", "a", "a")
            await settle(pilot)
            assert main.selected().key == "acme/app#7" and main.held is None
            agree(main, "rows back with the kept one")


async def test_a_pull_request_opened_by_link_stays_until_a_row_is_chosen():
    with FakeGitHub(fixture()) as github:
        tui = make_app(github)
        async with tui.run_test(size=SIZE) as pilot:
            await settle(pilot)
            main = tui.main
            main.scope_picked("org:acme")
            await settle(pilot)
            await pilot.press("colon", *"acme/app#5", "enter")
            await settle(pilot)
            assert "acme/app#5" not in keys(main) and main.pr.key == "acme/app#5"
            assert main.query_one("#list").current() is None and "opened by link" in main.pr_line()
            agree(main, "opened by link")
            await pilot.press("tab", "j")
            await settle(pilot)
            assert main.selected() is not None and main.pr.key == main.selected().key and main.linked is None
            agree(main, "a row chosen after the link")
