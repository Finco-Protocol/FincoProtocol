"""Opus H-3 — share-capital IRR vs total sponsor IRR.

The engine already computes both returns. These tests pin the contract that
``equity_irr`` keeps its meaning (pure share-capital return, equity_only), that the
total sponsor return (equity + shareholder loan) is explicit on every surface, that no
flow is counted twice, and that sponsor cash flows carry correct signs and dates.
"""
from __future__ import annotations

import dataclasses as dc
import re
from pathlib import Path
from types import SimpleNamespace

import pytest

from app import project_factories as pf
from app.api.v1_1.schemas import kpis_out
from app.services.clean_presentation_adapter import build_clean_sponsor_schedule
from app.services.production_financial_authority import run_clean_production
from app.services.v2_export_service import _RuntimeResultAdapter
from finco_core.sponsor.xirr import xirr
from financial_engine.financing.generic_product_policy import (
    DISABLED_GENERIC_FINANCING_POLICY as OFF,
)
from financial_engine.shareholder_waterfall import run_project_shareholder_waterfall_model

REPO = Path(__file__).resolve().parents[1]
TOL = 1e-9


@pytest.fixture(scope="module")
def shl_run():
    """Solar reference (SHL-funded) with the H-1 policy off: fast and returns are pinned."""
    return run_clean_production(
        pf.create_generic_solar_reference(), "Base", project_type="solar", financing_policy=OFF)


@pytest.fixture(scope="module")
def typed_run():
    """Same project through the typed (H-1) construction path with canonical period dates."""
    return run_clean_production(pf.create_generic_solar_reference(), "Base", project_type="solar")


def _flows(g2c):
    periods = g2c.waterfall_periods
    dates = [p.cashflow_date for p in periods]
    return (dates,
            [p.pure_equity_net_cashflow_keur for p in periods],
            [p.total_sponsor_net_cashflow_keur for p in periods])


# ── 1–2. Pure equity reconciles; SHL-funded structures diverge ──────────────

def test_pure_equity_financing_share_capital_and_sponsor_returns_reconcile():
    pi = pf.create_generic_solar_reference()
    pure_equity = dc.replace(pi, financing=dc.replace(
        pi.financing, share_capital_keur=8250.0, shl_amount_keur=0.0))
    g2c = run_project_shareholder_waterfall_model(pure_equity, source_id="h3-pure-equity")
    assert g2c.financing_result.derived_shl_cash_principal_keur == 0.0
    assert g2c.pure_equity_xirr == pytest.approx(g2c.total_sponsor_xirr, abs=TOL)
    dates, pe, ts = _flows(g2c)
    assert pe == pytest.approx(ts, abs=TOL)


def test_shl_funded_structure_returns_diverge_correctly(shl_run):
    g2c = shl_run.g2c_result
    assert g2c.pure_equity_xirr == pytest.approx(0.5046761426, abs=1e-8)   # unchanged
    assert g2c.total_sponsor_xirr == pytest.approx(0.1789632160, abs=1e-8)  # unchanged
    assert g2c.pure_equity_xirr > g2c.total_sponsor_xirr + 0.10


# ── 3–5. Each SHL / equity flow counted once ────────────────────────────────

def test_sponsor_flows_reconcile_to_shl_and_equity_components_once(shl_run):
    schedule = build_clean_sponsor_schedule(shl_run)
    summary, periods = schedule["summary"], schedule["periods"]
    g2c = shl_run.g2c_result
    _, pe, ts = _flows(g2c)

    # Equity distributions and contributions appear once in the pure-equity vector.
    contributions = sum(
        p["share_capital_contribution_keur"] + p["share_premium_contribution_keur"]
        + p["other_committed_equity_contribution_keur"] + p["additional_equity_contribution_keur"]
        for p in periods)
    distributions = sum(p["legal_equity_distribution_keur"] for p in periods)
    assert contributions == pytest.approx(summary["total_legal_equity_contributed_keur"], abs=1e-6)
    assert distributions == pytest.approx(summary["total_legal_equity_distributions_keur"], abs=1e-6)
    assert sum(pe) == pytest.approx(distributions - contributions, abs=1e-6)

    # SHL cash interest and principal appear once each in the receipts...
    interest = sum(p["shl_cash_interest_receipt_keur"] for p in periods)
    principal = sum(p["shl_principal_receipt_keur"] for p in periods)
    assert interest == pytest.approx(summary["total_shl_cash_interest_received_keur"], abs=1e-6)
    assert principal == pytest.approx(summary["total_shl_principal_received_keur"], abs=1e-6)
    # ...and the sponsor vector is the equity vector plus exactly those SHL flows.
    shl_contributed = summary["total_shl_cash_contributed_keur"]
    assert sum(ts) - sum(pe) == pytest.approx(interest + principal - shl_contributed, abs=1e-6)
    assert summary["total_sponsor_receipts_keur"] == pytest.approx(
        distributions + interest + principal, abs=1e-6)


