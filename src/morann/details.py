# SPDX-FileCopyrightText: 2026 Cristiano Carvalho
# SPDX-License-Identifier: Apache-2.0
"""The details panel under the lists: the highlighted pull request from the list's own data (nothing is fetched), laid
out github.com style in at most PANEL_LINES lines, folding to fewer lines and then dropping the least important ones
when the pane is short or narrow."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime

from morann.models import PrRow
from morann.textfmt import ASCII, Line, age, clean, cut, width_of, word_wrap
from morann.views import fit

PANEL_LINES = 6  # lines inside the panel's border at most


OK, BAD, WAIT = "✓", "✗", "●"  # github.com's check, cross and dot


REVIEW = {
    "APPROVED": (OK, "Approved", "ok"),
    "CHANGES_REQUESTED": (BAD, "Changes requested", "bad"),
    "REVIEW_REQUIRED": (WAIT, "Review required", "wait"),
}


MERGE = {
    "CLEAN": (OK, "Can merge", "ok"),
    "HAS_HOOKS": (OK, "Can merge", "ok"),
    "BEHIND": (WAIT, "Behind base", "wait"),
    "DIRTY": (BAD, "Conflicts", "bad"),
    "BLOCKED": (WAIT, "Blocked", "wait"),
    "UNSTABLE": (WAIT, "Checks failing", "wait"),
    "DRAFT": (WAIT, "Draft", "dim"),
}


REVIEWER = {
    "APPROVED": (OK, "ok"),
    "CHANGES_REQUESTED": (BAD, "bad"),
    "COMMENTED": ("○", "dim"),
    "DISMISSED": ("-", "dim"),
}


def panel_title(row: object) -> Line:
    """The panel's title: the number and the state badge, as (text, style) pieces."""
    if not isinstance(row, PrRow):
        return []
    state = ("Draft", "chip-dim") if row.draft else ("Open", "chip-ok")
    return [(f" #{row.number} ", "label"), (f" {state[0]} ", state[1]), (" ", "")]


def checks_chip(row: PrRow) -> tuple[str, str, str] | None:
    counts = dict(row.check_counts)
    if row.checks in ("FAILURE", "ERROR"):
        failed = counts.get("failed")
        return (BAD, f"{failed} failing" if failed else "Checks failing", "bad")
    if row.checks in ("PENDING", "EXPECTED"):
        running = counts.get("running")
        return (WAIT, f"{running} running" if running else "Checks running", "wait")
    if row.checks == "SUCCESS":
        passed = counts.get("passed")
        return (OK, f"{passed} passed" if passed else "Checks passed", "ok")
    return None


def chip(icon: str, text: str, tone: str) -> Line:
    return [(f" {icon} {text} ", f"chip-{tone}"), (" ", "")]


def trim(pieces: Line) -> Line:
    while pieces and pieces[-1] == (" ", ""):
        pieces = pieces[:-1]
    return pieces


def panel_parts(row: PrRow, now: datetime | None = None) -> dict[str, Line]:
    """Each line the panel can show, by name, in the order shown: who and where, labels and size, the status chips,
    the reviewers. Empty fields are left out."""
    parts: dict[str, Line] = {}
    who: Line = [(row.author or "?", "label"), (f"  {row.base_ref or '?'} <- {row.head_ref or '?'}", "dim")]
    opened, updated = age(row.created, now), age(row.updated, now)
    if opened or updated:
        when = ", ".join(
            part
            for part in (f"opened {opened} ago" if opened else "", f"updated {updated} ago" if updated else "")
            if part
        )
        who.append((f"  {when}", "dim"))
    parts["who"] = who
    size: Line = [piece for name in row.labels for piece in ((f" {name} ", "chip-label"), (" ", ""))]
    if row.additions or row.deletions or row.files:
        size += [(f"+{row.additions}", "ok"), (" ", ""), (f"-{row.deletions}", "bad")]
        size.append((f"  {row.files} file{'' if row.files == 1 else 's'}", "dim"))
    if size:
        parts["size"] = trim(size)
    status: Line = []
    for found in (REVIEW.get(row.decision), checks_chip(row), MERGE.get(row.merge_state)):
        if found:
            status += chip(*found)
    if status:
        parts["status"] = trim(status)
    people: Line = []
    for reviewer in row.reviewers:
        if reviewer.login.casefold() != row.author.casefold():
            icon, tone = REVIEWER.get(reviewer.state, ("?", "dim"))
            people += [(reviewer.login, ""), (f" {icon}", tone), ("  ", "")]
    for asked in row.asked:
        people += [(asked, ""), (f" {WAIT} asked", "wait"), ("  ", "")]
    if people:
        while people and people[-1] == ("  ", ""):
            people.pop()
        parts["reviewers"] = [("Reviewers ", "dim"), *people]
    return parts


ORDER = ("who", "size", "status", "reviewers")  # how the lines read under the title
DROP = ("size", "reviewers", "who", "status")  # what goes first when there is no room


def panel_lines(
    row: object,
    width: int,
    limit: int = PANEL_LINES,
    *,
    icons: Mapping[str, str] = ASCII,
    now: datetime | None = None,
) -> list[Line]:
    """The panel's lines for `width` cells and at most `limit` lines: the title (two lines when there is room), then
    who and where, labels and size, the status chips and the reviewers. Short of room it first joins lines that fit on
    one (size after who, reviewers after the chips), then drops the least important ones (size, reviewers, who)."""
    if not isinstance(row, PrRow) or limit < 1:
        return []
    width = max(10, width)
    parts = panel_parts(row, now)
    shown = [name for name in ORDER if name in parts]

    def wide(name: str) -> int:
        return sum(width_of(text) for text, _style in parts[name])

    for first, second in (("who", "size"), ("status", "reviewers")):
        if len(shown) + 1 > limit and first in shown and second in shown and wide(first) + 3 + wide(second) <= width:
            parts[first] = parts[first] + [("   ", "")] + parts.pop(second)
            shown.remove(second)
    for name in DROP:
        if len(shown) + 1 <= limit:
            break
        if name in shown:
            shown.remove(name)
    shown = shown[: max(0, limit - 1)]
    title = word_wrap(clean(row.title).replace("\n", " ") or "(no title)", width)
    rows = 2 if len(title) > 1 and len(shown) + 2 <= limit else 1
    lines: list[Line] = [[(text, "title")] for text in title[:rows]]
    if len(title) > rows:
        lines[-1] = [(cut(" ".join(title[rows - 1 :]), width, icons["ellipsis"]), "title")]
    return lines + [fit(parts[name], width, icons) for name in shown]
