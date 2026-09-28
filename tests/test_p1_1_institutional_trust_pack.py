"""P1.1 Institutional Model Trust Pack — fail-closed tests A through K.

These tests enforce the P1.1 institutional trust pack contract.  They are
separate from test_model_trust_pack.py (which covers formula authority,
parameter fidelity and live engine outputs at the unit level).

Acceptance markers (all must PASS):
  A: TRUST_PACK_REGISTRY_AUTHORITY
  B: TRUST_PACK_REGISTRY_SOURCE_FILES_EXIST
  C: TRUST_PACK_DSCR_AUTHORITATIVE_IS_CFADS
  D: TRUST_PACK_DSCR_LEGACY_IS_EBITDA
  E: TRUST_PACK_INSTITUTIONAL_GAPS_DOCUMENTED
  F: TRUST_PACK_XIRR_GAP_DOCUMENTED
  G: TRUST_PACK_WATERFALL_PRIORITY_IN_TEMPLATE
  H: TRUST_PACK_METHODOLOGY_NO_SUPERLATIVES
  I: TRUST_PACK_REGISTRY_IMPORTABLE
  J: TRUST_PACK_REGISTRY_COMPLETENESS
  K: TRUST_PACK_INSTITUTIONAL_GAPS_COMPLETENESS

Final composite: FINCO_P1_1_TRUST_PACK_FAIL_CLOSED_COMPLETE
"""
from __future__ import annotations

import os
import pathlib

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]


# ── A: Registry imports and is non-empty ─────────────────────────────────────

def test_a_registry_authority():
    """TRUST_PACK_REGISTRY_AUTHORITY: model_methodology_registry is importable and populated."""
    from app.model_methodology_registry import (
        METRIC_REGISTRY,
        INSTITUTIONAL_GAPS,
        metric_by_key,
        gap_by_key,
        registry_keys,
        gap_keys,
    )
    assert len(METRIC_REGISTRY) >= 10, (
        f"METRIC_REGISTRY must have at least 10 entries, got {len(METRIC_REGISTRY)}"
    )
    assert len(INSTITUTIONAL_GAPS) >= 5, (
        f"INSTITUTIONAL_GAPS must have at least 5 entries, got {len(INSTITUTIONAL_GAPS)}"
    )
    assert registry_keys()
    assert gap_keys()
    assert metric_by_key("ebitda") is not None
    assert metric_by_key("cfads") is not None
    assert metric_by_key("dscr") is not None
    assert metric_by_key("project_irr") is not None


# ── B: Registry source files exist ───────────────────────────────────────────

def test_b_registry_source_files_exist():
    """TRUST_PACK_REGISTRY_SOURCE_FILES_EXIST: every source_file in the registry exists."""
    from app.model_methodology_registry import METRIC_REGISTRY
    missing = []
    for m in METRIC_REGISTRY:
        p = REPO / m.source_file
        if not p.exists():
            missing.append(f"{m.key}: {m.source_file}")
    assert not missing, (
        f"Registry source files not found:\n" + "\n".join(missing)
    )


# ── C: Authoritative DSCR uses CFADS ─────────────────────────────────────────

def test_c_dscr_authoritative_is_cfads():
    """TRUST_PACK_DSCR_AUTHORITATIVE_IS_CFADS: the clean engine DSCR uses CFADS/DS."""
    src = (REPO / "financial_engine/senior_debt/sculpting.py").read_text()
    # The authoritative dscr computation must reference cfads
    assert "cfads / debt_service" in src or "cfads/debt_service" in src, (
        "financial_engine/senior_debt/sculpting.py must compute dscr = cfads / debt_service"
    )
    # Registry also documents this
    from app.model_methodology_registry import metric_by_key
    m = metric_by_key("dscr")
    assert m is not None
    assert "cfads" in m.formula.lower(), (
        f"Registry 'dscr' formula must reference CFADS, got: {m.formula!r}"
    )
    assert m.source_file == "financial_engine/senior_debt/sculpting.py"


# ── D: Legacy covenant utility uses EBITDA ───────────────────────────────────

