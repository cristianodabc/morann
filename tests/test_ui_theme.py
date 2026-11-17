# SPDX-FileCopyrightText: 2026 Cristiano Carvalho
# SPDX-License-Identifier: Apache-2.0
"""Colors come from design tokens. By default every token is one of the terminal's own colors: its default foreground
and background and its 16 ANSI colors, never an RGB or 256-color value and no background of Morann's own, so Morann
takes on the terminal's theme; only the diff, drawn like github.com's, leaves them on a 24-bit terminal. A named scheme
(--theme, MORANN_THEME or the config) draws in its own colors and nothing else. NO_COLOR drops color."""

import re
from pathlib import Path

import pytest

from fake_github import FakeGitHub, fixture
from morann import commands, core, paint, palette, theme
from support import make_app, settle

TERMINAL = ("DEFAULT", "STANDARD")  # rich's ColorType names: the terminal's default colors and its 16 ANSI ones


def colors(app, filtered=False):
    """Every color on the screen as (widget id, color), after the app's output filters when `filtered`."""
    found = set()
    for y, strip in enumerate(app.screen._compositor.render_strips()):
        segments = list(strip)
        if filtered:
            for line_filter in app._filters:
                segments = line_filter.apply(segments, app.screen.styles.background)
        x = 0
        for segment in segments:
            style = segment.style
            for color in (style.color, style.bgcolor) if style else ():
                if color is not None:
                    widget = app.screen.get_widget_at(min(x, app.size.width - 1), y)[0]
                    found.add((widget.id or type(widget).__name__, color))
            x += len(segment.text)
    return found


def foreign(app):
    """The colors that are not the terminal's own: RGB and 256-color values."""
    return sorted({(where, color.name) for where, color in colors(app) if color.type.name not in TERMINAL})


async def tour(pilot, look):
    """The list, the lower pane and its tabs, the tree, the editor, the summary, the submit bar, the actions and scope
    popups and the help, each passed to `look`."""
    steps = (
        ((), "list"),
        (("tab",), "diff focused"),
        (("1",), "conversation"),
        (("2",), "commits"),
        (("3",), "checks"),
        (("4",), "files"),
        (("e",), "file tree"),
        (("c",), "inline editor"),
        (("escape", "m"), "summary"),
        (("ctrl+s", "a"), "submit bar"),
        (("escape", "M"), "actions"),
        (("escape", "s"), "scope"),
        (("escape", "question_mark"), "help"),
        (("escape",), "back"),
    )
    for keys, label in steps:
        await pilot.press(*keys)
        await settle(pilot)
        look(label)


def assert_clean(app, label):
    leaks = foreign(app)
    assert not leaks, (label, leaks[:8])


def assert_tinted(app, tint):
    """The diff pane shows every tint of the scheme's diff colors: added, removed, changed words, hunk band."""
    shown = {color.name for where, color in colors(app) if where == "diff"}
    for name in ("add_line", "add_num", "add_word", "del_line", "del_num", "del_word", "hunk_line", "hunk_num"):
        assert getattr(tint, name) in shown, (name, getattr(tint, name), sorted(shown))


def assert_diff_only(app, label):
    """Only the diff pane leaves the terminal's own colors."""
    leaks = [leak for leak in foreign(app) if leak[0] != "diff"]
    assert not leaks, (label, leaks[:8])


def own_backgrounds(app):
    """Backgrounds that are a color rather than the terminal's default."""
    found = set()
    for strip in app.screen._compositor.render_strips():
        for segment in strip:
            style = segment.style
            if style and style.bgcolor is not None and style.bgcolor.type.name != "DEFAULT":
                found.add(style.bgcolor.name)
    return found


def assert_colorless(app, label):
    left = sorted({(where, color.name) for where, color in colors(app, filtered=True) if color.type.name != "DEFAULT"})
    assert not left, (label, left[:8])


