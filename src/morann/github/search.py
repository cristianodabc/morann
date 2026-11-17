# SPDX-FileCopyrightText: 2026 Cristiano Carvalho
# SPDX-License-Identifier: Apache-2.0
"""GitHub's search syntax for the lists: which pull requests a scope means, and a typed text made safe to search for."""

from __future__ import annotations

import re

from morann.models import Scope
from morann.settings import NAME, UsageError, check_owner, check_repo

PAGE = 50  # pull requests one list or one page holds


def terms(scope: Scope) -> str:
    """The search qualifiers of a scope: its repositories, else its owners."""
    if scope.repos:
        return " ".join(f"repo:{check_repo(repo)}" for repo in scope.repos)
    return " ".join(f"org:{check_owner(owner)}" for owner in scope.owners)


def list_queries(scope: Scope, narrowed: str | None = None) -> dict[str, str]:
    """The search for each list: open, not archived, newest update first; narrowed replaces the scope's own terms."""
    base = f"is:pr is:open archived:false {narrowed or terms(scope)} sort:updated-desc"
    return {"mine": f"{base} author:@me", "review": f"{base} review-requested:@me"}


def scope_terms(scope: Scope, kind: str, login: str = "") -> str:
    """The search qualifier of a scope kind: the chosen owners or repositories for mine, org:<name> for one
    organization, user:<login> for the personal account."""
    if kind == "mine":
        return terms(scope)
    if kind.startswith("org:"):
        return f"org:{check_owner(kind[4:])}"
    if kind == "personal":
        if not NAME.fullmatch(login or ""):
            raise UsageError("the personal scope needs the gh login")
        return f"user:{login}"
    raise UsageError(f"unknown scope {kind!r}")


def search_phrase(text: str) -> str:
    """Typed text as one quoted phrase for GitHub's search, or nothing: quotes and backslashes become spaces, so a
    qualifier typed in it (is:closed, org:other) is searched as text and never changes the scope's own rules."""
    words = re.sub(r'["\\]', " ", text or "").split()
    return f'"{" ".join(words)[:100].strip()}"' if words else ""


def scope_query(scope: Scope, kind: str, login: str = "", text: str = "") -> str:
    """The search for every open pull request in a scope kind (the All tab); with text, only those matching it."""
    phrase = search_phrase(text)
    found = f" {phrase}" if phrase else ""
    return f"is:pr is:open archived:false {scope_terms(scope, kind, login)}{found} sort:updated-desc"
