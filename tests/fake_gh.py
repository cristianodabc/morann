# SPDX-FileCopyrightText: 2026 Cristiano Carvalho
# SPDX-License-Identifier: Apache-2.0
"""The fake `gh` the tests put first on PATH: it answers from a JSON fixture and logs every call.

It runs as a program, once per call, with the standard library only. MORANN_FAKE_GH names the fixture file and
MORANN_FAKE_GH_LOG the call log; fake_github.FakeGitHub sets both."""

import json
import os
import re
import sys
import time
from pathlib import Path

HEAD = "a" * 40  # the head commit of every pull request in the fixture, until a test moves it

WRITE_KINDS = {  # the last segment of a REST write's path, and the fixture key that can refuse or slow it down
    "replies": "replies",
    "reviews": "reviews",
    "comments": "notes",
    "merge": "merge",
    "update-branch": "update",
    "requested_reviewers": "rerequest",
    "merge-async": "merge_async",
}


def scoped_nodes(data, term):
    """The pull requests a search qualifier (org:, user: or repo:) matches in the fixture's wider scopes."""
    if term.startswith("repo:"):
        return [
            node
            for nodes in data["scoped"].values()
            for node in nodes
            if node["repository"]["nameWithOwner"] == term[5:]
        ]
    return data["scoped"].get(term, [])


def page(nodes, variables, total_key):
    """One page of nodes after the cursor in the variables, shaped as a GraphQL connection."""
    start = int(variables.get("after") or 0)
    end = start + variables["first"]
    return {
        total_key: len(nodes),
        "pageInfo": {"hasNextPage": end < len(nodes), "endCursor": str(end)},
        "nodes": nodes[start:end],
    }


def save(path, data):
    """Replace the fixture in one step. The app runs gh calls in parallel, and a call that read a file another one
    was still writing would fail on half its JSON."""
    temp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    temp.write_text(json.dumps(data))
    os.replace(temp, path)


def answer(value):
    print(json.dumps(value))
    return 0


