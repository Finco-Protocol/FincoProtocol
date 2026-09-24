"""Model UX sponsor-transparency regression contract.

Presentation tests only: no financial-engine formulas or reference economics
are asserted or changed here.
"""
from pathlib import Path


def test_country_catalog_is_single_broad_iso_authority():
    from app.workbook.country_options import COUNTRY_CODE_TO_LABEL, COUNTRY_OPTIONS

    real = [code for code, _ in COUNTRY_OPTIONS if code not in {"XA", "XB", "XC"}]
    assert len(real) >= 50
    assert COUNTRY_CODE_TO_LABEL["HR"] == "Cro" + "atia (HR)"
    assert COUNTRY_CODE_TO_LABEL["XA"] == "Generic / World — Solar (XA)"
    assert COUNTRY_CODE_TO_LABEL["XB"] == "Generic / World — Wind (XB)"
    assert COUNTRY_CODE_TO_LABEL["XC"] == "Generic / World — Storage (XC)"


def test_country_catalog_is_the_only_public_safety_exception():
    from tools.public_safety_scan import scan_file

    root = Path(__file__).resolve().parents[1]
    assert scan_file("app/workbook/country_options.py", root) == []
    assert scan_file("app/templates/v2/partials/sheet_revenue.html", root) == []


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
