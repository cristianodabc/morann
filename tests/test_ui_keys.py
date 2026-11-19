# SPDX-FileCopyrightText: 2026 Cristiano Carvalho
# SPDX-License-Identifier: Apache-2.0
"""The keyboard: every control the mouse reaches has a key, shown where there is room (the top bar's chips and scope
key, the header's buttons), and the vim motions: counts, gg and G, H and L, ctrl+d ctrl+u ctrl+f ctrl+b, zt zz zb,
search with / n N, ctrl+o and ctrl+i, ctrl+e and ctrl+y, z., and { } between the list's repositories. The keys that
were already there keep working."""

from fake_github import FakeGitHub, fixture, long_fixture
from morann import chrome, core, vimkeys
from support import make_app, settle


def test_vim_helpers():
    jumps = vimkeys.Jumps()
    assert jumps.back("here") is None and jumps.forward() is None  # nothing recorded: nowhere to go
    jumps.clear()
    jumps.record("a")
    jumps.record("b")
    assert jumps.back("c") == "b" and jumps.back("c") == "a" and jumps.back("c") is None  # c was kept at the end
    assert jumps.forward() == "b" and jumps.forward() == "c" and jumps.forward() is None
    jumps.record("a")  # a place seen before moves to the end instead of repeating
    assert jumps.items == ["b", "c", "a"] and jumps.at == 3
    for number in range(vimkeys.JUMP_LIMIT + 20):
        jumps.record(number)
    assert len(jumps.items) == vimkeys.JUMP_LIMIT
    rows = [
        core.ViewRow("add", "import Json"),
        core.ViewRow("comment", "", body="why import?", author="ann"),
        core.ViewRow("info", "import", selectable=False),
        core.ViewRow("ctx", "other"),
    ]
    assert vimkeys.search_matches(rows, "import") == [
        0,
        1,
    ]  # a lower-case query ignores case, skips rows the cursor skips
    assert vimkeys.search_matches(rows, "Import") == [] and vimkeys.search_matches(rows, "Json") == [
        0
    ]  # a capital does not
    assert vimkeys.search_matches(rows, "ann") == [1] and vimkeys.search_matches(rows, "") == []


async def test_hints():
    """The chips, the scope button and the Merge button show their key; each key works; esc dismisses a pop-up note."""
    with FakeGitHub(fixture()) as github:
        tui = make_app(github)
        async with tui.run_test(size=(100, 40)) as pilot:
            await settle(pilot)
            main = tui.main
            top = str(main.query_one("#topinfo").content)
            assert "1 failing (!)" in top and "1 drafts (d)" in top and "1 mine" in top and "(m)" not in top, top
            assert main.query_one("#scopekey").display and str(main.query_one("#scopekey").content) == "s"
            assert str(main.query_one("#scope").label).startswith("Mine (")  # the button itself is untouched
            for key, name in (
                ("exclamation_mark", "failing"),
                ("b", "behind"),
                ("d", "draft"),
            ):  # a click on a chip, by key
                await pilot.press(key)
                await settle(pilot)
                assert main.attention_filter == name, (key, main.attention_filter)
                assert f"{name} only" in " ".join(r.text for r in main.query_one("#list").rows if hasattr(r, "text"))
                await pilot.press(key)
                assert main.attention_filter == ""
            await pilot.press("s")
            await settle(pilot)
            assert type(tui.screen).__name__ == "ScopeScreen"  # the scope button, by key
            await pilot.press("escape")
            await pilot.press("tab")  # the lower pane has the keys: the hints leave where they would not work
            await settle(pilot)
            top = str(main.query_one("#topinfo").content)
            assert (
                "(!)" not in top and "(d)" not in top and "1 failing" in top and not main.query_one("#scopekey").display
            ), top
            assert main.query_one("#prline").tooltip.endswith("/ searches")
            main.notify("a pop-up note", timeout=30)
            await pilot.pause()
            assert len(tui._notifications) >= 1
            await pilot.press("escape")  # a toast is dismissed by a click otherwise
            await pilot.pause()
            assert len(tui._notifications) == 0
            await pilot.press("tab")
        narrow = make_app(github)
        async with narrow.run_test(size=(70, 30)) as pilot:  # no room: the counts stay short and bare
            await settle(pilot)
            top = str(narrow.main.query_one("#topinfo").content)
            assert "(!)" not in top and "(d)" not in top and not narrow.main.query_one("#scopekey").display, top
        own = make_app(github)
        async with own.run_test(size=(100, 40)) as pilot:
            await settle(pilot)
            await pilot.press("1")  # Mine: #5 is mine
            await settle(pilot)
            assert str(own.main.query_one("#merge").label) == "Merge M"
            await pilot.press("M")
            await settle(pilot)
            assert own.main.acting is not None  # the button's key
            await pilot.press("escape")


