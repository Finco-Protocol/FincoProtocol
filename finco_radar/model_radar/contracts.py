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
import re
import decimal
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


class ModelEngineAuthority(str, Enum):
    """Exact typed frozen FINCO model-authority identifiers (G1).  An
    engine_authority string that is not one of these members is not frozen
    FINCO model authority, no matter how plausible it looks."""
    FINCO_CORE_XNPV = "finco_core.sponsor.xnpv"
    FINCO_CORE_XIRR = "finco_core.sponsor.xirr"
    FINANCIAL_ENGINE_ORCHESTRATOR = "financial_engine.orchestrator"


class ModelRadarGapKind(str, Enum):
    MODEL_SOURCE_AUTHORITY_UNAVAILABLE = "MODEL_SOURCE_AUTHORITY_UNAVAILABLE"
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


_SHA256_RE = re.compile(r"[0-9a-f]{64}")


def require_finite_decimal(value, name: str) -> None:
    """G5: every numeric authority must be a finite Decimal.  NaN/Infinity
    (Decimal or string form) are typed R10 errors, never silent inputs."""
    if not isinstance(value, decimal.Decimal):
        raise ModelRadarError(
            f"{name} must be a Decimal, got {type(value).__name__}",
            ModelRadarStatus.MODEL_RADAR_INPUT_INVALID,
        )
    if not value.is_finite():
        raise ModelRadarError(
            f"{name} must be finite (got {value}); NaN/Infinity are never "
            "admitted into R10 arithmetic",
            ModelRadarStatus.MODEL_RADAR_INPUT_INVALID,
        )


