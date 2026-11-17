# SPDX-FileCopyrightText: 2026 Cristiano Carvalho
# SPDX-License-Identifier: Apache-2.0
"""The All tab: it lists every open pull request of the configured owners, whoever opened it, and the usual filters
narrow it. The fixture has two owners; only #5, #32 and #52 are the viewer's."""

import json

from fake_github import FakeGitHub, fixture
from morann import core
from morann.github import GitHubProvider, search
from support import make_app, pr_numbers, settle

TERMS = "org:acme org:beta"
BOTH = core.Scope(owners=("acme", "beta"))


def all_fixture():
    """Open in acme and beta, newest update first: #51 zoe, #31 kim, #32 me (a draft), #33 dependabot, #52 me."""
    data = fixture()
    data["scoped"]["org:acme"][1]["isDraft"] = True
    return data


def search_fixture(**extra):
    """The All tab's fixture with #52, the last of five, titled for a search; extra replaces fixture keys such as
    fail."""
    data = all_fixture()
    data["scoped"]["org:beta"][1]["title"] = "Fix login timeout"
    data.update(extra)
    return data


def texts(listed):
    return [getattr(row, "text", "") for row in listed.rows]


def test_scope_query():
    assert search.scope_query(BOTH, "mine") == f"is:pr is:open archived:false {TERMS} sort:updated-desc"
    narrowed = search.scope_query(core.Scope(repos=("acme/app", "beta/svc")), "mine")
    assert "repo:acme/app repo:beta/svc" in narrowed and "org:" not in narrowed, narrowed  # --repo narrows it too
    searched = search.scope_query(BOTH, "mine", text=' login  "x" is:closed org:other\\ ')
    assert searched == (  # typed qualifiers stay text
        f'is:pr is:open archived:false {TERMS} "login x is:closed org:other" sort:updated-desc'
    ), searched
    assert search.scope_query(BOTH, "mine", text=' " ') == search.scope_query(BOTH, "mine")


def test_every_open_pull_request_of_the_owners_is_listed_and_paged(monkeypatch):
    with FakeGitHub(all_fixture()) as github:
        gh = GitHubProvider()
        page = gh.list_scope(BOTH, "mine")  # every pull request of both owners, not only the viewer's
        assert [r.number for r in page.rows] == [51, 31, 32, 33, 52] and page.total == 5 and page.cursor is None, page
        assert {r.author for r in page.rows} == {"zoe", "kim", "me", "dependabot"}
        assert TERMS in json.loads(github.calls()[-1]["stdin"])["variables"]["q"]
        monkeypatch.setattr(search, "PAGE", 2)  # pages of two: the next page carries on across both owners
        first = gh.list_scope(BOTH, "mine")
        second = gh.list_scope(BOTH, "mine", after=first.cursor)
        third = gh.list_scope(BOTH, "mine", after=second.cursor)
        assert [[r.number for r in p.rows] for p in (first, second, third)] == [[51, 31], [32, 33], [52]]
        assert (first.cursor, second.cursor, third.cursor) == ("2", "4", None)


def test_a_search_matches_across_the_scope():
    with FakeGitHub(search_fixture()):
        found = GitHubProvider().list_scope(BOTH, "mine", text="LOGIN")
        assert [r.number for r in found.rows] == [52] and found.total == 1 and found.cursor is None, found


async def test_all_tab():
    """The default view (Mine) has the All tab: every open pull request of both owners, filtered like the others,
    while the top bar's counts, Mine and To Review stay what they were."""
    with FakeGitHub(all_fixture()) as github:
        tui = make_app(github, BOTH)
        async with tui.run_test(size=(100, 40)) as pilot:
            await settle(pilot)
            main = tui.main
            tabs = main.query_one("#tabs")
            listed = main.query_one("#list")
            assert main.scope_kind == "mine" and tabs.get_tab("all").display, (
                "the All tab is hidden in the default scope"
            )
            assert str(tabs.get_tab("all").label) == "4 All [5]", tabs.get_tab("all").label
            assert "review 2" in main.sub_title and "mine 1" in main.sub_title, (
                main.sub_title
            )  # the bar follows the scope
            calls = [c["stdin"] for c in github.calls() if "search(" in c["stdin"]]
            assert "mine: search(" in calls[0] and "all: search(" in calls[1], calls  # Mine and To Review paint first
            await pilot.press("4")
            await settle(pilot)
            assert main.tab == "all" and pr_numbers(listed) == [31, 32, 33, 51, 52], pr_numbers(listed)
            assert [r.repo for r in listed.rows if isinstance(r, core.GroupRow)] == ["beta/svc", "acme/app", "acme/lib"]
            assert any("5 open in acme, beta" in text for text in texts(listed)), listed.rows
            await pilot.press("a")  # all -> me
            assert pr_numbers(listed) == [32, 52], pr_numbers(listed)
            await pilot.press("a", "a", "a")  # others, bots, all
            await pilot.press("m")
            assert pr_numbers(listed) == [32, 52], pr_numbers(listed)
            await pilot.press("m", "d")  # draft only
            assert pr_numbers(listed) == [32], pr_numbers(listed)
            await pilot.press("d", "slash", *"beta/", "enter")  # the text filter reads the owner
            assert pr_numbers(listed) == [51, 52], pr_numbers(listed)
            main.filter = ""  # the filter box is cleared the way esc clears it
            main.show_list()
            assert pr_numbers(listed) == [31, 32, 33, 51, 52], pr_numbers(listed)
            await pilot.press("r")  # a refresh keeps the tab and its rows
            await settle(pilot)
            assert main.tab == "all" and pr_numbers(listed) == [31, 32, 33, 51, 52], pr_numbers(listed)
            await pilot.press("1")
            assert pr_numbers(listed) == [5]
            await pilot.press("3")
            assert pr_numbers(listed) == [7, 9]
            assert not github.posts()
        state = core.State(github.dir / "state.json")
        state.save(tab="all")  # quit on All: the next start opens on All, not on To Review
        again = make_app(github, BOTH, state=state)
        async with again.run_test(size=(100, 40)) as pilot:
            await settle(pilot)
            assert again.main.tab == "all" and len(pr_numbers(again.main.query_one("#list"))) == 5


