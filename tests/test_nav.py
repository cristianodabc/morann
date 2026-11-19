# SPDX-FileCopyrightText: 2026 Cristiano Carvalho
# SPDX-License-Identifier: Apache-2.0
"""Getting around: the key table, and in the app the breadcrumb, the hint bar, the
command line, the ctrl+p jump palette, the app-wide jump list, ctrl+w, gt and gT, and the help's filter."""

from fake_github import FakeGitHub, fixture
from morann import core, dialogs, keymap
from support import make_app, settle


def test_keymap():
    assert keymap.sections_for("tree")[0].title == "File tree" and keymap.sections_for("list")[0].title == "Lists"
    assert [key.keys for key in keymap.hints("list")][:3] == ["j k", "enter", "/"]
    assert all(key.hint for place in keymap.HINTS for key in keymap.hints(place))
    for place, wanted in keymap.HINTS.items():  # every hinted key exists for its place, so none silently drops out
        assert len(keymap.hints(place)) == len(wanted), (place, [k.keys for k in keymap.hints(place)], wanted)
    found = [key for section in keymap.matching(keymap.SECTIONS, "resolve") for key in section.keys]
    assert "x" in [key.keys for key in found] and all("resolve" in key.text for key in found)
    assert "Commands" in [section.title for section in keymap.matching(keymap.SECTIONS, "commands")]
    assert keymap.matching(keymap.SECTIONS, "zzzz") == [] and len(keymap.matching(keymap.SECTIONS, " ")) > 5


def hints(main):
    """The hint bar's words, one space apart."""
    return " ".join(main.query_one("#status").content.plain.split())


def crumbs(main):
    return main.query_one("#crumbs").content.plain.strip()


async def test_breadcrumb_and_hints_follow_focus():
    with FakeGitHub(fixture()) as github:
        tui = make_app(github)
        async with tui.run_test(size=(100, 40)) as pilot:
            await settle(pilot)
            main = tui.main
            assert crumbs(main) == "acme > app > #7 > Files", crumbs(main)
            assert hints(main).startswith("READING ") and "j k move enter open / filter" in hints(main), hints(main)
            assert hints(main).endswith("? help") and "1/2" in hints(main)  # the position in the list
            await pilot.press("tab", "1")
            await settle(pilot)
            assert crumbs(main).endswith("#7 > Conversation") and "c comment" in hints(main), hints(main)
            await pilot.press("4")
            await settle(pilot)
            diff = main.query_one("#diff")
            diff.go(next(i for i, row in enumerate(diff.rows) if row.kind == "hunk" or not row.anchor))
            await pilot.pause()
            assert "c comment" not in hints(main)  # only the keys that work on the row under the cursor
            diff.go(next(i for i, row in enumerate(diff.rows) if row.anchor))
            await pilot.pause()
            main.show_hints()
            assert "c comment" in hints(main) and "a.py:" in hints(main), hints(main)  # the key, and file and line
            await pilot.press("f")
            await settle(pilot)
            assert "l enter open" in hints(main) and "h fold" in hints(main), hints(main)  # the tree's keys
            await pilot.press("escape", "c", "r")  # r starts the review the comment offers
            await settle(pilot)
            assert main.editing and hints(main).startswith("WRITING ") and "ctrl+s keep esc cancel" in hints(main)
            await pilot.press("escape")
            await pilot.resize_terminal(60, 30)
            await settle(pilot)
            assert main.query_one("#status").content.cell_len <= 60 and hints(main).startswith("REVIEWING")
            assert "j k move" not in hints(main)  # narrow: the keys go before the mode, the position or the progress
        empty = make_app(github)
        empty.main.load_lists = lambda: None
        async with empty.run_test(size=(100, 40)) as pilot:
            await settle(pilot)
            assert crumbs(empty.main) == "Mine > To Review"  # nothing open: the scope and the list's tab


