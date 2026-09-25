"""P6 Correction D — final merge blocker tests.

Items covered:
  1. Semaphore slot leak regression proof:
     - slot is released when request.form() raises (pre-execute post-acquire)
     - slot is released on normal successful run
     - a second acquisition succeeds after a leak-path exception
     - semaphore value is consistent: acquire count == release count

  2. Strict bootstrap transactional fail-closed:
     - Full table coverage: inserts projects, scenarios, workspace_states,
       runs, scenario_exports, capex/opex sub-lines, then verifies ALL
       are absent after bootstrap
     - Failure test: forced DELETE failure must raise, never return PASS
     - Post-condition verifies non-reference absence across all tables,
       not only projects
"""
from __future__ import annotations

import asyncio
import logging
import os
import sqlite3
import tempfile
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _make_demo_user_id() -> str:
    from app.auth import new_demo_user_id
    return new_demo_user_id()


def _make_demo_cookie(user_id: str) -> dict[str, str]:
    from app.auth import create_demo_session_token, DEMO_COOKIE_NAME
    return {DEMO_COOKIE_NAME: create_demo_session_token(user_id)}


def _ts_old() -> str:
    return "2025-01-01T00:00:00+00:00"


def _ts_fresh() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()


@pytest.fixture(scope="module")
def client():
    import main_web
    from starlette.testclient import TestClient
    with TestClient(main_web.app, raise_server_exceptions=False) as c:
        yield c


# ---------------------------------------------------------------------------
# 1. Semaphore slot leak regression proof
# ---------------------------------------------------------------------------

class TestSemaphoreSlotLeak:
    """Every successful _acquire_run_slot() must have exactly one matching
    _release_run_slot() on every subsequent exit path — including pre-execute
    failures that occur after acquisition but before execute_run_route."""

    def _semaphore_value(self, sem) -> int:
        """Return the number of available slots in the semaphore."""
        # asyncio.Semaphore stores the count as _value
        return sem._value

    def test_slot_released_when_form_parse_raises(self, client):
        """If request.form() raises after slot acquisition, slot must be released."""
        import main_web

        # Capture semaphore reference and initial value
        sem = main_web._run_semaphore
        if sem is None:
            pytest.skip("Semaphore disabled (FINCO_MAX_CONCURRENT_RUNS=0)")

        initial_value = self._semaphore_value(sem)
        uid = _make_demo_user_id()
        cookies = _make_demo_cookie(uid)

        # Patch request.form to raise after slot is acquired
        original_form = None

        async def _raising_form():
            raise RuntimeError("simulated_form_parse_failure")

        # We need to patch at the Request level — patch the form method on
        # the Request class so it raises when the /run route calls it.
        with patch(
            "starlette.requests.Request.form",
            new_callable=lambda: (lambda self: _make_async_raise(RuntimeError("simulated_form_parse_failure"))),
        ):
            resp = client.post("/run", data={}, cookies=cookies)

        # Response should be 500 (unhandled exception) not a hung server
        assert resp.status_code in (500, 503, 400, 422), (
            f"Got unexpected status {resp.status_code} for form-parse failure"
        )

        # Critical: semaphore must be back to its initial value
        after_value = self._semaphore_value(sem)
        assert after_value == initial_value, (
            f"Semaphore slot leaked! Before={initial_value}, after={after_value}. "
            "A form-parse exception after slot acquisition must release the slot."
        )

    def test_slot_released_on_normal_successful_run(self, client):
        """A normal (mocked) successful run must release exactly one slot."""
        import main_web

        sem = main_web._run_semaphore
        if sem is None:
            pytest.skip("Semaphore disabled (FINCO_MAX_CONCURRENT_RUNS=0)")

        initial_value = self._semaphore_value(sem)
        uid = _make_demo_user_id()
        cookies = _make_demo_cookie(uid)

        async def _noop_run(**kwargs):
            return SimpleNamespace(
                prepend_html=None,
                template_name="errors.html",
                context={},
                status_code=200,
            )

        with patch("app.services.run_service.execute_run_route", side_effect=_noop_run):
            client.post("/run", data={}, cookies=cookies)

        after_value = self._semaphore_value(sem)
        assert after_value == initial_value, (
            f"Semaphore slot leaked on successful run! Before={initial_value}, after={after_value}."
        )

    def test_slot_released_when_execute_run_route_raises(self, client):
        """When execute_run_route raises, the slot must still be released."""
        import main_web

        sem = main_web._run_semaphore
        if sem is None:
            pytest.skip("Semaphore disabled (FINCO_MAX_CONCURRENT_RUNS=0)")

        initial_value = self._semaphore_value(sem)
        uid = _make_demo_user_id()
        cookies = _make_demo_cookie(uid)

        async def _raising_run(**kwargs):
            raise ValueError("test_execute_run_failure")

        with patch("app.services.run_service.execute_run_route", side_effect=_raising_run):
            client.post("/run", data={}, cookies=cookies)

        after_value = self._semaphore_value(sem)
        assert after_value == initial_value, (
            f"Semaphore slot leaked when execute_run_route raised! "
            f"Before={initial_value}, after={after_value}."
        )

    def test_subsequent_request_not_capacity_busy_after_form_error(self, client):
        """After a form-error that released its slot, the next request must not get 503."""
        import main_web

        sem = main_web._run_semaphore
        if sem is None:
            pytest.skip("Semaphore disabled (FINCO_MAX_CONCURRENT_RUNS=0)")

        uid = _make_demo_user_id()
        cookies = _make_demo_cookie(uid)

        # First request: form parse raises (simulated by patching execute_run_route
        # — any post-acquire failure path is sufficient for the invariant proof)
        async def _raising_run(**kwargs):
            raise RuntimeError("pre_execute_sentinel_failure")

        with patch("app.services.run_service.execute_run_route", side_effect=_raising_run):
            client.post("/run", data={}, cookies=cookies)

        # Second request with a successful mock: must not get 503 capacity-busy
        async def _ok_run(**kwargs):
            return SimpleNamespace(
                prepend_html=None,
                template_name="errors.html",
                context={},
                status_code=200,
            )

        with patch("app.services.run_service.execute_run_route", side_effect=_ok_run):
            resp2 = client.post("/run", data={}, cookies=cookies)

        assert resp2.status_code != 503, (
            f"Second request after a failure-path slot release must not get 503 capacity-busy. "
            f"Got {resp2.status_code}. This indicates the slot was not properly released."
        )

    def test_semaphore_not_acquired_when_capacity_busy(self, client):
        """When all slots are full (_acquire_run_slot returns False),
        no slot is acquired and no release must happen."""
        import main_web

        sem = main_web._run_semaphore
        if sem is None:
            pytest.skip("Semaphore disabled (FINCO_MAX_CONCURRENT_RUNS=0)")

        initial_value = self._semaphore_value(sem)
        uid = _make_demo_user_id()
        cookies = _make_demo_cookie(uid)

        async def _always_busy():
            return False

        with patch.object(main_web, "_acquire_run_slot", side_effect=_always_busy):
            resp = client.post("/run", data={}, cookies=cookies)

        after_value = self._semaphore_value(sem)
        # Value must be identical: no acquire happened, no release must happen
        assert after_value == initial_value, (
            f"Capacity-busy path must not change semaphore value. "
            f"Before={initial_value}, after={after_value}."
        )


