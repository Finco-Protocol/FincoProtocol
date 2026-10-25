"""Local browser contract replay, not production persistence/financial acceptance."""
from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import urlparse

import pytest

pytest.importorskip("playwright", reason="playwright not installed in this workflow")
from tests.test_workflow_c_browser_v1 import browser  # noqa: E402,F401

ROOT = Path(__file__).resolve().parents[1]


def test_trust_diagnostics_and_history_render_exact_contracts_without_automatic_actions(browser, tmp_path):
    integrity = {"overall": "INCOMPLETE", "counts": {"PASS": 0, "UNAVAILABLE": 9},
                 "run_identity": {"snapshot_id": "snapshot-contract-123"},
                 "checks": [{"check_id": "balance", "title": "Balance reconciliation",
                             "status": "UNAVAILABLE", "detail": "Evidence is absent"}]}
    payloads = {
        "workspace": {"ok": True, "react_workspace": {"version": "ux02-v1"}, "project": {"code": "p", "name": "Contract replay", "project_type": "solar", "protected_reference": False},
                      "workbook": {"version": "2.0", "composite_hash": "hash-contract", "scenario_id": "scenario-b", "scenario_name": "Scenario B"},
                      "freshness": {"state": "CURRENT", "basis": "canonical", "has_runtime": True, "is_stale": False},
                      "identity": {"snapshot_id": "snapshot-contract-123", "ran_at": "2026-10-25", "scenario": "Scenario B", "scenario_proven": True},
                      "integrity": {"status": "INCOMPLETE", "counts": {}, "failures": []}, "integrity_available": True,
                      "engine": {"currency": "CURRENT_ENGINE"}},
        "trust": {"ok": True, "run_state": "CURRENT", "identity": {"snapshot_id": "snapshot-contract-123"}, "integrity": integrity,
                  "validation": {"state": "DEFERRED", "scope": "Pinned reference only; not validation of this Working Copy", "load_url": "/v2/workbook/trust/validation?project=p"},
                  "certificate": {"state": "DEFERRED", "scope": "Provenance only; availability not established", "load_url": "/v2/workbook/trust/certificate?project=p"}},
        "diagnostics": {"ok": True, "run_state": "CURRENT", "integrity": integrity,
                        "insight": {"run_state": "CURRENT", "context_note": "Committed Run", "not_claims": "Not Verify"},
                        "diagnostics": {"state": "CURRENT", "checks": [{"check_id": "balance", "label": "Balance reconciliation", "status": "UNAVAILABLE", "note": "Evidence is absent"}]}},
        "statements": {"ok": True, "project": {"name": "Contract replay"}, "state": "CURRENT", "snapshot": None,
                       "status": {"runId": "snapshot-contract-123", "freshness": "current", "integrity": "not evaluated", "engineVersion": "engine-contract", "dataOrigin": "caller-provided"},
                       "results": {"available": False}, "integrity_available": True, "integrity": {"status": "INCOMPLETE"}},
        "runs": {"ok": True, "project": {"protected_reference": False}, "run_contract": {"url": "/v2/workbook/run"},
                 "runs": [{"history_id": "history-contract", "runtime_snapshot_id": "snapshot-contract-123", "runtime_origin": "canonical-v2", "ran_at": "2026-10-25", "active_scenario_id": "scenario-b", "active_scenario_name": "Scenario B", "engine_version": "engine-contract", "composite_hash": "hash-contract"}]},
    }
    actions = []
    context = browser.new_context(viewport={"width": 1440, "height": 1000})
    page = context.new_page()
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    def route(request_route):
        request = request_route.request
        path = urlparse(request.url).path
        if request.method not in ("GET", "HEAD"):
            actions.append(request.url)
            return request_route.abort()
        if path.startswith("/v2/workbook/"):
            actions.append(request.url)
            return request_route.abort()
        if path.startswith("/static/"):
            target = ROOT / path.lstrip("/")
            if target.is_file():
                return request_route.fulfill(path=str(target), content_type="application/javascript" if target.suffix == ".js" else "text/css")
            return request_route.fulfill(status=404, body="")
        key = path.rsplit("/", 1)[-1]
        if key in payloads:
            return request_route.fulfill(content_type="application/json", body=json.dumps(payloads[key]))
        return request_route.fulfill(content_type="text/html", body='''<!doctype html><meta charset="utf-8"><link rel="stylesheet" href="/static/react/finco-react.css"><div id="finco-react-root" data-project="p" data-bootstrap-url="/v2/model-react/bootstrap" data-save-url="/v2/workbook/grid/save" data-validate-url="/v2/workbook/grid/validate" data-legacy-url="/v2/workbook?project=p"></div><script src="/static/react/finco-react.js"></script>''')
    context.route("**/*", route)
    try:
        page.goto("http://rc-ux-b.invalid/v2/model-react/p#trust")
        section = page.get_by_role("region", name="Trust and integrity evidence", exact=True)
        section.wait_for()
        assert "INCOMPLETE" in section.inner_text()
        assert "snapshot-contract-123" in section.inner_text()
        assert "not validation of this project" in section.inner_text()
        assert page.get_by_role("link", name="Explicitly run reference regression (separate evidence)").get_attribute("href") == "/v2/workbook/trust/validation?project=p"
        assert len(actions) == 0
        page.screenshot(path=str(tmp_path / "trust-contract-replay.png"), full_page=True)
        page.goto("http://rc-ux-b.invalid/v2/model-react/p#diagnostics")
        checks = page.get_by_role("region", name="Model checks and diagnostics", exact=True)
        checks.wait_for()
        assert "Run state: CURRENT" in checks.inner_text()
        assert "Balance reconciliation" in checks.inner_text()
        assert "Evidence is absent" in checks.inner_text()
        page.screenshot(path=str(tmp_path / "diagnostics-contract-replay.png"), full_page=True)
        page.goto("http://rc-ux-b.invalid/v2/model-react/p#results")
        history = page.get_by_role("region", name="Run history", exact=True)
        history.wait_for()
        assert "Scenario B" in history.inner_text()
        assert "canonical-v2" in history.inner_text()
        assert "hash-contract" in history.inner_text()
        assert "snapshot-contract-123" in history.inner_text()
        page.screenshot(path=str(tmp_path / "history-contract-replay.png"), full_page=True)
        assert not errors
        assert not actions
    except Exception:
        print("Browser errors:", errors)
        print("Rendered body:", page.locator("body").inner_text())
        raise
    finally:
        context.close()
