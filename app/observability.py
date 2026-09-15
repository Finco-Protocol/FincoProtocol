"""Phase 26D: Deployment / Observability — Runtime diagnostics helpers.

No financial model changes. No runtime calculations triggered.
Backend remains source of truth.

Secret redaction: FINCO_SECRET_KEY and FINCO_ADMIN_PASSWORD values
are never exposed in diagnostics output.
"""

import os
import sys
from pathlib import Path

# Sensitive environment variable names — never expose raw values
_SENSITIVE_ENVS = frozenset([
    "FINCO_SECRET_KEY",
    "FINCO_ADMIN_PASSWORD",
    "FINCO_ADMIN_PASSWORD_HASH",
    "FINCO_CSRF_SECRET",
])


def _is_sensitive_key(key: str) -> bool:
    """Return True if env var name is sensitive."""
    return key.upper() in _SENSITIVE_ENVS


def redact_config_value(value: str | None) -> str:
    """Redact a sensitive configuration value for diagnostics display."""
    if value is None:
        return "<not-set>"
    if not value or value == "None":
        return "<not-set>"
    if len(value) <= 4:
        return "****"
    return value[:2] + "****" + value[-2:]


def get_safe_config_summary() -> dict:
    """Return a summary of safe (non-secret) configuration for diagnostics.

    Sensitive keys (FINCO_SECRET_KEY, FINCO_ADMIN_PASSWORD, etc.) are redacted.
    No raw secret values are included in the output.
    """
    app_mode = os.getenv("FINCO_APP_MODE", "<not-set>")
    db_path = os.getenv("FINCO_DB_PATH", "<default>")
    backup_dir = os.getenv("FINCO_BACKUP_DIR", "<default>")
    auto_backup_enabled = os.getenv("FINCO_AUTO_BACKUP_ENABLED", "<not-set>")
    auto_backup_interval = os.getenv("FINCO_AUTO_BACKUP_INTERVAL_HOURS", "<not-set>")
    auto_backup_max_files = os.getenv("FINCO_AUTO_BACKUP_MAX_FILES", "<not-set>")

    return {
        "app_mode": app_mode,
        "db_path": db_path,
        "backup_dir": backup_dir,
        "auto_backup_enabled": auto_backup_enabled,
        "auto_backup_interval_hours": auto_backup_interval,
        "auto_backup_max_files": auto_backup_max_files,
    }


def get_app_health_status() -> dict:
    """Return a lightweight health status dictionary.

    Does NOT trigger model run. Does NOT access scenario data.
    Only checks: app import OK, config resolved, DB path accessible.

    Returns dict with keys:
        - status: "ok" | "degraded" | "error"
        - app_import: "ok" | "error"
        - app_mode: resolved mode string
        - db_reachable: bool
        - backup_dir_reachable: bool
        - diagnostics: safe config summary
    """
    health = {
        "status": "ok",
        "app_import": "ok",
        "app_mode": os.getenv("FINCO_APP_MODE", "<not-set>"),
        "db_reachable": False,
        "backup_dir_reachable": False,
        "diagnostics": get_safe_config_summary(),
    }

    # Check DB path reachability (not DB content — no query)
    db_path = os.getenv("FINCO_DB_PATH")
    if db_path:
        db_file = Path(db_path)
        db_dir = db_file.parent
        if db_dir.exists():
            health["db_reachable"] = True
        # DB file may not exist yet on fresh install — that's ok
    else:
        # Default path
        default_db = Path(__file__).parent.parent / "data" / "finco_runs.db"
        if default_db.parent.exists():
            health["db_reachable"] = True

    # Check backup directory reachability
    backup_dir = os.getenv("FINCO_BACKUP_DIR")
    if backup_dir:
        backup_path = Path(backup_dir)
        if backup_path.exists():
            health["backup_dir_reachable"] = True
    else:
        # Default path
        default_backup = Path(__file__).parent.parent / "data" / "backups" / "sqlite"
        if default_backup.exists():
            health["backup_dir_reachable"] = True

    # Degrade if backup dir is not reachable (but DB is ok)
    if not health["backup_dir_reachable"]:
        health["status"] = "degraded"

    return health


def get_runtime_diagnostics() -> dict:
    """Return lightweight runtime diagnostics for operational review.

    Safe for diagnostics: app mode, config summary, DB/backup reachability.
    Not included: scenario data, model outputs, secret values.
    """
    return {
        "health": get_app_health_status(),
        "safe_config": get_safe_config_summary(),
        "python_version": sys.version.split()[0],
    }
