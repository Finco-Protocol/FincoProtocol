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

TTL authority
-------------
A demo session is considered expired when the LATEST ``updated_at`` timestamp
across ALL project rows owned by that ``demo_*`` user_id is older than the TTL.
This is a conservative, activity-based rule:

  expired = MAX(updated_at for all projects owned by user) < cutoff

Consequence: as long as any project belonging to a demo session was updated
(or created) within the TTL window, the entire session is kept intact.
No fresh object is deleted merely because another object owned by the same
session is old.

Example (TTL = 24h):
  - User demo_X has Project A (updated 25h ago) and Project B (updated 2h ago).
  - MAX(updated_at) = 2h ago < cutoff? No → demo_X is NOT expired → all data kept.
  - User demo_Y has Project C (updated 30h ago) and no other projects.
  - MAX(updated_at) = 30h ago < cutoff? Yes → demo_Y is expired → all data deleted.
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


def cleanup_expired_demo_data(ttl_hours: int = DEMO_TTL_HOURS) -> dict:
    """Delete all data for demo sessions whose LATEST project activity is older
    than ``ttl_hours``.

    TTL authority: ``MAX(updated_at)`` across all project rows for that
    demo user_id. A session is expired only when its most-recently-updated
    project is beyond the TTL window. No fresh session-owned object is deleted
    merely because another object in the same session is old.

    Returns a summary dict: {table: rows_deleted}.
    Never touches admin (user_id='1') or reference (user_id='__reference__') rows.
    """
    from app.persistence.db import get_connection

    cutoff = _cutoff_iso(ttl_hours)
    summary: dict[str, int] = {}

    try:
        conn = get_connection()
        with conn:
            # Find demo user_ids whose LATEST project activity is before cutoff.
            # Using MAX(updated_at): as long as any project is fresh, the whole
            # session is kept. This is the activity-based TTL authority.
            expired_users_q = conn.execute(
                """
                SELECT user_id
                FROM projects
                WHERE user_id LIKE ?
                GROUP BY user_id
                HAVING MAX(updated_at) < ?
                """,
                (DEMO_USER_ID_PREFIX + "%", cutoff),
            ).fetchall()
            expired_ids = [r["user_id"] for r in expired_users_q]

            if not expired_ids:
                logger.debug("demo_cleanup: no expired demo sessions found (cutoff=%s)", cutoff)
                return {}

            logger.info(
                "demo_cleanup: found %d expired demo session(s) (cutoff=%s, authority=MAX(updated_at))",
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
    """Delete ALL demo data regardless of age. Used by demo reset only.

    This is a destructive full-wipe, not a TTL cleanup. Only called by
    ``tools/demo_reset.py`` after all safety gates have passed.
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
