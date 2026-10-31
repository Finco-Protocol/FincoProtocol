"""ON-05 read-only reporting regressions; expected values come from engine evidence."""
from dataclasses import replace
from decimal import Decimal
from functools import lru_cache
import csv
import io
from pathlib import Path
from types import SimpleNamespace

from jinja2 import Environment, FileSystemLoader
import pytest

from app import project_factories
from app.services import sensitivity_service as sensitivity
from app.services.lender_case_service import build_credit_summary
from app.services.production_waterfall_seam import execute_production_waterfall
from tools.numerical_validation.identities import RATIO, default_policies

KEUR_TOL = Decimal("1e-6")  # full precision sum, no persisted rounding allowance
RATIO_TOL = next(p.abs_tolerance for p in default_policies() if p.key == RATIO)


@lru_cache(maxsize=None)
def execution(kind, bps):
    base = getattr(project_factories, f"create_generic_{kind}_reference")()
    return execute_production_waterfall(sensitivity._apply_shock(base, "interest_rate", bps))


def decimal_sum(values):
    return sum((Decimal(str(v)) for v in values), Decimal(0))


@pytest.mark.parametrize("kind", ["solar", "wind"])
@pytest.mark.parametrize("bps", [-200, -100, 0, 100, 200])
def test_real_run_base_cfads_and_minimum_dscr(kind, bps, monkeypatch):
    actual = execution(kind, bps)
    base = execution(kind, 0)
    model = actual.clean_run.g2c_result.financing_result.project_model_result
    tax = model.tax_and_cfads
    senior = model.senior_debt
    # Exercise the public service mapping, retaining ONE authentic execution.
    monkeypatch.setattr("app.services.production_waterfall_seam.execute_production_waterfall", lambda proj: actual)
    kpis = sensitivity._run_once(actual.project_inputs)
    expected = decimal_sum(tax.cfads_keur)
    assert expected != 0
    assert abs(Decimal(str(kpis["_cfads_keur"])) - expected) <= KEUR_TOL
    assert kpis["min_dscr"] == actual.result.actual_min_dscr
    cfads_by_period = dict(zip(tax.period_indices, tax.cfads_keur, strict=True))
    ratios = []
    for period, debt_service, dscr in zip(senior.period_indices, senior.senior_debt_service_keur,
                                          senior.base_dscr, strict=True):
        if debt_service > 0 and dscr is not None:
            independently_derived = Decimal(str(cfads_by_period[period])) / Decimal(str(debt_service))
            assert abs(Decimal(str(dscr)) - independently_derived) <= RATIO_TOL
            ratios.append(dscr)
    assert abs(kpis["min_dscr"] - min(ratios)) <= float(RATIO_TOL)
    assert kpis["project_irr"] == base.result.project_irr
    if bps:
        base_model = base.clean_run.g2c_result.financing_result.project_model_result
        assert senior.debt_size_keur != base_model.senior_debt.debt_size_keur  # current design re-sizes
        assert senior.senior_interest_keur != base_model.senior_debt.senior_interest_keur
        assert tax.corporate_tax_cash_keur != base_model.tax_and_cfads.corporate_tax_cash_keur
        assert expected != decimal_sum(base_model.tax_and_cfads.cfads_keur)


@pytest.mark.parametrize("values", [None, (), (None,), (1, None), (float("nan"),), (float("inf"),), ("bad",)])
def test_missing_or_partial_cfads_is_absent_not_zero(values):
    result = SimpleNamespace(periods=[SimpleNamespace(r69_fcf_banks_keur=999)], min_dscr=99)
    kpis = sensitivity._extract_kpis(result, base_cfads=values)
    assert kpis["_cfads_keur"] is None
    assert kpis["min_dscr"] is None  # never use the misleading legacy attribute


