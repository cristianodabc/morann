# SPDX-FileCopyrightText: 2026 Cristiano Carvalho
# SPDX-License-Identifier: Apache-2.0
"""The app driven by Textual's pilot against the fake GitHub: a review from the first key to the posted review, the
file tree, the bulk update, the scopes, loading and the cache, links, and the lower pane's tabs and actions."""

import hashlib
import json
from datetime import timedelta

from fake_github import FILES, HEAD, NOW, FakeGitHub, fixture, pr_node, stack_fixture
from morann import core, dialogs
from morann.app import Morann
from morann.github import GitHubProvider
from support import make_app, pr_keys, settle


def saved_drafts(github):
    """The drafts of acme/app#7 as they are on disk."""
    return core.DraftStore(github.dir / "drafts").load("acme/app", 7)


def unsent(github, *pull_requests):
    """Leave one unsent comment on each (repo, number); returns the store they are in."""
    store = core.DraftStore(github.dir / "drafts")
    for repo, number in pull_requests:
        kept = store.load(repo, number)
        kept.add_note("unsent")
        store.save(kept)
    return store


async def test_a_review_from_the_first_key_to_the_posted_review():
    """Comment on a line, delete a draft, write the summary, approve: one review goes out, exactly as confirmed. The
    selection and the maximized diff are remembered; T tries the next theme without changing the one Morann starts
    with."""
    with FakeGitHub(fixture()) as github:
        tui = make_app(github, theme_name="github")  # an alias of github-dark
        async with tui.run_test(size=(80, 40)) as pilot:
            await settle(pilot)
            main = tui.main
            assert "review 2" in main.sub_title and "mine 1" in main.sub_title, main.sub_title
            await pilot.pause()
            scope = main.query_one("#scope")  # at 80 columns the whole name and age stay on screen
            assert str(scope.label).startswith("Mine (") and scope.size.width >= len(str(scope.label)), scope.label
            assert str(main.query_one("#tabs").get_tab("review").label) == "3 To Review [2]"  # each tab names its key
            assert (
                str(main.query_one("#tabs").get_tab("mine").label) == "1 Mine [1]"
                and main.query_one("#tabs").get_tab("all").display
            )
            assert str(main.query_one("#tabs").get_tab("all").label) == "4 All [3]"  # every open pull request of acme
            assert main.pr is not None and main.pr.key == "acme/app#7"  # the first row loads by itself
            assert str(main.query_one("#details").content).startswith("Change 7")  # the details panel under the lists
            assert "#7" in str(main.query_one("#details").border_title), main.query_one("#details").border_title
            await pilot.press("i")
            assert not main.query_one("#details").display
            await pilot.press("i")
            assert main.query_one("#details").display
            assert main.query_one("#top").display and main.query_one("#bottom").display
            assert tui.focused is main.query_one("#list")  # keys go to the list, not the tabs
            await pilot.press("1")
            assert main.tab == "mine" and main.query_one("#tabs").active == "mine"
            await pilot.press("m")  # my pull requests only: #5 is mine
            assert [r.key for r in main.query_one("#list").rows if isinstance(r, core.PrRow)] == ["acme/app#5"]
            await pilot.press("m", "3")
            await settle(pilot)
            assert main.tab == "review" and main.pr.key == "acme/app#7"
            await pilot.press("tab")
            assert main.focus_pane == "diff"
            diff = main.query_one("#diff")
            diff.go(next(i for i, row in enumerate(diff.rows) if row.text == "    done()"))
            await pilot.press("c")  # no review is on: one line asks to start one
            await settle(pilot)
            assert type(tui.screen).__name__ == "ChoiceScreen" and not main.reviewing()
            await pilot.press("r")  # start a review: an editor opens inline, under the line
            await settle(pilot)
            editor = main.query_one("#editor")
            assert editor.display and tui.focused is main.query_one("#editor-text") and diff.gap_start is not None
            assert editor.region.y == diff.region.y + diff.gap_start - diff.scroll_offset.y, (
                editor.region,
                diff.gap_start,
            )
            await pilot.press(*"looks off", "ctrl+s")
            await settle(pilot)
            assert not editor.display and diff.gap is None
            assert [(c["side"], c["line"], c["body"]) for c in saved_drafts(github).comments] == [
                ("RIGHT", 13, "looks off")
            ]
            assert any(
                row.kind == "draft" and row.badges == ("draft",) and row.body == "looks off" for row in diff.rows
            )
            diff.go(next(i for i, row in enumerate(diff.rows) if row.text == "import json"))
            await pilot.press("c", *"scratch", "ctrl+s")
            await settle(pilot)
            await pilot.press("j", "d")  # the draft under the line; one d only arms
            await settle(pilot)
            assert len(saved_drafts(github).comments) == 2
            await pilot.press("d")
            await settle(pilot)
            assert [c["body"] for c in saved_drafts(github).comments] == ["looks off"]
            await pilot.press("a")  # the submit bar replaces the footer and posts nothing by itself
            await settle(pilot)
            bar = main.query_one("#confirm")
            assert bar.display and not main.query_one("#status").display
            assert "1 comments" in str(main.query_one("#confirm-status").content)
            await pilot.press("l")
            await settle(pilot)
            assert "Comment on lib/a.py:13 (new file):" in str(main.query_one("#confirm-lines").content)
            await pilot.press("escape")
            await settle(pilot)
            assert not github.posts() and not bar.display and main.query_one("#status").display
            await pilot.press("g", "g", "n")
            assert diff.current().thread == "T2"  # collapsed under its removed line, above T1
            await pilot.press("n", "n")
            assert diff.current().thread == "T3"  # the outdated thread at the end of the file
            await pilot.press("p")
            assert diff.current().thread == "T1"
            await pilot.press("R")
            await settle(pilot)
            assert editor.display and diff.gap[0] == max(i for i, row in enumerate(diff.rows) if row.thread == "T1")
            await pilot.press(*"thanks", "escape")  # leaving the editor keeps nothing
            await settle(pilot)
            assert not saved_drafts(github).replies and not editor.display
            await pilot.press("m", *"Two things", "ctrl+s")  # the summary is written at the top of the pane
            await settle(pilot)
            assert saved_drafts(github).summary == "Two things" and not main.query_one("#summary").display
            await pilot.press("a", "r")  # in the bar, r switches the verdict
            await settle(pilot)
            assert main.submitting["event"] == "REQUEST_CHANGES" and main.submitting["plan"] is not None
            assert not main.check_action("comment", ()) and not main.check_action(
                "refresh", ()
            )  # the bar holds the keys
            main.drafts.add_comment("lib/a.py", "RIGHT", 2, "added behind the bar")  # drafts change under the bar
            await pilot.press("y")
            await settle(pilot)
            assert not github.posts() and main.submitting is not None  # y refused the stale plan and redrew the bar
            main.drafts.comments.pop()
            main.build_submit()
            await pilot.press("escape")
            await pilot.press("a", "y")
            await settle(pilot)
            reviews = [p for p in github.posts() if p["args"][3:4] == ["repos/acme/app/pulls/7/reviews"]]
            assert len(reviews) == 1 and json.loads(reviews[0]["stdin"])["event"] == "APPROVE"
            assert json.loads(reviews[0]["stdin"])["body"] == "Two things"
            assert json.loads(reviews[0]["stdin"])["comments"] == [
                {"path": "lib/a.py", "line": 13, "side": "RIGHT", "body": "looks off"}
            ]
            assert tui.theme == "github-dark" and not tui.painter.ansi
            after = tui.themes[tui.themes.index("github-dark") + 1 :] + tui.themes[:2]  # T steps on and wraps around
            for name in after:
                await pilot.press("T")
                await settle(pilot)
                assert tui.theme == name and tui.painter.ansi == (name == "terminal") and diff.visual
            await pilot.resize_terminal(70, 18)  # narrow and short: one pane at a time
            await settle(pilot)
            assert main.query_one("#bottom").display != main.query_one("#top").display
            await pilot.press("z")
            await pilot.press("q")
        state = json.loads((github.dir / "state.json").read_text())
        assert state["selected"] == "acme/app#7" and state["maximized"] is True and "theme" not in state
        again = make_app(github, theme_name="nord")  # the selection and the maximized diff come back
        async with again.run_test(size=(80, 40)) as pilot:
            await settle(pilot)
            assert again.main.max_diff and again.main.pr is not None and again.main.pr.key == "acme/app#7"
            assert not again.main.query_one("#top").display and again.focused is again.main.query_one("#diff")
            assert again.theme == "nord"


