# SPDX-FileCopyrightText: 2026 Cristiano Carvalho
# SPDX-License-Identifier: Apache-2.0
"""Every key Morann has, grouped by task, in one table: the help overlay draws it, the statusline picks from it for the
focused pane, and the README's key list follows it. Standard library only.

A key's `where` names the places it works: list, the lower pane's tabs (conversation, commits, checks, files), tree,
review (the review bar), actions (the actions dialog), editor, and "" for everywhere."""

from __future__ import annotations

from dataclasses import dataclass

from morann.commands import COMMANDS

PANE = ("conversation", "commits", "checks", "files")  # the lower pane's tabs
BOTH = ("list", *PANE)


@dataclass(frozen=True)
class Key:
    keys: str  # as the user types them: "j k", "ctrl+o", "d d"
    text: str  # what they do; {forge} is the forge's name
    hint: str = ""  # the statusline's short label; "" keeps it out of it
    where: tuple[str, ...] = ()  # where it works; () is everywhere
    action: str = ""  # the screen action the statusline asks about, so it shows only where it applies
    params: tuple[str, ...] = ()


@dataclass(frozen=True)
class Section:
    title: str
    keys: tuple[Key, ...]
    first: tuple[str, ...] = ()  # where this section opens the help, before the others


SECTIONS = (
    Section(
        "Move",
        (
            Key("j k", "move down, up (also the arrow keys)", "move", BOTH + ("tree",)),
            Key("ctrl+d ctrl+u", "half a page down, up", "", BOTH + ("tree",)),
            Key("ctrl+f ctrl+b", "a whole page down, up", "", BOTH + ("tree",)),
            Key("gg G", "the top, the bottom; 5G or 5gg is the fifth row", "", BOTH + ("tree",)),
            Key("H L", "the top, the bottom of the view; 3H is its third row", "", BOTH + ("tree",)),
            Key("zt zz zb", "scroll so the cursor row is at the top, middle, bottom", "", BOTH + ("tree",)),
            Key("5j", "a count repeats a motion; it starts at 5, since 1 to 4 switch tabs"),
            Key("tab", "the other pane: the list, or the pull request below it", "pane", BOTH),
            Key("ctrl+w j k", "the pull request pane, the list (ctrl+w w: the other one)"),
            Key("ctrl+w h l", "the file tree, the diff (ctrl+h and ctrl+l also work)", "", ("files", "tree")),
            Key("z", "maximize the pull request pane, or bring the list back"),
            Key("+ -", "grow, shrink the pull request pane"),
            Key("esc", "drop a count or a search, dismiss the notes"),
        ),
    ),
    Section(
        "Find and jump",
        (
            Key(":", "the command line: open a pull request, switch scope or tab, help, quit (:help commands)", "cmd"),
            Key("ctrl+p", "jump to any pull request on hand by a few letters of it (fuzzy)", "jump"),
            Key("ctrl+o", "back to where you were, across panes and pull requests"),
            Key("ctrl+i O", "forward again (most terminals send tab for ctrl+i, so O does it too)"),
            Key("/", "in the list: filter it (esc clears)", "filter", ("list",)),
            Key("/", "search the pane: enter keeps the search, esc cancels", "search", PANE),
            Key("n N", "the next, previous match; in the list, the next row the filter kept", "", BOTH),
        ),
    ),
    Section(
        "Lists",
        (
            Key("1 2 3 4", "Mine, Pending (your reviews in progress), To Review (waiting on you), All", "", ("list",)),
            Key("gt gT", "the next, previous tab of the focused pane", "", BOTH),
            Key("enter", "open the pull request below", "open", ("list",), "open_diff"),
            Key("o", "open it in {forge}", "", ("list",)),
            Key("s", "scope: Mine, Personal (read only), or one organization", "scope", ("list",)),
            Key("m", "my pull requests only, in any tab", "", ("list",)),
            Key("a", "authors in an organization or Personal: all, me, others, bots", "", ("list",)),
            Key("g", "group by repository or not; h l (or enter) fold and unfold one", "", ("list",)),
            Key("! b d", "failing, behind or draft pull requests only; the same key again shows all", "", ("list",)),
            Key("i", "show or hide the details panel", "", ("list",)),
            Key("r", "refresh the lists (ctrl+r: the pull request too)", "", ("list",)),
            Key("U", "update your pull requests that are behind their base", "", ("list",)),
        ),
        ("list",),
    ),
    Section(
        "Read a pull request",
        (
            Key("1 2 3 4", "Conversation, Commits, Checks, Files", "tabs", PANE),
            Key("[ ]", "the previous, next tab; a quick letter after them makes a motion instead (below)", "", PANE),
            Key("]c [c", "the next, previous change: a run of added or removed lines", "change", ("files",)),
            Key("]h [h", "the next, previous hunk", "", ("files",)),
            Key("]f [f  { }", "the next, previous file", "file", ("files",)),
            Key("]t [t", "the next, previous review thread, into the next file", "", PANE),
            Key("]u [u", "the next, previous unresolved thread, into the next file", "unresolved", PANE),
            Key("]m [m", "the next, previous comment", "", PANE),
            Key("]d [d", "the next, previous draft of yours", "", PANE),
            Key("n p", "the next, previous review thread (n is the next match while a search is on)", "thread", PANE),
            Key("u", "unresolved threads only, or all", "", PANE),
            Key("enter", "fold or unfold the thread", "fold", ("files",), "fold"),
            Key("enter", "open the thread in the Files tab, at its line", "in files", ("conversation",), "open_thread"),
            Key("enter", "open the check in {forge}", "open", ("checks",), "open_check"),
            Key(
                "enter",
                "on a row of folded unchanged lines: show them (:expand shows them all)",
                "show",
                ("files",),
                "expand",
            ),
            Key("o", "open the line, thread, commit or check under the cursor in {forge}", "", PANE),
            Key(
                "gx", "open a link of the comment under the cursor; its address shows first", "link", PANE, "open_link"
            ),
            Key("gy", "copy the address of a link of the row under the cursor", "", PANE),
            Key("V", "mark the file viewed, until it changes", "", ("files", "tree")),
            Key("|", "the diff side by side, old beside new, or in one column (it needs 120 columns)", "", ("files",)),
        ),
        PANE,
    ),
    Section(
        "Write a review",
        (
            Key(
                "c",
                "comment on the line (on a draft: edit it), on the Conversation tab at its end; with no review on, "
                "send it on its own (s) or start a review (r)",
                "comment",
                PANE,
                "comment",
            ),
            Key(
                "C",
                "comment on the conversation, from anywhere; with no review on, now (s) or in a review (r)",
                "",
                BOTH,
            ),
            Key(
                "R",
                "reply to the thread; with no review on, reply now (s) or add it to a review (r)",
                "reply",
                PANE,
                "reply",
            ),
            Key(
                "x",
                "resolve or unresolve the thread with the review; with none on, now (s) or in a review (r)",
                "resolve",
                PANE,
                "resolve",
            ),
            Key(
                "e",
                "edit the draft, or your own posted comment, summary or description, under the cursor (on the "
                "Files tab elsewhere e shows or hides the file tree)",
                "edit",
                PANE,
                "edit",
            ),
            Key(
                "d d",
                "delete the draft; on your own posted comment, delete it after a confirmation",
                "delete",
                PANE,
                "delete",
            ),
            Key("m", "write the review summary", "", PANE),
            Key(
                "v",
                "start a review (opening a pull request never does); once on, show what it would post",
                "review",
                BOTH,
                "submit",
                ("COMMENT",),
            ),
            Key("a r", "approve, request changes (never on your own pull request)", "", PANE),
            Key("ctrl+s", "keep the text as a draft", "keep", ("editor",)),
            Key("esc", "cancel the text", "cancel", ("editor",)),
        ),
        ("editor",),
    ),
    Section(
        "Review bar",
        (
            Key("c a r", "Comment, Approve, Request changes (needs a summary)", "", ("review",)),
            Key("m", "write the summary: ctrl+s keeps it, esc goes back", "", ("review",)),
            Key("l", "list every comment, reply and resolve it would post", "", ("review",)),
            Key("y", "post all of it as one review", "", ("review",)),
            Key("n esc", "back, posting nothing", "", ("review",)),
            Key(
                "D",
                "discard the review and its drafts, after a y; nothing is posted (:review discard)",
                "",
                ("review",),
            ),
        ),
        ("review",),
    ),
    Section(
        "Act on a pull request",
        (
            Key(
                "M",
                "the actions: merge, update, close, ready, auto-merge, re-request review",
                "actions",
                BOTH,
                "actions",
            ),
            Key("s m b", "squash and merge, merge commit, rebase and merge", "", ("actions",)),
            Key("u w", "update the branch; ready for review or back to draft", "", ("actions",)),
            Key("c o", "close, reopen", "", ("actions",)),
            Key("A R", "auto-merge on or off; re-request review (1 to 9 choose who)", "", ("actions",)),
            Key("g", "open it in {forge}", "", ("actions",)),
            Key("y", "send it; merge and close need y twice", "", ("actions",)),
        ),
        ("actions",),
    ),
    Section(
        "File tree",
        (
            Key(
                "f",
                "focus the file tree (it shows if hidden); f again: the diff",
                "tree",
                ("files", "tree"),
                "tree_focus",
            ),
            Key("e", "show or hide the file tree; it never takes the focus", "", ("files", "tree")),
            Key("l enter", "open the file", "open", ("tree",)),
            Key("h", "fold the folder, or go up to it", "fold", ("tree",)),
            Key("/", "filter the files", "filter", ("tree",)),
            Key("F", "the tree takes the whole width", "", ("files", "tree")),
            Key("< >", "narrower, wider", "", ("files", "tree")),
            Key("esc", "back to the diff", "diff", ("tree",)),
        ),
        ("tree",),
    ),
    Section(
        "Commands",
        tuple(
            Key(f":{command.name}" + (f" {command.arg.upper()}" if command.arg else ""), command.text)
            for command in COMMANDS
        ),
    ),
    Section(
        "Display",
        (
            Key("T", "try the next color theme; theme = NAME in the config keeps one (:theme NAME picks one)"),
            Key("?", "this help; / filters it", "help"),
            Key("q", "quit (also :q)", "", BOTH),
        ),
    ),
)

