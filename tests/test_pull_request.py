# SPDX-FileCopyrightText: 2026 Cristiano Carvalho
# SPDX-License-Identifier: Apache-2.0
"""One pull request read from the forge: its threads under their lines, the conversation, commits and checks, a head
that moves while loading, and the cache that shows the last read at once."""

import pytest

from fake_github import HEAD, MOVED, NOW, FakeGitHub, comment, fixture, load, load_pr, thread
from morann import core
from morann.github import GitHubProvider, parse
from support import refused


def test_threads_sit_under_their_lines():
    with FakeGitHub(fixture()) as github:
        pr = load()
        kinds = [call["args"][:2] for call in github.calls()]
        assert kinds == [["api", "graphql"], ["api", "--paginate"], ["api", "repos/acme/app/pulls/7"]], kinds
    assert pr.head == HEAD and pr.viewer == "me" and pr.author == "sam" and pr.files[0].path == "lib/a.py"
    t1 = pr.thread("T1")
    assert (t1.path, t1.line, t1.side, t1.resolved, t1.root.id, [c.author for c in t1.comments]) == (
        "lib/a.py",
        3,
        "RIGHT",
        False,
        101,
        ["ann", "sam"],
    )
    assert pr.thread("T2").resolved and pr.thread("T3").outdated and pr.thread("T3").line is None
    drafts = core.Drafts("acme/app", 7)
    rows = core.file_rows(pr, 0, drafts, now=NOW)
    texts = [row.text for row in rows]
    under_re = texts.index("import re")
    assert rows[under_re + 1].kind == "thread" and rows[under_re + 1].thread == "T1"
    assert rows[under_re + 2].text.startswith("ann 2d\nWhy re?") and rows[under_re + 3].text.startswith("> sam 2d")
    under_sys = texts.index("import sys")
    collapsed = rows[under_sys + 1]
    assert (
        collapsed.thread == "T2"
        and collapsed.text == "+ ann: sys is still used [resolved]"
        and collapsed.style == "dim"
    )
    outdated = texts.index("threads not on a line of this diff (outdated)")
    assert rows[outdated + 1].thread == "T3" and "[outdated]" in rows[outdated + 1].text
    assert all(row.thread != "T4" for row in rows)
    opened = core.file_rows(pr, 0, drafts, overrides={"T2": True}, now=NOW)
    assert any(row.thread == "T2" and row.kind == "comment" for row in opened)
    folded = core.file_rows(pr, 0, drafts, overrides={"T1": False}, now=NOW)
    assert [row.text for row in folded if row.thread == "T1"] == ["+ ann: Why re? (2)"]
    hidden = core.file_rows(pr, 0, drafts, unresolved_only=True, now=NOW)
    assert all(row.thread != "T2" for row in hidden)
    drafts.toggle_resolve(pr.thread("T2"))  # a pending unresolve keeps the thread visible
    assert any(row.thread == "T2" for row in core.file_rows(pr, 0, drafts, unresolved_only=True, now=NOW))
    for index in (1, 2, 3):  # binary, renamed without changes, too large
        assert core.file_rows(pr, index, drafts)[1].kind == "info"
    assert pr.file("docs/odd.md").lines[-1].text == "a b"  # one JSON line per file, even with U+2028 inside
    pending = parse.parse_threads([thread("T9", 1, comments=[comment(9, "me", "draft on github", state="PENDING")])])
    assert pending[0].comments[0].pending


def test_conversation_timeline():
    with FakeGitHub(fixture()):
        pr = load()
    talk = [row.text for row in core.conversation_rows(pr, core.Drafts("acme/app", 7), now=NOW)]
    assert talk[0] == "Use json #7" and talk[1] == "sam wants to merge 2 commits into main from json"
    assert talk[2] == "what needs you"  # then what waits on the viewer (me: nothing here but checks)
    described = talk.index("sam commented \nWhy\nBecause fast.")  # the description, as the author's comment
    assert all(not text.startswith(("ann", "bob")) for text in talk[:described])
    assert "ann commented 3 days ago\nLooks good" in talk and "bob requested changes 2 days ago\nPlease fix" in talk
    assert not any(text.startswith("ann reviewed") for text in talk)  # an empty COMMENTED review is inline only
    assert "gone.py line 1" in talk and "lib/a.py line 3" in talk  # review threads in the timeline, under file and line
    assert "This branch has no conflicts with the base branch" in talk and "Review required" in talk  # the merge box


def test_a_head_that_moves_while_loading_is_read_again():
    data = fixture()
    data["prs"]["acme/app#7"]["heads"] = [HEAD, MOVED, MOVED, MOVED]
    with FakeGitHub(data) as github:
        pr = load()
        assert pr.head == MOVED and len([c for c in github.calls() if c["args"][:2] == ["api", "--paginate"]]) == 2


def test_a_head_that_never_settles_is_an_error():
    data = fixture()
    data["prs"]["acme/app#7"]["heads"] = [HEAD, MOVED, HEAD, MOVED, HEAD, MOVED, HEAD]
    with FakeGitHub(data), refused(core.ForgeError, "kept getting new commits"):
        load()


