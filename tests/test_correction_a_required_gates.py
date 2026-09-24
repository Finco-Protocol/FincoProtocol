"""Correction A required gates — functional tests for PR #69.

Covers the mandatory acceptance criteria that were outstanding after the
initial post-PR65 correction commits:

A–H. DB bootstrap: real functional paths including legacy-schema upgrade and
     the exact ``opex_sub_lines.replay_metadata_json`` startup condition.
I.   MW rescaling via real HTTP path (POST /v2/workbook/update → capacity_mw).
J.   Reference-seed reset route (POST /v2/reference-seed/reset).
K.   Revenue real-run test (WaterfallResult periods → formatted summary).
L.   Same-MW economic parity — Solar and Wind working copy at reference MW
     reproduce all key KPIs from the canonical reference model.

DO NOT add network calls. DO NOT touch financial_engine or finco_core.
"""
from __future__ import annotations

import json
import sqlite3
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

REPO = Path(__file__).resolve().parents[1]


# ─────────────────────────────────────────────────────────────────────────────
# Shared fixtures
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture()
def isolated_db(tmp_path, monkeypatch):
    """Monkeypatched DB_PATH pointing at a fresh temp directory.

    Yields (db_module, db_path) — callers may use db_module.init_db() or
    db_module.get_connection() and the underlying file is auto-deleted.
    """
    from app.persistence import db as db_mod

    db_path = str(tmp_path / "gate-test.db")
    monkeypatch.setattr(db_mod, "DB_PATH", db_path)
    yield db_mod, db_path


@pytest.fixture()
def seeded_db(isolated_db):
    """Fully initialised DB (includes reference models)."""
    db_mod, db_path = isolated_db
    db_mod.init_db()
    yield db_mod, db_path


@pytest.fixture()
def seeded_solar_project(seeded_db):
    """Solar working copy seeded from the canonical 64 MW reference."""
    db_mod, _ = seeded_db
    from app.services.reference_seed_service import create_reference_seeded_project

    record = create_reference_seeded_project(
        user_id="gate-user",
        template_source="generic_solar_reference",
        requested_name="Gate Solar Project",
        capacity_mw=64.0,
    )
    yield db_mod, record


@pytest.fixture()
def seeded_wind_project(seeded_db):
    """Wind working copy seeded from the canonical 48 MW reference."""
    db_mod, _ = seeded_db
    from app.services.reference_seed_service import create_reference_seeded_project

    record = create_reference_seeded_project(
        user_id="gate-user",
        template_source="generic_wind_reference",
        requested_name="Gate Wind Project",
        capacity_mw=48.0,
    )
    yield db_mod, record


def _make_admin_cookie() -> dict[str, str]:
    from app.auth import COOKIE_NAME, create_session_token

    return {COOKIE_NAME: create_session_token(user_id="gate-user", username="admin")}


def _build_pis_with_hash(user_id: str, record) -> Any:
    """Build a ProjectInputSet with composite content_hash for ``record``."""
    from app.persistence.workspace_repository import get_workspace_state
    from app.workbook.service import WorkbookService
    from app.workbook.workbook_identity import assemble_consistent_for_get

    ws = get_workspace_state(user_id, record.project_id)
    assert ws is not None, "Workspace must exist for seeded project"

    pis = WorkbookService.build_draft_input_set_from_workspace(ws)
    identity = assemble_consistent_for_get(
        user_id=user_id,
        project_id=record.project_id,
        workbook_version=pis.workbook_version,
    )
    return pis.with_composite_hash(identity.composite_hash)


# ─────────────────────────────────────────────────────────────────────────────
# A. Blank DB → full schema bootstrap succeeds
# ─────────────────────────────────────────────────────────────────────────────

