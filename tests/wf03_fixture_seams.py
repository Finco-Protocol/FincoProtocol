"""Fixture-only seams for tests that predate the WF-03 lifecycle fences.

Production code can neither archive a project except through the lifecycle command (CAS + receipt) nor write a row whose owner differs from the
project's owner. Older tests set such states up with raw SQL. They now use:

* ``archive_through_lifecycle`` - the REAL ARCHIVE transition (version CAS, immutable receipt, ``USER_ACTION`` origin), so the project is archived
  exactly as a user would archive it; and
* ``foreign_row_forgery`` - a scoped, fixture-only window in which a cursor may forge a cross-owner/orphan row, purely to prove that reads and
  transactions refuse such a row. It uses the same connection-level disposal authority that ``app/demo_cleanup.py`` uses and is closed on exit.

Neither seam is importable by application code, and neither relaxes a production fence.
"""
from __future__ import annotations

import uuid
from contextlib import contextmanager


def archive_through_lifecycle(owner, project_code, *, request_id=None):
    """Archive ``project_code`` of ``owner`` through the real WF-03 transition at its current lifecycle version."""
    from app.persistence.db import get_cursor
    from app.persistence.project_lifecycle_repository import transition
    with get_cursor() as cur:
        row = cur.execute("SELECT lifecycle_version FROM projects WHERE user_id=? AND project_code=?", (owner, project_code)).fetchone()
    assert row is not None, (owner, project_code)
    return transition(owner, project_code, "ARCHIVE",
                      {"request_id": request_id or uuid.uuid4().hex, "expected_archived": False, "lifecycle_version": row[0]})


@contextmanager
def foreign_row_forgery(cursor):
    """Fixture-only: let ``cursor`` forge a row the WF-03 write fences refuse in production (cross-owner, orphan, archived-owner)."""
    connection = cursor.connection
    connection.create_function("wf03_terminal_disposal", 0, lambda: 1)
    try:
        yield cursor
    finally:
        connection.create_function("wf03_terminal_disposal", 0, lambda: 0)
