"""EV Charging Correction B — runtime driver authority acceptance.

Proves that persisted EV drivers are CAUSAL: editing a driver in the working
copy snapshot changes revenue / electricity exactly as the EV authority
dictates, with no stale reference schedule surviving (spec §12).  Also pins
the persisted driver keys (§7), the adapter-runs-last ordering (§8), the
single derived B.08 authority (§10), and non-editable availability policy.
"""

from __future__ import annotations

import pytest

from app import ev_charging_economics as ev
from finco_core.opex.projections import opex_item_amount_at_year


BASE_SNAPSHOT = {
    "project_name": "EV WC", "project_type": "EV Charging",
    "project_origin": "saved_baseline",
    "template_source": "generic_ev_charging_reference", "capacity_mw": "5",
    "operating_hours_p50": "2000", "p50_hours": "2000", "tariff_eur_mwh": "400",
    "ppa_term_years": "20", "opex_y1_keur": "2680", "total_capex_keur": "9000",
    "target_dscr": "1.3", "gearing_pct": "65", "interest_rate_pct": "6",
    "tenor_years": "10", "construction_months": "12", "horizon_years": "20",
    "cod_date": "2031-01-01", "country_market": "XE", "scenario": "Base",
}


@pytest.fixture()
def seeded_workspace(tmp_path_factory):
    """A REAL seeded EV working copy (reconciled S&U) whose snapshot carries
    the persisted driver keys; driver edits are applied to this snapshot."""
    from app.persistence import db as db_mod
    db_mod.DB_PATH = tmp_path_factory.mktemp("corb") / "drivers.db"
    from app.services.project_library_service import ensure_reference_models
    from app.services.reference_seed_service import create_reference_seeded_project
    from app.persistence.workspace_repository import get_workspace_state
    ensure_reference_models()
    record = create_reference_seeded_project(
        user_id="corb-driver-user", template_source="generic_ev_charging_reference",
        requested_name="CorB Drivers 5MW", capacity_mw=5.0,
    )
    return {"record": record, "user_id": "corb-driver-user"}


def _workspace_resolve(seeded_workspace, extra: dict | None = None):
    """Edit the seeded working copy snapshot and resolve + execute."""
    from app.input_adapter import build_projectinputs_from_snapshot
    from app.persistence.workspace_repository import get_workspace_state, save_workspace_state
    record = seeded_workspace["record"]
    user_id = seeded_workspace["user_id"]
    ws = get_workspace_state(user_id, record.project_id)
    snapshot = dict(ws.draft_snapshot)
    snapshot.update(extra or {})
    save_workspace_state(
        user_id=user_id, project_id=record.project_id, project_code=record.project_code,
        draft_snapshot=snapshot, saved_snapshot=ws.saved_snapshot, dirty=True,
        governance_state=ws.governance_state, replay_metadata=ws.replay_metadata,
    )
    ws = get_workspace_state(user_id, record.project_id)
    pi = build_projectinputs_from_snapshot(dict(ws.draft_snapshot))
    elec = next(i for i in pi.opex if i.name == "Electricity Procurement")
    return pi, elec


def _resolve(extra: dict | None = None):
    from app.input_adapter import build_projectinputs_from_snapshot
    snapshot = {**BASE_SNAPSHOT, **(extra or {})}
    out = build_projectinputs_from_snapshot(snapshot)
    elec = next(i for i in out.opex if i.name == "Electricity Procurement")
    return out, elec


def _runtime_revenue_by_year(pi) -> dict[int, float]:
    from app.services.production_waterfall_seam import execute_production_waterfall
    result = execute_production_waterfall(pi).result
    periods = sorted(
        (p for p in (getattr(result, "periods", None) or []) if getattr(p, "is_operation", True)),
        key=lambda p: getattr(p, "year_index", 0),
    )
    pairs = []
    for i in range(0, len(periods) - 1, 2):
        pairs.append(float(periods[i].revenue_keur or 0.0) + float(periods[i + 1].revenue_keur or 0.0))
    return pairs


def _drivers(base=None, **overrides) -> ev.EVChargingDrivers:
    values = {
        "full_load_hours_y1": 1200.0, "full_load_hours_y2": 1600.0,
        "full_load_hours_stabilized": 2000.0,
        "charging_price_eur_kwh": 0.40, "charging_price_escalation": 0.02,
        "charging_efficiency": 0.94,
        "electricity_price_eur_kwh": 0.12, "electricity_price_escalation": 0.02,
    }
    values.update(overrides)
    if base is not None:
        values.update({k: getattr(base, k) for k in values})
    return ev.EVChargingDrivers(**values)


