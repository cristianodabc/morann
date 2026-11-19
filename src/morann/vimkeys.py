# SPDX-FileCopyrightText: 2026 Cristiano Carvalho
# SPDX-License-Identifier: Apache-2.0
"""The vim-style keys that need memory: counts (5j), the g, z and ctrl+w prefixes (gg, gt, gT, zt, zz, z., zb, ctrl+w j),
/ search in the lower pane with n and N, and the jump list ctrl+o and ctrl+i walk. Mixed into Main; the plain motions
(G, H, L, ctrl+d, ctrl+u, ctrl+f, ctrl+b, ctrl+e, ctrl+y, and { } in the list) are bindings of the row widgets.

Where a vim key is already a Morann key, the Morann key stays: g in the list groups by repository, z maximizes the lower
pane, M opens the actions, n in the lower pane is the next thread unless a search is active, and m is the summary or the
my-pull-requests filter, so there are no marks. Digits 1-4 switch tabs, so a count starts with 5-9 (4-9 in the list)."""

from __future__ import annotations

import time

from textual.widgets import Input

from morann import core
from morann.main_motions import MOTIONS
from morann.widgets import DiffRows, ListRows, Rows, VimTree

LIST_TABS = tuple(core.LIST_TABS)

CHORD_WINDOW = 0.6  # seconds a g or a z waits for its second key
COUNT_DIGITS = 3  # a count of more than 999 is never what was meant
JUMP_LIMIT = 100  # places a jump list keeps
PLACES = {"t": "top", "z": "middle", "full_stop": "middle", "b": "bottom"}  # zt zz z. zb
WINDOWS = {  # ctrl+w and a key: the list is the top window and the pull request pane the bottom one
    "j": "diff",
    "down": "diff",
    "b": "diff",
    "k": "list",
    "up": "list",
    "t": "list",
    "w": "other",
    "ctrl+w": "other",
    "p": "other",  # the previous window: with two, the other one
    "h": "tree",
    "ctrl+h": "tree",
    "l": "code",
    "ctrl+l": "code",
}
BRACKETS = {"right_square_bracket": 1, "left_square_bracket": -1}  # ] and [ then a letter: main_motions.MOTIONS
SECOND = {  # what may follow each prefix
    "g": ("g", "t", "T", "x", "y"),
    "z": tuple(PLACES),
    "w": tuple(WINDOWS),
    **dict.fromkeys(BRACKETS, tuple(MOTIONS)),
}
REPEATED = {
    "j",
    "k",
    "down",
    "up",
    "ctrl+d",
    "ctrl+u",
    "ctrl+f",
    "ctrl+b",
    "ctrl+e",
    "ctrl+y",
    "pagedown",
    "pageup",
    "n",
    "N",
    "p",
    "left_curly_bracket",
    "right_curly_bracket",
}  # 5j runs j five times


class Jumps:
    """The places a pane came from, oldest first. ctrl+o goes back along them, ctrl+i forward again; a new jump from the
    middle starts a new end, as in vim."""

    def __init__(self):
        self.items = []
        self.at = 0  # len(items) while at the newest place, which is not in the list yet

    def clear(self):
        self.items, self.at = [], 0

    def record(self, place):
        self.items = [item for item in self.items if item != place]
        self.items.append(place)
        del self.items[:-JUMP_LIMIT]
        self.at = len(self.items)

    def back(self, here):
        """The place before this one, or None at the oldest. `here` is kept, so forward can come back to it."""
        if self.at >= len(self.items):
            self.record(here)
            self.at = len(self.items) - 1
        if self.at <= 0:
            return None
        self.at -= 1
        return self.items[self.at]

    def forward(self):
        if self.at + 1 >= len(self.items):
            return None
        self.at += 1
        return self.items[self.at]


def row_text(row):
    """What a search reads of a row: a diff line's text, a card's body and its author."""
    return "\n".join(
        part for part in (getattr(row, "text", ""), getattr(row, "body", ""), getattr(row, "author", "")) if part
    )


def search_matches(rows, query):
    """Indexes of the selectable rows that contain query. A query in lower case ignores case, one with a capital does not."""
    if not query:
        return []
    fold = query == query.lower()
    return [
        index
        for index, row in enumerate(rows)
        if getattr(row, "selectable", True) and query in (row_text(row).lower() if fold else row_text(row))
    ]


