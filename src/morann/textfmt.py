# SPDX-FileCopyrightText: 2026 Cristiano Carvalho
# SPDX-License-Identifier: Apache-2.0
"""Text helpers for the terminal: widths, cutting and wrapping, markdown made plain, ages, chip markers."""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Mapping
from datetime import UTC, datetime

# Text for the panes. The UI turns each (text, style) pair into colors; these functions decide what is shown.
Piece = tuple[str, str]  # (text, style)
Line = list[Piece]  # one screen line

ASCII = {
    "draft": "draft",
    "APPROVED": "ok",
    "CHANGES_REQUESTED": "chg",
    "REVIEW_REQUIRED": "req",
    "SUCCESS": "ci:ok",
    "FAILURE": "ci:x",
    "ERROR": "ci:x",
    "PENDING": "ci:..",
    "EXPECTED": "ci:..",
    "local": "*",
    "resolved": "[resolved]",
    "outdated": "[outdated]",
    "open": "-",
    "closed": "+",
    "ellipsis": "...",
    "crumb": ">",
    "flag:failing": "x",
    "flag:changes": "!",
    "flag:conflict": "#",
    "flag:behind": "<",
    "flag:new": "o",
}


NERD = {
    **ASCII,
    "draft": "",
    "APPROVED": "",
    "CHANGES_REQUESTED": "",
    "REVIEW_REQUIRED": "",
    "SUCCESS": "",
    "FAILURE": "",
    "ERROR": "",
    "PENDING": "",
    "EXPECTED": "",
    "local": "",
    "crumb": "\u203a",
    "flag:failing": "\uf057",
    "flag:changes": "\uf06a",
    "flag:conflict": "\uf126",
    "flag:behind": "\uf063",
    "flag:new": "\u25cf",
}


UNICODE = {  # glyphs every modern font has, each one cell wide
    **ASCII,
    "draft": "\u25cc",  # ◌
    "APPROVED": "\u2713",  # ✓
    "CHANGES_REQUESTED": "\u00b1",  # ±
    "REVIEW_REQUIRED": "\u25cb",  # ○
    "SUCCESS": "\u2713",
    "FAILURE": "\u2717",  # ✗
    "ERROR": "\u2717",
    "PENDING": "\u25cf",  # ●
    "EXPECTED": "\u25cf",
    "local": "\u270e",  # ✎
    "open": "\u25be",  # ▾
    "closed": "\u25b8",  # ▸
    "ellipsis": "\u2026",  # …
    "crumb": "\u203a",  # ›
    "flag:failing": "\u2717",
    "flag:changes": "\u00b1",
    "flag:conflict": "\u2260",  # ≠
    "flag:behind": "\u2193",  # ↓
    "flag:new": "\u25cf",
}


ICON_SETS = {"ascii": ASCII, "unicode": UNICODE, "nerd": NERD}

NERD_TERMINALS = ("kitty", "wezterm", "ghostty")  # they ship the Nerd Font symbols, so the icons draw in any font


def pick_icons(choice: str, environ: Mapping[str, str]) -> dict[str, str]:
    """The glyph set for --icons: ascii, unicode or nerd as named; auto (or anything else) picks nerd on a terminal
    that ships Nerd Font symbols, unicode where the locale is UTF-8, else ascii. MORANN_ICONS sets auto's answer."""
    choice = choice if choice in ICON_SETS else (environ.get("MORANN_ICONS") or "").strip().lower()
    if choice in ICON_SETS:
        return ICON_SETS[choice]
    term = f"{environ.get('TERM', '')} {environ.get('TERM_PROGRAM', '')}".lower()
    if any(name in term for name in NERD_TERMINALS) or environ.get("KITTY_WINDOW_ID") or environ.get("WEZTERM_PANE"):
        return NERD
    locale = next((environ[name] for name in ("LC_ALL", "LC_CTYPE", "LANG") if environ.get(name)), "")
    return UNICODE if "utf-8" in locale.lower() or "utf8" in locale.lower() else ASCII


