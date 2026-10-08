"""PR #222 Correction A — OPEX economic authority, Last Run export parity and
freshness safety (real integration, no mocks of the fold or the export).

* The canonical Last Run export must reconstruct EXACTLY the effective
  ``ProjectInputs`` the committed Run used (full equality of every CAPEX field and
  every OPEX item, not a Y1 total).
* A Run committed under the superseded OPEX fold must not be reported CURRENT.
"""
from __future__ import annotations

import dataclasses
import json

import pytest

from app.contingency_authority import SCENARIO_OVERRIDE_KEY
from tests.test_cost_workspace_consistency_v1 import (  # noqa: F401  (fixtures + helpers)
    HX, TECHNOLOGIES, _cost_workspace_executor_cleanup, _line_fields, _page, _post,
    _project, _row, _run, _state, seeded_db,
)


@pytest.fixture
def captured_run(monkeypatch):
    """Capture the exact ProjectInputs the V2 Run hands to the engine."""
    from app.runtime import model_execution as me

    box: dict = {}
    orig = me.run_model_process

    async def wrap(fn, key, scen, **kw):
        box["inputs"] = kw.get("project_inputs_override")
        return await orig(fn, key, scen, **kw)

    monkeypatch.setattr(me, "run_model_process", wrap)
    return box


def _export_inputs(user_id, rec):
    from app.persistence.projects_repository import get_project_by_id
    from app.services.export_service import resolve_export_authority

    return resolve_export_authority(get_project_by_id(rec.project_id), user_id).project_inputs


def _assert_full_parity(run_inputs, export_inputs):
    """Every dataclass field, every OPEX item (name, Y1, escalation, order)."""
    assert run_inputs is not None
    for f in dataclasses.fields(run_inputs):
        assert getattr(run_inputs, f.name) == getattr(export_inputs, f.name), f.name
    assert [(i.name, i.y1_amount_keur, i.annual_inflation) for i in run_inputs.opex] == \
           [(i.name, i.y1_amount_keur, i.annual_inflation) for i in export_inputs.opex]


def _active_ids(project_id, group=None):
    from app.persistence.db import get_cursor

    with get_cursor() as cur:
        cur.execute("SELECT sub_line_id, parent_group_code FROM opex_sub_lines "
                    "WHERE project_id=? AND is_active=1 ORDER BY display_order", (project_id,))
        return [r["sub_line_id"] for r in cur.fetchall()
                if group is None or r["parent_group_code"] == group]


def _first_group(project_id):
    from app.persistence.db import get_cursor

    with get_cursor() as cur:
        cur.execute("SELECT parent_group_code g FROM opex_sub_lines WHERE project_id=? "
                    "AND is_active=1 ORDER BY display_order LIMIT 1", (project_id,))
        return cur.fetchone()["g"]


def _deactivate(client, rec, sid, kind="opex"):
    assert _post(client, kind, "deactivate", **_line_fields(client, rec, kind, sid)).status_code == 200


def _add_custom(client, rec, kind="opex"):
    _, h, v = _page(client, rec.project_code)
    if kind == "opex":
        data = dict(project=rec.project_code, parent_group_code="B.09", label="Custom fee",
                    amount_keur="12", inflation_pct="2", notes="", workbook_version=v, content_hash=h)
    else:
        data = dict(project=rec.project_code, parent_category_code="C.01", label="Custom capex",
                    amount_keur="50", notes="", workbook_version=v, content_hash=h)
    assert client.post(f"/v2/{kind}/line/add", headers=HX, data=data).status_code == 200


def _scenario_with(client, rec, uid, overrides):
    from app.persistence.db import get_cursor

    client.post("/v2/workbook/scenarios/create", headers=HX,
                data={"project": rec.project_code, "scenario_name": "Parity S"})
    with get_cursor() as cur:
        cur.execute("UPDATE scenarios SET overrides_json=? WHERE user_id=? AND project_id=? "
                    "AND is_base_case=0", (json.dumps(overrides), uid, rec.project_id))


# ───────────────────── A. export reproduces the exact Run inputs ─────────────

CASES = ["fresh", "custom_row", "partial_deactivation", "category_all_inactive",
         "deactivate_reactivate", "scenario_amount_and_contingency"]


