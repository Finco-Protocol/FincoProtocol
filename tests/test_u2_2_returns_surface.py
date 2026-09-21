"""U2.2 — canonical Returns / Sponsor / Distribution V2 surface."""
from __future__ import annotations

from dataclasses import replace
import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import uuid

import pytest

from app.v2.returns_projection import NOT_AVAILABLE, build_returns_projection
from app.workbook.runtime_result import RuntimeResult


def _rr(*, project_irr=0.0759, equity_irr=0.1025, sponsor=True, distribution=True):
    sponsor_payload = None
    if sponsor:
        sponsor_payload = {
            "periods": [{
                "period": 1,
                "date": "2028-06-30",
                "share_capital_contribution_keur": 0.0,
                "share_premium_contribution_keur": 1250.0,
                "other_committed_equity_contribution_keur": None,
                "additional_equity_contribution_keur": 0.0,
                "shl_cash_interest_receipt_keur": 60.0,
                "shl_principal_receipt_keur": 100.0,
                "legal_equity_distribution_keur": 250.0,
            }],
            "summary": {
                "total_legal_equity_contributed_keur": 1250.0,
                "total_shl_cash_contributed_keur": 500.0,
                "total_legal_equity_distributions_keur": 250.0,
                "total_sponsor_moic": 1.23,
            },
            "source": "CovenantGatedWaterfallResult (clean G2C production authority)",
        }
    distribution_payload = None
    if distribution:
        distribution_payload = {
            "periods": [{
                "period": 1,
                "date": "2028-06-30",
                "distribution_keur": 250.0,
                "cum_distribution_keur": 250.0,
                "lockup_active": False,
                "cf_after_reserves_keur": 250.0,
                "dsra_balance_keur": 0.0,
                "dsra_contribution_keur": None,
                "mra_balance_keur": 0.0,
                "mra_contribution_keur": 0.0,
            }],
            "summary": {"distribution_source": "CovenantGatedWaterfallResult"},
        }
    return RuntimeResult(
        snapshot_id="run-1",
        ran_at="2026-09-21T10:30:00+00:00",
        origin="saved_state",
        runtime_summary={"project_irr": project_irr, "equity_irr": equity_irr},
        financial_statements=None,
        debt_schedule=None,
        tax_schedule=None,
        distribution_schedule=distribution_payload,
        sponsor_schedule=sponsor_payload,
    )


def _ws(*, dirty=False, current="Base", last_name="Downside", last_id="sc-down"):
    return SimpleNamespace(
        dirty=dirty,
        active_scenario_name=current,
        last_runtime_scenario_id=last_id,
        last_runtime_identity={"scenario_name": last_name},
    )


def _render(projection, *, editable=True):
    from app.v2.router import _templates
    return _templates.get_template("partials/sheet_returns.html").render({
        "returns": projection,
        "project_editable": editable,
        "project_code": "generic_solar_reference",
    })


def test_returns_tab_exists_and_is_reachable():
    html = Path("app/templates/v2/workbook.html").read_text(encoding="utf-8")
    assert 'id="tab-returns"' in html
    assert 'aria-controls="panel-returns"' in html
    assert 'id="panel-returns"' in html
    assert 'partials/sheet_returns.html' in html


def test_no_run_is_explicit_and_does_not_fabricate_zero():
    projection = build_returns_projection(None, _ws())
    html = _render(projection)
    assert projection.state == "NOT_RUN"
    assert "Run the model to generate sponsor and distribution results." in html
    assert "0.00%" not in html
    assert "0 kEUR" not in html


def test_project_and_equity_irr_are_persisted_last_run_values():
    projection = build_returns_projection(_rr(), _ws())
    assert projection.metrics[0].value == 0.0759
    assert projection.metrics[0].display == "7.59%"
    assert projection.metrics[1].value == 0.1025
    assert projection.metrics[1].display == "10.25%"


def test_sponsor_and_distribution_rows_are_passed_through_from_persistence():
    projection = build_returns_projection(_rr(), _ws())
    assert projection.sponsor_rows[0]["shl_principal_receipt_keur"] == 100.0
    assert projection.sponsor_rows[0]["legal_equity_distribution_keur"] == 250.0
    assert projection.distribution_rows[0]["cf_after_reserves_keur"] == 250.0
    assert projection.distribution_rows[0]["lockup_active"] is False


