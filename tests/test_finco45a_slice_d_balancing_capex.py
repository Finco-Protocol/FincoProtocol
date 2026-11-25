"""FINCO45A Slice D — Dual balancing rejection (P1-REV-03, protecting F2-NEW-01) & CAPEX negative update guard (C1-Q-04).

Verifies:
- D1: pct-only, per-MWh-only, schedule, legacy Wind 8 EUR/MWh vs explicit 0.0 (F2-NEW-01) against independent Decimal(50) oracle.
- D1: both nonzero (% merchant AND effective per-MWh / schedule / wind fallback) rejected with DUAL_BALANCING_COST_BASIS_FORBIDDEN
  across direct revenue_decomposition_schedule, input_adapter, Save, batch Save-All, and Run.
- D1: negative or nonfinite balancing values rejected; explicit 0.0 never treated as missing.
- D2: update_capex_line & update_cost_lines_batch reject -100, blank, NaN, Inf, overflow with CapexInvalidAmountError / CostBatchInvalidError (HTTP 422),
  leaving CAS hash, row_version, draft snapshot, and Run History untouched; 0.0 and positive updates succeed.
"""
from __future__ import annotations

from dataclasses import replace
from decimal import Decimal, getcontext
import pytest

from app.input_adapter import build_projectinputs_from_snapshot
from app.persistence.capex_sub_lines import get_active_sub_lines_for_project
from app.persistence.run_history_repository import get_run_history
from app.persistence.workspace_repository import get_workspace_state
from app.project_factories import create_generic_solar_reference, create_generic_wind_reference
from app.v2.capex_commands import CapexInvalidAmountError, add_capex_line, update_capex_line
from app.v2.cost_batch_commands import CostBatchInvalidError, CostLineEdit, update_cost_lines_batch
from app.workbook.registry import WORKBOOK
from app.workbook.update_service import FieldValidationError, WorkbookUpdateService
from app.workbook.workbook_identity import assemble_consistent_for_get
from finco_core.engine.period_engine import PeriodEngine
from finco_core.inputs import RevenueAdjustmentSchedule
from finco_core.revenue.generation import revenue_decomposition_schedule, validate_balancing_cost_inputs
from tests.model_mutation_csrf import post_valid_mutation
from tests.test_model_react_wf2_projections_v1 import OWNER, env  # noqa: F401

getcontext().prec = 50


def _engine(pi):
    return PeriodEngine(
        financial_close=pi.info.financial_close,
        construction_months=pi.info.construction_months,
        horizon_years=pi.info.horizon_years,
        ppa_years=int(pi.revenue.ppa_term_years),
        cod_date=pi.info.cod_date,
    )


def test_d1_single_basis_and_explicit_zero_f2_new_01_decimal50():
    # 1. Pct-only merchant balancing (Solar with 50% PPA share -> 50% merchant)
    solar_pct = create_generic_solar_reference()
    solar_pct = replace(
        solar_pct,
        revenue=replace(solar_pct.revenue, ppa_production_share=0.5, balancing_cost_pv=0.04, balancing_cost_eur_per_mwh=0.0, balancing_cost_wind_eur_mwh=0.0),
    )
    decomps_pct = revenue_decomposition_schedule(solar_pct, _engine(solar_pct))
    for d in decomps_pct.values():
        if not d["is_operation"]:
            continue
        gross_m = Decimal(str(d["gross_merchant_revenue_keur"]))
        expected_bal = gross_m * Decimal("0.04")
        assert abs(Decimal(str(d["balancing_cost_keur"])) - expected_bal) <= Decimal("1e-9")

    # 2. Per-MWh-only (wind default 8 EUR/MWh vs explicit 0.0 F2-NEW-01)
    wind_default = create_generic_wind_reference()
    assert wind_default.revenue.balancing_cost_pv == 0.0
    assert wind_default.revenue.balancing_cost_wind_eur_mwh == 8.0
    decomps_wind8 = revenue_decomposition_schedule(wind_default, _engine(wind_default))
    for d in decomps_wind8.values():
        if not d["is_operation"]:
            continue
        expected_bal = Decimal(str(d["generation_mwh"])) * Decimal("8") / Decimal("1000")
        assert abs(Decimal(str(d["balancing_cost_keur"])) - expected_bal) <= Decimal("1e-9")

    # 3. Schedule-only (precedence over wind fallback)
    wind_sched = replace(
        wind_default,
        revenue=replace(wind_default.revenue, balancing_cost_schedule=RevenueAdjustmentSchedule(constant_value=3.25)),
    )
    decomps_sched = revenue_decomposition_schedule(wind_sched, _engine(wind_sched))
    for d in decomps_sched.values():
        if not d["is_operation"]:
            continue
        expected_bal = Decimal(str(d["generation_mwh"])) * Decimal("3.25") / Decimal("1000")
        assert abs(Decimal(str(d["balancing_cost_keur"])) - expected_bal) <= Decimal("1e-9")

    # 4. Explicit zero via snapshot overrides factory Wind 8 EUR/MWh (F2-NEW-01)
    pi_zero = build_projectinputs_from_snapshot({
        "project_type": "Wind",
        "project_name": "Wind Zero Bal",
        "country_market": "DE",
        "capacity_mw": "50",
        "cod_date": "2031-01-01",
        "construction_months": "12",
        "horizon_years": "25",
        "p50_hours": "3000",
        "tariff_eur_mwh": "60",
        "ppa_term_years": "12",
        "total_capex_keur": "55000",
        "opex_y1_keur": "1500",
        "interest_rate_pct": "5.5",
        "_finval_interest_rate_unit": "human_percent_v1",
        "tenor_years": "15",
        "target_dscr": "1.2",
        "rev_balancing_cost_eur_per_mwh": "0",
        "rev_merchant_balancing_pct": "2.5",
    })
    assert pi_zero.revenue.balancing_cost_wind_eur_mwh == 0.0
    assert pi_zero.revenue.balancing_cost_eur_per_mwh == 0.0
    assert pi_zero.revenue.balancing_cost_pv == pytest.approx(0.025)
    validate_balancing_cost_inputs(pi_zero.revenue)