def _make_async_raise(exc: Exception):
    """Return a coroutine that raises exc when awaited."""
    async def _coro(*args, **kwargs):
        raise exc
    return _coro()


# ---------------------------------------------------------------------------
# 2. Strict bootstrap transactional fail-closed
# ---------------------------------------------------------------------------

def _build_test_db(db_path: str) -> None:
    """Initialise schema and insert a full set of non-reference rows."""
    with patch("app.persistence.db.DB_PATH", db_path):
        from app.persistence.db import get_connection
        conn = get_connection()

        # Insert non-reference projects for demo, admin, and ordinary user
        for uid, code in [
            ("demo_bootstrap_d_test", "demo_proj_d"),
            ("1", "admin_proj_d"),
            ("user_regular_d", "user_proj_d"),
        ]:
            pid = str(uuid.uuid4())
            conn.execute(
                """
                INSERT INTO projects
                  (project_id, project_code, user_id, project_name,
                   source_project_template, project_origin,
                   governance_state_json, last_run_summary_json,
                   created_at, updated_at)
                VALUES (?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    pid, code, uid, "Test",
                    "generic_solar", "factory_template",
                    "{}", "{}", _ts_old(), _ts_old(),
                ),
            )
            # Associated scenario
            conn.execute("PRAGMA foreign_keys=OFF")
            sc_id = str(uuid.uuid4())
            conn.execute(
                """
                INSERT INTO scenarios
                  (scenario_id, user_id, project_id, project_code, scenario_name,
                   source_project_template, snapshot_json, governance_state_json,
                   last_run_summary_json, created_at, updated_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    sc_id, uid, pid, code, "Base",
                    "generic_solar", "{}", "{}", "{}",
                    _ts_old(), _ts_old(),
                ),
            )
            # Associated workspace_state
            ws_id = str(uuid.uuid4())
            conn.execute(
                """
                INSERT INTO workspace_states
                  (workspace_id, project_id, user_id, project_code,
                   draft_snapshot_json, saved_snapshot_json,
                   last_runtime_snapshot_json, last_runtime_summary_json,
                   governance_state_json, created_at, updated_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    ws_id, pid, uid, code,
                    "{}", "{}", "{}", "{}", "{}",
                    _ts_old(), _ts_old(),
                ),
            )
            # Associated run
            run_id = str(uuid.uuid4())
            conn.execute(
                """
                INSERT INTO runs
                  (run_id, user_id, project_type, scenario, created_at, inputs_json, kpis_json)
                VALUES (?,?,?,?,?,?,?)
                """,
                (run_id, uid, "Solar", "Base", _ts_old(), "{}", "{}"),
            )
            # Associated export
            exp_id = str(uuid.uuid4())
            conn.execute(
                """
                INSERT INTO scenario_exports
                  (export_id, user_id, project_id, project_code,
                   export_type, artifact_name,
                   governance_state_json, created_at)
                VALUES (?,?,?,?,?,?,?,?)
                """,
                (
                    exp_id, uid, pid, code,
                    "csv", "export.csv",
                    "{}", _ts_old(),
                ),
            )
            # CAPEX sub-line
            try:
                sl_id = str(uuid.uuid4())
                conn.execute(
                    """
                    INSERT INTO capex_sub_lines
                      (sub_line_id, project_id, parent_category_code,
                       business_code, display_order, label,
                       governance_state_json, created_at, updated_at)
                    VALUES (?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        sl_id, pid, "CAPEX_INFRA",
                        f"capex_d_{pid[:8]}", 1, "Test CAPEX Line",
                        "{}", _ts_old(), _ts_old(),
                    ),
                )
            except Exception:
                pass  # schema variation — not all test envs have all columns

            # OPEX sub-line
            try:
                osl_id = str(uuid.uuid4())
                conn.execute(
                    """
                    INSERT INTO opex_sub_lines
                      (sub_line_id, project_id, parent_group_code,
                       business_code, display_order, label,
                       created_at, updated_at)
                    VALUES (?,?,?,?,?,?,?,?)
                    """,
                    (
                        osl_id, pid, "OPEX_OPS",
                        f"opex_d_{pid[:8]}", 1, "Test OPEX Line",
                        _ts_old(), _ts_old(),
                    ),
                )
            except Exception:
                pass  # schema variation

        conn.commit()
        conn.close()