def test_real_zero_and_authoritative_minimum_are_preserved():
    result = SimpleNamespace(actual_min_dscr=0.0, min_dscr=99)
    assert sensitivity._extract_kpis(result, base_cfads=(0.0, 0.0))["_cfads_keur"] == 0.0
    assert sensitivity._extract_kpis(result)["min_dscr"] == 0.0


def render_partial(name, **context):
    env = Environment(loader=FileSystemLoader(Path(__file__).resolve().parents[1] / "app/templates"), autoescape=True)
    return env.get_template("partials/" + name).render(
        _fmt_kpi=lambda value, fmt: "—" if value is None else str(value),
        _fmt_delta=lambda value, fmt: str(value), **context)


def test_mixed_default_units_csv_and_html_preserve_numeric_levels(monkeypatch):
    monkeypatch.setattr(sensitivity, "_run_once", lambda proj: {"project_irr": .1})
    # Unit presentation is independent of the engine; real shock behavior is proved above.
    monkeypatch.setattr(sensitivity, "_apply_shock", lambda proj, *args: object())
    monkeypatch.setattr(sensitivity, "rate_shock_evidence", lambda *args: {"before_pct": 5.5, "after_pct": 6.5})
    result = sensitivity.run_sensitivity(object(), ["interest_rate", "capex"])
    rate_rows = [row for row in result["rows"] if row["shock_type"] == "interest_rate"]
    assert [row["level_pct"] for row in rate_rows] == [-200, -100, -50, 50, 100, 200]
    assert [row["level_pct"] for row in result["rows"] if row["shock_type"] == "capex"] == [-15, -10, -5, 5, 10, 15]
    csv_rows = list(csv.reader(io.StringIO(sensitivity.export_sensitivity_csv(result))))
    assert csv_rows[0][:4] == ["Shock Type", "Level", "Unit", "Error"]
    assert csv_rows[2][1:3] == ["-200.0", "bps"]
    assert csv_rows[8][1:3] == ["-15.0", "%"]
    html = render_partial("scenario_sensitivity.html", sensitivity_result=result,
                          sensitivity_shock_types=["interest_rate", "capex"], tornado_data=[])
    assert "+100 bps" in html and "-200 bps" in html and "+15 %" in html
    assert "5.5% → 6.5%" in html
    assert "+100%" not in html and "basis-point deltas" in html
    explicit = sensitivity.run_sensitivity(object(), ["interest_rate"], [12.5])
    assert explicit["rows"][0]["level_pct"] == 12.5  # do not reinterpret stored/user numbers


def test_credit_cannot_attribute_input_estimates_to_any_run_or_debt_service():
    proj = project_factories.create_generic_solar_reference()
    kpis = {"total_senior_ds_keur": 999999, "senior_debt_keur": 123,
            "history_id": "different-project-history", "runtime_snapshot_id": "stale-snapshot"}
    original = dict(kpis)
    summary = build_credit_summary(proj, kpis)
    assert summary["debt_keur"] == proj.capex.total_capex * proj.financing.gearing_ratio
    assert summary["debt_keur"] not in (123, 999999)
    assert summary["financing_status"] == "ESTIMATE"
    assert "history_id" not in summary and "runtime_snapshot_id" not in summary
    assert kpis == original
    html = render_partial("credit_summary.html", credit_summary=summary)
    assert "Capital Structure — ESTIMATE" in html
    assert "do not reconcile to an executed Run" in html
    assert "All values from canonical engine" not in html
    assert "different-project-history" not in html and "stale-snapshot" not in html


@pytest.mark.parametrize("gearing", [None, float("nan"), -0.1, 1.1])
def test_not_yet_run_credit_with_missing_financing_never_invents_zero(gearing):
    proj = project_factories.create_generic_solar_reference()
    proj = replace(proj, financing=replace(proj.financing, gearing_ratio=gearing))
    summary = build_credit_summary(proj, {})
    assert summary["financing_status"] == "UNAVAILABLE"
    assert summary["debt_keur"] is summary["equity_keur"] is summary["gearing_pct"] is None
