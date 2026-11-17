# SPDX-FileCopyrightText: 2026 Cristiano Carvalho
# SPDX-License-Identifier: Apache-2.0
"""How Morann draws: colors, markdown, syntax, avatars and badges, and the Painter that turns core's rows into screen lines for the current theme."""

from __future__ import annotations

import io
import re
import zlib
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import replace
from datetime import datetime
from functools import lru_cache, partial
from typing import TYPE_CHECKING, Any

from pygments.lexers import get_lexer_for_filename
from pygments.lexers.special import TextLexer
from pygments.token import Comment, Keyword, Literal, Name, Number, Operator, String
from pygments.util import ClassNotFound
from rich.console import Console
from rich.markdown import Markdown
from rich.segment import Segment
from rich.style import Style
from rich.text import Text
from rich.theme import Theme
from textual.color import Color
from textual.strip import Strip

from morann import core, markdown, palette, theme

if TYPE_CHECKING:
    from morann.textfmt import Piece
    from morann.views import Columns, TabLabel, ViewRow

Drawn = Strip | Callable[[], Strip]  # one screen line of a row: drawn already, or drawn when it is first shown

STYLES: dict[str, tuple[str, tuple[str, ...]]] = {  # a row style's design token and its weight
    "gutter": ("muted", ()),
    "dim": ("muted", ()),
    "label": ("", ("bold",)),
    "title": ("", ("bold",)),
    "add": ("ok", ()),
    "del": ("bad", ()),
    "hunk": ("info", ()),
    "note": ("muted", ("italic",)),
    "file": ("", ("bold",)),
    "info": ("warn", ()),
    "heading": ("muted", ()),
    "thread": ("warn", ()),
    "draft": ("local", ()),
    "accent": ("accent", ("bold",)),
    "ok": ("ok", ()),
    "bad": ("bad", ()),
    "wait": ("warn", ()),
    "flag-failing": ("bad", ("bold",)),
    "flag-changes": ("bad", ("bold",)),
    "flag-conflict": ("bad", ("bold",)),
    "flag-behind": ("warn", ("bold",)),
    "flag-new": ("info", ("bold",)),
}
CHIPS = {"chip-ok": "ok", "chip-bad": "bad", "chip-wait": "warn", "chip-dim": "muted", "chip-draft": "local"}
CHIPS |= {"chip-label": "info", "chip-done": "merged"}


BADGE = {  # a badge's text and its design token
    "resolved": "ok",
    "open": "warn",
    "yours": "info",
    "your turn": "accent",
    "edited": "muted",
    "approved": "ok",
    "outdated": "warn",
    "\u2713": "ok",
    "\u00d7": "bad",
    "\u2022": "warn",
    "-": "info",
    "Open": "ok",
    "Draft": "muted",
    "Merged": "merged",
    "Closed": "bad",
    "draft": "local",
    "pending": "local",
    "reply": "local",
    "summary": "local",
    "comment": "local",
    "pass": "ok",
    "fail": "bad",
    "running": "warn",
    "cancelled": "warn",
    "skipped": "info",
    "required": "info",
}


AVATAR = ("bad", "ok", "warn", "info", "merged", "accent")  # an author's initials take one, by their login


ANSI_SYNTAX = {  # the terminal's colors for code
    "comment": Style(dim=True, italic=True),
    "keyword": Style(color="magenta"),
    "function": Style(color="blue"),
    "class": Style(color="yellow"),
    "decorator": Style(color="cyan"),
    "builtin": Style(color="cyan"),
    "tag": Style(color="blue"),
    "attribute": Style(color="yellow"),
    "string": Style(color="green"),
    "number": Style(color="cyan"),
    "literal": Style(color="cyan"),
}


TOKENS = (  # pygments token kinds, the most specific first, and what SYNTAX calls each
    (Comment, "comment"),
    (Keyword, "keyword"),
    (Operator.Word, "keyword"),
    (Name.Function, "function"),
    (Name.Class, "class"),
    (Name.Decorator, "decorator"),
    (Name.Builtin, "builtin"),
    (Name.Tag, "tag"),
    (Name.Attribute, "attribute"),
    (String, "string"),
    (Number, "number"),
    (Literal, "literal"),
)


