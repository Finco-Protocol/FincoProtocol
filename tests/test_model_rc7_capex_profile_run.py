"""RC-7 B1/B4 end to end on the REAL app: Save the monthly profile -> Working Copy dirty / Last Run STALE -> real Run -> reconciled
funding schedule and IDC -> Reset restores the default Run exactly.  No mocked engine, no mocked persistence."""
from __future__ import annotations

import json

import pytest

from app.capex_profiles import config
from app.capex_profiles.runtime import CapexProfileBindingError, leaves_for
from app.capex_profiles.service import CapexProfileConflict, save_profiles
from app.persistence.run_history_repository import get_run_history
from app.persistence.workspace_repository import get_workspace_state
from app.workbook.registry import WORKBOOK
from app.workbook.runtime_authority import RuntimeAuthorityState, resolve_runtime_freshness
from app.workbook.workbook_identity import assemble_consistent_for_get
from tests.test_model_decision_workspace_v2 import env, tokens  # noqa: F401

OWNER = "decision-user"


@pytest.fixture(autouse=True)
def _planner_routes(env):  # noqa: F811
    from app.v2.capex_router import capex_router
    if not any(getattr(r, "path", "") == "/v2/capex/spending-profiles" for r in env.client.app.routes):
        env.client.app.include_router(capex_router, prefix="/v2/capex")


def _hash(project):
    return assemble_consistent_for_get(OWNER, project.project_id, WORKBOOK.version).composite_hash


def _ws(project):
    return get_workspace_state(OWNER, project.project_id)


def _run(env, project):
    page = env.client.get("/v2/workbook", params={"project": project.project_code})
    assert page.status_code == 200
    response = env.client.post("/v2/workbook/run", headers={"HX-Request": "true"},
                               data={"project": project.project_code, **tokens(page.text)})
    return response


def _latest(project):
    return get_run_history(OWNER, project.project_id)[0]


def _doc(profiles):
    return json.dumps({"version": 1, "profiles": profiles})


def _row(key, shape, *, percents=(), month=None):
    return {"item_key": key, "shape": shape, "explicit_percent": list(percents), "milestone_month": month}


def _save(project, profiles, *, expected=None):
    ws = _ws(project)
    return save_profiles(owner=OWNER, project_id=project.project_id, expected_hash=expected or _hash(project),
                         expected_scenario_id=ws.active_scenario_id or "", raw=_doc(profiles))


def _base_leaves(project):
    from app.workbook.service import WorkbookService
    import dataclasses
    from app.services.capex_sub_lines_integration import apply_user_sub_lines_replacing_base
    pi = WorkbookService.to_projectinputs(WorkbookService.build_draft_input_set_from_workspace(_ws(project)))
    capex = apply_user_sub_lines_replacing_base(pi.capex, project_id=project.project_id)
    return [leaf for leaf in leaves_for(capex, project.project_id) if leaf.amount_keur > 0]


def _periods(entry):
    return entry.integrity_evidence["sources_uses"]["construction_periods"]


def _financing(entry):
    return entry.runtime_summary["financing_evidence"]["sources_uses"]


@pytest.fixture
def solar(env):  # noqa: F811
    project = env.create("solar")
    assert _run(env, project).status_code == 200
    return project


