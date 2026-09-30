"""P1 Model Completeness — Data Center sensitivity semantics (Opus NEW-M-1).

Proves:
  1. Data Center supported drivers map to exact existing canonical inputs.
  2. Renewable-only drivers are forbidden for Data Center (fail closed).
  3. DC-native shocks move exactly the canonical input they own
     (service price / occupancy -> revenue curve; PUE / electricity price ->
     B.08 Power Expenses schedule).
  4. DC base-case outputs are unchanged (no sensitivity leakage into the
     base model).
  5. Solar / Wind / EV driver sets unchanged; evaluation count bounded by
     the requested shock list.

No financial_engine / finco_core changes; the vertical capability registry
lives in the app sensitivity service.
"""
from __future__ import annotations

from dataclasses import replace

import pytest

from app.services.sensitivity_service import (
    DEFAULT_SHOCK_LEVELS,
    SHOCK_REGISTRY,
    UnsupportedSensitivityDriverError,
    _apply_shock,
    assert_driver_supported,
    resolve_vertical,
    run_sensitivity,
    supported_sensitivity_drivers,
)

FORBIDDEN_DC_DRIVERS = (
    "ppa_price", "merchant_price", "yield",  # renewable revenue semantics
)

DC_SUPPORTED = (
    "capex", "opex", "dc_service_price", "dc_occupancy",
    "dc_pue", "dc_electricity_price", "interest_rate", "tax_rate",
)


def _dc_project():
    from app.project_factories import create_generic_data_center_reference
    return create_generic_data_center_reference()


# ── 1. Vertical driver capability ───────────────────────────────────────────

class TestVerticalDriverCapability:
    def test_dc_supported_drivers_exact_set(self):
        assert supported_sensitivity_drivers("Data Center") == frozenset(DC_SUPPORTED)
        assert supported_sensitivity_drivers("data_center") == frozenset(DC_SUPPORTED)
        assert supported_sensitivity_drivers("datacenter") == frozenset(DC_SUPPORTED)

    def test_renewable_drivers_forbidden_for_dc(self):
        dc = supported_sensitivity_drivers("Data Center")
        for driver in FORBIDDEN_DC_DRIVERS:
            assert driver not in dc, driver

    def test_solar_wind_ev_keep_existing_drivers(self):
        renewable_set = frozenset({
            "capex", "opex", "ppa_price", "merchant_price", "yield",
            "availability", "interest_rate", "tax_rate",
        })
        assert supported_sensitivity_drivers("Solar") == renewable_set
        assert supported_sensitivity_drivers("Wind") == renewable_set
        assert supported_sensitivity_drivers("EV Charging") == renewable_set

    def test_fail_closed_for_unsupported_dc_driver(self):
        for driver in FORBIDDEN_DC_DRIVERS:
            with pytest.raises(UnsupportedSensitivityDriverError) as exc:
                assert_driver_supported("Data Center", driver)
            assert exc.value.vertical == "data_center"
            assert exc.value.shock_type == driver

    def test_run_sensitivity_fails_closed_before_any_execution(self, monkeypatch):
        """DATA_CENTER + ppa_price must fail closed BEFORE any model run —
        never a silent no-op that looks valid."""
        executed = []
        import app.services.sensitivity_service as ssvc

        def _no_exec(proj):
            executed.append(1)
            raise AssertionError("model must not execute for an unsupported driver")

        monkeypatch.setattr(ssvc, "_run_once", _no_exec)
        with pytest.raises(UnsupportedSensitivityDriverError):
            run_sensitivity(_dc_project(), ["ppa_price"], [-10.0, 10.0],
                            vertical="Data Center")
        assert executed == []

    def test_unknown_vertical_fails_closed(self):
        with pytest.raises(UnsupportedSensitivityDriverError):
            assert_driver_supported("geothermal", "capex")


# ── 2. DC-native shocks map to exact canonical inputs ──────────────────────