CHIP_STYLE = {
    "draft": "dim",
    "APPROVED": "ok",
    "CHANGES_REQUESTED": "bad",
    "REVIEW_REQUIRED": "wait",
    "SUCCESS": "ok",
    "FAILURE": "bad",
    "ERROR": "bad",
    "PENDING": "wait",
    "EXPECTED": "wait",
    "local": "draft",
}


def cell_width(ch: str) -> int:
    if unicodedata.combining(ch):
        return 0
    return 2 if unicodedata.east_asian_width(ch) in "WF" else 1


def width_of(text: str) -> int:
    return sum(cell_width(ch) for ch in text)


def clean(text: str, tab: int = 4) -> str:
    """Text safe to draw: tabs expanded, carriage returns dropped, and every other invisible control, format or line
    separator character (a bidi override, U+2028) shown as '?', so a review never hides what the code holds."""
    text = text.expandtabs(tab).replace("\r", "")
    return "".join(ch if ch == "\n" or unicodedata.category(ch) not in ("Cc", "Cf", "Zl", "Zp") else "?" for ch in text)


def cut(text: str, width: int, ellipsis: str = "...") -> str:
    """Text cut to `width` cells, ending in the ellipsis when cut."""
    if width_of(text) <= width:
        return text
    out: list[str] = []
    used, room = 0, max(0, width - width_of(ellipsis))
    for ch in text:
        if used + cell_width(ch) > room:
            break
        out.append(ch)
        used += cell_width(ch)
    return "".join(out) + ellipsis[: max(0, width - used)]


def hard_wrap(text: str, width: int) -> list[str]:
    """Text broken into lines of at most `width` cells, at any character: code keeps its spacing."""
    width = max(1, width)
    lines = []
    for paragraph in text.split("\n"):
        line: list[str] = []
        used = 0
        for ch in paragraph:
            if used + cell_width(ch) > width and line:
                lines.append("".join(line))
                line, used = [], 0
            line.append(ch)
            used += cell_width(ch)
        lines.append("".join(line))
    return lines


def word_wrap(text: str, width: int) -> list[str]:
    """Prose broken at spaces, and inside a word only when the word is wider than a line."""
    width = max(1, width)
    lines = []
    for paragraph in text.split("\n"):
        indent = paragraph[: len(paragraph) - len(paragraph.lstrip(" "))]
        if indent and paragraph.startswith("    "):  # code inside a comment keeps its layout
            lines.extend(hard_wrap(paragraph, width))
            continue
        line = ""
        for word in paragraph.split(" "):
            candidate = f"{line} {word}" if line else word
            if width_of(candidate) <= width:
                line = candidate
                continue
            if line:
                lines.append(line)
            while width_of(word) > width:
                head = hard_wrap(word, width)[0]
                lines.append(head)
                word = word[len(head) :]
            line = word
        lines.append(line)
    return lines