def syntax_styles(tokens: theme.Tokens | None) -> dict[str, Style]:
    """The styles code is highlighted with: a color scheme's colors, or the terminal's without one."""
    if tokens is None:
        return ANSI_SYNTAX
    colors = theme.syntax_colors(tokens)
    return {kind: Style(color=colors[kind], italic=kind == "comment" or None) for kind in ANSI_SYNTAX}


def markdown_theme(tokens: theme.Tokens | None) -> Theme:
    """Rich's markdown styles in a color scheme's colors, or the terminal's without one; a link's text in the link
    color, underlined."""
    code = tokens.accent if tokens else "cyan"
    quiet = tokens.muted if tokens else "dim"
    link = f"{tokens.info if tokens else 'blue'} underline"
    return Theme(
        {
            "markdown.code": f"bold {code}",
            "markdown.code_block": code,
            "markdown.block_quote": quiet,
            "markdown.hr": quiet,
            "markdown.link": link,
            "markdown.link_url": link,
            "markdown.h1": "bold underline",
            "markdown.h2": "bold underline",
            "markdown.h3": "bold",
            "markdown.h4": "bold",
            "markdown.item.bullet": "bold",
            "markdown.item.number": "bold",
        }
    )


PLAIN = Console(file=io.StringIO(), width=1000, color_system="standard", force_terminal=True)


@lru_cache(maxsize=1024)
def markdown_lines(
    body: str, width: int, dark: bool, tokens: theme.Tokens | None = None, links: bool = False
) -> tuple[tuple[Segment, ...], ...]:
    """A comment's markdown as screen lines of segments: headings, lists, quotes, tables, code and emphasis, and every
    link as its text in the link style, never its raw form. With `links` a web link is also a terminal hyperlink
    (OSC 8); without, the text alone shows and gx opens or copies the address. Cached per width, scheme and links;
    without a scheme it draws in the terminal's colors."""
    code_theme = "ansi_dark" if dark else "ansi_light"
    rendered = Markdown(core.trim_html(body) or " ", code_theme=code_theme, hyperlinks=True)
    with PLAIN.use_theme(markdown_theme(tokens)):
        lines = PLAIN.render_lines(rendered, PLAIN.options.update(width=max(10, width)), pad=False)
    return tuple(tuple(hyperlink(segment, links) for segment in line) for line in lines)


def hyperlink(segment: Segment, links: bool) -> Segment:
    """The segment, keeping its hyperlink only where the terminal shows them and the link goes to http or https."""
    style = segment.style
    if style is None or not style.link or links and style.link.startswith(markdown.WEB):
        return segment
    return Segment(segment.text, style.update_link(None))


@lru_cache(maxsize=256)
def lexer_for(path: str) -> Any:
    try:
        return get_lexer_for_filename(path, stripnl=False, ensurenl=False)
    except ClassNotFound:
        return TextLexer(stripnl=False, ensurenl=False)


def token_kind(kind: Any) -> str:
    return next((name for token, name in TOKENS if kind in token), "")


@lru_cache(maxsize=8192)
def code_text(path: str, text: str, tokens: theme.Tokens | None = None) -> Text:
    """One line of code with its syntax colors, in a color scheme's or the terminal's. Each diff line is read alone,
    which is how a diff shows it."""
    styles = syntax_styles(tokens)
    out = Text(end="")
    for kind, value in lexer_for(path).get_tokens(text):
        out.append(value.replace("\n", ""), styles.get(token_kind(kind), Style()))
    return out


def wrap_offsets(plain: str, width: int) -> list[int]:
    """Where a line of code breaks into screen lines of at most `width` cells, at any character, so code keeps its
    spacing. Needs no highlighting, so a row's height is known before its colors are."""
    offsets: list[int] = []
    used = 0
    for index, ch in enumerate(plain):
        cells = core.cell_width(ch)
        if used + cells > width and index:
            offsets.append(index)
            used = 0
        used += cells
    return offsets


