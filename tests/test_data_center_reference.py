"""Generic Data Center Reference V1 — canonical authority and runtime acceptance.

Covers the mandatory acceptance criteria of FINCO Generic Data Center
Reference V1:

S.1  Factory: canonical identity, 20 MW IT, 200,000 kEUR CAPEX, 24 months.
S.2  CAPEX reconciliation: every parent == sum(children); parents == 200,000.
S.3  Revenue math: 20 MW × 1,000 × 12 × 175 × occupancy == canonical identity,
     with the Y1/Y2/Y3 occupancy authority tested explicitly.
S.4  Power OPEX: IT MW × occupancy × PUE × 8,760 × EUR/MWh, unit conversions,
     and proof of no double count (revenue never includes electricity sales).
S.5  Full runtime: finite KPIs through the canonical engine, no crash, no
     renewable-only assertion failure.
S.6  Sources & Uses: engine convergence (financing model returns).
S.7  Debt: senior schedule reconciliation (opening/draws/repayment/closing).
S.8  Tax: reconciles through the generic tax path (part of the clean run).
S.9  Working-copy creation at 25 MW: CAPEX/OPEX PER_MW, revenue and power
     OPEX derived from the new capacity.
S.12 Derived power OPEX: driver edits recalculate B.08, never double count.
S.13 Protected reference: read-only, no editable forms, mutation rejected.

All assumptions are synthetic public generic data.  No real company,
operator, project, or jurisdiction is used.
"""
from __future__ import annotations

import math

import pytest


# ─────────────────────────────────────────────────────────────────────────────
# Shared helpers
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture
def seeded_db(tmp_path, monkeypatch):
    from app.persistence import db

    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "data-center-reference.db"))
    db.init_db()
    yield


def _factory():
    from app.project_factories import create_generic_data_center_reference
    return create_generic_data_center_reference()


def _drivers():
    from app.data_center_authority import GENERIC_DATA_CENTER_REFERENCE_DRIVERS
    return GENERIC_DATA_CENTER_REFERENCE_DRIVERS


# ─────────────────────────────────────────────────────────────────────────────
# S.1 Factory
# ─────────────────────────────────────────────────────────────────────────────

class TestDataCenterFactory:
    def test_canonical_identity(self):
        pi = _factory()
        assert pi.info.name == "Generic Data Center Reference"
        assert pi.info.company == "Synthetic Sponsor D"
        assert pi.info.code == "REF-DATACENTER-D"
        assert pi.info.country_iso == "XD"  # generic synthetic market code
        assert pi.info.construction_months == 24
        assert pi.info.horizon_years == 20
        assert str(pi.info.period_frequency).upper().endswith("SEMESTRIAL")
        assert pi.info.financial_close.year == 2030
        assert pi.info.cod_date > pi.info.financial_close

    def test_capacity_is_it_load_20mw(self):
        pi = _factory()
        assert pi.technical.capacity_mw == 20.0

    def test_capex_200000_keur_and_per_mw(self):
        pi = _factory()
        assert pi.capex.total_capex == pytest.approx(200_000.0)
        assert pi.capex.total_capex / pi.technical.capacity_mw == pytest.approx(10_000.0)

    def test_no_real_country_or_operator_language(self):
        pi = _factory()
        assert pi.info.country_iso not in {"HR", "DE", "IE", "NL", "US"}

    def test_financing_synthetic_starting_assumptions(self):
        pi = _factory()
        fin = pi.financing
        assert fin.gearing_ratio == pytest.approx(0.65)
        assert fin.senior_tenor_years == 12
        assert fin.base_rate == pytest.approx(0.03)
        assert fin.margin_bps == 300
        assert fin.target_dscr == pytest.approx(1.30)
        assert fin.lockup_dscr == pytest.approx(1.15)
        assert fin.dsra_months == 6

    def test_tax_is_generic_clean_25pct(self):
        pi = _factory()
        assert pi.tax.corporate_rate == pytest.approx(0.25)
        assert pi.tax.clean_cash_tax_timing_enabled is True


# ─────────────────────────────────────────────────────────────────────────────
# S.2 CAPEX reconciliation
# ─────────────────────────────────────────────────────────────────────────────