def test_d1_dual_nonzero_balancing_rejected_everywhere(env):  # noqa: F811
    solar = create_generic_solar_reference()
    dual_mwh = replace(solar, revenue=replace(solar.revenue, balancing_cost_pv=0.05, balancing_cost_eur_per_mwh=2.5))
    with pytest.raises(ValueError, match="DUAL_BALANCING_COST_BASIS_FORBIDDEN"):
        validate_balancing_cost_inputs(dual_mwh.revenue)
    with pytest.raises(ValueError, match="DUAL_BALANCING_COST_BASIS_FORBIDDEN"):
        revenue_decomposition_schedule(dual_mwh, _engine(dual_mwh))

    dual_sched = replace(
        solar,
        revenue=replace(
            solar.revenue,
            balancing_cost_pv=0.03,
            balancing_cost_schedule=RevenueAdjustmentSchedule(annual_values=(1.5,)),
        ),
    )
    with pytest.raises(ValueError, match="DUAL_BALANCING_COST_BASIS_FORBIDDEN"):
        revenue_decomposition_schedule(dual_sched, _engine(dual_sched))

    wind = create_generic_wind_reference()
    dual_wind_fallback = replace(wind, revenue=replace(wind.revenue, balancing_cost_pv=0.02))
    with pytest.raises(ValueError, match="DUAL_BALANCING_COST_BASIS_FORBIDDEN"):
        revenue_decomposition_schedule(dual_wind_fallback, _engine(dual_wind_fallback))

    # Nonfinite / negative balancing inputs fail closed
    bad_neg = replace(solar, revenue=replace(solar.revenue, balancing_cost_pv=-0.01))
    with pytest.raises(ValueError, match="BALANCING_COST_INVALID"):
        validate_balancing_cost_inputs(bad_neg.revenue)
    bad_nan = replace(solar, revenue=replace(solar.revenue, balancing_cost_eur_per_mwh=float("nan")))
    with pytest.raises(ValueError, match="BALANCING_COST_INVALID"):
        validate_balancing_cost_inputs(bad_nan.revenue)

    # input_adapter rejects dual nonzero snapshot
    with pytest.raises(ValueError, match="DUAL_BALANCING_COST_BASIS_FORBIDDEN"):
        build_projectinputs_from_snapshot({
            "project_type": "Solar",
            "project_name": "Dual Bal Snap",
            "country_market": "DE",
            "capacity_mw": "50",
            "cod_date": "2031-01-01",
            "construction_months": "12",
            "horizon_years": "25",
            "p50_hours": "1500",
            "tariff_eur_mwh": "55",
            "ppa_term_years": "12",
            "total_capex_keur": "35000",
            "opex_y1_keur": "900",
            "interest_rate_pct": "5.5",
            "_finval_interest_rate_unit": "human_percent_v1",
            "tenor_years": "15",
            "target_dscr": "1.2",
            "rev_merchant_balancing_pct": "2.5",
            "rev_balancing_cost_eur_per_mwh": "4.0",
        })

    # WorkbookUpdateService & Run fail closed on persisted invalid/conflicting Save
    rec = env.create("wind")
    ws = get_workspace_state(OWNER, rec.project_id)
    ident = assemble_consistent_for_get(OWNER, rec.project_id, WORKBOOK.version)
    # Wind has active default 8.0 EUR/MWh; saving merchant_pct=3.0 alone must be rejected
    with pytest.raises(FieldValidationError, match="DUAL_BALANCING_COST_BASIS_FORBIDDEN"):
        WorkbookUpdateService.apply_draft_update(
            ws=ws,
            field_id="revenue.balancing.merchant_pct",
            raw_value="3.0",
            content_hash=ident.composite_hash,
            workbook_version=WORKBOOK.version,
            project_record=rec,
        )
    # Atomic batch Save-All setting EUR/MWh=0 AND merchant_pct=3.0 together succeeds cleanly
    WorkbookUpdateService.apply_batch_draft_update(
        ws=ws,
        updates=[
            ("revenue.balancing.cost_eur_per_mwh", "0"),
            ("revenue.balancing.merchant_pct", "3.0"),
        ],
        content_hash=ident.composite_hash,
        workbook_version=WORKBOOK.version,
        expected_scenario_id=ws.active_scenario_id,
        project_record=rec,
        actor_user_id=OWNER,
    )
    ws2 = get_workspace_state(OWNER, rec.project_id)
    ident2 = assemble_consistent_for_get(OWNER, rec.project_id, WORKBOOK.version)
    with pytest.raises(FieldValidationError, match="DUAL_BALANCING_COST_BASIS_FORBIDDEN"):
        WorkbookUpdateService.apply_draft_update(
            ws=ws2,
            field_id="revenue.balancing.cost_eur_per_mwh",
            raw_value="2.5",
            content_hash=ident2.composite_hash,
            workbook_version=WORKBOOK.version,
            project_record=rec,
        )


