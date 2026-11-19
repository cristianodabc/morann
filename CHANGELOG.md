# Changelog

All notable changes to Morann are listed here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/)
and the project uses [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## Unreleased

## 0.1.0 - 2026-11-19

### Added

- Morann, a pull request reviewer for the terminal. It lists your open pull requests, the ones waiting for your
  review and every open pull request of the owners you choose, and shows the selected one below: its conversation,
  commits, checks, and its diff with the review threads under the lines they were left on.
- Reviews from local drafts. Comments, replies, resolves and the summary stay on your machine until one confirmed
  submit posts them as a single review.
- Actions on your own pull requests: merge, update the branch, close, reopen, mark ready or draft, turn auto-merge
  on or off, and re-request review. `mor update` updates every pull request of yours that is behind its base.
- The `mor` command, installed with `uv tool install`, `pipx install`, or `install.sh` from a clone with pinned,
  hashed dependencies.
- A forge interface, `morann.forge.Forge`, with GitHub as the provider behind it through the `gh` CLI.
  `MORANN_FORGE`, or a `forge = NAME` line in the config file, selects a provider, and another package can register
  one. `docs/adding-a-forge.md` describes it.
- A visual system built on design tokens. By default every token is one of the terminal's own colors, so Morann
  follows the terminal's theme. `--theme NAME`, `MORANN_THEME` or a `theme = NAME` config line picks a named scheme
  instead: Catppuccin Mocha and Latte, Tokyo Night, Gruvbox Dark, Nord, Rosé Pine, One Dark, GitHub Dark and Light, or your
  own TOML file in `~/.config/morann/themes`. `NO_COLOR` is respected. Each status keeps one color and one glyph
  everywhere.
- `--icons auto`, the default, picks Nerd Font icons on kitty, WezTerm and Ghostty, Unicode glyphs on a UTF-8
  locale, and ASCII otherwise; `--icons unicode` is new.
- Vim-style navigation: a `:` command line with completion and history, a `ctrl+p` fuzzy jump to any pull request,
  one `ctrl+o` and `ctrl+i` jump list across panes and pull requests, `ctrl+w` between panes, and `gt` `gT`
  between tabs.
- A header with a breadcrumb, a hint bar with the keys of the focused pane, a help grouped by task with a filter,
  and one dialog frame for the actions, the pickers and the help.
- The review screen: the diff drawn like github.com's in every theme (green and red lines, stronger changed words,
  a blue hunk band; the terminal theme blends the terminal's own green and red, asked of it at start), unchanged
  lines folded between hunks and shown on enter, old and new side by side on wide panes (`|`), the file and hunk
  held above the diff, review progress (files viewed, open threads, drafts), each thread's state, and `]`/`[`
  motions through changes, hunks, files, threads, unresolved threads, comments and drafts.
- The Conversation tab opens with what needs you; verdicts carry a chip; the Checks tab leads with a tally.
- Links in descriptions and comments show as their text, as real hyperlinks where the terminal has them; bare URLs
  and `#123` references become links; `gx` opens and `gy` copies one.
- A Pending tab of your reviews in progress, here or on GitHub, the longest waiting first.
- A review starts only on purpose (`v`, `:review`, or y to the question a commenting key asks), shows in the
  header while on, and ends by posting or by discarding it after a y. Opening a pull request keeps nothing.
- Tabs show their key dimmed and their count as a badge colored by meaning.
- `ctrl+p` also reaches the open pull request's files and the commands.
- One comment, reply, resolve or conversation comment can go on its own, outside a review, as github.com's "Add
  single comment" does, after a confirmation that shows what goes where. Every question is one centered dialog.
- A statusline in the style of Neovim's lualine in place of the hint bar: the mode, where you are, review progress,
  checks and merge state, a few keys, the position and the theme; its segments are a setting.
- Every surface draws descriptions and comments through one markdown renderer: images, footnotes, HTML links and
  details blocks show as text too, links never show raw, and code is left as written.
- Your own posted comments, review summaries and pull request descriptions can be edited (`e`, `:edit`) and your
  comments deleted (`d d`, `:delete`), each after a confirmation showing the change or the text; edited posts are
  marked.
