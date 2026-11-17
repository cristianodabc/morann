# SPDX-FileCopyrightText: 2026 Cristiano Carvalho
# SPDX-License-Identifier: Apache-2.0
"""GitHub as a forge: every call Morann makes to GitHub, through the gh CLI."""

from __future__ import annotations

import urllib.parse
from collections.abc import Callable
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from morann.actions import METHOD
from morann.forge import Capability, ForgeError
from morann.github import links, parse, queries, search
from morann.github.client import TIMEOUT, Gh
from morann.models import (
    FileContent,
    Lists,
    Note,
    Page,
    PrRow,
    PrState,
    PullRequest,
    Scope,
)
from morann.settings import NAME, check_repo

if TYPE_CHECKING:
    from morann.actions import ActionPlan
    from morann.drafts import Plan
    from morann.forge import Snapshot

ASYNC_POLLS = 30  # polls of an asynchronous merge, two seconds apart, before Morann stops waiting


def review_payload(plan: Plan) -> dict[str, Any]:
    """The body of the one review a plan posts: the verdict, the inline comments and, when there is one, the summary."""
    payload: dict[str, Any] = {
        "commit_id": plan.head,
        "event": plan.event,
        "comments": [
            {"path": c["path"], "line": c["line"], "side": c["side"], "body": c["body"]} for c in plan.comments
        ],
    }
    if plan.summary.strip():
        payload["body"] = plan.summary
    return payload