def test_d_dscr_legacy_is_ebitda():
    """TRUST_PACK_DSCR_LEGACY_IS_EBITDA: the legacy covenant utility uses EBITDA/DS."""
    src = (REPO / "finco_core/debt/covenants.py").read_text()
    assert "ebitda_keur / debt_service_keur" in src, (
        "finco_core/debt/covenants.py::dscr() must use EBITDA as numerator"
    )
    # Registry documents this as a separate entry
    from app.model_methodology_registry import metric_by_key
    m = metric_by_key("dscr_legacy_covenant_utility")
    assert m is not None, "Legacy DSCR entry must be documented in the registry"
    assert "ebitda" in m.formula.lower()
    assert "NOT called" in m.notes or "not called" in m.notes.lower()


# ── E: Institutional gaps include DSCR dual definition ───────────────────────

def test_e_institutional_gaps_documented():
    """TRUST_PACK_INSTITUTIONAL_GAPS_DOCUMENTED: DSCR dual definition is in INSTITUTIONAL_GAPS."""
    from app.model_methodology_registry import INSTITUTIONAL_GAPS, gap_by_key
    dscr_gap = gap_by_key("DSCR_DUAL_DEFINITION")
    assert dscr_gap is not None, "DSCR_DUAL_DEFINITION must be in INSTITUTIONAL_GAPS"
    assert "CFADS" in dscr_gap.description or "cfads" in dscr_gap.description.lower()
    assert "EBITDA" in dscr_gap.description or "ebitda" in dscr_gap.description.lower()


# ── F: XIRR gap is documented ────────────────────────────────────────────────

def test_f_xirr_gap_documented():
    """TRUST_PACK_XIRR_GAP_DOCUMENTED: XIRR vs periodic IRR gap is in INSTITUTIONAL_GAPS."""
    from app.model_methodology_registry import gap_by_key
    gap = gap_by_key("XIRR_NOT_PERIODIC_IRR")
    assert gap is not None, "XIRR_NOT_PERIODIC_IRR must be in INSTITUTIONAL_GAPS"
    assert "365" in gap.description or "periodic" in gap.description.lower()
    # Registry also has the XIRR year fraction metric
    from app.model_methodology_registry import metric_by_key
    m = metric_by_key("xirr_year_fraction")
    assert m is not None
    assert "365" in m.formula


# ── G: Cash waterfall priority appears in methodology template ────────────────

def test_g_waterfall_priority_in_template():
    """TRUST_PACK_WATERFALL_PRIORITY_IN_TEMPLATE: methodology page has the waterfall section."""
    html = (REPO / "app/templates/model_methodology.html").read_text()
    assert 'id="cash-waterfall"' in html, (
        "model_methodology.html must have a section id='cash-waterfall'"
    )
    assert "Senior debt service" in html
    assert "DSRA top-up" in html
    assert "Lock-up gate" in html or "lock-up" in html.lower()
    assert "Distribution Account" in html
    assert "Legal equity distribution" in html


# ── H: No marketing superlatives ─────────────────────────────────────────────

def test_h_methodology_no_superlatives():
    """TRUST_PACK_METHODOLOGY_NO_SUPERLATIVES: no banned marketing language in methodology."""
    html = (REPO / "app/templates/model_methodology.html").read_text()
    lower = html.lower()
    banned = [
        "bank-grade",
        "bank grade",
        "lender-approved",
        "lender approved",
        "audit-certified",
        "audit certified",
        "institutional-grade",
        "institutional grade",
        "guaranteed yield",
        "guaranteed returns",
        "risk-free",
        "staking is live",
        "dividend rights",
    ]
    found = [phrase for phrase in banned if phrase in lower]
    assert not found, (
        f"Marketing superlatives found in model_methodology.html: {found}"
    )


# ── I: Registry is importable without errors ─────────────────────────────────

