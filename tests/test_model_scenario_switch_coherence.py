"""Focused scenario-switch identity and HTMX presentation regressions."""
from __future__ import annotations
from html.parser import HTMLParser
from pathlib import Path
from types import SimpleNamespace


class _MarkerParser(HTMLParser):
    attrs = None

    def handle_starttag(self, tag, attrs):
        if tag == "div" and dict(attrs).get("id") == "v2-scenario-edit-authority":
            self.attrs = dict(attrs)


def _attrs(html):
    parser = _MarkerParser()
    parser.feed(html)
    assert parser.attrs is not None
    return parser.attrs


def test_scenario_switch_oob_carries_the_server_composite_identity():
    from app.v2.post_run_ui import _scenario_edit_authority_oob

    response = _scenario_edit_authority_oob(
        SimpleNamespace(content_hash="a" * 64, workbook_version="v2"),
        SimpleNamespace(active_scenario_id="scenario-x"),
    )
    attrs = _attrs(response)
    assert attrs["hx-swap-oob"] == "true"
    assert attrs["data-content-hash"] == "a" * 64
    assert attrs["data-workbook-version"] == "v2"
    assert attrs["data-active-scenario-id"] == "scenario-x"


def test_base_none_compatibility_and_attribute_escape():
    from app.v2.post_run_ui import _scenario_edit_authority_oob

    result = _scenario_edit_authority_oob(
        SimpleNamespace(content_hash="b" * 64, workbook_version="v2"),
        SimpleNamespace(active_scenario_id=None),
    )
    assert _attrs(result)["data-active-scenario-id"] == ""
    adversarial = _scenario_edit_authority_oob(
        SimpleNamespace(content_hash="c" * 64, workbook_version="v2"),
        SimpleNamespace(active_scenario_id='bad"><script>'),
    )
    assert "<script>" not in adversarial
    assert _attrs(adversarial)["data-active-scenario-id"] == 'bad"><script>'


def test_top_bar_server_scenario_label_is_coherent_and_escaped():
    from app.v2.router import _templates

    template = _templates.get_template("partials/_v2_toolbar_scenario.html")
    for name in ("Base", "Scenario X", "Scenario Y"):
        html = template.render({"active_scenario_name": "" if name == "Base" else name})
        assert 'id="v2-toolbar-scenario-label"' in html
        assert "<strong>" + name + "</strong>" in html
    html = template.render({"active_scenario_name": '<img src=x>'})
    assert "&lt;img src=x&gt;" in html
    assert "<img src=x>" not in html
