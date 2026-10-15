"""Regenerates the WF-A credit matrices from real committed Runs (opt-in: ``WFA_REPORT_DIR=<dir>``).

Run: ``WFA_REPORT_DIR=/tmp/out pytest tests/wfa_generate_reports.py``.  Skipped otherwise, so CI never depends on it.
"""
import json
import os
from decimal import Decimal
from pathlib import Path

import pytest

from tests import wfa_matrix as W
from tests import wfa_support as S
from tools.numerical_validation import credit_matrix as M

OUT = os.environ.get("WFA_REPORT_DIR")
pytestmark = pytest.mark.skipif(not OUT, reason="opt-in report generation")


@pytest.fixture(scope="module")
def lab(tmp_path_factory):
    lab = S.make_lab(tmp_path_factory, "wfareport")
    yield lab
    lab.patch.undo()


@pytest.mark.parametrize("kind,full", [("solar", True), ("wind", False), ("data_center", False), ("ev_charging", False)])
def test_generate(lab, kind, full):
    cases = W._cases(lab, kind, full)
    matrix = W.assemble(cases, kind)
    matrix["boundary"] = [{k: (str(v) if isinstance(v, Decimal) else v) for k, v in r.items()} for r in W.boundary_rows(cases)]
    out = Path(OUT)
    out.mkdir(parents=True, exist_ok=True)
    for name, data in M.render(matrix).items():
        (out / f"{kind}_{name}").write_bytes(data)
    (out / f"{kind}_summary.json").write_text(json.dumps(
        {"metric_counts": matrix["metric_counts"], "directional_counts": matrix["directional_counts"],
         "committed": sum(c.committed for c in cases.values()), "total": len(cases),
         "uncommitted": [{"case": c.label, "reason": c.reason} for c in cases.values() if not c.committed]}, indent=1, default=str))
    assert matrix["metric_counts"]["FAIL"] == 0, matrix["metric_counts"]


def test_credit_coverage(lab):
    """CR-* (and the debt/cfads identities they sit beside) per vertical, rendered through the shared coverage tooling."""
    from tests import wfa_cases as C
    from tools.numerical_validation import coverage
    results = {}
    for kind in ("solar", "wind", "data_center", "ev_charging"):
        case = C.build_case(lab, kind, "cov", "combined", "baseline")
        assert case.committed, case.reason
        results[f"{kind}/baseline"] = case.result
    matrix = coverage.build_matrix(results)
    matrix["identities"] = {k: v for k, v in matrix["identities"].items() if k.startswith(("CR-", "DEBT-", "FT-"))}
    out = Path(OUT)
    out.mkdir(parents=True, exist_ok=True)
    (out / "credit_coverage.json").write_bytes(coverage.to_json(matrix))
    (out / "credit_coverage.md").write_bytes(coverage.to_markdown(matrix))
    assert not matrix["configurations_with_fail"]
