"""EV Charging V1 — public detail catalogue and seed-adapter tests.

Covers the catalogue half of the acceptance contract: the EV technology key
reconciles in the shared public-generic detail catalogue (no second
allocation engine), Solar/Wind taxonomy is unchanged, and the scaled seed
base keeps every EV economic authority exact at arbitrary capacity.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from app import ev_charging_economics as ev
from app.reference_detail_catalog import (
    capex_children,
    opex_children,
    allocate_parent_amount,
)


EV_CAPEX_PARENTS = ("C.01", "C.02", "C.03", "C.04", "C.05", "C.06", "C.07",
                    "C.08", "C.09", "C.10", "C.11", "C.12", "C.13", "C.14",
                    "C.15", "C.16")
EV_OPEX_PARENTS = ("B.01", "B.02", "B.03", "B.04", "B.05", "B.06", "B.07",
                   "B.08", "B.09", "B.10", "B.11", "B.12", "B.13")


def test_ev_capex_catalogue_reconciles():
    for parent in EV_CAPEX_PARENTS:
        children = capex_children("ev_charging", parent)
        assert children, parent
        assert sum(c.weight for c in children) == Decimal(1), parent


def test_ev_opex_catalogue_reconciles():
    for parent in EV_OPEX_PARENTS:
        children = opex_children(parent, "ev_charging")
        assert children, parent
        assert sum(c.weight for c in children) == Decimal(1), parent


def test_ev_specific_catalogue_labels():
    c01 = [c.label for c in capex_children("ev_charging", "C.01")]
    assert "DC Fast Chargers" in c01
    b08 = [c.label for c in opex_children("B.08", "ev_charging")]
    assert b08 == ["Electricity Procurement"]  # 100% — single derived content
    b02 = [c.label for c in opex_children("B.02", "ev_charging")]
    assert "Preventive Charger Maintenance" in b02
    assert "Meteorological Station Maintenance" not in b02  # no renewable leakage


def test_solar_wind_catalogue_unchanged():
    """The shared catalogue must be untouched for existing technologies."""
    assert [c.label for c in capex_children("solar", "C.01")] == [
        "PV Modules", "Inverters", "Mounting Structure", "DC Cabling and Balance of System",
    ]
    assert [c.label for c in opex_children("B.02", "wind")][0] == "Preventive and Corrective Maintenance"
    # common parents unchanged
    assert [c.label for c in opex_children("B.08", "solar")] == ["Grid Services", "Market and Balancing Services"]


def test_allocate_parent_amount_ev_capex_total():
    """C.01 4,000 kEUR decomposes to exactly 4,000 across the EV children."""
    children = capex_children("ev_charging", "C.01")
    allocated = allocate_parent_amount(4_000.0, children)
    assert sum(a for _, a in allocated) == pytest.approx(4_000.0)
    assert allocated[0][1] == pytest.approx(4_000.0 * 0.55, rel=1e-9)


def test_scaled_ev_reference_inputs_at_reference_capacity_is_identity():
    from app.project_factories import create_generic_ev_charging_reference
    scaled = ev.scaled_ev_reference_inputs(5.0)
    reference = create_generic_ev_charging_reference()
    assert scaled.technical.capacity_mw == reference.technical.capacity_mw
    assert scaled.opex == reference.opex
    assert scaled.capex == reference.capex


def test_scaled_ev_reference_inputs_at_8mw():
    scaled = ev.scaled_ev_reference_inputs(8.0)
    assert scaled.technical.capacity_mw == 8.0
    total = sum(
        getattr(scaled.capex, f.name).amount_keur
        for f in scaled.capex.__dataclass_fields__.values()
        if hasattr(getattr(scaled.capex, f.name), "amount_keur")
    )
    assert total == pytest.approx(9_000.0 * 8 / 5)  # 14,400 kEUR (Z.10)
    fixed = [i for i in scaled.opex if i.name != "Electricity Procurement"]
    assert sum(i.y1_amount_keur for i in fixed) == pytest.approx(960.0 * 8 / 5)


def test_scaled_ev_reference_inputs_electricity_from_drivers():
    from finco_core.opex.projections import opex_item_amount_at_year
    for capacity in (5.0, 8.0, 12.5):
        scaled = ev.scaled_ev_reference_inputs(capacity)
        item = next(i for i in scaled.opex if i.name == "Electricity Procurement")
        for year in (1, 2, 3, 10, 20):
            assert opex_item_amount_at_year(item, year) == pytest.approx(
                ev.electricity_expense_keur(capacity, year), rel=1e-12
            ), (capacity, year)


def test_ev_snapshot_resolution_at_5_and_8mw():
    """The generic snapshot resolver must produce exact EV economics for a
    seeded working copy at any capacity (template_source-driven base)."""
    from app.input_adapter import build_projectinputs_from_snapshot
    from finco_core.opex.projections import opex_item_amount_at_year

    for capacity in (5.0, 8.0):
        anchor = (960.0 + ev.electricity_expense_keur(5.0, 1)) * capacity / 5.0
        snap = {
            "project_name": f"EV WC {capacity}", "project_type": "EV Charging",
            "project_origin": "saved_baseline",
            "template_source": "generic_ev_charging_reference",
            "capacity_mw": f"{capacity}", "operating_hours_p50": "2000",
            "p50_hours": "2000", "tariff_eur_mwh": "400", "ppa_term_years": "20",
            "opex_y1_keur": f"{anchor}", "total_capex_keur": f"{9000 * capacity / 5}",
            "target_dscr": "1.3", "gearing_pct": "65", "interest_rate_pct": "6",
            "tenor_years": "10", "construction_months": "12", "horizon_years": "20",
            "cod_date": "2031-01-01", "country_market": "XE", "scenario": "Base",
        }
        out = build_projectinputs_from_snapshot(snap)
        assert out.technical.capacity_mw == pytest.approx(capacity)
        names = [i.name for i in out.opex]
        assert "Electricity Procurement" in names, "derived line must survive resolution"
        item = next(i for i in out.opex if i.name == "Electricity Procurement")
        assert opex_item_amount_at_year(item, 3) == pytest.approx(
            ev.electricity_expense_keur(capacity, 3), rel=1e-12
        )
        total = sum(
            getattr(out.capex, f.name).amount_keur
            for f in out.capex.__dataclass_fields__.values()
            if hasattr(getattr(out.capex, f.name), "amount_keur")
        )
        assert total == pytest.approx(9_000.0 * capacity / 5.0)


def test_snapshot_resolver_rejects_unknown_technology_still():
    """The technology gate stays closed for genuinely unknown types."""
    from app.input_adapter import build_projectinputs_from_snapshot, SnapshotInputError
    snap = {
        "project_name": "X", "project_type": "Fusion", "project_origin": "saved_baseline",
        "capacity_mw": "5", "p50_hours": "2000", "opex_y1_keur": "100",
        "total_capex_keur": "1000", "tariff_eur_mwh": "50", "ppa_term_years": "10",
        "cod_date": "2031-01-01", "construction_months": "12", "horizon_years": "20",
        "country_market": "XA", "scenario": "Base",
    }
    with pytest.raises(SnapshotInputError):
        build_projectinputs_from_snapshot(snap)