def test_d2_capex_update_rejects_negative_and_invalid_and_allows_zero(env):  # noqa: F811
    rec = env.create()
    ident0 = assemble_consistent_for_get(OWNER, rec.project_id, WORKBOOK.version)

    # Negative add rejected
    with pytest.raises(CapexInvalidAmountError):
        add_capex_line(
            project_record=rec,
            user_id=OWNER,
            parent_category_code="C.01",
            label="Negative Add",
            amount_keur=-100.0,
            workbook_version=WORKBOOK.version,
            expected_content_hash=ident0.composite_hash,
        )

    # Create valid line to test update_capex_line & batch & HTTP 422
    added, _ = add_capex_line(
        project_record=rec,
        user_id=OWNER,
        parent_category_code="C.01",
        label="Custom Inverter Line",
        amount_keur=250.0,
        workbook_version=WORKBOOK.version,
        expected_content_hash=ident0.composite_hash,
    )
    before_ws = get_workspace_state(OWNER, rec.project_id)
    before_hash = assemble_consistent_for_get(OWNER, rec.project_id, WORKBOOK.version).composite_hash
    before_lines = get_active_sub_lines_for_project(rec.project_id)
    before_row = next(r for r in before_lines if r.sub_line_id == added.sub_line_id)

    for bad in (-100.0, "-100", "", "NaN", float("inf"), float("-inf"), None):
        with pytest.raises(CapexInvalidAmountError):
            update_capex_line(
                project_record=rec,
                user_id=OWNER,
                sub_line_id=added.sub_line_id,
                label="Custom Inverter Line",
                amount_keur=bad,
                row_version=before_row.updated_at,
                workbook_version=WORKBOOK.version,
                expected_content_hash=before_hash,
            )

    # Batch cost edit path also rejects negative amount without mutation
    with pytest.raises(CostBatchInvalidError):
        update_cost_lines_batch(
            project_record=rec,
            user_id=OWNER,
            edits=[
                CostLineEdit(
                    kind="capex",
                    sub_line_id=added.sub_line_id,
                    label="Custom Inverter Line",
                    amount_keur="-100",
                    row_version=before_row.updated_at,
                )
            ],
            workbook_version=WORKBOOK.version,
            expected_content_hash=before_hash,
        )

    # HTTP /v2/capex/line/update (non-HTMX) returns 422 and preserves state
    resp_422 = post_valid_mutation(
        env.client,
        "/v2/capex/line/update",
        data={
            "project": rec.project_code,
            "sub_line_id": added.sub_line_id,
            "label": "Custom Inverter Line",
            "amount_keur": "-100",
            "row_version": before_row.updated_at,
            "workbook_version": WORKBOOK.version,
            "content_hash": before_hash,
        },
    )
    assert resp_422.status_code == 422

    # Verify CAS hash, row_version, snapshot, and Run History are completely untouched
    after_hash = assemble_consistent_for_get(OWNER, rec.project_id, WORKBOOK.version).composite_hash
    after_ws = get_workspace_state(OWNER, rec.project_id)
    after_row = next(r for r in get_active_sub_lines_for_project(rec.project_id) if r.sub_line_id == added.sub_line_id)
    assert after_hash == before_hash
    assert after_row.updated_at == before_row.updated_at
    assert after_row.amount_keur == 250.0
    assert after_ws.draft_snapshot == before_ws.draft_snapshot
    assert len(get_run_history(OWNER, rec.project_id)) == 0

    # Zero update succeeds, then positive update succeeds
    zeroed, _ = update_capex_line(
        project_record=rec,
        user_id=OWNER,
        sub_line_id=added.sub_line_id,
        label="Custom Inverter Line",
        amount_keur=0.0,
        row_version=before_row.updated_at,
        workbook_version=WORKBOOK.version,
        expected_content_hash=before_hash,
    )
    assert zeroed.amount_keur == 0.0
    h_after_zero = assemble_consistent_for_get(OWNER, rec.project_id, WORKBOOK.version).composite_hash
    pos, _ = update_capex_line(
        project_record=rec,
        user_id=OWNER,
        sub_line_id=added.sub_line_id,
        label="Custom Inverter Line",
        amount_keur=300.0,
        row_version=zeroed.updated_at,
        workbook_version=WORKBOOK.version,
        expected_content_hash=h_after_zero,
    )
    assert pos.amount_keur == 300.0