async def test_read_only_keeps_drafts_and_never_opens_the_submit_bar():
    with FakeGitHub(fixture()) as github:
        core.State(github.dir / "state.json").save(maximized=True)  # start in the diff
        reader = make_app(github, forge=GitHubProvider(read_only=True))
        async with reader.run_test(size=(80, 40)) as pilot:
            await settle(pilot)
            posted = len(github.posts())
            assert "read-only" in reader.main.sub_title
            await pilot.press("j", "c")
            await settle(pilot)
            assert [label for _keys, label, _value in reader.screen.choices] == [
                "Start a review",
                "Cancel",
            ]  # read-only
            await pilot.press("r")
            await settle(pilot)
            await pilot.press(*"hi", "ctrl+s")
            await settle(pilot)
            assert [c["body"] for c in saved_drafts(github).comments] == ["hi"]
            for key in ("a", "r", "s"):
                await pilot.press(key)
                await settle(pilot)
                assert not reader.main.query_one("#confirm").display and len(github.posts()) == posted
            await pilot.press("M")  # the action bar shows every action as unavailable, read-only
            await settle(pilot)
            await pilot.press("s", "y", "y")
            await settle(pilot)
            assert reader.main.acting["plan"] is None and len(github.posts()) == posted


async def test_file_tree():
    """The file tree: e shows or hides it in every width (over the diff when narrow, beside it when wide) and never moves
    focus; f moves focus between the diff and the tree, showing it first if hidden; the choice is remembered; with the
    tree hidden the header names the file, and { } still move through files."""
    with FakeGitHub(fixture()) as github:

        def saved():
            return json.loads((github.dir / "state.json").read_text()).get("tree")

        narrow = make_app(github)
        async with narrow.run_test(size=(80, 40)) as pilot:
            await settle(pilot)
            main = narrow.main
            sidebar, diff = main.query_one("#sidebar"), main.query_one("#diff")
            await pilot.press("tab")
            assert main.mode == "files" and not sidebar.display  # off by default in a narrow pane
            assert "file 1/5 lib/a.py" in str(main.query_one("#prline").content)
            assert "e show/hide  f focus" in str(main.query_one("#tree-toggle").label)
            await pilot.press("right_curly_bracket")
            assert main.file_index == 1 and "file 2/5 img/logo.png" in str(main.query_one("#prline").content)
            await pilot.press("left_curly_bracket", "e")
            assert sidebar.display and sidebar.has_class("overlay") and narrow.focused is diff and saved() is True
            await pilot.press("e")
            assert not sidebar.display and narrow.focused is diff and saved() is False
            await pilot.press("f")  # hidden: f shows it and focuses it
            tree = main.query_one("#files")
            assert sidebar.display and narrow.focused is tree and tree.cursor_node.data == 0
            await pilot.press("f")
            assert narrow.focused is diff and sidebar.display
            await pilot.press("f", "j", "enter")  # lib/new_name.py; picking a file in a narrow pane uncovers the diff
            await settle(pilot)
            assert main.file_index == 2 and not sidebar.display and narrow.focused is diff
            await pilot.click("#tree-toggle")
            assert sidebar.display and narrow.focused is diff
            await pilot.press("e")
        wide = make_app(github)
        async with wide.run_test(size=(120, 40)) as pilot:
            await settle(pilot)
            main = wide.main
            sidebar, diff = main.query_one("#sidebar"), main.query_one("#diff")
            await pilot.press("tab", "4")
            assert not sidebar.display and diff.display  # remembered off; the diff takes the width
            await pilot.press("e")
            assert sidebar.display and not sidebar.has_class("overlay") and wide.focused is diff and saved() is True
            assert "Files tree on" in str(main.query_one("#tree-toggle").label)
            await pilot.press("V")  # the open file, viewed
            state = json.loads((github.dir / "state.json").read_text())
            assert (
                state["viewed"]["acme/app#7"][main.pr.files[main.file_index].path] == main.pr.files[main.file_index].sha
            )
            await pilot.press("f", "slash", *"odd")  # focus the tree, then filter it
            await settle(pilot)

            def leaves(node):
                return [
                    index
                    for child in node.children
                    for index in ([child.data] if child.data is not None else []) + leaves(child)
                ]

            assert leaves(main.query_one("#files").root) == [4]
            await pilot.press("enter", "enter")
            await settle(pilot)
            assert main.pr.files[main.file_index].path == "docs/odd.md" and sidebar.display and wide.focused is diff
            await pilot.press("f", "F")
            assert sidebar.styles.width.value == 100 and not diff.display
            await pilot.press("F", "escape")
            assert diff.display and wide.focused is diff
            await pilot.press("1")
            assert main.mode == "conversation" and not sidebar.display
            assert not main.check_action("tree_focus", ())  # f and e are for the Files tab