def test_i_registry_importable():
    """TRUST_PACK_REGISTRY_IMPORTABLE: model_methodology_registry has no import errors."""
    import importlib
    mod = importlib.import_module("app.model_methodology_registry")
    assert hasattr(mod, "METRIC_REGISTRY")
    assert hasattr(mod, "INSTITUTIONAL_GAPS")
    assert hasattr(mod, "metric_by_key")
    assert hasattr(mod, "gap_by_key")
    # All keys are unique
    keys = [m.key for m in mod.METRIC_REGISTRY]
    assert len(keys) == len(set(keys)), f"Duplicate metric keys: {keys}"
    gap_keys = [g.key for g in mod.INSTITUTIONAL_GAPS]
    assert len(gap_keys) == len(set(gap_keys)), f"Duplicate gap keys: {gap_keys}"


# ── J: Registry completeness — critical metrics present ──────────────────────

def test_j_registry_completeness():
    """TRUST_PACK_REGISTRY_COMPLETENESS: all critical P1.1 metrics are in the registry."""
    from app.model_methodology_registry import metric_by_key
    required = [
        "production",
        "revenue",
        "opex",
        "ebitda",
        "cash_tax",
        "cfads",
        "dscr",
        "dscr_legacy_covenant_utility",
        "senior_debt_service",
        "llcr",
        "project_irr",
        "equity_irr",
        "total_sponsor_xirr",
        "xirr_year_fraction",
    ]
    missing = [key for key in required if metric_by_key(key) is None]
    assert not missing, (
        f"Missing metrics in registry: {missing}"
    )


# ── K: Institutional gaps completeness ───────────────────────────────────────

def test_k_institutional_gaps_completeness():
    """TRUST_PACK_INSTITUTIONAL_GAPS_COMPLETENESS: all critical gaps are documented."""
    from app.model_methodology_registry import gap_by_key
    required_gaps = [
        "DSCR_DUAL_DEFINITION",
        "XIRR_NOT_PERIODIC_IRR",
        "THIN_CAP_ATAD_ONLY",
        "DSRF_NO_DRAW_ENGINE",
        "JUNIOR_DEBT_NOT_IMPLEMENTED",
        "REFINANCING_NOT_MODELLED",
        "SINGLE_CURRENCY_KEUR",
        "FINANCIAL_STATEMENTS_NOT_CONNECTED_TO_CLEAN_ENGINE",
        "CANONICAL_LAST_RUN_NO_UUID",
    ]
    missing = [key for key in required_gaps if gap_by_key(key) is None]
    assert not missing, (
        f"Missing institutional gaps: {missing}"
    )


# ── Final composite marker ────────────────────────────────────────────────────

def test_finco_p1_1_trust_pack_fail_closed_complete():
    """FINCO_P1_1_TRUST_PACK_FAIL_CLOSED_COMPLETE

    Composite acceptance: passes only when all A-K markers are satisfiable.
    """
    from app.model_methodology_registry import (
        METRIC_REGISTRY,
        INSTITUTIONAL_GAPS,
        metric_by_key,
        gap_by_key,
    )
    # A: registry populated
    assert len(METRIC_REGISTRY) >= 10
    assert len(INSTITUTIONAL_GAPS) >= 5

    # B: source files exist
    for m in METRIC_REGISTRY:
        assert (REPO / m.source_file).exists(), (
            f"Source file not found for metric '{m.key}': {m.source_file}"
        )

    # C+D: DSCR dual definition documented
    dscr_clean = metric_by_key("dscr")
    dscr_legacy = metric_by_key("dscr_legacy_covenant_utility")
    assert dscr_clean is not None and "cfads" in dscr_clean.formula.lower()
    assert dscr_legacy is not None and "ebitda" in dscr_legacy.formula.lower()

    # E+F: key gaps documented
    assert gap_by_key("DSCR_DUAL_DEFINITION") is not None
    assert gap_by_key("XIRR_NOT_PERIODIC_IRR") is not None

    # G: waterfall section in template
    html = (REPO / "app/templates/model_methodology.html").read_text()
    assert 'id="cash-waterfall"' in html

    # H: no superlatives
    lower = html.lower()
    for phrase in ("bank-grade", "lender-approved", "audit-certified"):
        assert phrase not in lower, f"Banned phrase found: {phrase!r}"

    # I: unique keys
    keys = [m.key for m in METRIC_REGISTRY]
    assert len(keys) == len(set(keys))
