# SPDX-FileCopyrightText: 2026 Cristiano Carvalho
# SPDX-License-Identifier: Apache-2.0
"""The draft pull request count and filter: the top bar's `N drafts` counts the open pull requests GitHub marks as
draft (not the local unsent comments, which read `unsent N`), and d, or a click on the count, narrows the list to
them."""

from fake_github import FakeGitHub, fixture, pr_row, search_node
from morann import attention, core
from support import make_app, pr_keys, settle


def test_draft_pull_requests_are_counted_once():
    mine = [pr_row(5, draft=True), pr_row(6)]
    review = [
        pr_row(7, draft=True),
        pr_row(8),
        pr_row(5, draft=True),
        pr_row(9, repo="acme/lib", draft=True),
    ]  # #5 is in both lists
    parts = attention.summary(mine, review)
    assert parts == [(2, "mine", ""), (4, "to review", ""), (3, "drafts", "draft")], parts  # each pull request once
    assert attention.summary_text(parts) == "2 mine  4 to review  3 drafts"
    assert attention.summary_text(parts, narrow=True) == "2m 4r 3d"
    assert [r.number for r in [*mine, *review] if attention.matches(r, "draft")] == [5, 7, 5, 9]
    assert attention.summary([pr_row(1)], [pr_row(2)]) == [(1, "mine", ""), (1, "to review", "")]  # none: left out
    wide = attention.summary([], [], ([pr_row(4, draft=True), pr_row(5), pr_row(6, draft=True)], 40))
    assert wide == [(40, "open", ""), (2, "drafts", "draft")], wide  # the scope's rows count too
    assert "draft" in attention.FILTERS and attention.KEYS["draft"] == "d"


def draft_fixture():
    """Mine: #5 draft and #6. To Review: #7 draft, #8, #9 draft in acme/lib and #10. Open in acme: #31 draft, #32."""
    data = fixture()
    data["search"]["mine"] = [search_node(5, draft=True, decision="", author="me"), search_node(6, author="me")]
    data["search"]["review"] = [
        search_node(7, draft=True),
        search_node(8),
        search_node(9, repo="acme/lib", draft=True, author="kim"),
        search_node(10),
    ]
    data["scoped"]["org:acme"] = [
        search_node(31, draft=True, author="kim"),
        search_node(32, repo="acme/lib", author="me"),
    ]
    return data


async def test_draft_prs_in_the_app():
    with FakeGitHub(draft_fixture()) as github:  # the drafts folder of this throwaway directory stays empty
        tui = make_app(github)
        async with tui.run_test(size=(100, 40)) as pilot:
            await settle(pilot)
            main = tui.main
            listed = main.query_one("#list")

            top = str(main.query_one("#topinfo").content)
            assert "3 drafts" in top and "unsent 0" in top and "drafts 0" not in top, top
            assert "unsent 0" in main.sub_title and "drafts" not in main.sub_title, main.sub_title
            assert sorted(pr_keys(listed)) == ["acme/app#10", "acme/app#7", "acme/app#8", "acme/lib#9"], pr_keys(
                listed
            )  # To Review
            await pilot.press("d")  # only the draft pull requests of the open list
            await settle(pilot)
            assert sorted(pr_keys(listed)) == ["acme/app#7", "acme/lib#9"] and main.attention_filter == "draft", (
                pr_keys(listed)
            )
            assert any("draft only (d)" in line.text for line in listed.rows if hasattr(line, "text")), listed.rows
            await pilot.press("d")
            await settle(pilot)
            assert len(pr_keys(listed)) == 4 and not main.attention_filter
            info = main.query_one("#topinfo")  # a click on the count filters the same way
            await pilot.click("#topinfo", offset=(str(info.content).index("3 drafts") + 1, 0))
            await settle(pilot)
            assert sorted(pr_keys(listed)) == ["acme/app#7", "acme/lib#9"], pr_keys(listed)
            await pilot.press("1")  # the filter follows the tab; the count stays the one of every list on hand
            await settle(pilot)
            assert pr_keys(listed) == ["acme/app#5"] and "3 drafts" in str(main.query_one("#topinfo").content), pr_keys(
                listed
            )
            await pilot.press("d")
            await settle(pilot)
            assert pr_keys(listed) == ["acme/app#5", "acme/app#6"] and not main.attention_filter, pr_keys(listed)
        with FakeGitHub(draft_fixture()) as other:  # local unsent comments are a different count: here there is one
            kept = core.DraftStore(other.dir / "drafts")
            note = kept.load("acme/app", 8)
            note.add_note("unsent")
            kept.save(note)
            again = make_app(other, store=kept)
            async with again.run_test(size=(100, 40)) as pilot:
                await settle(pilot)
                top = str(again.main.query_one("#topinfo").content)
                assert "3 drafts" in top and "unsent 1" in top, top  # draft pull requests: 3; unsent comments: 1
