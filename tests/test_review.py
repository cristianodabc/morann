# SPDX-FileCopyrightText: 2026 Cristiano Carvalho
# SPDX-License-Identifier: Apache-2.0
"""The details panel, the review payloads (the comment on the conversation and each verdict) with their refusals, and
the merge of a stacked pull request through GitHub's asynchronous merge, against the fake GitHub."""

import json

import pytest

from fake_github import HEAD, MOVED, NOW, FakeGitHub, fixture, load, load_pr, search_node
from morann import core
from morann.github import GitHubProvider, parse
from support import ROOT, refused


def text(lines):
    return ["".join(piece for piece, _style in line) for line in lines]


def detailed_row():
    node = search_node(7)
    node.update(
        headRefName="json",
        baseRefName="main",
        additions=12,
        deletions=3,
        changedFiles=4,
        mergeStateStatus="BEHIND",
        bodyText="Swaps sys for json.\nMore below.",
        labels={"nodes": [{"name": "backend"}]},
        latestReviews={
            "nodes": [
                {
                    "state": "CHANGES_REQUESTED",
                    "author": {"login": "bob", "__typename": "User"},
                    "commit": {"oid": HEAD},
                }
            ]
        },
        reviewRequests={"nodes": [{"requestedReviewer": {"__typename": "Team", "slug": "core"}}]},
        commits={
            "nodes": [
                {
                    "commit": {
                        "statusCheckRollup": {
                            "state": "FAILURE",
                            "contexts": {
                                "checkRunCountsByState": [
                                    {"state": "SUCCESS", "count": 18},
                                    {"state": "FAILURE", "count": 1},
                                    {"state": "IN_PROGRESS", "count": 2},
                                    {"state": "SKIPPED", "count": 0},
                                ],
                                "statusContextCountsByState": [{"state": "SUCCESS", "count": 1}],
                            },
                        }
                    }
                }
            ]
        },
    )
    return parse.parse_rows([node])[0]


def test_panel():
    """The details panel: a title with the number and state, then one line each for who and where, labels and size, the
    status chips and the reviewers; it joins lines, then drops the least important, as room runs out."""
    row = detailed_row()
    assert row.check_counts == (("passed", 19), ("failed", 1), ("running", 2))
    assert text([core.panel_title(row)]) == [" #7  Open  "]
    full = text(core.panel_lines(row, 70, now=NOW))
    assert full == [
        "Change 7",
        "sam  main <- json  opened 5d ago, updated 1d ago",
        " backend  +12 -3  4 files",
        " ● Review required   ✗ 1 failing   ● Behind base ",
        "Reviewers bob ✗  core (team) ● asked",
    ], full
    assert len(full) <= core.PANEL_LINES and all(core.width_of(line) <= 70 for line in full)
    three = text(core.panel_lines(row, 100, 3, now=NOW))  # short and wide: size joins who, the reviewers the chips
    assert three == [
        "Change 7",
        "sam  main <- json  opened 5d ago, updated 1d ago    backend  +12 -3  4 files",
        (" ● Review required   ✗ 1 failing   ● Behind base    Reviewers bob ✗  core (team) ● asked"),
    ], three
    three = text(core.panel_lines(row, 70, 3, now=NOW))  # short and narrow: nothing joins, so size and reviewers drop
    assert three == [
        "Change 7",
        "sam  main <- json  opened 5d ago, updated 1d ago",
        " ● Review required   ✗ 1 failing   ● Behind base ",
    ], three
    two = text(core.panel_lines(row, 40, 2, now=NOW))  # narrow and short: the title and the status chips stay
    assert two[0] == "Change 7" and "Review required" in two[1] and all(core.width_of(line) <= 40 for line in two)
    assert text(core.panel_lines(row, 70, 1, now=NOW)) == ["Change 7"] and core.panel_lines(row, 70, 0) == []
    row.title = "A title long enough to need two lines at forty columns, and then some more"
    wrapped = text(core.panel_lines(row, 40, now=NOW))
    assert wrapped[:2] == ["A title long enough to need two lines at", "forty columns, and then some more"], wrapped
    assert len(wrapped) == 6 and all(core.width_of(line) <= 40 for line in wrapped)
    five = text(core.panel_lines(row, 40, 5, now=NOW))  # one title line, cut, when every line is needed
    assert len(five) == 5 and five[0] == "A title long enough to need two lines..." and five[-1].startswith("Reviewers")
    bare = parse.parse_rows([search_node(9, decision="", checks="")])[0]
    assert text(core.panel_lines(bare, 70, now=NOW)) == ["Change 9", "sam  ? <- ?  opened 5d ago, updated 1d ago"]
    assert core.panel_lines(core.GroupRow("acme/app", 2), 70) == []


def test_no_rule_is_drawn_in_the_terminals_default_color():
    css = (ROOT / "src/morann/app.py").read_text()
    assert "panel-lighten" not in css and "white" not in css
    assert '"white"' not in (ROOT / "src/morann/paint.py").read_text()


