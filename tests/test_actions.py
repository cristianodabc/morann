# SPDX-FileCopyrightText: 2026 Cristiano Carvalho
# SPDX-License-Identifier: Apache-2.0
"""Pull request actions, re-requesting review and the bulk update, against the fake GitHub."""

import json

import pytest

from fake_github import HEAD, MOVED, FakeGitHub, fixture, load, load_pr, stack_fixture
from morann import cli, core
from morann.github import GitHubProvider
from support import refused

ACME = core.Scope(owners=("acme",))


@pytest.fixture
def update(capsys):
    """Runs `mor update --owner acme` with the flags given; returns (exit status, what it printed, its errors)."""

    def run(*flags):
        status = cli.main(["update", "--owner", "acme", *flags])
        printed = capsys.readouterr()
        return status, printed.out, printed.err

    return run


def test_actions():
    """Merge, update, close, ready and auto-merge: only on your own pull requests, only with the confirmed plan, only
    while the head is the one shown, never with --read-only."""
    with FakeGitHub(fixture()) as github:
        theirs = GitHubProvider().read_state("acme/app", 7)
        assert not theirs.own and {reason for *_rest, reason in core.action_menu(theirs)} == {
            "only on your own pull requests"
        }
        with refused(core.PlanError, "only on your own pull requests"):
            core.build_action(theirs, "squash")
        mine = GitHubProvider().read_state("acme/app", 5)
        assert mine.own and mine.methods == ("merge", "squash") and mine.id == "PR_me"
        menu = {action: reason for action, _label, _key, reason in core.action_menu(mine)}
        assert menu == {
            "merge": "",
            "squash": "",
            "rebase": "the repository does not allow rebase and merge",
            "update": "already up to date with the base branch",
            "close": "",
            "reopen": "already open",
            "ready": "not a draft",
            "draft": "",
            "automerge": "can merge now; auto-merge is for waiting on checks or reviews",
            "noautomerge": "auto-merge is off",
            "rerequest": "",
        }, menu
        plan = core.build_action(mine, "squash")
        assert plan.risky and plan.lines()[0] == f"Squash and merge into main: acme/app#5 at {HEAD[:7]}"
        for confirmed in (None, "x" * 64):  # not the confirmed plan: nothing sent
            with pytest.raises(core.NotConfirmed):
                core.run_action(GitHubProvider(), plan, confirmed)
        assert not github.posts()
        with refused(core.PlanError, "read-only"):  # refused after reading, before any write
            core.run_action(GitHubProvider(read_only=True), plan, plan.fingerprint())
        assert "read-only" in core.why_not(mine, "merge", read_only=True) and not github.posts()
        data = github.data()
        data["prs"]["acme/app#5"]["heads"] = [MOVED]
        github.write(data)
        with refused(core.HeadMoved, "nothing was sent"):  # the head moved after the bar showed it
            core.run_action(GitHubProvider(), plan, plan.fingerprint())
        assert not github.posts()
        data["prs"]["acme/app#5"]["heads"] = [HEAD]
        github.write(data)
        assert core.run_action(GitHubProvider(), plan, plan.fingerprint()) == "squash and merge: done on acme/app#5"
        sent = github.posts()[-1]
        assert sent["args"][:4] == ["api", "--method", "PUT", "repos/acme/app/pulls/5/merge"]
        assert json.loads(sent["stdin"]) == {"merge_method": "squash", "sha": HEAD}

        def run(action, **fields):
            github.set_pr("acme/app#5", **fields)
            state = GitHubProvider().read_state("acme/app", 5)
            step = core.build_action(state, action)
            core.run_action(GitHubProvider(), step, step.fingerprint())
            return github.posts()[-1]

        sent = run("update", mergeStateStatus="BEHIND")
        assert sent["args"][2:4] == ["PUT", "repos/acme/app/pulls/5/update-branch"]
        assert json.loads(sent["stdin"]) == {"expected_head_sha": HEAD}
        sent = run("close", mergeStateStatus="CLEAN")
        assert sent["args"][2:4] == ["PATCH", "repos/acme/app/pulls/5"] and json.loads(sent["stdin"]) == {
            "state": "closed"
        }
        sent = run("reopen", state="CLOSED")
        assert json.loads(sent["stdin"]) == {"state": "open"}
        sent = run("ready", state="OPEN", isDraft=True)
        body = json.loads(sent["stdin"])
        assert "markPullRequestReadyForReview" in body["query"] and body["variables"] == {"id": "PR_me"}
        sent = run("draft", isDraft=False)
        assert "convertPullRequestToDraft" in json.loads(sent["stdin"])["query"]
        sent = run("automerge", mergeStateStatus="BLOCKED", reviewDecision="APPROVED")
        body = json.loads(sent["stdin"])
        assert "enablePullRequestAutoMerge" in body["query"]
        assert body["variables"] == {"id": "PR_me", "method": "SQUASH", "head": HEAD}
        sent = run("noautomerge", autoMergeRequest={"enabledAt": "2026-11-06T10:00:00Z"})
        assert "disablePullRequestAutoMerge" in json.loads(sent["stdin"])["query"]
        for fields, reason in (
            ({"mergeStateStatus": "BLOCKED", "reviewDecision": "REVIEW_REQUIRED"}, "review required"),
            ({"mergeStateStatus": "BLOCKED", "reviewDecision": "APPROVED"}, "checks are red"),
            ({"mergeStateStatus": "DIRTY", "mergeable": "CONFLICTING"}, "conflicts with the base branch"),
            ({"mergeStateStatus": "BEHIND", "mergeable": "MERGEABLE"}, "behind the base branch"),
            ({"mergeStateStatus": "DRAFT", "isDraft": True}, "draft: mark it ready"),
            ({"state": "MERGED", "isDraft": False}, "already merged"),
        ):
            github.set_pr("acme/app#5", **fields)
            assert reason in core.why_not(GitHubProvider().read_state("acme/app", 5), "merge"), (fields, reason)
        github.set_pr("acme/app#5", state="OPEN", mergeStateStatus="CLEAN", mergeable="MERGEABLE")
        plan = core.build_action(GitHubProvider().read_state("acme/app", 5), "merge")
        github.set_pr("acme/app#5", state="MERGED")  # merged elsewhere between the bar and y
        before = len(github.posts())
        with pytest.raises(core.PlanError) as raised:
            core.run_action(GitHubProvider(), plan, plan.fingerprint())
        assert "already merged" in str(raised.value) and "nothing was sent" in str(raised.value)
        assert len(github.posts()) == before


