# Adding a forge

Morann ships with GitHub. This is how a provider for another forge, such as GitLab or Bitbucket, plugs in.

## How the code is split

```
 app, widgets, main_*          actions, drafts, views, lists
 (the terminal UI)             (plans, refusals, rows to draw)
        │                                   │
        └────────────┬──────────────────────┘
                     ▼
        forge.Forge  ·  models.*            the only way out
                     ▲
                     │ implements
        github.GitHubProvider ──▶ gh CLI ──▶ github.com
```

Nothing above the line imports `morann.github`. The UI and the logic call the `Forge` interface in
`src/morann/forge.py` and read the dataclasses in `src/morann/models.py`. A provider is one class that implements
that interface for one host.

## What to implement

Write a class with the members of `forge.Forge`. Its docstrings are the contract; `GitHubProvider` in
`src/morann/github/provider.py` is a complete example.

| Group | Members | Notes |
| --- | --- | --- |
| Identity | `name`, `label`, `host`, `capabilities`, `read_only`, `page_size`, `reader()` | `label` and `host` are used in messages. `reader()` returns the same forge with every write refused. |
| Viewer | `viewer_login()`, `organizations()` | |
| Lists | `list_pull_requests()`, `list_scope()` | Return `Lists` and `Page` of `PrRow`. |
| One pull request | `fetch_pr()`, `build_pr()`, `head_sha()` | See "Snapshots" below. |
| Review | `post_review()`, `post_reply()`, `resolve_thread()`, `post_comment()`, `post_line_comment()`, `edit_comment()`, `delete_comment()` | Each is one part of a confirmed plan, or one thing sent on its own after its own confirmation. |
| Pending review | `pending_review()`, `add_pending_comment()`, `add_pending_reply()`, `submit_pending_review()` | Only with `Capability.PENDING_REVIEW`; see below. |
| Actions | `read_state()`, `apply_action()`, `update_branch()`, `behind_by()` | |
| Links | `parse_ref()`, `pr_url()`, `file_url()`, `comment_url()`, `note_url()`, `commit_url()`, `checks_url()`, `owns_url()` | Build every link from checked parts, on `host`. |
| Files | `read_file()` | Returns `FileContent`: a file at a commit, to show the unchanged lines between hunks. |

Rules that hold for every method:

- Raise `forge.ForgeError` with one plain line when the host refuses or cannot be reached. Set `maybe_sent=True`
  when a write timed out, so Morann says it may have arrived instead of inviting a retry.
- Raise `settings.UsageError` for an argument that cannot be used.
- Refuse every write with `ForgeError` when the provider was made with `read_only=True`, before anything is sent.
- Never open or return a link outside `host`. `owns_url()` decides which links Morann may open.
- Store no credential. Use the forge's own CLI the user is logged in with, as GitHub does with `gh`, or the
  credential store that CLI uses.

### Models

Fill the dataclasses in `models.py` and nothing else crosses the line. The state fields use a fixed vocabulary
that the logic and the UI switch on. Map your forge's states onto it:

| Field | Values |
| --- | --- |
| `PrRow.decision`, `PullRequest.review_decision` | `APPROVED`, `CHANGES_REQUESTED`, `REVIEW_REQUIRED` or empty |
| `PrRow.checks`, `PrState.checks` | `SUCCESS`, `FAILURE`, `ERROR`, `PENDING`, `EXPECTED` or empty |
| `PrRow.pending` | `(comments, last change ISO time)` of the viewer's review started on the forge and not submitted, or `None`; it puts the row in the Pending tab |
| `PullRequest.pending` | a `PendingReview` (its id, comment count, summary, head and last change) of the viewer's own unsubmitted review, or `None`; never another person's |
| `mergeable` | `MERGEABLE`, `CONFLICTING`, `UNKNOWN` |
| `merge_state` | `CLEAN`, `BEHIND`, `BLOCKED`, `DIRTY`, `DRAFT`, `HAS_HOOKS`, `UNSTABLE`, `UNKNOWN` |
| `PullRequest.state`, `PrState.state` | `OPEN`, `CLOSED`, `MERGED` |
| `Reviewer.state`, `Note.state` | `APPROVED`, `CHANGES_REQUESTED`, `COMMENTED`, `DISMISSED`, `PENDING` |
| `Check.state` | `pass`, `fail`, `pending`, `skip`, `cancelled` |
| `Thread.side`, a comment's side | `RIGHT` for the new file, `LEFT` for the old one |
| `PrState.methods` | any of `merge`, `squash`, `rebase` |

Other points:

- A repository is `OWNER/REPO`: two plain segments, because the name becomes a path under the drafts folder. A
  forge with nested namespaces has to map them onto two segments.
- `PullRequest.forge` and `PrState.forge` are the provider that built them. Pass `self`. The views use it for
  links, and the plans use it for wording and capabilities. Writes never go through it.
- `File.lines` comes from `diffs.parse_patch()`, which reads a unified diff.
- Order `PullRequest.checks` with `models.order_checks()`.
- `PrState.stacked_on` is the number of the open pull request whose branch is this one's base, or `None`.