async def test_bulk_update():
    """U lists your pull requests behind their base, all chosen; a number leaves one out; y updates the rest in order."""
    with FakeGitHub(stack_fixture()) as github:
        tui = make_app(github)
        async with tui.run_test(size=(80, 40)) as pilot:
            await settle(pilot)
            main = tui.main
            await pilot.press("U")
            await settle(pilot)
            assert main.acting["bulk"] and [i.number for i in main.acting["items"]] == [20, 21, 23]
            assert "skip acme/app#22" in str(tui.screen.query_one("#actions-body").content)
            await pilot.press("3", "y")
            await settle(pilot)
            puts = [p["args"][3] for p in github.posts() if p["args"][2] == "PUT"]
            assert puts == ["repos/acme/app/pulls/20/update-branch", "repos/acme/app/pulls/21/update-branch"], puts
            assert main.acting["results"] == {"acme/app#20": "updated", "acme/app#21": "updated"}


async def test_scopes():
    """s opens the scope popup; an organization lists every open pull request there, grouped, with authors; Personal is
    only watched: no drafts, no actions, but Open in GitHub works; g ungroups; r refreshes once."""
    opened = []
    with FakeGitHub(fixture()) as github:
        tui = make_app(github, opener=opened.append)
        clock = [NOW]  # pinned: the refresh age is read from it
        tui.main.clock = lambda: clock[0]
        async with tui.run_test(size=(100, 40)) as pilot:
            await settle(pilot)
            main = tui.main
            assert str(main.query_one("#scope").label) == "Mine (0s)" and main.query_one("#tabs").display
            for passed, shown in (
                (45, "Mine (45s)"),
                (60, "Mine (1m)"),
                (3 * 60 + 59, "Mine (3m)"),
                (2 * 3600 + 1800, "Mine (2h)"),
            ):
                clock[0] = NOW + timedelta(seconds=passed)
                main.tick()  # the age keeps counting while nothing loads
                assert str(main.query_one("#scope").label) == shown, (passed, main.query_one("#scope").label)
            clock[0] = NOW
            searches = len([c for c in github.calls() if "search(" in c["stdin"]])
            await pilot.press("r", "r")  # the second one, right after, is ignored
            await settle(pilot)
            assert (
                len([c for c in github.calls() if "search(" in c["stdin"]]) == searches + 2
            )  # the lists, then the All page
            assert "refreshed" not in str(main.query_one("#topinfo").content)  # the age moved next to the scope name
            assert str(main.query_one("#scope").label) == "Mine (0s)"
            await pilot.press("s")
            await settle(pilot)
            assert isinstance(tui.screen, dialogs.ScopeScreen)
            await pilot.press(*"acm", "enter")
            await settle(pilot)
            assert main.scope_kind == "org:acme" and str(main.query_one("#scope").label) == "acme (0s)"
            assert main.query_one("#tabs").display and str(main.query_one("#tabs").get_tab("all").label) == "4 All [3]"
            assert main.tab == "review" and [
                r.key for r in main.query_one("#list").rows if isinstance(r, core.PrRow)
            ] == ["acme/app#7", "acme/lib#9"]
            await pilot.press("4")  # All: every open pull request in the organization
            rows = main.query_one("#list").rows
            assert [type(r).__name__ for r in rows][:2] == ["Info", "GroupRow"]
            assert sorted(r.number for r in rows if isinstance(r, core.PrRow)) == [31, 32, 33]
            await pilot.press("a", "a", "a")  # all -> me -> others -> bots
            assert main.authors == "bots" and [
                r.number for r in main.query_one("#list").rows if isinstance(r, core.PrRow)
            ] == [33]
            await pilot.press("a")
            await pilot.press("g")  # no groups: the repository is back on each row
            assert not any(isinstance(r, core.GroupRow) for r in main.query_one("#list").rows)
            await pilot.press("g")
            listing = main.query_one("#list")
            listing.go(
                next(i for i, r in enumerate(listing.rows) if isinstance(r, core.GroupRow) and r.repo == "acme/lib")
            )
            await pilot.press("h")  # fold that repository
            assert "acme/lib" in main.collapsed and not any(
                getattr(r, "repo", "") == "acme/lib" and isinstance(r, core.PrRow) for r in listing.rows
            )
            await pilot.press("s")
            await settle(pilot)
            await pilot.press(*"pers", "enter")
            await settle(pilot)
            assert main.scope_kind == "personal" and sorted(
                r.number for r in main.query_one("#list").rows if isinstance(r, core.PrRow)
            ) == [41, 42]
            assert main.pr is None or main.pr.repo == "me/notes"  # nothing of the organization stays on screen
            assert all(r.repo == "me/notes" for r in main.query_one("#list").rows if isinstance(r, core.PrRow))
            await settle(pilot)
            await pilot.press("o")
            assert opened[-1].startswith("https://github.com/me/notes/pull/4")
            await pilot.press("M", "U")
            await settle(pilot)
            assert main.acting is None  # no action bar, no bulk update in a personal repository
            await pilot.press("tab", "c")
            await settle(pilot)
            assert not main.query_one("#editor").display and main.editing is None
            assert not github.posts()
        assert json.loads((github.dir / "state.json").read_text())["scope"] == "personal"


