"""Typed contracts for FINCO Radar R7 cross-market intelligence.

R7 answers: for the same economic asset, how do the underlying market,
FX normalization, oracle/reference, tokenized representation, venue/DEX
observation and settlement context relate to each other — and at which layer
does an observed price dislocation originate?

R7 exposes THEORETICAL/OBSERVED dislocation and its attribution only.
It never claims executable profit (R8 boundary), never redefines R2 GAP or
R5 signal semantics, and never manufactures R4 reference authority.
"""
from __future__ import annotations

import hashlib
import json
import re
from types import MappingProxyType
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Any, Mapping

from finco_radar.assets.contracts import AssetKey
from finco_radar.quotes.contracts import QuoteSide

SCHEMA_VERSION = "radar-r7-cross-market-v1"
PHASE = "R7"

_ECONOMIC_UID_RE = re.compile(r"^[A-Z0-9][A-Z0-9._-]{0,31}$")


def deep_freeze(value: Any) -> Any:
    """Recursively convert mutable evidence into owned immutable structures.

    dict/Mapping -> MappingProxyType over a PRIVATE deep-frozen copy (caller
    mutations can never leak through), list/tuple -> tuple of frozen members,
    set/frozenset -> deterministically ordered tuple. Scalars pass through.
    """
    if isinstance(value, Mapping):
        return MappingProxyType(
            {key: deep_freeze(item) for key, item in value.items()}
        )
    if isinstance(value, (list, tuple)):
        return tuple(deep_freeze(item) for item in value)
    if isinstance(value, (set, frozenset)):
        return tuple(sorted((repr(deep_freeze(item)) for item in value)))
    return value


class CrossMarketStatus(str, Enum):
    """Typed fail-closed status family for R7 computation attempts."""

    CROSS_MARKET_OK = "CROSS_MARKET_OK"
    CROSS_MARKET_IDENTITY_UNRESOLVED = "CROSS_MARKET_IDENTITY_UNRESOLVED"
    CROSS_MARKET_INPUT_INVALID = "CROSS_MARKET_INPUT_INVALID"
    CROSS_MARKET_EVIDENCE_MISMATCH = "CROSS_MARKET_EVIDENCE_MISMATCH"
    CROSS_MARKET_TIME_MISMATCH = "CROSS_MARKET_TIME_MISMATCH"


class CrossMarketError(ValueError):
    """Raised when a cross-market stack cannot be built without guessing."""

    def __init__(
        self,
        message: str,
        status: CrossMarketStatus = CrossMarketStatus.CROSS_MARKET_INPUT_INVALID,
    ) -> None:
        super().__init__(message)
        self.status = status


class LayerType(str, Enum):
    """Typed observation layers of the cross-market price path."""

    UNDERLYING = "UNDERLYING"
    FX = "FX"
    ORACLE_REFERENCE = "ORACLE_REFERENCE"
    TOKEN = "TOKEN"
    VENUE = "VENUE"
    SETTLEMENT = "SETTLEMENT"


class LayerObservationStatus(str, Enum):
    """Availability of one layer. Missing authority stays explicitly missing."""

    AVAILABLE = "AVAILABLE"
    SOURCE_UNAVAILABLE = "SOURCE_UNAVAILABLE"
    SUPPRESSED_BY_AUTHORITY = "SUPPRESSED_BY_AUTHORITY"


class TimingState(str, Enum):
    ALIGNED = "ALIGNED"
    SKEWED = "SKEWED"
    STALE_LAYER = "STALE_LAYER"
    TIMING_UNRESOLVED = "TIMING_UNRESOLVED"


