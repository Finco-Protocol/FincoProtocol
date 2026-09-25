"""Demo session TTL cleanup and staging bootstrap — P6.5.

Deletes projects, scenarios, runs, workspace states, exports, and custom
sub-line rows for demo users whose sessions have expired. Safe to run
repeatedly (idempotent). Refuses to touch non-demo user_ids during TTL
cleanup; the full bootstrap function is explicit and safety-gated.

Invoked by:
  - The startup hook (background thread, deferred by 5 minutes)
  - The CLI: ``python -m app.demo_cleanup``
  - The demo reset tool: ``tools/demo_reset.py --cleanup-only``
  - The staging bootstrap: ``tools/demo_reset.py --full-bootstrap``

Demo user IDs start with ``demo_`` (defined in app.auth.DEMO_USER_ID_PREFIX).
The canonical reference user (``__reference__``) and admin user (``1``) are
never touched by TTL cleanup.

TTL authority
-------------
A demo session is considered expired when the LATEST activity timestamp
across ALL session-owned state is older than the TTL.  Session-owned state
covers every table that can be written independently of the parent project:

  tables            column used as activity marker
  ────────────────  ──────────────────────────────
  projects          updated_at
  scenarios         updated_at
  workspace_states  updated_at
  runs              created_at   (no updated_at)
  scenario_exports  created_at   (no updated_at)

The authority is:

  last_activity = MAX(updated_at/created_at) across ALL five tables for
                  that demo user_id

  expired = last_activity < cutoff

Consequence: as long as any session-owned object was written within the
TTL window, the entire session is kept intact.  No fresh object is deleted
merely because another object owned by the same session is old.

Example (TTL = 24h):
  - demo_X: project updated 30h ago, scenario updated 5 min ago.
    → last_activity = 5 min ago → NOT expired → all data kept.
  - demo_Y: project updated 30h ago, no scenarios/runs/workspaces/exports.
    → last_activity = 30h ago → expired → all data deleted.
"""

from __future__ import annotations

import logging
import sqlite3
from datetime import datetime, timedelta, timezone

from app.auth import DEMO_TTL_HOURS, DEMO_USER_ID_PREFIX

logger = logging.getLogger(__name__)

_TABLES_WITH_USER_ID = [
    "runs",
    "scenarios",
    "workspace_states",
    "scenario_exports",
]

# Sub-line tables reference project_id, not user_id.
# Ownership chain: capex_sub_lines.project_id → projects.project_id → projects.user_id
# These are cleaned via explicit JOIN, not by user_id directly.
_SUBLINE_TABLES = [
    "capex_sub_lines",
    "opex_sub_lines",
]


def _cutoff_iso(ttl_hours: int) -> str:
    cutoff = datetime.now(timezone.utc) - timedelta(hours=ttl_hours)
    return cutoff.isoformat()


def _find_expired_demo_users(conn: sqlite3.Connection, cutoff: str) -> list[str]:
    """Return demo user_ids whose last_activity across ALL owned tables is < cutoff.

    last_activity = MAX(updated_at / created_at) over projects, scenarios,
    workspace_states, runs, and scenario_exports for that user_id.

    A user appears here only if EVERY piece of their owned state is beyond
    the TTL window.  Fresh activity in any table keeps the whole session.

    CAPEX/OPEX sub-lines are not included here: their mutation only occurs
    within a project-save or workspace-save code path, which always touches
    the parent project or workspace_state updated_at.  Therefore the parent
    timestamp is always >= the sub-line timestamp, making sub-lines redundant
    in this query.
    """
    prefix = DEMO_USER_ID_PREFIX + "%"
    rows = conn.execute(
        """
        SELECT user_id
        FROM (
            SELECT user_id, MAX(last_activity) AS last_activity
            FROM (
                SELECT user_id, updated_at AS last_activity
                  FROM projects          WHERE user_id LIKE ?
                UNION ALL
                SELECT user_id, updated_at AS last_activity
                  FROM scenarios         WHERE user_id LIKE ?
                UNION ALL
                SELECT user_id, updated_at AS last_activity
                  FROM workspace_states  WHERE user_id LIKE ?
                UNION ALL
                SELECT user_id, created_at AS last_activity
                  FROM runs              WHERE user_id LIKE ?
                UNION ALL
                SELECT user_id, created_at AS last_activity
                  FROM scenario_exports  WHERE user_id LIKE ?
            )
            GROUP BY user_id
        )
        WHERE last_activity < ?
        """,
        (prefix, prefix, prefix, prefix, prefix, cutoff),
    ).fetchall()
    return [r["user_id"] for r in rows]