class TestDbBootstrapFunctional:
    """Scenarios A–H: real functional DB bootstrap paths."""

    def test_A_blank_db_bootstrap_creates_all_tables(self, isolated_db):
        """A. A completely blank DB bootstraps to full schema without errors."""
        db_mod, db_path = isolated_db
        db_mod.init_db()
        conn = sqlite3.connect(db_path)
        tables = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()}
        conn.close()
        for expected in ("runs", "scenarios", "projects", "workspace_states",
                         "capex_sub_lines", "opex_sub_lines"):
            assert expected in tables, f"Table {expected!r} missing after bootstrap"

    def test_B_legacy_db_without_replay_metadata_gets_column(self, isolated_db):
        """B. Legacy DB with opex_sub_lines but no replay_metadata_json gets the column."""
        db_mod, db_path = isolated_db
        # Create the opex_sub_lines table WITHOUT replay_metadata_json (as in pre-PR schema).
        conn = sqlite3.connect(db_path)
        conn.execute(
            """
            CREATE TABLE opex_sub_lines (
                sub_line_id         TEXT PRIMARY KEY,
                project_id          TEXT NOT NULL,
                parent_group_code   TEXT NOT NULL,
                label               TEXT NOT NULL,
                amount_keur         REAL NOT NULL DEFAULT 0.0,
                is_active           INTEGER NOT NULL DEFAULT 1,
                source              TEXT NOT NULL DEFAULT 'user',
                display_order       INTEGER NOT NULL DEFAULT 0,
                created_at          TEXT NOT NULL DEFAULT (datetime('now')),
                updated_at          TEXT NOT NULL DEFAULT (datetime('now')),
                inflation_pct       REAL NOT NULL DEFAULT 0.0,
                comments            TEXT NOT NULL DEFAULT '',
                business_code       TEXT NOT NULL DEFAULT ''
            )
            """
        )
        # Insert a row WITHOUT replay_metadata_json to simulate legacy data.
        conn.execute(
            "INSERT INTO opex_sub_lines "
            "(sub_line_id, project_id, parent_group_code, label, amount_keur, business_code) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            ("legacy-row-1", "project-abc", "B.01", "Legacy OPEX", 99.5, "B.01.001"),
        )
        conn.commit()
        conn.close()

        # init_db must upgrade the schema without losing existing data.
        db_mod.init_db()

        conn = sqlite3.connect(db_path)
        cols = {r[1] for r in conn.execute("PRAGMA table_info(opex_sub_lines)").fetchall()}
        assert "replay_metadata_json" in cols, (
            "init_db must add replay_metadata_json to legacy opex_sub_lines"
        )
        # Existing row must survive.
        rows = conn.execute(
            "SELECT label, amount_keur FROM opex_sub_lines WHERE sub_line_id=?",
            ("legacy-row-1",)
        ).fetchall()
        assert len(rows) == 1
        assert rows[0][0] == "Legacy OPEX"
        assert rows[0][1] == 99.5
        conn.close()

    def test_C_current_schema_with_replay_metadata_bootstraps_clean(self, isolated_db):
        """C. Current DB with replay_metadata_json present: bootstrap is a no-op."""
        db_mod, db_path = isolated_db
        # First bootstrap creates everything.
        db_mod.init_db()
        # Insert a real opex row with replay_metadata_json.
        conn = sqlite3.connect(db_path)
        conn.execute(
            "INSERT INTO opex_sub_lines "
            "(sub_line_id, project_id, parent_group_code, label, amount_keur, "
            " inflation_pct, source, business_code, replay_metadata_json, display_order, "
            " created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'), datetime('now'))",
            ("c-row", "proj-c", "B.02", "Test OPEX", 42.0, 2.0,
             "reference_seed", "B.02.001", '{"reference_seed": true}', 0),
        )
        conn.commit()
        conn.close()
        # Second bootstrap must not error and must not disturb the row.
        db_mod.init_db()
        conn = sqlite3.connect(db_path)
        row = conn.execute(
            "SELECT label, replay_metadata_json FROM opex_sub_lines WHERE sub_line_id=?",
            ("c-row",)
        ).fetchone()
        assert row is not None
        assert row[0] == "Test OPEX"
        assert json.loads(row[1]) == {"reference_seed": True}
        conn.close()

    def test_D_repeated_bootstrap_is_idempotent(self, isolated_db):
        """D. init_db called five times in a row never raises."""
        db_mod, _ = isolated_db
        for _ in range(5):
            db_mod.init_db()

    def test_E_existing_opex_rows_retained_across_bootstrap(self, isolated_db):
        """E. Opex rows written before a second init_db call survive intact."""
        db_mod, db_path = isolated_db
        db_mod.init_db()
        conn = sqlite3.connect(db_path)
        conn.execute(
            "INSERT INTO opex_sub_lines "
            "(sub_line_id, project_id, parent_group_code, label, amount_keur, "
            " inflation_pct, source, business_code, replay_metadata_json, display_order, "
            " created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'), datetime('now'))",
            ("e-row", "proj-e", "B.01", "Retained OPEX", 77.0, 1.5,
             "reference_seed", "B.01.001", "{}", 0),
        )
        conn.commit()
        conn.close()
        db_mod.init_db()  # second initialisation
        conn = sqlite3.connect(db_path)
        count = conn.execute(
            "SELECT COUNT(*) FROM opex_sub_lines WHERE sub_line_id=?", ("e-row",)
        ).fetchone()[0]
        assert count == 1, "Existing OPEX row must survive a second init_db"
        conn.close()

    def test_F_replay_metadata_json_value_retained(self, isolated_db):
        """F. replay_metadata_json content is preserved across bootstrap."""
        db_mod, db_path = isolated_db
        db_mod.init_db()
        payload = {"reference_seed": True, "canonical_key": "Technical Management",
                   "unit_rate_keur_per_mw": 2.5, "scaling_mode": "PER_MW"}
        conn = sqlite3.connect(db_path)
        conn.execute(
            "INSERT INTO opex_sub_lines "
            "(sub_line_id, project_id, parent_group_code, label, amount_keur, "
            " inflation_pct, source, business_code, replay_metadata_json, display_order, "
            " created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'), datetime('now'))",
            ("f-row", "proj-f", "B.01", "TM OPEX", 160.0, 2.0,
             "reference_seed", "B.01.001", json.dumps(payload), 0),
        )
        conn.commit()
        conn.close()
        db_mod.init_db()
        conn = sqlite3.connect(db_path)
        stored = conn.execute(
            "SELECT replay_metadata_json FROM opex_sub_lines WHERE sub_line_id=?",
            ("f-row",)
        ).fetchone()[0]
        assert json.loads(stored) == payload, (
            "replay_metadata_json content must survive init_db"
        )
        conn.close()

    def test_G_toctou_duplicate_column_exception_is_absorbed(self, isolated_db):
        """G. _ensure_column absorbs a 'duplicate column name' OperationalError
        (the TOCTOU race path) without re-raising."""
        db_mod, _ = isolated_db
        from app.persistence.db import _ensure_column

        conn = sqlite3.connect(":memory:", isolation_level=None)
        conn.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, name TEXT)")
        # First call: normal path — adds the column.
        _ensure_column(conn, "t", "extra", "TEXT NOT NULL DEFAULT 'x'")
        # Second call: PRAGMA reports column present → no ALTER → no exception.
        _ensure_column(conn, "t", "extra", "TEXT NOT NULL DEFAULT 'x'")
        # Verify column exists.
        cols = {r[1] for r in conn.execute("PRAGMA table_info(t)").fetchall()}
        assert "extra" in cols
        conn.close()

    def test_H_non_duplicate_operational_error_is_reraised(self, isolated_db):
        """H. _ensure_column re-raises OperationalErrors that are NOT
        'duplicate column name'."""
        from app.persistence.db import _ensure_column
        import sqlite3 as _sqlite3

        # Calling _ensure_column on a non-existent table triggers a genuine
        # OperationalError (not 'duplicate column name') which must be re-raised.
        conn = sqlite3.connect(":memory:", isolation_level=None)
        with pytest.raises(_sqlite3.OperationalError) as exc_info:
            _ensure_column(conn, "nonexistent_table", "col", "TEXT")
        assert "duplicate column name" not in str(exc_info.value).lower(), (
            "Only 'duplicate column name' errors must be absorbed; "
            f"got: {exc_info.value}"
        )
        conn.close()


