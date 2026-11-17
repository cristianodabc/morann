# SPDX-FileCopyrightText: 2026 Cristiano Carvalho
# SPDX-License-Identifier: Apache-2.0
"""A unified diff as rows with real line numbers, and the changed files as a tree."""

from __future__ import annotations

import re
from collections.abc import Iterator

from morann.models import DiffLine, File, TreeNode

HUNK = re.compile(r"^@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@")


def parse_patch(patch: str | None) -> list[DiffLine]:
    """The rows of a file's patch, each with its line number in the old file, the new file, or both."""
    rows: list[DiffLine] = []
    old, new = 0, 0
    for raw in (patch or "").split("\n"):
        hunk = HUNK.match(raw)
        if hunk:
            old, new = int(hunk[1]), int(hunk[2])
            rows.append(DiffLine("hunk", raw))
        elif not rows:
            continue
        elif raw.startswith("+"):
            rows.append(DiffLine("add", raw[1:], None, new))
            new += 1
        elif raw.startswith("-"):
            rows.append(DiffLine("del", raw[1:], old, None))
            old += 1
        elif raw.startswith(" "):
            rows.append(DiffLine("ctx", raw[1:], old, new))
            old += 1
            new += 1
        elif raw.startswith("\\"):
            rows.append(DiffLine("note", raw))
    return rows


def file_tree(files: list[File], query: str = "") -> list[TreeNode]:
    """The changed files as a tree: folders before files, each by name; a folder whose only child is a folder merges
    into one row (apps/shop/lib); a query keeps the files whose path contains it, ignoring case."""
    root = TreeNode("", "")
    needle = query.strip().casefold()
    for index, item in enumerate(files):
        if needle and needle not in item.path.casefold():
            continue
        parts = item.path.split("/")
        node = root
        for depth, part in enumerate(parts[:-1]):
            folder = "/".join(parts[: depth + 1])
            child = next((c for c in node.children if c.index is None and c.path == folder), None)
            if child is None:
                child = TreeNode(part, folder)
                node.children.append(child)
            node = child
        node.children.append(TreeNode(parts[-1], item.path, index))

    def tidy(node: TreeNode) -> None:
        merged = []
        for child in node.children:
            while child.index is None and len(child.children) == 1 and child.children[0].index is None:
                only = child.children[0]
                child = TreeNode(f"{child.name}/{only.name}", only.path, None, only.children)
            tidy(child)
            merged.append(child)
        node.children = sorted(merged, key=lambda c: (c.index is not None, c.name.casefold()))

    tidy(root)
    return root.children


def tree_order(nodes: list[TreeNode]) -> Iterator[int]:
    """The file indexes in the order the tree shows them, top to bottom."""
    for node in nodes:
        if node.index is not None:
            yield node.index
        yield from tree_order(node.children)
