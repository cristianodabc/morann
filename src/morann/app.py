# SPDX-FileCopyrightText: 2026 Cristiano Carvalho
# SPDX-License-Identifier: Apache-2.0
"""Morann's terminal UI (Textual). It draws what core.py decides and routes keys; it reaches the forge only through the
provider it was given; it posts only from the review bar, through core.submit, after y, and acts on a pull request only
from the actions popup, after y.

One screen: the pull request lists on top (tabs) with the highlighted one's details panel, the selected pull request
below with its header buttons (Comment, Review, Approve, Request changes, Merge, Open in the forge) and tabs, the diff
syntax highlighted, with the review threads as cards under their lines. Comments, replies and the summary are
written inline.

Colors come from design tokens (theme.py). By default they are the terminal's own colors, so Morann follows the
terminal's theme; --theme, MORANN_THEME or the config's theme line picks a named scheme instead, and T tries the next
one. NO_COLOR drops color."""

from __future__ import annotations

import os
from datetime import datetime
from typing import ClassVar

from rich.style import Style
from rich.text import Text
from textual.app import App, ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import Screen
from textual.widgets import (
    Button,
    Input,
    Static,
    Tab,
    Tabs,
)
from textual.widgets.button import ButtonVariant

from morann import attention, core, markdown, palette, statusline, termcolors, theme
from morann.chrome import CommandLine
from morann.main_attention import AttentionMixin
from morann.main_diff import DiffMixin
from morann.main_lists import ListsMixin
from morann.main_motions import MotionsMixin
from morann.main_nav import NavMixin
from morann.main_posts import DELETABLE, PostsMixin
from morann.main_review import ReviewMixin
from morann.main_select import SelectMixin
from morann.main_single import SingleMixin
from morann.main_submit import SubmitMixin
from morann.paint import Painter, markdown_lines
from morann.vimkeys import VimMixin
from morann.widgets import (
    OPEN_ONLY,
    ROOMY,
    ROW_ACTIONS,
    SPIN,
    STACK_BELOW,
    DiffRows,
    FileTree,
    InlineText,
    ListRows,
    ListTabs,
    SubmitBar,
    open_in_browser,
)

BUTTONS: tuple[tuple[str, ButtonVariant], ...] = (
    ("comment", "default"),
    ("review", "primary"),
    ("approve", "success"),
    ("changes", "error"),
    ("merge", "success"),
    ("actions", "default"),
    ("open-gh", "default"),
)  # the header's buttons, in order


TIPS = {  # {forge} is the forge's name
    "comment": "C: a comment on the conversation, from anywhere",
    "review": "v: Review changes, comment, approve or request changes with a summary",
    "approve": "a in the lower pane, or v then a",
    "changes": "r in the lower pane, or v then r",
    "merge": "the actions (M) with your repository's merge method chosen: y, then y again, merges",
    "actions": "M: merge, squash, rebase, update branch, close or reopen, ready or draft, auto-merge, re-request "
    "review, Open in {forge}",
    "open-gh": "o: the line or thread under the cursor, else the pull request",
}


