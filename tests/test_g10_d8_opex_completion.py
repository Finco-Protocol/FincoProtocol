"""G10/D8 OPEX completion (Draft) — bounded oracle set over synthetic data only.

Tiers (per references/g10_d8/G10_ORACLE_SPEC.md, corrected by NUMERIC_ERRATA.md):
* Kernel   — ``finco_core.opex.projections.opex_item_amount_at_year`` against hand-computed decimals (K1–K4, K6);
* T2       — full-year annual item sums over the canonical factory inputs (solar 380.0 / Y5 / Y20; DC fixed six items 9700);
* T3       — the new read-only Last-Run adapter (``GET /v2/model-react/opex-run-projection``): pass-through of the
             committed immutable Run's own P&L ``operating_expenses_keur`` periods, with identity/freshness labels,
             NOT_RUN when no Run exists (never zeros), and a periodized-evidence equality check against the
             persisted history row (the engine equality itself is owned by the run pipeline's own tests);
* D8       — source pins: the false "project's OPEX escalation" copy is gone; the truthful per-item-rate copy is in.

No engine change; no draft-value reuse; one canonical Run per solar fixture (bounded executor, thread mode).
"""
from __future__ import annotations

import math
from pathlib import Path

import pytest

from finco_core.inputs import OpexItem
from finco_core.opex.projections import opex_item_amount_at_year
from tests.test_model_react_wf2_projections_v1 import OWNER, env  # noqa: F401  (shared real-app fixture)

ROOT = Path(__file__).resolve().parents[1]


def _item(y1: float, inflation: float, steps=()) -> OpexItem:
    return OpexItem(name="synthetic", y1_amount_keur=y1, annual_inflation=inflation, step_changes=tuple(steps), percentage_of_opex=None)


# ── kernel cases (K1–K4, K6; K5 needs the opex_year aggregation and is covered by the T2 sums below) ─────────

def test_k1_two_percent_escallation_matches_exact_decimal():
    item = _item(100.0, 0.02)
    assert opex_item_amount_at_year(item, 1) == pytest.approx(100.0, abs=1e-9)
    assert opex_item_amount_at_year(item, 2) == pytest.approx(102.0, abs=1e-9)
    assert opex_item_amount_at_year(item, 3) == pytest.approx(104.04, abs=1e-9)
    assert opex_item_amount_at_year(item, 5) == pytest.approx(108.243216, abs=1e-9)
    assert opex_item_amount_at_year(item, 10) == pytest.approx(119.509256862231, abs=1e-9)  # NUMERIC_ERRATA E1 #1


def test_k2_zero_escalation_is_flat_including_the_new_line_default():
    item = _item(100.0, 0.0)
    assert all(opex_item_amount_at_year(item, t) == pytest.approx(100.0, abs=1e-12) for t in range(1, 21))


def test_k3_step_is_a_new_sustained_base_not_a_one_year_override():
    item = _item(100.0, 0.02, steps=[(5, 120.0)])
    assert opex_item_amount_at_year(item, 4) == pytest.approx(106.1208, abs=1e-9)
    assert opex_item_amount_at_year(item, 5) == pytest.approx(120.0, abs=1e-9)
    assert opex_item_amount_at_year(item, 6) == pytest.approx(122.4, abs=1e-9)
    assert opex_item_amount_at_year(item, 10) == pytest.approx(132.489696384, abs=1e-9)  # E1 #2


def test_k4_negative_rates_never_go_below_zero():
    item = _item(100.0, -0.5)
    assert [opex_item_amount_at_year(item, t) for t in (1, 2, 3)] == pytest.approx([100.0, 50.0, 25.0], abs=1e-9)
    assert all(opex_item_amount_at_year(item, t) >= 0.0 for t in range(1, 40))


def test_k6_construction_and_nonpositive_years_are_zero():
    item = _item(100.0, 0.02)
    assert opex_item_amount_at_year(item, 0) == 0.0
    assert opex_item_amount_at_year(item, -3) == 0.0


# ── T2: full-year annual item sums over the canonical factory inputs (T1 qualification: full-year figures) ──

def _factory_items(kind):
    from app import project_factories as F
    factory = {
        "solar": F.create_generic_solar_reference,
        "wind": F.create_generic_wind_reference,
        "data_center": F.create_generic_data_center_reference,
    }[kind]
    return factory().opex


def test_t2_solar_all_in_full_year_sums_match_the_corrected_oracle():
    items = _factory_items("solar")
    assert round(sum(i.y1_amount_keur for i in items), 9) == pytest.approx(380.0, abs=1e-9)
    for t, expected in ((5, 411.324220800), (20, 553.588245560563)):  # E1 #3/#4: 380 × 1.02^(t−1)
        assert sum(opex_item_amount_at_year(i, t) for i in items) == pytest.approx(expected, abs=1e-9)


def test_t2_data_center_fixed_six_items_total_9700_excluding_driver_row():
    items = _factory_items("data_center")
    fixed = [i for i in items if i.name != "Power Expenses"]          # driver-derived row excluded (E1 #5)
    assert len(fixed) == 6
    assert round(sum(i.y1_amount_keur for i in fixed), 9) == pytest.approx(9700.0, abs=1e-9)


