"""OPEX B.13 contingency truthfulness for seeded projects.

Authority trace (verified here):
  * The Solar / Wind reference ProjectInputs and the seeded user ProjectInputs contain NO
    contingency item - the 2 % / 6 % figures are presentation constants for the reference
    models, i.e. an informational estimate that the Run never applies.
  * A typed B.13 % (project value or scenario override) is the only thing that puts a
    ``percentage_of_opex`` item into the Run's inputs.
The sheet must therefore (a) show canonical OPEX that equals the Run's effective inputs,
(b) show the reference estimate separately as NOT applied, and (c) include contingency
only when it is really applied.
"""
from __future__ import annotations

import re

import pytest

from tests.test_cost_workspace_consistency_v1 import (  # noqa: F401
    HX, TECHNOLOGIES, _cost_workspace_executor_cleanup, _line_fields, _page, _post, _project,
    _run, _seeded_line, _state, seeded_db,
)
from tests.test_cost_workspace_parity_v1 import (  # noqa: F401
    _assert_full_parity, _export_inputs, _scenario_with, captured_run,
)
from app.contingency_authority import SCENARIO_OVERRIDE_KEY

SOLAR_WIND = ["generic_solar_reference", "generic_wind_reference"]


def _page_text(client, code):
    return client.get(f"/v2/workbook?project={code}").text


def _sheet_opex_y1(pg):
    return float(re.search(r'data-testid="opex-y1-total">\s*([\d,\.]+)', pg).group(1).replace(",", ""))


def _effective_run_items(uid, rec, scenario_overrides=None):
    """The OPEX items the Run is handed (same fold as the Run)."""
    from app.persistence.workspace_repository import get_workspace_state
    from app.services.opex_sub_lines_integration import apply_user_sub_lines_to_opex
    from app.workbook.service import WorkbookService

    ws = get_workspace_state(uid, rec.project_id)
    pi = WorkbookService.to_projectinputs(WorkbookService.build_draft_input_set_from_workspace(ws))
    return apply_user_sub_lines_to_opex(pi.opex, project_id=rec.project_id,
                                        scenario_overrides=scenario_overrides)


def _y1_incl_contingency(items):
    fixed = sum(float(i.y1_amount_keur) for i in items if not i.percentage_of_opex)
    return fixed * (1.0 + sum(float(i.percentage_of_opex) for i in items if i.percentage_of_opex))


def _set_typed_b13(uid, rec, pct):
    from app.persistence.projects_repository import get_project_by_id
    from app.v2.capex_commands import set_contingency_percentage
    from app.workbook.registry import WORKBOOK
    from app.workbook.workbook_identity import assemble_consistent_for_get

    h = assemble_consistent_for_get(uid, rec.project_id, WORKBOOK.version).composite_hash
    set_contingency_percentage(
        project_record=get_project_by_id(rec.project_id), user_id=uid, kind="opex", pct=pct,
        workbook_version=WORKBOOK.version, expected_content_hash=h)


@pytest.mark.parametrize("template", SOLAR_WIND)
def test_reference_estimate_is_shown_separately_and_not_in_the_total(seeded_db, captured_run, template):
    uid = f"u-b13-none-{template[8:12]}"
    client, rec = _project(uid, template)
    items = _effective_run_items(uid, rec)
    assert not [i for i in items if i.percentage_of_opex]            # authority: nothing applied
    pg = _page_text(client, rec.project_code)
    assert _sheet_opex_y1(pg) == pytest.approx(_y1_incl_contingency(items), abs=0.51)
    note = re.search(r'data-testid="opex-reference-contingency-note">(.*?)</p>', pg, re.S)
    assert note and "not applied" in note.group(1) and "excluded" in note.group(1)
    assert "(incl. contingency)" not in pg
    # the Run gets exactly what the sheet shows
    _run(client, rec.project_code)
    assert sum(float(i.y1_amount_keur) for i in captured_run["inputs"].opex) == pytest.approx(
        _sheet_opex_y1(pg), abs=0.51)
    assert not [i for i in captured_run["inputs"].opex if i.percentage_of_opex]


@pytest.mark.parametrize("template", SOLAR_WIND)
def test_explicit_typed_b13_is_applied_and_shown_as_included(seeded_db, captured_run, template):
    uid = f"u-b13-typed-{template[8:12]}"
    client, rec = _project(uid, template)
    _set_typed_b13(uid, rec, 5.0)
    items = _effective_run_items(uid, rec)
    assert [i.percentage_of_opex for i in items if i.percentage_of_opex] == [0.05]
    pg = _page_text(client, rec.project_code)
    assert _sheet_opex_y1(pg) == pytest.approx(_y1_incl_contingency(items), abs=0.51)
    assert "opex-reference-contingency-note" not in pg               # nothing is "not applied"
    assert "(incl. contingency)" in pg
    _run(client, rec.project_code)
    run_items = captured_run["inputs"].opex
    assert [i.percentage_of_opex for i in run_items if i.percentage_of_opex] == [0.05]
    assert _y1_incl_contingency(run_items) == pytest.approx(_sheet_opex_y1(pg), abs=0.51)
    _assert_full_parity(captured_run["inputs"], _export_inputs(uid, rec))   # export parity unchanged


