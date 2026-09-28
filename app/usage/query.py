"""B2.3 Usage/Metering — read-only usage summary queries.

Returns aggregated UsageSummary records for the authenticated subject.
No billing/pricing engine in V1. No fiat or token prices.
User isolation: queries are always scoped to the authenticated subject_id.
"""
from __future__ import annotations

from datetime import datetime
from typing import Sequence

from app.usage.contracts import (
    ALL_FEATURE_KEYS,
    UsageSummary,
)


class UsageQueryService:
    """Read-only query surface over the usage_events table.

    All queries are strictly scoped to the authenticated subject_id.
    No cross-user reads are possible through this interface.
    """

    def __init__(self, db_path: str | None = None) -> None:
        self._db_path = db_path

    def _get_conn(self):
        if self._db_path is not None:
            import sqlite3
            conn = sqlite3.connect(self._db_path, timeout=30.0, isolation_level=None)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL")
            return conn
        from app.persistence.db import get_connection
        return get_connection()

    def summaries_for_subject(
        self,
        *,
        subject_id: str,
        feature_key: str | None = None,
        period_start: datetime | None = None,
        period_end: datetime | None = None,
    ) -> list[UsageSummary]:
        """Return usage summaries grouped by feature_key for this subject only.

        Never returns data for any other subject_id. Optionally filtered by
        feature_key and/or time period.
        """
        if not subject_id:
            raise ValueError("subject_id is required")
        if feature_key is not None and feature_key not in ALL_FEATURE_KEYS:
            raise ValueError(f"unknown feature_key: {feature_key!r}")

        params: list = [subject_id]
        where = "subject_id = ?"

        if feature_key is not None:
            where += " AND feature_key = ?"
            params.append(feature_key)
        if period_start is not None:
            if period_start.tzinfo is None or period_start.utcoffset() is None:
                raise ValueError("period_start must be timezone-aware")
            where += " AND occurred_at >= ?"
            params.append(period_start.isoformat())
        if period_end is not None:
            if period_end.tzinfo is None or period_end.utcoffset() is None:
                raise ValueError("period_end must be timezone-aware")
            where += " AND occurred_at <= ?"
            params.append(period_end.isoformat())

        sql = f"""
            SELECT feature_key,
                   SUM(quantity) AS total_quantity,
                   COUNT(*)      AS event_count
              FROM usage_events
             WHERE {where}
             GROUP BY feature_key
             ORDER BY feature_key
        """
        conn = self._get_conn()
        try:
            rows = conn.execute(sql, params).fetchall()
        except Exception:
            conn.close()
            return []
        conn.close()

        return [
            UsageSummary(
                subject_id=subject_id,
                feature_key=row["feature_key"],
                total_quantity=row["total_quantity"],
                event_count=row["event_count"],
                period_start=period_start,
                period_end=period_end,
            )
            for row in rows
        ]
