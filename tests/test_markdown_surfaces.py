# SPDX-FileCopyrightText: 2026 Cristiano Carvalho
# SPDX-License-Identifier: Apache-2.0
"""No raw link reaches the screen: every surface that draws a description or a comment goes through the one markdown
renderer, so [text](url), images, footnotes, HTML links and summaries show as text, while code stays as written. The
bodies are shaped like a review bot's (the inline image, the suggestion fence, the details blocks, the footnote), with
invented names."""

import re

from fake_github import FakeGitHub, comment, fixture
from morann import core, markdown, paint
from support import make_app, settle

RAW = re.compile(r"\]\((?:https?|file):|!\[")  # a link or an image in its markdown form

BOT_REVIEW_COMMENT = """![medium](https://img.example/medium-priority.svg)

Using absolute URLs for files like `.tool-versions` breaks on [other branches](https://docs.example/branches).

```suggestion
[![Elixir](https://badge.example/elixir.svg)](./.tool-versions)
```"""

BOT_SUMMARY = """## Summary of Changes

Hello, I'm Review Bot[^1]! Here is a summary of [the change](https://docs.example/summary).

### Highlights

* **Restructuring**: rewrote the README, see [notes](https://docs.example/notes).

<details>
<summary><b>New Features</b></summary>

**Click [here](https://console.example/agents) to enable Memory.**
</details>

Feature | Command
--- | ---
Review | `/bot review`

[^1]: Review the [use policy](https://policy.example/use), and [use code with caution](https://support.example/caution).
"""

DESCRIPTION = """Fixes #3. See [the plan](https://plans.example/7), <https://auto.example/x>, https://bare.example/y and
[a reference][r].

[r]: https://ref.example/z

**Bold [inner](https://in.example/b)** and > not a quote

> quoted [q](https://q.example/c)

<a href="https://html.example/d">html link</a> [![badge](https://badge.example/b.svg)](https://ci.example/run)

`[code](https://code.example/e)`"""


def bot_fixture():
    data = fixture()
    node = data["prs"]["acme/app#7"]["node"]
    node["body"] = DESCRIPTION
    node["comments"]["nodes"].append(
        {"body": BOT_SUMMARY, "createdAt": "2026-11-04T12:00:00Z", "author": {"login": "review-bot"}}
    )
    node["reviews"]["nodes"][1]["body"] = "Please fix [the docs](https://docs.example/fix)."
    threads = node["reviewThreads"]["nodes"]
    threads[0]["comments"]["nodes"].append(comment(103, "review-bot", BOT_REVIEW_COMMENT, "2026-11-04T13:00:00Z"))
    threads[1]["comments"]["nodes"][0]["body"] = "see [the caller](https://src.example/caller) first"  # resolved
    return data


def shown(tui):
    """Everything the lower pane's rows draw, every row whether on screen or not."""
    main, painter = tui.main, tui.painter
    lines = []
    for row in main.query_one("#diff").rows:
        for strip in painter.diff_row(row, 120, main.number_width):
            strip = strip() if callable(strip) else strip
            lines.append("".join(segment.text for segment in strip))
    return "\n".join(lines)


def test_the_bot_bodies_render_without_raw_links():
    for body in (BOT_REVIEW_COMMENT, BOT_SUMMARY, DESCRIPTION):
        prepared = markdown.prepare(body, "acme/app", lambda repo, n: f"https://github.com/{repo}/pull/{n}")
        for links in (True, False):
            text = "\n".join(
                "".join(segment.text for segment in line)
                for line in paint.markdown_lines(prepared, 100, True, None, links)
            )
            prose = text.replace("[![Elixir](https://badge.example/elixir.svg)](./.tool-versions)", "")
            prose = prose.replace("[code](https://code.example/e)", "")
            assert not RAW.search(prose), (links, text)
            assert "[^1]" not in text
    summary = markdown.prepare(BOT_SUMMARY, "acme/app", lambda repo, n: "")
    assert "**New Features**" in summary and "\\[1\\] Review the" in summary
    review = markdown.prepare(BOT_REVIEW_COMMENT, "acme/app", lambda repo, n: "")
    assert review.startswith("[image: medium](https://img.example/medium-priority.svg)")
    assert (
        "**Suggested change**\n\n```suggestion\n[![Elixir](https://badge.example/elixir.svg)](./.tool-versions)\n```"
        in review
    )
    described = markdown.prepare(DESCRIPTION, "acme/app", lambda repo, n: f"https://github.com/{repo}/pull/{n}")
    assert "[html link](https://html.example/d)" in described and "[image: badge](https://ci.example/run)" in described
    assert "`[code](https://code.example/e)`" in described and "[#3](https://github.com/acme/app/pull/3)" in described


async def test_no_surface_draws_a_raw_link():
    with FakeGitHub(bot_fixture()) as github:
        store = core.DraftStore(github.dir / "drafts")
        drafts = store.load("acme/app", 7)
        drafts.started = True
        drafts.add_comment("lib/a.py", "RIGHT", 3, "draft with [a link](https://draft.example/f)", None)
        drafts.add_note("note with [a link](https://note.example/g)")
        store.save(drafts)
        tui = make_app(github, store=store)
        async with tui.run_test(size=(120, 40)) as pilot:
            await settle(pilot)
            main = tui.main
            for keys, surface in (
                (("tab", "1"), "conversation: description, comments, review summaries, threads, drafts"),
                (("4",), "files: threads under the diff, drafts"),
            ):
                await pilot.press(*keys)
                await settle(pilot)
                text = shown(tui)
                code_free = text.replace("[![Elixir](https://badge.example/elixir.svg)](./.tool-versions)", "")
                code_free = code_free.replace("[code](https://code.example/e)", "")
                assert not RAW.search(code_free), (surface, RAW.search(code_free), text)
                assert "(https://" not in code_free, (surface, text)
            await pilot.press("1")
            await settle(pilot)
            conversation = shown(tui)
            for text in ("the plan", "a reference", "html link", "image: badge", "the docs", "Review the use policy"):
                assert text in conversation, text
            assert "[code](https://code.example/e)" in conversation  # inline code is never a link
            await pilot.press("4")
            await settle(pilot)
            diff = main.query_one("#diff")
            preview = next(
                row for row in diff.rows if row.kind == "thread" and row.thread == "T2"
            )  # folded: its preview
            assert "see the caller first" in preview.body and "https://" not in preview.body
            files = shown(tui)
            assert "image: medium" in files and "other branches" in files and "draft with a link" in files
            await pilot.press("ctrl+w", "k", "2")  # the Pending tab and the details panel
            await settle(pilot)
            details = str(main.query_one("#details").content) if main.query_one("#details").display else ""
            assert not RAW.search(details), details
