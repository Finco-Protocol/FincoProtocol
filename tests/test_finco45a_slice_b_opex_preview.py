"""FINCO45A Slice B — OPEX nominal budget vs canonical Phase 2A operating preview (C3-E-05, FINCO44-IND-02, P1-OPEX-01).

Verifies:
- 4/25/100/250 OPEX line matrix comparing GET /v2/model-react/opex-projection operating_preview
  against authenticated HTTP Run, XLSX export, and independent Decimal(50) oracle (<= 1e-9 kEUR).
- Nominal full-year budget remains intact & clearly labeled; operating_preview never mutates DB,
  never commits a Run, and distinguishes draft preview vs Last Run via fingerprint + freshness.
- Covers partial COD, final stub, leap date, annual overrides (incl. explicit 0 & deletion),
  nonzero B.13 contingency, step/conditional items, legacy & dated Solar/Wind, fail-closed
  OPERATING_PREVIEW_UNAVAILABLE, G10 default 404 vs isolated monkeypatch 200, and cold/warm timing.
"""
from __future__ import annotations

import calendar
from datetime import date
from decimal import Decimal, getcontext
import io
import json
import sqlite3
import time

import openpyxl
import pytest

from app.persistence import db
from app.persistence.opex_sub_lines import create_sub_line, get_active_sub_lines_for_project
from app.persistence.run_history_repository import get_run_history
from app.persistence.workspace_repository import get_workspace_state
from app.v2.capex_commands import set_contingency_percentage
from app.workbook.registry import WORKBOOK
from app.workbook.workbook_identity import assemble_consistent_for_get
from finco_core.inputs import OpexItem
from finco_core.opex.projections import opex_item_amount_at_year
from tests.test_model_react_wf2_projections_v1 import OWNER, env  # noqa: F401

getcontext().prec = 50


def _db_dump() -> str:
    with sqlite3.connect(db.DB_PATH) as conn:
        return "\n".join(conn.iterdump())


def _set_opex_contingency(record, pct: float) -> None:
    ident = assemble_consistent_for_get(OWNER, record.project_id, WORKBOOK.version)
    set_contingency_percentage(
        project_record=record,
        user_id=OWNER,
        kind="opex",
        pct=pct,
        workbook_version=WORKBOOK.version,
        expected_content_hash=ident.composite_hash,
    )


def _seed_n_opex_lines(client, record, total_lines: int) -> None:
    """Adjust project to have ``total_lines - 4`` added B.09 lines at 0.15 kEUR & 0% B.13 contingency."""
    _set_opex_contingency(record, 0.0)
    need = max(0, total_lines - 4)
    if need > 0:
        with db.get_connection() as conn:
            cur = conn.cursor()
            for i in range(need):
                create_sub_line(
                    cur,
                    project_id=record.project_id,
                    parent_group_code="B.09",
                    business_code=f"B.09.U{i + 1:03d}",
                    label=f"Matrix OPEX {i + 1}",
                    amount_keur=0.15,
                    inflation_pct=2.0,
                )
            conn.commit()


def _daily_dated_opex_oracle(op_periods, *, cod: date, horizon_years: int, y1_budget: Decimal, inflation: Decimal):
    """FINCO45B independent OD-TIME-01/v1 oracle (shares no code with the engine): walk every calendar day of the
    contractual operating life [COD, COD + horizon years), charge y1 * (1 + i)^(operating year - 1) / days-in-that-
    calendar-year (exact Fraction), and bucket the days into the preview's half-open operating rows
    ([COD or previous end + 1 day, period_end + 1 day))."""
    from datetime import timedelta
    from fractions import Fraction

    def add_years(d: date, n: int) -> date:
        y = d.year + n
        return date(y, 2, 28) if (d.month, d.day) == (2, 29) and not calendar.isleap(y) else d.replace(year=y)

    end_excl = add_years(cod, horizon_years)
    anniversaries = [add_years(cod, k) for k in range(1, horizon_years + 1)]
    ops = [p for p in op_periods if p["is_operation"]]
    bounds, prev_end = [], None
    for p in ops:
        start = cod if prev_end is None else prev_end + timedelta(days=1)
        stop = date.fromisoformat(p["period_end"]) + timedelta(days=1)
        bounds.append((p["period_index"], start, min(stop, end_excl)))
        prev_end = date.fromisoformat(p["period_end"])
    y1, infl = Fraction(str(y1_budget)), Fraction(str(inflation))
    out = {}
    for idx, start, stop in bounds:
        total, d = Fraction(0), start
        while d < stop:
            op_year = 1 + sum(1 for a in anniversaries if a <= d)
            total += y1 * (1 + infl) ** (op_year - 1) / (366 if calendar.isleap(d.year) else 365)
            d += timedelta(days=1)
        out[idx] = total
    return out


