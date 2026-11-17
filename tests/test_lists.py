# SPDX-FileCopyrightText: 2026 Cristiano Carvalho
# SPDX-License-Identifier: Apache-2.0
"""The list queries and what comes back: both lists in one call, the wider scopes paged, the author filter and the
groups by repository."""

import json

import pytest

from fake_github import FakeGitHub, fixture, search_node
from morann import core
from morann.github import GitHubProvider, client, parse, search
from morann.github.client import Gh
from support import refused

ACME = core.Scope(owners=("acme",))


def test_list_queries():
    queries = search.list_queries(ACME)
    assert queries["mine"] == "is:pr is:open archived:false org:acme sort:updated-desc author:@me", queries
    assert queries["review"].endswith("org:acme sort:updated-desc review-requested:@me"), queries
    assert not ACME.several_owners() and core.Scope(owners=("a", "b")).several_owners()
    repos = search.list_queries(core.Scope(repos=("acme/app", "acme/lib")))["mine"]
    assert "repo:acme/app repo:acme/lib" in repos and "org:" not in repos


def test_repository_names():
    assert core.check_repo("acme/.github") == "acme/.github" and core.check_repo("acme/_tools") == "acme/_tools"


@pytest.mark.parametrize("bad", ["acme", "../etc", "acme/..", "acme/.", ".acme/app", "a b/c", "acme/app;rm"])
def test_bad_repository_names_are_refused(bad):
    with pytest.raises(core.UsageError):
        core.check_repo(bad)


def test_both_lists_come_in_one_call():
    with FakeGitHub(fixture()) as github:
        lists = GitHubProvider().list_pull_requests(ACME)
        call = github.calls()[0]
        assert call["args"] == ["api", "graphql", "--method", "POST", "--input", "-"]
        variables = json.loads(call["stdin"])["variables"]
        assert (
            variables["mine"].startswith("is:pr is:open archived:false org:acme") and variables["first"] == search.PAGE
        )
    assert lists.viewer == "me" and [row.key for row in lists.mine] == ["acme/app#5"]
    assert [row.key for row in lists.review] == ["acme/app#7", "acme/lib#9"]  # the empty node (an issue) is skipped
    row = lists.review[1]
    assert (row.repo, row.number, row.title, row.author, row.draft, row.decision, row.checks) == (
        "acme/lib",
        9,
        "Change 9",
        "kim",
        False,
        "CHANGES_REQUESTED",
        "FAILURE",
    )
    mine = lists.mine[0]
    assert mine.draft and mine.decision == "" and mine.checks == "PENDING"


def test_an_expired_login_is_reported():
    with FakeGitHub(fixture(down=True)), pytest.raises(core.ForgeError) as raised:
        GitHubProvider().list_pull_requests(ACME)
    assert str(raised.value) == client.LOGIN


def test_a_missing_gh_is_reported():
    with refused(core.ForgeError, "gh is not installed"):
        Gh(program="/nonexistent/gh").get("user")


def test_scope_kinds():
    """The wider scopes: one organization or the personal account, each with its own search terms and label."""
    assert search.scope_query(ACME, "org:acme") == "is:pr is:open archived:false org:acme sort:updated-desc"
    assert search.scope_query(ACME, "personal", "me") == "is:pr is:open archived:false user:me sort:updated-desc"
    for bad in (("org:a b", ""), ("personal", ""), ("everything", "me")):
        with pytest.raises(core.UsageError):
            search.scope_query(ACME, *bad)
    assert [core.scope_label(kind) for kind in ("mine", "personal", "org:acme")] == ["Mine", "Personal", "acme"]
    assert core.personal_repo("me/notes", "me") and not core.personal_repo("acme/app", "me")
    assert not core.personal_repo("me/x", "")


def test_a_wider_scope_is_paged_and_filtered_by_author(monkeypatch):
    with FakeGitHub(fixture()):
        gh = GitHubProvider()
        assert gh.organizations() == ["acme", "beta"] and gh.viewer_login() == "me"
        with monkeypatch.context() as patch:
            patch.setattr(search, "PAGE", 2)  # pages of two, to see a second one
            first = gh.list_scope(ACME, "org:acme")
            more = gh.list_scope(ACME, "org:acme", after=first.cursor)
        assert ([r.number for r in first.rows], first.total, first.cursor) == ([31, 32], 3, "2")
        assert ([r.number for r in more.rows], more.cursor) == ([33], None) and more.rows[0].bot
        rows = first.rows + more.rows
        assert [r.number for r in core.by_author(rows, "me", "me")] == [32]
        assert [r.number for r in core.by_author(rows, "others", "me")] == [31]
        assert [r.number for r in core.by_author(rows, "bots", "me")] == [33]
        assert len(core.by_author(rows, "all", "me")) == 3


def test_rows_group_by_repository():
    newer = parse.parse_rows([{**search_node(1, repo="acme/lib"), "updatedAt": "2026-11-06T10:00:00Z"}])
    older = parse.parse_rows([search_node(2), search_node(3, repo="acme/lib")])
    grouped = core.group_rows(older + newer)
    assert [(type(r).__name__, getattr(r, "repo", None), getattr(r, "number", None)) for r in grouped] == [
        ("GroupRow", "acme/lib", None),
        ("PrRow", "acme/lib", 1),
        ("PrRow", "acme/lib", 3),
        ("GroupRow", "acme/app", None),
        ("PrRow", "acme/app", 2),
    ]  # the repository updated last comes first
    folded = core.group_rows(older + newer, {"acme/lib"})
    assert [getattr(r, "number", r.repo) for r in folded] == ["acme/lib", "acme/app", 2] and folded[0].collapsed
