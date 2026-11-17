# SPDX-FileCopyrightText: 2026 Cristiano Carvalho
# SPDX-License-Identifier: Apache-2.0
"""The review bar, github.com's Review changes: Comment, Approve or Request changes with a summary field, opened from the list
or any tab of an open pull request, and the comment on the conversation. Only y in the bar posts, through core.submit."""

from __future__ import annotations

from rich.style import Style
from rich.text import Text
from textual.containers import VerticalScroll
from textual.widgets import Static

from morann import core
from morann.dialogs import ConfirmScreen
from morann.widgets import InlineText, SubmitBar, failure

VERDICT_KEY = {"COMMENT": "c", "APPROVE": "a", "REQUEST_CHANGES": "r"}


VERDICT_LABEL = {"COMMENT": "Comment", "APPROVE": "Approve", "REQUEST_CHANGES": "Request changes"}


class ReviewMixin:
    """The review bar and the comment on the conversation. Mixed into Main."""

    def own_pr(self, pr=None):
        """Whether the open pull request is the viewer's own: approve and request changes are refused there."""
        pr = pr or self.pr
        return pr is not None and bool(pr.viewer) and pr.author.casefold() == pr.viewer.casefold()

    def review_ready(self):
        """The open pull request can take a review now. From the list it must be the selected one, already loaded."""
        if self.focus_pane == "list" and not self.max_diff:
            row = self.selected()
            if row is None:
                self.notify("select a pull request first", severity="warning")
                return False
            if self.pr is None or self.pr.key != row.key:
                self.notify(f"{row.key} is still loading; try again in a moment", severity="warning")
                return False
        return self.can_edit()

    def refuse_own(self, event):
        if event != "COMMENT" and self.own_pr():
            self.notify(
                f"{self.forge.label} does not let you {core.VERDICT[event]} on your own pull request",
                severity="warning",
            )
            return True
        return False

    # A review starts only on purpose: v or :review, or y to the question a commenting key asks when none is on. Opening,
    # reading and moving through a pull request keep nothing on disk and send nothing.

    def reviewing(self):
        """Whether a review of the open pull request is on: started, or holding drafts."""
        return self.drafts is not None and not self.drafts.empty()

    def under_review(self, then, doing=""):
        """True when a review is on. Else it asks whether to start one, saying what was about to be done (`doing`); yes
        starts it and runs then(), cancel does nothing."""
        if self.reviewing():
            return True

        def answered(yes):
            if yes:
                self.start_review()
                then()

        what = f"{doing} starts a review of #{self.pr.number}." if doing else f"A review of #{self.pr.number} starts."
        what += " Its drafts stay on this machine until you post them; nothing is sent now."
        self.app.push_screen(ConfirmScreen("Start a review", what, "Start review"), answered)
        return False

    def start_review(self):
        if not self.can_edit():
            return
        self.drafts.started = True
        self.save_drafts()
        self.notify(
            f"Reviewing #{self.pr.number}: c comments on a line, v shows what would be posted, D in it discards",
            timeout=6,
        )

    def action_review(self, word=""):
        """:review starts a review, or shows what it would post; :review discard ends it with nothing posted."""
        if word == "discard":
            return self.action_discard_review()
        if self.reviewing():
            return self.action_submit("COMMENT")
        if self.review_ready():
            self.start_review()
        return None

    def action_discard_review(self):
        """D in the review bar, or :review discard: drop the review and every draft of it, after a y."""
        if not self.reviewing():
            self.notify("no review is on", timeout=3)
            return
        count = self.drafts.count()
        drafts = f" and its {count} draft{'s' if count != 1 else ''}" if count else ""

        def answered(yes):
            if not yes or self.drafts is None:
                return
            if self.submitting:
                self.action_close_submit()
            self.drafts = core.Drafts(self.drafts.repo, self.drafts.number)
            self.save_drafts()
            self.notify("review discarded; nothing was posted", timeout=4)

        what = f"The review of #{self.pr.number}{drafts} goes. Nothing was posted, and nothing will be."
        self.app.push_screen(ConfirmScreen("Discard the review", what, "Discard"), answered)

    # The comment on the conversation: c on the Conversation tab, C anywhere. ctrl+s keeps it, then the bar asks for y.

    def action_converse(self):
        if not self.review_ready():
            return
        if not self.offer("A comment on the conversation", "Comment now", self.converse_now, self.action_converse):
            return
        if self.focus_pane != "diff":
            self.focus_pane = "diff"
            self.layout_panes()
        if self.mode != "conversation":
            self.set_mode("conversation")
        self.query_one("#diff").focus()
        self.call_after_refresh(self.compose_note)

    def compose_note(self):
        diff = self.query_one("#diff")

        def keep(text):
            if text.strip():
                self.drafts.add_note(text)
                self.save_drafts()
                self.call_after_refresh(self.action_submit, "COMMENT")

        self.open_editor("Comment on the conversation", "", len(diff.rows) - 1, keep)

    # The bar: what one submit would post, with the verdict and the summary; only y posts.

    def action_submit(self, event):
        if not self.review_ready() or self.refuse_own(event):
            return
        if not self.reviewing() and event == "COMMENT":  # v with no review on: it starts one, on purpose
            return self.start_review()
        if not self.under_review(lambda: self.action_submit(event), VERDICT_LABEL[event]):
            return None
        if self.forge.read_only:
            self.notify(
                "Morann runs read-only (--read-only): drafts are kept, nothing can be posted", severity="warning"
            )
            return
        self.submitting = {"event": event}
        self.listing = True  # what would be posted shows from the start; l hides it
        self.query_one("#bar-text", InlineText).text = self.drafts.summary
        self.build_submit()
        bar = self.query_one("#confirm", SubmitBar)
        bar.display = True
        bar.focus()
        self.refresh_bindings()
        if event == "REQUEST_CHANGES" and not self.drafts.summary.strip():  # it needs one: start there
            self.action_bar_summary()

    def build_submit(self):
        event = self.submitting["event"]
        try:
            self.submitting.update(plan=core.build_plan(self.pr, self.drafts, event), problem="")
        except core.PlanError as error:
            self.submitting.update(plan=None, problem=str(error))
        plan = self.submitting["plan"]
        ink = self.app.painter.ink
        count = self.drafts.count()
        head = Text(f"Reviewing #{self.pr.number}: {count} draft{'s' if count != 1 else ''}  ", Style(bold=True))
        own = self.own_pr()
        for name in core.EVENTS if not own else ("COMMENT",):
            token = {"APPROVE": "ok", "REQUEST_CHANGES": "bad"}.get(name, "info")
            chosen = name == event
            label = f" {VERDICT_KEY[name]} {VERDICT_LABEL[name]} "
            head.append(label, ink.chip(token, bold=True) if chosen else ink(token))
            head.append(" ")
        if own:
            head.append(
                f"\napprove and request changes: not on your own pull request ({self.forge.label} refuses them)",
                Style(dim=True),
            )
        self.query_one("#confirm-head", Static).update(head)
        editing = bool(self.editing and self.editing[0] == "bar")
        need = " (needed to request changes)" if event == "REQUEST_CHANGES" else ""
        title = "Summary: ctrl+s keeps it, esc goes back" if editing else f"Summary{need}: m writes it"
        self.query_one("#bar-title", Static).update(Text(title, Style(bold=editing, dim=not editing)))
        status = Text()
        if plan is None:
            status.append(self.submitting["problem"], ink("bad"))
        else:
            status.append(
                f"{len(plan.comments)} comments  {len(plan.replies)} replies  {len(plan.resolves)} resolves"
                f"  {len(plan.notes)} on the conversation"
            )
            for warning in plan.warnings:
                status.append(f"\n{warning}", ink("warn"))
        self.query_one("#confirm-status", Static).update(status)
        self.query_one("#confirm-lines", Static).update(Text("\n".join(plan.lines()) if plan else ""))
        self.query_one("#confirm-list").display = self.listing and plan is not None
        verdicts = "c" if own else "c a r"
        if editing:
            keys = "ctrl+s keep the summary   esc back to the bar"
        elif plan:
            keys = (
                f"y post   n back   {verdicts} verdict   m summary   l {'hide' if self.listing else 'list'}   D discard"
            )
        else:
            keys = f"n back   {verdicts} verdict   m summary   D discard"
        self.query_one("#confirm-keys", Static).update(Text(keys, Style(bold=True)))

    def action_verdict(self, event):
        if self.submitting and not self.refuse_own(event):
            self.submitting["event"] = event
            self.build_submit()
            if event == "REQUEST_CHANGES" and not self.drafts.summary.strip():
                self.action_bar_summary()

    def action_bar_summary(self):
        """Write the summary in the bar's own field; ctrl+s keeps it as a draft and redraws what would be posted."""
        if not self.submitting or self.editing:
            return
        area = self.query_one("#bar-text", InlineText)
        area.text = self.drafts.summary

        def keep(text):
            self.drafts.summary = text
            self.save_drafts()

        self.editing = ("bar", keep)
        area.focus()
        area.move_cursor(area.document.end)
        self.build_submit()
        self.refresh_bindings()

    def bar_summary_closed(self):
        """Back from the summary field to the bar's keys, the field showing the kept summary."""
        self.query_one("#bar-text", InlineText).text = self.drafts.summary if self.drafts else ""
        if self.submitting:
            self.build_submit()
            self.query_one("#confirm").focus()

    def action_toggle_list(self):
        if self.submitting:
            self.listing = not self.listing
            self.build_submit()

    def action_scroll_list(self, step):
        self.query_one("#confirm-list", VerticalScroll).scroll_relative(y=step, animate=False)

    def action_close_submit(self):
        if self.editing and self.editing[0] == "bar":
            self.close_editor()
        self.submitting = None
        self.query_one("#confirm").display = False
        self.query_one(f"#{self.focus_pane}").focus()
        self.refresh_bindings()

    def action_post(self):
        plan = (self.submitting or {}).get("plan")
        if plan is None:
            return
        try:
            now = core.build_plan(self.pr, self.drafts, plan.event)
        except core.PlanError:
            now = None
        if now is None or now.fingerprint() != plan.fingerprint():  # the drafts changed under the bar: show it again
            self.build_submit()
            self.notify("the drafts changed; check the bar again before posting", severity="warning")
            return
        self.action_close_submit()
        self.busy["post"] = "posting..."
        self.show_bars()
        fingerprint = plan.fingerprint()  # the plan the bar showed; core.submit refuses any other
        self.run_worker(lambda: self.post(plan, fingerprint), thread=True, group="post", exclusive=True)

    def post(self, plan, fingerprint):
        try:
            posted = core.submit(self.writer(), plan, fingerprint, self.store)
        except Exception as error:  # noqa: BLE001 - shown in the app rather than closing it
            self.app.call_from_thread(self.posted, plan, None, failure(error))
            return
        self.app.call_from_thread(self.posted, plan, posted, "")

    def posted(self, plan, posted, error):
        self.busy.pop("post", None)
        key = f"{plan.repo}#{plan.number}"
        if not error:  # posted: a review with nothing left in it is over
            left = self.store.load(plan.repo, plan.number)
            if left.started and not left.count():
                left.started = False
                self.store.save(left)
        if self.pr is not None and self.pr.key == key:
            self.drafts = self.store.load(plan.repo, plan.number)
        self.read_drafts()
        if error:
            self.notify(error, severity="error", timeout=20)
        else:
            self.notify("posted: " + ", ".join(posted), timeout=10)
            if plan.replies and self.pr is not None and self.pr.key == key and self.pr.viewer == self.pr.author:
                self.replied_own.add(key)
        self.prs.pop(key, None)
        if self.pr is not None and self.pr.key == key:
            self.load_pr(self.pr, reason="reloading")
        self.show_list()
        self.show_pr()
