# SPDX-FileCopyrightText: 2026 Cristiano Carvalho
# SPDX-License-Identifier: Apache-2.0
"""The forge interface: everything Morann asks of a code host, and how one is chosen.

The UI, the review plan and the pull request actions talk only to `Forge` and to the models in `morann.models`. A
provider implements `Forge` for one host; `morann.github` is the one that ships. docs/adding-a-forge.md walks through
writing another."""

from __future__ import annotations

import enum
import importlib
import os
from collections.abc import Callable, Mapping
from importlib.metadata import entry_points
from typing import TYPE_CHECKING, Any, Protocol

from morann.settings import UsageError, config_path, parse_env, setting

if TYPE_CHECKING:
    from morann.actions import ActionPlan
    from morann.drafts import Plan
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

Snapshot = dict[str, Any]  # a provider's own answers for one pull request, as JSON; Morann caches it and hands it back


class ForgeError(Exception):
    """A call to the forge that failed; the message is one plain line saying why and, when there is one, the fix.
    maybe_sent is true when the call timed out, so a write may have reached the forge anyway."""

    def __init__(self, message: str, maybe_sent: bool = False) -> None:
        super().__init__(message)
        self.maybe_sent = maybe_sent


class Capability(enum.Enum):
    """What a forge may not have. A provider lists the ones it supports; Morann shows the rest as unavailable, with
    the forge's name, instead of failing. The value is how the refusal names it."""

    REQUEST_CHANGES = "request changes"
    RESOLVE_THREADS = "resolving threads"
    DRAFTS = "draft pull requests"
    AUTO_MERGE = "auto-merge"
    UPDATE_BRANCH = "update branch"
    REREQUEST_REVIEW = "re-request review"
    ORGANIZATIONS = "organizations"
    SEARCH = "search across a scope"
    READ_FILES = "reading files"
    SINGLE_COMMENTS = "comments outside a review"
    EDIT_COMMENTS = "editing comments"
    DELETE_COMMENTS = "deleting comments"


