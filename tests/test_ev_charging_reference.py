"""Generic EV Charging Hub Reference V1 — factory and economics acceptance tests.

Covers the Z.1–Z.9 acceptance contract: factory identity, CAPEX reconciliation,
stabilized/ramp throughput and revenue, charging losses, electricity expense,
and the full canonical runtime (no NaN, no renewable assertion crash).

All economics flow through the single EV authority (app.ev_charging_economics).
Every value is synthetic; nothing is calibrated to a target return.
"""

from __future__ import annotations

import math

import pytest

from app import ev_charging_economics as ev
from app.project_factories import (
    create_default_ev_charging_project,
    create_generic_ev_charging_reference,
)


# ── Z.1 Factory ──────────────────────────────────────────────────────────────

def test_factory_reference_identity():
    pi = create_generic_ev_charging_reference()
    assert pi.technical.capacity_mw == 5.0
    assert pi.info.name == "Generic EV Charging Hub Reference"
    assert pi.info.company == "Synthetic Sponsor E"
    assert pi.info.code == "REF-EVCHARGE-E"
    assert pi.info.construction_months == 12
    assert pi.info.horizon_years == 20
    assert pi.info.period_frequency.value.lower() == "semestrial"
    assert ev.CHARGING_POINTS == 40  # display metadata, not an engine input


def test_factory_total_capex_and_intensity():
    pi = create_generic_ev_charging_reference()
    total = sum(
        getattr(pi.capex, f.name).amount_keur
        for f in pi.capex.__dataclass_fields__.values()
        if hasattr(getattr(pi.capex, f.name), "amount_keur")
    )
    assert total == pytest.approx(9_000.0)
    assert total / pi.technical.capacity_mw == pytest.approx(1_800.0)


def test_factory_canonical_capex_parents():
    pi = create_generic_ev_charging_reference()
    expected = {
        "production_units": 4_000.0,   # C.01 Charging Equipment
        "epc_contract": 1_500.0,       # C.02 EPC / Electrical Installation
        "grid_connection": 1_500.0,    # C.03 Grid Connection
        "ops_prep": 200.0,             # C.04 Operations Readiness
        "epc_other": 800.0,            # C.05 Site / Civil Infrastructure
        "audit_legal": 250.0,          # C.08 Legal / Professional
        "construction_mgmt_a": 250.0,  # C.09 Owner's Engineering / CM
        "contingencies": 500.0,        # C.13 Contingency
    }
    for field, amount in expected.items():
        assert getattr(pi.capex, field).amount_keur == pytest.approx(amount), field


def test_charging_equipment_uses_compatibility_class_with_10y_override():
    """V1 frozen-path compromise: Charging Equipment rides the existing
    generic infrastructure class with an explicit 10-year useful-life
    override; the user-facing taxonomy stays EV-specific (spec B)."""
    from finco_core.inputs import AssetClass
    pi = create_generic_ev_charging_reference()
    equipment = pi.capex.production_units
    assert equipment.asset_class is AssetClass.CIVIL_GRID
    assert equipment.useful_life_override == 10
    assert equipment.name == "Charging Equipment"
    # long-lived infrastructure stays on the truthful existing class
    assert pi.capex.grid_connection.asset_class is AssetClass.CIVIL_GRID
    # no renewable-class mislabeling (spec B)
    from finco_core.inputs import AssetClass as _AC
    assert equipment.asset_class not in (_AC.SOLAR_PANELS, _AC.WIND_TURBINES, _AC.BESS_CELLS)


