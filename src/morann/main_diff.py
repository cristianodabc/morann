# SPDX-FileCopyrightText: 2026 Cristiano Carvalho
# SPDX-License-Identifier: Apache-2.0
"""The lower pane: its tabs, the file tree, moving through files and threads, and drafts written inline."""

from __future__ import annotations

from rich.style import Style
from rich.text import Text
from textual.widgets import (
    Input,
    Static,
    Tabs,
    Tree,
)

from morann import core
from morann.widgets import EDITOR_HEIGHT, WIDE, DiffRows, InlineText, failure


class DiffMixin:
    """The lower pane: its tabs, the file tree, moving through files and threads, and drafts written inline. Mixed into Main."""

    def paint_diff(self, row, width, _index):
        return self.app.painter.diff_row(row, width, self.number_width)

    @property
    def number_width(self):
        return core.number_width(self.pr, self.file_index) if self.mode == "files" else 1

    def diff_rows(self):
        if self.pr is None:
            if self.loading_key:  # a skeleton of the diff while the pull request loads
                return [
                    core.ViewRow(
                        "info", f"loading {self.loading_key}: conversation, commits, checks, files...", selectable=False
                    ),
                    *(
                        core.ViewRow("text", "\u2591" * width, style="dim", selectable=False)
                        for width in (12, 30, 44, 26, 38)
                    ),
                ]
            if self.error:
                return [core.ViewRow("info", f"{self.error}  ctrl+r retries", style="bad", selectable=False)]
            return [core.ViewRow("info", self.empty_note() or "select a pull request", selectable=False)]
        if self.mode == "conversation":
            return core.conversation_rows(self.pr, self.drafts, icons=self.icons, now=self.now)
        if self.mode == "commits":
            return core.commit_rows(self.pr, now=self.now)
        if self.mode == "checks":
            return core.check_rows(self.pr)
        if self.pr.files_loading:
            return [
                core.ViewRow("info", "loading files...", selectable=False),
                *(core.ViewRow("text", "\u2591" * width, style="dim", selectable=False) for width in (30, 44, 26)),
            ]
        if not self.pr.files:
            return [core.ViewRow("info", "no changed files", selectable=False)]
        return self.shown_file_rows(self.file_index)

    def shown_file_rows(self, index):
        """A file's rows as the Files tab shows them: its unchanged lines as expanded, side by side when that is on and
        the pane is wide enough."""
        item = self.pr.files[index]
        viewed = bool(item.sha) and (self.state.get("viewed") or {}).get(self.pr.key, {}).get(item.path) == item.sha
        rows = core.file_rows(
            self.pr,
            index,
            self.drafts,
            overrides=self.overrides,
            unresolved_only=self.unresolved_only,
            icons=self.icons,
            now=self.now,
            viewed=viewed,
            text=self.file_texts.get((self.pr.repo, item.path, self.pr.head)),
            expanded=self.expanded.get((self.pr.key, item.path), ()),
        )
        return core.split_rows(rows) if self.side_by_side() else rows

    def side_by_side(self):
        """Whether the diff shows old beside new now: | turned it on and the diff pane has the columns for it."""
        width = self.query_one("#diff", DiffRows).size.width or self.size.width
        return self.split_view and width >= core.SPLIT_WIDTH

    def action_split(self, on=None):
        """| (or :split and :unified): the diff side by side, old beside new, or in one column; remembered."""
        self.split_view = (not self.split_view) if on is None else on
        self.state.save(split_view=self.split_view)
        if self.split_view and not self.side_by_side():
            width = self.query_one("#diff", DiffRows).size.width or self.size.width
            self.notify(f"side by side needs {core.SPLIT_WIDTH} columns for the diff; it has {width}", timeout=4)
        if self.pr is not None and self.mode == "files":
            self.show_pr()

    # Unchanged lines between hunks: enter on a gap row, or :expand for every gap of the file, reads the file at the
    # head commit once and shows them. They take no comment: a forge takes comments only on the lines of the diff.

    def action_expand(self, every=False):
        if not self.need_pr() or self.mode != "files" or not self.pr.files:
            return
        diff = self.query_one("#diff", DiffRows)
        row = diff.current()
        gaps = (
            [r.counts[0] for r in diff.rows if r.kind == "gap"]
            if every
            else [row.counts[0]]
            if row and row.kind == "gap"
            else []
        )
        if not gaps:
            self.notify("no unchanged lines are folded here", timeout=3)
            return
        missing = core.lacks(self.forge, core.Capability.READ_FILES)
        if missing:
            self.notify(missing, severity="warning")
            return
        pr, item = self.pr, self.pr.files[self.file_index]
        if (pr.repo, item.path, pr.head) in self.file_texts:
            return self.expanded_gaps(pr.key, item.path, gaps)
        self.busy["file"] = f"reading {item.path}..."
        self.show_bars()

        def fetched():
            try:
                found = self.forge.read_file(pr.repo, item.path, pr.head)
            except Exception as error:  # noqa: BLE001 - shown in the app rather than closing it
                self.app.call_from_thread(self.file_read, pr, item.path, gaps, None, failure(error))
                return
            self.app.call_from_thread(self.file_read, pr, item.path, gaps, found.text, "")

        self.run_worker(fetched, thread=True, group="file", exclusive=True)
        return None

    def file_read(self, pr, path, gaps, text, error):
        self.busy.pop("file", None)
        if error or text is None:
            self.notify(error or f"{path} is too large or binary to show here; o opens it", severity="warning")
            self.show_bars()
            return
        self.file_texts[(pr.repo, path, pr.head)] = text.split("\n")
        self.expanded_gaps(pr.key, path, gaps)

    def expanded_gaps(self, key, path, gaps):
        self.expanded.setdefault((key, path), set()).update(gaps)
        if self.pr is not None and self.pr.key == key:
            self.show_pr()

    def show_pr(self, cursor=None):
        widget = self.query_one("#diff", DiffRows)
        old = widget.current()
        rows = self.diff_rows()
        if cursor is None and old is not None:
            same = [
                i
                for i, row in enumerate(rows)
                if row.selectable
                and (row.draft, row.thread, row.anchor, row.kind) == (old.draft, old.thread, old.anchor, old.kind)
            ]
            cursor = same[0] if same else min(widget.cursor, len(rows) - 1)
        widget.set_rows(rows, cursor)
        self.show_bars()
        self.call_after_refresh(self.place_sticky)

    # The file tree (Files tab): f shows or hides it, remembered between runs; beside the diff in a wide pane, over it in
    # a narrow one. tab moves focus between the tree and the diff.

    def wide_pane(self):
        return (self.query_one("#bottom").size.width or self.size.width) >= WIDE

    def tree_on(self):
        """Whether the tree shows on the Files tab: as f last left it, else only in a wide pane."""
        return self.wide_pane() if self.tree_shown is None else self.tree_shown

    def layout_tree(self):
        sidebar, diff = self.query_one("#sidebar"), self.query_one("#diff")
        wide = self.wide_pane()
        files = self.mode == "files" and self.pr is not None and bool(self.pr.files)
        show = files and self.tree_on()
        sidebar.display = show
        sidebar.set_class(show and not wide and not self.tree_full, "overlay")
        sidebar.styles.width = "100%" if self.tree_full else self.tree_width
        diff.display = not (show and self.tree_full)
        if not show and self.files_tree().has_focus:
            diff.focus()

    @staticmethod
    def tree_place(node):
        """Where a node sits, to find it again after a rebuild: a file by its index, a folder by the names above it."""
        if node.data is not None:
            return node.data
        names = []
        while node is not None and node.parent is not None:
            names.append(node.label.plain)
            node = node.parent
        return tuple(reversed(names))

    def tree_remembered(self, tree):
        """What a rebuild keeps of the tree as the reviewer left it: the folded folders, the cursor and the scroll."""
        if not tree.last_line >= 0:
            return None
        folded, stack = set(), list(tree.root.children)
        while stack:
            node = stack.pop()
            if node.data is None:
                if not node.is_expanded:
                    folded.add(self.tree_place(node))
                stack.extend(node.children)
        cursor = tree.cursor_node
        return folded, None if cursor is None else self.tree_place(cursor), tree.scroll_offset.y

    def build_tree(self, follow=False):
        """The tree for the open pull request: status letter, name, threads (#) and drafts (*), +/- counts; viewed files
        dimmed with v. The open file is highlighted. A rebuild keeps the folded folders, the scroll and the cursor where
        the reviewer left them; follow (opening another file, a new filter) moves the cursor to the open file instead."""
        tree = self.files_tree()
        kept = self.tree_remembered(tree) if self.pr is not None else None
        tree.clear()
        if self.pr is None:
            return
        folded, cursor, scroll = kept or (set(), None, 0)
        target = first = None
        viewed = (self.state.get("viewed") or {}).get(self.pr.key, {})
        threads, drafts = {}, {}
        for thread in self.pr.threads:
            threads[thread.path] = threads.get(thread.path, 0) + 1
        for draft in (self.drafts.comments + self.drafts.replies) if self.drafts else []:
            drafts[draft["path"]] = drafts.get(draft["path"], 0) + 1
        letters = {"added": ("A", "ok"), "removed": ("D", "bad"), "renamed": ("R", "info"), "copied": ("C", "info")}
        ink = self.app.painter.ink
        current = None

        def add(parent, nodes):
            nonlocal current, target, first
            for node in nodes:
                if node.index is None:
                    folder = parent.add(Text(node.name + "/", ink("accent", bold=True)), expand=True)
                    place = self.tree_place(folder)
                    if place in folded:
                        folder.collapse()
                    if place == cursor:
                        target = folder
                    add(folder, node.children)
                    continue
                item = self.pr.files[node.index]
                seen = item.sha and viewed.get(item.path) == item.sha
                letter, token = letters.get(item.status, ("M", "warn"))
                label = Text()
                label.append("v " if seen else f"{letter} ", ink("ok" if seen else token, bold=True))
                label.append(node.name, Style(bold=node.index == self.file_index, dim=bool(seen)))
                if threads.get(item.path):
                    label.append(f" #{threads[item.path]}", ink("warn"))
                if drafts.get(item.path):
                    label.append(f" *{drafts[item.path]}", ink("local"))
                label.append(f" +{item.additions}", ink("ok") + Style(dim=True))
                label.append(f" -{item.deletions}", ink("bad") + Style(dim=True))
                leaf = parent.add_leaf(label, data=node.index)
                first = first or leaf
                if node.index == self.file_index:
                    current = leaf
                if node.index == cursor:
                    target = leaf

        add(tree.root, core.file_tree(self.pr.files, self.tree_query))
        seen = sum(1 for item in self.pr.files if item.sha and viewed.get(item.path) == item.sha)
        self.query_one("#sidebar").border_title = f"Files {seen}/{len(self.pr.files)} viewed  e hide  f diff"
        if follow or target is None:
            target = current or first  # the open file, else the first one shown (a filter hid the open one)
        if target is not None:  # once the tree has laid out its lines, or the cursor does not land
            self.call_after_refresh(self.place_tree, target, scroll)

    def place_tree(self, node, scroll):
        if node._line < 0:  # from a tree a later rebuild already replaced
            return
        tree = self.files_tree()
        tree.scroll_to(y=scroll, animate=False, immediate=True)
        tree.move_cursor(node)  # scrolls only as far as the cursor needs

    def set_mode(self, mode, cursor=0):
        """Show one of the lower pane's tabs."""
        self.close_editor()
        self.mode = mode
        self.query_one("#ptabs", Tabs).active = mode
        self.show_pr(cursor=cursor)
        self.layout_tree()
        self.remember()

    def action_ptab(self, mode):
        if mode != self.mode and self.need_pr():
            self.record_jump("diff")
            self.set_mode(mode)

    def action_ptab_step(self, step):
        self.action_ptab(core.TABS[(core.TABS.index(self.mode) + step) % len(core.TABS)])

    # Moving around the diff.

    def need_pr(self):
        if self.pr is None:
            self.notify("no pull request open", severity="warning")
            return False
        return True

    def action_file(self, step):
        if not self.need_pr() or not self.pr.files:
            return
        target = self.file_index + step
        if not 0 <= target < len(self.pr.files):
            self.notify("last file" if step > 0 else "first file", timeout=3)
            return
        self.record_jump("diff")
        self.open_file(target)

    def open_file(self, index):
        self.file_index = index
        self.set_mode("files")
        self.build_tree(follow=True)

    def action_tree_toggle(self):
        """e: edit the draft or your own post under the cursor; elsewhere on the Files tab, show or hide the tree."""
        row = self.query_one("#diff", DiffRows).current() if self.pr is not None else None
        if self.mode == "files" and not (row is not None and row.draft or self.own_post(row)):
            return self.action_files()
        return self.action_edit()

    def action_files(self):
        """e on the Files tab: show or hide the file tree, in every width, and remember it. It never moves focus; f
        does."""
        if not self.need_pr() or not self.pr.files:
            return
        if self.mode != "files":
            self.set_mode("files")
        self.show_tree(not self.tree_on())

    def show_tree(self, shown):
        self.tree_shown = shown
        if self.split_view:  # the diff's width changes with the tree, and with it whether old and new fit side by side
            self.call_after_refresh(self.show_pr)
        self.state.save(tree=shown)
        if not shown:
            self.tree_full = False
        self.build_tree()
        self.layout_tree()
        self.show_bars()
        self.notify(f"file tree {'on' if shown else 'off'} (f)", timeout=2)

    def on_tree_node_selected(self, event: Tree.NodeSelected[int]):
        if event.node.data is None:
            return
        self.tree_full = False
        if not self.wide_pane():  # the tree covers the diff in a narrow pane: get out of the way of the file
            self.tree_shown = False
            self.state.save(tree=False)
        self.record_jump("diff")
        self.open_file(event.node.data)
        self.layout_tree()
        self.query_one("#diff").focus()

    def action_close_files(self):
        """esc in the tree: back to the diff."""
        self.tree_full = False
        self.layout_tree()
        self.query_one("#diff").focus()

    def action_tree_focus(self):
        """f on the Files tab: focus moves between the diff and the file tree, which shows if it was hidden."""
        if self.mode != "files" or not self.need_pr() or not self.pr.files:
            return None
        if self.files_tree().has_focus:
            return self.action_close_files()
        if not self.tree_on():
            self.show_tree(True)
        self.files_tree().focus()
        return None

    def action_pane_left(self):
        """ctrl+h in the diff: focus the file tree, which shows if it was hidden; in the tree it stays where it is."""
        if self.mode == "files" and not self.files_tree().has_focus:
            self.action_tree_focus()

    def action_pane_right(self):
        """ctrl+l in the file tree: focus the diff. The tree stays, with its cursor, scroll and folds as they are."""
        if self.files_tree().has_focus:
            self.action_close_files()

    def action_tree_up(self):
        """h: fold the folder under the cursor, or go up to its folder."""
        tree = self.files_tree()
        node = tree.cursor_node
        if node is None:
            return
        if node.children and node.is_expanded:
            node.collapse()
        elif node.parent is not None and node.parent is not tree.root:
            tree.move_cursor(node.parent)

    def action_tree_full(self):
        if self.mode != "files" or self.pr is None:
            return
        self.tree_full = not self.tree_full
        if self.tree_full:
            self.tree_shown = True
            self.build_tree()
        self.layout_tree()
        (self.files_tree() if self.tree_full else self.query_one("#diff")).focus()

    def action_tree_resize(self, step):
        self.tree_width = min(60, max(20, self.tree_width + step))
        self.state.save(tree_width=self.tree_width)
        self.layout_tree()

    def action_tree_filter(self):
        box = self.query_one("#treefilter", Input)
        box.value = self.tree_query
        box.focus()

    def action_viewed(self):
        """Mark the file under the tree cursor, or the open one, as viewed; it stays viewed until the file changes."""
        if self.pr is None or not self.pr.files:
            return
        tree = self.files_tree()
        index = (
            tree.cursor_node.data
            if tree.has_focus and tree.cursor_node and tree.cursor_node.data is not None
            else self.file_index
        )
        item = self.pr.files[index]
        viewed = self.state.get("viewed") or {}
        marks = viewed.setdefault(self.pr.key, {})
        if marks.get(item.path) == item.sha:
            marks.pop(item.path)
            self.notify(f"{item.path}: not viewed", timeout=3)
        else:
            marks[item.path] = item.sha
            self.notify(f"{item.path}: viewed", timeout=3)
        self.state.save(viewed=viewed)
        self.build_tree()

    def action_unresolved(self):
        self.unresolved_only = not self.unresolved_only
        self.remember()
        if self.pr is not None:
            self.show_pr()
        self.notify("unresolved threads only" if self.unresolved_only else "all threads", timeout=3)

    def thread_files(self):
        """Indexes of the files that have a visible thread, in order."""
        return [
            i
            for i, item in enumerate(self.pr.files)
            if any(t.path == item.path and core.visible(t, self.drafts, self.unresolved_only) for t in self.pr.threads)
        ]

    def action_thread(self, step):
        if (
            self.search and self.pr is not None
        ):  # a search is active: n is its next match (esc ends it, p stays previous thread)
            if step > 0:
                return self.action_match(1)
        if not self.need_pr():
            return
        self.record_jump("diff")
        if self.mode != "files":
            self.set_mode("files")
        widget = self.query_one("#diff", DiffRows)
        heads = [i for i, row in enumerate(widget.rows) if row.kind == "thread"]
        ahead = [i for i in heads if (i > widget.cursor if step > 0 else i < widget.cursor)]
        if ahead:
            widget.go(ahead[0] if step > 0 else ahead[-1])
            return
        others = [i for i in self.thread_files() if (i > self.file_index if step > 0 else i < self.file_index)]
        if not others:
            self.notify("no more threads" if step > 0 else "no earlier threads", timeout=3)
            return
        self.open_file(others[0] if step > 0 else others[-1])
        heads = [i for i, row in enumerate(widget.rows) if row.kind == "thread"]
        if heads:
            widget.go(heads[0] if step > 0 else heads[-1])

    def action_fold(self):
        row = self.query_one("#diff", DiffRows).current()
        thread = self.pr.thread(row.thread) if self.pr and row and row.thread else None
        if thread is not None:
            self.overrides[thread.id] = not core.thread_open(thread, self.overrides)
            self.show_pr()

    def action_open_thread(self):
        """enter on a thread's entry in the Conversation tab: the Files tab at that thread, opened."""
        row = self.query_one("#diff", DiffRows).current()
        thread = self.pr.thread(row.thread) if self.pr and row and row.thread else None
        if thread is None:
            return
        index = next((i for i, item in enumerate(self.pr.files) if item.path == thread.path), None)
        if index is None:
            why = "the files are still loading" if self.pr.files_loading else f"{thread.path} is no longer in the diff"
            self.notify(why, severity="warning", timeout=4)
            return
        self.record_jump("diff")
        self.overrides[thread.id] = True
        self.open_file(index)
        widget = self.query_one("#diff", DiffRows)
        head = next(
            (i for i, item in enumerate(widget.rows) if item.kind == "thread" and item.thread == thread.id), None
        )
        if head is None:
            self.notify("the thread is hidden: u shows resolved threads too", severity="warning", timeout=4)
        else:
            widget.go(head)

    # Drafts, written inline. Nothing here talks to the forge.

    def watch_only(self):
        """Personal repositories are only watched from here: no drafts, no posts, no actions."""
        repo = self.pr.repo if self.pr is not None else ""
        return self.scope_kind == "personal" or core.personal_repo(repo, self.login)

    def refuse_personal(self):
        if self.watch_only():
            self.notify(
                f"personal repositories are read-only here: view them, or open them in {self.forge.label} (o)",
                severity="warning",
            )
            return True
        return False

    def writer(self):
        """The forge writes go through: one that refuses them all when this pull request is only watched."""
        return self.forge.reader() if self.watch_only() else self.forge

    def can_edit(self):
        if not self.need_pr() or self.refuse_personal():
            return False
        if "post" in self.busy:
            self.notify("wait until posting finishes", severity="warning")
            return False
        return True

    def save_drafts(self):
        try:
            self.store.save(self.drafts)
        except OSError as error:
            self.notify(f"drafts could not be saved: {error}", severity="error", timeout=15)
        self.read_drafts()
        self.show_list()
        self.show_pr()
        self.build_tree()

    def open_editor(self, title, text, after, keep):
        """An editor under row `after` of the diff: the diff opens a gap there and the editor sits in it."""
        diff = self.query_one("#diff", DiffRows)
        diff.gap = (after, EDITOR_HEIGHT)
        diff.relayout()
        diff.call_after_refresh(diff.reveal_gap)  # once the gap is laid out, so the scroll can reach it
        self.query_one("#editor-title", Static).update(
            Text(f"{title}   ctrl+s keep as draft  esc cancel", style="bold")
        )
        area = self.query_one("#editor-text", InlineText)
        area.text = text
        self.query_one("#editor").display = True
        self.editing = ("editor", keep)
        area.focus()
        area.move_cursor(area.document.end)
        self.call_after_refresh(self.place_editor)
        self.refresh_bindings()

    def review_progress(self, short=False):
        """How far the review is: files viewed of all, open threads, your drafts; empty without a pull request. Short
        is the statusline's: 2/5 viewed 3 open 1 draft."""
        pr = self.pr
        if pr is None:
            return ""
        marks = (self.state.get("viewed") or {}).get(pr.key, {})
        viewed = sum(1 for item in pr.files if item.sha and marks.get(item.path) == item.sha)
        parts = (
            [f"{viewed}/{len(pr.files)} viewed" if short else f"viewed {viewed}/{len(pr.files)}"] if pr.files else []
        )
        open_threads = sum(1 for thread in pr.threads if not thread.resolved)
        if open_threads:
            parts.append(
                f"{open_threads} open" if short else f"{open_threads} open thread{'s' if open_threads != 1 else ''}"
            )
        drafts = self.drafts.count() if self.drafts else 0
        if drafts:
            parts.append(f"{drafts} draft{'s' if drafts != 1 else ''}")
        return (" " if short else "  ").join(parts)

    def diff_scrolled(self):
        self.place_editor()
        self.place_sticky()

    def place_sticky(self):
        """The line above the diff on the Files tab: the file, and the hunk the top of the view is in, so both stay in
        sight while their headers scroll away. A line of its own, so it never covers a row of the diff."""
        sticky = self.query_one("#sticky", Static)
        diff = self.query_one("#diff", DiffRows)
        shown = self.mode == "files" and self.pr is not None and bool(diff.rows) and diff.rows[0].kind == "file"
        if sticky.display != shown:  # only a change: each one lays the pane out again
            sticky.display = shown
        if not shown:
            return
        top = diff.row_at_line(0)
        hunk = next((row for row in reversed(diff.rows[: top + 1]) if row.kind == "hunk"), None)
        ink = self.app.painter.ink
        text = Text(" ")
        text.append(diff.rows[0].body, ink("accent", bold=True))
        if hunk is not None:
            text.append(f" {self.icons['crumb']} ", ink("subtle"))
            text.append(core.clean(hunk.text), ink("muted"))
        sticky.update(text)

    def place_editor(self):
        """Keep the editor over its gap as the diff scrolls; it never leaves the diff pane."""
        editor = self.query_one("#editor")
        diff = self.query_one("#diff", DiffRows)
        if not editor.display or diff.gap_start is None:
            return
        bottom = self.query_one("#bottom")
        top = diff.region.y - bottom.region.y
        y = top + diff.gap_start - diff.scroll_offset.y
        y = max(top, min(y, top + max(0, diff.size.height - EDITOR_HEIGHT)))
        x = diff.region.x - bottom.region.x + self.number_width + 1
        editor.styles.offset = (x, y)
        editor.styles.width = max(20, diff.size.width - self.number_width - 1)

    def close_editor(self):
        if not self.editing:
            return
        which, _keep = self.editing
        self.editing = None
        if which == "bar":  # the review bar's summary field: back to the bar's keys
            self.bar_summary_closed()
            self.refresh_bindings()
            return
        if which == "summary":
            self.query_one("#summary").display = False
        else:
            self.query_one("#editor").display = False
            diff = self.query_one("#diff", DiffRows)
            diff.gap = None
            diff.relayout()
        self.query_one("#diff").focus()
        self.refresh_bindings()
        if self.pending_pr is not None:  # the fresh read that came in while the editor was open
            pr, self.pending_pr = self.pending_pr, None
            self.open_pr(pr, keep=True)

    def action_keep_text(self):
        if not self.editing:
            return
        which, keep = self.editing
        text = self.query_one(f"#{which}-text", InlineText).text
        self.editing = (which, lambda _text: None)  # closed below; keep runs once, with the text read above
        keep(text)
        self.close_editor()

    def action_drop_text(self):
        self.close_editor()

    def last_row_of(self, thread_id):
        rows = self.query_one("#diff", DiffRows).rows
        return max(i for i, row in enumerate(rows) if row.thread == thread_id)

    def action_comment(self):
        if not self.can_edit():
            return
        diff = self.query_one("#diff", DiffRows)
        row = diff.current()
        if row is not None and row.draft and row.draft != "summary":
            return self.action_edit()
        if self.mode != "conversation" and (row is None or not row.anchor):
            self.notify("move the cursor to a diff line to comment", severity="warning")
            return
        if self.mode == "conversation":
            offered = self.offer("A comment on the conversation", "Comment now", self.note_now, self.action_comment)
        else:
            single = core.Capability.SINGLE_COMMENTS
            now = lambda: self.line_now(row)  # noqa: E731 - the row the cursor was on when the key was pressed
            offered = self.offer(
                f"A comment on line {row.anchor[2]}", "Add single comment", now, self.action_comment, capability=single
            )
        if not offered:
            return
        if self.mode == "conversation":  # a comment on the conversation, written at its end; then the bar asks for y
            return self.compose_note()
        path, side, line = row.anchor
        item = self.pr.file(path)
        index = item.find(side, line) if item else None
        context = core.line_context(item, index) if index is not None else None  # the code as it reads now

        def keep(text):
            if text.strip():
                self.drafts.add_comment(path, side, line, text, context)
                self.save_drafts()

        self.open_editor(f"Comment on line {line}{'' if side == 'RIGHT' else ' (old file)'}", "", diff.cursor, keep)

    def action_reply(self):
        if not self.can_edit():
            return
        row = self.query_one("#diff", DiffRows).current()
        thread = self.pr.thread(row.thread) if row and row.thread else None
        if thread is None or thread.root is None:
            self.notify("move the cursor to a thread to reply (n/p jump to threads)", severity="warning")
            return
        doing = f"A reply to {thread.root.author}"
        if not self.offer(doing, "Reply now", lambda: self.reply_now(thread), self.action_reply, "Add to review"):
            return
        if not core.thread_open(thread, self.overrides):  # open it, so the reply sits under the whole thread
            self.overrides[thread.id] = True
            self.show_pr()

        def keep(text):
            if text.strip():
                self.drafts.add_reply(thread, text)
                self.save_drafts()

        self.open_editor(f"Reply to {thread.root.author}", "", self.last_row_of(thread.id), keep)

    def action_resolve(self):
        if not self.can_edit():
            return
        row = self.query_one("#diff", DiffRows).current()
        thread = self.pr.thread(row.thread) if row and row.thread else None
        if thread is None:
            self.notify("move the cursor to a thread to resolve it", severity="warning")
            return
        verb = "Unresolve" if thread.resolved else "Resolve"
        where = f"{verb} the thread on {thread.path}, line {thread.line or thread.original_line}"
        if not self.offer(
            where,
            f"{verb} now",
            lambda: self.resolve_now(thread),
            self.action_resolve,
            "Add to review",
            capability=core.Capability.RESOLVE_THREADS,
        ):
            return
        marked = self.drafts.toggle_resolve(thread)
        self.save_drafts()
        if marked:
            self.notify(f"will {'unresolve' if thread.resolved else 'resolve'} on submit", timeout=3)
        else:
            self.notify("resolve mark removed", timeout=3)

    def action_edit(self):
        if not self.need_pr():
            return
        posted = self.query_one("#diff", DiffRows).current()
        if posted is not None and not posted.draft and self.own_post(posted):
            return self.edit_post(posted)
        if not self.can_edit():
            return
        diff = self.query_one("#diff", DiffRows)
        row = diff.current()
        if row is None or not row.draft:
            self.notify("move the cursor to a draft to edit it", severity="warning")
            return
        if row.draft == "summary":
            return self.action_summary()
        item = self.drafts.find(row.draft)
        if item is None or "body" not in item:
            self.notify("a resolve mark has no text; x removes it", severity="warning")
            return
        draft_id = row.draft

        def keep(text):
            self.drafts.edit(draft_id, text)
            self.save_drafts()

        self.open_editor("Edit draft (empty text deletes it)", item["body"], diff.cursor, keep)

    def action_delete(self):
        if not self.need_pr():
            return
        row = self.query_one("#diff", DiffRows).current()
        if row is not None and not row.draft and self.own_post(row):
            if self.delete_armed != row.post:  # d d, as for a draft; then the dialog shows what goes
                self.delete_armed = row.post
                self.notify("press d again to delete your comment from the forge", timeout=4)
                return None
            self.delete_armed = None
            return self.delete_post(row)
        if not self.can_edit():
            return
        if row is None or not row.draft:
            self.notify("move the cursor to a draft or a comment of yours to delete it", severity="warning")
            return
        if self.delete_armed != row.draft:  # d d, like vim: one press arms, the second deletes
            self.delete_armed = row.draft
            self.notify("press d again to delete this draft; it was never posted", timeout=4)
            return
        self.delete_armed = None
        if row.draft == "summary":
            self.drafts.summary = ""
        else:
            self.drafts.delete(row.draft)
        self.save_drafts()
        self.notify("draft deleted", timeout=3)

    def action_summary(self):
        if not self.can_edit() or not self.under_review(self.action_summary, "The review summary"):
            return
        area = self.query_one("#summary-text", InlineText)
        area.text = self.drafts.summary

        def keep(text):
            self.drafts.summary = text
            self.save_drafts()

        self.close_editor()
        self.editing = ("summary", keep)
        self.query_one("#summary").display = True
        area.focus()
        area.move_cursor(area.document.end)
        self.refresh_bindings()
