# SPDX-FileCopyrightText: 2026 Cristiano Carvalho
# SPDX-License-Identifier: Apache-2.0
"""What the panes show, as rows of (text, style) pairs: list rows, the diff with its threads and drafts, the conversation, commits and checks."""

from __future__ import annotations

from collections.abc import Collection, Iterable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import datetime
from typing import TYPE_CHECKING, Any, TypedDict

from morann import inline, markdown
from morann.diffs import HUNK, parse_patch
from morann.drafts import moved
from morann.models import PrRow
from morann.textfmt import (
    ASCII,
    CHIP_STYLE,
    Line,
    Piece,
    age,
    ago,
    clean,
    cut,
    hard_wrap,
    plain,
    width_of,
    word_wrap,
)

if TYPE_CHECKING:
    from morann.drafts import Drafts
    from morann.models import Comment, PullRequest, Thread

MERGE_CHIP = {"BEHIND": ("behind", "wait"), "DIRTY": ("conflict", "bad")}


class Columns(TypedDict):
    """The width of each column of the list, in cells; 0 leaves a column out."""

    repo: int
    flag: int
    number: int
    slots: list[int]  # one per chip of row_chips
    author: int
    title: int


def row_chips(row: PrRow, drafts: int = 0, icons: Mapping[str, str] = ASCII) -> list[Piece | None]:
    """A row's chips, each (text, style) in its own column: draft, review decision, checks, behind or conflict, drafts."""
    merge = MERGE_CHIP.get(row.merge_state) or (("conflict", "bad") if row.mergeable == "CONFLICTING" else None)
    return [
        (icons["draft"], CHIP_STYLE["draft"]) if row.draft else None,
        (icons[row.decision], CHIP_STYLE[row.decision]) if row.decision in icons else None,
        (icons[row.checks], CHIP_STYLE[row.checks]) if row.checks in icons else None,
        merge,
        (f"{icons['local']}{drafts}", CHIP_STYLE["local"]) if drafts else None,
    ]


def list_columns(
    rows: Iterable[object],
    width: int,
    *,
    counts: Mapping[str, int] | None = None,
    show_owner: bool = False,
    icons: Mapping[str, str] = ASCII,
    show_author: bool = False,
    show_repo: bool = True,
    flags: Mapping[str, str] | None = None,
) -> Columns:
    """Column widths shared by every row, so the columns line up: repository, attention flag (when any row has one),
    number, each chip, initials and age; the title takes what is left, or nothing when under 10 columns remain."""
    counts, flags = counts or {}, flags or {}
    listed = [row for row in rows if isinstance(row, PrRow)]
    names = [row.repo if show_owner else row.repo.split("/", 1)[1] for row in listed]
    repo = min(max([width_of(name) for name in names] + [0]), 18 if width < 90 else 28) if show_repo else 0
    number = max([len(str(row.number)) + 1 for row in listed] + [2])
    marks = [width_of(icons[f"flag:{flags[row.key]}"]) for row in listed if flags.get(row.key)]
    flag = max(marks) + 1 if marks else 0
    slots = [0] * 5
    for row in listed:
        for index, chip in enumerate(row_chips(row, counts.get(row.key, 0), icons)):
            if chip:
                slots[index] = max(slots[index], width_of(chip[0]) + 2)
    author = (
        min(max([width_of(row.author) for row in listed] + [2]), 14) + 2 if show_author else 4
    )  # " login " or " AB "
    used = (
        (repo + 1 if repo else 0) + flag + number + 1 + sum(slot + 1 for slot in slots if slot) + author + 4
    )  # " 2d "
    return {
        "repo": repo,
        "flag": flag,
        "number": number,
        "slots": slots,
        "author": author if show_author else 0,
        "title": width - used if width - used >= 10 else 0,
    }


