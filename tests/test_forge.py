# SPDX-FileCopyrightText: 2026 Cristiano Carvalho
# SPDX-License-Identifier: Apache-2.0
"""The forge seam: only the GitHub package knows GitHub, a forge is chosen by name, a forge that lacks something is
refused with its own name, and GitHub's repositories, folders and files are read through the same interface."""

import json
import re
from importlib.metadata import EntryPoint

from fake_github import NOW, FakeGitHub, drafted, fixture
from morann import core, forge
from morann.github import GitHubProvider
from support import ROOT, make_app, pr_numbers, refused, settle


class Bare(GitHubProvider):
    """A forge with none of the things a forge may lack, under its own name."""

    name = "bare"
    label = "Bare"
    host = "bare.test"
    capabilities = frozenset()


def test_seam():
    """Nothing outside morann.github imports it or names gh: the UI and the logic reach a forge through the
    interface alone."""
    package = ROOT / "src/morann"
    for path in sorted(package.glob("*.py")):
        source = path.read_text()
        assert not re.search(r"^\s*(?:from|import) morann\.github\b", source, flags=re.MULTILINE), path.name
        assert not re.search(r"\bGh\(|\.graphql\(|\bgh\.(?:get|post|send|pages|run)\(", source), path.name
    assert forge.BUILT_IN == {"github": "morann.github:GitHubProvider"}
    for name in (
        "viewer_login organizations list_pull_requests list_scope fetch_pr build_pr head_sha post_review post_reply "
        "resolve_thread post_comment read_state apply_action update_branch behind_by parse_ref pr_url file_url "
        "comment_url note_url commit_url checks_url owns_url read_file reader"
    ).split():
        assert callable(getattr(forge.Forge, name)) and callable(getattr(GitHubProvider, name)), name
    github = GitHubProvider()
    assert (github.name, github.label, github.host, github.page_size) == ("github", "GitHub", "github.com", 50)
    assert github.capabilities == frozenset(forge.Capability) and not github.read_only
    reader = github.reader()
    assert reader.read_only and not github.read_only and reader.gh.program == github.gh.program


def test_the_forge_is_chosen_by_name(tmp_path):
    """MORANN_FORGE, then the config file's forge line, then GitHub."""
    config = tmp_path / "morann/config"
    bare = {"HOME": str(tmp_path), "XDG_CONFIG_HOME": str(tmp_path)}
    assert forge.chosen(bare) == "github"
    assert forge.chosen({**bare, "MORANN_FORGE": " GitLab "}) == "gitlab"
    config.parent.mkdir(parents=True)
    config.write_text("owners = acme\nforge = Gitea\n")
    assert forge.chosen(bare) == "gitea" and forge.chosen({**bare, "MORANN_FORGE": "github"}) == "github"
    assert forge.chosen({**bare, "MORANN_CONFIG": str(tmp_path)}) == "github"  # an unreadable config names none


def test_selection(monkeypatch):
    """An unknown name is refused with the ones there are; another package adds a forge through the morann.forges
    entry point group and cannot replace a built-in one."""
    monkeypatch.setenv("MORANN_CONFIG", "/nonexistent-morann-config")
    monkeypatch.setattr(forge, "entry_points", lambda group: [])
    assert isinstance(forge.select(), GitHubProvider) and not forge.select().read_only
    assert forge.select(read_only=True).read_only and isinstance(core.select("github"), GitHubProvider)
    with refused(core.UsageError, "unknown forge 'gitlab': there is github"):
        forge.select("gitlab")
    with monkeypatch.context() as patch:
        patch.setenv("MORANN_FORGE", "nope")
        with refused(core.UsageError, "unknown forge 'nope'"):
            forge.select()
    registered = [
        EntryPoint("bare", "test_forge:Bare", forge.ENTRY_POINTS),
        EntryPoint("github", "test_forge:Bare", forge.ENTRY_POINTS),
        EntryPoint("broken", "morann_no_such_module:Thing", forge.ENTRY_POINTS),
    ]
    monkeypatch.setattr(forge, "entry_points", lambda group: registered)
    assert forge.providers() == {
        "bare": "test_forge:Bare",
        "broken": "morann_no_such_module:Thing",
        "github": "morann.github:GitHubProvider",
    }
    picked = forge.select("bare", read_only=True)
    assert type(picked).__name__ == "Bare" and picked.read_only and picked.label == "Bare"
    assert type(forge.select("github")).__name__ == "GitHubProvider"  # a package cannot take a built-in name
    with refused(core.UsageError, "the broken forge cannot be loaded"):
        forge.select("broken")