class AttributionState(str, Enum):
    """Deterministic dislocation attribution. Never an LLM, never a score."""

    NO_MATERIAL_DISLOCATION = "NO_MATERIAL_DISLOCATION"
    UNDERLYING_REFERENCE_DISLOCATION = "UNDERLYING_REFERENCE_DISLOCATION"
    FX_NORMALIZATION_DISLOCATION = "FX_NORMALIZATION_DISLOCATION"
    REFERENCE_TOKEN_DISLOCATION = "REFERENCE_TOKEN_DISLOCATION"
    TOKEN_VENUE_DISLOCATION = "TOKEN_VENUE_DISLOCATION"
    CROSS_VENUE_DISLOCATION = "CROSS_VENUE_DISLOCATION"
    CROSS_DEPLOYMENT_DISLOCATION = "CROSS_DEPLOYMENT_DISLOCATION"
    MULTI_LAYER_DISLOCATION = "MULTI_LAYER_DISLOCATION"
    ATTRIBUTION_UNAVAILABLE = "ATTRIBUTION_UNAVAILABLE"


class ComparabilityState(str, Enum):
    COMPARABLE = "COMPARABLE"
    PARTIALLY_COMPARABLE = "PARTIALLY_COMPARABLE"
    SUPPRESSED = "SUPPRESSED"
    UNAVAILABLE = "UNAVAILABLE"


class ComparabilityReason(str, Enum):
    IDENTITY_UNRESOLVED = "IDENTITY_UNRESOLVED"
    FX_UNAVAILABLE = "FX_UNAVAILABLE"
    REFERENCE_UNAVAILABLE = "REFERENCE_UNAVAILABLE"
    TIMING_SKEW = "TIMING_SKEW"
    STALE_LAYER = "STALE_LAYER"
    SETTLEMENT_CONTEXT_UNRESOLVED = "SETTLEMENT_CONTEXT_UNRESOLVED"
    MULTIPLIER_UNRESOLVED = "MULTIPLIER_UNRESOLVED"
    UPSTREAM_EVIDENCE_MISMATCH = "UPSTREAM_EVIDENCE_MISMATCH"
    INSUFFICIENT_MEMBERS = "INSUFFICIENT_MEMBERS"
    UNDERLYING_SOURCE_UNAVAILABLE = "UNDERLYING_SOURCE_UNAVAILABLE"


class EventKind(str, Enum):
    """Deterministic descriptive events. Never future movement, never advice."""

    DISLOCATION_APPEARED = "DISLOCATION_APPEARED"
    DISLOCATION_WIDENED = "DISLOCATION_WIDENED"
    DISLOCATION_NARROWED = "DISLOCATION_NARROWED"
    DISLOCATION_CLEARED = "DISLOCATION_CLEARED"
    ATTRIBUTION_CHANGED = "ATTRIBUTION_CHANGED"
    REFERENCE_DIVERGENCE = "REFERENCE_DIVERGENCE"
    VENUE_DIVERGENCE = "VENUE_DIVERGENCE"
    TIMING_ALIGNMENT_LOST = "TIMING_ALIGNMENT_LOST"
    TIMING_ALIGNMENT_RESTORED = "TIMING_ALIGNMENT_RESTORED"


def _require_aware(value: datetime, name: str) -> None:
    if value.tzinfo is None:
        raise CrossMarketError(
            f"{name} must be timezone-aware",
            CrossMarketStatus.CROSS_MARKET_TIME_MISMATCH,
        )


@dataclass(frozen=True)
class EconomicIdentityBinding:
    """Explicit binding of one economic asset to canonical token deployments.

    Economic identity is separate from token contract identity and is never
    inferred from ticker text alone: the binding is declared by a named source
    and fails closed on ambiguity or duplication.
    """

    economic_asset_uid: str
    canonical_keys: tuple[AssetKey, ...]
    source: str
    reference_identifiers: tuple[str, ...] = ()
    raw_evidence: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "raw_evidence", deep_freeze(self.raw_evidence))
        uid = self.economic_asset_uid.strip().upper()
        if not _ECONOMIC_UID_RE.fullmatch(uid):
            raise CrossMarketError(
                "economic_asset_uid must be 1-32 chars matching [A-Z0-9._-]",
                CrossMarketStatus.CROSS_MARKET_IDENTITY_UNRESOLVED,
            )
        if not self.canonical_keys:
            raise CrossMarketError(
                "economic identity binding must carry at least one canonical key",
                CrossMarketStatus.CROSS_MARKET_IDENTITY_UNRESOLVED,
            )
        if len(set(self.canonical_keys)) != len(self.canonical_keys):
            raise CrossMarketError(
                "economic identity binding contains duplicate canonical keys",
                CrossMarketStatus.CROSS_MARKET_IDENTITY_UNRESOLVED,
            )
        if not self.source.strip():
            raise CrossMarketError(
                "economic identity binding requires a non-empty declared source",
                CrossMarketStatus.CROSS_MARKET_IDENTITY_UNRESOLVED,
            )
        object.__setattr__(self, "economic_asset_uid", uid)


