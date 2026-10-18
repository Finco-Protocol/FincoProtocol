"""WF-D V4: exact lender evidence template rendering and optional isolated Chromium layout."""
from pathlib import Path
from types import SimpleNamespace

import pytest
from jinja2 import Environment, FileSystemLoader, select_autoescape

from app.v2.credit_v4_evidence import build_credit_v4

ROOT = Path(__file__).resolve().parents[1]


def _render():
    view = {
        "identity": {"history_id": "committed-1", "scenario": "P50", "state": "HISTORICAL", "integrity": "PASS"},
        "timeline": {
            "available": True,
            "columns": [{"index": 3, "date": "2030-06-30"}, {"index": 4, "date": "2030-12-31"}],
            "rows": [
                {"key": k, "cells": [{"v": x}, {"v": x}]}
                for k, x in (
                    ("dscr", .8), ("base_cfads", 120.0), ("bank_cfads", 110.0),
                    ("debt_service", 150.0), ("closing", 600.0), ("dsra_balance", 50.0),
                    ("distribution", 0.0),
                )
            ],
        },
        "capacity": {"min_dscr": {"v": .8}},
        "links": {"statements": "/v2/workbook/run-history/statements",
                  "financing": "/v2/workbook#debt",
                  "diagnostics": "/v2/workbook#diagnostics"},
    }
    other = dict(view)
    other["identity"] = dict(view["identity"], history_id="committed-2", scenario="P90")
    other["timeline"] = dict(view["timeline"], rows=[
        dict(row, cells=[{"v": float(cell["v"]) + .5} for cell in row["cells"]])
        for row in view["timeline"]["rows"]
    ])
    data = {"runs": [view, other], "credit_v4": build_credit_v4([view, other])}
    env = Environment(loader=FileSystemLoader(str(ROOT / "app/templates")),
                      autoescape=select_autoescape(("html",)))
    return env.get_template("v2/partials/_credit_decision_v4.html").render(data=data)


def test_v4_template_shows_two_run_shortfalls_and_no_false_covenant():
    html = _render()
    assert 'data-testid="cd-v4-risk"' in html
    assert "REVIEW REQUIRED" in html
    assert "2030-06-30" in html
    assert "PLCR" in html and "UNAVAILABLE" in html
    assert "not an approval" in html
    assert "Contractual covenant/default" in html
    assert "committed-1" in html


@pytest.mark.parametrize("width", [390, 1440])
def test_v4_rendered_panel_chromium_no_horizontal_page_overflow(width):
    sync_api = pytest.importorskip("playwright.sync_api")
    import shutil
    with sync_api.sync_playwright() as p:
        kwargs = {"args": ["--no-sandbox"]}
        if shutil.which("chromium"):
            kwargs["executable_path"] = shutil.which("chromium")
        browser = p.chromium.launch(headless=True, **kwargs)
        page = browser.new_page(viewport={"width": width, "height": 900})
        style = (ROOT / "static/css/model_credit_decision.css").read_text()
        page.set_content('<meta name="viewport" content="width=device-width, initial-scale=1"><style>*{box-sizing:border-box}'+style+'</style><div class="cd-page">'+_render()+'</div>')
        assert page.get_by_test_id("cd-v4-risk").is_visible()
        assert page.get_by_test_id("cd-v4-period-row").count() > 0
        assert page.locator("body").evaluate("(e) => e.scrollWidth <= window.innerWidth + 2")
        assert page.get_by_test_id("cd-v4-authority").is_visible()
        browser.close()