def test_review_payloads():
    """A comment on the conversation goes to the issue comments; each verdict is one review; approve and request changes
    are refused on your own pull request, request changes without a summary, and everything under --read-only."""
    with FakeGitHub(fixture()) as github:
        pr = load()
        store = core.DraftStore(github.dir / "drafts")
        drafts = store.load(pr.repo, pr.number)
        drafts.add_note("Looks right to me")
        plan = core.build_plan(pr, drafts, "COMMENT")
        assert core.submit(GitHubProvider(), plan, plan.fingerprint(), store) == ["comment on the conversation"]
        sent = github.posts()[-1]
        assert sent["args"][2:4] == ["POST", "repos/acme/app/issues/7/comments"]
        assert json.loads(sent["stdin"]) == {"body": "Looks right to me"}
        for event, summary in (("APPROVE", ""), ("REQUEST_CHANGES", "Please split this"), ("COMMENT", "A thought")):
            drafts = core.Drafts(pr.repo, pr.number, summary=summary)
            plan = core.build_plan(pr, drafts, event)
            core.submit(GitHubProvider(), plan, plan.fingerprint(), store)
            sent = github.posts()[-1]
            assert sent["args"][2:4] == ["POST", "repos/acme/app/pulls/7/reviews"], sent
            expected = {"commit_id": HEAD, "event": event, "comments": [], **({"body": summary} if summary else {})}
            assert json.loads(sent["stdin"]) == expected, sent
        posted = len(github.posts())
        with refused(core.PlanError, "needs a summary"):
            core.build_plan(pr, core.Drafts(pr.repo, pr.number), "REQUEST_CHANGES")
        own = load_pr(GitHubProvider(), "acme/app", 5)
        for event in ("APPROVE", "REQUEST_CHANGES"):
            with refused(core.PlanError, "your own pull request"):
                core.build_plan(own, core.Drafts(own.repo, own.number, summary="x"), event)
        note = core.Drafts(pr.repo, pr.number)
        note.add_note("not posted")
        plan = core.build_plan(pr, note, "COMMENT")
        with refused(core.SubmitError, "read-only"):
            core.submit(GitHubProvider(read_only=True), plan, plan.fingerprint(), store)
        assert len(github.posts()) == posted


def test_merge_async():
    """A stacked pull request (its base is another open pull request's branch) merges through GitHub's asynchronous merge:
    the head sha, the method and the default action, then polls until merged, queued or failed. Others merge as before."""
    data = fixture()
    data["prs"]["acme/app#5"]["node"]["baseRef"] = {"associatedPullRequests": {"nodes": [{"number": 4}]}}
    with FakeGitHub(data) as github:
        state = GitHubProvider().read_state("acme/app", 5)
        assert state.stacked_on == 4 and state.auto_method == "squash"
        assert ("Stacked on #4: GitHub merges it with the open pull requests below it", "wait") in core.merge_view(
            state
        )
        assert ("This branch has no conflicts with the base branch", "ok") in core.merge_view(state)
        plan = core.build_action(state, "squash")
        assert plan.stacked_on == 4 and "with the open pull requests below it" in plan.lines()[0]
        github.write(
            {
                **github.data(),
                "async_polls": [
                    {"status": "pending", "details": {"uuid": "u-1", "message": ""}},
                    {"status": "merged", "details": {"message": "merged"}},
                ],
            }
        )
        naps = []
        done = core.run_action(GitHubProvider(), plan, plan.fingerprint(), sleep=naps.append)
        assert done == "squash and merge: merged (acme/app#5)", done
        puts = [p for p in github.posts() if p["args"][2] == "PUT"]
        assert [p["args"][3] for p in puts] == ["repos/acme/app/pulls/5/merge-async"]
        assert json.loads(puts[0]["stdin"]) == {"sha": HEAD, "merge_method": "squash", "merge_action": "default"}
        polls = [c["args"][1] for c in github.calls() if "/merge-async/" in " ".join(c["args"])]
        assert polls == ["repos/acme/app/pulls/5/merge-async/u-1"] * 2 and naps == [2, 2], (polls, naps)
        github.write({**github.data(), "async_polls": [{"status": "enqueued", "details": {"message": "queued"}}]})
        assert core.run_action(GitHubProvider(), plan, plan.fingerprint(), sleep=naps.append).startswith(
            "squash and merge: queued in the merge queue"
        )
        github.write(
            {
                **github.data(),
                "async_polls": [{"status": "failed", "details": {"message": "Required status check is failing"}}],
            }
        )
        with pytest.raises(core.ForgeError) as raised:
            core.run_action(GitHubProvider(), plan, plan.fingerprint(), sleep=naps.append)
        assert str(raised.value) == "the merge failed: Required status check is failing"
        sent = len(github.posts())
        with refused(core.PlanError, "read-only"):  # refused before anything is sent
            core.run_action(GitHubProvider(read_only=True), plan, plan.fingerprint(), sleep=naps.append)
        data = github.data()
        data["prs"]["acme/app#5"]["heads"] = [MOVED]
        github.write(data)
        with pytest.raises(core.HeadMoved):
            core.run_action(GitHubProvider(), plan, plan.fingerprint(), sleep=naps.append)
        data["prs"]["acme/app#5"]["heads"] = [HEAD]
        data["prs"]["acme/app#5"]["node"]["baseRef"] = None  # the pull request below merged: no longer stacked
        github.write(data)
        with refused(core.PlanError, "the stack below it changed"):
            core.run_action(GitHubProvider(), plan, plan.fingerprint(), sleep=naps.append)
        assert len(github.posts()) == sent
        data["prs"]["acme/app#5"]["node"]["baseRef"] = {"associatedPullRequests": {"nodes": [{"number": 4}]}}
        github.write(data)
        close = core.build_action(GitHubProvider().read_state("acme/app", 5), "close")  # other actions ignore the stack
        core.run_action(GitHubProvider(), close, close.fingerprint(), sleep=naps.append)
        assert github.posts()[-1]["args"][2:4] == ["PATCH", "repos/acme/app/pulls/5"]
        data["prs"]["acme/app#5"]["node"]["baseRef"] = None
        github.write(data)
        flat = core.build_action(GitHubProvider().read_state("acme/app", 5), "squash")
        assert flat.stacked_on is None
        core.run_action(GitHubProvider(), flat, flat.fingerprint(), sleep=naps.append)
        assert github.posts()[-1]["args"][3] == "repos/acme/app/pulls/5/merge"  # not stacked: the usual merge
