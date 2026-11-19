# SPDX-FileCopyrightText: 2026 Cristiano Carvalho
# SPDX-License-Identifier: Apache-2.0
"""What Morann knows about pull requests and repositories, whichever forge they come from.

A forge provider fills these and nothing else reaches the rest of the program. The words in the state fields
(APPROVED, CHANGES_REQUESTED, MERGEABLE, BEHIND and so on) are the vocabulary of these models: a provider maps its
forge's own states onto them. A pull request and its state keep the provider that built them, `forge`, for links,
wording and capabilities; writes never go through it, they go through the forge handed to the function that posts."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from functools import cached_property
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from morann.forge import Forge

MERGE_METHODS = (
    "squash",
    "merge",
    "rebase",
)  # the order the merge methods are offered in, and the default when allowed


@dataclass(frozen=True)
class Scope:
    """The owners or the repositories whose pull requests are listed. Repositories win when both are given."""

    owners: tuple[str, ...] = ()
    repos: tuple[str, ...] = ()

    def label(self) -> str:
        """The owners or repositories this scope lists, for a line like `5 open in acme, beta`."""
        return ", ".join(self.repos or self.owners)

    def several_owners(self) -> bool:
        owners = {repo.split("/")[0].casefold() for repo in self.repos} or {owner.casefold() for owner in self.owners}
        return len(owners) > 1


@dataclass(frozen=True)
class Reviewer:
    login: str
    state: str  # the latest review: APPROVED, CHANGES_REQUESTED, COMMENTED or DISMISSED
    commit: str  # the head that review was written against


def rerequest_candidates(
    reviews: tuple[Reviewer, ...], asked: tuple[str, ...], author: str, head: str | None = None
) -> list[tuple[str, bool, str]]:
    """[(login, chosen, why)]: everyone who reviewed and is not asked now, the author aside. Chosen by default: those
    whose latest review requested changes or commented, so not an approval since the last push."""
    why = {
        "CHANGES_REQUESTED": "requested changes",
        "COMMENTED": "commented",
        "APPROVED": "approved",
        "DISMISSED": "review dismissed",
    }
    out = []
    for review in reviews:
        if review.login.casefold() == author.casefold() or review.login in asked:
            continue
        stale = " before the last push" if head and review.commit and review.commit != head else ""
        out.append(
            (
                review.login,
                review.state in ("CHANGES_REQUESTED", "COMMENTED"),
                why.get(review.state, review.state.lower()) + stale,
            )
        )
    return out


@dataclass
class PrRow:
    """A pull request as the lists show it, from the list query alone."""

    repo: str
    number: int
    title: str
    url: str
    author: str
    draft: bool
    decision: str  # APPROVED, CHANGES_REQUESTED, REVIEW_REQUIRED or ""
    checks: str  # SUCCESS, FAILURE, ERROR, PENDING, EXPECTED or ""
    created: str
    updated: str
    head_ref: str = ""
    base_ref: str = ""
    head: str = ""
    additions: int = 0
    deletions: int = 0
    files: int = 0
    mergeable: str = ""  # MERGEABLE, CONFLICTING or UNKNOWN
    merge_state: str = ""  # BEHIND, DIRTY, CLEAN, BLOCKED and so on
    body: str = ""
    labels: tuple[str, ...] = ()
    reviewers: tuple[Reviewer, ...] = ()
    asked: tuple[str, ...] = ()  # users and teams asked for a review now
    check_counts: tuple[tuple[str, int], ...] = ()  # (("passed", n), ("failed", n), ...)
    bot: bool = False  # opened by an app such as dependabot
    activity: int = 0  # comments and reviews so far, to tell new activity since it was last opened
    requested: tuple[tuple[str, str], ...] = ()  # (login, or team:slug, when) of each recent review request
    pending: tuple[int, str] | None = (
        None  # (comments, last change) of the viewer's review started on the forge, not submitted
    )

    @property
    def key(self) -> str:
        return f"{self.repo}#{self.number}"


@dataclass
class Lists:
    """The viewer's open pull requests and the ones that request their review."""

    viewer: str
    mine: list[PrRow]
    review: list[PrRow]
    totals: dict[str, int]


@dataclass
class Page:
    """One page of a scope's open pull requests."""

    rows: list[PrRow]
    total: int
    cursor: str | None  # where the next page starts, or None when this was the last


