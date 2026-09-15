"""Output table adapters — stable bridge between engine results and UI."""
from __future__ import annotations
import pandas as pd
import re
from typing import Any

# Re-export input helpers for convenience
from app.input_helpers import (
    build_inputs_summary_table,
    build_capex_summary_table,
    build_capex_items_table,
)


def _period_label(period: Any) -> str:
    """Return a period label string from a period object."""
    if hasattr(period, 'end_date'):
        return str(period.end_date)[:10]  # YYYY-MM-DD
    if hasattr(period, 'date'):
        return str(period.date)[:10]
    if hasattr(period, 'period'):
        return str(period.period)
    return str(period) if period is not None else "P?"


def _safe_get(obj: Any, name: str, default: float = 0.0) -> float:
    """Safely get a numeric attribute or dict key, with common aliases."""
    if obj is None:
        return default
    # Aliases
    alias_map = {
        "cash_tax_keur": "tax_keur",
        "cfads_keur": "cf_after_tax_keur",
        "senior_debt_service_keur": "senior_ds_keur",
        "senior_debt_balance_keur": "senior_balance_keur",
        "distributions_keur": "distribution_keur",
    }
    resolved_name = alias_map.get(name, name)
    if hasattr(obj, resolved_name):
        val = getattr(obj, resolved_name)
        return float(val) if val is not None else default
    if isinstance(obj, dict):
        return float(obj.get(resolved_name, default))
    return default


def _safe_get_or_none(obj: Any, name: str) -> float | None:
    if obj is None:
        return None
    if hasattr(obj, name):
        val = getattr(obj, name)
        return float(val) if val is not None else None
    if isinstance(obj, dict):
        v = obj.get(name)
        return float(v) if v is not None else None
    return None


def _first_available(obj, names: tuple[str, ...], default: float = 0.0) -> float:
    """Return first available attribute from obj, or default."""
    for name in names:
        if hasattr(obj, name):
            val = getattr(obj, name)
            if val is not None:
                return float(val)
    return default


def _cfads_value(period) -> float:
    """CFADS: use explicit cfads_keur if present, else ebitda_keur - tax_keur."""
    if hasattr(period, 'cfads_keur') and period.cfads_keur is not None:
        return float(period.cfads_keur)
    ebitda = _safe_get(period, 'ebitda_keur', 0.0)
    tax = _safe_get(period, 'tax_keur', 0.0)
    return max(0.0, ebitda - tax)


def build_dashboard_kpis(result) -> dict[str, float | str | None]:
    if result is None:
        return {}
    return {
        "total_revenue_keur": _safe_get_or_none(result, 'total_revenue_keur'),
        "total_ebitda_keur": _safe_get_or_none(result, 'total_ebitda_keur'),
        "total_tax_keur": _safe_get_or_none(result, 'total_tax_keur'),
        "project_irr": _safe_get_or_none(result, 'project_irr'),
        "equity_irr": _safe_get_or_none(result, 'equity_irr'),
        "sponsor_irr": _safe_get_or_none(result, 'sponsor_irr'),
        # Dashboard DSCR KPIs use actual period-measured DSCRs so they match the reference debt serviceCR Summary.
        "min_dscr": _safe_get_or_none(result, 'actual_min_dscr'),
        "avg_dscr": _safe_get_or_none(result, 'actual_avg_dscr'),
        "total_senior_ds_keur": _safe_get_or_none(result, 'total_senior_ds_keur'),
        "total_distribution_keur": _safe_get_or_none(result, 'total_distribution_keur'),
    }


