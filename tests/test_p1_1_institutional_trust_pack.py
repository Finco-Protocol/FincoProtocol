"""P1.1 Institutional Model Trust Pack — fail-closed tests A through K + Correction A additions.

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

Correction A additions:
  L: TRUST_PACK_SPONSOR_RETURNS_PRODUCTION_AUTHORITY
  M: TRUST_PACK_METRIC_VERTICAL_SCOPE_FAIL_CLOSED
  N: TRUST_PACK_XIRR_DATE_AXIS_AUTHORITY
  O: TRUST_PACK_TAX_LIMITATION_TRUTH
  P: TRUST_PACK_GAP_REGISTRY_PUBLIC_SYNC
  Q: TRUST_PACK_REGISTRY_RUNTIME_BINDING_FAIL_CLOSED
  R: TRUST_PACK_G2C_FIVE_COMPONENT_GATE
  S: TRUST_PACK_SUPPORTED_TODAY_SYNC

Final Sync additions:
  T: TRUST_PACK_XIRR_ACT_365F_CONVENTION

Final composite: FINCO_P1_1_TRUST_PACK_FAIL_CLOSED_COMPLETE
"""
from __future__ import annotations

import importlib
import inspect
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
    assert "cfads / debt_service" in src or "cfads/debt_service" in src, (
        "financial_engine/senior_debt/sculpting.py must compute dscr = cfads / debt_service"
    )
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
    mod = importlib.import_module("app.model_methodology_registry")
    assert hasattr(mod, "METRIC_REGISTRY")
    assert hasattr(mod, "INSTITUTIONAL_GAPS")
    assert hasattr(mod, "metric_by_key")
    assert hasattr(mod, "gap_by_key")
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
        "revenue_data_center",
        "revenue_ev_charging",
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
        "COUNTRY_SPECIFIC_INTEREST_LIMITATION_NOT_MODELLED",
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


# ── L: Sponsor returns production authority (Correction A — Blocker 1) ───────

def test_l_sponsor_returns_production_authority():
    """TRUST_PACK_SPONSOR_RETURNS_PRODUCTION_AUTHORITY: equity_irr and total_sponsor_xirr
    must document compute_gated_sponsor_return_metrics as the calculation function
    and the G2C waterfall as the production caller."""
    from app.model_methodology_registry import metric_by_key

    for key in ("equity_irr", "total_sponsor_xirr"):
        m = metric_by_key(key)
        assert m is not None, f"{key} must be in registry"
        assert m.source_function == "compute_gated_sponsor_return_metrics", (
            f"{key}.source_function must be 'compute_gated_sponsor_return_metrics' "
            f"(G2C production path), got {m.source_function!r}"
        )
        assert "run_project_shareholder_waterfall_model" in m.production_caller, (
            f"{key}.production_caller must reference run_project_shareholder_waterfall_model, "
            f"got {m.production_caller!r}"
        )
        assert "run_project_sponsor_returns_model" not in m.source_function, (
            f"{key}.source_function must not be run_project_sponsor_returns_model (G2B path)"
        )

    # Structural: compute_gated_sponsor_return_metrics exists in the module
    sponsor_mod = importlib.import_module("financial_engine.sponsor_returns.model")
    assert hasattr(sponsor_mod, "compute_gated_sponsor_return_metrics"), (
        "financial_engine/sponsor_returns/model.py must export compute_gated_sponsor_return_metrics"
    )

    # Structural: G2C waterfall calls compute_gated_sponsor_return_metrics
    waterfall_src = (REPO / "financial_engine/shareholder_waterfall/model.py").read_text()
    assert "compute_gated_sponsor_return_metrics" in waterfall_src, (
        "financial_engine/shareholder_waterfall/model.py must call compute_gated_sponsor_return_metrics"
    )


# ── M: Metric vertical scope (Correction A — Blocker 2) ─────────────────────

