"""Phase 1.5: Portfolio UI — display IndependentPortfolioResult.

No HoldCo. No SHL. No Sponsor IRR. No monthly model.
Minimal additive layer on top of existing domain/portfolio/independent/ results.
"""
from __future__ import annotations

import pandas as pd

from domain.portfolio.independent import IndependentPortfolioResult

from app.portfolio_ui_overlay import (
    build_spv_constraints_table,
    build_holdco_constraints_table,
    build_dist_constraints_table,
    aggregate_spv_warnings,
    aggregate_holdco_warnings,
    summarize_block_reasons,
    has_overlay_warnings,
)


# ── Column / label constants ────────────────────────────────────────────────

_IRR_LABEL = "Simple Average IRR (NOT Portfolio XIRR — uses unweighted per-SP average)"


def build_portfolio_summary_table(result: IndependentPortfolioResult) -> pd.DataFrame:
    """Portfolio-level summary as a single-row table.

    Args:
        result: IndependentPortfolioResult from run_independent_portfolio()

    Returns:
        DataFrame with one row: portfolio KPIs.
    """
    rows = [
        ("Portfolio Name", result.portfolio_name),
        ("Number of SPVs", result.num_spvs),
        ("", ""),
        ("--- Totals ---", ""),
        ("Total Revenue (kEUR)", f"{result.total_revenue_keur:,.0f}"),
        ("Total EBITDA (kEUR)", f"{result.total_ebitda_keur:,.0f}"),
        ("Total Tax (kEUR)", f"{result.total_tax_keur:,.0f}"),
        ("Total Senior Debt Service (kEUR)", f"{result.total_senior_ds_keur:,.0f}"),
        ("Total Distributions (kEUR)", f"{result.total_distribution_keur:,.0f}"),
        ("", ""),
        ("--- DSCR ---", ""),
        ("Min DSCR (conservative)", f"{result.min_dscr:.3f}x"),
        ("Avg DSCR (unweighted)", f"{result.avg_dscr:.3f}x"),
        ("", ""),
        ("--- IRR (Simple Average) ---", ""),
        ("Simple Avg Project IRR (NOT Portfolio XIRR)", _irr_pct(result.simple_avg_project_irr)),
        ("Simple Avg Equity IRR (NOT Portfolio XIRR)", _irr_pct(result.simple_avg_equity_irr)),
        ("", ""),
        ("--- DSRF ---", ""),
        ("DSRF Enabled", result.dsrf_enabled),
        ("Warnings Count", len(result.warnings)),
    ]

    if result.dsrf_enabled:
        rows.extend([
            ("", ""),
            ("--- DSRF Facility ---", ""),
            ("DSRF Facility Limit (kEUR)", f"{result.dsrf_facility_limit_keur:,.0f}"),
            ("DSRF Total Draw (kEUR)", f"{result.dsrf_total_draw_keur:,.0f}"),
            ("DSRF Total Repayment (kEUR)", f"{result.dsrf_total_repayment_keur:,.0f}"),
            ("DSRF Commitment Fee (kEUR)", f"{result.dsrf_commitment_fee_keur:,.0f}"),
            ("DSRF Drawn Interest (kEUR)", f"{result.dsrf_drawn_interest_keur:,.0f}"),
            ("DSRF Distribution Reduction (kEUR)", f"{result.dsrf_distribution_reduction_keur:,.0f}"),
        ])

    return pd.DataFrame(rows, columns=["Field", "Value"])


def build_portfolio_spv_table(result: IndependentPortfolioResult) -> pd.DataFrame:
    """Per-SPV breakdown table.

    Each row = one SPV. Columns: code, name, revenue, EBITDA, tax,
    senior DS, distributions, avg DSCR, min DSCR, project IRR, equity IRR.
    """
    rows = []
    for out in result.spv_outputs:
        rows.append({
            "SPV Code": out.project_code,
            "SPV Name": out.project_name,
            "Revenue (kEUR)": f"{out.total_revenue_keur:,.0f}",
            "EBITDA (kEUR)": f"{out.total_ebitda_keur:,.0f}",
            "Tax (kEUR)": f"{out.total_tax_keur:,.0f}",
            "Senior DS (kEUR)": f"{out.total_senior_ds_keur:,.0f}",
            "Distributions (kEUR)": f"{out.total_distribution_keur:,.0f}",
            "Avg DSCR": f"{out.avg_dscr:.3f}x",
            "Min DSCR": f"{out.min_dscr:.3f}x",
            "Project IRR": _irr_pct(out.project_irr),
            "Equity IRR": _irr_pct(out.equity_irr),
        })
    return pd.DataFrame(rows)


def build_portfolio_warnings_table(result: IndependentPortfolioResult) -> pd.DataFrame:
    """Portfolio-level warnings as a table (one row per warning)."""
    if not result.warnings:
        return pd.DataFrame(columns=["Warning"])
    return pd.DataFrame([(w,) for w in result.warnings], columns=["Warning"])


def render_portfolio_summary(result: IndependentPortfolioResult) -> str:
    """Render a compact text summary of the portfolio result.

    Useful for Streamlit display, logs, or quick inspection.
    Returns a multi-line string.
    """
    lines = [
        f"Portfolio: {result.portfolio_name}",
        f"SPVs: {result.num_spvs}",
        f"Total Revenue: {result.total_revenue_keur:,.0f} kEUR",
        f"Total EBITDA: {result.total_ebitda_keur:,.0f} kEUR",
        f"Total Distributions: {result.total_distribution_keur:,.0f} kEUR",
        f"Min DSCR: {result.min_dscr:.3f}x",
        f"Avg DSCR: {result.avg_dscr:.3f}x",
        f"Simple Avg Project IRR: {_irr_pct(result.simple_avg_project_irr)}  [NOT Portfolio XIRR]",
        f"Simple Avg Equity IRR: {_irr_pct(result.simple_avg_equity_irr)}  [NOT Portfolio XIRR]",
        f"DSRF Enabled: {result.dsrf_enabled}",
    ]
    if result.warnings:
        lines.append(f"Warnings: {len(result.warnings)}")
        for w in result.warnings:
            lines.append(f"  ⚠ {w}")
    else:
        lines.append("Warnings: none")
    return "\n".join(lines)


def _irr_pct(value: float) -> str:
    """Format IRR as percentage string."""
    return f"{value * 100:.2f}%"


__all__ = [
    "build_portfolio_summary_table",
    "build_portfolio_spv_table",
    "build_portfolio_warnings_table",
    "render_portfolio_summary",
    "_IRR_LABEL",
    # Phase 5F — overlay UI helpers
    "build_spv_constraints_table",
    "build_holdco_constraints_table",
    "build_dist_constraints_table",
    "aggregate_spv_warnings",
    "aggregate_holdco_warnings",
    "summarize_block_reasons",
    "has_overlay_warnings",
]