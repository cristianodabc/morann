# SPDX-FileCopyrightText: 2026 Cristiano Carvalho
# SPDX-License-Identifier: Apache-2.0
"""GitHub's answers turned into Morann's models: list rows, one pull request, its state for the actions."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from morann.diffs import parse_patch
from morann.forge import ForgeError
from morann.models import (
    Check,
    Comment,
    Commit,
    File,
    Note,
    PendingReview,
    PrRow,
    PrState,
    PullRequest,
    Reviewer,
    Thread,
    order_checks,
)

if TYPE_CHECKING:
    from morann.forge import Forge, Snapshot

Node = dict[str, Any]  # one JSON object of a GraphQL or REST answer


def login(node: Node | None) -> str:
    return ((node or {}).get("author") or {}).get("login") or "ghost"


def parse_reviewers(node: Node) -> tuple[tuple[Reviewer, ...], tuple[str, ...], tuple[str, ...]]:
    """(the latest review of each person, the people asked for a review now, the teams asked)."""
    reviews = tuple(
        Reviewer(login=login(r), state=r.get("state") or "", commit=((r.get("commit") or {}).get("oid")) or "")
        for r in (node.get("latestReviews") or {}).get("nodes") or []
        if ((r.get("author") or {}).get("__typename") or "User") == "User" and not login(r).endswith("[bot]")
    )
    asked = [(r.get("requestedReviewer") or {}) for r in (node.get("reviewRequests") or {}).get("nodes") or []]
    users = tuple(a["login"] for a in asked if a.get("__typename") == "User" and a.get("login"))
    teams = tuple(a["slug"] for a in asked if a.get("__typename") == "Team" and a.get("slug"))
    return reviews, users, teams


# The lists.


def parse_rows(nodes: list[Node] | None) -> list[PrRow]:
    rows = []
    for node in nodes or []:
        if not node or "number" not in node:
            continue
        commits = (node.get("commits") or {}).get("nodes") or [{}]
        rollup = ((commits[0] or {}).get("commit") or {}).get("statusCheckRollup") or {}
        reviewers, users, teams = parse_reviewers(node)
        rows.append(
            PrRow(
                repo=node["repository"]["nameWithOwner"],
                number=int(node["number"]),
                title=node.get("title") or "",
                url=node.get("url") or "",
                author=(node.get("author") or {}).get("login") or "ghost",
                draft=bool(node.get("isDraft")),
                decision=node.get("reviewDecision") or "",
                checks=rollup.get("state") or "",
                created=node.get("createdAt") or "",
                updated=node.get("updatedAt") or "",
                head_ref=node.get("headRefName") or "",
                base_ref=node.get("baseRefName") or "",
                head=node.get("headRefOid") or "",
                additions=int(node.get("additions") or 0),
                deletions=int(node.get("deletions") or 0),
                files=int(node.get("changedFiles") or 0),
                mergeable=node.get("mergeable") or "",
                merge_state=node.get("mergeStateStatus") or "",
                body=node.get("bodyText") or "",
                labels=tuple(
                    label["name"]
                    for label in (node.get("labels") or {}).get("nodes") or []
                    if label and label.get("name")
                ),
                reviewers=reviewers,
                asked=users + tuple(f"{t} (team)" for t in teams),
                check_counts=count_checks(rollup.get("contexts") or {}),
                bot=(node.get("author") or {}).get("__typename") == "Bot",
                activity=sum(int((node.get(name) or {}).get("totalCount") or 0) for name in ("comments", "reviews")),
                requested=review_requests(node),
                pending=pending_review(node),
            )
        )
    return rows


def pending_review(node: Node) -> tuple[int, str] | None:
    """(comments, updated) of the viewer's pending review, which only its author can see, or None without one."""
    reviews = (node.get("pending") or {}).get("nodes") or []
    if not reviews or not reviews[0]:
        return None
    review = reviews[0]
    return int((review.get("comments") or {}).get("totalCount") or 0), review.get("updatedAt") or ""


def resumable(node: Node, viewer: str) -> PendingReview | None:
    """The viewer's own pending review of a pull request node, or None. GitHub shows a pending review only to its
    author; one that is not the viewer's is ignored all the same, so it is never resumed."""
    for review in (node.get("pendingReviews") or {}).get("nodes") or []:
        if viewer and review and review.get("id") and login(review).casefold() == viewer.casefold():
            return PendingReview(
                id=review["id"],
                comments=int((review.get("comments") or {}).get("totalCount") or 0),
                body=review.get("body") or "",
                commit=(review.get("commit") or {}).get("oid") or "",
                updated=review.get("updatedAt") or "",
            )
    return None


def review_requests(node: Node) -> tuple[tuple[str, str], ...]:
    """(login or team:slug, when) for each review request event on the row, oldest first."""
    out = []
    for event in (node.get("timelineItems") or {}).get("nodes") or []:
        who = (event or {}).get("requestedReviewer") or {}
        name = who.get("login") or (f"team:{who['slug']}" if who.get("slug") else "")
        if name and event.get("createdAt"):
            out.append((name, event["createdAt"]))
    return tuple(out)