def list_row_lines(
    row: PrRow,
    width: int,
    *,
    drafts: int = 0,
    show_owner: bool = False,
    icons: Mapping[str, str] = ASCII,
    now: datetime | None = None,
    columns: Columns | None = None,
    flag: str = "",
    wait: tuple[str, str] | None = None,
) -> list[Line]:
    """A pull request in the list, number first on one line: repository, its attention flag, #number, chips in fixed
    columns, author initials, age (or, given `wait` as (text, style), how long your review was waited for), then the
    title when there is room. Each line is a list of (text, style) pairs; a chip's style starts with "chip-", a flag's
    with "flag-"."""
    columns = columns or list_columns(
        [row],
        width,
        counts={row.key: drafts},
        show_owner=show_owner,
        icons=icons,
        flags={row.key: flag} if flag else None,
    )
    name = row.repo if show_owner else row.repo.split("/", 1)[1]
    line: Line = (
        [(cut(name, columns["repo"], icons["ellipsis"]).ljust(columns["repo"]) + " ", "dim")] if columns["repo"] else []
    )
    if columns.get("flag"):
        mark = icons[f"flag:{flag}"] if flag else ""
        line.append((mark + " " * (columns["flag"] - width_of(mark)), f"flag-{flag}" if flag else ""))
    line.append((f"#{row.number}".rjust(columns["number"]) + " ", "label"))
    for chip, slot in zip(row_chips(row, drafts, icons), columns["slots"]):
        if not slot:
            continue
        if chip:
            text = f" {chip[0]} "
            line += [(text, f"chip-{chip[1]}"), (" " * (slot - width_of(text) + 1), "")]
        else:
            line.append((" " * (slot + 1), ""))
    if columns.get("author"):  # the wider scopes name the author
        who = cut(row.author, columns["author"] - 2, icons["ellipsis"]).ljust(columns["author"] - 2)
        line += [(f" {who} ", "initials" if not row.bot else "dim")]
    else:
        line += [(f" {initials_of(row.author)} ", "initials")]
    when, tone = wait if wait is not None else (age(row.updated, now), "dim")
    line.append((f"{when:>3} ", tone))
    if columns["title"]:
        line.append((cut(clean(row.title).replace("\n", " "), columns["title"], icons["ellipsis"]), "title"))
    used = sum(width_of(text) for text, _style in line)
    if used > width:  # a pane narrower than the fixed columns: cut from the end
        out, left = [], width
        for text, style in line:
            piece = text if width_of(text) <= left else cut(text, left, "")
            if piece:
                out.append((piece, style))
            left -= width_of(piece)
        line = out
    return [line]


def initials_of(login: str) -> str:
    parts = [part for part in (login or "?").replace("_", "-").replace(".", "-").split("-") if part] or ["?"]
    return (parts[0][0] + (parts[1][0] if len(parts) > 1 else parts[0][1:2] or " ")).upper()


def fit(pieces: Iterable[Piece], width: int, icons: Mapping[str, str] = ASCII) -> Line:
    """(text, style) pieces cut to one line of `width` cells."""
    out: Line = []
    left = width
    for text, style in pieces:
        if left <= 0:
            break
        piece = text if width_of(text) <= left else cut(text, left, icons["ellipsis"])
        out.append((piece, style))
        left -= width_of(piece)
    return out


@dataclass
class ViewRow:
    """One logical row of the diff or conversation pane. It wraps to as many screen lines as the width needs."""

    kind: str  # file, info, hunk, add, del, ctx, note, thread, comment, draft, mark, title, text, heading
    text: str
    number: str = ""  # the line number shown in the gutter
    marker: str = ""  # +, -, space, or | for a thread
    anchor: tuple[str, str, int | None] | None = None  # (path, side, line) a new comment would take
    thread: str | None = None
    draft: str | None = None
    selectable: bool = True
    style: str = ""  # overrides the kind's style, for example dim for a resolved thread
    author: str = ""  # a card's author, shown with initials
    when: str = ""  # a card's age, such as 2d
    body: str = ""  # a card's text as markdown, which the UI renders
    badges: tuple[str, ...] = ()  # short labels such as resolved, outdated, draft, pending
    link: str = ""  # what o opens for this row: a commit or a check
    old: str = ""  # a diff line's number in the old file, for the gutter
    new: str = ""  # a diff line's number in the new file
    marks: tuple[inline.Span, ...] = ()  # the character ranges that changed inside an edited line, in the cleaned text
    counts: tuple[int, ...] = ()  # a file header's (additions, deletions); a gap's (first new line, lines)
    path: str = ""  # an unchanged line shown from the file: its path, for the syntax colors, since it has no anchor
    pair: tuple[ViewRow | None, ViewRow | None] | None = None  # side by side: the old file's line and the new one's
    post: tuple[str, int] | None = None  # a posted comment: its kind (line, conversation, review, description) and id
    mine: bool = False  # the post is the viewer's own: it can be edited or deleted
    raw: str = ""  # a post's markdown as written, which an edit starts from


def is_viewer(login: str, pr: PullRequest) -> bool:
    return bool(pr.viewer) and login.casefold() == pr.viewer.casefold()


def linked(body: str | None, pr: PullRequest) -> str:
    """A comment's markdown with its bare URLs and #123 references as links on the pull request's forge."""
    return markdown.prepare(body or "", pr.repo, pr.forge.pr_url)


def thread_open(thread: Thread, overrides: Mapping[str, bool]) -> bool:
    """Resolved and outdated threads start collapsed, as on the forge; enter flips that."""
    return overrides.get(thread.id, not (thread.resolved or thread.outdated))


