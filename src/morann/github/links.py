# SPDX-FileCopyrightText: 2026 Cristiano Carvalho
# SPDX-License-Identifier: Apache-2.0
"""github.com links: reading a pull request reference, and building every link Morann opens from checked parts."""

from __future__ import annotations

import hashlib
import re
import urllib.parse

from morann.models import Note
from morann.settings import UsageError, check_repo

HOST = "github.com"
GITHUB = f"https://{HOST}"

PULL_PATH = re.compile(
    r"/([A-Za-z0-9][A-Za-z0-9-]*)/([A-Za-z0-9._-]+)/pull/(\d{1,9})(?:/(?:files|commits|checks)(?:/[0-9a-f]{7,40})?)?/?"
)


def parse_ref(text: str, default_repo: str | None = None) -> tuple[str, int]:
    """(owner/repo, number) out of a pull request link (https://github.com/OWNER/REPO/pull/N, nothing else on any other
    host or path), OWNER/REPO#N, or a bare N or #N inside default_repo."""
    text = (text or "").strip()
    if "://" in text or text.startswith(HOST):
        parts = urllib.parse.urlsplit(text if "://" in text else f"https://{text}")
        if (
            parts.scheme != "https"
            or parts.hostname not in (HOST, f"www.{HOST}")
            or parts.port
            or parts.username
            or parts.password
        ):
            raise UsageError("only https://github.com pull request links")
        match = PULL_PATH.fullmatch(parts.path)
        if not match:
            raise UsageError("not a pull request link: https://github.com/OWNER/REPO/pull/N")
        repo, number = f"{match[1]}/{match[2]}", int(match[3])
    elif match := re.fullmatch(r"([^#\s]+/[^#\s]+)#(\d{1,9})", text):
        repo, number = match[1], int(match[2])
    elif match := re.fullmatch(r"#?(\d{1,9})", text):
        if not default_repo:
            raise UsageError("a bare number needs a pull request selected in its repository")
        repo, number = default_repo, int(match[1])
    else:
        raise UsageError("give a pull request link, OWNER/REPO#N or a number")
    if number < 1:
        raise UsageError("pull request numbers start at 1")
    return check_repo(repo), number


def pr_url(repo: str, number: int) -> str:
    return f"{GITHUB}/{check_repo(repo)}/pull/{int(number)}"


def file_url(repo: str, number: int, path: str, side: str | None = None, line: int | None = None) -> str:
    """The file in the pull request's Files tab, at a line when given (GitHub's diff-<sha256 of the path> anchor)."""
    anchor = "diff-" + hashlib.sha256(path.encode()).hexdigest()
    if line:
        anchor += ("L" if side == "LEFT" else "R") + str(int(line))
    return f"{pr_url(repo, number)}/files#{anchor}"


def comment_url(repo: str, number: int, comment_id: int) -> str:
    return f"{pr_url(repo, number)}#discussion_r{int(comment_id)}"


def note_url(repo: str, number: int, note: Note) -> str:
    """A conversation comment or a review summary on the pull request page."""
    if note.id:
        return f"{pr_url(repo, number)}#{'pullrequestreview' if note.state else 'issuecomment'}-{int(note.id)}"
    return pr_url(repo, number)


def commit_url(repo: str, number: int, sha: str) -> str:
    if not re.fullmatch(r"[0-9a-f]{7,40}", sha or ""):
        return pr_url(repo, number)
    return f"{pr_url(repo, number)}/commits/{sha}"


def checks_url(repo: str, number: int, run_id: int | None = None) -> str:
    """The pull request's Checks tab, at one check run when its id is known. A check's own details link comes from the
    API and can point anywhere, so it is never opened."""
    return f"{pr_url(repo, number)}/checks" + (f"?check_run_id={int(run_id)}" if run_id else "")


def blob_url(repo: str, path: str, ref: str | None = None) -> str:
    """A file at a ref on github.com; the default branch without one."""
    return f"{GITHUB}/{check_repo(repo)}/blob/{urllib.parse.quote(ref or 'HEAD')}/{urllib.parse.quote(path)}"


def is_github_url(url: str) -> bool:
    parts = urllib.parse.urlsplit(url or "")
    return parts.scheme == "https" and parts.hostname == HOST and not parts.port and not parts.username
