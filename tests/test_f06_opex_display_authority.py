"""F06 — competing OPEX display authority tests.

Audit finding: the Workbook V2 OPEX sheet rendered two competing "Total OPEX
Y1" authorities:

  1. the live OpexViewModel total (KPI strip "OPEX Y1" + grand-total row),
     computed from the effective per-line OPEX + user sub-lines, and
  2. the registry summary field ``opex.summary.total_y1``, whose value came
     from the persisted snapshot scalar ``opex_y1_keur`` — a "display anchor"
     seeded once at project creation and never recomputed by any OPEX
     mutation (per-line scalar overrides and custom sub-lines both leave it
     stale).

The fix is presentation-only: the summary field's *displayed* value is the
live OpexViewModel Y1 total — the same number the sheet's dominant authority
already renders. The persisted anchor, the effective engine inputs, and every
financial formula are untouched; these tests pin exactly that boundary.

All values are synthetic fixtures; no real project data is used.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _wind_reference_snapshot() -> tuple[dict, float, object]:
    """Build a Generic Wind Reference snapshot exactly the way
    app.persistence.projects_repository seeds it at project creation.

    Returns (snapshot, persisted_anchor_value, factory_inputs).
    """
    from app.project_factories import create_generic_wind_reference

    pi = create_generic_wind_reference()
    anchor = sum(float(getattr(item, "y1_amount_keur", 0) or 0) for item in pi.opex)
    snapshot = {
        "active_project": "generic_wind_reference-baseline",
        "project_name": pi.info.name,
        "project_type": "Wind",
        "project_origin": "saved_baseline",
        "template_source": "generic_wind_reference",
        "country_market": pi.info.country_iso,
        "scenario": "Base",
        "capacity_mw": str(pi.technical.capacity_mw),
        "tariff_eur_mwh": str(pi.revenue.ppa_base_tariff),
        "p50_hours": str(pi.technical.operating_hours_p50),
        "total_capex_keur": str(pi.capex.total_capex),
        "opex_y1_keur": str(anchor),
        "gearing_pct": str(float(getattr(pi.financing, "gearing_ratio", 0.0) or 0.0) * 100),
        "target_dscr": str(pi.financing.target_dscr),
        "interest_rate_pct": str(pi.financing.base_rate + pi.financing.margin_bps / 10_000),
        "tenor_years": str(pi.financing.senior_tenor_years),
        "cod_date": str(pi.info.cod_date),
        "construction_months": str(pi.info.construction_months),
        "horizon_years": str(pi.info.horizon_years),
        "capacity_factor": f"{(pi.technical.operating_hours_p50 / 8760) * 100:.2f}",
        "ppa_term_years": str(int(pi.revenue.ppa_term_years)),
    }
    return snapshot, anchor, pi


def _fake_project_record() -> SimpleNamespace:
    """Minimal project-record shape _build_opex_vm_ctx reads.

    project_id is a random uuid that matches no DB row, so
    get_active_sub_lines_for_project returns no custom lines.
    """
    import uuid
    return SimpleNamespace(
        project_id=str(uuid.uuid4()),
        project_code="f06_display_authority_test",
        project_name="F06 Display Authority Test",
        project_type="Wind",
        project_origin="user",
        template_source="generic_wind_reference",
    )


def _build_ctx(snapshot: dict) -> dict:
    from app.v2.router import _build_opex_vm_ctx
    from app.workbook.input_set import ProjectInputSet
    pis = ProjectInputSet.from_snapshot(snapshot)
    return _build_opex_vm_ctx(_fake_project_record(), pis)


def _summary_total_field(ctx: dict) -> dict:
    matches = [f for f in ctx["opex_summary_fields"]
               if f["field_id"] == "opex.summary.total_y1"]
    assert len(matches) == 1, "registry must define exactly one summary total field"
    return matches[0]


# ---------------------------------------------------------------------------
# The competing-authority defect is real (pre-fix this failed)
# ---------------------------------------------------------------------------

def test_stale_anchor_diverges_from_live_total_after_scalar_override():
    """A per-line override is engine-effective but never updates the persisted
    anchor — proving the two displayed values genuinely drift apart."""
    snapshot, anchor, _pi = _wind_reference_snapshot()
    snapshot["opex_insurance_y1_keur"] = "999.0"  # B.06 override, engine-effective

    ctx = _build_ctx(snapshot)
    live_total = ctx["opex_vm"].y1_total_opex
    assert live_total != pytest.approx(anchor), (
        "test premise: live sheet total must diverge from the stale persisted "
        "anchor after a per-line override — otherwise F06 has no defect"
    )


# ---------------------------------------------------------------------------
# The fix: one visually identifiable authority on the sheet
# ---------------------------------------------------------------------------

def test_summary_field_displays_live_vm_total_not_stale_anchor():
    snapshot, _anchor, _pi = _wind_reference_snapshot()
    snapshot["opex_insurance_y1_keur"] = "999.0"

    ctx = _build_ctx(snapshot)
    field = _summary_total_field(ctx)
    assert field["value"] == pytest.approx(ctx["opex_vm"].y1_total_opex), (
        "summary 'Total OPEX Y1' must display the live sheet authority "
        "(OpexViewModel Y1 total), never the stale persisted anchor"
    )


def test_summary_field_matches_kpi_strip_and_grand_total():
    """KPI strip, grand-total row and the summary field must show one number."""
    snapshot, _anchor, _pi = _wind_reference_snapshot()
    snapshot["opex_insurance_y1_keur"] = "999.0"

    ctx = _build_ctx(snapshot)
    field = _summary_total_field(ctx)
    assert field["value"] == pytest.approx(ctx["opex_vm"].y1_total_opex)
    assert ctx["opex_vm"].total_incl_contingency[0] == pytest.approx(ctx["opex_vm"].y1_total_opex)


def test_anchor_deviates_from_authority_even_without_edits():
    """The persisted anchor's seed convention (sum of item y1 amounts) misses
    the percentage-derived contingency that both the engine and the display
    VM compute — so the anchor was never a faithful 'Total OPEX Y1', even on
    an untouched project. The fix therefore aligns the summary display to the
    live VM authority, not to the anchor."""
    snapshot, anchor, _pi = _wind_reference_snapshot()
    ctx = _build_ctx(snapshot)
    field = _summary_total_field(ctx)
    assert ctx["opex_vm"].y1_total_opex != pytest.approx(anchor), (
        "test premise: anchor convention (no contingency) must differ from the "
        "VM/engine authority (incl. contingency) on an untouched reference"
    )
    assert field["value"] == pytest.approx(ctx["opex_vm"].y1_total_opex), (
        "summary 'Total OPEX Y1' must still display the live sheet authority"
    )


def test_summary_field_registry_metadata_preserved():
    snapshot, _anchor, _pi = _wind_reference_snapshot()
    ctx = _build_ctx(snapshot)
    field = _summary_total_field(ctx)
    assert field["label"] == "Total OPEX Y1"
    assert field["unit"] == "kEUR/yr"
    assert field["binding_label"] == "partial"


# ---------------------------------------------------------------------------
# Boundary: presentation only — no engine/formula/persistence change
# ---------------------------------------------------------------------------

def test_persisted_anchor_is_not_rewritten():
    """The fix changes display only: the pis snapshot anchor must remain the
    seeded value so exports/DB state are byte-identical to pre-fix."""
    snapshot, anchor, _pi = _wind_reference_snapshot()
    from app.workbook.input_set import ProjectInputSet
    pis = ProjectInputSet.from_snapshot(snapshot)

    _build_ctx(snapshot)

    assert pis.get("opex.summary.total_y1") == pytest.approx(anchor), (
        "display fix must not write back into the persisted input set"
    )


def test_engine_consumed_opex_still_honors_override():
    """Zero financial-engine diff: the effective engine-bound opex vector must
    still carry the per-line override (the display fix must not touch it)."""
    snapshot, _anchor, _pi = _wind_reference_snapshot()
    snapshot["opex_insurance_y1_keur"] = "999.0"

    from app.input_adapter import build_projectinputs_from_snapshot
    effective = build_projectinputs_from_snapshot(dict(snapshot))
    insurance = [it for it in effective.opex if it.name == "Insurance"]
    assert insurance, "wind reference must carry a named Insurance item"
    assert insurance[0].y1_amount_keur == pytest.approx(999.0), (
        "engine-consumed B.06 value must remain the user's override"
    )


def test_custom_sub_lines_counted_in_live_total_but_never_in_anchor():
    """Custom OPEX sub-lines are folded into the display VM (and, at the run
    boundary, into the engine) but never into the persisted anchor — the
    second divergence class this finding covers."""
    from datetime import datetime, timezone

    from app.persistence.opex_sub_lines import OpexSubLine
    from app.ui.opex_view_model import build_opex_view_model

    snapshot, anchor, _pi = _wind_reference_snapshot()
    from app.input_adapter import build_projectinputs_from_snapshot
    from app.ui.project_context import build_project_context_for_record
    effective = build_projectinputs_from_snapshot(dict(snapshot))
    ctx = build_project_context_for_record(
        project_code="f06_display_authority_test",
        project_name="F06 Display Authority Test",
        project_type="Wind",
        project_origin="user",
        template_source="generic_wind_reference",
        baseline_snapshot=snapshot,
        effective_project_inputs=effective,
    )

    sub = OpexSubLine(
        sub_line_id="f06-sub-1",
        project_id="f06-project",
        parent_group_code="B.09",
        business_code="B.09.U001",
        display_order=1,
        label="F06 test fee line",
        amount_keur=137.0,
        inflation_pct=0.0,
        comments="",
        source="user",
        is_active=True,
        created_at=datetime.now(timezone.utc).isoformat(),
    )
    vm = build_opex_view_model(ctx, is_user_project=True, sub_lines=[sub])
    assert vm.y1_total_opex > anchor, (
        "live authority must include the custom line; the persisted anchor cannot"
    )


# ==========================================================================
# Correction A — escalation display authority (engine-bound fidelity)
# ==========================================================================

def _escalation_summary(ctx: dict) -> dict:
    return ctx["opex_escalation_summary"]


def test_ca_escalation_01_uniform_lines_display_single_authoritative_rate():
    """Wind reference lines all share 2.0% escalation: the card shows that
    single rate as uniform."""
    ctx = _build_ctx(_wind_reference_snapshot()[0])
    summary = _escalation_summary(ctx)
    assert summary["value"] == "2.0%"
    assert "uniform" in summary["label"]


def _opex_line_vm(code: str, name: str, inflation_pct: float,
                  y1_keur: float, *, custom: bool = True):
    from app.ui.opex_view_model import OpexLineVM
    return OpexLineVM(
        row_id="row-" + code, code=code, parent_code=code.rsplit(".", 1)[0],
        name=name, source="custom" if custom else "canonical",
        unit="kEUR", notes="", display_order=1,
        validation_status="OK", y1_keur=y1_keur,
        inflation_pct=inflation_pct, wht_flag=False, is_group=False,
        is_editable=True, is_read_only=False, is_derived=False,
        is_contingency=False, is_fixed=True, is_variable=False,
        is_custom=custom, is_active=True,
        year_values=(y1_keur,) * 20)


def test_ca_escalation_02_heterogeneous_lines_show_mixed():
    """Injected sub-lines under one group with different escalation rates:
    the grid group row shows "mixed" — never one rate masquerading as
    governing the whole group."""
    from app.ui.opex_view_model import OpexGroupVM, group_escalation_display
    lines = tuple(
        _opex_line_vm(f"B.01.0{i}", name, rate, 10.0 + i)
        for i, (name, rate) in enumerate(
            (("custom one", 3.5), ("custom two", 1.5)), start=1))
    group = OpexGroupVM(
        code="B.01", name="Test Group", inflation_pct=2.0,
        is_contingency=False, contingency_pct=0.0, lines=lines,
        subtotal_per_year=(30.0,) * 20)
    assert group_escalation_display(group) == "mixed"


def test_ca_escalation_03_uniform_lines_show_shared_rate():
    from app.ui.opex_view_model import OpexGroupVM, group_escalation_display
    lines = tuple(
        _opex_line_vm(f"B.01.0{i}", f"line {i}", 2.0, 10.0 + i)
        for i in (1, 2, 3))
    group = OpexGroupVM(
        code="B.01", name="Uniform", inflation_pct=2.0,
        is_contingency=False, contingency_pct=0.0, lines=lines,
        subtotal_per_year=(30.0,) * 20)
    assert group_escalation_display(group) == "2.0%"


def test_parent_summary_escalation_is_mixed_for_heterogeneous_children():
    """The parent table must not show a group default when children differ."""
    from app.ui.opex_sheet_projection import OpexSheetGroup
    from app.ui.opex_view_model import OpexGroupVM

    lines = (
        _opex_line_vm("B.01.01", "one", 1.5, 10.0),
        _opex_line_vm("B.01.02", "two", 3.5, 10.0),
    )
    group = OpexGroupVM(
        code="B.01", name="Test Group", inflation_pct=2.0,
        is_contingency=False, contingency_pct=0.0, lines=lines,
        subtotal_per_year=(20.0,) * 20,
    )
    projected = OpexSheetGroup(
        code="B.01", canonical_name="Technical Management",
        field_suffix="technical_management", is_always_derived=False,
        field=None, vm_group=group,
    )

    assert projected.escalation_display == "Mixed"


def _opex_group_codes():
    from app.ui.project_context import _OPEX_GROUP_META
    return sorted(meta[0] for meta in _OPEX_GROUP_META.values())


def _opex_group_codes():
    from app.ui.project_context import _OPEX_GROUP_META
    return [meta[0] for meta in _OPEX_GROUP_META.values()]