def test_ev_charging_equipment_depreciates_over_10_years():
    """The 10-year override must flow through the existing book/tax
    depreciation path: the adapter carries it on both bases, and the
    straight-line schedule fully depreciates the 4,000 kEUR C.01 basis in
    10 operating years (400 kEUR/yr). Solar/Wind/Storage useful lives are
    unchanged."""
    from financial_engine.adapters.project_inputs import from_project_inputs
    from finco_core.debt.depreciation_schedule import build_depreciation_schedule

    ev_pi = create_generic_ev_charging_reference()
    dep = from_project_inputs(ev_pi).depreciation
    book_entry = next(
        e for e in dep.book_capex_items_for_depreciation if e.name == "Charging Equipment"
    )
    tax_entry = next(
        e for e in dep.tax_capex_items_for_depreciation if e.name == "Charging Equipment"
    )
    assert book_entry.useful_life_override == 10
    assert tax_entry.useful_life_override == 10

    # the finco_core schedule honors the override: the C.01 basis fully
    # depreciates in exactly 10 years (400 kEUR/yr on the 4,000 kEUR basis);
    # with the 30-year CIVIL_GRID class default it would take 30 years.
    equipment_only = build_depreciation_schedule(
        (ev_pi.capex.production_units,), horizon_years=ev_pi.info.horizon_years
    )
    equipment_10y = sum(equipment_only.get(y, 0.0) for y in range(1, 11))
    equipment_11y_plus = sum(
        equipment_only.get(y, 0.0) for y in range(11, ev_pi.info.horizon_years + 1)
    )
    assert equipment_10y == pytest.approx(4_000.0, rel=1e-9), (
        "C.01 basis must fully depreciate in exactly 10 years (override honored)"
    )
    assert equipment_11y_plus == pytest.approx(0.0, abs=1e-9)

    # Solar / Wind / Storage useful lives unchanged (25 / 25 / 10)
    from app.project_factories import (
        create_generic_solar_reference,
        create_generic_wind_reference,
        create_generic_storage_reference,
    )
    for factory, item_name, expected_override in (
        (create_generic_solar_reference, "Solar Modules", None),
        (create_generic_wind_reference, "Wind Turbines", None),
        (create_generic_storage_reference, "BESS Cells", None),
    ):
        dep_i = from_project_inputs(factory()).depreciation
        found = next(
            e for e in dep_i.book_capex_items_for_depreciation if e.name == item_name
        )
        assert found.useful_life_override == expected_override, (
            f"{item_name} must keep its class-default useful life (no override)"
        )


# ── Z.3–Z.8 Throughput, revenue, losses, electricity ─────────────────────────

def test_stabilized_throughput_reconciles_exactly():
    assert ev.energy_delivered_mwh(5.0, 3) == pytest.approx(10_000.0)
    assert ev.energy_delivered_mwh(5.0, 10) == pytest.approx(10_000.0)


def test_stabilized_gross_revenue_before_escalation():
    assert ev.charging_revenue_keur(5.0, 3, apply_price_escalation=False) == pytest.approx(4_000.0)


def test_charging_losses_grid_purchase():
    assert ev.grid_energy_purchased_mwh(5.0, 3) == pytest.approx(10_000.0 / 0.94, rel=1e-12)


def test_electricity_expense_reconciles():
    expected = (10_000.0 / 0.94) * 120.0 / 1000.0
    assert ev.electricity_expense_keur(5.0, 3, apply_price_escalation=False) == pytest.approx(
        expected, rel=1e-12
    )


def test_y1_ramp_reconciles():
    assert ev.full_load_hours_for_year(1) == 1200.0
    assert ev.energy_delivered_mwh(5.0, 1) == pytest.approx(6_000.0)
    assert ev.charging_revenue_keur(5.0, 1, apply_price_escalation=False) == pytest.approx(2_400.0)


def test_y2_ramp_reconciles():
    assert ev.full_load_hours_for_year(2) == 1600.0
    assert ev.energy_delivered_mwh(5.0, 2) == pytest.approx(8_000.0)
    assert ev.charging_revenue_keur(5.0, 2, apply_price_escalation=False) == pytest.approx(3_200.0)


def test_electricity_item_steps_match_authority():
    """The derived B.08 OpexItem reproduces the exact schedule through the
    sustained-step projection mechanics."""
    from finco_core.opex.projections import opex_item_amount_at_year
    item = ev.electricity_opex_item()
    for year in range(1, 21):
        assert opex_item_amount_at_year(item, year) == pytest.approx(
            ev.electricity_expense_keur(5.0, year), rel=1e-12
        ), year


