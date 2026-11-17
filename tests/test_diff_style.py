# SPDX-FileCopyrightText: 2026 Cristiano Carvalho
# SPDX-License-Identifier: Apache-2.0
"""The diff pane: which words changed in an edited line, the two-column gutter, and how the rows are painted (syntax
colors, the changed words, the gutter, threads and drafts under their lines, lines drawn only when shown)."""

import pytest
from textual.strip import Strip

from fake_github import NOW, FakeGitHub, drafted, fixture, load
from morann import core, inline, paint, palette
from morann.termcolors import TerminalColors
from support import make_app, settle

EDIT_OLD = "    value = compute(alpha, beta) + 10"
EDIT_NEW = "    value = compute(alpha, gamma) + 12"


def span(text, word):
    start = text.index(word)
    return (start, start + len(word))


def test_changed_words():
    old, new = inline.spans(EDIT_OLD, EDIT_NEW)  # the words that differ, in both lines, and nothing else
    assert old == (span(EDIT_OLD, "beta"), span(EDIT_OLD, "10")), old
    assert new == (span(EDIT_NEW, "gamma"), span(EDIT_NEW, "12")), new
    assert inline.spans("return x", "class Foo(Base):") == ((), ())  # two different lines, not one edited
    assert inline.spans("foo", "bar") == ((), ())  # the whole line changed: the tint says it
    assert inline.spans("same", "same") == ((), ()) and inline.spans("x" * 700, "y" + "x" * 699) == ((), ())
    assert inline.spans("a, b", "a,  b")[1] == ((2, 4),)  # a space added is shown too
    lines = [
        ("ctx", "a"),
        ("del", "x = f(1)"),
        ("note", "\\ No newline at end of file"),
        ("add", "# new"),
        ("add", "x = f(2)"),
        ("add", "y = 3"),
    ]
    pairs = inline.marks(lines)  # a removed line looks past an unrelated added line for its partner
    assert pairs == {1: ((6, 7),), 4: ((6, 7),)}, pairs
    assert (
        inline.marks([("del", "a"), ("ctx", "b"), ("add", "a")]) == {}
    )  # only a run of removals and one of additions pair


def test_diff_rows_and_gutter():
    with FakeGitHub(fixture()):
        pr = load()
        rows = core.file_rows(pr, 0, core.Drafts(pr.repo, pr.number), now=NOW)
    header, hunk = rows[0], rows[1]
    assert header.kind == "file" and header.counts == (3, 1) and header.body == "lib/a.py" and header.badges == ()
    assert header.text == "lib/a.py  +3 -1" and hunk.kind == "hunk" and hunk.text == "@@ -1,4 +1,5 @@"
    gone = next(row for row in rows if row.kind == "del")
    added = next(row for row in rows if row.kind == "add")
    context = next(row for row in rows if row.kind == "ctx")
    assert (gone.text, gone.old, gone.new, gone.anchor) == ("import sys", "2", "", ("lib/a.py", "LEFT", 2))
    assert (added.text, added.old, added.new, added.anchor) == ("import json", "", "2", ("lib/a.py", "RIGHT", 2))
    assert gone.marks == (span("import sys", "sys"),) and added.marks == (span("import json", "json"),)
    assert (context.old, context.new, context.marks) == ("1", "1", ())
    third = [row for row in rows if row.kind == "add"][1]
    assert third.text == "import re" and third.marks == ()  # no partner left: tint only
    assert core.diff_gutter(gone, 2, 80) == ([" 2", "  "], "-") and core.diff_gutter(added, 2, 80) == (
        ["  ", " 2"],
        "+",
    )
    assert core.diff_gutter(context, 2, 80) == ([" 1", " 1"], " ")
    assert core.diff_gutter(gone, 2, core.TWO_NUMBERS - 1) == ([" 2"], "-")  # a narrow pane keeps one number
    assert core.diff_gutter(added, 2, core.TWO_NUMBERS - 1) == ([" 2"], "+")
    note = core.ViewRow("note", "\\ No newline at end of file")
    wide = ["".join(t for t, _ in line) for line in core.view_row_lines(note, 80, 2)]
    assert wide == ["        \\ No newline at end of file"], wide  # a note's text starts where the code does
    seen = core.file_rows(pr, 0, core.Drafts(pr.repo, pr.number), viewed=True)[0]
    assert seen.badges == ("Viewed",) and seen.text.endswith("  Viewed")


def channels(color):
    return [int(color[at : at + 2], 16) for at in (1, 3, 5)]


