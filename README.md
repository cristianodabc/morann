# Morann

[![CI](https://github.com/cristianodabc/morann/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/cristianodabc/morann/actions/workflows/ci.yml)
[![CodeQL](https://github.com/cristianodabc/morann/actions/workflows/codeql.yml/badge.svg?branch=main)](https://github.com/cristianodabc/morann/actions/workflows/codeql.yml)
[![License: Apache-2.0](https://img.shields.io/github/license/cristianodabc/morann)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue)](pyproject.toml)
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)

Review pull requests in the terminal, from any folder.

Morann is named after the legendary Irish judge whose collar tightened when he ruled falsely.

It lists your open pull requests, the ones waiting for your review and every open pull request of the owners you
choose. Below the list it shows the selected pull request: its conversation, commits, checks, and its diff with the
review threads under the lines they were left on. Comments, replies, resolves and the summary stay local drafts
until one confirmed submit posts them as a single review. On your own pull requests it can also merge, update the
branch, close, reopen, mark ready or draft, turn auto-merge on or off, and re-request review.

Morann talks to GitHub only through the `gh` CLI you are logged in with. It stores no token and posts nothing
without an explicit confirmation.

## Install

You need Python 3.11 or newer and a logged-in [GitHub CLI](https://cli.github.com/) (`gh auth login`).

With [uv](https://docs.astral.sh/uv/) or [pipx](https://pipx.pypa.io/):

```sh
uv tool install git+https://github.com/cristianodabc/morann
# or
pipx install git+https://github.com/cristianodabc/morann
```

Or from a clone, with every dependency pinned to an exact version and hash:

```sh
git clone https://github.com/cristianodabc/morann
morann/install.sh
```

`install.sh` builds a virtual environment from `requirements.txt` (exact versions with hashes, wheels only, so
nothing is built or run at install time) and links `mor` into `~/.local/bin`. Running it again with an unchanged
lock does nothing, and a failed build keeps the previous environment.

`mor --version` prints the version.

## Usage

```
mor [--owner OWNER]... [--repo OWNER/REPO]... [--theme NAME] [--icons auto|nerd|unicode|ascii] [--read-only] [PR]
mor update [--owner OWNER]... [--repo OWNER/REPO]... [--no-draft] [--yes]
```

- `mor --owner my-org` lists the pull requests of one owner. Repeat `--owner` for more, or name repositories with
  `--repo my-org/app`.
- `PR` opens one pull request straight away: `https://github.com/OWNER/REPO/pull/N` or `OWNER/REPO#N`.
- `--read-only` browses and keeps drafts but refuses every write.
- `--theme NAME` chooses the colors; see [Colors](#colors).
- `--icons` picks the status glyphs: `nerd` (needs a Nerd Font), `unicode` or `ascii`. The default, `auto`, picks
  `nerd` on kitty, WezTerm and Ghostty (they ship the Nerd Font symbols), else `unicode` on a UTF-8 locale, else
  `ascii`; `MORANN_ICONS` sets what `auto` picks.
- `mor update` lists your open pull requests that are behind their base. With `--yes` it updates each one, the
  lowest of a stack first, and skips those with conflicts. It exits 1 when an update was refused.

## Configuration

Morann lists the owners given with `--owner`, or the repositories given with `--repo`. Without either it takes the
owners from `MORANN_OWNERS` (separated by commas or spaces), else from the config file:

```
# ~/.config/morann/config
owners = my-org, other-org
theme = catppuccin-mocha
```

| Variable | Default | What it sets |
| --- | --- | --- |
| `MORANN_OWNERS` | none | the owners to list when no `--owner` or `--repo` is given |
| `MORANN_CONFIG` | `${XDG_CONFIG_HOME:-~/.config}/morann/config` | the config file |
| `MORANN_HOME` | `${XDG_CACHE_HOME:-~/.cache}/morann` | drafts, the pull request cache and the UI state |
| `MORANN_THEME` | `one-dark` | the theme, as `--theme` and the config's `theme = NAME` line set it |
| `MORANN_THEMES` | `${XDG_CONFIG_HOME:-~/.config}/morann/themes` | the folder of your own color schemes |
| `MORANN_ASK_COLORS` | `1` | `0` stops Morann asking the terminal for its colors at start |
| `MORANN_STATUSLINE_LEFT`, `MORANN_STATUSLINE_RIGHT` | as the config | the statusline's segments, in order |
| `MORANN_HYPERLINKS` | detected | `1` or `0`: whether the terminal shows real hyperlinks |
| `MORANN_ICONS` | none | the glyph set `--icons auto` picks: `nerd`, `unicode` or `ascii` |
| `MORANN_FORGE` | `github` | the forge to use; a `forge = NAME` line in the config file does the same |
| `MORANN_BIN_DIR` | `~/.local/bin` | where `install.sh` links `mor` (`--no-link` skips the link) |
| `MORANN_DATA_DIR` | `${XDG_DATA_HOME:-~/.local/share}/morann` | where `install.sh` builds the Python environment |
| `MORANN_PYTHON` | `$MORANN_DATA_DIR/venv/bin/python` | the Python the `mor` launcher from `install.sh` runs |
| `NO_COLOR` | unset | turns color off |

### Colors

By default Morann draws in the One Dark color scheme. Choose another with `--theme NAME`, `MORANN_THEME=NAME`, or a
`theme = NAME` line in the config file; `T` in the app tries the next one, and `:theme NAME` switches by name.

`--theme terminal` uses your terminal's own colors instead: its default foreground and background and its 16 ANSI
colors, and no background of its own. It looks like the rest of your terminal and follows its theme as that changes.
Hierarchy comes from bold, dim and reverse, and status from the ANSI colors, each with one meaning everywhere: green
passing or approved, red failing, changes requested or conflicting, yellow waiting or behind its base, blue new
activity, magenta merged and your unsent drafts. Each also has a glyph, so none depends on color alone.

| Name | Scheme |
| --- | --- |
| `terminal` | your terminal's own colors |
| `catppuccin-mocha`, `catppuccin-latte` | [Catppuccin](https://catppuccin.com) dark and light |
| `tokyo-night` | [Tokyo Night](https://github.com/folke/tokyonight.nvim) |
| `gruvbox-dark` | [Gruvbox](https://github.com/morhetz/gruvbox) |
| `nord` | [Nord](https://www.nordtheme.com) |
| `rose-pine` | [Rosé Pine](https://rosepinetheme.com) |
| `one-dark` | [One Dark](https://github.com/atom/atom/tree/master/packages/one-dark-syntax), from Atom (the default) |
| `github-dark`, `github-light` | github.com's dark and light modes |

To add your own, put a file `NAME.toml` in `~/.config/morann/themes` (or the folder `MORANN_THEMES` names) and
choose it by `NAME`; a file there with a built-in name replaces that scheme. Copy one of the built-in files in
[src/morann/themes](src/morann/themes) to start. `background`, `text`, `accent`, `ok`, `bad`, `warn`, `info` and
`merged` are required; `surface`, `panel`, `border`, `muted`, `subtle`, `local` and `selection` are worked out from
them when left out:

```toml
name = "My scheme"
dark = true

[colors]
background = "#1e1e2e"
text = "#cdd6f4"
accent = "#89b4fa"
ok = "#a6e3a1"
bad = "#f38ba8"
warn = "#f9e2af"
info = "#74c7ec"
merged = "#cba6f7"
```

`NO_COLOR` turns color off whatever the theme.

The diff looks like github.com's in every theme: added lines on a green background and removed lines on a red one
across the whole line, the changed words in a stronger shade, the line numbers tinted to match, and a blue band for
each hunk. On a terminal with 24-bit color (`COLORTERM=truecolor` or `24bit`) the colors are github's own, dark or
light to match the theme; in the terminal's theme they are blended from the terminal's own green, red and blue when
the terminal answers Morann's question for them at start (`MORANN_ASK_COLORS=0` skips it). With 16 colors the lines
sit on the terminal's ANSI green and red.

## Keys

Morann is driven from the keyboard, vim style; the mouse also works. `?` lists every key grouped by task, the focused
pane's first; `/` in the help filters it.

The bottom line is a statusline in the style of Neovim's lualine: a mode on the left (READING, REVIEWING, PENDING,
COMMAND, SEARCH, WRITING, each in its own color), then where you are, the branch, the tab, review progress, checks and
merge state, a few keys of the focused pane in the middle, and the position, the theme and `? help` on the right. On
a narrow terminal the theme, branch and merge state go first, then the keys, before the mode, position or progress.
Choose and order the segments in the config file:

```
statusline_left = mode, where, branch, tab, progress, checks, merge
statusline_right = position, theme, help
```

Each tab shows its key on the left, dimmed, and its count on the right as a badge: red for failing checks or
requested changes, the accent for what needs you.

### Getting around

| Keys | What they do |
| --- | --- |
| `:` | The command line; `tab` completes, up and down walk the history. See [Commands](#commands). |
| `ctrl+p` | Jump by a few letters to any pull request on hand, a file of the open one, or a command (fuzzy). |
| `ctrl+o` `ctrl+i` | Back to where you were and forward again, across panes and pull requests; `O` also goes forward, since most terminals send `tab` for `ctrl+i`. |
| `tab`, `ctrl+w` `j` `k` `w` | The other pane; the pull request pane, the list, the other one. `ctrl+w` `b` `t` are the bottom and top pane like `j` `k`, `ctrl+w` `p` and `ctrl+w` `ctrl+w` the other one. `ctrl+w` `h` `l` (or `ctrl+h` `ctrl+l` after it) move between the file tree and the diff. |
| `j` `k`, `gg` `G`, `H` `L` | Move; the top and bottom; the top and bottom of the view. A count repeats a motion (`5j`, `5G`). |
| `ctrl+d` `ctrl+u`, `ctrl+f` `ctrl+b`, `ctrl+e` `ctrl+y`, `zt` `zz` `zb` | Half and whole pages; scroll a line down or up, the cursor staying on its row until the row leaves the view; scroll the cursor row to the top, middle or bottom (`z.` is `zz`). |
| `{` `}` | In the list, the previous and next repository, or the first and last row where there is none. In the diff they are the previous and next file. |
| `gt` `gT`, `[` `]` | The next and previous tab of the focused pane. |
| `]c` `[c`, `]h`, `]f`, `]t`, `]u`, `]m`, `]d` | The next and previous change, hunk, file, thread, unresolved thread, comment or draft of yours, into the next file where this one has no more (`3]c` repeats). A quick letter after `[` or `]` makes the motion instead of the tab step. |
| `/`, `n` `N` | Filter the list or search the pull request pane; the next and previous match. |

### Reviewing

Opening and reading a pull request keeps nothing on disk and sends nothing. A review starts only on purpose: `v` or
`:review` starts one. With none on, `c`, `C`, `R` and `x` open a dialog that offers to send the comment, reply or
resolve on its own now, as github.com's "Add single comment" does (`s`), or to start a review (`r`); `m`, `a` and `r`
ask whether to start a review. Something sent on its own is written in the inline editor first, then a confirmation
shows exactly what goes where, and only its `y` sends it, while the pull request's head is still the one you read.
While a review is on, the header says "Reviewing: N drafts". It ends when you post it from the review bar, or when you
discard it (`D` in the bar, or `:review discard`, after a `y`). Every question is the same centered dialog: `y` or
`enter` to go on, `n` or `esc` to cancel.

A review you started and did not submit, on GitHub's own site or earlier from Morann, is resumed, not repeated. When
the pull request loads, Morann finds your pending review (only you can see it): its comments show under their lines
marked "pending on github.com", and the header says "Pending review: N comments". `c`, `R` and `v` then add to it, as
drafts on your machine, and the review bar says "resuming your pending review". The one `y` that posts adds each draft
comment and reply to that review and submits it with the verdict and summary you chose, so GitHub gets one review, not
a second. Nothing is sent before that `y`, except a single comment you choose to send on its own. If the pending
review was submitted or discarded elsewhere in the meantime, Morann reads it again, says so, sends nothing and keeps
your drafts. Only your own pending review is ever read or touched.

What you already posted can be changed too, when it is yours: `e` on your comment (on the diff or the conversation),
your review summary, or the description of your own pull request opens the editor with its text, and a confirmation
shows the change, old and new, before it is sent; `d` `d` on your comment shows it whole and asks before deleting it.
A submitted review's summary and a description can be edited, not deleted. An edited post is marked as such.
`--read-only` refuses both.

| Where | Keys |
| --- | --- |
| Anywhere | `v` starts a review, then shows what it would post. `C` comments on the conversation. `M` opens the actions. `z` `+` `-` size the pull request pane. `ctrl+r` refreshes, and `r` does in the list; the header names the one that works, beside the scope and the time since the last refresh. `T` tries the next color theme. `q` quits. |
| List | `1` `2` `3` `4` choose Mine, Pending (your reviews in progress, here or on GitHub, the longest waiting first), To Review or All. `enter` opens the pull request below (from Pending, at its first draft). `o` opens it in GitHub. `s` chooses the scope. `m` shows only yours. `g` groups by repository. `U` updates your pull requests behind their base. `!` `b` `d` show only failing, behind or draft pull requests. |
| Pull request | `1` `2` `3` `4` choose Conversation, Commits, Checks or Files. `{` `}` go to the previous and next file. `n` `p` go to the next and previous thread. `u` shows only unresolved threads. `gx` opens a link of the comment under the cursor, after showing its address; `gy` copies one. |
| Diff | `c` comments on the line. `R` replies. `x` marks a thread to resolve. `e` edits the draft, or your own posted comment, review summary or description, under the cursor (elsewhere on the Files tab it shows the file tree). `d` `d` deletes a draft, or your own posted comment after a confirmation. `a` approves. `r` requests changes. `m` writes the summary. `f` focuses the file tree. `V` marks the file viewed. `enter` on "N unchanged lines" shows them. <code>&#124;</code> shows old and new side by side, where the diff has 120 columns. |
| Review bar | `c` `a` `r` choose Comment, Approve or Request changes. `m` writes the summary. `l` hides or shows what it would post. `y` posts. `D` discards the review. `esc` goes back. |
| Actions | `s` `m` `b` choose squash, merge commit or rebase. `u` updates the branch. `c` `o` close and reopen. `w` marks ready or draft. `A` toggles auto-merge. `R` re-requests review. `y` sends, twice for a merge or a close. |

The Conversation tab opens with what needs you: a review asked of you, failing checks, requested changes, conflicts,
threads waiting on your reply, your unsent drafts. Each thread shows its state (open or resolved, outdated, yours,
your turn, draft), and the header counts the files viewed, the open threads and your drafts.

Descriptions and comments are drawn as markdown everywhere they show: headings, lists, quotes, tables, emphasis and
code, a link as its text, an image as a link named by its alt text, footnotes as `[1]`, `<details>` sections with
their summary in bold, and a suggested change labeled as one. Bare URLs and `#123` references become links too; code
is never touched. On a terminal known to show hyperlinks (kitty, WezTerm, Ghostty, Alacritty, foot, iTerm2, VS Code,
VTE terminals; `MORANN_HYPERLINKS=1` or `0` says so for any other, such as one behind a multiplexer) a link is a real
hyperlink; elsewhere its text alone shows. Only `http` and `https` links become hyperlinks, and `gx` shows a link's
whole address before it opens anything, `gy` copies it.

The list flags what needs you, with these glyphs in `--icons unicode` (the ASCII ones in brackets): failing checks
`✗` (`x`), changes requested `±` (`!`), conflicts `≠` (`#`), behind its base `↓` (`<`), and new activity since you
last opened it `●` (`o`).

A few vim keys already had a meaning here and keep it: in the list `g` groups, so `gg` is two quick presses; `z`
maximizes the pull request pane, and a quick `t`, `z`, `.` or `b` after it scrolls instead; `M` opens the actions, so
there is no `M` for the middle of the view; `m` is "mine only" in the list and the summary in the diff, so there are no
marks; `n` in the pull request pane is the next thread until a search is active. A count starts with 5 to 9, because 1
to 4 choose tabs. A row has no cursor column, so there are no word or line motions (`w`, `b`, `0`, `$`) and no `*`;
`?` is the help, so `/` and `n` `N` are the only search.

### Commands

| Command | What it does |
| --- | --- |
| `:open REF` | Open a pull request: a link, `OWNER/REPO#N`, `#N` or `N`; a bare link or reference works too. |
| `:review`, `:review discard` | Start a review, or show what it would post; discard it, after a `y`. |
| `:scope mine\|personal\|ORG`, `:tab mine\|pending\|review\|all` | Switch the scope or the list's tab. |
| `:repo OWNER/REPO`, `:filter TEXT` | Show only one repository's pull requests, or filter by text; empty clears. |
| `:files` `:conversation` `:commits` `:checks` | The pull request's tabs. |
| `:next KIND`, `:prev KIND` | The next or previous change, hunk, file, thread, unresolved thread, comment or draft. |
| `:split`, `:unified`, `:expand` | Side by side or one column; show every folded run of unchanged lines. |
| `:edit`, `:delete` | Edit or delete the draft, or your own posted comment, under the cursor. |
| `:link`, `:copy` | Open, or copy the address of, a link of the row under the cursor. |
| `:theme NAME`, `:refresh`, `:help [WORDS]`, `:q` | Pick a color theme, read again, the keys, quit. |

## Forges

| Forge | Status | Through |
| --- | --- | --- |
| GitHub | supported | the `gh` CLI you are logged in with |

The UI and the review logic talk to one interface, and GitHub is the provider behind it. A provider for GitLab,
Bitbucket or another forge can be added to this repository or shipped as its own package, and a forge that lacks
something, such as auto-merge, says so instead of failing. [docs/adding-a-forge.md](docs/adding-a-forge.md) has
the interface and the steps.

## Drafts

Everything you write is a draft first. Drafts are JSON files on your machine, one per pull request:

```
~/.cache/morann/drafts/OWNER/REPO/NUMBER.json
```

`MORANN_HOME` moves the folder. A draft is written whole and renamed into place, so a crash never leaves half a
file, and a damaged file is set aside instead of overwritten. A comment draft remembers the code it was written
on: after a push puts other code on that line, Morann refuses to post it and tells you to check it.

## Security

Morann calls only the forge CLI you are already logged in with and holds no credential. Nothing is posted, merged
or changed without `y`, a merge or a close takes `y` twice, and `--read-only` refuses every write. What is sent is
exactly what the confirmation showed, and only while the pull request's head is still the one you reviewed. The
details and how to report a vulnerability are in [SECURITY.md](SECURITY.md).

## Development

```sh
make setup   # .venv from requirements.txt and requirements-dev.txt: exact versions, hashes required
make check   # lint, types, tests with the coverage gate, shell, workflows, security, audit, secrets, build
```

The tests run with a throwaway home and a fake `gh` first on `PATH`, so they never touch your drafts or GitHub. CI
runs the same targets on Linux and macOS with Python 3.11, 3.12 and 3.13. [CONTRIBUTING.md](CONTRIBUTING.md) has
the rest.

## License

Apache License 2.0. See [LICENSE](LICENSE) and [NOTICE](NOTICE).