def test_genuine_zero_is_visible_while_missing_is_unavailable():
    projection = build_returns_projection(_rr(project_irr=0.0, equity_irr=None), _ws())
    html = _render(projection)
    assert projection.metrics[0].display == "0.00%"
    assert projection.metrics[1].display == NOT_AVAILABLE
    assert ">0<" in html  # persisted zero schedule cells
    assert "NOT AVAILABLE" in html
    assert "other_committed_equity_contribution_keur" not in html


def test_dirty_working_keeps_last_run_values_and_marks_stale():
    rr = _rr(project_irr=0.0759)
    clean = build_returns_projection(rr, _ws(dirty=False))
    stale = build_returns_projection(rr, _ws(dirty=True))
    assert clean.metrics == stale.metrics
    assert clean.state == "CLEAN"
    assert stale.state == "STALE"
    assert "Working changes pending" in _render(stale)


def test_last_run_scenario_is_independent_of_working_scenario():
    projection = build_returns_projection(
        _rr(), _ws(current="Base", last_name="Downside", last_id="sc-down")
    )
    assert projection.scenario_name == "Downside"
    html = _render(projection)
    assert "Scenario: <strong" in html
    assert ">Downside</strong>" in html


def test_missing_last_run_scenario_name_falls_back_without_using_working_name():
    projection = build_returns_projection(
        _rr(), _ws(current="Upside", last_name="", last_id="sc-42")
    )
    assert projection.scenario_name == "Scenario ID: sc-42"
    assert projection.scenario_name != "Upside"


def test_rerun_replaces_projection_only_when_new_runtime_is_committed():
    ws = _ws(dirty=True)
    run_a = _rr(project_irr=0.05, equity_irr=0.07)
    before_rerun = build_returns_projection(run_a, ws)
    assert before_rerun.metrics[1].value == 0.07
    run_b = _rr(project_irr=0.08, equity_irr=0.11)
    after_rerun = build_returns_projection(run_b, _ws(dirty=False))
    assert after_rerun.metrics[1].value == 0.11
    assert before_rerun.metrics[1].value != after_rerun.metrics[1].value


def test_reference_returns_is_read_only_and_preserves_working_copy_cta():
    html = _render(build_returns_projection(_rr(), _ws()), editable=False)
    assert 'data-testid="returns-reference-notice"' in html
    assert "Returns are read-only" in html
    assert "Create working copy" in html
    assert "<input" not in html
    assert "<form" not in html


def test_absent_schedule_is_unavailable_not_zero():
    projection = build_returns_projection(_rr(sponsor=False, distribution=False), _ws())
    html = _render(projection)
    assert not projection.sponsor_available
    assert not projection.distribution_available
    assert "Sponsor schedule NOT AVAILABLE" in html
    assert "Distribution schedule NOT AVAILABLE" in html


def test_sponsor_net_cash_flow_is_not_derived():
    projection = build_returns_projection(_rr(), _ws())
    net = next(m for m in projection.metrics if m.key == "sponsor_net_cash_flow")
    assert net.value is None
    assert net.display == NOT_AVAILABLE
    assert "Not persisted" in net.source


def test_viewing_returns_calls_no_financial_engine():
    with (
        patch("app.services.production_waterfall_seam.execute_production_waterfall",
              side_effect=AssertionError("engine called")) as waterfall,
        patch("app.services.production_financial_authority.run_clean_production",
              side_effect=AssertionError("engine called")) as clean,
        patch("app.api.project_runner.run_project",
              side_effect=AssertionError("engine called")) as project,
    ):
        html = _render(build_returns_projection(_rr(), _ws()))
    assert "7.59%" in html
    waterfall.assert_not_called()
    clean.assert_not_called()
    project.assert_not_called()


