"""FIN-V2-D01 + D02 — legacy sensitivity, lender case and EV Charging driver truth (real canonical engine runs).

Proves, with the production runner and no engine edit:
* a +/-100 bps shock moves the Senior rate the engine consumes (5.5 % -> 6.5 % / 4.5 %), moves the financing-dependent KPIs,
  and leaves the unlevered Project IRR unchanged;
* an unsupported / unapplied shock fails closed with a typed code and never a valid-looking flat row;
* every EV Charging driver still offered reaches its authoritative economics, and the inert price drivers are refused.
"""
from __future__ import annotations

import dataclasses
from dataclasses import replace
from functools import lru_cache

import pytest

from app import project_factories as factories
from app.services import rate_shock as rs
from app.services import sensitivity_service as svc
from app.services.lender_case_service import apply_lender_adjustments, run_lender_case


def _ref(kind):
    return getattr(factories, f"create_generic_{kind}_reference")()


def _calibrated(pi):
    cfg = pi.financing.senior_debt_interest_config
    vector = (0.05, 0.06) * (len(cfg.rate_schedule.explicit_all_in_rates) // 2 + 1)
    schedule = replace(cfg.rate_schedule, explicit_all_in_rates=vector)
    return replace(pi, financing=replace(pi.financing, senior_debt_interest_config=replace(cfg, rate_schedule=schedule)))


@lru_cache(maxsize=None)
def _base(kind):
    return svc._run_once(_ref(kind))


@pytest.fixture()
def run_counter(monkeypatch):
    calls = []
    real = svc._run_once

    def counting(proj):
        calls.append(proj)
        return real(proj)

    monkeypatch.setattr(svc, "_run_once", counting)
    return calls


def _dc_drivers():
    from app.data_center_authority import GENERIC_DATA_CENTER_REFERENCE_DRIVERS
    return GENERIC_DATA_CENTER_REFERENCE_DRIVERS


# ───────────────────────────── D01-A / D01-B : legacy sensitivity ─────────────────────────────
@pytest.mark.parametrize("kind,base_pct", [("solar", 5.5), ("wind", 5.5), ("ev_charging", 6.0)])
def test_legacy_interest_rows_apply_to_the_effective_rate_and_move_only_financing_kpis(kind, base_pct):
    result = svc.run_sensitivity(_ref(kind), ["interest_rate"], [-100.0, 100.0], kind)
    base = result["base_kpis"]
    low, high = result["rows"]
    for row, bps in ((low, -100.0), (high, 100.0)):
        assert row["error"] is None and row["error_code"] is None
        assert row["evidence"]["before_pct"] == pytest.approx(base_pct)
        assert row["evidence"]["after_pct"] == pytest.approx(base_pct + bps / 100.0)
        # unlevered Project IRR and operating totals are invariant; the financing-dependent KPIs are not all invariant
        for key in rs.UNLEVERED_KPIS:
            assert row["kpis"][key] == base[key], key
        moved = [k for k in rs.FINANCING_DEPENDENT_KPIS if row["kpis"][k] is not None and base[k] is not None
                 and row["kpis"][k] != base[k]]
        assert "total_senior_ds_keur" in moved and "equity_irr" in moved, moved
    assert low["kpis"]["equity_irr"] > base["equity_irr"] > high["kpis"]["equity_irr"]


def test_legacy_data_center_minus_100_bps_applies_and_improves_equity_return():
    row = svc.run_sensitivity(_ref("data_center"), ["interest_rate"], [-100.0], "data_center", _dc_drivers())["rows"][0]
    base = _base("data_center")
    assert row["error"] is None and row["evidence"]["before_pct"] == pytest.approx(6.0)
    assert row["evidence"]["after_pct"] == pytest.approx(5.0)
    assert row["kpis"]["project_irr"] == base["project_irr"] and row["kpis"]["equity_irr"] > base["equity_irr"]


def test_legacy_data_center_plus_100_bps_is_a_typed_engine_failure_never_a_flat_row():
    """The synthetic DC reference cannot repay its SHL at 7 %: a typed fail-closed row, not an unchanged KPI row."""
    row = svc.run_sensitivity(_ref("data_center"), ["interest_rate"], [100.0], "data_center", _dc_drivers())["rows"][0]
    assert row["error"] and all(v is None for v in row["kpis"].values())


def test_legacy_calibrated_schedule_is_refused_with_one_engine_run(run_counter):
    pi = _calibrated(_ref("solar"))
    result = svc.run_sensitivity(pi, ["interest_rate"], [-100.0, 100.0], "solar")
    assert len(run_counter) == 1                                          # only the base run: refused rows never execute
    for row in result["rows"]:
        assert row["error_code"] == "RATE_SHOCK_CALIBRATED_SCHEDULE" and row["error"].startswith("RATE_SHOCK_CALIBRATED_SCHEDULE")
        assert all(v is None for v in row["kpis"].values()) and all(v is None for v in row["deltas"].values())
        assert row["evidence"] is None


def test_legacy_out_of_range_rate_is_refused():
    row = svc.run_sensitivity(_ref("solar"), ["interest_rate"], [2000.0], "solar")["rows"][0]
    assert row["error_code"] == "RATE_SHOCK_OUT_OF_RANGE" and all(v is None for v in row["kpis"].values())


def test_unapplied_shock_is_never_reported_as_a_flat_valid_row(monkeypatch, run_counter):
    monkeypatch.setattr(svc, "_apply_shock", lambda proj, *a, **k: proj)   # a defective/inert shock implementation
    result = svc.run_sensitivity(_ref("solar"), ["capex"], [10.0, 0.0], "solar")
    inert, identity = result["rows"]
    assert inert["error_code"] == "SHOCK_NOT_APPLIED" and all(v is None for v in inert["kpis"].values())
    assert identity["error"] is None                                       # an explicit zero level is a legitimate identity
    assert len(run_counter) == 2                                           # base + the identity row


def test_zero_level_interest_row_is_the_unshocked_base():
    row = svc.run_sensitivity(_ref("solar"), ["interest_rate"], [0.0], "solar")["rows"][0]
    assert row["error"] is None and row["evidence"] is None and row["kpis"] == _base("solar")


def test_base_rate_alone_is_provably_inert_which_is_why_it_is_no_longer_the_lever():
    """Regression for the defect: moving ``financing.base_rate`` leaves every KPI bit-identical."""
    pi = _ref("solar")
    moved = replace(pi, financing=replace(pi.financing, base_rate=pi.financing.base_rate + 0.01))
    assert svc._run_once(moved) == _base("solar")


# ───────────────────────────── D01-A / D01-B : lender case ─────────────────────────────
@pytest.mark.parametrize("kind,base_pct", [("solar", 5.5), ("wind", 5.5)])
def test_lender_interest_stress_moves_the_effective_vector_and_the_financing_kpis(kind, base_pct):
    pi = _ref(kind)
    stressed = run_lender_case(pi, {"interest_stress": 100.0})
    reference = run_lender_case(pi, {})
    ev = stressed["rate_stress_evidence"]
    assert ev["before_pct"] == pytest.approx(base_pct) and ev["after_pct"] == pytest.approx(base_pct + 1.0)
    assert reference["rate_stress_evidence"] is None
    shocked_vector = stressed["project_inputs"].financing.senior_debt_interest_config.rate_schedule.explicit_all_in_rates
    assert all(r == pytest.approx((base_pct + 1.0) / 100.0, abs=1e-12) for r in shocked_vector)
    assert stressed["kpis"]["project_irr"] == reference["kpis"]["project_irr"]            # unlevered
    assert stressed["kpis"]["equity_irr"] != reference["kpis"]["equity_irr"]              # financing-dependent
    assert stressed["adjustment_summary"][0]["display"] == "+100 bps"


def test_lender_minus_100_bps_lowers_the_rate():
    out = run_lender_case(_ref("solar"), {"interest_stress": -100.0})
    assert out["rate_stress_evidence"]["after_pct"] == pytest.approx(4.5)


def test_lender_calibrated_schedule_is_refused_before_any_run(monkeypatch):
    monkeypatch.setattr("app.services.production_waterfall_seam.execute_production_waterfall",
                        lambda *a, **k: pytest.fail("engine must not run for a refused stress"))
    with pytest.raises(rs.RateShockRefusal) as exc:
        run_lender_case(_calibrated(_ref("solar")), {"interest_stress": 100.0})
    assert exc.value.code == "RATE_SHOCK_CALIBRATED_SCHEDULE"


def test_lender_unapplied_stress_is_refused_not_run_as_stressed(monkeypatch):
    monkeypatch.setattr(svc, "_apply_shock", lambda proj, *a, **k: proj)
    with pytest.raises(svc.ShockNotApplied):
        apply_lender_adjustments(_ref("solar"), {"capex_contingency": 5.0})
    assert apply_lender_adjustments(_ref("solar"), {}) == _ref("solar")


@pytest.mark.parametrize("adjustment", ["ppa_haircut", "merchant_haircut"])
def test_lender_price_haircut_on_an_ev_project_is_refused_as_inactive(adjustment):
    with pytest.raises(svc.InactiveShockDriver) as exc:
        apply_lender_adjustments(_ref("ev_charging"), {adjustment: 10.0})
    assert exc.value.code == "SHOCK_DRIVER_INACTIVE"


def test_lender_price_haircuts_still_reach_renewable_revenue():
    pi = _ref("solar")
    for adjustment, field in (("ppa_haircut", "ppa_base_tariff"), ("merchant_haircut", "market_prices_curve")):
        out = apply_lender_adjustments(pi, {adjustment: 10.0})
        assert getattr(out.revenue, field) != getattr(pi.revenue, field)


# ───────────────────────────── D02 : EV Charging ─────────────────────────────
def test_ev_offers_only_drivers_that_reach_its_economics():
    assert svc.supported_sensitivity_drivers("ev_charging") == frozenset(
        {"capex", "opex", "yield", "interest_rate", "tax_rate"})
    for removed in ("ppa_price", "merchant_price", "availability"):
        assert removed not in svc.supported_sensitivity_drivers("ev_charging")
    # renewable and data-center sets are unchanged
    assert svc.supported_sensitivity_drivers("solar") == svc.supported_sensitivity_drivers("wind") == frozenset(
        {"capex", "opex", "ppa_price", "merchant_price", "yield", "availability", "interest_rate", "tax_rate"})
    assert "ppa_price" not in svc.supported_sensitivity_drivers("data_center")


@pytest.mark.parametrize("driver", ["ppa_price", "merchant_price", "availability"])
def test_ev_inert_drivers_are_refused_before_any_model_execution(driver, run_counter):
    with pytest.raises(svc.UnsupportedSensitivityDriverError):
        svc.run_sensitivity(_ref("ev_charging"), [driver], [10.0], "ev_charging")
    assert run_counter == []


@pytest.mark.parametrize("driver", ["ppa_price", "merchant_price"])
def test_ev_price_shock_without_a_vertical_gate_is_structurally_refused(driver):
    """Callers that cannot pass a vertical (lender case) still never get an inert EV price shock."""
    with pytest.raises(svc.InactiveShockDriver):
        svc._apply_shock(_ref("ev_charging"), driver, 10.0)


def test_ev_ppa_price_was_inert_before_the_refusal():
    """Documents the defect: the shock changed an input the engine never reads (revenue delta exactly 0)."""
    pi = _ref("ev_charging")
    rev = pi.revenue
    assert rev.first_merchant_operating_period_index == 0 and rev.market_prices_by_calendar_year_eur_mwh
    inert = replace(pi, revenue=replace(rev, ppa_base_tariff=rev.ppa_base_tariff * 1.1))
    assert inert != pi and svc._run_once(inert)["total_revenue_keur"] == _base("ev_charging")["total_revenue_keur"]
    merchant = replace(pi, revenue=replace(rev, market_prices_curve=tuple(v * 1.1 for v in rev.market_prices_curve)))
    assert merchant != pi and svc._run_once(merchant)["total_revenue_keur"] == _base("ev_charging")["total_revenue_keur"]


def test_every_offered_ev_driver_changes_its_input_and_its_output():
    pi = _ref("ev_charging")
    base = _base("ev_charging")
    result = svc.run_sensitivity(pi, ["capex", "opex", "yield", "tax_rate", "interest_rate"], [10.0], "ev_charging")
    rows = {r["shock_type"]: r for r in result["rows"]}
    assert set(rows) == {"capex", "opex", "yield", "tax_rate", "interest_rate"}
    for driver, row in rows.items():
        assert row["error"] is None, (driver, row["error"])
        assert svc._apply_shock(pi, driver, 10.0, None, "ev_charging") != pi, driver      # the authoritative input moved
    delta = lambda r, k: r["kpis"][k] - base[k]                                            # noqa: E731
    assert delta(rows["capex"], "project_irr") < 0 and delta(rows["capex"], "total_revenue_keur") == 0
    assert delta(rows["opex"], "total_ebitda_keur") < 0 and delta(rows["opex"], "total_revenue_keur") == 0
    assert delta(rows["yield"], "total_revenue_keur") > 0 and delta(rows["yield"], "total_ebitda_keur") > 0
    assert delta(rows["tax_rate"], "total_tax_keur") != 0
    assert delta(rows["interest_rate"], "total_senior_ds_keur") != 0 and delta(rows["interest_rate"], "project_irr") == 0


@pytest.mark.parametrize("level", [-10.0, 10.0])
def test_ev_yield_shock_equals_rerunning_the_ev_authority_with_scaled_full_load_hours(level):
    """Purchased energy follows delivered energy: the shock must equal the EV adapter on EFLH drivers scaled together."""
    from app.ev_charging_economics import GENERIC_EV_CHARGING_REFERENCE_DRIVERS as D, apply_ev_charging_runtime_adapter

    pi = _ref("ev_charging")
    factor = 1.0 + level / 100.0
    scaled = dataclasses.replace(
        D, full_load_hours_y1=D.full_load_hours_y1 * factor, full_load_hours_y2=D.full_load_hours_y2 * factor,
        full_load_hours_stabilized=D.full_load_hours_stabilized * factor)
    authority = svc._run_once(apply_ev_charging_runtime_adapter(pi, scaled))
    shocked = svc._run_once(svc._apply_shock(pi, "yield", level, None, "ev_charging"))
    for key in ("total_revenue_keur", "total_ebitda_keur", "project_irr", "equity_irr", "total_tax_keur", "total_senior_ds_keur"):
        assert shocked[key] == pytest.approx(authority[key], rel=1e-9, abs=1e-9), key


def test_ev_yield_shock_scales_electricity_cost_with_energy_and_nothing_else():
    pi = _ref("ev_charging")
    shocked = svc._apply_shock(pi, "yield", 10.0, None, "ev_charging")
    before = {o.name: o for o in pi.opex}
    after = {o.name: o for o in shocked.opex}
    assert set(before) == set(after)
    e0, e1 = before["Electricity Procurement"], after["Electricity Procurement"]
    assert e1.y1_amount_keur == pytest.approx(e0.y1_amount_keur * 1.1)
    assert [y for y, _ in e1.step_changes] == [y for y, _ in e0.step_changes]
    assert [a for _, a in e1.step_changes] == pytest.approx([a * 1.1 for _, a in e0.step_changes])
    assert shocked.technical.operating_hours_p50 == pytest.approx(pi.technical.operating_hours_p50 * 1.1)
    assert shocked.technical.operating_hours_p90_10y == pytest.approx(pi.technical.operating_hours_p90_10y * 1.1)
    for name in before:
        if name != "Electricity Procurement":
            assert before[name] == after[name]
    assert shocked.revenue == pi.revenue


def test_ev_yield_without_the_electricity_authority_line_fails_closed():
    pi = _ref("ev_charging")
    stripped = replace(pi, opex=tuple(o for o in pi.opex if o.name != "Electricity Procurement"))
    with pytest.raises(svc.InactiveShockDriver):
        svc._apply_shock(stripped, "yield", 10.0, None, "ev_charging")


def test_renewable_yield_and_price_drivers_are_unchanged_by_the_ev_correction():
    """Solar/Wind semantics are exactly the pre-existing ones (no electricity scaling, active price drivers)."""
    pi = _ref("solar")
    plain = svc._apply_shock(pi, "yield", 10.0)
    assert plain == svc._apply_shock(pi, "yield", 10.0, None, "solar")
    assert plain.opex == pi.opex and plain.technical.operating_hours_p90_10y == pi.technical.operating_hours_p90_10y
    for kind in ("solar", "wind"):
        p = _ref(kind)
        assert svc._apply_shock(p, "ppa_price", 10.0).revenue.ppa_base_tariff == pytest.approx(p.revenue.ppa_base_tariff * 1.1)
        assert svc._apply_shock(p, "merchant_price", 10.0).revenue.market_prices_curve[0] == pytest.approx(
            p.revenue.market_prices_curve[0] * 1.1)


def test_merchant_shock_with_no_curve_is_refused_not_returned_unchanged():
    pi = _ref("solar")
    empty = replace(pi, revenue=replace(pi.revenue, market_prices_curve=()))
    with pytest.raises(svc.InactiveShockDriver):
        svc._apply_shock(empty, "merchant_price", 10.0)
    assert svc._apply_shock(empty, "merchant_price", 0.0) is empty        # zero is the identity
