# SPDX-FileCopyrightText: 2026 Cristiano Carvalho
# SPDX-License-Identifier: Apache-2.0
"""The top pane: the lists and their scopes, groups and filters, the details strip, links, and loading the pull request under the cursor."""

from __future__ import annotations

import time

from textual import events
from textual.widgets import (
    Button,
    Input,
    Static,
    Tabs,
)

from morann import core
from morann.dialogs import ConfirmScreen, ScopeScreen
from morann.widgets import (
    DEBOUNCE,
    LIST_MIN,
    RECENT,
    REFRESH_GAP,
    DiffRows,
    Info,
    ListRows,
    LoadMore,
    Rows,
    failure,
)

SEARCH_PAUSE = 0.4  # seconds typing in / rests before the All tab searches the forge


class ListsMixin:
    """The top pane: the lists and their scopes, groups and filters, the details strip, links, and loading the pull request under the cursor. Mixed into Main."""

    # Painting.

    def paint_list(self, row, width, index):
        rows = self.query_one("#list", ListRows).rows
        key = (width, id(rows), len(rows), tuple(sorted(self.counts.items())), tuple(sorted(self.flags.items())))
        if self.columns[0] != key:  # every row of the list shares the column widths
            self.columns = (
                key,
                core.list_columns(
                    rows,
                    width,
                    counts=self.row_counts(),
                    show_owner=self.scope.several_owners(),
                    icons=self.icons,
                    show_author=self.scope_kind != "mine" or self.tab == "all",
                    show_repo=not self.in_groups(),
                    flags=self.flags,
                ),
            )
        return self.app.painter.list_row(
            row,
            width,
            index,
            self.row_counts(),
            self.scope,
            self.icons,
            self.now,
            self.columns[1],
            flags=self.flags,
            waits=self.waits,
        )

    def row_counts(self):
        """The drafts chip of each row: local drafts, and on the Pending tab the forge's pending comments too."""
        if self.tab == "pending":
            return {item.row.key: item.drafts for item in self.pending}
        return self.counts

    def show_detail_strip(self):
        """The highlighted pull request's details panel under the lists; i folds it. It takes what the pane can spare
        while the list keeps LIST_MIN rows: up to core.PANEL_LINES lines with a blank row above and below, then no
        blank rows, then fewer lines, then nothing."""
        panel = self.query_one("#details", Static)
        row = self.chosen()  # the same pull request the lower pane shows
        top = self.query_one("#top")
        bars = 1 if self.query_one("#filter").display else 0
        room = (top.size.height or 0) - 2 - bars - LIST_MIN  # the tabs take two rows
        margins = room >= 5
        limit = min(core.PANEL_LINES, room - (4 if margins else 2))
        panel.display = self.show_details and isinstance(row, core.PrRow) and limit > 0
        if panel.display:
            width = max(10, top.size.width - 5)  # the pane's edge, the border and the padding
            panel.styles.margin = (1, 0, 1, 0) if margins else (0, 0, 0, 0)
            panel.border_title = self.app.painter.panel_title(row)
            panel.update(self.app.painter.details(row, width, limit, self.icons, self.now))

    def action_details(self):
        self.show_details = not self.show_details
        self.state.save(details=self.show_details)
        self.show_detail_strip()

    def in_groups(self):
        """Whether the list groups its rows by repository: as g sets it, except on Pending, a queue oldest first."""
        return self.grouped and self.tab != "pending"

    def read_drafts(self):
        """What the drafts folder holds now: the drafts per pull request and when each was last kept."""
        self.drafted = self.store.waiting()
        self.counts = {key: count for key, (count, _kept) in self.drafted.items() if count}

    def pending_items(self):
        """The Pending tab: reviews in progress, here or on the forge, the one waiting longest first."""
        rows = [*self.recent_rows(filtered=False), *self.all_rows()]
        return core.pending_rows(rows, self.drafted, self.unlisted_row)

    def unlisted_row(self, key):
        """A row for a pull request no list holds, named from what was remembered of it."""
        repo, _, number = key.rpartition("#")
        known = next((item for item in self.state.get("recent") or [] if f"{item['repo']}#{item['number']}" == key), {})
        return core.PrRow(
            repo=repo,
            number=int(number),
            title=known.get("title") or "",
            url=self.forge.pr_url(repo, int(number)),
            author=known.get("author") or "",
            draft=False,
            decision="",
            checks="",
            created="",
            updated="",
        )

    def visible_rows(self):
        """The rows of the open tab, with the author filter (a) and the my-pull-requests filter (m) applied."""
        if self.tab == "all":
            rows = self.wide["rows"] if self.wide else []
        elif self.tab == "pending":
            self.pending = self.pending_items()
            rows = [item.row for item in self.pending]
        else:
            rows = getattr(self.lists, self.tab, []) if self.lists else []
        who = "me" if self.only_mine else self.authors
        rows = core.by_author(rows, who, self.login)
        needle = self.filter.casefold()
        rows = [row for row in rows if not needle or needle in f"{row.key} {row.title} {row.author}".casefold()]
        found = self.searched()
        if found:  # the loaded matches, then what the forge found on pages not loaded
            keys = {row.key for row in rows}
            rows += [row for row in core.by_author(found["rows"], who, self.login) if row.key not in keys]
        return self.attention_filtered(rows)

    def searched(self):
        """The All tab's search on the forge for the filter text when it is for what is on screen now, else None."""
        found = self.found
        if found and self.tab == "all" and found["text"] == self.filter and found["kind"] == self.scope_kind:
            return found
        return None

    def all_page(self):
        """The All tab's page its counts and Load more follow: a search's result, else the scope's pages loaded so far."""
        found = self.searched()
        return found if found and not found["error"] else self.wide

    def want_search(self):
        """On the All tab, search the forge for the filter text once typing rests SEARCH_PAUSE, never on each
        keystroke. A forge without search across a scope only narrows the loaded rows."""
        if self.search_timer is not None:
            self.search_timer.stop()
            self.search_timer = None
        if not self.filter:
            self.found = None
        searches = core.Capability.SEARCH in self.forge.capabilities
        if searches and self.tab == "all" and self.filter and self.wide is not None and not self.searched():
            self.search_timer = self.set_timer(SEARCH_PAUSE, self.search_all)

    def search_all(self):
        self.search_timer = None
        if self.tab != "all" or not self.filter or self.wide is None:
            return
        self.search_token += 1
        token, text, kind = self.search_token, self.filter, self.scope_kind
        self.busy["search"] = "searching..."
        self.show_bars()

        def fetched():
            try:
                page = self.forge.list_scope(self.scope, kind, self.login, text=text)
            except Exception as error:  # noqa: BLE001 - shown in the list rather than closing the app
                self.app.call_from_thread(self.search_loaded, token, text, kind, None, failure(error))
                return
            self.app.call_from_thread(self.search_loaded, token, text, kind, page)

        self.run_worker(fetched, thread=True, group="search", exclusive=True)

    def search_loaded(self, token, text, kind, page, error=""):
        if token != self.search_token:  # a newer search is on its way
            return
        self.busy.pop("search", None)
        if kind == self.scope_kind:
            self.found = {
                "text": text,
                "kind": kind,
                "error": error,
                "rows": page.rows if page else [],
                "total": page.total if page else 0,
                "cursor": page.cursor if page else None,
            }
        self.show_list()

    def recent_rows(self, filtered=True):
        """The pull requests opened by link, newest first, as list rows; the lists' own row when it has one."""
        known = {row.key: row for row in (self.lists.mine + self.lists.review if self.lists else [])}
        needle = self.filter.casefold() if filtered else ""
        rows = []
        for item in self.state.get("recent") or []:
            key = f"{item['repo']}#{item['number']}"
            row = known.get(key) or core.PrRow(
                repo=item["repo"],
                number=int(item["number"]),
                title=item.get("title") or "",
                url=self.forge.pr_url(item["repo"], item["number"]),
                author=item.get("author") or "",
                draft=False,
                decision="",
                checks="",
                created="",
                updated="",
            )
            if not needle or needle in f"{row.key} {row.title} {row.author}".casefold():
                rows.append(row)
        return rows

    def show_list(self, wait=DEBOUNCE):
        widget = self.query_one("#list", ListRows)
        rows = self.visible_rows()
        self.flags, self.waits = self.attention_flags(rows), self.attention_waits(rows)
        if (
            not self.in_groups()
        ):  # flagged first, then by wait on To Review, else by latest update; grouped: in each group
            rows = self.attention_order(rows)
        recent = (
            self.recent_rows() if self.scope_kind == "mine" and self.tab in ("mine", "review") else []
        )  # Recent belongs to Mine
        if self.lists is None and self.error:
            shown = [Info(f"{self.error}  r retries", "bad")]
        elif self.lists is None or (self.tab == "all" and self.wide is None and "lists" in self.busy):  # skeleton rows
            shown = [
                Info(f"loading pull requests{self.where()}...", "dim"),
                *(Info("\u2591" * width, "dim") for width in (34, 46, 28, 40)),
            ]
        elif not rows:
            shown = [
                Info(
                    "no pull requests match the filter"
                    if self.filter or self.attention_filter
                    else "no open pull requests here"
                    if self.scope_kind != "mine"
                    else "nothing here"
                )
            ]
        else:
            shown = rows
        if rows and self.in_groups():
            shown = core.group_rows(rows, self.collapsed, order=self.attention_order, flags=self.flags)
        filters = [f"authors: {self.authors} (a)"] if self.authors != "all" else []
        filters += ["my pull requests only (m)"] if self.only_mine else []
        filters += (
            [f"{self.attention_filter} only ({core.attention.KEYS[self.attention_filter]})"]
            if self.attention_filter
            else []
        )
        found, page = self.searched(), self.all_page()
        if self.tab == "all" and page:
            filters.insert(
                0,
                f'{page["total"]} found for "{self.filter}" in {self.scope_name()}'
                if page is found
                else f"{page['total']} open in {self.scope_name()}",
            )
            if page["cursor"]:
                shown.append(LoadMore(self.forge.page_size, len(page["rows"]), page["total"]))
        if found and found["error"]:  # the loaded rows stay; one line says why nothing more was found
            shown = [Info(f"search failed: {found['error']}; showing the loaded rows", "bad"), *shown]
        if filters:
            shown = [Info(", ".join(filters), "heading"), *shown]
        if recent:
            label = "Needs my review" if self.tab == "review" else "My PRs"
            shown = [Info("recent", "heading"), *recent, Info(label, "heading"), *shown]
        keys = [getattr(row, "key", None) for row in shown]
        first = next((i for i, row in enumerate(shown) if isinstance(row, core.PrRow)), None)
        if self.wanted is not None and self.wanted in keys:
            widget.set_rows(shown, keys.index(self.wanted))
        elif self.wanted is not None and self.wanted == self.pinned():  # kept below: the list shows no selection
            widget.set_rows(shown, None, unselected=True)
        else:  # a pull request, not a header; the first one when the list had none
            had = any(isinstance(row, core.PrRow) for row in widget.rows)
            widget.set_rows(shown, first if not had or widget.cursor == 0 or widget.cursor >= len(shown) else None)
        self.sync_open(wait)
        self.show_detail_strip()
        self.show_bars()

    def selected(self):
        row = self.query_one("#list", ListRows).current()
        return row if isinstance(row, core.PrRow) else None

    # Lists.

    def load_lists(self):
        self.busy["lists"] = "refreshing..."
        self.show_bars()
        self.run_worker(self.fetch_lists, thread=True, group="lists", exclusive=True)

    def scope_name(self):
        """The scope as the All tab's header names it: the configured owners for Mine, else the organization or Personal."""
        return self.scope.label() if self.scope_kind == "mine" else core.scope_label(self.scope_kind)

    def where(self):
        """` in <scope>` for the messages of a list that is wider than Mine and To Review, else nothing."""
        return f" in {self.scope_name()}" if self.scope_kind != "mine" or self.tab == "all" else ""

    def fetch_lists(self):
        """Mine and To Review first, so the first paint is one call; then the All tab's first page, which keeps the rows on
        screen until it lands."""
        kind = self.scope_kind
        try:
            login = self.login
            if kind != "mine":  # Mine and To Review narrowed to the scope, which the personal one names by login
                login = login or self.forge.viewer_login()
            lists = self.forge.list_pull_requests(self.scope, kind, login)
        except Exception as error:  # noqa: BLE001 - a worker that raises closes the app; show the error instead
            self.app.call_from_thread(self.lists_failed, failure(error))
            return
        self.app.call_from_thread(self.lists_loaded, lists, kind)
        try:
            page = self.forge.list_scope(self.scope, kind, lists.viewer or login)
        except Exception as error:  # noqa: BLE001 - shown in the app rather than closing it
            self.app.call_from_thread(self.lists_failed, failure(error))
            return
        self.app.call_from_thread(self.wide_loaded, page, kind)

    def lists_loaded(self, lists, kind="mine"):
        if kind != self.scope_kind:  # a scope changed while this was loading
            return
        self.error = ""
        first = self.lists is None
        self.lists = lists
        self.login = lists.viewer or self.login
        self.refreshed_at = self.clock()
        other = "mine" if self.tab == "review" else "review"
        if (
            first and self.tab in ("mine", "review") and not getattr(lists, self.tab) and getattr(lists, other)
        ):  # one that has something
            self.tab = other
            self.query_one("#tabs", Tabs).active = other
        self.read_drafts()
        self.show_list()

    def wide_loaded(self, page, kind):
        if kind != self.scope_kind:
            return
        self.busy.pop("lists", None)
        self.wide = {"rows": page.rows, "total": page.total, "cursor": page.cursor}
        self.found = None  # a refresh searches again
        self.show_list()
        self.want_search()

    def lists_failed(self, message):
        self.busy.pop("lists", None)
        self.error = message
        self.read_drafts()
        self.show_list()
        self.notify(message, severity="error", timeout=10)

    def action_tab(self, name):
        if name != self.tab:
            self.query_one("#tabs", Tabs).active = name

    def on_tabs_tab_activated(self, event: Tabs.TabActivated):
        name = event.tab.id
        if event.tabs.id == "ptabs":  # a click on a lower-pane tab
            if name in core.TABS and name != self.mode and self.pr is not None:
                self.set_mode(name)
            return
        if name in core.LIST_TABS and name != self.tab:
            self.tab = name
            self.show_tab()

    def show_tab(self):
        """The list of the open tab, and below it the pull request now under the cursor, or nothing."""
        self.wanted = None
        self.query_one("#list", ListRows).cursor = 0
        self.show_list()
        self.remember()
        self.want_search()

    def action_only_mine(self):
        self.only_mine = not self.only_mine
        self.remember()
        self.show_list()
        self.notify("my pull requests only" if self.only_mine else "everyone's pull requests", timeout=3)

    def action_filter(self):
        box = self.query_one("#filter", Input)
        box.display = True
        box.value = self.filter
        box.focus()

    def on_input_changed(self, event: Input.Changed):
        if event.input.id == "treefilter":
            self.tree_query = event.value
            self.build_tree(follow=True)
            return
        if event.input.id == "search":
            self.search_changed(event.value)
            return
        if event.input.id != "filter":
            return
        self.filter = event.value.strip()
        self.show_list()
        self.want_search()

    def on_input_submitted(self, event: Input.Submitted):
        if event.input.id == "treefilter":
            self.files_tree().focus()
            return
        if event.input.id == "search":
            self.search_done(keep=True)
            return
        if event.input.id == "cmdline":
            self.run_command(event.value)
        else:
            self.close_filter()

    def on_key(self, event: events.Key):
        if event.key == "escape" and self.query_one("#filter", Input).has_focus:
            self.filter = ""
            self.close_filter()
            event.stop()
        elif event.key == "escape" and self.query_one("#treefilter", Input).has_focus:
            self.query_one("#treefilter", Input).value = ""
            self.files_tree().focus()
            event.stop()

    def close_filter(self):
        box = self.query_one("#filter", Input)
        box.display = bool(self.filter)
        self.query_one("#list").focus()
        self.want_search()  # esc: no search, and the paged list again
        self.show_list()
        self.remember()

    def action_open_diff(self):
        row = self.query_one("#list", ListRows).current()
        if isinstance(row, core.GroupRow):
            return self.action_group_fold(not row.collapsed)
        if isinstance(row, LoadMore):
            return self.load_more()
        if self.selected():
            if self.tab == "pending":  # straight to the review in progress: the first draft, once it is read
                self.to_drafts = self.selected().key
            self.record_jump("list")  # ctrl+o from the pull request comes back to this row
            self.focus_pane = "diff"
            self.layout_panes()
            self.query_one("#diff").focus()
            if self.pr is None or self.pr.key != self.selected().key:
                self.selection_changed(self.selected(), wait=0)
            else:
                self.land_on_drafts()  # already read: land now
        return None

    # Links: built by the forge from checked parts and opened only on its own host, never anything the API returned.

    def current_ref(self):
        """(repo, number) of the pull request the keys act on: the open one in the lower pane, else the selected row."""
        row = self.pr if self.focus_pane == "diff" and self.pr is not None else self.selected() or self.pr
        return (row.repo, row.number) if row is not None else None

    def open_url(self, url):
        if not self.forge.owns_url(url):
            self.notify(f"Morann opens {self.forge.host} links only", severity="warning")
            return
        self.opener(url)
        self.notify(f"opening {url}", timeout=4)

    def action_open_pr(self):
        ref = self.current_ref()
        if ref:
            self.open_url(self.forge.pr_url(*ref))

    def action_open_here(self):
        row = self.query_one("#diff", DiffRows).current() if self.pr is not None else None
        link = getattr(row, "link", "") if row is not None else ""
        if link:
            self.open_url(link)
        else:
            self.action_open_pr()

    def action_open_check(self):
        """o or enter on a check: its details page when the forge owns it, else the forge's page for the check run."""
        self.action_open_here()

    def on_button_pressed(self, event: Button.Pressed):
        """The top bar's scope button and the pull request header's buttons; each does what its key does."""
        press = {
            "open-gh": self.action_open_here,
            "scope": self.action_scope,
            "comment": self.action_converse,
            "review": lambda: self.action_submit("COMMENT"),
            "approve": lambda: self.action_submit("APPROVE"),
            "changes": lambda: self.action_submit("REQUEST_CHANGES"),
            "merge": self.action_actions,
            "actions": self.action_actions,
            "tree-toggle": self.action_files,
        }
        if event.button.id in press and not (self.editing or self.submitting or self.acting):
            press[event.button.id]()

    def tick(self):
        if self.busy:
            self.spin += 1
            self.show_bars()
        else:
            self.show_scope()  # the refresh age counts on while nothing is loading

    def action_scope(self):
        """The scope popup: Mine, Personal and each organization the login belongs to (read when it opens)."""

        def fetched():
            try:
                orgs = self.forge.organizations() if core.Capability.ORGANIZATIONS in self.forge.capabilities else []
            except Exception as error:  # noqa: BLE001 - shown in the app rather than closing it
                self.app.call_from_thread(self.notify, failure(error), severity="error", timeout=8)
                orgs = []
            choices = ["mine", "personal", *(f"org:{org}" for org in orgs)]
            self.app.call_from_thread(self.app.push_screen, ScopeScreen(choices, self.scope_kind), self.scope_picked)

        self.run_worker(fetched, thread=True, group="orgs", exclusive=True)

    def scope_picked(self, kind):
        if not kind or kind == self.scope_kind:
            return
        unsent = self.store.counts()
        if unsent:  # drafts stay saved with their pull request; say so before the view changes
            count = len(unsent)
            what = f"Unsent drafts on {count} pull request{'s' if count > 1 else ''} stay saved with them."
            name = core.scope_label(kind)
            self.app.push_screen(
                ConfirmScreen(f"Switch to {name}", what, "Switch"), lambda yes: yes and self.switch_scope(kind)
            )
            return
        self.switch_scope(kind)

    def switch_scope(self, kind):
        """Show another scope from a clean slate: no list, details, pull request or selection of the old one stays."""
        self.generation += 1
        self.scope_kind = kind
        self.state.save(scope=kind)
        if self.timer is not None:
            self.timer.stop()
            self.timer = None
        self.close_editor()
        self.lists, self.wide, self.columns, self.refreshed_at = None, None, (None, None), None
        self.pr = self.drafts = self.last_row = self.wanted = self.loading_key = None
        self.linked = self.held = self.failed = None
        self.prs.clear()
        self.error = ""
        self.files_tree().clear()
        self.query_one("#list", ListRows).cursor = 0
        self.show_list()
        self.show_pr(cursor=0)
        self.layout_tree()
        self.load_lists()

    def action_authors(self):
        self.authors = core.AUTHORS[(core.AUTHORS.index(self.authors) + 1) % len(core.AUTHORS)]
        self.state.save(authors=self.authors)
        self.show_list()

    def action_toggle_group(self):
        self.grouped = not self.grouped
        self.state.save(grouped=self.grouped)
        self.columns = (None, None)
        self.show_list()

    def action_group_step(self, step):
        """{ and }: the previous and next repository header of the grouped list, as vim moves between paragraphs; with
        none left in that direction, the first or last row."""
        rows = self.query_one("#list", ListRows)
        span = range(rows.cursor + 1, len(rows.rows)) if step > 0 else range(rows.cursor - 1, -1, -1)
        found = next((index for index in span if isinstance(rows.rows[index], core.GroupRow)), None)
        rows.jumped()
        rows.go(found if found is not None else len(rows.rows) - 1 if step > 0 else 0, step)

    def action_group_fold(self, fold):
        row = self.query_one("#list", ListRows).current()
        if not isinstance(row, core.GroupRow) or row.collapsed == fold:
            return
        (self.collapsed.add if fold else self.collapsed.discard)(row.repo)
        self.state.save(collapsed=sorted(self.collapsed))
        self.wanted = row.key
        self.show_list()

    def load_more(self):
        """The next page of the All tab, or of its search while one is shown."""
        current = self.all_page()
        if not current or not current["cursor"] or "lists" in self.busy:
            return
        self.busy["lists"] = "loading more..."
        kind, cursor = self.scope_kind, current["cursor"]
        text = current["text"] if current is self.found else ""

        def fetched():
            try:
                page = self.forge.list_scope(self.scope, kind, self.login, after=cursor, text=text)
            except Exception as error:  # noqa: BLE001 - shown in the app rather than closing it
                self.app.call_from_thread(self.lists_failed, failure(error))
                return
            self.app.call_from_thread(self.more_loaded, page, kind, text)

        self.run_worker(fetched, thread=True, group="lists", exclusive=True)

    def more_loaded(self, page, kind, text=""):
        self.busy.pop("lists", None)
        if kind != self.scope_kind:
            return
        current = self.found if text else self.wide
        if current and (not text or current["text"] == text):
            current.update(rows=current["rows"] + page.rows, total=page.total, cursor=page.cursor)
        self.show_list()

    def open_ref(self, repo, number):
        """Show any pull request below, listed under Recent, even when neither list has it."""
        key = f"{repo}#{number}"
        recent = [item for item in self.state.get("recent") or [] if f"{item['repo']}#{item['number']}" != key]
        known = next(
            (row for row in (self.lists.mine + self.lists.review if self.lists else []) if row.key == key), None
        )
        recent.insert(
            0,
            {
                "repo": repo,
                "number": number,
                "title": known.title if known else "",
                "author": known.author if known else "",
            },
        )
        self.state.save(recent=recent[:RECENT])
        self.linked = next(row for row in self.recent_rows(filtered=False) if row.key == key)
        self.wanted = key
        self.focus_pane = "diff"
        self.show_list(wait=0)  # in the list it is selected there; else it stays below with no selection
        self.layout_panes()
        self.query_one("#diff").focus()

    def on_rows_moved(self, event: Rows.Moved):
        if event.rows.id == "list":
            self.failed = None  # coming back to a pull request whose read failed reads it again
            self.sync_open()
            self.show_detail_strip()
        self.delete_armed = None
        self.show_bars()

    # The pull request under the list cursor.

    def selection_changed(self, row, wait=DEBOUNCE):
        if self.timer is not None:
            self.timer.stop()
            self.timer = None
        if not isinstance(row, core.PrRow):
            return
        self.wanted = row.key
        self.failed = None
        self.remember()
        if self.pr is not None and self.pr.key == row.key and not self.pr.stale:
            return  # already on screen and fresh; a cached one still gets its fresh read below
        if row.key in self.prs:
            self.open_pr(self.prs[row.key])
            return
        cached = self.cache.get(row.repo, row.number)
        if cached is not None:  # the last read at once, marked stale; the fresh one follows after the pause
            try:
                self.open_pr(self.forge.build_pr(row.repo, row.number, cached, stale=True))
            except core.ForgeError:
                pass
        if self.pr is not None and self.pr.key != row.key:  # its skeleton at once, never the last pull request
            self.close_editor()
            self.pr = self.drafts = None
            self.files_tree().clear()
        self.loading_key = row.key
        if self.pr is None:
            self.show_pr(cursor=0)
            self.layout_tree()
        if wait:
            self.timer = self.set_timer(wait, lambda: self.settled(row))
        else:
            self.load_pr(row)

    def settled(self, row):
        self.timer = None
        if row.key == self.wanted:
            self.load_pr(row)

    def load_pr(self, row, reason="loading"):
        self.busy["pr"] = f"{reason} {row.key}..."
        self.show_pr()  # a skeleton while nothing of it is on screen
        self.show_bars()
        generation = self.generation
        self.run_worker(
            lambda: self.fetch_pr(row.repo, row.number, generation), thread=True, group="pr", exclusive=True
        )

    def fetch_pr(self, repo, number, generation=0):
        """Read the pull request: the conversation, commits and checks show as soon as they arrive, then the files."""

        def early(raw):
            self.app.call_from_thread(self.pr_partial, self.forge.build_pr(repo, number, raw), generation)

        try:
            raw = self.forge.fetch_pr(repo, number, on_conversation=early)
            pr = self.forge.build_pr(repo, number, raw)
        except Exception as error:  # noqa: BLE001 - shown in the app rather than closing it
            self.app.call_from_thread(self.pr_failed, f"{repo}#{number}", failure(error))
            return
        self.cache.put(repo, number, raw)
        self.app.call_from_thread(self.pr_loaded, pr, generation)

    def pr_partial(self, pr, generation=0):
        """The conversation, commits and checks of a pull request with nothing on screen yet; its files are on their way."""
        if generation != self.generation:
            return
        if pr.key == self.wanted and (self.pr is None or self.pr.key != pr.key):
            self.open_pr(pr)

    def prefetch(self):
        """Read the pull requests just above and below the cursor in the background, so moving to them is instant."""
        rows = self.query_one("#list", ListRows).rows
        cursor = self.query_one("#list", ListRows).cursor
        for step in (1, -1):
            index = cursor + step
            while 0 <= index < len(rows) and not isinstance(rows[index], core.PrRow):
                index += step
            if not 0 <= index < len(rows):
                continue
            row = rows[index]
            if row.key in self.prs or row.key in self.prefetching:
                continue
            self.prefetching.add(row.key)
            generation = self.generation
            self.run_worker(
                lambda row=row, generation=generation: self.fetch_quietly(row, generation),
                thread=True,
                group=f"prefetch-{row.key}",
            )

    def fetch_quietly(self, row, generation=0):
        try:
            raw = self.forge.fetch_pr(row.repo, row.number)
            pr = self.forge.build_pr(row.repo, row.number, raw)
        except Exception:  # noqa: BLE001 - a prefetch that fails is read again when it is opened
            self.app.call_from_thread(self.prefetch_failed, row.key)
            return
        self.cache.put(row.repo, row.number, raw)
        self.app.call_from_thread(self.prefetched, pr, generation)

    def prefetch_failed(self, key):
        """Forget a read ahead that failed. A method, because Textual reads a callback's signature and a set's own
        discard has none before Python 3.13."""
        self.prefetching.discard(key)

    def prefetched(self, pr, generation=0):
        self.prefetching.discard(pr.key)
        if generation == self.generation:
            self.prs.setdefault(pr.key, pr)

    def pr_loaded(self, pr, generation=None):
        self.busy.pop("pr", None)
        if generation is not None and generation != self.generation:
            return  # read for the scope shown before this one
        self.prs[pr.key] = pr
        recent = self.state.get("recent") or []
        for item in recent:  # name a pull request opened by link once it is read
            if f"{item['repo']}#{item['number']}" == pr.key and (item.get("title"), item.get("author")) != (
                pr.title,
                pr.author,
            ):
                item.update(title=pr.title, author=pr.author)
                self.state.save(recent=recent)
                self.show_list()
        if pr.key == self.wanted or self.pr is not None and self.pr.key == pr.key:
            self.open_pr(pr, keep=self.pr is not None and self.pr.key == pr.key)
            self.refocus()
            if self.prefetch_on:
                self.prefetch()
        self.show_bars()

    def pr_failed(self, key, message):
        self.busy.pop("pr", None)
        if key == self.loading_key:
            self.loading_key = None
        if key == self.wanted:
            self.failed = key  # not read again until the cursor comes back to it or r refreshes
        if key == self.wanted and (self.pr is None or self.pr.key != key or not self.pr.stale):
            self.error = f"{key}: {message}"
            self.pr = None
            self.show_pr()
            self.refocus()
            self.notify(self.error, severity="error", timeout=10)
        self.show_bars()

    def refocus(self):
        """A pane that showed a loading indicator could not keep focus; give it back unless something else took it."""
        focused = self.app.focused
        keep = (
            "filter",
            "cmdline",
            "files",
            "treefilter",
            "search",
            "editor-text",
            "summary-text",
            "confirm",
            "actions",
        )  # on purpose
        if focused is not None and focused.id in keep and focused.display:
            return
        if focused is None or focused.id != self.focus_pane:
            self.query_one(f"#{self.focus_pane}").focus()

    def open_pr(self, pr, keep=False):
        same = keep and self.pr is not None and self.pr.key == pr.key
        if same and self.editing:  # a fresh read while you type: it lands when the editor closes, with your text kept
            self.pending_pr = pr
            return
        self.close_editor()
        self.pr = pr
        self.loading_key = None
        self.error = ""
        try:
            self.drafts = self.store.load(pr.repo, pr.number)
            if self.drafts.prune(pr):  # resolve marks the threads no longer need
                self.store.save(self.drafts)
        except (OSError, core.DraftError, core.UsageError) as error:
            self.drafts = core.Drafts(pr.repo, pr.number, warning=f"drafts cannot be read or kept: {error}")
        if self.drafts.warning:
            self.notify(self.drafts.warning, severity="warning", timeout=15)
        if not same:
            self.file_index, self.overrides = 0, {}
            self.vim_new_pr()
            self.mark_seen(pr.key)
        self.file_index = min(self.file_index, max(0, len(pr.files) - 1))
        self.show_pr(cursor=None if same else 0)
        self.build_tree()
        self.layout_tree()
        self.land_pending()
        self.land_on_drafts()

    def land_on_drafts(self):
        """Opened from the Pending tab: the cursor goes to the first draft, or to the first comment pending on the
        forge, in the Files tab, else in the Conversation tab; once the files are in."""
        pr = self.pr
        if self.to_drafts is None or pr is None or pr.key != self.to_drafts or pr.files_loading:
            return
        self.to_drafts = None

        def waiting(row):
            return bool(row.draft) or any(badge.startswith("pending on ") for badge in row.badges)

        for index in range(len(pr.files)):
            rows = self.shown_file_rows(index)
            at = next((i for i, row in enumerate(rows) if waiting(row)), None)
            if at is not None:
                self.open_file(index)
                self.query_one("#diff", DiffRows).go(at)
                return
        rows = core.conversation_rows(pr, self.drafts, icons=self.icons, now=self.now)
        at = next((i for i, row in enumerate(rows) if waiting(row)), None)
        if at is not None:
            self.set_mode("conversation", cursor=at)

    def action_refresh(self):
        if "lists" in self.busy or time.monotonic() - self.last_refresh < REFRESH_GAP:  # one at a time
            return
        self.last_refresh = time.monotonic()
        self.prs.clear()
        self.failed = None
        self.load_lists()
        if self.pr is not None:
            self.load_pr(self.pr, reason="refreshing")