def test_capabilities():
    """A forge without a capability refuses what needs it, by its own name, before anything is sent; GitHub, which has
    them all, is unaffected. Messages name the forge that built the pull request."""
    with FakeGitHub(fixture()) as github:
        bare = Bare()
        mine = bare.read_state("acme/app", 5)
        assert mine.forge is bare and mine.own
        menu = {action: reason for action, _label, _key, reason in core.action_menu(mine)}
        assert menu["update"] == "Bare has no update branch" and menu["rerequest"] == "Bare has no re-request review"
        assert menu["ready"] == menu["draft"] == "Bare has no draft pull requests"
        assert menu["automerge"] == menu["noautomerge"] == "Bare has no auto-merge"
        assert (menu["squash"], menu["merge"], menu["close"]) == ("", "", "")  # every forge merges and closes
        with refused(core.PlanError, "Bare has no auto-merge"):
            core.build_action(mine, "automerge")
        plan = core.build_action(mine, "squash")
        assert plan.forge == "Bare" and plan.lines()[1] == "Bare refuses it if the head moved"
        full = {
            action: reason for action, _l, _k, reason in core.action_menu(GitHubProvider().read_state("acme/app", 5))
        }
        assert not any("has no" in reason for reason in full.values()), full
        assert core.lacks(bare, core.Capability.READ_FILES) == "Bare has no reading files"
        assert core.lacks(GitHubProvider(), core.Capability.READ_FILES) == ""

        pr = bare.build_pr("acme/app", 7, bare.fetch_pr("acme/app", 7))
        assert pr.forge is bare
        store = core.DraftStore(github.dir / "drafts")
        drafts = drafted(store, pr)  # two comments, a reply, two resolve marks and a summary
        with refused(core.PlanError, "Bare has no request changes"):
            core.build_plan(pr, drafts, "REQUEST_CHANGES")
        with refused(core.PlanError, "Bare has no resolving threads: remove the resolve marks (x)"):
            core.build_plan(pr, drafts, "COMMENT")
        drafts.resolves.clear()
        assert core.build_plan(pr, drafts, "APPROVE").event == "APPROVE"  # a comment, an approval and a reply still go
        assert not github.posts()
        own = bare.build_pr("acme/app", 5, bare.fetch_pr("acme/app", 5))
        with refused(core.PlanError, "Bare does not let you approve on your own pull request"):
            core.build_plan(own, core.Drafts("acme/app", 5), "APPROVE")
        assert core.pending_review(bare).startswith("you have a review pending on bare.test; Bare refuses a second one")
        assert core.pending_review(GitHubProvider()).startswith("you have a review pending on github.com; GitHub ")
        big = core.File("big.json", "modified", 5000, 0)
        assert big.why_no_diff("Bare") == "diff too large for Bare's API; open the pull request in the browser (o)"
        rows = core.conversation_rows(pr, core.Drafts("acme/app", 7), now=NOW)
        assert all(row.link.startswith("https://github.com/") for row in rows if row.link)  # its links are its own
        assert core.merge_lines("Bare", "", "", "???")[-1] == ("Bare is checking whether this can merge", "dim")


