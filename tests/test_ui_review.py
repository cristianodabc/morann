# SPDX-FileCopyrightText: 2026 Cristiano Carvalho
# SPDX-License-Identifier: Apache-2.0
"""Review actions from every pane (the review bar with its summary field, the comment on the conversation), the
header buttons, the actions popup drawn whole at 70x30, the footers at 70 columns and pane focus."""

import json

import pytest

from fake_github import FakeGitHub, fixture, stack_fixture
from morann import core, dialogs
from morann.github import GitHubProvider
from support import make_app, settle


def screen_text(tui):
    """What the terminal shows, line by line."""
    return [strip.text for strip in tui.screen._compositor.render_strips()]


def footer_fits(main, width):
    hints = main.query_one("#status")
    return hints.display and 0 < hints.content.cell_len <= width


def reviews(github):
    """The reviews posted to acme/app#7, as their payloads."""
    return [json.loads(p["stdin"]) for p in github.posts() if p["args"][3:4] == ["repos/acme/app/pulls/7/reviews"]]


async def test_review_from_every_pane():
    with FakeGitHub(fixture()) as github:
        tui = make_app(github)
        async with tui.run_test(size=(70, 40)) as pilot:
            await settle(pilot)
            main = tui.main
            assert main.focus_pane == "list" and main.query_one("#top").has_class("focused")
            assert not main.query_one("#bottom").has_class("focused")
            assert footer_fits(main, 70)
            await pilot.press("v")  # from the list: it starts a review; again, the review bar shows what it would post
            await settle(pilot)
            assert main.reviewing() and not main.submitting and "Reviewing: 0 drafts" in str(main.pr_header())
            await pilot.press("v")
            await settle(pilot)
            assert main.submitting and main.submitting["event"] == "COMMENT" and main.pr.key == "acme/app#7"
            assert "y post" not in str(main.query_one("#confirm-keys").content)  # nothing drafted: nothing to post
            await pilot.press("n")
            await settle(pilot)
            assert main.submitting is None and tui.focused is main.query_one("#list")
            await pilot.press("C")  # from the list: a comment on the conversation, written inline
            await settle(pilot)
            assert main.mode == "conversation" and main.editing and main.editing[0] == "editor"
            await pilot.press(*"Thanks!", "ctrl+s")
            await settle(pilot)
            assert main.submitting and "Comment on the conversation:" in main.submitting["plan"].lines()
            await pilot.press("y")
            await settle(pilot)
            notes = [p for p in github.posts() if p["args"][3:4] == ["repos/acme/app/issues/7/comments"]]
            assert len(notes) == 1 and json.loads(notes[0]["stdin"]) == {"body": "Thanks!"} and not reviews(github)
            await pilot.press(
                "2", "r", "y"
            )  # the posted review ended; y starts another. Request changes needs a summary
            await settle(pilot)
            assert main.mode == "commits" and main.submitting["event"] == "REQUEST_CHANGES"
            assert main.editing[0] == "bar" and tui.focused is main.query_one("#bar-text")
            assert "needs a summary" in main.submitting["problem"]
            await pilot.press(*"Needs a test", "ctrl+s")
            await settle(pilot)
            assert main.editing is None and tui.focused is main.query_one("#confirm")
            assert main.submitting["plan"] is not None and main.drafts.summary == "Needs a test"
            assert "y post" in str(main.query_one("#confirm-keys").content)
            lines = screen_text(tui)
            assert any("y post" in line for line in lines), lines  # the bar's keys are on screen
            await pilot.press("y")
            await settle(pilot)
            assert reviews(github)[-1] == {
                "commit_id": "a" * 40,
                "event": "REQUEST_CHANGES",
                "comments": [],
                "body": "Needs a test",
            }
            await pilot.press("3", "v", "v", "a")  # Checks tab: start a review, open the bar, switch it to approve
            await settle(pilot)
            assert main.mode == "checks" and main.submitting["event"] == "APPROVE"
            await pilot.press("m")  # the summary field, from the bar's keys
            assert main.editing[0] == "bar"
            await pilot.press(*"LGTM", "escape")  # esc leaves the field without keeping it
            await settle(pilot)
            assert main.editing is None and main.drafts.summary == ""
            await pilot.press("y")
            await settle(pilot)
            assert reviews(github)[-1]["event"] == "APPROVE" and "body" not in reviews(github)[-1]
            await pilot.press("tab")
            await settle(pilot)
            await pilot.click("#review")  # the header's buttons do what their keys do: a review starts
            await settle(pilot)
            assert main.reviewing() and not main.submitting
            await pilot.click("#review")  # and then shows what it would post
            await settle(pilot)
            assert main.submitting and main.submitting["event"] == "COMMENT"
            await pilot.press("n")
            await settle(pilot)
            await pilot.press("tab")
            for tab in ("1", "2", "3", "4"):  # the footer fits 70 columns on every tab
                await pilot.press(tab)
                await settle(pilot)
                assert footer_fits(main, 70), tab
                buttons = [b for b in main.query("#prbuttons Button") if b.display]
                assert max(b.region.right for b in buttons) <= 70, [(b.id, b.region) for b in buttons]
            await pilot.press("f")
            assert tui.focused is main.query_one("#files") and footer_fits(main, 70)
            await pilot.press("f", "tab")
            assert tui.focused is main.query_one("#list") and main.query_one("#top").has_class("focused")
            await pilot.press("1")  # Mine: acme/app#5 is mine
            await settle(pilot)
            assert main.pr.key == "acme/app#5" and main.own_pr()
            assert not main.query_one("#approve").display and not main.query_one("#changes").display
            assert not main.query_one("#merge").disabled
            await pilot.press("tab")
            assert not main.check_action("submit", ("APPROVE",)) and not main.check_action(
                "submit", ("REQUEST_CHANGES",)
            )
            posted = len(github.posts())
            await pilot.press("a", "r")  # hidden on your own pull request, and nothing opens
            await settle(pilot)
            assert main.submitting is None
            await pilot.press("v", "v", "a")  # a review starts, then in the bar approve is refused with the reason
            await settle(pilot)
            assert main.submitting["event"] == "COMMENT"
            assert "not on your own pull request" in str(main.query_one("#confirm-head").content)
            await pilot.press("n")
            await settle(pilot)
            await pilot.click("#merge")  # your own: the actions popup with the merge method chosen
            await settle(pilot)
            assert isinstance(tui.screen, dialogs.ActionScreen) and main.acting["plan"].action == "squash"
            await pilot.press("escape")
            await settle(pilot)
            assert len(github.posts()) == posted and tui.screen is main
            await pilot.press("tab", "3")  # the list's To Review: someone else's, where Merge is dimmed
            await settle(pilot)
            assert main.pr.key == "acme/app#7" and main.query_one("#merge").disabled


