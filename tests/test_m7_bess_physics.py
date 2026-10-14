"""Independent rational-number oracle, boundaries and lifecycle conservation."""
import copy
import json
from dataclasses import FrozenInstanceError
from decimal import Decimal, getcontext
from fractions import Fraction

import pytest

from domain.bess.contracts import parse_configuration, BessInputError
from domain.bess.dispatch import evaluate
from domain.bess.synthetic import example


def execute(raw):
    return evaluate(parse_configuration(json.dumps(raw)))


def test_independent_hourly_fraction_oracle(record_property):
    raw = example()
    result = execute(raw)
    energy = Fraction(0)
    worst = 0.
    purchase = sale = aux = import_fee = export_fee = Fraction(0)
    for row in result.hours:
        profile = raw["dispatch"][row.start.hour]
        charge, discharge = Fraction(str(profile["charge_mw"])), Fraction(str(profile["discharge_mw"]))
        auxiliary = Fraction(1, 100)
        expected = energy + charge * Fraction(9, 10) - discharge / Fraction(9, 10)
        assert Fraction(row.closing_energy_mwh) == expected
        assert Fraction(row.grid_import_mwh) == charge + auxiliary
        assert Fraction(row.grid_export_mwh) == discharge
        assert Fraction(row.charging_loss_mwh) == charge / 10
        assert Fraction(row.discharging_loss_mwh) == discharge / 9
        energy = expected
        purchase += charge * 40 / 1000
        sale += discharge * 100 / 1000
        aux += auxiliary * 40 / 1000
        import_fee += (charge + auxiliary) * 2 / 1000
        export_fee += discharge / 1000
        worst = max(worst, abs(float(row.energy_conservation_residual_mwh)))
    assert energy == 0
    assert Fraction(result.gross_sale_revenue_keur) == sale
    assert Fraction(result.charging_purchase_cost_keur) == purchase
    assert Fraction(result.auxiliary_purchase_cost_keur) == aux
    assert Fraction(result.grid_import_charge_keur) == import_fee
    assert Fraction(result.grid_export_charge_keur) == export_fee
    assert Fraction(result.net_merchant_contribution_keur) == sale - purchase - aux - import_fee - export_fee
    assert result.total_dc_throughput_mwh == Decimal("3.6")
    assert result.total_equivalent_full_cycles == Decimal(".9")
    record_property("maximum_actual_energy_residual_mwh", worst)


@pytest.mark.parametrize("fault", ["negative", "nan", "boolean", "missing", "unknown", "technology", "unit", "rte", "duration",
    "simultaneous", "power", "grid", "soc-high", "soc-low", "unavailable", "terminal", "missing-hour", "duplicate-hour",
    "dst-offset", "quarter-hour", "too-many-hours", "negative-price", "free-augmentation", "unsourced", "unsupported-tax",
    "unordered-event", "initial-soc", "expired-life", "calendar-exhaustion", "cycle-exhaustion"])
def test_invalid_inputs_and_impossible_schedules_fail_without_clipping(fault):
    raw = example()
    battery, rows = raw["battery"], raw["dispatch"]
    if fault == "negative": battery["usable_energy_mwh"] = -1
    elif fault == "nan": battery["calendar_loss_per_year"] = float("nan")
    elif fault == "boolean": battery["charge_power_mw"] = True
    elif fault == "missing": del battery["duration_hours"]
    elif fault == "unknown": raw["optimal_dispatch"] = True
    elif fault == "technology": raw["technology"] = "SOLAR_BESS"
    elif fault == "unit": raw["price_unit"] = "EUR_PER_KWH"
    elif fault == "rte": battery["round_trip_efficiency"] = .9
    elif fault == "duration": battery["duration_hours"] = 2000
    elif fault == "simultaneous": rows[2]["discharge_mw"] = .1
    elif fault == "power": rows[2]["charge_mw"] = 1.01
    elif fault == "grid": battery["grid_import_limit_mw"] = 1
    elif fault == "soc-high": rows[3]["charge_mw"] = 1
    elif fault == "soc-low": rows[0]["discharge_mw"] = .1
    elif fault == "unavailable": rows[2]["available"] = False
    elif fault == "terminal": battery["terminal_energy_mwh"] = .1
    elif fault == "missing-hour": rows.pop()
    elif fault == "duplicate-hour": rows[3]["utc_hour"] = 2
    elif fault == "dst-offset": raw["start"] = "2028-01-01T00:00:00+01:00"
    elif fault == "quarter-hour": raw["start"] = "2028-01-01T00:15:00Z"
    elif fault == "too-many-hours": raw["end"] = "2099-01-01T00:00:00Z"
    elif fault == "negative-price": rows[0]["buy_price_eur_mwh"] = -1
    elif fault in ("free-augmentation", "unsupported-tax", "unordered-event"):
        raw["events"] = [event()]
        if fault == "free-augmentation": raw["events"][0]["cost_keur"] = 0
        elif fault == "unsupported-tax": raw["events"][0]["tax_book_policy"] = "EXPENSE_ALL"
        else: raw["events"].append(event())
    elif fault == "unsourced": raw["source_ref"] = ""
    elif fault == "initial-soc": battery["initial_energy_mwh"] = 3
    elif fault == "expired-life": raw["end"] = "2034-01-01T00:00:00Z"
    elif fault == "calendar-exhaustion": battery["calendar_loss_per_year"] = 1; raw["end"] = "2029-01-01T00:00:00Z"
    elif fault == "cycle-exhaustion": battery["cycle_loss_per_efc"] = 1
    with pytest.raises(BessInputError):
        execute(raw)