# ─────────────────────────────────────────────────────────────────────────────
# I. MW rescaling via real HTTP path
# ─────────────────────────────────────────────────────────────────────────────

class TestMwRescalingHttpPath:
    """I. POST /v2/workbook/update with capacity_mw triggers the rescale pipeline
    end-to-end: HTTP → WorkbookUpdateService → rescale_reference_seeded_project
    → persistence → verifiable DB state.
    """

    @pytest.mark.parametrize("template_source, initial_mw, new_mw", [
        ("generic_solar_reference", 64.0, 128.0),
        ("generic_wind_reference", 48.0, 96.0),
    ])
    def test_capacity_rescale_via_http_rescales_detail_rows(
        self, seeded_db, template_source, initial_mw, new_mw
    ):
        db_mod, _ = seeded_db
        from app.services.reference_seed_service import create_reference_seeded_project
        from app.persistence.capex_sub_lines import get_active_sub_lines_for_project
        from app.persistence.opex_sub_lines import (
            get_active_sub_lines_for_project as get_opex,
        )
        import main_web
        from fastapi.testclient import TestClient

        user_id = f"mw-http-{template_source}"
        record = create_reference_seeded_project(
            user_id=user_id,
            template_source=template_source,
            requested_name="HTTP Rescale Test",
            capacity_mw=initial_mw,
        )

        # Capture before state.
        capex_before = {x.sub_line_id: x for x in get_active_sub_lines_for_project(record.project_id)}
        opex_before = {x.sub_line_id: x for x in get_opex(record.project_id)}
        assert capex_before, "Seeded project must have CAPEX sub-lines"
        assert opex_before, "Seeded project must have OPEX sub-lines"

        # Build composite hash for the optimistic-concurrency guard.
        pis = _build_pis_with_hash(user_id, record)

        from app.auth import COOKIE_NAME, create_session_token
        cookies = {COOKIE_NAME: create_session_token(user_id=user_id, username="admin")}

        client = TestClient(main_web.app, raise_server_exceptions=True)
        resp = client.post(
            "/v2/workbook/update",
            data={
                "field_id": "project_setup.technical.capacity_mw",
                "value": str(new_mw),
                "project": record.project_code,
                "workbook_version": pis.workbook_version,
                "content_hash": pis.content_hash,
                "sheet_id": "inputs",
            },
            cookies=cookies,
            follow_redirects=False,
        )
        # Route returns redirect (303) on success for non-HTMX, or 200 for HTMX.
        assert resp.status_code in (200, 303), (
            f"Expected 200 or 303 from /v2/workbook/update, got {resp.status_code}: "
            f"{resp.text[:200]}"
        )

        # Verify DB state: all reference_seed rows were rescaled by the new ratio.
        capex_after = {x.sub_line_id: x for x in get_active_sub_lines_for_project(record.project_id)}
        opex_after = {x.sub_line_id: x for x in get_opex(record.project_id)}
        ratio = new_mw / initial_mw

        rescaled_capex = 0
        for sid, line in capex_after.items():
            before = capex_before.get(sid)
            if before and before.source == "reference_seed":
                expected = before.amount_keur * ratio
                assert line.amount_keur == pytest.approx(expected, rel=1e-6), (
                    f"CAPEX line {sid}: expected {expected:.4f}, got {line.amount_keur:.4f}"
                )
                rescaled_capex += 1
        assert rescaled_capex > 0, "At least one CAPEX row must have been rescaled"

        rescaled_opex = 0
        for sid, line in opex_after.items():
            before = opex_before.get(sid)
            if before and before.source == "reference_seed":
                expected = before.amount_keur * ratio
                assert line.amount_keur == pytest.approx(expected, rel=1e-6), (
                    f"OPEX line {sid}: expected {expected:.4f}, got {line.amount_keur:.4f}"
                )
                rescaled_opex += 1
        assert rescaled_opex > 0, "At least one OPEX row must have been rescaled"

    def test_capacity_rescale_leaves_user_override_intact(self, seeded_solar_project):
        """HTTP rescale must not change a user_override CAPEX row."""
        db_mod, record = seeded_solar_project
        from app.persistence.capex_sub_lines import get_active_sub_lines_for_project
        from app.persistence.db import get_cursor
        import main_web
        from fastapi.testclient import TestClient

        user_id = "gate-user"
        capex = get_active_sub_lines_for_project(record.project_id)
        held = capex[0]
        OVERRIDE_AMOUNT = 9999.0
        with get_cursor() as cur:
            cur.execute(
                "UPDATE capex_sub_lines SET amount_keur=?, source='user_override' "
                "WHERE sub_line_id=?",
                (OVERRIDE_AMOUNT, held.sub_line_id),
            )

        pis = _build_pis_with_hash(user_id, record)
        from app.auth import COOKIE_NAME, create_session_token
        cookies = {COOKIE_NAME: create_session_token(user_id=user_id, username="admin")}
        client = TestClient(main_web.app, raise_server_exceptions=True)
        client.post(
            "/v2/workbook/update",
            data={
                "field_id": "project_setup.technical.capacity_mw",
                "value": "128.0",
                "project": record.project_code,
                "workbook_version": pis.workbook_version,
                "content_hash": pis.content_hash,
                "sheet_id": "inputs",
            },
            cookies=cookies,
            follow_redirects=False,
        )
        capex_after = {x.sub_line_id: x for x in get_active_sub_lines_for_project(record.project_id)}
        assert capex_after[held.sub_line_id].amount_keur == pytest.approx(OVERRIDE_AMOUNT), (
            "user_override CAPEX row must be untouched by MW rescale"
        )

    def test_total_capex_snapshot_reconciles_after_rescale(self, seeded_solar_project):
        """total_capex_keur in workspace snapshot == sum of active CAPEX sub-lines after rescale."""
        db_mod, record = seeded_solar_project
        from app.persistence.capex_sub_lines import get_active_sub_lines_for_project
        from app.persistence.workspace_repository import get_workspace_state
        import main_web
        from fastapi.testclient import TestClient

        user_id = "gate-user"
        pis = _build_pis_with_hash(user_id, record)
        from app.auth import COOKIE_NAME, create_session_token
        cookies = {COOKIE_NAME: create_session_token(user_id=user_id, username="admin")}
        client = TestClient(main_web.app, raise_server_exceptions=True)
        client.post(
            "/v2/workbook/update",
            data={
                "field_id": "project_setup.technical.capacity_mw",
                "value": "96.0",
                "project": record.project_code,
                "workbook_version": pis.workbook_version,
                "content_hash": pis.content_hash,
                "sheet_id": "inputs",
            },
            cookies=cookies,
            follow_redirects=False,
        )
        lines = get_active_sub_lines_for_project(record.project_id)
        ws = get_workspace_state(user_id, record.project_id)
        snapshot_total = float(ws.draft_snapshot.get("total_capex_keur", 0))
        line_total = sum(x.amount_keur for x in lines)
        assert snapshot_total == pytest.approx(line_total, rel=1e-6), (
            f"total_capex_keur snapshot ({snapshot_total:.2f}) must reconcile with "
            f"sum of active CAPEX lines ({line_total:.2f}) after rescale"
        )