def test_save_marks_dirty_and_stale_then_run_changes_funding_and_idc_then_reset_restores_the_default(env, solar):
    base = _latest(solar)
    base_dict = base.to_dict()
    n_default = len(_periods(base))
    assert n_default == 3
    leaves = _base_leaves(solar)
    assert leaves, "the reference Solar project carries CAPEX base leaves"
    freshness = resolve_runtime_freshness(_ws(solar), current_composite_hash=_hash(solar))
    assert freshness.state == RuntimeAuthorityState.CURRENT

    before_hash = _hash(solar)
    new_hash = _save(solar, [_row(l.item_key, "FRONT_LOADED") for l in leaves])
    ws = _ws(solar)
    assert ws.dirty is True or ws.dirty == 1
    assert new_hash == _hash(solar) != before_hash                                            # composite identity covers the profile
    assert config.SNAPSHOT_KEY in ws.draft_snapshot and config.SNAPSHOT_KEY not in ws.saved_snapshot
    assert resolve_runtime_freshness(ws, current_composite_hash=_hash(solar)).state == RuntimeAuthorityState.STALE
    assert [h.history_id for h in get_run_history(OWNER, solar.project_id)] == [base.history_id]   # Save never runs or edits history

    assert _run(env, solar).status_code == 200
    bound = _latest(solar)
    assert bound.history_id != base.history_id
    periods = _periods(bound)
    assert len(periods) == 14                                                                 # monthly construction axis
    assert all(abs(p["difference"]) < 1e-6 and abs(p["sources"] - p["uses"]) < 1e-6 for p in periods)   # every month reconciles
    su_base, su_bound = _financing(base), _financing(bound)
    assert su_bound["base_project_capex_keur"] == pytest.approx(su_base["base_project_capex_keur"], abs=1e-6)   # hard CAPEX unchanged
    assert su_bound["capitalized_idc_keur"] != pytest.approx(su_base["capitalized_idc_keur"], abs=1e-3)           # timing moved IDC
    d_total = su_bound["total_uses_keur"] - su_base["total_uses_keur"]
    # Hard CAPEX and other uses are unchanged, so every Total-Uses movement is attributable to the financing-cost lines and to the initial
    # DSRA funding, which the canonical fixed point re-sizes because it follows the (re-timed, re-sized) Senior debt service.
    d_fin = sum(su_bound[k] - su_base[k] for k in ("capitalized_idc_keur", "commitment_fee_keur", "structuring_fee_keur",
                                                    "other_financing_costs_keur", "initial_dsra_funding_keur"))
    assert su_bound["other_uses_keur"] == su_base["other_uses_keur"]
    assert d_total == pytest.approx(d_fin, abs=1e-4)
    assert su_bound["total_sources_keur"] == pytest.approx(su_bound["total_uses_keur"], abs=1e-6)
    assert base.to_dict() == base_dict == get_run_history(OWNER, solar.project_id)[1].to_dict()    # historical Run immutable
    assert resolve_runtime_freshness(_ws(solar), current_composite_hash=_hash(solar)).state == RuntimeAuthorityState.CURRENT

    # Reset: removing the document restores the default Run EXACTLY (same numbers as before any profile existed)
    ws2 = _ws(solar)
    save_profiles(owner=OWNER, project_id=solar.project_id, expected_hash=_hash(solar),
                  expected_scenario_id=ws2.active_scenario_id or "", raw=_doc([]))
    assert config.SNAPSHOT_KEY not in _ws(solar).draft_snapshot
    assert _hash(solar) == before_hash                                                        # identity returns to the pre-profile hash
    assert _run(env, solar).status_code == 200
    reset = _latest(solar)
    assert len(_periods(reset)) == n_default
    assert _financing(reset) == _financing(base)
    assert reset.runtime_summary["total_project_uses_keur"] == base.runtime_summary["total_project_uses_keur"]


def test_stale_scope_and_invalid_documents_are_rejected_and_write_nothing(env, solar):
    leaves = _base_leaves(solar)
    key = leaves[0].item_key

    def snapshot_state():
        ws = _ws(solar)
        return (ws.draft_snapshot, ws.dirty, _hash(solar), tuple(h.history_id for h in get_run_history(OWNER, solar.project_id)))

    state = snapshot_state()
    with pytest.raises(CapexProfileConflict) as stale:
        _save(solar, [_row(key, "UNIFORM")], expected="0" * 64)
    assert stale.value.code == "CAPEX_PROFILE_STALE"
    for profiles, code in (
        ([_row("base:no_such_field", "UNIFORM")], "CAPEX_PROFILE_LEAF_UNKNOWN"),
        ([_row("C.99.99", "UNIFORM")], "CAPEX_PROFILE_LEAF_UNKNOWN"),
        ([_row(key, "UNIFORM"), _row(key, "FRONT_LOADED")], "CAPEX_PROFILE_DUPLICATE_ITEM"),
        ([_row(key, "EXPLICIT", percents=["50", "40"])], "CAPEX_PROFILE_PERIOD_COUNT_MISMATCH"),
        ([_row(key, "EXPLICIT", percents=["8"] * 14)], "CAPEX_PROFILE_WEIGHT_SUM_INVALID"),
        ([_row(key, "EXPLICIT", percents=["-1"] + ["8"] * 13)], "CAPEX_PROFILE_WEIGHT_NEGATIVE"),
        ([_row(key, "MILESTONE", month=99)], "CAPEX_PROFILE_MILESTONE_MONTH_INVALID"),
        ([_row(key, "GAUSSIAN")], "CAPEX_PROFILE_SHAPE_INVALID"),
        ([_row("derived:idc", "UNIFORM")], "CAPEX_PROFILE_ITEM_KEY_INVALID"),
    ):
        with pytest.raises(CapexProfileBindingError) as exc:
            _save(solar, profiles)
        assert exc.value.code == code, (profiles, exc.value)
    assert snapshot_state() == state