# ── §7: driver authority persisted in the working-copy snapshot ──────────────

def test_ev_working_copy_snapshot_persists_driver_keys():
    from app.persistence import db as db_mod
    import tempfile
    db_mod.DB_PATH = tempfile.mktemp(suffix=".db")
    from app.services.project_library_service import ensure_reference_models
    from app.services.reference_seed_service import create_reference_seeded_project
    from app.persistence.workspace_repository import get_workspace_state

    ensure_reference_models()
    record = create_reference_seeded_project(
        user_id="corb-user", template_source="generic_ev_charging_reference",
        requested_name="CorB 8MW", capacity_mw=8.0,
    )
    ws = get_workspace_state("corb-user", record.project_id)
    for key in ev.EV_DRIVER_SNAPSHOT_KEYS:
        assert key in ws.draft_snapshot and str(ws.draft_snapshot[key]).strip() != "", key
    assert float(ws.draft_snapshot["ev_full_load_hours_y1"]) == 1200.0
    assert float(ws.draft_snapshot["ev_charging_price_eur_kwh"]) == 0.40
    # percent convention: escalation stored as human-%
    assert float(ws.draft_snapshot["ev_charging_price_escalation"]) == 2.0


# ── §9: charging price is causal in the runtime ──────────────────────────────

def test_charging_price_edit_changes_runtime_revenue(seeded_workspace):
    pi, _ = _workspace_resolve(seeded_workspace, {"ev_charging_price_eur_kwh": "0.45"})
    assert pi.revenue.ppa_base_tariff == pytest.approx(450.0)
    pairs = _runtime_revenue_by_year(pi)
    authority_exact = sum(
        5.0 * ev.full_load_hours_for_year(y) * 450.0
        * (1.02 ** (y - 1)) / 1000.0
        for y in range(1, 21)
    )
    total = sum(pairs)
    assert total == pytest.approx(authority_exact, rel=1e-6)
    # the old 400 EUR/MWh authority must not survive
    old_total = sum(ev.charging_revenue_keur(5.0, y) for y in range(1, 21))
    assert total != pytest.approx(old_total, rel=1e-3)


# ── §9/§10: hours edits are causal ───────────────────────────────────────────

def test_stabilized_hours_edit_changes_energy_revenue_and_b08(seeded_workspace):
    pi, elec = _workspace_resolve(seeded_workspace, {"ev_full_load_hours_stabilized": "2200"})
    assert pi.technical.operating_hours_p50 == pytest.approx(2200.0)
    d = _drivers(full_load_hours_stabilized=2200.0)
    # Y3+ electricity rebuilt from the new stabilized hours
    for year in (3, 10, 20):
        assert opex_item_amount_at_year(elec, year) == pytest.approx(
            ev.driver_electricity_expense_keur(d, 5.0, year), rel=1e-12
        )
    pairs = _runtime_revenue_by_year(pi)
    # Y3+ revenue reflects 2200 h at the driver level
    authority_exact = sum(
        5.0 * (2200.0 if y >= 3 else ev.full_load_hours_for_year(y)) * 400.0
        * (1.02 ** (y - 1)) / 1000.0
        for y in range(1, 21)
    )
    assert sum(pairs) == pytest.approx(authority_exact, rel=1e-6)
    baseline = sum(ev.charging_revenue_keur(5.0, y) for y in range(1, 21))
    assert sum(pairs) > baseline  # more stabilized hours → more revenue


def test_y1_hours_edit_changes_y1_only():
    d = _drivers(full_load_hours_y1=1000.0)
    assert ev.__dict__["_driver_ramp"](d) == (1000.0, 1600.0, 2000.0)
    # effective rate Y1 reflects 1000 h; Y2/Y3 unchanged
    assert ev.driver_effective_rate_eur_mwh(d, 1) == pytest.approx(
        400.0 * (1000.0 / 2000.0), rel=1e-12
    )
    assert ev.driver_effective_rate_eur_mwh(d, 2) == pytest.approx(
        400.0 * (1600.0 / 2000.0) * 1.02, rel=1e-12
    )


def test_y2_hours_edit_changes_y2():
    d = _drivers(full_load_hours_y2=1800.0)
    assert ev.driver_effective_rate_eur_mwh(d, 2) == pytest.approx(
        400.0 * (1800.0 / 2000.0) * 1.02, rel=1e-12
    )
    assert ev.driver_effective_rate_eur_mwh(d, 1) == pytest.approx(240.0, rel=1e-12)


# ── §9: efficiency is causal on B.08 only ────────────────────────────────────

