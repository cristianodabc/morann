# SPDX-FileCopyrightText: 2026 Cristiano Carvalho
# SPDX-License-Identifier: Apache-2.0
"""The fake GitHub the tests run against: the fixture data, and FakeGitHub, which puts the fake gh first on PATH with
a fixture file and a call log in a throwaway folder."""

import copy
import json
import os
import shutil
import sys
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

from fake_gh import HEAD, save
from morann import core
from morann.github import GitHubProvider

FAKE_GH = Path(__file__).with_name("fake_gh.py")
NOW = datetime(2026, 11, 6, 12, 0, tzinfo=UTC)  # the clock every test reads ages from
MOVED = "b" * 40  # the head commit after a push


PATCH_LINES = (
    "@@ -1,4 +1,5 @@",
    " import os",
    "-import sys",
    "+import json",
    "+import re",
    " ",
    " def main():",
    "@@ -10,3 +11,4 @@ def main():",
    "     run()",
    "     stop()",
    "+    done()",
    " ",
    "\\ No newline at end of file",
)


PATCH = "\n".join(PATCH_LINES)


def search_node(number, repo="acme/app", draft=False, decision="REVIEW_REQUIRED", checks="SUCCESS", author="sam"):
    return {
        "number": number,
        "title": f"Change {number}",
        "url": f"https://github.com/{repo}/pull/{number}",
        "isDraft": draft,
        "reviewDecision": decision,
        "createdAt": "2026-11-01T10:00:00Z",
        "updatedAt": "2026-11-05T12:00:00Z",
        "author": {"login": author},
        "repository": {"nameWithOwner": repo},
        "commits": {"nodes": [{"commit": {"statusCheckRollup": {"state": checks} if checks else None}}]},
    }


def comment(number, author, body, created="2026-11-04T10:00:00Z", state="SUBMITTED"):
    return {"databaseId": number, "state": state, "body": body, "createdAt": created, "author": {"login": author}}


def thread(thread_id, line, side="RIGHT", resolved=False, outdated=False, path="lib/a.py", comments=(), hunk=None):
    node = {
        "id": thread_id,
        "isResolved": resolved,
        "isOutdated": outdated,
        "path": path,
        "line": line,
        "originalLine": line or 9,
        "diffSide": side,
        "comments": {"pageInfo": {"hasNextPage": False}, "nodes": list(comments)},
    }
    if hunk is not None:  # the diff the first comment was left on, as GitHub's diffHunk gives it
        node["hunk"] = {"nodes": [{"diffHunk": hunk}]}
    return node