async def test_a_scope_switch_asks_first_when_drafts_are_unsent():
    """Unsent drafts: ask before the view changes; n stays, y switches."""
    with FakeGitHub(fixture()) as github:
        store = unsent(github, ("acme/app", 7))
        tui = make_app(github)
        async with tui.run_test(size=(70, 30)) as pilot:
            await settle(pilot)
            main = tui.main
            hints = main.query_one("#status")
            assert hints.display and 0 < hints.content.cell_len <= 70  # the hint bar fits one line at 70 columns
            await pilot.press("s")
            await settle(pilot)
            await pilot.press(*"acm", "enter")
            await settle(pilot)
            assert type(tui.screen).__name__ == "ConfirmScreen" and main.scope_kind == "mine"
            assert "stay saved with them" in str(tui.screen.query_one("#ask-what").content)
            await pilot.press("n")
            assert main.scope_kind == "mine" and main.pr is not None
            await pilot.press("s")
            await settle(pilot)
            await pilot.press(*"acm", "enter")
            await settle(pilot)
            await pilot.press("y")
            assert (
                main.scope_kind == "org:acme" and main.generation == 1
            )  # switched; reads of the old scope are dropped
            await settle(pilot)
            shown = pr_keys(main.query_one("#list"))
            assert shown == [r.key for r in main.lists.review] and (main.pr is None or main.pr.key in shown)
            assert store.load("acme/app", 7).notes  # the draft stays saved with its pull request