def files_fixture():
    def blob(oid, size, text, binary=False, truncated=False):
        return {
            "__typename": "Blob",
            "oid": oid,
            "byteSize": size,
            "isBinary": binary,
            "isTruncated": truncated,
            "text": text,
        }

    data = fixture()
    data["objects"] = {
        "acme/app@HEAD:": {"__typename": "Tree", "entries": []},
        "acme/app@HEAD:README.md": blob("abc", 12, "# App\n\nHello\n"),
        "acme/app@feature/x:img/logo.png": blob("def", 900, None, binary=True),
        "acme/app@HEAD:big.json": blob("fed", 9000000, "{", truncated=True),
    }
    return data


def test_read_file():
    """A file at a ref as text, or flagged binary or too large; a path that is not there or not a file is an error."""
    with FakeGitHub(files_fixture()) as github:
        hub = GitHubProvider()
        readme = hub.read_file("acme/app", "README.md")
        assert (readme.text, readme.size, readme.binary, readme.truncated, readme.ref) == (
            "# App\n\nHello\n",
            12,
            False,
            False,
            "",
        )
        assert json.loads(github.calls()[-1]["stdin"])["variables"] == {
            "owner": "acme",
            "name": "app",
            "expression": "HEAD:README.md",
        }
        assert readme.url == "https://github.com/acme/app/blob/HEAD/README.md" and hub.owns_url(readme.url)
        logo = hub.read_file("acme/app", "img/logo.png", "feature/x")
        assert logo.text is None and logo.binary and not logo.truncated
        assert logo.url == "https://github.com/acme/app/blob/feature/x/img/logo.png"
        big = hub.read_file("acme/app", "big.json")
        assert big.text is None and big.truncated and big.size == 9000000  # never half a file as if it were whole
        with refused(core.ForgeError, "src not found in acme/app"):
            hub.read_file("acme/app", "src")
        with refused(core.ForgeError, "the root is not a file"):
            hub.read_file("acme/app", "")
        with refused(core.UsageError, "not an OWNER/REPO"):
            hub.read_file("../x", "a.py")
        assert not github.posts()
        assert hub.reader().read_file("acme/app", "README.md").text  # reads work read-only


async def test_capabilities_in_the_app():
    """In the app, with a forge that lacks them: the scope popup asks for no organizations, the All tab's filter narrows
    without searching, U and the actions say what the forge has not, and the buttons name the forge."""
    with FakeGitHub(fixture()) as github:
        tui = make_app(github, forge=Bare())
        async with tui.run_test(size=(100, 40)) as pilot:
            await settle(pilot)
            main = tui.main
            assert str(main.query_one("#open-gh").label) == "Open in Bare o", main.query_one("#open-gh").label
            await pilot.press("s")
            await settle(pilot)
            assert type(tui.screen).__name__ == "ScopeScreen" and tui.screen.choices == ["mine", "personal"]
            assert not any("user/orgs" in " ".join(call["args"]) for call in github.calls())
            await pilot.press("escape", "4")
            await settle(pilot)
            await pilot.press("slash", *"change 3")
            await pilot.pause(0.6)
            await settle(pilot)
            searched = [
                json.loads(c["stdin"])["variables"]["q"] for c in github.calls() if "all: search(" in c["stdin"]
            ]
            assert searched and not [query for query in searched if '"' in query], searched  # pages, never a search
            listed = pr_numbers(main.query_one("#list"))
            assert listed == [31, 32, 33], listed  # the loaded rows, narrowed
            await pilot.press("escape", "U")
            await settle(pilot)
            assert main.acting is None
            assert any("Bare has no update branch" in str(note.message) for note in tui._notifications)
            await pilot.press("1")  # Mine: acme/app#5 is mine
            await settle(pilot)
            await pilot.press("M")
            await settle(pilot)
            body = str(tui.screen.query_one("#actions-body").content)
            assert "enable auto-merge: Bare has no auto-merge" in body, body
            assert "update branch: Bare has no update branch" in body and " Open in Bare" in body, body
            assert main.acting["plan"].action == "squash"  # merging is still offered
            await pilot.press("escape")
            assert not github.posts()