def plain(markdown: str | None) -> str:
    """Markdown as readable plain text, for one-line previews and search: comments, HTML tags and emphasis markers
    gone, a link as its text, images named, footnotes as [1], code blocks indented, suggestions labeled."""
    text = re.sub(r"<!--.*?-->", "", (markdown or "").replace("\r\n", "\n"), flags=re.DOTALL)
    out, fence = [], None
    for line in text.split("\n"):
        mark = re.match(r"\s*(```|~~~)\s*([\w+-]*)", line)
        if mark and (fence is None or mark[1] == fence):
            if fence is None:
                fence = mark[1]
                if mark[2] == "suggestion":
                    out.append("suggested change:")
            else:
                fence = None
            continue
        if fence is not None:
            out.append("    " + line)
            continue
        line = re.sub(r"^\s{0,3}#{1,6}\s+", "", line)
        line = re.sub(r"^\s{0,3}>\s?", "| ", line)
        line = re.sub(r"\[!\[([^\]]*)\]\([^)]*\)\]\([^)]*\)", lambda m: f"[image: {m[1]}]" if m[1] else "[image]", line)
        line = re.sub(r"!\[([^\]]*)\]\([^)]*\)", lambda m: f"[image: {m[1]}]" if m[1] else "[image]", line)
        line = re.sub(r"<img\b[^>]*>", "[image]", line, flags=re.IGNORECASE)
        line = re.sub(r"<a\b[^>]*>(.*?)</a>", r"\1", line, flags=re.IGNORECASE)
        line = re.sub(r"\[([^\]]+)\]\(([^)\s]+)[^)]*\)", r"\1", line)  # a link reads as its text, as on the forge
        line = re.sub(r"<(https?://[^>\s]+)>", r"\1", line)
        line = re.sub(r"\[\^([^\]\s]+)\]:?", r"[\1]", line)  # a footnote and its note
        line = re.sub(r"</?[a-zA-Z][a-zA-Z0-9-]*(\s[^<>]*)?/?>", "", line)
        line = re.sub(r"(\*\*|__)(?=\S)(.+?)(?<=\S)\1", r"\2", line)
        line = re.sub(r"^(\s*)[*+-]\s+\[([ xX])\]\s+", lambda m: f"{m[1]}[{'x' if m[2] != ' ' else ' '}] ", line)
        line = re.sub(r"^(\s*)[*+]\s+", r"\1- ", line)
        line = line.replace("&nbsp;", " ").replace("&lt;", "<").replace("&gt;", ">").replace("&amp;", "&")
        out.append(line.rstrip())
    text = re.sub(r"\n{3,}", "\n\n", "\n".join(out)).strip("\n")
    return text


def trim_html(markdown: str | None) -> str:
    """Markdown with the HTML a forge allows reduced to text a terminal renderer shows: comments dropped, images named,
    line breaks kept, other tags removed, invisible characters shown as '?'."""
    text = re.sub(r"<!--.*?-->", "", (markdown or "").replace("\r\n", "\n"), flags=re.DOTALL)
    text = re.sub(r"<img\b[^>]*\balt=\"([^\"]*)\"[^>]*>", r"[image: \1]", text, flags=re.IGNORECASE)
    text = re.sub(r"<img\b[^>]*>", "[image]", text, flags=re.IGNORECASE)
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(
        r"</?(details|summary|p|div|span|sub|sup|b|i|em|strong|kbd|picture|source|a)\b[^>]*>",
        "",
        text,
        flags=re.IGNORECASE,
    )
    return clean(text).strip()


def ago(stamp: str, now: datetime | None = None) -> str:
    """How long ago, the way github.com says it: just now, 5 minutes ago, 2 hours ago, yesterday, 3 days ago."""
    short = age(stamp, now)
    if not short:
        return ""
    if short == "now":
        return "just now"
    count, unit = int(short[:-1]), short[-1]
    if unit == "d" and count == 1:
        return "yesterday"
    word = {"m": "minute", "h": "hour", "d": "day", "w": "week", "y": "year"}[unit]
    return f"{count} {word}{'s' if count != 1 else ''} ago"


def elapsed(seconds: float) -> str:
    """A short span for a running clock: 12s under a minute, 3m under an hour, then 2h."""
    seconds = max(0, int(seconds))
    if seconds < 60:
        return f"{seconds}s"
    return f"{seconds // 60}m" if seconds < 3600 else f"{seconds // 3600}h"


def age(stamp: str, now: datetime | None = None) -> str:
    """How long ago an ISO time was, in one short unit: 5m, 3h, 2d, 4w, 1y."""
    try:
        then = datetime.fromisoformat(stamp)
    except (ValueError, AttributeError):
        return ""
    seconds = max(0, int(((now or datetime.now(UTC)) - then).total_seconds()))
    for unit, size in (("y", 365 * 86400), ("w", 7 * 86400), ("d", 86400), ("h", 3600), ("m", 60)):
        if seconds >= size:
            return f"{seconds // size}{unit}"
    return "now"
