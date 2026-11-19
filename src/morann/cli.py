# SPDX-FileCopyrightText: 2026 Cristiano Carvalho
# SPDX-License-Identifier: Apache-2.0
"""Morann: review GitHub pull requests in the terminal, from any folder.

  mor [--owner OWNER]... [--repo OWNER/REPO]... [--theme NAME] [--icons auto|nerd|unicode|ascii] [--read-only] [PR]
  mor update [--owner OWNER]... [--repo OWNER/REPO]... [--no-draft] [--yes]

PR opens one pull request straight away, whether or not it is in the lists: https://github.com/OWNER/REPO/pull/N or
OWNER/REPO#N.

Lists your open pull requests and the open ones that request your review (directly or through a team) for the owners
given with --owner or the repositories given with --repo. Without either it lists the owners in MORANN_OWNERS (comma or
space separated), else those on the `owners = OWNER, OWNER` line of ~/.config/morann/config (MORANN_CONFIG names
another file). The selected pull request's diff opens below the list, with its review threads inline; comments,
replies, resolves and the summary stay local drafts until the confirmation screen posts them as one review.

mor update lists your open pull requests that are behind their base and, with --yes, updates each through GitHub's
update-branch, the lowest of a stack first, skipping those with conflicts. Without --yes it only says what it would do.
It exits 0 when everything was updated or nothing was behind, 1 when an update was refused.

It reads and writes GitHub only through the `gh` CLI you are logged in with. Press ? in the app for the keys.
"""

import argparse
import os
import sys

from morann import __version__, core, termcolors


def parse(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="mor", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--owner", action="append", default=[], help="a GitHub organization; repeat for more")
    parser.add_argument("--repo", action="append", default=[], help="an OWNER/REPO; repeat for more")
    parser.add_argument(
        "--icons",
        choices=("auto", "nerd", "unicode", "ascii"),
        default="auto",
        help="status glyphs: nerd needs a Nerd Font; auto picks nerd on kitty, WezTerm and Ghostty, else unicode "
        "on a UTF-8 locale, else ascii (MORANN_ICONS sets auto's choice)",
    )
    parser.add_argument(
        "--theme",
        help="colors: one-dark (the default), terminal (your terminal's own colors) or a scheme such as "
        "catppuccin-mocha, tokyo-night, gruvbox-dark, nord, rose-pine, catppuccin-latte, github-dark; also "
        "MORANN_THEME or `theme = NAME` in the config; your own schemes go in ~/.config/morann/themes/NAME.toml",
    )
    parser.add_argument("--read-only", action="store_true", help="browse and keep drafts, but never post to GitHub")
    parser.add_argument("--version", action="version", version=f"mor {__version__}")
    parser.add_argument(
        "ref", nargs="?", help="a pull request to open: https://github.com/OWNER/REPO/pull/N or OWNER/REPO#N"
    )
    return parser.parse_args(argv)


def update_main(argv: list[str]) -> int:
    """mor update: a dry run unless --yes."""
    parser = argparse.ArgumentParser(
        prog="mor update", description="Update your pull requests that are behind their base."
    )
    parser.add_argument("--owner", action="append", default=[], help="a GitHub organization; repeat for more")
    parser.add_argument("--repo", action="append", default=[], help="an OWNER/REPO; repeat for more")
    parser.add_argument("--draft", action=argparse.BooleanOptionalAction, default=True, help="include drafts (default)")
    parser.add_argument(
        "--yes", action="store_true", help="update them; without it mor only lists what it would update"
    )
    parser.add_argument("--read-only", action="store_true", help="refuse every write")
    args = parser.parse_args(argv)
    try:
        forge = core.select(read_only=args.read_only)
        items, skipped = core.update_candidates(forge, scope(args), include_drafts=args.draft)
    except (core.UsageError, core.ForgeError) as error:
        print(f"mor update: {error}", file=sys.stderr)
        return 2 if isinstance(error, core.UsageError) else 1
    for item, why in skipped:
        print(f"skip {item.key}: {why}")
    if not items:
        print("nothing is behind its base")
        return 0
    for n, item in enumerate(items, 1):
        behind = f"{item.behind_by} behind" if item.behind_by is not None else "behind"
        stack = f", on #{item.stacked_on}" if item.stacked_on else ""
        print(f"{n}. {item.key} {item.head_ref} <- {item.base} ({behind}{stack}) {item.title}")
    if not args.yes:
        print(f"dry run: {len(items)} would be updated in this order; add --yes to update them")
        return 0
    try:
        results = core.run_updates(
            forge,
            items,
            core.update_fingerprint(items),
            progress=lambda item, result: print(f"{item.key}: {result}", flush=True),
        )
    except (core.PlanError, core.NotConfirmed) as error:
        print(f"mor update: {error}", file=sys.stderr)
        return 1
    return 1 if core.update_failed(results) else 0


def scope(args: argparse.Namespace) -> core.Scope:
    if args.repo:
        return core.Scope(repos=tuple(core.check_repo(repo) for repo in args.repo))
    if args.owner:
        return core.Scope(owners=tuple(core.check_owner(owner) for owner in args.owner))
    return core.Scope(owners=tuple(core.default_owners()))


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if argv[:1] == ["update"]:
        return update_main(argv[1:])
    args = parse(argv)
    try:
        chosen = scope(args)
        forge = core.select(read_only=args.read_only)
        opening = forge.parse_ref(args.ref) if args.ref else None
    except core.UsageError as error:
        print(f"mor: {error}", file=sys.stderr)
        return 2
    try:
        from morann import app
    except ImportError as error:
        print(f"mor: the UI library is missing ({error}); install Morann again", file=sys.stderr)
        return 1
    try:
        tui = app.Morann(
            chosen,
            icons=core.pick_icons(args.icons, os.environ),
            forge=forge,
            opening=opening,
            theme_name=args.theme,
            terminal_colors=termcolors.ask() if sys.stdout.isatty() else None,
        )
    except core.UsageError as error:
        print(f"mor: {error}", file=sys.stderr)
        return 2
    tui.run()
    return 0
