# SPDX-FileCopyrightText: 2026 Cristiano Carvalho
# SPDX-License-Identifier: Apache-2.0
"""A patch becomes rows with real file line numbers, and the changed files become a tree."""

from fake_github import FILES, PATCH
from morann import core
from morann.github import parse


def test_a_patch_maps_to_file_lines():
    rows = core.parse_patch(PATCH)
    shape = [(row.kind, row.old, row.new) for row in rows]
    assert shape == [
        ("hunk", None, None),
        ("ctx", 1, 1),
        ("del", 2, None),
        ("add", None, 2),
        ("add", None, 3),
        ("ctx", 3, 4),
        ("ctx", 4, 5),
        ("hunk", None, None),
        ("ctx", 10, 11),
        ("ctx", 11, 12),
        ("add", None, 13),
        ("ctx", 12, 14),
        ("note", None, None),
    ], shape
    assert [row.anchor() for row in rows] == [
        None,
        ("RIGHT", 1),
        ("LEFT", 2),
        ("RIGHT", 2),
        ("RIGHT", 3),
        ("RIGHT", 4),
        ("RIGHT", 5),
        None,
        ("RIGHT", 11),
        ("RIGHT", 12),
        ("RIGHT", 13),
        ("RIGHT", 14),
        None,
    ]
    assert rows[2].text == "import sys" and rows[5].text == "" and rows[12].text.startswith("\\ No newline")
    item = parse.parse_file(FILES[0])
    assert item.find("RIGHT", 13) == 10 and item.find("LEFT", 2) == 2 and item.find("LEFT", 10) == 8  # a context line
    assert item.find("RIGHT", 6) is None and item.find("LEFT", 5) is None  # between hunks, outside the diff


def test_added_removed_and_one_line_files():
    added = core.parse_patch("@@ -0,0 +1,2 @@\n+one\n+two")
    assert [(row.kind, row.new) for row in added] == [("hunk", None), ("add", 1), ("add", 2)]
    removed = core.parse_patch("@@ -1,2 +0,0 @@\n-one\n-two")
    assert [(row.kind, row.old) for row in removed] == [("hunk", None), ("del", 1), ("del", 2)]
    assert core.parse_patch("@@ -5 +5 @@\n-a\n+b")[1:] == [
        core.DiffLine("del", "a", 5),
        core.DiffLine("add", "b", None, 5),
    ]


def test_files_without_a_diff_say_why():
    binary, renamed, big = (parse.parse_file(item) for item in FILES[1:4])
    assert binary.lines == [] and binary.why_no_diff("GitHub") == "binary or empty file, no diff"
    assert (
        renamed.why_no_diff("GitHub") == "renamed from lib/old_name.py, no changes"
        and renamed.previous == "lib/old_name.py"
    )
    assert "too large" in big.why_no_diff("GitHub")
    moved = parse.parse_file(
        {
            "filename": "b.py",
            "previous_filename": "a.py",
            "status": "renamed",
            "additions": 1,
            "deletions": 1,
            "patch": "@@ -3 +3 @@\n-x\n+y",
        }
    )
    assert moved.find("LEFT", 3) == 1 and moved.find("RIGHT", 3) == 2 and moved.why_no_diff("GitHub") is None


def test_file_tree():
    """The changed files as GitHub's tree: folders first, by name; single-folder chains merged; renames under their
    new path; a filter keeps matching paths."""

    def item(path, status="modified", previous=None):
        return core.File(path, status, 1, 0, previous=previous)

    files = [
        item("apps/shop/lib/b.ex"),
        item("apps/shop/lib/a.ex"),
        item("apps/shop/test/a_test.exs"),
        item("README.md"),
        item("apps/web/x.ex"),
        item("mix.exs"),
        item("apps/web/new.ex", "renamed", "apps/old.ex"),
        item("Zed.md"),
    ]

    def shape(nodes, depth=0):
        out = []
        for node in nodes:
            out.append("  " * depth + node.name + ("" if node.index is None else f" [{node.index}]"))
            out += shape(node.children, depth + 1)
        return out

    assert shape(core.file_tree(files)) == [
        "apps",
        "  shop",
        "    lib",
        "      a.ex [1]",
        "      b.ex [0]",
        "    test",
        "      a_test.exs [2]",
        "  web",
        "    new.ex [6]",
        "    x.ex [4]",
        "mix.exs [5]",
        "README.md [3]",
        "Zed.md [7]",
    ], shape(core.file_tree(files))
    assert list(core.tree_order(core.file_tree(files))) == [1, 0, 2, 6, 4, 5, 3, 7]
    assert shape(core.file_tree(files, "TEST")) == ["apps/shop/test", "  a_test.exs [2]"]  # a chain merges into one row
    assert shape(core.file_tree(files, "lib/")) == ["apps/shop/lib", "  a.ex [1]", "  b.ex [0]"]
    assert core.file_tree(files, "nothing") == [] and core.file_tree([]) == []
    assert shape(core.file_tree([item("deep/only/one/file.py")])) == ["deep/only/one", "  file.py [0]"]
