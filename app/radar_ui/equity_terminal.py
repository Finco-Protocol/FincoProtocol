"""E3 Company Terminal view model.

Builds presentation dicts for GET /radar/equity/{economic_asset_uid}.

Rules:
- MISSING != ZERO: None → "—"; 0.0 → "0.00"
- Statement adapter: JSON rendered as-is; no unit conversions; no field
  hardcoding; nested dicts flattened deterministically as "parent.child"
- SOURCE_DATA_MALFORMED when a statement field is present but not valid JSON
- No market prices, no quotes, no spreads, no GAP fields
"""
from __future__ import annotations

from typing import Any, List, Optional, Tuple

from finco_radar.equity.models import (
    AvailabilityState,
    EquityCompanyHistoryBundle,
    FinancialSnapshot,
    JsonField,
)
from app.radar_ui.equity_view_model import _fmt_float, _fmt_currency, _fmt_percent, _fmt_ratio_raw


def get_history_for_terminal(
    token_symbol: str,
    **kwargs,
) -> EquityCompanyHistoryBundle:
    """E3 router entry point: resolve a token symbol to an EquityCompanyHistoryBundle.

    Lazy-imports get_equity_company_history from the E1 service so router.py
    never needs to import from finco_radar directly.
    """
    from finco_radar.equity import get_equity_company_history
    return get_equity_company_history(token_symbol, **kwargs)


# ── statement adapter ─────────────────────────────────────────────────────────

def _flatten_dict(d: dict, prefix: str = "") -> List[Tuple[str, Any]]:
    """Flatten a dict deterministically.

    Nested dicts yield "parent.child" keys.
    Non-dict leaf values are returned as-is.
    Lists are skipped (not statement line items).
    Keys are sorted at each nesting level for deterministic output.
    """
    rows = []
    for key in sorted(d.keys()):
        val = d[key]
        full_key = f"{prefix}.{key}" if prefix else key
        if isinstance(val, dict):
            rows.extend(_flatten_dict(val, prefix=full_key))
        elif isinstance(val, list):
            pass  # lists are not statement line items; skip
        else:
            rows.append((full_key, val))
    return rows


def _fmt_statement_value(v: Any) -> str:
    """Format one statement field value for display.

    None  → "—"   (genuinely missing)
    0     → "0"   (explicit zero; not "—")
    float → str with up to 2 decimal places, commas
    int   → str with commas
    str   → as-is
    other → repr
    """
    if v is None:
        return "—"
    if isinstance(v, float):
        return _fmt_float(v, precision=2)
    if isinstance(v, int):
        return "{:,}".format(v)
    if isinstance(v, str):
        return v
    return repr(v)


def _adapt_statement(field: JsonField) -> dict:
    """Convert a JsonField statement to a presentation dict.

    Returns a dict with:
      'state': 'ABSENT' | 'SOURCE_DATA_MALFORMED' | 'AVAILABLE'
      'rows':  list of {'key': str, 'value': str} (only when AVAILABLE)
      'error': parse error string (only when SOURCE_DATA_MALFORMED)
    """
    if field.absent:
        return {"state": "ABSENT", "rows": [], "error": None}
    if field.parse_error is not None:
        return {
            "state": "SOURCE_DATA_MALFORMED",
            "rows": [],
            "error": field.parse_error,
        }
    assert field.value is not None
    raw_rows = _flatten_dict(field.value)
    return {
        "state": "AVAILABLE",
        "rows": [
            {"key": k, "value": _fmt_statement_value(v)}
            for k, v in raw_rows
        ],
        "error": None,
    }


# ── snapshot row builder ──────────────────────────────────────────────────────

def _build_snapshot_row(snap: FinancialSnapshot) -> dict:
    """Build a compact derived-metrics row for the financial history table."""
    d = snap.derived
    return {
        "timeframe": snap.timeframe,
        "period_end": snap.period_end or "—",
        "filing_date": snap.filing_date or "—",
        "fiscal_year": snap.fiscal_year or "—",
        "fiscal_quarter": snap.fiscal_quarter or "—",
        "provider": snap.provider or "—",
        "revenues": _fmt_currency(d.revenues) if d else "—",
        "revenue_growth": _fmt_float(d.revenue_growth) if d else "—",
        "gross_margin": _fmt_percent(d.gross_margin) if d else "—",
        "ebit_margin": _fmt_percent(d.ebit_margin) if d else "—",
        "ebitda_margin": _fmt_percent(d.ebitda_margin) if d else "—",
        "net_margin": _fmt_percent(d.net_margin) if d else "—",
        "free_cash_flow": _fmt_currency(d.free_cash_flow) if d else "—",
        "fcf_margin": _fmt_percent(d.fcf_margin) if d else "—",
        "return_on_equity": _fmt_percent(d.return_on_equity) if d else "—",
        "net_debt": _fmt_currency(d.net_debt) if d else "—",
        "debt_to_equity": _fmt_ratio_raw(d.debt_to_equity) if d else "—",
        "income_statement": _adapt_statement(snap.income_statement),
        "balance_sheet": _adapt_statement(snap.balance_sheet),
        "cash_flow_statement": _adapt_statement(snap.cash_flow_statement),
    }


# ── main terminal view builder ────────────────────────────────────────────────

