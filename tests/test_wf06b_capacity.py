"""WF-06B: read-only "per MW" figures and the Senior-debt source.

One stored amount per line (kEUR). Per-MW is a read-only division by the saved installed capacity, with an explicit basis; it fails
closed (no figure, with a reason) when the capacity is missing / zero / invalid or when the basis would be ambiguous (AC vs DC).
"""
from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.cost_line_ledger.capacity import CAPACITY_FIELD_ID, attach_per_mw, capacity_basis, per_mw_keur
from tests.test_model_react_wf2_projections_v1 import env, costlines  # noqa: F401  (shared real-app fixture)


def test_100_mw_and_1000_keur_is_10_keur_per_mw_and_10000_eur_per_mw():
    basis = capacity_basis("solar", "100")
    assert basis["available"] and basis["mw"] == "100" and basis["source_field"] == CAPACITY_FIELD_ID
    assert per_mw_keur("1000", basis) == "10"
    assert Decimal(per_mw_keur("1000", basis)) * 1000 == Decimal(10000)          # EUR/MW is the same figure shifted by 10^3 (display unit only)
    assert per_mw_keur(1000.5, basis) == "10.005" and per_mw_keur("0", basis) == "0"
    assert per_mw_keur("1", capacity_basis("wind", "3")) == "0.333333"            # bounded scale, no float artefacts


@pytest.mark.parametrize("raw,reason", [(None, "MISSING"), ("", "MISSING"), (0, "INVALID"), ("0", "INVALID"), (-5, "INVALID"),
                                         ("abc", "INVALID"), ("nan", "INVALID"), ("inf", "INVALID"), (True, "INVALID")])
def test_missing_zero_or_invalid_capacity_means_no_per_mw_figure(raw, reason):
    basis = capacity_basis("solar", raw)
    assert basis["available"] is False and basis["reason"] == reason and basis["note"] and basis["mw"] is None
    assert per_mw_keur("1000", basis) is None


def test_other_project_types_have_no_per_mw_basis():
    for kind in ("storage", "data_center", "bess", ""):
        assert capacity_basis(kind, "50")["reason"] == "UNSUPPORTED"


def test_two_capacity_quantities_for_the_technology_would_be_ambiguous_and_fail_closed(monkeypatch):
    from app.cost_line_ledger import capacity as mod

    monkeypatch.setattr(mod, "_capacity_fields_in_registry", lambda: [CAPACITY_FIELD_ID, "project_setup.technical.dc_capacity_mw"])
    basis = capacity_basis("solar", "100")
    assert basis["available"] is False and basis["reason"] == "AMBIGUOUS"
    monkeypatch.setattr(mod, "_capacity_fields_in_registry", lambda: [])
    assert capacity_basis("wind", "100")["reason"] == "AMBIGUOUS"


def test_the_registry_really_has_exactly_one_installed_capacity_in_mw():
    from app.cost_line_ledger.capacity import _capacity_fields_in_registry

    assert _capacity_fields_in_registry() == [CAPACITY_FIELD_ID]


def test_attach_adds_only_per_mw_and_the_basis_and_never_changes_an_amount():
    projection = {"lines": [{"sub_line_id": "a", "amount_keur": 1000.0}, {"sub_line_id": "b", "amount_keur": None}]}
    before = [dict(l) for l in projection["lines"]]
    attach_per_mw(projection, "opex", capacity_basis("wind", "100"))
    assert [l["amount_keur"] for l in projection["lines"]] == [l["amount_keur"] for l in before]
    assert [l["per_mw_keur"] for l in projection["lines"]] == ["10", None]
    assert projection["capacity"]["time_basis"] == "per year" and projection["capacity"]["available"] is True
    capex = {"lines": [{"sub_line_id": "a", "amount_keur": 5}]}
    attach_per_mw(capex, "capex", capacity_basis("solar", None))
    assert capex["lines"][0]["per_mw_keur"] is None and capex["capacity"]["time_basis"] is None and capex["capacity"]["reason"] == "MISSING"