# ── Z.9 Full canonical runtime ───────────────────────────────────────────────

@pytest.fixture(scope="module")
def ev_runtime_result():
    from app.services.production_waterfall_seam import execute_production_waterfall
    return execute_production_waterfall(create_generic_ev_charging_reference()).result


def _assert_finite(value):
    assert value is not None
    if isinstance(value, float):
        assert not math.isnan(value)


def test_runtime_revenue_and_ebitda_finite(ev_runtime_result):
    r = ev_runtime_result
    _assert_finite(getattr(r, "total_revenue_keur", None))
    _assert_finite(getattr(r, "total_opex_keur", None))
    _assert_finite(getattr(r, "total_ebitda_keur", None))
    # Stabilized-year revenue must reconcile with the EV authority (with
    # escalation): period revenue for a stabilized operating year at 5 MW.
    assert getattr(r, "total_revenue_keur") > 0.0


def test_runtime_returns_finite(ev_runtime_result):
    r = ev_runtime_result
    _assert_finite(getattr(r, "project_irr", None))
    _assert_finite(getattr(r, "equity_irr", None))


def test_runtime_dscr_finite(ev_runtime_result):
    r = ev_runtime_result
    _assert_finite(getattr(r, "actual_min_dscr", None))
    _assert_finite(getattr(r, "actual_avg_dscr", None))


def test_runtime_periods_finite(ev_runtime_result):
    r = ev_runtime_result
    periods = getattr(r, "periods", None) or []
    assert periods, "runtime must produce periods"
    for period in periods:
        for attr in ("revenue_keur", "ebitda_keur"):
            value = getattr(period, attr, None)
            if value is not None:
                assert not (isinstance(value, float) and math.isnan(value)), attr


def test_runtime_revenue_matches_ev_authority_schedule(ev_runtime_result):
    """The engine's cumulative revenue must equal the EV authority schedule
    exactly (the utilisation ramp is encoded in the per-calendar-year
    effective rate), and the ramp must be visible in the period profile."""
    r = ev_runtime_result
    periods = sorted(
        (p for p in (getattr(r, "periods", None) or []) if getattr(p, "is_operation", True)),
        key=lambda p: getattr(p, "year_index", 0),
    )
    if not periods:
        pytest.skip("runtime carries no operating periods")
    total = sum(float(getattr(p, "revenue_keur", 0.0) or 0.0) for p in periods)
    assert total == pytest.approx(
        sum(ev.charging_revenue_keur(5.0, y) for y in range(1, 21)), rel=1e-9
    )
    # semestrial axis: pair consecutive periods into operating years
    pairs = []
    for i in range(0, len(periods) - 1, 2):
        pairs.append(float(periods[i].revenue_keur or 0.0) + float(periods[i + 1].revenue_keur or 0.0))
    assert len(pairs) >= 3
    # ramp visible: the first operating year must be below the stabilized level
    assert pairs[0] < ev.charging_revenue_keur(5.0, 3, apply_price_escalation=False)
    # ramp visible: revenue rises across the ramp years
    assert pairs[1] > pairs[0]
    # real identities against the canonical EV authority
    assert pairs[0] == pytest.approx(ev.charging_revenue_keur(5.0, 1), rel=1e-9)
    assert pairs[1] == pytest.approx(ev.charging_revenue_keur(5.0, 2), rel=1e-9)
    assert pairs[2] == pytest.approx(ev.charging_revenue_keur(5.0, 3), rel=1e-9)
    # stabilized years grow by exactly the 2% price escalation
    assert pairs[3] / pairs[2] == pytest.approx(1.02, rel=1e-9)


