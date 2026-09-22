"""E1 configuration resolver for the equity fundamentals database.

Two env-vars govern the DB access:

  FINCO_EQUITY_FUNDAMENTALS_DB_PATH
    Absolute path to the equity_fundamentals.db file.
    Never inspected for a default; never auto-created.

  FINCO_EQUITY_FUNDAMENTALS_DB_MODE   (default: snapshot)
    snapshot — for a WAL-checkpointed standalone export/snapshot that will
               not change in place.  Opens with mode=ro&immutable=1.
               No WAL/SHM creation or source-directory write permission needed.
               Appropriate for: exported checkpointed DB, atomically replaced
               snapshot files, periodically produced read snapshots.

    live     — for a live WAL DB that an ingestion process may update.
               Opens with mode=ro only.  Standard WAL/SHM semantics are
               respected; the source directory must be writable by the
               SQLite runtime for SHM access.

The caller chooses the mode explicitly.  The implementation never silently
detects and switches modes.
"""
from __future__ import annotations

import os
from pathlib import Path

ENV_KEY = "FINCO_EQUITY_FUNDAMENTALS_DB_PATH"
ENV_KEY_MODE = "FINCO_EQUITY_FUNDAMENTALS_DB_MODE"

_VALID_MODES = frozenset({"snapshot", "live"})
_DEFAULT_MODE = "snapshot"


class EquityDBNotConfiguredError(RuntimeError):
    """Raised when FINCO_EQUITY_FUNDAMENTALS_DB_PATH is not set."""


class EquityDBNotFoundError(RuntimeError):
    """Raised when the configured DB path does not exist on disk."""


class EquityDBModeError(ValueError):
    """Raised when FINCO_EQUITY_FUNDAMENTALS_DB_MODE has an invalid value."""


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


def validate_db_mode(mode: str) -> str:
    """Normalize and validate a DB mode string.

    Normalizes to lowercase.  Accepts 'snapshot' and 'live' only.
    Raises EquityDBModeError for any other value.
    Never silently downgrades an unrecognised value to a valid mode.
    """
    normalized = mode.strip().lower()
    if normalized not in _VALID_MODES:
        raise EquityDBModeError(
            f"DB mode {mode!r} is invalid. "
            f"Must be one of: {sorted(_VALID_MODES)}"
        )
    return normalized


def resolve_db_mode() -> str:
    """Return the configured source mode ('snapshot' or 'live').

    Defaults to 'snapshot' when the env var is absent.
    Raises EquityDBModeError when set to an unrecognised value.
    """
    raw = os.environ.get(ENV_KEY_MODE, "").strip()
    if not raw:
        return _DEFAULT_MODE
    return validate_db_mode(raw)
