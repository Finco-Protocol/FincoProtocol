"""UX-01B Replit React source harvest — intake, quarantine and provenance guards.

The owner-supplied transfer package (``finco-react-transfer-rc1.zip``,
SHA-256 ``3b205723dea75383238036e99a7f65a6ee7f7826b15c0ea9a5794356893e159d``)
is the primary design source for the new FINCO Model UI.  These tests pin the
harvest contract:

* the harvested design tree exists and matches the package provenance;
* the production React bundle stays free of the harvested demo/synthetic state
  (no demo fixtures, no fm-* design CSS, no transfer harness in the served
  bundle);
* the production dependency surface is unchanged (React + react-dom only);
* the single source adaptation against the package is exactly the documented
  React-18 ref-type widening in StatementWorkbook.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
FRONTEND = REPO / "frontend"
FINCO = FRONTEND / "src" / "finco"
TRANSFER = FRONTEND / "transfer"
DOCS = REPO / "docs" / "react_migration" / "replit_source"
BUNDLE = REPO / "static" / "react" / "finco-react.js"

TRANSFER_ZIP_SHA256 = "3b205723dea75383238036e99a7f65a6ee7f7826b15c0ea9a5794356893e159d"

#: Harvested files that must exist (package-relative under src/finco/).
REQUIRED_FINCO_FILES = (
    "README.md",
    "_group.css",
    "ProjectLibrary.tsx",
    "ModelWorkspace.tsx",
    "ResultsAnalysis.tsx",
    "_shared/FincoShell.tsx",
    "_shared/FincoApplicationComposition.tsx",
    "_shared/viewModels.ts",
    "_shared/validation.ts",
    "_workbook/InputGrid.tsx",
    "_workbook/CostLinePlanner.tsx",
    "_workbook/RevenueWorkspace.tsx",
    "_workbook/StatementWorkbook.tsx",
    "_workbook/FinanceWorkspace.tsx",
    "_workbook/TimelineTaxWorkspace.tsx",
    "_workbook/CreditDecisionWorkspace.tsx",
    "_workbook/DecisionAnalysisWorkspace.tsx",
    "_workbook/ScenarioGovernanceWorkspace.tsx",
    "_workbook/ModelDeliveryWorkspace.tsx",
    "_workbook/WorkbookNavigation.tsx",
    "_workbook/statementContract.ts",
    "_workbook/periodGrid.ts",
    "_workbook/gridPaste.ts",
    "_workbook/catalog.ts",
)

REQUIRED_HARNESS_FILES = (
    "index.html",
    "main.tsx",
    "App.tsx",
    "routes.ts",
    "context.tsx",
    "fixtures.ts",
    "vite.transfer.config.ts",
    "globals.d.ts",
)

REQUIRED_DOCS = (
    "FINCO_REACT_TRANSFER_RC1_REPORT.md",
    "DESIGN_HARVEST_MANIFEST.md",
    "INTEGRATION_READINESS.md",
    "UI_COMPONENT_HANDOFF.md",
    "BROWSER_ACCEPTANCE.md",
    "COVERAGE.md",
    "TRANSFER_PROGRESS.md",
)

#: Markers that must NEVER appear in the served production bundle: the demo
#: state layer, the synthetic fixtures and the harvested design CSS namespace.
DEMO_MARKERS = (
    "demoProjectFixtures",
    "demoWorkingCopies",
    "demoSession",
    "demoAdapter",
    "TRANSFER_DEMO_STATEMENT",
    "fm-sw-",
)


def test_package_provenance_recorded():
    report = (DOCS / "FINCO_REACT_TRANSFER_RC1_REPORT.md").read_text(encoding="utf-8")
    assert "26ade41" in report, "package workspace revision must stay recorded"
    harvest = (REPO / "docs/react_migration/ux01b_source_harvest.md").read_text(encoding="utf-8")
    assert TRANSFER_ZIP_SHA256 in harvest, "transfer ZIP SHA-256 must stay recorded"


def test_harvested_tree_is_complete():
    missing = [rel for rel in REQUIRED_FINCO_FILES if not (FINCO / rel).is_file()]
    assert missing == [], missing
    missing = [rel for rel in REQUIRED_HARNESS_FILES if not (TRANSFER / rel).is_file()]
    assert missing == [], missing
    missing = [name for name in REQUIRED_DOCS if not (DOCS / name).is_file()]
    assert missing == [], missing


def test_no_dependency_catalogue_or_node_modules_inside_the_harvest():
    assert not list(FINCO.rglob("node_modules"))
    assert not list(FINCO.rglob("package.json"))
    assert not list(FINCO.rglob("*.lock"))
    # No synthetic-data payload files beyond the declared TS/CSS/MD sources.
    unexpected = [p.name for p in FINCO.rglob("*") if p.is_file()
                  and p.suffix.lower() not in {".tsx", ".ts", ".css", ".md", ".mjs"}]
    assert unexpected == [], unexpected


def test_single_documented_source_adaptation_statementworkbook_reftype():
    src = (FINCO / "_workbook" / "StatementWorkbook.tsx").read_text(encoding="utf-8")
    # React 19-style `RefObject<HTMLDivElement | null>` (as supplied) is widened
    # to the React-18-compatible `RefObject<HTMLDivElement>`; nothing else differs.
    assert "regionRef: React.RefObject<HTMLDivElement>;" in src
    assert "RefObject<HTMLDivElement | null>" not in src


def test_production_bundle_contains_no_demo_or_design_state():
    bundle = BUNDLE.read_text(encoding="utf-8")
    for marker in DEMO_MARKERS:
        assert marker not in bundle, f"production bundle must not contain {marker!r}"


def test_production_module_graph_excludes_harvested_tree():
    """Import-graph proof (stronger than bundle string markers): the production
    TypeScript program must not include any file under src/finco or transfer."""
    import subprocess

    tsc = FRONTEND / "node_modules" / "typescript" / "bin" / "tsc"
    if not tsc.is_file():
        pytest.skip("frontend toolchain not installed in this environment")
    result = subprocess.run(
        ["node", str(tsc), "-p", "tsconfig.json", "--noEmit", "--listFiles"],
        cwd=FRONTEND, capture_output=True, text=True, timeout=600)
    assert result.returncode == 0, result.stderr[-500:]
    listed = result.stdout.replace("\\", "/").splitlines()
    harvested = [line for line in listed
                 if re.search(r"frontend/(src/finco|transfer)/", line)]
    assert harvested == [], harvested[:10]


def test_production_dependency_surface_unchanged():
    import json

    manifest = json.loads((FRONTEND / "package.json").read_text(encoding="utf-8"))
    assert manifest["dependencies"] == {"react": "18.3.1", "react-dom": "18.3.1"}, \
        "the harvested design source must not add runtime dependencies"


def test_transfer_harness_is_not_served_by_the_backend():
    host = (REPO / "app/templates/v2/react_poc.html").read_text(encoding="utf-8")
    assert "transfer" not in host.lower(), "dev-only harness must stay out of the served host page"
    router = (REPO / "app/v2/react_poc_router.py").read_text(encoding="utf-8")
    assert "dist-transfer" not in router and "transfer" not in router.lower().replace(
        "transfer entry", "")
