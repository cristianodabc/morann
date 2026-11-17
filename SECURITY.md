# Security

## Reporting a vulnerability

Report it privately: open the repository's Security tab and choose "Report a vulnerability". Do not open a public
issue for it.

Say what you found, how to reproduce it, the version or commit, and what an attacker gains. A maintainer answers
as soon as the report is read, usually within a week. A fix is released before the details are published, and you
are credited unless you ask not to be.

Only the latest release is supported.

## What Morann does with your account

- It holds no credential. Every read and write goes through the forge CLI you are already logged in with (`gh` for
  GitHub). Morann never sees, stores or logs a token.
- It posts nothing without an explicit confirmation. Comments, replies, resolves and the summary are local drafts
  until `y` in the review bar. A merge or a close takes `y` twice. What is sent is the plan the screen showed: its
  fingerprint is checked again right before sending, and the pull request's head is read again, so a pull request
  that moved gets nothing.
- `--read-only` refuses every write before the forge CLI runs.
- Pull request actions run only on your own pull requests: merge, update, close, reopen, draft, auto-merge and
  re-request review are refused on anyone else's.
- It opens only links to the forge's own host, built from checked parts. A link returned by the API, such as a
  check's details page on another site, is never opened.
- Drafts, the pull request cache and the UI state are plain files in your cache folder. Nothing else is written.
- Text from the forge is cleaned before it is drawn: control characters, bidirectional overrides and line
  separators show as `?`, so a pull request cannot hide code or drive the terminal.

A forge provider from another package runs with your account. Morann imports only the provider you select, so
install only one you trust.

## What counts

A way to make Morann post, merge or change something without the confirmation it shows, open a link outside the
forge's host, write outside its own folders, run a command it was not meant to, or let content from a pull request
change what the terminal shows beyond its own text.

## Dependencies

The runtime dependencies are pinned to exact versions with hashes in `requirements.txt`, and `install.sh` installs
wheels only, so nothing is built or run at install time. The tools the checks run with are pinned the same way in
`requirements-dev.txt`, and each GitHub Actions workflow pins its actions to a commit. A pin is raised only after
the new version is reviewed.

On every push CI scans the history for secrets (gitleaks), both locks for known vulnerabilities (pip-audit) and the
code for unsafe calls (bandit). CodeQL and a dependency review of each pull request run once the repository is
public.
