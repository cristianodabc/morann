# SPDX-FileCopyrightText: 2026 Cristiano Carvalho
# SPDX-License-Identifier: Apache-2.0
"""What in the lists needs you: one attention flag per pull request, the counts for the top bar, and how long a review
request has waited. Standard library only; the list query already reads every field used here."""

from __future__ import annotations

from collections.abc import Collection, Iterable, Mapping, Sequence
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from morann.textfmt import age

if TYPE_CHECKING:
    from morann.models import PrRow

Part = tuple[int, str, str]  # one count of the top bar: (count, word, the filter it narrows to or "")

# In priority order: a pull request shows only the first that applies. Each with its list style (red, yellow, blue).
# Their markers are textfmt's ASCII and NERD "flag:NAME" entries.
FLAGS = (("failing", "bad"), ("changes", "bad"), ("conflict", "bad"), ("behind", "wait"), ("new", "new"))
FLAG_STYLE = dict(FLAGS)
FLAG_LABEL = {
    "failing": "CI failing",
    "changes": "changes requested",
    "conflict": "conflicts",
    "behind": "behind its base",
    "new": "new commits, comments or reviews since you last opened it",
}
FILTERS = ("failing", "behind", "draft")  # the summary's groups the list can be narrowed to
KEYS = {"failing": "!", "behind": "b", "draft": "d"}  # the key of each
WARN_DAYS, LATE_DAYS = 2, 5  # a review request older than this is yellow, then red
SEEN_LIMIT = 300  # pull requests remembered for the new-activity flag


def failing(row: PrRow) -> bool:
    return row.checks in ("FAILURE", "ERROR")


def behind(row: PrRow) -> bool:
    return row.merge_state == "BEHIND"


def drafted(row: PrRow) -> bool:
    return bool(row.draft)


def flag(row: PrRow, seen: Sequence[Any] | None = None) -> str:
    """The first of FLAGS that applies to a list row, or "". `seen` is what state.json kept from the last time the pull
    request was opened, [head, activity]; with none there is nothing to compare, so no new-activity flag."""
    if failing(row):
        return "failing"
    if row.decision == "CHANGES_REQUESTED":
        return "changes"
    if row.merge_state == "DIRTY" or row.mergeable == "CONFLICTING":
        return "conflict"
    if behind(row):
        return "behind"
    if seen and (seen[0] != row.head or row.activity > seen[1]):
        return "new"
    return ""


def remember(seen: Mapping[str, list[Any]] | None, row: PrRow) -> dict[str, list[Any]]:
    """`seen` with this row's head and activity as last opened, the oldest dropped past SEEN_LIMIT."""
    out = {key: value for key, value in (seen or {}).items() if key != row.key}
    out[row.key] = [row.head, row.activity]
    return dict(list(out.items())[-SEEN_LIMIT:])


def matches(row: PrRow, name: str) -> bool:
    """Whether a row belongs to a summary filter: failing, behind or draft."""
    return (
        failing(row)
        if name == "failing"
        else behind(row)
        if name == "behind"
        else drafted(row)
        if name == "draft"
        else True
    )


def summary(
    mine: Collection[PrRow] = (), review: Collection[PrRow] = (), wide: tuple[Iterable[PrRow], int] | None = None
) -> list[Part]:
    """The top bar's counts as (count, word, filter) parts, zero ones left out: mine and to review, the scope's open count
    in an organization or Personal (wide is (rows, total)), then behind, failing and draft pull requests over every row on hand."""
    parts: list[Part] = [(len(mine), "mine", ""), (len(review), "to review", "")]
    rows = {row.key: row for row in [*mine, *review]}
    if wide is not None:
        parts.append((wide[1], "open", ""))
        rows.update((row.key, row) for row in wide[0])
    parts += [
        (sum(1 for row in rows.values() if behind(row)), "behind", "behind"),
        (sum(1 for row in rows.values() if failing(row)), "failing", "failing"),
        (sum(1 for row in rows.values() if drafted(row)), "drafts", "draft"),
    ]
    return [part for part in parts if part[0]]


def summary_text(parts: Iterable[Part], narrow: bool = False) -> str:
    """ "2 mine  5 to review  1 failing", or counts with one letter when narrow: "2m 5r 1f"."""
    if narrow:
        return " ".join(f"{count}{'r' if word == 'to review' else word[0]}" for count, word, _ in parts)
    return "  ".join(f"{count} {word}" for count, word, _ in parts)


def waiting_since(row: PrRow, login: str) -> str:
    """When the latest review request to you (or to one of your teams) was made; the pull request's creation without one."""
    asked = [
        at
        for who, at in row.requested
        if at and (who.casefold() == (login or "").casefold() or who.startswith("team:"))
    ]
    return max(asked) if asked else row.created


def wait(row: PrRow, login: str, now: datetime | None = None) -> tuple[str, str]:
    """(compact age such as 3h, 2d or 3w, its style: dim, then wait past WARN_DAYS, bad past LATE_DAYS)."""
    return since(waiting_since(row, login), now)


def since(stamp: str, now: datetime | None = None) -> tuple[str, str]:
    """How long ago an ISO time was, compact, with its style: dim, wait past WARN_DAYS, bad past LATE_DAYS."""
    try:
        days = ((now or datetime.now(UTC)) - datetime.fromisoformat(stamp)).total_seconds() / 86400
    except (TypeError, ValueError):
        return "", "dim"
    return age(stamp, now), "bad" if days > LATE_DAYS else "wait" if days > WARN_DAYS else "dim"


def order(
    rows: Iterable[PrRow], flags: Mapping[str, str], *, login: str = "", oldest_wait: bool = False
) -> list[PrRow]:
    """Flagged rows first; then the longest waiting first (To Review) or the latest update first."""
    if oldest_wait:
        return sorted(rows, key=lambda row: (not flags.get(row.key), waiting_since(row, login) or ""))
    by_update = sorted(rows, key=lambda row: row.updated, reverse=True)
    return sorted(by_update, key=lambda row: not flags.get(row.key))
