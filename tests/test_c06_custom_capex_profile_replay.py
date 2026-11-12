"""C06 — replay, on the accepted current code, of a CUSTOM (user-added) CAPEX line that owns a monthly spending profile.

Synthetic disposable data only (the reference Solar project of the test harness, labels ``C06 ...``).  Every step is executed against the real app,
persistence and engine: add line -> eligible in the profile catalogue -> Save profile -> Working Copy dirty / Run STALE -> real Run -> reload ->
second row -> rename -> zero amount -> stale CAS -> retire (orphan) -> Run refused.  When ``C06_REPLAY_CSV`` names a path the observed rows are written
there (private owner evidence, never committed).  Nothing here changes a financial rule: it records what the canonical authority does.
"""
from __future__ import annotations

import csv
import json
import os

import pytest

from app.capex_profiles import config
from app.capex_profiles.runtime import CapexProfileBindingError, leaves_for
from app.capex_profiles.service import CapexProfileConflict, save_profiles
from app.persistence.run_history_repository import get_run_history
from app.workbook.registry import WORKBOOK
from tests.test_model_rc7_capex_profile_run import (  # noqa: F401  (shared real-app fixtures and helpers)
    OWNER, _doc, _financing, _hash, _latest, _periods, _planner_routes, _row, _run, _save, _ws, env, solar, tokens)

GROUP = "C.02"      # a category the reference project already times (a category with no base amount has no default construction timing)
_LOG: list[dict] = []


def _step(step, outcome, **detail):
    _LOG.append({"step": step, "outcome": outcome, "detail": json.dumps(detail, sort_keys=True, default=str)})


def _project_record(project):
    from app.persistence.projects_repository import get_project_by_id
    return get_project_by_id(project.project_id)


def _add(project, label, amount):
    from app.v2 import capex_commands as commands
    sub, _ = commands.add_capex_line(project_record=_project_record(project), user_id=OWNER, label=label, parent_category_code=GROUP,
                                     amount_keur=amount, workbook_version=WORKBOOK.version, expected_content_hash=_hash(project))
    return sub


def _fresh(project, sub_line_id):
    from app.persistence.capex_sub_lines import get_active_sub_lines_for_project
    return next(s for s in get_active_sub_lines_for_project(project.project_id) if s.sub_line_id == sub_line_id)


def _catalogue_keys(project):
    from app.v2.capex_profile_router import catalogue
    from app.workbook.service import WorkbookService
    pis = WorkbookService.build_draft_input_set_from_workspace(_ws(project))
    items, excluded = catalogue(pis, project.project_id)
    return {i.item_key for i in items}, {e.item_key for e in excluded}


