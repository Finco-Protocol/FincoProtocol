"""E2 presentation-only view model for equity fundamentals (E1 authority).

Rules enforced by construction:

- formats only; no new financial derivation except revenue_growth (see below)
- MISSING != ZERO: value is None → "—"; value == 0.0 → display zero
- negative values remain negative (never clamped)
- margin and return fields (gross_margin, ebit_margin, ebitda_margin,
  net_margin, fcf_margin, return_on_equity) are source fractions → × 100 → "%"
- revenues, free_cash_flow, net_debt: raw base-currency absolute values
  (e.g. 466_823_000_000 == USD 466.8B); formatted as compact $M/$B/$T
- revenue_growth: source field is universally NULL; derived from comparable
  quarterly snapshots via finco_radar.equity.derived.compute_ttm_revenue_growth
- debt_to_equity: dimensionless ratio; raw float (4 dp)
- company name follows deterministic precedence (see _company_name)
- no market prices, quotes, spreads or GAP fields

PROVEN UNIT CONTRACTS (equity_fundamentals.db, 2026-09-23):
  revenues / free_cash_flow / net_debt:
    raw base-currency absolute values (USD absolute, not thousands/millions)
    AAPL TTM 2026-06-27 = 466,823,000,000 → $466.8B
  margin/return fields: fractions (0.4865 == 48.65%)
  revenue_growth (source field): NULL universally → derive from quarterly history
"""
from __future__ import annotations

from typing import Any, Optional

from app.radar_ui.equity_enrichment import EnrichmentState, EquityEnrichmentResult  # noqa: F401
from finco_radar.equity.derived import compute_ttm_revenue_growth
from finco_radar.equity.models import (
    AvailabilityState,
    CompanyProfile,
    DerivedFundamentals,
    EquityAssetIdentity,
    EquityFundamentalsBundle,
    FinancialSnapshot,
    FundamentalsFreshness,
    JsonField,
)

# Per-field unit authority (proven from DB sample, 2026-09-23):
# - revenues/free_cash_flow/net_debt: raw absolute base-currency; compact display
# - margin/return fields: source fraction → × 100 → "%"
# - revenue_growth: NULL in source → derived from quarterly history as fraction
# - debt_to_equity: dimensionless ratio; raw float (4 dp)
UNIT_SEMANTICS_NOTE = (
    "monetary fields (revenues, FCF, net_debt) are raw base-currency absolute values "
    "displayed in compact units ($M/$B/$T); "
    "margin/return fields displayed as % (source fraction × 100); "
    "revenue_growth derived from quarterly history as YoY fraction"
)


# ── numeric formatters ────────────────────────────────────────────────────────

def _fmt_float(value: Optional[float], precision: int = 2) -> str:
    """Format an Optional[float] for display.

    None      → "—"  (genuinely missing)
    0.0       → "0.00" (genuine zero)
    negative  → preserved with minus sign
    """
    if value is None:
        return "—"
    fmt = f"{{:,.{precision}f}}"
    return fmt.format(value)


def _fmt_compact_currency(
    value: Optional[float],
    *,
    board: bool = False,
    currency_symbol: str = "$",
) -> str:
    """Format a raw base-currency absolute value in compact M/B/T units.

    PROVEN CONTRACT: revenues/free_cash_flow/net_debt are raw base-currency
    absolute values (e.g. 466_823_000_000 == USD 466.8B).  This formatter
    applies compact notation only — raw values are never mutated.

    None  → "—"   (missing; NOT zero)
    0.0   → "$0"  (genuine zero)
    board=True  → 1 decimal: $466.8B
    board=False → 2 decimals: $466.82B

    Thresholds (absolute value):
      < 1_000       → "$X" (or negative)
      < 1_000_000   → "$X.XK" / "$X.XXK"
      < 1_000_000_000 → "$X.XM" / "$X.XXM"
      < 1_000_000_000_000 → "$X.XB" / "$X.XXB"
      else          → "$X.XT" / "$X.XXT"

    Negative values: display "-$466.8B" form (minus before currency symbol).
    """
    if value is None:
        return "—"
    decimals = 1 if board else 2
    fmt_str = f"{{:.{decimals}f}}"
    sign = "-" if value < 0 else ""
    abs_val = abs(value)
    if abs_val == 0:
        return f"{currency_symbol}0"
    if abs_val < 1_000:
        return f"{sign}{currency_symbol}{fmt_str.format(abs_val)}"
    if abs_val < 1_000_000:
        return f"{sign}{currency_symbol}{fmt_str.format(abs_val / 1_000)}K"
    if abs_val < 1_000_000_000:
        return f"{sign}{currency_symbol}{fmt_str.format(abs_val / 1_000_000)}M"
    if abs_val < 1_000_000_000_000:
        return f"{sign}{currency_symbol}{fmt_str.format(abs_val / 1_000_000_000)}B"
    return f"{sign}{currency_symbol}{fmt_str.format(abs_val / 1_000_000_000_000)}T"


