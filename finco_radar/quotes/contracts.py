"""Typed, fail-closed execution quote contracts for FINCO Radar R0."""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
from typing import Any, Mapping, Sequence


class QuoteSide(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


class QuoteStatus(str, Enum):
    QUOTE_OK = "QUOTE_OK"
    QUOTE_UNAVAILABLE = "QUOTE_UNAVAILABLE"
    ROUTE_UNAVAILABLE = "ROUTE_UNAVAILABLE"
    INSUFFICIENT_LIQUIDITY = "INSUFFICIENT_LIQUIDITY"
    UNSUPPORTED_ASSET = "UNSUPPORTED_ASSET"
    SETTLEMENT_REFERENCE_UNAVAILABLE = "SETTLEMENT_REFERENCE_UNAVAILABLE"
    STALE_QUOTE = "STALE_QUOTE"
    AUTH_REQUIRED = "AUTH_REQUIRED"
    RATE_LIMITED = "RATE_LIMITED"
    QUOTE_SOURCE_ERROR = "QUOTE_SOURCE_ERROR"


class SettlementReferenceState(str, Enum):
    REFERENCE_CURRENT = "REFERENCE_CURRENT"
    REFERENCE_EXPECTEDLY_STATIC = "REFERENCE_EXPECTEDLY_STATIC"
    STALE_UNEXPECTED = "STALE_UNEXPECTED"
    REFERENCE_UNAVAILABLE = "REFERENCE_UNAVAILABLE"
    REFERENCE_STATE_UNKNOWN = "REFERENCE_STATE_UNKNOWN"


@dataclass(frozen=True)
class AssetRef:
    chain_id: int
    contract_address: str
    symbol: str | None = None
    decimals: int | None = None

    def __post_init__(self) -> None:
        if self.chain_id <= 0:
            raise ValueError("chain_id must be positive")
        address = self.contract_address.strip()
        if not address.startswith("0x") or len(address) != 42:
            raise ValueError("contract_address must be a 20-byte EVM address")
        object.__setattr__(self, "contract_address", address.lower())
        if self.decimals is not None and not 0 <= self.decimals <= 255:
            raise ValueError("decimals must be in [0, 255]")


@dataclass(frozen=True)
class SettlementReference:
    asset: AssetRef
    state: SettlementReferenceState
    usd_per_asset: Decimal | None
    source: str
    observed_at: datetime | None = None
    raw_evidence: Mapping[str, Any] = field(default_factory=dict)

    @property
    def usable(self) -> bool:
        return (
            self.state
            in {
                SettlementReferenceState.REFERENCE_CURRENT,
                SettlementReferenceState.REFERENCE_EXPECTEDLY_STATIC,
            }
            and self.usd_per_asset is not None
            and self.usd_per_asset > 0
        )


@dataclass(frozen=True)
class QuoteRequest:
    token: AssetRef
    settlement: SettlementReference
    side: QuoteSide
    requested_notional_usd: Decimal
    taker_address: str
    token_sizing_reference_usd: Decimal | None = None
    token_sizing_reference_source: str | None = None
    max_quote_age_seconds: int = 30

    def __post_init__(self) -> None:
        if self.requested_notional_usd <= 0:
            raise ValueError("requested_notional_usd must be positive")
        if self.token.chain_id != self.settlement.asset.chain_id:
            raise ValueError("R0 quote request must be same-chain")
        if self.side is QuoteSide.SELL:
            if self.token_sizing_reference_usd is None or self.token_sizing_reference_usd <= 0:
                raise ValueError("SELL requires a positive token sizing reference")
        taker = self.taker_address.strip()
        if not taker.startswith("0x") or len(taker) != 42:
            raise ValueError("taker_address must be a 20-byte EVM address")
        object.__setattr__(self, "taker_address", taker.lower())
        if self.max_quote_age_seconds <= 0:
            raise ValueError("max_quote_age_seconds must be positive")


@dataclass(frozen=True)
class RouteLeg:
    tool: str
    from_asset: str
    to_asset: str
    from_amount_raw: str | None = None
    to_amount_raw: str | None = None


@dataclass(frozen=True)
class QuoteEvidence:
    request_params: Mapping[str, Any]
    response_fields: Mapping[str, Any]
    route: Sequence[RouteLeg] = field(default_factory=tuple)
    transaction_to: str | None = None
    transaction_data: str | None = None
    source_request_id: str | None = None
    observed_block_number: int | None = None
    observed_block_hash: str | None = None
    block_binding: str = "SOURCE_UNBOUND"


@dataclass(frozen=True)
class ExecutionQuote:
    chain_id: int
    token_address: str
    side: QuoteSide
    input_asset: AssetRef
    output_asset: AssetRef
    requested_notional_usd: Decimal
    raw_amount_in: int | None
    raw_amount_out: int | None
    normalized_amount_in: Decimal | None
    normalized_amount_out: Decimal | None
    input_decimals: int | None
    output_decimals: int | None
    source: str
    quoted_at: datetime
    settlement_reference: SettlementReference
    status: QuoteStatus
    unavailable_reason: str | None = None
    fee_cost_usd: Decimal | None = None
    gas_cost_usd: Decimal | None = None
    evidence: QuoteEvidence | None = None

    @property
    def effective_output_per_input(self) -> Decimal | None:
        if (
            self.status is not QuoteStatus.QUOTE_OK
            or self.normalized_amount_in is None
            or self.normalized_amount_out is None
            or self.normalized_amount_in <= 0
        ):
            return None
        return self.normalized_amount_out / self.normalized_amount_in

    def with_status(self, status: QuoteStatus, reason: str) -> "ExecutionQuote":
        return replace(self, status=status, unavailable_reason=reason)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)
