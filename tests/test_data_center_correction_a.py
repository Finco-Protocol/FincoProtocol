"""PR #88 Correction A — Generic Data Center derived-authority closure.

Covers:
A5   Stateless run scaling re-derives Data Center economics at 20/25/40 MW.
B/C  Capacity rescale uses the CURRENT persisted drivers (never defaults).
D    Reset-reference-seeded-lines keeps the derived B.08 in the OPEX summary.
E    Availability is NOT an economic revenue driver (neutral runtime).
F    A4 preview and A5 run share the same capacity/CAPEX/OPEX semantics.

No financial_engine or finco_core changes; app.data_center_authority remains
the single Data Center economic authority.
"""
from __future__ import annotations

import math

import pytest


@pytest.fixture
def seeded_db(tmp_path, monkeypatch):
    from app.persistence import db

    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "dc-correction-a.db"))
    db.init_db()
    yield


def _dc_key() -> str:
    return "generic_data_center_reference"


def _expected_power_y1(capacity_mw: float, occ: float, pue: float, price: float) -> float:
    return capacity_mw * occ * pue * 8_760.0 * price / 1_000.0


def _b08_item(pi):
    return next(i for i in pi.opex if i.name == "Power Expenses")


# ─────────────────────────────────────────────────────────────────────────────
# A5: stateless run scaling re-derives Data Center authority
# ─────────────────────────────────────────────────────────────────────────────

class TestA5DataCenterScaling:
    def _scaled_pi(self, capacity_mw: float):
        from app.api.v1.model_run import _build_scaled_project_inputs
        from app.services.reference_seed_service import (
            _reference_inputs,
            build_reference_scaling_preview,
        )

        pi = _reference_inputs(_dc_key())
        preview = build_reference_scaling_preview(_dc_key(), capacity_mw)
        return _build_scaled_project_inputs(
            pi, preview["ratio"], capacity_mw, key_is_data_center=True
        ), preview

    @pytest.mark.parametrize("capacity_mw", [20.0, 25.0, 40.0])
    def test_a5_run_returns_finite_kpis(self, capacity_mw):
        from app.api.v1.model_run import build_run_response_data

        data = build_run_response_data(_dc_key(), capacity_mw)
        assert data["scaling"]["requested_capacity_mw"] == capacity_mw
        assert data["authority"]["calculation_count"] == 1
        assert data["authority"]["project_created"] is False
        results = data["results"]
        for k in ("total_revenue_keur", "total_ebitda_keur", "total_opex_keur", "min_dscr"):
            v = results[k]
            assert v is not None and math.isfinite(v), k

    def test_a5_40mw_capex_and_b08(self):
        pi, preview = self._scaled_pi(40.0)
        assert preview["scaled_total_capex_keur"] == pytest.approx(400_000.0)
        assert pi.technical.capacity_mw == pytest.approx(40.0)
        expected_y1_power = _expected_power_y1(40.0, 0.55, 1.30, 70.0)
        assert _b08_item(pi).step_changes[0] == (1, pytest.approx(expected_y1_power))
        assert _b08_item(pi).y1_amount_keur == pytest.approx(expected_y1_power)

    def test_a5_40mw_full_b08_schedule_is_40mw_not_reference(self):
        pi, _ = self._scaled_pi(40.0)
        steps = _b08_item(pi).step_changes
        assert len(steps) == 20
        for year, amount in steps:
            expected = _expected_power_y1(
                40.0,
                0.55 if year == 1 else (0.70 if year == 2 else 0.85),
                1.30,
                70.0,
            ) * (1.02 ** (year - 1))
            assert amount == pytest.approx(expected), year

    def test_a5_40mw_y1_revenue_identity(self):
        """40 × 1,000 × 12 × 175 × 55 % / 1,000 = 46,200 kEUR, exactly."""
        from finco_core.engine.period_engine import PeriodEngine
        from finco_core.revenue.generation import full_revenue_schedule

        pi, _ = self._scaled_pi(40.0)
        schedule = full_revenue_schedule(
            pi,
            PeriodEngine(
                pi.info.financial_close,
                pi.info.construction_months,
                pi.info.horizon_years,
                pi.revenue.ppa_term_years,
            ),
        )
        y1 = sum(v for idx, v in schedule.items() if v > 0 and 4 <= idx <= 5)
        assert y1 == pytest.approx(40.0 * 1_000 * 12 * 175.0 * 0.55 / 1_000.0)

    def test_a5_40mw_linearly_scalable_components_capacity_consistent(self):
        pi40, _ = self._scaled_pi(40.0)
        pi20 = _reference_inputs_20mw()

        # CAPEX scales exactly ×2.
        assert pi40.capex.total_capex == pytest.approx(2 * pi20.capex.total_capex)
        # Non-power OPEX scales exactly ×2.
        nonpower40 = sum(i.y1_amount_keur for i in pi40.opex if i.name != "Power Expenses")
        nonpower20 = sum(i.y1_amount_keur for i in pi20.opex if i.name != "Power Expenses")
        assert nonpower40 == pytest.approx(2 * nonpower20)
        # The revenue curve is capacity-independent (same EUR/MWh authority).
        assert pi40.revenue.market_prices_curve == pi20.revenue.market_prices_curve
        assert pi40.revenue.market_inflation == pi20.revenue.market_inflation
        # B.08 steps are exactly ×2 of the reference schedule (linearity).
        s40 = dict(_b08_item(pi40).step_changes)
        s20 = dict(_b08_item(pi20).step_changes)
        for year, amount in s20.items():
            assert s40[year] == pytest.approx(2 * amount), year
        # Sponsor equity scales exactly ×2.
        assert pi40.financing.share_capital_keur == pytest.approx(
            2 * pi20.financing.share_capital_keur
        )

    def test_a5_exactly_one_calculation_no_db(self, seeded_db):
        from app.api.v1.model_run import build_run_response_data

        data = build_run_response_data(_dc_key(), 25.0)
        assert data["authority"]["calculation_count"] == 1
        assert data["authority"]["workspace_mutated"] is False
        assert data["authority"]["persisted"] is False
        assert data["scaling"]["stateless"] is True


