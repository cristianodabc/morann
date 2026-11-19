# SPDX-FileCopyrightText: 2026 Cristiano Carvalho
# SPDX-License-Identifier: Apache-2.0
"""Resuming the viewer's pending review: it is found when the pull request loads, its comments show under their
lines, new comments and replies join it, and one confirmed submit sends it with the chosen verdict instead of creating
a second review. Nothing goes out before that submit, and a pending review that vanished, a refused call or a forge
that cannot do it leaves the drafts in place."""

import json
import re

import pytest

from fake_github import (
    HEAD,
    MOVED,
    NOW,
    FakeGitHub,
    drafted,
    fixture,
    load,
    load_pr,
    pending_fixture,
    pending_review_node,
)
from morann import core
from morann.github import GitHubProvider, parse, queries
from support import make_app, refused, settle

PENDING = core.PendingReview(
    id="PRR_pending", comments=1, body="", commit=HEAD, updated="2026-11-05T08:00:00Z"
)  # what pending_fixture holds


class Bare(GitHubProvider):
    """A forge that cannot resume a pending review."""

    name = "bare"
    label = "Bare"
    host = "bare.test"
    capabilities = frozenset(core.Capability) - {core.Capability.PENDING_REVIEW}


def mutations(github):
    """Every GraphQL mutation sent, as (name, variables), in order."""
    sent = []
    for call in github.posts():
        if "graphql" in call["args"]:
            body = json.loads(call["stdin"])
            sent.append((re.search(r"\{\s*(\w+)\(input", body["query"])[1], body["variables"]))
    return sent


def rest_writes(github):
    return [call["args"][3] for call in github.posts() if "graphql" not in call["args"]]


def planned(github, event, **change):
    """Pull request #7 with the viewer's review pending, its saved drafts (two comments, a reply, two resolve marks and
    a summary) and the plan to send them."""
    pr = load()
    store = core.DraftStore(github.dir / "drafts")
    drafts = drafted(store, pr)
    for key, value in change.items():
        setattr(drafts, key, value)
    return pr, store, core.build_plan(pr, drafts, event)


# Finding the pending review and showing it.


def test_the_viewers_pending_review_is_found_when_the_pull_request_loads():
    with FakeGitHub(pending_fixture()):
        pr = load()
        assert pr.pending == PENDING
        assert GitHubProvider().pending_review("acme/app", 7) == PENDING  # and when it is read again on its own


def test_a_pull_request_without_one_has_none():
    with FakeGitHub(fixture()):
        assert load().pending is None and GitHubProvider().pending_review("acme/app", 7) is None


def test_only_the_viewers_own_pending_review_counts():
    """GitHub shows a pending review to its author alone; one that is anyone else's is ignored all the same."""
    theirs = {"pendingReviews": {"nodes": [pending_review_node(author="bob")]}}
    mixed = {"pendingReviews": {"nodes": [pending_review_node(author="bob"), pending_review_node(author="Me", id="X")]}}
    assert parse.resumable(theirs, "me") is None and parse.resumable({}, "me") is None  # an older cached snapshot too
    assert parse.resumable(mixed, "me").id == "X"  # the viewer's, whatever the case of the login
    assert parse.resumable(mixed, "") is None
    with FakeGitHub(fixture()) as github:
        data = github.data()
        data["prs"]["acme/app#7"]["node"]["pendingReviews"] = theirs["pendingReviews"]
        github.write(data)
        assert load().pending is None and GitHubProvider().pending_review("acme/app", 7) is None


def test_its_comments_show_under_their_lines_marked_as_pending():
    with FakeGitHub(pending_fixture()):
        pr = load()
        rows = core.conversation_rows(pr, core.Drafts(pr.repo, pr.number), now=NOW)
        pending = [row for row in rows if "pending on github.com" in row.badges]
        assert [row.body for row in pending] == ["needs a docstring"] and pending[0].post is None  # not editable yet
        assert pr.thread("T5").comments[0].pending


# Resuming it: one plan, one review.