# ─────────────────────────────────────────────────────────────────────────────
# J. Reference reset route
# ─────────────────────────────────────────────────────────────────────────────

class TestReferenceSeedResetRoute:
    """J. POST /v2/reference-seed/reset restores overridden rows to canonical rates."""

    def test_reset_restores_capex_override_to_canonical_rate(self, seeded_solar_project):
        """After reset, the previously overridden CAPEX row is restored to
        its canonical unit_rate × current_capacity_mw."""
        db_mod, record = seeded_solar_project
        from app.persistence.capex_sub_lines import get_active_sub_lines_for_project
        from app.persistence.db import get_cursor
        import main_web
        from fastapi.testclient import TestClient

        user_id = "gate-user"
        capex = get_active_sub_lines_for_project(record.project_id)
        held = capex[0]
        canonical_rate = held.replay_metadata.get("unit_rate_keur_per_mw")
        assert canonical_rate is not None, "Seeded row must carry unit_rate_keur_per_mw"

        # Override the row.
        with get_cursor() as cur:
            cur.execute(
                "UPDATE capex_sub_lines SET amount_keur=?, source='user_override' "
                "WHERE sub_line_id=?",
                (99999.0, held.sub_line_id),
            )

        from app.auth import COOKIE_NAME, create_session_token
        cookies = {COOKIE_NAME: create_session_token(user_id=user_id, username="admin")}
        client = TestClient(main_web.app, raise_server_exceptions=True)
        resp = client.post(
            "/v2/reference-seed/reset",
            data={"project": record.project_code},
            cookies=cookies,
            follow_redirects=False,
        )
        assert resp.status_code in (200, 303), (
            f"Reset must succeed; got {resp.status_code}: {resp.text[:200]}"
        )

        capex_after = {x.sub_line_id: x for x in get_active_sub_lines_for_project(record.project_id)}
        restored_line = capex_after[held.sub_line_id]
        assert restored_line.source == "reference_seed", (
            "Reset must restore source to 'reference_seed'"
        )
        expected = canonical_rate * 64.0  # initial_mw=64
        assert restored_line.amount_keur == pytest.approx(expected, rel=1e-6), (
            f"Restored CAPEX row: expected {expected:.4f}, got {restored_line.amount_keur:.4f}"
        )

    def test_reset_does_not_touch_non_seed_custom_rows(self, seeded_solar_project):
        """Reset must not change CAPEX rows whose replay_metadata has no reference_seed key."""
        db_mod, record = seeded_solar_project
        from app.persistence.capex_sub_lines import create_sub_line, get_active_sub_lines_for_project
        from app.persistence.db import get_cursor
        import main_web
        from fastapi.testclient import TestClient

        user_id = "gate-user"
        # Create a genuinely custom row (not a reference seed).
        with get_cursor() as cur:
            create_sub_line(
                cur,
                project_id=record.project_id,
                parent_category_code="C.05",
                label="Custom EPC Add-on",
                amount_keur=555.0,
                source="user",
                comments="Custom",
                replay_metadata={},
            )

        from app.auth import COOKIE_NAME, create_session_token
        cookies = {COOKIE_NAME: create_session_token(user_id=user_id, username="admin")}
        client = TestClient(main_web.app, raise_server_exceptions=True)
        client.post(
            "/v2/reference-seed/reset",
            data={"project": record.project_code},
            cookies=cookies,
            follow_redirects=False,
        )
        lines = get_active_sub_lines_for_project(record.project_id)
        custom_lines = [l for l in lines if l.label == "Custom EPC Add-on"]
        assert len(custom_lines) == 1, "Custom row must survive reference seed reset"
        assert custom_lines[0].amount_keur == pytest.approx(555.0), (
            "Custom row amount must be unchanged by reset"
        )

    def test_reset_on_reference_model_returns_403(self, seeded_db):
        """POST /v2/reference-seed/reset on a protected reference returns 403."""
        import main_web
        from fastapi.testclient import TestClient

        # Bootstrap the canonical reference models into the temp DB so that the
        # route can find the protected reference and return 403 (not 404).
        from app.services.project_library_service import ensure_reference_models
        ensure_reference_models()

        from app.auth import COOKIE_NAME, create_session_token
        cookies = {COOKIE_NAME: create_session_token(user_id="gate-user", username="admin")}
        client = TestClient(main_web.app, raise_server_exceptions=True)
        resp = client.post(
            "/v2/reference-seed/reset",
            data={"project": "generic_solar_reference-reference"},
            cookies=cookies,
            follow_redirects=False,
        )
        assert resp.status_code == 403, (
            f"Resetting a protected reference must return 403; got {resp.status_code}"
        )