def fake_gh(args):
    """One answer per call shape Morann makes, and every call logged. Returns the exit status."""
    path = Path(os.environ["MORANN_FAKE_GH"])
    data = json.loads(path.read_text())
    stdin = sys.stdin.read() if "--input" in args else ""
    with open(os.environ["MORANN_FAKE_GH_LOG"], "a") as log:
        log.write(json.dumps({"args": args, "stdin": stdin}) + "\n")
    if data.get("down"):
        print("To get started with GitHub CLI, please run:  gh auth login", file=sys.stderr)
        return 4

    def head(key):
        heads = data["prs"][key]["heads"]
        if len(heads) == 1:
            return heads[0]
        value = heads.pop(0)
        save(path, data)
        return value

    def refuse(what):
        message = data["fail"].get(what)
        if message:
            print("gh: Validation Failed (HTTP 422)", file=sys.stderr)
            print(json.dumps({"message": "Validation Failed", "errors": [message]}))
            return True
        return False

    def graphql():
        body = json.loads(stdin)
        query, variables = body["query"], body["variables"]
        viewer = {"login": data["viewer"]}
        if "object(expression" in query:  # a file at a ref
            key = f"{variables['owner']}/{variables['name']}@{variables['expression']}"
            return answer({"data": {"repository": {"object": data.get("objects", {}).get(key)}}})
        if "all: search(" in query:  # one page of a wider scope, or a search in it for a quoted phrase
            phrase = re.search(r'"([^"]*)"', variables["q"])
            if phrase and refuse("search"):
                return 1
            outside = re.sub(r'"[^"]*"', "", variables["q"])  # a qualifier inside the phrase is only text
            terms = re.findall(r"(?:org|user|repo):\S+", outside)  # org:a org:b is a union, newest update first
            nodes = sorted(
                [node for term in terms for node in scoped_nodes(data, term)],
                key=lambda n: n["updatedAt"],
                reverse=True,
            )
            if phrase:
                nodes = [node for node in nodes if phrase[1].casefold() in node["title"].casefold()]
            return answer({"data": {"viewer": viewer, "all": page(nodes, variables, "issueCount")}})
        if query.strip() == "query { viewer { login } }":
            return answer({"data": {"viewer": viewer}})
        if "search(" in query:
            assert "author:@me" in variables["mine"] and "review-requested:@me" in variables["review"], variables
            lists = {name: {"issueCount": len(nodes), "nodes": nodes} for name, nodes in data["search"].items()}
            return answer({"data": {"viewer": viewer, **lists}})
        if query.lstrip().startswith("mutation"):
            name = re.search(r"\{\s*(\w+)\(input", query)[1]
            if refuse(name):
                return 1
            if name == "submitPullRequestReview":  # a submitted review is no longer pending, on any pull request
                for pull in data["prs"].values():
                    nodes = (pull["node"].get("pendingReviews") or {}).get("nodes") or []
                    for node in nodes:
                        if node["id"] == variables["review"]:  # GitHub keeps the old body unless a new one comes
                            body = variables["body"] if "body" in variables else node.get("body", "")
                            data.setdefault("submitted", {})[node["id"]] = {"event": variables["event"], "body": body}
                    pull["node"]["pendingReviews"] = {"nodes": [n for n in nodes if n["id"] != variables["review"]]}
                save(path, data)
            return answer({"data": {name: {"ok": True}}})
        if query.lstrip().startswith("query PendingReview"):  # the viewer's pending review alone, read before a resume
            if refuse("pending"):
                return 1
            key = f"{variables['owner']}/{variables['name']}#{variables['number']}"
            node = data["prs"][key]["node"]
            pending = {"pendingReviews": node.get("pendingReviews") or {"nodes": []}}
            return answer({"data": {"viewer": viewer, "repository": {"pullRequest": pending}}})
        if "pullRequest(" in query:
            key = f"{variables['owner']}/{variables['name']}#{variables['number']}"
            node = data["prs"].get(key)
            pull = None if node is None else {**node["node"], "headRefOid": head(key)}
            return answer({"data": {"viewer": viewer, "repository": {"pullRequest": pull, **data["repo"]}}})
        return None

    def write():
        kind = WRITE_KINDS.get(args[3].rsplit("/", 1)[-1], "state")
        time.sleep(data.get("slow", {}).get(kind, 0))
        if refuse(kind):
            return 1
        if kind == "merge_async":  # GitHub's asynchronous merge: accepted, pending, with the id to poll
            pending = {
                "status": "pending",
                "details": {
                    "uuid": "u-1",
                    "merge_method": "squash",
                    "merge_action": "default",
                    "expected_head_sha": HEAD,
                    "message": "pending",
                },
            }
            return answer(data.get("async_put") or pending)
        return answer({"id": 999})

    if args[:2] == ["api", "graphql"]:
        status = graphql()
        if status is not None:
            return status
    if args[:3] == ["api", "--paginate", "user/orgs?per_page=100"]:
        for org in data["orgs"]:
            print(json.dumps(org))
        return 0
    if args[:2] == ["api", "--paginate"] and args[3:] == ["--jq", ".[] | tojson"]:
        repo_path, _, _query = args[2].partition("?")
        _repos, owner, name, _pulls, number, _files = repo_path.split("/")
        sys.stdout.reconfigure(encoding="utf-8")
        for item in data["prs"][f"{owner}/{name}#{number}"]["files"]:
            print(json.dumps(item, ensure_ascii=False))  # U+2028 unescaped, as jq's tojson may leave it
        return 0
    if (
        args[:2] == ["api", "--method"]
        and args[2] in ("POST", "PUT", "PATCH", "DELETE")
        and args[4:] == ["--input", "-"]
    ):
        return write()
    if len(args) == 2 and args[0] == "api" and "/merge-async/" in args[1]:  # one poll of an asynchronous merge
        polls = data.setdefault("async_polls", [])
        merged = {"status": "merged", "details": {"message": "merged"}}
        result = polls.pop(0) if len(polls) > 1 else (polls[0] if polls else merged)
        save(path, data)
        return answer(result)
    if len(args) == 2 and args[0] == "api" and "/compare/" in args[1]:
        return answer({"behind_by": 3, "ahead_by": 1})
    if len(args) == 2 and args[0] == "api" and "/pulls/" in args[1]:
        _repos, owner, name, _pulls, number = args[1].split("/")
        return answer({"head": {"sha": head(f"{owner}/{name}#{number}")}})
    print(f"fake gh: unexpected call {args}", file=sys.stderr)
    return 3


if __name__ == "__main__":
    sys.exit(fake_gh(sys.argv[1:]))