async def test_command_line():
    with FakeGitHub(fixture()) as github:
        tui = make_app(github)
        async with tui.run_test(size=(100, 40)) as pilot:
            await settle(pilot)
            main = tui.main
            line = main.query_one("#cmdline")
            await pilot.press("colon")
            assert main.query_one("#cmdbar").display and hints(main).startswith("COMMAND") and line.has_focus
            await pilot.press(*"ta", "tab")
            assert line.value == "tab "  # one completion: taken, with a space
            await pilot.press("a", "tab")
            assert line.value == "tab all "
            await pilot.press("enter")
            await settle(pilot)
            assert main.tab == "all" and not main.query_one("#cmdbar").display and main.query_one("#status").display
            await pilot.press("colon", *"frob", "enter")  # a mistake keeps the line, with the reason
            await settle(pilot)
            assert main.query_one("#cmdbar").display and line.value == "frob"
            await pilot.press("escape")
            assert not main.query_one("#cmdbar").display and tui.focused is main.query_one("#list")
            await pilot.press("colon", "up")  # the history, newest first
            assert line.value == "frob"
            await pilot.press("up")
            assert line.value == "tab all"
            await pilot.press("down", "down")
            assert line.value == ""
            await pilot.press(*"files", "enter")
            await settle(pilot)
            assert main.mode == "files"
            await pilot.press("colon", *"open 5", "enter")  # a number opens it in the open pull request's repository
            await settle(pilot)
            assert main.pr.key == "acme/app#5"
            await pilot.press("colon", *"repo acme/lib", "enter")
            await settle(pilot)
            assert main.filter == "acme/lib#" and all(
                r.repo == "acme/lib"
                for r in main.query_one("#list").rows
                if isinstance(r, core.PrRow) and r not in main.recent_rows()
            )
            await pilot.press("colon", *"filter", "enter")
            await settle(pilot)
            assert main.filter == ""
            await pilot.press("colon", *"theme nord", "enter")
            await settle(pilot)
            assert tui.theme == "nord"
            await pilot.press("colon", *"theme plaid", "enter")  # no such theme: the line stays, with the names
            await settle(pilot)
            assert tui.theme == "nord" and main.query_one("#cmdbar").display
            await pilot.press("escape")
            await pilot.press("colon", *"scope acme", "enter")
            await settle(pilot)
            assert main.scope_kind == "org:acme"
            await pilot.press("colon", *"help resolve", "enter")
            await settle(pilot)
            assert isinstance(tui.screen, dialogs.HelpScreen) and "resolve" in tui.screen.needle
            assert "x" in [key.keys for section in tui.screen.sections() for key in section.keys]
            await pilot.press("escape", "colon", *"q", "enter")
            await settle(pilot)
        assert tui.return_code is not None or not tui.is_running


async def test_jump_palette():
    with FakeGitHub(fixture()) as github:
        tui = make_app(github)
        async with tui.run_test(size=(100, 40)) as pilot:
            await settle(pilot)
            main = tui.main
            await pilot.press("ctrl+p")
            await settle(pilot)
            picker = tui.screen
            assert isinstance(picker, dialogs.PickerScreen) and len(picker.shown) >= 3
            assert picker.shown[picker.query_one("#picker-list").highlighted] == "acme/app#7"  # the open one
            await pilot.press(*"lib9")
            assert picker.shown[0] == "acme/lib#9"
            await pilot.press("ctrl+u", *"app5")  # Mine's #5: not in this tab's list, so it opens below it
            assert picker.shown[0] == "acme/app#5"
            await pilot.press("enter")
            await settle(pilot)
            assert main.pr.key == "acme/app#5" and main.focus_pane == "diff" and tui.focused is main.query_one("#diff")
            await pilot.press("tab", "ctrl+p", *"app7", "enter")  # #7 is on the list: the list row moves to it
            await settle(pilot)
            assert main.pr.key == "acme/app#7" and main.selected().key == "acme/app#7"
            await pilot.press("ctrl+o")
            await settle(pilot)
            assert main.focus_pane == "list"
            await pilot.press("ctrl+p", *"zzzz")
            assert tui.screen.shown == []
            await pilot.press("escape")
            assert tui.screen is main