def test_m_metric_vertical_scope():
    """TRUST_PACK_METRIC_VERTICAL_SCOPE_FAIL_CLOSED: vertical-scoped metrics are correctly
    bounded; DC and EV Charging revenue entries exist."""
    from app.model_methodology_registry import metric_by_key

    # Solar/Wind generation metrics must be scoped to solar+wind only
    prod = metric_by_key("production")
    rev = metric_by_key("revenue")
    assert prod is not None and rev is not None

    for m in (prod, rev):
        assert m.applicable_verticals != ("all",), (
            f"{m.key}.applicable_verticals must not be ('all',) — it is generation-specific"
        )
        assert "solar" in m.applicable_verticals, (
            f"{m.key} must include 'solar' in applicable_verticals"
        )
        assert "wind" in m.applicable_verticals, (
            f"{m.key} must include 'wind' in applicable_verticals"
        )
        assert "data_center" not in m.applicable_verticals, (
            f"{m.key} must NOT claim data_center — different revenue driver"
        )
        assert "ev_charging" not in m.applicable_verticals, (
            f"{m.key} must NOT claim ev_charging — different revenue driver"
        )

    # DC and EV revenue entries exist and are scoped correctly
    dc_rev = metric_by_key("revenue_data_center")
    assert dc_rev is not None, "revenue_data_center must be in registry"
    assert dc_rev.applicable_verticals == ("data_center",), (
        f"revenue_data_center.applicable_verticals must be ('data_center',), got {dc_rev.applicable_verticals}"
    )
    assert dc_rev.source_file == "app/data_center_authority.py"
    assert dc_rev.source_function == "core_capacity_revenue_keur"

    ev_rev = metric_by_key("revenue_ev_charging")
    assert ev_rev is not None, "revenue_ev_charging must be in registry"
    assert ev_rev.applicable_verticals == ("ev_charging",), (
        f"revenue_ev_charging.applicable_verticals must be ('ev_charging',), got {ev_rev.applicable_verticals}"
    )
    assert ev_rev.source_file == "app/ev_charging_economics.py"
    assert ev_rev.source_function == "charging_revenue_keur"


# ── N: XIRR date axis (Correction A — Blocker 3) ─────────────────────────────

def test_n_xirr_date_axis_authority():
    """TRUST_PACK_XIRR_DATE_AXIS_AUTHORITY: XIRR metrics use DATED_IRREGULAR period_frequency,
    not SEMESTRIAL."""
    from app.model_methodology_registry import metric_by_key

    xirr_metrics = ["project_irr", "equity_irr", "total_sponsor_xirr", "xirr_year_fraction"]
    for key in xirr_metrics:
        m = metric_by_key(key)
        assert m is not None, f"{key} must be in registry"
        assert m.period_frequency == "DATED_IRREGULAR", (
            f"{key}.period_frequency must be 'DATED_IRREGULAR' (not SEMESTRIAL — XIRR is date-aware), "
            f"got {m.period_frequency!r}"
        )

    # Legacy covenant utility must be STANDALONE_UTILITY
    legacy = metric_by_key("dscr_legacy_covenant_utility")
    assert legacy is not None
    assert legacy.period_frequency == "STANDALONE_UTILITY", (
        f"dscr_legacy_covenant_utility.period_frequency must be 'STANDALONE_UTILITY', "
        f"got {legacy.period_frequency!r}"
    )

    # Cash tax must be ANNUAL_TAX
    cash_tax = metric_by_key("cash_tax")
    assert cash_tax is not None
    assert cash_tax.period_frequency == "ANNUAL_TAX", (
        f"cash_tax.period_frequency must be 'ANNUAL_TAX', got {cash_tax.period_frequency!r}"
    )


# ── O: Tax limitation truth (Correction A — Blocker 4) ───────────────────────