async def test_loading_and_the_cache():
    """Skeleton rows while the list loads; a cached pull request shows at once, marked stale; moving fast through the
    list reads only the row you stop on; the rows next to it are read ahead."""
    data = fixture()
    data["prs"]["acme/lib#9"] = {"node": pr_node(author="kim"), "heads": [HEAD], "files": FILES[:1]}
    with FakeGitHub(data) as github:
        waiting = make_app(github)
        waiting.main.load_lists = lambda: None  # the list never arrives: what it shows meanwhile
        async with waiting.run_test(size=(80, 30)) as pilot:
            await pilot.pause()
            rows = waiting.main.query_one("#list").rows
            assert rows[0].text.startswith("loading pull requests") and all(
                set(r.text) == {"\u2591"} for r in rows[1:5]
            )
            assert str(waiting.main.query_one("#scope").label) == "Mine"  # nothing refreshed yet: no age after the name
        first = make_app(github)
        async with first.run_test(size=(80, 30)) as pilot:
            await settle(pilot)
            assert first.main.pr.key == "acme/app#7" and not first.main.pr.stale
            assert "acme/lib#9" in first.main.prs  # the next row, read ahead
            assert (github.dir / "home/prs/acme/lib/9.json").exists()
        again = make_app(github)
        again.main.load_pr = lambda row, reason="loading": None  # only the cache answers
        async with again.run_test(size=(80, 30)) as pilot:
            await settle(pilot)
            assert (
                again.main.pr.key == "acme/app#7"
                and again.main.pr.stale
                and "cached, refreshing" in again.main.pr_line()
            )
        quick = make_app(github)
        quick.main.prefetch_on = False
        async with quick.run_test(size=(80, 30)) as pilot:
            await settle(pilot)
            before = len([c for c in github.calls() if '"number": 9' in c["stdin"]])
            await pilot.press(
                "j", "j", "k", "j"
            )  # past the acme/lib header and back, faster than the pause before a read
            await settle(pilot)
            assert quick.main.pr.key == "acme/lib#9"
            assert len([c for c in github.calls() if '"number": 9' in c["stdin"]]) == before + 1


