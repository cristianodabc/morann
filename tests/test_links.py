# SPDX-FileCopyrightText: 2026 Cristiano Carvalho
# SPDX-License-Identifier: Apache-2.0
"""Pull request references parse strictly, and every link Morann opens is a github.com URL built from checked
parts."""

import hashlib

import pytest

from fake_github import NOW, FakeGitHub, fixture, load
from morann import cli, core
from morann.github import links
from support import refused

ANCHOR = "diff-" + hashlib.sha256(b"lib/a.py").hexdigest()


@pytest.mark.parametrize(
    ("given", "expected"),
    [
        ("https://github.com/acme/app/pull/7", ("acme/app", 7)),
        ("https://github.com/acme/app/pull/7/files", ("acme/app", 7)),
        ("https://www.github.com/acme/.github/pull/12/", ("acme/.github", 12)),
        ("https://github.com/acme/app/pull/7/commits/" + "a" * 40, ("acme/app", 7)),
        ("https://github.com/acme/app/pull/7?w=1#discussion_r9", ("acme/app", 7)),
        ("github.com/acme/app/pull/8", ("acme/app", 8)),
        ("acme/lib#9", ("acme/lib", 9)),
        ("#11", ("acme/app", 11)),
        (" 12 ", ("acme/app", 12)),
    ],
)
def test_a_reference_names_a_pull_request(given, expected):
    assert links.parse_ref(given, "acme/app") == expected


@pytest.mark.parametrize(
    "bad",
    [
        "http://github.com/acme/app/pull/7",
        "https://gist.github.com/acme/app/pull/7",
        "https://github.com.evil.test/acme/app/pull/7",
        "https://evil.test/github.com/acme/app/pull/7",
        "https://user@github.com/acme/app/pull/7",
        "https://github.com:8443/acme/app/pull/7",
        "https://github.com/acme/app/issues/7",
        "https://github.com/acme/app/pull/x",
        "https://github.com/acme/../app/pull/7",
        "https://github.com/acme/app/pull/7/../../x",
        "javascript:alert(1)",
        "acme#7",
        "acme/app#0",
        "7; rm -rf /",
        "",
    ],
)
def test_anything_else_is_refused(bad):
    with pytest.raises(core.UsageError):
        links.parse_ref(bad, "acme/app")


def test_a_bare_number_needs_a_repository():
    with refused(core.UsageError, "needs a pull request selected"):
        links.parse_ref("7")


def test_links_are_built_from_checked_parts():
    assert links.pr_url("acme/app", 7) == "https://github.com/acme/app/pull/7"
    assert (
        links.file_url("acme/app", 7, "lib/a.py", "RIGHT", 13)
        == f"https://github.com/acme/app/pull/7/files#{ANCHOR}R13"
    )
    assert (
        links.file_url("acme/app", 7, "lib/a.py", "LEFT", 2) == f"https://github.com/acme/app/pull/7/files#{ANCHOR}L2"
    )
    assert links.comment_url("acme/app", 7, 101) == "https://github.com/acme/app/pull/7#discussion_r101"
    assert (
        links.note_url("acme/app", 7, core.Note("ann", "x", "", id=5))
        == "https://github.com/acme/app/pull/7#issuecomment-5"
    )
    assert (
        links.note_url("acme/app", 7, core.Note("bob", "x", "", "CHANGES_REQUESTED", 6))
        == "https://github.com/acme/app/pull/7#pullrequestreview-6"
    )
    assert links.commit_url("acme/app", 7, "not a sha") == "https://github.com/acme/app/pull/7"
    assert links.is_github_url("https://github.com/acme/app/pull/7") and not links.is_github_url("https://ci.test/x")
    assert cli.parse(["https://github.com/acme/app/pull/7"]).ref == "https://github.com/acme/app/pull/7"


def test_every_row_links_to_github():
    with FakeGitHub(fixture()):
        pr = load()
    rows = core.file_rows(pr, 0, core.Drafts(pr.repo, pr.number), overrides={"T2": True}, now=NOW)
    by_text = {row.text: row.link for row in rows if row.kind in ("add", "del", "ctx")}
    assert by_text["import re"] == f"https://github.com/acme/app/pull/7/files#{ANCHOR}R3"
    assert by_text["import sys"] == f"https://github.com/acme/app/pull/7/files#{ANCHOR}L2"
    comment_links = {row.text.split("\n")[0]: row.link for row in rows if row.kind == "comment"}
    assert comment_links["ann 2d"] == "https://github.com/acme/app/pull/7#discussion_r101"
    assert all(
        links.is_github_url(row.link)
        for row in rows
        + core.conversation_rows(pr, core.Drafts(pr.repo, pr.number))
        + core.commit_rows(pr)
        + core.check_rows(pr)
        if row.link
    )