def thread_badges(thread: Thread, drafts: Drafts, viewer: str) -> tuple[str, ...]:
    """A thread's state at a glance: resolved or open, outdated, yours (you started it), your turn (open, you are in
    it, and someone else spoke last), and draft when you have an unsent reply or resolve on it."""
    me = viewer.casefold()
    authors = [comment.author.casefold() for comment in thread.comments]
    root = thread.root
    mine = bool(me) and root is not None and root.author.casefold() == me
    turn = bool(me) and not thread.resolved and me in authors and authors[-1] != me
    drafted = any(item["thread"] == thread.id for item in drafts.replies + drafts.resolves)
    flags = (
        ("resolved" if thread.resolved else "open", True),
        ("outdated", thread.outdated),
        ("yours", mine),
        ("your turn", turn),
        ("draft", drafted),
    )
    return tuple(name for name, on in flags if on)


def thread_rows(
    thread: Thread,
    drafts: Drafts,
    overrides: Mapping[str, bool],
    icons: Mapping[str, str],
    now: datetime | None,
    pr: PullRequest,
) -> list[ViewRow]:
    """A review thread's rows: its heading, then its comments when it is open, then the drafts under it."""
    marks = [mark for mark, on in ((icons["resolved"], thread.resolved), (icons["outdated"], thread.outdated)) if on]
    pending = next((r for r in drafts.resolves if r["thread"] == thread.id), None)
    style = "dim" if thread.resolved else ""
    root = thread.root
    badges = thread_badges(thread, drafts, pr.viewer)

    waiting = f"pending on {pr.forge.host}"  # a comment in a review the viewer has not submitted there

    def link(comment: Comment | None) -> str:
        return pr.forge.comment_url(pr.repo, pr.number, comment.id) if comment is not None else ""

    if not thread_open(thread, overrides):
        first = plain(root.body).split("\n")[0] if root else ""
        count = f" ({len(thread.comments)})" if len(thread.comments) > 1 else ""
        rows = [
            ViewRow(
                "thread",
                f"{icons['closed']} {root.author if root else '?'}: {first}{count} {' '.join(marks)}".rstrip(),
                marker="|",
                thread=thread.id,
                style=style,
                author=root.author if root else "",
                when=age(root.created, now) if root else "",
                body=f"{first}{count}",
                badges=badges,
                link=link(root),
            )
        ]
    else:
        rows = [
            ViewRow(
                "thread",
                f"{icons['open']} thread on line {thread.line or thread.original_line} {' '.join(marks)}".rstrip(),
                marker="|",
                thread=thread.id,
                style=style,
                body=f"thread on line {thread.line or thread.original_line}",
                badges=badges,
                link=link(root),
            )
        ]
        for index, comment in enumerate(thread.comments):
            who = f"{'' if index == 0 else '> '}{comment.author} {age(comment.created, now)}"
            who += f" ({waiting})" if comment.pending else ""
            rows.append(
                ViewRow(
                    "comment",
                    f"{who}\n{plain(comment.body)}",
                    marker="|",
                    thread=thread.id,
                    style=style,
                    author=comment.author,
                    when=ago(comment.created, now),
                    body=linked(comment.body, pr),
                    badges=((waiting,) if comment.pending else ()) + (("edited",) if comment.edited else ()),
                    link=link(comment),
                    post=None if comment.pending else ("line", comment.id),
                    mine=is_viewer(comment.author, pr),
                    raw=comment.body,
                )
            )
    for reply in drafts.replies:
        if reply["thread"] == thread.id:
            rows.append(
                ViewRow(
                    "draft",
                    f"[pending reply] {reply['body']}",
                    marker="|",
                    thread=thread.id,
                    draft=reply["id"],
                    body=linked(reply["body"], pr),
                    badges=("pending", "reply"),
                )
            )
    if pending:
        verb = "resolve" if pending["resolve"] else "unresolve"
        rows.append(
            ViewRow(
                "draft",
                f"[will {verb} on submit]",
                marker="|",
                thread=thread.id,
                draft=pending["id"],
                body=f"will {verb} this thread on submit",
                badges=("pending",),
            )
        )
    return rows


def gap_rows(
    path: str, hunk: str, last_old: int, last_new: int, text: Sequence[str] | None, expanded: Collection[int]
) -> list[ViewRow]:
    """The unchanged lines before a hunk: one gap row saying how many, or the lines themselves once expanded."""
    found = HUNK.match(hunk)
    if not found:
        return []
    new_from, old_from = last_new + 1, last_old + 1
    count = int(found[2]) - new_from
    if count <= 0:
        return []
    if text is None or new_from not in expanded:
        word = "line" if count == 1 else "lines"
        return [ViewRow("gap", f"{count} unchanged {word}  enter shows them", style="dim", counts=(new_from, count))]
    rows = []
    for offset in range(count):
        new, old = new_from + offset, old_from + offset
        code = text[new - 1] if new - 1 < len(text) else ""
        rows.append(ViewRow("more", code, number=str(new), marker=" ", path=path, old=str(old), new=str(new)))
    return rows


def visible(thread: Thread, drafts: Drafts, unresolved_only: bool) -> bool:
    if not unresolved_only or not thread.resolved:
        return True
    return any(item["thread"] == thread.id for item in drafts.replies + drafts.resolves)


