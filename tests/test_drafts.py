# SPDX-FileCopyrightText: 2026 Cristiano Carvalho
# SPDX-License-Identifier: Apache-2.0
"""Local drafts and the plan built from them: what is stored, what a plan holds and refuses, drafts whose code moved,
and comments on the conversation."""

import json

import pytest

from fake_github import HEAD, MOVED, NOW, PATCH, FakeGitHub, drafted, fixture, load, load_pr
from morann import core
from morann.github import GitHubProvider
from morann.github.provider import review_payload
from support import refused

T1 = core.Thread("T1", "lib/a.py", 3, 3, "RIGHT", False, False, [core.Comment(101, "ann", "x", "")])
T2 = core.Thread("T2", "lib/a.py", 2, 2, "LEFT", True, False, [core.Comment(201, "ann", "y", "")])


def test_drafts_are_stored_per_pull_request(tmp_path):
    store = core.DraftStore(tmp_path)
    drafts = store.load("acme/app", 7)
    assert drafts.empty() and not store.path("acme/app", 7).exists()
    first = drafts.add_comment("lib/a.py", "RIGHT", 3, "why?")
    second = drafts.add_comment("lib/a.py", "LEFT", 2, "keep sys")
    reply = drafts.add_reply(T1, "agreed")
    drafts.toggle_resolve(T1)
    drafts.summary = "Looks fine"
    store.save(drafts)
    path = store.path("acme/app", 7)
    assert path == tmp_path / "acme/app/7.json" and path.exists()
    again = core.DraftStore(tmp_path).load("acme/app", 7)  # a restart reads the same drafts
    assert [c["body"] for c in again.comments] == ["why?", "keep sys"] and again.summary == "Looks fine"
    assert again.replies[0]["comment"] == 101 and again.resolves[0]["resolve"] is True and again.count() == 5
    again.edit(first, "why not json?")
    again.edit(second, "  ")  # empty text deletes
    again.delete(reply)
    assert again.toggle_resolve(T1) is None  # toggling again drops the mark
    store.save(again)
    third = store.load("acme/app", 7)
    assert [c["body"] for c in third.comments] == ["why not json?"] and not third.replies and not third.resolves
    assert store.counts() == {"acme/app#7": 2}
    third.comments.clear()
    third.summary = ""
    store.save(third)
    assert not path.exists() and store.counts() == {}
    with pytest.raises(core.DraftError):
        again.edit("nope", "x")


def test_a_damaged_draft_file_is_set_aside(tmp_path):
    store = core.DraftStore(tmp_path)
    path = store.path("acme/app", 7)
    path.parent.mkdir(parents=True)
    path.write_text("{not json")
    damaged = store.load("acme/app", 7)
    assert damaged.empty() and "damaged" in damaged.warning
    kept = list(path.parent.glob("7.json.damaged-*"))
    assert len(kept) == 1 and kept[0].read_text() == "{not json" and not path.exists()
    path.write_text(json.dumps({"version": 2, "repo": "acme/app", "number": 7}))
    assert "damaged" in store.load("acme/app", 7).warning  # an unknown version is set aside, never overwritten


@pytest.mark.parametrize("bad", ["../x", "acme/../../etc"])
def test_a_draft_path_stays_inside_the_store(tmp_path, bad):
    with pytest.raises(core.UsageError):
        core.DraftStore(tmp_path).path(bad, 1)


def test_plan():
    with FakeGitHub(fixture()) as github:
        pr = load()
        store = core.DraftStore(github.dir / "drafts")
        drafts = drafted(store, pr)
        plan = core.build_plan(pr, drafts, "REQUEST_CHANGES")
        assert review_payload(plan) == {
            "commit_id": HEAD,
            "event": "REQUEST_CHANGES",
            "body": "Two small things",
            "comments": [
                {"path": "lib/a.py", "line": 13, "side": "RIGHT", "body": "call done() last?"},
                {"path": "lib/a.py", "line": 2, "side": "LEFT", "body": "sys is used in main"},
            ],
        }
        lines = plan.lines()
        assert lines[2] == "Review: request changes" and "Comment on lib/a.py:2 (old file):" in lines
        assert "Reply on lib/a.py:3:" in lines and "Resolve thread on lib/a.py:3" in lines
        assert "Unresolve thread on lib/a.py:2" in lines and "    ok, makes sense" in lines
        changed = store.load(pr.repo, pr.number)
        changed.summary = "Changed my mind"
        assert core.build_plan(pr, changed, "REQUEST_CHANGES").fingerprint() != plan.fingerprint()
        bare = core.Drafts(pr.repo, pr.number)
        assert review_payload(core.build_plan(pr, bare, "APPROVE")) == {
            "commit_id": HEAD,
            "event": "APPROVE",
            "comments": [],
        }
        only_reply = core.Drafts(pr.repo, pr.number)
        only_reply.add_reply(pr.thread("T1"), "thanks")
        assert not core.build_plan(pr, only_reply, "COMMENT").has_review()
        assert not github.posts()