def test_a_missing_pull_request_is_an_error():
    with FakeGitHub(fixture()), refused(core.ForgeError, "not found"):
        load_pr(GitHubProvider(), "acme/app", 404)


def test_cache():
    """A pull request is read in two steps (the conversation, commits and checks first, then the files) and its
    answers cached on disk, so reopening it shows the last read at once, marked stale until the fresh one lands."""
    with FakeGitHub(fixture()) as github:
        early = []
        raw = GitHubProvider().fetch_pr(
            "acme/app", 7, on_conversation=lambda partial: early.append(len(github.calls()))
        )
        assert early == [1]  # after the GraphQL read, before the files
        partial = GitHubProvider().build_pr("acme/app", 7, {"data": raw["data"], "files": None})
        assert partial.files_loading and partial.files == [] and partial.commits and partial.checks
        cache = core.PrCache(github.dir / "prs")
        assert cache.get("acme/app", 7) is None
        cache.put("acme/app", 7, raw)
        cached = GitHubProvider().build_pr("acme/app", 7, cache.get("acme/app", 7), stale=True)
        assert (
            cached.stale
            and not cached.files_loading
            and [f.path for f in cached.files] == [f.path for f in load().files]
        )
        cache.path("acme/app", 7).write_text("{broken")
        assert cache.get("acme/app", 7) is None  # a damaged entry is a miss, never an error
        cache.KEEP = 1
        cache.put("acme/app", 7, raw)
        cache.put("acme/app", 5, raw)
        assert len(list((github.dir / "prs").glob("*/*/*.json"))) == 1  # the oldest go


def test_commits_checks_and_tab_labels():
    """Commits, checks and the timeline come with the pull request; each tab shows its count."""
    with FakeGitHub(fixture()):
        pr = load()
    assert [(c.sha[:7], c.headline, c.author) for c in pr.commits] == [
        ("ccccccc", "Use json", "sam"),
        ("ddddddd", "Keep re", "Sam Local"),
    ]
    assert pr.commit_total == 2
    assert [(c.name, c.state, c.required, c.workflow) for c in pr.checks] == [
        ("test", "fail", True, "CI"),
        ("lint", "pending", False, ""),
        ("deploy/preview", "pass", False, ""),
        ("docs", "skip", False, "CI"),
    ]
    label = core.TabLabel
    assert core.tab_labels(pr) == {
        "conversation": label("1", "Conversation", "2"),
        "commits": label("2", "Commits", "2"),
        "checks": label("3", "Checks", "1", "bad"),  # the failing ones, in red
        "files": label("4", "Files changed", "5"),
    }  # each with its key
    narrow = core.tab_labels(pr, narrow=True)
    assert [item.plain() for item in narrow.values()] == ["1 Talk [2]", "2 Commits [2]", "3 Checks [1]", "4 Files [5]"]
    assert sum(len(item.plain(False)) + 2 for item in narrow.values()) <= 70  # all four fit 70 columns
    assert core.tab_labels(None)["files"] == label("4", "Files changed")  # nothing read yet: no count
    assert label("1", "Mine").plain() == "1 Mine"  # no count, no badge
    commits = [row for row in core.commit_rows(pr, now=NOW) if row.kind == "commit"]
    assert [(row.number, row.author, row.when) for row in commits] == [
        ("ccccccc", "sam", "4d"),
        ("ddddddd", "Sam Local", "2d"),
    ]
    assert commits[0].link == "https://github.com/acme/app/pull/7/commits/" + "c" * 40
    checks = [row for row in core.check_rows(pr) if row.kind == "check"]
    assert [(row.body, row.badges, row.link, row.when) for row in checks] == [  # failing first, with why
        (
            "CI / test",
            ("×", "required"),
            "https://github.com/acme/app/pull/7/checks?check_run_id=555",
            "failure: 2 tests failed",
        ),  # another app's details link is never opened: GitHub's page for the run
        ("lint", ("•",), "https://github.com/acme/app/pull/7/checks?check_run_id=556", "in progress"),
        (
            "deploy/preview",
            ("✓",),
            "https://github.com/acme/app/pull/7/checks",
            "success",
        ),  # no run: the Checks tab
        ("CI / docs", ("-",), "https://github.com/acme/app/actions/runs/9/job/10", "skipped"),
    ]  # an Actions job page
    talk = core.conversation_rows(pr, core.Drafts(pr.repo, pr.number), now=NOW)
    order = [row.text.split("\n")[0] for row in talk if row.kind in ("comment", "event") and not row.thread]
    assert order == [
        "sam commented ",
        "sam added commit ccccccc Use json  4 days ago",
        "ann commented 3 days ago",
        "Sam Local added commit ddddddd Keep re  2 days ago",
        "bob requested changes 2 days ago",
    ], order


@pytest.mark.parametrize(
    ("node", "state"),
    [
        ({"__typename": "CheckRun", "name": "x", "status": "COMPLETED", "conclusion": "SKIPPED"}, "skip"),
        ({"__typename": "StatusContext", "context": "y", "state": "ERROR"}, "fail"),
    ],
)
def test_check_states(node, state):
    assert parse.parse_check(node).state == state