def test_o_tax_limitation_truth():
    """TRUST_PACK_TAX_LIMITATION_TRUTH: THIN_CAP_ATAD_ONLY renamed to
    COUNTRY_SPECIFIC_INTEREST_LIMITATION_NOT_MODELLED with accurate description."""
    from app.model_methodology_registry import gap_by_key

    # Old key must NOT exist
    old_gap = gap_by_key("THIN_CAP_ATAD_ONLY")
    assert old_gap is None, (
        "THIN_CAP_ATAD_ONLY must be removed; replaced by "
        "COUNTRY_SPECIFIC_INTEREST_LIMITATION_NOT_MODELLED"
    )

    # New key must exist
    new_gap = gap_by_key("COUNTRY_SPECIFIC_INTEREST_LIMITATION_NOT_MODELLED")
    assert new_gap is not None, (
        "COUNTRY_SPECIFIC_INTEREST_LIMITATION_NOT_MODELLED must be in INSTITUTIONAL_GAPS"
    )

    # Description must reference the actual configured calculation
    assert "atad" in new_gap.description.lower() or "ATAD" in new_gap.description, (
        "Gap description must reference ATAD configured calculation"
    )
    assert "calculate_annual_atad" in new_gap.description or "atad_ebitda_limit" in new_gap.description, (
        "Gap description must reference the actual implementation "
        "(calculate_annual_atad or atad_ebitda_limit)"
    )

    # Must NOT claim France/Netherlands/UK as jurisdiction examples
    desc_lower = new_gap.description.lower()
    for jurisdiction in ("france", "netherlands", "uk corporate", "group carve-out"):
        assert jurisdiction not in desc_lower, (
            f"Gap description must not reference unimplemented jurisdiction {jurisdiction!r}"
        )

    # Template must not use old thin-cap wording in the gaps table
    html = (REPO / "app/templates/model_methodology.html").read_text()
    assert "Thin-cap: ATAD only" not in html, (
        "model_methodology.html must not contain old 'Thin-cap: ATAD only' wording"
    )


# ── P: Gap registry public sync (Correction A — Blocker 5) ───────────────────

def test_p_gap_registry_public_sync():
    """TRUST_PACK_GAP_REGISTRY_PUBLIC_SYNC: InstitutionalGap has public_visible and
    public_label fields; public_gaps() returns only visible gaps; template is
    registry-driven."""
    from app.model_methodology_registry import (
        INSTITUTIONAL_GAPS, public_gaps, InstitutionalGap
    )

    # All gaps must have public_visible and public_label attributes
    for gap in INSTITUTIONAL_GAPS:
        assert hasattr(gap, "public_visible"), (
            f"Gap {gap.key!r} missing public_visible field"
        )
        assert hasattr(gap, "public_label"), (
            f"Gap {gap.key!r} missing public_label field"
        )

    # public_gaps() must be a proper subset
    visible = public_gaps()
    assert len(visible) > 0, "public_gaps() must return at least one gap"
    assert len(visible) <= len(INSTITUTIONAL_GAPS), (
        "public_gaps() must not exceed total gaps"
    )
    for gap in visible:
        assert gap.public_visible, f"public_gaps() returned non-visible gap {gap.key!r}"
        assert gap.public_label, f"public_visible gap {gap.key!r} must have non-empty public_label"

    # Template must be registry-driven (Jinja loop, not static rows)
    html = (REPO / "app/templates/model_methodology.html").read_text()
    assert "institutional_gaps" in html, (
        "model_methodology.html must reference institutional_gaps context variable"
    )
    assert "{% for gap in institutional_gaps %}" in html or "for gap in institutional_gaps" in html, (
        "model_methodology.html must loop over institutional_gaps from registry"
    )

    # Key gaps must be public_visible
    from app.model_methodology_registry import gap_by_key
    for key in ("DSCR_DUAL_DEFINITION", "XIRR_NOT_PERIODIC_IRR",
                "COUNTRY_SPECIFIC_INTEREST_LIMITATION_NOT_MODELLED",
                "DSRF_NO_DRAW_ENGINE", "JUNIOR_DEBT_NOT_IMPLEMENTED"):
        g = gap_by_key(key)
        assert g is not None and g.public_visible, (
            f"Gap {key!r} must be public_visible=True"
        )


# ── Q: Registry runtime binding (Correction A — Blocker 6) ───────────────────