RUN_COUNTS = {
    "SUCCESS": "passed",
    "FAILURE": "failed",
    "TIMED_OUT": "failed",
    "STARTUP_FAILURE": "failed",
    "ACTION_REQUIRED": "failed",
    "CANCELLED": "cancelled",
    "SKIPPED": "skipped",
    "NEUTRAL": "skipped",
    "STALE": "skipped",
    "QUEUED": "running",
    "IN_PROGRESS": "running",
    "PENDING": "running",
    "WAITING": "running",
    "REQUESTED": "running",
}

STATUS_COUNTS = {
    "SUCCESS": "passed",
    "FAILURE": "failed",
    "ERROR": "failed",
    "PENDING": "running",
    "EXPECTED": "running",
}


def count_checks(contexts: Node) -> tuple[tuple[str, int], ...]:
    """((kind, count), ...) in a fixed order: passed, failed, running, cancelled, skipped; zero counts left out."""
    totals: dict[str, int] = {}
    for key, names in (("checkRunCountsByState", RUN_COUNTS), ("statusContextCountsByState", STATUS_COUNTS)):
        for item in contexts.get(key) or []:
            kind = names.get(item.get("state"))
            if kind and item.get("count"):
                totals[kind] = totals.get(kind, 0) + int(item["count"])
    return tuple(
        (kind, totals[kind]) for kind in ("passed", "failed", "running", "cancelled", "skipped") if kind in totals
    )


# One pull request.


def parse_file(item: Node) -> File:
    patch = item.get("patch")
    return File(
        path=item["filename"],
        status=item.get("status") or "modified",
        additions=int(item.get("additions") or 0),
        deletions=int(item.get("deletions") or 0),
        previous=item.get("previous_filename"),
        patch=patch,
        lines=parse_patch(patch) if patch else [],
        sha=item.get("sha") or "",
    )


FAILING = ("FAILURE", "TIMED_OUT", "STARTUP_FAILURE", "ACTION_REQUIRED", "ERROR")


def parse_check(node: Node) -> Check:
    """A check run or a commit status, with its state folded to pass, fail, pending, skip or cancelled."""
    if node.get("__typename") == "CheckRun":
        raw = node.get("conclusion") or node.get("status") or ""
        if node.get("status") != "COMPLETED":
            state = "pending"
        else:
            state = {
                "SUCCESS": "pass",
                "NEUTRAL": "skip",
                "SKIPPED": "skip",
                "STALE": "skip",
                "CANCELLED": "cancelled",
            }.get(raw, "fail" if raw in FAILING else "pending")
        workflow = ((((node.get("checkSuite") or {}).get("workflowRun") or {}).get("workflow")) or {}).get("name") or ""
        run_id = node.get("databaseId")
        return Check(
            name=node.get("name") or "?",
            state=state,
            raw=raw,
            required=bool(node.get("isRequired")),
            workflow=workflow,
            run_id=int(run_id) if isinstance(run_id, int) else None,
            title=node.get("title") or "",
            url=node.get("detailsUrl") or "",
        )
    raw = node.get("state") or ""
    return Check(
        name=node.get("context") or "?",
        state={"SUCCESS": "pass", "FAILURE": "fail", "ERROR": "fail"}.get(raw, "pending"),
        raw=raw,
        required=bool(node.get("isRequired")),
        description=node.get("description") or "",
        url=node.get("targetUrl") or "",
    )


def parse_threads(nodes: list[Node] | None) -> list[Thread]:
    threads = []
    for node in nodes or []:
        comments = [
            Comment(
                id=int(c["databaseId"]),
                author=login(c),
                body=c.get("body") or "",
                created=c.get("createdAt") or "",
                pending=c.get("state") == "PENDING",
                edited=bool(c.get("lastEditedAt")),
            )
            for c in (node.get("comments") or {}).get("nodes") or []
            if c.get("databaseId") is not None
        ]
        first = ((node.get("hunk") or {}).get("nodes") or [None])[0] or {}
        threads.append(
            Thread(
                id=node["id"],
                path=node.get("path") or "",
                line=node.get("line"),
                original_line=node.get("originalLine"),
                side=node.get("diffSide") or "RIGHT",
                resolved=bool(node.get("isResolved")),
                outdated=bool(node.get("isOutdated")),
                comments=comments,
                hunk=first.get("diffHunk") or "",
            )
        )
    return threads