@dataclass
class DiffLine:
    kind: str  # hunk, add, del, ctx or note ("\ No newline at end of file")
    text: str
    old: int | None = None
    new: int | None = None

    def anchor(self) -> tuple[str, int | None] | None:
        """(side, line) a comment on this line takes: the new file's line for added and context lines, the old
        file's line for removed lines. None for a line that takes no comment."""
        if self.kind in ("add", "ctx"):
            return ("RIGHT", self.new)
        if self.kind == "del":
            return ("LEFT", self.old)
        return None


@dataclass
class File:
    path: str
    status: str  # added, removed, modified, renamed, copied, changed or unchanged
    additions: int
    deletions: int
    previous: str | None = None
    patch: str | None = None
    lines: list[DiffLine] = field(default_factory=list)
    sha: str = ""  # the blob the forge shows; a viewed mark holds while it stays the same

    @cached_property
    def number_width(self) -> int:
        """Digits of the biggest line number in the diff, read once: every row of the file asks."""
        return len(str(max([line.old or 0 for line in self.lines] + [line.new or 0 for line in self.lines] + [1])))

    def find(self, side: str, line: int | None) -> int | None:
        """The index of the diff line that (side, line) points at, or None."""
        for index, row in enumerate(self.lines):
            if side == "RIGHT" and row.kind in ("add", "ctx") and row.new == line:
                return index
            if side == "LEFT" and row.kind in ("del", "ctx") and row.old == line:
                return index
        return None

    def why_no_diff(self, forge: str) -> str | None:
        """Why a file has no lines to show, or None when it has some. `forge` is the forge's name, for the wording."""
        if self.lines:
            return None
        if self.status == "renamed" and not self.additions and not self.deletions:
            return f"renamed from {self.previous}, no changes"
        if self.additions or self.deletions:
            return f"diff too large for {forge}'s API; open the pull request in the browser (o)"
        return "binary or empty file, no diff"


@dataclass
class TreeNode:
    name: str  # what the row shows: a file name, or a folder chain such as apps/shop/lib
    path: str  # the folder's or the file's full path
    index: int | None = None  # the file's place in the pull request, None for a folder
    children: list[TreeNode] = field(default_factory=list)


@dataclass(frozen=True)
class PendingReview:
    """The viewer's own review on the forge that is not submitted yet. Only its author can see it. Morann resumes it:
    new comments and replies join it, and the viewer's submit sends it with the chosen verdict."""

    id: str  # the forge's id for the review, what the calls that add to it and submit it name
    comments: int = 0  # the comments already in it
    body: str = ""  # the summary already on it
    commit: str = ""  # the head it was started at
    updated: str = ""  # when it last changed, ISO time


@dataclass
class Comment:
    id: int  # the id a reply names
    author: str
    body: str
    created: str
    pending: bool = False  # part of a review the viewer has not submitted on the forge yet
    edited: bool = False  # changed since it was posted


@dataclass
class Thread:
    id: str  # the id resolve and unresolve take
    path: str
    line: int | None
    original_line: int | None
    side: str
    resolved: bool
    outdated: bool
    comments: list[Comment]
    hunk: str = ""  # the diff the first comment was left on, ending at its line; "" when the forge gave none

    @property
    def root(self) -> Comment | None:
        return self.comments[0] if self.comments else None


@dataclass
class Note:
    """A conversation comment or a review summary."""

    author: str
    body: str
    at: str
    state: str = ""  # a review's state: APPROVED, CHANGES_REQUESTED, COMMENTED, DISMISSED or PENDING
    id: int = 0  # for a link to it, and to edit or delete it
    edited: bool = False  # changed since it was posted


@dataclass
class Commit:
    sha: str
    headline: str
    author: str
    date: str


@dataclass
class Check:
    name: str
    state: str  # pass, fail, pending, skip or cancelled
    raw: str  # the forge's own conclusion or state, such as TIMED_OUT
    required: bool
    workflow: str = ""
    description: str = ""
    run_id: int | None = None  # a check run's id, for its page on the forge
    title: str = ""  # a check run's output title, such as "2 tests failed"
    url: str = ""  # its details link from the API, opened only when the forge owns it


def order_checks(checks: Iterable[Check]) -> list[Check]:
    """Checks in the order the Checks tab shows them: failing first, then running, cancelled, passed and skipped,
    the required ones first in each group."""
    order = {"fail": 0, "pending": 1, "cancelled": 2, "pass": 3, "skip": 4}
    return sorted(checks, key=lambda check: (order[check.state], not check.required, check.name))