@pytest.mark.parametrize("kind", ["solar", "wind"])
@pytest.mark.parametrize("sheet", ["capex", "opex"])
def test_route_per_mw_is_the_saved_amount_over_the_saved_capacity(env, kind, sheet):
    record = env.create(kind)
    payload = costlines(env, record, sheet)
    proj = payload["projection"]
    capacity = proj["capacity"]
    assert capacity["available"] is True and capacity["source_field"] == CAPACITY_FIELD_ID and capacity["technology"] == kind
    mw = Decimal(capacity["mw"])
    assert mw > 0
    assert capacity["time_basis"] == ("per year" if sheet == "opex" else None)
    checked = 0
    for line in proj["lines"]:
        if line["amount_keur"] is None:
            assert line["per_mw_keur"] is None
            continue
        expected = (Decimal(str(line["amount_keur"])) / mw).quantize(Decimal("0.000001")).normalize()
        assert Decimal(line["per_mw_keur"]) == expected, (line["sub_line_id"], line["per_mw_keur"], expected)
        checked += 1
    assert checked > 5
    assert [l["amount_keur"] for l in proj["lines"]] == [l["amount_keur"] for l in payload["lines"]]     # amounts untouched


def test_route_fails_closed_when_the_capacity_is_zero_or_unreadable(env, monkeypatch):
    from app.workbook.service import WorkbookService

    record = env.create("solar")
    real = WorkbookService.build_draft_input_set_from_workspace

    def zero(ws):
        pis = real(ws)
        return SimpleNamespace(get=lambda fid: 0 if fid == CAPACITY_FIELD_ID else pis.get(fid))

    monkeypatch.setattr(WorkbookService, "build_draft_input_set_from_workspace", staticmethod(zero))
    proj = costlines(env, record, "capex")["projection"]
    assert proj["capacity"]["available"] is False and proj["capacity"]["reason"] == "INVALID"
    assert all(l["per_mw_keur"] is None for l in proj["lines"])

    def boom(ws):
        raise RuntimeError("unreadable")

    monkeypatch.setattr(WorkbookService, "build_draft_input_set_from_workspace", staticmethod(boom))
    proj = costlines(env, record, "capex")["projection"]
    assert proj["capacity"]["available"] is False and all(l["per_mw_keur"] is None for l in proj["lines"])


def test_senior_debt_comes_only_from_the_persisted_run_and_is_absent_otherwise():
    from app.v2.react_workspace_router import _senior_debt_metric

    run = SimpleNamespace(runtime_summary={"senior_debt_keur": 61234.5}, debt_schedule={}, sponsor_schedule={})
    assert _senior_debt_metric(run) == {"available": True, "value_keur": 61234.5, "reason": ""}
    for missing in (SimpleNamespace(runtime_summary={}, debt_schedule={}, sponsor_schedule={}),
                    SimpleNamespace(runtime_summary={"senior_debt_keur": "61,234"}, debt_schedule={}, sponsor_schedule={}),
                    SimpleNamespace(runtime_summary={"senior_debt_keur": None}, debt_schedule={}, sponsor_schedule={})):
        out = _senior_debt_metric(missing)
        assert out["available"] is False and out["value_keur"] is None and out["reason"]
    zero = _senior_debt_metric(SimpleNamespace(runtime_summary={"senior_debt_keur": 0.0}, debt_schedule={}, sponsor_schedule={}))
    assert zero["available"] is True and zero["value_keur"] == 0.0, "a genuine zero is a value, not an absence"
    broken = _senior_debt_metric(object())
    assert broken["available"] is False and broken["value_keur"] is None


@pytest.mark.parametrize("kind", ["solar", "wind"])
def test_real_committed_run_publishes_senior_debt_exactly_as_persisted_and_no_run_means_none(env, kind):
    from tests.test_pr394_staging_corrections_v1 import run_json

    record = env.create(kind)
    before = env.client.get("/v2/model-react/statements", params={"project": record.project_code}).json()
    assert before["state"] == "NOT_RUN" and not (before["results"].get("senior_debt") or {}).get("available")
    response = run_json(env, record)
    assert response.status_code == 200 and response.json()["outcome"] == "COMMITTED"
    from app.persistence.run_history_repository import get_latest_history_entry

    persisted = get_latest_history_entry(record.user_id, record.project_id).to_dict()["runtime_summary"].get("senior_debt_keur")
    after = env.client.get("/v2/model-react/statements", params={"project": record.project_code}).json()["results"]["senior_debt"]
    if isinstance(persisted, (int, float)) and not isinstance(persisted, bool):
        assert after["available"] is True and after["value_keur"] == float(persisted)
    else:
        assert after["available"] is False and after["value_keur"] is None
