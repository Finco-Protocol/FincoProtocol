"""WF-D RC-7: actual committed Solar/Wind Run risk evidence (no production writes)."""
from __future__ import annotations

import pytest

from tests.test_model_credit_decision_v3_real_runs import cenv, credit, history, last  # noqa: F401
from tests.test_model_decision_workspace_v2 import env  # noqa: F401
from tests.test_model_financing_f2 import run, save, config

USER = "decision-user"


@pytest.mark.parametrize("kind", ["solar", "wind"])
def test_real_committed_run_v4_keeps_history_and_discloses_unavailable_policy(cenv, kind):
    record = cenv.create(kind)
    run(cenv, record)
    before = tuple(x.history_id for x in history(record))
    response, data = credit(cenv, record)
    assert response.status_code == 200
    assert 'data-testid="cd-v4-risk"' in response.text
    assert data["credit_v4"]["schema"] == "RC7_CREDIT_DECISION_V4_READONLY"
    assert len(data["credit_v4"]["run_risks"]) == 1
    assert data["credit_v4"]["run_risks"][0]["history_id"] == before[0]
    assert "CURRENT" in data["credit_v4"]["run_risks"][0]["state"]
    assert {x["metric"] for x in data["credit_v4"]["unavailable"]} >= {"PLCR", "Contractual covenant/default"}
    assert tuple(x.history_id for x in history(record)) == before


def test_real_historical_unchanged_and_current_stale_credit_risk_keeps_identity(cenv):
    record = cenv.create("solar")
    run(cenv, record)
    first = last(record)
    # Existing supported edit produces a STALE last Run without overwriting immutable evidence.
    response = save(cenv, record, config(lender_case="P90-10y"))
    assert response.status_code == 200
    _, stale = credit(cenv, record, first.history_id)
    assert stale["runs"][0]["identity"]["state"] == "LAST RUN · STALE"
    assert stale["credit_v4"]["run_risks"][0]["history_id"] == first.history_id
    assert stale["credit_v4"]["run_risks"][0]["state"] == "LAST RUN · STALE"
    assert stale["runs"][0]["structure"]["lender_case"]["value"]["v"] is None
    assert tuple(x.history_id for x in history(record)) == (first.history_id,)


def test_real_two_committed_runs_compare_exact_dates_only(cenv):
    record = cenv.create("solar")
    run(cenv, record)
    first = last(record)
    response = save(cenv, record, config(lender_case="P90-10y"))
    assert response.status_code == 200
    run(cenv, record)
    second = last(record)
    assert first.history_id != second.history_id
    _, data = credit(cenv, record, first.history_id, second.history_id)
    out = data["credit_v4"]["period_comparison"]
    # RC-7B Correction B: two real 6/6 Runs on the SAME committed axis have proven identical intervals (each period starts at the committed
    # previous period end), so the valid historical comparison is preserved and nothing is reported NOT_COMPARABLE.
    assert out["available"] and out["not_comparable_count"] == 0, out
    columns = data["runs"][0]["timeline"]["columns"]
    assert all(c["start"] is None or c["start"] < c["date"] for c in columns)
    assert any(c["start"] for c in columns)
    if out["available"]:
        assert out["common_periods"] > 0
        assert all(row["date"].count("-") == 2 for row in out["rows"])
        assert all(row["state"] in ("CHANGED", "UNAVAILABLE") for row in out["rows"])
    # The historical lender case is still unavailable (not persisted with Run).
    assert data["runs"][0]["structure"]["lender_case"]["value"]["v"] is None
    assert {x.history_id for x in history(record)} >= {first.history_id, second.history_id}