async def test_read_only_keeps_the_comment_a_draft():
    with FakeGitHub(fixture()) as github:
        reader = make_app(github, forge=GitHubProvider(read_only=True))
        async with reader.run_test(size=(80, 40)) as pilot:  # no bar opens
            await settle(pilot)
            main = reader.main
            posted = len(github.posts())
            await pilot.press("v")
            await settle(pilot)
            assert main.submitting is None
            await pilot.press("C", *"kept", "ctrl+s")
            await settle(pilot)
            assert main.submitting is None and [n["body"] for n in main.drafts.notes] == ["kept"]
            assert len(github.posts()) == posted


async def test_a_personal_repository_is_only_watched():
    """Personal: watched only, so no review either."""
    with FakeGitHub(fixture()) as github:
        tui = make_app(github)
        async with tui.run_test(size=(80, 40)) as pilot:
            await settle(pilot)
            main = tui.main
            await pilot.press("s")
            await settle(pilot)
            await pilot.press(*"pers", "enter")
            await settle(pilot)
            assert main.scope_kind == "personal"
            await pilot.press("v", "C")
            await settle(pilot)
            assert main.submitting is None and main.editing is None and not github.posts()


async def test_popups_draw_every_row():
    """The actions popup and the bulk update list draw every row at 70x30, with the keys to press."""
    with FakeGitHub(stack_fixture()) as github:
        tui = make_app(github)
        async with tui.run_test(size=(70, 30)) as pilot:
            await settle(pilot)
            main = tui.main
            await pilot.press("1")
            await settle(pilot)
            listing = main.query_one("#list")
            listing.go(next(i for i, r in enumerate(listing.rows) if isinstance(r, core.PrRow) and r.number == 21))
            await settle(pilot)
            await pilot.press("M")
            await settle(pilot)
            shown = "\n".join(screen_text(tui))
            state = main.acting["state"]
            assert "Actions: acme/app#21" in shown and "y  send" in shown and "esc  close" in shown, shown
            for _action, label, key, reason in core.action_menu(state):
                assert (f"{label}: " if reason else f" {key}  {label}") in shown, (label, shown)  # every row, keyed
            assert "This branch is out-of-date with the base branch" in shown  # GitHub's merge box wording
            await pilot.press("escape", "U")
            await settle(pilot)
            shown = "\n".join(screen_text(tui))
            for item in main.acting["items"]:
                assert item.key in shown, (item.key, shown)
            assert "y updates the chosen ones" in shown and not github.posts()


@pytest.mark.parametrize(("size", "most"), [((80, 40), core.PANEL_LINES), ((80, 30), 3)])
async def test_details_panel(size, most):
    """The details panel: a titled border, no white rule, fewer lines in a short pane while the list keeps its rows."""
    with FakeGitHub(fixture()) as github:
        tui = make_app(github)
        async with tui.run_test(size=size) as pilot:
            await settle(pilot)
            main = tui.main
            panel, listing = main.query_one("#details"), main.query_one("#list")
            lines = str(panel.content).split("\n")
            assert panel.display and lines[0] == "Change 7" and len(lines) <= most, (size, lines)
            assert listing.size.height >= 3, (size, listing.size)
            shown = screen_text(tui)
            assert any("#7  Open" in line for line in shown), shown
            assert not any(set(line.strip()) == {"─"} for line in shown)  # no bare rule across a pane