def _fmt_currency(value: Optional[float], *, board: bool = False) -> str:
    """Format a raw base-currency absolute value using compact notation.

    Delegates to _fmt_compact_currency with the proven unit contract:
    revenues/free_cash_flow/net_debt are raw absolute base-currency values.
    Raw values are never modified; only the display string is compacted.
    """
    return _fmt_compact_currency(value, board=board)


def _fmt_revenue_growth(value: Optional[float]) -> str:
    """Format a revenue growth fraction for display.

    value is a fraction (0.145 = +14.5%) as returned by
    compute_ttm_revenue_growth.  Displayed as +14.5% / -3.2% / 0.0%.

    None → "—"  (not available / not derivable)
    0.0  → "0.0%"  (genuine zero growth)
    """
    if value is None:
        return "—"
    pct = value * 100
    sign = "+" if pct > 0 else ""
    return f"{sign}{pct:.1f}%"


def _fmt_percent(value: Optional[float]) -> str:
    """Format a source-fraction field as a percentage.

    Applied to margin and return fields whose canonical derivation is a
    numerator/denominator ratio (e.g. gross_profit/revenue, net_income/equity).
    Multiplies by 100 and appends %; the raw value is preserved in the view
    dict's 'raw' key for evidence purposes.

    Do NOT use for revenue_growth — use _fmt_revenue_growth instead.
    """
    if value is None:
        return "—"
    return f"{value * 100:,.2f}%"


def _fmt_ratio_raw(value: Optional[float]) -> str:
    """Format a dimensionless ratio field as the raw source float.

    debt_to_equity is a ratio (e.g. -1.8x) not a percentage fraction;
    semantics are best expressed as a plain multiplier.
    """
    return _fmt_float(value, precision=4)


def _fmt_human_timestamp(ts_str: Optional[str]) -> str:
    """Format an ISO timestamp string as a human-readable display value.

    Input:  "2026-09-21T12:46:12.350937+00:00"
    Output: "21 Sep 2026 · 12:46 UTC"

    The raw value must be preserved in a 'title' attribute or '_raw' field
    for full precision access.  Returns "—" on None or parse failure.
    Timezone is always displayed as UTC to avoid ambiguity.
    """
    if not ts_str or ts_str == "—":
        return "—"
    try:
        # Strip fractional seconds and timezone; work in UTC
        ts = ts_str.strip()
        # Handle +00:00 / Z / no-tz variants
        if ts.endswith("Z"):
            ts = ts[:-1]
        elif "+" in ts[10:]:
            ts = ts[: ts.rindex("+", 10)]
        elif ts[10:].count("-") > 0:
            # negative UTC offset — remove it
            tail = ts[10:]
            idx = tail.rfind("-")
            if idx >= 0:
                ts = ts[: 10 + idx]
        # Remove sub-second
        if "." in ts:
            ts = ts[: ts.index(".")]
        from datetime import datetime
        dt = datetime.fromisoformat(ts)
        month_abbr = dt.strftime("%b")
        return f"{dt.day} {month_abbr} {dt.year} · {dt.strftime('%H:%M')} UTC"
    except (ValueError, AttributeError, TypeError):
        return ts_str or "—"


# ── company name precedence ────────────────────────────────────────────────────

