# SPDX-FileCopyrightText: 2026 Cristiano Carvalho
# SPDX-License-Identifier: Apache-2.0
"""Which words changed inside a removed line and the added line that replaces it, so the diff shows the change itself and
nobody compares two lines by eye. Standard library only."""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from difflib import SequenceMatcher

Span = tuple[int, int]  # (start, end) characters of a line

TOKEN = re.compile(r"\w+|\s+|[^\w\s]")  # a word, a run of spaces, or one symbol
RELATED = 0.5  # share of tokens two lines must share to count as one line edited rather than two unrelated lines
LONGEST = 600  # characters; a longer line (minified code, data) is shown without emphasis
REACH = 3  # how many added lines past the last pairing a removed line may look for its partner


def spans(old: str, new: str) -> tuple[tuple[Span, ...], tuple[Span, ...]]:
    """The changed character ranges of an edited line, as (old spans, new spans), each a tuple of (start, end). Both are
    empty when the lines share too little to be the same line edited, or when the change is the whole line."""
    if old == new or len(old) > LONGEST or len(new) > LONGEST:
        return (), ()
    a, b = TOKEN.findall(old), TOKEN.findall(new)
    matcher = SequenceMatcher(None, a, b, autojunk=False)
    if matcher.quick_ratio() < RELATED or matcher.ratio() < RELATED:
        return (), ()
    first: list[Span] = []
    second: list[Span] = []
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag != "equal":
            first.append((i1, i2))
            second.append((j1, j2))
    return tuple(ranges(a, first, old)), tuple(ranges(b, second, new))


def ranges(tokens: Sequence[str], changed: Iterable[Span], text: str) -> list[Span]:
    """Token ranges as character ranges, joined when only spaces lie between them, and none at all when they cover the
    whole line."""
    starts = [0]
    for token in tokens:
        starts.append(starts[-1] + len(token))
    out: list[Span] = []
    for first, last in changed:
        start, end = starts[first], starts[last]
        if start == end:
            continue
        if out and not text[out[-1][1] : start].strip():
            start = out.pop()[0]
        out.append((start, end))
    whole = len(out) == 1 and not text[: out[0][0]].strip() and not text[out[0][1] :].strip()
    return [] if whole else out


def marks(lines: Sequence[tuple[str, str]]) -> dict[int, tuple[Span, ...]]:
    """The changed spans of every edited line in a file's diff. `lines` is a list of (kind, text); the result maps an
    index to its spans. In each run of removed lines followed by a run of added lines, a removed line is paired with the
    next added line it resembles, in order."""
    code = [index for index, (kind, _text) in enumerate(lines) if kind != "note"]  # "\ No newline" sits between a pair
    out: dict[int, tuple[Span, ...]] = {}
    at = 0
    while at < len(code):
        if lines[code[at]][0] != "del":
            at += 1
            continue
        mid = at
        while mid < len(code) and lines[code[mid]][0] == "del":
            mid += 1
        end = mid
        while end < len(code) and lines[code[end]][0] == "add":
            end += 1
        last = mid
        for gone in range(at, mid):
            for added in range(last, min(end, last + REACH + 1)):
                old, new = spans(lines[code[gone]][1], lines[code[added]][1])
                if old or new:
                    out[code[gone]], out[code[added]] = old, new
                    last = added + 1
                    break
        at = max(mid, end)
    return out
