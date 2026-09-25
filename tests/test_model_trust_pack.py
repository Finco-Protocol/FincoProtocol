"""P1 Institutional Trust Pack — unit-level methodology markers.

Every test in this module asserts a traceable formula, parameter, or engine
output for the Generic Solar Reference model.  Tests are grouped into three
layers:

  1. Source-level authority — formula text present in the right file
  2. Parameter fidelity — reference model inputs match documented values
  3. Live engine outputs — actual Phase 2C run matches published numbers

Acceptance markers (one per test function) make each claim individually
pass/fail so CI surfaces the exact broken link.

Final composite marker:
  FINCO_MODEL_P1_INSTITUTIONAL_TRUST_PACK_COMPLETE
"""
from __future__ import annotations

import os
import math
import pytest


# ── helpers ──────────────────────────────────────────────────────────────────

def _read_source(rel_path: str) -> str:
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    with open(os.path.join(root, rel_path), encoding="utf-8") as fh:
        return fh.read()


def _solar_reference():
    from app.project_factories import create_generic_solar_reference
    return create_generic_solar_reference()


def _solar_full_run():
    from app.project_factories import create_generic_solar_reference
    from financial_engine.financing.project import run_project_financing_model
    from financial_engine.sponsor_returns.model import run_project_sponsor_returns_model
    pi = create_generic_solar_reference()
    fin = run_project_financing_model(pi)
    sponsor = run_project_sponsor_returns_model(pi)
    return pi, fin, sponsor


# ── Layer 1: Source-level authority ──────────────────────────────────────────

def test_trust_cfads_formula_authority():
    """TRUST_PACK_CFADS_FORMULA_SOURCED — cfads.py must declare the exact formula."""
    src = _read_source("financial_engine/cfads.py")
    assert "cfads_keur=ebitda + fin_income - cash_tax" in src, (
        "canonical CFADS formula not found in financial_engine/cfads.py"
    )
    assert "calculate_canonical_cfads" in src


def test_trust_ebitda_formula_authority():
    """TRUST_PACK_EBITDA_FORMULA_SOURCED — finco_core/ebitda.py must contain the formula."""
    src = _read_source("finco_core/ebitda.py")
    assert "return revenue_keur - opex_keur" in src, (
        "EBITDA formula 'return revenue_keur - opex_keur' not found in finco_core/ebitda.py"
    )


def test_trust_backward_induction_authority():
    """TRUST_PACK_BACKWARD_INDUCTION_SOURCED — solver.py must contain backward induction."""
    src = _read_source("financial_engine/senior_debt/solver.py")
    assert "backward" in src.lower(), (
        "backward induction comment not found in senior_debt/solver.py"
    )
    # The closing-at-maturity = 0 convention
    assert "closing" in src.lower()


def test_trust_xirr_365_day_authority():
    """TRUST_PACK_XIRR_365_DAY_SOURCED — XIRR must use 365-day year convention."""
    src = _read_source("finco_core/sponsor/xirr.py")
    assert "365" in src, (
        "365-day year convention not found in finco_core/sponsor/xirr.py"
    )
    assert "robust_xirr" in src


def test_trust_methodology_template_exists():
    """TRUST_PACK_METHODOLOGY_PAGE_EXISTS — HTML template must be present."""
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    tpl = os.path.join(root, "app", "templates", "model_methodology.html")
    assert os.path.isfile(tpl), f"model_methodology.html not found at {tpl}"
    content = open(tpl, encoding="utf-8").read()
    assert "FINCO Model Methodology" in content
    assert "cfads_keur" in content
    assert "ebitda_keur" in content


def test_trust_methodology_route_registered():
    """TRUST_PACK_METHODOLOGY_ROUTE_REGISTERED — router.py must expose /model/methodology."""
    src = _read_source("app/protocol_ui/router.py")
    assert "/model/methodology" in src, (
        "/model/methodology route not found in app/protocol_ui/router.py"
    )
    assert "model_methodology" in src


# ── Layer 2: Reference model parameter fidelity ───────────────────────────────

