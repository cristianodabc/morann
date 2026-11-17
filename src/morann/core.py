# SPDX-FileCopyrightText: 2026 Cristiano Carvalho
# SPDX-License-Identifier: Apache-2.0
"""Morann's logic without its UI: standard library only, so it runs and is tested without Textual.

It reads and writes a forge only through `morann.forge.Forge`, turns a pull request's patches into rows with real
file line numbers, keeps unsent comments, replies and resolves as local drafts, and posts them only through `submit`,
which needs the fingerprint of the exact plan the confirmation screen showed.

The code lives in modules by responsibility; this one names what the UI uses, so the UI keeps saying core.X. Nothing
here names a particular forge."""

from morann import attention  # noqa: F401 - the lists' attention flags, top bar counts and review waits
from morann.actions import (  # noqa: F401
    RISKY,
    action_menu,
    build_action,
    merge_view,
    run_action,
    run_updates,
    update_candidates,
    update_failed,
    update_fingerprint,
    why_not,
)
from morann.cache import PrCache  # noqa: F401
from morann.details import (  # noqa: F401
    PANEL_LINES,
    panel_lines,
    panel_title,
)
from morann.diffs import file_tree, parse_patch, tree_order  # noqa: F401
from morann.drafts import (  # noqa: F401
    EVENTS,
    VERDICT,
    DraftError,
    Drafts,
    DraftStore,
    HeadMoved,
    NotConfirmed,
    PlanError,
    SubmitError,
    build_plan,
    line_context,
    pending_review,
    submit,
)
from morann.forge import Capability, ForgeError, lacks, select  # noqa: F401
from morann.lists import (  # noqa: F401
    AUTHORS,
    LIST_TABS,
    GroupRow,
    Pending,
    by_author,
    group_rows,
    pending_rows,
    personal_repo,
    scope_label,
)
from morann.models import (  # noqa: F401
    MERGE_METHODS,
    Comment,
    DiffLine,
    File,
    Note,
    PrRow,
    Scope,
    Thread,
)
from morann.settings import (  # noqa: F401
    UsageError,
    check_owner,
    check_repo,
    config_path,
    default_owners,
    home,
)
from morann.textfmt import (  # noqa: F401
    ASCII,
    NERD,
    UNICODE,
    age,
    ago,
    cell_width,
    clean,
    cut,
    elapsed,
    hard_wrap,
    pick_icons,
    plain,
    trim_html,
    width_of,
    word_wrap,
)
from morann.uistate import State  # noqa: F401
from morann.views import (  # noqa: F401
    SPLIT_WIDTH,
    TABS,
    TWO_NUMBERS,
    TabLabel,
    ViewRow,
    check_rows,
    commit_rows,
    conversation_rows,
    diff_gutter,
    file_rows,
    list_columns,
    list_row_lines,
    merge_lines,
    number_width,
    split_rows,
    state_badge,
    tab_labels,
    thread_open,
    view_row_lines,
    visible,
)
