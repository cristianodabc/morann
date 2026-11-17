# SPDX-FileCopyrightText: 2026 Cristiano Carvalho
# SPDX-License-Identifier: Apache-2.0
"""Review threads on the Conversation tab: each thread under its file and line with the diff it was left on, its
comments and replies open, its drafts, a note when GitHub gave no diff, and enter taking it to the Files tab."""

from fake_github import NOW, FakeGitHub, drafted, fixture, load
from morann import core
from morann.github import parse, queries
from support import make_app, settle


def entry(rows, thread_id):
    """The rows of one thread's entry on the Conversation tab, from its file and line down to its last draft."""
    return [row for row in rows if row.thread == thread_id]


def test_conversation_threads():
    """The diff hunk comes with the threads in the one pull request query, and each thread on the Conversation tab
    shows the last lines of it, ending at the commented line, in the Files tab's row kinds and numbers."""
    assert "hunk: comments(first: 1) { nodes { diffHunk } }" in queries.PR_QUERY
    with FakeGitHub(fixture()) as github:
        pr = load()
        store = core.DraftStore(github.dir / "drafts")
        talk = core.conversation_rows(pr, core.Drafts(pr.repo, pr.number), now=NOW)
        rows = entry(talk, "T1")  # a thread with a reply
        assert rows[0].text == "lib/a.py line 3"
        code = [
            (row.kind, row.old.strip(), row.new.strip(), row.text) for row in rows if row.kind in ("add", "del", "ctx")
        ]
        assert code == [
            ("ctx", "1", "1", "import os"),
            ("del", "2", "", "import sys"),
            ("add", "", "2", "import json"),
            ("add", "", "3", "import re"),
        ], code
        assert all(row.anchor and row.anchor[0] == "lib/a.py" for row in rows if row.kind in ("add", "del", "ctx"))
        assert [row.author for row in rows if row.kind == "comment"] == ["ann", "sam"]  # the reply under the root
        resolved = entry(talk, "T2")  # resolved: open here, dimmed, with its badge
        assert [(row.kind, row.text) for row in resolved if row.kind in ("ctx", "del")] == [
            ("ctx", "import os"),
            ("del", "import sys"),
        ]
        assert any(row.kind == "thread" and "resolved" in row.badges for row in resolved)
        assert [row.body for row in resolved if row.kind == "comment"] == ["sys is still used"]
        outdated = entry(talk, "T3")  # outdated and no hunk from GitHub: the path, one note, the comments
        assert outdated[0].text == "lib/a.py line 9"
        assert [row.text for row in outdated if row.kind == "info"] == [
            "the diff this thread was left on is not available"
        ]
        assert not any(row.kind in ("add", "del", "ctx") for row in outdated)
        assert [row.body for row in outdated if row.kind == "comment"] == ["old remark"]
        drafts = drafted(store, pr)  # a pending reply and resolve marks show in the entry, as in the Files tab
        talk = core.conversation_rows(pr, drafts, now=NOW)
        assert [row.badges for row in entry(talk, "T1") if row.kind == "draft"] == [("pending", "reply"), ("pending",)]
        assert any(row.kind == "draft" for row in entry(talk, "T2"))


def test_a_thread_cached_before_hunks_were_read_has_none():
    legacy = parse.parse_threads([{"id": "T9", "path": "x", "comments": {"nodes": []}}])
    assert legacy[0].hunk == ""


async def test_enter_on_a_thread_opens_it_in_the_files_tab():
    """enter on a thread's entry on the Conversation tab opens the Files tab at that thread; elsewhere it stays put."""
    with FakeGitHub(fixture()) as github:
        tui = make_app(github)
        async with tui.run_test(size=(100, 40)) as pilot:
            await settle(pilot)
            main = tui.main
            diff = main.query_one("#diff")
            await pilot.press("tab", "1")
            await settle(pilot)
            assert main.mode == "conversation"
            code = next(i for i, row in enumerate(diff.rows) if row.thread == "T2" and row.kind == "del")
            diff.go(code)
            await pilot.press("enter")  # from a line of the hunk: the resolved thread, opened, in lib/a.py
            await settle(pilot)
            assert main.mode == "files" and main.pr.files[main.file_index].path == "lib/a.py"
            row = diff.current()
            assert row.kind == "thread" and row.thread == "T2", row
            assert any(r.thread == "T2" and r.kind == "comment" for r in diff.rows)  # opened, though resolved
            await pilot.press("1")
            await settle(pilot)
            gone = next(i for i, row in enumerate(diff.rows) if row.thread == "T4")
            diff.go(gone)
            await pilot.press("enter")  # its file left the pull request: say so, stay on the Conversation tab
            await settle(pilot)
            assert main.mode == "conversation"
            assert any("gone.py" in str(note.message) for note in tui._notifications), list(tui._notifications)
            title = next(i for i, row in enumerate(diff.rows) if row.kind == "title")
            diff.go(title)
            await pilot.press("enter")  # not a thread: nothing happens
            await settle(pilot)
            assert main.mode == "conversation"