def build_terminal_view(
    bundle: EquityCompanyHistoryBundle,
    economic_asset_uid: str,
    fallback_name: str = "",
) -> dict[str, Any]:
    """Build the E3 Company Terminal view dict from a history bundle.

    Always returns a dict; 'state' key always present.
    """
    availability = bundle.availability

    if availability == AvailabilityState.SOURCE_UNAVAILABLE:
        return {
            "state": "SOURCE_UNAVAILABLE",
            "available": False,
            "economic_asset_uid": economic_asset_uid,
        }

    if availability == AvailabilityState.NOT_FOUND:
        return {
            "state": "NOT_FOUND",
            "available": False,
            "economic_asset_uid": economic_asset_uid,
            "symbol": bundle.robinhood_token_symbol,
        }

    # NOT_AVAILABLE, PARTIAL, AVAILABLE
    asset = bundle.asset
    profile = bundle.company_profile

    # Company name: profile JSON name > asset.name > fallback_name > symbol
    company_name: str = fallback_name or bundle.robinhood_token_symbol
    if profile is not None:
        prof_json = profile.profile
        if prof_json.is_available and isinstance(prof_json.value, dict):
            n = prof_json.value.get("name")
            if isinstance(n, str) and n.strip():
                company_name = n.strip()
    if company_name == (fallback_name or bundle.robinhood_token_symbol) and asset and asset.name:
        company_name = asset.name

    # Identity section
    identity: Optional[dict] = None
    if asset is not None:
        identity = {
            "available": True,
            "symbol": asset.robinhood_token_symbol,
            "company_name": company_name,
            "underlying_ticker": asset.underlying_ticker,
            "exchange": asset.underlying_exchange,
            "currency": asset.currency,
            "security_type": asset.security_type,
            "cik": asset.cik,
            "figi": asset.figi,
        }

    # Company profile section
    profile_section: Optional[dict] = None
    if profile is not None:
        prof_json = profile.profile
        if prof_json.is_available and isinstance(prof_json.value, dict):
            profile_section = {
                "available": True,
                "rows": [
                    {"key": k, "value": _fmt_statement_value(v)}
                    for k, v in sorted(prof_json.value.items())
                    if not isinstance(v, (dict, list))
                ],
                "fetched_at": profile.fetched_at or "—",
                "provider": profile.provider or "—",
                "source_contract": profile.source_contract or "—",
            }
        else:
            profile_section = {
                "available": False,
                "absent": prof_json.absent,
                "parse_error": prof_json.parse_error,
                "fetched_at": profile.fetched_at or "—",
            }

    # Financial history tables
    annual_rows = [_build_snapshot_row(s) for s in bundle.annual_history]
    quarterly_rows = [_build_snapshot_row(s) for s in bundle.quarterly_history]
    ttm_rows = [_build_snapshot_row(s) for s in bundle.ttm_history]

    # Corporate actions
    dividend_rows = [
        {
            "ex_dividend_date": d.ex_dividend_date or "—",
            "pay_date": d.pay_date or "—",
            "cash_amount": _fmt_float(d.cash_amount) if d.cash_amount is not None else "—",
            "currency": d.currency or "—",
            "frequency": str(d.frequency) if d.frequency is not None else "—",
            "dividend_type": d.dividend_type or "—",
        }
        for d in bundle.recent_dividends
    ]
    split_rows = [
        {
            "execution_date": s.execution_date or "—",
            "split_from": _fmt_float(s.split_from) if s.split_from is not None else "—",
            "split_to": _fmt_float(s.split_to) if s.split_to is not None else "—",
        }
        for s in bundle.recent_splits
    ]

    # Lineage
    lineage_rows = [
        {
            "lineage_id": lin.lineage_id,
            "stage": lin.stage or "—",
            "provider": lin.provider or "—",
            "source_contract": lin.source_contract or "—",
            "endpoint": lin.endpoint or "—",
            "payload_hash": lin.payload_hash or "—",
            "fetched_at": lin.fetched_at or "—",
        }
        for lin in bundle.source_lineage
    ]

    # Freshness
    freshness = bundle.freshness

    return {
        "state": availability.value,
        "available": availability in (AvailabilityState.AVAILABLE, AvailabilityState.PARTIAL),
        "economic_asset_uid": economic_asset_uid,
        "symbol": bundle.robinhood_token_symbol,
        "company_name": company_name,
        "identity": identity,
        "profile": profile_section,
        "annual_history": annual_rows,
        "quarterly_history": quarterly_rows,
        "ttm_history": ttm_rows,
        "dividends": dividend_rows,
        "splits": split_rows,
        "lineage": lineage_rows,
        "freshness": {
            "ttm_period_end": freshness.ttm_period_end or "—",
            "ttm_filing_date": freshness.ttm_filing_date or "—",
            "quarterly_period_end": freshness.quarterly_period_end or "—",
            "annual_period_end": freshness.annual_period_end or "—",
            "profile_fetched_at": freshness.profile_fetched_at or "—",
            "asset_last_seen_at": freshness.asset_last_seen_at or "—",
        },
        "execution_simulator_url": f"/radar?asset_uid={economic_asset_uid}#radar-panels",
        "radar_url": "/radar",
    }