def test_real_canonical_tariff_change_changes_equity_irr():
    """Causal proof uses the real canonical model; UI still only reads outputs."""
    from app.api.project_runner import run_project
    from app.project_factories import create_generic_solar_reference

    inputs_a = create_generic_solar_reference()
    inputs_b = replace(
        inputs_a,
        revenue=replace(
            inputs_a.revenue,
            ppa_base_tariff=inputs_a.revenue.ppa_base_tariff * 1.10,
        ),
    )
    result_a = run_project("Solar", "Base", project_inputs_override=inputs_a)
    result_b = run_project("Solar", "Base", project_inputs_override=inputs_b)
    assert result_a["kpis"]["equity_irr"] != result_b["kpis"]["equity_irr"]


def test_returns_uses_existing_workbook_access_boundary():
    source = Path("app/v2/router.py").read_text(encoding="utf-8")
    access = source.index("resolve_accessible_project(user.user_id, project)")
    workspace = source.index("get_workspace_state(user_id=workspace_owner", access)
    projection = source.index("context.update(_build_returns_ctx", workspace)
    assert access < workspace < projection


def test_workbook_route_renders_returns_and_preserves_cross_user_isolation():
    import main_web
    from app.auth import COOKIE_NAME, create_session_token
    from app.persistence.db import get_connection
    from app.persistence.repository import create_project_record
    from starlette.testclient import TestClient

    owner = "u22owner_" + uuid.uuid4().hex[:10]
    intruder = "u22other_" + uuid.uuid4().hex[:10]
    code = "u22_" + uuid.uuid4().hex[:10]
    snapshot = {
        "active_project": code,
        "project_name": "U2.2 Returns Route",
        "project_type": "Solar",
        "project_origin": "user_created",
        "country_market": "HR",
        "scenario": "Base",
        "capacity_mw": 50.0,
        "cod_date": "2028-01-01",
        "construction_months": 12,
        "horizon_years": 25,
        "tariff_eur_mwh": 60.0,
        "ppa_term_years": 10,
        "p50_hours": 1500.0,
        "opex_y1_keur": 500.0,
        "total_capex_keur": 45000.0,
        "gearing_pct": 65.0,
        "interest_rate_pct": 6.0,
        "tenor_years": 15,
        "target_dscr": 1.3,
    }
    record = create_project_record(
        user_id=owner,
        project_code=code,
        project_name="U2.2 Returns Route",
        project_type="Solar",
        project_origin="user_created",
        template_source="",
        baseline_snapshot=snapshot,
    )
    from app.persistence.workspace_repository import save_workspace_state
    save_workspace_state(
        user_id=owner,
        project_id=record.project_id,
        project_code=code,
        draft_snapshot=snapshot,
        saved_snapshot=snapshot,
    )
    try:
        with TestClient(main_web.app, raise_server_exceptions=False) as client:
            owner_token = create_session_token(user_id=owner, username="u22-owner")
            with (
                patch("app.services.production_waterfall_seam.execute_production_waterfall",
                      side_effect=AssertionError("engine called while viewing Returns")) as waterfall,
                patch("app.services.production_financial_authority.run_clean_production",
                      side_effect=AssertionError("engine called while viewing Returns")) as clean,
                patch("app.api.project_runner.run_project",
                      side_effect=AssertionError("engine called while viewing Returns")) as project,
            ):
                owner_response = client.get(
                    f"/v2/workbook?project={code}",
                    headers={"Cookie": f"{COOKIE_NAME}={owner_token}"},
                )
            assert owner_response.status_code == 200
            assert 'id="tab-returns"' in owner_response.text
            assert 'data-testid="returns-no-run"' in owner_response.text
            waterfall.assert_not_called()
            clean.assert_not_called()
            project.assert_not_called()

            intruder_token = create_session_token(user_id=intruder, username="u22-other")
            denied = client.get(
                f"/v2/workbook?project={code}",
                headers={"Cookie": f"{COOKIE_NAME}={intruder_token}"},
                follow_redirects=False,
            )
            assert denied.status_code == 302
            assert denied.headers["location"].startswith("/library")
    finally:
        conn = get_connection()
        conn.execute("DELETE FROM workspace_states WHERE user_id=?", (owner,))
        conn.execute("DELETE FROM projects WHERE user_id=?", (owner,))
        conn.commit()
        conn.close()