@dataclass(frozen=True)
class LayerObservation:
    """One priced observation layer, or an explicitly missing one.

    An unavailable layer carries price=None and a named source status; it is
    never filled with assumptions and never presented as current.
    """

    layer: LayerType
    status: LayerObservationStatus
    source: str
    price: Decimal | None = None
    currency: str | None = None
    observed_at: datetime | None = None
    instrument: str | None = None
    multiplier: Decimal | None = None
    usable: bool | None = None
    asset_uid: str | None = None
    asset_key: AssetKey | None = None
    raw_evidence: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "raw_evidence", deep_freeze(self.raw_evidence))
        if not self.source.strip():
            raise CrossMarketError(
                f"{self.layer.value} layer requires a non-empty source",
                CrossMarketStatus.CROSS_MARKET_INPUT_INVALID,
            )
        if self.status is LayerObservationStatus.AVAILABLE:
            if self.price is None or not self.price.is_finite() or self.price <= 0:
                raise CrossMarketError(
                    f"{self.layer.value} AVAILABLE observation requires a positive "
                    "finite price",
                    CrossMarketStatus.CROSS_MARKET_INPUT_INVALID,
                )
            if not self.currency or not self.currency.strip():
                raise CrossMarketError(
                    f"{self.layer.value} AVAILABLE observation requires a quote currency",
                    CrossMarketStatus.CROSS_MARKET_INPUT_INVALID,
                )
            if self.observed_at is None:
                raise CrossMarketError(
                    f"{self.layer.value} AVAILABLE observation requires observed_at",
                    CrossMarketStatus.CROSS_MARKET_TIME_MISMATCH,
                )
            _require_aware(self.observed_at, f"{self.layer.value} observed_at")
        else:
            if self.price is not None:
                raise CrossMarketError(
                    f"{self.layer.value} unavailable observation must not carry a price",
                    CrossMarketStatus.CROSS_MARKET_INPUT_INVALID,
                )


@dataclass(frozen=True)
class VenueObservation:
    """One venue/DEX execution observation bound to a canonical deployment."""

    venue: str
    side: QuoteSide
    notional_usd: Decimal
    price: Decimal
    currency: str
    observed_at: datetime
    source: str
    asset_key: AssetKey
    gap_bps: Decimal | None = None
    route_signature: str | None = None
    raw_evidence: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "raw_evidence", deep_freeze(self.raw_evidence))
        if not self.venue.strip() or not self.source.strip():
            raise CrossMarketError(
                "venue observation requires non-empty venue and source",
                CrossMarketStatus.CROSS_MARKET_INPUT_INVALID,
            )
        if not self.price.is_finite() or self.price <= 0:
            raise CrossMarketError(
                "venue observation price must be positive and finite",
                CrossMarketStatus.CROSS_MARKET_INPUT_INVALID,
            )
        if not self.notional_usd.is_finite() or self.notional_usd <= 0:
            raise CrossMarketError(
                "venue observation notional must be positive and finite",
                CrossMarketStatus.CROSS_MARKET_INPUT_INVALID,
            )
        _require_aware(self.observed_at, "venue observed_at")

    @property
    def member_key(self) -> tuple[str, str, str]:
        return (self.venue, self.side.value, str(self.notional_usd))