def build_waterfall_table(result) -> pd.DataFrame:
    if result is None or not hasattr(result, 'periods') or not result.periods:
        return pd.DataFrame(columns=["P1"])

    periods = result.periods
    labels = [_period_label(p) for p in periods]

    def row_values(getter) -> list[float]:
        return [getter(p) for p in periods]

    rows = {
        "Revenue": row_values(lambda p: _safe_get(p, 'revenue_keur')),
        "OpEx": row_values(lambda p: _safe_get(p, 'opex_keur')),
        "EBITDA": row_values(lambda p: _safe_get(p, 'ebitda_keur')),
        "Depreciation": row_values(lambda p: _safe_get(p, 'depreciation_keur')),
        "Taxable Profit": row_values(lambda p: _safe_get(p, 'taxable_profit_keur')),
        "Cash Tax": row_values(lambda p: _first_available(p, ('tax_keur', 'cash_tax_keur'))),
        "CFADS": row_values(_cfads_value),
        "Senior Debt Service": row_values(lambda p: _first_available(p, ('senior_ds_keur', 'senior_debt_service_keur'))),
        "SHL Service": row_values(lambda p: _safe_get(p, 'shl_service_keur')),
        "DSRA Contribution": row_values(lambda p: _safe_get(p, 'dsra_contribution_keur')),
        "Distributions": row_values(lambda p: _first_available(p, ('distribution_keur', 'distributions_keur'))),
        "Cash Balance": row_values(lambda p: _safe_get(p, 'cash_balance_keur')),
        "Senior Debt Balance": row_values(lambda p: _first_available(p, ('senior_balance_keur', 'senior_debt_balance_keur'))),
        "SHL Balance": row_values(lambda p: _safe_get(p, 'shl_balance_keur')),
    }

    df = pd.DataFrame(rows, index=labels).T
    df.index.name = "Line Item"
    return df


def build_revenue_table(result) -> pd.DataFrame:
    if result is None or not hasattr(result, 'periods') or not result.periods:
        return pd.DataFrame(columns=["P1"])

    periods = result.periods
    labels = [_period_label(p) for p in periods]

    rows = {
        "Generation MWh": [_safe_get(p, 'generation_mwh') for p in periods],
        "Revenue kEUR": [_safe_get(p, 'revenue_keur') for p in periods],
        "Total Revenue kEUR": [_safe_get(p, 'total_revenue_keur') for p in periods],
    }

    # BESS and hybrid are optional
    bess_rev = [_safe_get(p, 'bess_revenue_keur') for p in periods]
    if any(v != 0.0 for v in bess_rev):
        rows["BESS Revenue kEUR"] = bess_rev

    hybrid_rev = [_safe_get(p, 'hybrid_revenue_keur') for p in periods]
    if any(v != 0.0 for v in hybrid_rev):
        rows["Hybrid Revenue kEUR"] = hybrid_rev

    df = pd.DataFrame(rows, index=labels).T
    df.index.name = "Line Item"
    return df


def build_debt_table(result) -> pd.DataFrame:
    if result is None or not hasattr(result, 'periods') or not result.periods:
        return pd.DataFrame(columns=["P1"])

    periods = result.periods
    labels = [_period_label(p) for p in periods]

    rows = {
        "Senior Interest": [_safe_get(p, 'senior_interest_keur') for p in periods],
        "Senior Principal": [_safe_get(p, 'senior_principal_keur') for p in periods],
        "Senior Debt Service": [_safe_get(p, 'senior_debt_service_keur') for p in periods],
        "Senior Debt Balance": [_safe_get(p, 'senior_debt_balance_keur') for p in periods],
        "DSCR": [_safe_get(p, 'dscr') for p in periods],
        "LLCR": [_safe_get(p, 'llcr') for p in periods],
        "PLCR": [_safe_get(p, 'plcr') for p in periods],
    }

    df = pd.DataFrame(rows, index=labels).T
    df.index.name = "Line Item"
    return df


def build_tax_depreciation_table(result) -> pd.DataFrame:
    if result is None or not hasattr(result, 'periods') or not result.periods:
        return pd.DataFrame(columns=["P1"])

    periods = result.periods
    labels = [_period_label(p) for p in periods]

    rows = {
        "EBITDA": [_safe_get(p, 'ebitda_keur') for p in periods],
        "Depreciation": [_safe_get(p, 'depreciation_keur') for p in periods],
        "Senior Interest": [_safe_get(p, 'senior_interest_keur') for p in periods],
        "SHL Interest": [_safe_get(p, 'shl_interest_keur') for p in periods],
        "Taxable Profit": [_safe_get(p, 'taxable_profit_keur') for p in periods],
        "Cash Tax": [_safe_get(p, 'cash_tax_keur') for p in periods],
    }

    df = pd.DataFrame(rows, index=labels).T
    df.index.name = "Line Item"
    return df


