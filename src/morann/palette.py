# SPDX-FileCopyrightText: 2026 Cristiano Carvalho
# SPDX-License-Identifier: Apache-2.0
"""The diff's colors, github.com's look in every theme: github's own dark and light colors, the terminal's own green and
red blended the same way, or its ANSI green and red; and whether the terminal shows 24-bit color."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from morann.termcolors import TerminalColors
from morann.theme import blend


@dataclass(frozen=True)
class DiffPalette:
    """The colors of a diff drawn github.com style: hex in 24-bit color, ANSI color names in 16."""

    add_line: str  # an added line, across the whole row
    add_num: str  # the old and new line numbers of an added line
    add_word: str  # the words that changed inside an added line
    del_line: str
    del_num: str
    del_word: str
    hunk_line: str  # a hunk header's text band
    hunk_num: str  # the band over the hunk header's line-number columns
    text: str  # the text color of added and removed lines, so they read on any terminal foreground
    muted: str  # context line numbers and the hunk header's text
    cursor: str  # the cursor row is tinted toward this
    page: str  # github's page background, which a context line has when the terminal gives none


# Read from github.com's computed styles on a pull request's Files changed page, in its dark and light color modes; the
# dark ones are github's translucent colors flattened over its page background.
DARK = DiffPalette(
    add_line="#12261e",
    add_num="#1c4328",
    add_word="#1d572d",
    del_line="#24171c",
    del_num="#532426",
    del_word="#792e2e",
    hunk_line="#111d2e",
    hunk_num="#0c2d6b",
    text="#f0f6fc",
    muted="#9198a1",
    cursor="#388bfd",
    page="#0d1117",
)
LIGHT = DiffPalette(
    add_line="#dafbe1",
    add_num="#aceebb",
    add_word="#aceebb",
    del_line="#ffebe9",
    del_num="#ffcecb",
    del_word="#ffcecb",
    hunk_line="#ddf4ff",
    hunk_num="#b6e3ff",
    text="#1f2328",
    muted="#59636e",
    cursor="#54aeff",
    page="#ffffff",
)
# The terminal's 16 colors: whole lines on its green and red, the changed words on the bright ones, black text so the
# lines read whatever the theme makes of green and red.
ANSI = DiffPalette(
    add_line="green",
    add_num="green",
    add_word="bright_green",
    del_line="red",
    del_num="red",
    del_word="bright_red",
    hunk_line="blue",
    hunk_num="blue",
    text="black",
    muted="black",
    cursor="",
    page="",
)

CURSOR_SHARE = 0.35  # how far the cursor row's colors move toward the palette's cursor color

SHARES = {  # how much of the terminal's green, red or blue each tint lays over its background, about github's own
    "line": 0.15,  # an added or removed line
    "number": 0.3,  # its line numbers
    "word": 0.42,  # the words that changed in it
    "hunk_line": 0.12,
    "hunk_number": 0.35,
}


def github(dark: bool) -> DiffPalette:
    return DARK if dark else LIGHT


def from_terminal(colors: TerminalColors) -> DiffPalette:
    """github's look made from the terminal's own colors: its green, red and blue laid over its background."""

    def tint(color: str, share: str) -> str:
        return blend(color, colors.background, SHARES[share])

    return DiffPalette(
        add_line=tint(colors.green, "line"),
        add_num=tint(colors.green, "number"),
        add_word=tint(colors.green, "word"),
        del_line=tint(colors.red, "line"),
        del_num=tint(colors.red, "number"),
        del_word=tint(colors.red, "word"),
        hunk_line=tint(colors.blue, "hunk_line"),
        hunk_num=tint(colors.blue, "hunk_number"),
        text=colors.foreground,
        muted=blend(colors.foreground, colors.background, 0.6),
        cursor=colors.blue,
        page=colors.background,
    )


def choose(
    *, truecolor: bool, no_color: bool, dark: bool, terminal_theme: bool, colors: TerminalColors | None = None
) -> DiffPalette | None:
    """The diff's colors: none under NO_COLOR; the ANSI green and red without 24-bit color; with it, the terminal's
    own green and red for the terminal's theme when the terminal told them, else github.com's, dark or light."""
    if no_color:
        return None
    if not truecolor:
        return ANSI
    if terminal_theme and colors is not None:
        return from_terminal(colors)
    return github(dark)


def truecolor(environ: Mapping[str, str]) -> bool:
    """Whether the terminal says it shows 24-bit color: COLORTERM=truecolor or 24bit, or a TERM that names it. Any other
    terminal keeps to its 16 ANSI colors."""
    if environ.get("COLORTERM", "").strip().lower() in ("truecolor", "24bit"):
        return True
    term = environ.get("TERM", "").lower()
    return "truecolor" in term or "24bit" in term or term.endswith("-direct")
