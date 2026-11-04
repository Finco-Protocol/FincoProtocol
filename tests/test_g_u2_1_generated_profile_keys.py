"""G-U2-1: a generated ``C.NN.U###`` CAPEX profile key is admitted ONLY when it names an extant ACTIVE line of this project in the sub-line ledger.

Synthetic disposable data only. The key shape is syntax; the ledger is the authority. Every refusal leaves the draft snapshot and the composite identity unchanged.
"""
from __future__ import annotations

import json

import pytest

from app.capex_profiles import config
from app.capex_profiles.contract import ProfileError
from app.capex_profiles.runtime import CapexProfileBindingError
from app.capex_profiles.service import save_profiles
from app.persistence.db import get_connection
from app.workbook.registry import WORKBOOK
from tests.test_model_rc7_capex_profile_run import (  # noqa: F401  (shared real-app fixtures and helpers)
    OWNER, _doc, _hash, _planner_routes, _row, _save, _ws, env, solar, tokens)

GROUP = "C.02"      # a category the reference project already times (a category with no base amount has no default construction timing)


def _add(project, label="G-U2-1 line", amount="120"):
    from app.persistence.projects_repository import get_project_by_id
    from app.v2 import capex_commands as commands
    sub, _ = commands.add_capex_line(project_record=get_project_by_id(project.project_id), user_id=OWNER, label=label,
                                     parent_category_code=GROUP, amount_keur=amount, workbook_version=WORKBOOK.version,
                                     expected_content_hash=_hash(project))
    return sub


def _state(project):
    return _ws(project).draft_snapshot, _hash(project)


def _sql(statement, params=()):
    conn = get_connection()
    try:
        conn.execute(statement, params)
        conn.commit()
    finally:
        conn.close()


def test_a_generated_key_of_an_extant_active_line_is_saved_and_persisted_verbatim(solar):
    sub = _add(solar)
    assert sub.business_code.startswith(GROUP + ".U")
    _save(solar, [_row(sub.business_code, "FRONT_LOADED")])
    doc = json.loads(_ws(solar).draft_snapshot[config.SNAPSHOT_KEY])
    assert [p["item_key"] for p in doc["profiles"]] == [sub.business_code]


@pytest.mark.parametrize("key", ["C.2.U1", "C.02.U1", "C.02.U0001", "C.02.u001", "C.02.U00A", "C.02.U001 ", "c.02.U001", "C.02.U", "C.02.U-01",
                                 "C.02.U001\n", "C．02.U001", "C.٠٢.U001"])
def test_a_malformed_generated_key_is_refused_before_any_ledger_lookup(solar, key):
    before = _state(solar)
    with pytest.raises((CapexProfileBindingError, ProfileError)) as exc:
        _save(solar, [_row(key, "UNIFORM")])
    assert "ITEM_KEY_INVALID" in str(exc.value.code)
    assert _state(solar) == before


def test_a_well_formed_key_with_no_ledger_line_is_refused(solar):
    sub = _add(solar)
    before = _state(solar)
    typo = sub.business_code[:-1] + ("9" if not sub.business_code.endswith("9") else "8")
    for key in (typo, "C.02.U099", "C.05.U001"):
        with pytest.raises(CapexProfileBindingError) as exc:
            _save(solar, [_row(key, "UNIFORM")])
        assert exc.value.code == "CAPEX_PROFILE_LEAF_UNKNOWN"
    assert _state(solar) == before


def test_another_projects_line_with_the_same_code_is_not_this_projects_line(env, solar):
    other = env.create("solar")
    theirs = _add(other, "Their line")
    before = _state(solar)
    with pytest.raises(CapexProfileBindingError) as exc:
        _save(solar, [_row(theirs.business_code, "UNIFORM")])                       # solar has no such line: the code alone grants nothing
    assert exc.value.code == "CAPEX_PROFILE_LEAF_UNKNOWN"
    assert _state(solar) == before


def test_a_retired_or_hard_deleted_line_is_refused(solar):
    from app.persistence.projects_repository import get_project_by_id
    from app.v2 import capex_commands as commands
    retired, deleted = _add(solar, "Will retire"), _add(solar, "Will vanish")
    commands.deactivate_capex_line(project_record=get_project_by_id(solar.project_id), user_id=OWNER, sub_line_id=retired.sub_line_id,
                                   row_version=retired.updated_at, workbook_version=WORKBOOK.version, expected_content_hash=_hash(solar))
    _sql("DELETE FROM capex_sub_lines WHERE sub_line_id=?", (deleted.sub_line_id,))
    before = _state(solar)
    for key in (retired.business_code, deleted.business_code):
        with pytest.raises(CapexProfileBindingError) as exc:
            _save(solar, [_row(key, "UNIFORM")])
        assert exc.value.code == "CAPEX_PROFILE_LEAF_UNKNOWN"
    assert _state(solar) == before


def test_a_key_whose_category_disagrees_with_the_ledger_line_is_refused(solar):
    sub = _add(solar)
    # same line identity (still folded into C.02), but its code now claims C.05: the key's NN disagrees with the ledger category
    _sql("UPDATE capex_sub_lines SET business_code=?, parent_category_code=? WHERE sub_line_id=?", ("C.05.U001", GROUP, sub.sub_line_id))
    before = _state(solar)
    with pytest.raises(CapexProfileBindingError) as exc:
        _save(solar, [_row("C.05.U001", "UNIFORM")])
    assert exc.value.code == "CAPEX_PROFILE_LEAF_CATEGORY_MISMATCH"
    assert _state(solar) == before


def test_another_tenant_cannot_profile_this_projects_generated_line(solar):
    sub = _add(solar)
    before = _state(solar)
    with pytest.raises(Exception):
        save_profiles(owner="someone-else", project_id=solar.project_id, expected_hash=_hash(solar), expected_scenario_id="",
                      raw=_doc([_row(sub.business_code, "UNIFORM")]))
    assert _state(solar) == before


def test_explicit_weights_for_a_generated_line_stay_count_matched_finite_nonnegative_and_sum_to_100(solar):
    sub = _add(solar)
    before = _state(solar)
    for percents, code in ((["50", "50"], "CAPEX_PROFILE_PERIOD_COUNT_MISMATCH"),):
        with pytest.raises(CapexProfileBindingError) as exc:
            _save(solar, [_row(sub.business_code, "EXPLICIT", percents=percents)])
        assert exc.value.code == code
    months = 14
    for bad, code in ((["nan"] + ["0"] * (months - 1), "CAPEX_PROFILE_WEIGHT_NON_FINITE"),
                      (["-10", "110"] + ["0"] * (months - 2), "CAPEX_PROFILE_WEIGHT_NEGATIVE"),
                      (["10"] * months, "CAPEX_PROFILE_WEIGHT_SUM_INVALID")):
        with pytest.raises(CapexProfileBindingError) as exc:
            _save(solar, [_row(sub.business_code, "EXPLICIT", percents=bad)])
        assert exc.value.code == code
    assert _state(solar) == before