def build_returns_table(result) -> pd.DataFrame:
    if result is None:
        return pd.DataFrame(columns=["Value"])

    project_irr = _safe_get_or_none(result, 'project_irr')
    equity_irr = _safe_get_or_none(result, 'equity_irr')
    sponsor_irr = _safe_get_or_none(result, 'sponsor_irr')
    project_npv = _safe_get_or_none(result, 'project_npv')
    equity_npv = _safe_get_or_none(result, 'equity_npv')

    def _fmt_irr_pct(val):
        if val is None or val == 0.0:
            return "n/a"
        return f"{val * 100:.2f}%"

    def _fmt_npv(val):
        if val is None:
            return "n/a"
        return f"{val:,.0f} kEUR"

    labels = ["Project IRR", "Equity IRR", "Sponsor IRR", "Project NPV", "Equity NPV"]
    values = [
        _fmt_irr_pct(project_irr),
        _fmt_irr_pct(equity_irr),
        _fmt_irr_pct(sponsor_irr),
        _fmt_npv(project_npv),
        _fmt_npv(equity_npv),
    ]

    df = pd.DataFrame({"Value": values}, index=labels)
    df.index.name = "Metric"
    return df


def build_portfolio_table(portfolio_result) -> pd.DataFrame:
    if portfolio_result is None:
        return pd.DataFrame(columns=["Value"])

    labels = [
        "Pooled Revenue",
        "Pooled EBITDA",
        "Pooled Tax",
        "Pooled CFADS",
        "Portfolio Senior Debt Service",
        "Avg DSCR",
        "Min DSCR",
        "Portfolio Debt",
    ]
    portfolio_sponsor = portfolio_result.portfolio_sponsor_irr
    sponsor_label = (
        "Sponsor IRR (placeholder)"
        if portfolio_sponsor == 0.0 or portfolio_sponsor is None
        else f"Sponsor IRR"
    )
    if portfolio_result.portfolio_project_irr not in (None, 0.0):
        labels.append("Portfolio Project IRR")
    labels.append(sponsor_label)

    values = [
        _safe_get_or_none(portfolio_result, 'total_revenue_keur'),
        _safe_get_or_none(portfolio_result, 'total_ebitda_keur'),
        _safe_get_or_none(portfolio_result, 'total_tax_keur'),
        sum(portfolio_result.pooled_cfads_schedule) if portfolio_result.pooled_cfads_schedule else 0.0,
        _safe_get_or_none(portfolio_result, 'total_senior_ds_keur'),
        _safe_get_or_none(portfolio_result, 'avg_dscr'),
        _safe_get_or_none(portfolio_result, 'min_dscr'),
        _safe_get_or_none(portfolio_result, 'portfolio_debt_keur'),
    ]
    if portfolio_result.portfolio_project_irr not in (None, 0.0):
        values.append(_safe_get_or_none(portfolio_result, 'portfolio_project_irr'))
    values.append(portfolio_sponsor if portfolio_sponsor not in (None, 0.0) else "n/a")

    df = pd.DataFrame({"Value": values}, index=labels)
    df.index.name = "Metric"
    return df


def aggregate_period_table_annual(df: pd.DataFrame, ratio_rows: tuple[str, ...] = ("DSCR", "LLCR", "PLCR")) -> pd.DataFrame:
    """Aggregate semiannual DataFrame to annual by summing or taking min for ratio rows.

    Columns are expected to be date-like (YYYY-MM-DD).
    Groups by year prefix (first 4 chars) and sums numeric rows.
    For ratio rows, takes the minimum over the year.
    """
    if df.empty or len(df.columns) == 0:
        return df

    # Identify year groups from column names
    year_groups: dict[str, list[str]] = {}
    for col in df.columns:
        col_str = str(col)
        # Try to extract year
        m = re.match(r"(\d{4})", col_str)
        if m:
            year = m.group(1)
        else:
            year = col_str  # fallback: treat as-is
        year_groups.setdefault(year, []).append(col_str)

    result_rows = {}
    for row_label in df.index:
        row = df.loc[row_label]
        is_ratio = row_label in ratio_rows
        agg_values = []
        for year, cols in sorted(year_groups.items()):
            year_vals = [row[c] for c in cols if c in row.index]
            if is_ratio:
                agg_values.append(min(year_vals))
            else:
                agg_values.append(sum(year_vals))
        result_rows[row_label] = agg_values

    result_df = pd.DataFrame(result_rows, index=sorted(year_groups.keys())).T
    result_df.index.name = df.index.name or "Line Item"
    return result_df