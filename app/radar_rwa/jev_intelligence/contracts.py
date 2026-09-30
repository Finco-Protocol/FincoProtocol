"""Typed contracts for JEV Radar Intelligence V1."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Mapping

FEATURE_SCHEMA_VERSION = "JEV_RLIVE_FEATURES_V1"
QUESTION_SCHEMA_VERSION = "JEV_RLIVE_QUESTIONS_V1"
PROVIDER = "TYPESAFE_JEV"

DISCLOSURE = (
    "Jev intelligence is a probabilistic interpretation of FINCO canonical market evidence. "
    "It does not modify canonical market data and is not an executable price, investment "
    "recommendation, FINCO Verify result, or deterministic calculation authority."
)

UNAVAILABLE_FEATURE = "UNAVAILABLE"
FINGERPRINT_RE = re.compile(r"^[0-9a-f]{64}$")

FAILURE_CATEGORIES = frozenset({
    "TIMEOUT", "NETWORK", "HTTP_408", "HTTP_429", "HTTP_5XX", "AUTH",
    "INVALID_REQUEST", "INVALID_RESPONSE", "RETRY_BUDGET_EXHAUSTED",
})

REGIME_OPTIONS = ("MOMENTUM", "MEAN_REVERTING", "RANGE_BOUND", "UNRESOLVED")
ATTENTION_LEVELS = ("NORMAL", "ELEVATED", "HIGH")
QUESTION_IDS = frozenset({"market_regime", "attention"})


class IntelligenceState(str, Enum):
    AVAILABLE = "AVAILABLE"
    DISABLED = "DISABLED"
    UNAVAILABLE = "UNAVAILABLE"
    INVALID_RESPONSE = "INVALID_RESPONSE"


class JevMode(str, Enum):
    OFF = "OFF"
    SHADOW = "SHADOW"
    VISIBLE = "VISIBLE"


@dataclass(frozen=True)
class FeatureState:
    """Identity-blinded deterministic feature buckets plus local-only evidence digest."""

    features: Mapping[str, str]
    input_fingerprint: str
    observation_digest: str
    as_of: datetime
    sources: tuple[str, ...]
    ttl_seconds: int
    schema_version: str = FEATURE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if not FINGERPRINT_RE.fullmatch(self.input_fingerprint):
            raise ValueError("input_fingerprint must be a lowercase sha256 hex digest")
        if not FINGERPRINT_RE.fullmatch(self.observation_digest):
            raise ValueError("observation_digest must be a lowercase sha256 hex digest")


@dataclass(frozen=True)
class RegimeAnswer:
    choice: str
    probabilities: tuple[tuple[str, Decimal], ...]
    confidence: Decimal | None


@dataclass(frozen=True)
class AttentionAnswer:
    state: str
    score: Decimal
    confidence: Decimal | None


@dataclass(frozen=True)
class Diagnostics:
    cache_status: str = "MISS"  # MISS | HIT | COALESCED | NOT_APPLICABLE
    latency_ms: Decimal | None = None
    attempt_count: int | None = None
    provider_request_id: str | None = None
    usage: tuple[tuple[str, str], ...] = ()
    failure_category: str | None = None


@dataclass(frozen=True)
class IntelligenceResult:
    state: IntelligenceState
    canonical_id: str
    economic_asset_uid: str | None = None
    reason: str | None = None
    observation_digest: str | None = None
    input_fingerprint: str | None = None
    feature_schema_version: str = FEATURE_SCHEMA_VERSION
    question_schema_version: str = QUESTION_SCHEMA_VERSION
    market_regime: RegimeAnswer | None = None
    attention: AttentionAnswer | None = None
    requested_model: str | None = None
    resolved_model: str | None = None
    evaluated_at: datetime | None = None
    as_of: datetime | None = None
    sources: tuple[str, ...] = ()
    mode: JevMode = JevMode.VISIBLE
    diagnostics: Diagnostics = field(default_factory=Diagnostics)

    def __post_init__(self) -> None:
        if self.state is IntelligenceState.AVAILABLE:
            if self.market_regime is None or self.attention is None:
                raise ValueError("available intelligence requires typed answers")
            if not self.resolved_model or not self.requested_model:
                raise ValueError("available intelligence requires requested and resolved model")
            if self.reason is not None:
                raise ValueError("available intelligence cannot carry a reason")
        else:
            if self.market_regime is not None or self.attention is not None:
                raise ValueError("non-available intelligence cannot carry answers")
            if not self.reason:
                raise ValueError("non-available intelligence requires a reason")

    def with_cache_status(self, status: str) -> "IntelligenceResult":
        from dataclasses import replace
        return replace(self, diagnostics=replace(self.diagnostics, cache_status=status))

    def to_public_dict(self) -> dict:
        def num(value: Decimal | None) -> str | None:
            return None if value is None else format(value, "f")

        answers = None
        if self.state is IntelligenceState.AVAILABLE:
            answers = {
                "market_regime": {
                    "choice": self.market_regime.choice,
                    "probabilities": {k: num(v) for k, v in self.market_regime.probabilities},
                    "confidence": num(self.market_regime.confidence),
                },
                "attention": {
                    "state": self.attention.state,
                    "score": num(self.attention.score),
                    "confidence": num(self.attention.confidence),
                },
            }
        diag = self.diagnostics
        return {
            "state": self.state.value,
            "reason": self.reason,
            "label": "EXPERIMENTAL",
            "canonical_identity": {
                "canonical_id": self.canonical_id,
                "economic_asset_uid": self.economic_asset_uid,
            },
            "observation_digest": self.observation_digest,
            "feature_schema_version": self.feature_schema_version,
            "question_schema_version": self.question_schema_version,
            "input_fingerprint": self.input_fingerprint,
            "answers": answers,
            "provider": PROVIDER,
            "requested_model": self.requested_model,
            "resolved_model": self.resolved_model,
            "model_match": (None if not (self.requested_model and self.resolved_model)
                            else self.requested_model == self.resolved_model),
            "evaluated_at": self.evaluated_at.isoformat() if self.evaluated_at else None,
            "provenance": {
                "as_of": self.as_of.isoformat() if self.as_of else None,
                "feature_sources": list(self.sources),
                "authority": "JEV_INTERPRETATION_NON_CANONICAL",
            },
            "diagnostics": {
                "cache_status": diag.cache_status,
                "latency_ms": num(diag.latency_ms),
                "attempt_count": diag.attempt_count,
                "provider_request_id": diag.provider_request_id,
                "usage": dict(diag.usage),
                "failure_category": diag.failure_category,
            },
            "disclosure": DISCLOSURE,
        }
