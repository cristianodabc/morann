# SPDX-FileCopyrightText: 2026 Cristiano Carvalho
# SPDX-License-Identifier: Apache-2.0
"""The terminal's own colors, asked of the terminal itself before the UI starts: its foreground, background, green,
red and blue. The terminal theme blends its diff tints from them, so the diff looks like github.com's in the
terminal's own colors. A terminal that does not answer in time gives None, and github's colors are used instead.
Standard library only; POSIX terminals only."""

from __future__ import annotations

import os
import re
import select
import time
from collections.abc import Mapping
from dataclasses import dataclass

# OSC 10 and 11 ask the foreground and background, OSC 4 a palette color; the DA1 request after them is answered by
# every terminal, so its answer says that nothing more is coming.
ASKS = {"foreground": "10", "background": "11", "red": "4;1", "green": "4;2", "blue": "4;4"}
QUERY = "".join(f"\x1b]{code};?\x1b\\" for code in ASKS.values()) + "\x1b[c"
ANSWER = re.compile(r"\x1b\](10|11|4;\d+);rgba?:([0-9a-fA-F]{1,4})/([0-9a-fA-F]{1,4})/([0-9a-fA-F]{1,4})")
DONE = re.compile(r"\x1b\[\?[\d;]*c")
WAIT = 0.25  # seconds the terminal has to answer


@dataclass(frozen=True)
class TerminalColors:
    foreground: str
    background: str
    red: str
    green: str
    blue: str

    @property
    def dark(self) -> bool:
        """Whether the background is dark, by its relative luminance."""
        red, green, blue = (int(self.background[at : at + 2], 16) / 255 for at in (1, 3, 5))
        return 0.2126 * red + 0.7152 * green + 0.0722 * blue < 0.5


def dark_background(environ: Mapping[str, str]) -> bool:
    """A guess at a dark background for a terminal that did not answer: COLORFGBG's background color when it names
    one (0 to 6 and 8 are dark), else dark."""
    background = environ.get("COLORFGBG", "").rpartition(";")[2]
    return not background.isdigit() or int(background) in (0, 1, 2, 3, 4, 5, 6, 8)


def channel(digits: str) -> int:
    """One channel of an XParseColor answer (1 to 4 hex digits) on the 0 to 255 scale."""
    top: int = 16 ** len(digits) - 1
    return round(int(digits, 16) * 255 / top)


def parse(reply: str) -> TerminalColors | None:
    """The colors in a terminal's answers, or None when one of them is missing."""
    codes = {code: name for name, code in ASKS.items()}
    found = {}
    for answer in ANSWER.finditer(reply):
        name = codes.get(answer.group(1))
        if name:
            found[name] = "#" + "".join(f"{channel(answer.group(at)):02x}" for at in (2, 3, 4))
    return TerminalColors(**found) if len(found) == len(ASKS) else None


def ask(environ: Mapping[str, str] | None = None, wait: float = WAIT) -> TerminalColors | None:
    """Ask the terminal on /dev/tty for its colors; None without a terminal, under NO_COLOR or MORANN_ASK_COLORS=0,
    or when it does not answer within `wait` seconds."""
    environ = os.environ if environ is None else environ
    if "NO_COLOR" in environ or environ.get("MORANN_ASK_COLORS", "").strip() == "0":
        return None
    try:
        import termios
    except ImportError:  # not a POSIX system
        return None
    try:
        fd = os.open("/dev/tty", os.O_RDWR | os.O_NOCTTY)
    except OSError:
        return None
    try:
        before = termios.tcgetattr(fd)
    except termios.error:
        os.close(fd)
        return None
    reply = b""
    try:
        quiet = termios.tcgetattr(fd)
        quiet[3] &= ~(termios.ECHO | termios.ICANON)  # the answers must not show on screen or wait for enter
        termios.tcsetattr(fd, termios.TCSANOW, quiet)
        os.write(fd, QUERY.encode())
        deadline = time.monotonic() + wait
        while not DONE.search(reply.decode(errors="replace")):
            left = deadline - time.monotonic()
            if left <= 0 or not select.select([fd], [], [], left)[0]:
                break
            reply += os.read(fd, 1024)
    except OSError:
        return None
    finally:
        termios.tcsetattr(fd, termios.TCSAFLUSH, before)
        os.close(fd)
    return parse(reply.decode(errors="replace"))