def _company_name(
    bundle: EquityFundamentalsBundle,
    fallback_name: str,
) -> str:
    """Return the best available company name.

    Precedence (per E2 spec §16):
    1. E1 company/profile name if the profile JSON is valid and the name key
       is a non-empty string
    2. E1 asset.name
    3. Robinhood selected.token_name (caller-supplied fallback_name)
    4. canonical token symbol

    Malformed profile JSON does not erase a valid asset identity.
    """
    if bundle.company_profile is not None:
        prof = bundle.company_profile.profile
        if prof.is_available and isinstance(prof.value, dict):
            name = prof.value.get("name")
            if isinstance(name, str) and name.strip():
                return name.strip()
    if bundle.asset is not None and bundle.asset.name:
        return bundle.asset.name
    if fallback_name:
        return fallback_name
    return bundle.robinhood_token_symbol


# ── section builders ───────────────────────────────────────────────────────────

def _identity_section(
    asset: Optional[EquityAssetIdentity],
    fallback_name: str,
    bundle: EquityFundamentalsBundle,
) -> dict[str, Any]:
    if asset is None:
        return {
            "available": False,
            "symbol": bundle.robinhood_token_symbol,
            "company_name": fallback_name or bundle.robinhood_token_symbol,
            "underlying_ticker": None,
            "exchange": None,
            "currency": None,
            "security_type": None,
        }
    return {
        "available": True,
        "symbol": asset.robinhood_token_symbol,
        "company_name": _company_name(bundle, fallback_name),
        "underlying_ticker": asset.underlying_ticker,
        "exchange": asset.underlying_exchange,
        "currency": asset.currency,
        "security_type": asset.security_type,
    }


def _best_snapshot(
    latest_ttm: Optional[FinancialSnapshot],
    latest_quarterly: Optional[FinancialSnapshot],
    latest_annual: Optional[FinancialSnapshot],
) -> Optional[FinancialSnapshot]:
    """Return the best available snapshot using TTM → quarterly → annual precedence."""
    return latest_ttm or latest_quarterly or latest_annual


def _reporting_section(
    freshness: FundamentalsFreshness,
    latest_ttm: Optional[FinancialSnapshot],
    latest_quarterly: Optional[FinancialSnapshot],
    latest_annual: Optional[FinancialSnapshot],
) -> dict[str, Any]:
    best = _best_snapshot(latest_ttm, latest_quarterly, latest_annual)
    provider = best.provider if best else None
    source_contract = best.source_contract if best else None
    fetched_at = best.fetched_at if best else None
    normalized_at = best.normalized_at if best else None
    filing_date = best.filing_date if best else None
    return {
        "ttm_period_end": freshness.ttm_period_end or "—",
        "ttm_filing_date": freshness.ttm_filing_date or "—",
        "quarterly_period_end": freshness.quarterly_period_end or "—",
        "quarterly_fetched_at": freshness.quarterly_fetched_at or "—",
        "annual_period_end": freshness.annual_period_end or "—",
        "annual_fetched_at": freshness.annual_fetched_at or "—",
        "provider": provider or "—",
        "source_contract": source_contract or "—",
        "fetched_at": fetched_at or "—",
        "normalized_at": normalized_at or "—",
        "filing_date": filing_date or "—",
        "profile_fetched_at": freshness.profile_fetched_at or "—",
    }