@dataclass(frozen=True)
class FxObservation:
    """Typed FX normalization authority. Stablecoin parity is never assumed."""

    source_currency: str
    target_currency: str
    rate: Decimal
    source: str
    observed_at: datetime
    raw_evidence: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "raw_evidence", deep_freeze(self.raw_evidence))
        if not self.source_currency.strip() or not self.target_currency.strip():
            raise CrossMarketError(
                "FX observation requires both currencies",
                CrossMarketStatus.CROSS_MARKET_INPUT_INVALID,
            )
        if not self.rate.is_finite() or self.rate <= 0:
            raise CrossMarketError(
                "FX rate must be positive and finite",
                CrossMarketStatus.CROSS_MARKET_INPUT_INVALID,
            )
        if not self.source.strip():
            raise CrossMarketError(
                "FX observation requires a non-empty source",
                CrossMarketStatus.CROSS_MARKET_INPUT_INVALID,
            )
        _require_aware(self.observed_at, "FX observed_at")

    @property
    def pair(self) -> tuple[str, str]:
        return (self.source_currency.strip().upper(), self.target_currency.strip().upper())


@dataclass(frozen=True)
class TokenRepresentation:
    """Tokenized representation of one economic asset; multiplier is metadata.

    observed_price (optional) is a token-layer price observation from a source
    distinct from DEX venue execution; when absent, the TOKEN layer has no
    independent price and the price path connects ORACLE_REFERENCE directly to
    VENUE observations.
    """

    economic_asset_uid: str
    asset_key: AssetKey
    symbol: str
    multiplier: Decimal
    representation_status: str
    reference_usable: bool
    observed_price: Decimal | None = None
    currency: str | None = None
    observed_at: datetime | None = None
    raw_evidence: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "raw_evidence", deep_freeze(self.raw_evidence))
        if not self.multiplier.is_finite() or self.multiplier <= 0:
            raise CrossMarketError(
                "token representation multiplier must be positive and finite",
                CrossMarketStatus.CROSS_MARKET_INPUT_INVALID,
            )
        price_fields = (self.observed_price, self.currency, self.observed_at)
        if any(p is not None for p in price_fields) and not all(p is not None for p in price_fields):
            raise CrossMarketError(
                "token observed price requires price, currency and observed_at together",
                CrossMarketStatus.CROSS_MARKET_INPUT_INVALID,
            )
        if self.observed_price is not None:
            if not self.observed_price.is_finite() or self.observed_price <= 0:
                raise CrossMarketError(
                    "token observed price must be positive and finite",
                    CrossMarketStatus.CROSS_MARKET_INPUT_INVALID,
                )
            _require_aware(self.observed_at, "token observed_at")


@dataclass(frozen=True)
class SettlementContext:
    """Settlement CONTEXT only — never R8 economics (no fees/gas/PnL)."""

    settlement_asset_symbol: str
    chain_id: int | None
    contract_address: str | None
    settlement_currency: str | None
    transfer_required: bool | None
    authority_status: str
    resolved: bool
    raw_evidence: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "raw_evidence", deep_freeze(self.raw_evidence))
        if not self.authority_status.strip():
            raise CrossMarketError(
                "settlement context requires an authority status",
                CrossMarketStatus.CROSS_MARKET_INPUT_INVALID,
            )


@dataclass(frozen=True)
class CrossMarketPolicy:
    """Mandatory caller-supplied cross-market policy. No engine defaults."""

    comparison_currency: str
    material_dislocation_bps: Decimal
    max_layer_skew_seconds: Decimal
    stale_layer_seconds: Decimal

    def __post_init__(self) -> None:
        if not self.comparison_currency.strip():
            raise CrossMarketError(
                "comparison_currency must be non-empty",
                CrossMarketStatus.CROSS_MARKET_INPUT_INVALID,
            )
        for name in ("material_dislocation_bps", "max_layer_skew_seconds", "stale_layer_seconds"):
            value = getattr(self, name)
            if not isinstance(value, Decimal) or not value.is_finite() or value <= 0:
                raise CrossMarketError(
                    f"{name} must be a positive finite Decimal",
                    CrossMarketStatus.CROSS_MARKET_INPUT_INVALID,
                )


