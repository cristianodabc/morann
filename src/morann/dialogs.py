# SPDX-FileCopyrightText: 2026 Cristiano Carvalho
# SPDX-License-Identifier: Apache-2.0
"""Every popup Morann opens is a Dialog: one frame with its title on the border, a body, and a line of the keys that
work in it. The actions and confirmations, the pickers (scope, jump) and the help are dialogs."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, ClassVar, Generic, TypeVar

from rich.console import RenderableType
from rich.table import Table
from rich.text import Text
from textual import events
from textual.app import ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Input, OptionList, Static

from morann import core, fuzzy, keymap
from morann.chrome import key_line

T = TypeVar("T")


class Dialog(ModalScreen[T], Generic[T]):
    """A framed popup. Subclasses yield their body from `body()`, size it with FRAME (popup, picker or sheet) and name
    their keys in KEYS; `show_keys` changes them while it is open."""

    FRAME = "popup"
    FRAME_ID = "dialog"
    KEYS: ClassVar[Sequence[tuple[str, str]]] = (("esc", "close"),)

    def __init__(self, title: str) -> None:
        super().__init__()
        self.heading = title
        self.keys: list[tuple[str, str]] = list(self.KEYS)  # what the key line shows; a dialog may set its own

    def body(self) -> ComposeResult:
        yield from ()

    def compose(self) -> ComposeResult:
        with Vertical(classes=f"dialog {self.FRAME}", id=self.FRAME_ID):
            yield from self.body()
            yield Static(id="dialog-keys")

    def on_mount(self) -> None:
        self.query_one(f"#{self.FRAME_ID}").border_title = self.heading
        self.show_keys(self.keys)

    def show_keys(self, keys: Sequence[tuple[str, str]]) -> None:
        self.query_one("#dialog-keys", Static).update(key_line(keys, self.app.painter.ink))  # type: ignore[attr-defined]

    def action_close(self) -> None:
        self.dismiss(None)


class ChoiceScreen(Dialog[Any]):
    """A question before something happens: a title, what will happen, and a button per choice, each with its keys
    shown in the dialog's key line. A key or a click picks; the last choice is the one esc and n take, cancel."""

    FRAME = "confirm"
    FRAME_ID = "ask-popup"
    BINDINGS: ClassVar[list[BindingType]] = [Binding("escape,n", "pick(-1)", show=False)]

    def __init__(self, title: str, what: str, choices: Sequence[tuple[str, str, Any]]) -> None:
        """choices: (keys, label, value) each; dismisses with the value picked."""
        super().__init__(title)
        self.what, self.choices = what, list(choices)
        self.keys = [(keys, label.lower()) for keys, label, _value in self.choices]

    def body(self) -> ComposeResult:
        yield Static(self.what, id="ask-what")
        with Horizontal(id="ask-buttons"):
            for at, (_keys, label, _value) in enumerate(self.choices):
                yield Button(label, id=f"ask-{at}", variant="primary" if at == 0 else "default", compact=True)

    def on_mount(self) -> None:
        for button in self.query(Button):
            button.can_focus = False  # a key picks; enter must not press whichever button has focus

    def on_key(self, event: events.Key) -> None:
        for at, (keys, _label, _value) in enumerate(self.choices[:-1]):
            if event.key in keys.split():
                event.stop()
                event.prevent_default()
                self.action_pick(at)
                return

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.action_pick(int(str(event.button.id).removeprefix("ask-")))

    def action_pick(self, at: int) -> None:
        self.dismiss(self.choices[at][2])


class ConfirmScreen(ChoiceScreen):
    """Yes or cancel: y or enter says yes, n or esc cancels. Dismisses with True for yes."""

    def __init__(self, title: str, what: str, yes: str = "Confirm") -> None:
        super().__init__(title, what, [("y enter", yes, True), ("n esc", "Cancel", False)])


