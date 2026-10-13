"""Diagnostics V1 presentation-only numeric regressions and loader parity.

No production evidence transform, scorer, financial arithmetic or JUnit golden refresh.
"""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
import json
import re

import pytest
from jinja2 import Environment, FileSystemLoader

from test_public_surface_hygiene import hygiene_client, _cookies, _visible_text, _long_floats

ROOT = Path(__file__).resolve().parents[1]
V2_ROOT = ROOT / "app" / "templates" / "v2"
MAIN_ROOT = ROOT / "app" / "templates"


@pytest.mark.parametrize("loader_root,template_name", [
    (V2_ROOT, "partials/sheet_overview.html"),
    (MAIN_ROOT, "v2/partials/sheet_overview.html"),
])
def test_model_health_uses_one_component_under_both_jinja_loaders(loader_root, template_name):
    from app.v2.overview_projection import build_overview_projection

    env = Environment(loader=FileSystemLoader(str(loader_root)), autoescape=True)
    for dirty in (False, True):
        ov = build_overview_projection(
            None, dirty, SimpleNamespace(template_source="generic_solar"))
        html = env.get_template(template_name).render(
            overview=ov, project_editable=True, project_name="Solar", project_type="solar",
        )
        assert html.count('id="v2-model-health"') == 1
        assert 'data-state="NOT_RUN"' in html
        assert 'data-testid="overview-state-strip"' in html


@pytest.mark.parametrize("loader_root,template_name", [
    (V2_ROOT, "partials/sheet_diagnostics.html"),
    (MAIN_ROOT, "v2/partials/sheet_diagnostics.html"),
])
def test_diagnostics_visible_precision_and_full_json_remain_distinct(loader_root, template_name):
    data = {
        "state": "STALE", "available": True, "scenario_name": "Synthetic",
        "identity": {"snapshot_id": "run-1", "run_at": "2030-01-01",
                     "composite_hash": "hash-unchanged", "engine_version": "engine"},
        "integrity": {"overall": "PASS", "checks": []},
        "score": {
            "score_display": "89", "coverage_weighted_pct": 28.763880,
            "counts": {"fail": 0, "warning": 1, "pass": 1,
                       "unavailable": 0, "not_applicable": 0},
        },
        "blocking_count": 0, "truncated": False, "total_periods": 4,
        "columns": [{"index": i, "label": "P"+str(i), "date": "2030-01-01"}
                    for i in range(4)],
        "checks": [{
            "check_id": "QM-SYNTH", "category": "Cash", "title": "Cash parity",
            "status": "WARNING", "severity": "WARNING",
            "measured_value": 1.299999999979685, "measured_unit": "kEUR",
            "threshold_value": -2.5e-11, "global_component": None,
            "periods": [],
        }],
        "waterfall": [{
            "label": "Canonical CFADS", "source": "Last Run canonical",
            "unit": "kEUR", "values": [-1.2e-7, 0.0, 28.763880, None],
        }],
    }
    data["groups"] = [{"category": "Cash", "checks": data["checks"]}]
    original = deepcopy(data)
    env = Environment(loader=FileSystemLoader(str(loader_root)), autoescape=True)
    html = env.get_template(template_name).render(diagnostics=data, project_name="Synthetic")
    match = re.search(r'<script type="application/json" data-md-payload>(.*?)</script>', html, re.S)
    assert match, "Canonical raw diagnostics JSON is required and unchanged"
    payload = json.loads(match.group(1))
    assert payload == original and data == original
    assert payload["checks"][0]["measured_value"] == 1.299999999979685
    assert payload["checks"][0]["threshold_value"] == -2.5e-11
    assert payload["waterfall"][0]["values"] == [-1.2e-7, 0.0, 28.763880, None]
    visible = _visible_text(html)
    assert not _long_floats(visible), _long_floats(visible)
    assert "28.76" in visible and "1.30" in visible
    assert "-2.500e-11" in visible and "-1.200e-07" in visible
    assert "UNAVAILABLE" in visible
    assert ">0</td>" in html  # real economic zero remains zero


def test_display_formatter_preserves_tiny_negative_missing_and_ratio_units():
    env = Environment(loader=FileSystemLoader(str(V2_ROOT)))
    number = env.get_template("partials/sheet_diagnostics.html").module.number
    assert str(number(None)) == "—"
    assert str(number(0.0, "kEUR")) == "0"
    assert str(number(-0.0, "kEUR")) == "0"
    assert str(number(-1.2e-10, "kEUR")) == "-1.200e-10"
    assert str(number(2.5e-12, "kEUR")) == "2.500e-12"
    assert str(number(1.299999999979685, "kEUR")) == "1.30"
    assert str(number(28.763880, "%")) == "28.76"
    assert str(number(-1.299999999979685, "ratio")) == "-1.300"


def test_diagnostics_javascript_formats_only_display_and_keeps_json_full_precision():
    js = (ROOT / "static/js/model_diagnostics_v1.js").read_text(encoding="utf-8")
    assert "return node ? JSON.parse(node.textContent) : null" in js
    assert "value.toExponential(3)" in js
    assert "value.toLocaleString('en-US'" in js
    assert "dd.textContent = displayFact(value)" in js
    assert "JSON.stringify(value, function" in js


def test_ev_reference_workbook_visible_text_uses_institutional_precision(hygiene_client):
    html = hygiene_client.get(
        "/v2/workbook?project=generic_ev_charging_reference-reference",
        cookies=_cookies(),
    ).text
    visible = _visible_text(html)
    assert not _long_floats(visible), _long_floats(visible)
    assert "None%" not in visible