def test_a_plan_resumes_the_pending_review():
    with FakeGitHub(pending_fixture()) as github:
        _pr, _store, plan = planned(github, "REQUEST_CHANGES")
        assert plan.resume == {"id": "PRR_pending", "comments": 1, "summary": "", "commit": HEAD}
        lines = plan.lines()
        assert lines[2] == "Review: request changes, sent with your pending review (1 comment already in it)"
        assert "Reply on lib/a.py:3 (in the pending review):" in lines and plan.warnings == ()


def test_a_confirmed_submit_adds_to_the_pending_review_and_submits_it():
    """Each comment and reply goes into the pending review, which is then submitted with the verdict and the summary;
    no second review is created. Resolves and the rest go as before."""
    with FakeGitHub(pending_fixture()) as github:
        pr, store, plan = planned(github, "REQUEST_CHANGES")
        assert not github.posts()  # planning sent nothing
        posted = core.submit(GitHubProvider(), plan, plan.fingerprint(), store)
        assert [name for name, _ in mutations(github)] == [
            "addPullRequestReviewThread",
            "addPullRequestReviewThread",
            "addPullRequestReviewThreadReply",
            "submitPullRequestReview",
            "resolveReviewThread",
            "unresolveReviewThread",
        ]
        assert not rest_writes(github)  # no POST to /reviews, no REST reply
        sent = dict(enumerate(mutations(github)))
        assert sent[0][1] == {
            "review": "PRR_pending",
            "path": "lib/a.py",
            "line": 13,
            "side": "RIGHT",
            "body": "call done() last?",
        }
        assert sent[1][1] == {
            "review": "PRR_pending",
            "path": "lib/a.py",
            "line": 2,
            "side": "LEFT",
            "body": "sys is used in main",
        }
        assert sent[2][1] == {"review": "PRR_pending", "thread": "T1", "body": "ok, makes sense"}
        assert sent[3][1] == {"review": "PRR_pending", "event": "REQUEST_CHANGES", "body": "Two small things"}
        calls = [call["args"] for call in github.calls()]
        read = next(
            i for i, args in enumerate(calls) if "graphql" in args and "PendingReview" in github.calls()[i]["stdin"]
        )
        first_write = next(i for i, call in enumerate(github.calls()) if call in github.posts())
        assert read < first_write  # the pending review is read again before anything is sent
        assert posted[-3] == "pending review (request changes)" and len(posted) == 6
        assert not store.path(pr.repo, pr.number).exists()
        assert load().pending is None  # it was submitted: GitHub has no pending review now


@pytest.mark.parametrize("event", ["COMMENT", "APPROVE"])
def test_a_resumed_review_submits_with_nothing_new(event):
    """Nothing drafted: the pending review goes as it is, with the verdict, and without a summary the forge keeps its own."""
    with FakeGitHub(pending_fixture()) as github:
        pr = load()
        store = core.DraftStore(github.dir / "drafts")
        plan = core.build_plan(pr, core.Drafts(pr.repo, pr.number), event)
        assert plan.has_review() and plan.lines()[3] == "Summary: (none)"
        core.submit(GitHubProvider(), plan, plan.fingerprint(), store)
        assert mutations(github) == [("submitPullRequestReview", {"review": "PRR_pending", "event": event})]


def test_the_summary_already_on_the_pending_review_counts():
    """Request changes needs a summary; the one on the pending review is enough, and the plan says it stays."""
    data = pending_fixture()
    data["prs"]["acme/app#7"]["node"]["pendingReviews"] = {"nodes": [pending_review_node(body="Please look at this")]}
    with FakeGitHub(data):
        pr = load()
        plan = core.build_plan(pr, core.Drafts(pr.repo, pr.number), "REQUEST_CHANGES")
        assert plan.lines()[3] == "Summary: (none new; the pending review keeps its own)"
    with FakeGitHub(pending_fixture()):
        pr = load()
        with refused(core.PlanError, "request changes needs a summary"):
            core.build_plan(pr, core.Drafts(pr.repo, pr.number), "REQUEST_CHANGES")