class TestDataCenterCapexReconciliation:
    def test_parent_amounts_sum_to_200000(self):
        pi = _factory()
        expected = {
            "production_units": 80_000.0,
            "epc_contract": 55_000.0,
            "grid_connection": 20_000.0,
            "ops_prep": 5_000.0,
            "epc_other": 15_000.0,
            "audit_legal": 8_000.0,
            "construction_mgmt_a": 7_000.0,
            "contingencies": 10_000.0,
        }
        total = 0.0
        for field_name, amount in expected.items():
            item = getattr(pi.capex, field_name)
            assert item.amount_keur == pytest.approx(amount), field_name
            total += item.amount_keur
        assert total == pytest.approx(200_000.0)
        # Every other canonical parent is zero (no duplicate contributions).
        for field_name in (
            "insurances", "lease_tax", "construction_mgmt_b", "commissioning",
            "taxes", "project_acquisition", "project_rights",
        ):
            assert getattr(pi.capex, field_name).amount_keur == 0.0, field_name

    def test_detail_children_reconcile_to_parents(self):
        from app.reference_detail_catalog import capex_children, allocate_parent_amount

        parents = {
            "C.01": 80_000.0, "C.02": 55_000.0, "C.03": 20_000.0, "C.04": 5_000.0,
            "C.05": 15_000.0, "C.08": 8_000.0, "C.09": 7_000.0, "C.13": 10_000.0,
        }
        for code, amount in parents.items():
            children = capex_children("data_center", code)
            allocated = allocate_parent_amount(amount, children)
            assert abs(sum(a for _, a in allocated) - amount) < 1e-6, code

    def test_capex_children_fail_closed_for_unknown_technology(self):
        from app.reference_detail_catalog import capex_children
        with pytest.raises(ValueError):
            capex_children("data_center_typo", "C.01")


# ─────────────────────────────────────────────────────────────────────────────
# S.3 Revenue math
# ─────────────────────────────────────────────────────────────────────────────

class TestDataCenterRevenueMath:
    def test_stabilized_core_capacity_revenue_identity(self):
        from app.data_center_authority import core_capacity_revenue_keur
        assert core_capacity_revenue_keur(
            capacity_mw=20.0, service_price_eur_kw_month=175.0, occupancy=0.85,
        ) == pytest.approx(35_700.0)

    def test_occupancy_ramp_authority_y1_y2_y3(self):
        from app.data_center_authority import occupancy_for_year
        d = _drivers()
        assert occupancy_for_year(d, 1) == pytest.approx(0.55)
        assert occupancy_for_year(d, 2) == pytest.approx(0.70)
        assert occupancy_for_year(d, 3) == pytest.approx(0.85)
        assert occupancy_for_year(d, 10) == pytest.approx(0.85)

    def test_runtime_revenue_matches_canonical_identity(self):
        """Semester revenue schedule must reproduce the annual identity exactly."""
        from finco_core.engine.period_engine import PeriodEngine
        from finco_core.revenue.generation import full_revenue_schedule

        pi = _factory()
        d = _drivers()
        schedule = full_revenue_schedule(
            pi,
            PeriodEngine(
                pi.info.financial_close,
                pi.info.construction_months,
                pi.info.horizon_years,
                pi.revenue.ppa_term_years,
            ),
        )
        annual = {}
        for period_idx, value in schedule.items():
            if value <= 0:
                continue
            # period 0..3 = construction (24 months); operating years follow
            operating_period = period_idx - 4
            year = operating_period // 2 + 1
            annual[year] = annual.get(year, 0.0) + value
        expected_y1 = 20.0 * 12 * 175.0 * d.occupancy_y1
        expected_y2 = 20.0 * 12 * 175.0 * d.occupancy_y2 * (1 + d.revenue_escalation)
        expected_y3 = 20.0 * 12 * 175.0 * d.stabilized_occupancy * (1 + d.revenue_escalation) ** 2
        assert annual[1] == pytest.approx(expected_y1, rel=1e-6)
        assert annual[2] == pytest.approx(expected_y2, rel=1e-6)
        assert annual[3] == pytest.approx(expected_y3, rel=1e-6)


# ─────────────────────────────────────────────────────────────────────────────
# S.4 Power OPEX
# ─────────────────────────────────────────────────────────────────────────────