HINTS = {  # the statusline's keys per place, most useful first
    "list": ("j k", "enter", "/", "ctrl+p", ":", "s", "v", "M", "tab"),
    "files": ("c", "R", "x", "e", "d d", "enter", "]c [c", "n p", "/", "v", "M", "]u [u", "]f [f  { }", "f"),
    "conversation": ("c", "R", "x", "e", "d d", "enter", "gx", "n p", "/", "v", "M", "tab"),
    "commits": ("j k", "1 2 3 4", "/", "v", "M", "ctrl+p", "tab"),
    "checks": ("enter", "j k", "1 2 3 4", "/", "v", "M", "tab"),
    "tree": ("j k", "l enter", "h", "/", "esc"),
    "editor": ("ctrl+s", "esc"),
}

NOTES = (
    "Every draft shown is part of the review until you delete it. Drafts stay on this machine (in "
    "~/.cache/morann/drafts, or MORANN_HOME/drafts) until posted.",
    "Nothing is posted, merged or changed without y, and nothing at all with --read-only.",
)


def hints(place: str) -> list[Key]:
    """The statusline's keys for a place, in HINTS order: the entry of each key that works there."""
    found = []
    for keys in HINTS.get(place, ()):
        key = next(
            (k for section in SECTIONS for k in section.keys if k.keys == keys and k.hint and works(k, place)), None
        )
        if key is not None:
            found.append(key)
    return found


def works(key: Key, place: str) -> bool:
    return not key.where or place in key.where


def sections_for(place: str) -> list[Section]:
    """The help's sections, the ones about the focused place first."""
    return sorted(SECTIONS, key=lambda section: place not in section.first)


def matching(sections: list[Section], query: str) -> list[Section]:
    """The sections with only the keys whose keys or text contain every word of the query (any case)."""
    words = query.casefold().split()
    if not words:
        return list(sections)
    kept = []
    for section in sections:
        keys = tuple(
            key
            for key in section.keys
            if all(word in f"{key.keys} {key.text} {section.title}".casefold() for word in words)
        )
        if keys:
            kept.append(Section(section.title, keys, section.first))
    return kept
