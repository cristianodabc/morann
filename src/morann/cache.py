# SPDX-FileCopyrightText: 2026 Cristiano Carvalho
# SPDX-License-Identifier: Apache-2.0
"""The last snapshot the forge gave for each pull request, on disk, so reopening one shows it at once."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING

from morann.settings import check_repo, home

if TYPE_CHECKING:
    from morann.forge import Snapshot


class PrCache:
    """The last snapshot of each pull request, shown at once while a fresh read runs.
    <root>/<owner>/<repo>/<number>.json, written whole through a rename; the oldest go beyond KEEP files."""

    KEEP = 200

    def __init__(self, root: str | Path | None = None) -> None:
        self.root = Path(root) if root else home() / "prs"

    def path(self, repo: str, number: int) -> Path:
        owner, name = check_repo(repo).split("/")
        return self.root / owner / name / f"{int(number)}.json"

    def get(self, repo: str, number: int) -> Snapshot | None:
        """The cached snapshot when it is a whole one (its files are in), else None. A damaged entry is a miss."""
        try:
            raw = json.loads(self.path(repo, number).read_text())
        except (OSError, ValueError):
            return None
        return raw if isinstance(raw, dict) and raw.get("files") is not None else None

    def put(self, repo: str, number: int, raw: Snapshot) -> None:
        path = self.path(repo, number)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            handle, temporary = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
            with os.fdopen(handle, "w") as out:
                json.dump(raw, out)
            os.replace(temporary, path)
            cached = sorted(self.root.glob("*/*/*.json"), key=lambda item: item.stat().st_mtime)
            for old in cached[: -self.KEEP]:
                old.unlink(missing_ok=True)
        except OSError:
            pass  # a cache that cannot be written only means the next open waits for the forge
