"""Normalized cross-venue market observation contract + integrity digest.

One MarketObservation is the append-only unit of Tokenized Markets
evidence.  House conventions:
  - persisted economic values are decimal STRINGS (exact round-trip);
  - missing values are None — never 0;
  - ``ts`` is the SOURCE/provider evidence timestamp, ``collected_at`` is
    FINCO's collection clock; one never substitutes the other;
  - the digest is deterministic canonical JSON over the observation minus
    the digest itself (same evidence → same digest; different evidence →
    different digest).
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum


class FreshnessState(str, Enum):
    AVAILABLE = "AVAILABLE"
    STALE = "STALE"
    UNAVAILABLE = "UNAVAILABLE"


class ObservationStatus(str, Enum):
    OK = "OK"
    QUARANTINED = "QUARANTINED"


def _iso(value: datetime) -> str:
    if value.tzinfo is None:
        raise ValueError("observation timestamps must be timezone-aware")
    return value.astimezone(timezone.utc).isoformat()


@dataclass(frozen=True)
class MarketObservation:
    """One normalized market observation for one exact instrument."""

    ts: str                          # source/provider evidence timestamp (ISO-8601 UTC)
    collected_at: str                # FINCO collection timestamp (ISO-8601 UTC)
    canonical_asset_id: str          # exact canonical underlying symbol
    venue_id: str                    # platform/network key
    instrument_id: str               # exact symbol or 0x-contract identity
    instrument_type: str

    price: str | None = None
    reference_price: str | None = None
    basis_bps: str | None = None
    volume_24h: str | None = None
    open_interest: str | None = None
    funding_rate: str | None = None

    source: str = ""
    freshness_state: FreshnessState = FreshnessState.UNAVAILABLE
    observation_status: ObservationStatus = ObservationStatus.OK
    payload: dict = field(default_factory=dict)
    digest: str | None = None        # derived; excluded from digest input

    def __post_init__(self) -> None:
        for clock_name in ("ts", "collected_at"):
            raw = getattr(self, clock_name)
            datetime.fromisoformat(raw)  # raises on malformed stamps
        for numeric in ("price", "reference_price", "basis_bps",
                        "volume_24h", "open_interest", "funding_rate"):
            value = getattr(self, numeric)
            if value is None:
                continue
            if not isinstance(value, str):
                raise ValueError(
                    f"{numeric} must be a decimal string or None "
                    "(never float, never fabricated zero)")
            from decimal import Decimal, InvalidOperation
            try:
                parsed = Decimal(value)
            except InvalidOperation as exc:
                raise ValueError(
                    f"{numeric} is not a valid decimal string: {value!r}") from exc
            if not parsed.is_finite():
                raise ValueError(
                    f"{numeric} must be finite (NaN/Infinity are not evidence)")
        if not isinstance(self.freshness_state, FreshnessState):
            object.__setattr__(
                self, "freshness_state", FreshnessState(self.freshness_state))
        if not isinstance(self.observation_status, ObservationStatus):
            object.__setattr__(
                self, "observation_status",
                ObservationStatus(self.observation_status))

    @staticmethod
    def clocks(source_timestamp: datetime | None,
               collected_at: datetime) -> tuple[str | None, str]:
        """Canonical clock handling: the SOURCE timestamp is used only when
        the provider actually supplies one — it is never replaced by the
        collection clock while pretending to be evidence.  A provider
        without a source timestamp is represented explicitly (ts=None in
        payload; the persisted ts column then carries the collection instant
        ONLY as the ordering key, with freshness reflecting that
        limitation)."""
        collected = _iso(collected_at)
        if source_timestamp is None:
            return None, collected
        return _iso(source_timestamp), collected

    def digest_input(self) -> dict:
        data = asdict(self)
        data.pop("digest", None)
        return data

    def compute_digest(self) -> str:
        canonical = json.dumps(
            self.digest_input(), sort_keys=True, separators=(",", ":"),
            ensure_ascii=False)
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def resolved_digest(self) -> str:
        return self.digest or self.compute_digest()


def utc_now() -> datetime:
    return datetime.now(timezone.utc)