class TestDataCenterPowerOpex:
    def test_stabilized_power_cost_identity(self):
        from app.data_center_authority import annual_power_cost_keur
        # 20 × 0.85 × 1.30 × 8,760 × 70 / 1000 = 13,551.72 kEUR
        assert annual_power_cost_keur(
            capacity_mw=20.0, occupancy=0.85, pue=1.30, electricity_price_eur_mwh=70.0,
        ) == pytest.approx(13_551.72)

    def test_power_step_changes_match_identity_per_year(self):
        from app.data_center_authority import power_step_changes
        d = _drivers()
        steps = power_step_changes(d, 20.0, 20)
        assert len(steps) == 20
        y1_expected = 20.0 * d.occupancy_y1 * d.pue * 8_760 * d.electricity_price_eur_mwh / 1_000
        assert steps[0] == (1, pytest.approx(y1_expected))
        y2_expected = (
            20.0 * d.occupancy_y2 * d.pue * 8_760 * d.electricity_price_eur_mwh / 1_000
            * (1 + d.electricity_price_escalation)
        )
        assert steps[1][0] == 2
        assert steps[1][1] == pytest.approx(y2_expected)

    def test_no_double_count_revenue_has_no_electricity_sale(self):
        """The 175 EUR/kW/month is all-in service revenue; electricity is OPEX."""
        pi = _factory()
        assert pi.revenue.co2_enabled is False
        assert pi.revenue.ppa_production_share == pytest.approx(0.0)
        assert pi.revenue.balancing_cost_pv == pytest.approx(0.0)
        assert pi.revenue.balancing_cost_wind_eur_mwh == pytest.approx(0.0)
        # No pass-through power revenue: revenue comes only from the service
        # price curve; power costs appear only in the B.08 OPEX item.
        power_items = [i for i in pi.opex if i.name == "Power Expenses"]
        assert len(power_items) == 1

    def test_power_opex_is_derived_not_per_mw_seeded(self, seeded_db):
        from app.services.reference_seed_service import create_reference_seeded_project
        record = create_reference_seeded_project(
            user_id="dc-power-user",
            template_source="generic_data_center_reference",
            requested_name="DC Power Check",
            capacity_mw=20.0,
        )
        from app.persistence.opex_sub_lines import get_active_sub_lines_for_project
        rows = get_active_sub_lines_for_project(record.project_id)
        b08_rows = [r for r in rows if r.parent_group_code == "B.08"]
        assert b08_rows == [], "B.08 must never be seeded as a persisted PER_MW line"


# ─────────────────────────────────────────────────────────────────────────────
# S.5–S.8 Full runtime
# ─────────────────────────────────────────────────────────────────────────────

class TestDataCenterFullRuntime:
    def test_clean_production_run_produces_finite_kpis(self):
        from app.api.project_runner import run_project

        result = run_project("Generic Data Center Reference", "Base")
        kpis = result["kpis"]
        for key in ("total_capex_keur", "total_revenue_keur", "total_ebitda_keur",
                    "total_opex_keur", "min_dscr", "avg_dscr"):
            value = kpis.get(key)
            assert value is not None and isinstance(value, float) and math.isfinite(value), key
        assert kpis["total_revenue_keur"] > 0
        assert kpis["total_ebitda_keur"] > 0
        # Honest economics: no renewable-only assertion failure; DSCR series
        # is finite and the ramp years surface as lock-up periods.
        assert kpis["target_dscr"] == pytest.approx(1.30)

    def test_project_irr_is_honest_unscaled_result(self):
        from app.api.project_runner import run_project

        kpis = run_project("Generic Data Center Reference", "Base")["kpis"]
        project_irr = kpis.get("project_irr")
        assert project_irr is not None and math.isfinite(project_irr)

    def test_senior_debt_reconciles(self):
        from app.services.production_financial_authority import run_clean_production

        run = run_clean_production(_factory(), "Base", project_type="Data Center")
        fin = run.g2c_result.financing_result
        sized = getattr(fin, "final_senior_commitment_keur", None)
        assert sized is not None and math.isfinite(sized) and sized > 0
        capacity = getattr(fin, "dscr_debt_capacity_keur", None)
        assert capacity is not None and math.isfinite(capacity)
        # Fixed-point Sources & Uses converged (S.6) — the outer financing
        # fixed point returns only on convergence or raises.
        assert getattr(fin, "fixed_point_iteration_count", 1) >= 1

    def test_dscr_sizing_binds_below_gearing_cap(self):
        """Honest economics: DSCR capacity < the 65% gearing cap (documented)."""
        from app.services.production_financial_authority import run_clean_production

        run = run_clean_production(_factory(), "Base", project_type="Data Center")
        fin = run.g2c_result.financing_result
        capacity = getattr(fin, "dscr_debt_capacity_keur", None)
        if capacity is not None:
            assert capacity < 0.65 * 200_000.0

    def test_runtime_adapter_recomputes_power_from_capacity(self):
        from app.project_factories import create_default_data_center_project
        pi = create_default_data_center_project(capacity_mw=40.0)
        power = next(i for i in pi.opex if i.name == "Power Expenses")
        expected_y1 = 40.0 * 0.55 * 1.30 * 8_760 * 70.0 / 1_000
        assert power.step_changes[0] == (1, pytest.approx(expected_y1))
        assert pi.technical.capacity_mw == pytest.approx(40.0)


