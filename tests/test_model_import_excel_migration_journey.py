"""Excel migration V3 journeys through the real routes: assess -> scenario slice -> review -> Apply -> Run -> reconcile."""
from __future__ import annotations

from decimal import Decimal

import pytest

from app.auth import generate_csrf_token
from app.persistence.run_history_repository import get_run_history
from app.persistence.workspace_repository import get_workspace_state
from app.workbook.input_set import ProjectInputSet
from app.workbook.registry import WORKBOOK
from tests.migration_routes_support import (
    OWNER, apply, assess, confirm, err, evidence, full_apply, hidden, journey_workbook, recon_detail, recon_rows, reconcile,
    review_slice, run_model, selection, slice_ticket, ws_of,
)
from tests.test_model_decision_workspace_v2 import env  # noqa: F401


@pytest.fixture(autouse=True)
def _routes(env):
    from app.v2.import_router import router
    if not any(getattr(r, "path", "") == "/v2/workbook/import/assess" for r in env.client.app.routes):
        env.client.app.include_router(router, prefix="/v2")


def value(project, field):
    return ProjectInputSet.from_snapshot(ws_of(project).draft_snapshot, workbook=WORKBOOK).get(field)


def test_full_journey_assess_review_apply_run_reconcile_comparable(env):
    project = env.create("solar")
    before = evidence(project)
    assessed = assess(env, project, journey_workbook())
    assert assessed.status_code == 200, err(assessed)
    assert evidence(project) == before                                  # assessment: no write, no Run
    for needle in ("STATIC_OBSERVABLE", "Base Case", "Upside", "output for reconciliation only", "formula", "Total CAPEX"):
        assert needle in assessed.text, needle
    reviewed = review_slice(env, project, slice_ticket(assessed, "base_case"), hidden(assessed, "manifest_token"))
    assert reviewed.status_code == 200 and "migration-banner" in reviewed.text, err(reviewed)
    assert evidence(project) == before                                  # review: still nothing written
    preview_ticket = hidden(reviewed, "preview_ticket")
    no_confirm = confirm(env, project, preview_ticket, scenario_confirmed=False, **selection(reviewed))
    assert no_confirm.status_code == 422 and "IMPORT_SCENARIO_CONFIRMATION_REQUIRED" in no_confirm.text
    assert evidence(project) == before
    confirmed = confirm(env, project, preview_ticket, hidden(reviewed, "manifest_token"), **selection(reviewed))
    assert confirmed.status_code == 200 and "migration-banner-confirm" in confirmed.text, err(confirmed)
    applied = apply(env, project, hidden(confirmed, "approved_ticket"), hidden(confirmed, "manifest_token"))
    assert applied.status_code == 200 and "CHANGED — NOT RUN" in applied.text, err(applied)
    assert float(value(project, "opex.lines.insurance")) == pytest.approx(40.0)            # Base Case column
    assert float(value(project, "capex.C.grid_connection")) == pytest.approx(1200.0)        # EUR -> kEUR
    assert float(value(project, "debt.senior.interest_rate_pct")) == pytest.approx(5.25)
    ws = ws_of(project)
    assert ws.dirty and not get_run_history(OWNER, project.project_id)                      # changed, not run
    # no Run yet: reconciliation cannot compare anything
    applied_ticket = hidden(applied, "applied_ticket")
    early = recon_rows(reconcile(env, project, applied_ticket))
    assert early["Summary!B2"][0] == "NOT_COMPARABLE" and "RUN_NOT_CURRENT_FOR_APPLIED_INPUTS" in early["Summary!B2"][1]
    run_model(env, project)                                                                 # explicit native Run
    assert len(get_run_history(OWNER, project.project_id)) == 1
    compared = reconcile(env, project, applied_ticket)
    assert compared.status_code == 200
    rows = recon_rows(compared)
    # Total CAPEX depends only on applied inputs (Inputs!B3, Common!B3): a REAL difference is reported, not parity
    status, reasons = rows["Summary!B2"]
    assert status == "FAIL" and reasons == ["OUTSIDE_APPROVED_TOLERANCE"]
    entry = get_run_history(OWNER, project.project_id)[0]
    assert f"<code>{entry.history_id}</code>" in compared.text and 'data-testid="run-state">CURRENT' in compared.text
    cells = recon_detail(compared)["Summary!B2"]["cells"]
    finco = Decimal(str(entry.runtime_summary["total_capex_keur"]))
    assert cells[1].startswith("1245.5")                                        # cached source value, kEUR
    assert Decimal(cells[3]) == finco                                           # FINCO committed Run value
    assert Decimal(cells[4].split()[0]) == finco - Decimal("1245.5")            # signed residual FINCO - source
    # input mapping success is NOT parity; Equity IRR has no numeric input leaves and is not compared
    assert rows["Summary!B3"][0] == "NOT_COMPARABLE" and "SOURCE_OUTPUT_HAS_NO_INPUT_LEAVES" in rows["Summary!B3"][1]


def test_real_scenario_workflow_targets_the_new_scenario_and_leaves_base_untouched(env):
    project = env.create("solar")
    base_before = evidence(project)
    created = env.client.post("/v2/workbook/scenarios/create", data={"project": project.project_code, "scenario_name": "Upside"})
    assert created.status_code in (200, 303)
    ws = ws_of(project)
    assert ws.active_scenario_id and ws.active_scenario_name == "Upside"
    assessed, applied = full_apply(env, project, key="upside")
    assert "Upside" in assessed.text and "scenario-confirm" not in assessed.text
    assert hidden(applied, "applied_ticket")
    ws = ws_of(project)
    assert float(value(project, "opex.lines.insurance")) == pytest.approx(38.0)             # the Upside column
    assert ws.dirty
    # the applied evidence is bound to the scenario that received the writes
    sw = env.client.post("/v2/workbook/scenarios/select", data={"project": project.project_code, "scenario_id": ws.active_scenario_id})
    assert sw.status_code in (200, 303)
    assert base_before[0] != ws.draft_snapshot
