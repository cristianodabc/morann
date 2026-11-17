# SPDX-FileCopyrightText: 2026 Cristiano Carvalho
# SPDX-License-Identifier: Apache-2.0
"""Links in descriptions and comments: bare URLs and #123 made into links, real terminal hyperlinks where the terminal
has them and `text (url)` where it does not, and gx and gy on the row under the cursor."""

from fake_github import FakeGitHub, fixture
from morann import markdown, paint
from support import make_app, settle


def url_for(repo, number):
    return f"https://github.com/{repo}/pull/{number}"


def test_linkify():
    linked = markdown.linkify("see https://example.com/a?b=1. and #12, acme/lib#3", "acme/app", url_for)
    assert linked == (
        "see <https://example.com/a?b=1>. and [#12](https://github.com/acme/app/pull/12), "
        "[acme/lib#3](https://github.com/acme/lib/pull/3)"
    )
    kept = "`#12 https://x.dev` [docs](https://d.dev/#3) <https://a.dev> &#123; # 12 a#12"
    assert markdown.linkify(kept, "acme/app", url_for) == kept  # code, links, entities and headings stay
    fenced = "```\n#12 https://x.dev\n```\nafter #4"
    assert markdown.linkify(fenced, "acme/app", url_for).endswith("after [#4](https://github.com/acme/app/pull/4)")
    assert "https://x.dev" not in markdown.linkify(fenced, "acme/app", url_for).split("```")[-1]


def test_links_in_a_body():
    body = (
        "[docs](https://d.dev) and <https://a.dev>, `[no](https://code.dev)`, [mail](mailto:x@y) [docs](https://d.dev)"
    )
    assert markdown.links(body) == [("docs", "https://d.dev"), ("https://a.dev", "https://a.dev")]
    assert markdown.links("") == []


def test_hyperlink_terminals():
    assert markdown.hyperlinks({"TERM": "xterm-kitty"}) and markdown.hyperlinks({"TERM_PROGRAM": "WezTerm"})
    assert markdown.hyperlinks({"TERM": "alacritty"}) and markdown.hyperlinks({"VTE_VERSION": "7600"})
    assert not markdown.hyperlinks({"TERM": "xterm-256color"}) and not markdown.hyperlinks({"VTE_VERSION": "4000"})
    assert not markdown.hyperlinks({"TERM": "xterm-kitty", "TMUX": "/tmp/t"})  # tmux needs its own setting
    assert markdown.hyperlinks({"TERM": "dumb", "MORANN_HYPERLINKS": "1"})
    assert not markdown.hyperlinks({"TERM": "xterm-kitty", "MORANN_HYPERLINKS": "off"})


def text_of(lines):
    return "\n".join("".join(segment.text for segment in line) for line in lines)


def test_a_link_is_its_text_never_its_raw_form():
    body = "Read [the guide](https://d.dev/guide) and [local](file:///etc/passwd).\n\n> quoted\n\n- *one*\n- `two`"
    prepared = markdown.prepare(body, "acme/app", url_for)
    linked = paint.markdown_lines(prepared, 80, True, None, True)
    shown = text_of(linked)
    assert "the guide" in shown and "https://d.dev/guide" not in shown and "quoted" in shown and "• one" in shown
    styles = {segment.text: segment.style for line in linked for segment in line}
    assert styles["the guide"].link == "https://d.dev/guide" and styles["the guide"].underline
    assert "local" in shown and "file:" not in shown and "[local]" not in shown  # a refused link: its text only
    plain = paint.markdown_lines(prepared, 80, True, None, False)  # no hyperlinks: the text alone, still underlined
    assert "Read the guide and local." in text_of(plain) and "https://" not in text_of(plain)
    assert not any(segment.style and segment.style.link for line in plain for segment in line)


async def test_gx_opens_and_gy_copies_a_link_of_the_comment():
    data = fixture()
    data["prs"]["acme/app#7"]["node"]["body"] = "See [the plan](https://plans.example/7) and #5."
    with FakeGitHub(data) as github:
        opened = []
        tui = make_app(github, opener=opened.append, hyperlinks=True)
        async with tui.run_test(size=(100, 40)) as pilot:
            await settle(pilot)
            main = tui.main
            await pilot.press("tab", "1")
            await settle(pilot)
            diff = main.query_one("#diff")
            diff.go(next(i for i, row in enumerate(diff.rows) if "plans.example" in row.body))
            await pilot.pause()
            assert "gx link" in " ".join(main.query_one("#status").content.plain.split())
            await pilot.press("g", "x")
            await settle(pilot)
            picker = tui.screen
            assert picker.shown == [
                "https://plans.example/7",
                "https://github.com/acme/app/pull/5",
                "https://github.com/acme/app/pull/7",
            ]
            await pilot.press("enter")
            await settle(pilot)
            assert opened == ["https://plans.example/7"] and tui.screen is main
            await pilot.press("g", "y", *"pull/5", "enter")
            await settle(pilot)
            assert tui.clipboard == "https://github.com/acme/app/pull/5"
            diff.go(next(i for i, row in enumerate(diff.rows) if row.kind == "event"))  # a commit: its one link
            await pilot.pause()
            await pilot.press("g", "y")
            assert tui.clipboard.startswith("https://github.com/acme/app/pull/7/commits/")
            await pilot.press("colon", *"link", "enter")
            await settle(pilot)
            assert isinstance(tui.screen, type(picker))
            await pilot.press("escape")
            await pilot.press("4", "g", "g")  # g waits for its second key in the diff; gg is the top
            assert diff.cursor == diff.selectable_rows()[0]
