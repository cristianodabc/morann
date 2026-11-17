# SPDX-FileCopyrightText: 2026 Cristiano Carvalho
# SPDX-License-Identifier: Apache-2.0
"""One comment, reply or resolve sent on its own, outside any review, as github.com's "Add single comment" does. With
no review on, a commenting key offers it beside starting a review. The text is written in the same inline editor,
then a confirmation shows exactly what goes where; only its yes sends, after checking the head did not move. Mixed
into Main."""

from __future__ import annotations

from morann import core
from morann.dialogs import ChoiceScreen, ConfirmScreen
from morann.widgets import DiffRows, failure


class SingleMixin:
    def offer(self, doing, now_label, now, again, review_label="Start a review", capability=None):
        """With no review on: send it on its own (now_label, then now()), start a review and go on (again()), or
        cancel. The first choice shows only where the forge can do it and Morann may write."""
        if self.reviewing():
            return True
        choices = []
        if not self.forge.read_only and (capability is None or capability in self.forge.capabilities):
            choices.append(("s", now_label, "now"))
        choices += [("r", review_label, "review"), ("n esc", "Cancel", None)]
        what = (
            f"{doing}: send it on its own now, after you see exactly what goes, or keep it as a draft in a review "
            f"of #{self.pr.number}, posted as one when you choose."
        )

        def picked(choice):
            if choice == "now":
                now()
            elif choice == "review":
                self.start_review()
                again()

        self.app.push_screen(ChoiceScreen(doing, what, choices), picked)
        return False

    def line_now(self, row):
        """Write one comment on a line of the diff, then confirm and post it on its own."""
        path, side, line = row.anchor
        where = f"{path}, line {line} of the {'new' if side == 'RIGHT' else 'old'} file"
        pr = self.pr

        def send(text):
            self.writer().post_line_comment(pr.repo, pr.number, pr.head, path, side, line, text)

        self.write_then_post(
            f"Comment on line {line}, sent on its own",
            self.query_one("#diff", DiffRows).cursor,
            f"A comment on {where}",
            send,
        )

    def reply_now(self, thread):
        """Write one reply to a thread, then confirm and post it on its own."""
        pr, root = self.pr, thread.root
        where = f"a reply to {root.author} on {thread.path}, line {thread.line or thread.original_line}"

        def send(text):
            self.writer().post_reply(pr.repo, pr.number, root.id, text)

        self.write_then_post(f"Reply to {root.author}, sent on its own", self.last_row_of(thread.id), where, send)

    def note_now(self):
        """Write one comment on the conversation, then confirm and post it on its own."""
        pr = self.pr

        def send(text):
            self.writer().post_comment(pr.repo, pr.number, text)

        rows = self.query_one("#diff", DiffRows).rows
        self.write_then_post(
            "Comment on the conversation, sent on its own",
            len(rows) - 1,
            f"A comment on the conversation of #{pr.number}",
            send,
        )

    def converse_now(self):
        """C with no review on, sent on its own: the Conversation tab, then the comment at its end."""
        self.focus_on("diff")
        if self.mode != "conversation":
            self.set_mode("conversation")
        self.call_after_refresh(self.note_now)

    def resolve_now(self, thread):
        """Resolve or unresolve a thread at once; the choice that led here said so, in words, first."""
        resolve = not thread.resolved
        self.send_now(lambda: self.writer().resolve_thread(thread.id, resolve), check_head=False)

    def write_then_post(self, title, after, where, send, text=""):
        """The inline editor under row `after`; ctrl+s shows what would be posted and where, and only yes posts it.
        Cancel brings the text back to the editor."""

        def keep(written):
            if not written.strip():
                return
            what = f"{where}, posted now and on its own:\n\n{written.strip()}"

            def answered(yes):
                if yes:
                    self.send_now(lambda: send(written.strip()))
                else:
                    self.call_after_refresh(self.write_then_post, title, after, where, send, written)

            self.app.push_screen(ConfirmScreen("Post it now", what, "Post"), answered)

        self.open_editor(title, text, after, keep)

    def send_now(self, send, check_head=True):
        """Run one write in the background, refused when the pull request's head moved since it was read; then read
        the pull request again so what was sent shows."""
        pr = self.pr
        self.busy["post"] = "posting..."
        self.show_bars()

        def work():
            try:
                if check_head:
                    head = self.forge.head_sha(pr.repo, pr.number)
                    if head != pr.head:
                        raise core.HeadMoved(f"#{pr.number} moved to {head[:7]} since it was read; r reads it again")
                send()
            except Exception as error:  # noqa: BLE001 - shown in the app rather than closing it
                self.app.call_from_thread(self.sent_now, pr, failure(error))
                return
            self.app.call_from_thread(self.sent_now, pr, "")

        self.run_worker(work, thread=True, group="post", exclusive=True)

    def sent_now(self, pr, error):
        self.busy.pop("post", None)
        if error:
            self.notify(error, severity="error", timeout=15)
        else:
            self.notify("sent", timeout=4)
        self.prs.pop(pr.key, None)
        if self.pr is not None and self.pr.key == pr.key:
            self.load_pr(self.pr, reason="reloading")
        self.show_bars()
