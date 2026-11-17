# SPDX-FileCopyrightText: 2026 Cristiano Carvalho
# SPDX-License-Identifier: Apache-2.0
"""Tree and diff focus: ctrl+h and ctrl+l move focus between the file tree and the diff without hiding the tree, and
the tree keeps its folded folders, cursor and current file wherever focus goes and whenever it is rebuilt."""

from textual import events

from fake_github import FakeGitHub, fixture, long_fixture
from support import make_app, settle


def folders(tree):
    return {
        line.node.label.plain: line.node.is_expanded
        for line in tree._tree_lines
        if line.node.data is None and line.node is not tree.root
    }


async def test_focus_moves_between_the_tree_and_the_diff():
    with FakeGitHub(long_fixture()) as github:
        tui = make_app(github)
        async with tui.run_test(size=(120, 40)) as pilot:
            await settle(pilot)
            main = tui.main
            diff, tree = main.query_one("#diff"), main.query_one("#files")
            await pilot.press("tab", "4")
            assert tui.focused is diff and main.tree_on()
            await pilot.press("ctrl+h")  # to the tree; the diff's ctrl+h does not hide or toggle anything
            assert tui.focused is tree and main.tree_on()
            await pilot.press("ctrl+h")  # in the tree it is a no-op
            assert tui.focused is tree
            await pilot.press("g", "g")  # fold the first folder, then rest the cursor on another line
            while tree.cursor_node.data is not None:
                await pilot.press("j")
            await pilot.press("h")
            folded = folders(tree)
            assert list(folded.values()).count(False) == 1, folded
            await pilot.press("j")
            line, node = tree.cursor_line, tree.cursor_node
            await pilot.press("ctrl+l")  # back to the diff; the tree stays on screen
            await settle(pilot)
            assert tui.focused is diff and main.query_one("#sidebar").display and main.tree_on()
            await pilot.press("ctrl+l")  # in the diff it is a no-op
            assert tui.focused is diff
            await pilot.press("ctrl+h")
            await settle(pilot)
            assert tui.focused is tree and tree.cursor_line == line and tree.cursor_node is node
            assert folders(tree) == folded
            await pilot.press("f", "f")  # f still goes to the diff and back, with the same place kept
            await settle(pilot)
            assert tui.focused is tree and tree.cursor_line == line and folders(tree) == folded
            await pilot.press("ctrl+l", "e", "e")  # hiding and showing the tree keeps it too
            await settle(pilot)
            assert main.tree_on() and folders(tree) == folded and tree.cursor_line == line, (tree.cursor_line, line)
            await pilot.press("ctrl+h", "V")  # marking a file viewed rebuilds the tree: still the same place
            await settle(pilot)
            assert folders(tree) == folded and tree.cursor_line == line
            await pilot.press("ctrl+l", "right_curly_bracket")  # the next file moves the cursor to the open file
            await settle(pilot)
            assert tree.cursor_node.data == main.file_index and folders(tree) == folded, (
                main.file_index,
                folders(tree),
            )


async def test_a_late_focus_message_does_not_move_the_pane():
    """Opening by link focuses the list on mount, then the diff. Each focus message reaches the screen through the
    focused widget's own parents, so on a busy machine the list's can arrive last: it must not take the pane back,
    or the pull request's arrival hands focus to the list."""
    with FakeGitHub(fixture()) as github:
        tui = make_app(github, opening=("acme/app", 7))
        async with tui.run_test(size=(80, 40)) as pilot:
            await settle(pilot)
            main = tui.main
            listing, diff = main.query_one("#list"), main.query_one("#diff")
            assert tui.focused is diff and main.focus_pane == "diff"
            main.post_message(events.DescendantFocus(listing))  # the list's message, delivered after the diff's
            await settle(pilot)
            assert main.focus_pane == "diff", main.focus_pane
            main.refocus()  # what a pull request arriving does
            await settle(pilot)
            assert tui.focused is diff and main.focus_pane == "diff", (tui.focused, main.focus_pane)
