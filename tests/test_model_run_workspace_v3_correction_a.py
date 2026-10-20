"""PR #331 Correction A: immutable Integrity, selector reliability and fail-closed numeric evidence."""
from __future__ import annotations

import copy
import json
import sqlite3
from types import SimpleNamespace

import pytest
from bs4 import BeautifulSoup

from app.persistence.run_history_repository import get_run_history_entry
from app.run_integrity import evidence_digest
from app.v2 import run_workspace_v3_projection as projection
from app.v2.run_workspace_v3_router import _history_side, _run_integrity_status
from tests.test_model_decision_support_v1 import two_runs, _history_ids  # noqa: F401

URL = "/v2/workbook/run-workspace-v3"
OWNER = "ds-user"


def _replace_stored_evidence(history_id, evidence):
    """Adversarial evidence mutation in isolated test DB only, never production."""
    from app.persistence import db
    with sqlite3.connect(db.DB_PATH) as con:
        con.execute(
            "UPDATE model_run_history SET integrity_evidence_json=? WHERE history_id=?",
            (json.dumps(evidence, sort_keys=True), history_id),
        )


def _selected_integrity(html):
    doc = BeautifulSoup(html, "html.parser")
    out = []
    for card in doc.select('[data-testid="rw-run-identity"] .v3-rw-identity'):
        definitions = [x.get_text(" ", strip=True) for x in card.select("dt")]
        values = [x.get_text(" ", strip=True) for x in card.select("dd")]
        out.append(dict(zip(definitions, values)).get("Integrity"))
    return out


def test_authentic_persisted_integrity_not_derived_from_credit_wrapper(two_runs):
    client, cookies, record, ids = two_runs
    entries = [get_run_history_entry(OWNER, record.project_id, history_id)
               for history_id in ids]
    expected = [_run_integrity_status(_history_side(entry)) for entry in entries]
    assert all(status in ("PASS", "FAIL", "INCOMPLETE") for status in expected)
    page = client.get(URL, params={"project": record.project_code,
                                   "run": ids, "reference": ids[-1]}, cookies=cookies)
    assert page.status_code == 200, page.text[:300]
    assert _selected_integrity(page.text) == expected


def test_persisted_failure_incomplete_and_missing_evidence_remain_distinct(two_runs):
    client, cookies, record, ids = two_runs
    entry = get_run_history_entry(OWNER, record.project_id, ids[-1])
    baseline = copy.deepcopy(entry.integrity_evidence)
    assert baseline.get("schema") == "RUN_INTEGRITY_EVIDENCE_V1"
    query = {"project": record.project_code, "run": ids, "reference": ids[-1]}

    # Tamper the committed payload without changing its digest: actual
    # authoritative EVIDENCE_DIGEST check must FAIL, not be inherited from Last.
    failed = copy.deepcopy(baseline)
    failed["digest"] = "wrong-committed-digest"
    _replace_stored_evidence(ids[-1], failed)
    resp = client.get(URL, params=query, cookies=cookies)
    assert resp.status_code == 200
    assert _selected_integrity(resp.text)[1] == "FAIL"

    # Valid schema, cryptographically resealed but incomplete source evidence:
    # its original check evaluator reports INCOMPLETE (not a fabricated PASS).
    incomplete = copy.deepcopy(baseline)
    incomplete.pop("senior_debt", None)
    incomplete["digest"] = evidence_digest(incomplete)
    _replace_stored_evidence(ids[-1], incomplete)
    resp = client.get(URL, params=query, cookies=cookies)
    assert resp.status_code == 200
    assert _selected_integrity(resp.text)[1] == "INCOMPLETE"

    # Missing or structurally malformed evidence is not a valid report.
    for evidence in ({}, {"schema": "FOREIGN"}, {"schema": "RUN_INTEGRITY_EVIDENCE_V1", "senior_debt": []}):
        _replace_stored_evidence(ids[-1], evidence)
        resp = client.get(URL, params=query, cookies=cookies)
        assert resp.status_code == 200
        assert _selected_integrity(resp.text)[1] in ("UNAVAILABLE", "INCOMPLETE")
        if not evidence or evidence.get("schema") != "RUN_INTEGRITY_EVIDENCE_V1":
            assert _selected_integrity(resp.text)[1] == "UNAVAILABLE"


