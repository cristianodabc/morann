# SPDX-FileCopyrightText: 2026 Cristiano Carvalho
# SPDX-License-Identifier: Apache-2.0
"""The chrome around the panes: the header's breadcrumb, the `:` command line, and the key line every dialog ends
with (the statusline is statusline.py). Each draws in the theme's tokens."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
from typing import ClassVar

from rich.text import Text
from textual.binding import Binding, BindingType
from textual.widgets import Input

from morann import core
from morann.theme import Ink

KEY_GAP = "  "  # between two keys in a key line


def key_line(pairs: Iterable[tuple[str, str]], ink: Ink, width: int = 0, tail: Sequence[tuple[str, str]] = ()) -> Text:
    """Keys and what they do, `key label  key label`, each key drawn as a cap. Given a width, the pairs that do not fit
    are left out from the end, and `tail` (such as ? help) is kept at the end."""

    def piece(key: str, label: str) -> Text:
        out = Text(f" {key} ", ink.key())
        if label:
            out.append(f" {label}", ink("muted"))
        return out

    pieces = [piece(key, label) for key, label in pairs]
    ending = [piece(key, label) for key, label in tail]
    room = width - sum(p.cell_len + len(KEY_GAP) for p in ending) if width else 0
    out = Text(end="")
    for part in pieces:
        if width and out.cell_len + part.cell_len + len(KEY_GAP) > room:
            break
        out.append_text(part)
        out.append(KEY_GAP)
    for part in ending:
        out.append_text(part)
        out.append(KEY_GAP)
    out.rstrip()
    return out


def crumbs(parts: Sequence[str], ink: Ink, separator: str, width: int) -> Text:
    """Where you are, `owner › repo › #7 › Files`: the last part bright, the others muted, the first parts dropped
    until it fits `width`."""
    parts = [part for part in parts if part]
    while len(parts) > 1 and core.width_of(f" {separator} ".join(parts)) + 2 > width:
        parts = parts[1:]
    out = Text(" ", end="")
    for index, part in enumerate(parts):
        if index:
            out.append(f" {separator} ", ink("subtle"))
        last = index == len(parts) - 1
        out.append(
            core.cut(part, max(4, width - 2)) if last else part, ink("accent", bold=True) if last else ink("muted")
        )
    out.append("  ")
    return out


class CommandLine(Input):
    """The `:` line. tab completes the command or its argument, up and down walk the history, enter runs it, esc
    closes. Main reads what it does through `complete`, `history` and `closed`, set when the line opens."""

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("tab", "complete", show=False, priority=True),
        Binding("up", "history(-1)", show=False, priority=True),
        Binding("down", "history(1)", show=False, priority=True),
        Binding("escape", "close", show=False, priority=True),
    ]

    def __init__(self, **kwargs: object) -> None:
        super().__init__(**kwargs)  # type: ignore[arg-type]
        self.complete: Callable[[str], list[str]] = lambda _text: []
        self.history: list[str] = []
        self.closed: Callable[[], None] = lambda: None
        self.at = 0  # where up and down are in the history; len(history) is the line being typed
        self.typed = ""
        self.choices: list[str] = []  # the completions tab cycles through, and which is shown
        self.choice = -1

    def start(self, history: list[str]) -> None:
        self.history, self.at, self.typed = list(history), len(history), ""
        self.choices, self.choice = [], -1
        self.value = ""

    def action_complete(self) -> None:
        """tab: the completions of what was typed, one after the other; a single one is taken with a space after."""
        if self.choice < 0 or self.value not in self.choices:
            self.choices, self.choice = self.complete(self.value), -1
        if not self.choices:
            return
        self.choice = (self.choice + 1) % len(self.choices)
        self.value = self.choices[self.choice] + (" " if len(self.choices) == 1 else "")
        self.cursor_position = len(self.value)

    def action_history(self, step: int) -> None:
        if not self.history:
            return
        if self.at == len(self.history):
            self.typed = self.value
        self.at = min(max(0, self.at + step), len(self.history))
        self.value = self.history[self.at] if self.at < len(self.history) else self.typed
        self.cursor_position = len(self.value)

    def action_close(self) -> None:
        self.closed()
