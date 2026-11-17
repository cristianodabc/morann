# SPDX-FileCopyrightText: 2026 Cristiano Carvalho
# SPDX-License-Identifier: Apache-2.0
"""Editing and deleting what you already posted: a comment on the diff, a comment on the conversation, a review's
summary, the description of your own pull request. e opens the inline editor with the text as it stands, and a
confirmation shows the change, old and new, before it is sent; d d asks with the whole text before a delete. Only
your own posts, only where the forge can, and never with --read-only. Mixed into Main."""

from __future__ import annotations

import difflib

from morann import core
from morann.dialogs import ConfirmScreen
from morann.widgets import DiffRows

KIND_NAMES = {
    "line": "comment",
    "conversation": "comment on the conversation",
    "review": "review summary",
    "description": "description",
}
DELETABLE = ("line", "conversation")  # a submitted review and a description can be edited, never deleted


def change(old: str, new: str) -> str:
    """The lines an edit changes, - old and + new, with one line of what stays around them."""
    lines = difflib.unified_diff(old.strip().splitlines(), new.strip().splitlines(), lineterm="", n=1)
    return "\n".join(line for line in lines if not line.startswith(("---", "+++", "@@")))


class PostsMixin:
    def own_post(self, row):
        """Whether the row is a post of the viewer's that can be changed."""
        return row is not None and row.post is not None and row.mine

    def may_change(self, capability, verb):
        """Refuse, saying why, with --read-only or on a forge without the capability."""
        if self.forge.read_only:
            self.notify(f"Morann runs read-only (--read-only): nothing can be {verb}", severity="warning")
            return False
        missing = core.lacks(self.forge, capability)
        if missing:
            self.notify(missing, severity="warning")
            return False
        return not self.refuse_personal()

    def edit_post(self, row):
        """e on your own post: the editor with its text; ctrl+s shows the change, and only yes sends it."""
        if not self.may_change(core.Capability.EDIT_COMMENTS, "edited"):
            return
        kind, post_id = row.post
        pr, name = self.pr, KIND_NAMES[kind]

        def ask(text):
            if text.strip() == row.raw.strip():
                self.notify("nothing changed", timeout=3)
                return

            def answered(yes):
                if yes:
                    self.send_now(
                        lambda: self.writer().edit_comment(pr.repo, pr.number, kind, post_id, text.strip()),
                        check_head=False,
                    )
                else:
                    self.call_after_refresh(
                        self.open_editor, f"Edit your {name}", text, self.query_one("#diff", DiffRows).cursor, ask
                    )

            what = f"Your {name}, changed on {self.forge.label}:\n\n{change(row.raw, text)}"
            self.app.push_screen(ConfirmScreen("Save the edit", what, "Save"), answered)

        self.open_editor(f"Edit your {name}", row.raw, self.query_one("#diff", DiffRows).cursor, ask)

    def delete_post(self, row):
        """d d on your own comment: the whole text, and yes deletes it from the forge for good."""
        kind, post_id = row.post
        if kind not in DELETABLE:
            self.notify(f"a {KIND_NAMES[kind]} can be edited (e), not deleted", severity="warning", timeout=4)
            return
        if not self.may_change(core.Capability.DELETE_COMMENTS, "deleted"):
            return
        pr, name = self.pr, KIND_NAMES[kind]

        def answered(yes):
            if yes:
                self.send_now(lambda: self.writer().delete_comment(pr.repo, pr.number, kind, post_id), check_head=False)

        what = f"Your {name}, deleted from {self.forge.label} for good:\n\n{row.raw.strip()}"
        self.app.push_screen(ConfirmScreen("Delete it", what, "Delete"), answered)
