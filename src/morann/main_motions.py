# SPDX-FileCopyrightText: 2026 Cristiano Carvalho
# SPDX-License-Identifier: Apache-2.0
"""Motions through a pull request, vim-unimpaired style: ] and [ then a letter go to the next and previous change (c),
hunk (h), file (f), thread (t), unresolved thread (u), comment (m) or draft (d), crossing into the next file where the
Files tab has no more of them. A count repeats it (3]c). Mixed into Main."""

from __future__ import annotations

from morann.widgets import DiffRows

MOTIONS = {  # the letter after ] or [, what it reaches, and whether it crosses files
    "c": ("change", True),
    "h": ("hunk", True),
    "f": ("file", True),
    "t": ("thread", True),
    "u": ("unresolved thread", True),
    "m": ("comment", False),
    "d": ("draft", True),
}


def is_change(rows, index):
    """The first line of a run of added or removed lines."""
    return rows[index].kind in ("add", "del") and (index == 0 or rows[index - 1].kind not in ("add", "del"))


class MotionsMixin:
    def motion_test(self, letter):
        """Whether a row is what `letter` goes to, as a function of (rows, index)."""
        pr = self.pr

        def unresolved(rows, index):
            thread = pr.thread(rows[index].thread) if rows[index].kind == "thread" else None
            return thread is not None and not thread.resolved

        return {
            "c": is_change,
            "h": lambda rows, index: rows[index].kind == "hunk",
            "t": lambda rows, index: rows[index].kind == "thread",
            "u": unresolved,
            "m": lambda rows, index: rows[index].marker == "|" and rows[index].kind in ("comment", "draft"),
            "d": lambda rows, index: bool(rows[index].draft),
        }[letter]

    def action_motion(self, letter, step, count=1):
        """]x and [x: `count` times to the next (step 1) or previous (step -1) place of that kind."""
        if letter not in MOTIONS or not self.need_pr():
            return
        if letter == "f":
            for _ in range(max(1, count)):
                self.action_file(step)
            return
        self.record_jump("diff")
        self.jumping = True
        try:
            for _ in range(max(1, count)):
                if not self.seek(letter, step):
                    name = MOTIONS[letter][0]
                    self.notify(f"no {'next' if step > 0 else 'earlier'} {name}", timeout=2)
                    break
        finally:
            self.jumping = False

    def seek(self, letter, step):
        """Move to the next place of a kind in this tab, else (on the Files tab, for the kinds that cross) in the next
        file that has one. False when there is none."""
        test = self.motion_test(letter)
        diff = self.query_one("#diff", DiffRows)
        rows = diff.rows
        span = range(diff.cursor + 1, len(rows)) if step > 0 else range(diff.cursor - 1, -1, -1)
        found = next((index for index in span if rows[index].selectable and test(rows, index)), None)
        if found is not None:
            diff.go(found)
            return True
        if self.mode != "files" or not MOTIONS[letter][1] or not self.pr.files:
            return False
        files = range(self.file_index + 1, len(self.pr.files)) if step > 0 else range(self.file_index - 1, -1, -1)
        for index in files:
            other = self.shown_file_rows(index)
            hits = [i for i in range(len(other)) if other[i].selectable and test(other, i)]
            if hits:
                self.open_file(index)
                diff.go(hits[0] if step > 0 else hits[-1])
                return True
        return False