def test_d8_escalation_sources_have_no_project_wide_input():
    """D8 Option 1: escalation stays per-item; the factory rates are the only 'default' that exists."""
    for kind, expected in (("solar", 0.02), ("data_center", 0.02)):
        fixed = [i for i in _factory_items(kind) if i.name != "Power Expenses"]
        assert {i.annual_inflation for i in fixed} == {expected}
    dc_driver = [i for i in _factory_items("data_center") if i.name == "Power Expenses"]
    assert dc_driver and dc_driver[0].annual_inflation == 0.0          # driver-derived row: rate 0%, value from driver


# ── T3: the new read-only Last-Run adapter (dedicated default-OFF gate FINCO_G10_RUN_OPEX_PANEL) ────────────

@pytest.fixture(autouse=True)
def _g10_panel_enabled(monkeypatch):
    monkeypatch.setenv("FINCO_G10_RUN_OPEX_PANEL", "1")


def _run_projection(env, record):
    return env.client.get("/v2/model-react/opex-run-projection", params={"project": record.project_code})


def test_g10_panel_gate_is_default_off(monkeypatch, env):
    """No unintended general-release exposure: without the dedicated flag the route is a typed 404,
    even with the React surface flag on."""
    monkeypatch.delenv("FINCO_G10_RUN_OPEX_PANEL", raising=False)
    record = env.create("solar")
    response = _run_projection(env, record)
    assert response.status_code == 404
    assert response.json()["code"] == "G10_RUN_OPEX_PANEL_DISABLED"


def test_g10_session_isolation_stranger_gets_404_and_owner_data(env):
    """The latest committed history belongs to the authorized owner only; a stranger's session resolves
    no project and must not see the owner's Run evidence (typed 404, never a payload)."""
    from tests.test_model_react_wf2_projections_v1 import env as _env  # noqa: F401
    record = env.create("solar")
    from tests.test_model_react_rcm_goal_seek_v1 import run_canonical
    run_canonical(env, record.project_code)
    stranger_view = env.stranger.get("/v2/model-react/opex-run-projection", params={"project": record.project_code})
    assert stranger_view.status_code == 404, stranger_view.text[:200]
    assert "history_id" not in stranger_view.text
    owner_view = _run_projection(env, record)
    assert owner_view.status_code == 200 and owner_view.json()["run"]["history_id"]


def test_g10_freshness_follows_the_authoritative_resolver_and_labels_the_displayed_row(env):
    """CURRENT right after the Run; STALE after a working-copy input change (authoritative resolver);
    the freshness label is bound to the displayed history row's identity, never fabricated CURRENT."""
    from tests.test_model_react_rcm_goal_seek_v1 import run_canonical
    from tests.fin_v2_3_support import config_json
    from app.workbook.financial_core_config import FIELD_ID
    from app.workbook.registry import WORKBOOK
    from app.workbook.update_service import WorkbookUpdateService
    from app.persistence.workspace_repository import get_workspace_state
    record = env.create("solar")
    run_canonical(env, record.project_code)
    body = _run_projection(env, record).json()
    assert body["freshness"]["state"] == "CURRENT" and body["run"]["history_id"]
    # change a saved input through the canonical writer (valuation policy, as the NPV parity test does)
    ws = get_workspace_state(OWNER, record.project_id)
    projection = env.client.get("/v2/model-react/fields/project_setup", params={"project": record.project_code}).json()
    WorkbookUpdateService.apply_batch_draft_update(ws=ws, updates=[(FIELD_ID, config_json())], content_hash=projection["save"]["content_hash"],
                                                  workbook_version=WORKBOOK.version, expected_scenario_id=ws.active_scenario_id,
                                                  project_record=record, actor_user_id=record.user_id)
    after = _run_projection(env, record).json()
    assert after["freshness"]["state"] == "STALE"
    assert after["run"]["history_id"] == body["run"]["history_id"]   # same displayed row, honest STALE label


def test_g10_endpoint_requires_flag_session_and_project(env):
    response = env.client.get("/v2/model-react/opex-run-projection")
    assert response.status_code in (401, 404)                          # no session / flag off → typed refusal, never data
    assert env.client.get("/v2/model-react/opex-run-projection", params={"project": "nope"}).status_code == 404


def test_g10_no_run_is_not_run_never_zero(env):
    record = env.create("solar")
    response = _run_projection(env, record)
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True and body["status"] == "NOT_RUN" and body["run"] is None
    assert body["periods"] == [] and body["freshness"]["state"] == "NOT_RUN"