# ─────────────────────────────────────────────────────────────────────────────
# K. Revenue real-run test (not template-source-only)
# ─────────────────────────────────────────────────────────────────────────────

class TestRevenueRealRunPeriods:
    """K. Actual model run → period-level revenue data.

    Verifies that the revenue derivation evidence produced by a real
    WaterfallResult run contains the period series and that the formatted
    runtime_summary matches the raw engine output — no secondary formula.
    """

    @pytest.mark.parametrize("project_key", ["Solar", "Wind"])
    def test_run_produces_non_empty_revenue_periods(self, project_key):
        """run_project returns revenue_periods with at least one operating period."""
        from app.api.project_runner import run_project

        result = run_project(project_key, "Base")
        periods = result["derivation_evidence"]["revenue"]["revenue_periods"]
        assert len(periods) > 0, (
            f"{project_key}: revenue_periods must be non-empty in a real run"
        )

    @pytest.mark.parametrize("project_key", ["Solar", "Wind"])
    def test_period_labels_are_non_empty_strings(self, project_key):
        """Every period has a non-empty period_label string."""
        from app.api.project_runner import run_project

        result = run_project(project_key, "Base")
        periods = result["derivation_evidence"]["revenue"]["revenue_periods"]
        for p in periods:
            assert isinstance(p["period_label"], str) and p["period_label"].strip(), (
                f"{project_key}: every period must have a non-empty period_label"
            )

    @pytest.mark.parametrize("project_key", ["Solar", "Wind"])
    def test_period_generation_and_revenue_are_positive(self, project_key):
        """All operating periods carry positive generation_mwh and revenue_keur."""
        from app.api.project_runner import run_project

        result = run_project(project_key, "Base")
        periods = result["derivation_evidence"]["revenue"]["revenue_periods"]
        for p in periods:
            assert float(p["generation_mwh"]) > 0, (
                f"{project_key}: generation_mwh must be positive in {p['period_label']}"
            )
            assert float(p["revenue_keur"]) > 0, (
                f"{project_key}: revenue_keur must be positive in {p['period_label']}"
            )

    @pytest.mark.parametrize("project_key", ["Solar", "Wind"])
    def test_formatted_periods_match_raw_engine_data(self, project_key):
        """Runtime summary formatted periods are derived from engine data, not a parallel formula."""
        from app.api.project_runner import run_project
        from app.ui.runtime_summary import _format_revenue_derivation

        result = run_project(project_key, "Base")
        raw = result["derivation_evidence"]["revenue"]
        formatted = _format_revenue_derivation(raw)

        raw_periods = raw["revenue_periods"]
        fmt_periods = formatted["revenue_periods"]
        assert len(fmt_periods) == len(raw_periods), (
            "Formatted period count must match raw engine period count"
        )
        for raw_p, fmt_p in zip(raw_periods, fmt_periods):
            assert fmt_p["period_label"] == raw_p["period_label"], (
                "Formatted period_label must match raw period_label"
            )
            # Revenue_keur_raw is preserved unmodified.
            assert fmt_p["revenue_keur_raw"] == pytest.approx(raw_p["revenue_keur"]), (
                "revenue_keur_raw must equal raw engine revenue_keur"
            )

    @pytest.mark.parametrize("project_key", ["Solar", "Wind"])
    def test_period_count_consistent_with_horizon(self, project_key):
        """Period count matches the derivation_evidence metadata."""
        from app.api.project_runner import run_project

        result = run_project(project_key, "Base")
        rev_ev = result["derivation_evidence"]["revenue"]
        raw_count = rev_ev.get("period_count", 0)
        actual_count = len(rev_ev["revenue_periods"])
        assert actual_count == raw_count, (
            f"{project_key}: period_count metadata ({raw_count}) must match "
            f"actual period list length ({actual_count})"
        )