@dataclass
class PullRequest:
    """One pull request with everything its tabs show, read at one head commit."""

    forge: Forge  # the provider that built it: its links, its name and what it can do
    repo: str
    number: int
    title: str
    body: str
    url: str
    author: str
    draft: bool
    state: str
    base: str
    head_ref: str
    head: str  # the head commit the files were read at
    viewer: str
    files: list[File]
    threads: list[Thread]
    notes: list[Note]
    truncated: list[str] = field(default_factory=list)
    commits: list[Commit] = field(default_factory=list)
    commit_total: int = 0
    checks: list[Check] = field(default_factory=list)
    reviewers: tuple[Reviewer, ...] = ()  # the latest review of each person
    asked: tuple[str, ...] = ()  # logins asked for a review now
    created: str = ""
    mergeable: str = ""  # MERGEABLE, CONFLICTING or UNKNOWN
    merge_state: str = ""  # CLEAN, BEHIND, BLOCKED, DIRTY, UNSTABLE, DRAFT and so on
    review_decision: str = ""  # APPROVED, CHANGES_REQUESTED, REVIEW_REQUIRED or ""
    stale: bool = False  # read from the disk cache; a fresh read is on its way
    files_loading: bool = False  # the conversation, commits and checks are in; the files are still on their way
    fetched: str = ""  # when the forge was read, ISO time
    edited: bool = False  # the description changed since it was posted
    pending: PendingReview | None = None  # the viewer's unsubmitted review, which a submit resumes

    @property
    def key(self) -> str:
        return f"{self.repo}#{self.number}"

    def rerequest_due(self) -> bool:
        """Whether someone who requested changes or commented has not seen the latest push: time to ask them again."""
        return (
            bool(self.viewer)
            and self.author.casefold() == self.viewer.casefold()
            and any(
                r.state in ("CHANGES_REQUESTED", "COMMENTED")
                and r.commit
                and r.commit != self.head
                and r.login not in self.asked
                for r in self.reviewers
            )
        )

    def file(self, path: str) -> File | None:
        return next((item for item in self.files if item.path == path), None)

    def thread(self, thread_id: str) -> Thread | None:
        return next((item for item in self.threads if item.id == thread_id), None)


@dataclass(frozen=True)
class PrState:
    """What the forge says about a pull request right now: what the actions are decided on."""

    forge: Forge  # the provider that read it: its name and what it can do
    repo: str
    number: int
    id: str
    state: str  # OPEN, CLOSED or MERGED
    draft: bool
    head: str
    base: str
    author: str
    viewer: str
    mergeable: str  # MERGEABLE, CONFLICTING or UNKNOWN
    merge_state: str  # CLEAN, BEHIND, BLOCKED, DIRTY, DRAFT, HAS_HOOKS, UNKNOWN or UNSTABLE
    review_decision: str
    auto_merge: bool
    methods: tuple[str, ...]  # the merge methods the repository allows: merge, squash, rebase
    auto_merge_allowed: bool
    checks: str  # the head's rollup: SUCCESS, FAILURE, ERROR, PENDING, EXPECTED or ""
    reviewers: tuple[Reviewer, ...] = ()
    asked: tuple[str, ...] = ()  # logins asked for a review now
    stacked_on: int | None = None  # the open pull request whose branch is this one's base

    def candidates(self) -> list[tuple[str, bool, str]]:
        return rerequest_candidates(self.reviewers, self.asked, self.author, self.head)

    @property
    def own(self) -> bool:
        return bool(self.viewer) and self.author.casefold() == self.viewer.casefold()

    @property
    def auto_method(self) -> str:
        """The method auto-merge uses: the first the repository allows of squash, merge, rebase."""
        return next((method for method in MERGE_METHODS if method in self.methods), "merge")


# A file at a commit, read to show the unchanged lines between a diff's hunks.


@dataclass(frozen=True)
class FileContent:
    """A file at a ref. `text` is None for a binary file and for one the forge would not send whole."""

    repo: str
    path: str
    ref: str
    text: str | None
    size: int = 0
    sha: str = ""
    binary: bool = False
    truncated: bool = False  # too large for the forge to send; `url` still opens it
    url: str = ""