def test_returns_browser_acceptance_no_run_current_and_stale():
    playwright = pytest.importorskip("playwright.sync_api")
    css = Path("static/css/workbook_v2.css").read_text(encoding="utf-8")
    states = {
        "no-run": build_returns_projection(None, _ws()),
        "current": build_returns_projection(_rr(), _ws(dirty=False)),
        "stale": build_returns_projection(_rr(), _ws(dirty=True)),
    }
    manager = playwright.sync_playwright()
    try:
        pw = manager.start()
    except Exception as exc:
        pytest.skip(f"Playwright process unavailable: {exc}")
    try:
        try:
            browser = pw.chromium.launch(args=["--no-sandbox"])
        except Exception as exc:
            pytest.skip(f"Chromium unavailable: {exc}")
        try:
            for label, projection in states.items():
                for width in (1280, 390):
                    page = browser.new_page(viewport={"width": width, "height": 900})
                    page.set_content(
                        "<!doctype html><html><head><style>"
                        + css
                        + "</style></head><body>"
                        + _render(projection)
                        + "</body></html>"
                    )
                    assert page.locator("#v2-sheet-returns").count() == 1
                    assert page.evaluate(
                        "document.documentElement.scrollWidth <= window.innerWidth"
                    )
                    if label == "no-run":
                        assert page.locator('[data-testid="returns-no-run"]').is_visible()
                    else:
                        assert page.locator('[data-testid="returns-sponsor-table"]').is_visible()
                        assert page.locator('[data-testid="returns-distribution-table"]').is_visible()
                    screenshot_dir = os.getenv("FINCO_RETURNS_SCREENSHOT_DIR")
                    if screenshot_dir:
                        target = Path(screenshot_dir)
                        target.mkdir(parents=True, exist_ok=True)
                        page.screenshot(
                            path=str(target / f"returns-{label}-{width}.png"),
                            full_page=True,
                        )
                    page.close()
        finally:
            browser.close()
    finally:
        pw.stop()


# ---------------------------------------------------------------------------
# F03 — scenario identity fails closed; never falls back to "Base Case"
# ---------------------------------------------------------------------------

def test_f03_both_identity_sources_absent_returns_not_available():
    ws = SimpleNamespace(
        dirty=False,
        active_scenario_name="Base Case",
        last_runtime_scenario_id="",
        last_runtime_identity={},
    )
    projection = build_returns_projection(_rr(), ws)
    assert projection.scenario_name == NOT_AVAILABLE
    assert projection.scenario_name != "Base Case"


def test_f03_identity_scenario_name_none_and_id_none_returns_not_available():
    ws = SimpleNamespace(
        dirty=False,
        active_scenario_name="Upside",
        last_runtime_scenario_id=None,
        last_runtime_identity={"scenario_name": None},
    )
    projection = build_returns_projection(_rr(), ws)
    assert projection.scenario_name == NOT_AVAILABLE
    assert projection.scenario_name != "Upside"


def test_f03_working_scenario_never_substituted_for_last_run_identity():
    ws = SimpleNamespace(
        dirty=False,
        active_scenario_name="Downside",
        last_runtime_scenario_id="",
        last_runtime_identity={"scenario_name": ""},
    )
    projection = build_returns_projection(_rr(), ws)
    assert projection.scenario_name != "Downside"
    assert projection.scenario_name == NOT_AVAILABLE


def test_f03_valid_persisted_name_still_returned():
    projection = build_returns_projection(
        _rr(), _ws(current="Upside", last_name="Base Case", last_id="sc-base")
    )
    assert projection.scenario_name == "Base Case"


def test_f03_scenario_id_fallback_still_returned():
    projection = build_returns_projection(
        _rr(), _ws(current="Upside", last_name="", last_id="sc-99")
    )
    assert projection.scenario_name == "Scenario ID: sc-99"


# ---------------------------------------------------------------------------
# F02 — schedule money() macro rejects booleans; genuine zero renders as zero
# ---------------------------------------------------------------------------

