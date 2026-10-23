"""UX-02 Replit source reconciliation — RC5/RC6/RC7 provenance and quarantine guards.

The owner-supplied packages (verified against the expected checksums) supersede the
RC1 harvest in the source tree:

* RC5  ``74b792e0a0411e779dbc0085e8a4c560893866ea2cc68a29ff57e6f8d92352e2`` — full snapshot
* RC6  ``7f75f389d87eb55e8253b05032437a7f878b1dbf380f0dafb82a5475bcbf7957`` — 17-member delta over RC5
* RC7  ``5f531c8060882da1fd6ee35c6f3621b945214c5c999c40cc261279c1fba1d0fc`` — 13-member overlay (owner-accepted)

Reconstitution order: RC5 → RC6 → RC7 (the RC7 manifest's own order).  The RC1
harvest record in ``tests/test_model_react_source_harvest_v1.py`` remains the
historical authority for the RC1 era; THIS module pins the current RC7-level tree.

Quarantine model (Workstream A3): production may render APPROVED harvested
presentation components, but must never include the demo/synthetic state —
no demo session storage, no synthetic statement/results providers, no demo
fixtures, no transfer-harness modules.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
FRONTEND = REPO / "frontend"
FINCO = FRONTEND / "src" / "finco"
TRANSFER = FRONTEND / "transfer"
DOCS = REPO / "docs" / "react_migration"
BUNDLE = REPO / "static" / "react" / "finco-react.js"

RC5_SHA256 = "74b792e0a0411e779dbc0085e8a4c560893866ea2cc68a29ff57e6f8d92352e2"
RC6_SHA256 = "7f75f389d87eb55e8253b05032437a7f878b1dbf380f0dafb82a5475bcbf7957"
RC7_SHA256 = "5f531c8060882da1fd6ee35c6f3621b945214c5c999c40cc261279c1fba1d0fc"

RC5_NEW_FILES = (
    "ResultsAnalysisView.tsx",
    "_results/resultsContract.ts",
    "_workbook/syntheticStatementProvider.ts",
    "_shared/SourceAuthorityDrawer.tsx",
    "_shared/source-authority.css",
)
RC7_NEW_FILES = (
    "_results/runComparisonFixtures.ts",
    "_shared/SourceAuthorityDrawer.tsx",
)

#: Modules whose CONTENT must never appear in the served production bundle.
FORBIDDEN_BUNDLE_MARKERS = (
    "demoProjectFixtures",
    "SYNTHETIC_REFERENCE_PROJECTS",
    "syntheticStatementProvider",
    "syntheticResultsProvider",
    "runComparisonFixtures",
    "TRANSFER_DEMO_STATEMENT",
    "Adriatic Solar I",       # demo fixture project name
    "demoSessionStoragePrefix",
    "sessionStorage",          # no browser-session persistence in production
)

#: Harvest-tree modules production is never allowed to import (allowlist inverse).
FORBIDDEN_PRODUCTION_MODULES = (
    "src/finco/_shared/demoSession.ts",
    "src/finco/_shared/demoSessionKeys.ts",
    "src/finco/_shared/demoWorkingCopies.ts",
    "src/finco/_shared/demoProjectFixtures.ts",
    "src/finco/_shared/demoAdapter.ts",
    "src/finco/_workbook/syntheticStatementProvider.ts",
    "src/finco/_results/syntheticResultsProvider.ts",
    "src/finco/_results/runComparisonFixtures.ts",
    # UX-03: new RC11 demo/synthetic modules stay out of the production graph.
    "src/finco/_shared/demoSessionStorage.ts",
    "src/finco/_insight/syntheticInsightFixtures.ts",
)


def test_package_checksums_recorded():
    doc = (DOCS / "react_migration_ux02_source_integration.md").read_text(encoding="utf-8")
    for sha in (RC5_SHA256, RC6_SHA256, RC7_SHA256):
        assert sha in doc, f"package SHA-256 {sha[:12]} must stay recorded"
    assert "RC5" in doc and "RC6" in doc and "RC7" in doc
    assert "74b792e0" in doc


def test_rc5_rc7_sources_present_in_tree():
    for rel in RC5_NEW_FILES:
        assert (FINCO / rel).is_file(), rel
    for rel in RC7_NEW_FILES:
        assert (FINCO / rel).is_file(), rel
    assert (TRANSFER / "productStates.ts").is_file()
    assert (TRANSFER / "resultsFixtures.ts").is_file()


def test_rc5_handoff_docs_preserved():
    rc5_docs = DOCS / "replit_source" / "rc5"
    for name in ("BROWSER_ACCEPTANCE.md", "COVERAGE.md", "INTEGRATION_READINESS.md",
                 "UI_COMPONENT_HANDOFF.md", "RC6_TO_RC7_MANIFEST.md"):
        assert (rc5_docs / name).is_file(), name


def test_single_source_adaptation_statementworkbook_reftype_rc5():
    src = (FINCO / "_workbook" / "StatementWorkbook.tsx").read_text(encoding="utf-8")
    assert "regionRef: React.RefObject<HTMLDivElement>;" in src
    assert "RefObject<HTMLDivElement | null>" not in src


def test_integration_targets_import_no_synthetic_providers():
    for target in ("_workbook/StatementWorkbook.tsx", "ResultsAnalysisView.tsx",
                   "_shared/FincoShell.tsx", "ProjectLibrary.tsx"):
        src = (FINCO / target).read_text(encoding="utf-8")
        for provider in ("syntheticStatementProvider", "syntheticResultsProvider",
                         "runComparisonFixtures", "productStates", "demoProjectFixtures",
                         "demoSession", "demoWorkingCopies"):
            assert provider not in src, f"{target} must not import {provider}"


def test_production_bundle_contains_no_demo_or_synthetic_state():
    bundle = BUNDLE.read_text(encoding="utf-8")
    for marker in FORBIDDEN_BUNDLE_MARKERS:
        assert marker not in bundle, f"production bundle must not contain {marker!r}"


def test_production_module_graph_excludes_forbidden_modules():
    """Import-graph proof: the production TypeScript program must not include any
    demo/synthetic module or transfer-harness file."""
    import subprocess

    tsc = FRONTEND / "node_modules" / "typescript" / "bin" / "tsc"
    if not tsc.is_file():
        pytest.skip("frontend toolchain not installed in this environment")
    result = subprocess.run(
        ["node", str(tsc), "-p", "tsconfig.json", "--noEmit", "--listFiles"],
        cwd=FRONTEND, capture_output=True, text=True, timeout=600)
    assert result.returncode == 0, result.stderr[-500:]
    listed = result.stdout.replace("\\", "/").splitlines()
    forbidden = [line for line in listed
                 for module in FORBIDDEN_PRODUCTION_MODULES
                 if line.endswith(module.replace("src/finco/", "src/finco/"))]
    assert forbidden == [], forbidden[:10]
    assert not [line for line in listed if "/frontend/transfer/" in line], "transfer harness must stay out of production"


def test_no_dependency_catalogue_in_the_source_tree():
    assert not list(FINCO.rglob("package.json"))
    assert not list(FINCO.rglob("node_modules"))
    unexpected = [p.name for p in FINCO.rglob("*") if p.is_file()
                  and p.suffix.lower() not in {".tsx", ".ts", ".css", ".md", ".mjs"}]
    assert unexpected == [], unexpected


def test_production_dependency_surface_unchanged():
    import json

    manifest = json.loads((FRONTEND / "package.json").read_text(encoding="utf-8"))
    assert manifest["dependencies"] == {"react": "18.3.1", "react-dom": "18.3.1"}, \
        "the harvested source must not add runtime dependencies"
