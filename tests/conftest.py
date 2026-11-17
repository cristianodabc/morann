# SPDX-FileCopyrightText: 2026 Cristiano Carvalho
# SPDX-License-Identifier: Apache-2.0
"""Test setup: every run gets a throwaway home, and a coroutine test is run to its end."""

import asyncio
import inspect
import os
import shutil
import tempfile

import pytest

SCRATCH = pytest.StashKey[str]()
FOLDERS = {"HOME": "home", "XDG_CACHE_HOME": "cache", "XDG_CONFIG_HOME": "config", "XDG_DATA_HOME": "data"}
UNSET = ("NO_COLOR", "COLORTERM")  # the tests that depend on color say which they want
TEST_TIMEOUT = 300  # seconds a coroutine test may take: one that hangs fails instead of holding the whole run


def pytest_configure(config):
    """Point HOME, the XDG folders and MORANN_HOME at a throwaway folder and drop every MORANN_ setting, so a run
    never reads or writes your drafts, cache or config, and never depends on them."""
    scratch = tempfile.mkdtemp(prefix="morann-tests-")
    config.stash[SCRATCH] = scratch
    for name in list(os.environ):
        if name.startswith("MORANN_") or name in UNSET:
            del os.environ[name]
    for name, folder in FOLDERS.items():
        os.environ[name] = os.path.join(scratch, folder)
    os.environ["MORANN_HOME"] = os.path.join(scratch, "morann")
    os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
    os.makedirs(os.environ["HOME"])


def pytest_unconfigure(config):
    shutil.rmtree(config.stash[SCRATCH], ignore_errors=True)


@pytest.hookimpl(tryfirst=True)
def pytest_pyfunc_call(pyfuncitem):
    """Run a coroutine test to its end, or to TEST_TIMEOUT. Textual's pilot needs a running event loop and nothing
    more."""
    if not inspect.iscoroutinefunction(pyfuncitem.obj):
        return None
    names = inspect.signature(pyfuncitem.obj).parameters
    test = pyfuncitem.obj(**{name: pyfuncitem.funcargs[name] for name in names})
    asyncio.run(asyncio.wait_for(test, TEST_TIMEOUT))
    return True