async def test_motions():
    """Counts, gg and G, H and L, and the page keys, in the diff, in the list and in the file tree."""
    with FakeGitHub(long_fixture()) as github:
        tui = make_app(github)
        async with tui.run_test(size=(80, 24)) as pilot:
            await settle(pilot)
            main = tui.main
            diff = main.query_one("#diff")
            await pilot.press("tab")
            await settle(pilot)
            assert main.mode == "files" and len(diff.rows) > 100, len(diff.rows)
            rows = diff.selectable_rows()
            height = diff.size.height
            await pilot.press("G")
            assert diff.cursor == rows[-1]  # existing: G is the bottom
            await pilot.press("g", "g")
            assert diff.cursor == rows[0] and diff.scroll_offset.y <= diff.starts[rows[0]], (
                diff.cursor,
                rows[:3],
                diff.scroll_offset.y,
            )
            await pilot.press("5", "j")
            assert diff.cursor == rows[5], (diff.cursor, rows[:8])
            await pilot.press("5", "G")  # the fifth row, as in vim the fifth line
            assert diff.cursor == rows[4]
            await pilot.press("7", "g", "g")
            assert diff.cursor == rows[6]
            await pilot.press("9", "k")  # a count stops at the top
            assert diff.cursor == rows[0]
            await pilot.press("6", "escape", "j")  # esc drops the count
            assert diff.cursor == rows[1] and main.count == ""
            await pilot.press("g", "g", "ctrl+d")
            half = diff.starts[diff.cursor]
            await pilot.press("g", "g", "ctrl+f")
            whole = diff.starts[diff.cursor]
            assert 0 < half < whole and whole >= height - 1, (half, whole, height)  # ctrl+d is half of ctrl+f
            await pilot.press("ctrl+b")
            assert diff.starts[diff.cursor] < whole
            await pilot.press("g", "g", "ctrl+f", "ctrl+f", "ctrl+u")  # the existing half page up
            assert diff.starts[diff.cursor] > 0
            await pilot.press("g", "g", "5", "ctrl+d")
            before = diff.starts[diff.cursor]
            await pilot.press("g", "g", "ctrl+d")
            assert before > diff.starts[diff.cursor], "5ctrl+d goes further than one"
            await pilot.press("g", "g", "ctrl+f", "ctrl+f")
            offset = diff.scroll_offset.y
            assert offset > 0
            await pilot.press("H")  # the first row that starts in the view; the view stays

            def top_row():
                row = diff.row_at_line(0)
                return row + 1 if diff.starts[row] < diff.scroll_offset.y else row

            assert diff.cursor == top_row() and diff.scroll_offset.y == offset
            height = diff.size.height
            await pilot.press("L")
            assert diff.scroll_offset.y <= diff.starts[diff.cursor] < diff.scroll_offset.y + height
            assert diff.cursor == diff.row_at_line(height - 1) and diff.scroll_offset.y == offset
            await pilot.press("H", "5", "L")  # the fifth row from the bottom is above L's own row
            assert diff.cursor == diff.row_at_line(height - 1) - 4
            await pilot.press("H", "5", "H")
            assert diff.cursor == top_row() + 4
            await pilot.press("M")  # M is still the actions popup, not the middle of the view
            await settle(pilot)
            assert main.acting is not None
            await pilot.press("escape")
            await settle(pilot)
            assert main.acting is None
            await pilot.press("tab")  # the list: 4-9 start a count there, 1-3 are still the tabs
            assert main.focus_pane == "list" and tui.focused is main.query_one("#list")
            listing = main.query_one("#list")
            assert main.tab == "review"
            await pilot.press("G")
            assert listing.cursor == listing.selectable_rows()[-1]
            await pilot.press("5", "k")
            assert listing.cursor == listing.selectable_rows()[0] and main.count == ""
            await pilot.press("3")  # a tab key that is not part of a count
            assert main.tab == "review"
            await pilot.press("1")
            assert main.tab == "mine"
            await pilot.press("3")
            assert main.tab == "review"


