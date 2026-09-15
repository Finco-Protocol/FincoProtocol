"""Demo session TTL cleanup — P6.5.

Deletes projects, scenarios, runs, workspace states, exports, and custom
sub-line rows for demo users whose sessions have expired. Safe to run
repeatedly (idempotent). Refuses to touch non-demo user_ids.

Invoked by:
  - The startup hook (background thread, deferred by 5 minutes)
  - The CLI: ``python -m app.demo_cleanup``
  - The demo reset tool: ``tools/demo_reset.py --cleanup-only``

Demo user IDs start with ``demo_`` (defined in app.auth.DEMO_USER_ID_PREFIX).
The canonical reference user (``__reference__``) and admin user (``1``) are
never touched.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone

from app.auth import DEMO_TTL_HOURS, DEMO_USER_ID_PREFIX

logger = logging.getLogger(__name__)

_TABLES_WITH_USER_ID = [
    "runs",
    "scenarios",
    "workspace_states",
    "scenario_exports",
]

# Sub-line tables reference project_id, not user_id — cleaned up via project cascade
# after projects rows are deleted (if FK cascade is enabled) or via explicit join.
_SUBLINE_TABLES = [
    "capex_sub_lines",
    "opex_sub_lines",
]


def _cutoff_iso(ttl_hours: int) -> str:
    cutoff = datetime.now(timezone.utc) - timedelta(hours=ttl_hours)
    return cutoff.isoformat()


def cleanup_expired_demo_data(ttl_hours: int = DEMO_TTL_HOURS) -> dict:
    """Delete all data for demo sessions older than ``ttl_hours``.

    Returns a summary dict: {table: rows_deleted}.
    Never touches admin or reference users.
    """
    from app.persistence.db import get_connection

    cutoff = _cutoff_iso(ttl_hours)
    summary: dict[str, int] = {}

    try:
        conn = get_connection()
        with conn:
            # Find expired demo user_ids (based on their oldest project/run created_at)
            # We use the projects table as the authoritative source; users without
            # any project are not tracked and have no data to clean up.
            expired_users_q = conn.execute(
                """
                SELECT DISTINCT user_id FROM projects
                WHERE user_id LIKE ?
                  AND created_at < ?
                """,
                (DEMO_USER_ID_PREFIX + "%", cutoff),
            ).fetchall()
            expired_ids = [r["user_id"] for r in expired_users_q]

            if not expired_ids:
                logger.debug("demo_cleanup: no expired demo sessions found (cutoff=%s)", cutoff)
                return {}

            logger.info(
                "demo_cleanup: found %d expired demo session(s) (cutoff=%s)",
                len(expired_ids),
                cutoff,
            )

            placeholders = ",".join("?" * len(expired_ids))

            # Clean sub-lines first (reference project_id, not user_id)
            for table in _SUBLINE_TABLES:
                try:
                    cur = conn.execute(
                        f"""DELETE FROM {table} WHERE project_id IN (
                            SELECT project_id FROM projects
                            WHERE user_id IN ({placeholders})
                        )""",
                        expired_ids,
                    )
                    if cur.rowcount:
                        summary[table] = cur.rowcount
                        logger.info("demo_cleanup: deleted %d rows from %s", cur.rowcount, table)
                except Exception as exc:
                    logger.warning("demo_cleanup: error cleaning %s: %s", table, exc)

            # Clean tables scoped by user_id
            for table in _TABLES_WITH_USER_ID:
                try:
                    cur = conn.execute(
                        f"DELETE FROM {table} WHERE user_id IN ({placeholders})",
                        expired_ids,
                    )
                    deleted = cur.rowcount
                    if deleted:
                        summary[table] = deleted
                        logger.info("demo_cleanup: deleted %d rows from %s", deleted, table)
                except Exception as exc:
                    logger.warning("demo_cleanup: error cleaning %s: %s", table, exc)

            # Delete projects last (after sub-lines)
            try:
                cur = conn.execute(
                    f"DELETE FROM projects WHERE user_id IN ({placeholders})",
                    expired_ids,
                )
                if cur.rowcount:
                    summary["projects"] = cur.rowcount
                    logger.info("demo_cleanup: deleted %d rows from projects", cur.rowcount)
            except Exception as exc:
                logger.warning("demo_cleanup: error cleaning projects: %s", exc)

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
    """Delete ALL demo data regardless of age. Used by demo reset only."""
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

            placeholders = ",".join("?" * len(all_ids))

            for table in _SUBLINE_TABLES:
                try:
                    cur = conn.execute(
                        f"""DELETE FROM {table} WHERE project_id IN (
                            SELECT project_id FROM projects
                            WHERE user_id IN ({placeholders})
                        )""",
                        all_ids,
                    )
                    if cur.rowcount:
                        summary[table] = cur.rowcount
                except Exception as exc:
                    logger.warning("demo_cleanup: error cleaning %s: %s", table, exc)

            for table in _TABLES_WITH_USER_ID:
                try:
                    cur = conn.execute(
                        f"DELETE FROM {table} WHERE user_id IN ({placeholders})",
                        all_ids,
                    )
                    if cur.rowcount:
                        summary[table] = cur.rowcount
                except Exception as exc:
                    logger.warning("demo_cleanup: error cleaning %s: %s", table, exc)

            try:
                cur = conn.execute(
                    f"DELETE FROM projects WHERE user_id IN ({placeholders})",
                    all_ids,
                )
                if cur.rowcount:
                    summary["projects"] = cur.rowcount
            except Exception as exc:
                logger.warning("demo_cleanup: error cleaning projects: %s", exc)

    except Exception as exc:
        logger.error("demo_cleanup: DB error: %s", exc)
    finally:
        try:
            conn.close()
        except Exception:
            pass

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
