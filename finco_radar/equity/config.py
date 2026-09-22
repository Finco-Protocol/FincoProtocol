"""E1 configuration resolver for the equity fundamentals database.

The DB path is resolved exclusively from the environment variable
FINCO_EQUITY_FUNDAMENTALS_DB_PATH.  The application never inspects
machine-specific default paths and never creates the file.
"""
from __future__ import annotations

import os
from pathlib import Path

ENV_KEY = "FINCO_EQUITY_FUNDAMENTALS_DB_PATH"


class EquityDBNotConfiguredError(RuntimeError):
    """Raised when FINCO_EQUITY_FUNDAMENTALS_DB_PATH is not set."""


class EquityDBNotFoundError(RuntimeError):
    """Raised when the configured DB path does not exist on disk."""


def resolve_db_path() -> Path:
    """Return the configured equity fundamentals DB path.

    Raises EquityDBNotConfiguredError if the env var is absent or empty.
    Raises EquityDBNotFoundError if the configured path does not exist.
    Never creates the file; never falls back to a default path.
    """
    raw = os.environ.get(ENV_KEY, "").strip()
    if not raw:
        raise EquityDBNotConfiguredError(
            f"{ENV_KEY} is not set. "
            "Configure it to the absolute path of equity_fundamentals.db."
        )
    p = Path(raw)
    if not p.exists():
        raise EquityDBNotFoundError(
            f"Equity fundamentals DB not found at configured path: {p}"
        )
    return p