@pytest.mark.parametrize("template", ["generic_data_center_reference", "generic_ev_charging_reference"])
def test_data_center_and_ev_are_unchanged(seeded_db, template):
    uid = f"u-b13-other-{template[8:12]}"
    client, rec = _project(uid, template)
    pg = _page_text(client, rec.project_code)
    assert "opex-reference-contingency-note" not in pg
    items = _effective_run_items(uid, rec)
    assert _sheet_opex_y1(pg) == pytest.approx(_y1_incl_contingency(items), abs=0.51)


@pytest.mark.parametrize("template", SOLAR_WIND)
def test_deactivate_reactivate_before_and_after_run_keep_sheet_equal_to_the_run(
        seeded_db, captured_run, template):
    uid = f"u-b13-cycle-{template[8:12]}"
    client, rec = _project(uid, template)
    sid = _seeded_line(rec.project_id, "opex")

    def check():
        pg = _page_text(client, rec.project_code)
        assert _sheet_opex_y1(pg) == pytest.approx(
            _y1_incl_contingency(_effective_run_items(uid, rec)), abs=0.51)
        return _sheet_opex_y1(pg)

    base = check()
    assert _post(client, "opex", "deactivate", **_line_fields(client, rec, "opex", sid)).status_code == 200
    reduced = check()
    assert reduced < base
    _run(client, rec.project_code)                                   # Run with the line inactive
    assert sum(float(i.y1_amount_keur) for i in captured_run["inputs"].opex) == pytest.approx(reduced, abs=0.51)
    assert _post(client, "opex", "reactivate", **_line_fields(client, rec, "opex", sid)).status_code == 200
    assert check() == pytest.approx(base, abs=0.51)
    _run(client, rec.project_code)                                   # and after reactivation
    assert sum(float(i.y1_amount_keur) for i in captured_run["inputs"].opex) == pytest.approx(base, abs=0.51)
    _assert_full_parity(captured_run["inputs"], _export_inputs(uid, rec))


@pytest.mark.parametrize("template", SOLAR_WIND)
def test_scenario_b13_override_is_applied_to_sheet_and_run(seeded_db, captured_run, template):
    uid = f"u-b13-scen-{template[8:12]}"
    client, rec = _project(uid, template)
    _scenario_with(client, rec, uid, {SCENARIO_OVERRIDE_KEY: {"opex": 3.0}})
    sc_items = _effective_run_items(uid, rec, scenario_overrides={SCENARIO_OVERRIDE_KEY: {"opex": 3.0}})
    assert [i.percentage_of_opex for i in sc_items if i.percentage_of_opex] == [0.03]
    pg = _page_text(client, rec.project_code)
    assert _sheet_opex_y1(pg) == pytest.approx(_y1_incl_contingency(sc_items), abs=0.51)
    assert "opex-reference-contingency-note" not in pg
    _run(client, rec.project_code)
    assert [i.percentage_of_opex for i in captured_run["inputs"].opex if i.percentage_of_opex] == [0.03]
    _assert_full_parity(captured_run["inputs"], _export_inputs(uid, rec))


@pytest.mark.parametrize("key,factory", [("Generic Wind Reference", "create_generic_wind_reference"),
                                         ("Generic Solar Reference", "create_generic_solar_reference")])
def test_engine_applies_no_contingency_to_the_reference_unless_it_is_typed(key, factory):
    """The authority fact behind the presentation rule: the factory reference run equals a run
    on its own items (no hidden contingency), and an explicit 6 % adds exactly 6 % OPEX."""
    import dataclasses

    from app import project_factories
    from app.api.project_runner import run_project
    from app.contingency_authority import apply_opex_contingency

    pi = getattr(project_factories, factory)()
    assert not [i for i in pi.opex if i.percentage_of_opex]
    plain = run_project(key, "Base")["kpis"]["total_opex_keur"]
    same = run_project(key, "Base", project_inputs_override=pi)["kpis"]["total_opex_keur"]
    typed = run_project(key, "Base", project_inputs_override=dataclasses.replace(
        pi, opex=apply_opex_contingency(pi.opex, 6.0)))["kpis"]["total_opex_keur"]
    assert plain == pytest.approx(same)
    assert typed == pytest.approx(same * 1.06, rel=1e-6)