def file_rows(
    pr: PullRequest,
    index: int,
    drafts: Drafts,
    *,
    overrides: Mapping[str, bool] | None = None,
    unresolved_only: bool = False,
    icons: Mapping[str, str] = ASCII,
    now: datetime | None = None,
    viewed: bool = False,
    text: Sequence[str] | None = None,
    expanded: Collection[int] = (),
) -> list[ViewRow]:
    """The rows of one file: its header, each diff line with the threads and drafts under it, then the threads the forge
    could not place in the current diff (outdated ones) and drafts whose line is no longer in it. The unchanged lines
    between two hunks are one gap row; given the file's `text` at the head, a gap whose first new line is in `expanded`
    shows those lines instead."""
    overrides = overrides or {}
    item = pr.files[index]
    renamed = f" (from {item.previous})" if item.previous and item.previous != item.path else ""
    rows = [
        ViewRow(
            "file",
            f"{item.path}{renamed}  +{item.additions} -{item.deletions}{'  Viewed' if viewed else ''}",
            selectable=False,
            link=pr.forge.file_url(pr.repo, pr.number, item.path),
            body=f"{item.path}{renamed}",
            counts=(item.additions, item.deletions),
            badges=("Viewed",) if viewed else (),
        )
    ]
    why = item.why_no_diff(pr.forge.label)
    if why:
        rows.append(ViewRow("info", why))
    threads = [t for t in pr.threads if t.path == item.path and visible(t, drafts, unresolved_only)]
    # Where the thread's (side, line) lands in this diff; an outdated thread or one whose line left the diff has no place.
    at = {t.id: None if t.outdated or t.line is None else item.find(t.side, t.line) for t in threads}
    mine = [c for c in drafts.comments if c["path"] == item.path]
    edited = inline.marks([(line.kind, clean(line.text)) for line in item.lines])
    last_old = last_new = 0  # the last line numbers the diff showed, where a gap before the next hunk starts
    for position, line in enumerate(item.lines):
        if line.kind == "hunk":
            rows.extend(gap_rows(item.path, line.text, last_old, last_new, text, expanded))
            rows.append(ViewRow("hunk", line.text))
            continue
        last_old, last_new = line.old or last_old, line.new or last_new
        number = line.old if line.kind == "del" else line.new
        side_line = line.anchor()
        rows.append(
            ViewRow(
                line.kind,
                line.text,
                number=str(number) if number else "",
                marker={"add": "+", "del": "-"}.get(line.kind, " "),
                anchor=(item.path, *side_line) if side_line else None,
                link=pr.forge.file_url(pr.repo, pr.number, item.path, *side_line) if side_line else "",
                old=str(line.old or ""),
                new=str(line.new or ""),
                marks=edited.get(position, ()),
            )
        )
        for thread in threads:
            if at[thread.id] == position:
                rows.extend(thread_rows(thread, drafts, overrides, icons, now, pr))
        for c in mine:
            if item.find(c["side"], c["line"]) == position:
                changed = moved(item, c)
                rows.append(
                    ViewRow(
                        "draft",
                        f"[draft{', the code here changed' if changed else ''}] {c['body']}",
                        marker="|",
                        draft=c["id"],
                        anchor=(item.path, *side_line) if side_line else None,
                        style="bad" if changed else "",
                        body=linked(c["body"], pr),
                        badges=("draft", "code changed") if changed else ("draft",),
                    )
                )
    rest = [t for t in threads if at[t.id] is None]
    if rest:
        rows.append(ViewRow("heading", "threads not on a line of this diff (outdated)", selectable=False))
        for thread in rest:
            rows.extend(thread_rows(thread, drafts, overrides, icons, now, pr))
    stale = [c for c in mine if item.find(c["side"], c["line"]) is None]
    if stale:
        rows.append(ViewRow("heading", "drafts whose line is no longer in the diff", selectable=False))
        rows.extend(
            ViewRow(
                "draft",
                f"[draft, line {c['line']}] {c['body']}",
                marker="|",
                draft=c["id"],
                style="bad",
                body=c["body"],
                badges=("draft", f"line {c['line']} gone"),
            )
            for c in stale
        )
    return rows


TABS = ("conversation", "commits", "checks", "files")


@dataclass(frozen=True)
class TabLabel:
    """A tab as its row shows it: the key that opens it, its name, and a count badge styled by what it means."""

    key: str
    name: str
    count: str = ""  # "" shows no badge: zero, or nothing read yet
    tone: str = "muted"  # muted for a plain total, accent for what needs you, bad for failing or changes requested

    def plain(self, ascii_badge: bool = True) -> str:
        badge = f" [{self.count}]" if ascii_badge else f"  {self.count} "
        return f"{self.key} {self.name}" + (badge if self.count else "")


