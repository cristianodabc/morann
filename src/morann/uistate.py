# SPDX-FileCopyrightText: 2026 Cristiano Carvalho
# SPDX-License-Identifier: Apache-2.0
"""What Morann remembers between runs. The keys are in keymap.py."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

from morann.settings import home

# The UI state Morann remembers between runs. A damaged file is ignored, never fatal.


class State:
    def __init__(self, path: str | os.PathLike[str] | None = None) -> None:
        self.path = Path(path) if path else home() / "state.json"
        self.data: dict[str, Any] = {}
        try:
            found = json.loads(self.path.read_text())
        except (OSError, ValueError):
            return
        if isinstance(found, dict):
            self.data = found

    def get(self, key: str, default: Any = None) -> Any:
        return self.data.get(key, default)

    def save(self, **values: Any) -> None:
        self.data.update(values)
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            handle, temporary = tempfile.mkstemp(dir=self.path.parent, prefix=".state.")
            with os.fdopen(handle, "w") as out:
                json.dump(self.data, out)
            os.replace(temporary, self.path)
        except OSError:
            pass