@dataclass(frozen=True)
class DislocationComponent:
    """One deterministic between-layer difference. Attribution evidence only."""

    from_layer: LayerType
    to_layer: LayerType
    label: str
    from_price: Decimal
    to_price: Decimal
    delta: Decimal
    delta_bps: Decimal
    threshold_bps: Decimal
    material: bool
    timing_valid: bool
    fx_source_currency: str | None
    fx_target_currency: str | None
    fx_rate: Decimal | None
    from_observed_at: datetime
    to_observed_at: datetime
    timing_skew_seconds: Decimal
    from_source: str
    to_source: str
    timing_dependencies: tuple[tuple[str, datetime], ...] = ()
    timing_oldest: datetime | None = None
    timing_newest: datetime | None = None

    def to_evidence_dict(self) -> dict[str, Any]:
        return {
            "fromLayer": self.from_layer.value,
            "toLayer": self.to_layer.value,
            "label": self.label,
            "fromPrice": str(self.from_price),
            "toPrice": str(self.to_price),
            "delta": str(self.delta),
            "deltaBps": str(self.delta_bps),
            "thresholdBps": str(self.threshold_bps),
            "material": self.material,
            "timingValid": self.timing_valid,
            "fx": {
                "sourceCurrency": self.fx_source_currency,
                "targetCurrency": self.fx_target_currency,
                "rate": str(self.fx_rate) if self.fx_rate is not None else None,
            },
            "fromObservedAt": self.from_observed_at.isoformat(),
            "toObservedAt": self.to_observed_at.isoformat(),
            "timingAuthority": {
                "timingDependencyObservations": [
                    {"observation": label, "observedAt": stamp.isoformat()}
                    for label, stamp in self.timing_dependencies
                ],
                "timingOldest": (
                    self.timing_oldest.isoformat()
                    if self.timing_oldest is not None
                    else None
                ),
                "timingNewest": (
                    self.timing_newest.isoformat()
                    if self.timing_newest is not None
                    else None
                ),
                "timingSkewSeconds": str(self.timing_skew_seconds),
            },
            "fromSource": self.from_source,
            "toSource": self.to_source,
        }


@dataclass(frozen=True)
class StackTiming:
    """Deterministic timing diagnostics over all available layer timestamps."""

    state: TimingState
    oldest: datetime | None
    newest: datetime | None
    total_skew_seconds: Decimal | None
    policy_max_layer_skew_seconds: Decimal
    policy_stale_layer_seconds: Decimal
    stale_layers: tuple[str, ...]

    def to_evidence_dict(self) -> dict[str, Any]:
        return {
            "state": self.state.value,
            "oldest": self.oldest.isoformat() if self.oldest is not None else None,
            "newest": self.newest.isoformat() if self.newest is not None else None,
            "totalSkewSeconds": (
                str(self.total_skew_seconds) if self.total_skew_seconds is not None else None
            ),
            "policy": {
                "maxLayerSkewSeconds": str(self.policy_max_layer_skew_seconds),
                "staleLayerSeconds": str(self.policy_stale_layer_seconds),
            },
            "staleLayers": list(self.stale_layers),
        }


@dataclass(frozen=True)
class CrossMarketEvent:
    kind: EventKind
    label: str
    detail: str

    def to_evidence_dict(self) -> dict[str, str]:
        return {"kind": self.kind.value, "label": self.label, "detail": self.detail}


