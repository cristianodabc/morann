# SPDX-FileCopyrightText: 2026 Cristiano Carvalho
# SPDX-License-Identifier: Apache-2.0
"""Pull request actions (merge, update, close, ready, auto-merge, re-request review) and the bulk update of pull
requests behind their base. Own pull requests only, confirmed, the head checked again.

The user merges, updates, closes and drafts only their own pull requests, so every action is refused on anyone else's,
with the reason shown. An action is sent only through run_action, which needs the fingerprint of the plan the popup
showed, reads the pull request again and refuses when the head moved or the action no longer fits."""

from __future__ import annotations

import hashlib
import json
import time
from collections.abc import Callable, Collection
from dataclasses import asdict, dataclass
from typing import TYPE_CHECKING

from morann.drafts import HeadMoved, NotConfirmed, PlanError
from morann.forge import Capability, ForgeError, lacks
from morann.models import PrState, Scope
from morann.views import merge_lines

if TYPE_CHECKING:
    from morann.forge import Forge

# (action, what the popup calls it, the key that picks it)
ACTIONS = (
    ("squash", "squash and merge", "s"),
    ("merge", "merge commit", "m"),
    ("rebase", "rebase and merge", "b"),
    ("update", "update branch", "u"),
    ("close", "close", "c"),
    ("reopen", "reopen", "o"),
    ("ready", "mark ready for review", "w"),
    ("draft", "convert to draft", "w"),
    ("automerge", "enable auto-merge", "A"),
    ("noautomerge", "disable auto-merge", "A"),
    ("rerequest", "re-request review", "R"),
)

LABEL = {action: label for action, label, _key in ACTIONS}

METHOD = {"merge": "merge", "squash": "squash", "rebase": "rebase"}

RISKY = ("merge", "squash", "rebase", "close")  # these take a second y

NEEDS = {  # the actions a forge may not have at all
    "update": Capability.UPDATE_BRANCH,
    "ready": Capability.DRAFTS,
    "draft": Capability.DRAFTS,
    "automerge": Capability.AUTO_MERGE,
    "noautomerge": Capability.AUTO_MERGE,
    "rerequest": Capability.REREQUEST_REVIEW,
}


def merge_view(state: PrState) -> list[tuple[str, str]]:
    """What the actions popup shows above the merge methods, in the merge box wording: reviews, checks, the branch,
    and for a stacked pull request that merging it lands the ones below it too. (text, style) pairs."""
    lines = merge_lines(state.forge.label, state.review_decision, state.checks, state.merge_state)
    if state.stacked_on:
        lines.append(
            (
                f"Stacked on #{state.stacked_on}: {state.forge.label} merges it with the open pull requests below it",
                "wait",
            )
        )
    return lines


def why_not(state: PrState, action: str, read_only: bool = False) -> str:
    """Why this action cannot run on this pull request now, or "" when it can."""
    if read_only:
        return "Morann runs read-only (--read-only)"
    if action in NEEDS and (missing := lacks(state.forge, NEEDS[action])):
        return missing
    if not state.own:
        return "only on your own pull requests"
    if state.state == "MERGED":
        return "already merged"
    if action == "reopen":
        return "" if state.state == "CLOSED" else "already open"
    if state.state == "CLOSED":
        return "closed: reopen it first"
    if action == "close":
        return ""
    if action == "rerequest":
        return "" if state.candidates() else "nobody reviewed it yet who is not asked already"
    if action == "ready":
        return "" if state.draft else "not a draft"
    if action == "draft":
        return "already a draft" if state.draft else ""
    if action == "noautomerge":
        return "" if state.auto_merge else "auto-merge is off"
    if action == "update":
        if state.mergeable == "CONFLICTING" or state.merge_state == "DIRTY":
            return "conflicts with the base branch: update it locally"
        return "" if state.merge_state == "BEHIND" else "already up to date with the base branch"
    if action == "automerge":
        if not state.auto_merge_allowed:
            return "the repository does not allow auto-merge"
        if state.auto_merge:
            return "auto-merge is already on"
    elif METHOD[action] not in state.methods:
        return f"the repository does not allow {LABEL[action]}"
    if state.draft:
        return "draft: mark it ready for review first"
    if state.mergeable == "CONFLICTING" or state.merge_state == "DIRTY":
        return "conflicts with the base branch"
    if action == "automerge":
        return (
            "can merge now; auto-merge is for waiting on checks or reviews"
            if state.merge_state in ("CLEAN", "HAS_HOOKS", "UNSTABLE")
            else ""
        )
    if state.merge_state == "BEHIND":
        return "behind the base branch: update branch first"
    if state.merge_state == "BLOCKED":
        if state.review_decision == "CHANGES_REQUESTED":
            return "changes requested"
        if state.review_decision == "REVIEW_REQUIRED":
            return "review required"
        if state.checks in ("FAILURE", "ERROR"):
            return "checks are red"
        if state.checks in ("PENDING", "EXPECTED"):
            return "checks are still running"
        return "blocked by branch protection"
    if state.mergeable == "UNKNOWN" or state.merge_state == "UNKNOWN":
        return f"{state.forge.label} is still checking mergeability; refresh in a moment"
    return ""


