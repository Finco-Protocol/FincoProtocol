"""FINCO42 — BESS independent 40-digit Decimal physical/commercial/financial oracles & closed-gate lifecycle proof."""
from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, localcontext
import json
import math

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.auth import COOKIE_NAME, create_session_token
from app.bess_commercial_candidate.contracts import (
    ACTIVATION_ENABLED as COMMERCIAL_ACTIVATION_ENABLED,
    BessCommercialError,
    Decision,
    require_release as require_commercial_release,
)
from app.product_capability import PRODUCT_CAPABILITIES, ProductStatus
from app.services import bess_standalone_candidate as b2_cand
from app.services.production_financial_authority import (
    CleanProductionRunUnavailable,
    classify_production_authority,
    run_clean_production,
)
from app.workbook import bess_config
from domain.bess.contracts import BessInputError, parse_configuration
from domain.bess.dispatch import evaluate as evaluate_bess_physics
from domain.bess.settlement import aggregate_to_financial_periods
from finco_core.engine.date_authority import DATE_AUTHORITY_VERSION
from finco_core.engine.period_engine import PeriodEngine, PeriodFrequency
from financial_engine.adapters.project_inputs import from_project_inputs
from financial_engine.bess import require_native_separation
from financial_engine.orchestrator import run_operating_model


# ---------------------------------------------------------------------------
# Independent 40-digit Decimal Physical & Commercial Oracle (ZERO domain.bess reuse)
# ---------------------------------------------------------------------------

def _d(x) -> Decimal:
    return Decimal(str(x))


def _make_10mw_20mwh_daily_config(
    *,
    start_iso: str = "2028-01-01T00:00:00Z",
    end_iso: str = "2030-01-01T00:00:00Z",
    buy_price: float = 35.0,
    sell_price: float = 115.0,
    charge_mw: float = 10.0,
    discharge_mw: float = 9.025,
    aux_mw: float = 0.05,
    import_charge: float = 2.0,
    export_charge: float = 1.0,
    var_om_eur_per_dc_mwh: float = 1.5,
    initial_mwh: float = 0.0,
    terminal_mwh: float = 0.0,
    events: list[dict] | None = None,
) -> dict:
    """Analytical synthetic 10 MW / 20 MWh (2.0 h duration, 95% x 95% = 90.25% RTE) BESS config.

    Notice: charging 10 MW for 1h at 95% eff adds +9.5 MWh DC; discharging 9.025 MW AC for 1h
    at 95% eff removes 9.025 / 0.95 = 9.5 MWh DC -> exact 0 net daily SoC delta!
    These are synthetic verification parameters, NOT production defaults.
    """
    points = []
    for hour in range(24):
        if hour == 2:
            c_mw, d_mw = charge_mw, 0.0
        elif hour == 18:
            c_mw, d_mw = 0.0, discharge_mw
        else:
            c_mw, d_mw = 0.0, 0.0
        points.append(
            {
                "utc_hour": hour,
                "available": True,
                "charge_mw": c_mw,
                "discharge_mw": d_mw,
                "auxiliary_grid_mw": aux_mw,
                "buy_price_eur_mwh": buy_price,
                "sell_price_eur_mwh": sell_price,
                "import_charge_eur_mwh": import_charge,
                "export_charge_eur_mwh": export_charge,
                "source_ref": "finco-synthetic-hourly-assumption",
            }
        )
    return {
        "version": 1,
        "configuration": {
            "version": 1,
            "technology": "STANDALONE_GRID_BESS",
            "time_convention": "UTC_HOURLY_END_EXCLUSIVE",
            "degradation_convention": "ADDITIVE_CALENDAR_ACT365_AND_CYCLE",
            "efc_convention": "DC_TWO_WAY_OVER_2_NOMINAL_USABLE",
            "price_unit": "EUR_PER_MWH",
            "settlement_policy": "CANONICAL_FINANCIAL_PERIOD_END",
            "information_policy": "USER_DECLARED_EX_ANTE_FIXED_PLAN",
            "outage_policy": "SUSPEND_FIXED_PLAN_VALIDATE_EXPLICIT",
            "cohort_policy": "AGGREGATE_DC_POOL_NOMINAL_CYCLE_ALLOCATION",
            "source_ref": "finco-synthetic-10mw-20mwh-plan",
            "start": start_iso,
            "end": end_iso,
            "dispatch_mode": "FIXED_DAILY_PLAN",
            "battery": {
                "discharge_power_mw": 10.0,
                "charge_power_mw": 10.0,
                "grid_import_limit_mw": 10.5,
                "grid_export_limit_mw": 10.0,
                "installed_energy_mwh": 24.0,
                "usable_energy_mwh": 20.0,
                "duration_hours": 2.0,
                "charge_efficiency": 0.95,
                "discharge_efficiency": 0.95,
                "round_trip_efficiency": 0.9025,
                "soc_min": 0.0,
                "soc_max": 1.0,
                "initial_energy_mwh": initial_mwh,
                "terminal_energy_mwh": terminal_mwh,
                "calendar_loss_per_year": 0.01,
                "cycle_loss_per_efc": 0.0001,
                "minimum_soh": 0.70,
                "useful_life_years": 15,
            },
            "dispatch": points,
            "outages": [],
            "events": events or [],
        },
        "variable_om_eur_per_dc_mwh": var_om_eur_per_dc_mwh,
    }