def test_choosing_a_theme(tmp_path):
    config = tmp_path / "config"
    assert theme.chosen(None, {}) == "terminal" and theme.chosen("Nord", {}) == "nord"
    assert theme.chosen(None, {"MORANN_THEME": "builtin"}) == "github-dark" == theme.chosen("github", {})
    config.write_text("owners = acme\ntheme = tokyo-night\n")
    env = {"MORANN_CONFIG": str(config)}
    assert theme.chosen(None, env) == "tokyo-night"  # the config's theme line
    assert theme.chosen(None, {**env, "MORANN_THEME": "nord"}) == "nord"  # the environment over the config
    assert theme.chosen("gruvbox-dark", {**env, "MORANN_THEME": "nord"}) == "gruvbox-dark"  # --theme over both
    known = theme.schemes({})
    assert theme.check("terminal", known) == "terminal" and theme.check("nord", known) == "nord"
    with pytest.raises(core.UsageError, match="no theme named 'plaid'; there are: terminal, catppuccin-latte"):
        theme.check("plaid", known)


def test_scheme_files(tmp_path):
    """The built-in schemes, and your own beside the config: each token a hex color, the optional ones filled in."""
    built = theme.schemes({})
    assert {"catppuccin-mocha", "catppuccin-latte", "tokyo-night", "gruvbox-dark", "nord", "rose-pine"} <= set(built)
    for name, scheme in built.items():
        assert scheme.title and all(len(scheme.tokens.get(t)) == 7 for t in theme.TOKEN_NAMES), name
    assert not built["catppuccin-latte"].tokens.dark and built["catppuccin-mocha"].tokens.dark
    folder = tmp_path / "themes"
    folder.mkdir()
    (folder / "mine.toml").write_text(
        'name = "Mine"\ndark = false\n[colors]\n'
        + "".join(f'{name} = "#{n:02x}{n:02x}{n:02x}"\n' for n, name in enumerate(theme.REQUIRED, 10))
    )
    (folder / "nord.toml").write_text((theme.BUILT_IN / "nord.toml").read_text().replace("Nord", "My Nord"))
    mine = theme.schemes({"MORANN_THEMES": str(folder)})
    assert mine["mine"].title == "Mine" and not mine["mine"].tokens.dark and mine["nord"].title == "My Nord"
    assert mine["mine"].tokens.local == mine["mine"].tokens.merged  # filled in from the required ones
    assert theme.user_folder({"XDG_CONFIG_HOME": "/x"}) == Path("/x/morann/themes")
    for body, words in (
        ("name = 1", "no [colors] table"),
        ("[colors]\nbackground = '#000000'", "missing colors: text"),
        ("[colors]\nshade = '#000000'", "unknown colors: shade"),
        ("[colors]\n" + "".join(f"{n} = 'red'\n" for n in theme.REQUIRED), "not #rrggbb: accent"),
        ("[colors", "cannot read the theme"),
    ):
        broken = folder / "broken.toml"
        broken.write_text(body)
        with pytest.raises(core.UsageError, match=re.escape(words)):
            theme.load_scheme(broken)


def test_ink():
    ink = theme.Ink(theme.TERMINAL)
    assert ink("muted").dim and ink("ok").color.name == "green" and ink.chip("bad").reverse and ink("").color is None
    assert ink.fill("ok") == ink.fill("panel")  # no fills in the terminal's colors
    mocha = theme.schemes({})["catppuccin-mocha"].tokens
    tinted = theme.Ink(mocha)
    assert tinted("ok").color.triplet.hex == mocha.ok and tinted.chip("ok").bgcolor is not None
    assert theme.blend("#ffffff", "#000000", 0.5) == "#808080"


