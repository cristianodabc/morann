# SPDX-FileCopyrightText: 2026 Cristiano Carvalho
# SPDX-License-Identifier: Apache-2.0
"""The list dashboard: the attention flag's priority, the top bar's counts, the review wait and its order, and in the
app the flag column, the group header count, the ! and b filters (key and click), the To Review waits and the
new-activity flag after a pull request was opened."""

from fake_github import NOW, FakeGitHub, fixture, pr_row, search_node, stamp
from morann import attention, core
from morann.github import parse
from support import make_app, pr_keys, settle


def test_attention_flags_counts_and_waits():
    everything = {
        "checks": "FAILURE",
        "decision": "CHANGES_REQUESTED",
        "merge_state": "DIRTY",
        "mergeable": "CONFLICTING",
    }
    steps = [
        ({}, "failing"),
        ({"checks": "ERROR"}, "failing"),
        ({"checks": "SUCCESS"}, "changes"),
        ({"decision": "APPROVED"}, "conflict"),
        ({"merge_state": "BEHIND", "mergeable": "MERGEABLE"}, "behind"),
        ({"merge_state": "CLEAN"}, ""),
    ]
    for change, expected in steps:  # each flag shows only when every one above it is gone
        everything.update(change)
        assert attention.flag(pr_row(**everything)) == expected, (everything, expected)
    quiet = pr_row(activity=3)
    assert attention.flag(quiet) == "" and attention.flag(quiet, ["h1", 3]) == ""  # never opened, or nothing new
    assert attention.flag(quiet, ["h0", 3]) == "new" and attention.flag(quiet, ["h1", 2]) == "new"
    assert attention.flag(pr_row(checks="FAILURE"), ["h0", 0]) == "failing"  # new activity is the lowest
    seen = attention.remember({"acme/app#1": ["h0", 0], "acme/app#2": ["x", 1]}, quiet)
    assert seen["acme/app#1"] == ["h1", 3] and list(seen)[-1] == "acme/app#1"
    many = {f"acme/app#{n}": ["h", 0] for n in range(attention.SEEN_LIMIT + 5)}
    assert len(attention.remember(many, quiet)) == attention.SEEN_LIMIT and "acme/app#1" in attention.remember(
        many, quiet
    )

    mine = [pr_row(1, checks="FAILURE"), pr_row(2)]
    review = [
        pr_row(3, merge_state="BEHIND"),
        pr_row(1, checks="FAILURE"),
    ]  # one pull request in both lists counts once
    parts = attention.summary(mine, review)
    assert parts == [(2, "mine", ""), (2, "to review", ""), (1, "behind", "behind"), (1, "failing", "failing")], parts
    assert attention.summary_text(parts) == "2 mine  2 to review  1 behind  1 failing"
    assert attention.summary_text(parts, narrow=True) == "2m 2r 1b 1f"
    assert attention.summary([pr_row(2)], []) == [(1, "mine", "")]  # zero parts are left out
    wide = attention.summary([], [], ([pr_row(4, checks="ERROR"), pr_row(5)], 40))
    assert wide == [(40, "open", ""), (1, "failing", "failing")], wide
    assert [r.number for r in mine + review if attention.matches(r, "failing")] == [1, 1]
    assert [r.number for r in review if attention.matches(r, "behind")] == [3]

    node = search_node(7)
    node.update(
        comments={"totalCount": 2},
        reviews={"totalCount": 1},
        timelineItems={
            "nodes": [
                {"createdAt": "2026-11-02T10:00:00Z", "requestedReviewer": {"__typename": "User", "login": "kim"}},
                {"createdAt": "2026-11-03T10:00:00Z", "requestedReviewer": {"__typename": "Team", "slug": "core"}},
                {"createdAt": "2026-11-04T10:00:00Z", "requestedReviewer": {"__typename": "User", "login": "me"}},
                {},
            ]
        },
    )
    parsed = parse.parse_rows([node])[0]
    assert parsed.activity == 3 and parsed.requested == (
        ("kim", "2026-11-02T10:00:00Z"),
        ("team:core", "2026-11-03T10:00:00Z"),
        ("me", "2026-11-04T10:00:00Z"),
    )
    assert attention.waiting_since(parsed, "me") == "2026-11-04T10:00:00Z"  # the latest request to me or my team
    assert attention.waiting_since(parsed, "bob") == "2026-11-03T10:00:00Z"  # a team's request, not kim's
    assert attention.waiting_since(pr_row(created="2026-11-01T10:00:00Z"), "me") == "2026-11-01T10:00:00Z"  # no request
    for ago, expected in (
        ({"hours": 3}, ("3h", "dim")),
        ({"days": 2}, ("2d", "dim")),
        ({"days": 3}, ("3d", "wait")),
        ({"days": 6}, ("6d", "bad")),
        ({"days": 21}, ("3w", "bad")),
    ):
        waited = pr_row(requested=(("me", stamp(**ago)),))
        assert attention.wait(waited, "me", NOW) == expected, (ago, attention.wait(waited, "me", NOW))
    old, new, flagged = (
        pr_row(1, requested=(("me", stamp(days=4)),)),
        pr_row(2, requested=(("me", stamp(hours=1)),)),
        pr_row(3, checks="FAILURE", requested=(("me", stamp(minutes=5)),)),
    )
    flags = {"acme/app#3": "failing"}
    assert [r.number for r in attention.order([new, flagged, old], flags, login="me", oldest_wait=True)] == [3, 1, 2]
    latest = [pr_row(1, updated="2026-11-01T00:00:00+00:00"), pr_row(2, updated="2026-11-06T00:00:00+00:00"), pr_row(3)]
    assert [r.number for r in attention.order(latest, {})] == [2, 3, 1]  # by latest update otherwise

    line = core.list_row_lines(pr_row(9, checks="FAILURE"), 80, flag="failing", wait=("6d", "bad"), now=NOW)[0]
    assert ("x ", "flag-failing") in line and (" 6d ", "bad") in line, line
    assert core.list_row_lines(pr_row(9), 80, flag="failing", icons=core.NERD, now=NOW)[0][1] == (" ", "flag-failing")
    groups = core.group_rows(
        [pr_row(1), pr_row(2, checks="FAILURE")],
        flags={"acme/app#2": "failing"},
        order=lambda members: attention.order(members, {"acme/app#2": "failing"}),
    )
    assert groups[0].flagged == 1 and [r.number for r in groups[1:]] == [2, 1]