def test_a_pending_review_started_at_an_older_head_is_said_so():
    data = pending_fixture()
    data["prs"]["acme/app#7"]["node"]["pendingReviews"] = {"nodes": [pending_review_node(commit={"oid": MOVED})]}
    with FakeGitHub(data):
        pr = load()
        plan = core.build_plan(pr, core.Drafts(pr.repo, pr.number), "COMMENT")
        assert plan.warnings == (
            f"your pending review was started at {MOVED[:7]}; the pull request is at {HEAD[:7]} now",
        )


# What can go wrong.


def test_a_pending_review_that_vanished_posts_nothing_and_keeps_the_drafts():
    """Submitted or discarded on GitHub between the load and the submit: it is read again, the user is told, and
    every draft stays."""
    with FakeGitHub(pending_fixture()) as github:
        pr, store, plan = planned(github, "COMMENT")
        data = github.data()
        data["prs"]["acme/app#7"]["node"]["pendingReviews"] = {"nodes": []}
        github.write(data)
        with pytest.raises(core.PendingGone, match="changed: it was submitted, discarded or replaced there"):
            core.submit(GitHubProvider(), plan, plan.fingerprint(), store)
        assert not github.posts() and store.load(pr.repo, pr.number).count() == 6
        assert core.build_plan(load(), store.load(pr.repo, pr.number), "COMMENT").resume is None  # the old flow now


def test_a_pending_review_replaced_by_another_posts_nothing():
    with FakeGitHub(pending_fixture()) as github:
        pr, store, plan = planned(github, "COMMENT")
        data = github.data()
        data["prs"]["acme/app#7"]["node"]["pendingReviews"] = {"nodes": [pending_review_node(id="PRR_other")]}
        github.write(data)
        with pytest.raises(core.PendingGone):
            core.submit(GitHubProvider(), plan, plan.fingerprint(), store)
        assert not github.posts() and store.load(pr.repo, pr.number).count() == 6


def test_a_viewer_without_permission_keeps_the_drafts():
    """The pending review cannot be read, or the forge refuses to add to it: the message is GitHub's own."""
    with FakeGitHub(pending_fixture(fail={"pending": "Resource not accessible by personal access token"})) as github:
        pr, store, plan = planned(github, "COMMENT")
        with pytest.raises(
            core.SubmitError, match="nothing was posted; GitHub refused the rest: .*not accessible"
        ) as raised:
            core.submit(GitHubProvider(), plan, plan.fingerprint(), store)
        assert raised.value.posted == [] and not github.posts() and store.load(pr.repo, pr.number).count() == 6
    refusal = "Must have push access to pull request reviews"
    with FakeGitHub(pending_fixture(fail={"addPullRequestReviewThread": refusal})) as github:
        pr, store, plan = planned(github, "COMMENT")
        with pytest.raises(core.SubmitError, match="nothing was posted") as raised:
            core.submit(GitHubProvider(), plan, plan.fingerprint(), store)
        assert refusal in str(raised.value) and "stays as drafts" in str(raised.value)
        assert (
            store.load(pr.repo, pr.number).count() == 6 and github.data()["prs"]["acme/app#7"]["node"]["pendingReviews"]
        )


def test_a_refused_submit_keeps_the_pending_review_resumable():
    """The comments were added to the pending review, so they leave the drafts; the submit was refused, so the rest
    stays, and the next try resumes the same review."""
    with FakeGitHub(pending_fixture(fail={"submitPullRequestReview": "Review body can't be blank"})) as github:
        pr, store, plan = planned(github, "COMMENT")
        with pytest.raises(core.SubmitError) as raised:
            core.submit(GitHubProvider(), plan, plan.fingerprint(), store)
        assert raised.value.posted == [
            "comment on lib/a.py:13 (pending)",
            "comment on lib/a.py:2 (pending)",
            "reply on lib/a.py:3 (pending)",
        ]
        assert "Review body can't be blank" in str(raised.value)
        left = store.load(pr.repo, pr.number)
        assert not left.comments and not left.replies and left.summary and len(left.resolves) == 2
        data = github.data()
        assert data["prs"]["acme/app#7"]["node"]["pendingReviews"]["nodes"][0]["id"] == "PRR_pending"