@pytest.mark.parametrize("truecolor", [False, True], ids=["16 colors", "24-bit"])
@pytest.mark.parametrize("width", [70, 100])
async def test_the_default_is_the_terminals_own_colors(width, truecolor):
    """The terminal's colors everywhere and no background of Morann's own, but the diff: github's look, in the ANSI green
    and red with 16 colors and in github's colors with 24-bit color."""
    with FakeGitHub(fixture()) as github:
        tui = make_app(github, truecolor=truecolor)
        async with tui.run_test(size=(width, 40)) as pilot:
            await settle(pilot)
            assert tui.theme == "terminal" and tui.native_ansi_color and tui.painter.ansi
            assert tui.painter.tint is (palette.DARK if truecolor else palette.ANSI)
            await tour(pilot, lambda label: assert_diff_only(tui, label) if truecolor else assert_clean(tui, label))
            if not truecolor:  # the selection's, and the diff's green, red and blue
                diff = {"green", "red", "blue", "bright_green", "bright_red"}
                assert own_backgrounds(tui) <= {"cyan", "black", *diff}, own_backgrounds(tui)
            await pilot.press("T")  # T tries the next theme, a scheme
            await settle(pilot)
            assert tui.theme == tui.themes[1] != "terminal" and not tui.painter.ansi


@pytest.mark.parametrize("dark", [True, False])
def test_markdown_keeps_to_the_terminals_colors(dark):
    for line in paint.markdown_lines("`x` and\n\n```python\ndef f(x):\n    return 'a' + 1\n```", 60, dark):
        assert all(
            s.style is None or all(c is None or c.type.name in TERMINAL for c in (s.style.color, s.style.bgcolor))
            for s in line
        ), line


def test_diff_syntax_keeps_to_the_terminals_colors():
    for segment in paint.code_text("a.py", "def f(x): return 'a' # c").render(paint.PLAIN):
        style = segment.style
        assert style is None or style.color is None or style.color.type.name in TERMINAL, style


async def test_no_color_drops_every_color(monkeypatch):
    """Textual reads NO_COLOR once, when the app starts; a scheme asked for and 24-bit color bring no color back."""
    monkeypatch.setenv("NO_COLOR", "1")
    monkeypatch.setenv("MORANN_THEME", "catppuccin-mocha")
    with FakeGitHub(fixture()) as github:
        plain = make_app(github, truecolor=True)
        async with plain.run_test(size=(100, 40)) as pilot:
            await settle(pilot)
            assert plain.no_color and plain.theme == "terminal" and plain.painter.tint is None
            assert plain.themes == ["terminal"]  # T has nothing to step to
            await tour(pilot, lambda label: assert_colorless(plain, label))


def ansi_leaks(app):
    """The colors on screen that are ANSI ones: in a scheme every color is the scheme's own."""
    return sorted({(where, color.name) for where, color in colors(app) if color.type.name == "STANDARD"})


def assert_no_ansi(app, label):
    leaks = ansi_leaks(app)
    assert not leaks, (label, leaks[:8])


@pytest.mark.parametrize("name", ["catppuccin-mocha", "catppuccin-latte", "gruvbox-dark"])
async def test_a_scheme_draws_in_its_own_colors(name):
    """A named scheme: its background and accent on screen, its diff tints in the diff with 24-bit color, and no ANSI
    color anywhere on any screen, which would mean a color that skipped the tokens."""
    with FakeGitHub(fixture()) as github:
        tui = make_app(github, theme_name=name, truecolor=True)
        async with tui.run_test(size=(100, 40)) as pilot:
            await settle(pilot)
            tokens = tui.schemes[name].tokens
            assert tui.theme == name and not tui.painter.ansi and tui.painter.tint is palette.github(tokens.dark)
            shown = {color.name for _where, color in colors(tui)}
            assert tokens.accent in shown and tokens.background in shown, sorted(shown)
            await pilot.press("tab", "4")
            await settle(pilot)
            if tui.main.query_one("#sidebar").display:  # the file tree would cover the gutter
                await pilot.press("e")
                await settle(pilot)
            diff = tui.main.query_one("#diff")
            diff.go(next(i for i, row in enumerate(diff.rows) if row.kind == "ctx"))
            await pilot.pause()
            assert_tinted(tui, tui.painter.tint)
            await pilot.press("tab")
            await settle(pilot)
            await tour(pilot, lambda label: assert_no_ansi(tui, label))


