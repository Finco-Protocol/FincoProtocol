"""WF-React-1 — static product-truth guards for the live React workspace.

The live modules (``frontend/src/app/**``) must never carry prototype copy, a
hardcoded Run identity or a synthetic KPI, must not import demo/synthetic
providers, and must not import the design-prototype Results view.  The pure
unit-conversion utility is exercised by ``frontend/transfer/scripts/units.test.mjs``.
Browser proof of the rendered DOM lives in
``tests/test_model_react_wf1_browser_acceptance.py``.
"""
from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
LIVE = REPO / "frontend" / "src" / "app"

#: Files owned by the pending Run/Clone CSRF PR (#376): WF-React-1 must not edit them.
OWNED_BY_376 = ("api.ts", "types.ts", "ux040506Views.tsx")

FORBIDDEN_IN_LIVE = (
    "DEMO-FIXED", "Design prototype", "SYNTHETIC DEMO", "No live calculations", "backend connection",
    "12.46", "1.82x", "Adriatic", "fixed reference", "NOT CONNECTED", "syntheticResultsProvider",
    "syntheticStatementProvider", "demoSession", "demoAdapter", "demoProjectFixtures", "ResultsAnalysisView",
)


def _live_sources():
    return [p for p in LIVE.glob("*.ts*") if p.name not in OWNED_BY_376]


def test_live_modules_carry_no_prototype_copy_or_synthetic_identity():
    offenders = []
    for path in _live_sources():
        text = path.read_text(encoding="utf-8")
        for token in FORBIDDEN_IN_LIVE:
            if token in text:
                offenders.append(f"{path.name}: {token}")
    assert offenders == [], offenders


def test_live_modules_do_not_derive_financial_results():
    """Presentation conversion only: no arithmetic aggregation over series in the live views."""
    for name in ("FinancialResults.tsx", "LibraryView.tsx", "WorkspaceNav.tsx"):
        text = (LIVE / name).read_text(encoding="utf-8")
        assert not re.search(r"\.reduce\(\s*\(", text), f"{name} must not aggregate series"
        assert "Math.pow" not in text and "toFixed(" not in text, f"{name} must not format numbers itself"
    units = (LIVE / "units.ts").read_text(encoding="utf-8")
    assert "toFixed(" not in units, "unit conversion must use exact decimal strings, not binary floats"
    assert "parseFloat" not in units


def test_live_shell_has_no_demo_chrome_when_canonical():
    shell = (REPO / "frontend/src/finco/_shared/FincoShell.tsx").read_text(encoding="utf-8")
    assert 'dataOrigin === "canonical-run"' in shell
    assert "{!live && <div className=\"fm-notice\">" in shell, "prototype notice must be demo-only"
    assert "{!live && <div className=\"fm-avatar\">" in shell


def test_statement_workbook_has_canonical_origin_without_hardcoded_sponsor_kpis():
    text = (REPO / "frontend/src/finco/_workbook/StatementWorkbook.tsx").read_text(encoding="utf-8")
    assert "canonical-run" in text
    # the fixed demo sponsor KPI line may only render for the synthetic-demo origin
    index = text.index("Fixed sponsor outputs")
    assert 'dataOrigin === "synthetic-demo"' in text[max(0, index - 200):index]


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_unit_conversion_node_suite_passes():
    result = subprocess.run(
        ["node", "--test", "frontend/transfer/scripts/units.test.mjs"],
        cwd=REPO, capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, result.stdout[-1500:] + result.stderr[-500:]
