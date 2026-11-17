# SPDX-FileCopyrightText: 2026 Cristiano Carvalho
# SPDX-License-Identifier: Apache-2.0
"""Both panels agree: the details panel and the lower pane show the pull request selected in the list, or nothing. Every
change to the list's rows or cursor ends in sync_open, the one place that decides what the lower pane shows. Mixed into
Main."""

from __future__ import annotations

from morann import core
from morann.widgets import DEBOUNCE, ListRows

AUTHOR_REASONS = {
    "me": ("none of these are yours", "a cycles the authors"),
    "others": ("none by others", "a cycles the authors"),
    "bots": ("none by bots", "a cycles the authors"),
}


class SelectMixin:
    def chosen(self):
        """The list's selection: the pull request under the cursor; on a repository header or the load-more row, the last
        pull request the cursor was on while the list still shows it; else none."""
        widget = self.query_one("#list", ListRows)
        row = widget.current()
        if isinstance(row, core.PrRow):
            return row
        if row is None or self.last_row is None:
            return None
        return next(
            (shown for shown in widget.rows if isinstance(shown, core.PrRow) and shown.key == self.last_row.key), None
        )

    def pinned(self):
        """The pull request the lower pane keeps while the list shows no selection: one opened by link (o, :) that the list
        does not show, or one kept open for its unsent drafts when the view emptied."""
        if self.linked is not None and self.wanted == self.linked.key:
            return self.linked.key
        return self.held if self.held is not None and self.wanted == self.held else None

    def sync_open(self, wait=DEBOUNCE):
        """Make the lower pane follow the list: open the chosen pull request, or clear the pane when nothing is chosen.
        Two exceptions keep a pull request with no selection in the list: one opened by link, until another row is chosen,
        and one with unsent drafts, which stay stored with it either way."""
        row = self.chosen()
        if row is not None:
            self.held = None
            if self.linked is not None and self.linked.key != row.key:
                self.linked = None
            if isinstance(self.query_one("#list", ListRows).current(), core.PrRow):
                self.last_row = row
            self.follow(row, wait)
            return
        if self.linked is not None and self.wanted == self.linked.key:
            self.follow(self.linked, wait)
            return
        if self.lists is None:  # still loading, or failed: the remembered selection waits for the list
            return
        if self.pr is not None and (self.editing or self.drafts is not None and self.drafts.count()):
            self.held = self.pr.key
            self.wanted = self.pr.key
            return
        self.clear_open()

    def follow(self, row, wait):
        """Open `row` unless it is open and fresh, on its way, or its read just failed."""
        if (
            row.key in (self.loading_key, self.failed)
            or self.pr is not None
            and self.pr.key == row.key
            and not self.pr.stale
        ):
            self.wanted = row.key
            return
        self.selection_changed(row, wait)

    def clear_open(self):
        """Nothing chosen: no pull request, drafts, header buttons, tabs' contents, file tree or diff stay below."""
        if self.timer is not None:
            self.timer.stop()
            self.timer = None
        self.close_editor()
        self.pr = self.drafts = self.loading_key = self.last_row = self.failed = self.held = None
        if not any(isinstance(row, core.PrRow) for row in self.query_one("#list", ListRows).rows):
            self.wanted = None  # when rows return, the first one is selected
            self.remember()
        self.files_tree().clear()
        self.show_pr(cursor=0)
        self.layout_tree()

    def hold_note(self):
        """The top bar's and the header's word on a pull request kept below while the list shows no selection."""
        if self.pr is None or self.chosen() is not None:
            return ""
        if self.held == self.pr.key:
            count = self.drafts.count() if self.drafts is not None else 0
            return (
                f"kept open: {self.pr.key} has {count} unsent drafts" if count else f"kept open: editing {self.pr.key}"
            )
        if self.linked is not None and self.linked.key == self.pr.key:
            return "opened by link"
        return ""

    def empty_note(self):
        """The lower pane's empty state when the list shows no pull request: why, and the key that brings some back."""
        if self.lists is None:
            return ""
        widget = self.query_one("#list", ListRows)
        if any(isinstance(row, core.PrRow) for row in widget.rows):
            return ""
        reason, key = self.empty_reason()
        return f"No pull requests here: {reason}" + (f"  {key}" if key else "")

    def empty_reason(self):
        if self.tab == "all":
            base = (self.wide["rows"] if self.wide else []) + (self.found["rows"] if self.searched() else [])
        elif self.tab == "pending":
            base = [item.row for item in self.pending_items()]
        else:
            base = getattr(self.lists, self.tab, []) if self.lists else []
        where = self.where()
        if not base:
            if self.tab == "review":
                return f"nothing waits on your review{where}", ""
            if self.tab == "pending":
                return "no review in progress", "c on a line, or v, starts one"
            if self.tab == "mine":
                return f"you have no open pull requests{where}", ""
            return f"no open pull requests{where}", ""
        if self.visible_rows():
            return "every repository here is folded", "l unfolds the one under the cursor"
        if self.filter:
            return f'no match for the filter "{self.filter}"', "/ then esc clears it"
        if self.attention_filter:
            key = "!" if self.attention_filter == "failing" else "b"
            return f"no {self.attention_filter} pull requests", f"{key} shows all"
        if self.only_mine:
            return "none of these are yours", "m shows everyone's"
        return AUTHOR_REASONS.get(self.authors, ("no match", "a cycles the authors"))
