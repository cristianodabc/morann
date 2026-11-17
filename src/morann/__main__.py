# SPDX-FileCopyrightText: 2026 Cristiano Carvalho
# SPDX-License-Identifier: Apache-2.0
"""`python -m morann`, and the file the `mor` launcher runs."""

import sys
from pathlib import Path

if not __package__:  # run as a file by bin/mor under python -I, which leaves the checkout's src folder off the path
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from morann.cli import main  # noqa: E402 - after the path is set

sys.exit(main())
