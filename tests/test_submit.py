# SPDX-FileCopyrightText: 2026 Cristiano Carvalho
# SPDX-License-Identifier: Apache-2.0
"""Posting a review: nothing goes out without the confirmed plan or after the head moved, what was posted leaves the
drafts and the rest stays, and --read-only refuses every write."""

import json

import pytest

from fake_github import HEAD, MOVED, FakeGitHub, drafted, fixture, load
from morann import core
from morann.github import GitHubProvider, queries
from morann.github.provider import review_payload


def planned(github, event):
    """The pull request's drafts saved in the fake's folder, and the plan to post them."""
    pr = load()
    store = core.DraftStore(github.dir / "drafts")
    return pr, store, core.build_plan(pr, drafted(store, pr), event)


def test_nothing_is_posted_without_the_confirmed_fingerprint():
    """Not with none, a wrong one, or one from an older plan."""
    with FakeGitHub(fixture()) as github:
        pr, store, plan = planned(github, "COMMENT")
        for confirmed in (None, "", "0" * 64):
            with pytest.raises(core.NotConfirmed):
                core.submit(GitHubProvider(), plan, confirmed, store)
        newer = store.load(pr.repo, pr.number)
        newer.summary = "edited after the screen was shown"
        with pytest.raises(core.NotConfirmed):
            core.submit(GitHubProvider(), core.build_plan(pr, newer, "COMMENT"), plan.fingerprint(), store)
        assert not github.posts() and store.load(pr.repo, pr.number).count() == 6


def test_a_moved_head_posts_nothing_and_keeps_every_draft():
    with FakeGitHub(fixture()) as github:
        pr, store, plan = planned(github, "APPROVE")
        data = github.data()
        data["prs"]["acme/app#7"]["heads"] = [MOVED]
        github.write(data)
        with pytest.raises(core.HeadMoved) as raised:
            core.submit(GitHubProvider(), plan, plan.fingerprint(), store)
        message = str(raised.value)
        assert "nothing was posted" in message and HEAD[:7] in message and MOVED[:7] in message
        assert not github.posts() and store.load(pr.repo, pr.number).count() == 6


def test_a_confirmed_plan_posts_one_review_then_replies_and_resolves():
    """One review with its comments, each reply to the thread's first comment, then resolve and unresolve."""
    with FakeGitHub(fixture()) as github:
        pr, store, plan = planned(github, "REQUEST_CHANGES")
        posted = core.submit(GitHubProvider(), plan, plan.fingerprint(), store)
        posts = github.posts()
        assert [p["args"][3] if "graphql" not in p["args"] else "graphql" for p in posts] == [
            "repos/acme/app/pulls/7/reviews",
            "repos/acme/app/pulls/7/comments/101/replies",
            "graphql",
            "graphql",
        ]
        assert json.loads(posts[0]["stdin"]) == review_payload(plan)
        assert json.loads(posts[1]["stdin"]) == {"body": "ok, makes sense"}
        mutations = [json.loads(p["stdin"]) for p in posts[2:]]
        assert "resolveReviewThread" in mutations[0]["query"] and "unresolve" not in mutations[0]["query"]
        assert mutations[0]["variables"] == {"id": "T1"}
        assert "unresolveReviewThread" in mutations[1]["query"] and mutations[1]["variables"] == {"id": "T2"}
        assert posted[0] == "review (request changes, 2 comments)" and len(posted) == 4
        assert not store.path(pr.repo, pr.number).exists()  # every draft went out


def test_a_reply_refused_part_way_keeps_what_was_not_posted():
    """The review went out and left the drafts; the rest stays."""
    with FakeGitHub(fixture(fail={"replies": "can only reply to a top-level comment"})) as github:
        pr, store, plan = planned(github, "COMMENT")
        with pytest.raises(core.SubmitError) as raised:
            core.submit(GitHubProvider(), plan, plan.fingerprint(), store)
        assert raised.value.posted == ["review (comment, 2 comments)"]
        assert "can only reply to a top-level comment" in str(raised.value) and "stays as drafts" in str(raised.value)
        left = store.load(pr.repo, pr.number)
        assert not left.comments and not left.summary and len(left.replies) == 1 and len(left.resolves) == 2
        assert len(github.posts()) == 2


def test_drafts_that_cannot_be_updated_stop_the_submit():
    """The review posts but the drafts cannot be saved: stop, and say they would post twice."""
    with FakeGitHub(fixture()) as github:
        _pr, store, plan = planned(github, "COMMENT")

        def full(_drafts):
            raise OSError("No space left on device")

        store.save = full
        with pytest.raises(core.SubmitError) as raised:
            core.submit(GitHubProvider(), plan, plan.fingerprint(), store)
        assert raised.value.posted == ["review (comment, 2 comments)"] and "post twice" in str(raised.value)
        assert len(github.posts()) == 1  # nothing after the review


def test_a_write_that_times_out_may_have_arrived():
    """Say so instead of inviting a retry."""
    with FakeGitHub(fixture(slow={"reviews": 3})) as github:
        pr, store, plan = planned(github, "COMMENT")
        with pytest.raises(core.SubmitError) as raised:
            core.submit(GitHubProvider(timeout=1), plan, plan.fingerprint(), store)
        assert "may have reached GitHub" in str(raised.value) and raised.value.posted == []
        assert store.load(pr.repo, pr.number).count() == 6


def test_a_refused_review_changes_nothing_locally():
    with FakeGitHub(fixture(fail={"reviews": "User can only have one pending review per pull request"})) as github:
        pr, store, plan = planned(github, "COMMENT")
        with pytest.raises(core.SubmitError) as raised:
            core.submit(GitHubProvider(), plan, plan.fingerprint(), store)
        message = str(raised.value)
        assert raised.value.posted == [] and "nothing was posted" in message and "one pending review" in message
        assert store.load(pr.repo, pr.number).count() == 6


def test_read_only_refuses_every_write_before_gh_runs():
    """Even with a confirmed plan."""
    with FakeGitHub(fixture()) as github:
        pr, store, plan = planned(github, "APPROVE")
        reader = GitHubProvider(read_only=True)
        with pytest.raises(core.SubmitError, match="read-only") as raised:
            core.submit(reader, plan, plan.fingerprint(), store)
        assert raised.value.posted == []
        for write in (
            lambda: reader.gh.post("repos/acme/app/pulls/7/reviews", {}),
            lambda: reader.gh.graphql(queries.RESOLVE, {"id": "T1"}),
            lambda: reader.gh.graphql(queries.UNRESOLVE, {"id": "T2"}),
        ):
            with pytest.raises(core.ForgeError, match="read-only"):
                write()
        assert not github.posts() and store.load(pr.repo, pr.number).count() == 6
        assert reader.list_pull_requests(core.Scope(owners=("acme",))).viewer == "me"  # reads still work