def test_a_plan_that_cannot_be_posted_is_refused():
    with FakeGitHub(fixture()) as github:
        pr = load()
        bare = core.Drafts(pr.repo, pr.number)
        with refused(core.PlanError, "needs a summary"):
            core.build_plan(pr, bare, "REQUEST_CHANGES")
        with refused(core.PlanError, "nothing to submit"):
            core.build_plan(pr, bare, "COMMENT")
        stale = core.Drafts(pr.repo, pr.number)
        stale.add_comment("lib/a.py", "RIGHT", 7, "between hunks")
        with refused(core.PlanError, "no longer in the diff"):
            core.build_plan(pr, stale, "COMMENT")
        own = load_pr(GitHubProvider(), "acme/app", 7)
        own.author = "me"
        with refused(core.PlanError, "your own pull request"):
            core.build_plan(own, drafted(core.DraftStore(github.dir / "drafts"), pr), "APPROVE")
        assert not github.posts()


def test_a_draft_whose_code_moved_cannot_be_posted():
    """A draft keeps the code it was written against: after a push puts other code on its line, it cannot be
    posted."""
    with FakeGitHub(fixture()) as github:
        pr = load()
        item = pr.file("lib/a.py")
        drafts = core.Drafts(pr.repo, pr.number)
        drafts.add_comment(
            "lib/a.py", "RIGHT", 13, "call done() last?", core.line_context(item, item.find("RIGHT", 13))
        )
        assert core.build_plan(pr, drafts, "COMMENT").comments[0]["line"] == 13
        data = github.data()
        data["prs"]["acme/app#7"]["heads"] = [MOVED]
        data["prs"]["acme/app#7"]["files"][0]["patch"] = PATCH.replace(
            "     stop()\n+    done()", "+    log()\n     stop()"
        )
        github.write(data)
        pushed = load()
        assert pushed.file("lib/a.py").find("RIGHT", 13) is not None  # line 13 still exists, holding other code
        with refused(core.PlanError, "changed since the draft was written"):
            core.build_plan(pushed, drafts, "COMMENT")
        assert any(
            row.text.startswith("[draft, the code here changed]") and row.style == "bad"
            for row in core.file_rows(pushed, 0, drafts)
        )


def test_marks_on_threads_that_changed_are_pruned():
    with FakeGitHub(fixture()):
        pr = load()
    pr.threads = [T1, T2]
    drafts = core.Drafts(
        pr.repo,
        pr.number,
        resolves=[
            {"id": "a", "thread": "T1", "resolve": True, "path": "lib/a.py", "line": 3},
            {"id": "b", "thread": "T2", "resolve": True, "path": "lib/a.py", "line": 2},  # already resolved
            {"id": "c", "thread": "T9", "resolve": True, "path": "lib/a.py", "line": 9},  # thread gone
        ],
    )
    assert drafts.prune(pr) and [r["id"] for r in drafts.resolves] == ["a"] and not drafts.prune(pr)
    drafts.replies.append({"id": "r", "thread": "T9", "comment": 9, "path": "gone.py", "line": 1, "body": "late"})
    orphan = [row for row in core.conversation_rows(pr, drafts, now=NOW) if row.draft == "r"]
    assert orphan and orphan[0].text == "[reply, gone.py:1] late"  # reachable, so d can delete it


def test_a_conversation_comment_is_a_draft_that_goes_out_last():
    """A comment on the conversation is a draft like the rest and goes to the issue comments endpoint."""
    with FakeGitHub(fixture()) as github:
        pr = load()
        store = core.DraftStore(github.dir / "drafts")
        drafts = store.load(pr.repo, pr.number)
        drafts.add_note("Thanks, merging after CI")
        store.save(drafts)
        drafts = store.load(pr.repo, pr.number)
        assert [n["body"] for n in drafts.notes] == ["Thanks, merging after CI"] and drafts.count() == 1
        assert any(
            row.kind == "draft" and row.badges == ("pending", "comment")
            for row in core.conversation_rows(pr, drafts, now=NOW)
        )
        plan = core.build_plan(pr, drafts, "COMMENT")
        assert not plan.has_review() and "Comment on the conversation:" in plan.lines()
        assert core.submit(GitHubProvider(), plan, plan.fingerprint(), store) == ["comment on the conversation"]
        posts = github.posts()
        assert [p["args"][3] for p in posts] == ["repos/acme/app/issues/7/comments"]
        assert json.loads(posts[0]["stdin"]) == {"body": "Thanks, merging after CI"}
        assert not store.path(pr.repo, pr.number).exists()