def test_q_registry_runtime_binding():
    """TRUST_PACK_REGISTRY_RUNTIME_BINDING_FAIL_CLOSED: source_function must exist
    in the named source module for importable modules."""
    from app.model_methodology_registry import METRIC_REGISTRY

    # Map of source_file (dot-path style) → module import path
    _FILE_TO_MODULE = {
        "finco_core/ebitda.py": "finco_core.ebitda",
        "finco_core/revenue/generation.py": "finco_core.revenue.generation",
        "finco_core/opex/projections.py": "finco_core.opex.projections",
        "finco_core/debt/covenants.py": "finco_core.debt.covenants",
        "finco_core/sponsor/xirr.py": "finco_core.sponsor.xirr",
        "financial_engine/cfads.py": "financial_engine.cfads",
        "financial_engine/senior_debt/sculpting.py": "financial_engine.senior_debt.sculpting",
        "financial_engine/senior_debt/interest.py": "financial_engine.senior_debt.interest",
        "financial_engine/sponsor_returns/model.py": "financial_engine.sponsor_returns.model",
        "financial_engine/tax/engine.py": "financial_engine.tax.engine",
        "app/data_center_authority.py": "app.data_center_authority",
        "app/ev_charging_economics.py": "app.ev_charging_economics",
    }

    failures = []
    for m in METRIC_REGISTRY:
        mod_path = _FILE_TO_MODULE.get(m.source_file)
        if mod_path is None:
            continue  # not mapped for import — file-existence check covers it
        try:
            mod = importlib.import_module(mod_path)
        except ImportError as e:
            failures.append(f"{m.key}: could not import {mod_path}: {e}")
            continue
        if not hasattr(mod, m.source_function):
            failures.append(
                f"{m.key}: {m.source_function!r} not found in {mod_path}"
            )

    assert not failures, (
        "Registry source_function binding failures:\n" + "\n".join(failures)
    )


# ── R: Five-component gate in template (Correction A — Blocker 7) ────────────

def test_r_g2c_five_component_gate():
    """TRUST_PACK_G2C_FIVE_COMPONENT_GATE: methodology template documents all five
    distribution gate components including DSRF no-draw and J-DSRA always False."""
    html = (REPO / "app/templates/model_methodology.html").read_text()

    # All five gate components must be documented
    for comp, desc in [
        ("A", "DSCR"),
        ("B", "construction"),
        ("C", "Distribution Account"),
        ("D", "DSRA"),
        ("E", "J-DSRA"),
    ]:
        assert f"<strong>{comp}</strong>" in html or f">{ comp}<" in html or f"Component {comp}" in html or (
            comp in html and desc.lower() in html.lower()
        ), f"Gate component {comp} ({desc}) not documented in cash-waterfall section"

    # DSRF no-draw must be noted
    assert "DSRF_AVAILABLE_SUPPORT_ONLY_NO_DRAW_ENGINE" in html or "no draw engine" in html.lower(), (
        "Waterfall section must note DSRF has no draw engine"
    )

    # J-DSRA always False must be noted
    assert "j_dsra" in html.lower() or "J-DSRA" in html, (
        "Waterfall section must note J-DSRA"
    )
    assert "always False" in html or "always false" in html.lower(), (
        "Waterfall section must note J-DSRA gate is always False for single-tranche projects"
    )


# ── S: Supported today / EV sync (Correction A — Blocker 8) ──────────────────

def test_s_supported_today_sync():
    """TRUST_PACK_SUPPORTED_TODAY_SYNC: hero badge in methodology template must
    list every LIVE model vertical from the canonical capability registry."""
    from app.product_capability import live_vertical_names

    live_names = live_vertical_names()
    html = (REPO / "app/templates/model_methodology.html").read_text()

    # Template must derive badge from live_vertical_names context variable
    assert "live_vertical_names" in html, (
        "model_methodology.html must reference live_vertical_names context variable in hero badge"
    )

    # All current live verticals must appear somewhere in the template text
    # (confirming the template correctly iterates the registry)
    for name in live_names:
        assert name in html, (
            f"LIVE vertical {name!r} not found in model_methodology.html — "
            "hero badge must be registry-driven via live_vertical_names()"
        )

    # EV Charging specifically must be present (regression guard)
    assert "EV Charging" in html, (
        "EV Charging must appear in model_methodology.html hero badge"
    )

    # Static hard-coded badge must be gone
    assert "Solar / Wind / Data Center</span>" not in html, (
        "Static 'Solar / Wind / Data Center' badge must be replaced with registry-driven output"
    )


# ── T: XIRR ACT/365F convention (Final Sync — Correction B) ─────────────────

