"""Workflow A — the CAPEX / OPEX sheet totals a user sees equal the canonical inputs
the Run uses, for every technology, at reference and non-reference capacity, before and
after a line edit and a deactivate / reactivate cycle (no hidden edit leaves a total
unchanged, no total disagrees with the model)."""
from __future__ import annotations

import re

import pytest

from tests.test_cost_workspace_consistency_v1 import (  # noqa: F401
    HX, TECHNOLOGIES, _cost_workspace_executor_cleanup, _canonical_total, _line_fields, _page,
    _post, _project, _row, _seeded_line, seeded_db,
)


def _canonical_total(uid, rec, kind):  # noqa: F811  (OPEX shown INCLUDING the engine's B.13 rule)
    from tests.test_cost_workspace_consistency_v1 import _canonical_total as base_total

    total = base_total(uid, rec, kind)
    if kind != "opex":
        return total
    from app.persistence.workspace_repository import get_workspace_state
    from app.services.opex_sub_lines_integration import apply_user_sub_lines_to_opex
    from app.workbook.service import WorkbookService

    ws = get_workspace_state(uid, rec.project_id)
    pi = WorkbookService.to_projectinputs(WorkbookService.build_draft_input_set_from_workspace(ws))
    items = apply_user_sub_lines_to_opex(pi.opex, project_id=rec.project_id, scenario_overrides=None)
    fixed = sum(float(i.y1_amount_keur) for i in items if not i.percentage_of_opex)
    return fixed + sum(float(i.percentage_of_opex) * fixed for i in items if i.percentage_of_opex)


def _sheet_total(client, code, kind):
    """The total exactly as the sheet shows it (no adjustment)."""
    pg = client.get(f"/v2/workbook?project={code}").text
    pat = (r'data-testid="total-capex-keur">\s*([\d,\.]+)' if kind == "capex"
           else r'data-testid="opex-y1-total">\s*([\d,\.]+)')
    return float(re.search(pat, pg).group(1).replace(",", ""))


@pytest.mark.parametrize("capacity", [20.0, 40.0])
@pytest.mark.parametrize("kind", ["capex", "opex"])
@pytest.mark.parametrize("template", TECHNOLOGIES)
def test_sheet_total_equals_canonical_input_total(seeded_db, template, kind, capacity):
    uid = f"u-rec-{template[8:12]}-{kind}-{int(capacity)}"
    client, rec = _project(uid, template, capacity=capacity)
    canon = _canonical_total(uid, rec, kind)
    shown = _sheet_total(client, rec.project_code, kind)
    # CAPEX shows rounded grouped kEUR; OPEX shows whole kEUR
    assert shown == pytest.approx(canon, abs=1.0), (template, kind, capacity, shown, canon)


@pytest.mark.parametrize("kind", ["capex", "opex"])
@pytest.mark.parametrize("template", TECHNOLOGIES)
def test_edit_and_lifecycle_keep_the_sheet_equal_to_canonical(seeded_db, template, kind):
    uid = f"u-rec2-{template[8:12]}-{kind}"
    client, rec = _project(uid, template)
    sid = _seeded_line(rec.project_id, kind)
    amount = float(_row(rec.project_id, sid, kind)["amount_keur"])
    f = _line_fields(client, rec, kind, sid)
    data = dict(f, label=_row(rec.project_id, sid, kind)["label"], amount_keur=str(amount + 7), notes="")
    if kind == "opex":
        data["inflation_pct"] = str(_row(rec.project_id, sid, kind)["inflation_pct"])
    assert _post(client, kind, "update", **data).status_code == 200
    assert _sheet_total(client, rec.project_code, kind) == pytest.approx(
        _canonical_total(uid, rec, kind), abs=1.0)
    assert _post(client, kind, "deactivate", **_line_fields(client, rec, kind, sid)).status_code == 200
    assert _sheet_total(client, rec.project_code, kind) == pytest.approx(
        _canonical_total(uid, rec, kind), abs=1.0)
    assert _post(client, kind, "reactivate", **_line_fields(client, rec, kind, sid)).status_code == 200
    assert _sheet_total(client, rec.project_code, kind) == pytest.approx(
        _canonical_total(uid, rec, kind), abs=1.0)


def test_data_center_b08_power_follows_project_capacity_not_the_template(seeded_db):
    """B.08 is derived from IT MW: at 40 MW the sheet must show the Run's amount, which is
    twice the 20 MW reference amount (previously the sheet kept the reference figure)."""
    client_a, rec_a = _project("u-dc-20", "generic_data_center_reference", capacity=20.0)
    client_b, rec_b = _project("u-dc-40", "generic_data_center_reference", capacity=40.0)

    def b08(client, code):
        pg = client.get(f"/v2/workbook?project={code}").text
        return float(re.search(r'data-testid="opex-subtotal-B.08"[^>]*>\s*([\d,\.]+)', pg)
                     .group(1).replace(",", ""))

    p20, p40 = b08(client_a, rec_a.project_code), b08(client_b, rec_b.project_code)
    assert p40 == pytest.approx(2 * p20, rel=1e-3)