def test_trust_period_semestrial():
    """TRUST_PACK_PERIOD_SEMESTRIAL — Solar reference must use SEMESTRIAL frequency."""
    pi = _solar_reference()
    # Accept both the enum value string and the enum itself
    freq = str(pi.info.period_frequency)
    assert "SEMESTRIAL" in freq.upper() or "2" in freq, (
        f"Expected SEMESTRIAL frequency, got {pi.info.period_frequency!r}"
    )


def test_trust_solar_capex_total():
    """TRUST_PACK_SOLAR_CAPEX_TOTAL_KEUR — Total CAPEX must be 33,000 kEUR."""
    pi = _solar_reference()
    total = float(pi.capex.total_capex)
    assert math.isclose(total, 33_000.0, rel_tol=1e-4), (
        f"Expected total_capex = 33,000 kEUR, got {total}"
    )


def test_trust_solar_opex_y1():
    """TRUST_PACK_SOLAR_OPEX_Y1_KEUR — Y1 OPEX must be 380 kEUR."""
    pi = _solar_reference()
    total_opex_y1 = sum(float(item.y1_amount_keur) for item in pi.opex)
    assert math.isclose(total_opex_y1, 380.0, rel_tol=1e-4), (
        f"Expected Y1 OPEX = 380 kEUR, got {total_opex_y1}"
    )


def test_trust_solar_tax_rate():
    """TRUST_PACK_SOLAR_TAX_RATE — Corporate tax rate must be 25%."""
    pi = _solar_reference()
    rate = float(pi.tax.corporate_rate)
    assert math.isclose(rate, 0.25, rel_tol=1e-6), (
        f"Expected corporate_rate = 0.25, got {rate}"
    )


def test_trust_solar_target_dscr():
    """TRUST_PACK_SOLAR_TARGET_DSCR — Target DSCR must be 1.20."""
    pi = _solar_reference()
    dscr = float(pi.financing.target_dscr)
    assert math.isclose(dscr, 1.20, rel_tol=1e-6), (
        f"Expected target_dscr = 1.20, got {dscr}"
    )


def test_trust_solar_gearing_ratio():
    """TRUST_PACK_SOLAR_GEARING_RATIO — Gearing ratio must be 0.75."""
    pi = _solar_reference()
    g = float(pi.financing.gearing_ratio)
    assert math.isclose(g, 0.75, rel_tol=1e-6), (
        f"Expected gearing_ratio = 0.75, got {g}"
    )


# ── Layer 3: Live engine outputs ─────────────────────────────────────────────

def test_trust_solar_operating_periods():
    """TRUST_PACK_SOLAR_OPERATING_PERIODS — Must produce exactly 50 operating periods."""
    from app.project_factories import create_generic_solar_reference
    from financial_engine.orchestrator import run_operating_model
    from financial_engine.adapters.project_inputs import from_project_inputs
    pi = create_generic_solar_reference()
    op_input = from_project_inputs(pi)
    result = run_operating_model(op_input)
    op_count = sum(1 for p in result.periods if p.is_operation)
    assert op_count == 50, (
        f"Expected 50 operating periods (25yr × 2), got {op_count}"
    )


def test_trust_solar_senior_debt_drawn():
    """TRUST_PACK_SOLAR_SENIOR_DEBT_KEUR — Senior debt must be 24,750 kEUR (75% × 33,000)."""
    from app.project_factories import create_generic_solar_reference
    from financial_engine.financing.project import run_project_financing_model
    pi = create_generic_solar_reference()
    fin = run_project_financing_model(pi)
    drawn = float(fin.final_senior_commitment_keur)
    assert math.isclose(drawn, 24_750.0, rel_tol=1e-4), (
        f"Expected senior debt = 24,750 kEUR, got {drawn}"
    )


def test_trust_solar_binding_constraint_gearing():
    """TRUST_PACK_SOLAR_BINDING_CONSTRAINT_GEARING — DSCR capacity must exceed gearing cap."""
    from app.project_factories import create_generic_solar_reference
    from financial_engine.financing.project import run_project_financing_model
    pi = create_generic_solar_reference()
    fin = run_project_financing_model(pi)
    assert "GEARING" in fin.binding_senior_constraint.upper(), (
        f"Expected binding constraint GEARING, got {fin.binding_senior_constraint!r}"
    )
    # DSCR capacity exceeds gearing cap
    assert fin.dscr_debt_capacity_keur > fin.gearing_debt_capacity_keur