class ActionScreen(Dialog[None]):
    """The pull request actions (merge first), the bulk update or the scope-switch question. Main draws the body and
    acts; only y here sends anything."""

    FRAME_ID = "actions-popup"
    KEYS = (("y", "send"), ("esc", "close"), ("j k", "scroll"))
    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("y", "act", show=False),
        Binding("n,escape,q", "close", show=False),
        Binding("g", "open_pr", show=False),
        Binding("j,down", "scroll(1)", show=False),
        Binding("k,up", "scroll(-1)", show=False),
        *(Binding(key, f"pick('{key}')", show=False) for key in ("m", "s", "b", "u", "c", "o", "w", "A", "R")),
        *(Binding(str(n), f"choose({n})", show=False) for n in range(1, 10)),
    ]

    def body(self) -> ComposeResult:
        with VerticalScroll(id="actions-scroll"):
            yield Static(id="actions-body")

    def on_mount(self) -> None:
        super().on_mount()
        self.app.main.draw_actions()  # type: ignore[attr-defined]

    def action_act(self) -> None:
        self.app.main.action_act()  # type: ignore[attr-defined]

    def action_close(self) -> None:
        self.app.main.action_close_actions()  # type: ignore[attr-defined]

    def action_pick(self, key: str) -> None:
        self.app.main.action_pick(key)  # type: ignore[attr-defined]

    def action_choose(self, n: int) -> None:
        self.app.main.action_toggle_reviewer(n)  # type: ignore[attr-defined]

    def action_open_pr(self) -> None:
        self.app.main.action_open_pr()  # type: ignore[attr-defined]

    def action_scroll(self, step: int) -> None:
        self.query_one("#actions-scroll", VerticalScroll).scroll_relative(y=step, animate=False)


class PickerScreen(Dialog[Any]):
    """Type a few letters, pick one: a fuzzy filter over labeled choices, best match first, with the matched letters
    marked. Dismisses with the chosen value, or None."""

    FRAME = "picker"
    FRAME_ID = "picker"
    KEYS = (("enter", "pick"), ("ctrl+j ctrl+k", "move"), ("esc", "close"))
    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("escape", "close", show=False),
        Binding("down,ctrl+j,ctrl+n", "move(1)", show=False, priority=True),
        Binding("up,ctrl+k,ctrl+p", "move(-1)", show=False, priority=True),
    ]

    def __init__(self, title: str, choices: Sequence[tuple[Text, Any]], current: Any = None, hint: str = "") -> None:
        super().__init__(title)
        self.entries, self.current, self.hint = list(choices), current, hint
        self.shown: list[Any] = []

    def body(self) -> ComposeResult:
        yield Input(id="picker-filter", placeholder=self.hint or "type to filter")
        yield OptionList(id="picker-list")

    def on_mount(self) -> None:
        super().on_mount()
        self.fill("")
        self.query_one("#picker-filter").focus()

    def fill(self, needle: str) -> None:
        options = self.query_one("#picker-list", OptionList)
        options.clear_options()
        found = fuzzy.rank(needle, ((label.plain, (label, value)) for label, value in self.entries))
        accent = self.app.painter.ink("accent", bold=True, underline=True)  # type: ignore[attr-defined]
        labels = []
        self.shown = []
        for _score, positions, (label, value) in found:
            marked = label.copy()
            for at in positions:
                marked.stylize(accent, at, at + 1)
            labels.append(marked)
            self.shown.append(value)
        options.add_options(labels)
        if self.shown:
            options.highlighted = self.shown.index(self.current) if self.current in self.shown and not needle else 0
        self.query_one(f"#{self.FRAME_ID}").border_subtitle = f"{len(self.shown)} of {len(self.entries)}"

    def on_input_changed(self, event: Input.Changed) -> None:
        self.fill(event.value)

    def on_input_submitted(self, _event: Input.Submitted) -> None:
        options = self.query_one("#picker-list", OptionList)
        if options.highlighted is not None and self.shown:
            self.dismiss(self.shown[options.highlighted])

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        self.dismiss(self.shown[event.option_index])

    def on_key(self, event: events.Key) -> None:
        if event.key in ("j", "k") and not self.query_one("#picker-filter", Input).value:
            self.action_move(1 if event.key == "j" else -1)
            event.stop()
            event.prevent_default()

    def action_move(self, step: int) -> None:
        options = self.query_one("#picker-list", OptionList)
        if self.shown:
            options.highlighted = min(len(self.shown) - 1, max(0, (options.highlighted or 0) + step))


