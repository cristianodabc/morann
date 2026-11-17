# SPDX-FileCopyrightText: 2026 Cristiano Carvalho
# SPDX-License-Identifier: Apache-2.0
"""Editing and deleting what you posted: only your own, shown old and new (or whole, for a delete) before anything is
sent, marked edited afterwards, and never with --read-only or on a forge that cannot."""

import json

from fake_github import FakeGitHub, comment, fixture
from morann.github import GitHubProvider
from support import make_app, settle
from test_forge import Bare


def mine_fixture():
    data = fixture()
    node = data["prs"]["acme/app#7"]["node"]
    node["reviewThreads"]["nodes"][0]["comments"]["nodes"].append(comment(104, "me", "my take", "2026-11-04T14:00:00Z"))
    node["comments"]["nodes"].append(
        {
            "databaseId": 501,
            "body": "ship it",
            "createdAt": "2026-11-04T15:00:00Z",
            "author": {"login": "me"},
            "lastEditedAt": "2026-11-04T16:00:00Z",
        }
    )
    node["reviews"]["nodes"].append(
        {
            "databaseId": 601,
            "state": "COMMENTED",
            "body": "a few notes",
            "submittedAt": "2026-11-04T17:00:00Z",
            "author": {"login": "me"},
        }
    )
    return data


def writes(github):
    return [(post["args"][2], post["args"][3], json.loads(post["stdin"] or "{}")) for post in github.posts()]


def go(main, test):
    diff = main.query_one("#diff")
    diff.go(next(i for i, row in enumerate(diff.rows) if test(row)))


async def test_edit_your_comment_on_the_diff():
    with FakeGitHub(mine_fixture()) as github:
        tui = make_app(github)
        async with tui.run_test(size=(120, 40)) as pilot:
            await settle(pilot)
            main = tui.main
            await pilot.press("tab", "4")
            await settle(pilot)
            go(main, lambda row: row.kind == "comment" and row.author == "ann")
            await pilot.pause()
            assert not main.check_action("edit", ()) and not main.check_action("delete", ())  # not yours
            go(main, lambda row: row.post == ("line", 104))
            await pilot.pause()
            assert main.check_action("edit", ()) and main.check_action("delete", ())
            await pilot.press("e")  # the editor, with the text as it stands
            await settle(pilot)
            assert main.editing and main.query_one("#editor-text").text == "my take"
            await pilot.press(*" v2", "ctrl+s")
            await settle(pilot)
            what = str(tui.screen.query_one("#ask-what").content)
            assert "-my take" in what and "+my take v2" in what and not github.posts()
            await pilot.press("n")  # back to the editor, the new text kept
            await settle(pilot)
            assert main.editing and main.query_one("#editor-text").text == "my take v2"
            await pilot.press("ctrl+s", "y")
            await settle(pilot)
            assert writes(github) == [("PATCH", "repos/acme/app/pulls/comments/104", {"body": "my take v2"})]
            go(main, lambda row: row.post == ("line", 104))
            await pilot.press("d", "d")
            await settle(pilot)
            assert "deleted from GitHub for good" in str(tui.screen.query_one("#ask-what").content)
            await pilot.press("y")
            await settle(pilot)
            assert writes(github)[-1] == ("DELETE", "repos/acme/app/pulls/comments/104", {})


async def test_edit_and_delete_on_the_conversation():
    with FakeGitHub(mine_fixture()) as github:
        tui = make_app(github)
        async with tui.run_test(size=(120, 40)) as pilot:
            await settle(pilot)
            main = tui.main
            await pilot.press("tab", "1")
            await settle(pilot)
            row = next(row for row in main.query_one("#diff").rows if row.post == ("conversation", 501))
            assert "edited" in row.badges  # changed since it was posted, as github.com marks it
            go(main, lambda row: row.post == ("conversation", 501))
            await pilot.press("colon", *"delete", "enter", "y")  # :delete, with the same confirmation
            await settle(pilot)
            assert writes(github) == [("DELETE", "repos/acme/app/issues/comments/501", {})]
            go(main, lambda row: row.post == ("review", 601))
            await pilot.press("d", "d")  # a submitted review cannot be deleted
            await settle(pilot)
            assert tui.screen is main and len(github.posts()) == 1
            await pilot.press("e", *" more", "ctrl+s", "y")  # its summary can be edited
            await settle(pilot)
            assert writes(github)[-1] == ("PUT", "repos/acme/app/pulls/7/reviews/601", {"body": "a few notes more"})


async def test_edit_the_description_of_your_own_pull_request():
    with FakeGitHub(fixture()) as github:
        tui = make_app(github)
        async with tui.run_test(size=(120, 40)) as pilot:
            await settle(pilot)
            main = tui.main
            await pilot.press("1")  # Mine: #5 is mine
            await settle(pilot)
            await pilot.press("tab", "1")
            await settle(pilot)
            go(main, lambda row: row.post == ("description", 5))
            await pilot.press("colon", *"edit", "enter")
            await settle(pilot)
            await pilot.press(*"!", "ctrl+s", "y")
            await settle(pilot)
            assert writes(github)[0][:2] == ("PATCH", "repos/acme/app/pulls/5")
            assert writes(github)[0][2]["body"].endswith("**fast**.!")


async def test_never_with_read_only_or_without_the_capability():
    for forge, words in ((GitHubProvider(read_only=True), "read-only"), (Bare(), "Bare has no editing comments")):
        with FakeGitHub(mine_fixture()) as github:
            tui = make_app(github, forge=forge)
            async with tui.run_test(size=(120, 40)) as pilot:
                await settle(pilot)
                main = tui.main
                await pilot.press("tab", "4")
                await settle(pilot)
                go(main, lambda row: row.post == ("line", 104))
                await pilot.press("e")
                await settle(pilot)
                assert not main.editing and not github.posts()
                assert any(words in str(note.message) for note in tui._notifications), list(tui._notifications)