def test_integrity_view_does_not_borrow_another_history_entries_evidence(two_runs):
    _, _, record, ids = two_runs
    entries = [get_run_history_entry(OWNER, record.project_id, rid) for rid in ids]
    first = _history_side(entries[0])
    second = _history_side(entries[1])
    first["integrity_evidence"] = {"schema": "FOREIGN"}
    # The evaluator must use the actual entry, not an unrelated side's payload.
    assert _run_integrity_status(first) == _run_integrity_status(_history_side(entries[0]))
    assert _run_integrity_status(second) == _run_integrity_status(_history_side(entries[1]))


def test_reference_options_are_only_selected_and_empty_slots_are_allowed(two_runs):
    client, cookies, record, ids = two_runs
    query = {"project": record.project_code, "run": [ids[1], "", ids[0]],
             "reference": ids[0]}
    resp = client.get(URL, params=query, cookies=cookies)
    assert resp.status_code == 200
    doc = BeautifulSoup(resp.text, "html.parser")
    slots = doc.select('select[name="run"]')
    ref_options = [x.get("value") for x in doc.select('select[name="reference"] option')]
    assert len(slots) == 3 and len(ref_options) == 2
    assert set(ref_options) == set(ids)
    assert doc.select_one('[data-testid="rw-reference"]').get("value") is None
    assert 'static/js/model_run_workspace_v3.js' in resp.text

    one = client.get(URL, params={"project": record.project_code, "run": ["", ids[1], ""]},
                     cookies=cookies)
    assert one.status_code == 200 and 'data-testid="rw-not-enough-runs"' in one.text
    blank = client.get(URL, params={"project": record.project_code,
                                    "run": ["", "", ""]}, cookies=cookies)
    assert blank.status_code == 200


def test_reference_and_duplicate_run_are_server_validated(two_runs):
    client, cookies, record, ids = two_runs
    assert client.get(URL, params={"project": record.project_code, "run": ids,
                 "reference": "foreign-id"}, cookies=cookies).status_code == 422
    assert client.get(URL, params={"project": record.project_code, "run": [ids[0], ids[0]]},
                      cookies=cookies).status_code == 422
    assert client.get(URL, params={"project": record.project_code,
                                    "run": ["last", ids[0]]}, cookies=cookies).status_code == 422
    assert client.get(URL, params={"project": record.project_code,
                                    "run": [ids[0], ids[1], "", ""]}, cookies=cookies).status_code == 422


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -float("inf"),
                                  10**600, -(10**600), 1e120, True, "bad"])
def test_huge_and_nonfinite_numeric_sources_are_unavailable(value):
    assert projection._finite(value) is None
    sides = [{"runtime_summary": {"total_capex_keur": value, "project_irr": 0.08},
              "debt_schedule": {}, "sponsor_schedule": {}},
             {"runtime_summary": {"total_capex_keur": 0.0, "project_irr": 0.09},
              "debt_schedule": {}, "sponsor_schedule": {}}]
    rows = {row["key"]: row for section in projection.build_kpi_sections(sides, 0)
            for row in section["rows"]}
    assert rows["total_capex_keur"]["values"][0] == "—"
    assert rows["total_capex_keur"]["deltas"][1] == "—"
    assert rows["project_irr"]["deltas"][1] == "+1.00 pp"


def test_malformed_credit_period_numeric_evidence_is_not_reconstructed(monkeypatch):
    from app.v2 import credit_decision_projection as credit
    monkeypatch.setattr(credit, "_timeline", lambda _inp: (_ for _ in ()).throw(OverflowError()))
    result = projection._period_evidence({"entry": SimpleNamespace(
        integrity_evidence={}, debt_schedule={}, distribution_schedule={}, sponsor_schedule={})})
    assert not result["valid"] and result["reason"] == "PERIOD_EVIDENCE_INVALID"


def test_invalid_statement_dates_and_giant_cells_never_become_financial_values(monkeypatch):
    import app.v2.statement_presentation as statements
    fake_tables = [{"id": "pnl", "columns": [
        {"date": "2035-06-30"}, {"date": "2035-06"}, {"date": "2035-12-31"},
    ], "rows": [{"key": "revenues_keur", "cells": [
        {"v": 10**600}, {"v": 200.0}, {"v": 500.0},
    ]}]}]
    monkeypatch.setattr(statements, "statements_from_run", lambda *_args: fake_tables)
    source = {"entry": None, "financial_statements": {}, "runtime_summary": {}}
    rows = projection._statement_rows(source)
    assert rows["2035-06-30"]["statement:pnl:revenues_keur"] is None
    assert "2035-06" not in rows
    assert rows["2035-12-31"]["statement:pnl:revenues_keur"] == 500.0