def test_efficiency_edit_changes_b08_not_revenue():
    pi_94, elec_94 = _resolve()
    pi_92, elec_92 = _resolve({"ev_charging_efficiency": "92"})
    # revenue authority unchanged
    assert pi_92.revenue.ppa_base_tariff == pi_94.revenue.ppa_base_tariff == pytest.approx(400.0)
    # grid purchase increases by 94/92
    y1_94 = opex_item_amount_at_year(elec_94, 1)
    y1_92 = opex_item_amount_at_year(elec_92, 1)
    assert y1_92 == pytest.approx(y1_94 * (0.94 / 0.92), rel=1e-9)
    assert y1_92 > y1_94
    # snapshot/runtime parity: the persisted human-percent value resolves to
    # exactly the runtime fraction the drivers carry.
    from app.ev_charging_economics import drivers_from_snapshot
    resolved = drivers_from_snapshot({"ev_charging_efficiency": "92"})
    assert resolved.charging_efficiency == pytest.approx(0.92)


# ── §10: electricity price + escalation are causal ───────────────────────────

def test_electricity_price_edit_changes_b08_exactly():
    _, elec_12 = _resolve()
    _, elec_15 = _resolve({"ev_electricity_price_eur_kwh": "0.15"})
    for year in (1, 2, 3, 10):
        a = opex_item_amount_at_year(elec_12, year)
        b = opex_item_amount_at_year(elec_15, year)
        assert b == pytest.approx(a * (0.15 / 0.12), rel=1e-9), year


def test_electricity_escalation_edit_changes_later_years_not_y1():
    _, elec_2 = _resolve()
    _, elec_5 = _resolve({"ev_electricity_price_escalation": "5"})
    # Y1 has no escalation applied yet
    assert opex_item_amount_at_year(elec_5, 1) == pytest.approx(
        opex_item_amount_at_year(elec_2, 1), rel=1e-12
    )
    # Y3+ follow the new escalation authority (5% vs 2%)
    assert opex_item_amount_at_year(elec_5, 3) > opex_item_amount_at_year(elec_2, 3)
    expected_y3 = (
        5.0 * 2000.0 / 0.94 * (0.12 * 1000.0 * (1.05 ** 2)) / 1000.0
    )
    assert opex_item_amount_at_year(elec_5, 3) == pytest.approx(expected_y3, rel=1e-9)


# ── §10: single derived B.08 authority ───────────────────────────────────────

def test_b08_single_derived_authority():
    pi, elec = _resolve()
    electricity = [i for i in pi.opex if i.name == "Electricity Procurement"]
    assert len(electricity) == 1
    # runtime adapter re-derives from drivers (never a stale scaled value):
    drivers = ev.drivers_from_snapshot({**BASE_SNAPSHOT, "ev_electricity_price_eur_kwh": "0.15"})
    adapted = ev.apply_ev_charging_runtime_adapter(pi, drivers)
    adapted_elec = next(i for i in adapted.opex if i.name == "Electricity Procurement")
    assert opex_item_amount_at_year(adapted_elec, 1) == pytest.approx(
        ev.driver_electricity_expense_keur(drivers, 5.0, 1), rel=1e-12
    )


# ── §8: adapter runs last (declared price cannot survive a driver edit) ─────

def test_adapter_overrides_generic_compatibility_fields():
    # a stale generic PPA tariff in the snapshot must NOT survive the adapter
    pi, _ = _resolve({"tariff_eur_mwh": "999", "ev_charging_price_eur_kwh": "0.45"})
    assert pi.revenue.ppa_base_tariff == pytest.approx(450.0)


# ── §6: availability stays informational (never an economic driver) ─────────

def test_availability_is_not_resolved_from_snapshot():
    # even if a key were present, drivers_from_snapshot never reads it
    d = ev.drivers_from_snapshot({"ev_availability": "0.5"})
    assert d == ev.GENERIC_EV_CHARGING_REFERENCE_DRIVERS


# ── reference defaults unchanged ─────────────────────────────────────────────

def test_reference_driver_defaults_unchanged():
    d = ev.GENERIC_EV_CHARGING_REFERENCE_DRIVERS
    assert (d.full_load_hours_y1, d.full_load_hours_y2, d.full_load_hours_stabilized) == (1200.0, 1600.0, 2000.0)
    assert d.charging_price_eur_kwh == 0.40 and d.charging_price_escalation == 0.02
    assert d.charging_efficiency == 0.94
    assert d.electricity_price_eur_kwh == 0.12 and d.electricity_price_escalation == 0.02