def tab_labels(pr: PullRequest | None, narrow: bool = False) -> dict[str, TabLabel]:
    """The lower pane's tabs: Conversation (red when changes are requested), Commits, Checks (red with the failing
    count while any fail) and Files, each with its count; no count before it is read. Narrow panes get shorter names so all four fit in 70 columns."""
    names = {
        "conversation": "Talk" if narrow else "Conversation",
        "commits": "Commits",
        "checks": "Checks",
        "files": "Files" if narrow else "Files changed",
    }
    keys = {name: str(TABS.index(name) + 1) for name in TABS}
    if pr is None:
        return {name: TabLabel(keys[name], names[name]) for name in TABS}
    comments = sum(1 for note in pr.notes if note.body.strip())
    failing = sum(1 for check in pr.checks if check.state == "fail")
    counts = {
        "conversation": (comments, "bad" if pr.review_decision == "CHANGES_REQUESTED" else "muted"),
        "commits": (pr.commit_total, "muted"),
        "checks": (failing, "bad") if failing else (len(pr.checks), "muted"),
        "files": (len(pr.files), "muted"),
    }
    labels = {}
    for name in TABS:
        count, tone = counts[name]
        shown = str(count) if count and not (name == "files" and pr.files_loading) else ""
        labels[name] = TabLabel(keys[name], names[name], shown, tone)
    return labels


def commit_rows(pr: PullRequest, *, now: datetime | None = None) -> list[ViewRow]:
    rows = [ViewRow("heading", f"{pr.commit_total} commits on {pr.head_ref}", selectable=False)]
    if pr.commit_total > len(pr.commits):
        rows.append(ViewRow("info", f"the last {len(pr.commits)} are shown", selectable=False))
    for commit in pr.commits:
        rows.append(
            ViewRow(
                "commit",
                f"{commit.sha[:7]} {commit.headline}",
                author=commit.author,
                when=age(commit.date, now),
                body=commit.headline,
                number=commit.sha[:7],
                link=pr.forge.commit_url(pr.repo, pr.number, commit.sha),
            )
        )
    return rows


CHECK_WORDS = {"fail": "failing", "pending": "running", "cancelled": "cancelled", "pass": "passed", "skip": "skipped"}
CHECK_STYLE = {"fail": "bad", "pending": "wait", "cancelled": "wait", "pass": "ok", "skip": "dim"}


def check_rows(pr: PullRequest) -> list[ViewRow]:
    """The Checks tab: a tally that leads with the worst (failing, running, passed...), then each check, failing ones
    first with why they failed."""
    if not pr.checks:
        return [ViewRow("info", "no checks on the head commit", selectable=False)]
    tally = {state: sum(1 for check in pr.checks if check.state == state) for state in CHECK_WORDS}
    summary = [(f"{tally[state]} {word}", CHECK_STYLE[state]) for state, word in CHECK_WORDS.items() if tally[state]]
    rows = [
        ViewRow("text", "  ".join(text for text, _style in summary), style=summary[0][1], selectable=False),
        ViewRow(
            "heading",
            f"checks on {pr.head[:7]}: o or enter opens one on {pr.forge.label}, ctrl+r refreshes",
            selectable=False,
        ),
    ]
    for check in pr.checks:  # failing first (the provider orders them)
        name = f"{check.workflow} / {check.name}" if check.workflow else check.name
        detail = check.raw.lower().replace("_", " ")
        label = {"pass": "\u2713", "fail": "\u00d7", "pending": "\u2022", "skip": "-", "cancelled": "-"}[check.state]
        when = detail if detail not in (check.state, "pending") else "in progress"
        if check.state == "fail":  # why it failed, readable here: the run's output title or the status's description
            when = ": ".join(part for part in (detail, clean(check.title or check.description)) if part)
        # a details link on the forge itself (a job page with the logs) opens; any other opens the forge's page for the run
        link = check.url if pr.forge.owns_url(check.url) else pr.forge.checks_url(pr.repo, pr.number, check.run_id)
        rows.append(
            ViewRow(
                "check",
                f"{label} {name} {detail}",
                body=name,
                badges=(label,) + (("required",) if check.required else ()),
                when=when,
                link=link,
                style={"fail": "bad", "pass": "ok", "pending": "wait"}.get(check.state, "dim"),
            )
        )
    return rows


STATE_BADGE = {"OPEN": "Open", "CLOSED": "Closed", "MERGED": "Merged"}


def state_badge(pr: PullRequest) -> str:
    """The state shown beside the title: Draft, Open, Closed or Merged."""
    return "Draft" if pr.draft and pr.state == "OPEN" else STATE_BADGE.get(pr.state, pr.state.title())


def merge_box(pr: PullRequest) -> Line:
    """The merge box, line by line: reviews, checks, the branch, and how it can merge. (text, style) pairs."""
    failing = any(check.state == "fail" for check in pr.checks)
    running = any(check.state == "pending" for check in pr.checks)
    rollup = ("FAILURE" if failing else "PENDING" if running else "SUCCESS") if pr.checks else ""
    return merge_lines(pr.forge.label, pr.review_decision, rollup, pr.merge_state)