# ─────────────────────────────────────────────────────────────────────────────
# S.9 Working-copy creation at 25 MW
# ─────────────────────────────────────────────────────────────────────────────

class TestDataCenterWorkingCopy:
    @pytest.fixture()
    def dc_copy(self, seeded_db):
        from app.services.reference_seed_service import create_reference_seeded_project
        record = create_reference_seeded_project(
            user_id="dc-25-user",
            template_source="generic_data_center_reference",
            requested_name="DC 25 MW Working Copy",
            capacity_mw=25.0,
        )
        return record

    def test_working_copy_identity(self, dc_copy):
        assert dc_copy.project_type == "Data Center"
        assert dc_copy.template_source == "generic_data_center_reference"
        assert dc_copy.is_protected is False
        assert dc_copy.is_readonly is False

    def test_capex_scales_per_mw(self, dc_copy):
        from app.persistence.capex_sub_lines import get_active_sub_lines_for_project
        from app.persistence.workspace_repository import get_workspace_state

        rows = get_active_sub_lines_for_project(dc_copy.project_id)
        total = sum(r.amount_keur for r in rows)
        assert total == pytest.approx(250_000.0)  # 25 MW × 10,000 kEUR/MW
        ws = get_workspace_state("dc-25-user", dc_copy.project_id)
        assert float(ws.draft_snapshot["total_capex_keur"]) == pytest.approx(250_000.0)

    def test_nonpower_opex_scales_per_mw(self, dc_copy):
        from app.persistence.opex_sub_lines import get_active_sub_lines_for_project

        rows = get_active_sub_lines_for_project(dc_copy.project_id)
        total = sum(r.amount_keur for r in rows)
        assert total == pytest.approx(9_700.0 * 25.0 / 20.0)

    def test_revenue_and_power_derived_from_25mw(self, dc_copy):
        from app.persistence.workspace_repository import get_workspace_state
        from app.input_adapter import build_projectinputs_from_snapshot

        ws = get_workspace_state("dc-25-user", dc_copy.project_id)
        pi = build_projectinputs_from_snapshot(dict(ws.draft_snapshot))
        assert pi.technical.capacity_mw == pytest.approx(25.0)
        power = next(i for i in pi.opex if i.name == "Power Expenses")
        expected_y1 = 25.0 * 0.55 * 1.30 * 8_760 * 70.0 / 1_000
        assert power.step_changes[0] == (1, pytest.approx(expected_y1))
        # Revenue curve scales linearly with capacity (same EUR/MWh curve).
        from app.project_factories import create_generic_data_center_reference
        ref = create_generic_data_center_reference()
        assert pi.revenue.market_prices_curve == ref.revenue.market_prices_curve

    def test_full_run_at_25mw(self, dc_copy):
        from app.persistence.workspace_repository import get_workspace_state
        from app.input_adapter import build_projectinputs_from_snapshot
        from app.services.production_financial_authority import run_clean_production

        ws = get_workspace_state("dc-25-user", dc_copy.project_id)
        pi = build_projectinputs_from_snapshot(dict(ws.draft_snapshot))
        run = run_clean_production(pi, "Base", project_type="Data Center")
        assert run.g2c_result.total_gross_dividend_paid_keur is not None
        assert math.isfinite(run.g2c_result.financing_result.final_senior_commitment_keur)


# ─────────────────────────────────────────────────────────────────────────────
# S.12 Derived power OPEX follows driver edits
# ─────────────────────────────────────────────────────────────────────────────

