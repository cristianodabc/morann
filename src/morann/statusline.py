# SPDX-FileCopyrightText: 2026 Cristiano Carvalho
# SPDX-License-Identifier: Apache-2.0
"""The statusline, lualine style: one line of colored sections, the mode first, then where you are and how the review
stands, a few keys of the focused pane dimmed in the middle, and the position, the theme and ? help on the right.
Which segments show, and in which order, is a setting; what does not fit is dropped, least needed first."""

from __future__ import annotations

import os
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from rich.style import Style
from rich.text import Text

from morann.settings import UsageError, config_value
from morann.theme import Ink

SEGMENTS = ("mode", "where", "branch", "tab", "progress", "checks", "merge", "position", "theme", "help")
LEFT = ("mode", "where", "branch", "tab", "progress", "checks", "merge")
RIGHT = ("position", "theme", "help")
KEEP = (  # what stays longest on a narrow terminal first; "hints" is the keys in the middle
    "mode",
    "position",
    "progress",
    "where",
    "help",
    "hints",
    "tab",
    "checks",
    "merge",
    "branch",
    "theme",
)
HINTS = 5  # the most keys the middle shows

MODES = {  # a mode and its token
    "READING": "accent",
    "REVIEWING": "local",
    "PENDING": "warn",
    "COMMAND": "merged",
    "SEARCH": "info",
    "WRITING": "ok",
}

SEPARATORS = {  # per glyph set: the edge after a left section, the one before a right section
    "nerd": ("", ""),
    "unicode": ("▌", "▐"),
    "ascii": ("|", "|"),
}


@dataclass(frozen=True)
class Segment:
    name: str
    text: str
    token: str = ""  # the color it is drawn in; "" for the plain sections


def layout(environ: Mapping[str, str] | None = None) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """The segments each side shows, in order: `statusline_left` and `statusline_right` in the config file
    (MORANN_STATUSLINE_LEFT and _RIGHT override them), names separated by commas or spaces; the defaults otherwise.
    An unknown name is a UsageError that lists the known ones."""
    environ = os.environ if environ is None else environ
    sides = []
    for side, default in (("left", LEFT), ("right", RIGHT)):
        named = environ.get(f"MORANN_STATUSLINE_{side.upper()}") or config_value(f"statusline_{side}", environ)
        names = tuple(name for name in named.replace(",", " ").split() if name) if named else default
        unknown = [name for name in names if name not in SEGMENTS]
        if unknown:
            raise UsageError(f"unknown statusline segment {unknown[0]!r}; there are: {', '.join(SEGMENTS)}")
        sides.append(names)
    return sides[0], sides[1]


def fit(
    left: Sequence[Segment], right: Sequence[Segment], hints: Sequence[tuple[str, str]], width: int, cost: int
) -> tuple[list[Segment], list[Segment], list[tuple[str, str]]]:
    """What fits `width` cells, dropping by KEEP from its end: the theme, the branch and the merge state go first, then
    the keys one at a time, before the mode, the position, the progress or where you are. `cost` is what one
    segment's separators and padding take."""
    kept_left, kept_right, kept_hints = list(left), list(right), list(hints)

    def total() -> int:
        segments = sum(len(seg.text) + cost for seg in [*kept_left, *kept_right])
        return segments + (len(keys_text(kept_hints)) + 2 if kept_hints else 0)

    for name in reversed(KEEP):
        while name == "hints" and kept_hints and total() > width:
            kept_hints.pop()
        if total() <= width:
            break
        kept_left = [seg for seg in kept_left if seg.name != name]
        kept_right = [seg for seg in kept_right if seg.name != name]
    return kept_left, kept_right, kept_hints


def keys_text(hints: Sequence[tuple[str, str]]) -> str:
    return "  ".join(f"{keys} {label}" for keys, label in hints)


def render(
    left: Sequence[Segment],
    right: Sequence[Segment],
    hints: Sequence[tuple[str, str]],
    width: int,
    ink: Ink,
    glyphs: str,
) -> Text:
    """The line. In a color scheme each section is a filled block and the separators join them, powerline style; in the
    terminal's colors the mode is a reversed pill and the rest plain, with dim separators."""
    out_left, out_right = SEPARATORS.get(glyphs, SEPARATORS["ascii"])
    left, right, hints = fit(left, right, hints, width, 3)
    line = Text(end="", no_wrap=True, overflow="crop")
    fills = [ink.color("panel"), ink.color("surface")]  # the sections after the mode alternate
    previous = None
    for index, seg in enumerate(left):
        fill = ink.color(seg.token) if seg.token and index == 0 else fills[index % 2]
        body = section_style(seg, fill, ink, index == 0)
        if previous is not None or index:
            line.append(out_left, edge(previous, fill, ink))
        line.append(f" {seg.text} ", body)
        previous = fill
    if left:
        line.append(out_left, edge(previous, None, ink))
    middle = Text(f"  {keys_text(hints)}" if hints else "", ink("muted"))
    line.append_text(middle)
    tail = Text(end="", no_wrap=True)
    previous = None
    for index, seg in enumerate(right):
        fill = fills[(index + 1) % 2]
        tail.append(out_right, edge(fill, previous, ink))
        tail.append(f" {seg.text} ", section_style(seg, fill, ink, False))
        previous = fill
    gap = max(1, width - line.cell_len - tail.cell_len)
    line.append(" " * gap)
    line.append_text(tail)
    line.truncate(width)
    return line


def section_style(seg: Segment, fill: str | None, ink: Ink, first: bool) -> Style:
    if first and seg.token:  # the mode: its color, filled
        if not ink.truecolor:
            return Style(color=ink.color(seg.token), reverse=True, bold=True)
        return Style(color=ink.color("background"), bgcolor=fill, bold=True)
    base = ink(seg.token, bold=True) if seg.token else ink("text")
    return base + Style(bgcolor=fill) if ink.truecolor and fill else base


def edge(front: str | None, back: str | None, ink: Ink) -> Style:
    """A separator, powerline style: drawn in one section's fill over the next one's. Without fills, a dim one."""
    if not ink.truecolor or front is None and back is None:
        return ink("subtle")
    return Style(color=front, bgcolor=back)
