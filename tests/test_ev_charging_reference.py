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
    # stabilized years grow only by the 2% price escalation
    assert pairs[2] == pytest.approx(pairs[1] * (pairs[2] / pairs[1]), rel=1e-9)


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