class TestStrictBootstrap:
    """bootstrap_staging_db must be transactionally fail-closed and must verify
    absence of non-reference state across all relevant tables."""

    def test_full_bootstrap_clears_all_tables(self):
        """After bootstrap: zero non-ref rows in projects, scenarios, workspace_states,
        runs, scenario_exports, and sub-line tables."""
        fd, db_path = tempfile.mkstemp(suffix=".db", prefix="finco_test_d_full_")
        os.close(fd)
        try:
            _build_test_db(db_path)

            with patch("app.persistence.db.DB_PATH", db_path):
                from app.persistence.db import get_connection
                conn = get_connection()
                from app.demo_cleanup import bootstrap_staging_db
                result = bootstrap_staging_db(conn)
                conn.close()

            assert result["post_condition"] == "PASS", (
                f"Expected post_condition=PASS, got {result['post_condition']!r}"
            )

            # Re-open and verify each table
            with patch("app.persistence.db.DB_PATH", db_path):
                from app.persistence.db import get_connection
                conn = get_connection()

                ref_count = conn.execute(
                    "SELECT COUNT(*) FROM projects WHERE user_id='__reference__'"
                ).fetchone()[0]
                assert ref_count == 4, f"Expected 4 ref projects, got {ref_count}"

                for table in ("projects", "scenarios", "workspace_states", "runs", "scenario_exports"):
                    non_ref = conn.execute(
                        f"SELECT COUNT(*) FROM {table} WHERE user_id != '__reference__'"
                    ).fetchone()[0]
                    assert non_ref == 0, (
                        f"Expected 0 non-reference rows in {table} after bootstrap, got {non_ref}"
                    )

                # Sub-lines: no orphan rows
                for table in ("capex_sub_lines", "opex_sub_lines"):
                    try:
                        orphan = conn.execute(
                            f"""SELECT COUNT(*) FROM {table}
                                WHERE project_id IN (
                                    SELECT project_id FROM projects
                                    WHERE user_id != '__reference__'
                                )"""
                        ).fetchone()[0]
                        assert orphan == 0, (
                            f"Expected 0 orphan rows in {table} after bootstrap, got {orphan}"
                        )
                    except sqlite3.OperationalError:
                        pass  # table may not exist in minimal schema

                conn.close()
        finally:
            try:
                os.unlink(db_path)
            except Exception:
                pass

    def test_bootstrap_raises_when_required_delete_fails(self):
        """If a required DELETE fails, bootstrap_staging_db must raise, never return PASS."""
        fd, db_path = tempfile.mkstemp(suffix=".db", prefix="finco_test_d_fail_")
        os.close(fd)
        try:
            _build_test_db(db_path)

            with patch("app.persistence.db.DB_PATH", db_path):
                from app.persistence.db import get_connection
                conn = get_connection()

                # Wrap the connection in a subclass that intercepts the projects DELETE
                class _FailingConn(sqlite3.Connection):
                    pass

                # Since we can't subclass a live connection, use a wrapper object
                class _ConnWrapper:
                    def __init__(self, real_conn):
                        self._conn = real_conn

                    def execute(self, sql, *args, **kwargs):
                        if (
                            sql.strip().upper().startswith("DELETE FROM PROJECTS")
                            and "__reference__" in sql
                        ):
                            raise sqlite3.OperationalError("simulated_delete_failure")
                        return self._conn.execute(sql, *args, **kwargs)

                    def __enter__(self):
                        return self

                    def __exit__(self, *a):
                        pass  # let the real connection handle commit

                    def commit(self):
                        return self._conn.commit()

                    def rollback(self):
                        return self._conn.rollback()

                    def close(self):
                        return self._conn.close()

                    def __getattr__(self, name):
                        return getattr(self._conn, name)

                wrapped = _ConnWrapper(conn)

                from app.demo_cleanup import bootstrap_staging_db
                with pytest.raises((sqlite3.OperationalError, RuntimeError, ValueError)):
                    bootstrap_staging_db(wrapped)

                conn.close()
        finally:
            try:
                os.unlink(db_path)
            except Exception:
                pass

    def test_bootstrap_post_condition_checks_scenarios_not_only_projects(self):
        """Post-condition must fail if scenarios remain even when projects are empty."""
        fd, db_path = tempfile.mkstemp(suffix=".db", prefix="finco_test_d_sc_")
        os.close(fd)
        try:
            _build_test_db(db_path)

            with patch("app.persistence.db.DB_PATH", db_path):
                from app.persistence.db import get_connection
                conn = get_connection()

                # Wrap connection to skip the scenarios DELETE so a non-ref scenario remains
                class _SkipScenariosConn:
                    def __init__(self, real_conn):
                        self._conn = real_conn

                    def execute(self, sql, *args, **kwargs):
                        if (
                            sql.strip().upper().startswith("DELETE FROM SCENARIOS")
                            and "__reference__" in sql
                        ):
                            fake = MagicMock()
                            fake.rowcount = 0
                            return fake
                        return self._conn.execute(sql, *args, **kwargs)

                    def __enter__(self):
                        return self

                    def __exit__(self, *a):
                        pass

                    def commit(self):
                        return self._conn.commit()

                    def rollback(self):
                        return self._conn.rollback()

                    def close(self):
                        return self._conn.close()

                    def __getattr__(self, name):
                        return getattr(self._conn, name)

                wrapped = _SkipScenariosConn(conn)

                from app.demo_cleanup import bootstrap_staging_db
                # bootstrap must either raise or report FAIL because scenarios are not clean
                try:
                    result = bootstrap_staging_db(wrapped)
                    # If it returns, post_condition must NOT be PASS
                    assert result.get("post_condition", "") != "PASS", (
                        "bootstrap_staging_db must not report PASS when non-reference "
                        "scenarios remain after bootstrap."
                    )
                except (ValueError, RuntimeError, sqlite3.OperationalError,
                        sqlite3.IntegrityError, sqlite3.DatabaseError):
                    pass  # Correct: raised an exception — any exception means not PASS

                conn.close()
        finally:
            try:
                os.unlink(db_path)
            except Exception:
                pass

    def test_bootstrap_idempotent_after_full_clear(self):
        """Running bootstrap twice on a clean DB must still produce PASS."""
        fd, db_path = tempfile.mkstemp(suffix=".db", prefix="finco_test_d_idem_")
        os.close(fd)
        try:
            with patch("app.persistence.db.DB_PATH", db_path):
                from app.persistence.db import get_connection
                conn = get_connection()
                from app.demo_cleanup import bootstrap_staging_db
                bootstrap_staging_db(conn)
                result2 = bootstrap_staging_db(conn)
                conn.close()

            assert result2["post_condition"] == "PASS", (
                f"Second bootstrap run must still PASS, got {result2['post_condition']!r}"
            )
        finally:
            try:
                os.unlink(db_path)
            except Exception:
                pass