async def test_prefixes():
    """z still maximizes and g still groups; a quick second key turns them into zt zz zb and gg, and puts the first back."""
    with FakeGitHub(long_fixture()) as github:
        tui = make_app(github)
        async with tui.run_test(size=(80, 24)) as pilot:
            await settle(pilot)
            main = tui.main
            clock = [100.0]
            main.keyclock = lambda: clock[0]  # time that only moves when the check says so

            def later():
                clock[0] += 5

            listing, diff = main.query_one("#list"), main.query_one("#diff")
            assert main.grouped
            await pilot.press("g")  # alone: the list groups by repository, as it always did
            assert not main.grouped
            later()
            await pilot.press("g")
            assert main.grouped  # a g a long time after is a g again
            later()
            await pilot.press("G")
            assert listing.cursor == listing.selectable_rows()[-1]
            await pilot.press("g")  # the first g of gg groups, as always
            assert not main.grouped
            await pilot.press("g")  # the second, quickly after, puts that back and goes to the top
            assert main.grouped and listing.cursor == listing.selectable_rows()[0]
            listing.go(next(i for i, r in enumerate(listing.rows) if getattr(r, "key", None) == "acme/app#7"))
            await settle(pilot)  # the pull request with the long diff, for the scrolling below
            assert main.pr is not None and main.pr.key == "acme/app#7"
            later()
            await pilot.press("z")  # alone: z maximizes the lower pane
            assert main.max_diff and main.focus_pane == "diff"
            later()
            await pilot.press("z")
            assert (
                not main.max_diff and main.focus_pane == "diff"
            )  # maximizing leaves the focus below, as it always did
            await settle(pilot)
            assert len(diff.selectable_rows()) > 100, (len(diff.rows), main.mode, main.pr and main.pr.key, tui.focused)
            await pilot.press("g", "g", "9", "9", "j")  # two digits make 99
            assert diff.cursor == diff.selectable_rows()[99]
            await pilot.press("g", "g", "ctrl+f", "ctrl+f", "H", "5", "j")
            later()
            height = diff.size.height
            await pilot.press("z", "t")  # the maximize came back undone, and the cursor row is at the top
            await pilot.pause(0.3)
            assert not main.max_diff and main.focus_pane == "diff" and tui.focused is diff
            assert diff.scroll_offset.y == diff.starts[diff.cursor], (diff.scroll_offset.y, diff.starts[diff.cursor])
            later()
            await pilot.press("z", "b")
            await pilot.pause(0.3)
            assert diff.scroll_offset.y + height - 1 == diff.span(diff.cursor)[1] and not main.max_diff, (
                diff.scroll_offset.y,
                height,
                diff.size.height,
                diff.span(diff.cursor),
                diff.max_scroll_y,
            )
            later()
            await pilot.press("z", "z")
            await pilot.pause(0.3)
            middle = diff.starts[diff.cursor] - diff.scroll_offset.y
            assert abs(middle - (height - 1) // 2) <= 1 and not main.max_diff, (middle, height)
            later()
            await pilot.press("z", "x")  # not one of the three: the z maximized, x is its own key
            assert main.max_diff
            later()
            await pilot.press("z")
            assert not main.max_diff
            later()
            await pilot.press("f")  # the tree: z keeps its meaning there too, undone by a quick t
            await pilot.press("z", "t")
            await pilot.pause(0.3)
            assert not main.max_diff and tui.focused is main.query_one("#files")


async def test_search():
    """/ searches the lower pane as you type, enter keeps it, n and N step through the matches and wrap, esc cancels;
    without a search n is still the next thread; in the list / is still the filter and n, N step through what it kept."""
    with FakeGitHub(long_fixture()) as github:
        tui = make_app(github)
        async with tui.run_test(size=(100, 30)) as pilot:
            await settle(pilot)
            main = tui.main
            diff, box = main.query_one("#diff"), main.query_one("#search")
            await pilot.press("tab")
            await settle(pilot)
            await pilot.press("n")  # no search: still the next thread
            assert diff.current().thread is not None and main.search is None
            await pilot.press("g", "g")
            assert diff.cursor == diff.selectable_rows()[0]
            await pilot.press("N")
            assert main.search is None  # says so, goes nowhere
            await pilot.press("slash")
            assert box.display and tui.focused is box
            await pilot.press(*"line 7")  # as it is typed: the first line 7 (also line 70..79 start the same)
            assert diff.current().text == "line 7" and main.search == "line 7"
            await pilot.press("escape")
            assert (
                not box.display and main.search is None and diff.cursor == diff.selectable_rows()[0]
            )  # back where it began
            assert tui.focused is diff
            await pilot.press("slash", *"nothing like this", "enter")
            await settle(pilot)
            assert main.search is None and diff.cursor == diff.selectable_rows()[0] and tui.focused is diff
            await pilot.press("slash", *"line 7", "enter")
            await settle(pilot)
            matches = vimkeys.search_matches(diff.rows, "line 7")
            assert len(matches) == 11 and diff.cursor == matches[0] and tui.focused is diff and not box.display, matches
            assert "/line 7 1/11" in str(main.query_one("#prline").content)
            await pilot.press("n")
            assert diff.cursor == matches[1] and "/line 7 2/11" in str(main.query_one("#prline").content)
            await pilot.press("5", "n")  # a count steps that many matches
            assert diff.cursor == matches[6]
            await pilot.press("N")
            assert diff.cursor == matches[5]
            await pilot.press("G", "N")  # from the end, the last match
            assert diff.cursor == matches[-1]
            await pilot.press("n")
            assert diff.cursor == matches[0]  # wrapped
            await pilot.press("p")  # p is still the previous thread, search or not
            assert diff.current().thread is not None and diff.cursor < matches[0]
            await pilot.press("escape")
            await settle(pilot)
            assert main.search is None
            await pilot.press("g", "g", "n")  # n is the thread key again
            assert diff.current().thread == "T2"
            await pilot.press("2")  # the search works on the other tabs of the pane too
            await pilot.press("slash", *"Use json", "enter")
            await settle(pilot)
            assert (
                main.mode == "commits"
                and main.search == "Use json"
                and diff.current() is not None
                and "Use json" in diff.current().text
            ), (main.mode, main.search, diff.current())
            await pilot.press("escape", "4")
            # Smart case: lower case ignores it, a capital matches it exactly.
            await pilot.press("slash", *"Line", "enter")
            await settle(pilot)
            assert main.search is None and tui.focused is diff  # no "Line" with a capital in the file
            await pilot.press("tab")  # the list
            listing = main.query_one("#list")
            await pilot.press("n")  # no filter yet: nothing to step through, and the cursor stays
            assert listing.current().key == "acme/app#7"
            await pilot.press("slash", *"acme", "enter")
            await settle(pilot)
            assert main.filter == "acme" and tui.focused is listing  # the list's filter, as before
            await pilot.press("n")  # the next pull request the filter kept
            assert listing.current().key == "acme/lib#9"
            await pilot.press("n")
            assert listing.current().key == "acme/app#7"  # wrapped
            await pilot.press("N")
            assert listing.current().key == "acme/lib#9"
            await pilot.press("slash", "escape")  # esc in the filter box still clears it
            assert main.filter == ""


async def test_jumps():
    """ctrl+o goes back to where a jump left, ctrl+i and O forward; tab is still tab."""
    with FakeGitHub(long_fixture()) as github:
        tui = make_app(github)
        async with tui.run_test(size=(100, 30)) as pilot:
            await settle(pilot)
            main = tui.main
            diff, listing = main.query_one("#diff"), main.query_one("#list")
            await pilot.press("tab")
            await settle(pilot)
            rows = diff.selectable_rows()
            await pilot.press("j", "j")
            here = diff.cursor
            await pilot.press("G")
            assert diff.cursor == rows[-1]
            await pilot.press("ctrl+o")
            assert diff.cursor == here  # back to where G left
            await pilot.press("ctrl+i")  # forward, where the terminal tells ctrl+i from tab
            assert diff.cursor == rows[-1]
            await pilot.press("ctrl+o", "O")
            assert diff.cursor == rows[-1]
            await pilot.press("ctrl+o", "ctrl+o")  # past the oldest: stays
            assert diff.cursor == here
            await pilot.press("g", "g")
            await pilot.press("2")  # a tab switch is a jump too
            await settle(pilot)
            assert main.mode == "commits"
            await pilot.press("ctrl+o")
            assert main.mode == "files" and diff.cursor == rows[0]
            await pilot.press("right_curly_bracket")  # and so is the next file
            await settle(pilot)
            assert main.file_index == 1
            await pilot.press("ctrl+o")
            assert main.file_index == 0 and main.mode == "files"
            await pilot.press("tab")  # tab moves focus, whatever ctrl+i does
            assert main.focus_pane == "list"
            first = listing.current().key
            await pilot.press("G")
            assert listing.current().key != first
            await pilot.press("ctrl+o")
            assert listing.current().key == first
            await pilot.press("ctrl+i")
            assert main.focus_pane == "list"


async def test_tree_and_help():
    """The file tree and the help move with the same keys; e, f and enter in the tree still work."""
    with FakeGitHub(long_fixture()) as github:
        tui = make_app(github)
        async with tui.run_test(size=(120, 40)) as pilot:
            await settle(pilot)
            main = tui.main
            await pilot.press("tab", "4")
            await pilot.press("f")
            tree = main.query_one("#files")
            assert tui.focused is tree and tree.last_line >= 4
            await pilot.press("G")
            assert tree.cursor_line == tree.last_line
            await pilot.press("g", "g")
            assert tree.cursor_line == 0
            await pilot.press("3", "j")
            assert tree.cursor_line == 3
            await pilot.press("2", "k")  # in the tree no digit is a tab, so a count starts with any of them
            assert tree.cursor_line == 1
            await pilot.press("ctrl+f")
            assert tree.cursor_line == tree.last_line
            await pilot.press("ctrl+b")
            assert tree.cursor_line == 0
            await pilot.press("L")
            assert tree.cursor_line == min(
                tree.last_line, tree.scroll_offset.y + tree.scrollable_content_region.height - 1
            )
            await pilot.press("H", "3", "ctrl+d")
            assert tree.cursor_line == tree.last_line
            await pilot.press("g", "g", "j")
            assert tree.cursor_line == 1
            leaf = next(line for line in range(tree.last_line + 1) if tree._tree_lines[line].node.data is not None)
            tree.move_cursor_to_line(leaf)
            wanted = tree.cursor_node.data
            await pilot.press("enter")  # enter still opens the file under the cursor
            await settle(pilot)
            assert main.file_index == wanted and tui.focused is main.query_one("#diff"), (main.file_index, wanted)
            await pilot.press("question_mark")
            await settle(pilot)
            body = tui.screen.query_one("#help")
            assert body.max_scroll_y > 0 and body.scroll_y == 0
            await pilot.press("G")
            await pilot.pause()
            assert body.scroll_y == body.max_scroll_y
            await pilot.press("g")
            await pilot.pause()
            assert body.scroll_y == 0
            await pilot.press("ctrl+e", "ctrl+e")  # a line at a time, as j and k do
            await pilot.pause()
            assert body.scroll_y == 2
            await pilot.press("ctrl+y")
            await pilot.pause()
            assert body.scroll_y == 1
            await pilot.press("ctrl+y")
            await pilot.pause()
            assert body.scroll_y == 0
            await pilot.press("ctrl+f")
            await pilot.pause()
            assert body.scroll_y > 0
            await pilot.press("ctrl+d", "ctrl+u", "ctrl+b")
            await pilot.pause()
            assert body.scroll_y == 0
            await pilot.press("escape")
            await settle(pilot)
            assert tui.screen is main


async def test_refresh_hint():
    """The scope carries a muted hint naming what refreshes: r while the list has the keys, ctrl+r below it. It is the
    key line's own cap and muted label, the key it names works, and it goes before the scope, the crumbs or the counts
    would be cut."""
    with FakeGitHub(fixture()) as github:

        def reads():
            return len([c for c in github.calls() if "search(" in c["stdin"]])

        tui = make_app(github)
        async with tui.run_test(size=(140, 40)) as pilot:
            await settle(pilot)
            main = tui.main
            hint = main.query_one("#refreshkey")
            assert hint.display and str(hint.content).split() == ["r", "refresh"], hint.content
            assert hint.content == chrome.key_line([("r", "refresh")], tui.painter.ink)  # no color of its own
            before = reads()
            await pilot.press("r")  # the key it names refreshes
            await settle(pilot)
            assert reads() > before
            await pilot.press("tab")  # the pull request pane: r is something else there, so the hint says ctrl+r
            await settle(pilot)
            assert hint.display and str(hint.content).split() == ["ctrl+r", "refresh"], hint.content
            main.last_refresh = 0.0
            before = reads()
            await pilot.press("ctrl+r")
            await settle(pilot)
            assert reads() > before
        shown = []
        for width in (60, 70, 80, 100, 120, 140, 160):
            narrow = make_app(github)
            async with narrow.run_test(size=(width, 30)) as pilot:
                await settle(pilot)
                bar = narrow.main
                scope, hint, info = (bar.query_one(f"#{name}") for name in ("scope", "refreshkey", "topinfo"))
                assert scope.size.width >= len(str(scope.label)), (width, scope.label)  # the scope is never cut
                if hint.display:  # nothing else is cut for it, and it ends inside the window
                    assert hint.region.right <= width and hint.region.x >= scope.region.right, (width, hint.region)
                    assert info.size.width >= core.width_of(str(info.content)), width
                shown.append(hint.display)
        assert shown[0] is False and shown[-1] is True and shown == sorted(shown), shown  # it goes as room does


async def test_scroll_lines():
    """ctrl+e and ctrl+y scroll the view a line (a count, more) and keep the cursor on its row until the row leaves the
    view; then it takes the nearest row that is wholly in view. The file tree does the same."""
    with FakeGitHub(long_fixture()) as github:
        tui = make_app(github)
        async with tui.run_test(size=(80, 24)) as pilot:
            await settle(pilot)
            main = tui.main
            diff = main.query_one("#diff")
            await pilot.press("tab")
            await settle(pilot)
            rows = diff.selectable_rows()
            height = diff.size.height
            await pilot.press("g", "g", "9", "9", "j")
            assert diff.cursor == rows[99]
            offset = diff.scroll_offset.y
            await pilot.press("ctrl+e")
            assert diff.scroll_offset.y == offset + 1 and diff.cursor == rows[99]  # the row is still in view
            await pilot.press("ctrl+y")
            assert diff.scroll_offset.y == offset and diff.cursor == rows[99]
            await pilot.press("g", "g", "ctrl+f", "ctrl+f", "H")
            cursor, offset = diff.cursor, diff.scroll_offset.y
            await pilot.press("7", "ctrl+e")  # the cursor row scrolls off the top: the first row that starts in view
            assert diff.scroll_offset.y == offset + 7
            first = next(i for i in rows if diff.starts[i] >= diff.scroll_offset.y)
            assert diff.cursor == first and diff.cursor > cursor
            await pilot.press("7", "ctrl+y")
            assert diff.scroll_offset.y == offset
            await pilot.press("L", "8", "ctrl+y")  # off the bottom: the last row that ends in view
            bottom = diff.scroll_offset.y + height
            assert diff.scroll_offset.y == offset - 8
            assert diff.cursor == max(i for i in rows if diff.span(i)[1] < bottom), (diff.cursor, bottom)
            await pilot.press("G")
            end = diff.scroll_offset.y
            await pilot.press("ctrl+e")  # at the end there is nothing to scroll into
            assert diff.scroll_offset.y == end and diff.cursor == rows[-1]
            await pilot.press("g", "g", "9", "ctrl+y")
            assert diff.scroll_offset.y == 0 and diff.cursor == rows[0]  # nor above the top
            await pilot.press("tab")  # the list: its rows move with the same keys
            listing = main.query_one("#list")
            assert listing.scroll_offset.y == 0 and len(listing.visual) > listing.size.height
            await pilot.press("ctrl+e")  # this window shows part of the list
            assert listing.scroll_offset.y == 1 and listing.starts[listing.cursor] >= 1
            await pilot.press("ctrl+y")
            assert listing.scroll_offset.y == 0
        short = make_app(github)
        async with short.run_test(size=(100, 12)) as pilot:  # a window short enough to scroll the file tree
            await settle(pilot)
            await pilot.press("tab", "4", "f")
            tree = short.main.files_tree()
            height = tree.scrollable_content_region.height
            assert short.focused is tree and tree.last_line + 1 > height
            await pilot.press("g", "g")
            assert tree.cursor_line == 0 and tree.scroll_offset.y == 0
            await pilot.press("ctrl+e")  # the cursor line scrolls off the top: it follows
            assert tree.scroll_offset.y == 1 and tree.cursor_line == 1
            await pilot.press("5", "ctrl+e")
            assert tree.scroll_offset.y == min(6, tree.last_line + 1 - height)
            assert tree.cursor_line >= tree.scroll_offset.y
            await pilot.press("G", "9", "ctrl+y")
            assert tree.scroll_offset.y == 0 and tree.cursor_line == height - 1  # it stops at the bottom of the view
            await pilot.press("ctrl+e", "ctrl+y")
            assert tree.cursor_line == height - 1  # still in view: the cursor stays


async def test_place_with_a_dot():
    """z. puts the cursor row in the middle of the view, as zz does, and undoes the maximize its z began."""
    with FakeGitHub(long_fixture()) as github:
        tui = make_app(github)
        async with tui.run_test(size=(80, 24)) as pilot:
            await settle(pilot)
            main = tui.main
            diff = main.query_one("#diff")
            await pilot.press("tab")
            await settle(pilot)
            await pilot.press("g", "g", "9", "9", "j")
            height = diff.size.height
            await pilot.press("z", "full_stop")
            await pilot.pause(0.3)
            middle = diff.starts[diff.cursor] - diff.scroll_offset.y
            assert abs(middle - (height - 1) // 2) <= 1 and not main.max_diff and tui.focused is diff, (middle, height)
            await pilot.press("z", "x")  # not a place: z is still the maximize
            assert main.max_diff


async def test_repository_steps():
    """{ and } in the grouped list go to the previous and next repository, then to the first and last row; a count
    repeats them, ungrouped they are the ends, and ctrl+o comes back."""
    with FakeGitHub(fixture()) as github:
        tui = make_app(github)
        async with tui.run_test(size=(100, 40)) as pilot:
            await settle(pilot)
            main = tui.main
            listing = main.query_one("#list")
            assert [type(row).__name__ for row in listing.rows] == ["GroupRow", "PrRow", "GroupRow", "PrRow"]
            listing.go(1)
            await pilot.press("right_curly_bracket")
            assert listing.cursor == 2
            await pilot.press("right_curly_bracket")  # no repository after this one: the last row
            assert listing.cursor == 3
            await pilot.press("left_curly_bracket")
            assert listing.cursor == 2
            await pilot.press("left_curly_bracket", "left_curly_bracket")  # the header above, then the first row
            assert listing.cursor == 0
            await pilot.press("ctrl+o")  # a jump, as in vim
            assert listing.cursor == 2
            listing.go(0)
            await pilot.press("5", "right_curly_bracket")
            assert listing.cursor == 3
            await pilot.press("g")  # ungroup: one run of pull requests
            await settle(pilot)
            assert not main.grouped and all(isinstance(row, core.PrRow) for row in listing.rows)
            listing.go(0)
            await pilot.press("right_curly_bracket")
            assert listing.cursor == len(listing.rows) - 1
            await pilot.press("left_curly_bracket")
            assert listing.cursor == 0
