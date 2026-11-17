# SPDX-FileCopyrightText: 2026 Cristiano Carvalho
# SPDX-License-Identifier: Apache-2.0
"""Helpers the tests share: where the checkout is, a refusal to expect, and the app driven by Textual's pilot."""

import re
from pathlib import Path

import pytest

from fake_github import NOW
from morann import core
from morann.app import Morann

ROOT = Path(__file__).resolve().parents[1]
MAIN = ROOT / "src/morann/__main__.py"  # the file the mor launcher runs


def refused(error, words=""):
    """A context for a call that must raise `error` with `words` somewhere in its message."""
    return pytest.raises(error, match=re.escape(words))


def make_app(github, scope=None, **extra):
    """The app against a fake GitHub: its drafts and UI state in the fake's folder, the clock pinned, and links
    printed instead of opened. The key clock stands still too: on a busy machine the pilot can take longer between
    two keys than a chord such as gg or ]c waits, so a test that times one out moves the clock itself."""
    options = {
        "store": core.DraftStore(github.dir / "drafts"),
        "state": core.State(github.dir / "state.json"),
        "now": NOW,
        "opener": print,
        **extra,
    }
    app = Morann(scope or core.Scope(owners=("acme",)), **options)
    app.main.keyclock = lambda: 0.0
    return app


async def settle(pilot):
    """Wait until the app's debounce timer, its workers and the messages they post have all finished."""
    for _ in range(100):
        await pilot.pause(0.02)
        main = pilot.app.main
        if not main.busy and main.timer is None and not any(worker.is_running for worker in pilot.app.workers):
            break
    await pilot.app.workers.wait_for_complete()
    await pilot.pause()


def pr_keys(listing):
    """The keys of the pull requests a list widget shows, in order."""
    return [row.key for row in listing.rows if isinstance(row, core.PrRow)]


def pr_numbers(listing):
    """The numbers of the pull requests a list widget shows, lowest first."""
    return sorted(row.number for row in listing.rows if isinstance(row, core.PrRow))