### Snapshots

`fetch_pr()` returns a snapshot: a JSON object holding whatever your provider needs to rebuild the pull request.
Morann writes it to the cache as it is and hands it back to `build_pr()`, so a reopened pull request shows at once.
Two rules:

- A whole snapshot has a `files` key that is not `None`. The snapshot passed to `on_conversation` has
  `"files": None`, and `build_pr()` then returns a pull request with `files_loading` set.
- `build_pr()` raises `ForgeError` for a snapshot it cannot read, for example one cached by an older version.

Read every file at one head commit. If the head moves while you read, read again.

## Declaring what the forge lacks

`capabilities` is a set of `forge.Capability`. Leave out what your forge cannot do:

| Capability | Without it |
| --- | --- |
| `REQUEST_CHANGES` | A request-changes review is refused when the plan is built. |
| `RESOLVE_THREADS` | A plan with resolve marks is refused. |
| `DRAFTS` | "Mark ready" and "convert to draft" show as unavailable. |
| `AUTO_MERGE` | The auto-merge actions show as unavailable. |
| `UPDATE_BRANCH` | "Update branch" and the bulk update show as unavailable. |
| `REREQUEST_REVIEW` | "Re-request review" shows as unavailable. |
| `ORGANIZATIONS` | The scope popup offers Mine and Personal only; `organizations()` is not called. |
| `SEARCH` | The All tab's filter narrows the loaded rows and does not search the forge. |
| `EDIT_COMMENTS` | Posted comments, review summaries and descriptions cannot be edited from Morann. Implement `edit_comment()` to offer it. |
| `DELETE_COMMENTS` | Posted comments cannot be deleted from Morann. Implement `delete_comment()` to offer it. |
| `SINGLE_COMMENTS` | A comment on a diff line can only go in a review: with no review on, `c` offers to start one and nothing else. Implement `post_line_comment()` to offer it. |
| `READ_FILES` | The unchanged lines between hunks stay folded: showing them reads the file at the head with `read_file()`. |
| `PENDING_REVIEW` | A review the viewer started and did not submit is not resumed: the plan posts a new review with `post_review()`, and the forge's own refusal of a second one is shown as a warning. Implement the four pending review members to offer it. |

An unavailable action is shown dimmed with the reason, for example "Bitbucket has no auto-merge", the same way an
action the forge refuses for one pull request is shown. A method behind a capability you left out is never called,
so it can raise `ForgeError`.

A pending review is the viewer's review that is started and not submitted. With `PENDING_REVIEW`, `build_pr()` fills
`PullRequest.pending` with it, and one confirmed submit calls `pending_review()` again, `add_pending_comment()` for each
comment, `add_pending_reply()` for each reply and `submit_pending_review()` once, instead of `post_review()` and
`post_reply()`. That happens only when the drafts hold review content (an inline comment, a reply, a summary or a
verdict other than comment); resolves and conversation comments alone never touch it. `pending_review()` returns the
viewer's own review only and `None` once it is gone, which stops the submit with the drafts kept. A forge without the
capability that is handed a resumed plan sends nothing and says so, naming the forge ("Bare has no resuming a pending
review").

Things that differ per repository are data, not capabilities: `PrState.methods` lists the merge methods the
repository allows, and `PrState.auto_merge_allowed` says whether it allows auto-merge.

## How a forge is selected

The name comes from, in order:

1. `MORANN_FORGE`
2. the `forge = NAME` line of `~/.config/morann/config`
3. `github`

`forge.select()` looks the name up among the providers and calls the class with `read_only=`.

A provider can live in this repository or in its own package:

- **In this repository**: add it to `BUILT_IN` in `src/morann/forge.py` as `"name": "module:Class"`.
- **In another package**: register an entry point in the `morann.forges` group. Installing the package beside
  Morann makes the name selectable. A built-in name cannot be replaced.

  ```toml
  [project.entry-points."morann.forges"]
  gitlab = "morann_gitlab:GitLabProvider"
  ```

Only the selected provider is imported. A provider runs with the user's account, so install only one you trust.

## Testing a provider

The tests never reach a real forge. For GitHub, a fake `gh` first on `PATH` (`tests/fake_gh.py`) answers from a
JSON fixture and logs every call, and the tests assert on that log: which calls were made, with which body, and
that nothing was sent when a plan was not confirmed. `tests/fake_github.py` holds the fixture and puts the fake in
place. Do the same for your forge's CLI or HTTP client. The cases worth covering:

- the lists, a page boundary and a search;
- one pull request read while its head moves;
- a review with comments, a reply, a resolve and a conversation comment, and a failure part way through;
- each action, a moved head, and a refused action;
- `read_only`: every write refused before anything is sent;
- links: every accepted and refused shape of a pull request reference.

## What still names GitHub

The pull request logic takes the forge's name from `label` and `host`. A few fixed texts in the UI still say
GitHub: the command line help and the built-in color themes named after github.com. The key help, the statusline
and the buttons already use `label`.
