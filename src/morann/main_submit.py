# SPDX-FileCopyrightText: 2026 Cristiano Carvalho
# SPDX-License-Identifier: Apache-2.0
"""The dialogs for the pull request actions (merge first) and the bulk update. Every write starts from a y in one of them; the review bar is in main_review."""

from __future__ import annotations

from rich.style import Style
from rich.text import Text
from textual.widgets import Static

from morann import core
from morann.dialogs import ActionScreen
from morann.widgets import failure


class SubmitMixin:
    """The pull request actions, the bulk update and the scope-switch question. Mixed into Main."""

    # Pull request actions: a popup with what the forge allows now, and why not for the rest.

    def action_actions(self):
        row = self.pr if self.focus_pane == "diff" and self.pr is not None else self.selected()
        if self.scope_kind == "personal" or row is not None and core.personal_repo(row.repo, self.login):
            self.notify(
                f"personal repositories are read-only here: view them, or open them in {self.forge.label} (o)",
                severity="warning",
            )
            return
        if row is None:
            self.notify("select a pull request first", severity="warning")
            return
        self.busy["state"] = f"reading {row.key}..."
        self.show_bars()
        repo, number = row.repo, row.number
        self.run_worker(lambda: self.fetch_state(repo, number), thread=True, group="state", exclusive=True)

    def fetch_state(self, repo, number):
        try:
            state = self.forge.read_state(repo, number)
        except Exception as error:  # noqa: BLE001 - shown in the app rather than closing it
            self.app.call_from_thread(self.state_failed, failure(error))
            return
        self.app.call_from_thread(self.show_actions, state)

    def state_failed(self, message):
        self.busy.pop("state", None)
        self.notify(message, severity="error", timeout=10)
        self.show_bars()

    def show_actions(self, state):
        self.busy.pop("state", None)
        if self.editing or self.submitting:
            return
        self.acting = {"state": state, "plan": None, "armed": False}
        method = state.auto_method  # the merge method preselected: squash first, as the repository allows
        if not core.why_not(state, method, self.forge.read_only):
            self.acting["plan"] = core.build_action(state, method, self.forge.read_only)
        self.app.push_screen(ActionScreen(f"Actions: {state.repo}#{state.number}"))  # it draws itself once mounted
        self.show_bars()

    def action_body(self, body):
        """Show the popup's text, once the popup is on screen."""
        screen = self.app.screen
        if isinstance(screen, ActionScreen):
            screen.query_one("#actions-body", Static).update(body)

    def draw_actions(self):
        if not self.acting:
            return None
        if self.acting.get("bulk"):
            return self.draw_bulk()
        state, plan = self.acting["state"], self.acting["plan"]
        ink = self.app.painter.ink
        tones = {"ok": "ok", "bad": "bad", "wait": "warn"}
        body = Text()
        body.append(f"Merge {state.repo}#{state.number}", Style(bold=True))
        body.append(
            f"  {state.state.lower()}  head {state.head[:7]} into {state.base}  by {state.author}\n", Style(dim=True)
        )
        for text, tone in core.merge_view(state):
            body.append(f"  {text}\n", ink(tones.get(tone, "muted")))
        menu = core.action_menu(state, self.forge.read_only)
        for group in (core.MERGE_METHODS, None):  # the merge methods first, then everything else
            for action, label, key, reason in menu:
                if (action in core.MERGE_METHODS) != (group is not None):
                    continue
                chosen = plan is not None and plan.action == action
                if reason:
                    body.append(f"   {label}: {reason}\n", ink("muted"))
                else:
                    body.append(f" {key} ", ink.key())
                    body.append(
                        f" {label}{'  <' if chosen else ''}\n",
                        ink("bad", bold=True) if action in core.RISKY else Style(bold=True),
                    )
            if group is not None:
                body.append("\n")
        body.append(" g ", ink.key())
        body.append(f" Open in {self.forge.label}\n", Style(bold=True))
        if plan is None:
            body.append("press a key to choose, esc closes", Style(bold=True))
            return self.action_body(body)
        body.append("\n")
        for line in plan.lines():
            body.append(f"{line}\n", ink("warn") if line.startswith("Note:") else Style(bold=True))
        if plan.action == "rerequest":  # each past reviewer, chosen or not; a number toggles one
            for n, (login, _pick, why) in enumerate(state.candidates(), 1):
                chosen = login in plan.reviewers
                body.append(f" {n} {login} ", Style(reverse=chosen, bold=chosen, dim=not chosen))
                body.append(f" {why}\n", Style(dim=True))
            body.append("1-9 choose who to ask\n", Style(dim=True))
        if self.acting["armed"]:
            body.append(f"press y again to {plan.label}, esc closes", ink("bad", bold=True))
        elif plan.risky:
            body.append(
                f"y, then y again, to {plan.label}; another key picks that instead; esc closes", Style(bold=True)
            )
        else:
            body.append(f"y to {plan.label}; esc closes", Style(bold=True))
        return self.action_body(body)

    def action_pick(self, key):
        if not self.acting or self.acting.get("bulk") or self.acting["armed"]:
            return
        state = self.acting["state"]
        choices = [
            (action, reason)
            for action, _label, action_key, reason in core.action_menu(state, self.forge.read_only)
            if action_key == key
        ]
        action = next((action for action, reason in choices if not reason), choices[0][0] if choices else None)
        if action is None:
            return
        try:
            self.acting["plan"] = core.build_action(state, action, self.forge.read_only)
        except core.PlanError as error:
            self.notify(str(error), severity="warning", timeout=6)
            return
        self.draw_actions()

    # Bulk update: your pull requests behind their base, all chosen; 1-9 toggle; y updates, the lowest of a stack first.

    def action_bulk_update(self):
        if self.refuse_personal():
            return
        missing = core.lacks(self.forge, core.Capability.UPDATE_BRANCH)
        if missing:
            self.notify(missing, severity="warning")
            return
        if self.forge.read_only:
            self.notify("Morann runs read-only (--read-only): nothing can be updated", severity="warning")
            return
        self.busy["state"] = "finding your pull requests behind their base..."
        self.show_bars()
        self.run_worker(self.fetch_behind, thread=True, group="state", exclusive=True)

    def fetch_behind(self):
        try:
            items, skipped = core.update_candidates(self.forge, self.scope)
        except Exception as error:  # noqa: BLE001 - shown in the app rather than closing it
            self.app.call_from_thread(self.state_failed, failure(error))
            return
        self.app.call_from_thread(self.show_bulk, items, skipped)

    def show_bulk(self, items, skipped):
        self.busy.pop("state", None)
        if self.editing or self.submitting:
            return
        self.acting = {
            "bulk": True,
            "items": items,
            "skipped": skipped,
            "chosen": {item.key for item in items},
            "results": {},
            "plan": None,
            "running": False,
        }
        self.app.push_screen(ActionScreen("Update branches behind their base"))
        self.show_bars()

    def draw_bulk(self):
        acting = self.acting
        body = Text("Update branches behind their base (your pull requests)\n", Style(bold=True))
        if not acting["items"]:
            body.append("nothing is behind its base\n", Style(dim=True))
        for n, item in enumerate(acting["items"], 1):
            chosen = item.key in acting["chosen"]
            body.append(f" {n} ", Style(reverse=chosen, bold=chosen, dim=not chosen))
            behind = f"{item.behind_by} behind" if item.behind_by is not None else "behind"
            body.append(f" {item.key} {item.head_ref} <- {item.base}  {behind}", Style(bold=chosen, dim=not chosen))
            if item.stacked_on:
                body.append(f"  on #{item.stacked_on}", Style(dim=True))
            result = acting["results"].get(item.key)
            if result:
                token = "ok" if result == "updated" else "bad" if result.startswith("refused") else "warn"
                body.append(f"  {result}", self.app.painter.ink(token))
            body.append("\n")
        for item, why in acting["skipped"]:
            body.append(f"   skip {item.key}: {why}\n", Style(dim=True))
        if acting["running"]:
            body.append("updating, lowest of each stack first...", Style(bold=True))
        elif acting["results"]:
            body.append("done; esc closes", Style(bold=True))
        else:
            body.append("y updates the chosen ones in this order; 1-9 toggle; esc closes", Style(bold=True))
        self.action_body(body)

    def run_bulk(self):
        acting = self.acting
        items = [item for item in acting["items"] if item.key in acting["chosen"]]
        if not items or acting["running"] or acting["results"]:
            return
        acting["running"] = True
        self.draw_actions()
        fingerprint = core.update_fingerprint(items)  # what the bar showed; run_updates refuses any other

        def work():
            try:
                core.run_updates(
                    self.writer(),
                    items,
                    fingerprint,
                    progress=lambda item, result: self.app.call_from_thread(self.bulk_progress, item, result),
                )
            except Exception as error:  # noqa: BLE001 - shown in the app rather than closing it
                self.app.call_from_thread(self.notify, failure(error), severity="error", timeout=15)
            self.app.call_from_thread(self.bulk_done)

        self.run_worker(work, thread=True, group="post", exclusive=True)

    def bulk_progress(self, item, result):
        if self.acting and self.acting.get("bulk"):
            self.acting["results"][item.key] = result
            self.draw_actions()

    def bulk_done(self):
        if self.acting and self.acting.get("bulk"):
            self.acting["running"] = False
            results = list(self.acting["results"].values())
            self.draw_actions()
            self.notify(f"updated {results.count('updated')} of {len(results)}", timeout=8)
        self.action_refresh()

    def action_toggle_reviewer(self, n):
        if self.acting and self.acting.get("bulk"):
            items = self.acting["items"]
            if 1 <= n <= len(items) and not self.acting["running"] and not self.acting["results"]:
                self.acting["chosen"] ^= {items[n - 1].key}
                self.draw_actions()
            return
        plan = (self.acting or {}).get("plan")
        if plan is None or plan.action != "rerequest":
            return
        candidates = [login for login, _pick, _why in self.acting["state"].candidates()]
        if not 1 <= n <= len(candidates):
            return
        chosen = set(plan.reviewers) ^ {candidates[n - 1]}
        self.acting["plan"] = core.build_action(
            self.acting["state"], "rerequest", self.forge.read_only, reviewers=chosen
        )
        self.acting["armed"] = False
        self.draw_actions()

    def action_act(self):
        if self.acting and self.acting.get("bulk"):
            return self.run_bulk()
        plan = (self.acting or {}).get("plan")
        if plan is None:
            return
        if plan.action == "rerequest" and not plan.reviewers:
            self.notify("choose at least one reviewer (1-9)", severity="warning")
            return
        if plan.risky and not self.acting["armed"]:  # merges and close take a second y
            self.acting["armed"] = True
            self.draw_actions()
            return
        self.action_close_actions()
        self.busy["post"] = f"{plan.label}..."
        self.show_bars()
        fingerprint = plan.fingerprint()  # the action the bar showed; core.run_action refuses any other
        self.run_worker(lambda: self.send_action(plan, fingerprint), thread=True, group="post", exclusive=True)

    def send_action(self, plan, fingerprint):
        try:
            done = core.run_action(self.writer(), plan, fingerprint)
        except Exception as error:  # noqa: BLE001 - shown in the app rather than closing it
            self.app.call_from_thread(self.action_done, None, failure(error))
            return
        self.app.call_from_thread(self.action_done, done, "")

    def action_done(self, done, error):
        self.busy.pop("post", None)
        if error:
            self.notify(error, severity="error", timeout=20)
        else:
            self.notify(done, timeout=10)
            if done.startswith("re-request review"):
                self.replied_own.discard(self.pr.key if self.pr else "")
        self.action_refresh()

    def action_close_actions(self):
        self.acting = None
        if isinstance(self.app.screen, ActionScreen):
            self.app.pop_screen()
        self.query_one(f"#{self.focus_pane}").focus()
        self.refresh_bindings()
