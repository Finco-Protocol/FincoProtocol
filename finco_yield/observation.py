"""Canonical source-observation contract for FINCO Yield live ingestion.

One accepted observation answers: which provider and source-native record
produced it, which chain/protocol/contract it represents, when it was observed
and fetched, which values are source-native and which FINCO derived.

Economic identity is ONLY chain + protocol + product type + contract address +
underlying asset address + share token (the existing ``identity.YieldIdentity``
scheme).  Symbols, names and display strings never establish identity.

Optional metrics (APY components, TVL) are ``None`` when the source does not
prove them.  ``None`` is UNAVAILABLE, never zero.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

from .evidence_v1 import canonical_json
from .history import ImmutableObservationRecord
from .identity import YieldIdentity, canonical_address, yield_opportunity_uid
from .schema import EvidenceConfidence

SOURCE_OBSERVATION_SCHEMA = "YIELD_SOURCE_OBSERVATION_V1"

# observed_at provenance policy.  FETCHED_AT is used when the provider response
# carries no trustworthy source-side timestamp; the policy is recorded on every
# observation so it can never be mistaken for a source timestamp.
OBSERVED_AT_SOURCE_TIMESTAMP = "SOURCE_TIMESTAMP"
OBSERVED_AT_FETCHED_AT = "FETCHED_AT"
_OBSERVED_AT_POLICIES = frozenset({OBSERVED_AT_SOURCE_TIMESTAMP, OBSERVED_AT_FETCHED_AT})

DATA_ORIGIN_SOURCE_OBSERVED = "SOURCE_OBSERVED"
DATA_ORIGIN_REFERENCE_FIXTURE = "REFERENCE_FIXTURE"

# Plausibility bounds.  APY is a fraction (0.04 == 4%).
_APY_MIN = Decimal("-1")
_APY_MAX = Decimal("100")
_FUTURE_SKEW = timedelta(seconds=120)


class ObservationRejected(ValueError):
    """An observation failed contract validation.  ``code`` is a typed reason."""

    def __init__(self, code: str, message: str = ""):
        super().__init__(message or code)
        self.code = code


@dataclass(frozen=True)
class SourceObservation:
    provider: str
    source_record_id: str
    chain_id: int
    protocol: str
    product_type: str
    contract_address: str
    underlying_address: str
    share_token: str
    underlying_symbol: str
    name: str
    fetched_at: datetime
    observed_at: datetime
    observed_at_policy: str
    source_uri: str
    adapter: str
    adapter_version: str
    source_type: EvidenceConfidence
    tvl_usd: Decimal | None = None
    apy_total: Decimal | None = None
    apy_base: Decimal | None = None
    apy_rewards: Decimal | None = None
    # Provider-native 30d averages, when the source contract exposes them
    # (Morpho: avgNetApy / avgNetApyExcludingRewards, lookback THIRTY_DAYS).
    # Provenance is carried in ``apy_30d_avg_source`` -- never silently mixed
    # with FINCO-computed statistics.
    apy_total_30d_avg: Decimal | None = None
    apy_base_30d_avg: Decimal | None = None
    apy_30d_avg_source: str | None = None
    # Values exactly as the source supplied them (JSON primitives).
    source_native: dict[str, Any] = field(default_factory=dict)
    # How each FINCO field was derived from source-native values.
    derived: dict[str, str] = field(default_factory=dict)
    schema_version: str = SOURCE_OBSERVATION_SCHEMA

    @property
    def identity(self) -> YieldIdentity:
        return YieldIdentity(
            chain_id=self.chain_id,
            protocol=self.protocol,
            product_type=self.product_type,
            contract_address=self.contract_address,
            underlying_assets=(self.underlying_address,),
            share_token=self.share_token,
        )

    @property
    def uid(self) -> str:
        return yield_opportunity_uid(self.identity)

    def validate(self) -> "SourceObservation":
        """Raise ``ObservationRejected`` unless the contract is satisfied."""
        if not self.provider or not self.source_record_id:
            raise ObservationRejected("OBSERVATION_PROVENANCE_MISSING")
        if self.observed_at_policy not in _OBSERVED_AT_POLICIES:
            raise ObservationRejected("OBSERVATION_POLICY_INVALID")
        for stamp in (self.fetched_at, self.observed_at):
            if not isinstance(stamp, datetime) or stamp.tzinfo is None:
                raise ObservationRejected("OBSERVATION_TIMESTAMP_INVALID")
        if self.observed_at.astimezone(timezone.utc) > self.fetched_at.astimezone(timezone.utc) + _FUTURE_SKEW:
            raise ObservationRejected("OBSERVATION_FROM_FUTURE")
        try:
            # Exact identity or rejection; also normalises addresses.
            self.identity.canonical()
            canonical_address(self.contract_address)
        except ValueError as exc:
            raise ObservationRejected("OBSERVATION_IDENTITY_INVALID") from exc
        for label, value in (("tvl_usd", self.tvl_usd), ("apy_total", self.apy_total),
                             ("apy_base", self.apy_base), ("apy_rewards", self.apy_rewards)):
            if value is None:
                continue
            if not isinstance(value, Decimal) or not value.is_finite():
                raise ObservationRejected("OBSERVATION_VALUE_INVALID", label)
            if label == "tvl_usd" and value < 0:
                raise ObservationRejected("OBSERVATION_VALUE_INVALID", label)
            if label != "tvl_usd" and not (_APY_MIN <= value <= _APY_MAX):
                raise ObservationRejected("OBSERVATION_VALUE_INVALID", label)
        if self.apy_total is None and self.tvl_usd is None:
            # No proven economic value at all: nothing to record.
            raise ObservationRejected("OBSERVATION_EMPTY")
        return self

    # ------------------------------------------------------------------ views
    def payload(self) -> dict[str, Any]:
        """History payload.  Keys ``apy_total``/``tvl_usd``/``apy_rewards`` are
        the canonical fields consumed by Yield Alerts."""

        def _s(value: Decimal | None) -> str | None:
            return None if value is None else format(value.normalize(), "f") if value != 0 else "0"

        return {
            "schema": self.schema_version,
            "provider": self.provider,
            "source_record_id": self.source_record_id,
            "chain_id": self.chain_id,
            "apy_total": _s(self.apy_total),
            "apy_base": _s(self.apy_base),
            "apy_rewards": _s(self.apy_rewards),
            "apy_total_30d_avg": _s(self.apy_total_30d_avg),
            "apy_base_30d_avg": _s(self.apy_base_30d_avg),
            "apy_30d_avg_source": self.apy_30d_avg_source,
            "tvl_usd": _s(self.tvl_usd),
            "fetched_at": self.fetched_at.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
            "observed_at_policy": self.observed_at_policy,
            "source_native": dict(self.source_native),
            "derived": dict(self.derived),
        }

    def content_key(self) -> str:
        """Canonical identity of the observation's CONTENT (excludes fetch time)."""
        payload = self.payload()
        payload.pop("fetched_at", None)
        return canonical_json({"uid": self.uid, "payload": payload})

    def to_history_record(self) -> ImmutableObservationRecord:
        return ImmutableObservationRecord(
            opportunity_uid=self.uid,
            observed_at=self.observed_at,
            source_authority=self.source_type.value,
            source_uri=self.source_uri,
            adapter_version=self.adapter_version,
            payload=self.payload(),
        )