async def test_a_failed_read_ahead_is_forgotten():
    """acme/lib#9 is listed next to the open pull request but cannot be read: the read ahead fails quietly, and it is
    read again when it is opened."""
    with FakeGitHub(fixture()) as github:
        tui = make_app(github)
        async with tui.run_test(size=(80, 30)) as pilot:
            await settle(pilot)
            main = tui.main
            assert main.pr.key == "acme/app#7" and "acme/lib#9" not in main.prs and not main.prefetching
            assert any("pulls/9" in " ".join(call["args"]) or '"number": 9' in call["stdin"] for call in github.calls())


async def test_a_failed_list_says_how_to_retry():
    with FakeGitHub(fixture(down=True)):
        broken = Morann(
            core.Scope(owners=("acme",)),
            store=core.DraftStore("/nonexistent-morann-drafts"),
            now=NOW,
            state=core.State("/nonexistent-morann-state.json"),
            opener=print,
        )
        async with broken.run_test(size=(80, 30)) as pilot:
            await settle(pilot)
            assert broken.main.query_one("#list").rows[0].text.endswith("r retries")


async def test_the_unsent_count_never_waits_for_the_forge():
    """Drafts are local files: they are counted when the list fails and before it arrives."""
    with FakeGitHub(fixture(down=True)) as github:
        unsent(github, ("acme/app", 7), ("acme/lib", 9))
        offline = make_app(github)
        async with offline.run_test(size=(100, 30)) as pilot:
            await settle(pilot)
            assert offline.main.lists is None and offline.main.error  # the list failed
            assert "unsent 2" in offline.main.sub_title, offline.main.sub_title
            assert "unsent 2" in str(offline.main.query_one("#topinfo").content)
    with FakeGitHub(fixture()) as github:
        unsent(github, ("acme/app", 7))
        slow = make_app(github)
        slow.main.load_lists = lambda: None  # the list has not arrived yet
        async with slow.run_test(size=(100, 30)) as pilot:
            await pilot.pause()
            assert "unsent 1" in slow.main.sub_title, slow.main.sub_title