def pr_node(author="sam"):
    return {
        "title": "Use json",
        "body": "## Why\nBecause <!-- hidden -->**fast**.",
        "url": "https://github.com/acme/app/pull/7",
        "isDraft": False,
        "state": "OPEN",
        "baseRefName": "main",
        "headRefName": "json",
        "author": {"login": author},
        "reviewThreads": {
            "pageInfo": {"hasNextPage": False},
            "nodes": [
                thread(
                    "T1",
                    3,
                    comments=[comment(101, "ann", "Why **re**?"), comment(102, "sam", "for the regex")],
                    hunk="\n".join(PATCH_LINES[:5]),
                ),
                thread(
                    "T2",
                    2,
                    side="LEFT",
                    resolved=True,
                    comments=[comment(201, "ann", "sys is still used")],
                    hunk="\n".join(PATCH_LINES[:3]),
                ),
                thread("T3", None, outdated=True, comments=[comment(301, "bob", "old remark")]),
                thread(
                    "T4", 1, path="gone.py", comments=[comment(401, "bob", "moved away")], hunk="@@ -0,0 +1 @@\n+moved"
                ),
            ],
        },
        "comments": {
            "pageInfo": {"hasNextPage": False},
            "nodes": [
                {"body": "Looks good <!-- bot -->", "createdAt": "2026-11-03T09:00:00Z", "author": {"login": "ann"}}
            ],
        },
        "reviews": {
            "pageInfo": {"hasNextPage": False},
            "nodes": [
                {"state": "COMMENTED", "body": "", "submittedAt": "2026-11-04T10:00:00Z", "author": {"login": "ann"}},
                {
                    "state": "CHANGES_REQUESTED",
                    "body": "Please fix",
                    "submittedAt": "2026-11-04T11:00:00Z",
                    "author": {"login": "bob"},
                },
            ],
        },
        "id": f"PR_{author}",
        "mergeable": "MERGEABLE",
        "mergeStateStatus": "CLEAN",
        "reviewDecision": "REVIEW_REQUIRED",
        "autoMergeRequest": None,
        "latestReviews": {
            "nodes": [
                {
                    "state": "CHANGES_REQUESTED",
                    "author": {"login": "bob", "__typename": "User"},
                    "commit": {"oid": "c" * 40},
                },
                {"state": "COMMENTED", "author": {"login": "ann", "__typename": "User"}, "commit": {"oid": HEAD}},
                {"state": "APPROVED", "author": {"login": "kim", "__typename": "User"}, "commit": {"oid": "c" * 40}},
                {
                    "state": "COMMENTED",
                    "author": {"login": "lint-bot[bot]", "__typename": "Bot"},
                    "commit": {"oid": HEAD},
                },
                {"state": "COMMENTED", "author": {"login": author, "__typename": "User"}, "commit": {"oid": HEAD}},
            ]
        },
        "reviewRequests": {
            "nodes": [
                {"requestedReviewer": {"__typename": "User", "login": "zed"}},
                {"requestedReviewer": {"__typename": "Team", "slug": "core"}},
            ]
        },
        "commits": {
            "totalCount": 2,
            "nodes": [
                {
                    "commit": {
                        "oid": "c" * 40,
                        "messageHeadline": "Use json",
                        "committedDate": "2026-11-02T10:00:00Z",
                        "author": {"name": "Sam", "user": {"login": "sam"}},
                    }
                },
                {
                    "commit": {
                        "oid": "d" * 40,
                        "messageHeadline": "Keep re",
                        "committedDate": "2026-11-04T10:30:00Z",
                        "author": {"name": "Sam Local", "user": None},
                    }
                },
            ],
        },
        "headCommit": {
            "nodes": [
                {
                    "commit": {
                        "statusCheckRollup": {
                            "state": "FAILURE",
                            "contexts": {
                                "nodes": [
                                    {
                                        "__typename": "StatusContext",
                                        "context": "deploy/preview",
                                        "state": "SUCCESS",
                                        "targetUrl": "https://preview.test",
                                        "description": "ready",
                                        "isRequired": False,
                                    },
                                    {
                                        "__typename": "CheckRun",
                                        "name": "lint",
                                        "status": "IN_PROGRESS",
                                        "conclusion": None,
                                        "detailsUrl": "https://ci.test/lint",
                                        "isRequired": False,
                                        "checkSuite": None,
                                        "databaseId": 556,
                                    },
                                    {
                                        "__typename": "CheckRun",
                                        "name": "test",
                                        "status": "COMPLETED",
                                        "conclusion": "FAILURE",
                                        "detailsUrl": "https://ci.test/test",
                                        "isRequired": True,
                                        "databaseId": 555,
                                        "title": "2 tests failed",
                                        "checkSuite": {"workflowRun": {"workflow": {"name": "CI"}}},
                                    },
                                    {
                                        "__typename": "CheckRun",
                                        "name": "docs",
                                        "status": "COMPLETED",
                                        "conclusion": "SKIPPED",
                                        "isRequired": False,
                                        "detailsUrl": "https://github.com/acme/app/actions/runs/9/job/10",
                                        "databaseId": 557,
                                        "checkSuite": {"workflowRun": {"workflow": {"name": "CI"}}},
                                    },
                                ]
                            },
                        }
                    }
                }
            ]
        },
    }


