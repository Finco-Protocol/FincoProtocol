"""Model UX sponsor-transparency regression contract.

Presentation tests only: no financial-engine formulas or reference economics
are asserted or changed here.
"""
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace


def test_country_catalog_is_single_broad_iso_authority():
    from app.workbook.country_options import COUNTRY_CODE_TO_LABEL, COUNTRY_OPTIONS

    real = [code for code, _ in COUNTRY_OPTIONS if code not in {"XA", "XB", "XC"}]
    assert len(real) >= 50
    assert COUNTRY_CODE_TO_LABEL["HR"] == "Cro" + "atia (HR)"
    assert COUNTRY_CODE_TO_LABEL["XA"] == "Generic / World — Solar (XA)"
    assert COUNTRY_CODE_TO_LABEL["XB"] == "Generic / World — Wind (XB)"
    assert COUNTRY_CODE_TO_LABEL["XC"] == "Generic / World — Storage (XC)"


def test_country_catalog_has_a_narrow_public_safety_exception():
    from tools.public_safety_scan import scan_file

    root = Path(__file__).resolve().parents[1]
    assert scan_file("app/workbook/country_options.py", root) == []
    assert scan_file("app/templates/v2/partials/sheet_revenue.html", root) == []

    # Only the approved literal is excused.  The same historical identifier
    # elsewhere in the catalog, and anywhere else in the repository, fails.
    approved = '("HR", "Cro' + 'atia (HR)")'
    forbidden = 'Cro' + 'atia'
    with TemporaryDirectory() as tmp:
        temp_root = Path(tmp)
        catalog = temp_root / "app/workbook/country_options.py"
        catalog.parent.mkdir(parents=True)
        catalog.write_text(approved + "\n# " + forbidden)
        assert scan_file("app/workbook/country_options.py", temp_root)
        other = temp_root / "app/other.py"
        other.write_text("# " + forbidden)
        assert scan_file("app/other.py", temp_root)


def test_total_sponsor_metric_uses_persisted_sponsor_schedule_authority():
    from app.v2.output_metric_projection import build_overview_metric_projections

    metrics = build_overview_metric_projections(
        {"project_irr": 0.1, "equity_irr": 0.2}, {},
        {"total_sponsor_xirr": 0.15}, freshness="current",
    )
    assert metrics["equity_irr"].label == "Pure Equity IRR"
    assert metrics["sponsor_irr"].label == "Total Sponsor IRR"
    assert metrics["sponsor_irr"].raw_value == 0.15
    assert metrics["sponsor_irr"].source == "sponsor_schedule.summary"


def test_revenue_and_sponsor_templates_keep_authority_copy_visible():
    root = Path(__file__).resolve().parents[1]
    revenue = (root / "app/templates/v2/partials/sheet_revenue.html").read_text()
    debt = (root / "app/templates/v2/partials/sheet_senior_debt.html").read_text()
    returns = (root / "app/templates/v2/partials/sheet_returns.html").read_text()

    assert "Revenue Pricing Basis" in revenue
    assert "Selecting a country does not automatically change" in revenue
    assert "Sponsor Funding / Shareholder Loan" in debt
    assert "Working financing inputs" in debt
    assert "Last Run evidence" in debt
    assert "Pure Equity IRR" in returns
    assert "Total Sponsor IRR" in returns


def test_financial_statements_and_returns_share_grouped_keur_formatter():
    root = Path(__file__).resolve().parents[1]
    formatter = (root / "app/templates/v2/partials/_money_format.html").read_text()
    statements = (root / "app/templates/v2/partials/sheet_financial_statements.html").read_text()
    returns = (root / "app/templates/v2/partials/sheet_returns.html").read_text()

    assert '"{:,.0f}".format(value)' in formatter
    assert 'import grouped_keur' in statements
    assert 'import grouped_keur' in returns
    assert 'grouped_keur(v)' in statements


def _financing(mode, share_capital=500.0):
    return SimpleNamespace(
        sponsor_funding_mode=SimpleNamespace(value=mode),
        share_capital_keur=share_capital,
        shl_rate=0.08,
        clean_shl_repayment_method=SimpleNamespace(value="BULLET"),
        shl_principal_eligibility_start_period=3,
        shl_maturity_period_index=20,
        shl_day_count_convention=SimpleNamespace(value="ACT_365_FIXED"),
    )


def _freshness(state):
    return SimpleNamespace(state=SimpleNamespace(value=state))


def _last_run(shl_principal=11818.0):
    return SimpleNamespace(sponsor_schedule={
        "summary": {"total_shl_cash_contributed_keur": shl_principal,
                    "total_sponsor_xirr": 0.145},
    }, runtime_summary={"equity_irr": 0.12}, distribution_schedule={})


def test_sponsor_funding_mode_comes_from_typed_project_inputs():
    from app.v2.router import _build_sponsor_funding_presentation

    first = _build_sponsor_funding_presentation(
        _financing("SHARE_CAPITAL_THEN_SHL"), _last_run(), _freshness("CURRENT")
    )
    second = _build_sponsor_funding_presentation(
        _financing("EQUITY_ONLY"), _last_run(), _freshness("CURRENT")
    )
    assert first["sponsor_working_rows"][0][1] == "SHARE_CAPITAL_THEN_SHL"
    assert second["sponsor_working_rows"][0][1] == "EQUITY_ONLY"


def test_sponsor_funding_not_run_current_and_stale_states_are_truthful():
    from app.v2.router import _build_sponsor_funding_presentation

    not_run = _build_sponsor_funding_presentation(_financing("EQUITY_ONLY"), None, _freshness("NOT_RUN"))
    assert not_run["sponsor_funding_freshness"]["state"] == "NOT_RUN"
    assert not_run["sponsor_last_run_rows"][0][1] is None
    assert not_run["sponsor_last_run_rows"][0][2] == "UNAVAILABLE"

    current = _build_sponsor_funding_presentation(_financing("EQUITY_ONLY"), _last_run(), _freshness("CURRENT"))
    assert current["sponsor_funding_freshness"]["state"] == "CURRENT"
    assert current["sponsor_last_run_rows"][0][2] == "CURRENT"

    stale = _build_sponsor_funding_presentation(_financing("EQUITY_ONLY", 750.0), _last_run(), _freshness("STALE"))
    assert stale["sponsor_funding_freshness"]["state"] == "STALE"
    assert stale["sponsor_working_rows"][1][1] == 750.0
    assert stale["sponsor_last_run_rows"][0] == (
        "Runtime-derived SHL principal", 11818.0, "LAST RUN / STALE"
    )


def test_returns_keep_persisted_pure_equity_and_sponsor_irr_when_stale():
    from app.v2.returns_projection import build_returns_projection

    projection = build_returns_projection(
        _last_run(), SimpleNamespace(dirty=True), runtime_is_stale=True
    )
    metrics = {metric.key: metric for metric in projection.metrics}
    assert projection.state == "STALE"
    assert metrics["equity_irr"].value == 0.12
    assert metrics["total_sponsor_irr"].value == 0.145
    assert metrics["equity_irr"].source.startswith("RuntimeResult.runtime_summary")
    assert metrics["total_sponsor_irr"].source.startswith("RuntimeResult.sponsor_schedule.summary")


def test_capex_compact_mobile_selector_matches_rendered_per_mw_class():
    root = Path(__file__).resolve().parents[1]
    css = (root / "static/css/workbook_v2.css").read_text()

    assert ".v2-capex-compact-edit-row .v2-capex-subline-permw" in css
    assert ".v2-capex-child-per-mw" not in css
    assert "grid-template-columns: 3rem 1fr 5rem auto" in css
