"""PR-U2b: OPEX Years per saved line — read-only, lineage to saved rows, reconciles with the existing group projection; nothing written.

Independent oracle: each saved line's yearly value is recomputed here as ``y1 * (1 + inflation/100) ** (t - 1)`` from the SAVED line (the
cost-line ledger), not from the view model the route passes through; group rows and totals must equal the existing group adapter exactly.
"""
from __future__ import annotations

import math

import pytest

from tests.test_model_react_wf2_projections_v1 import OWNER, costlines, env  # noqa: F401  (shared real-app fixture)

KINDS = ["solar", "wind", "data_center", "ev_charging"]


def _lines(env, record):
    return env.client.get("/v2/model-react/opex-projection/lines", params={"project": record.project_code})


def _groups(env, record):
    return env.client.get("/v2/model-react/opex-projection", params={"project": record.project_code}).json()


def _create(env, kind):
    try:
        return env.create(kind)
    except Exception as exc:  # pragma: no cover - a vertical this fixture cannot create is reported, not hidden
        pytest.fail(f"{kind}: reference project could not be created: {exc!r}")


@pytest.mark.parametrize("kind", KINDS)
def test_every_listed_line_is_a_saved_active_line_and_matches_an_independent_escalation(env, kind):
    record = _create(env, kind)
    payload = _lines(env, record).json()
    assert payload["ok"] is True and payload["unit"] == "kEUR"
    years = payload["years"]
    saved = {l["sub_line_id"]: l for l in costlines(env, record, "opex")["lines"] if l.get("active", True)}
    listed = [row for g in payload["groups"] for row in g["lines"]]
    assert listed, "a reference project has saved OPEX lines"
    for row in listed:
        assert row["source"] == "saved_line" and row["sub_line_id"] in saved, row                     # lineage: only saved rows
        src = saved[row["sub_line_id"]]
        y1, infl = float(src["amount_keur"]), float(src["inflation_pct"] or 0.0)
        expected = [y1 * (1 + infl / 100.0) ** (t - 1) for t in years]
        assert all(math.isclose(a, b, rel_tol=1e-12, abs_tol=1e-9) for a, b in zip(row["values"], expected)), (row["label"], row["values"][:3], expected[:3])
    contingency_codes = {g["code"] for g in payload["groups"] if g["derived"]}
    listed_ids = {r["sub_line_id"] for r in listed}
    for sid, line in saved.items():                       # every saved active non-contingency line is listed exactly once
        if line.get("category") not in contingency_codes:
            assert sid in listed_ids, line["label"]
    assert len(listed_ids) == len(listed)


@pytest.mark.parametrize("kind", KINDS)
def test_group_rows_and_totals_equal_the_existing_group_projection_and_lines_reconcile(env, kind):
    record = _create(env, kind)
    lines, groups = _lines(env, record).json(), _groups(env, record)
    by_code = {r["code"]: r for r in groups["rows"]}
    for g in lines["groups"]:
        assert g["values"] == by_code[g["code"]]["values"], g["code"]
        if not g["derived"] and g["has_data"]:
            assert g["reconciles"] is True, (kind, g["code"], g["values"][:2])
    assert lines["totals"] == groups["totals"] and lines["contingency"] == groups["contingency"]


@pytest.mark.parametrize("kind", ["solar", "wind"])
def test_bases_are_listed_separately_and_equal_the_costlines_bases(env, kind):
    record = _create(env, kind)
    payload = _lines(env, record).json()
    assert payload["bases"] == costlines(env, record, "opex")["projection"]["bases"]
    assert "do not" in payload["basis"] and "Run adds them" in payload["basis"]                 # never presented as all-in OPEX


def test_data_center_power_expenses_is_a_driver_row_not_a_saved_line(env):
    record = _create(env, "data_center")
    payload = _lines(env, record).json()
    b08 = next(g for g in payload["groups"] if g["code"] == "B.08")
    assert b08["drivers"] and all(d["source"] == "technology_driver" for d in b08["drivers"]) and not b08["lines"]


def test_added_line_appears_retired_line_disappears_and_the_read_changes_nothing(env):
    from app.v2 import opex_commands
    from app.workbook.registry import WORKBOOK
    from app.workbook.workbook_identity import assemble_consistent_for_get

    record = _create(env, "wind")
    h = assemble_consistent_for_get(OWNER, record.project_id, WORKBOOK.version).composite_hash
    line, _ = opex_commands.add_opex_line(project_record=record, user_id=OWNER, label="Synthetic patrol", parent_group_code="B.05",
                                          amount_keur=12.0, inflation_pct=3.0, notes="", workbook_version=WORKBOOK.version, expected_content_hash=h)
    before = costlines(env, record, "opex")["save"]["content_hash"]
    payload = _lines(env, record).json()
    b05 = next(g for g in payload["groups"] if g["code"] == "B.05")
    row = next(r for r in b05["lines"] if r["sub_line_id"] == line.sub_line_id)
    assert row["values"][:2] == [12.0, 12.0 * 1.03] and b05["reconciles"] is True
    assert costlines(env, record, "opex")["save"]["content_hash"] == before                    # a read, nothing written
    h2 = assemble_consistent_for_get(OWNER, record.project_id, WORKBOOK.version).composite_hash
    opex_commands.deactivate_opex_line(project_record=record, user_id=OWNER, sub_line_id=line.sub_line_id,
                                       row_version=line.updated_at, workbook_version=WORKBOOK.version, expected_content_hash=h2)
    after = _lines(env, record).json()
    assert all(r["sub_line_id"] != line.sub_line_id for g in after["groups"] for r in g["lines"])


def test_owner_scoping_and_flag(env, monkeypatch):
    record = _create(env, "solar")
    assert env.stranger.get("/v2/model-react/opex-projection/lines", params={"project": record.project_code}).status_code == 404
    monkeypatch.setenv("FINCO_MODEL_REACT_V1", "0")
    assert _lines(env, record).status_code == 404


@pytest.mark.parametrize("kind", KINDS)
def test_authenticated_read_only_no_provenance_and_no_all_in_figure(env, kind):
    """The route needs a session, accepts GET only, carries no source provenance, and never states an all-in OPEX total."""
    from fastapi.testclient import TestClient

    from app.cost_line_ledger.projection import assert_no_source_provenance

    record = _create(env, kind)
    anon = TestClient(env.client.app).get("/v2/model-react/opex-projection/lines", params={"project": record.project_code})
    assert anon.status_code == 401 and anon.json()["code"] == "AUTH_REQUIRED"
    for method in ("post", "put", "patch", "delete"):
        assert getattr(env.client, method)("/v2/model-react/opex-projection/lines", params={"project": record.project_code}).status_code == 405, method
    payload = _lines(env, record).json()
    assert_no_source_provenance(payload)                                                       # raises on any source / workbook provenance key
    keys = set()

    def walk(o):
        if isinstance(o, dict):
            keys.update(o)
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)
    walk(payload)
    assert not {k for k in keys if "all_in" in k or "including_bases" in k}, keys                # no all-in OPEX aggregate
    assert set(payload["totals"]) == {"excluding_contingency", "including_contingency"}         # the existing line-item totals only