@pytest.mark.parametrize("case", CASES)
@pytest.mark.parametrize("template", TECHNOLOGIES)
def test_canonical_export_reproduces_the_exact_run_inputs(seeded_db, captured_run, template, case):
    uid = f"u-par-{template[8:12]}-{case[:6]}"
    client, rec = _project(uid, template)
    ids = _active_ids(rec.project_id)

    if case == "custom_row":
        _add_custom(client, rec, "opex")
        _add_custom(client, rec, "capex")
    elif case == "partial_deactivation":
        _deactivate(client, rec, ids[0])
    elif case == "category_all_inactive":
        for sid in _active_ids(rec.project_id, _first_group(rec.project_id)):
            _deactivate(client, rec, sid)
    elif case == "deactivate_reactivate":
        _deactivate(client, rec, ids[1])
        assert _post(client, "opex", "reactivate",
                     **_line_fields(client, rec, "opex", ids[1])).status_code == 200
    elif case == "scenario_amount_and_contingency":
        _scenario_with(client, rec, uid, {
            "_opex_sub_line_overrides": {ids[0]: 77.0},
            SCENARIO_OVERRIDE_KEY: {"opex": 0.5, "capex": 0.5},
        })

    _run(client, rec.project_code)
    if case == "scenario_amount_and_contingency":     # the scenario really reached the Run
        items = captured_run["inputs"].opex
        assert any(i.y1_amount_keur == 77.0 for i in items)
        assert any(getattr(i, "percentage_of_opex", 0) for i in items)
    _assert_full_parity(captured_run["inputs"], _export_inputs(uid, rec))


@pytest.mark.parametrize("capacity", [20.0, 55.0])
@pytest.mark.parametrize("template", ["generic_solar_reference", "generic_wind_reference"])
def test_export_parity_at_non_reference_capacity(seeded_db, captured_run, template, capacity):
    uid = f"u-par-cap-{template[8:12]}-{int(capacity)}"
    client, rec = _project(uid, template, capacity=capacity)
    _run(client, rec.project_code)
    _assert_full_parity(captured_run["inputs"], _export_inputs(uid, rec))


@pytest.mark.parametrize("template", ["generic_solar_reference", "generic_wind_reference"])
def test_seeded_decomposition_counts_exactly_once_in_the_run(seeded_db, captured_run, template):
    from app.persistence.db import get_cursor

    uid = f"u-par-once-{template[8:12]}"
    client, rec = _project(uid, template)
    _run(client, rec.project_code)
    run_y1 = sum(float(i.y1_amount_keur) for i in captured_run["inputs"].opex)
    with get_cursor() as cur:
        cur.execute("SELECT SUM(amount_keur) s FROM opex_sub_lines WHERE project_id=? AND is_active=1",
                    (rec.project_id,))
        lines = float(cur.fetchone()["s"])
    assert run_y1 == pytest.approx(lines)          # not 2x


def test_custom_additive_row_still_adds_on_top_of_the_seeded_decomposition(seeded_db, captured_run):
    uid = "u-par-add"
    client, rec = _project(uid, "generic_solar_reference")
    _run(client, rec.project_code)
    before = sum(float(i.y1_amount_keur) for i in captured_run["inputs"].opex)
    _add_custom(client, rec, "opex")
    _run(client, rec.project_code)
    after = sum(float(i.y1_amount_keur) for i in captured_run["inputs"].opex)
    assert after == pytest.approx(before + 12.0)


def test_failed_export_resolution_never_touches_the_committed_run(seeded_db):
    from app.persistence.workspace_repository import get_workspace_state

    uid = "u-par-imm"
    client, rec = _project(uid, "generic_solar_reference")
    _run(client, rec.project_code)
    ws0 = get_workspace_state(uid, rec.project_id)
    _export_inputs(uid, rec)
    ws1 = get_workspace_state(uid, rec.project_id)
    assert (ws0.last_runtime_identity, ws0.last_runtime_composite_hash, ws0.last_runtime_snapshot_id) == \
           (ws1.last_runtime_identity, ws1.last_runtime_composite_hash, ws1.last_runtime_snapshot_id)


# ──────────────── B. pre-correction Runs are not reported CURRENT ────────────

