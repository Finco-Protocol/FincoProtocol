from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from .schema import EvidenceConfidence, SourceReference


@dataclass(frozen=True)
class FreshnessPolicy:
    native_max_age_seconds: int = 1800
    third_party_max_age_seconds: int = 900
    direct_block_max_age_seconds: int = 180
    future_clock_skew_seconds: int = 120


@dataclass(frozen=True)
class FreshnessResult:
    state: str
    age_seconds: int | None
    reason: str


def evaluate_freshness(source: SourceReference, *, now: datetime | None = None, policy: FreshnessPolicy | None = None) -> FreshnessResult:
    policy = policy or FreshnessPolicy()
    now = now or datetime.now(timezone.utc)
    if source.observed_at.tzinfo is None or now.tzinfo is None:
        return FreshnessResult("INVALID", None, "timezone-aware timestamp required")
    age = int((now.astimezone(timezone.utc) - source.observed_at.astimezone(timezone.utc)).total_seconds())
    if age < -policy.future_clock_skew_seconds:
        return FreshnessResult("FUTURE_TIMESTAMP", age, "source timestamp is in the future")
    if source.source_type == EvidenceConfidence.DIRECT_ONCHAIN:
        if source.block_number is None:
            return FreshnessResult("INVALID", age, "direct authority requires explicit block identity")
        if age > policy.direct_block_max_age_seconds:
            return FreshnessResult("STALE", age, "direct observation exceeds freshness policy")
        return FreshnessResult("CURRENT", age, "explicit block-bound observation")
    max_age = policy.native_max_age_seconds if source.source_type == EvidenceConfidence.NATIVE_ENRICHED else policy.third_party_max_age_seconds
    if age > max_age:
        return FreshnessResult("STALE", age, "source observation exceeds freshness policy")
    return FreshnessResult("CURRENT", age, "source observation within freshness policy")