def test_xirr_is_reproduced_from_the_flow_vectors_with_unchanged_conventions(shl_run):
    dates, pe, ts = _flows(shl_run.g2c_result)
    assert xirr(pe, dates) == pytest.approx(shl_run.g2c_result.pure_equity_xirr, abs=1e-9)
    assert xirr(ts, dates) == pytest.approx(shl_run.g2c_result.total_sponsor_xirr, abs=1e-9)


# ── 6. Signs and dates ──────────────────────────────────────────────────────

def test_sponsor_funding_signs_and_dates(shl_run):
    dates, pe, ts = _flows(shl_run.g2c_result)
    periods = shl_run.g2c_result.waterfall_periods
    financial_close = shl_run.project_inputs.info.financial_close
    assert dates[0] == financial_close and ts[0] < 0.0 and pe[0] < 0.0
    assert dates == sorted(dates)
    for period, pe_cash, ts_cash in zip(periods, pe, ts):
        if period.is_construction:
            assert pe_cash <= 0.0 and ts_cash <= 0.0  # funding only
            assert ts_cash <= pe_cash + TOL           # SHL funding never reduces the outflow


def test_typed_construction_periods_use_canonical_period_dates(typed_run):
    g2c = typed_run.g2c_result
    funding = g2c.financing_result.construction_funding.periods
    construction = [p for p in g2c.waterfall_periods if p.is_construction]
    assert len(construction) == len(funding) > 1
    for period, funded in zip(construction, funding):
        assert funded.period_start is not None
        assert period.cashflow_date == funded.period_start  # not financial_close + k months
    starts = [p.cashflow_date for p in construction]
    assert starts == sorted(starts) and len(set(starts)) == len(starts)
    assert (starts[1] - starts[0]).days >= 180  # semiannual construction periods


# ── 7–9. Compatibility: machine fields, API, persistence, labels ────────────

def test_machine_fields_keep_their_meaning_and_are_explicit():
    from app.api.project_runner import run_project

    kpis = run_project("Generic Solar Reference", "Base")["kpis"]
    assert kpis["equity_irr"] == kpis["share_capital_irr"]          # same value, explicit name
    assert kpis["sponsor_irr"] == kpis["total_sponsor_xirr"]        # legacy key retained
    assert kpis["equity_irr"] != kpis["total_sponsor_xirr"]         # never aliased in SHL case
    assert kpis["share_capital_irr_status"] == "OK"
    assert kpis["total_sponsor_xirr_status"] == "OK"


def _ws():
    return SimpleNamespace(draft_snapshot={}, last_runtime_snapshot={})


def test_v1_1_serves_total_sponsor_xirr_from_persisted_evidence():
    persisted = {"equity_irr": 0.50, "share_capital_irr": 0.50, "total_sponsor_xirr": 0.18,
                 "sponsor_irr": 0.18, "min_dscr": 1.25}
    out = kpis_out(_ws(), _RuntimeResultAdapter(persisted, {"periods": []}))
    assert out["total_sponsor_xirr"] == {"value": 0.18, "state": "AVAILABLE", "unit": "pct"}
    assert out["share_capital_irr"]["value"] == 0.50
    assert out["equity_irr"]["value"] == 0.50


def test_v1_1_reads_older_last_runs_that_persisted_only_sponsor_irr():
    out = kpis_out(_ws(), _RuntimeResultAdapter({"equity_irr": 0.5, "sponsor_irr": 0.18},
                                                {"periods": []}))
    assert out["total_sponsor_xirr"]["value"] == 0.18  # previously always UNAVAILABLE


def test_missing_sponsor_return_is_unavailable_never_zero():
    out = kpis_out(_ws(), _RuntimeResultAdapter({"equity_irr": 0.5}, {"periods": []}))
    assert out["total_sponsor_xirr"] == {"value": None, "state": "UNAVAILABLE", "unit": "pct"}


def test_labels_say_what_each_return_is():
    from app.ui.trust_pack import _CORE_KPI_ROWS

    labels = {key: label for key, label, _ in _CORE_KPI_ROWS}
    assert labels["equity_irr"] == "Share-capital IRR (equity only)"
    assert labels["total_sponsor_xirr"] == "Total Sponsor XIRR (equity + SHL)"
    order = [key for key, _, _ in _CORE_KPI_ROWS]
    assert order.index("total_sponsor_xirr") < order.index("equity_irr")  # sponsor headline first

    workbook = (REPO / "app/export/institutional_workbook.py").read_text(encoding="utf-8-sig")
    assert '"Share-capital IRR (equity only)"' in workbook
    assert "EXCLUDES shareholder-loan flows" in workbook
    assert re.search(r'^\s+"Equity IRR",\s*$', workbook, re.M) is None  # no bare row label


def test_machine_key_and_api_field_names_are_unchanged():
    schemas = (REPO / "app/api/v1_1/schemas.py").read_text(encoding="utf-8-sig")
    assert '"equity_irr": _kpi_field(_safe("equity_irr"), "pct")' in schemas
    assert '"total_sponsor_xirr": _kpi_field(' in schemas
    runner = (REPO / "app/api/project_runner.py").read_text(encoding="utf-8-sig")
    assert '"equity_irr": result.equity_irr' in runner
    assert '"sponsor_irr": getattr(result, \'sponsor_irr\', None)' in runner