class ScopeScreen(PickerScreen):
    """Which pull requests the list shows: Mine, Personal, or one organization. Picking one only changes the view."""

    def __init__(self, choices: Sequence[str], current: str) -> None:
        labels = [(Text(f"{'● ' if kind == current else '  '}{core.scope_label(kind)}"), kind) for kind in choices]
        super().__init__("Show pull requests from", labels, current)
        self.choices = list(choices)


class HelpFilter(Input):
    """The help's filter line: esc clears it and goes back to the keys, before esc can close the help."""

    BINDINGS: ClassVar[list[BindingType]] = [Binding("escape", "screen.unfilter", show=False)]


class HelpScreen(Dialog[None]):
    """The keys, grouped by task, the focused pane's first. / filters them by key or by what they do."""

    FRAME = "sheet"
    FRAME_ID = "help-frame"
    KEYS = (("/", "filter"), ("j k", "scroll"), ("esc", "close"))
    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("escape,q,question_mark", "close", show=False),
        Binding("slash", "filter", show=False),
        Binding("j,down,ctrl+e", "scroll(1)", show=False),
        Binding("k,up,ctrl+y", "scroll(-1)", show=False),
        Binding("ctrl+d,pagedown", "page(0.5)", show=False),
        Binding("ctrl+u,pageup", "page(-0.5)", show=False),
        Binding("ctrl+f,space", "page(1)", show=False),
        Binding("ctrl+b", "page(-1)", show=False),
        Binding("g,home", "edge(-1)", show=False),
        Binding("G,end", "edge(1)", show=False),
    ]

    def __init__(self, place: str = "", query: str = "") -> None:
        super().__init__("Morann keys")
        self.place, self.needle = place, query

    def body(self) -> ComposeResult:
        yield HelpFilter(
            self.needle, id="help-filter", placeholder="filter the keys: a word of what they do, or the key"
        )
        with VerticalScroll(id="help"):
            yield Static(id="help-body")

    def on_mount(self) -> None:
        super().on_mount()
        self.query_one("#help-filter").display = bool(self.needle)
        self.draw()
        self.query_one("#help").focus()

    def draw(self) -> None:
        self.query_one("#help-body", Static).update(self.table())

    def sections(self) -> list[keymap.Section]:
        """The sections shown: the focused place's first, only the keys the filter keeps."""
        return keymap.matching(keymap.sections_for(self.place), self.needle)

    def table(self) -> RenderableType:
        ink = self.app.painter.ink  # type: ignore[attr-defined]
        forge = self.app.main.forge.label  # type: ignore[attr-defined]
        sections = self.sections()
        grid = Table.grid(padding=(0, 2), expand=True)
        grid.add_column(no_wrap=True, min_width=14)
        grid.add_column(ratio=1)
        for index, section in enumerate(sections):
            if index:
                grid.add_row("", "")
            grid.add_row(Text(section.title, ink("accent", bold=True)), "")
            for key in section.keys:
                grid.add_row(Text(key.keys, ink("text", bold=True)), Text(key.text.format(forge=forge)))
        if not sections:
            grid.add_row(Text(f"no key matches {self.needle!r}", ink("muted")), "")
        if not self.needle:
            grid.add_row("", "")
            for note in keymap.NOTES:
                grid.add_row("", Text(note, ink("muted")))
        return grid

    def on_input_changed(self, event: Input.Changed) -> None:
        self.needle = event.value
        self.draw()
        self.query_one("#help", VerticalScroll).scroll_to(y=0, animate=False)

    def on_input_submitted(self, _event: Input.Submitted) -> None:
        self.query_one("#help").focus()

    def action_unfilter(self) -> None:
        box = self.query_one("#help-filter", Input)
        box.value, box.display = "", False
        self.query_one("#help").focus()

    def action_filter(self) -> None:
        box = self.query_one("#help-filter", Input)
        box.display = True
        box.focus()

    def action_scroll(self, step: int) -> None:
        self.query_one("#help", VerticalScroll).scroll_relative(y=step, animate=False)

    def action_page(self, pages: float) -> None:
        view = self.query_one("#help", VerticalScroll)
        view.scroll_relative(y=round(pages * max(1, view.scrollable_content_region.height)), animate=False)

    def action_edge(self, step: int) -> None:
        view = self.query_one("#help", VerticalScroll)
        view.scroll_to(y=view.max_scroll_y if step > 0 else 0, animate=False)