def merge_lines(forge: str, review_decision: str, checks: str, merge_state: str) -> Line:
    """The merge box wording for a review decision, a checks rollup and a merge state. `forge` is the forge's name."""
    lines: Line = []
    review = {
        "APPROVED": ("Changes approved", "ok"),
        "CHANGES_REQUESTED": ("Changes requested", "bad"),
        "REVIEW_REQUIRED": ("Review required", "wait"),
    }.get(review_decision)
    if review:
        lines.append(review)
    check = {
        "FAILURE": ("Some checks were not successful", "bad"),
        "ERROR": ("Some checks were not successful", "bad"),
        "PENDING": ("Some checks haven't completed yet", "wait"),
        "EXPECTED": ("Some checks haven't completed yet", "wait"),
        "SUCCESS": ("All checks have passed", "ok"),
    }.get(checks)
    if check:
        lines.append(check)
    lines.append(
        {
            "BEHIND": ("This branch is out-of-date with the base branch", "wait"),
            "DIRTY": ("This branch has conflicts that must be resolved", "bad"),
            "BLOCKED": ("Merging is blocked", "bad"),
            "DRAFT": ("This pull request is still a work in progress", "dim"),
            "UNSTABLE": ("This branch has no conflicts with the base branch, but checks are failing", "wait"),
            "CLEAN": ("This branch has no conflicts with the base branch", "ok"),
            "HAS_HOOKS": ("This branch has no conflicts with the base branch", "ok"),
        }.get(merge_state, (f"{forge} is checking whether this can merge", "dim"))
    )
    return lines


HUNK_TAIL = 4  # the diff lines shown above a review thread in the conversation, as github.com does


def hunk_rows(thread: Thread, pr: PullRequest) -> list[ViewRow]:
    """The last lines of the diff a thread was left on, ending at its line, as the Files tab draws them; one note when
    the forge gave no diff for it."""
    lines = [line for line in parse_patch(thread.hunk) if line.kind != "hunk"][-HUNK_TAIL:]
    if not lines:
        return [ViewRow("info", "the diff this thread was left on is not available", style="dim", thread=thread.id)]
    width = max(len(str(number)) for line in lines for number in (line.old, line.new, 1) if number)
    edited = inline.marks([(line.kind, clean(line.text)) for line in lines])
    rows = []
    for position, line in enumerate(lines):
        side_line = line.anchor()
        number = line.old if line.kind == "del" else line.new
        rows.append(
            ViewRow(
                line.kind,
                line.text,
                number=str(number or "").rjust(width),
                marker={"add": "+", "del": "-"}.get(line.kind, " "),
                thread=thread.id,
                anchor=(thread.path, *side_line) if side_line else None,
                link=pr.forge.file_url(pr.repo, pr.number, thread.path, *side_line) if side_line else "",
                old=str(line.old or "").rjust(width),
                new=str(line.new or "").rjust(width),
                marks=edited.get(position, ()),
            )
        )
    return rows


def needs_you(pr: PullRequest, drafts: Drafts, icons: Mapping[str, str] = ASCII) -> Line:
    """What on this pull request waits on you, most pressing first, as (text, style) lines: a review asked of you,
    failing checks, requested changes, conflicts, threads waiting on your reply, your unsent drafts; "nothing" when
    none does."""
    me = pr.viewer.casefold()
    lines: Line = []
    own = bool(me) and pr.author.casefold() == me
    if me and me in (login.casefold() for login in pr.asked):
        lines.append((f"{icons['flag:new']} your review is requested", "accent"))
    failing = [check.name for check in pr.checks if check.state == "fail"]
    if failing:
        names = ", ".join(failing[:3]) + (f" and {len(failing) - 3} more" if len(failing) > 3 else "")
        lines.append(
            (f"{icons['flag:failing']} {len(failing)} failing check{'s' if len(failing) > 1 else ''}: {names}", "bad")
        )
    if pr.review_decision == "CHANGES_REQUESTED":
        lines.append((f"{icons['flag:changes']} changes requested", "bad"))
    if pr.mergeable == "CONFLICTING" or pr.merge_state == "DIRTY":
        lines.append((f"{icons['flag:conflict']} conflicts with {pr.base}", "bad"))
    elif pr.merge_state == "BEHIND":
        lines.append((f"{icons['flag:behind']} behind {pr.base}", "wait"))
    turns = [thread for thread in pr.threads if "your turn" in thread_badges(thread, drafts, pr.viewer)]
    if turns:
        lines.append(
            (f"{icons['flag:new']} {len(turns)} thread{'s' if len(turns) > 1 else ''} wait on your reply", "accent")
        )
    if own and pr.rerequest_due():
        lines.append((f"{icons['flag:new']} reviewers have not seen your last push: M then R asks them again", "wait"))
    count = drafts.count()
    if count:
        lines.append(
            (f"{icons['local']} {count} unsent draft{'s' if count > 1 else ''}: v shows what would be posted", "draft")
        )
    return lines or [(f"{icons['SUCCESS']} nothing waits on you here", "ok")]


