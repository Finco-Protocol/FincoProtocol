"""One-shot FINCO Yield background alert evaluation.

    python -m finco_yield.evaluate_alerts

    scheduler/timer
    -> enumerate users with canonical watchlist items
    -> THE existing per-user evaluator (the same function manual Refresh calls)
    -> THE existing alert store (deterministic ids, atomic checkpoints)
    -> existing in-app /crypto alert read model

No new economics, rule engine, watchlist, history, freshness or notification
code lives here: this is orchestration only.  There is no delivery of any
kind (no email / Telegram / Discord / push) and no infinite loop; scheduling
is external (systemd timer).  The command is disabled unless
``FINCO_YIELD_ALERT_AUTOMATION_ENABLED`` is truthy.

Environment (no secrets are read or printed):

    FINCO_YIELD_ALERT_AUTOMATION_ENABLED   1 to allow a run (default off)
    FINCO_YIELD_HISTORY_PATH               canonical history (required; the
                                           same variable web/collector use)
    FINCO_DB_PATH                          watchlist + alert DB (existing)
    FINCO_YIELD_ALERT_LOCK_PATH            optional lock file
                                           (default: <history path>.alerts-eval.lock)

Run status / exit codes (explicit, tested; mirrors the Y-LIVE collector):

    0   OK        every discovered user evaluated (or none have watchlists)
    2   FAILED    canonical inputs / watchlist unavailable, or every user failed
    3   PARTIAL   some users evaluated, some failed (failures are visible)
    4   DISABLED / CONFIG_ERROR   automation not enabled, or config invalid
    75  LOCKED    another evaluator run is active (matches ``flock -E 75``)

One evaluation instant is read once per run and shared by every user, so a
run is reproducible.  A failure for one user never touches another user's
checkpoints (each transition commits its alerts and checkpoint atomically in
the existing store).  Nothing unavailable is ever reported as success.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import sys
from typing import Any, Callable

from .flags import _TRUE

REPORT_SCHEMA = "YIELD_ALERT_EVALUATION_REPORT_V1"
EXIT_OK, EXIT_FAILED, EXIT_PARTIAL, EXIT_CONFIG, EXIT_LOCKED = 0, 2, 3, 4, 75


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _iso(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def user_ref(user_id: str) -> str:
    """Stable pseudonymous reference: failures are traceable by an operator
    who can hash a known id, but the raw identifier never enters the report."""
    return hashlib.sha256(str(user_id).encode("utf-8")).hexdigest()[:12]


def _report(status: str, code: int, started: datetime, finished: datetime, **extra: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "schema": REPORT_SCHEMA,
        "status": status,
        "exit_code": code,
        "started_at": _iso(started),
        "finished_at": _iso(finished),
        "evaluated_at": None,
        "users_discovered": 0,
        "users_evaluated": 0,
        "users_failed": 0,
        "alerts_created": 0,
        "failures": [],
        "reason": None,
    }
    body.update(extra)
    return body


def run_evaluation(
    *,
    now: Callable[[], datetime] = _utcnow,
    discover_users: Callable[[], list[str]] | None = None,
) -> dict[str, Any]:
    """Evaluate every canonical watchlist owner once; return the report."""
    from app.yield_alerts_gateway import YieldAlertsGateway
    from .watchlist import list_watchlist_user_ids

    started = now()
    evaluation_instant = now()                       # ONE instant for the whole run
    discover = discover_users or list_watchlist_user_ids

    # Canonical inputs resolved ONCE per run through the same resolver manual
    # Refresh uses.  Unavailable inputs are a FAILED run, never a quiet success.
    history_store, registry, reason = YieldAlertsGateway.resolve_inputs()
    if reason is not None:
        return _report("FAILED", EXIT_FAILED, started, now(), reason=reason,
                       evaluated_at=_iso(evaluation_instant))

    try:
        users = sorted(set(discover()))
    except (OSError, sqlite3.Error, ValueError, TypeError):
        return _report("FAILED", EXIT_FAILED, started, now(), reason="WATCHLIST_UNAVAILABLE",
                       evaluated_at=_iso(evaluation_instant))

    evaluated = 0
    created_total = 0
    failures: list[dict[str, str]] = []
    for user_id in users:
        try:
            outcome = YieldAlertsGateway.evaluate_user(
                user_id, history_store=history_store, registry=registry,
                now=evaluation_instant)
        except Exception:                            # never let one user stop the run
            failures.append({"user_ref": user_ref(user_id), "reason": "ALERT_EVALUATION_ERROR"})
            continue
        if outcome.available:
            evaluated += 1
            created_total += int(outcome.created_count or 0)
        else:
            failures.append({"user_ref": user_ref(user_id), "reason": str(outcome.reason)})

    if not users or not failures:
        status, code = "OK", EXIT_OK
    elif evaluated == 0:
        status, code = "FAILED", EXIT_FAILED
    else:
        status, code = "PARTIAL", EXIT_PARTIAL
    return _report(
        status, code, started, now(),
        evaluated_at=_iso(evaluation_instant),
        users_discovered=len(users), users_evaluated=evaluated,
        users_failed=len(failures), alerts_created=created_total,
        failures=failures,
        reason=None if not failures else "USER_EVALUATION_FAILURES",
    )


def _emit(report: dict[str, Any], out) -> None:
    out.write(json.dumps(report, sort_keys=True, separators=(",", ":")) + "\n")
    out.flush()


def _early(status: str, code: int, now: datetime, reason: str) -> dict[str, Any]:
    return _report(status, code, now, now, reason=reason)


def main(
    argv: list[str] | None = None,
    *,
    env: dict[str, str] | None = None,
    now: Callable[[], datetime] = _utcnow,
    out=None,
    discover_users: Callable[[], list[str]] | None = None,
) -> int:
    argparse.ArgumentParser(
        prog="python -m finco_yield.evaluate_alerts",
        description="One-shot FINCO Yield background alert evaluation (in-app alerts only).",
    ).parse_args(argv)
    env = dict(os.environ) if env is None else env
    out = out or sys.stdout

    if env.get("FINCO_YIELD_ALERT_AUTOMATION_ENABLED", "0").strip().lower() not in _TRUE:
        _emit(_early("DISABLED", EXIT_CONFIG, now(), "FINCO_YIELD_ALERT_AUTOMATION_ENABLED is not set"), out)
        return EXIT_CONFIG
    history_raw = env.get("FINCO_YIELD_HISTORY_PATH", "").strip()
    if not history_raw:
        _emit(_early("CONFIG_ERROR", EXIT_CONFIG, now(), "FINCO_YIELD_HISTORY_PATH is required"), out)
        return EXIT_CONFIG

    lock_raw = env.get("FINCO_YIELD_ALERT_LOCK_PATH", "").strip()
    lock_path = Path(lock_raw) if lock_raw else Path(history_raw + ".alerts-eval.lock")
    try:
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        lock = open(lock_path, "a+")
    except OSError:
        _emit(_early("CONFIG_ERROR", EXIT_CONFIG, now(), "lock directory is not writable"), out)
        return EXIT_CONFIG
    try:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            _emit(_early("LOCKED", EXIT_LOCKED, now(), "another evaluator run is active"), out)
            return EXIT_LOCKED
        # The canonical stores (watchlist, alerts, history) read FINCO_DB_PATH /
        # FINCO_YIELD_HISTORY_PATH from the process environment, which is what
        # ``env`` defaults to; this runner never mutates the environment.
        report = run_evaluation(now=now, discover_users=discover_users)
        _emit(report, out)
        return int(report["exit_code"])
    finally:
        lock.close()


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