async def test_jump_list_crosses_panes_and_pull_requests():
    with FakeGitHub(fixture()) as github:
        tui = make_app(github)
        async with tui.run_test(size=(100, 40)) as pilot:
            await settle(pilot)
            main = tui.main
            await pilot.press("enter")  # from the list row into #7
            await settle(pilot)
            await pilot.press("1")  # its Conversation tab: a jump inside it
            await settle(pilot)
            assert main.focus_pane == "diff" and main.mode == "conversation"
            await pilot.press("ctrl+o")
            await settle(pilot)
            assert main.mode == "files" and main.focus_pane == "diff"
            await pilot.press("ctrl+o")  # past the pull request: the list row it was opened from
            await settle(pilot)
            assert main.focus_pane == "list" and tui.focused is main.query_one("#list")
            await pilot.press("O")  # forward again, into the pull request
            await settle(pilot)
            assert main.focus_pane == "diff" and main.mode == "files"
            await pilot.press("colon", *"open acme/app#5", "enter")  # another pull request
            await settle(pilot)
            assert main.pr.key == "acme/app#5"
            await pilot.press("ctrl+o")  # back to #7, reopened, on the tab and row it was left on
            await settle(pilot)
            assert main.pr.key == "acme/app#7" and main.mode == "files" and main.pending_place is None


async def test_window_keys_and_tab_steps():
    with FakeGitHub(fixture()) as github:
        tui = make_app(github)
        async with tui.run_test(size=(100, 40)) as pilot:
            await settle(pilot)
            main = tui.main
            await pilot.press("ctrl+w", "j")
            assert main.focus_pane == "diff" and tui.focused is main.query_one("#diff")
            await pilot.press("ctrl+w", "k")
            assert main.focus_pane == "list"
            await pilot.press("ctrl+w", "w")
            assert main.focus_pane == "diff"
            await pilot.press("ctrl+w", "x", "j")  # an unknown second key does nothing; j moves again
            assert main.focus_pane == "diff"
            await pilot.press("4")
            await settle(pilot)
            await pilot.press("ctrl+w", "h")
            await settle(pilot)
            assert tui.focused is main.files_tree()
            await pilot.press("ctrl+w", "l")
            assert tui.focused is main.query_one("#diff")
            await pilot.press("g", "t")  # the lower pane's next tab wraps to the first
            await settle(pilot)
            assert main.mode == "conversation"
            await pilot.press("g", "T")
            await settle(pilot)
            assert main.mode == "files"
            await pilot.press("ctrl+w", "k")
            grouped = main.grouped
            await pilot.press("g", "t")  # in the list: the next tab, and the grouping g toggled is put back
            await settle(pilot)
            assert main.tab == "all" and main.grouped == grouped
            await pilot.press("g", "T", "g", "T")
            await settle(pilot)
            assert main.tab == "pending"  # All, To Review, Pending


async def test_more_window_keys():
    """ctrl+w t and b are the top and bottom window (the list, the pull request), p the previous one, ctrl+w ctrl+w the
    other, and ctrl+w ctrl+h and ctrl+l the file tree and the diff, as vim has them."""
    with FakeGitHub(fixture()) as github:
        tui = make_app(github)
        async with tui.run_test(size=(100, 40)) as pilot:
            await settle(pilot)
            main = tui.main
            await pilot.press("ctrl+w", "b")
            assert main.focus_pane == "diff" and tui.focused is main.query_one("#diff")
            await pilot.press("ctrl+w", "t")
            assert main.focus_pane == "list" and tui.focused is main.query_one("#list")
            await pilot.press("ctrl+w", "p")
            assert main.focus_pane == "diff"
            await pilot.press("ctrl+w", "ctrl+w")
            assert main.focus_pane == "list"
            await pilot.press("ctrl+w", "ctrl+w")
            assert main.focus_pane == "diff"
            await pilot.press("4")
            await settle(pilot)
            await pilot.press("ctrl+w", "ctrl+h")
            await settle(pilot)
            assert tui.focused is main.files_tree()
            await pilot.press("ctrl+w", "ctrl+l")
            assert tui.focused is main.query_one("#diff")