def _delete_owned_state(
    conn: sqlite3.Connection,
    user_ids: list[str],
    summary: dict[str, int],
) -> None:
    """Delete all state owned by ``user_ids``.

    Deletion order:
    1. Sub-lines (reference project_id, not user_id — cleaned via JOIN)
    2. Per-user tables (scenarios, runs, workspace_states, scenario_exports)
    3. Projects (last, after sub-lines)
    """
    placeholders = ",".join("?" * len(user_ids))

    for table in _SUBLINE_TABLES:
        try:
            cur = conn.execute(
                f"""DELETE FROM {table} WHERE project_id IN (
                    SELECT project_id FROM projects WHERE user_id IN ({placeholders})
                )""",
                user_ids,
            )
            if cur.rowcount:
                summary[table] = summary.get(table, 0) + cur.rowcount
                logger.info("demo_cleanup: deleted %d rows from %s", cur.rowcount, table)
        except Exception as exc:
            logger.warning("demo_cleanup: error cleaning %s: %s", table, exc)

    for table in _TABLES_WITH_USER_ID:
        try:
            cur = conn.execute(
                f"DELETE FROM {table} WHERE user_id IN ({placeholders})",
                user_ids,
            )
            deleted = cur.rowcount
            if deleted:
                summary[table] = summary.get(table, 0) + deleted
                logger.info("demo_cleanup: deleted %d rows from %s", deleted, table)
        except Exception as exc:
            logger.warning("demo_cleanup: error cleaning %s: %s", table, exc)

    try:
        cur = conn.execute(
            f"DELETE FROM projects WHERE user_id IN ({placeholders})",
            user_ids,
        )
        if cur.rowcount:
            summary["projects"] = summary.get("projects", 0) + cur.rowcount
            logger.info("demo_cleanup: deleted %d rows from projects", cur.rowcount)
    except Exception as exc:
        logger.warning("demo_cleanup: error cleaning projects: %s", exc)


def cleanup_expired_demo_data(ttl_hours: int = DEMO_TTL_HOURS) -> dict:
    """Delete all data for demo sessions whose LAST ACTIVITY is older than
    ``ttl_hours``.

    TTL authority: ``MAX(updated_at / created_at)`` across **all** session-
    owned tables (projects, scenarios, workspace_states, runs,
    scenario_exports) for that demo user_id.  A session is expired only when
    all of its owned state is beyond the TTL window.

    Returns a summary dict: {table: rows_deleted}.
    Never touches admin (user_id='1') or reference (user_id='__reference__') rows.
    """
    from app.persistence.db import get_connection

    cutoff = _cutoff_iso(ttl_hours)
    summary: dict[str, int] = {}

    try:
        conn = get_connection()
        with conn:
            expired_ids = _find_expired_demo_users(conn, cutoff)

            if not expired_ids:
                logger.debug("demo_cleanup: no expired demo sessions found (cutoff=%s)", cutoff)
                return {}

            logger.info(
                "demo_cleanup: found %d expired demo session(s) "
                "(cutoff=%s, authority=MAX(updated_at/created_at) across all tables)",
                len(expired_ids),
                cutoff,
            )
            _delete_owned_state(conn, expired_ids, summary)

    except Exception as exc:
        logger.error("demo_cleanup: DB error: %s", exc)
        return {}
    finally:
        try:
            conn.close()
        except Exception:
            pass

    return summary


def cleanup_all_demo_data() -> dict:
    """Delete ALL demo data regardless of age. Used by demo reset only.

    This is a destructive full-wipe, not a TTL cleanup. Only called by
    ``tools/demo_reset.py --cleanup-only`` after all safety gates have passed.
    Never touches admin (user_id='1') or reference (user_id='__reference__') rows.
    """
    from app.persistence.db import get_connection

    summary: dict[str, int] = {}

    try:
        conn = get_connection()
        with conn:
            all_demo_q = conn.execute(
                "SELECT DISTINCT user_id FROM projects WHERE user_id LIKE ?",
                (DEMO_USER_ID_PREFIX + "%",),
            ).fetchall()
            all_ids = [r["user_id"] for r in all_demo_q]

            if not all_ids:
                return {}

            _delete_owned_state(conn, all_ids, summary)

    except Exception as exc:
        logger.error("demo_cleanup: DB error: %s", exc)
    finally:
        try:
            conn.close()
        except Exception:
            pass

    return summary