def _make_pre_correction(uid, rec):
    """Rewrite persisted state to what a Run committed BEFORE this correction
    looks like: identical composite hash, no ``opex_fold`` authority record."""
    from app.persistence.db import get_cursor

    with get_cursor() as cur:
        cur.execute("SELECT last_runtime_identity_json j FROM workspace_states "
                    "WHERE user_id=? AND project_id=?", (uid, rec.project_id))
        ident = json.loads(cur.fetchone()["j"])
        assert "opex_fold" in ident                                  # new Runs carry it
        ident.pop("opex_fold")
        cur.execute("UPDATE workspace_states SET last_runtime_identity_json=? "
                    "WHERE user_id=? AND project_id=?", (json.dumps(ident), uid, rec.project_id))
    return ident


def test_new_run_records_the_opex_fold_authority_and_is_current(seeded_db):
    from app.persistence.workspace_repository import get_workspace_state

    uid = "u-par-new"
    client, rec = _project(uid, "generic_wind_reference")
    _run(client, rec.project_code)
    fold = get_workspace_state(uid, rec.project_id).last_runtime_identity["opex_fold"]
    assert fold["semantics"] == "seed_replace_v1"
    assert fold["replaces_aggregate"] is True
    assert fold["replaced_canonical_keys"]
    assert _state(client, rec.project_code).lower().startswith("current")


@pytest.mark.parametrize("template", TECHNOLOGIES)
def test_run_committed_under_the_old_fold_is_stale_not_current(seeded_db, template):
    from app.persistence.workspace_repository import get_workspace_state
    from app.workbook.registry import WORKBOOK
    from app.workbook.runtime_authority import resolve_runtime_freshness
    from app.workbook.workbook_identity import assemble_for_workspace

    uid = f"u-par-old-{template[8:12]}"
    client, rec = _project(uid, template)
    _run(client, rec.project_code)
    assert _state(client, rec.project_code).lower().startswith("current")
    ident_before = _make_pre_correction(uid, rec)

    ws = get_workspace_state(uid, rec.project_id)
    cur_hash = assemble_for_workspace(ws, user_id=uid, project_id=rec.project_id,
                                      workbook_version=WORKBOOK.version).composite_hash
    assert cur_hash == ws.last_runtime_composite_hash                # inputs unchanged...
    fr = resolve_runtime_freshness(ws, current_composite_hash=cur_hash)
    assert fr.is_stale and fr.source == "opex_fold_semantics_superseded"   # ...economics are not
    assert _state(client, rec.project_code).lower().startswith("stale")
    # nothing about the historical record was rewritten by looking at it
    assert get_workspace_state(uid, rec.project_id).last_runtime_identity == ident_before


def test_export_of_a_pre_correction_run_fails_closed_not_guessed(seeded_db):
    uid = "u-par-old-exp"
    client, rec = _project(uid, "generic_solar_reference")
    _run(client, rec.project_code)
    _make_pre_correction(uid, rec)
    with pytest.raises(ValueError, match="CANONICAL_LAST_RUN_UNAVAILABLE: OPEX_FOLD_PROVENANCE_MISSING"):
        _export_inputs(uid, rec)


def test_rerun_after_correction_restores_current_and_export(seeded_db, captured_run):
    uid = "u-par-rerun"
    client, rec = _project(uid, "generic_solar_reference")
    _run(client, rec.project_code)
    _make_pre_correction(uid, rec)
    assert _state(client, rec.project_code).lower().startswith("stale")
    _run(client, rec.project_code)
    assert _state(client, rec.project_code).lower().startswith("current")
    _assert_full_parity(captured_run["inputs"], _export_inputs(uid, rec))


def test_project_without_seeded_opex_rows_is_not_invalidated(seeded_db):
    """A legacy (unseeded) working copy folds identically under both semantics,
    so its pre-correction Run stays CURRENT and its export keeps working."""
    from app.persistence.projects_repository import get_reference_by_template_source
    from app.services import project_library_service as pls

    uid = "u-par-unseeded"
    client, _seed = _project(uid, "generic_solar_reference", name="seed")
    ref = get_reference_by_template_source("generic_solar_reference")
    legacy = pls.create_working_copy(user_id=uid, source_reference_id=ref.project_id)
    _run(client, legacy.project_code)
    _make_pre_correction(uid, legacy)
    assert _state(client, legacy.project_code).lower().startswith("current")
    assert _export_inputs(uid, legacy) is not None