def _rr_with_row(row_values: dict):
    """Build a RuntimeResult with a single sponsor period using the given values."""
    sponsor_payload = {
        "periods": [{"period": 1, "date": "2028-06-30", **row_values}],
        "summary": {
            "total_legal_equity_contributed_keur": None,
            "total_shl_cash_contributed_keur": None,
            "total_legal_equity_distributions_keur": None,
            "total_sponsor_moic": None,
        },
        "source": "test",
    }
    return RuntimeResult(
        snapshot_id="run-f02",
        ran_at="2026-09-21T10:30:00+00:00",
        origin="saved_state",
        runtime_summary={},
        financial_statements=None,
        debt_schedule=None,
        tax_schedule=None,
        distribution_schedule=None,
        sponsor_schedule=sponsor_payload,
    )


def _render_sponsor_cell(value) -> str:
    projection = build_returns_projection(_rr_with_row({"share_capital_contribution_keur": value}), _ws())
    return _render(projection)


def test_f02_genuine_zero_int_renders_as_zero():
    html = _render_sponsor_cell(0)
    assert ">0<" in html


def test_f02_genuine_zero_float_renders_as_zero():
    html = _render_sponsor_cell(0.0)
    assert ">0<" in html


def test_f02_positive_number_renders():
    html = _render_sponsor_cell(1250.0)
    assert "1,250" in html


def test_f02_negative_number_renders_with_negative_class():
    html = _render_sponsor_cell(-500.0)
    assert "v2-returns-negative" in html
    assert "500" in html


def test_f02_false_renders_as_em_dash():
    html = _render_sponsor_cell(False)
    assert ">—<" in html
    assert ">0<" not in html


def test_f02_true_renders_as_em_dash():
    html = _render_sponsor_cell(True)
    assert ">—<" in html
    # money(True) must not render as ">1<" in a numeric cell (v2-num column)
    assert 'class="v2-num"><span class="">1</span>' not in html
    assert 'v2-num"><span>1</span>' not in html


def test_f02_none_renders_as_em_dash():
    html = _render_sponsor_cell(None)
    assert ">—<" in html


def test_f02_string_renders_as_em_dash():
    html = _render_sponsor_cell("500")
    assert ">—<" in html
    assert ">500<" not in html


def test_f02_numeric_looking_string_renders_as_em_dash():
    html = _render_sponsor_cell("0")
    assert ">—<" in html
    assert ">0<" not in html


def test_f02_lockup_active_boolean_rendering_unaffected():
    """The dedicated lockup_active column uses sameas comparison not money(), unaffected."""
    distribution_payload = {
        "periods": [
            {"period": 1, "date": "2028-06-30", "lockup_active": True,
             "distribution_keur": 100.0, "cum_distribution_keur": 100.0,
             "cf_after_reserves_keur": 100.0, "dsra_balance_keur": 0.0,
             "dsra_contribution_keur": 0.0, "mra_balance_keur": 0.0,
             "mra_contribution_keur": 0.0},
            {"period": 2, "date": "2029-06-30", "lockup_active": False,
             "distribution_keur": 200.0, "cum_distribution_keur": 300.0,
             "cf_after_reserves_keur": 200.0, "dsra_balance_keur": 0.0,
             "dsra_contribution_keur": 0.0, "mra_balance_keur": 0.0,
             "mra_contribution_keur": 0.0},
        ],
        "summary": {"distribution_source": "test"},
    }
    rr = RuntimeResult(
        snapshot_id="run-lockup",
        ran_at="2026-09-21T10:30:00+00:00",
        origin="saved_state",
        runtime_summary={},
        financial_statements=None,
        debt_schedule=None,
        tax_schedule=None,
        distribution_schedule=distribution_payload,
        sponsor_schedule=None,
    )
    html = _render(build_returns_projection(rr, _ws()))
    assert "Active" in html
    assert "Open" in html


# ---------------------------------------------------------------------------
# F01 — scenario-select OOB-refreshes #v2-sheet-returns
# ---------------------------------------------------------------------------

