"""Revenue V2 structured editor: bounded presentation authority only.

These tests intentionally do not compute revenue or replace canonical endpoint tests.
Financial parity, authenticated saves and immutable export remain covered by WF07.
"""
from pathlib import Path
import json

from bs4 import BeautifulSoup
from jinja2 import Environment, FileSystemLoader

ROOT = Path(__file__).resolve().parents[1]
PARTIAL = ROOT / "app/templates/v2/partials/revenue_contracts.html"
SCRIPT = ROOT / "static/js/model_revenue_contract_editor.js"


def render(book="", editable=True, overridden=False):
    env = Environment(loader=FileSystemLoader(str(PARTIAL.parents[1])), autoescape=True)
    payload = json.loads(book) if book else None
    return env.get_template("partials/revenue_contracts.html").render(
        contracts={"raw": book, "rows": payload["streams"] if payload else [],
                   "scope": "Working Copy", "active": bool(payload), "overridden": overridden},
        project_editable=editable, project_type="Solar", project_code="solar-test",
        content_hash="composite-token", revenue_contracts_csrf_token="signed-csrf",
        revenue_runtime_summary={})


def test_form_has_single_original_authorized_writer_and_composite_cas():
    page = BeautifulSoup(render(), "html.parser")
    form = page.select_one('[data-testid="revenue-contracts-form"]')
    assert form and form["action"] == form["hx-post"] == "/v2/workbook/revenue/contracts"
    assert form["hx-target"] == "#v2-sheet-revenue"
    assert form.select_one('input[name="project"]')["value"] == "solar-test"
    assert form.select_one('input[name="content_hash"]')["value"] == "composite-token"
    assert form.select_one('input[name="csrf_token"]')["value"] == "signed-csrf"
    payloads = form.select('[name="contracts"]')
    assert len(payloads) == 1 and payloads[0].name == "input"
    assert form.select_one("#revenue-contracts-json").has_attr("readonly")
    assert not form.select_one("#revenue-contracts-json").has_attr("name")
    assert form.select_one('[data-revenue-save]')["value"] == "save"
    assert form.select_one('[data-revenue-table]')
    assert form.select_one('[data-revenue-feedback]')
    assert form.select_one('[data-revenue-error]')


def test_scenario_inherit_and_protected_reference_are_unchanged():
    inherited = BeautifulSoup(render(overridden=True), "html.parser")
    button = inherited.select_one('[data-revenue-inherit]')
    assert button["name"] == "action" and button["value"] == "inherit"
    reference = BeautifulSoup(render(editable=False), "html.parser")
    assert not reference.select_one('[data-testid="revenue-contracts-form"]')
    assert not reference.select_one('[name="contracts"]')
    assert reference.select_one('table[aria-label="Saved revenue contracts"]')


def test_five_editor_variants_and_disabled_unsupported_features():
    page = BeautifulSoup(render(), "html.parser")
    variants = [x["value"] for x in page.select('[data-revenue-add-type] option')]
    assert variants == ["fixed_ppa", "indexed_ppa", "merchant", "residual_merchant", "cfd"]
    assert not any(x in variants for x in ("capacity_market", "ancillary", "rec"))
    text = SCRIPT.read_text(encoding="utf-8")
    assert "FINCO" not in text.upper() or "financial" not in text.lower()  # no economics owned here
    for essential in ("JSON.stringify(book)", "htmx:configRequest",
                      "fromPct", "kindOverrides", "data-revenue-row", "data-revenue-source"):
        assert essential in text
    assert "fetch(" not in text
    assert "window.confirm" in text


def test_existing_contract_raw_is_preserved_in_readonly_diagnostic():
    book = {"version": 1, "technology": "solar", "indexation_basis": "OPERATING_YEAR",
            "streams": [{
                "id": "ppa-1", "type": "ppa", "start_date": "2031-01-01", "end_date": "2051-01-01",
                "volume_share": .5, "price_eur_mwh": 95, "indexation_rate": .02,
                "settlement": "SAME_PERIOD", "source_ref": "signed-contract-document"
            }]}
    original = json.dumps(book)
    page = BeautifulSoup(render(original), "html.parser")
    assert page.select_one("#revenue-contracts-json").text == original
    assert page.select_one('[data-revenue-payload]')["value"] == ""
    assert "Revenue contracts" in page.text
