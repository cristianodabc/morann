# SPDX-FileCopyrightText: 2026 Cristiano Carvalho
# SPDX-License-Identifier: Apache-2.0
"""Morann's widgets: the scrolling row views, the inline editor, the file tree and the review bar. The dialogs are in
dialogs.py, the header and command line in chrome.py, the statusline in statusline.py."""

from __future__ import annotations

import shutil
import subprocess
import webbrowser
from typing import ClassVar

from textual import events
from textual.binding import Binding, BindingType
from textual.containers import Vertical
from textual.geometry import Size
from textual.message import Message
from textual.scroll_view import ScrollView
from textual.strip import Strip
from textual.widgets import (
    Tabs,
    TextArea,
    Tree,
)

from morann import core

STACK_BELOW = 24  # rows: a shorter window shows one pane at a time


DEBOUNCE = 0.25  # seconds the list cursor rests before the pull request under it loads


RECENT = 8  # pull requests opened by link that the list keeps on top


WIDE = 90  # columns: a narrower lower pane hides the file tree; f shows it over the diff


ROOMY = 30  # rows: a taller window keeps a blank line under the header


SPIN = "|/-\\"  # the activity spinner in the top bar


REFRESH_GAP = 2  # seconds: a second refresh within this is ignored


EDITOR_HEIGHT = 8  # rows an inline editor takes under its line


LIST_MIN = 3  # rows the list keeps before the details panel takes any


ROW_ACTIONS = {
    "comment": "anchor",
    "reply": "thread",
    "resolve": "thread",
    "fold": "thread",
    "open_thread": "thread",
    "edit": "draft",
    "delete": "draft",
    "tree_toggle": "draft",
}  # diff actions shown only on a row that has this


OPEN_ONLY = {
    "editing": {"keep_text", "drop_text"},
    "submitting": {
        "post",
        "close_submit",
        "verdict",
        "toggle_list",
        "scroll_list",
        "bar_summary",
        "discard_review",
        "keep_text",
        "drop_text",
    },
    "acting": {"pick", "act", "close_actions", "toggle_reviewer", "open_pr"},
}  # all an open editor, bar or popup allows