@pytest.fixture(scope="module", autouse=True)
def _write_private_replay():
    yield
    target = os.environ.get("C06_REPLAY_CSV")
    if target and _LOG:
        with open(target, "w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=["seq", "step", "outcome", "detail"])
            writer.writeheader()
            for n, row in enumerate(_LOG, 1):
                writer.writerow({"seq": n, **row})


def test_custom_line_profile_replay_save_reload_run_and_binding(env, solar):
    base = _latest(solar)
    a = _add(solar, "C06 custom line A", "120")
    assert a.business_code.startswith(GROUP + ".U") and a.is_active
    keys, excluded = _catalogue_keys(solar)
    _step("1 add custom line", "ELIGIBLE_IN_CATALOGUE" if a.business_code in keys else "NOT_IN_CATALOGUE",
          code_shape="C.NN.U###", in_catalogue=a.business_code in keys, in_excluded=a.business_code in excluded)
    assert a.business_code in keys and a.business_code not in excluded
    leaf = next(l for l in leaves_for(_ws_capex(solar), solar.project_id) if l.item_key == a.business_code)
    assert leaf.amount_keur > 0

    before = _hash(solar)
    new_hash = _save(solar, [_row(a.business_code, "FRONT_LOADED")])
    ws = _ws(solar)
    doc = json.loads(ws.draft_snapshot[config.SNAPSHOT_KEY])
    assert [p["item_key"] for p in doc["profiles"]] == [a.business_code]
    assert new_hash == _hash(solar) != before and (ws.dirty is True or ws.dirty == 1)
    _step("2 save profile", "PERSISTED_IN_DRAFT_AND_IDENTITY_MOVED", shape="FRONT_LOADED", dirty=True)

    history = len(get_run_history(OWNER, solar.project_id))
    assert _run(env, solar).status_code == 200
    run1 = _latest(solar)
    periods = _periods(run1)
    assert len(periods) == 14 and all(abs(p["difference"]) < 1e-6 for p in periods)
    assert len(get_run_history(OWNER, solar.project_id)) == history + 1
    _step("3 run with the custom-line profile", "RUN_OK_MONTHLY_AXIS_RECONCILES", months=len(periods),
          idc_moved=_financing(run1)["capitalized_idc_keur"] != _financing(base)["capitalized_idc_keur"])
    assert _financing(run1)["total_sources_keur"] == pytest.approx(_financing(run1)["total_uses_keur"], abs=1e-6)

    again = json.loads(_ws(solar).draft_snapshot[config.SNAPSHOT_KEY])           # reload: the saved document is exactly what was saved
    assert again == doc
    _step("4 reload", "SAME_DOCUMENT", rows=len(again["profiles"]))

    b = _add(solar, "C06 custom line B", "80")
    pct = ["0"] * 14
    pct[2], pct[9] = "37.5", "62.5"
    _save(solar, [_row(a.business_code, "FRONT_LOADED"), _row(b.business_code, "EXPLICIT", percents=pct)])
    assert _run(env, solar).status_code == 200
    run2 = _latest(solar)
    assert len(_periods(run2)) == 14 and _financing(run2)["total_sources_keur"] == pytest.approx(_financing(run2)["total_uses_keur"], abs=1e-6)
    _step("5 two custom rows, explicit decimal percents", "RUN_OK", rows=2, precision="37.5 / 62.5")

    from app.v2 import capex_commands as commands
    renamed, _ = commands.update_capex_line(project_record=_project_record(solar), user_id=OWNER, sub_line_id=a.sub_line_id,
                                            label="C06 custom line A (renamed)", amount_keur=120, row_version=_fresh(solar, a.sub_line_id).updated_at,
                                            workbook_version=WORKBOOK.version, expected_content_hash=_hash(solar))
    assert renamed.business_code == a.business_code
    assert _run(env, solar).status_code == 200
    _step("6 rename", "CODE_STABLE_PROFILE_KEPT", code=a.business_code)

    commands.update_capex_line(project_record=_project_record(solar), user_id=OWNER, sub_line_id=b.sub_line_id, label="C06 custom line B",
                               amount_keur=0, row_version=_fresh(solar, b.sub_line_id).updated_at, workbook_version=WORKBOOK.version,
                               expected_content_hash=_hash(solar))
    zero = _run(env, solar)
    assert zero.status_code == 200 or "CAPEX_" in zero.text
    _step("7 profiled line amount set to zero", "RUN_OK" if zero.status_code == 200 and "CAPEX_PROFILE" not in zero.text else "RUN_REFUSED",
          http=zero.status_code, refusal=next((c for c in ("CAPEX_BINDING_ZERO_CATEGORY", "CAPEX_PROFILE_LEAF_UNKNOWN") if c in zero.text), None))

    stale = before                                                              # an identity from before the save
    with pytest.raises(CapexProfileConflict):
        save_profiles(owner=OWNER, project_id=solar.project_id, expected_hash=stale, expected_scenario_id=_ws(solar).active_scenario_id or "",
                      raw=_doc([_row(a.business_code, "UNIFORM")]))
    assert json.loads(_ws(solar).draft_snapshot[config.SNAPSHOT_KEY])["profiles"][0]["item_key"] in {a.business_code, b.business_code}
    _step("8 stale CAS save", "REFUSED_CONFLICT_NOTHING_WRITTEN")

    saved_before_retire = _ws(solar).draft_snapshot[config.SNAPSHOT_KEY]
    count = len(get_run_history(OWNER, solar.project_id))
    commands.deactivate_capex_line(project_record=_project_record(solar), user_id=OWNER, sub_line_id=a.sub_line_id,
                                   row_version=_fresh(solar, a.sub_line_id).updated_at, workbook_version=WORKBOOK.version,
                                   expected_content_hash=_hash(solar))
    refused = _run(env, solar)
    assert "CAPEX_PROFILE_LEAF_UNKNOWN" in refused.text
    assert len(get_run_history(OWNER, solar.project_id)) == count
    assert _ws(solar).draft_snapshot[config.SNAPSHOT_KEY] == saved_before_retire        # the orphan is neither silently dropped nor re-assigned
    _step("9 retire the profiled custom line", "RUN_REFUSED_CAPEX_PROFILE_LEAF_UNKNOWN", orphan_kept_in_document=True, history_unchanged=True)


def _ws_capex(project):
    from app.workbook.service import WorkbookService
    from app.services.capex_sub_lines_integration import apply_user_sub_lines_replacing_base
    pi = WorkbookService.to_projectinputs(WorkbookService.build_draft_input_set_from_workspace(_ws(project)))
    return apply_user_sub_lines_replacing_base(pi.capex, project_id=project.project_id)


def test_a_custom_line_profile_with_the_wrong_month_count_is_refused_with_a_typed_code_and_writes_nothing(env, solar):
    a = _add(solar, "C06 custom line months", "100")
    before = (_ws(solar).draft_snapshot, _hash(solar))
    with pytest.raises(CapexProfileBindingError) as exc:
        _save(solar, [_row(a.business_code, "EXPLICIT", percents=["50", "50"])])
    assert exc.value.code == "CAPEX_PROFILE_PERIOD_COUNT_MISMATCH"
    assert (_ws(solar).draft_snapshot, _hash(solar)) == before
    _step("10 explicit weights for a different number of months", "REFUSED_" + exc.value.code, nothing_written=True)


def test_a_custom_line_cannot_borrow_another_lines_code_or_a_foreign_category(env, solar):
    a = _add(solar, "C06 custom line owner", "100")
    before = (_ws(solar).draft_snapshot, _hash(solar))
    wrong_category = "C.05." + a.business_code.split(".")[-1]
    with pytest.raises(CapexProfileBindingError) as exc:
        _save(solar, [_row(wrong_category, "UNIFORM")])
    assert exc.value.code in {"CAPEX_PROFILE_LEAF_UNKNOWN", "CAPEX_PROFILE_LEAF_CATEGORY_MISMATCH"}
    assert (_ws(solar).draft_snapshot, _hash(solar)) == before
    _step("11 a code the ledger does not hold for this project", "REFUSED_" + exc.value.code, nothing_written=True)
