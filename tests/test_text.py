# SPDX-FileCopyrightText: 2026 Cristiano Carvalho
# SPDX-License-Identifier: Apache-2.0
"""Text as the terminal shows it: markdown made plain, wrapping by cell width, ages, and the rows of the list and the
diff laid out to a width."""

from fake_github import NOW, search_node
from morann import core
from morann.github import parse


def joined(line):
    return "".join(text for text, _style in line)


def test_markdown_becomes_plain_text():
    assert (
        core.plain("<!-- x -->Hi **there** see [docs](https://d.io) and ![shot](u.png)<br>")
        == "Hi there see docs and [image: shot]"
    )
    assert core.plain("```suggestion\nreturn 1\n```") == "suggested change:\n    return 1"
    assert core.plain("> quoted\n- [x] done\n* item") == "| quoted\n[x] done\n- item"
    assert core.plain("<details><summary>Logs</summary>\n\n\n\nbody</details>") == "Logs\n\nbody"


def test_wrapping_and_cutting_count_cells():
    assert core.hard_wrap("abcdefgh", 3) == ["abc", "def", "gh"] and core.hard_wrap("", 5) == [""]
    assert core.word_wrap("one two three", 7) == ["one two", "three"]
    assert core.word_wrap("a supercalifragilistic word", 8) == ["a", "supercal", "ifragili", "stic", "word"]
    assert core.hard_wrap("界界界", 4) == ["界界", "界"]  # wide characters take two cells
    assert core.cut("abcdefghij", 6) == "abc..." and core.cut("abc", 6) == "abc"


def test_text_from_the_forge_cannot_drive_the_terminal():
    assert core.clean("a\tb\r\x1b[31m") == "a   b?[31m"
    assert core.clean("a b‮c") == "a?b?c"  # a line separator and a bidi override are shown, not obeyed


def test_ages():
    assert core.age("2026-11-06T11:55:00Z", NOW) == "5m" and core.age("2026-10-01T12:00:00Z", NOW) == "5w"
    assert [core.elapsed(s) for s in (-5, 0, 59, 60, 179, 3599, 3600, 7200 + 59, 90000)] == [
        "0s",
        "0s",
        "59s",
        "1m",
        "2m",
        "59m",
        "1h",
        "2h",
        "25h",
    ]  # seconds, then minutes, then hours
    assert (
        core.ago("2026-11-06T11:00:00Z", NOW) == "1 hour ago" and core.ago("2026-11-05T11:00:00Z", NOW) == "yesterday"
    )
    assert core.ago("2026-11-06T12:00:00Z", NOW) == "just now"


def test_a_list_row_fits_its_width():
    row = parse.parse_rows(
        [search_node(7, repo="acme/app", draft=True, decision="CHANGES_REQUESTED", checks="FAILURE")]
    )[0]
    row.title = "A rather long title that will not fit in a seventy column pane at all"
    lines = core.list_row_lines(row, 70, drafts=2, now=NOW)
    first = joined(lines[0])
    assert len(lines) == 1 and len(first) == 70, (len(first), first)  # one line per pull request, number first
    assert first.startswith("app #7  draft   chg   ci:x   *2   SA  1d A rather long") and first.endswith("..."), first
    chips = [style for _text, style in lines[0] if style.startswith("chip-")]
    assert chips == ["chip-dim", "chip-bad", "chip-bad", "chip-draft"], chips  # each chip its own badge
    narrow = joined(core.list_row_lines(row, 40, drafts=2, now=NOW)[0])
    assert (
        len(narrow) <= 40 and "rather" not in narrow and narrow.startswith("app #7 ")
    )  # no title, number and chips stay
    assert joined(core.list_row_lines(row, 70, show_owner=True, now=NOW)[0]).startswith("acme/app #7 ")
    nerd = joined(core.list_row_lines(row, 70, icons=core.NERD, now=NOW)[0])
    assert "" in nerd and "ci:x" not in nerd
    other = parse.parse_rows([search_node(1234, repo="acme/platform", decision="APPROVED", checks="SUCCESS")])[0]
    other.merge_state = "BEHIND"
    columns = core.list_columns([row, other], 90, counts={row.key: 2})
    texts = [
        joined(core.list_row_lines(r, 90, drafts=d, columns=columns, now=NOW)[0]) for r, d in ((row, 2), (other, 0))
    ]
    assert texts[0].index("SA") == texts[1].index("SA") and texts[0].index("ci:x") == texts[1].index(
        "ci:ok"
    )  # columns line up
    assert "behind" in texts[1] and texts[1].startswith("platform #1234 ")


def test_a_view_row_wraps_under_its_gutter():
    diff_row = core.ViewRow("add", "x" * 30, number="13", marker="+")
    wrapped = core.view_row_lines(diff_row, 20, 2)
    assert [joined(line) for line in wrapped] == ["13 + " + "x" * 15, "     " + "x" * 15]
    thread_row = core.ViewRow("comment", "ann 2d\nsome words here", marker="|")
    assert [joined(line) for line in core.view_row_lines(thread_row, 14, 2)] == [
        "   | ann 2d",
        "     some",
        "     words",
        "     here",
    ]


def test_icon_sets():
    """--icons auto: nerd only where the terminal ships Nerd Font symbols, unicode on a UTF-8 locale, else ascii; every
    glyph one cell wide, and every set names the same chips."""
    from morann.textfmt import ASCII, NERD, UNICODE, pick_icons, width_of

    assert (
        pick_icons("auto", {"TERM": "xterm-kitty"}) is NERD and pick_icons("auto", {"TERM_PROGRAM": "WezTerm"}) is NERD
    )
    assert pick_icons("auto", {"TERM": "xterm-ghostty", "LANG": "C"}) is NERD
    assert pick_icons("auto", {"TERM": "xterm-256color", "LANG": "en_US.UTF-8"}) is UNICODE
    assert pick_icons("auto", {"TERM": "xterm-256color", "LC_ALL": "C"}) is ASCII and pick_icons("auto", {}) is ASCII
    assert pick_icons("auto", {"TERM": "xterm-kitty", "MORANN_ICONS": "ascii"}) is ASCII
    assert pick_icons("unicode", {"TERM": "xterm-kitty"}) is UNICODE and pick_icons("nerd", {}) is NERD
    assert ASCII.keys() == UNICODE.keys() == NERD.keys()
    assert all(width_of(glyph) == 1 for key, glyph in UNICODE.items() if glyph != ASCII[key])