@dataclass(frozen=True)
class CrossMarketSnapshot:
    """Successful R7 output: deterministic cross-market evidence for one
    economic asset. Immutable; serialized evidence is canonical and digested.
    """

    status: CrossMarketStatus
    economic_asset_uid: str
    binding: EconomicIdentityBinding
    underlying: LayerObservation | None
    fx: FxObservation | None
    oracle_reference: LayerObservation | None
    external_oracle: LayerObservation | None
    token: TokenRepresentation | None
    venues: tuple[VenueObservation, ...]
    settlement: SettlementContext | None
    timing: StackTiming
    comparability_state: ComparabilityState
    comparability_reasons: tuple[ComparabilityReason, ...]
    price_path: tuple[DislocationComponent, ...]
    dislocation_components: tuple[DislocationComponent, ...]
    attribution_state: AttributionState
    events: tuple[CrossMarketEvent, ...]
    upstream_evidence: Mapping[str, Any]
    source_digests: Mapping[str, str] = field(default_factory=dict)
    live_disclosures: Mapping[str, Any] = field(default_factory=dict)
    synthetic: bool = False
    generated_at: datetime | None = None
    git_head: str = "UNKNOWN"
    comparison_currency: str = "USD"
    r7_snapshot_digest: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "upstream_evidence", deep_freeze(self.upstream_evidence))
        object.__setattr__(self, "source_digests", deep_freeze(self.source_digests))
        object.__setattr__(self, "live_disclosures", deep_freeze(self.live_disclosures))
        if self.status is not CrossMarketStatus.CROSS_MARKET_OK:
            raise CrossMarketError(
                "successful snapshot requires CROSS_MARKET_OK",
                CrossMarketStatus.CROSS_MARKET_INPUT_INVALID,
            )
        if self.economic_asset_uid != self.binding.economic_asset_uid:
            raise CrossMarketError(
                "snapshot economic asset UID does not match the identity binding",
                CrossMarketStatus.CROSS_MARKET_EVIDENCE_MISMATCH,
            )
        _require_aware(self.generated_at, "generated_at")
        ordered = tuple(sorted(self.venues, key=lambda v: (v.venue, v.side.value, str(v.notional_usd), str(v.price))))
        if ordered != self.venues:
            raise CrossMarketError(
                "venue members must be supplied in deterministic canonical order",
                CrossMarketStatus.CROSS_MARKET_INPUT_INVALID,
            )

    def to_evidence_dict(self) -> dict[str, Any]:
        """Canonical, deterministic serialization (fresh output every call)."""
        return {
            "schemaVersion": SCHEMA_VERSION,
            "phase": PHASE,
            "status": self.status.value,
            "gitHead": self.git_head,
            "generatedAt": self.generated_at.isoformat(),
            "economicAssetUid": self.economic_asset_uid,
            "identityBinding": {
                "economicAssetUid": self.binding.economic_asset_uid,
                "canonicalKeys": [
                    {"chainId": k.chain_id, "contractAddress": k.contract_address}
                    for k in self.binding.canonical_keys
                ],
                "referenceIdentifiers": list(self.binding.reference_identifiers),
                "source": self.binding.source,
            },
            "layers": {
                "underlying": _layer_dict(self.underlying),
                "fx": {
                    "present": self.fx is not None,
                    "sourceCurrency": self.fx.source_currency if self.fx else None,
                    "targetCurrency": self.fx.target_currency if self.fx else None,
                    "rate": str(self.fx.rate) if self.fx else None,
                    "source": self.fx.source if self.fx else None,
                    "observedAt": self.fx.observed_at.isoformat() if self.fx else None,
                },
                "oracleReference": _layer_dict(self.oracle_reference),
                "externalOracle": _layer_dict(self.external_oracle),
                "token": (
                    {
                        "economicAssetUid": self.token.economic_asset_uid,
                        "chainId": self.token.asset_key.chain_id,
                        "contractAddress": self.token.asset_key.contract_address,
                        "symbol": self.token.symbol,
                        "multiplier": str(self.token.multiplier),
                        "representationStatus": self.token.representation_status,
                        "referenceUsable": self.token.reference_usable,
                        "observedPrice": (
                            str(self.token.observed_price)
                            if self.token.observed_price is not None
                            else None
                        ),
                        "currency": self.token.currency,
                        "observedAt": (
                            self.token.observed_at.isoformat()
                            if self.token.observed_at is not None
                            else None
                        ),
                    }
                    if self.token is not None
                    else None
                ),
                "venues": [
                    {
                        "venue": v.venue,
                        "side": v.side.value,
                        "notionalUsd": str(v.notional_usd),
                        "price": str(v.price),
                        "currency": v.currency,
                        "observedAt": v.observed_at.isoformat(),
                        "source": v.source,
                        "chainId": v.asset_key.chain_id,
                        "contractAddress": v.asset_key.contract_address,
                        "gapBps": str(v.gap_bps) if v.gap_bps is not None else None,
                        "routeSignature": v.route_signature,
                        "rawEvidence": _deep_copy_mapping(v.raw_evidence),
                    }
                    for v in self.venues
                ],
                "settlement": (
                    {
                        "settlementAssetSymbol": self.settlement.settlement_asset_symbol,
                        "chainId": self.settlement.chain_id,
                        "contractAddress": self.settlement.contract_address,
                        "settlementCurrency": self.settlement.settlement_currency,
                        "transferRequired": self.settlement.transfer_required,
                        "authorityStatus": self.settlement.authority_status,
                        "resolved": self.settlement.resolved,
                    }
                    if self.settlement is not None
                    else None
                ),
            },
            "timing": self.timing.to_evidence_dict(),
            "comparabilityState": self.comparability_state.value,
            "comparabilityReasons": [r.value for r in self.comparability_reasons],
            "pricePath": [c.to_evidence_dict() for c in self.price_path],
            "dislocationComponents": [c.to_evidence_dict() for c in self.dislocation_components],
            "attributionState": self.attribution_state.value,
            "events": [e.to_evidence_dict() for e in self.events],
            "upstreamEvidence": _deep_copy_mapping(self.upstream_evidence),
            "sourceDigests": _deep_copy_mapping(self.source_digests),
            "liveDataDisclosures": _deep_copy_mapping(self.live_disclosures),
            "synthetic": self.synthetic,
            "boundaries": {
                "referenceStateAuthority": "R4_APPLIED",
                "signalAuthority": "R5_APPLIED",
                "historyAuthority": "R5_APPLIED",
                "terminalAuthority": "R6_APPLIED",
                "crossMarketAuthority": "R7_APPLIED",
                "executableEdgeAuthority": "R8_NOT_YET_APPLIED",
                "assetGraphAuthority": "R9_NOT_YET_APPLIED",
            },
            "r7SnapshotDigest": self.r7_snapshot_digest,
        }