def test_a_comment_line_that_left_the_diff_is_refused_before_anything_is_sent():
    """A draft whose line is not in the diff any more stops the plan, with or without a pending review; a line GitHub
    refuses later leaves the drafts as they are."""
    with FakeGitHub(pending_fixture()) as github:
        pr = load()
        store = core.DraftStore(github.dir / "drafts")
        drafts = store.load(pr.repo, pr.number)
        drafts.add_comment("lib/a.py", "RIGHT", 99, "far below")
        with refused(core.PlanError, "the draft on lib/a.py:99 is no longer in the diff"):
            core.build_plan(pr, drafts, "COMMENT")
        assert not github.posts()
    with FakeGitHub(pending_fixture(fail={"addPullRequestReviewThread": "Line must be part of the diff"})) as github:
        pr, store, plan = planned(github, "COMMENT")
        with pytest.raises(core.SubmitError, match="Line must be part of the diff"):
            core.submit(GitHubProvider(), plan, plan.fingerprint(), store)
        assert store.load(pr.repo, pr.number).count() == 6


def test_no_pending_review_is_the_old_flow():
    with FakeGitHub(fixture()) as github:
        pr = load()
        store = core.DraftStore(github.dir / "drafts")
        plan = core.build_plan(pr, drafted(store, pr), "APPROVE")
        assert plan.resume is None and plan.warnings == () and plan.lines()[2] == "Review: approve"
        core.submit(GitHubProvider(), plan, plan.fingerprint(), store)
        assert rest_writes(github)[0] == "repos/acme/app/pulls/7/reviews"
        assert [name for name, _ in mutations(github)] == ["resolveReviewThread", "unresolveReviewThread"]
        assert not any("PendingReview" in call["stdin"] for call in github.calls())


def test_a_forge_that_cannot_resume_keeps_the_old_flow_and_refuses_a_resumed_plan():
    with FakeGitHub(pending_fixture()) as github:
        bare = Bare()
        pr = load_pr(bare, "acme/app", 7)
        assert pr.pending == PENDING
        store = core.DraftStore(github.dir / "drafts")
        plan = core.build_plan(pr, drafted(store, pr), "COMMENT")
        assert plan.resume is None and core.pending_review(bare) in plan.warnings  # GitHub's old refusal is the warning
        resumed = core.build_plan(load(), core.Drafts(pr.repo, pr.number), "COMMENT")
        with pytest.raises(core.SubmitError, match="nothing was posted; Bare has no resuming a pending review"):
            core.submit(bare, resumed, resumed.fingerprint(), store)
        assert not github.posts()


def test_a_pending_review_is_never_written_read_only():
    with FakeGitHub(pending_fixture()) as github:
        reader = GitHubProvider(read_only=True)
        assert reader.pending_review("acme/app", 7) == PENDING  # reading it is fine
        for write in (
            lambda: reader.add_pending_comment("acme/app", 7, "PRR_pending", "lib/a.py", "RIGHT", 13, "x"),
            lambda: reader.add_pending_reply("acme/app", 7, "PRR_pending", "T1", "x"),
            lambda: reader.submit_pending_review("acme/app", 7, "PRR_pending", "COMMENT", ""),
        ):
            with pytest.raises(core.ForgeError, match="read-only"):
                write()
        assert not github.posts()
        assert queries.PENDING_QUERY.startswith("query PendingReview")


# In the app.


async def open_files(pilot, main):
    await settle(pilot)
    await pilot.press("tab", "4")
    await settle(pilot)
    diff = main.query_one("#diff")
    diff.go(
        next(i for i, row in enumerate(diff.rows) if row.anchor and row.anchor[2] == 13 and row.anchor[1] == "RIGHT")
    )
    return diff