def event(kind="AUGMENT", at="2028-01-02T00:00:00Z"):
    return dict(at=at, kind=kind, installed_energy_mwh=2.5, usable_energy_mwh=2, cost_keur=100,
                useful_life_years=5, source_ref="finco-synthetic-paid-event", tax_book_policy="UNRESOLVED")


@pytest.mark.parametrize("kind", ["AUGMENT", "REPLACE"])
def test_paid_events_change_capacity_without_free_energy_or_netting_into_revenue(kind):
    raw = example()
    raw["events"] = [event(kind)]
    result = execute(raw)
    point = result.hours[24]
    assert point.opening_energy_mwh == 0
    assert point.lifecycle_capex_keur == 100
    assert point.available_energy_opening_mwh > result.hours[23].available_energy_closing_mwh
    assert point.installed_energy_mwh == (5 if kind == "AUGMENT" else Decimal("2.5"))
    baseline = execute(example())
    assert result.gross_sale_revenue_keur == baseline.gross_sale_revenue_keur
    assert result.net_merchant_contribution_keur == baseline.net_merchant_contribution_keur
    assert result.lifecycle_capex_keur == 100  # Never subtracted from revenue or substituted for depreciation.


def test_replacement_cannot_write_off_stored_inventory():
    raw = example()
    raw["events"] = [event("REPLACE", "2028-01-01T03:00:00Z")]
    with pytest.raises(BessInputError, match="REPLACEMENT_INVENTORY"):
        execute(raw)


def test_degradation_is_monotonic_and_caller_decimal_precision_is_irrelevant():
    config = parse_configuration(json.dumps(example()))
    first = evaluate(config)
    old = getcontext().prec
    try:
        getcontext().prec = 10
        assert evaluate(config) == first
    finally:
        getcontext().prec = old
    assert all(a.available_energy_closing_mwh <= a.available_energy_opening_mwh for a in first.hours)
    with pytest.raises(FrozenInstanceError):
        config.battery.soc_max = Decimal(1)


def test_zero_dispatch_has_zero_revenue_and_no_invented_cycle():
    raw = example()
    for point in raw["dispatch"]:
        point.update(charge_mw=0, discharge_mw=0, auxiliary_grid_mw=0)
    result = execute(raw)
    assert result.gross_sale_revenue_keur == result.charging_purchase_cost_keur == result.net_merchant_contribution_keur == 0
    assert result.total_equivalent_full_cycles == result.total_dc_throughput_mwh == 0


def test_explicit_timeline_and_daily_plan_are_equivalent_and_missing_hour_is_rejected():
    from datetime import timedelta
    raw = example()
    baseline = execute(raw)
    raw["dispatch_mode"] = "EXPLICIT_HOURLY"
    raw["dispatch"] = [dict({k: v for k, v in example()["dispatch"][i % 24].items() if k != "utc_hour"},
        timestamp=row.start.strftime("%Y-%m-%dT%H:%M:%SZ")) for i, row in enumerate(baseline.hours)]
    assert execute(raw).hours == baseline.hours
    raw["dispatch"][1]["timestamp"] = (baseline.hours[1].start + timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
    with pytest.raises(BessInputError, match="CONTINUITY"):
        execute(raw)


def test_declared_outage_suspends_fixed_plan_but_never_repairs_insufficient_soc():
    raw = example()
    raw["outages"] = [dict(start=raw["start"], end="2028-01-02T00:00:00Z", source_ref="finco-planned-maintenance")]
    result = execute(raw)
    assert all(row.ac_charge_mwh == row.ac_discharge_mwh == 0 for row in result.hours[:24])
    assert result.hours[2].outage_suspension and result.hours[2].requested_charge_mw == 1
    assert result.hours[2].auxiliary_grid_mwh == Decimal(".01")
    raw["outages"][0]["end"] = "2028-01-01T04:00:00Z"
    with pytest.raises(BessInputError, match="CLOSING_SOC"):
        execute(raw)


def test_leap_year_is_not_a_365_day_or_half_year_multiplier():
    result = execute(example("2028-01-01T00:00:00Z", "2029-01-01T00:00:00Z"))
    assert len(result.hours) == 366 * 24
    assert result.delivered_export_mwh == Decimal(".81") * 366
    assert result.purchased_import_mwh == Decimal("1.24") * 366
    assert result.maximum_energy_residual_mwh == 0


def test_input_fingerprint_changes_without_mutating_existing_result():
    raw = example()
    before = execute(raw)
    snapshot = copy.deepcopy(before)
    raw["dispatch"][20]["sell_price_eur_mwh"] = 120
    after = execute(raw)
    assert before == snapshot
    assert before.input_fingerprint != after.input_fingerprint
    assert after.hours[20].ac_discharge_mwh == before.hours[20].ac_discharge_mwh
    assert after.gross_sale_revenue_keur > before.gross_sale_revenue_keur
