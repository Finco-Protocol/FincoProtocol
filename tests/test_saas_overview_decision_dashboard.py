"""The decision dashboard projects saved Last-Run values without recalc."""
from types import SimpleNamespace
from app.v2.overview_projection import build_overview_projection
from app.workbook.runtime_result import RuntimeResult


def _runtime(*, with_cash=True):
    cash = {"pf_cash_waterfall": {"periods": [
        {"date": "2029-12-31", "revenue_cash_keur": 1200.0, "opex_cash_keur": -300.0,
         "ebitda_cash_keur": 900.0, "fcf_banks_keur": 650.0, "senior_total_ds_keur": -400.0},
    ]}} if with_cash else None
    return RuntimeResult(
        snapshot_id="run-1", ran_at="2029-12-31T12:00:00+00:00", origin="saved_state",
        runtime_summary={"project_irr": .09, "equity_irr": .14, "project_npv_keur": 2500.0,
                         "total_capex_keur": 40000.0, "min_dscr": 1.3, "avg_dscr": 1.5},
        debt_schedule={"periods": [{"date": "2029-12-31", "is_operation": True,
                                     "senior_balance_keur": 20000.0, "senior_ds_keur": 400.0, "dscr": 1.5}],
                       "summary": {"min_llcr": 1.2}},
        financial_statements=cash, tax_schedule=None, distribution_schedule=None, sponsor_schedule=None,
    )


def _project(rr, dirty=False):
    return build_overview_projection(rr, dirty, SimpleNamespace(template_source="generic_solar"))


def test_authoritative_cash_series_and_npv_stay_identical_after_working_edit():
    rr = _runtime()
    current, stale = _project(rr), _project(rr, dirty=True)
    assert current.chart_operating_periods == stale.chart_operating_periods
    assert current.chart_operating_periods[0]["fcf_banks_keur"] == 650.0
    assert current.chart_operating_periods[0]["senior_total_ds_keur"] == -400.0
    assert current.output_metrics["project_npv_keur"].raw_value == 2500.0
    assert stale.output_metrics["project_npv_keur"].raw_value == 2500.0
    from main_web import templates
    html = templates.get_template("v2/partials/sheet_overview.html").render(
        overview=current, project_editable=True, project_name="Solar", project_type="Solar")
    for chart in ("chart-operating-performance", "chart-cash-service", "chart-debt-balance", "chart-dscr-profile"):
        assert f'data-testid="{chart}"' in html
    assert 'data-testid="kpi-project-npv"' in html
    stale_html = templates.get_template("v2/partials/sheet_overview.html").render(
        overview=stale, project_editable=True, project_name="Solar", project_type="Solar")
    assert "Inputs changed since the last run" in stale_html
    assert 'data-testid="chart-cash-service"' in stale_html


def test_missing_canonical_cash_series_fails_closed_and_no_run_uses_one_form():
    assert _project(_runtime(with_cash=False)).chart_operating_periods is None
    no_run = _project(None)
    from main_web import templates
    html = templates.get_template("v2/partials/sheet_overview.html").render(
        overview=no_run, project_editable=True, project_name="Solar", project_type="Solar")
    assert 'form="v2-canonical-run-form"' in html
    assert 'document.querySelector' not in html
    assert 'data-testid="chart-cash-service"' not in html