def open_in_browser(url):
    """macOS's open with the exact URL; elsewhere the standard library's browser launcher."""
    if shutil.which("open"):
        subprocess.Popen(["open", url], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    else:
        webbrowser.open(url)


class Rows(ScrollView, can_focus=True):
    """Logical rows that wrap to the pane width, with a cursor that rests on selectable rows, drawn through the line API so
    a redraw touches only the lines on screen. A gap of blank lines can open under one row for an inline editor."""

    tinted = False  # the pane is drawn in github's diff colors, so the cursor lifts the row's colors instead of replacing them

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("j,down", "move(1)", "down", show=False),
        Binding("k,up", "move(-1)", "up", show=False),
        Binding("ctrl+d,pagedown", "page(1)", show=False),
        Binding("ctrl+u,pageup", "page(-1)", show=False),
        Binding("ctrl+f", "page(1, True)", show=False),
        Binding("ctrl+b", "page(-1, True)", show=False),
        Binding("ctrl+e", "scroll_lines(1)", show=False),
        Binding("ctrl+y", "scroll_lines(-1)", show=False),
        Binding("home", "edge(-1)", show=False),
        Binding("G,end", "edge(1)", show=False),
        Binding("H", "view('top')", show=False),
        Binding("L", "view('bottom')", show=False),
        Binding("ctrl+o", "screen.jump(-1)", show=False),
        Binding("ctrl+i,O", "screen.jump(1)", show=False),
        Binding("escape", "screen.clear_notices", show=False),
    ]  # g, z and the digits are prefixes and counts: vimkeys.py reads them before these bindings run

    class Moved(Message):
        def __init__(self, rows, row):
            super().__init__()
            self.rows = rows
            self.row = row

    def __init__(self, painter, **kwargs):
        super().__init__(**kwargs)
        self.painter = painter
        self.rows = []
        self.cursor = 0
        self.unselected = False  # no row selected: the cursor is hidden until a move or a click picks one
        self.visual = []  # (row index, or -1 for a gap line, and its strip) per screen line; a lazy line holds a callable
        self.starts = []  # first screen line of each row
        self.width = 0
        self.gap = None  # (row index, height): blank lines under that row
        self.gap_start = None
        self.scrolled = None  # called when the view scrolls or resizes
        self.before_jump = None  # called before a motion that leaves the place ctrl+o comes back to

    def set_rows(self, rows, cursor=None, unselected=False):
        self.rows = list(rows)
        self.unselected = unselected
        self.cursor = self.nearest(
            min(max(0, self.cursor if cursor is None else cursor), max(0, len(self.rows) - 1)), 1
        )
        self.relayout()
        self.reveal()
        self.call_after_refresh(self.reveal)  # again once the new height is laid out, which bounds the scroll

    def relayout(self):
        self.width = max(10, self.scrollable_content_region.width or self.size.width or 80)
        self.visual, self.starts, self.gap_start = [], [], None
        blank = Strip.blank(self.width)
        for index, row in enumerate(self.rows):
            self.starts.append(len(self.visual))
            self.visual.extend((index, strip) for strip in self.painter(row, self.width, index))
            if self.gap and self.gap[0] == index:
                self.gap_start = len(self.visual)
                self.visual.extend((-1, blank) for _ in range(self.gap[1]))
        self.virtual_size = Size(self.width, len(self.visual))
        self.refresh()

    def on_resize(self, _event):
        self.relayout()
        self.reveal()
        if self.scrolled:
            self.scrolled()

    def watch_scroll_y(self, old_value, new_value):
        super().watch_scroll_y(old_value, new_value)
        if self.scrolled:
            self.scrolled()

    def on_focus(self, _event):
        self.refresh()

    def on_blur(self, _event):
        self.refresh()

    def render_line(self, y):
        index = self.scroll_offset.y + y
        if index >= len(self.visual):
            return Strip.blank(self.size.width)
        row, strip = self.visual[index]
        if not isinstance(strip, Strip):  # a line the painter left to draw when it is first shown
            strip = strip()
            self.visual[index] = (row, strip)
        if row == self.cursor and not self.unselected and self.rows and getattr(self.rows[row], "selectable", True):
            strip = self.app.painter.cursor_strip(strip, self.has_focus, self.tinted)
        return strip.crop_extend(0, self.size.width, None)

    def current(self):
        if (
            not self.unselected
            and 0 <= self.cursor < len(self.rows)
            and getattr(self.rows[self.cursor], "selectable", True)
        ):
            return self.rows[self.cursor]
        return None

    def nearest(self, index, step):
        """The first selectable row from index going in step's direction, then the other way; index when none is."""
        for direction in (step, -step):
            probe = index
            while 0 <= probe < len(self.rows):
                if getattr(self.rows[probe], "selectable", True):
                    return probe
                probe += direction
        return index

    def go(self, index, step=1):
        if not self.rows:
            return
        index = self.nearest(min(max(0, index), len(self.rows) - 1), step)
        changed = index != self.cursor or self.unselected
        self.cursor, self.unselected = index, False
        self.reveal()
        self.refresh()
        if changed:
            self.post_message(self.Moved(self, self.current()))

    def span(self, index):
        first = self.starts[index]
        last = (self.starts[index + 1] if index + 1 < len(self.starts) else len(self.visual)) - 1
        return first, last

    def show_lines(self, first, last):
        top, height = self.scroll_offset.y, max(1, self.size.height)
        if first < top or last - first + 1 > height:
            self.scroll_to(y=first, animate=False, immediate=True)
        elif last >= top + height:
            self.scroll_to(y=last - height + 1, animate=False, immediate=True)

    def reveal(self):
        if self.starts and self.cursor < len(self.starts):
            self.show_lines(*self.span(self.cursor))

    def reveal_gap(self):
        if self.gap_start is not None:
            self.show_lines(max(0, self.gap_start - 2), self.gap_start + self.gap[1] - 1)

    def action_move(self, step):
        if self.unselected:  # the first move selects the row where the hidden cursor is
            return self.go(self.cursor, step)
        probe = self.cursor + step
        while 0 <= probe < len(self.rows) and not getattr(self.rows[probe], "selectable", True):
            probe += step
        if 0 <= probe < len(self.rows):
            self.go(probe, step)

    def action_page(self, step, whole=False):
        """Half a page (ctrl+d, ctrl+u), or a whole one (ctrl+f, ctrl+b)."""
        if not self.starts:
            return
        lines = max(1, self.size.height if whole else self.size.height // 2)
        target = min(max(0, self.starts[self.cursor] + step * lines), len(self.visual) - 1)
        row = self.visual[target][0]
        self.go(row if row >= 0 else self.cursor + step, step)

    def action_scroll_lines(self, step):
        """ctrl+e and ctrl+y: scroll the view a line down or up. The cursor stays on its row while any of it is in view;
        past that it moves to the nearest row that is wholly in view, as vim keeps the cursor on screen."""
        if not self.starts:
            return
        height = max(1, self.size.height)
        top = min(max(0, self.scroll_offset.y + step), max(0, len(self.visual) - height))
        self.scroll_to(y=top, animate=False, immediate=True)
        first, last = self.span(self.cursor)
        if last < top:  # off the top: the first row that starts in the view
            self.go(next((i for i, start in enumerate(self.starts) if start >= top), len(self.rows) - 1), 1)
        elif first >= top + height:  # off the bottom: the last row that ends in the view
            self.go(max((i for i in range(len(self.rows)) if self.span(i)[1] < top + height), default=0), -1)

    def jumped(self):
        if self.before_jump:
            self.before_jump()

    def action_edge(self, step):
        self.jumped()
        self.go(len(self.rows) - 1 if step > 0 else 0, -step)

    def selectable_rows(self):
        return [index for index, row in enumerate(self.rows) if getattr(row, "selectable", True)]

    def go_nth(self, number):
        """The number-th selectable row, counting from 1 (5G, 5gg); the last one when there are fewer."""
        rows = self.selectable_rows()
        if rows:
            self.jumped()
            self.go(rows[min(max(1, number), len(rows)) - 1])

    def row_at_line(self, line):
        """The row drawn on a screen line of the view, the next one down when that line is a gap."""
        line = min(max(0, self.scroll_offset.y + line), len(self.visual) - 1) if self.visual else 0
        while line < len(self.visual) and self.visual[line][0] < 0:
            line += 1
        return self.visual[line][0] if line < len(self.visual) else max(0, len(self.rows) - 1)

    def action_view(self, where, offset=0):
        """H and L: the row at the top or the bottom of the view, offset rows in (3H is the third row)."""
        if not self.visual:
            return
        self.jumped()
        height = max(1, self.size.height)
        if where == "top":
            row = self.row_at_line(0)
            if self.starts[row] < self.scroll_offset.y and row + 1 < len(self.rows):  # its first line is above the view
                row += 1
            self.go(min(row + offset, len(self.rows) - 1) if offset else row, 1)
        else:
            row = self.row_at_line(min(height, len(self.visual) - self.scroll_offset.y) - 1)
            self.go(max(row - offset, 0) if offset else row, -1)

    def place(self, where):
        """zt, zz, zb: scroll so the cursor row is at the top, the middle or the bottom of the view; the cursor stays."""
        if not self.starts or self.cursor >= len(self.starts):
            return
        first, last = self.span(self.cursor)
        height = max(1, self.size.height)
        if where == "top":
            top = first
        elif where == "bottom":
            top = last - height + 1
        else:
            top = first - (height - (last - first + 1)) // 2
        self.scroll_to(y=max(0, top), animate=False, immediate=True)

    def on_click(self, event: events.Click):
        index = self.scroll_offset.y + event.y
        if 0 <= index < len(self.visual) and self.visual[index][0] >= 0:
            self.go(self.visual[index][0])


class ListRows(Rows):
    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("1", "screen.tab('mine')", show=False),
        Binding("2", "screen.tab('pending')", show=False),
        Binding("3", "screen.tab('review')", show=False),
        Binding("4", "screen.tab('all')", show=False),
        Binding("m", "screen.only_mine", show=False),
        Binding("enter", "screen.open_diff", "open"),
        Binding("v", "screen.submit('COMMENT')", "review"),
        Binding("C", "screen.converse", "comment"),
        Binding("M", "screen.actions", "actions"),
        Binding("o", "screen.open_pr", show=False),
        Binding("r", "screen.refresh", show=False),
        Binding("s", "screen.scope", "scope"),
        Binding("slash", "screen.filter", "find", key_display="/"),
        Binding("i", "screen.details", show=False),
        Binding("U", "screen.bulk_update", show=False),
        Binding("colon", "screen.command", show=False),
        Binding("a", "screen.authors", "authors", show=False),
        Binding("g", "screen.toggle_group", "group", show=False),
        Binding("h", "screen.group_fold(True)", show=False),
        Binding("l", "screen.group_fold(False)", show=False),
        Binding("exclamation_mark", "screen.attention('failing')", show=False, key_display="!"),
        Binding("b", "screen.attention('behind')", show=False),
        Binding("d", "screen.attention('draft')", show=False),
        Binding("n", "screen.match(1)", show=False),
        Binding("N", "screen.match(-1)", show=False),
        Binding("left_curly_bracket", "screen.group_step(-1)", show=False),
        Binding("right_curly_bracket", "screen.group_step(1)", show=False),
    ]