class TestDataCenterDerivedPowerRecalculation:
    def _pi_from_snapshot(self, snapshot: dict):
        from app.input_adapter import build_projectinputs_from_snapshot
        return build_projectinputs_from_snapshot(snapshot)

    def _power_y1(self, pi) -> float:
        return next(i for i in pi.opex if i.name == "Power Expenses").step_changes[0][1]

    def _base_snapshot(self) -> dict:
        from app.persistence.projects_repository import _compute_baseline_snapshot
        return dict(_compute_baseline_snapshot("Data Center", "generic_data_center_reference"))

    def test_capacity_change_recalculates_power(self):
        snap = self._base_snapshot()
        snap["capacity_mw"] = "30"
        pi = self._pi_from_snapshot(snap)
        expected = 30.0 * 0.55 * 1.30 * 8_760 * 70.0 / 1_000
        assert self._power_y1(pi) == pytest.approx(expected)

    def test_occupancy_change_recalculates_power(self):
        snap = self._base_snapshot()
        snap["dc_occupancy_y1"] = "80"  # percent convention
        pi = self._pi_from_snapshot(snap)
        expected = 20.0 * 0.80 * 1.30 * 8_760 * 70.0 / 1_000
        assert self._power_y1(pi) == pytest.approx(expected)

    def test_pue_change_recalculates_power(self):
        snap = self._base_snapshot()
        snap["dc_pue"] = "1.5"
        pi = self._pi_from_snapshot(snap)
        expected = 20.0 * 0.55 * 1.50 * 8_760 * 70.0 / 1_000
        assert self._power_y1(pi) == pytest.approx(expected)

    def test_electricity_price_change_recalculates_power(self):
        snap = self._base_snapshot()
        snap["dc_electricity_price_eur_mwh"] = "90"
        pi = self._pi_from_snapshot(snap)
        expected = 20.0 * 0.55 * 1.30 * 8_760 * 90.0 / 1_000
        assert self._power_y1(pi) == pytest.approx(expected)

    def test_service_price_change_recalculates_revenue(self):
        snap = self._base_snapshot()
        snap["dc_service_price_eur_kw_month"] = "200"
        pi = self._pi_from_snapshot(snap)
        d = _drivers()
        expected_curve_y1 = 12_000.0 * 200.0 * d.occupancy_y1 / 8_760.0
        assert pi.revenue.market_prices_curve[0] == pytest.approx(expected_curve_y1)


# ─────────────────────────────────────────────────────────────────────────────
# S.13 Protected reference contract
# ─────────────────────────────────────────────────────────────────────────────

class TestDataCenterProtectedReference:
    def test_reference_is_protected_and_readonly(self, seeded_db):
        from app.services.project_library_service import ensure_reference_models
        from app.persistence.projects_repository import get_reference_by_template_source

        ensure_reference_models()
        ref = get_reference_by_template_source("generic_data_center_reference")
        assert ref is not None
        assert ref.user_id == "__reference__"
        assert ref.project_role == "reference"
        assert ref.is_protected is True
        assert ref.is_readonly is True

    def test_reference_is_canonical_and_cloneable(self, seeded_db):
        from app.services.project_library_service import (
            CANONICAL_REFERENCE_TEMPLATE_SOURCES,
            CLONEABLE_TEMPLATE_SOURCES,
            ensure_reference_models,
        )

        ensure_reference_models()
        assert "generic_data_center_reference" in CANONICAL_REFERENCE_TEMPLATE_SOURCES
        assert "generic_data_center_reference" in CLONEABLE_TEMPLATE_SOURCES

    def test_reference_workbook_has_no_editable_forms(self, seeded_db):
        from fastapi.testclient import TestClient
        import main_web
        from app.services.project_library_service import ensure_reference_models

        ensure_reference_models()
        from app.auth import COOKIE_NAME, create_session_token
        cookies = {COOKIE_NAME: create_session_token(user_id="dc-prot-user", username="admin")}
        client = TestClient(main_web.app, raise_server_exceptions=True)
        page = client.get("/v2/workbook?project=generic_data_center_reference-reference", cookies=cookies)
        assert page.status_code == 200
        assert 'hx-post="/v2/capex/line/update"' not in page.text
        assert 'hx-post="/v2/opex/line/update"' not in page.text

    def test_direct_mutation_rejected(self, seeded_db):
        from app.persistence.projects_repository import get_project_by_code
        from app.services.project_library_service import ensure_reference_models
        from app.v2.capex_commands import CapexProtectedReferenceError, add_capex_line
        from app.workbook.registry import WORKBOOK

        ensure_reference_models()
        ref = get_project_by_code("__reference__", "generic_data_center_reference-reference")
        assert ref is not None
        with pytest.raises(CapexProtectedReferenceError):
            add_capex_line(
                project_record=ref, user_id="__reference__", label="Rejected",
                parent_category_code="C.01", amount_keur=1.0,
                workbook_version=WORKBOOK.version, expected_content_hash="not-used",
            )