def _form(env, project):
    page = env.client.get("/v2/capex/spending-profiles", params={"project": project.project_code})
    assert page.status_code == 200
    import re
    return {"project": project.project_code,
            "csrf_token": re.search(r'name="csrf_token" value="([^"]+)"', page.text).group(1),
            "content_hash": re.search(r'name="content_hash" value="([^"]+)"', page.text).group(1)}, page


def test_planner_routes_save_run_and_reconcile_then_reset(env, solar):
    import re
    base = _latest(solar)
    form, page = _form(env, solar)
    assert 'data-testid="profile-status" data-saved="false"' in page.text
    leaves = _base_leaves(solar)
    rows = {}
    for i, leaf in enumerate(leaves):
        rows[f"key_{i}"], rows[f"shape_{i}"] = leaf.item_key, "BACK_LOADED"
    saved = env.client.post("/v2/capex/spending-profiles/save", data={**form, **rows, "action": "save"}, follow_redirects=False)
    assert saved.status_code == 303 and saved.headers["location"].endswith("&saved=saved")
    page = env.client.get(saved.headers["location"])
    assert 'data-saved="true" data-bound="true"' in page.text and "Last Run is now STALE" in page.text
    assert config.SNAPSHOT_KEY in _ws(solar).draft_snapshot and _ws(solar).dirty
    for leaf in leaves:                                                         # the saved profile pre-fills the form
        assert re.search(r'<tr data-item="%s".*?<option value="BACK_LOADED" selected' % re.escape(leaf.item_key), page.text, re.S)
    assert 'data-testid="last-run-freshness">STALE' in page.text and 'data-used-profile="false"' in page.text

    assert _run(env, solar).status_code == 200
    page = env.client.get("/v2/capex/spending-profiles", params={"project": solar.project_code})
    assert 'data-testid="last-run-freshness">CURRENT' in page.text and 'data-used-profile="true"' in page.text
    assert len(re.findall(r"<tr><td>\d+</td><td class=\"num\">", page.text)) == 14                      # the monthly Run periods are shown
    bound = _latest(solar)
    assert float(re.search(r'data-testid="lr-idc">([\d.]+)', page.text).group(1)) == pytest.approx(_financing(bound)["capitalized_idc_keur"], abs=1e-3)
    assert float(re.search(r'data-testid="lr-total-uses">([\d.]+)', page.text).group(1)) == pytest.approx(_financing(bound)["total_uses_keur"], abs=1e-3)

    form, _ = _form(env, solar)
    reset = env.client.post("/v2/capex/spending-profiles/save", data={**form, "action": "reset"}, follow_redirects=False)
    assert reset.status_code == 303 and config.SNAPSHOT_KEY not in _ws(solar).draft_snapshot
    assert _run(env, solar).status_code == 200
    assert _financing(_latest(solar)) == _financing(base)                       # exact return to the default Run