FILES = (  # the files of pull request #7; a fixture gets its own copy, so a test can change it
    {"filename": "lib/a.py", "status": "modified", "additions": 3, "deletions": 1, "patch": PATCH, "sha": "1" * 40},
    {"filename": "img/logo.png", "status": "added", "additions": 0, "deletions": 0},
    {
        "filename": "lib/new_name.py",
        "status": "renamed",
        "previous_filename": "lib/old_name.py",
        "additions": 0,
        "deletions": 0,
    },
    {"filename": "big.json", "status": "modified", "additions": 5000, "deletions": 0},
    {
        "filename": "docs/odd.md",
        "status": "modified",
        "additions": 1,
        "deletions": 0,
        "patch": "@@ -1 +1,2 @@\n x\n+a\u2028b",
    },
)


def fixture(**extra):
    return {
        "viewer": "me",
        "search": {
            "mine": [search_node(5, draft=True, decision="", checks="PENDING", author="me")],
            "review": [
                search_node(7),
                {},
                search_node(9, repo="acme/lib", decision="CHANGES_REQUESTED", checks="FAILURE", author="kim"),
            ],
        },
        "prs": {
            "acme/app#7": {"node": pr_node(), "heads": [HEAD], "files": copy.deepcopy(list(FILES))},
            "acme/app#5": {
                "node": {**pr_node(author="me"), "title": "My change", "isDraft": False},
                "heads": [HEAD],
                "files": copy.deepcopy(list(FILES[:1])),
            },
        },
        "repo": {
            "mergeCommitAllowed": True,
            "squashMergeAllowed": True,
            "rebaseMergeAllowed": False,
            "autoMergeAllowed": True,
        },
        "orgs": [{"login": "acme"}, {"login": "beta"}],
        "scoped": {
            "org:acme": [
                search_node(31, author="kim"),
                search_node(32, repo="acme/lib", author="me"),
                {**search_node(33, author="dependabot"), "author": {"login": "dependabot", "__typename": "Bot"}},
            ],
            "org:beta": [
                {**search_node(51, repo="beta/svc", author="zoe"), "updatedAt": "2026-11-06T09:00:00Z"},
                search_node(52, repo="beta/svc", author="me"),
            ],
            "user:me": [
                search_node(41, repo="me/notes", author="me"),
                {
                    **search_node(42, repo="me/notes", author="dependabot"),
                    "author": {"login": "dependabot", "__typename": "Bot"},
                },
            ],
        },
        "fail": {},
        **extra,
    }


def stack_fixture(**extra):
    """My pull requests: #21 is stacked on #20 and listed first, #22 has conflicts, #23 is a draft, #24 is current."""

    def mine(number, head_ref, base, merge_state, draft=False, mergeable="MERGEABLE"):
        node = search_node(number, draft=draft, decision="", checks="SUCCESS", author="me")
        node.update(
            headRefName=head_ref,
            baseRefName=base,
            headRefOid=f"{number:040d}",
            mergeStateStatus=merge_state,
            mergeable=mergeable,
        )
        return node

    data = fixture(**extra)
    data["search"]["mine"] = [
        mine(21, "feat-b", "feat-a", "BEHIND"),
        mine(20, "feat-a", "main", "BEHIND"),
        mine(22, "feat-c", "main", "DIRTY", mergeable="CONFLICTING"),
        mine(23, "wip", "main", "BEHIND", draft=True),
        mine(24, "done", "main", "CLEAN"),
    ]
    for number in (20, 21, 23):
        node = {**pr_node(author="me"), "mergeStateStatus": "BEHIND", "isDraft": number == 23}
        data["prs"][f"acme/app#{number}"] = {"node": node, "heads": [f"{number:040d}"], "files": []}
    return data


