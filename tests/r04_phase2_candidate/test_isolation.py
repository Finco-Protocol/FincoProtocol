"""R04 Phase A (Phase 2 preparatory candidate, integrated from #447) — production isolation, behaviour-based.

The candidate must stay unreachable from production: no product module imports it, no route serves it, the React
component is not mounted (not imported by any non-candidate source, absent from the served bundle), the research
package imports no writer/persistence/web module, and the production gate always refuses. The candidate's own node
render/syntax suite is executed here so it runs in Model CI.
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
PACKAGE = ROOT / "research/r04_phase2_candidate"
COMPONENT_DIR = ROOT / "frontend/src/app/workflow/r04Candidate"
NEEDLE = re.compile(r"r04_phase2_candidate|r04Candidate|AnnualQuantityCandidateField|AnnualQuantityDraft|R04_P2_ANNUAL_QUANTITY_CANDIDATE")


def _tracked_and_new(*globs):
    out = subprocess.check_output(["git", "ls-files", "--cached", "--others", "--exclude-standard", "--", *globs],
                                  cwd=ROOT, text=True)
    return [p for p in out.splitlines() if p]


def test_no_production_source_references_the_candidate():
    files = _tracked_and_new("*.py", "*.ts", "*.tsx", "*.js", "*.mjs", "*.html", "*.json", "*.toml", "*.cfg", "*.ini", "*.yml")
    allowed = ("research/r04_phase2_candidate/", "frontend/src/app/workflow/r04Candidate/", "tests/", "archive/", "docs/")
    offenders = [f for f in files if not f.startswith(allowed) and (ROOT / f).is_file()
                 and NEEDLE.search((ROOT / f).read_text(encoding="utf-8", errors="ignore"))]
    assert offenders == [], offenders


def test_the_component_is_not_in_the_served_bundle():
    bundle = (ROOT / "static/react/finco-react.js").read_text(encoding="utf-8", errors="ignore")
    # Rendered component strings (type-only literals never reach a bundle, so they would prove nothing).
    for marker in ("No server period review is available", "Declared period review only"):
        assert marker not in bundle, marker


def test_the_research_package_imports_no_writer_persistence_or_web_module():
    forbidden = re.compile(r"^\s*(?:from|import)\s+(app|main_web|main_api|domain)(\.|\s|$)", re.M)
    for path in PACKAGE.glob("*.py"):
        text = path.read_text(encoding="utf-8")
        assert not forbidden.search(text), path.name
        code = re.sub(r'"""[\s\S]*?"""', "", text)  # docstrings may say what the module does NOT do
        for writer in ("save_", "get_connection(", "app.persistence", "run_history", "INSERT INTO", "UPDATE "):
            assert writer not in code, (path.name, writer)


def test_no_mounted_route_serves_the_candidate():
    import main_web
    for route in main_web.app.routes:
        path = getattr(route, "path", "")
        assert "r04" not in path.lower() and "annual-quantity" not in path.lower(), path


def test_the_production_gate_always_refuses():
    from research.r04_phase2_candidate.contracts import CandidateError, require_production_contract
    for book in (None, object(), {"anything": True}):
        with pytest.raises(CandidateError) as exc:
            require_production_contract(book)
        assert exc.value.code == "R04_P2_ANNUAL_DELIVERY_POLICY_AND_PRODUCTION_ADMISSION_REQUIRED"
        assert exc.value.production_supported is False and exc.value.annual_semantics_verified is False


def test_candidate_node_render_and_syntax_suite_passes():
    assert (ROOT / "frontend/node_modules/esbuild").is_dir(), "frontend node_modules (npm ci) is required"
    proc = subprocess.run(["node", "--test", str(COMPONENT_DIR / "candidate.test.mjs")], cwd=ROOT / "frontend",
                          capture_output=True, text=True, timeout=600)
    tail = (proc.stdout + proc.stderr)[-4000:]
    assert proc.returncode == 0, tail
    assert re.search(r"^# fail 0$", proc.stdout, re.M) and re.search(r"^# pass [1-9]", proc.stdout, re.M), tail