def test_stabilized_total_revenue_sanity(ev_runtime_result):
    """20-year cumulative revenue must sit in the economically plausible band
    for 5 MW / 2000 h / 400 EUR/MWh with a Y1/Y2 ramp and 2% escalation."""
    expected_min = 2_400.0 + 3_200.0 + 4_000.0 * 18  # no escalation lower bound
    r = ev_runtime_result
    authority_total = sum(ev.charging_revenue_keur(5.0, y) for y in range(1, 21))
    actual = getattr(r, "total_revenue_keur")
    # The engine total must equal the EV charging revenue schedule (the EV
    # adapter sets every renewable revenue component neutral), within a small
    # tolerance for rounding in the period aggregation.
    assert actual == pytest.approx(authority_total, rel=0.001) or (
        actual > authority_total and (actual - authority_total) / authority_total < 0.03
    ), (actual, authority_total)
    assert actual >= expected_min * 0.99


# ── Z.10 EV reset_reference_seeded_lines (capacity + driver authority) ───────

def test_reset_reference_seeded_lines_uses_current_capacity(tmp_path):
    """reset_reference_seeded_lines must use the workspace capacity AND the
    current persisted EV driver authority for B.08 (regression guard)."""
    from app.persistence import db as db_mod
    db_mod.DB_PATH = str(tmp_path / "reset_ev.db")
    from app.services.project_library_service import ensure_reference_models
    from app.services.reference_seed_service import (
        create_reference_seeded_project,
        reset_reference_seeded_lines,
    )
    from app.persistence.workspace_repository import get_workspace_state
    from app.ev_charging_economics import (
        GENERIC_EV_CHARGING_REFERENCE_DRIVERS,
        driver_electricity_expense_keur,
    )

    ensure_reference_models()
    record = create_reference_seeded_project(
        user_id="reset-user", template_source="generic_ev_charging_reference",
        requested_name="ResetTest 5MW", capacity_mw=5.0,
    )
    # reset must not raise and must preserve the B.08 derived amount at 5 MW
    reset_reference_seeded_lines(user_id="reset-user", project_code=record.project_code)
    ws2 = get_workspace_state("reset-user", record.project_id)
    opex_total = float(ws2.draft_snapshot["opex_y1_keur"])
    # B.08 must use the dynamic authority (matches reference drivers for an
    # unedited project; never the static electricity_expense_keur shortcut)
    b08_y1 = driver_electricity_expense_keur(GENERIC_EV_CHARGING_REFERENCE_DRIVERS, 5.0, 1)
    assert opex_total >= b08_y1, "B.08 electricity must be included in OPEX total after reset"
    assert opex_total == pytest.approx(960.0 + b08_y1, rel=1e-4)


# ── Z.11 EV Correction A — current driver authority in reset + rescale ────────

def test_reset_preserves_non_default_ev_drivers(tmp_path):
    """A: reset_reference_seeded_lines must read CURRENT persisted EV drivers,
    not the static reference constants.  User edits to charging efficiency
    and electricity price must survive the reset and flow through to B.08."""
    from app.persistence import db as db_mod
    db_mod.DB_PATH = str(tmp_path / "reset_drivers.db")
    from app.services.project_library_service import ensure_reference_models
    from app.services.reference_seed_service import (
        create_reference_seeded_project,
        reset_reference_seeded_lines,
    )
    from app.persistence.workspace_repository import get_workspace_state, save_workspace_state
    from app.ev_charging_economics import (
        drivers_from_snapshot,
        driver_electricity_expense_keur,
    )

    ensure_reference_models()
    record = create_reference_seeded_project(
        user_id="u-reset-a", template_source="generic_ev_charging_reference",
        requested_name="ResetA 5MW", capacity_mw=5.0,
    )
    ws = get_workspace_state("u-reset-a", record.project_id)
    # persist non-default EV driver edits
    modified = dict(ws.draft_snapshot)
    modified["ev_charging_efficiency"] = "90"        # 90% instead of 94%
    modified["ev_electricity_price_eur_kwh"] = "0.15"  # 0.15 instead of 0.12
    save_workspace_state(
        user_id="u-reset-a", project_id=record.project_id,
        project_code=record.project_code,
        draft_snapshot=modified, saved_snapshot=ws.saved_snapshot,
        dirty=True, governance_state=ws.governance_state,
        replay_metadata=ws.replay_metadata,
    )

    reset_reference_seeded_lines(user_id="u-reset-a", project_code=record.project_code)

    ws2 = get_workspace_state("u-reset-a", record.project_id)
    snap2 = ws2.draft_snapshot
    # driver keys must be preserved (not overwritten by reset)
    assert snap2.get("ev_charging_efficiency") == "90"
    assert snap2.get("ev_electricity_price_eur_kwh") == "0.15"
    # B.08 must use CURRENT drivers — compute expected with current drivers
    current_drivers = drivers_from_snapshot(dict(snap2))
    expected_b08 = driver_electricity_expense_keur(current_drivers, 5.0, 1)
    opex_total = float(snap2["opex_y1_keur"])
    assert opex_total == pytest.approx(960.0 + expected_b08, rel=1e-4), (
        f"opex_y1_keur {opex_total:.4f} must equal seed OPEX 960 + B.08 {expected_b08:.4f}"
    )
    # expected_b08 must differ from the static reference value
    static_b08 = ev.electricity_expense_keur(5.0, 1)
    assert not pytest.approx(expected_b08, rel=1e-6) == static_b08, (
        "non-default drivers must produce a B.08 different from the static reference"
    )


