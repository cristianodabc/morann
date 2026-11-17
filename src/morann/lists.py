# SPDX-FileCopyrightText: 2026 Cristiano Carvalho
# SPDX-License-Identifier: Apache-2.0
"""The lists beyond what the forge returns: the scope kinds, the author filter and the repository groups."""

from __future__ import annotations

from collections.abc import Callable, Collection, Iterable, Mapping
from dataclasses import dataclass
from typing import ClassVar

from morann.models import PrRow

# A scope kind says whose pull requests the lists show: mine (the configured owners or repositories), org:<name> (one
# organization the user belongs to) or personal (the user's own account, which the app only watches).

AUTHORS = ("all", "me", "others", "bots")

LIST_TABS = {"mine": "Mine", "pending": "Pending", "review": "To Review", "all": "All"}  # in order; 1 to 4 open them


@dataclass(frozen=True)
class Pending:
    """A review in progress on one pull request: drafts kept here, a review started on the forge, or both."""

    row: PrRow
    drafts: int  # local drafts plus the comments of the review waiting on the forge
    last: str  # ISO time of the newest of them, "" when unknown


def pending_rows(
    rows: Iterable[PrRow], local: Mapping[str, tuple[int, str]], make: Callable[[str], PrRow]
) -> list[Pending]:
    """The pull requests with a review in progress, the one waiting longest first: every row on hand that has local
    drafts (`local` is DraftStore.waiting) or a pending review on the forge, and a row made by `make(key)` for drafts
    on a pull request no list holds."""
    known = {row.key: row for row in rows}
    keys = [key for key, row in known.items() if key in local or row.pending]
    keys += [key for key in local if key not in known]
    found = []
    for key in keys:
        row = known.get(key) or make(key)
        count, kept = local.get(key, (0, ""))
        forge_count, forge_at = row.pending or (0, "")
        found.append(Pending(row, count + forge_count, max(kept, forge_at)))
    return sorted(found, key=lambda item: item.last)


def scope_label(kind: str) -> str:
    """What the top bar shows for a scope kind: Mine, Personal, or the one organization's name."""
    return {"mine": "Mine", "personal": "Personal"}.get(kind, kind.removeprefix("org:"))


def by_author(rows: Iterable[PrRow], who: str, viewer: str) -> list[PrRow]:
    """Rows opened by: all, me, others (people but not me) or bots (apps such as dependabot)."""
    if who == "me":
        return [row for row in rows if row.author.casefold() == viewer.casefold()]
    if who == "bots":
        return [row for row in rows if row.bot or row.author.endswith("[bot]")]
    if who == "others":
        return [
            row
            for row in rows
            if row.author.casefold() != viewer.casefold() and not row.bot and not row.author.endswith("[bot]")
        ]
    return list(rows)


@dataclass
class GroupRow:
    """A repository's header in the grouped list: its name and open count; enter, h or l fold it."""

    repo: str
    count: int
    collapsed: bool = False
    flagged: int = 0  # its pull requests with an attention flag
    selectable: ClassVar[bool] = True

    @property
    def key(self) -> str:
        return f"group:{self.repo}"


def group_rows(
    rows: Iterable[PrRow],
    collapsed: Collection[str] = (),
    order: Callable[[list[PrRow]], list[PrRow]] | None = None,
    flags: Mapping[str, str] | None = None,
) -> list[GroupRow | PrRow]:
    """Pull requests under one header per repository: repositories by their latest update, newest first, and pull
    requests inside by `order` (a function of the members), else by latest update. A collapsed repository shows only
    its header; each header counts its pull requests with an attention flag in `flags`."""
    flags = flags or {}
    order = order or (lambda members: sorted(members, key=lambda row: row.updated, reverse=True))
    groups: dict[str, list[PrRow]] = {}
    for row in rows:
        groups.setdefault(row.repo, []).append(row)
    ordered = sorted(groups.items(), key=lambda item: max(row.updated for row in item[1]), reverse=True)
    out: list[GroupRow | PrRow] = []
    for repo, members in ordered:
        folded = repo in collapsed
        out.append(GroupRow(repo, len(members), folded, sum(1 for row in members if flags.get(row.key))))
        if not folded:
            out.extend(order(members))
    return out


def personal_repo(repo: str, viewer: str) -> bool:
    """Whether a repository belongs to the user's own account, where Morann only watches."""
    return bool(viewer) and repo.split("/", 1)[0].casefold() == viewer.casefold()