async def test_all_tab_loads_more_than_a_page(monkeypatch):
    """More than a page: a Load more row, then the rest."""
    with FakeGitHub(all_fixture()) as github:
        tui = make_app(github, BOTH)
        monkeypatch.setattr(search, "PAGE", 3)
        async with tui.run_test(size=(100, 40)) as pilot:
            await settle(pilot)
            main = tui.main
            await pilot.press("4")
            await settle(pilot)
            listed = main.query_one("#list")
            assert pr_numbers(listed) == [31, 32, 51]
            more = [r for r in listed.rows if type(r).__name__ == "LoadMore"]
            assert more and "(3 of 5 shown)" in more[0].text, more
            main.load_more()
            await settle(pilot)
            assert pr_numbers(listed) == [31, 32, 33, 51, 52]


def searches(github):
    """The searches for a typed phrase the app sent, as their queries."""
    queries = [json.loads(c["stdin"])["variables"]["q"] for c in github.calls() if "all: search(" in c["stdin"]]
    return [query for query in queries if '"' in query]


async def test_all_tab_search(monkeypatch):
    """/ on the All tab narrows the loaded rows at once and, after a pause, searches GitHub across the scope: a pull
    request on a page not loaded yet is found, esc brings the paged list back, and Mine never searches."""
    monkeypatch.setattr(search, "PAGE", 3)  # #52 is on the second page, not loaded
    with FakeGitHub(search_fixture()) as github:
        tui = make_app(github, BOTH)
        async with tui.run_test(size=(100, 40)) as pilot:
            await settle(pilot)
            main = tui.main
            listed, tabs = main.query_one("#list"), main.query_one("#tabs")
            await pilot.press("4")
            await settle(pilot)
            assert pr_numbers(listed) == [31, 32, 51], pr_numbers(listed)
            await pilot.press("slash", *"login")
            assert pr_numbers(listed) == [] and not searches(github), (
                pr_numbers(listed),
                searches(github),
            )  # no call per key
            await pilot.pause(0.6)
            await settle(pilot)
            assert pr_numbers(listed) == [52], pr_numbers(listed)
            assert len(searches(github)) == 1 and TERMS in searches(github)[0], searches(github)
            assert any('1 found for "login" in acme, beta' in t for t in texts(listed)), texts(listed)
            assert str(tabs.get_tab("all").label) == "4 All [1]", tabs.get_tab("all").label
            assert not any("load " in t for t in texts(listed)), texts(listed)
            await pilot.press("escape")  # clearing: the paged list as it was
            await settle(pilot)
            assert main.filter == "" and pr_numbers(listed) == [31, 32, 51], pr_numbers(listed)
            assert any("(3 of 5 shown)" in t for t in texts(listed)) and str(tabs.get_tab("all").label) == "4 All [5]"
            await pilot.press("1", "slash", *"login")  # Mine narrows only
            await pilot.pause(0.6)
            await settle(pilot)
            assert len(searches(github)) == 1, searches(github)
            await pilot.press("escape")
            assert not github.posts()


async def test_a_failed_search_keeps_the_loaded_rows(monkeypatch):
    monkeypatch.setattr(search, "PAGE", 3)
    with FakeGitHub(search_fixture(fail={"search": "search is down"})) as github:
        tui = make_app(github, BOTH)
        async with tui.run_test(size=(100, 40)) as pilot:
            await settle(pilot)
            main = tui.main
            listed = main.query_one("#list")
            await pilot.press("4")
            await settle(pilot)
            await pilot.press("slash", *"change 3")
            await pilot.pause(0.6)
            await settle(pilot)
            assert len(searches(github)) == 1 and pr_numbers(listed) == [31, 32], pr_numbers(listed)  # matches stay
            assert any(t.startswith("search failed: ") and "search is down" in t for t in texts(listed)), texts(listed)
            assert main.query_one("#filter").has_focus, "the filter lost focus"
            await pilot.press("escape")
            await settle(pilot)
            assert pr_numbers(listed) == [31, 32, 51] and not any("search failed" in t for t in texts(listed))
