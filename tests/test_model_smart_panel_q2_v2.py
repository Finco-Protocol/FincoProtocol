"""Q2 FINCO Insight — read-only authority and presentation regression gates.

No engine or persistence mutation is permitted.  Browser acceptance remains
a separate runtime gate; these tests check typed projection and DOM contracts.
"""
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from app.v2.smart_panel_projection import build_smart_panel_projection


def panel(**kw):
    base = dict(
        trust_pack=None,
        runtime_state="NOT_RUN",
        has_runtime=False,
        project_key="",
        assumption_register_view=None,
    )
    base.update(kw)
    return build_smart_panel_projection(**base)


def html(projection):
    env = Environment(
        loader=FileSystemLoader("app/templates/v2"),
        autoescape=select_autoescape(["html"]),
    )
    return env.get_template("partials/_model_smart_panel.html").render(
        {"smart_panel": projection}
    )


def test_authoritative_financial_fail_precedes_stale_warning():
    p = panel(
        runtime_state="STALE",
        has_runtime=True,
        trust_pack={"integrity": {
            "state": "AVAILABLE", "overall": "FAIL",
            "counts": {"FAIL": 1},
            "checks": [{"status": "FAIL", "reason_code": "PROVEN_FAILURE"}],
        }},
        assumption_register_view={"available": True, "rows": []},
    )
    assert p.issues[0].key == "last-run-integrity-fail"
    assert p.issues[0].severity == "fail"
    assert "PROVEN_FAILURE" in p.issues[0].detail
    assert any(i.key == "working-copy-stale" for i in p.issues)
    assert "not changed Working Copy inputs" in p.issues[0].detail


def test_no_invented_breach_or_financial_severity_from_missing_authorities():
    p = panel(trust_pack={
        "integrity": {"state": "UNAVAILABLE"},
        "validation": {"state": "DEFERRED"},
    })
    assert not any(i.severity == "fail" for i in p.issues)
    assert not any("covenant breach" in i.label.lower() for i in p.issues)
    assert not any(i.key == "reference-regression-unavailable" for i in p.issues)


def test_inspector_uses_only_available_register_view_and_preserves_zero():
    p = panel(assumption_register_view={
        "available": True,
        "entry_count": 2,
        "rows": [
            {"path": "debt.margin", "section": "FINANCING",
             "label": "Debt margin", "value": "0", "unit": "%",
             "source": "USER_INPUT"},
            {"path": "debt.margin", "label": "Duplicate", "value": "9"},
            {"path": "", "label": "Unknown"},
        ],
    })
    assert len(p.inspector_fields) == 1
    assert p.inspector_fields[0]["value"] == "0"
    assert p.inspector_fields[0]["source"] == "USER_INPUT"
    assert p.inspector_fields[0]["path"] == "debt.margin"
    assert panel().inspector_fields == ()


def test_modes_metadata_and_stale_kpi_lineage_survive_render():
    p = panel(
        runtime_state="STALE", has_runtime=True,
        trust_pack={
            "kpi_strip_source": {
                "state": "AVAILABLE",
                "runtime_summary": {"project_irr": 0.09, "min_dscr": 1.4},
                "sponsor_summary": {},
                "run_scenario_name": "Scenario A",
            },
            "last_run": {"state": "AVAILABLE", "run_at_display": "2026-10-10"},
        },
        assumption_register_view={"available": True, "rows": [
            {"path": "finance.margin", "label": "Margin", "section": "DEBT",
             "value": "2.5", "unit": "%", "source": "USER_INPUT"}]},
    )
    rendered = html(p)
    for mode in ("solutions", "inspector", "changes"):
        assert f'data-sp-mode="{mode}"' in rendered
        assert f'data-sp-view="{mode}"' in rendered
    assert 'data-run-state="STALE"' in rendered
    assert 'data-sp-run-scenario="Scenario A"' in rendered
    assert 'data-path="finance.margin"' in rendered
    assert 'value="k:project_irr"' in rendered
    assert 'data-value="9.00%"' in rendered
    assert "not a field-level formula tree" not in rendered  # no fake lineage
    assert 'data-nav-tab="tab-run-history"' in rendered


def test_not_run_has_no_computed_kpi_values():
    p = panel(
        runtime_state="NOT_RUN",
        trust_pack={"kpi_strip_source": {
            "state": "UNAVAILABLE", "runtime_summary": {"project_irr": 0.42},
        }},
    )
    rendered = html(p)
    assert 'data-run-state="NOT_RUN"' in rendered
    assert 'data-value="42.00%"' not in rendered
    assert 'data-available="false"' in rendered
    assert "UNAVAILABLE" in rendered


def test_trace_remains_explicitly_unavailable_and_no_engine_on_build(monkeypatch):
    import app.api.project_runner as runner

    monkeypatch.setattr(
        runner, "run_project",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("financial engine called from Q2 projection")),
    )
    p = panel(
        runtime_state="CURRENT", has_runtime=True,
        trust_pack={"last_run": {"state": "AVAILABLE"}},
    )
    assert p.sections[-1].key == "trace"
    assert p.sections[-1].available is False
    assert p.sections[-1].link is None
    assert "not persisted after a run" in p.sections[-1].empty_text


def test_dedicated_assets_loaded_once_after_existing_workbook_script():
    page = Path("app/templates/v2/workbook.html").read_text(encoding="utf-8")
    assert page.count('/static/css/model_smart_panel_v2.css') == 1
    assert page.count('/static/js/model_smart_panel_v2.js') == 1
    assert page.index('/static/js/workbook_v2.js') < page.index(
        '/static/js/model_smart_panel_v2.js')
    js = Path("static/js/model_smart_panel_v2.js").read_text(encoding="utf-8")
    assert 'window.__fincoSmartPanelV2' in js
    assert "htmx:afterSwap" in js and "htmx:afterSettle" in js
    assert "data-sp-return" in js and "v2FieldValidationUx.jump" in js
    assert "fetch(" not in js and "htmx.ajax(" not in js
    assert "run_project" not in js

def test_finco_insight_branded_accessibly_without_internal_renames():
    from html.parser import HTMLParser

    rendered = html(panel())
    assert 'data-testid="finco-insight-heading"' in rendered
    assert "<h2 class=\"v2-sp-brand-title\">FINCO Insight</h2>" in rendered
    assert "Model findings, assumptions and run context." in rendered
    assert 'aria-label="FINCO Insight modes"' in rendered
    for key, visible in (("solutions", "Findings"), ("inspector", "Explore"),
                         ("changes", "Changes")):
        assert f'data-sp-mode="{key}">{visible}</button>' in rendered
        assert f'data-sp-view="{key}"' in rendered
    assert 'aria-label="Select assumption or KPI to explore"' in rendered
    assert 'aria-label="Smart panel"' not in rendered
    # One approved inspection-only selector, no financial input forms.
    assert rendered.count('<select ') == 1
    assert 'id="v2-sp-inspect-select"' in rendered
    assert 'name="financing.' not in rendered
    assert '<form' not in rendered and '<textarea' not in rendered