def test_t_xirr_act_365f_convention():
    """TRUST_PACK_XIRR_ACT_365F_CONVENTION: xirr_year_fraction registry entry correctly
    documents ACT/365F-style (actual days / 365) convention, not misleading 'NOT actual/365'."""
    from app.model_methodology_registry import metric_by_key

    m = metric_by_key("xirr_year_fraction")
    assert m is not None

    # Formula must match source: (date - date[0]).days / 365.0
    assert "365" in m.formula and ".days" in m.formula.replace(" ", ""), (
        f"xirr_year_fraction formula must reflect (days).days / 365.0, got {m.formula!r}"
    )

    notes_lower = m.notes.lower()

    # Must describe actual-days / fixed-365 nature
    assert "actual" in notes_lower and "365" in notes_lower, (
        "xirr_year_fraction notes must describe actual calendar days / 365"
    )

    # Must reference ACT/365F-style
    assert "act/365f" in notes_lower or "act/365" in notes_lower, (
        "xirr_year_fraction notes must use ACT/365F-style terminology"
    )

    # Must NOT say "NOT actual/365" (that was the misleading statement)
    assert "not actual/365" not in notes_lower, (
        "xirr_year_fraction notes must not contain 'NOT actual/365' — "
        "the convention IS actual-days / 365, ACT/365F-style"
    )

    # Source code alignment: xirr.py must use .days / 365
    xirr_src = (REPO / "finco_core/sponsor/xirr.py").read_text()
    assert ".days / 365" in xirr_src or ".days/365" in xirr_src, (
        "finco_core/sponsor/xirr.py must compute year_fractions as .days / 365"
    )

    # Template XIRR section must not contain the old misleading comment
    html = (REPO / "app/templates/model_methodology.html").read_text()
    assert "365-day year fraction (no leap-year adjustment)" not in html, (
        "Template must not use old '365-day year fraction (no leap-year adjustment)' — "
        "use ACT/365F-style terminology instead"
    )
    # Template should reflect ACT/365F
    assert "ACT/365F" in html or "act/365f" in html.lower(), (
        "Template XIRR section must document ACT/365F-style convention"
    )


# ── Final composite marker ────────────────────────────────────────────────────

def test_finco_p1_1_trust_pack_fail_closed_complete():
    """FINCO_P1_1_TRUST_PACK_FAIL_CLOSED_COMPLETE

    Composite acceptance: passes only when all A-K + Correction A markers are satisfiable.
    """
    from app.model_methodology_registry import (
        METRIC_REGISTRY,
        INSTITUTIONAL_GAPS,
        metric_by_key,
        gap_by_key,
        public_gaps,
    )
    from app.product_capability import live_vertical_names

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

    # L: sponsor returns production authority
    for key in ("equity_irr", "total_sponsor_xirr"):
        m = metric_by_key(key)
        assert m is not None
        assert m.source_function == "compute_gated_sponsor_return_metrics"
        assert "run_project_shareholder_waterfall_model" in m.production_caller

    # M: vertical scope
    prod = metric_by_key("production")
    assert prod.applicable_verticals != ("all",)
    assert "solar" in prod.applicable_verticals
    assert "data_center" not in prod.applicable_verticals
    assert metric_by_key("revenue_data_center") is not None
    assert metric_by_key("revenue_ev_charging") is not None

    # N: XIRR date axis
    for key in ("project_irr", "equity_irr", "total_sponsor_xirr", "xirr_year_fraction"):
        m = metric_by_key(key)
        assert m.period_frequency == "DATED_IRREGULAR", f"{key} must be DATED_IRREGULAR"

    # O: tax limitation renamed
    assert gap_by_key("THIN_CAP_ATAD_ONLY") is None
    assert gap_by_key("COUNTRY_SPECIFIC_INTEREST_LIMITATION_NOT_MODELLED") is not None

    # P: public sync
    visible = public_gaps()
    assert len(visible) > 0
    assert "institutional_gaps" in html

    # R: five-component gate
    assert "J-DSRA" in html or "j_dsra" in html.lower()
    assert "DSRF_AVAILABLE_SUPPORT_ONLY_NO_DRAW_ENGINE" in html or "no draw engine" in html.lower()

    # S: supported today sync
    assert "live_vertical_names" in html
    assert "EV Charging" in html
    for name in live_vertical_names():
        assert name in html, f"LIVE vertical {name!r} missing from methodology template"

    # T: XIRR ACT/365F convention
    xirr_m = metric_by_key("xirr_year_fraction")
    assert xirr_m is not None
    notes_lower = xirr_m.notes.lower()
    assert "act/365f" in notes_lower or "act/365" in notes_lower, (
        "xirr_year_fraction notes must describe ACT/365F-style convention"
    )
    assert "not actual/365" not in notes_lower, (
        "xirr_year_fraction notes must not say 'NOT actual/365' (misleading)"
    )
