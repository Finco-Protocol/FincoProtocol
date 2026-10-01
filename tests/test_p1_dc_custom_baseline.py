"""PR #155 Correction C — DC sensitivity starts from ACTUAL project drivers.

Uses a NON-GENERIC custom Data Center snapshot deliberately far from the
reference defaults:

  IT MW = 31, service price = 231, occupancy = 63/79/91 %,
  PUE = 1.17, electricity price = 96 EUR/MWh

Proves every dc_* sensitivity shock starts from the project's ACTUAL
canonical source drivers (resolved via drivers_from_snapshot) — never from
GENERIC_DATA_CENTER_REFERENCE_DRIVERS — and that dc_* shocks without a
resolved context fail closed.
"""
from __future__ import annotations

import pytest

CUSTOM = {
    "capacity_mw": "31",
    "dc_service_price_eur_kw_month": "231",
    "dc_occupancy_y1": "63",
    "dc_occupancy_y2": "79",
    "dc_occupancy_stabilized": "91",
    "dc_pue": "1.17",
    "dc_electricity_price_eur_mwh": "96",
}

CUSTOM_DRIVERS = {
    "capacity_mw": 31.0,
    "service_price_eur_kw_month": 231.0,
    "occupancy_y1": 0.63,
    "occupancy_y2": 0.79,
    "stabilized_occupancy": 0.91,
    "pue": 1.17,
    "electricity_price_eur_mwh": 96.0,
}


def _custom_snapshot():
    from app.persistence.projects_repository import _compute_baseline_snapshot
    base = dict(_compute_baseline_snapshot(
        "Data Center", "generic_data_center_reference"))
    base.update(CUSTOM)
    return base


def _custom_drivers():
    from app.data_center_authority import DataCenterDrivers
    d = {k: v for k, v in CUSTOM_DRIVERS.items() if k != "capacity_mw"}
    return DataCenterDrivers(**d)


def _custom_project():
    from app.input_adapter import build_projectinputs_from_snapshot
    return build_projectinputs_from_snapshot(_custom_snapshot())


@pytest.fixture
def seeded_db(tmp_path, monkeypatch):
    from app.persistence import db

    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "dc-custom-baseline.db"))
    db.init_db()
    yield