def dashboard_fixture():
    """To Review: #7 asked of me 3 hours ago, #8 6 days ago and behind, #9 in acme/lib failing; Mine: #5."""

    def asked(node, when):
        node["timelineItems"] = {
            "nodes": [{"createdAt": when, "requestedReviewer": {"__typename": "User", "login": "me"}}]
        }
        return node

    data = fixture()
    eight = data["prs"]["acme/app#7"]  # readable, so it opens; the read keeps the list's merge state
    data["prs"]["acme/app#8"] = {**eight, "node": {**eight["node"], "mergeStateStatus": "BEHIND"}}
    data["search"]["review"] = [
        asked(search_node(7), stamp(hours=3)),
        asked({**search_node(8), "mergeStateStatus": "BEHIND"}, stamp(days=6)),
        search_node(9, repo="acme/lib", decision="CHANGES_REQUESTED", checks="FAILURE", author="kim"),
    ]
    return data


async def test_dashboard_in_the_app():
    with FakeGitHub(dashboard_fixture()) as github:
        tui = make_app(github)
        async with tui.run_test(size=(100, 40)) as pilot:
            await settle(pilot)
            main = tui.main
            listed = main.query_one("#list")

            def screen():
                return ["".join(s.text for s in strip) for strip in tui.screen._compositor.render_strips()]

            top = str(main.query_one("#topinfo").content)
            assert "1 mine  3 to review  1 behind (b)  1 failing (!)" in top, top  # each filter count names its key
            assert main.tab == "review" and pr_keys(listed) == ["acme/app#8", "acme/app#7", "acme/lib#9"], pr_keys(
                listed
            )  # flagged, oldest
            assert main.flags == {"acme/app#8": "behind", "acme/lib#9": "failing"}, main.flags
            assert main.waits["acme/app#8"] == ("6d", "bad") and main.waits["acme/app#7"] == ("3h", "dim"), main.waits
            heads = [r for r in listed.rows if isinstance(r, core.GroupRow)]
            assert [(g.repo, g.flagged) for g in heads] == [("acme/app", 1), ("acme/lib", 1)], heads
            lines = screen()
            assert any("acme/app  2 open  1 flagged" in line for line in lines), lines
            assert any("< #8" in line and " 6d " in line for line in lines), lines
            await pilot.press("!")  # failing only, and again everything
            await settle(pilot)
            assert pr_keys(listed) == ["acme/lib#9"] and main.attention_filter == "failing"
            await pilot.press("!")
            await settle(pilot)
            assert len(pr_keys(listed)) == 3 and not main.attention_filter
            await pilot.press("b")
            await settle(pilot)
            assert pr_keys(listed) == ["acme/app#8"]
            await pilot.press("b")
            await settle(pilot)
            info = main.query_one("#topinfo")
            offset = str(info.content).index("1 failing")  # a click on the count filters the same way
            await pilot.click("#topinfo", offset=(offset + 1, 0))
            await settle(pilot)
            assert pr_keys(listed) == ["acme/lib#9"], pr_keys(listed)
            await pilot.click("#topinfo", offset=(str(info.content).index("1 failing") + 1, 0))
            await settle(pilot)
            assert len(pr_keys(listed)) == 3
            await pilot.resize_terminal(70, 40)  # narrow: counts with one letter
            await settle(pilot)
            assert "1m 3r 1b 1f" in str(main.query_one("#topinfo").content), main.query_one("#topinfo").content
            await pilot.press("1")
            await settle(pilot)
            assert not main.waits  # the age column is the last update outside To Review
        assert core.State(github.dir / "state.json").get("seen", {}).get("acme/app#8") == ["", 0]  # opened: remembered

        data = github.data()  # new activity on #8, which was opened: a blue dot once the list is read again
        data["search"]["review"][1]["comments"] = {"totalCount": 2}
        data["search"]["review"][1]["mergeStateStatus"] = "CLEAN"
        github.write(data)
        again = make_app(github)
        async with again.run_test(size=(100, 40)) as pilot:
            await settle(pilot)
            assert again.main.tab == "mine"  # remembered; To Review's rows are not opened yet
            flags = again.main.attention_flags(again.main.lists.review)
            assert flags == {"acme/app#8": "new", "acme/lib#9": "failing"}, flags  # #7 was never opened: no baseline
            await pilot.press("3")
            await settle(pilot)
            assert again.main.query_one("#list").current().key == "acme/app#8"  # flagged first, so it opens and is seen
            assert core.State(github.dir / "state.json").get("seen")["acme/app#8"] == ["", 2]
            assert "acme/app#8" not in again.main.flags