def test_rerequest():
    """Re-request review: by default the people who requested changes or commented, never the author, a bot or someone
    asked already; only on your own pull request, behind the confirmed plan, never read-only."""
    with FakeGitHub(fixture()) as github:
        pr = load_pr(GitHubProvider(), "acme/app", 5)
        assert pr.rerequest_due() and not load().rerequest_due()  # bob reviewed an older head of my pull request
        assert [(r.login, r.state) for r in pr.reviewers] == [
            ("bob", "CHANGES_REQUESTED"),
            ("ann", "COMMENTED"),
            ("kim", "APPROVED"),
            ("me", "COMMENTED"),
        ]
        assert pr.asked == ("zed",)
        mine = GitHubProvider().read_state("acme/app", 5)
        assert mine.candidates() == [
            ("bob", True, "requested changes before the last push"),
            ("ann", True, "commented"),
            ("kim", False, "approved before the last push"),
        ]
        plan = core.build_action(mine, "rerequest")
        assert plan.reviewers == ("bob", "ann") and plan.lines()[0].startswith("Request review again from bob, ann:")
        assert core.build_action(mine, "rerequest", reviewers={"kim", "zed", "eve"}).reviewers == ("kim",)  # known only
        with pytest.raises(core.NotConfirmed):
            core.run_action(GitHubProvider(), plan, None)
        with refused(core.PlanError, "read-only"):
            core.run_action(GitHubProvider(read_only=True), plan, plan.fingerprint())
        assert not github.posts()
        assert core.run_action(GitHubProvider(), plan, plan.fingerprint()) == "re-request review: done on acme/app#5"
        sent = github.posts()[-1]
        assert sent["args"][2:4] == ["POST", "repos/acme/app/pulls/5/requested_reviewers"]
        assert json.loads(sent["stdin"]) == {"reviewers": ["bob", "ann"], "team_reviewers": []}
        theirs = GitHubProvider().read_state("acme/app", 7)
        assert core.why_not(theirs, "rerequest") == "only on your own pull requests"


