# SPDX-FileCopyrightText: 2026 Cristiano Carvalho
# SPDX-License-Identifier: Apache-2.0
"""Local drafts and the review plan: what one submit posts, and submit itself, which needs the fingerprint of the
plan the user confirmed."""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import tempfile
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from morann.forge import Capability, ForgeError, lacks
from morann.models import File, PullRequest, Thread
from morann.settings import UsageError, check_repo, home

if TYPE_CHECKING:
    from morann.forge import Forge

EVENTS = ("COMMENT", "APPROVE", "REQUEST_CHANGES")

VERDICT = {"COMMENT": "comment", "APPROVE": "approve", "REQUEST_CHANGES": "request changes"}

Draft = dict[str, Any]  # one unsent comment, reply, resolve mark or conversation comment, as it is stored


# Local drafts: unsent comments, replies, resolve toggles and the summary. Nothing here talks to a forge.


class DraftError(Exception):
    """A draft that cannot be read, kept or edited."""


@dataclass
class Drafts:
    repo: str
    number: int
    summary: str = ""
    comments: list[Draft] = field(default_factory=list)  # {id, path, side, line, body, context}
    replies: list[Draft] = field(default_factory=list)  # {id, thread, comment, path, line, body}
    resolves: list[Draft] = field(default_factory=list)  # {id, thread, resolve, path, line}
    notes: list[Draft] = field(default_factory=list)  # {id, body}: comments on the conversation
    started: bool = False  # a review was started on purpose (v, :review); opening a pull request never starts one
    warning: str = ""  # set when a damaged drafts file was moved aside

    def groups(self) -> tuple[list[Draft], ...]:
        return (self.comments, self.replies, self.resolves, self.notes)

    def count(self) -> int:
        return sum(len(group) for group in self.groups()) + (1 if self.summary.strip() else 0)

    def empty(self) -> bool:
        """No review: nothing drafted and none started, so nothing is kept on disk."""
        return not self.started and self.count() == 0

    def find(self, draft_id: str) -> Draft | None:
        return next((item for group in self.groups() for item in group if item["id"] == draft_id), None)

    def add_note(self, body: str) -> str:
        """A comment on the conversation, which is posted apart from the review."""
        item = {"id": new_id(), "body": body}
        self.notes.append(item)
        return item["id"]

    def add_comment(self, path: str, side: str, line: int, body: str, context: list[str] | None = None) -> str:
        """context is the code around the line when the comment was written (line_context); a plan refuses the draft
        once that code changed, so a push can never move the comment onto other code."""
        item: Draft = {"id": new_id(), "path": path, "side": side, "line": int(line), "body": body}
        if context is not None:
            item["context"] = list(context)
        self.comments.append(item)
        return str(item["id"])

    def prune(self, pr: PullRequest) -> bool:
        """Drop resolve marks the pull request no longer needs: the thread is gone or already in that state. True when
        something was dropped."""
        keep = [r for r in self.resolves if (t := pr.thread(r["thread"])) is not None and t.resolved != r["resolve"]]
        dropped = len(keep) != len(self.resolves)
        self.resolves = keep
        return dropped

    def add_reply(self, thread: Thread, body: str) -> str:
        """A reply to a thread goes to its first comment, the one a forge's reply call names."""
        root = thread.root
        if root is None:
            raise DraftError("a thread with no comment takes no reply")
        item: Draft = {
            "id": new_id(),
            "thread": thread.id,
            "comment": root.id,
            "path": thread.path,
            "line": thread.line or thread.original_line,
            "body": body,
        }
        self.replies.append(item)
        return str(item["id"])

    def toggle_resolve(self, thread: Thread) -> str | None:
        """Mark the thread to flip its resolved state on submit, or drop that mark."""
        for item in self.resolves:
            if item["thread"] == thread.id:
                self.resolves.remove(item)
                return None
        item = {
            "id": new_id(),
            "thread": thread.id,
            "resolve": not thread.resolved,
            "path": thread.path,
            "line": thread.line or thread.original_line,
        }
        self.resolves.append(item)
        return str(item["id"])

    def edit(self, draft_id: str, body: str) -> None:
        """Change a comment's or reply's text; empty text deletes it."""
        item = self.find(draft_id)
        if item is None or "body" not in item:
            raise DraftError("no draft to edit there")
        if body.strip():
            item["body"] = body
        else:
            self.delete(draft_id)

    def delete(self, draft_id: str) -> None:
        for group in self.groups():
            group[:] = [item for item in group if item["id"] != draft_id]

    def to_json(self) -> dict[str, Any]:
        return {
            "version": 1,
            "repo": self.repo,
            "number": self.number,
            "summary": self.summary,
            "comments": self.comments,
            "replies": self.replies,
            "resolves": self.resolves,
            "notes": self.notes,
            "started": self.started,
        }


