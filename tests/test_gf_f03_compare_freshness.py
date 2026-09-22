"""GF-F03: Compare GET is fresh-on-read; reflects current scenario lifecycle.

Route-level regression protecting the canonical Compare authority independently
of the browser tab-loading mechanism.  No engine execution occurs from any
Compare GET.
"""
from __future__ import annotations

import uuid
from unittest.mock import patch


BASE_SC_NAME = "Base Case"


def _setup(owner: str, code: str):
    """Create a minimal project + workspace + base-case scenario."""
    import main_web
    from app.persistence.projects_repository import create_project_record
    from app.persistence.scenarios_repository import get_or_create_base_case_scenario
    from app.persistence.workspace_repository import save_workspace_state

    snapshot = main_web._project_baseline_snapshot("Solar", "generic_solar")
    snapshot.update({
        "active_project": code,
        "project_name": BASE_SC_NAME,
        "project_type": "Solar",
        "project_origin": "user_created",
        "country_market": "Synthetic Market",
        "scenario": "Base",
    })
    record = create_project_record(
        user_id=owner,
        project_code=code,
        project_name=BASE_SC_NAME,
        project_type="Solar",
        project_origin="user_created",
        template_source="generic_solar",
        baseline_snapshot=snapshot,
    )
    save_workspace_state(
        user_id=owner,
        project_id=record.project_id,
        project_code=code,
        draft_snapshot=snapshot,
        saved_snapshot=snapshot,
        dirty=False,
    )
    base_sc = get_or_create_base_case_scenario(
        user_id=owner,
        project_id=record.project_id,
        project_code=code,
        project_name=BASE_SC_NAME,
        project_type="Solar",
        source_project_template="generic_solar",
        base_input_set=snapshot,
        governance_state=None,
    )
    return record, base_sc, snapshot


def _client(owner: str):
    import main_web
    from app.auth import COOKIE_NAME, create_session_token
    from starlette.testclient import TestClient

    token = create_session_token(user_id=owner, username=owner)
    client = TestClient(main_web.app, raise_server_exceptions=False)
    client.headers.update({"Cookie": f"{COOKIE_NAME}={token}"})
    return client


def test_compare_get_includes_newly_created_scenario():
    """Creating Scenario X then GET compare shows both Base and Scenario X chips."""
    owner = "gf-f03-a-" + uuid.uuid4().hex[:8]
    code = "gf-f03-a-" + uuid.uuid4().hex[:8]
    record, base_sc, snapshot = _setup(owner, code)
    client = _client(owner)

    from app.persistence.scenarios_repository import add_scenario
    sc_x = add_scenario(
        user_id=owner,
        project_id=record.project_id,
        project_code=code,
        scenario_name="Scenario X",
        parent_scenario_id=base_sc.scenario_id,
        base_input_set=snapshot,
    )

    resp = client.get(f"/v2/workbook/scenarios/compare?project={code}")
    assert resp.status_code == 200, resp.text
    assert 'id="v2-sheet-compare"' in resp.text
    assert "Base Case" in resp.text
    assert "Scenario X" in resp.text

    chip_count = resp.text.count('class="v2-compare-chip')
    assert chip_count >= 2, f"Expected ≥2 chips, got {chip_count}"


def test_compare_get_excludes_archived_scenario():
    """Archived Scenario X must not appear in subsequent Compare GET."""
    owner = "gf-f03-b-" + uuid.uuid4().hex[:8]
    code = "gf-f03-b-" + uuid.uuid4().hex[:8]
    record, base_sc, snapshot = _setup(owner, code)
    client = _client(owner)

    from app.persistence.scenarios_repository import add_scenario, archive_scenario
    sc_x = add_scenario(
        user_id=owner,
        project_id=record.project_id,
        project_code=code,
        scenario_name="Scenario Archived",
        parent_scenario_id=base_sc.scenario_id,
        base_input_set=snapshot,
    )

    before = client.get(f"/v2/workbook/scenarios/compare?project={code}")
    assert "Scenario Archived" in before.text

    archive_scenario(user_id=owner, scenario_id=sc_x.scenario_id)

    after = client.get(f"/v2/workbook/scenarios/compare?project={code}")
    assert after.status_code == 200, after.text
    assert "Scenario Archived" not in after.text
    assert "Base Case" in after.text


def test_compare_get_reflects_rename():
    """Renaming a scenario is immediately visible in the next Compare GET."""
    owner = "gf-f03-c-" + uuid.uuid4().hex[:8]
    code = "gf-f03-c-" + uuid.uuid4().hex[:8]
    record, base_sc, snapshot = _setup(owner, code)
    client = _client(owner)

    from app.persistence.scenarios_repository import add_scenario, rename_scenario
    sc_x = add_scenario(
        user_id=owner,
        project_id=record.project_id,
        project_code=code,
        scenario_name="Old Name",
        parent_scenario_id=base_sc.scenario_id,
        base_input_set=snapshot,
    )

    before = client.get(f"/v2/workbook/scenarios/compare?project={code}")
    assert "Old Name" in before.text

    rename_scenario(user_id=owner, scenario_id=sc_x.scenario_id, new_name="New Name")

    after = client.get(f"/v2/workbook/scenarios/compare?project={code}")
    assert after.status_code == 200, after.text
    assert "New Name" in after.text
    assert "Old Name" not in after.text


