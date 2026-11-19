# SPDX-FileCopyrightText: 2026 Cristiano Carvalho
# SPDX-License-Identifier: Apache-2.0
"""Morann's design tokens: the semantic colors every part of the UI draws with, and the themes that fill them.

Code never names a raw color. It asks for a token (ok, bad, warn, accent, muted...) and `Ink` answers with a style in
the current theme. The default theme is One Dark. The terminal theme fills every token with the terminal's own default
colors and its 16 ANSI colors and paints no background, so Morann takes on whatever theme the terminal has. The other
themes are named color schemes (Catppuccin, Tokyo Night, Gruvbox, Nord, Rose Pine, One Dark, GitHub), each a TOML
file: the built-in ones in morann/themes, and your own in ~/.config/morann/themes (MORANN_THEMES names another
folder)."""

from __future__ import annotations

import os
import re
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass, fields
from pathlib import Path

from rich.color import Color as RichColor
from rich.style import Style
from textual.theme import Theme

from morann.settings import UsageError, config_path, config_value


@dataclass(frozen=True)
class Tokens:
    """One palette. A value is a hex color, an ANSI color name, or "" for the terminal's default color drawn dim (the
    muted tokens) or plain (the others)."""

    dark: bool
    background: str  # the page
    surface: str  # bars: the header, the hint line, a pull request's header
    panel: str  # raised blocks: dialogs, the details panel's fill
    border: str  # a frame at rest
    text: str
    muted: str  # secondary text: ages, counts, hints
    subtle: str  # what should almost disappear: rules, separators, skeleton rows
    accent: str  # focus, the brand, the active tab, links
    ok: str  # passing, approved, added
    bad: str  # failing, changes requested, conflicts, removed
    warn: str  # pending, waiting, behind its base
    info: str  # new activity, labels, required checks
    merged: str  # merged pull requests, commits
    local: str  # your unsent drafts, which exist only on this machine
    selection: str  # the cursor row's fill in the focused pane

    def get(self, name: str) -> str:
        value: str = getattr(self, name)
        return value


TOKEN_NAMES = tuple(f.name for f in fields(Tokens) if f.name != "dark")
REQUIRED = ("background", "text", "accent", "ok", "bad", "warn", "info", "merged")  # a scheme file must set these
DERIVED = {  # the rest, when a scheme leaves them out: (token, laid over the background at this share)
    "surface": ("text", 0.04),
    "panel": ("text", 0.08),
    "border": ("text", 0.2),
    "muted": ("text", 0.65),
    "subtle": ("text", 0.4),
    "local": ("merged", 1.0),
    "selection": ("accent", 0.25),
}
HEX = re.compile(r"#[0-9a-fA-F]{6}")

# The terminal's own colors: its default foreground and background and its 16 ANSI colors.
TERMINAL = Tokens(
    dark=True,
    background="",
    surface="",
    panel="",
    border="",
    text="",
    muted="",
    subtle="",
    accent="cyan",
    ok="green",
    bad="red",
    warn="yellow",
    info="blue",
    merged="magenta",
    local="magenta",
    selection="",
)

TERMINAL_NAME = "terminal"  # the name of the terminal's own colors
DEFAULT = "one-dark"  # the theme when --theme, MORANN_THEME and the config's theme line are all unset
ALIASES = {"github": "github-dark", "builtin": "github-dark", "": DEFAULT}  # names earlier versions used
BUILT_IN = Path(__file__).with_name("themes")


@dataclass(frozen=True)
class Scheme:
    name: str  # the name --theme takes: the file's name without .toml
    title: str  # as people know it: Catppuccin Mocha
    tokens: Tokens


def user_folder(environ: Mapping[str, str]) -> Path:
    """Where your own scheme files go: MORANN_THEMES, else a themes folder beside the config file."""
    named = environ.get("MORANN_THEMES")
    return Path(named) if named else config_path(environ).parent / "themes"


