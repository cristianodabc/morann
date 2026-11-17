# SPDX-FileCopyrightText: 2026 Cristiano Carvalho
# SPDX-License-Identifier: Apache-2.0
"""Where you are and how you get anywhere: the header's breadcrumb, the statusline, the `:` command line, the ctrl+p jump
palette and the help. Mixed into Main; the jump list and the vim prefixes are in vimkeys."""

from __future__ import annotations

from rich.text import Text
from textual.widgets import Input, Static

from morann import commands, core, keymap, markdown, statusline, theme
from morann.chrome import CommandLine, crumbs
from morann.dialogs import HelpScreen, PickerScreen
from morann.main_motions import MOTIONS
from morann.widgets import DiffRows, InlineText, ListRows

LIST_TABS = core.LIST_TABS
PANE_TABS = {"conversation": "Conversation", "commits": "Commits", "checks": "Checks", "files": "Files"}
MOTION_WORDS = tuple(what.split()[0] for what, _crosses in MOTIONS.values())  # change, hunk, ... unresolved
INPUT_KEYS = (("enter", "done"), ("esc", "cancel"))
COMMAND_KEYS = (("tab", "complete"), ("up down", "history"), ("enter", "run"), ("esc", "cancel"))


class NavMixin:
    # The header's breadcrumb and the statusline.

    def crumb_parts(self):
        """owner › repo › #7 › Files with a pull request open, else the scope and the list's tab."""
        if self.pr is not None:
            owner, _, repo = self.pr.repo.partition("/")
            return [owner, repo, f"#{self.pr.number}", PANE_TABS.get(self.mode, self.mode)]
        return [core.scope_label(self.scope_kind), LIST_TABS[self.tab]]

    def show_crumbs(self):
        width = max(12, self.size.width * 2 // 5)
        separator = self.icons.get("crumb", ">")
        self.query_one("#crumbs", Static).update(crumbs(self.crumb_parts(), self.app.painter.ink, separator, width))

    def hint_place(self):
        """Which keys the statusline shows: the editor's, an input's, the file tree's, the list's or the open tab's."""
        focused = self.app.focused
        if self.editing or isinstance(focused, InlineText):
            return "editor"
        if isinstance(focused, CommandLine):
            return "command"
        if isinstance(focused, Input):
            return "input"
        if focused is not None and focused.id == "files":
            return "tree"
        return "list" if self.focus_pane == "list" else self.mode

    def show_hints(self):
        """The statusline: the mode, where you are, how the review stands, a few keys, the position, the theme."""
        bar = self.query_one("#status", Static)
        bar.display = not self.submitting
        if not bar.display:
            return
        place = self.hint_place()
        if place in ("input", "command"):
            pairs = INPUT_KEYS if place == "input" else COMMAND_KEYS
        else:
            pairs = [
                (key.keys, key.hint)
                for key in keymap.hints(place)
                if not key.action or self.check_action(key.action, key.params)
            ]
        hints = list(pairs[: statusline.HINTS])
        made = {seg.name: seg for seg in self.status_segments(place) if seg is not None}
        left = [made[name] for name in self.status_layout[0] if name in made]
        right = [made[name] for name in self.status_layout[1] if name in made]
        glyphs = "nerd" if self.icons is core.NERD else "unicode" if self.icons is core.UNICODE else "ascii"
        bar.update(statusline.render(left, right, hints, max(10, self.size.width), self.app.painter.ink, glyphs))

    def status_segments(self, place):
        """Every segment the statusline can show, None where there is nothing to say."""
        Segment = statusline.Segment
        pr = self.pr
        mode = (
            "COMMAND"
            if place == "command" or self.query_one("#cmdbar").display
            else "SEARCH"
            if place == "input"
            else "WRITING"
            if place == "editor"
            else "REVIEWING"
            if self.reviewing()
            else "PENDING"
            if self.tab == "pending" and self.focus_pane == "list"
            else "READING"
        )
        tab = PANE_TABS.get(self.mode, self.mode) if self.focus_pane == "diff" and pr else LIST_TABS[self.tab]
        yield Segment("mode", mode, statusline.MODES[mode])
        yield Segment("where", f"{pr.repo} #{pr.number}" if pr else core.scope_label(self.scope_kind))
        yield Segment("branch", pr.head_ref) if pr and pr.head_ref else None
        yield Segment("tab", tab)
        yield Segment("progress", self.review_progress(short=True)) if pr and self.review_progress() else None
        yield self.checks_segment()
        yield self.merge_segment()
        yield Segment("position", self.position())
        yield Segment("theme", self.app.theme)
        yield Segment("help", "? help")

    def checks_segment(self):
        pr = self.pr
        if pr is None or not pr.checks:
            return None
        states = [check.state for check in pr.checks]
        for state, glyph, token in (("fail", "FAILURE", "bad"), ("pending", "PENDING", "warn")):
            if state in states:
                return statusline.Segment("checks", f"{self.icons[glyph]} {states.count(state)}", token)
        return statusline.Segment("checks", f"{self.icons['SUCCESS']} {len(states)}", "ok")

    def merge_segment(self):
        pr = self.pr
        found = {
            "DIRTY": ("conflicts", "bad"),
            "BEHIND": ("behind", "warn"),
            "BLOCKED": ("blocked", "warn"),
            "CLEAN": ("mergeable", "ok"),
            "HAS_HOOKS": ("mergeable", "ok"),
        }.get(pr.merge_state if pr else "")
        return statusline.Segment("merge", *found) if found else None

    def position(self):
        """Where the cursor is: the file and line and how far through the diff, or the row of the list."""
        if self.focus_pane == "list":
            listing = self.query_one("#list", ListRows)
            shown = [row for row in listing.rows if isinstance(row, core.PrRow)]
            current = listing.current()
            at = shown.index(current) + 1 if current in shown else 0
            return f"{at}/{len(shown)}"
        diff = self.query_one("#diff", DiffRows)
        percent = round(100 * diff.cursor / max(1, len(diff.rows) - 1)) if diff.rows else 0
        row = diff.current()
        if self.mode == "files" and self.pr is not None and self.pr.files:
            line = (row.new or row.old or row.number) if row is not None else ""
            path = self.pr.files[self.file_index].path.rpartition("/")[2]
            return f"{path}:{line} {percent}%" if line else f"{path} {percent}%"
        return f"{percent}%"

    # The command line.

    def action_command(self, text=""):
        """: opens the command line at the bottom, under the statusline."""
        line = self.query_one("#cmdline", CommandLine)
        line.complete = lambda typed: commands.complete(typed, self.command_choices())
        line.closed = self.close_command
        line.start(self.state.get("commands") or [])
        line.value = text
        line.cursor_position = len(text)
        self.query_one("#cmdbar").display = True
        line.focus()
        self.show_hints()

    def close_command(self):
        self.query_one("#cmdbar").display = False
        self.show_hints()
        self.query_one(f"#{self.focus_pane}").focus()
        self.show_bars()

    def command_choices(self):
        """What tab completes each command's argument from."""
        rows = self.jump_rows()
        orgs = sorted({row.repo.split("/")[0] for row in rows})
        return {
            "ref": [row.key for row in rows],
            "scope": ["mine", "personal", *orgs],
            "repo": sorted({row.repo for row in rows}),
            "tab": list(commands.TABS),
            "theme": list(self.app.themes),
            "motion": list(MOTION_WORDS),
            "review": ["discard"],
            "help": ["commands", *(section.title.split()[0].lower() for section in keymap.SECTIONS)],
        }

    def run_command(self, line):
        """Run one command line. A mistake keeps the line open with the reason, so it can be fixed in place."""
        if line.strip():  # kept even when it fails, so up brings it back to fix
            self.state.save(commands=commands.remember(self.state.get("commands") or [], line))
        try:
            parsed = commands.parse(line)
            self.close_command()
            if parsed is not None:
                self.dispatch_command(*parsed)
        except core.UsageError as error:
            self.query_one("#cmdbar").display = True
            self.query_one("#cmdline").focus()
            self.notify(str(error), severity="error", timeout=6)

    def dispatch_command(self, command, arg):
        name = command.name
        if name == "open":
            ref = self.current_ref()
            repo, number = self.forge.parse_ref(
                arg.lstrip("#") if arg.startswith("#") else arg, ref[0] if ref else None
            )
            self.record_jump(self.focus_pane)
            self.open_ref(repo, number)
        elif name == "scope":
            self.command_scope(arg)
        elif name in ("repo", "filter"):
            text = f"{core.check_repo(arg)}#" if name == "repo" and arg else arg
            self.set_filter(text)
        elif name == "tab":
            wanted = next((tab for tab in LIST_TABS if tab.startswith(arg.casefold())), None) if arg else None
            if wanted is None:
                raise core.UsageError(f"no such tab: {arg!r}; {', '.join(LIST_TABS)}")
            self.action_tab(wanted)
        elif name in PANE_TABS:
            self.action_ptab(name)
        elif name in ("next", "prev"):
            letter = next(
                (key for key, (what, _) in MOTIONS.items() if what.split()[0] == (arg or "x").split()[0]), None
            )
            if letter is None:
                raise core.UsageError(f"go to what? {', '.join(MOTION_WORDS)}")
            self.action_motion(letter, 1 if name == "next" else -1)
        elif name in ("split", "unified"):
            self.action_split(name == "split")
        elif name == "expand":
            self.action_expand(every=True)
        elif name == "review":
            self.action_review(arg.strip().casefold())
        elif name == "edit":
            self.action_edit()
        elif name == "delete":
            self.delete_armed = None
            self.action_delete()
            self.action_delete()  # :delete is the d d itself; the dialog still asks
        elif name == "link":
            self.action_open_link()
        elif name == "copy":
            self.action_copy_link()
        elif name == "refresh":
            self.action_refresh()
        elif name == "theme":
            self.command_theme(arg)
        elif name == "help":
            self.action_help(arg)
        elif name == "quit":
            self.action_quit()

    def command_scope(self, arg):
        word = arg.strip()
        if not word:
            return self.action_scope()
        kind = word.casefold() if word.casefold() in ("mine", "personal") else f"org:{core.check_owner(word)}"
        return self.scope_picked(kind)

    def command_theme(self, arg):
        if not arg:
            return self.action_theme()
        name = theme.check(theme.chosen(arg), self.app.schemes)
        if name not in self.app.themes:  # under NO_COLOR only the terminal's colors
            raise core.UsageError("NO_COLOR is set: colors stay off")
        self.app.theme = name
        return None

    def set_filter(self, text):
        self.filter = text
        box = self.query_one("#filter", Input)
        box.value = text
        box.display = bool(text)
        self.show_list()
        self.want_search()
        self.remember()

    # The jump palette and the help.

    def jump_rows(self):
        """Every pull request on hand, once each: the recently opened first, then Mine, To Review, the All tab and the
        reviews in progress."""
        seen, rows = set(), []
        for row in [*self.recent_rows(filtered=False), *self.all_rows(), *(item.row for item in self.pending_items())]:
            if row.key not in seen:
                seen.add(row.key)
                rows.append(row)
        return rows

    def jump_label(self, row):
        ink = self.app.painter.ink
        label = Text(f"{row.repo}#{row.number}", ink("muted"))
        label.append("  ")
        label.append(core.clean(row.title).replace("\n", " ") or "(not read yet)", ink("text"))
        if row.author:
            label.append(f"  {row.author}", ink("muted"))
        return label

    def action_jump_palette(self):
        """ctrl+p: a few letters and enter. Any pull request on hand (repository, number, title or author), then the
        open pull request's files, then the : commands that need nothing more."""
        ink = self.app.painter.ink
        choices = [(self.jump_label(row), row.key) for row in self.jump_rows()]
        if self.pr is not None:
            for index, item in enumerate(self.pr.files):
                label = Text.assemble(("file ", ink("muted")), (item.path, ink("text")))
                label.append(f"  +{item.additions} -{item.deletions}", ink("muted"))
                choices.append((label, ("file", index)))
        for command in commands.COMMANDS:
            if command.arg in ("", "motion", "review", "theme"):
                label = Text.assemble((f":{command.name}", ink("accent")), ("  " + command.text, ink("muted")))
                choices.append((label, ("command", command.name)))
        current = self.pr.key if self.pr is not None else None
        hint = "a pull request, a file of the open one, or a : command"
        self.app.push_screen(PickerScreen("Jump", choices, current, hint), self.jump_to)

    def jump_to(self, key):
        """Go where the palette's pick says: a pull request, on its list row when the list shows it, else below the
        list; a file of the open one; or a command, which runs, or waits on the command line for what it needs."""
        if not key:
            return
        if isinstance(key, tuple):
            kind, value = key
            if kind == "file":
                self.record_jump(self.focus_pane)
                self.focus_on("diff")
                self.open_file(value)
                return
            if commands.find(value).arg:  # it takes a word: the command line, ready for it
                self.action_command(f"{value} ")
            else:
                self.run_command(value)
            return
        self.record_jump(self.focus_pane)
        listing = self.query_one("#list", ListRows)
        index = next((i for i, row in enumerate(listing.rows) if getattr(row, "key", None) == key), None)
        if index is None:
            repo, _, number = key.rpartition("#")
            self.open_ref(repo, int(number))
            return
        self.jumping = True  # the list row is part of this one jump, not a jump of its own
        try:
            listing.go(index)
        finally:
            self.jumping = False
        self.focus_pane = "diff"
        self.layout_panes()
        self.query_one("#diff", DiffRows).focus()
        self.selection_changed(listing.current(), wait=0)

    # Links in the comment under the cursor: gx opens one, gy copies one's address.

    def row_links(self):
        """The (text, URL) of the web links in the lower pane's row under the cursor, its own link last."""
        row = self.query_one("#diff", DiffRows).current() if self.pr is not None else None
        if row is None:
            return []
        found = markdown.links(row.body)
        if row.link and row.link not in [url for _text, url in found]:
            found.append(("this row on " + self.forge.label, row.link))
        return found

    def pick_link(self, title, then):
        """`then(url)` with the row's one link, or the one picked from them; each shows its whole address first."""
        found = self.row_links()
        if not found:
            self.notify("no link here: gx and gy work on a comment, a line, a commit or a check", timeout=4)
            return
        if len(found) == 1 and then == self.copy_url:
            then(found[0][1])
            return
        ink = self.app.painter.ink
        choices = [
            (Text.assemble((text, ink("text", bold=True)), "  ", (url, ink("muted"))), url) for text, url in found
        ]
        self.app.push_screen(
            PickerScreen(title, choices, hint="the link's text or address"), lambda url: url and then(url)
        )

    def action_open_link(self):
        """gx: open a link of the row in the browser, after its address shows; a comment's links can go anywhere on
        the web, so one is never opened unseen."""
        self.pick_link("Open a link", self.open_web)

    def action_copy_link(self):
        """gy: copy a link's address to the clipboard (OSC 52, where the terminal allows it)."""
        self.pick_link("Copy a link's address", self.copy_url)

    def open_web(self, url):
        if not url.startswith(markdown.WEB):
            self.notify("Morann opens only http and https links", severity="warning")
            return
        self.opener(url)
        self.notify(f"opening {url}", timeout=4)

    def copy_url(self, url):
        self.app.copy_to_clipboard(url)
        self.notify(f"copied {url}", timeout=4)

    def action_help(self, query=""):
        self.app.push_screen(HelpScreen(self.hint_place(), query))