class FakeGitHub:
    """A temporary folder with the fake gh on PATH, its fixture and its call log."""

    def __init__(self, data):
        self.dir = Path(tempfile.mkdtemp(prefix="morann-test-"))
        self.fixture = self.dir / "github.json"
        self.log = self.dir / "calls.log"
        self.write(data)
        bin_dir = self.dir / "bin"
        bin_dir.mkdir()
        gh = bin_dir / "gh"
        gh.write_text(f'#!/bin/sh\nexec "{sys.executable}" -B "{FAKE_GH}" "$@"\n')
        gh.chmod(0o755)
        self.env = {
            "PATH": f"{bin_dir}:{os.environ['PATH']}",
            "MORANN_FAKE_GH": str(self.fixture),
            "MORANN_FAKE_GH_LOG": str(self.log),
            "MORANN_HOME": str(self.dir / "home"),
        }
        self.saved = {}

    def write(self, data):
        save(self.fixture, data)  # in one step: the app may be reading it in a worker

    def data(self):
        return json.loads(self.fixture.read_text())

    def calls(self):
        return [json.loads(line) for line in self.log.read_text().splitlines()] if self.log.exists() else []

    def posts(self):
        """Every write: a REST POST, PUT or PATCH, or a GraphQL mutation."""
        return [
            call
            for call in self.calls()
            if "graphql" not in call["args"]
            and {"POST", "PUT", "PATCH", "DELETE"} & set(call["args"])
            or "graphql" in call["args"]
            and "mutation" in call["stdin"]
        ]

    def set_pr(self, key, **fields):
        """Change fields of a pull request node, for example its state, as GitHub would."""
        data = self.data()
        data["prs"][key]["node"].update(fields)
        self.write(data)

    def __enter__(self):
        for key, value in self.env.items():
            self.saved[key] = os.environ.get(key)
            os.environ[key] = value
        return self

    def __exit__(self, *_exc):
        for key, value in self.saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        shutil.rmtree(self.dir)


def load_pr(forge, repo, number):
    """One pull request, every file read at one head commit."""
    return forge.build_pr(repo, number, forge.fetch_pr(repo, number))


def load():
    """Pull request acme/app#7, someone else's, as the fixture has it."""
    return load_pr(GitHubProvider(), "acme/app", 7)


def drafted(store, pr):
    """Saved drafts for a pull request: two comments, a reply, two resolve marks and a summary."""
    drafts = store.load(pr.repo, pr.number)
    drafts.add_comment("lib/a.py", "RIGHT", 13, "call done() last?")
    drafts.add_comment("lib/a.py", "LEFT", 2, "sys is used in main")
    drafts.add_reply(pr.thread("T1"), "ok, makes sense")
    drafts.toggle_resolve(pr.thread("T1"))
    drafts.toggle_resolve(pr.thread("T2"))
    drafts.summary = "Two small things"
    store.save(drafts)
    return drafts


def long_fixture():
    """Pull request #7 with a 120 line patch in its first file, so the diff pane scrolls."""
    data = fixture()
    lines = [f" line {number}" for number in range(1, 120)]
    patch = "@@ -1,119 +1,120 @@\n" + "\n".join([*lines[:60], "-gone", "+new one", "+new two", *lines[60:]])
    data["prs"]["acme/app#7"]["files"][0] = {**FILES[0], "patch": patch, "additions": 2, "deletions": 1}
    return data


def pr_row(number=1, repo="acme/app", **fields):
    """A list row with quiet defaults: open, passing, not a draft, last updated a day before NOW."""
    base = {
        "repo": repo,
        "number": number,
        "title": f"Change {number}",
        "url": "",
        "author": "sam",
        "draft": False,
        "decision": "",
        "checks": "SUCCESS",
        "created": "2026-11-01T10:00:00+00:00",
        "updated": "2026-11-05T12:00:00+00:00",
        "head": "h1",
    }
    return core.PrRow(**{**base, **fields})


def stamp(**ago):
    """The time that long before NOW, as GitHub writes it."""
    return (NOW - timedelta(**ago)).isoformat()