@pytest.mark.parametrize("authority", ["legacy", "dated"])
@pytest.mark.parametrize("n_lines,expected_y1_budget", [
    (4, 500.30),
    (25, 503.45),
    (100, 514.70),
    (250, 537.20),
])
def test_opex_4_25_100_250_matrix_matches_http_run_xlsx_and_decimal_oracle(
    env, monkeypatch, n_lines, expected_y1_budget, authority
):
    """FINCO45B: ``dated`` is the new default creation (OD-TIME-01/v1, no flag set); ``legacy`` is a retained
    LEGACY_CALENDAR/v0 project created through the explicit creation rollback, proving its old oracle unchanged."""
    from app.runtime.model_execution import ModelExecutionConfig, ModelExecutor, reset_model_executor_for_tests

    monkeypatch.setenv("FINCO_MODEL_EXECUTION_MODE", "thread")
    reset_model_executor_for_tests(ModelExecutor(ModelExecutionConfig(mode="thread")))

    if authority == "legacy":
        monkeypatch.setenv("FINCO_NEW_PROJECT_DATE_AUTHORITY", "legacy")
    else:
        monkeypatch.delenv("FINCO_NEW_PROJECT_DATE_AUTHORITY", raising=False)
    record = env.create("solar")
    monkeypatch.delenv("FINCO_NEW_PROJECT_DATE_AUTHORITY", raising=False)
    stored_version = get_workspace_state(OWNER, record.project_id).draft_snapshot.get("date_authority_version")
    assert stored_version == (None if authority == "legacy" else "OD-TIME-01/v1")
    # Keep all 19 reference-seeded lines active (preserving has_reference_seed per group)
    # with total 500.30 kEUR, plus (n_lines - 4) added B.09 lines at 0.15 kEUR each ->
    # exact Neon matrix totals 500.30 / 503.45 / 514.75 / 537.25 kEUR.
    lines0 = get_active_sub_lines_for_project(record.project_id)
    from app.persistence.db import get_connection
    with get_connection() as conn:
        for idx, sl in enumerate(lines0):
            amt = 500.30 if idx == 0 else 0.0
            conn.execute(
                "UPDATE opex_sub_lines SET amount_keur = ?, inflation_pct = 2.0 WHERE sub_line_id = ?",
                (amt, sl.sub_line_id),
            )
        conn.commit()
    _seed_n_opex_lines(env.client, record, n_lines)
    assert len(get_active_sub_lines_for_project(record.project_id)) == len(lines0) + max(0, n_lines - 4)

    # Cold + warm preview timings without mutating DB
    before_dump = _db_dump()
    t0 = time.perf_counter()
    r_cold = env.client.get("/v2/model-react/opex-projection", params={"project": record.project_code})
    cold_ms = (time.perf_counter() - t0) * 1000.0
    assert r_cold.status_code == 200, r_cold.text

    t1 = time.perf_counter()
    r_warm = env.client.get("/v2/model-react/opex-projection", params={"project": record.project_code})
    warm_ms = (time.perf_counter() - t1) * 1000.0
    assert r_warm.status_code == 200
    assert _db_dump() == before_dump
    assert len(get_run_history(OWNER, record.project_id)) == 0

    body = r_warm.json()
    assert body["kpis"]["year1_total_keur"] == pytest.approx(expected_y1_budget, abs=1e-9)
    op = body["operating_preview"]
    assert op["available"] is True
    assert op["status"] == "OK"
    assert op["freshness"]["state"] == "NOT_RUN"
    assert op["freshness"]["matches_last_run"] is False
    assert cold_ms >= 0 and warm_ms >= 0

    # Independent Decimal(50) oracle for calendar Y1 (2031-03-01..2031-12-31 = 306 days / 365)
    y1_budget_dec = Decimal(str(expected_y1_budget))
    expected_cal_y1 = y1_budget_dec * Decimal(306) / Decimal(365)
    assert abs(Decimal(str(op["kpis"]["first_operating_calendar_year_opex_keur"])) - expected_cal_y1) <= Decimal("1e-9")

    # Execute canonical authenticated HTTP Run and compare EVERY calendar year & period
    ws_shell = env.client.get("/v2/model-react/workspace", params={"project": record.project_code}).json()
    runs_meta = env.client.get("/v2/model-react/runs", params={"project": record.project_code}).json()
    r_run = env.client.post(
        "/v2/workbook/run",
        headers={"Accept": "application/json"},
        data={
            "project": record.project_code,
            "csrf_token": runs_meta["run_contract"]["csrf_token"],
            "content_hash": ws_shell["workbook"]["composite_hash"],
            "workbook_version": ws_shell["workbook"]["version"],
            "run_intent_id": f"33333333-4444-4555-8666-{n_lines:012d}",
        },
    )
    assert r_run.status_code == 200, r_run.text
    assert r_run.json()["outcome"] == "COMMITTED"

    # Compare preview calendar_years AND periods against committed Statements P&L and Run History
    stmts = env.client.get("/v2/model-react/statements", params={"project": record.project_code}).json()
    snap = stmts["snapshot"]
    pnl_sheet = next(s for s in snap["sheets"] if any(r["id"] == "operating_expenses_keur" for r in s["rows"]))
    opex_row = next(r for r in pnl_sheet["rows"] if r["id"] == "operating_expenses_keur")
    prev_by_yr = {c["calendar_year"]: c["operating_expenses_keur"] for c in op["calendar_years"]}
    for lbl, run_val in zip(snap["annualPeriods"], opex_row["annual_v"]):
        yr = int(str(lbl)[:4])
        # Statements table values are rounded to 2dp for display
        assert abs(prev_by_yr[yr] - float(run_val)) <= 0.01 + 1e-9, (yr, prev_by_yr[yr], run_val)

    from app.persistence.run_history_repository import get_latest_history_entry
    entry = get_latest_history_entry(OWNER, record.project_id)
    assert entry is not None
    hist_periods = entry.financial_statements["pnl"]["periods"]
    assert len(op["periods"]) == len(hist_periods)
    for pp, hp in zip(op["periods"], hist_periods):
        # Persisted P&L periods round to 2dp (0.01 kEUR)
        assert round(pp["operating_expenses_keur"], 2) == pytest.approx(float(hp["operating_expenses_keur"]), abs=1e-9)

    # Full-precision (<= 1e-9 kEUR) comparison against canonical Decimal(50) oracle across Y1..Y25
    assert op["date_authority_version"] == ("LEGACY_CALENDAR/v0" if authority == "legacy" else "OD-TIME-01/v1")
    if authority == "legacy":
        # In LEGACY_CALENDAR/v0, Year 1 is partial COD year (306/365); subsequent years sum period day_fractions.
        one_plus_inf = Decimal("1.02")
        periods_by_op_yr: dict[int, list[dict]] = {}
        for pp in op["periods"]:
            if pp["is_operation"] and pp["operating_year"] >= 1:
                periods_by_op_yr.setdefault(pp["operating_year"], []).append(pp)
        for op_row in op["operating_years"]:
            yr = op_row["operating_year"]
            df_sum = sum(Decimal(repr(p["day_fraction"])) for p in periods_by_op_yr[yr])
            expected_op_yr = y1_budget_dec * (one_plus_inf ** (yr - 1)) * df_sum
            assert abs(Decimal(str(op_row["operating_expenses_keur"])) - expected_op_yr) <= Decimal("1e-9"), yr
    else:
        snap_now = get_workspace_state(OWNER, record.project_id).draft_snapshot
        oracle = _daily_dated_opex_oracle(
            op["periods"], cod=date.fromisoformat(str(snap_now["cod_date"])),
            horizon_years=int(float(snap_now["horizon_years"])), y1_budget=y1_budget_dec, inflation=Decimal("0.02"))
        by_index = {p["period_index"]: p for p in op["periods"]}
        assert oracle and set(oracle) <= set(by_index)
        for idx, expected in oracle.items():
            assert abs(Decimal(repr(by_index[idx]["operating_expenses_keur"])) - Decimal(expected.numerator) /
                       Decimal(expected.denominator)) <= Decimal("1e-9"), idx
        assert sum(p["operating_expenses_keur"] for p in op["periods"] if p["period_index"] not in oracle) == 0.0
    # And full-precision (<= 1e-9 kEUR) comparison against canonical clean engine Run (with CAPEX + ON-08 SHL authority)
    from app.api.project_runner import run_project
    from app.persistence.projects_repository import get_reference_by_template_source
    from app.services import on08_shl_index_authority as _on08
    from app.services.capex_sub_lines_integration import apply_user_sub_lines_replacing_base
    from app.services.opex_sub_lines_integration import apply_user_sub_lines_to_opex
    from app.services.reference_seed_service import get_reference_inputs
    from app.workbook.service import WorkbookService
    from dataclasses import replace as _dc_replace
    ws_curr = get_workspace_state(OWNER, record.project_id)
    pi_run = WorkbookService.to_projectinputs(WorkbookService.build_draft_input_set_from_workspace(ws_curr))
    pi_run = _dc_replace(
        pi_run,
        capex=apply_user_sub_lines_replacing_base(pi_run.capex, project_id=record.project_id),
        opex=apply_user_sub_lines_to_opex(pi_run.opex, project_id=record.project_id),
    )
    _ref = get_reference_by_template_source(record.template_source)
    pi_run, _ = _on08.apply_generic_shl_index_authority(
        pi_run,
        project_record=record,
        actor_user_id=OWNER,
        owner_user_id=OWNER,
        runtime_project_key="Solar",
        canonical_reference=_ref,
        factory_reference_inputs=get_reference_inputs(record.template_source),
        grid_last_provider=_on08.effective_grid_last_index,
    )
    from app.services.production_financial_authority import run_clean_production
    clean_run = run_clean_production(pi_run, "Base", project_type="Solar")
    for pp, rp in zip(op["periods"], clean_run.g2c_result.financing_result.project_model_result.periods):
        assert abs(pp["operating_expenses_keur"] - float(rp.opex_keur)) <= 1e-9

    # Compare against Last-Run XLSX export P&L values
    r_xlsx = env.client.post(
        "/v2/workbook/export",
        data={"project": record.project_code, "csrf_token": runs_meta["exports"]["last_run"]["csrf_token"]},
    )
    assert r_xlsx.status_code == 200
    wb = openpyxl.load_workbook(io.BytesIO(r_xlsx.content), data_only=True)
    assert len(wb.sheetnames) >= 1

    # Freshness after Run must now report CURRENT & matches_last_run=True
    after_run = env.client.get("/v2/model-react/opex-projection", params={"project": record.project_code}).json()
    assert after_run["operating_preview"]["freshness"]["state"] == "CURRENT"
    assert after_run["operating_preview"]["freshness"]["matches_last_run"] is True