def _deep_copy_mapping(value: Any) -> Any:
    """Fresh deep copy into plain JSON-compatible structures.

    Serialized mutation must never mutate the source, and deep-frozen internal
    structures (MappingProxyType over private dicts, tuple sequences) must
    never leak into serialized output.
    """
    if isinstance(value, Mapping):
        return {k: _deep_copy_mapping(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_deep_copy_mapping(v) for v in value]
    return value


def _layer_dict(observation: LayerObservation | None) -> dict[str, Any] | None:
    if observation is None:
        return None
    return {
        "status": observation.status.value,
        "source": observation.source,
        "price": str(observation.price) if observation.price is not None else None,
        "currency": observation.currency,
        "observedAt": (
            observation.observed_at.isoformat() if observation.observed_at is not None else None
        ),
        "instrument": observation.instrument,
        "multiplier": (
            str(observation.multiplier) if observation.multiplier is not None else None
        ),
        "usable": observation.usable,
        "assetUid": observation.asset_uid,
        "assetKey": (
            observation.asset_key.canonical_id if observation.asset_key is not None else None
        ),
    }


def canonical_evidence_bytes(evidence: Mapping[str, Any]) -> bytes:
    """Canonical JSON encoding used for every R7 digest."""
    return json.dumps(evidence, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode(
        "utf-8"
    )


def compute_snapshot_digest(snapshot: "CrossMarketSnapshot") -> str:
    evidence = snapshot.to_evidence_dict()
    evidence.pop("r7SnapshotDigest", None)
    return hashlib.sha256(canonical_evidence_bytes(evidence)).hexdigest()


def reconstruct_snapshot_digest(snapshot: "CrossMarketSnapshot") -> str:
    """Fresh serialization + digest reconstruction (R6 Correction A pattern)."""
    return compute_snapshot_digest(snapshot)


def verify_serialized_evidence(evidence: Mapping[str, Any]) -> bool:
    """Tamper detection: recompute the digest over serialized evidence.

    The r7SnapshotDigest field is removed, the canonical digest recomputed and
    compared with the recorded digest. Any mutation of the serialized payload
    breaks verification.
    """
    if not isinstance(evidence, Mapping) or "r7SnapshotDigest" not in evidence:
        return False
    material = _deep_copy_mapping(evidence)
    recorded = material.pop("r7SnapshotDigest")
    recomputed = hashlib.sha256(canonical_evidence_bytes(material)).hexdigest()
    return recorded == recomputed
