"""Correction A: historical-capital totals, separate date coverage and scale."""
from dataclasses import replace

import pytest

from app.v2.portfolio_projection import ProjectEvidence, build_portfolio
from tests.test_portfolio_monitoring import item, record


def test_initial_capital_total_includes_different_and_unavailable_funding_dates():
    a, b, c = item("a"), item("b"), item("c")
    b.entry.runtime_summary["financing_evidence"]["construction_funding"]["periods"][0]["period_end"] = "2031-06-30"
    del c.entry.runtime_summary["financing_evidence"]["construction_funding"]["periods"][0]["period_start"]
    view = build_portfolio([a, b, c])
    capital = view["capital_groups"][0]
    assert capital["totals"]["capex"]["value"] == "3000.0"
    assert capital["totals"]["senior"]["value"] == "2100.0"
    assert capital["totals"]["senior"]["coverage"] == 3
    assert capital["complete_dates"] == 2 and capital["count"] == 3
    assert len(view["cohorts"]) == 2
    assert view["cohorts"][0]["totals"]["capex"]["value"] == "1000.0"
    assert view["cohorts"][1]["totals"]["capex"]["value"] == "1000.0"


def test_undated_fc_amount_remains_valid_historical_capital_not_current_exposure():
    a = item()
    a.entry.runtime_summary["financing_evidence"]["construction_funding"]["non_construction_fc_use"] = {
        "uses_keur": 40, "total_sources_keur": 40, "residual_keur": 0}
    view = build_portfolio([a])
    capital = view["capital_groups"][0]
    assert capital["totals"]["senior"]["value"] == "700.0"
    assert capital["complete_dates"] == 0
    # Date-specific financing remains unavailable, not allocated to an invented date.
    assert view["cohorts"][0]["totals"]["senior"]["value"] is None
    assert "current_outstanding" not in view


def test_invalid_or_foreign_financial_evidence_is_not_a_zero_contribution():
    a, b = item("a"), item("b")
    b.entry.runtime_summary["financing_evidence"]["currency"] = "USD"
    missing = ProjectEvidence(record("no-run"), freshness="NOT_RUN")
    view = build_portfolio([a, b, missing])
    total = view["capital_groups"][0]["totals"]["capex"]
    assert total["value"] == "1000.0" and total["coverage"] == 1 and total["projects"] == 3
    assert view["capital_excluded_count"] == 2


@pytest.mark.parametrize("count", [20, 100])
def test_large_portfolios_keep_exact_coverage_determinism_and_single_project_count(count):
    values = [item(str(index), project_type="solar" if index % 2 else "wind") for index in range(count)]
    first = build_portfolio(values)
    assert first == build_portfolio(list(reversed(values)))
    assert first["total"] == count
    assert first["capital_groups"][0]["totals"]["capex"]["value"] == str(count * 1000) + ".0"
    assert first["capital_groups"][0]["totals"]["capex"]["coverage"] == count


def test_historical_totals_preserve_stale_status_and_all_zero_is_not_unavailable():
    a = item()
    a = replace(a, freshness="STALE")
    view = build_portfolio([a])
    assert view["rows"][0]["freshness"] == "STALE"
    assert view["capital_groups"][0]["totals"]["shl"]["value"] == "0.0"
    assert view["capital_groups"][0]["totals"]["shl"]["coverage"] == 1