def tab_keys(widget):
    """The digits the focused pane uses for tabs: a count cannot start with one of them."""
    return "1234" if isinstance(widget, (ListRows, DiffRows)) else ""


class VimMixin:
    def init_vim(self):
        self.count = ""  # the digits typed so far
        self.prefix = None  # {"kind", "at", "count", "undo"} after a g or a z
        self.keyclock = time.monotonic
        self.jumps = Jumps()  # one for the whole app: a place names its pane and pull request
        self.jumping = False
        self.search = None  # the text / looks for in the lower pane
        self.search_from = 0  # the cursor row when / was pressed, where esc goes back to
        self.pending_place = None  # a jump back to a pull request that is still loading: where to land once it is in

    # Counts and prefixes, read before the focused pane's bindings run.

    async def on_key(self, event):
        if event.key == "escape" and self.query_one("#search", Input).has_focus:
            self.search_done(keep=False)
            event.stop()
            event.prevent_default()
            return
        if await self.vim_key(self.app.focused, event.key):
            event.stop()
            event.prevent_default()

    async def vim_key(self, focused, key):
        """True when the key was a count, a prefix or the end of one, and nothing else should act on it."""
        if self.editing or self.submitting or self.acting or not isinstance(focused, (Rows, VimTree)):
            self.count, self.prefix = "", None
            return False
        count, pending, self.count, self.prefix = self.count, self.prefix, "", None
        if pending and self.keyclock() - pending["at"] > CHORD_WINDOW:
            pending = None
        if pending and key in SECOND[pending["kind"]]:
            self.finish_prefix(focused, pending, key)
            return True
        if pending and pending["kind"] == "w":  # ctrl+w and a key it does not know: nothing, as in vim
            return True
        if count:
            self.show_bars()
        if key == "escape" and count:
            return True
        if key.isdigit() and (count or key != "0" and key not in tab_keys(focused)):
            self.count = (count + key)[:COUNT_DIGITS]
            self.show_bars()
            return True
        number = int(count) if count else 0
        if key == "g":
            return self.start_g(focused, number)
        if key == "z":
            self.start_z()
            return False
        if key == "ctrl+w":
            self.arm("w")
            return True
        if key in BRACKETS and isinstance(focused, DiffRows):
            return self.start_bracket(focused, key, number)
        return await self.counted(focused, key, number) if number else False

    def arm(self, kind, count=0, undo=None, size=None):
        self.prefix = {"kind": kind, "at": self.keyclock(), "count": count, "undo": undo, "size": size}

    def start_g(self, focused, number):
        """g: in the list it still groups by repository, taking it back if a second key follows; elsewhere, and after a
        count, it only waits for the second key (gg, gt, gT, gx, gy)."""
        if number or not isinstance(focused, ListRows):
            self.arm("g", number)
            return True
        self.arm("g", 0, self.action_toggle_group)
        return False

    def start_bracket(self, focused, key, number):
        """] and [ still step to the next and previous tab at once; a quick c h f t u m or d after them puts the tab
        back and makes the motion instead (]c, [u), as z and a quick t z b do."""
        before = (self.mode, focused.cursor)

        def restore():
            if self.mode != before[0]:
                self.set_mode(before[0], cursor=before[1])

        self.arm(key, number, restore)
        if self.pr is not None:
            self.action_ptab_step(BRACKETS[key])
        return True

    def start_z(self):
        """z still maximizes the lower pane; a t, z or b right after puts it back and scrolls instead."""
        before, widget = (self.max_diff, self.focus_pane), self.app.focused
        size = widget.size

        def restore():
            if (self.max_diff, self.focus_pane) != before:
                self.max_diff, self.focus_pane = before
                self.layout_panes()
                (widget if widget is not None and widget.is_attached else self.query_one(f"#{self.focus_pane}")).focus()
                self.remember()
                self.show_bars()

        self.arm("z", 0, restore, size)

    def when_laid_out(self, widget, size, then, tries=25):
        """Run then() once the widget is the size it was before the layout changed, which takes a few frames."""
        if widget.size == size or tries == 0:
            then()
        else:
            self.set_timer(0.02, lambda: self.when_laid_out(widget, size, then, tries - 1))

    def finish_prefix(self, focused, pending, key):
        if pending["undo"]:
            pending["undo"]()
        if pending["kind"] == "z":
            self.call_after_refresh(self.when_laid_out, focused, pending["size"], lambda: focused.place(PLACES[key]))
            return
        if pending["kind"] == "w":
            self.window(WINDOWS[key])
            return
        if pending["kind"] in BRACKETS:
            self.action_motion(key, BRACKETS[pending["kind"]], pending["count"] or 1)
            return
        if key in ("t", "T"):  # gt gT: the focused pane's next or previous tab
            self.step_tab(focused, 1 if key == "t" else -1)
            return
        if key in ("x", "y"):  # gx gy: open a link of the row under the cursor, copy one's address
            (self.action_open_link if key == "x" else self.action_copy_link)()
            return
        if pending["count"]:
            focused.go_nth(pending["count"])
        else:
            focused.action_edge(-1)

    def window(self, where):
        """ctrl+w and j k w h l: the pull request pane, the list, the other one, the file tree, the diff."""
        if where == "tree":
            return self.action_pane_left()
        if where == "code":
            return self.action_pane_right()
        target = ("list" if self.focus_pane == "diff" else "diff") if where == "other" else where
        if target != self.focus_pane or self.files_tree().has_focus:
            if target == self.focus_pane:
                return self.action_close_files()
            return self.action_switch()
        return None

    def step_tab(self, focused, step):
        if isinstance(focused, ListRows):
            self.action_tab(LIST_TABS[(LIST_TABS.index(self.tab) + step) % len(LIST_TABS)])
        else:
            self.action_ptab_step(step)

    async def counted(self, focused, key, number):
        """A count and then a motion: 5j, 3ctrl+d, 4n, 7G, 3H. Anything else ends the count and acts once."""
        tree = isinstance(focused, VimTree)
        if key in REPEATED:
            for _ in range(number):
                await self.app._check_bindings(key)
            return True
        if key == "G":
            focused.go_nth(number)
            return True
        if key in ("H", "L"):
            (focused.action_tree_view if tree else focused.action_view)("top" if key == "H" else "bottom", number - 1)
            return True
        return False

    def action_clear_notices(self):
        """esc in a pane: forget a count and a search, and dismiss the pop-ups."""
        self.count, self.prefix = "", None
        if self.search:
            self.search = None
        self.show_bars()
        self.app.clear_notifications()

    # Search in the lower pane. In the list / is the filter, and n and N step through the rows it kept.

    def action_search(self):
        if not self.need_pr():
            return
        box = self.query_one("#search", Input)
        self.search_from = self.query_one("#diff", DiffRows).cursor
        box.value = ""
        box.display = True
        box.focus()

    def search_changed(self, value):
        """Each letter typed moves to the first match from where the search began."""
        diff = self.query_one("#diff", DiffRows)
        self.search = value or None
        hits = search_matches(diff.rows, value)
        diff.go(next((index for index in hits if index >= self.search_from), hits[0]) if hits else self.search_from)
        self.show_bars()

    def search_done(self, keep):
        """enter keeps the search and the place it moved to; esc goes back to where it began and forgets it."""
        box = self.query_one("#search", Input)
        box.display = False
        diff = self.query_one("#diff", DiffRows)
        if keep and self.search and search_matches(diff.rows, self.search):
            self.jumps.record(self.place("diff", self.search_from))
        else:
            diff.go(self.search_from)
            if self.search:
                self.notify(f"no match for {self.search}" if keep else "search canceled", timeout=3)
            self.search = None
        diff.focus()
        self.show_bars()

    def search_note(self):
        """The header's note on the search: /text, which match the cursor is at, and how many there are."""
        if not self.search:
            return ""
        hits = search_matches(self.query_one("#diff", DiffRows).rows, self.search)
        cursor = self.query_one("#diff", DiffRows).cursor
        return f"  /{self.search} {sum(1 for hit in hits if hit <= cursor)}/{len(hits)}"

    def action_match(self, step):
        """n and N: the next and previous search match in the lower pane, or in the list the next and previous pull request
        that the filter kept. In the lower pane without a search, n is still the next thread."""
        listing = isinstance(self.app.focused, ListRows)
        widget = self.query_one("#list" if listing else "#diff", Rows)
        if listing:
            if not (self.filter or self.attention_filter):
                self.notify("no filter: / filters the list, then n and N step through what it kept", timeout=4)
                return
            hits = [index for index, row in enumerate(widget.rows) if isinstance(row, core.PrRow)]
        elif not self.search:
            self.notify("no search: / looks for text in the pane, then n and N step through the matches", timeout=4)
            return
        else:
            hits = search_matches(widget.rows, self.search)
        if not hits:
            self.notify(
                f"no match for {self.search}" if self.search and not listing else "nothing to step through", timeout=3
            )
            return
        ahead = [index for index in hits if (index > widget.cursor if step > 0 else index < widget.cursor)]
        if not ahead:
            self.notify("search wrapped" if not listing else "wrapped", timeout=2)
        widget.jumped()
        widget.go((ahead[0] if step > 0 else ahead[-1]) if ahead else (hits[0] if step > 0 else hits[-1]))
        self.show_bars()

    def vim_new_pr(self):
        """Another pull request is open: its rows are not where the old search pointed."""
        self.search = None
        self.query_one("#search").display = False

    # The jump list, one for the whole app: ctrl+o goes back, ctrl+i (or O, since most terminals send tab for ctrl+i)
    # forward. A place names its pane, so going back can change the pane, the pull request, its tab and its file.

    def place(self, pane, cursor=None):
        """Where a pane is: the list's row, or the lower pane's pull request, tab, file and row."""
        if pane == "list":
            rows = self.query_one("#list", ListRows)
            key = getattr(rows.rows[rows.cursor], "key", None) if rows.rows and rows.cursor < len(rows.rows) else None
            return ("list", key) if key else None
        if self.pr is None:
            return None
        diff = self.query_one("#diff", DiffRows)
        return ("diff", self.pr.key, self.mode, self.file_index, diff.cursor if cursor is None else cursor)

    def record_jump(self, pane):
        place = None if self.jumping else self.place(pane)
        if place:
            self.jumps.record(place)

    def action_jump(self, step):
        place = self.place("list" if self.focus_pane == "list" else "diff")
        target = self.jumps.back(place) if step < 0 and place else self.jumps.forward() if step > 0 else None
        if target is None or not self.goto_place(target):
            self.notify("no older position" if step < 0 else "no newer position", timeout=2)

    def focus_on(self, pane):
        if self.focus_pane != pane or self.app.focused is not self.query_one(f"#{pane}"):
            self.focus_pane = pane
            if pane == "list":
                self.max_diff = False
            self.layout_panes()
            self.query_one(f"#{pane}").focus()

    def goto_place(self, place):
        """Go to a recorded place: its pane, its row, and for the lower pane its pull request (opened again if another
        one is open; the rest lands once it is read), tab and file."""
        self.jumping = True
        try:
            if place[0] == "list":
                rows = self.query_one("#list", ListRows)
                index = next((i for i, row in enumerate(rows.rows) if getattr(row, "key", None) == place[1]), None)
                if index is None:
                    return False
                self.focus_on("list")
                rows.go(index)
                return True
            key = place[1]
            self.focus_on("diff")
            if self.pr is None or self.pr.key != key:
                self.pending_place = place
                repo, _, number = key.rpartition("#")
                self.open_ref(repo, int(number))
                return True
            self.restore(place)
            return True
        finally:
            self.jumping = False

    def restore(self, place):
        _, _key, mode, file_index, row = place
        if (mode, file_index if mode == "files" else self.file_index) != (self.mode, self.file_index):
            if mode == "files":
                self.open_file(min(file_index, max(0, len(self.pr.files) - 1)))
            else:
                self.set_mode(mode)
        diff = self.query_one("#diff", DiffRows)
        diff.go(min(row, max(0, len(diff.rows) - 1)))

    def land_pending(self):
        """A pull request came in: if a jump back was waiting for it, put the tab, file and row where they were."""
        place = self.pending_place
        if place is None or self.pr is None or self.pr.key != place[1]:
            return
        if place[2] == "files" and self.pr.files_loading:
            return
        self.pending_place = None
        self.jumping = True
        try:
            self.restore(place)
        finally:
            self.jumping = False