def _reference_inputs_20mw():
    from app.services.reference_seed_service import _reference_inputs
    return _reference_inputs(_dc_key())


# ─────────────────────────────────────────────────────────────────────────────
# F: A4 preview and A5 run consistency
# ─────────────────────────────────────────────────────────────────────────────

class TestPreviewRunConsistency:
    @pytest.mark.parametrize("capacity_mw", [20.0, 25.0, 40.0])
    def test_preview_and_run_agree(self, capacity_mw):
        from app.api.v1.model_run import build_run_response_data
        from app.services.reference_seed_service import build_reference_scaling_preview

        preview = build_reference_scaling_preview(_dc_key(), capacity_mw)
        run = build_run_response_data(_dc_key(), capacity_mw)

        assert run["scaling"]["requested_capacity_mw"] == preview["requested_capacity_mw"]
        assert run["capex"]["scaled_total_capex_keur"] == pytest.approx(
            preview["scaled_total_capex_keur"]
        )
        # Y1 OPEX summary semantics: non-power PER_MW + derived B.08 Y1.
        b08 = next(
            it for it in preview["opex_items"] if it["canonical_key"] == "Power Expenses"
        )
        assert b08["scaling_mode"] == "DERIVED"
        expected_y1_opex = sum(
            it["scaled_amount_keur"]
            for it in preview["opex_items"]
            if it["canonical_key"] != "Power Expenses"
        ) + _expected_power_y1(capacity_mw, 0.55, 1.30, 70.0)
        assert preview["scaled_opex_y1_keur"] == pytest.approx(expected_y1_opex)
        assert run["opex"]["scaled_opex_y1_keur"] == pytest.approx(preview["scaled_opex_y1_keur"])
        # No 20-MW residue: the derived B.08 at this capacity is not the
        # reference amount (except at the reference capacity itself).
        if capacity_mw != 20.0:
            assert b08["scaled_amount_keur"] != pytest.approx(b08["reference_amount_keur"])


# ─────────────────────────────────────────────────────────────────────────────
# B/C: current-driver authority survives capacity rescale (sequential HTTP)
# ─────────────────────────────────────────────────────────────────────────────