def wrap_text(text: Text, width: int) -> list[Text]:
    """A Text cut into pieces of at most `width` cells, at any character, so code keeps its spacing."""
    return list(text.divide(wrap_offsets(text.plain, width))) or [Text(end="")]


class Lazy:
    """The screen lines of one row, built the first time any of them is drawn. A diff of thousands of lines is laid out
    for what its rows need in height, and highlighted only for the lines that reach the screen."""

    __slots__ = ("lines", "make")

    def __init__(self, make: Callable[[], list[Strip]]) -> None:
        self.make = make
        self.lines: list[Strip] | None = None

    def __call__(self, index: int) -> Strip:
        if self.lines is None:
            self.lines = self.make()
        return self.lines[index]

    def strips(self, count: int) -> list[Callable[[], Strip]]:
        """One callable per screen line; Rows replaces each with its strip when it is first drawn."""
        return [partial(self, index) for index in range(count)]


HUNK_HEAD = re.compile(r"^(@@[^@]*@@)\s?(.*)$")


def initials(login: str) -> str:
    parts = [part for part in login.replace("_", "-").replace(".", "-").split("-") if part] or ["?"]
    return (parts[0][0] + (parts[1][0] if len(parts) > 1 else parts[0][1:2])).upper()


class Painter:
    """Turns core's rows into screen lines for the current theme, in its design tokens (see theme.py). In a color
    scheme on a terminal with 24-bit color the diff pane is drawn like github.com's diff view (tinted lines, the changed
    words, a hunk band, the line numbers in their line's color) in the scheme's own colors. In the terminal's colors,
    or under NO_COLOR, an edit is marked with colored blocks and nothing is tinted."""

    def __init__(self, app: Any) -> None:
        self.app = app  # the Morann app: its theme, and whether it shows color and 24-bit color
        self.reset()

    def reset(self) -> None:
        current = self.app.current_theme
        scheme = None if current.ansi else self.app.schemes.get(current.name)
        self.ansi = scheme is None
        self.scheme = scheme.tokens if scheme is not None else None  # what markdown and code are colored with
        tokens = self.scheme or theme.TERMINAL
        self.dark = tokens.dark if scheme is not None else bool(current.dark)
        self.ink = theme.Ink(tokens)
        self.styles = {
            name: self.ink(token, bold="bold" in weight, italic="italic" in weight)
            for name, (token, weight) in STYLES.items()
        }
        self.styles |= {name: self.ink.chip(token) for name, token in CHIPS.items()}
        self.zebra = self.cursor_bg = None
        if self.ink.truecolor:
            self.zebra = Style(bgcolor=theme.blend(tokens.text, tokens.background, 0.025))
            self.cursor_bg = Style(bgcolor=tokens.selection, bold=True)
        colors = self.app.terminal_colors  # what the terminal said its colors are, or None
        self.tint = palette.choose(
            truecolor=self.app.truecolor,
            no_color=self.app.no_color,
            dark=(colors.dark if colors else self.app.dark_terminal) if self.ansi else self.dark,
            terminal_theme=self.ansi,
            colors=colors,
        )
        self.blended = self.tint is not None and self.tint is not palette.ANSI  # 24-bit tints the cursor can lift
        self.emphasis, self.marker = {}, {}  # the changed words of an edited line and the + or - cell, by line kind
        self.add_bg = self.del_bg = self.hunk_bg = self.hunk_num = self.muted = None
        self.numbers = {}  # the line numbers' style by line kind
        self.mark = {"add": self.ink("ok", bold=True), "del": self.ink("bad", bold=True)}
        if self.tint is None:
            for kind, token in (("add", "ok"), ("del", "bad")):  # the terminal's colors only: a colored block, no tint
                self.emphasis[kind] = Style(color=self.ink.color(token), bold=True, reverse=True)
                self.marker[kind] = self.emphasis[kind]
                self.numbers[kind] = self.mark[kind]
            return
        tint = self.tint
        text = tint.text or None  # the terminal's own foreground when it did not say what it is
        self.add_bg = Style(color=text, bgcolor=tint.add_line)
        self.del_bg = Style(color=text, bgcolor=tint.del_line)
        self.hunk_bg, self.hunk_num = (
            Style(color=tint.muted or None, bgcolor=tint.hunk_line),
            Style(bgcolor=tint.hunk_num),
        )
        self.muted = Style(color=tint.muted) if self.blended else Style(dim=True)  # context line numbers
        for kind, word, number in (("add", tint.add_word, tint.add_num), ("del", tint.del_word, tint.del_num)):
            self.emphasis[kind] = Style(bgcolor=word, bold=not self.blended or None)
            self.marker[kind] = Style()
            self.numbers[kind] = Style(color=text, bgcolor=number)

    def markdown(self, body: str, width: int) -> tuple[tuple[Segment, ...], ...]:
        return markdown_lines(body, width, self.dark, self.scheme, self.app.hyperlinks)

    def style(self, name: str) -> Style:
        """A row style (dim, ok, chip-bad, flag-new...) in the current theme."""
        return self.styles.get(name, Style())

    def avatar(self, login: str) -> Segment:
        """An author's initials as a small block in a color their login always gets."""
        return Segment(f" {initials(login)} ", self.avatar_style(login))

    def avatar_style(self, login: str) -> Style:
        return self.ink.chip(AVATAR[zlib.crc32((login or "?").encode()) % len(AVATAR)], bold=True)

    def badge(self, name: str) -> Segment:
        """A short label (resolved, draft, required...) as a pill in its status color."""
        if name.startswith("pending on "):  # a comment still in a review on the forge's own site
            token = "warn"
        else:
            token = BADGE.get(name, "bad" if "gone" in name or "changed" in name or "requested" in name else "info")
        return Segment(f" {name} ", self.ink.chip(token))

    def cursor(self, focused: bool) -> Style:
        if not focused:
            return Style(underline=True)
        return self.cursor_bg if self.cursor_bg is not None else Style(reverse=True)

    def cursor_strip(self, strip: Strip, focused: bool, tinted: bool = False) -> Strip:
        """A row's strip with the cursor on it. A tinted diff row keeps its colors and moves each toward the palette's
        cursor color, since a background laid over a tint would be hidden by it."""
        if tinted and focused and self.tint is palette.ANSI:  # a fill would sit under the line's own green or red
            return strip.apply_style(Style(reverse=True))
        if not (tinted and focused and self.blended and self.tint is not None):
            return strip.apply_style(self.cursor(focused))
        aim, page = Color.parse(self.tint.cursor), Color.parse(self.tint.page)
        lifted = []
        for segment in strip:
            style = segment.style or Style()
            if not style.reverse:  # a badge drawn as a block keeps its look
                start = Color.from_rich_color(style.bgcolor) if style.bgcolor is not None else page
                style += Style(bgcolor=start.blend(aim, palette.CURSOR_SHARE).rich_color)
            lifted.append(Segment(segment.text, style))
        return Strip(lifted, strip.cell_length)

    @staticmethod
    def strip(segments: Iterable[Segment], width: int, base: Style | None = None) -> Strip:
        strip = Strip([segment for segment in segments if segment.text]).adjust_cell_length(width)
        return strip.apply_style(base) if base is not None else strip

    def pairs(self, line: Iterable[Piece], width: int, base: Style | None = None) -> Strip:
        return self.strip([Segment(text, self.style(style)) for text, style in line], width, base)

    def list_row(
        self,
        row: Any,  # a pull request, a repository header, or a line of text with a style
        width: int,
        index: int,
        counts: Mapping[str, int],
        scope: core.Scope,
        icons: Mapping[str, str],
        now: datetime | None,
        columns: Columns | None = None,
        show_author: bool = False,
        flags: Mapping[str, str] | None = None,
        waits: Mapping[str, tuple[str, str]] | None = None,
    ) -> list[Strip]:
        if isinstance(row, core.GroupRow):
            mark = "+" if row.collapsed else "-"
            flagged = [Segment(f"  {row.flagged} flagged", self.style("bad"))] if row.flagged else []
            return [
                self.strip(
                    [
                        Segment(f"{mark} ", self.ink("subtle")),
                        Segment(row.repo, self.ink("accent", bold=True)),
                        Segment(f"  {row.count} open", self.ink("muted")),
                        *flagged,
                    ],
                    width,
                )
            ]
        if not isinstance(row, core.PrRow):
            style = self.ink("muted", bold=True) if row.style == "heading" else self.style(row.style)
            return [self.strip([Segment(core.cut(row.text, width), style)], width)]
        base = self.zebra if self.zebra is not None and index % 2 else None
        lines = core.list_row_lines(
            row,
            width,
            drafts=counts.get(row.key, 0),
            show_owner=scope.several_owners(),
            icons=icons,
            now=now,
            columns=columns,
            flag=(flags or {}).get(row.key, ""),
            wait=(waits or {}).get(row.key),
        )
        return [
            self.strip(
                [
                    Segment(
                        text,
                        self.avatar_style(row.author) if style == "initials" else self.style(style),
                    )
                    for text, style in line
                ],
                width,
                base,
            )
            for line in lines
        ]

    def tone(self, style: str) -> Style:
        """A panel style in the theme's colors: label is the accent in bold, the rest as `style` names them."""
        return self.ink("accent", bold=True) if style == "label" else self.style(style)

    def details(self, row: object, width: int, limit: int, icons: Mapping[str, str], now: datetime | None) -> Text:
        """The details panel's body: core.panel_lines in the theme's colors."""
        lines = core.panel_lines(row, width, limit, icons=icons, now=now)
        return Text("\n").join(Text.assemble(*[(text, self.tone(style)) for text, style in line]) for line in lines)

    def panel_title(self, row: object) -> Text:
        return Text.assemble(*[(text, self.tone(style)) for text, style in core.panel_title(row)])

    def tab_text(self, label: TabLabel, ascii_badge: bool) -> Text:
        """A tab: its key dimmed like a keycap, its name, and its count as a badge that never looks like the key, a
        pill (a bracketed count with the ASCII glyphs) in the color of what it means."""
        out = Text(end="")
        out.append(label.key, self.ink("subtle" if self.ink.truecolor else "muted"))
        out.append(f" {label.name}")
        if label.count:
            token = {"accent": "accent", "bad": "bad"}.get(label.tone, "muted")
            if ascii_badge:
                out.append(f" [{label.count}]", self.ink(token, bold=True))
            else:
                out.append(" ")
                out.append(f" {label.count} ", self.ink.chip(token, bold=True))
        return out

    def state_chip(self, state: str) -> Text:
        """The state badge beside a pull request's title: Open, Draft, Merged or Closed."""
        token = {"Open": "ok", "Merged": "merged", "Closed": "bad"}.get(state, "muted")
        return Text(f" {state} ", self.ink.chip(token, bold=True))

    def diff_row(self, row: ViewRow, width: int, number_width: int) -> Sequence[Drawn]:
        if row.pair is not None:
            return self.pair(row, width, number_width)
        if row.kind == "commit":
            head = [
                Segment(f"{row.number} ", self.ink("warn")),
                Segment(core.cut(core.clean(row.body), max(0, width - 10))),
            ]
            meta = [
                Segment("        "),
                self.avatar(row.author),
                Segment(f" {row.author} {row.when}", self.ink("muted")),
            ]
            return [self.strip(head, width), self.strip(meta, width)]
        if row.kind == "check":
            head = [segment for name in row.badges for segment in (self.badge(name), Segment(" "))]
            used = sum(len(segment.text) for segment in head)
            head.append(Segment(core.cut(core.clean(row.body), max(0, width - used))))
            lines = [self.strip(head, width)]
            if row.when:  # a failure's reason in the error color, so it reads without leaving the app
                lines.append(
                    self.strip(
                        [
                            Segment(
                                f"  {core.cut(row.when, max(0, width - 2))}",
                                self.ink("bad") if row.style == "bad" else self.ink("muted"),
                            )
                        ],
                        width,
                    )
                )
            return lines
        if row.kind in ("add", "del", "ctx") and row.anchor or row.kind == "more":
            return self.code(row, width, number_width)
        if row.kind == "file" and row.counts:
            return self.file_header(row, width)
        if row.kind == "hunk":
            return [self.hunk_header(row, width, number_width)]
        if row.marker == "|" and (row.body or row.author or row.badges):
            return self.card(row, width, number_width)
        if row.kind == "text" and row.body:
            return [self.strip(line, width) for line in self.markdown(row.body, width)]
        if row.kind == "text" and row.badges:  # a line led by its badges, such as the pull request's state
            head = [segment for name in row.badges for segment in (self.badge(name), Segment(" "))]
            used = sum(len(segment.text) for segment in head)
            return [
                self.strip(
                    [*head, Segment(core.cut(core.clean(row.text), max(0, width - used)), self.ink("muted"))], width
                )
            ]
        return [self.pairs(line, width) for line in core.view_row_lines(row, width, number_width)]

    def file_header(self, row: ViewRow, width: int) -> list[Strip]:
        """A file's name in bold with its added and removed counts, on a heavy rule that runs to the pane's edge."""
        rule = self.ink("subtle")
        head = Text(end="")
        head.append("━━ ", rule)
        head.append(row.body, Style(bold=True))
        head.append(f"  +{row.counts[0]}", self.mark["add"])
        head.append(f" -{row.counts[1]}", self.mark["del"])
        for badge_name in row.badges:
            head.append(f"  {badge_name}", self.ink("muted"))
        lines = [list(piece.render(PLAIN)) for piece in wrap_text(head, width)]
        left = width - sum(core.width_of(segment.text) for segment in lines[-1]) - 1
        if left > 0:
            lines[-1].append(Segment(" " + "━" * left, rule))
        return [self.strip(line, width) for line in lines]

    def hunk_header(self, row: ViewRow, width: int, number_width: int) -> Strip:
        """A hunk's line ranges, dimmed, then the code it sits in (a function name) in full, on a rule. In github's colors
        it is github's band instead: blue over the line-number columns, a lighter blue under the text."""
        found = HUNK_HEAD.match(core.clean(row.text))
        ranges, context = (found[1], found[2]) if found else (core.clean(row.text), "")
        if self.tint:
            numbers, _marker = core.diff_gutter(row, number_width, width)
            gutter = len(" ".join(numbers)) + 1
            text = core.cut(f"{ranges} {context}".rstrip(), max(0, width - gutter - 1))
            return self.strip([Segment(" " * gutter, self.hunk_num), Segment(" " + text)], width, self.hunk_bg)
        quiet = self.ink("info") + Style(dim=True)
        lead = [Segment("── ", quiet), Segment(ranges, quiet)]
        room = width - sum(core.width_of(segment.text) for segment in lead) - 3
        if context and room >= 4:
            lead += [Segment(" "), Segment(core.cut(context, room), self.ink("info"))]
        left = width - sum(core.width_of(segment.text) for segment in lead) - 1
        if left > 0:
            lead.append(Segment(" " + "─" * left, quiet))
        return self.strip(lead, width)

    def pair(self, row: ViewRow, width: int, number_width: int) -> list[Callable[[], Strip]]:
        """Side by side: the old file's line on the left, the new file's on the right, each with its own number and
        tint, a thin rule between; a side with no line stays blank. Drawn when first shown, as code lines are."""
        half = (width - 1) // 2
        other = width - 1 - half
        left, right = row.pair or (None, None)

        def side(item: ViewRow | None, cells: int, number: str) -> list[Callable[[], Strip]]:
            if item is None:
                return []
            single = replace(item, old="", new="", number=number or item.number)
            return self.code(single, cells, number_width)

        lefts = side(left, half, left.old if left is not None else "")
        rights = side(right, other, right.new if right is not None else "")
        height = max(len(lefts), len(rights), 1)
        rule = Strip([Segment("\u2502", self.ink("subtle"))], 1)

        def make() -> list[Strip]:
            lines = []
            for at in range(height):
                old = lefts[at]() if at < len(lefts) else Strip.blank(half)
                new = rights[at]() if at < len(rights) else Strip.blank(other)
                lines.append(Strip.join([old.crop_extend(0, half, None), rule, new.crop_extend(0, other, None)]))
            return lines

        return Lazy(make).strips(height)

    def code(self, row: ViewRow, width: int, number_width: int) -> list[Callable[[], Strip]]:
        """A line of code: old and new line numbers, a marker cell, then the highlighted text wrapped under itself. An
        edited line shows its changed words in a stronger color. The colors are made when a line is first drawn."""
        numbers, marker = core.diff_gutter(row, number_width, width)
        lead_width = len(" ".join(numbers)) + 3
        text = core.clean(row.text)
        offsets = wrap_offsets(text, max(10, width - lead_width))
        return Lazy(partial(self.code_lines, row, text, offsets, width, numbers, marker)).strips(len(offsets) + 1)

    def code_lines(
        self, row: ViewRow, text: str, offsets: list[int], width: int, numbers: list[str], marker: str
    ) -> list[Strip]:
        if self.tint is palette.ANSI and row.kind in (
            "add",
            "del",
        ):  # syntax colors would vanish on a green or red line
            styled = Text(text, end="")
        else:
            styled = code_text(row.path or (row.anchor[0] if row.anchor else ""), text, self.scheme)
        if row.marks:
            styled = styled.copy()
            for start, end in row.marks:
                styled.stylize(self.emphasis[row.kind], start, end)
        base = {"add": self.add_bg, "del": self.del_bg}.get(row.kind)
        changed = row.kind in ("add", "del")
        active = 0 if row.kind == "del" else len(numbers) - 1  # the number of the file the line belongs to
        reach = len(" ".join(numbers)) + 1  # the gutter's cells, which github colors as one block
        lines = []
        for index, piece in enumerate(styled.divide(offsets) if offsets else [styled]):
            if index:  # a wrapped line keeps its gutter's color, with no number
                lead = [
                    Segment(" " * reach, self.numbers[row.kind] if self.tint and changed else Style()),
                    Segment("  "),
                ]
            else:
                lead = []
                for at, number in enumerate(numbers):
                    if self.tint:
                        style = self.numbers[row.kind] if changed else self.muted
                    else:
                        style = self.mark[row.kind] if changed and at == active else self.ink("muted")
                    lead += [
                        Segment(number, style),
                        Segment(" ", style if self.tint and changed else Style(dim=not self.tint)),
                    ]
                lead += [Segment(marker, self.marker[row.kind] if changed else Style(dim=True)), Segment(" ")]
            lines.append(self.strip([*lead, *piece.render(PLAIN)], width, base))
        return lines

    def card(self, row: ViewRow, width: int, number_width: int) -> list[Strip]:
        """A thread comment, a draft or a pending reply as a card: a colored left border, initials, author, age and
        badges, then the markdown body."""
        indent = Segment(" " * (number_width + 1))
        token = "local" if row.kind == "draft" else "bad" if row.style == "bad" else "warn"
        border = Segment("▌ ", self.ink("subtle" if row.style == "dim" else token))
        head = [indent, border]
        if row.author:
            head += [
                self.avatar(row.author),
                Segment(" "),
                Segment(row.author, Style(bold=True)),
                Segment(f" {row.when}", self.ink("muted")),
            ]
        for name in row.badges:
            head += [Segment(" "), self.badge(name)]
        room = width - number_width - 3
        if row.kind == "thread":  # a thread's first line: collapsed with its first words, or open
            used = sum(len(segment.text) for segment in head[2:])
            text = core.cut(core.clean(row.body), max(0, room - used - 1))
            return [self.strip([*head, Segment(" "), Segment(text, self.ink("muted"))], width)]
        lines = [self.strip(head, width)]
        lines += [self.strip([indent, border, *line], width) for line in self.markdown(row.body, room)]
        return lines