def _ttm_metrics_section(
    latest_ttm: Optional[FinancialSnapshot],
    quarterly_history: tuple = (),
) -> dict[str, Any]:
    if latest_ttm is None:
        return {"available": False, "reason": "TTM_UNAVAILABLE", "fields": {}}

    derived_source = latest_ttm.derived_source
    if not derived_source.is_available:
        if derived_source.absent:
            return {
                "available": False,
                "reason": "TTM_DERIVED_ABSENT",
                "fields": {},
                "source_note": "derived_source is NULL in DB",
            }
        return {
            "available": False,
            "reason": "TTM_DERIVED_PARSE_ERROR",
            "parse_error": derived_source.parse_error,
            "fields": {},
            "source_note": "derived_source present but not valid JSON",
        }

    d: Optional[DerivedFundamentals] = latest_ttm.derived
    if d is None:
        return {"available": False, "reason": "TTM_DERIVED_NOT_EXTRACTED", "fields": {}}

    # Revenue growth is universally NULL in source; derive from comparable quarterly history.
    derived_rev_growth = compute_ttm_revenue_growth(quarterly_history)

    return {
        "available": True,
        "reason": None,
        "unit_semantics_note": UNIT_SEMANTICS_NOTE,
        "fields": {
            "revenues": {
                "label": "Revenue",
                "value": _fmt_currency(d.revenues),
                "raw": d.revenues,
                "is_missing": d.revenues is None,
                "unit_rule": "raw source value; currency unit from asset.currency if available",
            },
            "revenue_growth": {
                "label": "Revenue Growth",
                "value": _fmt_revenue_growth(derived_rev_growth),
                "raw": derived_rev_growth,
                "is_missing": derived_rev_growth is None,
                "unit_rule": "YoY TTM fraction derived from 8 comparable quarterly snapshots",
            },
            "gross_margin": {
                "label": "Gross Margin",
                "value": _fmt_percent(d.gross_margin),
                "raw": d.gross_margin,
                "is_missing": d.gross_margin is None,
                "unit_rule": "source-fraction proven; displayed as % (raw × 100)",
            },
            "ebit_margin": {
                "label": "EBIT Margin",
                "value": _fmt_percent(d.ebit_margin),
                "raw": d.ebit_margin,
                "is_missing": d.ebit_margin is None,
                "unit_rule": "source-fraction proven; displayed as % (raw × 100)",
            },
            "ebitda_margin": {
                "label": "EBITDA Margin",
                "value": _fmt_percent(d.ebitda_margin),
                "raw": d.ebitda_margin,
                "is_missing": d.ebitda_margin is None,
                "unit_rule": "source-fraction proven; displayed as % (raw × 100)",
            },
            "net_margin": {
                "label": "Net Margin",
                "value": _fmt_percent(d.net_margin),
                "raw": d.net_margin,
                "is_missing": d.net_margin is None,
                "unit_rule": "source-fraction proven; displayed as % (raw × 100)",
            },
            "free_cash_flow": {
                "label": "Free Cash Flow",
                "value": _fmt_currency(d.free_cash_flow),
                "raw": d.free_cash_flow,
                "is_missing": d.free_cash_flow is None,
                "unit_rule": "raw source value; currency unit from asset.currency if available",
            },
            "fcf_margin": {
                "label": "FCF Margin",
                "value": _fmt_percent(d.fcf_margin),
                "raw": d.fcf_margin,
                "is_missing": d.fcf_margin is None,
                "unit_rule": "source-fraction proven; displayed as % (raw × 100)",
            },
            "return_on_equity": {
                "label": "Return on Equity",
                "value": _fmt_percent(d.return_on_equity),
                "raw": d.return_on_equity,
                "is_missing": d.return_on_equity is None,
                "unit_rule": "source-fraction proven; displayed as % (raw × 100)",
            },
            "net_debt": {
                "label": "Net Debt",
                "value": _fmt_currency(d.net_debt),
                "raw": d.net_debt,
                "is_missing": d.net_debt is None,
                "unit_rule": "raw source value; currency unit from asset.currency if available",
            },
            "debt_to_equity": {
                "label": "Debt / Equity",
                "value": _fmt_ratio_raw(d.debt_to_equity),
                "raw": d.debt_to_equity,
                "is_missing": d.debt_to_equity is None,
                "unit_rule": "dimensionless ratio (e.g. -1.8×); not a percentage fraction",
            },
        },
    }


def _lineage_section(bundle: EquityFundamentalsBundle) -> dict[str, Any]:
    """Compact source/lineage block — follows same TTM → quarterly → annual precedence."""
    snap = _best_snapshot(bundle.latest_ttm, bundle.latest_quarterly, bundle.latest_annual)
    if snap is None:
        return {
            "available": False,
            "provider": None,
            "source_contract": None,
            "period_end": None,
            "filing_date": None,
            "fetched_at": None,
            "normalized_at": None,
            "payload_hash": None,
        }
    return {
        "available": True,
        "provider": snap.provider,
        "source_contract": snap.source_contract,
        "period_end": snap.period_end,
        "filing_date": snap.filing_date,
        "fetched_at": snap.fetched_at,
        "normalized_at": snap.normalized_at,
        "payload_hash": snap.payload_hash,
    }


# ── main view builder ─────────────────────────────────────────────────────────

