# SPDX-FileCopyrightText: 2026 Cristiano Carvalho
# SPDX-License-Identifier: Apache-2.0
"""The GraphQL Morann sends to GitHub: the lists, one pull request, its state for the actions, and the mutations."""

from __future__ import annotations

VIEWER_QUERY = "query { viewer { login } }"


LIST_QUERY = """query($mine: String!, $review: String!, $first: Int!) {
  viewer { login }
  mine: search(query: $mine, type: ISSUE, first: $first) { issueCount nodes { ...row } }
  review: search(query: $review, type: ISSUE, first: $first) { issueCount nodes { ...row } }
}
fragment row on PullRequest {
  number title url isDraft reviewDecision createdAt updatedAt headRefName baseRefName headRefOid
  additions deletions changedFiles mergeable mergeStateStatus bodyText
  author { login __typename } repository { nameWithOwner } labels(first: 10) { nodes { name } }
  latestReviews(first: 20) { nodes { state author { login __typename } commit { oid } } }
  reviewRequests(first: 20) { nodes { requestedReviewer { __typename ... on User { login } ... on Team { slug } } } }
  comments { totalCount } reviews { totalCount }
  pending: reviews(states: PENDING, first: 1) { nodes { updatedAt comments { totalCount } } }
  timelineItems(itemTypes: [REVIEW_REQUESTED_EVENT], last: 10) { nodes { ... on ReviewRequestedEvent { createdAt
    requestedReviewer { __typename ... on User { login } ... on Team { slug } } } } }
  commits(last: 1) { nodes { commit { statusCheckRollup { state contexts {
    checkRunCountsByState { state count } statusContextCountsByState { state count } } } } } }
}"""


SCOPE_QUERY = """query($q: String!, $first: Int!, $after: String) {
  viewer { login }
  all: search(query: $q, type: ISSUE, first: $first, after: $after) {
    issueCount pageInfo { hasNextPage endCursor } nodes { ...row } }
}
fragment row on PullRequest {""" + LIST_QUERY.split("fragment row on PullRequest {", 1)[1]


PR_QUERY = """query($owner: String!, $name: String!, $number: Int!) {
  viewer { login }
  repository(owner: $owner, name: $name) { pullRequest(number: $number) {
    title body url isDraft state baseRefName headRefName headRefOid author { login } createdAt lastEditedAt
    mergeable mergeStateStatus reviewDecision
    reviewThreads(first: 100) { pageInfo { hasNextPage } nodes {
      id isResolved isOutdated path line originalLine diffSide
      hunk: comments(first: 1) { nodes { diffHunk } }
      comments(first: 100) { pageInfo { hasNextPage } nodes { databaseId state body createdAt lastEditedAt author { login } } } } }
    comments(first: 100) { pageInfo { hasNextPage } nodes { databaseId body createdAt lastEditedAt author { login } } }
    reviews(first: 100) { pageInfo { hasNextPage } nodes { databaseId state body submittedAt lastEditedAt author { login } } }
    latestReviews(first: 50) { nodes { state author { login __typename } commit { oid } } }
      reviewRequests(first: 50) { nodes { requestedReviewer { __typename ... on User { login } ... on Team { slug } } } }
    commits(last: 100) { totalCount nodes { commit { oid messageHeadline committedDate author { name user { login } } } } }
    headCommit: commits(last: 1) { nodes { commit { statusCheckRollup { contexts(first: 100) { nodes { __typename
      ... on CheckRun { databaseId name status conclusion title detailsUrl isRequired(pullRequestNumber: $number)
                        checkSuite { workflowRun { workflow { name } } } }
      ... on StatusContext { context state targetUrl description isRequired(pullRequestNumber: $number) } } } } } } }
  } }
}"""


STATE_QUERY = """query($owner: String!, $name: String!, $number: Int!) {
  viewer { login }
  repository(owner: $owner, name: $name) { mergeCommitAllowed squashMergeAllowed rebaseMergeAllowed autoMergeAllowed
    pullRequest(number: $number) { id state isDraft headRefOid baseRefName author { login } mergeable mergeStateStatus
      reviewDecision autoMergeRequest { enabledAt }
      baseRef { associatedPullRequests(states: OPEN, first: 1) { nodes { number } } }
      latestReviews(first: 50) { nodes { state author { login __typename } commit { oid } } }
      reviewRequests(first: 50) { nodes { requestedReviewer { __typename ... on User { login } ... on Team { slug } } } }
      headCommit: commits(last: 1) { nodes { commit { statusCheckRollup { state } } } } } }
}"""


READY = (
    "mutation($id: ID!) { markPullRequestReadyForReview(input: {pullRequestId: $id}) { pullRequest { id isDraft } } }"
)


TO_DRAFT = (
    "mutation($id: ID!) { convertPullRequestToDraft(input: {pullRequestId: $id}) { pullRequest { id isDraft } } }"
)


AUTO_ON = (
    "mutation($id: ID!, $method: PullRequestMergeMethod!, $head: GitObjectID) { enablePullRequestAutoMerge(input: "
    "{pullRequestId: $id, mergeMethod: $method, expectedHeadOid: $head}) { pullRequest { id } } }"
)


AUTO_OFF = "mutation($id: ID!) { disablePullRequestAutoMerge(input: {pullRequestId: $id}) { pullRequest { id } } }"


RESOLVE = "mutation($id: ID!) { resolveReviewThread(input: {threadId: $id}) { thread { id isResolved } } }"


UNRESOLVE = "mutation($id: ID!) { unresolveReviewThread(input: {threadId: $id}) { thread { id isResolved } } }"

# A file at a commit, to show the unchanged lines between a diff's hunks.

FILE_QUERY = """query($owner: String!, $name: String!, $expression: String!) {
  repository(owner: $owner, name: $name) { object(expression: $expression) { __typename
    ... on Blob { oid byteSize isBinary isTruncated text } } }
}"""
