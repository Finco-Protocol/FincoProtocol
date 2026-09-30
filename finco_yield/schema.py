from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
from typing import Any
from .identity import YieldIdentity, yield_opportunity_uid

class EvidenceConfidence(str, Enum):
    DIRECT_ONCHAIN = "DIRECT_ONCHAIN"
    NATIVE_ENRICHED = "NATIVE_ENRICHED"
    THIRD_PARTY_REFERENCE = "THIRD_PARTY_REFERENCE"
    PARTIAL = "PARTIAL"
    STALE = "STALE"
    UNKNOWN = "UNKNOWN"

class ComponentState(str, Enum):
    AVAILABLE = "AVAILABLE"
    COMPONENTS_UNAVAILABLE = "COMPONENTS_UNAVAILABLE"
    COMPONENT_MISMATCH = "COMPONENT_MISMATCH"

class ScenarioState(str, Enum):
    MODELLED = "MODELLED"
    NOT_MODELLED = "NOT_MODELLED"

@dataclass(frozen=True)
class SourceReference:
    source_type: EvidenceConfidence
    uri: str
    observed_at: datetime
    block_number: int | None = None
    adapter: str = ""
    adapter_version: str = "y0.1"

@dataclass(frozen=True)
class YieldObservation:
    tvl_usd: Decimal | None
    apy_total: Decimal | None
    apy_base: Decimal | None = None
    apy_rewards: Decimal | None = None
    apy_intrinsic: Decimal | None = None
    annualized_costs: Decimal | None = None
    withdrawal_type: str | None = None
    capacity_usd: Decimal | None = None
    slippage_bps: Decimal | None = None
    fee_bps: Decimal | None = None
    queue_seconds: int | None = None
    quote_size_usd: Decimal | None = None

@dataclass(frozen=True)
class YieldOpportunity:
    identity: YieldIdentity
    name: str
    underlying_symbol: str
    observation: YieldObservation
    source: SourceReference
    official_url: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def uid(self) -> str:
        return yield_opportunity_uid(self.identity)

    def freshness_state(self, now: datetime | None = None, max_age_seconds: int = 1800) -> EvidenceConfidence:
        now = now or datetime.now(timezone.utc)
        age = (now - self.source.observed_at.astimezone(timezone.utc)).total_seconds()
        return EvidenceConfidence.STALE if age > max_age_seconds else self.source.source_type
