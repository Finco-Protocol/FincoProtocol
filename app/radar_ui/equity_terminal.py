"""E3 Company Terminal view model.

Builds presentation dicts for GET /radar/equity/{economic_asset_uid}.

Rules:
- MISSING != ZERO: None → "—"; 0.0 → "0.00"
- Statement adapter: JSON rendered as-is; no unit conversions; no field
  hardcoding; nested dicts flattened deterministically as "parent.child"
- SOURCE_DATA_MALFORMED when a statement field is present but not valid JSON
- No market prices, no quotes, no spreads, no GAP fields
- identity_state: VERIFIED/IDENTITY_MISMATCH/PARTIAL_IDENTITY/NOT_AVAILABLE
- IDENTITY_MISMATCH suppresses all financial data sections
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence, Tuple

from finco_radar.equity.config import EquityDBModeError
from finco_radar.equity.models import (
    AvailabilityState,
    EquityCompanyHistoryBundle,
    FinancialSnapshot,
    FundamentalsFreshness,
    JsonField,
)
from app.radar_ui.equity_view_model import _fmt_float, _fmt_currency, _fmt_percent, _fmt_ratio_raw


def get_history_for_terminal(
    token_symbol: str,
    **kwargs,
) -> EquityCompanyHistoryBundle:
    """E3 router entry point: resolve a token symbol to an EquityCompanyHistoryBundle.

    Lazy-imports get_equity_company_history from the E1 service so router.py
    never needs to import from finco_radar directly (frozen gate compliance).

    Catches EquityDBModeError at the application boundary and returns a
    FUNDAMENTALS_CONFIG_INVALID bundle rather than letting it become a 500.
    """
    from finco_radar.equity import get_equity_company_history
    try:
        return get_equity_company_history(token_symbol, **kwargs)
    except EquityDBModeError:
        return EquityCompanyHistoryBundle(
            robinhood_token_symbol=token_symbol,
            asset=None,
            company_profile=None,
            annual_history=(),
            quarterly_history=(),
            ttm_history=(),
            recent_dividends=(),
            recent_splits=(),
            source_lineage=(),
            availability=AvailabilityState.FUNDAMENTALS_CONFIG_INVALID,
            freshness=FundamentalsFreshness(
                ttm_period_end=None, ttm_filing_date=None, ttm_fetched_at=None,
                ttm_normalized_at=None, quarterly_period_end=None,
                quarterly_fetched_at=None, annual_period_end=None,
                annual_fetched_at=None, profile_fetched_at=None,
                asset_last_seen_at=None,
            ),
        )


def validate_terminal_identity(
    selected_symbol: str,
    selected_contract: Optional[str],
    bundle: EquityCompanyHistoryBundle,
) -> str:
    """Compare Robinhood universe identity vs E1 DB identity.

    Precedence (F06):
      1. bundle.asset is None                         → NOT_AVAILABLE
      2. symbol mismatch (case-insensitive)           → IDENTITY_MISMATCH
      3. symbol matches, either contract absent       → PARTIAL_IDENTITY
      4. both contracts present but differ            → IDENTITY_MISMATCH
      5. symbol and contract both match               → VERIFIED

    A known symbol mismatch is never downgraded to PARTIAL_IDENTITY.
    """
    if bundle.asset is None:
        return "NOT_AVAILABLE"

    db_symbol = bundle.asset.robinhood_token_symbol
    db_contract = bundle.asset.token_contract_address

    # Step 2: symbol takes absolute precedence
    if db_symbol.upper() != selected_symbol.upper():
        return "IDENTITY_MISMATCH"

    # Symbol matches — evaluate contract
    if not selected_contract or not db_contract:
        return "PARTIAL_IDENTITY"

    if db_contract.lower() != selected_contract.lower():
        return "IDENTITY_MISMATCH"

    return "VERIFIED"


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


# ── field presentation maps ───────────────────────────────────────────────────
# Source-proven from OpenClaw equity data; unknown fields rendered with raw key.

_INCOME_FIELD_MAP: Dict[str, str] = {
    # Core income line items (MASSIVE / LEGACY_MASSIVE_VX snake_case keys)
    "revenues": "Revenue",
    "cost_of_revenue": "Cost of Revenue",
    "cost_of_revenue_goods": "Cost of Revenue (Goods)",
    "cost_of_revenue_services": "Cost of Revenue (Services)",
    "gross_profit": "Gross Profit",
    "research_and_development": "R&D",
    "selling_general_and_administrative_expenses": "SG&A",
    "operating_expenses": "Operating Expenses",
    "other_operating_expenses": "Other Operating Expenses",
    "benefits_costs_expenses": "Benefits, Costs & Expenses",
    "costs_and_expenses": "Total Costs & Expenses",
    "operating_income_loss": "Operating Income",
    "interest_expense_operating": "Interest Expense",
    "nonoperating_income_loss": "Non-Operating Income",
    "income_loss_before_equity_method_investments": "Income (Before Equity Method)",
    "income_loss_from_continuing_operations_before_tax": "Pre-Tax Income",
    "income_tax_expense_benefit": "Income Tax",
    "income_tax_expense_benefit_current": "Income Tax (Current)",
    "income_tax_expense_benefit_deferred": "Income Tax (Deferred)",
    "income_loss_from_continuing_operations_after_tax": "After-Tax Income",
    "net_income_loss": "Net Income",
    "net_income_loss_attributable_to_parent": "Net Income (Parent)",
    "net_income_loss_attributable_to_noncontrolling_interest": "Net Income (NCI)",
    "net_income_loss_available_to_common_stockholders_basic": "Net Income (Common)",
    "participating_securities_distributed_and_undistributed_earnings_loss_basic": "Participating Securities",
    "preferred_stock_dividends_and_other_adjustments": "Preferred Dividends & Adj.",
    "common_stock_dividends": "Common Stock Dividends",
    "depreciation_and_amortization": "D&A",
    "basic_earnings_per_share": "EPS (Basic)",
    "diluted_earnings_per_share": "EPS (Diluted)",
    "basic_average_shares": "Shares (Basic)",
    "diluted_average_shares": "Shares (Diluted)",
}

_BALANCE_FIELD_MAP: Dict[str, str] = {
    # Assets (MASSIVE / LEGACY_MASSIVE_VX snake_case keys)
    "assets": "Total Assets",
    "current_assets": "Current Assets",
    "cash": "Cash & Equivalents",
    "inventory": "Inventory",
    "prepaid_expenses": "Prepaid Expenses",
    "other_current_assets": "Other Current Assets",
    "noncurrent_assets": "Non-Current Assets",
    "fixed_assets": "Fixed Assets (PP&E)",
    "intangible_assets": "Intangible Assets",
    "other_noncurrent_assets": "Other Non-Current Assets",
    # Liabilities
    "liabilities": "Total Liabilities",
    "current_liabilities": "Current Liabilities",
    "accounts_payable": "Accounts Payable",
    "wages": "Wages Payable",
    "other_current_liabilities": "Other Current Liabilities",
    "noncurrent_liabilities": "Non-Current Liabilities",
    "long_term_debt": "Long-term Debt",
    "other_noncurrent_liabilities": "Other Non-Current Liabilities",
    "commitments_and_contingencies": "Commitments & Contingencies",
    # Equity
    "equity": "Total Equity",
    "equity_attributable_to_parent": "Equity (to Parent)",
    "equity_attributable_to_noncontrolling_interest": "Equity (NCI)",
    "temporary_equity": "Temporary Equity",
    "temporary_equity_attributable_to_parent": "Temporary Equity (Parent)",
    "redeemable_noncontrolling_interest": "Redeemable NCI",
    "liabilities_and_equity": "Liabilities & Equity",
}

_CASHFLOW_FIELD_MAP: Dict[str, str] = {
    # Cash flow activities (MASSIVE / LEGACY_MASSIVE_VX snake_case keys)
    "net_cash_flow_from_operating_activities": "Operating Cash Flow",
    "net_cash_flow_from_operating_activities_continuing": "Operating CF (Continuing)",
    "net_cash_flow_from_investing_activities": "Investing Cash Flow",
    "net_cash_flow_from_investing_activities_continuing": "Investing CF (Continuing)",
    "net_cash_flow_from_financing_activities": "Financing Cash Flow",
    "net_cash_flow_from_financing_activities_continuing": "Financing CF (Continuing)",
    "net_cash_flow_continuing": "Net Cash Flow (Continuing)",
    "net_cash_flow": "Net Change in Cash",
    "exchange_gains_losses": "FX Gains / Losses",
}

_STMT_FIELD_MAPS: Dict[str, Dict[str, str]] = {
    "income_statement": _INCOME_FIELD_MAP,
    "balance_sheet": _BALANCE_FIELD_MAP,
    "cash_flow_statement": _CASHFLOW_FIELD_MAP,
}

_NAV_STMT_TO_FIELD_KEY: Dict[str, str] = {
    "income": "income_statement",
    "balance": "balance_sheet",
    "cashflow": "cash_flow_statement",
}


def _period_label(snap: FinancialSnapshot) -> str:
    """Human-readable period label for statement matrix column headers."""
    if snap.timeframe == "annual":
        return f"FY{snap.fiscal_year}" if snap.fiscal_year else (snap.period_end or "?")
    if snap.timeframe == "quarterly":
        q = snap.fiscal_quarter or ""
        y = snap.fiscal_year or ""
        label = f"{q} {y}".strip()
        return label or (snap.period_end or "?")
    return f"TTM {snap.period_end}" if snap.period_end else "TTM"


def _build_statement_matrix(
    snapshots: Sequence,
    stmt_key: str,
) -> dict:
    """Build a multi-period statement cross-tab for the Financials tab.

    stmt_key: "income_statement" | "balance_sheet" | "cash_flow_statement"

    Matrix-level state (F07 — SOURCE_DATA_MALFORMED != NOT_AVAILABLE):
      AVAILABLE            all periods available (at least one)
      PARTIAL              mix of available + malformed/absent
      SOURCE_DATA_MALFORMED all periods present but all have parse errors
      NOT_AVAILABLE        no periods, or all absent

    Returns:
      period_headers: list[{label, period_end, timeframe, fiscal_year, fiscal_quarter, state}]
      rows: list[{field_key, label, cells: list[str]}]
      unit_note: "Source values — no unit conversion applied."
      available: bool  (True when AVAILABLE or PARTIAL)
      state: str       matrix-level state
      stmt_key: str

    Cell values: "—" for missing/absent/malformed; formatted value otherwise.
    0/0.0 → displayed zero (MISSING != ZERO invariant).
    Negative values preserved.
    No unit conversions, no derived calculations.
    """
    field_map = _STMT_FIELD_MAPS.get(stmt_key, {})

    period_data: List[Tuple[dict, Optional[dict], str]] = []
    for snap in snapshots:
        stmt_field: JsonField = getattr(snap, stmt_key)
        header = {
            "label": _period_label(snap),
            "period_end": snap.period_end,
            "timeframe": snap.timeframe,
            "fiscal_year": snap.fiscal_year,
            "fiscal_quarter": snap.fiscal_quarter,
        }
        if stmt_field.absent:
            period_data.append((header, None, "NOT_AVAILABLE"))
        elif stmt_field.parse_error is not None:
            period_data.append((header, None, "SOURCE_DATA_MALFORMED"))
        else:
            flat = dict(_flatten_dict(stmt_field.value or {}))
            period_data.append((header, flat, "AVAILABLE"))

    # Matrix-level state derivation
    if not period_data:
        matrix_state = "NOT_AVAILABLE"
    else:
        available_count = sum(1 for _, _, s in period_data if s == "AVAILABLE")
        malformed_count = sum(1 for _, _, s in period_data if s == "SOURCE_DATA_MALFORMED")
        if available_count == len(period_data):
            matrix_state = "AVAILABLE"
        elif available_count > 0:
            matrix_state = "PARTIAL"
        elif malformed_count > 0:
            matrix_state = "SOURCE_DATA_MALFORMED"
        else:
            matrix_state = "NOT_AVAILABLE"

    matrix_available = matrix_state in ("AVAILABLE", "PARTIAL")

    # Union all field paths from available periods
    all_fields_set: set = set()
    for _, fdict, _ in period_data:
        if fdict is not None:
            all_fields_set.update(fdict.keys())

    # Known fields in map order, then unknown fields sorted alphabetically
    known_ordered = [k for k in field_map if k in all_fields_set]
    unknown_sorted = sorted(all_fields_set - set(known_ordered))
    all_fields = known_ordered + unknown_sorted

    period_headers = [
        {**h, "state": col_state}
        for h, _, col_state in period_data
    ]

    rows = []
    for fkey in all_fields:
        label = field_map.get(fkey, fkey)
        cells = []
        for _, fdict, col_state in period_data:
            if col_state != "AVAILABLE" or fdict is None:
                cells.append("—")
            elif fkey not in fdict:
                cells.append("—")
            else:
                cells.append(_fmt_statement_value(fdict[fkey]))
        rows.append({"field_key": fkey, "label": label, "cells": cells})

    return {
        "period_headers": period_headers,
        "rows": rows,
        "unit_note": "Source values — no unit conversion applied.",
        "available": matrix_available,
        "state": matrix_state,
        "stmt_key": stmt_key,
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


def _build_snapshot_evidence_row(snap: FinancialSnapshot) -> dict:
    """Build per-period evidence metadata. Never includes raw_payload_json."""
    return {
        "timeframe": snap.timeframe,
        "fiscal_year": snap.fiscal_year or "—",
        "fiscal_quarter": snap.fiscal_quarter or "—",
        "period_end": snap.period_end or "—",
        "filing_date": snap.filing_date or "—",
        "provider": snap.provider or "—",
        "source_contract": snap.source_contract or "—",
        "fetched_at": snap.fetched_at or "—",
        "normalized_at": snap.normalized_at or "—",
        "payload_hash": snap.payload_hash or "—",
    }


# ── main terminal view builder ────────────────────────────────────────────────

def build_terminal_view(
    bundle: EquityCompanyHistoryBundle,
    economic_asset_uid: str,
    fallback_name: str = "",
    identity_state: str = "NOT_AVAILABLE",
    selected_chain_id: Optional[str] = None,
    selected_contract_address: Optional[str] = None,
    nav: Optional[dict] = None,
    selected_symbol: str = "",
    selected_name: str = "",
) -> dict[str, Any]:
    """Build the E3 Company Terminal view dict from a history bundle.

    Always returns a dict; 'state' and 'nav' keys always present.

    identity_state controls financial data suppression:
      IDENTITY_MISMATCH → financial sections are empty (suppress all financials).
    """
    if nav is None:
        nav = {"tab": "overview", "timeframe": "annual", "statement": "income"}

    availability = bundle.availability

    if availability == AvailabilityState.FUNDAMENTALS_CONFIG_INVALID:
        return {
            "state": "FUNDAMENTALS_CONFIG_INVALID",
            "available": False,
            "economic_asset_uid": economic_asset_uid,
            "nav": nav,
        }

    if availability == AvailabilityState.SOURCE_UNAVAILABLE:
        return {
            "state": "SOURCE_UNAVAILABLE",
            "available": False,
            "economic_asset_uid": economic_asset_uid,
            "nav": nav,
        }

    if availability == AvailabilityState.NOT_FOUND:
        return {
            "state": "FUNDAMENTALS_NOT_FOUND",
            "available": False,
            "economic_asset_uid": economic_asset_uid,
            "symbol": selected_symbol,
            "company_name": selected_name or selected_symbol,
            "message": "Asset exists in Robinhood universe, but no matching fundamentals record is available.",
            "nav": nav,
        }

    # NOT_AVAILABLE, PARTIAL, AVAILABLE
    availability = bundle.availability

    # Selected Robinhood identity — always use selected params (Robinhood-selected), never bundle
    selected_token = {
        "symbol": selected_symbol,
        "economic_asset_uid": economic_asset_uid,
        "chain_id": selected_chain_id or "—",
        "contract_address": selected_contract_address or "—",
    }

    _empty_profile_evidence: dict = {
        "available": False,
        "provider": None,
        "source_contract": None,
        "fetched_at": None,
        "payload_hash": None,
    }
    _empty_freshness: dict = {
        "ttm_period_end": "—",
        "ttm_filing_date": "—",
        "quarterly_period_end": "—",
        "annual_period_end": "—",
        "profile_fetched_at": "—",
        "asset_last_seen_at": "—",
    }
    _empty_matrix: dict = {
        "available": False,
        "state": "NOT_AVAILABLE",
        "period_headers": [],
        "rows": [],
        "unit_note": "Source values — no unit conversion applied.",
        "stmt_key": _NAV_STMT_TO_FIELD_KEY.get(nav.get("statement", "income"), "income_statement"),
    }

    # F05: IDENTITY_MISMATCH — fail closed at a single explicit boundary.
    # No DB-derived company/fundamental/corporate-action data may be exposed.
    # The selected Robinhood universe identity remains authoritative.
    if identity_state == "IDENTITY_MISMATCH":
        # Fail closed: never read bundle identity on mismatch; use only Robinhood-selected params.
        _mismatch_symbol = selected_symbol if selected_symbol else "—"
        _mismatch_name = selected_name or fallback_name or _mismatch_symbol
        return {
            "state": availability.value,
            "available": False,
            "economic_asset_uid": economic_asset_uid,
            "symbol": _mismatch_symbol,
            "company_name": _mismatch_name,
            "identity": None,
            "identity_state": "IDENTITY_MISMATCH",
            "profile": None,
            "profile_evidence": _empty_profile_evidence,
            "snapshot_evidence": [],
            "annual_history": [],
            "quarterly_history": [],
            "ttm_history": [],
            "statement_matrix": _empty_matrix,
            "dividends": [],
            "splits": [],
            "lineage": [],
            "nav": nav,
            "selected_token": selected_token,
            "freshness": _empty_freshness,
            "execution_simulator_url": f"/radar?asset_uid={economic_asset_uid}#radar-panels",
            "radar_url": "/radar",
        }

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

    # Profile section (Overview tab)
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
                "payload_hash": profile.payload_hash or "—",
            }
        else:
            profile_section = {
                "available": False,
                "absent": prof_json.absent,
                "parse_error": prof_json.parse_error,
                "fetched_at": profile.fetched_at or "—",
                "payload_hash": profile.payload_hash or "—",
            }

    # Profile evidence (Evidence tab)
    if profile is not None:
        profile_evidence: dict = {
            "available": True,
            "provider": profile.provider or "—",
            "source_contract": profile.source_contract or "—",
            "fetched_at": profile.fetched_at or "—",
            "payload_hash": profile.payload_hash or "—",
        }
    else:
        profile_evidence = _empty_profile_evidence

    # Snapshot evidence (all timeframes, all periods — no raw_payload_json)
    snapshot_evidence_rows = [
        _build_snapshot_evidence_row(s)
        for s in (
            list(bundle.annual_history)
            + list(bundle.quarterly_history)
            + list(bundle.ttm_history)
        )
    ]

    # Financial history rows
    annual_rows = [_build_snapshot_row(s) for s in bundle.annual_history]
    quarterly_rows = [_build_snapshot_row(s) for s in bundle.quarterly_history]
    ttm_rows = [_build_snapshot_row(s) for s in bundle.ttm_history]

    # Statement matrix for Financials tab
    nav_timeframe = nav.get("timeframe", "annual")
    nav_statement = nav.get("statement", "income")
    stmt_key = _NAV_STMT_TO_FIELD_KEY.get(nav_statement, "income_statement")
    timeframe_snapshots_map: dict = {
        "annual": bundle.annual_history,
        "quarterly": bundle.quarterly_history,
        "ttm": bundle.ttm_history,
    }
    snapshots_for_matrix = timeframe_snapshots_map.get(nav_timeframe, bundle.annual_history)
    statement_matrix = _build_statement_matrix(snapshots_for_matrix, stmt_key)

    # Corporate actions — all authority fields
    dividend_rows = [
        {
            "declaration_date": d.declaration_date or "—",
            "ex_dividend_date": d.ex_dividend_date or "—",
            "record_date": d.record_date or "—",
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

    # Source lineage — no raw_payload_json
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
        "identity_state": identity_state,
        "profile": profile_section,
        "profile_evidence": profile_evidence,
        "snapshot_evidence": snapshot_evidence_rows,
        "annual_history": annual_rows,
        "quarterly_history": quarterly_rows,
        "ttm_history": ttm_rows,
        "statement_matrix": statement_matrix,
        "dividends": dividend_rows,
        "splits": split_rows,
        "lineage": lineage_rows,
        "nav": nav,
        "selected_token": selected_token,
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