async def test_links():
    """o opens the pull request from the list and what is under the cursor in the diff, : goes to any pull request, and
    mor with a link opens straight into it. The opener is a stand-in here."""
    opened = []
    with FakeGitHub(fixture()) as github:
        tui = make_app(github, opener=opened.append)
        async with tui.run_test(size=(80, 40)) as pilot:
            await settle(pilot)
            main = tui.main
            await pilot.press("o")
            assert opened == ["https://github.com/acme/app/pull/7"], opened
            await pilot.press("tab")
            diff = main.query_one("#diff")
            diff.go(next(i for i, row in enumerate(diff.rows) if row.text == "import re"))
            await pilot.press("o")
            anchor = "diff-" + hashlib.sha256(b"lib/a.py").hexdigest()
            assert opened[-1] == f"https://github.com/acme/app/pull/7/files#{anchor}R3"
            diff.go(next(i for i, row in enumerate(diff.rows) if row.kind == "comment" and row.thread == "T1"))
            await pilot.press("o")
            assert opened[-1] == "https://github.com/acme/app/pull/7#discussion_r101"
            await pilot.click("#open-gh")
            assert opened[-1] == "https://github.com/acme/app/pull/7#discussion_r101"
            await pilot.press("colon", *"acme/app#5", "enter")
            await settle(pilot)
            rows = main.query_one("#list").rows
            assert main.pr.key == "acme/app#5" and rows[0].text == "recent" and rows[1].key == "acme/app#5"
            await pilot.press("colon", *"http://evil.test/acme/app/pull/1", "enter")  # refused, nothing opens
            await settle(pilot)
            assert main.pr.key == "acme/app#5" and main.query_one("#cmdbar").display and len(opened) == 4
            await pilot.press("escape")
        assert json.loads((github.dir / "state.json").read_text())["recent"][0]["title"] == "My change"
        straight = make_app(github, opening=("acme/app", 7))  # mor https://github.com/acme/app/pull/7
        async with straight.run_test(size=(80, 40)) as pilot:
            await settle(pilot)
            assert straight.main.pr.key == "acme/app#7" and straight.focused is straight.main.query_one("#diff"), (
                straight.main.pr and straight.main.pr.key,
                straight.focused,
                straight.main.focus_pane,
            )
            assert pr_keys(straight.main.query_one("#list"))[:2] == ["acme/app#7", "acme/app#5"]


