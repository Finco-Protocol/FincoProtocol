"""PR B characterization: presentation must preserve the existing authorities."""
from pathlib import Path
import pytest

from app.workbook.runtime_projection import aggregate_to_annual

ROOT = Path(__file__).resolve().parents[1]


def test_annual_authority_preserves_flows_stocks_and_missing():
    rows = [
        {"key": "flow", "label": "Flow", "values": [2, -3, None]},
        {"key": "stock", "label": "Stock", "is_stock": True, "values": [7, 5, None]},
        {"key": "missing", "label": "Missing", "values": [None, None, None]},
    ]
    annual, labels = aggregate_to_annual(rows, ["2026-01", "2026-02", "2027-01"])
    assert labels == ["2026", "2027"]
    assert [r["values"] for r in annual] == [[-1, None], [5, None], [None, None]]


def test_original_tab_and_oob_compatibility_targets_exist():
    page = (ROOT / "app/templates/v2/workbook.html").read_text(encoding="utf-8")
    for tab in ("overview", "project-setup", "inputs", "input-grid", "revenue", "capex", "opex",
                "investor", "debt", "tax", "fs", "returns", "outputs", "scenarios", "compare",
                "sensitivity", "goal-seek", "trust", "run-history"):
        assert f'id="tab-{tab}"' in page
        assert f'id="panel-{tab}"' in page
    legacy = (ROOT / "app/templates/v2/partials/sheet_financial_statements.html").read_text(encoding="utf-8")
    assert 'id="v2-sheet-financial-statements"' in legacy
    assert 'id="fs-runtime-bar"' in legacy


def test_manifest_is_complete_unique_and_shared_by_visible_navigation():
    from app.v2.workspace_destinations import DESTINATIONS, navigation_manifest
    from app.v2.workspace_shell_projection import workspace_nav_groups
    ids = [d.tab_id for d in DESTINATIONS]
    assert len(ids) == len(set(ids)) == 19
    assert {d.tab_id for d in DESTINATIONS if not d.alias_of} == {
        i.tab_id for g in workspace_nav_groups() for i in g.items}
    assert next(d for d in DESTINATIONS if d.tab_id == 'tab-fs').alias_of == 'tab-outputs'
    assert [a['label'] for a in navigation_manifest()['areas']] == ['Inputs', 'Scenarios', 'Outputs', 'Analysis', 'Trust']
    script = (ROOT / 'static/js/inputs_grid_v1.js').read_text(encoding='utf-8')
    assert 'manifest.destinations.forEach' in script
    assert "inputs:    ['tab-" not in script


def test_absent_scalar_never_becomes_an_editable_subtotal():
    from app.v2.input_grid_projection import _row_from_field
    from types import SimpleNamespace
    field = {'field_id': 'capex.C.production_units', 'unit': 'kEUR'}
    pis = SimpleNamespace(get=lambda _: None)
    for total in (3000, 30000):  # Solar and Wind C.01 presentation values
        editable = _row_from_field('C.01', 'Production Units', field, pis, None,
                                  editable=True, reason='', category_total=total)
        assert editable.value == '' and float(editable.category_value.replace(',', '')) == total
        reference = _row_from_field('C.01', 'Production Units', field, pis, None,
                                   editable=False, reason='Read-only', category_total=total)
        assert float(reference.value.replace(',', '')) == total
        assert not reference.editable and 'scalar override absent' in reference.reason
    zero = _row_from_field('C.01', 'Production Units', field, SimpleNamespace(get=lambda _: 0), None,
                           editable=True, reason='', category_total=30000)
    assert zero.value == '0' and zero.category_value == ''


def test_both_statement_consumers_use_one_renderer_and_one_annual_authority():
    legacy = (ROOT / 'app/templates/v2/partials/sheet_financial_statements.html').read_text(encoding='utf-8')
    outputs = (ROOT / 'app/templates/v2/partials/sheet_outputs.html').read_text(encoding='utf-8')
    for source in (legacy, outputs):
        assert 'partials/_statement_table.html' in source
    assert '<table' not in legacy and '<table' not in outputs
    assert 'statements_from_run(runtime_result' in (ROOT / 'app/v2/output_workspace_projection.py').read_text(encoding='utf-8')
    assert 'aggregate_to_annual(' not in (ROOT / 'app/v2/statement_presentation.py').read_text(encoding='utf-8')


def test_csp_filter_removed_without_security_policy_change():
    investor = (ROOT / 'app/templates/v2/partials/sheet_investor.html').read_text(encoding='utf-8')
    assert 'htmx:afterRequest[' not in investor
    script = (ROOT / 'static/js/workbook_v2.js').read_text(encoding='utf-8')
    assert "String(config.verb).toLowerCase() !== 'post'" in script


@pytest.mark.parametrize('template,total', [('generic_solar_reference', 3000), ('generic_wind_reference', 30000)])
def test_real_protected_reference_category_value_and_permission(tmp_path, monkeypatch, template, total):
    from app.persistence import db
    from app.persistence.projects_repository import get_reference_by_template_source
    from app.persistence.workspace_repository import get_workspace_state
    from app.services.project_library_service import ensure_reference_models
    from app.v2 import router as presentation
    monkeypatch.setattr(db, 'DB_PATH', str(tmp_path / 'prb-reference.db'))
    db.init_db()
    ensure_reference_models()
    record = get_reference_by_template_source(template)
    ws = get_workspace_state(record.user_id, record.project_id)
    pis = presentation._build_pis_with_composite_identity(ws, record, record.user_id)
    grid = presentation._build_input_grid_ctx(record, pis, ws, record.user_id, project_editable=False)['input_grid']
    row = next(category.rows[0] for section in grid.sections if section.section_id == 'capex'
               for category in section.categories if category.code == 'C.01')
    assert not row.editable
    assert float(row.value.replace(',', '')) == total
    assert 'scalar override absent' in row.reason or 'Sum of line items' in row.reason
    assert all(not row.editable for section in grid.sections for category in section.categories for row in category.rows)