class Forge(Protocol):
    """One code host. Every method raises ForgeError when the host refuses or cannot be reached, and UsageError for an
    argument it cannot use. A write is refused with ForgeError when `read_only` is set."""

    @property
    def name(self) -> str:
        """The key it is selected by, such as github."""

    @property
    def label(self) -> str:
        """What messages call it, such as GitHub."""

    @property
    def host(self) -> str:
        """The host its links are on, such as github.com."""

    @property
    def capabilities(self) -> frozenset[Capability]:
        """What it supports of the things a forge may lack."""

    @property
    def read_only(self) -> bool:
        """Whether every write is refused."""

    @property
    def page_size(self) -> int:
        """How many pull requests one page of a list holds."""

    def reader(self) -> Forge:
        """This forge with every write refused."""

    # Who is logged in, and the organizations they can choose as a scope.

    def viewer_login(self) -> str: ...

    def organizations(self) -> list[str]:
        """The organizations the login belongs to, by name. None without Capability.ORGANIZATIONS."""

    # The lists.

    def list_pull_requests(self, scope: Scope, kind: str = "mine", login: str = "") -> Lists:
        """The viewer's open pull requests and the open ones that request their review, in a scope kind: mine (the
        scope's owners or repositories), org:<name> or personal (which needs the login)."""

    def list_scope(self, scope: Scope, kind: str, login: str = "", after: str | None = None, text: str = "") -> Page:
        """One page of every open pull request in a scope kind, newest update first, starting after a cursor. With
        text (Capability.SEARCH), only those matching it, searched on the forge across the whole scope."""

    # One pull request.

    def fetch_pr(self, repo: str, number: int, on_conversation: Callable[[Snapshot], None] | None = None) -> Snapshot:
        """Everything the forge says about one pull request, every file read at one head commit. on_conversation
        gets a snapshot without the files (its "files" is None) as soon as the conversation, commits and checks are
        in. The snapshot is JSON: Morann caches it and gives it back to build_pr."""

    def build_pr(self, repo: str, number: int, snapshot: Snapshot, stale: bool = False) -> PullRequest:
        """The pull request out of a snapshot, fresh or from the cache. A snapshot this provider cannot read is a
        ForgeError."""

    def head_sha(self, repo: str, number: int) -> str:
        """The pull request's head commit right now."""

    # Posting a review. Each call is one part of a confirmed plan; drafts.submit orders them.

    def post_review(self, plan: Plan) -> None:
        """One review: the verdict, the summary and the inline comments, against the plan's head commit."""

    def post_reply(self, repo: str, number: int, comment_id: int, body: str) -> None:
        """A reply to a review thread, addressed to its first comment."""

    def resolve_thread(self, thread_id: str, resolved: bool) -> None:
        """Resolve or unresolve a review thread (Capability.RESOLVE_THREADS)."""

    def post_comment(self, repo: str, number: int, body: str) -> None:
        """A comment on the conversation, apart from any review."""

    def edit_comment(self, repo: str, number: int, kind: str, comment_id: int, body: str) -> None:
        """Replace the text of one of the viewer's posts (Capability.EDIT_COMMENTS). `kind` is line (a comment on the
        diff), conversation (a comment on the conversation), review (a submitted review's summary) or description
        (the pull request's own; comment_id is ignored)."""

    def delete_comment(self, repo: str, number: int, kind: str, comment_id: int) -> None:
        """Delete one of the viewer's comments (Capability.DELETE_COMMENTS): line or conversation. A forge that
        cannot delete a kind raises ForgeError saying so."""

    def post_line_comment(
        self, repo: str, number: int, commit: str, path: str, side: str, line: int, body: str
    ) -> None:
        """One comment on a line of the diff at `commit`, posted on its own at once, outside any review
        (Capability.SINGLE_COMMENTS). `side` is LEFT for the old file's line, RIGHT for the new one's."""

    # Acting on a pull request. actions.run_action and actions.run_updates check the plan first.

    def read_state(self, repo: str, number: int) -> PrState:
        """What decides the actions: state, mergeability, reviews, checks and what the repository allows."""

    def apply_action(self, plan: ActionPlan, sleep: Callable[[float], None]) -> str:
        """Send one confirmed action, carrying the head it was planned for so the forge refuses a moved one. Returns
        how it ended when that is worth saying (merged, queued), else nothing."""

    def update_branch(self, repo: str, number: int, expected_head: str) -> None:
        """Bring the base into the pull request's branch (Capability.UPDATE_BRANCH)."""

    def behind_by(self, row: PrRow) -> int | None:
        """How many commits the base has that the head does not, or None when the forge cannot say."""

    # Links. Each is built from checked parts and is on `host`.

    def parse_ref(self, text: str, default_repo: str | None = None) -> tuple[str, int]:
        """(OWNER/REPO, number) out of a pull request link on this forge, OWNER/REPO#N, or a bare number inside
        default_repo. Anything else is a UsageError."""

    def pr_url(self, repo: str, number: int) -> str: ...

    def file_url(self, repo: str, number: int, path: str, side: str | None = None, line: int | None = None) -> str:
        """The file in the pull request's diff, at a line when given."""

    def comment_url(self, repo: str, number: int, comment_id: int) -> str: ...

    def note_url(self, repo: str, number: int, note: Note) -> str:
        """A conversation comment or a review summary on the pull request page."""

    def commit_url(self, repo: str, number: int, sha: str) -> str: ...

    def checks_url(self, repo: str, number: int, run_id: int | None = None) -> str:
        """The pull request's checks, at one run when its id is known."""

    def owns_url(self, url: str) -> bool:
        """Whether a link is on this forge, so it may be opened."""

    # Reading a file (Capability.READ_FILES).

    def read_file(self, repo: str, path: str, ref: str | None = None) -> FileContent:
        """A file at a ref; the default branch without one."""


def lacks(forge: Forge, capability: Capability) -> str:
    """Why something cannot be done on this forge, or nothing when it supports it."""
    return "" if capability in forge.capabilities else f"{forge.label} has no {capability.value}"


# Choosing a forge.

BUILT_IN = {"github": "morann.github:GitHubProvider"}
DEFAULT = "github"
ENTRY_POINTS = "morann.forges"  # the entry point group another package registers its provider under


def providers() -> dict[str, str]:
    """Every provider by name, each as "module:attribute": the ones other installed packages register under the
    morann.forges entry point group, then the built-in ones, which a package cannot replace."""
    return {**{entry.name: entry.value for entry in entry_points(group=ENTRY_POINTS)}, **BUILT_IN}


def chosen(environ: Mapping[str, str] | None = None) -> str:
    """The forge to use: MORANN_FORGE, else the forge line of the config file, else GitHub."""
    environ = os.environ if environ is None else environ
    name = setting("FORGE", environ).strip()
    if not name:
        try:
            name = parse_env(config_path(environ).read_text()).get("forge", "")
        except (OSError, UnicodeDecodeError):
            name = ""
    return name.casefold() or DEFAULT


def select(name: str | None = None, *, read_only: bool = False) -> Forge:
    """The provider for a forge name, the chosen one without a name. An unknown name, or a provider that cannot be
    loaded, is a UsageError naming the ones there are."""
    known = providers()
    name = name or chosen()
    if name not in known:
        raise UsageError(f"unknown forge {name!r}: there is {', '.join(sorted(known))}")
    module, _, attribute = known[name].partition(":")
    try:
        factory = getattr(importlib.import_module(module), attribute)
    except (ImportError, AttributeError) as error:
        raise UsageError(f"the {name} forge cannot be loaded: {error}") from None
    forge: Forge = factory(read_only=read_only)
    return forge