def action_menu(state: PrState, read_only: bool = False) -> list[tuple[str, str, str, str]]:
    """[(action, label, key, reason)] for every action; reason is "" for the ones that can run now."""
    return [(action, label, key, why_not(state, action, read_only)) for action, label, key in ACTIONS]


@dataclass(frozen=True)
class ActionPlan:
    action: str
    repo: str
    number: int
    id: str
    head: str
    base: str
    method: str = ""
    warnings: tuple[str, ...] = ()
    reviewers: tuple[str, ...] = ()  # who a re-request asks
    stacked_on: int | None = None  # the open pull request below it, which a merge lands too
    forge: str = ""  # what the forge is called, for the plan's wording

    @property
    def label(self) -> str:
        return LABEL[self.action]

    @property
    def risky(self) -> bool:
        return self.action in RISKY

    def fingerprint(self) -> str:
        return hashlib.sha256(json.dumps(asdict(self), sort_keys=True).encode()).hexdigest()

    def lines(self) -> list[str]:
        what = {
            "merge": f"Merge into {self.base} with a merge commit",
            "squash": f"Squash and merge into {self.base}",
            "rebase": f"Rebase and merge into {self.base}",
            "update": f"Update the branch from {self.base}",
            "close": "Close the pull request",
            "reopen": "Reopen the pull request",
            "ready": "Mark ready for review",
            "draft": "Convert to draft",
            "automerge": f"Enable auto-merge ({self.method}) into {self.base}",
            "noautomerge": "Disable auto-merge",
            "rerequest": "Request review again from " + (", ".join(self.reviewers) or "nobody"),
        }[self.action]
        if self.action in METHOD and self.stacked_on:
            what += f", with the open pull requests below it (stacked on #{self.stacked_on})"
        return [
            f"{what}: {self.repo}#{self.number} at {self.head[:7]}",
            f"{self.forge} refuses it if the head moved"
            if self.action in ("merge", "squash", "rebase", "update", "automerge")
            else "Morann reads the pull request again and refuses if the head moved",
            *(f"Note: {warning}" for warning in self.warnings),
        ]


def build_action(
    state: PrState, action: str, read_only: bool = False, reviewers: Collection[str] | None = None
) -> ActionPlan:
    """The plan for one action on this pull request, or a PlanError with the reason it cannot run. A re-request asks
    the reviewers given, or by default those the candidates chose."""
    if action not in LABEL:
        raise PlanError(f"unknown action {action}")
    reason = why_not(state, action, read_only)
    if reason:
        raise PlanError(f"{LABEL[action]}: {reason}")
    if action == "rerequest":
        known = [login for login, _chosen, _why in state.candidates()]
        chosen = (
            [login for login, pick, _why in state.candidates() if pick]
            if reviewers is None
            else [login for login in known if login in reviewers]
        )
        return ActionPlan(
            action=action,
            repo=state.repo,
            number=state.number,
            id=state.id,
            head=state.head,
            base=state.base,
            reviewers=tuple(chosen),
            forge=state.forge.label,
        )
    warnings = ("some checks are failing",) if action in METHOD and state.merge_state == "UNSTABLE" else ()
    return ActionPlan(
        action=action,
        repo=state.repo,
        number=state.number,
        id=state.id,
        head=state.head,
        base=state.base,
        method=METHOD.get(action) or (state.auto_method if action == "automerge" else ""),
        warnings=warnings,
        stacked_on=state.stacked_on if action in METHOD else None,
        forge=state.forge.label,
    )


def run_action(
    forge: Forge, plan: ActionPlan, confirmed: str | None, sleep: Callable[[float], None] = time.sleep
) -> str:
    """Send one confirmed action. The pull request is read again first: a moved head or a state that no longer allows
    the action sends nothing. The forge gets the head the plan was made for, so it refuses a moved one too."""
    if not confirmed or confirmed != plan.fingerprint():
        raise NotConfirmed("not confirmed in the action bar; nothing was sent")
    fresh = forge.read_state(plan.repo, plan.number)
    if fresh.head != plan.head:
        raise HeadMoved(
            f"the pull request moved from {plan.head[:7]} to {fresh.head[:7]}; nothing was sent. Look again"
        )
    reason = why_not(fresh, plan.action, forge.read_only)
    if reason:
        raise PlanError(f"{plan.label}: {reason}; nothing was sent")
    if plan.action in METHOD and (fresh.stacked_on or None) != plan.stacked_on:
        raise PlanError(f"{plan.label}: the stack below it changed; nothing was sent. Look again")
    if plan.action == "rerequest" and not plan.reviewers:
        raise PlanError("re-request review: nobody chosen; nothing was sent")
    outcome = forge.apply_action(plan, sleep)
    key = f"{plan.repo}#{plan.number}"
    return f"{plan.label}: {outcome} ({key})" if outcome else f"{plan.label}: done on {key}"