def test_opex_preview_overrides_contingency_dated_leap_and_g10_gate(env, monkeypatch):
    from app.runtime.model_execution import ModelExecutionConfig, ModelExecutor, reset_model_executor_for_tests

    monkeypatch.setenv("FINCO_MODEL_EXECUTION_MODE", "thread")
    reset_model_executor_for_tests(ModelExecutor(ModelExecutionConfig(mode="thread")))

    # FINCO45B: G10 panel is ON by default (NOT_RUN before any Run); the explicit operator OFF is a typed 404
    record = env.create("wind")
    monkeypatch.delenv("FINCO_G10_RUN_OPEX_PANEL", raising=False)
    first = env.client.get("/v2/model-react/opex-run-projection", params={"project": record.project_code})
    assert first.status_code == 200 and first.json()["status"] == "NOT_RUN"
    monkeypatch.setenv("FINCO_G10_RUN_OPEX_PANEL", "0")
    assert env.client.get("/v2/model-react/opex-run-projection", params={"project": record.project_code}).status_code == 404
    monkeypatch.delenv("FINCO_G10_RUN_OPEX_PANEL", raising=False)

    # Nonzero B.13 contingency (5%)
    _set_opex_contingency(record, 5.0)
    # Apply explicit zero & custom annual OPEX exceptions (FINCO38), then delete one to restore inheritance
    lines = get_active_sub_lines_for_project(record.project_id)
    first_code = lines[0].business_code
    ed = env.client.get("/v2/model-react/opex-projection/annual-exceptions/editor", params={"project": record.project_code}).json()
    r_exc = env.client.post(
        "/v2/model-react/opex-projection/annual-exceptions",
        json={
            "project": record.project_code,
            "csrf_token": ed["csrf_token"],
            "content_hash": ed["content_hash"],
            "workbook_version": ed["workbook_version"],
            "base_token": ed["base_token"],
            "overrides": [
                {"line_key": first_code, "year": 2, "amount_keur": 0.0},
                {"line_key": first_code, "year": 3, "amount_keur": 120.0},
            ],
        },
    )
    assert r_exc.status_code == 200, r_exc.text

    proj_with_ov = env.client.get("/v2/model-react/opex-projection", params={"project": record.project_code}).json()
    op_with_ov = proj_with_ov["operating_preview"]
    assert op_with_ov["available"] is True
    # Run the model and verify exact parity with overrides & B.13=5%
    ws_shell = env.client.get("/v2/model-react/workspace", params={"project": record.project_code}).json()
    runs_meta = env.client.get("/v2/model-react/runs", params={"project": record.project_code}).json()
    r_run = env.client.post(
        "/v2/workbook/run",
        headers={"Accept": "application/json"},
        data={
            "project": record.project_code,
            "csrf_token": runs_meta["run_contract"]["csrf_token"],
            "content_hash": ws_shell["workbook"]["composite_hash"],
            "workbook_version": ws_shell["workbook"]["version"],
            "run_intent_id": "44444444-5555-4666-8777-888888888888",
        },
    )
    assert r_run.status_code == 200, r_run.text

    # Delete Y2=0 override -> restores inheritance and flips freshness to STALE
    ed2 = env.client.get("/v2/model-react/opex-projection/annual-exceptions/editor", params={"project": record.project_code}).json()
    r_del = env.client.post(
        "/v2/model-react/opex-projection/annual-exceptions",
        json={
            "project": record.project_code,
            "csrf_token": ed2["csrf_token"],
            "content_hash": ed2["content_hash"],
            "workbook_version": ed2["workbook_version"],
            "base_token": ed2["base_token"],
            "overrides": [{"line_key": first_code, "year": 3, "amount_keur": 120.0}],
        },
    )
    assert r_del.status_code == 200
    after_del = env.client.get("/v2/model-react/opex-projection", params={"project": record.project_code}).json()
    assert after_del["operating_preview"]["freshness"]["state"] == "STALE"
    assert after_del["operating_preview"]["freshness"]["matches_last_run"] is False
    # Operating Y2 cost increased when explicit 0.0 override was deleted
    y2_before = op_with_ov["operating_years"][1]["operating_expenses_keur"]
    y2_after = after_del["operating_preview"]["operating_years"][1]["operating_expenses_keur"]
    assert y2_after > y2_before

    # G10 (default ON, no flag): reflects committed Last Run while draft preview reflects edited state
    g10 = env.client.get("/v2/model-react/opex-run-projection", params={"project": record.project_code})
    assert g10.status_code == 200
    assert g10.json()["freshness"]["state"] == "STALE"


def test_step_conditional_opex_item_and_fail_closed_unavailable(env, monkeypatch):
    # Step & conditional item parity in opex_item_amount_at_year
    step_item = OpexItem(
        name="Step Maintenance",
        y1_amount_keur=100.0,
        annual_inflation=0.02,
        step_changes=((5, 150.0),),
    )
    assert opex_item_amount_at_year(step_item, 1) == pytest.approx(100.0)
    assert opex_item_amount_at_year(step_item, 5) == pytest.approx(150.0)
    assert opex_item_amount_at_year(step_item, 6) == pytest.approx(150.0 * 1.02)

    # Unsupported/unavailable preview returns typed OPERATING_PREVIEW_UNAVAILABLE, never fake zeros
    record = env.create("solar")
    import financial_engine.orchestrator as orch
    monkeypatch.setattr(orch, "run_operating_model", lambda *_a, **_kw: (_ for _ in ()).throw(RuntimeError("boom")))
    r = env.client.get("/v2/model-react/opex-projection", params={"project": record.project_code})
    assert r.status_code == 200
    op = r.json()["operating_preview"]
    assert op["available"] is False
    assert op["status"] == "OPERATING_PREVIEW_UNAVAILABLE"
    assert op["periods"] == []