class Main(
    VimMixin,
    NavMixin,
    MotionsMixin,
    SingleMixin,
    PostsMixin,
    ListsMixin,
    SelectMixin,
    AttentionMixin,
    DiffMixin,
    ReviewMixin,
    SubmitMixin,
    Screen[None],
):
    AUTO_FOCUS = None  # on_mount focuses the remembered pane

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("tab", "switch", "pane"),
        Binding("question_mark", "help", "help", key_display="?"),
        Binding("z", "maximize", show=False),
        Binding("plus,equals_sign", "resize(10)", show=False),
        Binding("minus", "resize(-10)", show=False),
        Binding("ctrl+r", "refresh", show=False),
        Binding("T", "theme", show=False),
        Binding("q", "quit", show=False),
        Binding("colon", "command", show=False),
        Binding("ctrl+p", "jump_palette", show=False),
    ]

    def __init__(self, scope, forge, store, state, icons, now=None, opener=None, opening=None, cache=None):
        super().__init__()
        self.scope, self.forge, self.store, self.state, self.icons, self.now = scope, forge, store, state, icons, now
        self.opener = opener or open_in_browser
        self.opening = opening  # (repo, number) from the command line
        self.cache = cache or core.PrCache()
        self.prefetching = set()
        self.generation = 0  # bumped by a scope switch: reads started before it are dropped when they arrive
        self.prefetch_on = True
        self.pending_pr = None
        self.lists = None
        self.drafted = store.waiting()  # local files, read now, not once the forge answers: drafts and when kept
        self.counts = {key: count for key, (count, _kept) in self.drafted.items() if count}
        self.pending = []  # the Pending tab's reviews in progress, as visible_rows last read them
        self.tab_shown = {}  # (tab row, tab) -> the label and theme it was last drawn with
        self.status_layout = statusline.layout()  # the statusline's segments, left and right
        self.split_view = bool(state.get("split_view"))  # | : old beside new, where the diff pane is wide enough
        self.file_texts = {}  # (repo, path, head) -> the file's lines, read to show unchanged lines between hunks
        self.expanded = {}  # (pull request key, path) -> the first new line of each gap shown
        self.to_drafts = None  # the key opened from the Pending tab: land on its first draft once it is read
        self.tab = state.get("tab") if state.get("tab") in core.LIST_TABS else "review"
        self.only_mine = bool(state.get("only_mine"))
        self.filter = str(state.get("filter") or "")
        self.wanted = state.get("selected")
        self.split = min(85, max(30, int(state.get("split") or 60)))  # percent of the height the diff pane takes
        self.max_diff = bool(state.get("maximized"))
        self.unresolved_only = bool(state.get("unresolved_only"))
        self.focus_pane = "list"
        self.prs = {}  # loaded pull requests by key
        self.pr = None
        self.loading_key = None
        self.drafts = None
        self.file_index = 0
        self.mode = state.get("ptab") if state.get("ptab") in core.TABS else "files"
        self.overrides = {}
        self.busy = {}
        self.error = ""
        self.timer = None
        self.editing = None  # (which editor, keep callback) while an inline editor is open
        self.submitting = None  # {"event", "plan", "problem"} while the submit bar is open
        self.acting = None  # {"state", "plan", "armed"} while the action bar is open
        self.replied_own = set()  # own pull requests that got replies here: time to ask the reviewers again
        self.listing = False
        self.delete_armed = None
        self.columns = (None, None)  # (width and rows they were measured for, the widths)
        self.scope_kind = state.get("scope") or "mine"
        if self.scope_kind != "mine" and self.scope_kind != "personal" and not str(self.scope_kind).startswith("org:"):
            self.scope_kind = "mine"
        self.wide = None  # {"rows", "total", "cursor"}: the All tab's page of every open pull request in the scope
        self.found = (
            None  # the All tab's search on the forge for the filter text: wide's keys plus "text", "kind", "error"
        )
        self.search_timer = None
        self.search_token = 0  # bumped by each search: an answer to an older one is dropped
        self.authors = state.get("authors") if state.get("authors") in core.AUTHORS else "all"
        self.grouped = state.get("grouped", True) is not False
        self.collapsed = set(state.get("collapsed") or [])
        self.login = ""
        self.last_row = None  # the last pull request the list cursor was on, kept while it rests on a repository header
        self.linked = None  # the row of a pull request opened by link (o, :), kept below until another row is chosen
        self.held = None  # the key of a pull request kept below for its unsent drafts when the list emptied
        self.failed = None  # the key whose read failed: not read again until the cursor comes back to it
        self.refreshed_at = None
        self.clock = datetime.now
        self.last_refresh = 0.0
        self.spin = 0
        self.tree_width = min(60, max(20, int(state.get("tree_width") or 30)))
        self.tree_shown = state.get("tree") if isinstance(state.get("tree"), bool) else None  # f; None: on when wide
        self.tree_full = False  # the tree takes the whole width (F)
        self.tree_query = ""
        self.show_details = state.get("details", True) is not False
        self.attention_filter = state.get("attention") if state.get("attention") in attention.FILTERS else ""
        self.flags = {}  # attention flags of the rows on screen, by key
        self.waits = {}  # on To Review: how long each review request has waited, by key
        self.init_vim()

    def compose(self) -> ComposeResult:
        with Horizontal(id="topbar"):
            yield Static(" morann ", id="brand")
            yield Static(id="crumbs")
            yield Static(id="topinfo")
            yield Static("s", id="scopekey")  # the scope button's key, shown while the list has the keys
            yield Button("Mine", id="scope", compact=True)
        with Vertical(id="top"):
            yield ListTabs(
                *(Tab(f"{n} {label}", id=name) for n, (name, label) in enumerate(core.LIST_TABS.items(), 1)), id="tabs"
            )
            yield Input(id="filter", placeholder="filter: repo, title or author")
            yield ListRows(self.paint_list, id="list")
            yield Static(id="details")
        with Vertical(id="bottom"):
            with Vertical(id="prhead"):
                with Horizontal(id="prtop"):
                    yield Static(id="prline")
                    yield Button("Files tree: on (f)", id="tree-toggle", compact=True)
                with Horizontal(id="prbuttons"):
                    for name, variant in BUTTONS:
                        yield Button(name, id=name, variant=variant, compact=True)
            yield ListTabs(*(Tab(label.plain(), id=name) for name, label in core.tab_labels(None).items()), id="ptabs")
            yield Input(id="search", placeholder="search this pane: n and N step through the matches, esc cancels")
            with Vertical(id="summary", classes="inline"):
                yield Static("Review summary: ctrl+s keeps it as a draft, esc cancels", classes="inline-title")
                yield InlineText(id="summary-text", soft_wrap=True, show_line_numbers=False, tab_behavior="indent")
            yield Static(id="sticky")
            with Horizontal(id="split"):
                with Vertical(id="sidebar"):
                    yield Input(id="treefilter", placeholder="filter files")
                    yield FileTree("files", id="files")
                yield DiffRows(self.paint_diff, id="diff")
            with Vertical(id="editor", classes="inline"):
                yield Static(id="editor-title", classes="inline-title")
                yield InlineText(id="editor-text", soft_wrap=True, show_line_numbers=False, tab_behavior="indent")
        with SubmitBar(id="confirm"):
            yield Static(id="confirm-head")
            yield Static(id="bar-title")
            yield InlineText(id="bar-text", soft_wrap=True, show_line_numbers=False, tab_behavior="indent")
            yield Static(id="confirm-status")
            with VerticalScroll(id="confirm-list"):
                yield Static(id="confirm-lines")
            yield Static(id="confirm-keys")
        with Vertical(id="bottombar"):  # the statusline, and the command line under it while it is open
            yield Static(id="status")
            with Horizontal(id="cmdbar"):
                yield Static(":", id="cmdprompt")
                yield CommandLine(id="cmdline", placeholder="open REF, scope NAME, tab NAME, help, q  (tab completes)")

    def on_mount(self):
        for hidden in ("#summary", "#sidebar", "#editor", "#confirm", "#confirm-list"):
            self.query_one(hidden).display = False
        self.query_one("#filter").display = bool(self.filter)
        self.query_one("#cmdbar").display = False
        self.query_one("#search").display = False
        self.query_one("#list", ListRows).before_jump = lambda: self.record_jump("list")
        self.query_one("#diff", DiffRows).before_jump = lambda: self.record_jump("diff")
        for name in [name for name, _variant in BUTTONS] + ["tree-toggle"]:  # a click acts; keys stay with the panes
            self.query_one(f"#{name}", Button).can_focus = False
        self.query_one("#scope", Button).can_focus = False
        self.query_one("#scope", Button).tooltip = "s: Mine, Personal or one organization"
        self.set_interval(0.2, self.tick)
        for name, tip in TIPS.items():
            self.query_one(f"#{name}", Button).tooltip = tip.format(forge=self.forge.label)
        self.query_one("#sidebar").border_title = "Files  e hide  f diff"
        tabs = self.query_one("#tabs", Tabs)
        tabs.active = self.tab
        tabs.tooltip = "1 and 2 switch the lists"
        ptabs = self.query_one("#ptabs", Tabs)
        ptabs.active = self.mode
        ptabs.tooltip = "1 to 4, or [ and ], switch tabs"
        self.query_one("#list").tooltip = (
            "chips: draft  ok approved  chg changes requested  req review required  "
            "ci:ok ci:x ci:.. checks  *N your unsent drafts"
        )
        self.query_one("#prline").tooltip = "} and { change the file, f shows the file tree, M merges, / searches"
        self.query_one("#diff", DiffRows).scrolled = self.diff_scrolled
        self.files_tree().show_root = False
        self.focus_pane = "diff" if self.max_diff else "list"
        self.query_one(f"#{self.focus_pane}").focus()
        self.app.theme_changed_signal.subscribe(self, self.theme_changed)
        if not self.state.get("intro_seen"):  # a first run: one line on how to start
            self.notify(
                "Morann: j k move, enter opens, tab switches panes, s picks the scope, ? lists every key", timeout=12
            )
            self.state.save(intro_seen=True)
        self.layout_panes()
        self.show_list()
        self.show_pr()
        self.load_lists()
        if self.opening:
            self.open_ref(*self.opening)

    def files_tree(self):
        return self.query_one("#files", FileTree)

    def repaint(self):
        self.query_one("#list", ListRows).relayout()
        self.query_one("#diff", DiffRows).relayout()

    def show_scope(self):
        """The scope name, and once the list has loaded how long ago that was: Mine (3m)."""
        label = core.scope_label(self.scope_kind)
        if self.refreshed_at is not None:
            label += f" ({core.elapsed((self.clock() - self.refreshed_at).total_seconds())})"
        button = self.query_one("#scope", Button)
        if str(button.label) != label:
            button.label = label
            button.refresh(layout=True)  # its width follows the label, so the suffix never cuts the name

    def show_bars(self):
        lists = self.lists
        review = len(lists.review) if lists else 0
        mine = len(lists.mine) if lists else 0
        status = next(iter(self.busy.values()), "") or self.error or (self.held and self.hold_note())
        parts = [f"review {review}", f"mine {mine}", f"unsent {len(self.counts)}"]
        if self.forge.read_only:
            parts.append("read-only")
        if status:
            parts.append(status)
        self.title = "Morann"
        self.sub_title = "  ".join(parts)
        page = self.all_page()
        if self.scope_kind != "mine" and page:
            parts[:2] = [f"open {page['total']}"]
        spinner = f"{SPIN[self.spin % len(SPIN)]}" if self.busy else ""
        info = Text(f" {spinner}", Style(dim=True)) if spinner else Text()
        info.append_text(self.attention_summary(narrow=self.size.width < 90))  # counts that follow the scope; ! and b
        waiting = len(self.pending_items())
        if waiting:  # reviews in progress, the Pending tab's count
            info.append(f"  {waiting} pending", self.app.painter.ink("local", bold=True))
        rest = [part for part in parts if part.startswith(("unsent", "read-only"))]
        info.append(f"  {'  '.join(rest)}", Style(dim=True))
        if status:
            info.append(
                f"  {status}", self.app.painter.ink("bad" if status == self.error and not self.busy else "warn")
            )
        if self.count:  # a count being typed: 5 then j
            info.append(f"  {self.count}", Style(bold=True))
        self.query_one("#topinfo", Static).update(info)
        self.show_crumbs()
        self.query_one("#scopekey").display = self.focus_pane == "list" and self.size.width >= 90
        self.show_scope()

        tabs = self.query_one("#tabs", Tabs)
        for name, label in self.list_tab_labels(waiting).items():
            self.set_tab(tabs, name, label)
        self.query_one("#prline", Static).update(self.pr_header())
        self.show_buttons()
        ptabs = self.query_one("#ptabs", Tabs)
        narrow = (self.query_one("#bottom").size.width or self.size.width) < 90
        for name, label in core.tab_labels(self.pr, narrow).items():
            self.set_tab(ptabs, name, label)
        for pane, name in ((self.query_one("#top"), "list"), (self.query_one("#bottom"), "diff")):
            pane.set_class(self.focus_pane == name, "focused")
        self.refresh_bindings()
        self.show_hints()

    def set_tab(self, tabs, name, label):
        """Draw a tab's label when it changed: a new label lays the tab row out again, which typing must not wait on."""
        shown = (label, self.app.theme)
        if self.tab_shown.get((tabs.id, name)) != shown:
            self.tab_shown[(tabs.id, name)] = shown
            tabs.get_tab(name).label = self.app.painter.tab_text(label, self.icons is core.ASCII)

    def list_tab_labels(self, waiting):
        """The lists' tabs: Mine and All a plain total, Pending and To Review in the accent (they need you), and a
        loading mark until the first rows arrive. Only then: a changed tab label lays the screen out again, which
        typing in the filter must not wait on, and the header's spinner shows every later read."""
        lists, page = self.lists, self.all_page()
        spin = self.icons["ellipsis"] if lists is None and "lists" in self.busy else ""
        counts = {
            "mine": (len(lists.mine) if lists else spin, "muted"),
            "pending": (waiting, "accent"),
            "review": (len(lists.review) if lists else spin, "accent"),
            "all": (page["total"] if page else spin, "muted"),
        }
        return {
            name: core.TabLabel(str(n), label, str(counts[name][0] or ""), counts[name][1])
            for n, (name, label) in enumerate(core.LIST_TABS.items(), 1)
        }

    def pr_header(self):
        """The pull request's header, github.com style: its state, title and number, author, base <- head; on the
        Files tab, the file and the keys that move through files."""
        if self.pr is None:
            return Text(" no pull request open", Style(dim=True))
        focused = self.focus_pane == "diff"
        out = Text(" ")
        out.append_text(self.app.painter.state_chip(core.state_badge(self.pr)))
        out.append(f" {self.pr.title} ", Style(bold=focused, dim=not focused))
        out.append(f"#{self.pr.number}", Style(dim=True))
        if self.reviewing():  # a review is on: plainly, with how much it holds
            count = self.drafts.count()
            out.append("  ")
            out.append(
                f" Reviewing: {count} draft{'s' if count != 1 else ''} ", self.app.painter.ink.chip("local", bold=True)
            )
        if self.mode == "files" and self.pr.files:  # which file first, so { and } are enough without the tree
            item = self.pr.files[self.file_index]
            out.append(f"  file {self.file_index + 1}/{len(self.pr.files)} ", Style(dim=True))
            out.append(item.path, Style(bold=focused))
            out.append(f" +{item.additions} -{item.deletions}", Style(dim=True))
        if self.mode == "checks" and self.pr.checks:
            out.append(f"  o open check on {self.forge.label}", Style(bold=focused))
        out.append(f"  {self.pr.author}  {self.pr.base} <- {self.pr.head_ref}  ", Style(dim=True))
        out.append(self.pr_line().strip(), Style(dim=True))
        return out

    def show_buttons(self):
        """The header's buttons: each names its key where that key works in the focused pane. Approve and Request
        changes are gone on your own pull request; Merge is dimmed, with the reason, on anyone else's."""
        row = self.query_one("#prbuttons")
        row.display = self.pr is not None
        toggle = self.query_one("#tree-toggle", Button)
        toggle.display = self.pr is not None and self.mode == "files" and bool(self.pr.files)
        if self.pr is None:
            return
        room = (self.query_one("#bottom").size.width or self.size.width) - 1  # the pane's focus edge takes one
        narrow = room < 89
        state = "on" if self.tree_on() else "off"
        toggle.label = "e show/hide  f focus" if narrow else f"Files tree {state}: e show/hide  f focus"
        toggle.styles.width = core.width_of(str(toggle.label)) + 2
        in_diff = self.focus_pane == "diff"
        own = self.own_pr()
        keyed = " a" if in_diff else "", " r" if in_diff else ""
        initials = "".join(ch for ch in self.forge.label if ch.isupper())  # GH for GitHub
        labels = {
            "comment": "Comment C",
            "review": "Review v",
            "approve": f"Approve{keyed[0]}",
            "changes": f"Request changes{keyed[1]}",
            "merge": "Merge M" if own else "Merge: only your own PRs",
            "actions": "Actions M",
            "open-gh": f"Open in {self.forge.label} o",
        }
        shown = {name for name in labels if not (own and name in ("approve", "changes"))}
        shorter = [
            ("changes", f"Changes{keyed[1]}"),
            ("open-gh", f"{initials} o"),
            ("merge", "Merge: own PRs"),
            ("merge", "Merge"),
            ("open-gh", None),
        ]  # in this order until the row fits the pane
        for name, label in [(None, None), *shorter]:
            if name is not None and name in shown:
                if label is None:
                    shown.discard(name)
                elif own and name == "merge" and label != "Merge":
                    continue
                else:
                    labels[name] = label
            if sum(core.width_of(labels[n]) + 3 for n in shown) <= room:
                break
        for name, label in labels.items():
            button = self.query_one(f"#{name}", Button)
            button.label = label
            button.display = name in shown
            button.styles.width = core.width_of(label) + 2  # the label changes; an auto width would not follow
        merge = self.query_one("#merge", Button)
        merge.disabled = not own
        merge.variant = "success" if own else "default"

    def pr_line(self):
        if self.pr is None:
            return " no pull request open"
        line = f" {self.pr.head[:7]}"
        if self.pr.stale:
            line += "  cached, refreshing..."
        elif self.pr.files_loading:
            line += "  loading files..."
        if self.unresolved_only:
            line += "  unresolved only"
        line += self.search_note()
        progress = self.review_progress()
        if progress:
            line += f"  {progress}"
        if self.pr.rerequest_due() or self.pr.key in self.replied_own:
            line += "  re-request review: M R"
        note = self.hold_note()
        return line + (f"  {note}" if note else "")

    def check_action(self, action, parameters):
        """Keys that would leave an open editor or submit bar do nothing, and each diff row action shows only on a row it
        applies to."""
        for state, allowed in OPEN_ONLY.items():
            if getattr(self, state) and action not in allowed:
                return False
        if action == "submit" and parameters and parameters[0] != "COMMENT" and self.own_pr():
            return False  # approve and request changes are refused on your own pull request; the bar says so
        if action == "expand":  # enter on a row of folded unchanged lines
            row = self.query_one("#diff", DiffRows).current() if self.is_mounted else None
            return self.mode == "files" and row is not None and row.kind == "gap"
        if action == "open_link":  # gx, in the statusline only where the row has a link
            return bool(self.is_mounted and self.row_links())
        if action == "open_check":  # o and enter on a row of the Checks tab
            row = self.query_one("#diff", DiffRows).current() if self.is_mounted else None
            return self.mode == "checks" and row is not None and row.kind == "check"
        if action == "tree_focus":  # f and e work the file tree on the Files tab; elsewhere e edits a draft
            return self.mode == "files"
        if action == "tree_toggle" and self.mode == "files":
            return True
        if action == "fold" and self.mode == "conversation" or action == "open_thread" and self.mode != "conversation":
            return False  # enter on a thread: folds it in the Files tab, opens it there from the Conversation tab
        need = ROW_ACTIONS.get(action)
        if need is None:
            return True
        if action == "comment" and self.mode == "conversation":
            return True
        try:
            row = self.query_one("#diff", DiffRows).current()
        except Exception:  # noqa: BLE001 - asked before the pane exists
            return False
        if row is None:
            return False
        if action == "comment":
            return self.mode == "conversation" or bool(row.anchor or row.draft and row.draft != "summary")
        if action in ("edit", "tree_toggle"):  # a draft, or a post of yours
            return bool(row.draft) or self.own_post(row)
        if action == "delete":
            return bool(row.draft) or self.own_post(row) and row.post[0] in DELETABLE
        return bool(getattr(row, need))

    # Layout: list on top, diff below; one pane at a time when the window is short or the diff is maximized.

    def layout_panes(self):
        top, bottom = self.query_one("#top"), self.query_one("#bottom")
        height = self.size.height or 40
        top.styles.margin = (1 if height >= ROOMY else 0, 0, 0, 0)  # room under the header unless the window is short
        if self.max_diff or height < STACK_BELOW:
            show_list = not self.max_diff and self.focus_pane == "list"
            top.display, bottom.display = show_list, not show_list
            top.styles.height = "1fr"
        else:
            top.display = bottom.display = True
            top.styles.height = max(5, (height - 3) * (100 - self.split) // 100)
        bottom.styles.height = "1fr"
        self.layout_tree()
        self.call_after_refresh(self.place_editor)
        self.call_after_refresh(self.show_detail_strip)

    def on_resize(self, _event):
        self.layout_panes()
        if self.split_view and self.pr is not None and self.mode == "files":  # side by side may now fit, or not
            self.call_after_refresh(self.show_pr)
        self.show_bars()
        self.call_after_refresh(self.show_detail_strip)

    def remember(self):
        self.state.save(
            tab=self.tab,
            only_mine=self.only_mine,
            ptab=self.mode,
            filter=self.filter,
            selected=self.wanted,
            split=self.split,
            maximized=self.max_diff,
            unresolved_only=self.unresolved_only,
        )

    def action_switch(self):
        """tab: the list or the lower pane (f moves between the diff and the file tree)."""
        self.focus_pane = "diff" if self.focus_pane == "list" else "list"
        if self.focus_pane == "list" and self.max_diff:
            self.max_diff = False
        self.layout_panes()
        self.query_one(f"#{self.focus_pane}").focus()
        self.remember()
        self.show_bars()

    def action_maximize(self):
        self.max_diff = not self.max_diff
        if self.max_diff:
            self.focus_pane = "diff"
            self.query_one("#diff").focus()
        self.layout_panes()
        self.remember()
        self.show_bars()

    def action_resize(self, step):
        self.split = min(85, max(30, self.split + step))
        self.max_diff = False
        self.layout_panes()
        self.remember()

    def action_theme(self):
        """T: the next theme, to try them; the config's theme line or --theme is the one Morann starts with."""
        themes, current = self.app.themes, self.app.theme
        self.app.theme = themes[(themes.index(current) + 1) % len(themes)] if current in themes else themes[0]

    def theme_changed(self, theme):
        self.app.painter.reset()
        markdown_lines.cache_clear()
        self.repaint()
        self.remember()
        title = self.app.schemes[theme.name].title if theme.name in self.app.schemes else "the terminal's colors"
        self.notify(f"{title}: theme = {theme.name} in the config keeps it", timeout=4)

    def on_descendant_focus(self, event):
        widget = event.widget
        if widget.id == "bar-text" and self.submitting and not self.editing:  # a click in the summary field
            self.action_bar_summary()
        if widget is not self.focused:
            # Each widget posts this through its own parents' queues, so two focus moves in a row can arrive out of
            # order; one that has already lost focus must not set the pane that refocus gives focus back to.
            return
        if widget.id in ("list", "filter") and self.focus_pane == "diff" and self.query_one("#diff").loading:
            return  # the loading diff pushed focus away; it comes back when the pull request arrives (refocus)
        if widget.id in ("list", "filter"):
            self.focus_pane = "list"
        elif widget.id in ("diff", "files", "treefilter", "search", "editor-text", "summary-text"):
            self.focus_pane = "diff"
        self.show_bars()

    def action_quit(self):
        self.remember()
        self.app.exit()


class Morann(App[None]):
    TITLE = "Morann"
    ENABLE_COMMAND_PALETTE = False  # ctrl+p is the jump palette; every action is a key or a : command
    CSS = """
    Screen { background: $background; color: $foreground; }
    /* the header: brand, breadcrumb, counts, scope */
    #topbar { height: 1; background: $surface; }
    #brand { width: auto; color: $accent; text-style: bold reverse; }
    #crumbs { width: auto; height: 1; }
    #topinfo { width: 1fr; height: 1; }
    #scope { width: auto; min-width: 0; height: 1; margin: 0 0 0 1; }
    #scopekey { width: auto; height: 1; margin: 0 0 0 1; color: $accent; text-style: bold; }
    /* the panes: the focused one shows by its tab underline and its filled cursor row, never by a bar on its edge */
    #top, #bottom { height: 1fr; }
    #prhead { height: auto; }
    #prtop { height: 1; background: $surface; }
    #prline { height: 1; width: 1fr; background: $surface; }
    #tree-toggle { width: auto; min-width: 0; height: 1; margin: 0; }
    #prbuttons { height: 1; }
    #prbuttons Button { width: auto; min-width: 0; height: 1; margin: 0 1 0 0; }
    /* the ANSI themes give a disabled or pressed button a frame, even a compact one; on one row it hides the label */
    Button.-textual-compact { border: none !important; }
    ListTabs Underline > .underline--bar { color: $border-blurred; }
    .focused ListTabs Underline > .underline--bar { color: $accent; }
    Rows { scrollbar-size: 0 0; background: $background; }
    #filter, #search { height: 1; border: none; padding: 0 1; background: $surface; }
    #details { height: auto; margin: 1 0; padding: 0 1; border: round $border-blurred; border-title-color: $foreground;
               background: $background; }
    #bottom { layers: base overlay; }
    .inline { height: auto; padding: 0 0 0 1; background: $background; }
    .inline-title { height: 1; color: $accent; }
    #summary-text { height: 5; border: none; background: $background; }
    #editor { layer: overlay; position: absolute; height: 8; }
    #editor-text { height: 7; border: none; background: $background; }
    #split { height: 1fr; layers: base overlay; }
    #sticky { height: 1; background: $surface; display: none; }
    #sidebar { height: 100%; background: $background; border: round $border-blurred; border-title-color: $foreground; }
    #sidebar:focus-within { border: round $accent; }
    #sidebar.overlay { layer: overlay; position: absolute; }
    #treefilter { height: 1; border: none; padding: 0 1; background: $surface; }
    #files { height: 1fr; background: $background; scrollbar-size: 0 0; }
    #diff { width: 1fr; }
    #confirm { dock: bottom; height: auto; max-height: 60%; border-top: thick $accent; padding: 0 1; background: $surface; }
    #bar-title { height: 1; }
    #bar-text { height: 4; border: none; background: $surface; }
    #confirm-list { height: auto; max-height: 12; padding-left: 1; }
    #confirm-keys { height: 1; }
    /* the bottom line: the focused pane's keys, or the command line */
    #bottombar { dock: bottom; height: auto; }
    #status { height: 1; background: $surface; }
    #cmdbar { height: 1; background: $surface; }
    #cmdprompt { width: 1; height: 1; color: $accent; text-style: bold; }
    #cmdline { width: 1fr; height: 1; border: none; padding: 0; background: $surface; }
    /* dialogs: one frame, one look */
    ModalScreen { background: $background 70%; align: center middle; }
    .dialog.confirm { width: 64; max-width: 100%; }
    #ask-what { height: auto; margin: 1 0 1 0; }
    #ask-buttons { height: 1; }
    #ask-buttons Button { width: auto; min-width: 0; height: 1; margin: 0 2 0 0; }
    .dialog { height: auto; max-height: 90%; border: round $accent; border-title-color: $accent;
              border-title-style: bold; border-subtitle-color: $foreground-muted; padding: 0 1; background: $background; }
    .dialog.popup { width: 76; max-width: 100%; }
    .dialog.picker { width: 80; max-width: 100%; }
    .dialog.sheet { width: 100; max-width: 100%; height: 90%; }
    #dialog-keys { height: 1; margin: 1 0 0 0; }
    #actions-scroll { height: auto; max-height: 24; }
    #picker-filter, #help-filter { height: 1; border: none; padding: 0 1; margin: 0 0 1 0; background: $surface; }
    #picker-list { height: auto; max-height: 16; border: none; padding: 0; background: $background; }
    #picker-list > .option-list--option-highlighted { background: $block-cursor-background;
                                                       color: $block-cursor-foreground; text-style: bold; }
    #help { height: 1fr; }
    """

    def __init__(
        self,
        scope,
        icons=core.ASCII,
        forge=None,
        store=None,
        state=None,
        now=None,
        opener=None,
        opening=None,
        cache=None,
        theme_name=None,
        truecolor=None,
        terminal_colors=None,
        hyperlinks=None,
    ):
        """theme_name is a theme's name (see theme.py); without one, theme.chosen reads it. A name that is no theme is a
        UsageError."""
        self.truecolor = palette.truecolor(os.environ) if truecolor is None else truecolor  # 24-bit color
        self.no_color_env = "NO_COLOR" in os.environ
        self.hyperlinks = markdown.hyperlinks(os.environ) if hyperlinks is None else hyperlinks  # OSC 8 links
        self.terminal_colors = terminal_colors  # termcolors.TerminalColors the terminal answered with, or None
        self.dark_terminal = terminal_colors.dark if terminal_colors else termcolors.dark_background(os.environ)
        self.schemes = theme.schemes()
        wanted = theme.DEFAULT if self.no_color_env else theme.chosen(theme_name)
        self.start_theme = theme.check(wanted, self.schemes)
        self.themes = [theme.DEFAULT] if self.no_color_env else [theme.DEFAULT, *self.schemes]  # what T steps through
        # The terminal's theme draws in native ANSI, so the terminal's own palette is used as is; a scheme in RGB. Under
        # NO_COLOR it is native ANSI throughout: Textual then removes color, where its grayscale filter for RGB themes
        # fails on unstyled segments.
        super().__init__(ansi_color=True if self.no_color_env else None)
        self.saved = state or core.State()
        for made in theme.all_themes(self.schemes):
            self.register_theme(made)
        self.main = Main(
            scope,
            forge or core.select(),
            store or core.DraftStore(),
            self.saved,
            icons,
            now,
            opener=opener,
            opening=opening,
            cache=cache,
        )
        self.painter = None

    def on_mount(self):
        self.theme = self.start_theme
        self.painter = Painter(self)
        self.push_screen(self.main)