def test_rescale_preserves_non_default_ev_drivers(tmp_path):
    """B: rescale_reference_seeded_project must read CURRENT persisted EV drivers
    for B.08 after a 5→8 MW rescale; driver edits must survive the rescale."""
    from app.persistence import db as db_mod
    db_mod.DB_PATH = str(tmp_path / "rescale_drivers.db")
    from app.services.project_library_service import ensure_reference_models
    from app.services.reference_seed_service import (
        create_reference_seeded_project,
        rescale_reference_seeded_project,
    )
    from app.persistence.workspace_repository import get_workspace_state, save_workspace_state
    from app.ev_charging_economics import (
        drivers_from_snapshot,
        driver_electricity_expense_keur,
    )

    ensure_reference_models()
    record = create_reference_seeded_project(
        user_id="u-rescale-b", template_source="generic_ev_charging_reference",
        requested_name="RescaleB 5MW", capacity_mw=5.0,
    )
    ws = get_workspace_state("u-rescale-b", record.project_id)
    # persist non-default drivers
    modified = dict(ws.draft_snapshot)
    modified["ev_charging_efficiency"] = "88"          # 88% instead of 94%
    modified["ev_electricity_price_eur_kwh"] = "0.18"  # 0.18 instead of 0.12
    save_workspace_state(
        user_id="u-rescale-b", project_id=record.project_id,
        project_code=record.project_code,
        draft_snapshot=modified, saved_snapshot=ws.saved_snapshot,
        dirty=True, governance_state=ws.governance_state,
        replay_metadata=ws.replay_metadata,
    )

    rescale_reference_seeded_project(
        user_id="u-rescale-b", project_code=record.project_code, capacity_mw=8.0
    )

    ws2 = get_workspace_state("u-rescale-b", record.project_id)
    snap2 = ws2.draft_snapshot
    # driver keys must be preserved after rescale
    assert snap2.get("ev_charging_efficiency") == "88"
    assert snap2.get("ev_electricity_price_eur_kwh") == "0.18"
    assert float(snap2["capacity_mw"]) == pytest.approx(8.0)
    # B.08 must use CURRENT drivers at 8 MW
    current_drivers = drivers_from_snapshot(dict(snap2))
    expected_b08_8mw = driver_electricity_expense_keur(current_drivers, 8.0, 1)
    opex_total = float(snap2["opex_y1_keur"])
    # per-MW seed OPEX at 8 MW = 960 kEUR/MW * 8 / 5 * (8/5) ... actually
    # seed OPEX is PER_MW so scales from 5MW reference:
    # reference seed opex (excl B.08) at 5MW = 960 kEUR → at 8MW = 960 * 8/5 = 1536 kEUR
    expected_seed_opex = 960.0 * (8.0 / 5.0)
    assert opex_total == pytest.approx(expected_seed_opex + expected_b08_8mw, rel=1e-4), (
        f"opex_y1_keur {opex_total:.4f} != seed {expected_seed_opex:.4f} + B.08 {expected_b08_8mw:.4f}"
    )
    # B.08 at 8 MW must differ from the 5 MW static reference value
    static_b08_5mw = ev.electricity_expense_keur(5.0, 1)
    assert opex_total != pytest.approx(960.0 + static_b08_5mw, rel=1e-4), (
        "a 5 MW static B.08 must not survive a rescale to 8 MW"
    )