def test_compare_get_forwards_selected_ids():
    """s1/s2 params from a prior selection are reflected in the rendered form."""
    owner = "gf-f03-d-" + uuid.uuid4().hex[:8]
    code = "gf-f03-d-" + uuid.uuid4().hex[:8]
    record, base_sc, snapshot = _setup(owner, code)
    client = _client(owner)

    from app.persistence.scenarios_repository import add_scenario
    sc_x = add_scenario(
        user_id=owner,
        project_id=record.project_id,
        project_code=code,
        scenario_name="Selected X",
        parent_scenario_id=base_sc.scenario_id,
        base_input_set=snapshot,
    )

    resp = client.get(
        f"/v2/workbook/scenarios/compare"
        f"?project={code}&s1={base_sc.scenario_id}&s2={sc_x.scenario_id}"
    )
    assert resp.status_code == 200, resp.text
    assert base_sc.scenario_id in resp.text
    assert sc_x.scenario_id in resp.text
    assert "v2-compare-chip--selected" in resp.text
    assert ".v2-compare-table" in resp.text or "v2-compare-table" in resp.text


def test_compare_get_has_no_engine_execution():
    """Compare GET must never invoke run_project, run_clean_production, or execute_production_waterfall."""
    owner = "gf-f03-e-" + uuid.uuid4().hex[:8]
    code = "gf-f03-e-" + uuid.uuid4().hex[:8]
    record, base_sc, snapshot = _setup(owner, code)
    client = _client(owner)

    from app.persistence.scenarios_repository import add_scenario
    sc_x = add_scenario(
        user_id=owner,
        project_id=record.project_id,
        project_code=code,
        scenario_name="Engine Guard X",
        parent_scenario_id=base_sc.scenario_id,
        base_input_set=snapshot,
    )

    with (
        patch(
            "app.api.project_runner.run_project",
            side_effect=AssertionError("run_project called from Compare GET"),
        ) as run_project,
        patch(
            "app.services.production_financial_authority.run_clean_production",
            side_effect=AssertionError("run_clean_production called from Compare GET"),
        ) as run_clean,
        patch(
            "app.services.production_waterfall_seam.execute_production_waterfall",
            side_effect=AssertionError("execute_production_waterfall called from Compare GET"),
        ) as waterfall,
    ):
        resp = client.get(
            f"/v2/workbook/scenarios/compare"
            f"?project={code}&s1={base_sc.scenario_id}&s2={sc_x.scenario_id}"
        )

    assert resp.status_code == 200, resp.text
    run_project.assert_not_called()
    run_clean.assert_not_called()
    waterfall.assert_not_called()


def test_compare_get_stale_workbook_vs_fresh_compare_endpoint():
    """GF-F03 root cause: initial workbook GET has stale Compare; canonical Compare GET is fresh.

    Sequence:
      1. Initial workbook GET (only Base Case exists) → Compare partial has 1 chip.
      2. Create Scenario X after the GET.
      3. Canonical Compare GET → returns 2 chips (fresh from persistence).

    This proves the server-side authority: the Compare endpoint always reads
    current persistence regardless of when the page was loaded.
    The tab-click HTMX mechanism (workbook.html) is what makes the browser
    show fresh Compare without a full page reload.
    """
    owner = "gf-f03-f-" + uuid.uuid4().hex[:8]
    code = "gf-f03-f-" + uuid.uuid4().hex[:8]
    record, base_sc, snapshot = _setup(owner, code)
    client = _client(owner)

    # Step 1: Initial workbook GET — only Base Case exists at this point.
    overview = client.get(f"/v2/workbook?project={code}")
    assert overview.status_code == 200, overview.text
    stale_chips = overview.text.count('class="v2-compare-chip')
    assert stale_chips == 1, (
        f"Initial Compare render should have 1 chip (base case only), got {stale_chips}"
    )

    # Step 2: Create Scenario X AFTER the page was loaded.
    from app.persistence.scenarios_repository import add_scenario
    add_scenario(
        user_id=owner,
        project_id=record.project_id,
        project_code=code,
        scenario_name="Post-Load Scenario X",
        parent_scenario_id=base_sc.scenario_id,
        base_input_set=snapshot,
    )

    # Step 3: Canonical Compare GET returns the fresh state — 2 chips.
    compare = client.get(f"/v2/workbook/scenarios/compare?project={code}")
    assert compare.status_code == 200, compare.text
    assert "Post-Load Scenario X" in compare.text
    fresh_chips = compare.text.count('class="v2-compare-chip')
    assert fresh_chips >= 2, (
        f"Canonical Compare GET must show ≥2 chips after scenario creation, got {fresh_chips}"
    )