# Bulk update: every pull request of yours that is behind its base, updated on the forge, the lowest of a stack first.
# Nothing is forced: each one is read again right before, and the forge gets the head that was just read.


@dataclass(frozen=True)
class UpdateItem:
    repo: str
    number: int
    title: str
    head_ref: str
    base: str
    draft: bool
    behind_by: int | None = None
    stacked_on: int | None = None  # the pull request whose branch is this one's base

    @property
    def key(self) -> str:
        return f"{self.repo}#{self.number}"


def update_candidates(
    forge: Forge, scope: Scope, include_drafts: bool = True
) -> tuple[list[UpdateItem], list[tuple[UpdateItem, str]]]:
    """([UpdateItem] behind their base, lowest of a stack first; [(UpdateItem, why)] left out: conflicts, drafts when
    asked). Only your own open pull requests."""
    mine = forge.list_pull_requests(scope).mine
    branch = {(row.repo, row.head_ref): row for row in mine}
    items, skipped = [], []
    for row in mine:
        parent = branch.get((row.repo, row.base_ref))
        item = UpdateItem(
            repo=row.repo,
            number=row.number,
            title=row.title,
            head_ref=row.head_ref,
            base=row.base_ref,
            draft=row.draft,
            stacked_on=parent.number if parent else None,
        )
        if row.merge_state == "DIRTY" or row.mergeable == "CONFLICTING":
            skipped.append((item, "conflicts with its base: update it locally"))
        elif row.merge_state != "BEHIND":
            continue
        elif row.draft and not include_drafts:
            skipped.append((item, "draft (--no-draft)"))
        else:
            items.append(UpdateItem(**{**asdict(item), "behind_by": forge.behind_by(row)}))
    return stack_order(items), skipped


def stack_order(items: list[UpdateItem]) -> list[UpdateItem]:
    """Pull requests in an order that updates a stack from the bottom: one whose base is another's branch comes after
    it."""
    by_number = {(item.repo, item.number): item for item in items}

    def chain(item: UpdateItem, seen: tuple[str, ...] = ()) -> tuple[int, ...]:
        """The item's ancestors in the list, bottom first, then the item."""
        parent = by_number.get((item.repo, item.stacked_on)) if item.stacked_on is not None else None
        if parent is None or parent.key in seen:
            return (item.number,)
        return (*chain(parent, (*seen, item.key)), item.number)

    return sorted(items, key=lambda item: (item.repo, chain(item)))  # each stack together, bottom first


def update_fingerprint(items: list[UpdateItem]) -> str:
    return hashlib.sha256(json.dumps(sorted(item.key for item in items)).encode()).hexdigest()


def run_updates(
    forge: Forge,
    items: list[UpdateItem],
    confirmed: str | None,
    *,
    sleep: Callable[[float], None] = time.sleep,
    progress: Callable[[UpdateItem, str], None] | None = None,
    waits: int = 5,
) -> list[tuple[UpdateItem, str]]:
    """Update each pull request in order. Each is read again first: someone else's, closed, already current or in
    conflict is reported and left alone; the update carries the head just read. Returns [(UpdateItem, result)] with
    result one of updated, already current, conflicts, or refused: why."""
    if not confirmed or confirmed != update_fingerprint(items):
        raise NotConfirmed("not confirmed; nothing was updated")
    if forge.read_only:
        raise PlanError("Morann runs read-only (--read-only); nothing was updated")
    results = []
    for item in items:
        try:
            state = forge.read_state(item.repo, item.number)
            for _wait in range(waits):  # right after its base moved, the forge needs a moment to see it is behind
                if state.merge_state != "UNKNOWN":
                    break
                sleep(2)
                state = forge.read_state(item.repo, item.number)
            if state.merge_state == "UNKNOWN":
                result = f"refused: {forge.label} is still checking whether it is behind; run it again in a moment"
            elif not state.own:
                result = "refused: not your pull request"
            elif state.state != "OPEN":
                result = f"refused: {state.state.lower()}"
            elif state.mergeable == "CONFLICTING" or state.merge_state == "DIRTY":
                result = "conflicts"
            elif state.merge_state != "BEHIND":
                result = "already current"
            else:
                forge.update_branch(item.repo, item.number, state.head)
                result = "updated"
        except ForgeError as error:
            result = f"refused: {error}"
        results.append((item, result))
        if progress:
            progress(item, result)
    return results


def update_failed(results: list[tuple[UpdateItem, str]]) -> bool:
    return any(result.startswith("refused") for _item, result in results)
