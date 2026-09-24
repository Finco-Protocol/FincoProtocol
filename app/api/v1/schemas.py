"""A1/A2 Radar API Pydantic response schemas.

All response bodies follow the standard envelope:
  {
    "api_version": "v1",
    "state": "<availability string>",
    "economic_asset_uid": "<uid or null>",
    "data": {...},
    "freshness": {...},
    "evidence": {...}
  }

MISSING != ZERO is preserved from the E1 authority: Optional[float] fields
distinguish genuine 0.0 from absent/null.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field

API_VERSION = "v1"


# ── shared envelope ───────────────────────────────────────────────────────────

class ApiErrorEnvelope(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    api_version: str = API_VERSION
    error: str
    detail: str
    economic_asset_uid: Optional[str] = None


class RadarEnvelope(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    api_version: str = API_VERSION
    state: str
    economic_asset_uid: Optional[str] = None
    data: Optional[Dict[str, Any]] = None
    freshness: Optional[Dict[str, Any]] = None
    evidence: Optional[Dict[str, Any]] = None


class AssetListEnvelope(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    api_version: str = API_VERSION
    state: str
    data: Optional[Dict[str, Any]] = None


# ── per-section helpers (typed dicts serialised to plain dicts) ───────────────

def deployment_out(key) -> Dict[str, Any]:
    return {
        "chain_id": key.chain_id,
        "contract_address": key.contract_address,
        "canonical_id": key.canonical_id,
    }


def equity_identity_out(asset) -> Optional[Dict[str, Any]]:
    if asset is None:
        return None
    return {
        "robinhood_token_symbol": asset.robinhood_token_symbol,
        "underlying_ticker": asset.underlying_ticker,
        "name": asset.name,
        "token_contract_address": asset.token_contract_address,
        "chain_network": asset.chain_network,
        "underlying_exchange": asset.underlying_exchange,
        "cik": asset.cik,
        "figi": asset.figi,
        "currency": asset.currency,
        "security_type": asset.security_type,
        "active": asset.active,
        "first_seen_at": asset.first_seen_at,
        "last_seen_at": asset.last_seen_at,
    }


def freshness_out(freshness) -> Dict[str, Any]:
    return {
        "ttm_period_end": freshness.ttm_period_end,
        "ttm_filing_date": freshness.ttm_filing_date,
        "ttm_fetched_at": freshness.ttm_fetched_at,
        "ttm_normalized_at": freshness.ttm_normalized_at,
        "quarterly_period_end": freshness.quarterly_period_end,
        "quarterly_fetched_at": freshness.quarterly_fetched_at,
        "annual_period_end": freshness.annual_period_end,
        "annual_fetched_at": freshness.annual_fetched_at,
        "profile_fetched_at": freshness.profile_fetched_at,
        "asset_last_seen_at": freshness.asset_last_seen_at,
    }


def _json_field_out(jf) -> Optional[Dict[str, Any]]:
    if jf is None:
        return None
    return {
        "value": jf.value,
        "absent": jf.absent,
        "parse_error": jf.parse_error,
    }


def _derived_out(d) -> Optional[Dict[str, Any]]:
    if d is None:
        return None
    return {
        "revenues": d.revenues,
        "revenue_growth": d.revenue_growth,
        "gross_margin": d.gross_margin,
        "ebit_margin": d.ebit_margin,
        "ebitda_margin": d.ebitda_margin,
        "net_margin": d.net_margin,
        "free_cash_flow": d.free_cash_flow,
        "fcf_margin": d.fcf_margin,
        "return_on_equity": d.return_on_equity,
        "net_debt": d.net_debt,
        "debt_to_equity": d.debt_to_equity,
    }


def snapshot_out(snap) -> Optional[Dict[str, Any]]:
    if snap is None:
        return None
    return {
        "ticker": snap.ticker,
        "timeframe": snap.timeframe,
        "fiscal_year": snap.fiscal_year,
        "fiscal_quarter": snap.fiscal_quarter,
        "period_end": snap.period_end,
        "filing_date": snap.filing_date,
        "provider": snap.provider,
        "fetched_at": snap.fetched_at,
        "normalized_at": snap.normalized_at,
        "income_statement": _json_field_out(snap.income_statement),
        "balance_sheet": _json_field_out(snap.balance_sheet),
        "cash_flow_statement": _json_field_out(snap.cash_flow_statement),
        "derived": _derived_out(snap.derived),
    }


def company_profile_out(profile) -> Optional[Dict[str, Any]]:
    if profile is None:
        return None
    return {
        "ticker": profile.ticker,
        "cik": profile.cik,
        "provider": profile.provider,
        "fetched_at": profile.fetched_at,
        "profile": _json_field_out(profile.profile),
    }


def dividend_out(div) -> Dict[str, Any]:
    return {
        "ticker": div.ticker,
        "external_id": div.external_id,
        "cash_amount": div.cash_amount,
        "currency": div.currency,
        "declaration_date": div.declaration_date,
        "ex_dividend_date": div.ex_dividend_date,
        "record_date": div.record_date,
        "pay_date": div.pay_date,
        "frequency": div.frequency,
        "dividend_type": div.dividend_type,
        "first_seen_at": div.first_seen_at,
    }


def split_out(split) -> Dict[str, Any]:
    return {
        "ticker": split.ticker,
        "external_id": split.external_id,
        "execution_date": split.execution_date,
        "split_from": split.split_from,
        "split_to": split.split_to,
        "first_seen_at": split.first_seen_at,
    }


def lineage_out(lin) -> Dict[str, Any]:
    return {
        "lineage_id": lin.lineage_id,
        "ticker": lin.ticker,
        "stage": lin.stage,
        "provider": lin.provider,
        "source_contract": lin.source_contract,
        "endpoint": lin.endpoint,
        "payload_hash": lin.payload_hash,
        "normalized_ref": lin.normalized_ref,
        "fetched_at": lin.fetched_at,
    }


# ── A2: execution simulation schemas ─────────────────────────────────────────


def _fix_execution_simulation_request_schema(schema: dict) -> None:
    """Override OpenAPI schema to document the strict public string contract.

    Runtime fields remain Any so malformed values reach the handler and return
    400 rather than Pydantic 422.  This callable replaces the generated Any
    field schemas with the accurate public enum contract and marks both fields
    required."""
    schema["required"] = ["direction", "notional_usd"]
    props = schema.setdefault("properties", {})
    props["direction"] = {
        "type": "string",
        "enum": ["BUY", "SELL"],
        "description": "Trade direction: 'BUY' or 'SELL'.",
        "examples": ["BUY", "SELL"],
        "title": "Direction",
    }
    props["notional_usd"] = {
        "type": "string",
        "enum": ["100", "1000"],
        "description": "Requested notional in USD (exact string: '100' or '1000').",
        "examples": ["100", "1000"],
        "title": "Notional Usd",
    }


class ExecutionSimulationRequest(BaseModel):
    """A2 POST body: direction and notional_usd.

    Both fields use Any internally so Pydantic never raises 422 for field
    value errors; the route handler owns all public validation and returns
    400 explicitly.

    Public contract: STRICT STRING INPUT ONLY.
    Valid:    "100", "1000" for notional_usd; "BUY", "SELL" for direction.
    Invalid:  integers, floats, booleans, null, arrays, objects — all → 400.

    OpenAPI schema is overridden via json_schema_extra to expose the correct
    string enum contract while preserving the Any runtime type.
    """
    model_config = ConfigDict(
        populate_by_name=True,
        json_schema_extra=_fix_execution_simulation_request_schema,
    )

    direction: Any = Field(
        default=None,
        description="Trade direction: 'BUY' or 'SELL'.",
        examples=["BUY", "SELL"],
    )
    notional_usd: Any = Field(
        default=None,
        description="Requested notional in USD (exact string: '100' or '1000').",
        examples=["100", "1000"],
    )


class ModelReferenceListEnvelope(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    api_version: str = API_VERSION
    state: str
    data: Optional[Dict[str, Any]] = None


class ModelReferenceEnvelope(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    api_version: str = API_VERSION
    state: str
    reference_key: Optional[str] = None
    data: Optional[Dict[str, Any]] = None


class ExecutionSimulationEnvelope(BaseModel):
    """A2 POST /execution-simulation response envelope."""
    model_config = ConfigDict(populate_by_name=True)

    api_version: str = API_VERSION
    state: str
    economic_asset_uid: Optional[str] = None
    snapshot_id: Optional[str] = None
    simulation: Optional[Dict[str, Any]] = None
    identity: Optional[Dict[str, Any]] = None
    reference: Optional[Dict[str, Any]] = None
    execution: Optional[Dict[str, Any]] = None
    gap: Optional[Dict[str, Any]] = None
    freshness: Optional[Dict[str, Any]] = None