def require_sha256_shape(digest: str, name: str) -> None:
    if not isinstance(digest, str) or not _SHA256_RE.fullmatch(digest):
        raise ModelRadarError(
            f"{name} must be a lowercase 64-hex SHA-256 digest, got {digest!r}",
            ModelRadarStatus.MODEL_RADAR_EVIDENCE_MISMATCH,
        )


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
            converted = Decimal(value)
        except decimal.InvalidOperation as exc:
            raise ModelRadarError(
                f"model authority {field_name} is not a usable number: "
                f"{value!r}",
                ModelRadarStatus.MODEL_RADAR_INPUT_INVALID,
            ) from exc
        except Exception as exc:
            raise ModelRadarError(
                f"model authority {field_name} is not a usable number: "
                f"{value!r}",
                ModelRadarStatus.MODEL_RADAR_INPUT_INVALID,
            ) from exc
        if not converted.is_finite():
            raise ModelRadarError(
                f"model authority {field_name} must be finite (got {value}); "
                "NaN/Infinity are never admitted",
                ModelRadarStatus.MODEL_RADAR_INPUT_INVALID,
            )
        return converted
    if isinstance(value, decimal.Decimal):
        require_finite_decimal(value, f"model authority {field_name}")
        return value
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
    unit_multiplier_basis: "ModelUnitBasis | None" = None
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
        if isinstance(self.engine_authority, str):
            try:
                object.__setattr__(
                    self, "engine_authority",
                    ModelEngineAuthority(self.engine_authority))
            except ValueError as exc:
                raise ModelRadarError(
                    f"engine_authority {self.engine_authority!r} is not an "
                    "exact typed frozen FINCO model-authority identifier "
                    "(ModelEngineAuthority)",
                    ModelRadarStatus.MODEL_RADAR_EVIDENCE_MISMATCH,
                ) from exc
        if not isinstance(self.engine_authority, ModelEngineAuthority):
            raise ModelRadarError(
                f"engine_authority {self.engine_authority!r} is not an exact "
                "typed frozen FINCO model-authority identifier "
                "(ModelEngineAuthority)",
                ModelRadarStatus.MODEL_RADAR_EVIDENCE_MISMATCH,
            )
        require_finite_decimal(self.value, "model value")
        # G6: closed kind x basis coherence matrix at construction time.
        if self.value_kind is ModelValueKind.VALUE_PER_ECONOMIC_UNIT:
            if self.unit_basis not in PER_UNIT_BASES:
                raise ModelRadarError(
                    "VALUE_PER_ECONOMIC_UNIT requires a PER_UNIT basis; got "
                    f"{self.unit_basis.value}",
                    ModelRadarStatus.MODEL_RADAR_INPUT_INVALID,
                )
        elif self.value_kind is ModelValueKind.EQUITY_VALUE_TOTAL:
            if self.unit_basis is not ModelUnitBasis.TOTAL_EQUITY:
                raise ModelRadarError(
                    "EQUITY_VALUE_TOTAL requires the TOTAL_EQUITY basis; got "
                    f"{self.unit_basis.value}",
                    ModelRadarStatus.MODEL_RADAR_INPUT_INVALID,
                )
            if (self.unit_multiplier_basis is ModelUnitBasis.PER_TOKEN_CLAIM):
                raise ModelRadarError(
                    "an equity total cannot declare a per-token-claim "
                    "multiplier basis: no ownership/token-claim bridge "
                    "authority exists in v1",
                    ModelRadarStatus.MODEL_RADAR_INPUT_INVALID,
                )
        elif self.value_kind is ModelValueKind.ENTERPRISE_VALUE_TOTAL:
            if self.unit_basis is not ModelUnitBasis.TOTAL_ENTERPRISE:
                raise ModelRadarError(
                    "ENTERPRISE_VALUE_TOTAL requires the TOTAL_ENTERPRISE "
                    f"basis; got {self.unit_basis.value}",
                    ModelRadarStatus.MODEL_RADAR_INPUT_INVALID,
                )
        elif self.value_kind is ModelValueKind.PROJECT_NPV_TOTAL:
            if self.unit_basis is not ModelUnitBasis.TOTAL_PROJECT:
                raise ModelRadarError(
                    "PROJECT_NPV_TOTAL requires the TOTAL_PROJECT basis; "
                    f"got {self.unit_basis.value}",
                    ModelRadarStatus.MODEL_RADAR_INPUT_INVALID,
                )
        elif self.value_kind is ModelValueKind.NAV_TOTAL:
            if self.unit_basis not in TOTAL_BASES:
                raise ModelRadarError(
                    "NAV_TOTAL requires a TOTAL unit basis; got "
                    f"{self.unit_basis.value}",
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
        if isinstance(self.engine_authority, str):
            try:
                object.__setattr__(
                    self, "engine_authority",
                    ModelEngineAuthority(self.engine_authority))
            except ValueError as exc:
                raise ModelRadarError(
                    f"engine_authority {self.engine_authority!r} is not an "
                    "exact typed frozen FINCO model-authority identifier "
                    "(ModelEngineAuthority)",
                    ModelRadarStatus.MODEL_RADAR_EVIDENCE_MISMATCH,
                ) from exc
        if not isinstance(self.engine_authority, ModelEngineAuthority):
            raise ModelRadarError(
                f"engine_authority {self.engine_authority!r} is not an exact "
                "typed frozen FINCO model-authority identifier "
                "(ModelEngineAuthority)",
                ModelRadarStatus.MODEL_RADAR_EVIDENCE_MISMATCH,
            )
        require_finite_decimal(self.value, "model value")
        # G6: closed kind x basis coherence matrix at construction time.
        if self.value_kind is ModelValueKind.VALUE_PER_ECONOMIC_UNIT:
            if self.unit_basis not in PER_UNIT_BASES:
                raise ModelRadarError(
                    "VALUE_PER_ECONOMIC_UNIT requires a PER_UNIT basis; got "
                    f"{self.unit_basis.value}",
                    ModelRadarStatus.MODEL_RADAR_INPUT_INVALID,
                )
        elif self.value_kind is ModelValueKind.EQUITY_VALUE_TOTAL:
            if self.unit_basis is not ModelUnitBasis.TOTAL_EQUITY:
                raise ModelRadarError(
                    "EQUITY_VALUE_TOTAL requires the TOTAL_EQUITY basis; got "
                    f"{self.unit_basis.value}",
                    ModelRadarStatus.MODEL_RADAR_INPUT_INVALID,
                )
            if (self.unit_multiplier_basis is ModelUnitBasis.PER_TOKEN_CLAIM):
                raise ModelRadarError(
                    "an equity total cannot declare a per-token-claim "
                    "multiplier basis: no ownership/token-claim bridge "
                    "authority exists in v1",
                    ModelRadarStatus.MODEL_RADAR_INPUT_INVALID,
                )
        elif self.value_kind is ModelValueKind.ENTERPRISE_VALUE_TOTAL:
            if self.unit_basis is not ModelUnitBasis.TOTAL_ENTERPRISE:
                raise ModelRadarError(
                    "ENTERPRISE_VALUE_TOTAL requires the TOTAL_ENTERPRISE "
                    f"basis; got {self.unit_basis.value}",
                    ModelRadarStatus.MODEL_RADAR_INPUT_INVALID,
                )
        elif self.value_kind is ModelValueKind.PROJECT_NPV_TOTAL:
            if self.unit_basis is not ModelUnitBasis.TOTAL_PROJECT:
                raise ModelRadarError(
                    "PROJECT_NPV_TOTAL requires the TOTAL_PROJECT basis; "
                    f"got {self.unit_basis.value}",
                    ModelRadarStatus.MODEL_RADAR_INPUT_INVALID,
                )
        elif self.value_kind is ModelValueKind.NAV_TOTAL:
            if self.unit_basis not in TOTAL_BASES:
                raise ModelRadarError(
                    "NAV_TOTAL requires a TOTAL unit basis; got "
                    f"{self.unit_basis.value}",
                    ModelRadarStatus.MODEL_RADAR_INPUT_INVALID,
                )
        if self.unit_multiplier is not None:
            require_finite_decimal(self.unit_multiplier, "unit_multiplier")
            if self.unit_multiplier <= 0:
                raise ModelRadarError(
                    "unit multiplier must be positive when source-proven",
                    ModelRadarStatus.MODEL_RADAR_INPUT_INVALID,
                )
            if self.unit_multiplier_basis is None or not isinstance(
                self.unit_multiplier_basis, ModelUnitBasis
            ) or self.unit_multiplier_basis not in PER_UNIT_BASES:
                raise ModelRadarError(
                    "a source-proven unit multiplier must declare the exact "
                    "per-unit basis it counts (PER_UNIT basis); it is never "
                    "inferred",
                    ModelRadarStatus.MODEL_RADAR_INPUT_INVALID,
                )
        elif self.unit_multiplier_basis is not None:
            raise ModelRadarError(
                "unit multiplier basis supplied without a unit multiplier",
                ModelRadarStatus.MODEL_RADAR_INPUT_INVALID,
            )
        # F4: digests are self-verifying, never caller-asserted.
        require_sha256_shape(self.input_digest, "input_digest")
        require_sha256_shape(self.output_digest, "output_digest")
        if self.input_digest != digest_payload(_plain(self.input_evidence)):
            raise ModelRadarError(
                "input_digest does not equal the canonical digest of "
                "inputEvidence",
                ModelRadarStatus.MODEL_RADAR_EVIDENCE_MISMATCH,
            )
        if self.output_digest != digest_payload(_plain(self.output_evidence)):
            raise ModelRadarError(
                "output_digest does not equal the canonical digest of "
                "outputEvidence",
                ModelRadarStatus.MODEL_RADAR_EVIDENCE_MISMATCH,
            )
        # G3: the declared comparison-critical fields must be exactly the
        # authoritative serialized output observation; two independently
        # caller-asserted versions of the model value can never exist.
        output = _plain(self.output_evidence)
        for key in ("value", "valueKind", "currency", "unitBasis"):
            if key not in output:
                raise ModelRadarError(
                    f"model output observation is missing the "
                    f"comparison-critical key {key!r}",
                    ModelRadarStatus.MODEL_RADAR_EVIDENCE_MISMATCH,
                )
        if output["value"] != str(self.value):
            raise ModelRadarError(
                f"model output observation value {output['value']!r} does "
                f"not equal the declared model value {str(self.value)!r}",
                ModelRadarStatus.MODEL_RADAR_EVIDENCE_MISMATCH,
            )
        if output["valueKind"] != self.value_kind.value:
            raise ModelRadarError(
                f"model output observation valueKind {output['valueKind']!r} "
                f"does not equal the declared valueKind "
                f"{self.value_kind.value!r}",
                ModelRadarStatus.MODEL_RADAR_EVIDENCE_MISMATCH,
            )
        if output["currency"] != self.currency:
            raise ModelRadarError(
                f"model output observation currency {output['currency']!r} "
                f"does not equal the declared currency {self.currency!r}",
                ModelRadarStatus.MODEL_RADAR_EVIDENCE_MISMATCH,
            )
        if output["unitBasis"] != self.unit_basis.value:
            raise ModelRadarError(
                f"model output observation unitBasis {output['unitBasis']!r} "
                f"does not equal the declared unitBasis "
                f"{self.unit_basis.value!r}",
                ModelRadarStatus.MODEL_RADAR_EVIDENCE_MISMATCH,
            )
        # Multiplier/valuation timestamp are bound wherever they are
        # declared as authority (output or input); disagreement fails.
        for source_name, source in (("output", output),
                                    ("input", _plain(self.input_evidence))):
            if source.get("unitMultiplier") is not None and str(
                source["unitMultiplier"]
            ) != (
                str(self.unit_multiplier)
                if self.unit_multiplier is not None else None
            ):
                raise ModelRadarError(
                    f"model {source_name} observation unitMultiplier "
                    f"{source['unitMultiplier']!r} does not equal the "
                    f"declared unit multiplier",
                    ModelRadarStatus.MODEL_RADAR_EVIDENCE_MISMATCH,
                )
            if source.get("valuationAsOf") is not None and str(
                source["valuationAsOf"]
            ) != self.valuation_as_of.isoformat():
                raise ModelRadarError(
                    f"model {source_name} observation valuationAsOf "
                    f"{source['valuationAsOf']!r} does not equal the "
                    "declared valuation timestamp",
                    ModelRadarStatus.MODEL_RADAR_EVIDENCE_MISMATCH,
                )
        if self.value_original_representation == "":
            object.__setattr__(
                self, "value_original_representation", str(self.value))
        computed = self._compute_run_digest()
        if self.model_run_digest:
            require_sha256_shape(self.model_run_digest, "model_run_digest")
            if self.model_run_digest != computed:
                raise ModelRadarError(
                    "supplied model_run_digest does not equal the "
                    "deterministically computed run digest",
                    ModelRadarStatus.MODEL_RADAR_EVIDENCE_MISMATCH,
                )
        else:
            object.__setattr__(self, "model_run_digest", computed)

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
            "unitMultiplierBasis": (
                self.unit_multiplier_basis.value
                if self.unit_multiplier_basis is not None else None
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
            "unitMultiplierBasis": (
                self.unit_multiplier_basis.value
                if self.unit_multiplier_basis is not None else None
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
        required = {d for d in ComparabilityDimension}
        seen: dict[ComparabilityDimension, int] = {}
        for result in self.dimensions:
            if not isinstance(result.dimension, ComparabilityDimension):
                raise ModelRadarError(
                    "unknown comparability dimension",
                    ModelRadarStatus.MODEL_RADAR_INPUT_INVALID,
                )
            seen[result.dimension] = seen.get(result.dimension, 0) + 1
        duplicates = sorted(d.value for d, count in seen.items() if count > 1)
        missing = sorted(d.value for d in required if d not in seen)
        if duplicates or missing:
            raise ModelRadarError(
                "comparability evaluation must contain exactly one result "
                f"per dimension; missing={missing} duplicated={duplicates}",
                ModelRadarStatus.MODEL_RADAR_INPUT_INVALID,
            )
        # G4: semantic consistency between records and declared state.
        for result in self.dimensions:
            if result.ok and result.gap_kind is not None:
                raise ModelRadarError(
                    f"dimension {result.dimension.value} is ok but carries "
                    f"gap {result.gap_kind.value}",
                    ModelRadarStatus.MODEL_RADAR_INPUT_INVALID,
                )
            if not result.ok and result.gap_kind is None:
                raise ModelRadarError(
                    f"dimension {result.dimension.value} failed without a "
                    "typed gap kind",
                    ModelRadarStatus.MODEL_RADAR_INPUT_INVALID,
                )
        failed = {
            result.dimension for result in self.dimensions if not result.ok
        }
        if self.state is ComparabilityState.COMPARABLE and failed:
            raise ModelRadarError(
                "COMPARABLE state with failed dimensions: "
                f"{sorted(d.value for d in failed)}",
                ModelRadarStatus.MODEL_RADAR_INPUT_INVALID,
            )
        if self.state is ComparabilityState.PARTIALLY_COMPARABLE:
            unauthorized = failed - {ComparabilityDimension.REFERENCE_AVAILABILITY}
            if not failed or unauthorized:
                raise ModelRadarError(
                    "PARTIALLY_COMPARABLE is reserved for reference-only "
                    f"unavailability; unauthorized failures: "
                    f"{sorted(d.value for d in unauthorized or failed)}",
                    ModelRadarStatus.MODEL_RADAR_INPUT_INVALID,
                )
        if self.state is ComparabilityState.NOT_COMPARABLE and not failed:
            raise ModelRadarError(
                "NOT_COMPARABLE state with all seven dimensions ok",
                ModelRadarStatus.MODEL_RADAR_INPUT_INVALID,
            )
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
            require_finite_decimal(value, name)
            if value <= 0:
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
        comparison_keys = [
            (c.side, Decimal(c.requested_notional_usd), c.quote_source)
            for c in self.execution_comparisons
        ]
        if comparison_keys != sorted(comparison_keys):
            raise ModelRadarError(
                "execution comparisons must be supplied in canonical "
                "(side, notional, venue) order; canonicalization happens "
                "before the snapshot digest, never after",
                ModelRadarStatus.MODEL_RADAR_EVIDENCE_MISMATCH,
            )
        gap_keys = [
            (g.gap_kind.value, g.source, g.reason) for g in self.gaps
        ]
        if gap_keys != sorted(gap_keys):
            raise ModelRadarError(
                "gaps must be supplied in canonical order",
                ModelRadarStatus.MODEL_RADAR_EVIDENCE_MISMATCH,
            )

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
