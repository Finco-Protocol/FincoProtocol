"""Typed output contract for the experimental Jev transient forecast."""
from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal
from enum import Enum
from typing import Mapping


INTERPRETATION_SCHEMA_VERSION = "RWA_REFLEX_INTERPRETATION_V2"
_FINGERPRINT_RE = re.compile(r"^[0-9a-f]{64}$")
JEV_FAILURE_CATEGORIES = frozenset({
    "TIMEOUT", "NETWORK", "HTTP_408", "HTTP_429", "HTTP_5XX", "AUTH",
    "INVALID_REQUEST", "INVALID_RESPONSE", "RETRY_BUDGET_EXHAUSTED",
})


class InterpretationState(str, Enum):
    AVAILABLE = "AVAILABLE"
    DISABLED = "DISABLED"
    UNAVAILABLE = "UNAVAILABLE"
    INVALID_RESPONSE = "INVALID_RESPONSE"


def _probability(value: Decimal | None, name: str) -> None:
    if value is None:
        return
    if not value.is_finite() or not Decimal("0") <= value <= Decimal("1"):
        raise ValueError(f"{name} must be finite and between 0 and 1")


@dataclass(frozen=True)
class ReflexInterpretation:
    state: InterpretationState
    input_fingerprint: str
    request_schema_version: str | None = None
    likely_transient_probability: Decimal | None = None
    provider: str | None = None
    requested_model: str | None = None
    resolved_model: str | None = None
    provider_request_id: str | None = None
    latency_ms: Decimal | None = None
    attempt_count: int | None = None
    usage: tuple[tuple[str, str], ...] = ()
    reason: str | None = None
    failure_category: str | None = None
    schema_version: str = INTERPRETATION_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != INTERPRETATION_SCHEMA_VERSION:
            raise ValueError("unsupported Reflex interpretation schema version")
        if not _FINGERPRINT_RE.fullmatch(self.input_fingerprint):
            raise ValueError("input_fingerprint must be a lowercase sha256 hex digest")
        if self.request_schema_version is not None and not self.request_schema_version.strip():
            raise ValueError("request_schema_version must be named when present")
        _probability(self.likely_transient_probability, "likely_transient_probability")
        if self.latency_ms is not None and (not self.latency_ms.is_finite() or self.latency_ms < 0):
            raise ValueError("latency_ms must be finite and nonnegative")
        if self.attempt_count is not None and (isinstance(self.attempt_count, bool) or self.attempt_count < 1):
            raise ValueError("attempt_count must be a positive integer")
        if any(not key.strip() for key, _ in self.usage):
            raise ValueError("usage metadata keys must be named")
        if self.failure_category is not None and self.failure_category not in JEV_FAILURE_CATEGORIES:
            raise ValueError("unsupported Jev failure category")

        if self.state is InterpretationState.AVAILABLE:
            if self.request_schema_version is None:
                raise ValueError("available interpretation requires request schema provenance")
            if self.likely_transient_probability is None:
                raise ValueError("available interpretation requires transient probability")
            if self.provider is None or not self.provider.strip():
                raise ValueError("available interpretation requires provider")
            if self.requested_model is None or not self.requested_model.strip():
                raise ValueError("available interpretation requires requested model")
            if self.resolved_model is None or not self.resolved_model.strip():
                raise ValueError("available interpretation requires resolved model")
            if self.reason is not None or self.failure_category is not None:
                raise ValueError("available interpretation cannot carry failure metadata")
        else:
            if self.likely_transient_probability is not None:
                raise ValueError("non-available interpretation cannot carry forecast probability")
            if self.reason is None or not self.reason.strip():
                raise ValueError("non-available interpretation requires reason")


def normalized_usage(value: object) -> tuple[tuple[str, str], ...]:
    """Persist provider usage as a closed scalar map; never preserve arbitrary bodies."""
    if not isinstance(value, Mapping):
        return ()
    rows: list[tuple[str, str]] = []
    for key in sorted(value):
        item = value[key]
        if isinstance(key, str) and key.strip() and isinstance(item, (str, int, float)) and not isinstance(item, bool):
            rows.append((key, str(item)))
    return tuple(rows)