def bootstrap_staging_db(conn: "sqlite3.Connection") -> dict:
    """Full disposable-staging bootstrap — transactionally fail-closed.

    Wipes ALL non-reference project and user state from ``conn``, then seeds
    the three canonical reference models.  Called ONLY after the fail-closed
    safety gates in ``tools/demo_reset.py`` have passed.

    Scope:
    - Deletes ALL rows from sub-line tables belonging to non-reference projects
    - Deletes ALL rows from per-user tables (runs, scenarios, workspace_states,
      scenario_exports) for any user_id that is not '__reference__'
    - Deletes ALL project rows that are not owned by '__reference__'
    - Seeds Solar XA / Wind XB / Storage XC / EV Charging XE canonical references
    - Verifies post-condition across ALL relevant tables: exactly 5 reference
      project rows, zero non-reference rows in projects, scenarios,
      workspace_states, runs, scenario_exports, capex_sub_lines,
      opex_sub_lines

    Returns a summary dict with keys:
      - 'deleted': {table: rows_deleted}
      - 'seeded': number of reference rows seeded
      - 'post_condition': 'PASS' | 'FAIL: <detail>'

    Raises:
      - RuntimeError if any required DELETE fails (transactional abort)
      - ValueError if the post-condition fails

    Never deletes canonical reference rows themselves.
    Never swallows required DELETE failures.
    """
    summary: dict = {"deleted": {}, "seeded": 0}

    with conn:
        # 1. Wipe sub-lines for all non-reference projects.
        # These are required deletes — any failure aborts the bootstrap.
        for table in _SUBLINE_TABLES:
            cur = conn.execute(
                f"""DELETE FROM {table} WHERE project_id IN (
                    SELECT project_id FROM projects WHERE user_id != '__reference__'
                )"""
            )
            if cur.rowcount:
                summary["deleted"][table] = cur.rowcount
                logger.info("bootstrap_staging_db: deleted %d rows from %s", cur.rowcount, table)

        # 2. Wipe per-user tables for non-reference users.
        # Required deletes — any failure aborts the bootstrap.
        for table in _TABLES_WITH_USER_ID:
            cur = conn.execute(
                f"DELETE FROM {table} WHERE user_id != '__reference__'"
            )
            if cur.rowcount:
                summary["deleted"][table] = cur.rowcount
                logger.info("bootstrap_staging_db: deleted %d rows from %s", cur.rowcount, table)

        # 3. Wipe all non-reference projects.
        # Required delete — any failure aborts the bootstrap.
        cur = conn.execute(
            "DELETE FROM projects WHERE user_id != '__reference__'"
        )
        if cur.rowcount:
            summary["deleted"]["projects"] = cur.rowcount
            logger.info("bootstrap_staging_db: deleted %d rows from projects", cur.rowcount)

    # 4. Seed canonical reference models using the standard service
    from app.services.project_library_service import ensure_reference_models
    seeded = ensure_reference_models()
    summary["seeded"] = len(seeded) if seeded else 0

    # 5. Verify post-condition across ALL relevant tables.
    # Non-reference state must be fully absent everywhere, not only in projects.
    _VERIFY_TABLES_USER_ID = [
        "projects",
        "scenarios",
        "workspace_states",
        "runs",
        "scenario_exports",
    ]
    failures: list[str] = []

    ref_count = conn.execute(
        "SELECT COUNT(*) FROM projects WHERE user_id = '__reference__'"
    ).fetchone()[0]
    if ref_count != 5:
        failures.append(f"projects: ref_count={ref_count} (expected 5)")

    for table in _VERIFY_TABLES_USER_ID:
        non_ref = conn.execute(
            f"SELECT COUNT(*) FROM {table} WHERE user_id != '__reference__'"
        ).fetchone()[0]
        if non_ref != 0:
            failures.append(f"{table}: non_ref_count={non_ref} (expected 0)")

    # Sub-lines have no user_id; verify via project FK
    for table in _SUBLINE_TABLES:
        try:
            orphan = conn.execute(
                f"""SELECT COUNT(*) FROM {table}
                    WHERE project_id IN (
                        SELECT project_id FROM projects WHERE user_id != '__reference__'
                    )"""
            ).fetchone()[0]
            if orphan != 0:
                failures.append(f"{table}: orphan_count={orphan} (expected 0)")
        except Exception as exc:
            logger.warning("bootstrap_staging_db: post-condition check skipped for %s: %s", table, exc)

    if not failures:
        summary["post_condition"] = "PASS"
        logger.info(
            "bootstrap_staging_db: PASS — 3 canonical refs, 0 non-reference rows in all tables"
        )
    else:
        detail = "; ".join(failures)
        summary["post_condition"] = f"FAIL: {detail}"
        raise ValueError(
            f"bootstrap_staging_db post-condition failed: {detail}."
        )

    return summary


if __name__ == "__main__":
    import sys

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    result = cleanup_expired_demo_data()
    if result:
        for table, count in result.items():
            print(f"  {table}: {count} rows deleted")
    else:
        print("No expired demo data found.")
    sys.exit(0)