class TestCurrentDriverThenCapacityRescale:
    def test_sequential_driver_edits_then_capacity(self, seeded_db):
        from app.auth import COOKIE_NAME, create_session_token
        from app.persistence.workspace_repository import get_workspace_state
        from app.input_adapter import build_projectinputs_from_snapshot
        from app.services.reference_seed_service import create_reference_seeded_project
        from fastapi.testclient import TestClient
        import main_web

        user_id = "dc-corr-a-user"
        record = create_reference_seeded_project(
            user_id=user_id,
            template_source=_dc_key(),
            requested_name="Correction A Sequential",
            capacity_mw=20.0,
        )
        cookies = {COOKIE_NAME: create_session_token(user_id=user_id, username="admin")}
        client = TestClient(main_web.app, raise_server_exceptions=True)

        def _update(field_id: str, value: str) -> None:
            page = client.get(f"/v2/workbook?project={record.project_code}", cookies=cookies)
            assert page.status_code == 200
            import re

            m = re.search(r'name="content_hash" value="([^"]+)"', page.text)
            mv = re.search(r'name="workbook_version" value="([^"]+)"', page.text)
            assert m and mv, f"identity fields missing for {field_id}"
            resp = client.post(
                "/v2/workbook/update",
                data={
                    "field_id": field_id,
                    "value": value,
                    "project": record.project_code,
                    "workbook_version": mv.group(1),
                    "content_hash": m.group(1),
                    "sheet_id": "revenue" if field_id.startswith(("revenue.",)) else "project_setup",
                },
                cookies=cookies,
                headers={"HX-Request": "true"},
                follow_redirects=False,
            )
            assert resp.status_code == 200, f"{field_id}: {resp.text[:300]}"

        # Edit drivers on the 20 MW working copy.
        _update("revenue.data_center.pue", "1.50")
        _update("revenue.data_center.electricity_price", "90")
        _update("revenue.data_center.occupancy_y1", "65")

        # Then change capacity 20 → 25 MW.
        _update("project_setup.technical.capacity_mw", "25")

        expected_power_y1 = _expected_power_y1(25.0, 0.65, 1.50, 90.0)
        wrong_default_power = _expected_power_y1(25.0, 0.55, 1.30, 70.0)
        assert expected_power_y1 == pytest.approx(19_217.25)
        assert expected_power_y1 != pytest.approx(wrong_default_power)

        # Draft snapshot: edited drivers preserved, derived power current.
        ws = get_workspace_state(user_id, record.project_id)
        snap = dict(ws.draft_snapshot)
        assert float(snap["dc_pue"]) == pytest.approx(1.50)
        assert float(snap["dc_electricity_price_eur_mwh"]) == pytest.approx(90.0)
        assert float(snap["dc_occupancy_y1"]) == pytest.approx(65.0)
        assert float(snap["capacity_mw"]) == pytest.approx(25.0)
        assert float(snap["opex_power_expenses_y1_keur"]) == pytest.approx(expected_power_y1)

        # opex_y1_keur = non-power (PER_MW rescaled) + derived B.08 Y1.
        non_power = sum(
            r.amount_keur
            for r in __import__(
                "app.persistence.opex_sub_lines", fromlist=["get_active_sub_lines_for_project"]
            ).get_active_sub_lines_for_project(record.project_id)
        )
        assert float(snap["opex_y1_keur"]) == pytest.approx(non_power + expected_power_y1)

        # Built ProjectInputs + B.08 runtime item carry the current authority.
        pi = build_projectinputs_from_snapshot(snap)
        assert pi.technical.capacity_mw == pytest.approx(25.0)
        assert _b08_item(pi).step_changes[0] == (1, pytest.approx(expected_power_y1))
        assert _b08_item(pi).step_changes[0][1] != pytest.approx(wrong_default_power)

        # Actual production run boundary: the exact resolution the run
        # pipeline consumes (WorkbookService.to_projectinputs) carries the
        # current authority — no stale/default values can enter the engine.
        from app.workbook.service import WorkbookService
        from app.workbook.input_set import ProjectInputSet
        from app.workbook.registry import WORKBOOK

        pis_draft = ProjectInputSet.from_snapshot(snap, workbook=WORKBOOK)
        run_boundary_pi = WorkbookService.to_projectinputs(pis_draft)
        assert _b08_item(run_boundary_pi).step_changes[0] == (
            1, pytest.approx(expected_power_y1)
        )
        assert _b08_item(run_boundary_pi).step_changes[0][1] != pytest.approx(
            wrong_default_power
        )
        assert run_boundary_pi.technical.capacity_mw == pytest.approx(25.0)

        # The clean engine outcome for these aggressive synthetic driver
        # edits (PUE 1.50 / 90 EUR/MWh) is a deterministic fail-closed: the
        # SHL sweep cannot fully repay at 65 % gearing-cap / DSCR-1.30 with
        # the reduced EBITDA.  That is the honest economic result of the
        # user's drivers — crucially, the engine refuses with the CURRENT
        # authority (the debt-solver failure is reached with these inputs),
        # never silently running on stale/default values.
        from app.services.production_financial_authority import (
            CleanProductionRunUnavailable,
            run_clean_production,
        )
        with pytest.raises(CleanProductionRunUnavailable) as exc_info:
            run_clean_production(pi, "Base", project_type="Data Center")
        assert "SHL_MATURITY_RESIDUAL_FAILS_CLOSED" in str(exc_info.value.detail)

        # Workbook reload: persistence proof.
        reloaded = client.get(f"/v2/workbook?project={record.project_code}", cookies=cookies)
        assert reloaded.status_code == 200
        import re as _re

        assert _re.search(r'value="1\.5(|0+)"', reloaded.text)
        assert _re.search(r'value="90(\.0+)?"', reloaded.text)
        assert _re.search(r'value="65(\.0+)?"', reloaded.text)