async def test_tabs_and_actions():
    """The lower pane's tabs, a comment on the conversation, and the actions popup: disabled on someone else's pull
    request, two y presses to squash your own."""
    with FakeGitHub(fixture()) as github:
        tui = make_app(github)
        async with tui.run_test(size=(80, 40)) as pilot:
            await settle(pilot)
            main = tui.main
            diff, ptabs = main.query_one("#diff"), main.query_one("#ptabs")
            await pilot.press("tab")
            assert (
                main.mode == "files" and str(ptabs.get_tab("checks").label) == "3 Checks [1]"
            )  # short under 90 columns
            assert (
                str(ptabs.get_tab("conversation").label) == "1 Talk [2]"
                and str(ptabs.get_tab("files").label) == "4 Files [5]"
            )
            await pilot.press("1")
            assert main.mode == "conversation" and ptabs.active == "conversation"
            await pilot.press("g", "t")
            assert main.mode == "commits" and [row.number for row in diff.rows if row.kind == "commit"] == [
                "ccccccc",
                "ddddddd",
            ]
            await pilot.press("g", "t")
            assert main.mode == "checks" and next(row.badges for row in diff.rows if row.kind == "check") == (
                "\u00d7",
                "required",
            )
            await pilot.press("g", "T", "4", "right_curly_bracket")
            assert main.mode == "files" and main.file_index == 1
            await pilot.press("1", "c", "r")  # a comment on the conversation, written inline at its end
            await settle(pilot)
            assert main.query_one("#editor").display and diff.gap[0] == len(diff.rows) - 1
            await pilot.press(*"ship it", "ctrl+s")
            await settle(pilot)
            assert [n["body"] for n in core.DraftStore(github.dir / "drafts").load("acme/app", 7).notes] == ["ship it"]
            assert main.submitting and main.submitting["event"] == "COMMENT"  # kept, and the bar asks for y
            assert "Comment on the conversation:" in main.submitting["plan"].lines()
            await pilot.press("n")
            await settle(pilot)
            assert not github.posts() and main.submitting is None
            await pilot.press("M")  # someone else's pull request: every action unavailable, with the reason
            await settle(pilot)
            assert main.acting and isinstance(tui.screen, dialogs.ActionScreen)
            assert "only on your own pull requests" in str(tui.screen.query_one("#actions-body").content)
            await pilot.press("s", "y", "y")
            await settle(pilot)
            assert main.acting["plan"] is None and not github.posts()
            await pilot.press("escape")
            await settle(pilot)
            assert main.acting is None and tui.screen is main
            await pilot.press("tab", "1")  # Mine: acme/app#5 is mine
            await settle(pilot)
            assert main.pr.key == "acme/app#5"
            await pilot.press("M")
            await settle(pilot)
            assert main.acting["plan"].action == "squash"  # the repository's merge method, chosen already
            await pilot.press("m")
            assert main.acting["plan"].action == "merge"  # another key picks another one before the first y
            await pilot.press("s")
            assert main.acting["plan"].action == "squash"
            await pilot.press("y")  # one y arms a merge, it sends nothing
            await settle(pilot)
            assert main.acting["armed"] and not github.posts()
            await pilot.press("y")
            await settle(pilot)
            merges = [p for p in github.posts() if p["args"][2:4] == ["PUT", "repos/acme/app/pulls/5/merge"]]
            assert len(merges) == 1 and json.loads(merges[0]["stdin"]) == {"merge_method": "squash", "sha": HEAD}
            assert main.acting is None
            assert "re-request review: M R" in main.pr_line()  # bob reviewed an older head of my pull request
            await pilot.press("M")
            await settle(pilot)
            await pilot.press("R")
            assert main.acting["plan"].reviewers == ("bob", "ann")  # requested changes or commented, not kim's approval
            await pilot.press("3", "1")  # toggle kim in, bob out
            assert main.acting["plan"].reviewers == ("ann", "kim")
            await pilot.press("y")
            await settle(pilot)
            asks = [p for p in github.posts() if p["args"][3:4] == ["repos/acme/app/pulls/5/requested_reviewers"]]
            assert len(asks) == 1 and json.loads(asks[0]["stdin"]) == {
                "reviewers": ["ann", "kim"],
                "team_reviewers": [],
            }
