"""FINCO47 React-only unification, unified shell navigation, and Save->Run race guard."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_react_host_page_has_no_legacy_workbook_link():
    html = (ROOT / "app" / "templates" / "v2" / "react_poc.html").read_text(encoding="utf-8")
    assert "open the legacy workbook" not in html.lower()
    assert "data-legacy-url" not in html
    assert "/v2/workbook?" not in html


def test_react_shell_and_app_expose_unified_routes():
    shell = (ROOT / "frontend" / "src" / "finco" / "_shared" / "FincoShell.tsx").read_text(encoding="utf-8")
    for route in ("/v2/model-react/", "/v2/model-react/#new-project", "/v2/model-react/#compare-projects",
                  "/v2/model-react/#guide", "/v2/model-react/#platform", "/v2/model-react/#account"):
        assert route in shell, f"missing unified shell route {route}"
    app_tsx = (ROOT / "frontend" / "src" / "App.tsx").read_text(encoding="utf-8")
    for comp in ("GuideMethodologyView", "PlatformApiVerifyView", "AccountSessionView"):
        assert comp in app_tsx


def test_save_to_run_race_guard_blocks_run_while_identity_refreshing():
    ws = (ROOT / "frontend" / "src" / "app" / "WorkspaceView.tsx").read_text(encoding="utf-8")
    wb = (ROOT / "frontend" / "src" / "app" / "workflow" / "WorkflowBar.tsx").read_text(encoding="utf-8")
    assert 'useReportPending("grid-save", busy)' in ws
    assert "identityRefreshing={identityReads > 0 || busy}" in ws
    assert "identityRefreshing" in wb
    assert "Refreshing saved project state before Run" in wb