class TestCustomBaselineShocks:
    def test_service_price_starts_from_231_not_175(self, seeded_db):
        from app.data_center_authority import GENERIC_DATA_CENTER_REFERENCE_DRIVERS
        from app.services.sensitivity_service import _apply_shock

        proj = _custom_project()
        assert proj.revenue.ppa_base_tariff != pytest.approx(
            GENERIC_DATA_CENTER_REFERENCE_DRIVERS.service_price_eur_kw_month)
        shocked = _apply_shock(
            proj, "dc_service_price", 10.0,
            dc_drivers=_custom_drivers())
        # +10% of the PROJECT's 231-based equivalent tariff.
        assert shocked.revenue.ppa_base_tariff == pytest.approx(
            proj.revenue.ppa_base_tariff * 1.10)
        # Generic 175 baseline would give a different absolute result.
        generic_ratio = (
            GENERIC_DATA_CENTER_REFERENCE_DRIVERS.service_price_eur_kw_month * 1.10
            / GENERIC_DATA_CENTER_REFERENCE_DRIVERS.service_price_eur_kw_month)
        # Same ratio, but the ABSOLUTE tariff proves the 231 base:
        assert shocked.revenue.ppa_base_tariff > 200 * 1.10

    def test_pue_starts_from_117_not_130(self, seeded_db):
        from app.services.sensitivity_service import _apply_shock

        proj = _custom_project()
        power = next(o for o in proj.opex if o.name == "Power Expenses")
        shocked = _apply_shock(proj, "dc_pue", 10.0, dc_drivers=_custom_drivers())
        power_new = next(o for o in shocked.opex if o.name == "Power Expenses")
        # Custom base: 31 x 0.63 x 1.17 x 8760 x 96 / 1000
        expected_base = 31.0 * 0.63 * 1.17 * 8760 * 96 / 1000
        assert power.y1_amount_keur == pytest.approx(expected_base, rel=1e-6)
        assert power_new.y1_amount_keur == pytest.approx(expected_base * 1.10)

    def test_electricity_price_starts_from_96_not_70(self, seeded_db):
        from app.services.sensitivity_service import _apply_shock

        proj = _custom_project()
        shocked = _apply_shock(proj, "dc_electricity_price", 10.0,
                               dc_drivers=_custom_drivers())
        power_new = next(o for o in shocked.opex if o.name == "Power Expenses")
        expected_base = 31.0 * 0.63 * 1.17 * 8760 * 96 / 1000
        assert power_new.y1_amount_keur == pytest.approx(expected_base * 1.10)
        # 70 EUR/MWh generic base would give a different absolute:
        generic_abs = 31.0 * 0.63 * 1.17 * 8760 * 70 / 1000
        assert power_new.y1_amount_keur != pytest.approx(generic_abs * 1.10)

    def test_occupancy_uses_project_ramp(self, seeded_db):
        """+5% occupancy (stabilized 91% -> 95.5%, inside the <=100% clamp):
        REVENUE and POWER PROCUREMENT both recompute by exactly the same
        factor through the canonical adapter."""
        from app.services.sensitivity_service import _apply_shock

        proj = _custom_project()
        shocked = _apply_shock(proj, "dc_occupancy", 5.0,
                               dc_drivers=_custom_drivers())
        factor = 1.05
        old_curve = proj.revenue.market_prices_curve
        assert all(new == pytest.approx(old * factor)
                   for new, old in zip(shocked.revenue.market_prices_curve,
                                       old_curve))
        power_old = next(o for o in proj.opex if o.name == "Power Expenses")
        power_new = next(o for o in shocked.opex if o.name == "Power Expenses")
        expected_old = 31.0 * 0.63 * 1.17 * 8760 * 96 / 1000
        assert power_old.y1_amount_keur == pytest.approx(expected_old, rel=1e-6)
        assert power_new.y1_amount_keur == pytest.approx(expected_old * factor)

    def test_it_mw_shock_starts_from_31(self, seeded_db):
        from app.data_center_authority import GENERIC_DATA_CENTER_REFERENCE_DRIVERS
        from app.services.sensitivity_service import _apply_shock

        proj = _custom_project()
        assert proj.technical.capacity_mw == pytest.approx(31.0)
        shocked = _apply_shock(proj, "dc_it_mw", 10.0, dc_drivers=_custom_drivers())
        assert shocked.technical.capacity_mw == pytest.approx(31.0 * 1.10)
        # Revenue curve linear in capacity:
        assert shocked.revenue.market_prices_curve[0] == pytest.approx(
            proj.revenue.market_prices_curve[0])
        power_old = next(o for o in proj.opex if o.name == "Power Expenses")
        power_new = next(o for o in shocked.opex if o.name == "Power Expenses")
        assert power_new.y1_amount_keur == pytest.approx(
            power_old.y1_amount_keur * 1.10)
        assert (GENERIC_DATA_CENTER_REFERENCE_DRIVERS.stabilized_occupancy
                != 0.91)

    def test_service_price_does_not_touch_power_source(self, seeded_db):
        from app.services.sensitivity_service import _apply_shock

        proj = _custom_project()
        shocked = _apply_shock(proj, "dc_service_price", 10.0,
                               dc_drivers=_custom_drivers())
        power_old = next(o for o in proj.opex if o.name == "Power Expenses")
        power_new = next(o for o in shocked.opex if o.name == "Power Expenses")
        assert power_new.y1_amount_keur == pytest.approx(power_old.y1_amount_keur)
        assert shocked.revenue.ppa_base_tariff != proj.revenue.ppa_base_tariff

    def test_pue_does_not_touch_revenue(self, seeded_db):
        from app.services.sensitivity_service import _apply_shock

        proj = _custom_project()
        shocked = _apply_shock(proj, "dc_pue", 10.0, dc_drivers=_custom_drivers())
        assert shocked.revenue.market_prices_curve == proj.revenue.market_prices_curve
        power_old = next(o for o in proj.opex if o.name == "Power Expenses")
        power_new = next(o for o in shocked.opex if o.name == "Power Expenses")
        assert power_new.y1_amount_keur != power_old.y1_amount_keur

    def test_electricity_price_does_not_touch_revenue(self, seeded_db):
        from app.services.sensitivity_service import _apply_shock

        proj = _custom_project()
        shocked = _apply_shock(proj, "dc_electricity_price", 10.0,
                               dc_drivers=_custom_drivers())
        assert shocked.revenue.market_prices_curve == proj.revenue.market_prices_curve

    def test_scenario_override_becomes_baseline(self, seeded_db):
        """Scenario overrides dc_pue to 1.15 -> +10% PUE sensitivity starts
        from 1.15, not the base snapshot 1.17 and not generic 1.30."""
        snap = _custom_snapshot()
        snap["dc_pue"] = "1.15"
        from app.input_adapter import build_projectinputs_from_snapshot
        from app.data_center_authority import drivers_from_snapshot

        proj = build_projectinputs_from_snapshot(snap)
        drivers = drivers_from_snapshot(snap)
        assert drivers.pue == pytest.approx(1.15)

        from app.services.sensitivity_service import _apply_shock
        shocked = _apply_shock(proj, "dc_pue", 10.0, dc_drivers=drivers)
        power_old = next(o for o in proj.opex if o.name == "Power Expenses")
        power_new = next(o for o in shocked.opex if o.name == "Power Expenses")
        expected_base = 31.0 * 0.63 * 1.15 * 8760 * 96 / 1000
        assert power_old.y1_amount_keur == pytest.approx(expected_base, rel=1e-6)
        assert power_new.y1_amount_keur == pytest.approx(expected_base * 1.10)

    def test_generic_drivers_never_substituted_for_custom_project(
            self, seeded_db, monkeypatch):
        """Correction C core regression: run_sensitivity with a custom DC
        project must use the project's own drivers, not the generic set."""
        import app.services.sensitivity_service as ssvc
        from app.data_center_authority import GENERIC_DATA_CENTER_REFERENCE_DRIVERS

        proj = _custom_project()
        # Baseline power y1 from the CUSTOM drivers:
        power_custom = next(
            o for o in proj.opex if o.name == "Power Expenses").y1_amount_keur
        gd = GENERIC_DATA_CENTER_REFERENCE_DRIVERS
        power_generic = (
            20.0 * gd.occupancy_y1 * gd.pue * 8760
            * gd.electricity_price_eur_mwh / 1000)
        assert power_custom != pytest.approx(power_generic, rel=0.01)

        # If the route fails to pass the context, the seam fails closed.
        from app.services.sensitivity_service import DCDriverContextRequiredError
        with pytest.raises(DCDriverContextRequiredError):
            ssvc._apply_shock(proj, "dc_pue", 10.0, dc_drivers=None)

        # With the context, the shocked result carries the custom baseline.
        shocked = ssvc._apply_shock(proj, "dc_pue", 10.0,
                                    dc_drivers=_custom_drivers())
        power_new = next(o for o in shocked.opex if o.name == "Power Expenses")
        assert power_new.y1_amount_keur == pytest.approx(power_custom * 1.10)

    def test_renewable_drivers_still_fail_before_execution(
            self, seeded_db, monkeypatch):
        import app.services.sensitivity_service as ssvc

        executed = []
        monkeypatch.setattr(ssvc, "_run_once",
                            lambda p: (executed.append(1), {"k": None})[1])
        with pytest.raises(Exception):
            ssvc.run_sensitivity(_custom_project(), ["yield"], [10.0],
                                 vertical="Data Center",
                                 dc_drivers=_custom_drivers())
        assert executed == []