def load_scheme(path: Path) -> Scheme:
    """A scheme file: `name`, `dark`, and a [colors] table of tokens as #rrggbb. REQUIRED must be there; DERIVED is
    filled in from them when left out. Anything wrong is a UsageError naming the file."""
    try:
        data = tomllib.loads(path.read_text())
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError) as error:
        raise UsageError(f"cannot read the theme {path}: {error}") from None
    colors = data.get("colors")
    if not isinstance(colors, dict):
        raise UsageError(f"the theme {path} has no [colors] table")
    unknown = sorted(set(colors) - set(TOKEN_NAMES))
    missing = [name for name in REQUIRED if name not in colors]
    bad = sorted(name for name, value in colors.items() if not (isinstance(value, str) and HEX.fullmatch(value)))
    for problem, names in (("unknown colors", unknown), ("missing colors", missing), ("not #rrggbb", bad)):
        if names:
            raise UsageError(f"the theme {path}: {problem}: {', '.join(names)}")
    filled = {name: value.lower() for name, value in colors.items()}
    for name, (base, share) in DERIVED.items():
        filled.setdefault(name, blend(filled[base], filled["background"], share))
    return Scheme(path.stem, str(data.get("name") or path.stem), Tokens(dark=data.get("dark") is not False, **filled))


def schemes(environ: Mapping[str, str] | None = None) -> dict[str, Scheme]:
    """Every scheme by name: the built-in ones, then yours, which win over a built-in of the same name."""
    environ = os.environ if environ is None else environ
    found = {}
    for folder in (BUILT_IN, user_folder(environ)):
        for path in sorted(folder.glob("*.toml")) if folder.is_dir() else ():
            scheme = load_scheme(path)
            found[scheme.name] = scheme
    return found


def chosen(flag: str | None, environ: Mapping[str, str] | None = None) -> str:
    """The theme to start with: --theme, else MORANN_THEME, else the config file's `theme = NAME` line, else One
    Dark."""
    environ = os.environ if environ is None else environ
    value = flag or environ.get("MORANN_THEME") or config_value("theme", environ) or ""
    name = value.strip().lower()
    return ALIASES.get(name, name)


def check(name: str, known: Mapping[str, Scheme]) -> str:
    """The name, when it is the terminal's colors or a scheme; else a UsageError listing the names there are."""
    if name == TERMINAL_NAME or name in known:
        return name
    raise UsageError(f"no theme named {name!r}; there are: {', '.join([TERMINAL_NAME, *sorted(known)])}")


def textual_theme(name: str, tokens: Tokens) -> Theme:
    """A Textual theme that paints its widgets (borders, inputs, scrollbars, the cursor) from the tokens."""
    return Theme(
        name=name,
        primary=tokens.accent,
        secondary=tokens.merged,
        accent=tokens.accent,
        warning=tokens.warn,
        error=tokens.bad,
        success=tokens.ok,
        foreground=tokens.text,
        background=tokens.background,
        surface=tokens.surface,
        panel=tokens.panel,
        dark=tokens.dark,
        variables={
            "border": tokens.accent,
            "border-blurred": tokens.border,
            "foreground-muted": tokens.muted,
            "text-muted": tokens.muted,
            "block-cursor-background": tokens.selection,
            "block-cursor-foreground": tokens.text,
            "block-cursor-text-style": "bold",
            "block-cursor-blurred-background": tokens.panel,
            "block-hover-background": tokens.panel,
            "input-selection-background": tokens.selection,
            "scrollbar": tokens.border,
            "scrollbar-hover": tokens.subtle,
            "scrollbar-active": tokens.accent,
            "scrollbar-background": tokens.background,
        },
    )