def test_stale_page_and_invalid_rows_are_rejected_by_the_route_and_write_nothing(env, solar):
    form, _ = _form(env, solar)
    key = _base_leaves(solar)[0].item_key
    state = (_ws(solar).draft_snapshot, _hash(solar))
    stale = env.client.post("/v2/capex/spending-profiles/save", data={**form, "content_hash": "0" * 64, "key_0": key, "shape_0": "UNIFORM"})
    assert stale.status_code == 409 and "CAPEX_PROFILE_STALE" in stale.text
    bad = env.client.post("/v2/capex/spending-profiles/save",
                          data={**form, "key_0": key, "shape_0": "EXPLICIT", "explicit_0": "50,40", "action": "save"})
    assert bad.status_code == 422 and "CAPEX_PROFILE_PERIOD_COUNT_MISMATCH" in bad.text
    unknown = env.client.post("/v2/capex/spending-profiles/save", data={**form, "key_0": "base:nothing_here", "shape_0": "UNIFORM"})
    assert unknown.status_code == 422 and "CAPEX_PROFILE_LEAF_UNKNOWN" in unknown.text
    assert (_ws(solar).draft_snapshot, _hash(solar)) == state


def test_a_profile_orphaned_by_removing_its_leaf_fails_the_run_closed(env, solar):
    """A stored profile whose leaf no longer carries cash (sub-line deactivated) must stop the Run, not silently revert to default timing."""
    from app.persistence.capex_sub_lines import get_active_sub_lines_for_project
    from app.persistence.projects_repository import get_project_by_id
    from app.v2 import capex_commands as commands
    leaf = next(l for l in _base_leaves(solar) if not l.item_key.startswith("base:"))
    sub = next(s for s in get_active_sub_lines_for_project(solar.project_id) if s.business_code == leaf.item_key)
    _save(solar, [_row(leaf.item_key, "UNIFORM")])
    count = len(get_run_history(OWNER, solar.project_id))
    commands.deactivate_capex_line(project_record=get_project_by_id(solar.project_id), user_id=OWNER, sub_line_id=sub.sub_line_id,
                                   row_version=sub.updated_at, workbook_version=WORKBOOK.version, expected_content_hash=_hash(solar))
    response = _run(env, solar)
    assert "CAPEX_PROFILE_LEAF_UNKNOWN" in response.text                         # explicit refusal, not a silent default Run
    assert len(get_run_history(OWNER, solar.project_id)) == count


def test_scenarios_inherit_but_cannot_edit_the_profile(env, solar):
    from app.persistence.scenarios_repository import save_scenario, select_scenario
    ws = _ws(solar)
    key = _base_leaves(solar)[0].item_key
    _save(solar, [_row(key, "FRONT_LOADED")])
    scenario = save_scenario(user_id=OWNER, project_id=solar.project_id, scenario_name="Downside", project_code=solar.project_code,
                             source_project_template=solar.template_source, snapshot=dict(_ws(solar).draft_snapshot))
    assert select_scenario(OWNER, solar.project_id, scenario.scenario_id)
    with pytest.raises(CapexProfileConflict) as exc:
        save_profiles(owner=OWNER, project_id=solar.project_id, expected_hash=_hash(solar),
                      expected_scenario_id=_ws(solar).active_scenario_id or "", raw=_doc([_row(key, "BACK_LOADED")]))
    assert exc.value.code == "CAPEX_PROFILE_SCENARIO_EDIT_UNSUPPORTED"
    form, page = _form(env, solar)
    assert 'data-testid="read-only-note"' in page.text and "profile-save" not in page.text
    refused = env.client.post("/v2/capex/spending-profiles/save", data={**form, "key_0": key, "shape_0": "UNIFORM"})
    assert refused.status_code == 403 and "CAPEX_PROFILE_SCENARIO_EDIT_UNSUPPORTED" in refused.text
    assert config.SNAPSHOT_KEY in _ws(solar).draft_snapshot and ws is not None


def test_a_reference_project_you_do_not_own_cannot_be_written(env, solar):
    from app.persistence.workspace_repository import get_workspace_state
    other = env.create("wind")
    ws = get_workspace_state(OWNER, other.project_id)
    with pytest.raises(Exception):
        save_profiles(owner="someone-else", project_id=other.project_id, expected_hash=_hash(other), expected_scenario_id="", raw=_doc([_row("base:production_units", "UNIFORM")]))
    assert config.SNAPSHOT_KEY not in get_workspace_state(OWNER, other.project_id).draft_snapshot and ws is not None