def test_f01_scenario_select_oob_replaces_returns_fragment():
    """True lifecycle regression: Scenario A has a committed run; selecting
    Scenario B must replace #v2-sheet-returns with the no-run state (not
    show Scenario A economics). Engine must never be called.

    Failure mode on the pre-Correction-A codebase: scenario-select response
    does not contain an OOB replacement for #v2-sheet-returns, so Scenario A
    committed economics remain in the browser even though the workspace now
    has Scenario B selected."""
    import uuid
    from datetime import datetime, timezone
    import main_web
    from app.auth import COOKIE_NAME, create_session_token
    from app.persistence.db import get_connection
    from app.persistence.repository import create_project_record
    from app.persistence.scenarios_repository import add_scenario, get_or_create_base_case_scenario
    from app.persistence.workspace_repository import (
        save_workspace_state, v2_atomic_run_commit,
    )
    from app.workbook.registry import WORKBOOK
    from app.workbook.workbook_identity import assemble_consistent_for_get
    from starlette.testclient import TestClient

    # Unique unmistakable equity IRR for Scenario A — chosen so formatted
    # display "13.57%" will not appear in normal boilerplate HTML.
    SC_A_EQUITY_IRR = 0.1357

    owner = "u22f01_" + uuid.uuid4().hex[:10]
    code = "f01_" + uuid.uuid4().hex[:8]
    snapshot = {
        "active_project": code,
        "project_name": "F01 Scenario Select Returns",
        "project_type": "Solar",
        "project_origin": "user_created",
        "country_market": "HR",
        "scenario": "Base",
        "capacity_mw": 50.0,
        "cod_date": "2028-01-01",
        "construction_months": 12,
        "horizon_years": 25,
        "tariff_eur_mwh": 60.0,
        "ppa_term_years": 10,
        "p50_hours": 1500.0,
        "opex_y1_keur": 500.0,
        "total_capex_keur": 45000.0,
        "gearing_pct": 65.0,
        "interest_rate_pct": 6.0,
        "tenor_years": 15,
        "target_dscr": 1.3,
    }
    conn = get_connection()
    try:
        # ── Step 1-2: project + workspace + Base Case scenario ──────────────── #
        record = create_project_record(
            user_id=owner,
            project_code=code,
            project_name="F01 Scenario Select Returns",
            project_type="Solar",
            project_origin="user_created",
            template_source="",
            baseline_snapshot=snapshot,
        )
        save_workspace_state(
            user_id=owner,
            project_id=record.project_id,
            project_code=code,
            draft_snapshot=snapshot,
            saved_snapshot=snapshot,
        )
        base_sc = get_or_create_base_case_scenario(
            user_id=owner, project_id=record.project_id, project_code=code,
            project_name="F01 Scenario Select Returns", project_type="Solar",
            source_project_template="", base_input_set=snapshot, governance_state={},
        )

        # ── Step 3: commit real RuntimeResult for Scenario A (Base Case) ───── #
        # Use the canonical v2_atomic_run_commit path, exactly as the Run flow
        # does. Derive the composite hash first so the CAS check passes.
        identity = assemble_consistent_for_get(
            user_id=owner,
            project_id=record.project_id,
            workbook_version=WORKBOOK.version,
        )
        sponsor_schedule_a = {
            "periods": [{
                "period": 1,
                "date": "2028-06-30",
                "share_capital_contribution_keur": 0.0,
                "share_premium_contribution_keur": 1500.0,
                "other_committed_equity_contribution_keur": None,
                "additional_equity_contribution_keur": 0.0,
                "shl_cash_interest_receipt_keur": 75.0,
                "shl_principal_receipt_keur": 150.0,
                "legal_equity_distribution_keur": 300.0,
            }],
            "summary": {
                "total_legal_equity_contributed_keur": 1500.0,
                "total_shl_cash_contributed_keur": 600.0,
                "total_legal_equity_distributions_keur": 300.0,
                "total_sponsor_moic": 1.45,
            },
            "source": "CovenantGatedWaterfallResult (clean G2C production authority)",
        }
        v2_atomic_run_commit(
            user_id=owner,
            project_id=record.project_id,
            project_code=code,
            expected_composite_hash=identity.composite_hash,
            runtime_snapshot_id="snap-sc-a-" + uuid.uuid4().hex[:8],
            runtime_origin="v2_run",
            runtime_summary={
                "project_irr": 0.0812,
                "equity_irr": SC_A_EQUITY_IRR,
            },
            financial_statements=None,
            debt_schedule=None,
            tax_schedule=None,
            distribution_schedule=None,
            sponsor_schedule=sponsor_schedule_a,
            active_scenario_id=base_sc.scenario_id,
            active_scenario_name="Base Case",
            last_runtime_scenario_id=base_sc.scenario_id,
            ran_at=datetime.now(timezone.utc),
        )

        # ── Step 4: prove Scenario A Returns are visible before switching ───── #
        from app.persistence.workspace_repository import get_workspace_state
        from app.workbook.service import WorkbookService
        ws_after_run = get_workspace_state(user_id=owner, project_id=record.project_id)
        assert ws_after_run is not None
        rr_a = WorkbookService.get_runtime_result(ws_after_run)
        assert rr_a is not None, "RuntimeResult must be present after v2_atomic_run_commit"
        from app.v2.returns_projection import build_returns_projection
        proj_a = build_returns_projection(rr_a, ws_after_run)
        equity_irr_metric = next(m for m in proj_a.metrics if m.key == "equity_irr")
        assert abs(equity_irr_metric.value - SC_A_EQUITY_IRR) < 1e-9, (
            f"Scenario A equity IRR must be persisted as {SC_A_EQUITY_IRR}, got {equity_irr_metric.value}"
        )
        # Unmistakable display string — must appear before switch, must vanish after
        SC_A_IRR_DISPLAY = "13.57%"
        assert SC_A_IRR_DISPLAY in _render(proj_a), (
            f"Scenario A Returns HTML must contain '{SC_A_IRR_DISPLAY}' before switch"
        )

        # ── Step 5: create Scenario B (not run) ─────────────────────────────── #
        sc_b = add_scenario(
            user_id=owner,
            project_id=record.project_id,
            project_code=code,
            scenario_name="Scenario B",
            parent_scenario_id=base_sc.scenario_id,
            base_input_set=snapshot,
        )

        # ── Steps 6-9: POST scenario-select, assert OOB + no A values ─────── #
        with TestClient(main_web.app, raise_server_exceptions=False) as client:
            token = create_session_token(user_id=owner, username="u22-f01")
            with (
                patch("app.services.production_waterfall_seam.execute_production_waterfall",
                      side_effect=AssertionError("engine called during scenario select")) as waterfall,
                patch("app.services.production_financial_authority.run_clean_production",
                      side_effect=AssertionError("engine called during scenario select")) as clean,
                patch("app.api.project_runner.run_project",
                      side_effect=AssertionError("engine called during scenario select")) as project_runner,
            ):
                resp = client.post(
                    "/v2/workbook/scenarios/select",
                    data={"project": code, "scenario_id": sc_b.scenario_id},
                    headers={
                        "Cookie": f"{COOKIE_NAME}={token}",
                        "HX-Request": "true",
                    },
                )
            assert resp.status_code == 200, resp.text
            html = resp.text

            # OOB target must be present
            assert 'id="v2-sheet-returns"' in html, "Returns OOB fragment missing from response"
            assert 'hx-swap-oob="true"' in html, "hx-swap-oob attribute missing"

            # Must show no-run state for Scenario B
            assert 'data-testid="returns-no-run"' in html, (
                "Returns fragment must show no-run state after switching to unrun Scenario B"
            )

            # Must NOT contain Scenario A's unique committed equity IRR
            assert SC_A_IRR_DISPLAY not in html, (
                f"Scenario A equity IRR '{SC_A_IRR_DISPLAY}' must not appear after selecting Scenario B"
            )

            # Engine must never be called (Returns is pure presentation)
            waterfall.assert_not_called()
            clean.assert_not_called()
            project_runner.assert_not_called()
    finally:
        conn.execute("DELETE FROM scenarios WHERE user_id=?", (owner,))
        conn.execute("DELETE FROM workspace_states WHERE user_id=?", (owner,))
        conn.execute("DELETE FROM projects WHERE user_id=?", (owner,))
        conn.commit()
        conn.close()