def build_pr(forge: Forge, repo: str, number: int, raw: Snapshot, stale: bool = False) -> PullRequest:
    """A PullRequest out of GitHub's answers, fresh or from the cache. Files None means they are on their way."""
    data, files = raw.get("data"), raw.get("files")
    if not isinstance(data, dict):
        raise ForgeError(f"{repo}#{number}: this is not a snapshot of a GitHub pull request")
    node = (data.get("repository") or {}).get("pullRequest")
    if not node:
        raise ForgeError(f"{repo}#{number} not found, or this login cannot read it")
    truncated = [
        what
        for what, part in (
            ("threads", node.get("reviewThreads")),
            ("comments", node.get("comments")),
            ("reviews", node.get("reviews")),
        )
        if ((part or {}).get("pageInfo") or {}).get("hasNextPage")
    ]
    notes = [
        Note(
            author=login(c),
            body=c.get("body") or "",
            at=c.get("createdAt") or "",
            id=int(c.get("databaseId") or 0),
            edited=bool(c.get("lastEditedAt")),
        )
        for c in (node.get("comments") or {}).get("nodes") or []
    ]
    notes += [
        Note(
            author=login(r),
            body=r.get("body") or "",
            at=r.get("submittedAt") or "",
            state=r.get("state") or "",
            id=int(r.get("databaseId") or 0),
            edited=bool(r.get("lastEditedAt")),
        )
        for r in (node.get("reviews") or {}).get("nodes") or []
    ]
    notes.sort(key=lambda note: note.at)
    commits = [
        Commit(
            sha=c["oid"],
            headline=c.get("messageHeadline") or "",
            date=c.get("committedDate") or "",
            author=((c.get("author") or {}).get("user") or {}).get("login")
            or (c.get("author") or {}).get("name")
            or "?",
        )
        for c in (((n or {}).get("commit") or {}) for n in (node.get("commits") or {}).get("nodes") or [])
        if c.get("oid")
    ]
    head_nodes = (node.get("headCommit") or {}).get("nodes") or [{}]
    rollup = ((head_nodes[0] or {}).get("commit") or {}).get("statusCheckRollup") or {}
    contexts = (rollup.get("contexts") or {}).get("nodes")
    checks = order_checks(parse_check(c) for c in contexts or [] if c)
    reviewers, asked, _teams = parse_reviewers(node)
    return PullRequest(
        forge=forge,
        repo=repo,
        number=int(number),
        title=node.get("title") or "",
        body=node.get("body") or "",
        edited=bool(node.get("lastEditedAt")),
        url=node.get("url") or "",
        author=login(node),
        draft=bool(node.get("isDraft")),
        state=node.get("state") or "",
        base=node.get("baseRefName") or "",
        head_ref=node.get("headRefName") or "",
        head=node["headRefOid"],
        viewer=(data.get("viewer") or {}).get("login") or "",
        files=[parse_file(item) for item in files or []],
        threads=parse_threads((node.get("reviewThreads") or {}).get("nodes")),
        notes=notes,
        truncated=truncated,
        commits=commits,
        commit_total=int((node.get("commits") or {}).get("totalCount") or len(commits)),
        checks=checks,
        reviewers=reviewers,
        asked=asked,
        stale=stale,
        files_loading=files is None,
        created=node.get("createdAt") or "",
        mergeable=node.get("mergeable") or "",
        merge_state=node.get("mergeStateStatus") or "",
        review_decision=node.get("reviewDecision") or "",
        fetched=raw.get("fetched") or "",
        pending=resumable(node, (data.get("viewer") or {}).get("login") or ""),
    )


# Its state, for the actions.


def parse_state(forge: Forge, repo: str, number: int, data: Node) -> PrState:
    repository = data.get("repository") or {}
    node = repository.get("pullRequest")
    if not node:
        raise ForgeError(f"{repo}#{number} not found, or this login cannot read it")
    head_nodes = (node.get("headCommit") or {}).get("nodes") or [{}]
    rollup = (((head_nodes[0] or {}).get("commit") or {}).get("statusCheckRollup") or {}).get("state") or ""
    reviewers, asked, _teams = parse_reviewers(node)
    below = (((node.get("baseRef") or {}).get("associatedPullRequests") or {}).get("nodes") or [None])[0] or {}
    methods = tuple(
        method
        for method, key in (
            ("merge", "mergeCommitAllowed"),
            ("squash", "squashMergeAllowed"),
            ("rebase", "rebaseMergeAllowed"),
        )
        if repository.get(key)
    )
    return PrState(
        forge=forge,
        repo=repo,
        number=int(number),
        id=node.get("id") or "",
        state=node.get("state") or "",
        draft=bool(node.get("isDraft")),
        head=node.get("headRefOid") or "",
        base=node.get("baseRefName") or "",
        author=login(node),
        viewer=(data.get("viewer") or {}).get("login") or "",
        mergeable=node.get("mergeable") or "UNKNOWN",
        merge_state=node.get("mergeStateStatus") or "UNKNOWN",
        review_decision=node.get("reviewDecision") or "",
        auto_merge=bool(node.get("autoMergeRequest")),
        methods=methods,
        auto_merge_allowed=bool(repository.get("autoMergeAllowed")),
        checks=rollup,
        reviewers=reviewers,
        asked=asked,
        stacked_on=below.get("number"),
    )
