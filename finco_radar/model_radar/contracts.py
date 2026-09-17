"""Typed contracts for FINCO Radar R10 — FINCO MODEL × RADAR.

R10 binds existing frozen FINCO model authority to the R9 economic asset
identity and compares model evidence with market/reference/execution
evidence only when economic identity, value kind, unit basis, currency,
multiplier and timing are source-proven compatible.

A FINCO model value is MODEL EVIDENCE, not market truth.  R10 never
fabricates model authority: a missing binding is an explicit typed gap
(``MODEL_RADAR_PARTIAL``), never a synthetic valuation.

Deep immutability from initial implementation.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import Enum
from types import MappingProxyType
from typing import Any, Mapping

SCHEMA_VERSION = "radar-r10-model-radar-v1"
PHASE = "R10"


class ModelRadarStatus(str, Enum):
    MODEL_RADAR_OK = "MODEL_RADAR_OK"
    MODEL_RADAR_PARTIAL = "MODEL_RADAR_PARTIAL"
    MODEL_RADAR_LINEAGE_MISMATCH = "MODEL_RADAR_LINEAGE_MISMATCH"
    MODEL_RADAR_INPUT_INVALID = "MODEL_RADAR_INPUT_INVALID"
    MODEL_RADAR_TIMING_INVALID = "MODEL_RADAR_TIMING_INVALID"
    MODEL_RADAR_EVIDENCE_MISMATCH = "MODEL_RADAR_EVIDENCE_MISMATCH"


class ModelRadarGapKind(str, Enum):
    MODEL_BINDING_UNAVAILABLE = "MODEL_BINDING_UNAVAILABLE"
    MODEL_INPUT_UNAVAILABLE = "MODEL_INPUT_UNAVAILABLE"
    MODEL_OUTPUT_UNAVAILABLE = "MODEL_OUTPUT_UNAVAILABLE"
    MODEL_VALUE_UNAVAILABLE = "MODEL_VALUE_UNAVAILABLE"
    MODEL_DISCOUNT_RATE_AUTHORITY_UNAVAILABLE = (
        "MODEL_DISCOUNT_RATE_AUTHORITY_UNAVAILABLE"
    )
    VALUE_KIND_MISMATCH = "VALUE_KIND_MISMATCH"
    UNIT_BASIS_UNAVAILABLE = "UNIT_BASIS_UNAVAILABLE"
    UNIT_BASIS_MISMATCH = "UNIT_BASIS_MISMATCH"
    MULTIPLIER_UNAVAILABLE = "MULTIPLIER_UNAVAILABLE"
    CURRENCY_UNAVAILABLE = "CURRENCY_UNAVAILABLE"
    CURRENCY_MISMATCH = "CURRENCY_MISMATCH"
    FX_AUTHORITY_UNAVAILABLE = "FX_AUTHORITY_UNAVAILABLE"
    MODEL_TIMING_UNAVAILABLE = "MODEL_TIMING_UNAVAILABLE"
    MODEL_STALE = "MODEL_STALE"
    TIMING_SKEW_INVALID = "TIMING_SKEW_INVALID"
    REFERENCE_UNAVAILABLE = "REFERENCE_UNAVAILABLE"
    EXECUTION_EVIDENCE_UNAVAILABLE = "EXECUTION_EVIDENCE_UNAVAILABLE"
    MODEL_VALUE_NONPOSITIVE = "MODEL_VALUE_NONPOSITIVE"


class ModelValueKind(str, Enum):
    """Closed value-kind vocabulary.  Return metrics (XIRR/IRR) and operating
    metrics (DSCR/LLCR/EBITDA/cash flow) are NON_PRICE_METRIC evidence and are
    never silently classified as value."""
    VALUE_PER_ECONOMIC_UNIT = "VALUE_PER_ECONOMIC_UNIT"
    EQUITY_VALUE_TOTAL = "EQUITY_VALUE_TOTAL"
    ENTERPRISE_VALUE_TOTAL = "ENTERPRISE_VALUE_TOTAL"
    NAV_TOTAL = "NAV_TOTAL"
    PROJECT_NPV_TOTAL = "PROJECT_NPV_TOTAL"
    NON_PRICE_METRIC = "NON_PRICE_METRIC"


class ModelUnitBasis(str, Enum):
    """Explicit denominator vocabulary.  The denominator is never inferred."""
    PER_SHARE = "PER_SHARE"
    PER_TOKEN_CLAIM = "PER_TOKEN_CLAIM"
    PER_ECONOMIC_UNIT = "PER_ECONOMIC_UNIT"
    TOTAL_EQUITY = "TOTAL_EQUITY"
    TOTAL_ENTERPRISE = "TOTAL_ENTERPRISE"
    TOTAL_PROJECT = "TOTAL_PROJECT"


class ComparabilityState(str, Enum):
    COMPARABLE = "COMPARABLE"
    PARTIALLY_COMPARABLE = "PARTIALLY_COMPARABLE"
    NOT_COMPARABLE = "NOT_COMPARABLE"


class ComparabilityDimension(str, Enum):
    ECONOMIC_IDENTITY = "ECONOMIC_IDENTITY"
    VALUE_KIND = "VALUE_KIND"
    UNIT_BASIS = "UNIT_BASIS"
    CURRENCY = "CURRENCY"
    MULTIPLIER = "MULTIPLIER"
    TIMING = "TIMING"
    REFERENCE_AVAILABILITY = "REFERENCE_AVAILABILITY"


# Unit-basis families that can be price-comparable against a per-unit market
# price without any normalization authority.
PER_UNIT_BASES = (
    ModelUnitBasis.PER_ECONOMIC_UNIT,
    ModelUnitBasis.PER_SHARE,
    ModelUnitBasis.PER_TOKEN_CLAIM,
)
TOTAL_BASES = (
    ModelUnitBasis.TOTAL_EQUITY,
    ModelUnitBasis.TOTAL_ENTERPRISE,
    ModelUnitBasis.TOTAL_PROJECT,
)


class ModelRadarError(ValueError):
    """Typed fail-closed R10 error."""

    def __init__(self, message: str, status: ModelRadarStatus) -> None:
        super().__init__(message)
        self.status = status


def deep_freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType({k: deep_freeze(v) for k, v in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(deep_freeze(v) for v in value)
    return value


def _plain(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {k: _plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(v) for v in value]
    return value


def canonical_evidence_bytes(evidence: Any) -> bytes:
    return json.dumps(evidence, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False).encode("utf-8")


def digest_payload(payload: Any) -> str:
    return hashlib.sha256(canonical_evidence_bytes(payload)).hexdigest()


def decimal_from_authority(value: Any, *, field_name: str = "value") -> Decimal:
    """Convert an upstream authority result to Decimal via its canonical
    textual representation.  Frozen model functions may return Python float:
    the authoritative value is preserved through str() text, never through
    Decimal(binary_float)."""
    if isinstance(value, Decimal):
        return value
    if isinstance(value, bool) or value is None:
        raise ModelRadarError(
            f"model authority {field_name} is not a number",
            ModelRadarStatus.MODEL_RADAR_INPUT_INVALID,
        )
    if isinstance(value, float):
        if value != value or value in (float("inf"), float("-inf")):
            raise ModelRadarError(
                f"model authority {field_name} is not finite",
                ModelRadarStatus.MODEL_RADAR_INPUT_INVALID,
            )
        return Decimal(repr(value))
    if isinstance(value, (int, str)):
        try:
            return Decimal(value)
        except Exception as exc:
            raise ModelRadarError(
                f"model authority {field_name} is not a usable number: {value!r}",
                ModelRadarStatus.MODEL_RADAR_INPUT_INVALID,
            ) from exc
    raise ModelRadarError(
        f"model authority {field_name} has unsupported type {type(value).__name__}",
        ModelRadarStatus.MODEL_RADAR_INPUT_INVALID,
    )


def _require_aware(value: datetime, name: str) -> None:
    if value.tzinfo is None or value.tzinfo.utcoffset(value) is None:
        raise ModelRadarError(
            f"{name} must be timezone-aware",
            ModelRadarStatus.MODEL_RADAR_TIMING_INVALID,
        )


@dataclass(frozen=True)
class ModelBinding:
    """Typed model-to-economic-asset binding.  Binding identity is derived
    from the canonical economic identity (UID + canonical R9 economic node
    ID) plus the model identity — never from a ticker or display name."""
    economic_asset_uid: str
    economic_node_id: str
    model_id: str
    model_version: str
    binding_id: str = ""

    def __post_init__(self) -> None:
        if not self.economic_asset_uid.strip():
            raise ModelRadarError(
                "binding economic_asset_uid must be non-empty",
                ModelRadarStatus.MODEL_RADAR_INPUT_INVALID,
            )
        expected_node = f"economic:{self.economic_asset_uid}"
        if self.economic_node_id != expected_node:
            raise ModelRadarError(
                "binding economic_node_id must be the canonical R9 economic "
                f"node {expected_node}",
                ModelRadarStatus.MODEL_RADAR_INPUT_INVALID,
            )
        if not self.model_id.strip() or not self.model_version.strip():
            raise ModelRadarError(
                "binding model_id and model_version must be non-empty",
                ModelRadarStatus.MODEL_RADAR_INPUT_INVALID,
            )
        canonical = {
            "economicAssetUid": self.economic_asset_uid,
            "economicNodeId": self.economic_node_id,
            "modelId": self.model_id,
            "modelVersion": self.model_version,
        }
        expected = (
            "model-binding:" + hashlib.sha256(
                canonical_evidence_bytes(canonical)).hexdigest()
        )
        if not self.binding_id:
            object.__setattr__(self, "binding_id", expected)
        elif self.binding_id != expected:
            raise ModelRadarError(
                "binding_id does not match the canonical binding identity",
                ModelRadarStatus.MODEL_RADAR_EVIDENCE_MISMATCH,
            )

    def to_evidence_dict(self) -> dict[str, Any]:
        return {
            "bindingId": self.binding_id,
            "economicAssetUid": self.economic_asset_uid,
            "economicNodeId": self.economic_node_id,
            "modelId": self.model_id,
            "modelVersion": self.model_version,
        }


@dataclass(frozen=True)
class ModelEvidence:
    """Immutable evidence record for one frozen-authority model output bound
    to one economic asset."""
    model_id: str
    model_version: str
    engine_authority: str
    economic_asset_uid: str
    economic_node_id: str
    valuation_as_of: datetime
    value_kind: ModelValueKind
    value: Decimal
    currency: str
    unit_basis: ModelUnitBasis
    input_digest: str
    output_digest: str
    model_run_digest: str = ""
    input_evidence: Mapping[str, Any] = field(default_factory=dict)
    output_evidence: Mapping[str, Any] = field(default_factory=dict)
    unit_multiplier: Decimal | None = None
    value_original_representation: str = ""
    synthetic: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "input_evidence", deep_freeze(self.input_evidence))
        object.__setattr__(self, "output_evidence", deep_freeze(self.output_evidence))
        _require_aware(self.valuation_as_of, "valuation_as_of")
        if not isinstance(self.value, Decimal):
            raise ModelRadarError(
                "model value must already be a Decimal (use "
                "decimal_from_authority at the boundary)",
                ModelRadarStatus.MODEL_RADAR_INPUT_INVALID,
            )
        if not isinstance(self.value_kind, ModelValueKind):
            raise ModelRadarError(
                "model value_kind must be a closed ModelValueKind member",
                ModelRadarStatus.MODEL_RADAR_INPUT_INVALID,
            )
        if not isinstance(self.unit_basis, ModelUnitBasis):
            raise ModelRadarError(
                "model unit_basis must be a closed ModelUnitBasis member; "
                "the denominator is never inferred",
                ModelRadarStatus.MODEL_RADAR_INPUT_INVALID,
            )
        if not isinstance(self.value_kind, ModelValueKind):
            raise ModelRadarError(
                "model value_kind must be a closed ModelValueKind member",
                ModelRadarStatus.MODEL_RADAR_INPUT_INVALID,
            )
        if not isinstance(self.unit_basis, ModelUnitBasis):
            raise ModelRadarError(
                "model unit_basis must be a closed ModelUnitBasis member; "
                "the denominator is never inferred",
                ModelRadarStatus.MODEL_RADAR_INPUT_INVALID,
            )
        if not self.input_digest.strip() or not self.output_digest.strip():
            raise ModelRadarError(
                "model input/output digests are required",
                ModelRadarStatus.MODEL_RADAR_EVIDENCE_MISMATCH,
            )
        if self.value_original_representation == "":
            object.__setattr__(
                self, "value_original_representation", str(self.value))
        object.__setattr__(
            self,
            "model_run_digest",
            self.model_run_digest or self._compute_run_digest(),
        )

    def _compute_run_digest(self) -> str:
        material = {
            "modelId": self.model_id,
            "modelVersion": self.model_version,
            "engineAuthority": self.engine_authority,
            "economicAssetUid": self.economic_asset_uid,
            "economicNodeId": self.economic_node_id,
            "valuationAsOf": self.valuation_as_of.isoformat(),
            "valueKind": self.value_kind.value,
            "value": str(self.value),
            "currency": self.currency,
            "unitBasis": self.unit_basis.value,
            "unitMultiplier": (
                str(self.unit_multiplier)
                if self.unit_multiplier is not None else None
            ),
            "inputDigest": self.input_digest,
            "outputDigest": self.output_digest,
        }
        return digest_payload(material)

    def to_evidence_dict(self) -> dict[str, Any]:
        return {
            "modelId": self.model_id,
            "modelVersion": self.model_version,
            "engineAuthority": self.engine_authority,
            "economicAssetUid": self.economic_asset_uid,
            "economicNodeId": self.economic_node_id,
            "valuationAsOf": self.valuation_as_of.isoformat(),
            "valueKind": self.value_kind.value,
            "value": str(self.value),
            "currency": self.currency,
            "unitBasis": self.unit_basis.value,
            "unitMultiplier": (
                str(self.unit_multiplier)
                if self.unit_multiplier is not None else None
            ),
            "valueOriginalRepresentation": self.value_original_representation,
            "inputDigest": self.input_digest,
            "outputDigest": self.output_digest,
            "modelRunDigest": self.model_run_digest,
            "inputEvidence": _plain(self.input_evidence),
            "outputEvidence": _plain(self.output_evidence),
            "synthetic": self.synthetic,
        }


@dataclass(frozen=True)
class ComparabilityDimensionResult:
    dimension: ComparabilityDimension
    ok: bool
    gap_kind: ModelRadarGapKind | None = None
    detail: str = ""

    def to_evidence_dict(self) -> dict[str, Any]:
        return {
            "dimension": self.dimension.value,
            "ok": self.ok,
            "gapKind": self.gap_kind.value if self.gap_kind else None,
            "detail": self.detail,
        }


@dataclass(frozen=True)
class ModelComparability:
    state: ComparabilityState
    dimensions: tuple[ComparabilityDimensionResult, ...]

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "dimensions",
            tuple(sorted(self.dimensions, key=lambda d: d.dimension.value)))

    @property
    def gaps(self) -> tuple[ModelRadarGapKind, ...]:
        return tuple(
            d.gap_kind for d in self.dimensions
            if d.gap_kind is not None
        )

    def to_evidence_dict(self) -> dict[str, Any]:
        return {
            "state": self.state.value,
            "dimensions": [d.to_evidence_dict() for d in self.dimensions],
            "gaps": [g.value for g in self.gaps],
        }


@dataclass(frozen=True)
class ReferenceComparison:
    """Descriptive market-reference-vs-model deviation.  Field names are
    deliberately neutral: never upside/downside/profit/opportunity."""
    model_value: Decimal
    reference_price: Decimal
    reference_source: str
    reference_minus_model_value: Decimal
    reference_vs_model_bps: Decimal
    model_observed_at: datetime
    reference_observed_at: datetime

    def to_evidence_dict(self) -> dict[str, Any]:
        return {
            "modelValue": str(self.model_value),
            "referencePrice": str(self.reference_price),
            "referenceSource": self.reference_source,
            "referenceMinusModelValue": str(self.reference_minus_model_value),
            "referenceVsModelBps": str(self.reference_vs_model_bps),
            "modelObservedAt": self.model_observed_at.isoformat(),
            "referenceObservedAt": self.reference_observed_at.isoformat(),
            "semantics": (
                "descriptive deviation; positive bps means the market "
                "reference is above the model value basis"
            ),
        }


@dataclass(frozen=True)
class ExecutionComparison:
    """Observed R8 execution value vs model value.  R8 economics are never
    recomputed and R8 partial states are preserved verbatim."""
    model_value: Decimal
    execution_price: Decimal
    execution_minus_model_value: Decimal
    execution_vs_model_bps: Decimal
    side: str
    requested_notional_usd: str
    quote_source: str
    r8_net_edge_state: str
    r8_scenario_index: int

    def to_evidence_dict(self) -> dict[str, Any]:
        return {
            "modelValue": str(self.model_value),
            "executionPrice": str(self.execution_price),
            "executionMinusModelValue": str(self.execution_minus_model_value),
            "executionVsModelBps": str(self.execution_vs_model_bps),
            "side": self.side,
            "requestedNotionalUsd": self.requested_notional_usd,
            "quoteSource": self.quote_source,
            "r8NetEdgeState": self.r8_net_edge_state,
            "r8ScenarioIndex": self.r8_scenario_index,
            "semantics": (
                "descriptive deviation with identical sign semantics for BUY "
                "and SELL; not the R8 favorable executable edge"
            ),
        }


@dataclass(frozen=True)
class ModelRadarTimingPolicy:
    max_model_age_seconds: Decimal
    max_model_market_skew_seconds: Decimal

    def __post_init__(self) -> None:
        for name in ("max_model_age_seconds", "max_model_market_skew_seconds"):
            value = getattr(self, name)
            if not isinstance(value, Decimal) or value <= 0:
                raise ModelRadarError(
                    f"{name} must be a positive Decimal",
                    ModelRadarStatus.MODEL_RADAR_INPUT_INVALID,
                )

    def to_evidence_dict(self) -> dict[str, Any]:
        return {
            "maxModelAgeSeconds": str(self.max_model_age_seconds),
            "maxModelMarketSkewSeconds": str(self.max_model_market_skew_seconds),
        }


@dataclass(frozen=True)
class ModelRadarGap:
    gap_kind: ModelRadarGapKind
    source: str
    reason: str

    def to_evidence_dict(self) -> dict[str, str]:
        return {
            "gapKind": self.gap_kind.value,
            "source": self.source,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class ModelRadarSnapshot:
    status: ModelRadarStatus
    generated_at: datetime
    git_head: str
    economic_asset_uid: str
    economic_node_id: str
    canonical_asset_key: Mapping[str, Any]
    model_binding: ModelBinding | None
    model_evidence: ModelEvidence | None
    comparability: ModelComparability | None
    reference_comparison: ReferenceComparison | None
    execution_comparisons: tuple[ExecutionComparison, ...]
    gaps: tuple[ModelRadarGap, ...]
    source_digests: Mapping[str, str]
    upstream_evidence: Mapping[str, Any]
    boundaries: Mapping[str, str]
    timing_policy: ModelRadarTimingPolicy
    synthetic: bool
    r10_snapshot_digest: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "canonical_asset_key",
                           deep_freeze(self.canonical_asset_key))
        object.__setattr__(self, "source_digests", deep_freeze(self.source_digests))
        object.__setattr__(self, "upstream_evidence", deep_freeze(self.upstream_evidence))
        object.__setattr__(self, "boundaries", deep_freeze(self.boundaries))
        _require_aware(self.generated_at, "generated_at")
        if not self.r10_snapshot_digest:
            raise ModelRadarError(
                "r10_snapshot_digest is required",
                ModelRadarStatus.MODEL_RADAR_EVIDENCE_MISMATCH,
            )
        comparisons = tuple(sorted(
            self.execution_comparisons,
            key=lambda c: (c.side, Decimal(c.requested_notional_usd), c.quote_source),
        ))
        object.__setattr__(self, "execution_comparisons", comparisons)
        gaps = tuple(sorted(
            self.gaps, key=lambda g: (g.gap_kind.value, g.source, g.reason)))
        object.__setattr__(self, "gaps", gaps)

    def to_evidence_dict(self) -> dict[str, Any]:
        return {
            "schemaVersion": SCHEMA_VERSION,
            "phase": PHASE,
            "status": self.status.value,
            "generatedAt": self.generated_at.isoformat(),
            "gitHead": self.git_head,
            "economicAssetUid": self.economic_asset_uid,
            "economicNodeId": self.economic_node_id,
            "canonicalAssetKey": _plain(self.canonical_asset_key),
            "modelBinding": (
                self.model_binding.to_evidence_dict()
                if self.model_binding else None
            ),
            "modelEvidence": (
                self.model_evidence.to_evidence_dict()
                if self.model_evidence else None
            ),
            "comparability": (
                self.comparability.to_evidence_dict()
                if self.comparability else None
            ),
            "referenceComparison": (
                self.reference_comparison.to_evidence_dict()
                if self.reference_comparison else None
            ),
            "executionComparisons": [
                c.to_evidence_dict() for c in self.execution_comparisons
            ],
            "gaps": [g.to_evidence_dict() for g in self.gaps],
            "sourceDigests": dict(self.source_digests),
            "upstreamEvidence": _plain(self.upstream_evidence),
            "boundaries": dict(self.boundaries),
            "timingPolicy": self.timing_policy.to_evidence_dict(),
            "synthetic": self.synthetic,
            "r10SnapshotDigest": self.r10_snapshot_digest,
        }


def compute_snapshot_digest(snapshot: ModelRadarSnapshot) -> str:
    evidence = snapshot.to_evidence_dict()
    evidence.pop("r10SnapshotDigest", None)
    return digest_payload(evidence)


def verify_r10_snapshot_digest(snapshot: ModelRadarSnapshot) -> bool:
    return compute_snapshot_digest(snapshot) == snapshot.r10_snapshot_digest


def verify_serialized_r10_evidence(evidence: Any) -> bool:
    """Fail-closed tamper detection over serialized R10 evidence dicts."""
    if not isinstance(evidence, Mapping) or "r10SnapshotDigest" not in evidence:
        return False
    material = _plain(evidence)
    recorded = material.pop("r10SnapshotDigest")
    return recorded == digest_payload(material)