# ─────────────────────────────────────────────────────────────────────────────
# D: reset-reference-seeded-lines preserves derived B.08
# ─────────────────────────────────────────────────────────────────────────────

class TestResetPreservesDerivedB08:
    def test_reset_keeps_b08_and_driver_edits(self, seeded_db):
        from app.auth import COOKIE_NAME, create_session_token
        from app.persistence.opex_sub_lines import (
            get_active_sub_lines_for_project,
            update_sub_line,
        )
        from app.persistence.workspace_repository import get_workspace_state
        from app.services.reference_seed_service import (
            create_reference_seeded_project,
            reset_reference_seeded_lines,
        )
        from fastapi.testclient import TestClient
        import main_web

        user_id = "dc-reset-user"
        record = create_reference_seeded_project(
            user_id=user_id,
            template_source=_dc_key(),
            requested_name="DC Reset Check",
            capacity_mw=20.0,
        )
        cookies = {COOKIE_NAME: create_session_token(user_id=user_id, username="admin")}
        client = TestClient(main_web.app, raise_server_exceptions=True)

        seed_rows = get_active_sub_lines_for_project(record.project_id)
        target = next(r for r in seed_rows if r.amount_keur > 0 and r.source == "reference_seed")
        seed_amount = target.amount_keur

        # 1. Modify an OPEX line (source flips to user_override).
        rows = get_active_sub_lines_for_project(record.project_id)
        target = next(r for r in rows if r.sub_line_id == target.sub_line_id)
        from app.persistence.db import get_cursor

        with get_cursor() as cur:
            updated = update_sub_line(
                cur,
                project_id=record.project_id,
                sub_line_id=target.sub_line_id,
                label=target.label,
                amount_keur=seed_amount + 25.0,
                inflation_pct=float(target.inflation_pct),
                row_version=target.updated_at,
            )
        assert updated is not None
        rows_after_edit = get_active_sub_lines_for_project(record.project_id)
        edited = next(r for r in rows_after_edit if r.sub_line_id == target.sub_line_id)
        assert edited.source == "user_override"

        # 2. Modify a Data Center power driver (via the real update endpoint).
        page = client.get(f"/v2/workbook?project={record.project_code}", cookies=cookies)
        assert page.status_code == 200
        import re

        m = re.search(r'name="content_hash" value="([^"]+)"', page.text)
        mv = re.search(r'name="workbook_version" value="([^"]+)"', page.text)
        resp = client.post(
            "/v2/workbook/update",
            data={
                "field_id": "revenue.data_center.electricity_price",
                "value": "90",
                "project": record.project_code,
                "workbook_version": mv.group(1),
                "content_hash": m.group(1),
                "sheet_id": "revenue",
            },
            cookies=cookies,
            headers={"HX-Request": "true"},
            follow_redirects=False,
        )
        assert resp.status_code == 200, resp.text[:300]

        # 3. Reset reference-seeded lines.
        reset_reference_seeded_lines(user_id=user_id, project_code=record.project_code)

        ws = get_workspace_state(user_id, record.project_id)
        snap = dict(ws.draft_snapshot)

        # User OPEX line returns to its seed amount.
        rows_after_reset = get_active_sub_lines_for_project(record.project_id)
        restored = next(
            r for r in rows_after_reset if r.sub_line_id == target.sub_line_id
        )
        assert restored.amount_keur == pytest.approx(seed_amount)
        assert restored.source == "reference_seed"

        # The driver edit is NOT silently reset.
        assert float(snap["dc_electricity_price_eur_mwh"]) == pytest.approx(90.0)

        # B.08 is freshly derived from the CURRENT drivers, exactly once.
        expected_power_y1 = _expected_power_y1(20.0, 0.55, 1.30, 90.0)
        assert float(snap["opex_power_expenses_y1_keur"]) == pytest.approx(expected_power_y1)
        non_power = sum(r.amount_keur for r in rows_after_reset)
        assert float(snap["opex_y1_keur"]) == pytest.approx(non_power + expected_power_y1)

        # Runtime OPEX equals the snapshot authority.
        from app.input_adapter import build_projectinputs_from_snapshot

        pi = build_projectinputs_from_snapshot(snap)
        assert _b08_item(pi).step_changes[0] == (1, pytest.approx(expected_power_y1))
        runtime_opex_y1 = sum(i.y1_amount_keur for i in pi.opex)
        assert runtime_opex_y1 == pytest.approx(float(snap["opex_y1_keur"]))

        # Workbook reload consistency.
        reloaded = client.get(f"/v2/workbook?project={record.project_code}", cookies=cookies)
        assert reloaded.status_code == 200
        import re as _re

        assert _re.search(r'value="90(\.0+)?"', reloaded.text)