def test_g10_run_projection_passes_through_the_committed_run_evidence(env):
    from tests.test_model_react_rcm_goal_seek_v1 import run_canonical
    from app.persistence.run_history_repository import get_latest_history_entry
    from app.persistence.workspace_repository import get_workspace_state

    record = env.create("solar")
    run_canonical(env, record.project_code)
    response = _run_projection(env, record)
    assert response.status_code == 200, response.text[:200]
    body = response.json()
    assert body["status"] == "OK" and body["unit"] == "kEUR"
    assert body["run"] and body["run"]["history_id"] and body["run"]["runtime_snapshot_id"]
    # scenario id/name are whatever the Run recorded (a fresh working copy's first Run may legitimately
    # carry no explicit scenario selection) — shown as persisted, never guessed.
    assert body["freshness"]["state"] == "CURRENT"                     # nothing changed after the Run
    ws = get_workspace_state(OWNER, record.project_id)
    entry = get_latest_history_entry(OWNER, record.project_id)
    persisted = entry.financial_statements["pnl"]["periods"]
    assert len(body["periods"]) == len(persisted)                      # pass-through, no invention
    for shown, stored in zip(body["periods"], persisted):
        assert shown["period"] == stored["period"] and shown["date"] == stored["date"]
        assert shown["operating_expenses_keur"] == stored["operating_expenses_keur"]
    zero_periods = [p for p in body["periods"] if p["operating_expenses_keur"] == 0.0]
    assert zero_periods, "a solar Run has construction periods whose OPEX is exactly 0.0"
    operating = [p for p in body["periods"] if p["operating_expenses_keur"] and p["operating_expenses_keur"] > 0]
    assert operating, "the Run must contain operating periods with positive OPEX"
    # Full-year T2 figure is NOT equated to any period (T1 qualification); only ordering is asserted where a
    # period covers a complete operating year its value stays below the 20-year escalated all-in.
    assert all(p["operating_expenses_keur"] <= 553.588245560563 + 1e-6 for p in operating)


def test_g10_second_run_appends_and_first_evidence_is_untouched(env):
    """Positive+negative immutability oracle: the first committed row's stored P&L periods are byte/value
    identical after a second Run, the API shows the SECOND id with the second row's own periods, and the
    first row stays accessible. The first fetch is snapshotted before the second Run — never compared to itself."""
    import copy
    import json
    from tests.test_model_react_rcm_goal_seek_v1 import run_canonical
    from app.persistence.run_history_repository import get_latest_history_entry, get_run_history_entry
    record = env.create("solar")
    run_canonical(env, record.project_code)
    first_entry = get_latest_history_entry(OWNER, record.project_id)
    first = first_entry.history_id
    first_payload = _run_projection(env, record).json()
    assert first_payload["run"]["history_id"] == first
    first_stored = copy.deepcopy(first_entry.financial_statements["pnl"]["periods"])
    first_shown = copy.deepcopy(first_payload["periods"])
    projected = [{"period": p["period"], "date": p["date"], "operating_expenses_keur": p["operating_expenses_keur"]} for p in first_stored]
    assert first_shown == projected                                     # adapter showed exactly the stored row's projected fields
    run_canonical(env, record.project_code)                             # second Run (same inputs)
    second = get_latest_history_entry(OWNER, record.project_id).history_id
    assert second != first
    # negative half: the FIRST row's stored evidence must be untouched by the second commit
    first_after = get_run_history_entry(OWNER, record.project_id, first)
    assert first_after.history_id == first
    assert first_after.financial_statements["pnl"]["periods"] == first_stored
    assert json.dumps(first_after.financial_statements["pnl"]["periods"], sort_keys=True) == \
           json.dumps(first_stored, sort_keys=True)
    # positive half: the API now shows the SECOND id with the SECOND row's own periods (not the cached first)
    second_payload = _run_projection(env, record).json()
    second_stored = get_latest_history_entry(OWNER, record.project_id).financial_statements["pnl"]["periods"]
    assert second_payload["run"]["history_id"] == second
    assert second_payload["periods"] == [{"period": p["period"], "date": p["date"], "operating_expenses_keur": p["operating_expenses_keur"]} for p in second_stored]


# ── D8: source pins for the copy corrections ────────────────────────────────────────────────────────────────

def test_d8_false_project_wide_escalation_copy_is_gone_and_truthful_copy_present():
    grid = (ROOT / "frontend/src/app/editing/CostLinesGridView.tsx").read_text(encoding="utf-8")
    assert "the project's OPEX escalation" not in grid
    assert "No project-wide OPEX escalation input exists" in grid
    manager = (ROOT / "frontend/src/app/workflow/CostLineManager.tsx").read_text(encoding="utf-8")
    assert "no project-wide OPEX escalation is saved" in manager        # the pre-existing correct copy stays


def test_g10_endpoint_module_has_no_writer_surface():
    source = (ROOT / "app/v2/react_opex_run_projection.py").read_text(encoding="utf-8")
    assert '@router.get(' in source
    assert "@router.post(" not in source and "@router.put(" not in source and "@router.delete(" not in source
    registered = (ROOT / "app/v2/react_workspace_router.py").read_text(encoding="utf-8")
    assert "from app.v2.react_opex_run_projection import router as _g10_opex_run_router" in registered
    assert "router.include_router(_g10_opex_run_router)" in registered