def build_equity_view(
    result: EquityEnrichmentResult,
    fallback_name: str = "",
) -> dict[str, Any]:
    """Build the E2 equity fundamentals view dict from an enrichment result.

    Always returns a dict — callers do not need to guard for None.
    The 'state' key is always present so templates can branch on it.
    """
    state = result.state

    if state == EnrichmentState.FUNDAMENTALS_CONFIG_INVALID:
        return {
            "state": state.value,
            "available": False,
            "identity_note": result.identity_note,
        }

    if state == EnrichmentState.SOURCE_UNAVAILABLE:
        return {
            "state": state.value,
            "available": False,
            "identity_note": None,
        }

    if state == EnrichmentState.NOT_FOUND:
        return {
            "state": state.value,
            "available": False,
            "symbol": result.bundle.robinhood_token_symbol if result.bundle else "",
            "identity_note": None,
        }

    if state == EnrichmentState.NOT_AVAILABLE:
        bundle = result.bundle
        return {
            "state": state.value,
            "available": False,
            "symbol": bundle.robinhood_token_symbol if bundle else "",
            "identity": _identity_section(
                bundle.asset if bundle else None, fallback_name,
                bundle,
            ) if bundle else None,
            "identity_note": None,
        }

    if state == EnrichmentState.IDENTITY_MISMATCH:
        return {
            "state": state.value,
            "available": False,
            "identity_note": result.identity_note,
        }

    # AVAILABLE or PARTIAL
    bundle = result.bundle
    assert bundle is not None

    return {
        "state": state.value,
        "available": True,
        "symbol": bundle.robinhood_token_symbol,
        "identity": _identity_section(bundle.asset, fallback_name, bundle),
        "reporting": _reporting_section(
            bundle.freshness,
            bundle.latest_ttm,
            bundle.latest_quarterly,
            bundle.latest_annual,
        ),
        "ttm_metrics": _ttm_metrics_section(bundle.latest_ttm, bundle.quarterly_history),
        "lineage": _lineage_section(bundle),
        "identity_note": None,
    }


def build_equity_board_row(
    result: EquityEnrichmentResult,
    asset_uid: str,
    fallback_name: str = "",
    token_symbol: str = "",
) -> dict[str, Any]:
    """Build a compact board row dict for the Featured Equities board.

    Always returns a dict.  The 'state', 'symbol', 'company_name',
    'asset_uid' and 'details_url' keys are always present.
    Financial metrics (revenues, revenue_growth, gross_margin, fcf_margin,
    period_end) are shown only when AVAILABLE or PARTIAL.

    token_symbol: canonical Robinhood token symbol (e.g. "NVDA"), separate
    from asset_uid (e.g. "rh-equity-nvda-002").  When supplied it is used as
    the displayed symbol so UID values never leak into the symbol column.
    """
    state = result.state
    bundle = result.bundle

    # Displayed symbol: E1 canonical > caller token_symbol > fallback_name > asset_uid
    if bundle is not None and bundle.robinhood_token_symbol:
        symbol = bundle.robinhood_token_symbol
    elif token_symbol:
        symbol = token_symbol
    elif fallback_name:
        symbol = fallback_name
    else:
        symbol = asset_uid

    # Company name: best available
    company_name: str = fallback_name or symbol
    if bundle is not None:
        company_name = _company_name(bundle, fallback_name)

    base = {
        "state": state.value,
        "symbol": symbol,
        "company_name": company_name,
        "asset_uid": asset_uid,
        "details_url": f"/radar/equity/{asset_uid}",
    }

    if state not in (EnrichmentState.AVAILABLE, EnrichmentState.PARTIAL):
        return base

    assert bundle is not None
    ttm = bundle.latest_ttm
    d = ttm.derived if ttm is not None else None

    derived_rev_growth = compute_ttm_revenue_growth(bundle.quarterly_history)

    base.update({
        "revenues": _fmt_currency(d.revenues, board=True) if d else "—",
        "revenue_growth": _fmt_revenue_growth(derived_rev_growth),
        "gross_margin": _fmt_percent(d.gross_margin) if d else "—",
        "ebit_margin": _fmt_percent(d.ebit_margin) if d else "—",
        "period_end": (ttm.period_end or "—") if ttm else "—",
    })
    return base
