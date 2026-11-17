# SPDX-FileCopyrightText: 2026 Cristiano Carvalho
# SPDX-License-Identifier: Apache-2.0
"""What in the lists needs you, on screen: each row's attention flag, the To Review tab's waits, the top bar's counts with
their filters (! failing, b behind, d draft), and remembering what was seen when a pull request was opened. Mixed into Main."""

from __future__ import annotations

from datetime import UTC, datetime

from rich.style import Style
from rich.text import Text

from morann import attention


class AttentionMixin:
    def all_rows(self):
        """Every list row on hand: Mine, To Review and the wider scope's rows."""
        rows = [*(self.lists.mine if self.lists else []), *(self.lists.review if self.lists else [])]
        return rows + (self.wide["rows"] if self.wide else []) + (self.found["rows"] if self.found else [])

    def attention_flags(self, rows):
        seen = self.state.get("seen") or {}
        flags = {row.key: attention.flag(row, seen.get(row.key)) for row in rows}
        return {key: name for key, name in flags.items() if name}

    def attention_waits(self, rows):
        """On the To Review tab, how long each request for your review has waited; on Pending, how long since the last
        draft; elsewhere nothing."""
        if self.tab == "pending":
            now = self.now or datetime.now(UTC)
            return {item.row.key: attention.since(item.last, now) for item in self.pending}
        if self.tab != "review":
            return {}
        return {row.key: attention.wait(row, self.login, self.now or datetime.now(UTC)) for row in rows}

    def attention_order(self, members):
        if self.tab == "pending":  # the review waiting longest first, as pending_rows put them
            return list(members)
        return attention.order(members, self.flags, login=self.login, oldest_wait=self.tab == "review")

    def attention_filtered(self, rows):
        return [row for row in rows if attention.matches(row, self.attention_filter)]

    def action_attention(self, name):
        """! b d, or a click on the count in the top bar: only failing, behind or draft pull requests; the same again clears."""
        self.attention_filter = "" if self.attention_filter == name else name
        self.state.save(attention=self.attention_filter)
        self.show_list()
        self.notify(
            f"{name} only: {attention.KEYS[name]} again shows all" if self.attention_filter else "all pull requests",
            timeout=3,
        )

    def mark_seen(self, key):
        """Opening a pull request clears its new-activity flag until something new lands."""
        row = next((row for row in self.all_rows() if row.key == key), None)
        if row is None:
            return
        self.state.save(seen=attention.remember(self.state.get("seen") or {}, row))
        if self.flags.get(key) == "new":
            del self.flags[key]
            self.query_one("#list").relayout()

    def attention_summary(self, narrow):
        """The top bar's counts, each filter count clickable, the active filter underlined."""
        page = self.all_page()  # on the All tab, a search's result
        wide = (page["rows"], page["total"]) if self.scope_kind != "mine" and page else None
        parts = attention.summary(self.lists.mine if self.lists else (), self.lists.review if self.lists else (), wide)
        out = Text(" ")
        for index, part in enumerate(parts):
            name = part[2]
            if index:
                out.append(" " if narrow else "  ")
            ink = self.app.painter.ink
            style = ink("muted")
            text = attention.summary_text([part], narrow)
            if name:
                token = "bad" if name == "failing" else "warn" if name == "behind" else "info"
                style = ink(token, bold=True, underline=self.attention_filter == name) + Style(
                    meta={"@click": f"screen.attention('{name}')"}
                )
                if not narrow and self.focus_pane == "list":  # the key, where the list has the keys and there is room
                    text += f" ({attention.KEYS[name]})"
            out.append(text, style)
        if self.attention_filter and not any(name == self.attention_filter for _c, _w, name in parts):
            out.append(
                f"  {self.attention_filter} only",
                Style(underline=True, meta={"@click": f"screen.attention('{self.attention_filter}')"}),
            )
        return out