COLORS = TerminalColors(foreground="#c0caf5", background="#1a1b26", red="#f7768e", green="#9ece6a", blue="#7aa2f7")


def test_palette():
    """github's own diff colors, dark and light; the terminal's own green and red blended the same way; the ANSI
    colors without 24-bit color; nothing under NO_COLOR."""
    assert palette.github(True) is palette.DARK and palette.github(False) is palette.LIGHT
    assert (palette.LIGHT.add_line, palette.LIGHT.add_num, palette.LIGHT.del_line, palette.LIGHT.del_num) == (
        "#dafbe1",
        "#aceebb",
        "#ffebe9",
        "#ffcecb",
    )
    assert (palette.DARK.add_line, palette.DARK.add_num, palette.DARK.del_line, palette.DARK.del_num) == (
        "#12261e",
        "#1c4328",
        "#24171c",
        "#532426",
    )
    assert (palette.DARK.hunk_line, palette.DARK.hunk_num, palette.LIGHT.hunk_line) == ("#111d2e", "#0c2d6b", "#ddf4ff")
    own = palette.from_terminal(COLORS)
    for tint in (palette.DARK, palette.LIGHT, own):  # green lines, red lines; a changed word a stronger shade
        assert channels(tint.add_line)[1] > channels(tint.add_line)[0] and tint.add_word != tint.add_line
        assert channels(tint.del_line)[0] > channels(tint.del_line)[1] and tint.del_word != tint.del_line
    assert own.page == COLORS.background and own.text == COLORS.foreground and COLORS.dark
    choose = palette.choose
    assert choose(truecolor=True, no_color=True, dark=True, terminal_theme=True) is None
    assert choose(truecolor=False, no_color=False, dark=True, terminal_theme=True, colors=COLORS) is palette.ANSI
    assert choose(truecolor=True, no_color=False, dark=False, terminal_theme=True) is palette.LIGHT
    assert choose(truecolor=True, no_color=False, dark=True, terminal_theme=True, colors=COLORS) == own
    assert choose(truecolor=True, no_color=False, dark=True, terminal_theme=False, colors=COLORS) is palette.DARK
    assert (palette.ANSI.add_line, palette.ANSI.del_line, palette.ANSI.add_word) == ("green", "red", "bright_green")


@pytest.mark.parametrize(
    ("environ", "expected"),
    [
        ({"COLORTERM": "truecolor"}, True),
        ({"COLORTERM": "24bit"}, True),
        ({"COLORTERM": "TrueColor"}, True),
        ({"TERM": "xterm-direct"}, True),
        ({"TERM": "xterm-truecolor"}, True),
        ({}, False),
        ({"TERM": "xterm-256color"}, False),
        ({"COLORTERM": "yes", "TERM": "screen"}, False),
        ({"COLORTERM": ""}, False),
        ({"TERM": "xterm-256color", "TERM_PROGRAM": "Apple_Terminal"}, False),
    ],
)
def test_when_a_terminal_shows_24_bit_color(environ, expected):
    assert palette.truecolor(environ) is expected


def strip_text(strips):
    return "".join(segment.text for segment in strips)


def drawn(strips):
    """Each screen line of a painted row as a Strip, drawing the lazy ones as the pane does when it shows them."""
    return [strip if isinstance(strip, Strip) else strip() for strip in strips]


def segment_with(strip, text):
    """The segment that draws `text`, give or take the spaces around it."""
    return next(segment for segment in strip if segment.text == text or segment.text.strip() == text.strip())


def background(segment):
    """A segment's background as hex, or None when the terminal's own shows."""
    color = segment.style.bgcolor if segment.style else None
    return color.name if color is not None else None


def backgrounds(strip):
    return [background(segment) for segment in strip]


CASES = {  # what is drawn: the theme, 24-bit color, what the terminal said its colors are, and the diff colors
    "terminal, 16 colors": ("terminal", False, None, palette.ANSI),
    "terminal, 24-bit, colors unknown": ("terminal", True, None, palette.DARK),
    "terminal, 24-bit, its own colors": ("terminal", True, COLORS, palette.from_terminal(COLORS)),
    "catppuccin latte": ("catppuccin-latte", True, None, palette.LIGHT),
    "gruvbox dark": ("gruvbox-dark", True, None, palette.DARK),
    "nord, 16 colors": ("nord", False, None, palette.ANSI),
}