def test_bulk_update():
    """Your pull requests behind their base: a stack from the bottom, conflicts and (when asked) drafts left out, each
    read again right before its update, which carries that head; confirmed only; never read-only."""
    with FakeGitHub(stack_fixture()) as github:
        items, skipped = core.update_candidates(GitHubProvider(), ACME)
        assert [(i.number, i.stacked_on, i.behind_by) for i in items] == [(20, None, 3), (21, 20, 3), (23, None, 3)]
        assert [(i.number, why) for i, why in skipped] == [(22, "conflicts with its base: update it locally")]
        kept, without = core.update_candidates(GitHubProvider(), ACME, include_drafts=False)
        assert [i.number for i in kept] == [20, 21]
        assert (23, "draft (--no-draft)") in [(i.number, why) for i, why in without]
        fingerprint = core.update_fingerprint(items)
        with pytest.raises(core.NotConfirmed):
            core.run_updates(GitHubProvider(), items, None)
        with pytest.raises(core.PlanError):
            core.run_updates(GitHubProvider(read_only=True), items, fingerprint)
        assert not github.posts()
        github.set_pr("acme/app#23", mergeStateStatus="CLEAN")  # someone updated it meanwhile
        seen = []
        results = core.run_updates(
            GitHubProvider(),
            items,
            fingerprint,
            sleep=lambda s: None,
            progress=lambda item, result: seen.append(item.number),
        )
        assert [(i.number, r) for i, r in results] == [(20, "updated"), (21, "updated"), (23, "already current")]
        assert seen == [20, 21, 23] and not core.update_failed(results)
        puts = [p for p in github.posts() if p["args"][2] == "PUT"]
        assert [p["args"][3] for p in puts] == [
            "repos/acme/app/pulls/20/update-branch",
            "repos/acme/app/pulls/21/update-branch",
        ]
        assert json.loads(puts[0]["stdin"]) == {"expected_head_sha": f"{20:040d}"}
        github.set_pr("acme/app#20", mergeStateStatus="UNKNOWN")  # GitHub has not worked it out yet: wait, then say so
        naps = []
        only = items[:1]
        _item, first = core.run_updates(GitHubProvider(), only, core.update_fingerprint(only), sleep=naps.append)[0]
        assert first.startswith("refused: GitHub is still checking") and naps == [2] * 5


def test_update_command(update):
    """mor update: a dry run without --yes, refused read-only, then each update in order."""
    with FakeGitHub(stack_fixture()) as github:
        status, printed, errors = update()
        assert status == 0 and not github.posts(), errors
        assert (
            "1. acme/app#20 feat-a <- main (3 behind) Change 20" in printed
            and "2. acme/app#21 feat-b <- feat-a (3 behind, on #20)" in printed
            and "dry run: 3 would be updated" in printed
        ), printed
        assert "skip acme/app#22: conflicts" in printed
        status, _printed, errors = update("--yes", "--read-only")
        assert status == 1 and "read-only" in errors and not github.posts()
        status, printed, _errors = update("--yes")
        assert status == 0 and "acme/app#21: updated" in printed and len(github.posts()) == 3, printed


def test_update_command_reports_a_refused_update(update):
    with FakeGitHub(stack_fixture(fail={"update": "Head branch was modified"})):
        status, printed, _errors = update("--yes")
        assert status == 1 and "acme/app#20: refused: Validation Failed: Head branch was modified" in printed


def test_update_command_with_nothing_behind(update):
    with FakeGitHub(fixture()):
        status, printed, _errors = update()
        assert status == 0 and "nothing is behind its base" in printed


def test_update_command_when_the_forge_cannot_be_read(update):
    with FakeGitHub(fixture(down=True)):
        status, _printed, errors = update()
        assert status == 1 and "gh auth login" in errors