async def test_help_filters_by_key_or_words():
    with FakeGitHub(fixture()) as github:
        tui = make_app(github)
        async with tui.run_test(size=(100, 40)) as pilot:
            await settle(pilot)
            await pilot.press("question_mark")
            await settle(pilot)
            help_screen = tui.screen
            assert help_screen.sections()[0].title == "Lists"  # the list has focus: its keys first
            assert not help_screen.query_one("#help-filter").display
            await pilot.press("slash", *"thread")
            await settle(pilot)
            titles = [section.title for section in help_screen.sections()]
            assert titles and all(
                "thread" in f"{key.keys} {key.text} {section.title}"
                for section in help_screen.sections()
                for key in section.keys
            ), titles
            await pilot.press("escape")  # clears the filter first
            assert tui.screen is help_screen and not help_screen.query_one("#help-filter").display
            assert help_screen.needle == ""
            await pilot.press("escape")
            assert tui.screen is tui.main


async def test_brackets_step_tabs_and_make_motions():
    """[ and ] still step through the tabs; a quick letter after one puts the tab back and moves instead."""
    with FakeGitHub(fixture()) as github:
        tui = make_app(github)
        async with tui.run_test(size=(100, 40)) as pilot:
            await settle(pilot)
            main = tui.main
            await pilot.press("tab", "4")
            await settle(pilot)
            await pilot.press("right_square_bracket")
            await settle(pilot)
            assert main.mode == "conversation"  # at once, wrapping round
            await pilot.press("left_square_bracket")
            await settle(pilot)
            assert main.mode == "files"
            diff = main.query_one("#diff")
            await pilot.press("g", "g", "right_square_bracket", "c")
            await settle(pilot)
            assert main.mode == "files" and diff.current().kind in ("add", "del"), diff.current()
            first = diff.cursor
            await pilot.press("right_square_bracket", "c")
            await settle(pilot)
            assert diff.cursor > first and diff.current().kind in ("add", "del")
            await pilot.press("left_square_bracket", "c")
            await settle(pilot)
            assert diff.cursor == first
            await pilot.press("right_square_bracket", "h")
            await settle(pilot)
            assert diff.current().kind == "hunk"
            await pilot.press("right_square_bracket", "u")  # the next unresolved thread
            await settle(pilot)
            row = diff.current()
            assert row.kind == "thread" and not main.pr.thread(row.thread).resolved
            await pilot.press("right_square_bracket", "f")
            await settle(pilot)
            assert main.file_index == 1 and main.mode == "files"
            await pilot.press("left_square_bracket", "d")  # back to the draft? none here: a note says so
            await settle(pilot)
            assert main.file_index == 1
            await pilot.press("colon", *"prev file", "enter")
            await settle(pilot)
            assert main.file_index == 0
            await pilot.press("colon", *"next nowhere", "enter")  # an unknown kind keeps the line with the reason
            await settle(pilot)
            assert main.query_one("#cmdbar").display


async def test_the_palette_reaches_files_and_commands():
    with FakeGitHub(fixture()) as github:
        tui = make_app(github)
        async with tui.run_test(size=(100, 40)) as pilot:
            await settle(pilot)
            main = tui.main
            await pilot.press("ctrl+p", *"newname")  # a file of the open pull request
            await settle(pilot)
            assert tui.screen.shown[0] == ("file", 2)
            await pilot.press("enter")
            await settle(pilot)
            assert main.mode == "files" and main.file_index == 2 and main.focus_pane == "diff"
            await pilot.press("ctrl+p", *":unified", "enter")  # a command that needs nothing more runs
            await settle(pilot)
            assert not main.split_view and tui.screen is main
            await pilot.press("ctrl+p", *":next", "enter")  # one that takes a word waits on the command line
            await settle(pilot)
            assert main.query_one("#cmdbar").display and main.query_one("#cmdline").value == "next "