def assert_tinted(painter, tint, removed, inserted, same, label):
    """A removed, an added and a context line in github's colors: the whole line tinted, the gutter's numbers in the
    stronger shade, the changed words stronger still, a context line left to the terminal; and the cursor lifts the
    colors of the row it is on."""
    for line, kind in ((removed, "del"), (inserted, "add")):
        line_bg, number_bg, word_bg = (
            getattr(tint, f"{kind}_line"),
            getattr(tint, f"{kind}_num"),
            getattr(tint, f"{kind}_word"),
        )
        segments = list(line)
        assert background(segments[0]) == number_bg, (label, kind)
        assert background(segments[1]) == number_bg  # the old and the new number are one block
        assert background(segments[-1]) == line_bg and line.cell_length == 100  # the tint runs to the pane's edge
        assert background(segment_with(line, "import")) == line_bg
        assert background(segment_with(line, "sys" if kind == "del" else "json")) == word_bg
        assert background(segment_with(line, "-" if kind == "del" else "+")) == line_bg
        assert not any(segment.style.bold for segment in segments[:4])  # github does not bold a number
    assert set(backgrounds(same)) == {None}  # a context line is the terminal's own
    if tint is palette.ANSI:  # 16 colors: context numbers dimmed, the cursor reversed over the line's own colors
        assert segment_with(same, " 1").style.dim
        lifted = list(painter.cursor_strip(inserted, True, True))
        assert all(segment.style.reverse for segment in lifted), [(s.text, str(s.style)) for s in lifted]
        return
    assert segment_with(same, " 1").style.color.name == tint.muted
    for line in (removed, inserted, same):  # the cursor: a lifted color, never the plain tint, the words still apart
        lifted = painter.cursor_strip(line, True, True)
        assert lifted.cell_length == line.cell_length and strip_text(lifted) == strip_text(line)
        assert None not in backgrounds(lifted) and backgrounds(lifted) != backgrounds(line)
    lifted = painter.cursor_strip(
        inserted, True, True
    )  # the changed word stays apart from its line, the gutter from the text
    assert background(segment_with(lifted, "json")) != background(segment_with(lifted, "import"))
    assert background(segment_with(lifted, "import")) != background(segment_with(lifted, " 2"))
    assert painter.cursor_strip(inserted, False, True) is not None and all(
        segment.style.underline for segment in painter.cursor_strip(inserted, False, True)
    )  # unfocused: underlined