def terminal_theme() -> Theme:
    """The terminal's colors: its default foreground and background (no background of Morann's own) and its 16 ANSI
    colors, with cyan as the accent. Hierarchy comes from bold, dim and reverse, not from shades."""
    return Theme(
        name=TERMINAL_NAME,
        ansi=True,
        primary="ansi_cyan",
        secondary="ansi_magenta",
        warning="ansi_yellow",
        error="ansi_red",
        success="ansi_green",
        accent="ansi_cyan",
        foreground="ansi_default",
        background="ansi_default",
        surface="ansi_default",
        panel="ansi_default",
        boost="ansi_default",
        dark=True,
        variables={
            "ansi-background": "ansi_default",
            "ansi-foreground": "ansi_default",
            "border": "ansi_cyan",
            "border-blurred": "ansi_bright_black",
            "foreground-muted": "ansi_bright_black",
            "text-muted": "ansi_bright_black",
            "block-cursor-foreground": "ansi_black",
            "block-cursor-background": "ansi_cyan",
            "block-cursor-text-style": "bold",
            "block-cursor-blurred-background": "ansi_default",
            "block-hover-background": "ansi_default",
            "input-cursor-background": "ansi_default",
            "input-cursor-foreground": "ansi_default",
            "input-cursor-text-style": "reverse",
            "input-selection-background": "ansi_cyan",
            "input-selection-foreground": "ansi_black",
            "screen-selection-background": "ansi_cyan",
            "screen-selection-foreground": "ansi_black",
            "scrollbar": "ansi_bright_black",
            "scrollbar-hover": "ansi_cyan",
            "scrollbar-active": "ansi_cyan",
            "scrollbar-background": "ansi_default",
            "scrollbar-background-hover": "ansi_default",
            "scrollbar-background-active": "ansi_default",
            "scrollbar-corner-color": "ansi_default",
        },
    )


def all_themes(known: Mapping[str, Scheme]) -> list[Theme]:
    """Every theme Morann registers with Textual: the terminal's colors and one per scheme."""
    return [terminal_theme(), *(textual_theme(name, scheme.tokens) for name, scheme in known.items())]


def blend(front: str, back: str, share: float) -> str:
    """`front` laid over `back` at `share` opacity, as hex."""
    a, b = RichColor.parse(front).get_truecolor(), RichColor.parse(back).get_truecolor()
    mixed = (round(x * share + y * (1 - share)) for x, y in zip(a, b))
    return "#" + "".join(f"{value:02x}" for value in mixed)


class Ink:
    """The tokens of the current theme as rich styles: `ink("ok")` is passing-green text, `ink.chip("bad")` a pill.
    In the terminal themes the muted tokens are the default color dimmed, and the rest are ANSI colors."""

    def __init__(self, tokens: Tokens) -> None:
        self.tokens = tokens
        self.truecolor = tokens is not TERMINAL

    def color(self, name: str) -> str | None:
        """The token's color, None for the terminal's default color (and for no token at all)."""
        return (self.tokens.get(name) or None) if name else None

    def __call__(self, name: str, *, bold: bool = False, italic: bool = False, underline: bool = False) -> Style:
        """Text in the token's color; "" (the terminal's default color) for a token the palette leaves empty, dimmed
        for the muted ones."""
        value = self.color(name)
        dim = value is None and name in ("muted", "subtle")
        return Style(
            color=value, dim=dim or None, bold=bold or None, italic=italic or None, underline=underline or None
        )

    def chip(self, name: str, bold: bool = False) -> Style:
        """A pill: the token's color on a faint fill of it in truecolor, reversed in the terminal's colors."""
        value = self.color(name)
        if name in ("muted", "subtle"):
            if not self.truecolor:
                return Style(dim=True, reverse=True, bold=bold or None)
            return Style(color=self.tokens.text, bgcolor=self.tokens.border, bold=bold or None)
        if value is None:
            return Style(reverse=True, bold=bold or None)
        if not self.truecolor:
            return Style(color=value, reverse=True, bold=bold or None)
        return Style(color=value, bgcolor=blend(value, self.tokens.background, 0.2), bold=bold or None)

    def key(self) -> Style:
        """A key cap in the help and the dialogs."""
        if not self.truecolor:
            return Style(color=self.color("accent"), bold=True)
        return Style(color=self.tokens.accent, bgcolor=self.tokens.panel, bold=True)

    def fill(self, name: str) -> Style:
        """A background in the token's color; nothing in the terminal's colors."""
        value = self.color(name)
        return Style(bgcolor=value) if value and self.truecolor else Style()


SYNTAX = {  # pygments token kind -> design token, for code in the truecolor themes
    "comment": "subtle",
    "keyword": "merged",
    "function": "info",
    "class": "warn",
    "decorator": "accent",
    "builtin": "accent",
    "tag": "info",
    "attribute": "warn",
    "string": "ok",
    "number": "accent",
    "literal": "accent",
}


def syntax_colors(tokens: Tokens) -> Mapping[str, str]:
    """The colors code is highlighted with in a palette: SYNTAX's tokens resolved to hex."""
    return {kind: tokens.get(token) for kind, token in SYNTAX.items()}
