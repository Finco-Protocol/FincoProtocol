"""Distinct underlying, token reference, and execution observations."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import Enum

from finco_radar.assets.contracts import AssetKey, normalize_asset_uid
from finco_radar.quotes.contracts import QuoteSide


class AuthorityState(str, Enum):
    AVAILABLE = "AVAILABLE"
    STALE = "STALE"
    UNAVAILABLE = "UNAVAILABLE"
    IDENTITY_UNAVAILABLE = "IDENTITY_UNAVAILABLE"


@dataclass(frozen=True)
class AuthorityPolicy:
    max_registry_age_seconds: int
    max_reference_age_seconds: int
    max_execution_age_seconds: int
    max_evidence_skew_seconds: int
    approved_token_reference_sources: frozenset[str]

    def __post_init__(self) -> None:
        if min(self.max_registry_age_seconds, self.max_reference_age_seconds, self.max_execution_age_seconds,
               self.max_evidence_skew_seconds) <= 0:
            raise ValueError("authority age and skew limits must be positive")
        if any(not source.strip() for source in self.approved_token_reference_sources):
            raise ValueError("approved token reference sources must be named")


@dataclass(frozen=True)
class IndependentTokenReference:
    """Source-attested token price; never derived from an execution quote."""

    registry_asset_uid: str
    asset_key: AssetKey
    price_usd_per_token: Decimal
    source: str
    observed_at: datetime

    def __post_init__(self) -> None:
        object.__setattr__(self, "registry_asset_uid", normalize_asset_uid(self.registry_asset_uid))
        if not self.source.strip() or not self.price_usd_per_token.is_finite() or self.price_usd_per_token <= 0:
            raise ValueError("token reference needs a source and positive finite price")
        if self.observed_at.tzinfo is None or self.observed_at.utcoffset() is None:
            raise ValueError("token reference timestamp must be timezone-aware")


@dataclass(frozen=True)
class ReferenceLayer:
    state: AuthorityState
    registry_asset_uid: str | None
    asset_key: AssetKey | None
    label: str | None
    price_usd_per_token: Decimal | None
    source: str | None
    observed_at: datetime | None
    reason: str | None = None


@dataclass(frozen=True)
class ExecutionLayer:
    state: AuthorityState
    asset_key: AssetKey | None
    side: QuoteSide | None
    requested_notional_usd: Decimal | None
    effective_price_usd_per_token: Decimal | None
    provider: str | None
    route: tuple[tuple[str, str, str], ...] | None
    fee_cost_usd: Decimal | None
    gas_cost_usd: Decimal | None
    observed_at: datetime | None
    reason: str | None = None


@dataclass(frozen=True)
class BasisPointQuantity:
    state: AuthorityState
    value_bps: Decimal | None
    numerator_usd_per_token: Decimal | None
    denominator_usd_per_token: Decimal | None
    formula: str
    sources: tuple[str, ...]
    observed_at: tuple[datetime, ...]
    reason: str | None = None


@dataclass(frozen=True)
class ExecutionGap:
    state: AuthorityState
    reference_premium_bps: Decimal | None
    execution_impact_bps: Decimal | None
    effective_gap_bps: Decimal | None
    fee_treatment: str
    reason: str | None = None


@dataclass(frozen=True)
class AuthoritySnapshot:
    economic_asset_uid: str | None
    canonical_token: AssetKey
    registry_source: str | None
    registry_observed_at: datetime | None
    underlying: ReferenceLayer
    token: ReferenceLayer
    premium: BasisPointQuantity
    execution: ExecutionLayer
    execution_gap: ExecutionGap