class DiffRows(Rows):
    """The diff pane. Main.check_action lets each row action run, and the statusline show it, only where it applies."""

    tinted = True

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("c", "screen.comment", "comment"),
        Binding("R", "screen.reply", "reply"),
        Binding("x", "screen.resolve", "res"),
        Binding("e", "screen.tree_toggle", "tree"),
        Binding("o", "screen.open_check", show=False),  # on a check row; else o below
        Binding("d", "screen.delete", "del"),
        Binding("enter", "screen.fold", "fold"),
        Binding("enter", "screen.open_thread", "in files"),  # on a thread's entry in the Conversation tab
        Binding("enter", "screen.open_check", show=False),
        Binding("enter", "screen.expand", show=False),  # on a row of folded unchanged lines
        Binding("vertical_line", "screen.split", show=False),
        Binding("a", "screen.submit('APPROVE')", show=False),
        Binding("r", "screen.submit('REQUEST_CHANGES')", show=False),
        Binding("v", "screen.submit('COMMENT')", "review"),
        Binding("s", "screen.submit('COMMENT')", show=False),
        Binding("C", "screen.converse", show=False),
        Binding("m", "screen.summary", show=False),
        Binding("f", "screen.tree_focus", "focus"),
        Binding("ctrl+h", "screen.pane_left", show=False),
        Binding("M", "screen.actions", "actions"),
        Binding("V", "screen.viewed", "viewed", show=False),
        Binding("F", "screen.tree_full", show=False),
        Binding("less_than_sign", "screen.tree_resize(-4)", show=False),
        Binding("greater_than_sign", "screen.tree_resize(4)", show=False),
        Binding("1", "screen.ptab('conversation')", show=False),
        Binding("2", "screen.ptab('commits')", show=False),
        Binding("3", "screen.ptab('checks')", show=False),
        Binding("4", "screen.ptab('files')", show=False),
        Binding("n", "screen.thread(1)", show=False),
        Binding("p", "screen.thread(-1)", show=False),
        Binding("right_curly_bracket", "screen.file(1)", show=False),
        Binding("left_curly_bracket", "screen.file(-1)", show=False),
        Binding("u", "screen.unresolved", show=False),
        Binding("o", "screen.open_here", show=False),
        Binding("colon", "screen.command", show=False),
        Binding("slash", "screen.search", show=False),
        Binding("N", "screen.match(-1)", show=False),
    ]