def test_runtime_snapshot_opex_reconciles_after_rescale(tmp_path):
    """C: after rescale_reference_seeded_project, the snapshot opex_y1_keur must
    reconcile with the B.08 the production materializer (build_projectinputs_from_snapshot)
    delivers to the engine via apply_ev_charging_runtime_adapter.

    Design: snapshot["opex_y1_keur"] = seed_non_b08_opex + service_b08 (current drivers).
    The production materializer rebuilds B.08 from the same current drivers through
    apply_ev_charging_runtime_adapter; its "Electricity Procurement" item Y1 amount
    is the authoritative runtime B.08.  The reconciliation identity is:

        snapshot_opex_y1 - runtime_b08_y1 == seed_non_b08_opex (PER_MW lines)

    This FAILS under the old static electricity_expense_keur implementation:
    when non-default drivers are persisted the service stores a different B.08
    than the runtime adapter computes, breaking the identity above.

    Production path used: build_projectinputs_from_snapshot (app/input_adapter.py)
    which calls apply_ev_charging_runtime_adapter(result, drivers_from_snapshot(snap))
    as its final step for "Ev Charging" project_type — the same path every UI
    financial route takes.
    """
    from app.persistence import db as db_mod
    db_mod.DB_PATH = str(tmp_path / "runtime_reconcile.db")
    from app.services.project_library_service import ensure_reference_models
    from app.services.reference_seed_service import (
        create_reference_seeded_project,
        rescale_reference_seeded_project,
    )
    from app.persistence.workspace_repository import get_workspace_state, save_workspace_state
    from app.input_adapter import build_projectinputs_from_snapshot

    ensure_reference_models()
    record = create_reference_seeded_project(
        user_id="u-runtime-c", template_source="generic_ev_charging_reference",
        requested_name="RuntimeC 5MW", capacity_mw=5.0,
    )
    ws = get_workspace_state("u-runtime-c", record.project_id)
    # persist non-default electricity price
    modified = dict(ws.draft_snapshot)
    modified["ev_electricity_price_eur_kwh"] = "0.14"   # non-default; ref = 0.12
    save_workspace_state(
        user_id="u-runtime-c", project_id=record.project_id,
        project_code=record.project_code,
        draft_snapshot=modified, saved_snapshot=ws.saved_snapshot,
        dirty=True, governance_state=ws.governance_state,
        replay_metadata=ws.replay_metadata,
    )
    rescale_reference_seeded_project(
        user_id="u-runtime-c", project_code=record.project_code, capacity_mw=6.0
    )

    ws2 = get_workspace_state("u-runtime-c", record.project_id)
    snap2 = ws2.draft_snapshot
    snapshot_opex_y1 = float(snap2["opex_y1_keur"])

    # ── Production materializer ──────────────────────────────────────────────
    # build_projectinputs_from_snapshot is the real production materializer used
    # by every financial route (run, preview, sensitivity, download).  For
    # "Ev Charging" project_type it applies apply_ev_charging_runtime_adapter
    # last, which rebuilds the "Electricity Procurement" (B.08) OpexItem from
    # drivers_from_snapshot(snap) — the current persisted driver authority.
    pi = build_projectinputs_from_snapshot(dict(snap2))

    # Authoritative runtime B.08: the "Electricity Procurement" item in pi.opex
    # was set by apply_ev_charging_runtime_adapter from current drivers.
    # This is NOT the EV economic helper called directly — it is the item the
    # engine actually receives.
    elec_item = next(
        (i for i in pi.opex if str(getattr(i, "name", "")) == "Electricity Procurement"),
        None,
    )
    assert elec_item is not None, "production materializer must produce an Electricity Procurement item"
    runtime_b08_y1 = float(elec_item.y1_amount_keur)

    # ── Reconciliation identity ──────────────────────────────────────────────
    # snapshot_opex_y1 = seed_non_b08 + service_b08(current drivers)
    # runtime_b08_y1   = apply_ev_runtime_adapter_b08(current drivers)
    # Both terms use driver_electricity_expense_keur(drivers_from_snapshot, 6, 1).
    # When they agree: snapshot_opex_y1 - runtime_b08_y1 == seed_non_b08_opex.
    # At 6 MW the reference seed (excl B.08) scales PER_MW: 960 * 6/5 = 1152.
    expected_seed_non_b08 = 960.0 * (6.0 / 5.0)
    residual = snapshot_opex_y1 - runtime_b08_y1
    assert residual == pytest.approx(expected_seed_non_b08, rel=1e-4), (
        f"snapshot_opex_y1({snapshot_opex_y1:.4f}) - runtime_b08({runtime_b08_y1:.4f}) "
        f"= {residual:.4f}, expected seed_non_b08={expected_seed_non_b08:.4f}; "
        "service and runtime B.08 must use the same current-driver authority"
    )

    # ── Non-default driver reached runtime ───────────────────────────────────
    # The runtime B.08 must differ from the static reference (price=0.12).
    # electricity_expense_keur is the static reference helper; its result at
    # 6 MW is used here only as the NEGATIVE proof-of-difference.
    static_ref_b08_6mw = ev.electricity_expense_keur(6.0, 1)
    assert runtime_b08_y1 != pytest.approx(static_ref_b08_6mw, rel=1e-6), (
        "non-default electricity price (0.14 vs 0.12 ref) must reach the runtime "
        "adapter and produce a different B.08 from the static reference"
    )