class GitHubProvider:
    """GitHub through the gh CLI the user is logged in with. No token is read or stored."""

    name = "github"
    label = "GitHub"
    host = links.HOST
    capabilities = frozenset(Capability)

    def __init__(self, read_only: bool = False, program: str = "gh", timeout: float = TIMEOUT) -> None:
        self.gh = Gh(program=program, timeout=timeout, read_only=read_only)

    @property
    def read_only(self) -> bool:
        return self.gh.read_only

    @property
    def page_size(self) -> int:
        return search.PAGE

    def reader(self) -> GitHubProvider:
        return GitHubProvider(read_only=True, program=self.gh.program, timeout=self.gh.timeout)

    # Who is logged in, and their organizations.

    def viewer_login(self) -> str:
        return (self.gh.graphql(queries.VIEWER_QUERY).get("viewer") or {}).get("login") or ""

    def organizations(self) -> list[str]:
        """The organizations the gh login belongs to, by name."""
        return sorted(
            {
                item["login"]
                for item in self.gh.pages("user/orgs?per_page=100")
                if isinstance(item, dict) and NAME.fullmatch(item.get("login") or "")
            },
            key=str.casefold,
        )

    # The lists.

    def list_pull_requests(self, scope: Scope, kind: str = "mine", login: str = "") -> Lists:
        """My open pull requests and the open ones that request my review (directly or through a team), in one call;
        a kind other than mine narrows both to that organization or to the personal account."""
        narrowed = None if kind == "mine" else search.scope_terms(scope, kind, login)
        found = search.list_queries(scope, narrowed)
        data = self.gh.graphql(
            queries.LIST_QUERY, {"mine": found["mine"], "review": found["review"], "first": search.PAGE}
        )
        return Lists(
            viewer=(data.get("viewer") or {}).get("login") or "",
            mine=parse.parse_rows((data.get("mine") or {}).get("nodes")),
            review=parse.parse_rows((data.get("review") or {}).get("nodes")),
            totals={name: (data.get(name) or {}).get("issueCount", 0) for name in ("mine", "review")},
        )

    def list_scope(self, scope: Scope, kind: str, login: str = "", after: str | None = None, text: str = "") -> Page:
        """One page of a scope's open pull requests, whoever opened them, newest update first; with text, GitHub's
        search for it across the whole scope."""
        data = self.gh.graphql(
            queries.SCOPE_QUERY,
            {"q": search.scope_query(scope, kind, login, text), "first": search.PAGE, "after": after},
        )
        found = data.get("all") or {}
        info = found.get("pageInfo") or {}
        return Page(
            rows=parse.parse_rows(found.get("nodes")),
            total=int(found.get("issueCount") or 0),
            cursor=info.get("endCursor") if info.get("hasNextPage") else None,
        )

    # One pull request.

    def fetch_pr(
        self,
        repo: str,
        number: int,
        on_conversation: Callable[[Snapshot], None] | None = None,
        attempts: int = 3,
    ) -> Snapshot:
        """GitHub's answers for one pull request, every file's patch read at one head commit: when the head moves
        while loading, read again. on_conversation gets the conversation, commits and checks before the files."""
        owner, name = check_repo(repo).split("/")
        for attempt in range(attempts):
            data = self.gh.graphql(queries.PR_QUERY, {"owner": owner, "name": name, "number": int(number)})
            node = (data.get("repository") or {}).get("pullRequest")
            if not node:
                raise ForgeError(f"{repo}#{number} not found, or this login cannot read it")
            if on_conversation is not None and attempt == 0:
                on_conversation({"data": data, "files": None})
            files = self.gh.pages(f"repos/{repo}/pulls/{int(number)}/files?per_page=100")
            if self.head_sha(repo, number) == node["headRefOid"]:
                return {"data": data, "files": files, "fetched": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")}
        raise ForgeError("the pull request kept getting new commits while loading; try again")

    def build_pr(self, repo: str, number: int, snapshot: Snapshot, stale: bool = False) -> PullRequest:
        return parse.build_pr(self, repo, number, snapshot, stale)

    def head_sha(self, repo: str, number: int) -> str:
        return (self.gh.get(f"repos/{check_repo(repo)}/pulls/{int(number)}").get("head") or {}).get("sha") or ""

    # Posting a review.

    def post_review(self, plan: Plan) -> None:
        self.gh.post(f"repos/{plan.repo}/pulls/{plan.number}/reviews", review_payload(plan))

    def post_reply(self, repo: str, number: int, comment_id: int, body: str) -> None:
        self.gh.post(f"repos/{repo}/pulls/{number}/comments/{int(comment_id)}/replies", {"body": body})

    def resolve_thread(self, thread_id: str, resolved: bool) -> None:
        self.gh.graphql(queries.RESOLVE if resolved else queries.UNRESOLVE, {"id": thread_id})

    def post_comment(self, repo: str, number: int, body: str) -> None:
        self.gh.post(f"repos/{repo}/issues/{number}/comments", {"body": body})

    def edit_comment(self, repo: str, number: int, kind: str, comment_id: int, body: str) -> None:
        if kind == "line":
            self.gh.send("PATCH", f"repos/{repo}/pulls/comments/{int(comment_id)}", {"body": body})
        elif kind == "conversation":
            self.gh.send("PATCH", f"repos/{repo}/issues/comments/{int(comment_id)}", {"body": body})
        elif kind == "review":
            self.gh.send("PUT", f"repos/{repo}/pulls/{int(number)}/reviews/{int(comment_id)}", {"body": body})
        elif kind == "description":
            self.gh.send("PATCH", f"repos/{repo}/pulls/{int(number)}", {"body": body})
        else:
            raise ForgeError(f"GitHub cannot edit a {kind}")

    def delete_comment(self, repo: str, number: int, kind: str, comment_id: int) -> None:
        if kind == "line":
            self.gh.send("DELETE", f"repos/{repo}/pulls/comments/{int(comment_id)}", {})
        elif kind == "conversation":
            self.gh.send("DELETE", f"repos/{repo}/issues/comments/{int(comment_id)}", {})
        else:  # a submitted review's summary can only be edited; a description has no delete
            raise ForgeError(
                f"GitHub cannot delete a {'submitted review' if kind == 'review' else kind}; edit it instead"
            )

    def post_line_comment(
        self, repo: str, number: int, commit: str, path: str, side: str, line: int, body: str
    ) -> None:
        """GitHub's "Add single comment": a review comment created with no review, which GitHub publishes at once."""
        payload = {"body": body, "commit_id": commit, "path": path, "line": int(line), "side": side}
        self.gh.post(f"repos/{repo}/pulls/{int(number)}/comments", payload)

    # Acting on a pull request.

    def read_state(self, repo: str, number: int) -> PrState:
        owner, name = check_repo(repo).split("/")
        data = self.gh.graphql(queries.STATE_QUERY, {"owner": owner, "name": name, "number": int(number)})
        return parse.parse_state(self, repo, number, data)

    def apply_action(self, plan: ActionPlan, sleep: Callable[[float], None]) -> str:
        """Merges carry the head sha and update-branch the expected head, so GitHub refuses a moved one. A stacked
        pull request merges through GitHub's asynchronous merge, the only one that takes a stack."""
        base = f"repos/{plan.repo}/pulls/{plan.number}"
        if plan.action in METHOD and plan.stacked_on:
            return self.merge_async(plan, sleep)
        if plan.action in METHOD:
            self.gh.send("PUT", f"{base}/merge", {"merge_method": plan.method, "sha": plan.head})
        elif plan.action == "update":
            self.update_branch(plan.repo, plan.number, plan.head)
        elif plan.action in ("close", "reopen"):
            self.gh.send("PATCH", base, {"state": "closed" if plan.action == "close" else "open"})
        elif plan.action == "rerequest":
            self.gh.send(
                "POST", f"{base}/requested_reviewers", {"reviewers": list(plan.reviewers), "team_reviewers": []}
            )
        elif plan.action == "automerge":
            self.gh.graphql(queries.AUTO_ON, {"id": plan.id, "method": plan.method.upper(), "head": plan.head})
        else:
            mutation = {"ready": queries.READY, "draft": queries.TO_DRAFT, "noautomerge": queries.AUTO_OFF}
            self.gh.graphql(mutation[plan.action], {"id": plan.id})
        return ""

    def merge_async(self, plan: ActionPlan, sleep: Callable[[float], None], polls: int = ASYNC_POLLS) -> str:
        """GitHub's asynchronous merge: request it with the head sha, the method and the default action (the merge
        queue when the base has one), then poll until it is merged, enqueued or failed. Returns merged or queued in
        the merge queue; a failure raises ForgeError with GitHub's message."""
        base = f"repos/{plan.repo}/pulls/{plan.number}/merge-async"
        answer = self.gh.send("PUT", base, {"sha": plan.head, "merge_method": plan.method, "merge_action": "default"})
        uuid = str((answer.get("details") or {}).get("uuid") or "")
        for _poll in range(polls):
            if answer.get("status") != "pending" or not uuid:
                break
            sleep(2)
            answer = self.gh.get(f"{base}/{urllib.parse.quote(uuid, safe='')}")
        status, message = answer.get("status"), str((answer.get("details") or {}).get("message") or "")
        if status == "merged":
            return "merged"
        if status == "enqueued":
            return "queued in the merge queue"
        if status == "failed":
            raise ForgeError(f"the merge failed: {message or 'GitHub gave no reason'}")
        if status == "pending":
            return "requested; GitHub is still merging it, refresh in a moment"
        raise ForgeError(
            f"GitHub answered the merge with {status or 'no status'}: {message or 'check the pull request'}"
        )

    def update_branch(self, repo: str, number: int, expected_head: str) -> None:
        self.gh.send("PUT", f"repos/{repo}/pulls/{number}/update-branch", {"expected_head_sha": expected_head})

    def behind_by(self, row: PrRow) -> int | None:
        """How many commits the base has that the head does not, or None when GitHub cannot say."""
        if not row.head:
            return None
        try:
            base = urllib.parse.quote(row.base_ref, safe="/")
            return int(self.gh.get(f"repos/{check_repo(row.repo)}/compare/{base}...{row.head}").get("behind_by"))
        except (ForgeError, TypeError, ValueError):
            return None

    # Links.

    def parse_ref(self, text: str, default_repo: str | None = None) -> tuple[str, int]:
        return links.parse_ref(text, default_repo)

    def pr_url(self, repo: str, number: int) -> str:
        return links.pr_url(repo, number)

    def file_url(self, repo: str, number: int, path: str, side: str | None = None, line: int | None = None) -> str:
        return links.file_url(repo, number, path, side, line)

    def comment_url(self, repo: str, number: int, comment_id: int) -> str:
        return links.comment_url(repo, number, comment_id)

    def note_url(self, repo: str, number: int, note: Note) -> str:
        return links.note_url(repo, number, note)

    def commit_url(self, repo: str, number: int, sha: str) -> str:
        return links.commit_url(repo, number, sha)

    def checks_url(self, repo: str, number: int, run_id: int | None = None) -> str:
        return links.checks_url(repo, number, run_id)

    def owns_url(self, url: str) -> bool:
        return links.is_github_url(url)

    # Reading a file.

    def read_file(self, repo: str, path: str, ref: str | None = None) -> FileContent:
        owner, name = check_repo(repo).split("/")
        expression = f"{ref or 'HEAD'}:{path.strip('/')}"
        data = self.gh.graphql(queries.FILE_QUERY, {"owner": owner, "name": name, "expression": expression})
        found: dict[str, Any] | None = (data.get("repository") or {}).get("object")
        if not found:
            raise ForgeError(f"{path or 'the root'} not found in {repo} at {ref or 'its default branch'}")
        if found.get("__typename") != "Blob":
            raise ForgeError(f"{path or 'the root'} is not a file")
        binary, truncated = bool(found.get("isBinary")), bool(found.get("isTruncated"))
        return FileContent(
            repo=repo,
            path=path.strip("/"),
            ref=ref or "",
            text=None if binary or truncated else found.get("text") or "",
            size=int(found.get("byteSize") or 0),
            sha=found.get("oid") or "",
            binary=binary,
            truncated=truncated,
            url=links.blob_url(repo, path.strip("/"), ref),
        )