def new_id() -> str:
    return secrets.token_hex(4)


class DraftStore:
    """One JSON file per pull request: <root>/<owner>/<repo>/<number>.json. A file is written whole through a rename,
    so a crash leaves the old one; an empty draft set removes it."""

    def __init__(self, root: str | Path | None = None) -> None:
        self.root = Path(root) if root else home() / "drafts"

    def path(self, repo: str, number: int) -> Path:
        owner, name = check_repo(repo).split("/")
        return self.root / owner / name / f"{int(number)}.json"

    def load(self, repo: str, number: int) -> Drafts:
        path = self.path(repo, number)
        try:
            data = json.loads(path.read_text())
            if data.get("version") != 1 or data.get("repo") != repo or data.get("number") != int(number):
                raise ValueError("not a version 1 drafts file for this pull request")
            for group in ("comments", "replies", "resolves", "notes"):
                if not isinstance(data.get(group, []), list) or any("id" not in item for item in data.get(group, [])):
                    raise ValueError(f"bad {group}")
            return Drafts(
                repo=repo,
                number=int(number),
                summary=str(data.get("summary") or ""),
                comments=data.get("comments", []),
                replies=data.get("replies", []),
                resolves=data.get("resolves", []),
                notes=data.get("notes", []),
                started=bool(data.get("started")),
            )
        except FileNotFoundError:
            return Drafts(repo=repo, number=int(number))
        except (OSError, ValueError, TypeError, AttributeError) as error:
            aside = path.with_name(f"{path.name}.damaged-{int(datetime.now().timestamp())}")
            try:
                path.rename(aside)
            except OSError:
                raise DraftError(f"cannot read or move aside {path}: {error}") from None
            return Drafts(repo=repo, number=int(number), warning=f"drafts file was damaged ({error}); kept as {aside}")

    def save(self, drafts: Drafts) -> None:
        path = self.path(drafts.repo, drafts.number)
        if drafts.empty():
            path.unlink(missing_ok=True)
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        handle, temporary = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
        try:
            with os.fdopen(handle, "w") as out:
                json.dump(drafts.to_json(), out, indent=1)
            os.replace(temporary, path)
        except BaseException:
            Path(temporary).unlink(missing_ok=True)
            raise

    def waiting(self) -> dict[str, tuple[int, str]]:
        """{owner/repo#number: (drafts, when the last was kept, ISO)} for every review in progress: drafts kept, or a
        review started with none yet."""
        found = {}
        for path in self.root.glob("*/*/*.json"):
            repo = f"{path.parent.parent.name}/{path.parent.name}"
            try:
                drafts = self.load(repo, int(path.stem))
                kept = path.stat().st_mtime
            except (OSError, ValueError, DraftError, UsageError):
                continue
            if not drafts.empty():
                when = datetime.fromtimestamp(kept, UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
                found[f"{repo}#{int(path.stem)}"] = (drafts.count(), when)
        return found

    def counts(self) -> dict[str, int]:
        """{owner/repo#number: number of drafts} for every pull request with drafts."""
        return {key: count for key, (count, _kept) in self.waiting().items() if count}


# The review plan: what one submit posts. The confirmation screen shows plan.lines(); submit posts only the plan whose
# fingerprint the screen hands back.


class PlanError(Exception):
    """The drafts cannot be submitted as they are; the message says what to change."""


class NotConfirmed(Exception):
    """What was asked for is not the plan the screen showed, so nothing was sent."""


class HeadMoved(Exception):
    """The pull request got new commits since the plan was made, so nothing was sent."""


class SubmitError(Exception):
    """A submit that stopped part way; `posted` lists what went out before it did."""

    def __init__(self, message: str, posted: list[str]) -> None:
        super().__init__(message)
        self.posted = posted


@dataclass(frozen=True)
class Plan:
    repo: str
    number: int
    head: str
    event: str
    summary: str
    comments: tuple[Draft, ...]  # ({id, path, side, line, body}, ...)
    replies: tuple[Draft, ...]
    resolves: tuple[Draft, ...]
    warnings: tuple[str, ...] = ()
    notes: tuple[Draft, ...] = ()  # ({id, body}, ...): comments on the conversation

    def has_review(self) -> bool:
        return self.event != "COMMENT" or bool(self.summary.strip()) or bool(self.comments)

    def fingerprint(self) -> str:
        return hashlib.sha256(json.dumps(asdict(self), sort_keys=True).encode()).hexdigest()

    def lines(self) -> list[str]:
        """What the confirmation screen lists: every action submit would take, in order."""
        out = [f"{self.repo}#{self.number} at {self.head[:7]}", ""]
        if self.has_review():
            out.append(f"Review: {VERDICT[self.event]}")
            out.append("Summary: " + (self.summary.strip() or "(none)"))
            for c in self.comments:
                out.append(f"Comment on {c['path']}:{c['line']} ({'new' if c['side'] == 'RIGHT' else 'old'} file):")
                out.extend("    " + line for line in c["body"].splitlines() or [""])
        for r in self.replies:
            out.append(f"Reply on {r['path']}:{r['line']}:")
            out.extend("    " + line for line in r["body"].splitlines() or [""])
        for r in self.resolves:
            out.append(f"{'Resolve' if r['resolve'] else 'Unresolve'} thread on {r['path']}:{r['line']}")
        for n in self.notes:
            out.append("Comment on the conversation:")
            out.extend("    " + line for line in n["body"].splitlines() or [""])
        out.extend(f"Note: {warning}" for warning in self.warnings)
        return out


def pending_review(forge: Forge) -> str:
    """The warning for a review the viewer left unsubmitted on the forge's own site."""
    return (
        f"you have a review pending on {forge.host}; {forge.label} refuses a second one until it is submitted "
        "or discarded there"
    )


def build_plan(pr: PullRequest, drafts: Drafts, event: str) -> Plan:
    """The plan for this verdict and these drafts, or a PlanError naming what to fix first."""
    if event not in EVENTS:
        raise PlanError(f"unknown verdict {event}")
    problems = []
    if event != "COMMENT" and pr.viewer and pr.author.casefold() == pr.viewer.casefold():
        problems.append(f"{pr.forge.label} does not let you {VERDICT[event]} on your own pull request")
    if event == "REQUEST_CHANGES" and (missing := lacks(pr.forge, Capability.REQUEST_CHANGES)):
        problems.append(missing)
    if event == "REQUEST_CHANGES" and not drafts.summary.strip():
        problems.append("request changes needs a summary: press m")
    comments = []
    for c in drafts.comments:
        found = pr.file(c["path"])
        if found is None or found.find(c["side"], c["line"]) is None:
            problems.append(f"the draft on {c['path']}:{c['line']} is no longer in the diff; edit or delete it")
        elif moved(found, c):
            problems.append(
                f"the code at {c['path']}:{c['line']} changed since the draft was written; check it, then "
                "delete it and comment again"
            )
        else:
            comments.append({key: c[key] for key in ("id", "path", "side", "line", "body")})
    replies = []
    for r in drafts.replies:
        if pr.thread(r["thread"]) is None:
            problems.append(
                f"the thread of the reply on {r['path']}:{r['line']} is gone; delete the reply in the "
                "Conversation tab (1)"
            )
        else:
            replies.append({key: r[key] for key in ("id", "thread", "comment", "path", "line", "body")})
    resolves = []
    for r in drafts.resolves:
        thread = pr.thread(r["thread"])
        if thread is None:
            problems.append(
                f"the thread to {'resolve' if r['resolve'] else 'unresolve'} on {r['path']}:{r['line']} is gone"
            )
        elif thread.resolved != r["resolve"]:  # one already in that state is a no-op (Drafts.prune drops it)
            resolves.append({key: r[key] for key in ("id", "thread", "resolve", "path", "line")})
    if resolves and (missing := lacks(pr.forge, Capability.RESOLVE_THREADS)):
        problems.append(f"{missing}: remove the resolve marks (x)")
    if problems:
        raise PlanError("; ".join(problems))
    pending = any(c.pending and c.author == pr.viewer for t in pr.threads for c in t.comments)
    plan = Plan(
        repo=pr.repo,
        number=pr.number,
        head=pr.head,
        event=event,
        summary=drafts.summary,
        comments=tuple(comments),
        replies=tuple(replies),
        resolves=tuple(resolves),
        warnings=(pending_review(pr.forge),) if pending else (),
        notes=tuple(dict(n) for n in drafts.notes),
    )
    if not plan.has_review() and not plan.replies and not plan.resolves and not plan.notes:
        raise PlanError("nothing to submit: add a comment (c), a reply (R), a summary (m) or a verdict (a or r)")
    return plan


def line_context(item: File, index: int) -> list[str]:
    """The diff lines around one line of a file, as they read now: what a comment draft is checked against."""
    rows = item.lines[max(0, index - 1) : index + 2]
    return [f"{row.kind}:{row.text}" for row in rows]


def moved(item: File, comment: Draft) -> bool:
    """Whether the code a comment draft was written against is no longer at its line."""
    index = item.find(comment["side"], comment["line"])
    return "context" in comment and (index is None or line_context(item, index) != comment["context"])


def submit(forge: Forge, plan: Plan, confirmed: str | None, store: DraftStore) -> list[str]:
    """Post the plan: one review with its inline comments, then each reply, each resolve or unresolve, and each
    comment on the conversation.

    `confirmed` must be the fingerprint of this plan as the confirmation screen showed it; anything else posts
    nothing. The head is read again first and nothing is posted when it moved. Each part that posts is removed from
    the drafts before the next one starts, so a failure part way leaves exactly the unsent parts as drafts."""
    if not confirmed or confirmed != plan.fingerprint():
        raise NotConfirmed("not confirmed on the confirmation screen; nothing was posted")
    current = forge.head_sha(plan.repo, plan.number)
    if current != plan.head:
        raise HeadMoved(
            f"the pull request moved from {plan.head[:7]} to {current[:7]} since its diff was loaded; nothing "
            "was posted. Reload with ctrl+r; your drafts are kept"
        )
    posted: list[str] = []

    def forget(what: str, *draft_ids: str, summary: bool = False) -> None:
        posted.append(what)
        try:
            drafts = store.load(plan.repo, plan.number)
            for draft_id in draft_ids:
                drafts.delete(draft_id)
            if summary:
                drafts.summary = ""
            store.save(drafts)
        except (OSError, DraftError, UsageError) as error:
            raise SubmitError(
                f"posted {', '.join(posted)}, but could not take it off the drafts ({error}); delete those "
                "drafts before submitting again, or they post twice",
                posted,
            ) from None

    try:
        if plan.has_review():
            forge.post_review(plan)
            forget(
                f"review ({VERDICT[plan.event]}, {len(plan.comments)} comments)",
                *(c["id"] for c in plan.comments),
                summary=True,
            )
        for reply in plan.replies:
            forge.post_reply(plan.repo, plan.number, int(reply["comment"]), reply["body"])
            forget(f"reply on {reply['path']}:{reply['line']}", reply["id"])
        for item in plan.resolves:
            forge.resolve_thread(item["thread"], bool(item["resolve"]))
            forget(f"{'resolved' if item['resolve'] else 'unresolved'} {item['path']}:{item['line']}", item["id"])
        for note in plan.notes:
            forge.post_comment(plan.repo, plan.number, note["body"])
            forget("comment on the conversation", note["id"])
    except ForgeError as error:
        done = f"posted {', '.join(posted)}; " if posted else "nothing was posted; "
        if error.maybe_sent:
            raise SubmitError(
                f"{done}then {error}: the next part may have reached {forge.label} anyway. Check the pull request "
                f"on {forge.host} and delete what already arrived before submitting again",
                posted,
            ) from None
        raise SubmitError(f"{done}{forge.label} refused the rest: {error}. The rest stays as drafts", posted) from None
    return posted