def _oracle_hourly_bess_and_periods(raw: dict, operating_periods) -> dict:
    """Pure 40-digit Decimal hourly energy balance & period aggregation oracle."""
    with localcontext() as ctx:
        ctx.prec = 40
        cfg = raw["configuration"]
        bat = cfg["battery"]
        start = datetime.fromisoformat(cfg["start"].replace("Z", "+00:00"))
        end = datetime.fromisoformat(cfg["end"].replace("Z", "+00:00"))
        total_hours = int((end - start).total_seconds() // 3600)
        by_hour = {p["utc_hour"]: p for p in cfg["dispatch"]}

        eta_c = _d(bat["charge_efficiency"])
        eta_d = _d(bat["discharge_efficiency"])
        usable_nom = _d(bat["usable_energy_mwh"])
        cal_per_hour = _d(bat["calendar_loss_per_year"]) / Decimal(8760)
        cyc_loss = _d(bat["cycle_loss_per_efc"])
        var_om_rate = _d(raw["variable_om_eur_per_dc_mwh"])

        soh = Decimal(1)
        soc = _d(bat["initial_energy_mwh"])
        max_residual = Decimal(0)

        hour_rows = []
        t = start
        for _ in range(total_hours):
            pt = by_hour[t.hour]
            c_mw = _d(pt["charge_mw"])
            d_mw = _d(pt["discharge_mw"])
            aux_mw = _d(pt["auxiliary_grid_mw"])
            buy_p = _d(pt["buy_price_eur_mwh"])
            sell_p = _d(pt["sell_price_eur_mwh"])
            imp_c = _d(pt["import_charge_eur_mwh"])
            exp_c = _d(pt["export_charge_eur_mwh"])

            dc_in = c_mw * eta_c
            dc_out = d_mw / eta_d
            closing = soc + dc_in - dc_out
            residual = abs((soc + dc_in - dc_out) - closing)
            if residual > max_residual:
                max_residual = residual

            throughput = dc_in + dc_out
            efc = throughput / (Decimal(2) * usable_nom)
            soh = soh - cal_per_hour - efc * cyc_loss
            assert Decimal(0) <= closing <= usable_nom * soh

            hour_rows.append(
                {
                    "end": t + timedelta(hours=1),
                    "grid_import_mwh": c_mw + aux_mw,
                    "grid_export_mwh": d_mw,
                    "throughput_dc_mwh": throughput,
                    "gross_sale_keur": (d_mw * sell_p) / Decimal(1000),
                    "charge_cost_keur": (c_mw * buy_p) / Decimal(1000),
                    "aux_cost_keur": (aux_mw * buy_p) / Decimal(1000),
                    "import_fee_keur": ((c_mw + aux_mw) * imp_c) / Decimal(1000),
                    "export_fee_keur": (d_mw * exp_c) / Decimal(1000),
                    "var_om_keur": (throughput * var_om_rate) / Decimal(1000),
                    "soh": soh,
                }
            )
            soc = closing
            t += timedelta(hours=1)

        assert soc == _d(bat["terminal_energy_mwh"])

        period_totals = {}
        for op in operating_periods:
            p_start = datetime(op.start_date.year, op.start_date.month, op.start_date.day, tzinfo=timezone.utc)
            p_end = datetime(op.end_date.year, op.end_date.month, op.end_date.day, tzinfo=timezone.utc)
            slice_h = [h for h in hour_rows if p_start < h["end"] <= p_end]
            period_totals[op.index] = {
                "hours": len(slice_h),
                "gross_sale_keur": sum((h["gross_sale_keur"] for h in slice_h), Decimal(0)),
                "charge_cost_keur": sum((h["charge_cost_keur"] for h in slice_h), Decimal(0)),
                "aux_cost_keur": sum((h["aux_cost_keur"] for h in slice_h), Decimal(0)),
                "import_fee_keur": sum((h["import_fee_keur"] for h in slice_h), Decimal(0)),
                "export_fee_keur": sum((h["export_fee_keur"] for h in slice_h), Decimal(0)),
                "var_om_keur": sum((h["var_om_keur"] for h in slice_h), Decimal(0)),
                "grid_export_mwh": sum((h["grid_export_mwh"] for h in slice_h), Decimal(0)),
                "ending_soh": slice_h[-1]["soh"],
            }
        return {"total_hours": total_hours, "max_residual": max_residual, "periods": period_totals, "ending_soh": soh}


# ---------------------------------------------------------------------------
# 1. Physical & Commercial 10 MW / 20 MWh Oracle + Leap Year + Refusals (4A)
# ---------------------------------------------------------------------------

def test_bess_physical_commercial_10mw_20mwh_decimal_oracle_and_leap_year():
    periods = PeriodEngine(date(2027, 1, 1), 12, 2, 0, cod_date=date(2028, 1, 1)).periods()
    op_periods = [p for p in periods if p.is_operation]
    raw = _make_10mw_20mwh_daily_config(
        start_iso=op_periods[0].start_date.isoformat() + "T00:00:00Z",
        end_iso=op_periods[-1].end_date.isoformat() + "T00:00:00Z",
    )
    cfg = parse_configuration(json.dumps(raw["configuration"]))
    res = evaluate_bess_physics(cfg)
    assert len(res.hours) == 730 * 24  # 2028 leap (366d) + 2029 non-leap ending 2029-12-31 (364d)
    assert res.maximum_energy_residual_mwh == Decimal(0)

    # Also verify exact full 2-year leap + non-leap physical horizon (366 + 365 days = 17,544 hours)
    raw_full = _make_10mw_20mwh_daily_config(start_iso="2028-01-01T00:00:00Z", end_iso="2030-01-01T00:00:00Z")
    res_full = evaluate_bess_physics(parse_configuration(json.dumps(raw_full["configuration"])))
    assert len(res_full.hours) == (366 + 365) * 24
    assert res_full.maximum_energy_residual_mwh == Decimal(0)

    settled = aggregate_to_financial_periods(res, periods)
    oracle = _oracle_hourly_bess_and_periods(raw, op_periods)

    assert len(res.hours) == oracle["total_hours"]
    assert abs(res.hours[-1].soh_closing - oracle["ending_soh"]) <= Decimal("1e-18")
    for s in settled:
        exp = oracle["periods"][s.period_index]
        assert s.hours == exp["hours"]
        assert abs(s.gross_sale_revenue_keur - exp["gross_sale_keur"]) <= Decimal("1e-12")
        assert abs(s.charging_purchase_cost_keur - exp["charge_cost_keur"]) <= Decimal("1e-12")
        assert abs(s.auxiliary_purchase_cost_keur - exp["aux_cost_keur"]) <= Decimal("1e-12")
        assert abs(s.import_charges_keur - exp["import_fee_keur"]) <= Decimal("1e-12")
        assert abs(s.export_charges_keur - exp["export_fee_keur"]) <= Decimal("1e-12")
        assert abs(s.grid_export_mwh - exp["grid_export_mwh"]) <= Decimal("1e-12")

    # Commercial candidate remains strictly release-closed & Decision has only OPEN
    assert COMMERCIAL_ACTIVATION_ENABLED is False
    assert list(Decision) == [Decision.OPEN]
    with pytest.raises(BessCommercialError, match="BESS_COMMERCIAL_RELEASE_CLOSED"):
        require_commercial_release()


def test_bess_physical_infeasibility_and_augmentation_inventory_refusals():
    # Negative price refused at schema parser
    neg = _make_10mw_20mwh_daily_config(buy_price=-1.0)
    with pytest.raises(BessInputError):
        parse_configuration(json.dumps(neg["configuration"]))

    # Simultaneous charge + discharge refused by physics
    sim = _make_10mw_20mwh_daily_config()
    sim["configuration"]["dispatch"][2]["discharge_mw"] = 1.0
    with pytest.raises(BessInputError, match="BESS_SIMULTANEOUS"):
        evaluate_bess_physics(parse_configuration(json.dumps(sim["configuration"])))

    # Over-power charge refused
    over_p = _make_10mw_20mwh_daily_config()
    over_p["configuration"]["dispatch"][2]["charge_mw"] = 11.0
    with pytest.raises(BessInputError, match="BESS_POWER"):
        evaluate_bess_physics(parse_configuration(json.dumps(over_p["configuration"])))

    # SoC underflow (discharge from empty 0 MWh battery before charging)
    under = _make_10mw_20mwh_daily_config()
    under["configuration"]["dispatch"][0]["discharge_mw"] = 5.0
    with pytest.raises(BessInputError, match="BESS_CLOSING_SOC"):
        evaluate_bess_physics(parse_configuration(json.dumps(under["configuration"])))

    # Terminal SoC mismatch refused
    term = _make_10mw_20mwh_daily_config(initial_mwh=0.0, terminal_mwh=1.0)
    with pytest.raises(BessInputError, match="BESS_TERMINAL_SOC"):
        evaluate_bess_physics(parse_configuration(json.dumps(term["configuration"])))

    # Post-COD augmentation: physical dispatch accepts resolved tax_book_policy=UNRESOLVED,
    # while canonical financial boundary strictly refuses with BESS_POST_COD_ACCOUNTING_RELEASE_CLOSED
    from tests.test_m7_bess_physics import event as m7_event
    aug = _make_10mw_20mwh_daily_config(events=[m7_event()])
    aug_res = evaluate_bess_physics(parse_configuration(json.dumps(aug["configuration"])))
    assert aug_res.lifecycle_capex_keur > Decimal(0)
    from financial_engine.bess import operating_evidence
    periods = PeriodEngine(date(2027, 1, 1), 12, 2, 0, cod_date=date(2028, 1, 1)).periods()
    with pytest.raises(ValueError, match="BESS_POST_COD_ACCOUNTING_RELEASE_CLOSED"):
        operating_evidence(json.dumps(aug), periods)

    # Nonzero initial/terminal inventory refused at financial boundary
    inv = _make_10mw_20mwh_daily_config(initial_mwh=1.0, terminal_mwh=1.0)
    with pytest.raises(ValueError, match="BESS_INVENTORY_FINANCIAL_BASIS_UNRESOLVED"):
        operating_evidence(json.dumps(inv), periods)


# ---------------------------------------------------------------------------
# 2. Financial Economics & Canonical Integration Oracle (4B)
# ---------------------------------------------------------------------------

def _build_10mw_project_inputs(monkeypatch, *, buy_price: float = 35.0, sell_price: float = 115.0, zero_dispatch: bool = False):
    monkeypatch.setattr(bess_config, "ACTIVATION_ENABLED", True)
    p = bess_config.native_base_inputs()
    p = replace(
        p,
        info=replace(
            p.info,
            financial_close=date(2027, 1, 1),
            construction_months=12,
            cod_date=date(2028, 1, 1),
            horizon_years=2,
        ),
        technical=replace(p.technical, capacity_mw=10.0),
        capex=replace(
            p.capex,
            epc_contract=replace(p.capex.epc_contract, amount_keur=240.0),
            production_units=replace(p.capex.production_units, amount_keur=40.0),
            epc_other=replace(p.capex.epc_other, amount_keur=40.0),
        ),
        opex=(replace(p.opex[0], y1_amount_keur=10.0, annual_inflation=0.0),),
        financing=replace(
            p.financing,
            share_capital_keur=10.0,
            senior_tenor_years=2,
            gearing_ratio=0.5,
            senior_debt_interest_config=None,
        ),
    )
    periods = PeriodEngine(p.info.financial_close, 12, 2, 0, cod_date=p.info.cod_date).periods()
    op_periods = [q for q in periods if q.is_operation]
    raw = _make_10mw_20mwh_daily_config(
        start_iso=op_periods[0].start_date.isoformat() + "T00:00:00Z",
        end_iso=op_periods[-1].end_date.isoformat() + "T00:00:00Z",
        buy_price=buy_price,
        sell_price=sell_price,
        charge_mw=0.0 if zero_dispatch else 10.0,
        discharge_mw=0.0 if zero_dispatch else 9.025,
        aux_mw=0.0 if zero_dispatch else 0.05,
    )
    return bess_config.apply_config(p, json.dumps(raw)), raw, op_periods


def test_bess_financial_10mw_20mwh_oracle_stress_and_no_double_charging(monkeypatch):
    # Base 10 MW / 20 MWh case
    p_base, raw_base, op_periods = _build_10mw_project_inputs(monkeypatch, buy_price=35.0, sell_price=115.0)
    oracle = _oracle_hourly_bess_and_periods(raw_base, op_periods)

    # Check operating model period-by-period against independent Decimal oracle (tolerance < 1e-7 kEUR)
    op_by_dates = {(op.start_date, op.end_date): oracle["periods"][op.index] for op in op_periods}
    op_res = run_operating_model(from_project_inputs(p_base))
    for period in op_res.periods:
        if not period.is_operation:
            assert period.revenue_keur == 0.0 and period.opex_keur == 0.0
            continue
        exp = op_by_dates[(period.period_start, period.period_end)]
        fixed_opex = _d(period.day_fraction) * _d(10.0)
        exp_opex = (
            exp["charge_cost_keur"]
            + exp["aux_cost_keur"]
            + exp["import_fee_keur"]
            + exp["export_fee_keur"]
            + exp["var_om_keur"]
            + fixed_opex
        )
        assert abs(_d(period.revenue_keur) - exp["gross_sale_keur"]) <= Decimal("1e-7")
        assert abs(_d(period.opex_keur) - exp_opex) <= Decimal("1e-7")
        assert abs(_d(period.ebitda_keur) - (exp["gross_sale_keur"] - exp_opex)) <= Decimal("1e-7")

    # Canonical G2C + Statements + Sources=Uses + Operating BS
    clean_base = run_clean_production(p_base, project_type="Storage")
    fr = clean_base.g2c_result.financing_result
    assert fr.final_senior_commitment_keur > 0
    total_sources = (
        fr.final_senior_commitment_keur
        + fr.share_capital_keur
        + fr.share_premium_keur
        + fr.other_equity_funding_before_shl_keur
        + fr.additional_equity_keur
    )
    assert abs(total_sources - fr.project_uses.total_project_uses_keur) <= 1e-7
    op_idxs = {row.index for row in op_periods}
    for row in clean_base.financial_statements_result.balance_sheet_periods:
        if row.period_index in op_idxs:
            assert row.balance_check_keur is not None and abs(row.balance_check_keur) <= 1e-7

    # Stress case: compressed arbitrage spread (sell=75 vs 115) lowers sculpted Senior debt capacity, BS balanced
    p_stress, _, _ = _build_10mw_project_inputs(monkeypatch, buy_price=35.0, sell_price=75.0)
    clean_stress = run_clean_production(p_stress, project_type="Storage")
    assert clean_stress.g2c_result.financing_result.final_senior_commitment_keur < fr.final_senior_commitment_keur
    for row in clean_stress.financial_statements_result.balance_sheet_periods:
        if row.period_index in op_idxs:
            assert row.balance_check_keur is not None and abs(row.balance_check_keur) <= 1e-7

    print(
        "FINCO42_BESS_10MW_20MWH_METRICS:",
        json.dumps(
            {
                "base_total_uses_keur": round(fr.project_uses.total_project_uses_keur, 6),
                "base_senior_debt_keur": round(fr.final_senior_commitment_keur, 6),
                "base_project_xirr": round(clean_base.g2c_result.return_summary.project.project_xirr, 6),
                "base_pure_equity_xirr": round(clean_base.g2c_result.pure_equity_xirr, 6),
                "stress_senior_debt_keur": round(clean_stress.g2c_result.financing_result.final_senior_commitment_keur, 6),
                "stress_project_xirr": round(clean_stress.g2c_result.return_summary.project.project_xirr, 6),
            }
        ),
    )

    # Zero-dispatch -> NO_DEBT_CAPACITY fail-closed refusal (no fake debt or IRR)
    p_zero, _, _ = _build_10mw_project_inputs(monkeypatch, zero_dispatch=True)
    p_zero = replace(p_zero, opex=())
    with pytest.raises(CleanProductionRunUnavailable, match="NO_DEBT_CAPACITY"):
        run_clean_production(p_zero, project_type="Storage")


def test_bess_date_authority_quarterly_hybrid_and_legacy_refusals(monkeypatch):
    p_base, _, _ = _build_10mw_project_inputs(monkeypatch)

    # OD-TIME-01/v1 dated grid is NOT admitted for BESS (native V10/V11 & production authority decline)
    from app.services.production_financial_authority import _is_dated_native_proved
    dated_p = replace(p_base, info=replace(p_base.info, date_authority_version=DATE_AUTHORITY_VERSION))
    assert _is_dated_native_proved(dated_p) is False

    # Quarterly 3/3 axis rejected for BESS (QuarterlyProjectInfo + quarterly_scope)
    from financial_engine.financing.quarterly_scope import require_supported_quarterly_project
    from finco_core.inputs import PeriodFrequency as InputPeriodFrequency
    from finco_core.inputs._models import QuarterlyProjectInfo
    from finco_core.engine.calendar_policy import quarterly_candidate_policy
    q_info = QuarterlyProjectInfo(
        name=p_base.info.name,
        company=p_base.info.company,
        code=p_base.info.code,
        country_iso=p_base.info.country_iso,
        financial_close=p_base.info.financial_close,
        construction_months=p_base.info.construction_months,
        cod_date=p_base.info.cod_date,
        horizon_years=p_base.info.horizon_years,
        period_frequency=InputPeriodFrequency.QUARTERLY,
        operating_calendar_policy=quarterly_candidate_policy(),
    )
    quarterly_p = replace(p_base, info=q_info)
    with pytest.raises(ValueError, match="QUARTERLY_TECHNOLOGY_UNSUPPORTED"):
        require_supported_quarterly_project(quarterly_p)

    # Hybrid yield / duplicate revenue authority rejected
    with pytest.raises(BessInputError, match="BESS_HYBRID_NOT_SUPPORTED"):
        require_native_separation(replace(p_base, technical=replace(p_base.technical, operating_hours_p50=1500.0)))
    with pytest.raises(BessInputError, match="BESS_DUPLICATE_REVENUE_AUTHORITY"):
        require_native_separation(replace(p_base, revenue=replace(p_base.revenue, ppa_base_tariff=50.0)))

    # Legacy non-native BessParams rejected at clean adapter
    legacy_only = replace(p_base, technical=replace(p_base.technical, bess_native_config_json=""))
    with pytest.raises(Exception, match="BESS_NATIVE_CONTRACT_REQUIRED|BESS_FINANCIAL_ACTIVATION_RELEASE_CLOSED"):
        run_clean_production(legacy_only, project_type="Storage")


# ---------------------------------------------------------------------------
# 3. Closed Production Gates & BESS02 (#436) / Preview Route Integrity (4C)
# ---------------------------------------------------------------------------

def test_closed_production_gates_bess02_roundtrip_and_preview_csrf_integrity(tmp_path, monkeypatch):
    # All production gates remain strictly closed by default
    assert bess_config.ACTIVATION_ENABLED is False
    storage_cap = next(c for c in PRODUCT_CAPABILITIES if c.key == "storage")
    assert storage_cap.status is ProductStatus.PREVIEW
    assert not any(
        (
            storage_cap.runnable,
            storage_cap.cloneable,
            storage_cap.working_copy_editable,
            storage_cap.canonical_last_run,
            storage_cap.api_available,
            storage_cap.export_available,
        )
    )
    p = bess_config.native_base_inputs()
    auth = classify_production_authority(replace(p, technical=replace(p.technical, bess_enabled=True)))
    assert auth.reason_code == "BESS_FINANCIAL_ACTIVATION_RELEASE_CLOSED"

    with pytest.raises(b2_cand.BessStandaloneCandidateError, match="BESS02_CANONICAL_CREATOR_RELEASE_CLOSED"):
        b2_cand.create_standalone_project("owner", "test-storage")

    # BESS02 (#436) export/import roundtrip + tamper rejections
    from tests.test_bess_standalone_candidate import native_document, declaration
    from finco_core.inputs.senior_rate_schedule import (
        SeniorDayCountConvention, SeniorDebtInterestConfig, SeniorRateMode, SeniorRateSchedule,
    )
    costs = {
        name: replace(
            getattr(p.capex, name),
            amount_keur=(25.0 if name == "epc_contract" else 5.0 if name in {"production_units", "epc_other"} else 0.0),
            useful_life_override=5 if name == "epc_contract" else 10,
        )
        for name in p.capex._CAPEX_ITEM_FIELDS
    }
    explicit = replace(
        p,
        info=replace(p.info, country_iso="XC", financial_close=date(2027, 1, 1), construction_months=12, cod_date=date(2028, 1, 1), horizon_years=3),
        technical=replace(p.technical, capacity_mw=1.0, bess=None),
        capex=replace(p.capex, **costs),
        opex=(replace(p.opex[0], y1_amount_keur=1.0, annual_inflation=0.0),),
        revenue=replace(p.revenue, ppa_base_tariff=0.0, ppa_term_years=0.0, ppa_production_share=0.0),
        financing=replace(
            p.financing,
            share_capital_keur=1.0,
            senior_tenor_years=2,
            gearing_ratio=0.5,
            senior_debt_interest_config=SeniorDebtInterestConfig(
                enabled=True,
                rate_schedule=SeniorRateSchedule(mode=SeniorRateMode.EXPLICIT_ALL_IN_SCHEDULE, explicit_all_in_rates=(0.055,) * 4),
                day_count=SeniorDayCountConvention.ACT_360,
            ),
        ),
    )
    nat_doc = native_document()
    decl_doc = declaration(explicit, nat_doc)
    prepared = b2_cand.prepare_candidate(explicit, json.dumps(nat_doc), json.dumps(decl_doc))
    exported = b2_cand.export_candidate_document(explicit, json.dumps(nat_doc), json.dumps(decl_doc))
    reimported = b2_cand.import_candidate_document(exported)
    assert reimported.native_input_sha256 == prepared.native_input_sha256
    assert reimported.base_input_sha256 == prepared.base_input_sha256
    assert reimported.declaration_sha256 == prepared.declaration_sha256

    tampered_doc = json.loads(exported)
    tampered_doc["base_inputs_sha256"] = "0" * 64
    with pytest.raises(b2_cand.BessStandaloneCandidateError):
        b2_cand.import_candidate_document(json.dumps(tampered_doc))

    # Preview HTTP route: authenticated + CSRF-bound + zero DB writes + honest blocked capabilities
    from app.persistence import db as persistence_db
    db_path = tmp_path / "bess_preview.db"
    monkeypatch.setattr(persistence_db, "DB_PATH", str(db_path))
    monkeypatch.setenv("FINCO_DB_PATH", str(db_path))
    monkeypatch.setenv("FINCO_MODEL_REACT_V1", "1")
    persistence_db.init_db()

    from app.v2.bess_candidate_router import router as cand_router
    from app.v2.bess_setup_router import router as setup_router
    from app.v2.bess_workspace_router import router as ws_router
    app = FastAPI()
    app.include_router(setup_router, prefix="/v2")
    app.include_router(cand_router, prefix="/v2")
    app.include_router(ws_router, prefix="/v2")

    with TestClient(app) as client:
        client.cookies.set(COOKIE_NAME, create_session_token(user_id="bess_owner", username="owner"))
        assert client.get("/v2/workbook/bess/candidate?project=x").status_code == 404
        assert client.get("/v2/workbook/bess/inputs?project=x").status_code in (404, 409)

        opts = client.get("/v2/model-react/new-project/bess-options")
        assert opts.status_code == 200
        body = opts.json()
        assert body["capability"]["create_supported"] is False
        assert body["capability"]["save_supported"] is False
        assert body["capability"]["run_supported"] is False

        bad_csrf = client.post(
            "/v2/model-react/new-project/bess-preview",
            json={"request_id": body["request_id"], "csrf_token": "forged", "native_json": json.dumps(_make_10mw_20mwh_daily_config()), "edits": {}},
        )
        assert bad_csrf.status_code == 403

        ok_prev = client.post(
            "/v2/model-react/new-project/bess-preview",
            json={"request_id": body["request_id"], "csrf_token": body["csrf_token"], "native_json": json.dumps(_make_10mw_20mwh_daily_config()), "edits": {}},
        )
        assert ok_prev.status_code == 200
        pj = ok_prev.json()
        assert pj["preview"]["declared_terms"]["costs"]["capex"]["status"] == "NOT_AVAILABLE"
        assert pj["preview"]["persisted"] is False
