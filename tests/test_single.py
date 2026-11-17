# SPDX-FileCopyrightText: 2026 Cristiano Carvalho
# SPDX-License-Identifier: Apache-2.0
"""One comment, reply or resolve sent on its own, outside any review, as github.com's "Add single comment" does:
offered beside starting a review, written in the inline editor, shown in full with where it goes, and sent only on
the confirmation's yes, while the head is still the one read."""

import json

from fake_gh import HEAD
from fake_github import MOVED, FakeGitHub, fixture
from morann import core
from support import make_app, settle
from test_forge import Bare


def writes(github, endpoint):
    return [json.loads(post["stdin"]) for post in github.posts() if post["args"][3:4] == [endpoint]]


async def open_files(pilot):
    await pilot.press("tab", "4")
    await settle(pilot)
    return pilot.app.main.query_one("#diff")


async def test_a_single_comment_on_a_line():
    with FakeGitHub(fixture()) as github:
        tui = make_app(github)
        async with tui.run_test(size=(100, 40)) as pilot:
            await settle(pilot)
            main = tui.main
            diff = await open_files(pilot)
            diff.go(next(i for i, row in enumerate(diff.rows) if row.text == "import re"))
            await pilot.press("c", "s")  # Add single comment: the editor, nothing sent yet
            await settle(pilot)
            assert main.editing and not github.posts() and not main.reviewing()
            await pilot.press(*"use re2", "ctrl+s")
            await settle(pilot)
            what = str(tui.screen.query_one("#ask-what").content)
            assert "lib/a.py, line 3 of the new file, posted now and on its own" in what and "use re2" in what
            assert not github.posts()
            await pilot.press("n")  # cancel: back to the editor, the text kept
            await settle(pilot)
            assert main.editing and main.query_one("#editor-text").text == "use re2" and not github.posts()
            await pilot.press("ctrl+s", "y")
            await settle(pilot)
            assert writes(github, "repos/acme/app/pulls/7/comments") == [
                {"body": "use re2", "commit_id": HEAD, "path": "lib/a.py", "line": 3, "side": "RIGHT"}
            ]
            assert not main.reviewing() and not list((github.dir / "drafts").rglob("*.json"))


async def test_a_reply_and_a_resolve_now():
    with FakeGitHub(fixture()) as github:
        tui = make_app(github)
        async with tui.run_test(size=(100, 40)) as pilot:
            await settle(pilot)
            main = tui.main
            diff = await open_files(pilot)
            diff.go(next(i for i, row in enumerate(diff.rows) if row.kind == "thread" and row.thread == "T1"))
            await pilot.press("R")
            await settle(pilot)
            assert [label for _keys, label, _value in tui.screen.choices] == ["Reply now", "Add to review", "Cancel"]
            await pilot.press("s", *"done", "ctrl+s", "y")
            await settle(pilot)
            assert writes(github, "repos/acme/app/pulls/7/comments/101/replies") == [{"body": "done"}]
            diff.go(next(i for i, row in enumerate(diff.rows) if row.kind == "thread" and row.thread == "T1"))
            await pilot.press("x")
            await settle(pilot)
            assert "Resolve the thread on lib/a.py, line 3" in str(tui.screen.query_one("#ask-what").content)
            await pilot.press("s")
            await settle(pilot)
            mutations = [c for c in github.calls() if "graphql" in c["args"] and "resolveReviewThread" in c["stdin"]]
            assert len(mutations) == 1 and not main.reviewing()


async def test_a_conversation_comment_now():
    with FakeGitHub(fixture()) as github:
        tui = make_app(github)
        async with tui.run_test(size=(100, 40)) as pilot:
            await settle(pilot)
            await pilot.press("C", "s")
            await settle(pilot)
            await pilot.press(*"Thanks!", "ctrl+s", "y")
            await settle(pilot)
            assert writes(github, "repos/acme/app/issues/7/comments") == [{"body": "Thanks!"}]


async def test_nothing_is_sent_once_the_head_moved():
    data = fixture()
    data["prs"]["acme/app#7"]["heads"] = [HEAD, HEAD, MOVED]  # read at HEAD, then a push lands
    with FakeGitHub(data) as github:
        tui = make_app(github)
        async with tui.run_test(size=(100, 40)) as pilot:
            await settle(pilot)
            diff = await open_files(pilot)
            diff.go(next(i for i, row in enumerate(diff.rows) if row.text == "import re"))
            await pilot.press("c", "s", *"late", "ctrl+s", "y")
            await settle(pilot)
            assert not github.posts()
            assert any("moved" in str(note.message) for note in tui._notifications), list(tui._notifications)


async def test_a_forge_without_single_comments_offers_only_a_review():
    with FakeGitHub(fixture()) as github:
        tui = make_app(github, forge=Bare())
        async with tui.run_test(size=(100, 40)) as pilot:
            await settle(pilot)
            diff = await open_files(pilot)
            diff.go(next(i for i, row in enumerate(diff.rows) if row.text == "import re"))
            await pilot.press("c")
            await settle(pilot)
            assert [label for _keys, label, _value in tui.screen.choices] == ["Start a review", "Cancel"]
            assert core.Capability.SINGLE_COMMENTS not in tui.main.forge.capabilities


async def test_the_dialog_names_its_keys():
    with FakeGitHub(fixture()) as github:
        tui = make_app(github)
        async with tui.run_test(size=(100, 40)) as pilot:
            await settle(pilot)
            diff = await open_files(pilot)
            diff.go(next(i for i, row in enumerate(diff.rows) if row.text == "import re"))
            await pilot.press("c")
            await settle(pilot)
            keys = " ".join(str(tui.screen.query_one("#dialog-keys").content).split())
            assert keys == "s add single comment r start a review n esc cancel", keys
            await pilot.click("#ask-1")  # a click on Start a review does what r does
            await settle(pilot)
            assert tui.main.reviewing() and tui.main.editing