async def test_a_scheme_without_24_bit_color_draws_the_diff_in_ansi_green_and_red():
    with FakeGitHub(fixture()) as github:
        tui = make_app(github, theme_name="nord", truecolor=False)
        async with tui.run_test(size=(100, 40)) as pilot:
            await settle(pilot)
            assert tui.theme == "nord" and tui.painter.tint is palette.ANSI and tui.painter.zebra is not None


@pytest.mark.parametrize("name", ["terminal", "catppuccin-latte"])
async def test_a_tab_shows_its_key_apart_from_its_count(name):
    """The key dimmed like a keycap on the left, the count a badge on the right in the color of what it means: a pill
    with Unicode glyphs, bracketed with ASCII; no badge for zero."""
    with FakeGitHub(fixture()) as github:
        tui = make_app(github, theme_name=name, truecolor=True, icons=core.UNICODE)
        async with tui.run_test(size=(100, 40)) as pilot:
            await settle(pilot)
            painter = tui.painter
            review = tui.main.query_one("#tabs").get_tab("review").label
            assert str(review) == "3 To Review  2 ", str(review)  # a pill around the count
            text = painter.tab_text(core.TabLabel("3", "Checks", "1", "bad"), ascii_badge=False)
            key, badge = text.spans[0].style, text.spans[-1].style
            assert key.color != badge.color and badge == painter.ink.chip("bad", bold=True)
            assert key.dim if painter.ansi else key.color.name == painter.ink.color("subtle")
            plain = painter.tab_text(core.TabLabel("1", "Mine", "12"), ascii_badge=True)
            assert plain.plain == "1 Mine [12]" and plain.spans[-1].style == painter.ink("muted", bold=True)
            assert painter.tab_text(core.TabLabel("2", "Pending"), ascii_badge=False).plain == "2 Pending"


async def test_one_dark():
    """One Dark loads like the other schemes, is chosen by name, sits in the T cycle and the palette, and its diff is
    github.com's dark one: green lines and red lines, as every dark theme's on a 24-bit terminal."""
    scheme = theme.schemes({})["one-dark"]
    tokens = scheme.tokens
    assert scheme.title == "One Dark" and tokens.dark
    assert (tokens.background, tokens.text, tokens.bad, tokens.ok, tokens.warn) == (
        "#282c34",
        "#abb2bf",
        "#e06c75",
        "#98c379",
        "#e5c07b",
    )
    assert (tokens.accent, tokens.merged, tokens.info) == ("#61afef", "#c678dd", "#56b6c2")
    assert theme.chosen("one-dark", {}) == "one-dark" and theme.chosen(None, {"MORANN_THEME": "One-Dark"}) == "one-dark"
    with FakeGitHub(fixture()) as github:
        tui = make_app(github, theme_name="one-dark", truecolor=True)
        async with tui.run_test(size=(100, 40)) as pilot:
            await settle(pilot)
            tint = tui.painter.tint
            assert tui.theme == "one-dark" and "one-dark" in tui.themes and tint is palette.DARK
            red, green = (int(tint.add_line[at : at + 2], 16) for at in (1, 3))
            assert green > red  # an added line is green
            red, green = (int(tint.del_line[at : at + 2], 16) for at in (1, 3))
            assert red > green  # a removed line is red
            await pilot.press("ctrl+p", *":theme")
            await settle(pilot)
            assert ("command", "theme") in tui.screen.shown
            await pilot.press("enter")  # :theme waits on the command line; tab offers one-dark among the names
            await settle(pilot)
            assert "theme one-dark" in commands.complete("theme one", tui.main.command_choices())
