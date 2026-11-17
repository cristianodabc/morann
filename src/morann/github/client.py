# SPDX-FileCopyrightText: 2026 Cristiano Carvalho
# SPDX-License-Identifier: Apache-2.0
"""GitHub through the gh CLI the user is logged in with: one process per call, no token read or stored."""

from __future__ import annotations

import json
import subprocess
from typing import Any

from morann.forge import ForgeError
from morann.textfmt import cut

TIMEOUT = 60  # seconds one gh call may take

LOGIN = "GitHub login expired, run: gh auth login"


def explain(text: str) -> str:
    """One plain line for what gh printed when it failed: the login command for an expired login, GitHub's own messages
    for a refused request, else gh's first line."""
    text = text or ""
    if "gh auth login" in text or "HTTP 401" in text:
        return LOGIN
    for start in (i for i, ch in enumerate(text) if ch == "{"):
        try:
            body = json.loads(text[start:])
        except ValueError:
            continue
        if isinstance(body, dict):
            parts = [str(body.get("message") or "")]
            for error in body.get("errors") or []:
                parts.append(str(error.get("message") or error) if isinstance(error, dict) else str(error))
            line = ": ".join(part for part in parts if part)
            if line:
                return cut(line, 200)
        break
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    return cut(lines[0].removeprefix("gh:").strip() if lines else "gh failed", 200)


class Gh:
    """The gh CLI. Every failure is a ForgeError, never a crash of the app. With read_only, every write (a POST, PUT,
    PATCH or DELETE to REST, or a GraphQL mutation) is refused before gh runs."""

    def __init__(self, program: str = "gh", timeout: float = TIMEOUT, read_only: bool = False) -> None:
        self.program = program
        self.timeout = timeout
        self.read_only = read_only

    def refuse_writes(self) -> None:
        if self.read_only:
            raise ForgeError("Morann runs read-only (--read-only); nothing was posted")

    def run(self, args: list[str], stdin: str | None = None) -> str:
        """What gh printed for these arguments, with stdin as its input when given."""
        feed: dict[str, Any] = {"input": stdin} if stdin is not None else {"stdin": subprocess.DEVNULL}
        try:
            done = subprocess.run(  # noqa: S603 - the program is gh and the arguments are built here, never a shell line
                [self.program, *args],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=self.timeout,
                check=False,
                **feed,
            )
        except FileNotFoundError:
            raise ForgeError("gh is not installed or not on PATH; install GitHub CLI and run gh auth login") from None
        except subprocess.TimeoutExpired:
            raise ForgeError(f"gh took more than {self.timeout} seconds", maybe_sent=True) from None
        except OSError as error:
            raise ForgeError(f"gh could not run: {error}") from None
        if done.returncode != 0:
            raise ForgeError(explain(f"{done.stderr}\n{done.stdout}"))
        return str(done.stdout)

    def get(self, path: str) -> Any:
        return self.decode(self.run(["api", path]))

    def pages(self, path: str) -> list[Any]:
        """Every item of a paginated list endpoint, one JSON value per line."""
        out = self.run(["api", "--paginate", path, "--jq", ".[] | tojson"])
        return [self.decode(line) for line in out.split("\n") if line.strip()]

    def graphql(self, query: str, variables: dict[str, Any] | None = None) -> dict[str, Any]:
        if query.lstrip().startswith("mutation"):
            self.refuse_writes()
        out = self.run(
            ["api", "graphql", "--method", "POST", "--input", "-"],
            stdin=json.dumps({"query": query, "variables": variables or {}}),
        )
        body = self.decode(out)
        if body.get("errors"):
            raise ForgeError(cut("; ".join(str(error.get("message", error)) for error in body["errors"]), 200))
        data: dict[str, Any] = body.get("data") or {}
        return data

    def post(self, path: str, payload: dict[str, Any]) -> Any:
        return self.send("POST", path, payload)

    def send(self, method: str, path: str, payload: dict[str, Any]) -> Any:
        """A REST write (POST, PUT, PATCH or DELETE) with a JSON body."""
        self.refuse_writes()
        return self.decode(
            self.run(["api", "--method", method, path, "--input", "-"], stdin=json.dumps(payload)) or "{}"
        )

    @staticmethod
    def decode(text: str) -> Any:
        try:
            return json.loads(text)
        except ValueError:
            raise ForgeError("gh printed something that is not JSON") from None
