# SPDX-FileCopyrightText: 2026 Cristiano Carvalho
# SPDX-License-Identifier: Apache-2.0
"""Fuzzy matching for the pickers, fzf style: the query's characters in order anywhere in the text, scored higher when
they are consecutive or start a word, and lower across gaps. Standard library only."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from typing import TypeVar

T = TypeVar("T")

MATCH = 16  # each matched character
STREAK = 8  # a character right after the previous match
BOUNDARY = 10  # a character that starts a word: after a separator, or a capital after a small letter
FIRST = 6  # a match on the text's first character
GAP_START, GAP = 3, 1  # leaving a gap, and each character skipped inside it
SEPARATORS = " /#-_.:,()[]"


def boundary(text: str, index: int) -> bool:
    if index == 0:
        return True
    before, here = text[index - 1], text[index]
    return before in SEPARATORS or before.islower() and here.isupper() or not before.isdigit() and here.isdigit()


def match(query: str, text: str) -> tuple[int, tuple[int, ...]] | None:
    """(score, positions of the matched characters) when every character of the query is in the text in order, else
    None. A query in lower case ignores case, one with a capital does not. Spaces in the query are ignored.

    The leftmost match is found first, then tightened from its end backwards to the shortest window, as fzf does, so
    `ab` in `a-x-ab` scores the adjacent pair."""
    needle = query.replace(" ", "")
    if not needle:
        return 0, ()
    fold = needle == needle.lower()
    hay = text.lower() if fold else text
    at, end = 0, -1
    for ch in needle:
        end = hay.find(ch, at)
        if end < 0:
            return None
        at = end + 1
    positions = []
    at = end
    for ch in reversed(needle):  # backwards from the last match: the shortest window that still holds the query
        at = hay.rfind(ch, 0, at + 1)
        positions.append(at)
        at -= 1
    positions.reverse()
    return score(text, positions), tuple(positions)


def score(text: str, positions: Sequence[int]) -> int:
    total = 0
    for n, index in enumerate(positions):
        total += MATCH + (BOUNDARY if boundary(text, index) else 0)
        if n and index == positions[n - 1] + 1:
            total += STREAK
        elif n:
            total -= GAP_START + GAP * (index - positions[n - 1] - 1)
    if positions and positions[0] == 0:
        total += FIRST
    return total


def rank(query: str, items: Iterable[tuple[str, T]]) -> list[tuple[int, tuple[int, ...], T]]:
    """The items whose text matches, best first; ties keep the order they came in, so a list in order of recency stays
    so. An empty query keeps every item, in order."""
    found = []
    for order, (text, value) in enumerate(items):
        hit = match(query, text)
        if hit is not None:
            found.append((-hit[0], order, hit[1], value))
    found.sort(key=lambda entry: (entry[0], entry[1]))
    return [(-negative, positions, value) for negative, _order, positions, value in found]