def conversation_rows(
    pr: PullRequest, drafts: Drafts, *, icons: Mapping[str, str] = ASCII, now: datetime | None = None
) -> list[ViewRow]:
    """The Conversation tab in github.com's order: the description as the author's first comment, then reviews,
    comments, pushed commits and review threads (under their file and line, with the diff they were left on, open) by
    time, the merge box, and your drafts."""
    state = {
        "APPROVED": "approved these changes",
        "CHANGES_REQUESTED": "requested changes",
        "COMMENTED": "reviewed",
        "DISMISSED": "review dismissed",
        "PENDING": "review pending",
    }
    rows = [
        ViewRow("title", f"{pr.title} #{pr.number}"),
        ViewRow(
            "text",
            f"{pr.author} wants to merge {pr.commit_total} commits into {pr.base} from {pr.head_ref}",
            style="dim",
            badges=(state_badge(pr),),
        ),
        ViewRow("heading", "what needs you", selectable=False),
        *(ViewRow("text", text, style=style, selectable=False) for text, style in needs_you(pr, drafts, icons)),
        ViewRow(
            "comment",
            f"{pr.author} commented {ago(pr.created, now)}\n{plain(pr.body) or 'No description provided.'}",
            marker="|",
            author=pr.author,
            when=ago(pr.created, now),
            body=linked(pr.body, pr) or "*No description provided.*",
            link=pr.forge.pr_url(pr.repo, pr.number),
            badges=("edited",) if pr.edited else (),
            post=("description", pr.number),
            mine=is_viewer(pr.author, pr),
            raw=pr.body,
        ),
    ]
    notes = [note for note in pr.notes if note.body.strip() or note.state in ("APPROVED", "CHANGES_REQUESTED")]
    timeline: list[tuple[str, str, Any]] = [(note.at, "note", note) for note in notes]
    timeline += [(c.date, "commit", c) for c in pr.commits]
    timeline += [(thread.root.created, "thread", thread) for thread in pr.threads if thread.root]
    for _at, kind, item in sorted(timeline, key=lambda entry: entry[0]):
        if kind == "commit":
            rows.append(
                ViewRow(
                    "event",
                    f"{item.author} added commit {item.sha[:7]} {item.headline}  {ago(item.date, now)}",
                    style="dim",
                    link=pr.forge.commit_url(pr.repo, pr.number, item.sha),
                )
            )
        elif (
            kind == "thread"
        ):  # a review thread as github.com shows it in the timeline: file and line, the diff, comments
            rows.append(
                ViewRow(
                    "text",
                    f"{item.path} line {item.line or item.original_line}",
                    style="dim",
                    thread=item.id,
                    link=pr.forge.comment_url(pr.repo, pr.number, item.root.id),
                )
            )
            rows.extend(hunk_rows(item, pr))
            rows.extend(thread_rows(item, drafts, {item.id: True}, icons, now, pr))
        else:
            verb = state.get(item.state, item.state.lower()) if item.state else "commented"
            style = {"APPROVED": "ok", "CHANGES_REQUESTED": "bad"}.get(item.state, "")
            chip = {"APPROVED": ("approved",), "CHANGES_REQUESTED": ("changes requested",)}.get(item.state, ())
            rows.append(
                ViewRow(
                    "comment",
                    f"{item.author} {verb} {ago(item.at, now)}\n{plain(item.body)}".rstrip(),
                    style=style,
                    marker="|",
                    author=item.author,
                    when=f"{verb} {ago(item.at, now)}",
                    body=linked(item.body, pr),
                    badges=chip + (("edited",) if item.edited else ()),
                    link=pr.forge.note_url(pr.repo, pr.number, item),
                    post=("review" if item.state else "conversation", item.id) if item.id else None,
                    mine=is_viewer(item.author, pr),
                    raw=item.body,
                )
            )
    if pr.state == "OPEN":
        rows.append(ViewRow("heading", "merge", selectable=False))
        rows.extend(ViewRow("text", text, style=style, selectable=False) for text, style in merge_box(pr))
    for note in drafts.notes:
        rows.append(
            ViewRow(
                "draft",
                f"[pending comment] {note['body']}",
                draft=note["id"],
                marker="|",
                body=note["body"],
                badges=("pending", "comment"),
            )
        )
    rows.append(
        ViewRow("info", "c writes a comment on the conversation; ctrl+s keeps it, then y posts it", selectable=True)
    )
    paths = {item.path for item in pr.files}
    lost = [c for c in drafts.comments if c["path"] not in paths]
    if lost:
        rows.append(ViewRow("heading", "drafts on files no longer in the diff", selectable=False))
        rows.extend(
            ViewRow(
                "draft",
                f"[draft, {c['path']}:{c['line']}] {c['body']}",
                draft=c["id"],
                style="bad",
                marker="|",
                body=c["body"],
                badges=("draft", f"{c['path']}:{c['line']} gone"),
            )
            for c in lost
        )
    orphans = [r for r in drafts.replies if pr.thread(r["thread"]) is None]
    if orphans:
        rows.append(ViewRow("heading", "replies to threads that are gone", selectable=False))
        rows.extend(
            ViewRow(
                "draft",
                f"[reply, {r['path']}:{r['line']}] {r['body']}",
                draft=r["id"],
                style="bad",
                marker="|",
                body=r["body"],
                badges=("pending", "thread gone"),
            )
            for r in orphans
        )
    if drafts.summary.strip():
        rows.append(ViewRow("heading", "review summary (draft)", selectable=False))
        rows.append(
            ViewRow("draft", drafts.summary, draft="summary", marker="|", body=drafts.summary, badges=("summary",))
        )
    if pr.truncated:
        rows.append(
            ViewRow("info", f"only the first 100 {', '.join(pr.truncated)} are shown; the rest is on {pr.forge.label}")
        )
    return rows


