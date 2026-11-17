# SPDX-FileCopyrightText: 2026 Cristiano Carvalho
# SPDX-License-Identifier: Apache-2.0
"""A review starts only on purpose. Opening, reading and moving through pull requests keeps nothing on disk and sends
nothing; v or :review starts a review, a commenting key asks first, and a review ends by posting it or by discarding
it after a y."""

from fake_github import FakeGitHub, fixture
from support import make_app, settle


def kept(github):
    """The drafts files on disk."""
    return sorted(path.name for path in (github.dir / "drafts").rglob("*.json"))


async def test_reading_keeps_nothing_and_sends_nothing():
    with FakeGitHub(fixture()) as github:
        tui = make_app(github)
        async with tui.run_test(size=(100, 40)) as pilot:
            await settle(pilot)
            main = tui.main
            for keys in (
                ("j", "k", "enter"),  # open #7 from the list
                ("1", "2", "3", "4"),  # every tab of it
                ("g", "g", "right_square_bracket", "c", "right_square_bracket", "u", "G"),  # move through the diff
                ("slash", *"import", "enter", "n"),  # search
                ("f", "j", "enter"),  # the file tree
                ("ctrl+p", *"app5", "enter"),  # another pull request
                ("tab", "2", "3", "4", "1"),  # every list tab
            ):
                await pilot.press(*keys)
                await settle(pilot)
            assert kept(github) == [] and not github.posts() and main.store.waiting() == {}
            assert not main.reviewing() and main.pending_items() == []
            assert "Reviewing" not in str(main.pr_header())


async def test_a_review_starts_on_purpose_and_ends_on_purpose():
    with FakeGitHub(fixture()) as github:
        tui = make_app(github)
        async with tui.run_test(size=(100, 40)) as pilot:
            await settle(pilot)
            main = tui.main
            await pilot.press("tab", "4")
            await settle(pilot)
            diff = main.query_one("#diff")
            diff.go(next(i for i, row in enumerate(diff.rows) if row.anchor))
            await pilot.press("c")  # a commenting key with no review on: it offers a single comment or a review
            await settle(pilot)
            assert type(tui.screen).__name__ == "ChoiceScreen" and "review of #7" in str(
                tui.screen.query_one("#ask-what").content
            )
            labels = [label for _keys, label, _value in tui.screen.choices]
            assert labels == ["Add single comment", "Start a review", "Cancel"], labels
            await pilot.press("n")  # cancel: nothing opens, nothing is kept
            await settle(pilot)
            assert tui.screen is main and not main.editing and kept(github) == []
            await pilot.press("x")  # not on a thread: the note says so, and nothing asks
            await settle(pilot)
            assert tui.screen is main
            await pilot.press("colon", *"review", "enter")  # :review starts one on purpose
            await settle(pilot)
            assert main.reviewing() and kept(github) == ["7.json"] and main.drafts.count() == 0
            assert "Reviewing: 0 drafts" in str(main.pr_header())
            assert [item.row.key for item in main.pending_items()] == ["acme/app#7"]  # it is in progress
            await pilot.press("c")  # a review is on: no question, the editor opens
            await settle(pilot)
            await pilot.press(*"why?", "ctrl+s")
            await settle(pilot)
            assert "Reviewing: 1 draft" in str(main.pr_header())
            await pilot.press("v")  # on: the bar, with what it would post
            await settle(pilot)
            assert main.submitting and "Reviewing #7: 1 draft" in str(main.query_one("#confirm-head").content)
            assert "D discard" in str(main.query_one("#confirm-keys").content)
            await pilot.press("D", "n")  # discard asks first; n keeps it
            await settle(pilot)
            assert main.submitting and main.drafts.count() == 1
            await pilot.press("D")
            await settle(pilot)
            assert "The review of #7 and its 1 draft goes" in str(tui.screen.query_one("#ask-what").content)
            await pilot.press("y")
            await settle(pilot)
            assert not main.submitting and not main.reviewing() and kept(github) == [] and not github.posts()
            await pilot.press("v")  # v starts one too
            await settle(pilot)
            assert main.reviewing()
            await pilot.press("colon", *"review discard", "enter", "y")
            await settle(pilot)
            assert not main.reviewing() and kept(github) == []


async def test_posting_ends_the_review():
    with FakeGitHub(fixture()) as github:
        tui = make_app(github)
        async with tui.run_test(size=(100, 40)) as pilot:
            await settle(pilot)
            main = tui.main
            await pilot.press("tab", "1", "c", "r")  # a comment on the conversation, with a review started for it
            await settle(pilot)
            await pilot.press(*"Thanks!", "ctrl+s")
            await settle(pilot)
            await pilot.press("y")  # the bar asks; y posts
            await settle(pilot)
            assert len(github.posts()) == 1 and kept(github) == [] and not main.reviewing()
