"""The F3 financial-evidence tool reproduces Solar and Wind from canonical Runs and every reconciliation holds."""
import json
import os

import pytest

from tools import model_financing_f3_evidence as tool


@pytest.fixture
def evidence(tmp_path, monkeypatch):
    monkeypatch.setenv("FINCO_MODEL_EXECUTION_MODE", "thread")
    out = tmp_path / "financial-evidence.json"
    monkeypatch.setattr("sys.argv", ["tool", "--out", str(out)])
    rc = tool.main()
    return rc, json.loads(out.read_text(encoding="utf-8"))


def test_solar_and_wind_reconcile_from_canonical_runs(evidence):
    rc, payload = evidence
    assert rc == 0 and payload["all_cases_pass"] is True
    assert {c["project_code"] for c in payload["cases"]} == {"f3-evidence-solar", "f3-evidence-wind"}
    for case in payload["cases"]:
        assert case["all_reconciliations_pass"] is True
        assert len(case["reconciliations"]) >= 25
        assert not [r for r in case["reconciliations"] if not r["pass"]]