@pytest.mark.parametrize("label", CASES)
async def test_painted_rows(label):
    """Painted rows in the terminal's colors and in github's: syntax colors, the changed words, the gutter, the
    threads and drafts under their lines, and lines highlighted only when drawn."""
    name, truecolor, colors, tint = CASES[label]
    with FakeGitHub(fixture()) as github:
        pr = load()
        drafts = drafted(core.DraftStore(github.dir / "drafts"), pr)
        rows = core.file_rows(pr, 0, drafts, overrides={"T2": True}, now=NOW)
        gone = next(row for row in rows if row.kind == "del")
        added = next(row for row in rows if row.kind == "add")
        context = next(row for row in rows if row.text == "import os")
        tui = make_app(github, theme_name=name, truecolor=truecolor, terminal_colors=colors)
        async with tui.run_test(size=(100, 40)) as pilot:
            await settle(pilot)
            painter = tui.painter
            assert painter.ansi == (name == "terminal")
            assert painter.tint == tint, label
            paint.code_text.cache_clear()
            lazy = painter.diff_row(context, 100, 2)  # nothing is highlighted until a line is drawn
            assert not isinstance(lazy[0], Strip) and paint.code_text.cache_info().currsize == 0
            [same] = drawn(lazy)
            assert paint.code_text.cache_info().currsize == 1
            [removed] = drawn(painter.diff_row(gone, 100, 2))
            assert strip_text(removed).rstrip() == " 2" + " " + "  " + " " + "- import sys", strip_text(removed)
            [inserted] = drawn(painter.diff_row(added, 100, 2))
            assert strip_text(inserted).rstrip() == "  " + " " + " 2" + " " + "+ import json", strip_text(inserted)
            assert strip_text(same).rstrip() == " 1" + " " + " 1" + " " + "  import os"
            keyword = segment_with(removed, "import").style
            assert keyword.color is not None and not keyword.reverse  # syntax colors, or the 16-color line's text
            if tint is not palette.ANSI:
                assert segment_with(same, "import").style.color == keyword.color  # one color for one kind of token
            assert_tinted(painter, tint, removed, inserted, same, label)
            [narrow] = drawn(painter.diff_row(gone, 40, 2))
            assert strip_text(narrow).rstrip() == " 2 - import sys", strip_text(narrow)
            # one number column: the tinted block is as wide as the gutter, the line to the edge
            assert background(list(narrow)[0]) == tint.del_num and background(list(narrow)[-1]) == tint.del_line
            assert narrow.cell_length == 40
            head = [strip_text(strip) for strip in drawn(painter.diff_row(rows[0], 100, 2))]
            assert len(head) == 1 and head[0].startswith("━━ lib/a.py  +3 -1 ━") and head[0].endswith("━")
            [rule] = drawn(painter.diff_row(rows[1], 100, 2))
            # github's hunk band: blue over the numbers, lighter blue under the text, to the pane's edge
            assert strip_text(rule).rstrip() == " " * 7 + "@@ -1,4 +1,5 @@" and rule.cell_length == 100
            first, *rest = list(rule)
            assert background(first) == tint.hunk_num and first.text == " " * 6
            assert {background(segment) for segment in rest} == {tint.hunk_line}
            assert next(s for s in rest if "@@" in s.text).style.color.name == tint.muted
            items = [row for row in rows if row.kind == "hunk"][1]  # a function name shows in full after the ranges
            assert "def main():" in strip_text(drawn(painter.diff_row(items, 100, 2))[0])
            long = core.ViewRow("add", "x" * 150, number="9", marker="+", anchor=("a.py", "RIGHT", 9), new="9")
            wrapped = drawn(painter.diff_row(long, 60, 2))  # a long line wraps under its gutter, all of it kept
            assert len(wrapped) == 3 and sum(strip_text(line).count("x") for line in wrapped) == 150
            # a wrapped line keeps its gutter's color and its tint, and has no number
            assert [background(list(line)[0]) for line in wrapped] == [tint.add_num] * 3
            assert all(background(list(line)[-1]) == tint.add_line for line in wrapped)
            assert all(strip_text(line).startswith("   ") for line in wrapped[1:])
            for index, row in enumerate(rows):  # the threads and drafts stay under their lines, the line numbers real
                if row.kind in ("add", "del", "ctx"):
                    assert row.anchor == (
                        "lib/a.py",
                        "RIGHT" if row.kind != "del" else "LEFT",
                        int(row.new if row.kind != "del" else row.old),
                    ), row
            under = next(i for i, row in enumerate(rows) if row.thread == "T1")
            assert rows[under - 1].text == "import re" and rows[under - 1].kind == "add"
            card = "\n".join(strip_text(strip) for strip in drawn(painter.diff_row(rows[under], 100, 2)))
            assert "thread on line 3" in card
            shown = [
                strip_text(strip)
                for row in rows[under:]
                if row.thread == "T1" or row.kind == "draft"
                for strip in drawn(painter.diff_row(row, 100, 2))
            ]
            assert any("ann" in text for text in shown) and any("call done() last?" in text for text in shown), shown
            big = [
                core.ViewRow(  # context lines: highlighted in every color depth
                    "ctx",
                    f"value_{n} = compute(item_{n}) + {n}",
                    number=str(n),
                    marker=" ",
                    old=str(n),
                    new=str(n),
                    anchor=("big.py", "RIGHT", n),
                )
                for n in range(1, 3001)
            ]
            paint.code_text.cache_clear()
            laid = [painter.diff_row(row, 100, 4) for row in big]  # a big file lays out without highlighting a line
            assert len(laid) == 3000 and paint.code_text.cache_info().currsize == 0
            drawn(laid[0])
            assert paint.code_text.cache_info().currsize == 1


GREEN = ("green", "bright_green")
RED = ("red", "bright_red")


def hue(color):
    """green, red or neither, for an ANSI name or a hex color."""
    if color in GREEN:
        return "green"
    if color in RED:
        return "red"
    red, green, _blue = channels(color)
    return "green" if green > red else "red" if red > green else ""


@pytest.mark.parametrize("label", CASES)
async def test_an_added_line_is_green_and_a_removed_one_red(label):
    """github's look in every theme and color depth: an added line on a green background and a removed line on a red
    one, across the whole line, the gutter included."""
    name, truecolor, colors, _tint = CASES[label]
    with FakeGitHub(fixture()) as github:
        pr = load()
        rows = core.file_rows(pr, 0, core.Drafts(pr.repo, pr.number), now=NOW)
        tui = make_app(github, theme_name=name, truecolor=truecolor, terminal_colors=colors)
        async with tui.run_test(size=(100, 40)) as pilot:
            await settle(pilot)
            for kind, wanted in (("add", "green"), ("del", "red")):
                [line] = drawn(tui.painter.diff_row(next(row for row in rows if row.kind == kind), 100, 2))
                assert {hue(background(segment)) for segment in line} == {wanted}, (label, kind, backgrounds(line))