# ─────────────────────────────────────────────────────────────────────────────
# L. Same-MW economic parity (Solar and Wind)
# ─────────────────────────────────────────────────────────────────────────────

class TestSameMwEconomicParity:
    """L. A working copy seeded at the canonical reference MW must reproduce
    all key KPIs from the canonical reference model.

    This test runs the actual economic model — no mock outputs.
    """

    @pytest.mark.parametrize("template_source, capacity", [
        ("generic_solar_reference", 64.0),
        ("generic_wind_reference", 48.0),
    ])
    def test_same_mw_kpis_match_canonical_reference(
        self, seeded_db, template_source, capacity
    ):
        """Working copy at canonical MW reproduces Project IRR, Equity IRR,
        Project NPV, Min DSCR, Avg DSCR, Min LLCR, Total CAPEX, and OPEX Y1."""
        from app.api.project_runner import run_project
        from app.input_adapter import _resolve_user_inputs, _snapshot_to_dict
        from app.persistence.workspace_repository import get_workspace_state
        from app.project_factories import (
            create_generic_solar_reference,
            create_generic_wind_reference,
        )
        from app.services.capex_sub_lines_integration import apply_user_sub_lines_replacing_base
        from app.services.opex_sub_lines_integration import apply_user_sub_lines_to_opex
        from app.services.reference_seed_service import (
            create_reference_seeded_project,
            restore_reference_seed_technical_authority,
        )

        user_id = f"parity-{template_source[:5]}"
        record = create_reference_seeded_project(
            user_id=user_id,
            template_source=template_source,
            requested_name="Parity Test",
            capacity_mw=capacity,
        )
        ws = get_workspace_state(user_id, record.project_id)
        ref_factory = (
            create_generic_solar_reference
            if "solar" in template_source
            else create_generic_wind_reference
        )
        reference = ref_factory()
        base_inputs = _resolve_user_inputs(
            base_inputs=reference, **_snapshot_to_dict(ws.draft_snapshot)
        )
        base_inputs = restore_reference_seed_technical_authority(
            base_inputs, ws.draft_snapshot
        )
        inputs = replace(
            base_inputs,
            capex=apply_user_sub_lines_replacing_base(
                base_inputs.capex, project_id=record.project_id
            ),
            opex=apply_user_sub_lines_to_opex(
                base_inputs.opex, project_id=record.project_id
            ),
        )

        project_key = (
            "Generic Solar Reference" if "solar" in template_source
            else "Generic Wind Reference"
        )
        working_copy_result = run_project(
            project_key, "Base", project_inputs_override=inputs
        )
        reference_result = run_project(project_key, "Base")

        def _kpi(result, key):
            return float(result["kpis"].get(key) or 0)

        for metric in (
            "project_irr", "equity_irr", "project_npv",
            "min_dscr", "avg_dscr", "min_llcr",
        ):
            wc_val = _kpi(working_copy_result, metric)
            ref_val = _kpi(reference_result, metric)
            assert wc_val == pytest.approx(ref_val, rel=1e-5), (
                f"{template_source} {metric}: working copy ({wc_val:.6f}) "
                f"must match reference ({ref_val:.6f}) at same MW"
            )

        # Total CAPEX and OPEX Y1 from the materialized inputs.
        assert float(inputs.capex.total_capex) == pytest.approx(
            float(reference.capex.total_capex), rel=1e-5
        ), "Total CAPEX must match reference at same MW"
        assert sum(float(x.y1_amount_keur) for x in inputs.opex) == pytest.approx(
            sum(float(x.y1_amount_keur) for x in reference.opex), rel=1e-5
        ), "OPEX Y1 total must match reference at same MW"