SPLIT_WIDTH = 120  # columns the diff pane needs to show the old and the new file side by side

LINES = ("add", "del", "ctx", "more")


def split_rows(rows: list[ViewRow]) -> list[ViewRow]:
    """A file's rows side by side: each run of removed lines beside the run of added lines after it, an unchanged line
    beside itself, and the threads, drafts and other rows of a run after its pairs, full width. A pair's anchor is the
    new line's, else the old one's: a comment goes on the new file where it can."""
    out: list[ViewRow] = []
    index = 0
    while index < len(rows):
        row = rows[index]
        if row.kind in ("ctx", "more"):
            out.append(pair_row(row, row))
            index += 1
            continue
        if row.kind not in ("add", "del"):
            out.append(row)
            index += 1
            continue
        removed: list[ViewRow] = []
        added: list[ViewRow] = []
        cards: list[ViewRow] = []
        while index < len(rows) and rows[index].kind not in ("ctx", "more", "hunk", "gap", "heading", "file"):
            current = rows[index]
            (removed if current.kind == "del" else added if current.kind == "add" else cards).append(current)
            index += 1
        for at in range(max(len(removed), len(added))):
            out.append(pair_row(removed[at] if at < len(removed) else None, added[at] if at < len(added) else None))
        out.extend(cards)
    return out


def pair_row(left: ViewRow | None, right: ViewRow | None) -> ViewRow:
    """One side-by-side row: the new line's row (else the old one's) carrying both sides; its text holds both, so a
    search finds either."""
    main = right if right is not None else left
    if main is None:
        raise ValueError("a pair needs a side")
    sides = [main] if left is right else [side for side in (left, right) if side is not None]
    kind = main.kind if left is right else "add" if right is not None else "del"
    return replace(main, kind=kind, text="\n".join(side.text for side in sides), pair=(left, right))


TWO_NUMBERS = 50  # columns; a narrower pane shows the one line number a line has, not old and new


def diff_gutter(row: ViewRow, number_width: int, width: int) -> tuple[list[str], str]:
    """A diff line's gutter as (numbers, marker): the old and the new line number when the pane is wide enough for both,
    else the one the line is known by, then its + or - marker. The text starts after " ".join(numbers) + " " + marker + " "."""
    if width >= TWO_NUMBERS and (row.old or row.new or not row.number):
        return [row.old.rjust(number_width), row.new.rjust(number_width)], row.marker or " "
    return [row.number.rjust(number_width)], row.marker or " "


def view_row_lines(row: ViewRow, width: int, number_width: int) -> list[Line]:
    """A row as screen lines of (text, style) pairs: a narrow gutter with the line number, a marker, then the text wrapped
    under itself so nothing needs sideways scrolling."""
    style = row.style or row.kind
    if row.kind in ("add", "del", "ctx", "note"):
        numbers, marker = diff_gutter(row, number_width, width)
        gutter = f"{' '.join(numbers)} {marker} "
        body = hard_wrap(clean(row.text), width - len(gutter))
    elif row.marker == "|":
        gutter = f"{'':>{number_width}} | "
        body = word_wrap(clean(row.text), width - len(gutter))
    elif row.kind in ("hunk", "file", "heading"):
        gutter = ""
        body = hard_wrap(clean(row.text if row.kind != "heading" else f"-- {row.text} --"), width)
    else:
        gutter = ""
        body = word_wrap(clean(row.text), width)
    lines = []
    for index, text in enumerate(body):
        lead = gutter if index == 0 else " " * len(gutter)
        lines.append([(lead, "gutter"), (text, style)] if lead else [(text, style)])
    return lines


def number_width(pr: PullRequest | None, index: int) -> int:
    item = pr.files[index] if pr and 0 <= index < len(pr.files) else None
    return item.number_width if item else 1