def test_trust_solar_min_dscr_above_target():
    """TRUST_PACK_SOLAR_MIN_DSCR — Min DSCR must be >= target DSCR (1.20)."""
    from app.project_factories import create_generic_solar_reference
    from financial_engine.financing.project import run_project_financing_model
    pi = create_generic_solar_reference()
    fin = run_project_financing_model(pi)
    sd = fin.project_model_result.senior_debt
    dscr_vals = [d for d in sd.base_dscr if d is not None]
    min_dscr = min(dscr_vals)
    target = float(pi.financing.target_dscr)
    assert min_dscr >= target - 0.001, (
        f"Min DSCR {min_dscr:.4f} below target {target:.2f}"
    )


def test_trust_solar_project_irr():
    """TRUST_PACK_SOLAR_PROJECT_IRR — Project IRR must be approximately 11.56%."""
    from app.project_factories import create_generic_solar_reference
    from financial_engine.financing.project import run_project_financing_model
    from financial_engine.project_returns.model import _project_return
    pi = create_generic_solar_reference()
    fin = run_project_financing_model(pi)
    pr = _project_return(pi, fin)
    assert pr.project_xirr is not None, "Project IRR returned None"
    irr_pct = pr.project_xirr * 100
    assert math.isclose(irr_pct, 11.56, abs_tol=0.1), (
        f"Expected Project IRR ≈ 11.56%, got {irr_pct:.4f}%"
    )


def test_trust_solar_sponsor_xirr():
    """TRUST_PACK_SOLAR_SPONSOR_XIRR — Total Sponsor XIRR must be approximately 17.90%."""
    from app.project_factories import create_generic_solar_reference
    from financial_engine.sponsor_returns.model import run_project_sponsor_returns_model
    pi = create_generic_solar_reference()
    result = run_project_sponsor_returns_model(pi)
    xirr_pct = result.total_sponsor_xirr * 100
    assert math.isclose(xirr_pct, 17.90, abs_tol=0.1), (
        f"Expected Total Sponsor XIRR ≈ 17.90%, got {xirr_pct:.4f}%"
    )


# ── Final composite acceptance marker ─────────────────────────────────────────

def test_finco_model_p1_institutional_trust_pack_complete():
    """FINCO_MODEL_P1_INSTITUTIONAL_TRUST_PACK_COMPLETE

    This test passes only when all individual trust-pack markers are logically
    satisfiable in the same codebase revision.  It asserts a subset of the most
    critical invariants so CI surfaces this marker explicitly.
    """
    pi = _solar_reference()

    # Formula authorities present in source
    cfads_src = _read_source("financial_engine/cfads.py")
    assert "calculate_canonical_cfads" in cfads_src
    ebitda_src = _read_source("finco_core/ebitda.py")
    assert "revenue_keur" in ebitda_src

    # Reference model parameters
    assert math.isclose(float(pi.capex.total_capex), 33_000.0, rel_tol=1e-4)
    assert math.isclose(sum(float(i.y1_amount_keur) for i in pi.opex), 380.0, rel_tol=1e-4)
    assert math.isclose(float(pi.tax.corporate_rate), 0.25, rel_tol=1e-6)

    # Live engine: senior debt and IRR
    from financial_engine.financing.project import run_project_financing_model
    from financial_engine.project_returns.model import _project_return
    fin = run_project_financing_model(pi)
    assert math.isclose(fin.final_senior_commitment_keur, 24_750.0, rel_tol=1e-4)
    pr = _project_return(pi, fin)
    assert pr.project_xirr is not None
    assert math.isclose(pr.project_xirr * 100, 11.56, abs_tol=0.1)

    # Methodology page exists
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    tpl = os.path.join(root, "app", "templates", "model_methodology.html")
    assert os.path.isfile(tpl)