class InlineText(TextArea):
    """A text editor that sits inside the diff pane. ctrl+s keeps the text as a draft, esc drops the edit."""

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("ctrl+s,ctrl+enter", "screen.keep_text", "keep", priority=True),
        Binding("escape", "screen.drop_text", "cancel", priority=True),
    ]


class VimTree(Tree[int]):
    """A tree that moves like the rows do: half and whole pages, the top and the bottom, the top and bottom of the view."""

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("ctrl+d,pagedown", "tree_page(1)", show=False),
        Binding("ctrl+u,pageup", "tree_page(-1)", show=False),
        Binding("ctrl+f", "tree_page(1, True)", show=False),
        Binding("ctrl+b", "tree_page(-1, True)", show=False),
        Binding("ctrl+e", "tree_scroll(1)", show=False),
        Binding("ctrl+y", "tree_scroll(-1)", show=False),
        Binding("home", "tree_edge(-1)", show=False),
        Binding("G,end", "tree_edge(1)", show=False),
        Binding("H", "tree_view('top')", show=False),
        Binding("L", "tree_view('bottom')", show=False),
    ]

    def go_line(self, line):
        if self.last_line >= 0:
            self.move_cursor_to_line(min(max(0, line), self.last_line))

    def action_tree_page(self, step, whole=False):
        height = max(1, self.scrollable_content_region.height)
        self.go_line(max(0, self.cursor_line) + step * max(1, height if whole else height // 2))

    def action_tree_scroll(self, step):
        """ctrl+e and ctrl+y: scroll the view a line; the cursor moves only when it would leave the view."""
        height = max(1, self.scrollable_content_region.height)
        top = min(max(0, self.scroll_offset.y + step), max(0, self.last_line + 1 - height))
        self.scroll_to(y=top, animate=False, immediate=True)
        self.go_line(min(max(self.cursor_line, top), top + height - 1))

    def action_tree_edge(self, step):
        self.go_line(self.last_line if step > 0 else 0)

    action_edge = action_tree_edge

    def action_tree_view(self, where, offset=0):
        top = self.scroll_offset.y
        bottom = min(top + max(1, self.scrollable_content_region.height) - 1, self.last_line)
        self.go_line(top + offset if where == "top" else bottom - offset)

    def place(self, where):
        """zt, zz, zb: scroll so the cursor line is at the top, the middle or the bottom of the view."""
        height = max(1, self.scrollable_content_region.height)
        line = max(0, self.cursor_line)
        top = line if where == "top" else line - height + 1 if where == "bottom" else line - height // 2
        self.scroll_to(y=max(0, top), animate=False, immediate=True)

    def selectable_rows(self):
        return list(range(self.last_line + 1))

    def go_nth(self, number):
        self.go_line(number - 1)


class FileTree(VimTree):
    """The Files tab's file tree, github.com style: folders open and closed with + and -, guides, merged folder chains."""

    ICON_NODE = "+ "
    ICON_NODE_EXPANDED = "- "
    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("j", "cursor_down", "move", key_display="j/k"),
        Binding("k", "cursor_up", show=False),
        Binding("l", "select_cursor", "open"),
        Binding("h", "screen.tree_up", "fold"),
        Binding("slash", "screen.tree_filter", "filter", key_display="/"),
        Binding("e", "screen.files", "hide"),
        Binding("f", "screen.tree_focus", "diff"),
        Binding("ctrl+l", "screen.pane_right", show=False),
        Binding("V", "screen.viewed", show=False),
        Binding("F", "screen.tree_full", show=False),
        Binding("less_than_sign", "screen.tree_resize(-4)", show=False),
        Binding("greater_than_sign", "screen.tree_resize(4)", show=False),
        Binding("escape", "screen.close_files", show=False, priority=True),
    ]


class SubmitBar(Vertical, can_focus=True):
    """What one submit would post, in place of the statusline. Only y here posts."""

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("y", "screen.post", "post"),
        Binding("n,escape,q", "screen.close_submit", "back"),
        Binding("c", "screen.verdict('COMMENT')", "comment"),
        Binding("a", "screen.verdict('APPROVE')", "approve"),
        Binding("r", "screen.verdict('REQUEST_CHANGES')", "changes"),
        Binding("l", "screen.toggle_list", "list"),
        Binding("m", "screen.bar_summary", "summary"),
        Binding("D", "screen.discard_review", "discard"),
        Binding("j,down", "screen.scroll_list(1)", show=False),
        Binding("k,up", "screen.scroll_list(-1)", show=False),
    ]


class ListTabs(Tabs, can_focus=False):
    """Tabs that never take the keys: the pane under them keeps focus, number keys switch, the mouse can click."""


class LoadMore:
    """The row at the end of a wider scope that loads its next page."""

    selectable = True
    style = "dim"

    def __init__(self, size, shown, total):
        self.text = f"load {size} more ({shown} of {total} shown)"


class Info:
    """A list row that is not a pull request: loading, empty, an error."""

    selectable = False

    def __init__(self, text, style="dim"):
        self.text = text
        self.style = style


def failure(error):
    """One line for an error raised in a worker: Morann's own errors as they are, anything else with its type."""
    if isinstance(
        error,
        (
            core.ForgeError,
            core.NotConfirmed,
            core.HeadMoved,
            core.PendingGone,
            core.SubmitError,
            core.DraftError,
            core.UsageError,
        ),
    ):
        return str(error)
    return f"unexpected error ({type(error).__name__}: {error})"