# ─────────────────────────────────────────────────────────────────────────────
# E: availability is not an economic revenue driver
# ─────────────────────────────────────────────────────────────────────────────

class TestAvailabilitySemantics:
    def test_availability_never_changes_runtime_revenue(self, seeded_db):
        from app.input_adapter import build_projectinputs_from_snapshot
        from app.persistence.projects_repository import _compute_baseline_snapshot

        base = dict(_compute_baseline_snapshot("Data Center", _dc_key()))
        neutral = build_projectinputs_from_snapshot(dict(base))
        assert neutral.technical.plant_availability == pytest.approx(1.0)
        assert neutral.technical.combined_availability == pytest.approx(1.0)

        # A user-entered availability percentage cannot silently reduce revenue.
        tilted = dict(base)
        tilted["dc_availability"] = "60"
        tilted_pi = build_projectinputs_from_snapshot(tilted)
        assert tilted_pi.technical.plant_availability == pytest.approx(1.0)
        assert tilted_pi.revenue.market_prices_curve == neutral.revenue.market_prices_curve

        from finco_core.engine.period_engine import PeriodEngine
        from finco_core.revenue.generation import full_revenue_schedule

        def _y1(pi):
            schedule = full_revenue_schedule(
                pi,
                PeriodEngine(
                    pi.info.financial_close,
                    pi.info.construction_months,
                    pi.info.horizon_years,
                    pi.revenue.ppa_term_years,
                ),
            )
            return sum(v for v in schedule.values() if v > 0 and 4 <= sorted(schedule).index(
                next(i for i, v in schedule.items() if v > 0)) <= 5)

        # Compare full schedules instead: identical curves → identical revenue.
        s1 = full_revenue_schedule(
            neutral,
            PeriodEngine(neutral.info.financial_close, neutral.info.construction_months,
                         neutral.info.horizon_years, neutral.revenue.ppa_term_years),
        )
        s2 = full_revenue_schedule(
            tilted_pi,
            PeriodEngine(tilted_pi.info.financial_close, tilted_pi.info.construction_months,
                         tilted_pi.info.horizon_years, tilted_pi.revenue.ppa_term_years),
        )
        assert s1 == s2

    def test_availability_field_is_display_only(self):
        from app.workbook.registry import WORKBOOK

        spec = WORKBOOK.field("revenue.data_center.availability")
        assert spec.editable is False
        assert spec.binding_status.value == "DISPLAY_ONLY"
        assert spec.min_value == 100 and spec.max_value == 100

    def test_revenue_bridge_and_runtime_share_authority(self):
        """The published reconciliation math equals the runtime curve math."""
        from app.data_center_authority import (
            GENERIC_DATA_CENTER_REFERENCE_DRIVERS as d,
            core_capacity_revenue_keur,
            equivalent_market_price_eur_mwh,
        )
        from app.project_factories import create_generic_data_center_reference

        pi = create_generic_data_center_reference()
        # Bridge: IT MW × 1,000 × 12 × price × occupancy (stabilized, pre-index).
        bridge = core_capacity_revenue_keur(
            capacity_mw=20.0,
            service_price_eur_kw_month=d.service_price_eur_kw_month,
            occupancy=d.stabilized_occupancy,
        )
        # Runtime curve entry for year 3 (stabilized, indexation y-1=2).
        curve_y3 = equivalent_market_price_eur_mwh(
            service_price_eur_kw_month=d.service_price_eur_kw_month,
            occupancy=d.stabilized_occupancy,
        ) * (1.0 + d.revenue_escalation) ** 2
        runtime_y3 = 20.0 * 8_760.0 * curve_y3 / 1_000.0
        assert runtime_y3 == pytest.approx(bridge * (1.0 + d.revenue_escalation) ** 2)
        # Availability nowhere in either side: combined availability is 1.0.
        assert pi.technical.combined_availability == pytest.approx(1.0)