async def test_resume_and_comment_in_the_app():
    """The header says a pending review waits; c adds to it as a draft (nothing is sent), and the bar sends it as one
    review with a resumed one's name."""
    with FakeGitHub(pending_fixture()) as github:
        tui = make_app(github)
        async with tui.run_test(size=(110, 40)) as pilot:
            main = tui.main
            await open_files(pilot, main)
            assert "Pending review: 1 comment" in str(main.pr_header()) and not main.reviewing()
            await pilot.press("c")
            await settle(pilot)
            assert type(tui.screen).__name__ == "ChoiceScreen"
            assert [label for _keys, label, _value in tui.screen.choices] == [
                "Add single comment",
                "Add to your pending review",
                "Cancel",
            ]
            assert "your pending review of #7 on GitHub" in str(tui.screen.query_one("#ask-what").content)
            await pilot.press("r")
            await settle(pilot)
            assert main.reviewing() and "Resuming your pending review (1 comment)" in " ".join(
                str(note.message) for note in tui._notifications
            )
            assert not github.posts()
            await pilot.press(*"also here", "ctrl+s")
            await settle(pilot)
            header = str(main.pr_header())
            assert "Reviewing: 1 draft" in header and "resuming your pending review: 1 comment" in header
            await pilot.press("v")
            await settle(pilot)
            assert main.submitting and "resuming your pending review (1 comment)" in str(
                main.query_one("#confirm-head").content
            )
            assert "sent with your pending review (1 comment already in it)" in str(
                main.query_one("#confirm-lines").content
            )
            assert not github.posts()  # the bar shows it; only y sends
            await pilot.press("a", "y")
            await settle(pilot)
            names = mutations(github)
            assert [name for name, _ in names] == ["addPullRequestReviewThread", "submitPullRequestReview"]
            assert names[0][1]["body"] == "also here" and names[0][1]["review"] == "PRR_pending"
            assert names[1][1] == {"review": "PRR_pending", "event": "APPROVE"} and not rest_writes(github)
            assert not main.reviewing() and main.pr.pending is None and "Pending review" not in str(main.pr_header())


async def test_resume_and_submit_with_the_review_started_empty():
    """v starts the review that resumes the pending one; the bar can send it as it is."""
    with FakeGitHub(pending_fixture()) as github:
        tui = make_app(github)
        async with tui.run_test(size=(110, 40)) as pilot:
            main = tui.main
            await open_files(pilot, main)
            await pilot.press("v", "v")
            await settle(pilot)
            assert main.submitting and main.submitting["plan"].resume["id"] == "PRR_pending"
            assert "y post" in str(main.query_one("#confirm-keys").content)
            await pilot.press("y")
            await settle(pilot)
            assert mutations(github) == [("submitPullRequestReview", {"review": "PRR_pending", "event": "COMMENT"})]


async def test_the_pending_review_vanishing_before_the_submit_keeps_the_drafts_in_the_app():
    with FakeGitHub(pending_fixture()) as github:
        tui = make_app(github)
        async with tui.run_test(size=(110, 40)) as pilot:
            main = tui.main
            await open_files(pilot, main)
            await pilot.press("c", "r")
            await settle(pilot)
            await pilot.press(*"keep me", "ctrl+s")
            await settle(pilot)
            await pilot.press("v")
            await settle(pilot)
            assert main.submitting
            data = github.data()  # submitted from the GitHub web page meanwhile
            data["prs"]["acme/app#7"]["node"]["pendingReviews"] = {"nodes": []}
            github.write(data)
            await pilot.press("y")
            await settle(pilot)
            assert not github.posts()
            assert any(
                "changed: it was submitted, discarded or replaced there" in str(n.message) for n in tui._notifications
            )
            assert main.drafts.count() == 1 and main.pr.pending is None  # kept, and read again: no pending review now
            assert "resuming" not in str(main.pr_header())


async def test_discarding_while_resuming_leaves_the_pending_review_alone():
    with FakeGitHub(pending_fixture()) as github:
        tui = make_app(github)
        async with tui.run_test(size=(110, 40)) as pilot:
            main = tui.main
            await open_files(pilot, main)
            await pilot.press("v")
            await settle(pilot)
            await pilot.press("colon", *"review discard", "enter")
            await settle(pilot)
            assert "Your pending review on GitHub stays as it is" in str(tui.screen.query_one("#ask-what").content)
            await pilot.press("y")
            await settle(pilot)
            assert not main.reviewing() and not github.posts() and main.pr.pending == PENDING