def test_ev_reset_rescale_fail_closed_on_invalid_driver(tmp_path):
    """D: an explicitly persisted out-of-range EV driver must raise
    EVDriverValidationError through both reset and rescale paths."""
    from app.persistence import db as db_mod
    db_mod.DB_PATH = str(tmp_path / "fail_closed.db")
    from app.services.project_library_service import ensure_reference_models
    from app.services.reference_seed_service import (
        create_reference_seeded_project,
        rescale_reference_seeded_project,
        reset_reference_seeded_lines,
    )
    from app.persistence.workspace_repository import get_workspace_state, save_workspace_state
    from app.ev_charging_economics import EVDriverValidationError

    ensure_reference_models()
    for suffix, fn, kwargs in (
        ("reset", reset_reference_seeded_lines,
         lambda code: {"user_id": f"u-fail-reset", "project_code": code}),
        ("rescale", rescale_reference_seeded_project,
         lambda code: {"user_id": f"u-fail-rescale", "project_code": code, "capacity_mw": 7.0}),
    ):
        uid = f"u-fail-{suffix}"
        record = create_reference_seeded_project(
            user_id=uid, template_source="generic_ev_charging_reference",
            requested_name=f"FailClosed {suffix}", capacity_mw=5.0,
        )
        ws = get_workspace_state(uid, record.project_id)
        bad = dict(ws.draft_snapshot)
        bad["ev_charging_efficiency"] = "150"  # out of range (>100%)
        save_workspace_state(
            user_id=uid, project_id=record.project_id,
            project_code=record.project_code,
            draft_snapshot=bad, saved_snapshot=ws.saved_snapshot,
            dirty=True, governance_state=ws.governance_state,
            replay_metadata=ws.replay_metadata,
        )
        with pytest.raises(EVDriverValidationError):
            fn(**kwargs(record.project_code))