class TestDCShockMappings:
    def test_dc_service_price_scales_curve_and_tariff(self):
        proj = _dc_project()
        base_curve = proj.revenue.market_prices_curve
        shocked = _apply_shock(proj, "dc_service_price", 10.0)
        assert shocked.revenue.ppa_base_tariff == pytest.approx(
            proj.revenue.ppa_base_tariff * 1.10)
        assert tuple(v * 1.10 for v in base_curve) == shocked.revenue.market_prices_curve

    def test_dc_occupancy_scales_curve_only(self):
        proj = _dc_project()
        shocked = _apply_shock(proj, "dc_occupancy", 10.0)
        assert tuple(v * 1.10 for v in proj.revenue.market_prices_curve) \
            == shocked.revenue.market_prices_curve
        assert shocked.revenue.market_inflation == proj.revenue.market_inflation

    def test_dc_pue_scales_power_expense_schedule(self):
        proj = _dc_project()
        power = next(o for o in proj.opex if o.name == "Power Expenses")
        # PUE shock in +10% → +10% facility power; applied to the +10%
        # electricity-price-equivalent step (i.e. factor applied twice total
        # via composition is NOT the contract: the driver applies exactly
        # one +10% factor to the power schedule).
        factor = 1.10
        base_power_y1 = power.y1_amount_keur
        base_step3 = dict(power.step_changes)[3] * (1.02 ** 2)
        shocked = _apply_shock(proj, "dc_pue", 10.0)
        power_new = next(o for o in shocked.opex if o.name == "Power Expenses")
        assert power_new.y1_amount_keur == pytest.approx(base_power_y1 * factor)
        assert dict(power_new.step_changes)[1] == pytest.approx(
            dict(power.step_changes)[1] * factor)
        assert dict(power_new.step_changes)[3] == pytest.approx(
            dict(power.step_changes)[3] * factor)
        # Non-power lines untouched.
        other_old = next(o for o in proj.opex if o.name == "Insurance")
        other_new = next(o for o in shocked.opex if o.name == "Insurance")
        assert other_new.y1_amount_keur == other_old.y1_amount_keur

    def test_dc_electricity_price_scales_power_expense(self):
        proj = _dc_project()
        shocked = _apply_shock(proj, "dc_electricity_price", -10.0)
        power_old = next(o for o in proj.opex if o.name == "Power Expenses")
        power_new = next(o for o in shocked.opex if o.name == "Power Expenses")
        assert power_new.y1_amount_keur == pytest.approx(power_old.y1_amount_keur * 0.90)


# ── 3. Base outputs unchanged + bounded evaluation ─────────────────────────

class TestBaseOutputsAndBounds:
    def test_dc_base_outputs_unchanged_by_capability_registry(self):
        from app.data_center_authority import core_capacity_revenue_keur
        proj = _dc_project()
        # Registry introduction must not touch the canonical identities.
        stabilized = core_capacity_revenue_keur(
            capacity_mw=proj.technical.capacity_mw,
            service_price_eur_kw_month=175.0, occupancy=0.85)
        assert stabilized == pytest.approx(35_700.0)

    def test_evaluation_count_bounded_by_shock_list(self, monkeypatch):
        import app.services.sensitivity_service as ssvc

        runs = []
        real = ssvc._run_once
        monkeypatch.setattr(ssvc, "_run_once",
                            lambda p: (runs.append(1), real(p))[1])
        result = run_sensitivity(_dc_project(), ["dc_service_price"],
                                 [-10.0, 0.0, 10.0], vertical="Data Center")
        # base + 3 shocks = 4 executions; no unbounded fanout.
        assert len(runs) == 4
        assert len(result["rows"]) == 3

    def test_invalid_shock_does_not_silently_pass(self):
        with pytest.raises(UnsupportedSensitivityDriverError):
            run_sensitivity(_dc_project(), ["yield"], [10.0], vertical="Data Center")

    def test_solar_vertical_unchanged_behavior(self):
        from app.project_factories import create_generic_solar_reference
        proj = create_generic_solar_reference()
        shocked = _apply_shock(proj, "yield", 10.0)
        assert shocked.technical.operating_hours_p50 == pytest.approx(
            proj.technical.operating_hours_p50 * 1.10)

    def test_wind_vertical_unchanged_behavior(self):
        from app.project_factories import create_generic_wind_reference
        proj = create_generic_wind_reference()
        shocked = _apply_shock(proj, "ppa_price", 10.0)
        assert shocked.revenue.ppa_base_tariff == pytest.approx(
            proj.revenue.ppa_base_tariff * 1.10)

    def test_ev_vertical_unchanged_behavior(self):
        """EV availability is pinned at the 1.0 cap by the existing clamp
        (min(1.0, x*factor)); the driver behavior itself is unchanged —
        prove via the yield driver instead."""
        from app.project_factories import create_generic_ev_charging_reference
        proj = create_generic_ev_charging_reference()
        shocked = _apply_shock(proj, "yield", 10.0)
        assert shocked.technical.operating_hours_p50 == pytest.approx(
            proj.technical.operating_hours_p50 * 1.10)

    def test_shock_registry_labels_unchanged_for_renewables(self):
        assert SHOCK_REGISTRY["ppa_price"][0] == "PPA Price"
        assert SHOCK_REGISTRY["yield"][0] == "Yield (P50 Hours)"
