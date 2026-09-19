"""Typed immutable contracts for the post-R12 acquisition runtime.

The acquisition runtime is ORCHESTRATION, not financial/market authority.
All R0-R12 authority semantics (quote statuses, freshness, verification,
twin composition) remain owned by the frozen ``finco_radar`` packages.
This module defines:

- :class:`AcquisitionRequest` — immutable, canonically fingerprinted
  acquisition request identified by authority identity (chain + contract),
  never ticker alone.
- :class:`ProviderResult` — one provider observation with an explicit
  runtime result state, preserved verbatim evidence and source timestamps.
- :class:`AcquisitionSnapshot` — one immutable, content-addressed
  observation snapshot; the single unit all downstream reads consume.

Runtime status vocabulary (P12) means ACQUISITION/RUNTIME completeness
only.  It never redefines or overrides R0-R12 authority statuses, and a
runtime cache/TTL never turns stale source evidence into fresh evidence.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from types import MappingProxyType
from typing import Any, Mapping

SCHEMA_VERSION = "radar-runtime-acquisition-v1"
REQUEST_FINGERPRINT_PREFIX = "acq-req:"
SNAPSHOT_ID_PREFIX = "acq-snap:"

DIRECTIONS = frozenset({"BUY", "SELL"})

# A4: exact ASCII decimal-digit raw amounts only.
_RAW_AMOUNT_RE = re.compile(r"[0-9]+")

# A2: maximum canonical evidence nesting depth.
MAX_EVIDENCE_DEPTH = 64


class RadarRuntimeError(ValueError):
    """Typed acquisition-runtime error (never leaks as a raw crash)."""


class RuntimeContractError(RadarRuntimeError):
    """Malformed runtime input/output at the runtime boundary."""


class SnapshotConflictError(RadarRuntimeError):
    """The same snapshot_id was presented with different content — hard
    failure; historical snapshots are never mutated."""


class SnapshotNotFoundError(RadarRuntimeError):
    """No snapshot exists for the requested snapshot_id."""


class ProviderResultState(str, Enum):
    """Per-provider runtime result state (P12) — acquisition completeness
    only, never an R0-R12 authority status."""

    SUCCESS = "SUCCESS"
    TIMEOUT = "TIMEOUT"
    TRANSPORT_ERROR = "TRANSPORT_ERROR"
    PROVIDER_ERROR = "PROVIDER_ERROR"
    INVALID_RESPONSE = "INVALID_RESPONSE"


class AcquisitionState(str, Enum):
    """Overall snapshot state: acquisition completeness only."""

    COMPLETE = "COMPLETE"
    PARTIAL = "PARTIAL"
    UNAVAILABLE = "UNAVAILABLE"


def canonical_json_bytes(payload: Any) -> bytes:
    """Deterministic canonical JSON: UTF-8, sorted keys, compact
    separators — the only serialization used for fingerprints/ids."""
    return json.dumps(payload, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False).encode("utf-8")


def canonical_sha256(payload: Any) -> str:
    return hashlib.sha256(canonical_json_bytes(payload)).hexdigest()


def deep_freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType({k: deep_freeze(v) for k, v in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(deep_freeze(v) for v in value)
    return value


def plain(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {k: plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [plain(v) for v in value]
    return value


def _require_exact_int(value: Any, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise RuntimeContractError(
            f"{name} must be a positive exact integer, got {value!r}")
    return value


def _require_nonempty_str(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise RuntimeContractError(
            f"{name} must be a non-empty string, got {value!r}")
    return value


def _require_raw_amount(value: Any, name: str) -> "str | None":
    """A4: exact raw amount representation.  None permitted where optional;
    otherwise EXACT ASCII decimal digits only (``[0-9]+``).  No whitespace
    tolerance (never .strip()-normalized), no signs, no decimals, no
    exponents, no Unicode digit forms, no numeric types.  The accepted
    string is preserved exactly as provided."""
    if value is None:
        return None
    if not isinstance(value, str) or not _RAW_AMOUNT_RE.fullmatch(value):
        raise RuntimeContractError(
            f"{name} must be an exact ASCII decimal-digit string or None, "
            f"got {value!r}")
    return value


def ensure_canonical_evidence(value: Any, _depth: int = 0) -> None:
    """A2: the single shared contract deciding whether provider evidence
    can enter the canonical snapshot serialization.  SUCCESS evidence and
    canonical snapshot construction therefore cannot disagree.

    Accepts exactly the canonical JSON value domain: None, exact bool,
    int, finite float, str, list/tuple, Mapping with str keys.  Rejects
    sets, bytes, arbitrary objects, non-string mapping keys, unsupported
    containers, non-finite floats and excessive nesting with the stable
    internal code ``EVIDENCE_NOT_CANONICAL``.  Never stringifies or
    partially drops malformed content — the whole evidence is rejected."""
    if _depth > MAX_EVIDENCE_DEPTH:
        raise RuntimeContractError(
            "EVIDENCE_NOT_CANONICAL: nesting exceeds the canonical depth "
            "bound")
    if value is None or isinstance(value, bool) or isinstance(value, str):
        return
    if isinstance(value, int):
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            raise RuntimeContractError(
                "EVIDENCE_NOT_CANONICAL: non-finite float")
        return
    if isinstance(value, (list, tuple)):
        for item in value:
            ensure_canonical_evidence(item, _depth + 1)
        return
    if isinstance(value, Mapping):
        for key, item in value.items():
            if not isinstance(key, str):
                raise RuntimeContractError(
                    "EVIDENCE_NOT_CANONICAL: non-string mapping key")
            ensure_canonical_evidence(item, _depth + 1)
        return
    raise RuntimeContractError(
        "EVIDENCE_NOT_CANONICAL: unsupported type "
        f"{type(value).__name__}")


@dataclass(frozen=True)
class AcquisitionRequest:
    """Immutable acquisition request identified by CANONICAL AUTHORITY
    IDENTITY (chain_id + contract_address).  Ticker alone never identifies
    an acquisition; different chains/contracts are never normalized into
    the same request."""

    chain_id: int
    contract_address: str
    direction: str
    sources: "tuple[str, ...]"
    purpose: str = "observation"
    raw_amount: "str | None" = None
    notional_usd: "str | None" = None
    economic_asset_uid: "str | None" = None
    provider_config: "Mapping[str, Any] | None" = None

    def __post_init__(self) -> None:
        _require_exact_int(self.chain_id, "chain_id")
        _require_nonempty_str(self.contract_address, "contract_address")
        if self.direction not in DIRECTIONS:
            raise RuntimeContractError(
                f"direction must be one of {sorted(DIRECTIONS)}, got "
                f"{self.direction!r}")
        _require_nonempty_str(self.purpose, "purpose")
        if not isinstance(self.sources, tuple) or not self.sources:
            raise RuntimeContractError(
                "sources must be a non-empty tuple of provider names")
        for source in self.sources:
            _require_nonempty_str(source, "source")
        if len(set(self.sources)) != len(self.sources):
            raise RuntimeContractError("sources must not contain duplicates")
        _require_raw_amount(self.raw_amount, "raw_amount")
        _require_raw_amount(self.notional_usd, "notional_usd")
        if self.economic_asset_uid is not None:
            _require_nonempty_str(self.economic_asset_uid,
                                  "economic_asset_uid")
        if self.provider_config is not None:
            if not isinstance(self.provider_config, Mapping):
                raise RuntimeContractError(
                    "provider_config must be a mapping")
            object.__setattr__(
                self, "provider_config", deep_freeze(self.provider_config))
        object.__setattr__(self, "fingerprint", self._compute_fingerprint())

    def payload(self) -> dict[str, Any]:
        """Canonical immutable request payload (the fingerprint material)."""
        return {
            "schemaVersion": SCHEMA_VERSION,
            "chainId": self.chain_id,
            "contractAddress": self.contract_address,
            "direction": self.direction,
            "purpose": self.purpose,
            "sources": sorted(self.sources),
            "rawAmount": self.raw_amount,
            "notionalUsd": self.notional_usd,
            "economicAssetUid": self.economic_asset_uid,
            "providerConfig": (
                plain(self.provider_config)
                if self.provider_config is not None else None),
        }

    def _compute_fingerprint(self) -> str:
        return REQUEST_FINGERPRINT_PREFIX + canonical_sha256(self.payload())

    fingerprint: str = field(init=False, repr=False, default="")

    def __eq__(self, other: Any) -> bool:
        return isinstance(other, AcquisitionRequest) and (
            self.fingerprint == other.fingerprint)

    def __hash__(self) -> int:
        return hash(self.fingerprint)


@dataclass(frozen=True)
class ProviderResult:
    """One provider observation.  Evidence is preserved verbatim (P5) —
    the runtime never replaces provider values with requested values,
    rounds raw amounts, rewrites chain identity, or discards timestamps.
    Provider failure stays explicit."""

    provider: str
    state: ProviderResultState
    elapsed_ms: float
    evidence: "Mapping[str, Any] | None" = None
    observed_at: "str | None" = None
    error_class: "str | None" = None

    def __post_init__(self) -> None:
        _require_nonempty_str(self.provider, "provider")
        if not isinstance(self.state, ProviderResultState):
            raise RuntimeContractError(
                "state must be a ProviderResultState member")
        if not isinstance(self.elapsed_ms, (int, float)) or (
            isinstance(self.elapsed_ms, bool)
        ) or self.elapsed_ms < 0:
            raise RuntimeContractError(
                f"elapsed_ms must be a non-negative number, got "
                f"{self.elapsed_ms!r}")
        if self.evidence is not None and not isinstance(self.evidence, Mapping):
            raise RuntimeContractError("evidence must be a mapping or None")
        if self.evidence is not None:
            # A2: evidence must satisfy the shared canonical contract so
            # SUCCESS evidence and snapshot serialization cannot disagree.
            ensure_canonical_evidence(self.evidence)
        if self.observed_at is not None:
            _require_nonempty_str(self.observed_at, "observed_at")
        if self.error_class is not None:
            _require_nonempty_str(self.error_class, "error_class")
        object.__setattr__(
            self, "evidence",
            deep_freeze(self.evidence) if self.evidence is not None else None)

    def to_payload(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "state": self.state.value,
            "elapsedMs": self.elapsed_ms,
            "evidence": plain(self.evidence),
            "observedAt": self.observed_at,
            "errorClass": self.error_class,
        }


@dataclass(frozen=True)
class AcquisitionSnapshot:
    """One immutable, content-addressed observation snapshot (P4).  The
    ``snapshot_id`` is deterministically derived from the canonical
    payload; once written, the payload is never overwritten."""

    request_fingerprint: str
    request: Mapping[str, Any]
    chain_id: int
    contract_address: str
    started_at: str
    completed_at: str
    state: AcquisitionState
    providers: "tuple[ProviderResult, ...]"
    runtime_metadata: Mapping[str, Any]
    economic_asset_uid: "str | None" = None

    def __post_init__(self) -> None:
        if not isinstance(self.request, Mapping):
            raise RuntimeContractError("request must be a mapping")
        # A5: content addressing alone is not enough for the durable read
        # contract — internally related claims must agree.
        request_payload = plain(self.request)
        if request_payload.get("schemaVersion") != SCHEMA_VERSION:
            raise RuntimeContractError(
                "embedded request payload has unsupported schema version "
                f"{request_payload.get('schemaVersion')!r}")
        # A5 request fingerprint: full recomputation from the embedded
        # canonical request payload — prefix-only checks are not accepted.
        recomputed_fingerprint = REQUEST_FINGERPRINT_PREFIX + (
            canonical_sha256(request_payload))
        if self.request_fingerprint != recomputed_fingerprint:
            raise RuntimeContractError(
                "request_fingerprint does not recompute from the embedded "
                "canonical request payload")
        _require_exact_int(self.chain_id, "chain_id")
        _require_nonempty_str(self.contract_address, "contract_address")
        # A5 identity consistency (exact contract semantics).
        if self.chain_id != request_payload.get("chainId"):
            raise RuntimeContractError(
                "snapshot chain_id disagrees with the embedded request")
        if self.contract_address != request_payload.get("contractAddress"):
            raise RuntimeContractError(
                "snapshot contract_address disagrees with the embedded "
                "request")
        if self.economic_asset_uid != request_payload.get("economicAssetUid"):
            raise RuntimeContractError(
                "snapshot economic_asset_uid disagrees with the embedded "
                "request")
        for name in ("started_at", "completed_at"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise RuntimeContractError(
                    f"{name} must be an ISO timestamp string")
            try:
                parsed = datetime.fromisoformat(value)
            except (ValueError, TypeError) as exc:
                raise RuntimeContractError(
                    f"{name} is not a parsable ISO timestamp") from exc
            if parsed.tzinfo is None:
                raise RuntimeContractError(f"{name} must be timezone-aware")
        if not isinstance(self.state, AcquisitionState):
            raise RuntimeContractError(
                "state must be an AcquisitionState member")
        if not isinstance(self.providers, tuple):
            raise RuntimeContractError("providers must be a tuple")
        for result in self.providers:
            if not isinstance(result, ProviderResult):
                raise RuntimeContractError(
                    "providers members must be ProviderResult instances")
        # A5 provider-set consistency: results correspond EXACTLY to the
        # requested providers — none missing, none duplicated, none
        # invented — in the payload's canonical (sorted) order.
        sources = request_payload.get("sources")
        if not isinstance(sources, list):
            raise RuntimeContractError(
                "embedded request payload sources must be a list")
        names = [result.provider for result in self.providers]
        if len(set(names)) != len(names):
            raise RuntimeContractError(
                "provider results must not contain duplicates")
        if sorted(names) != sorted(sources):
            raise RuntimeContractError(
                "provider results must correspond exactly to the requested "
                "provider set")
        if names != sorted(names):
            raise RuntimeContractError(
                "provider results must be in canonical (sorted) order")
        # A5 overall-state consistency: the serialized acquisition state
        # must equal the state recomputed from the provider results.
        successful = sum(
            1 for result in self.providers
            if result.state is ProviderResultState.SUCCESS)
        if successful == len(self.providers) and successful > 0:
            expected_state = AcquisitionState.COMPLETE
        elif successful > 0:
            expected_state = AcquisitionState.PARTIAL
        else:
            expected_state = AcquisitionState.UNAVAILABLE
        if self.state is not expected_state:
            raise RuntimeContractError(
                f"snapshot state {self.state.value!r} disagrees with the "
                f"recomputed acquisition state {expected_state.value!r}")
        if not isinstance(self.runtime_metadata, Mapping):
            raise RuntimeContractError("runtime_metadata must be a mapping")
        object.__setattr__(self, "request", deep_freeze(self.request))
        object.__setattr__(
            self, "runtime_metadata", deep_freeze(self.runtime_metadata))
        object.__setattr__(self, "snapshot_id", self._compute_snapshot_id())

    snapshot_id: str = field(init=False, repr=False, default="")

    def to_payload(self) -> dict[str, Any]:
        """Canonical immutable snapshot payload (the snapshot_id material).
        Does NOT include snapshot_id itself."""
        return {
            "schemaVersion": SCHEMA_VERSION,
            "requestFingerprint": self.request_fingerprint,
            "request": plain(self.request),
            "chainId": self.chain_id,
            "contractAddress": self.contract_address,
            "economicAssetUid": self.economic_asset_uid,
            "startedAt": self.started_at,
            "completedAt": self.completed_at,
            "state": self.state.value,
            "providers": [p.to_payload() for p in self.providers],
            "runtime": plain(self.runtime_metadata),
        }

    def _compute_snapshot_id(self) -> str:
        return SNAPSHOT_ID_PREFIX + canonical_sha256(self.to_payload())

    def __eq__(self, other: Any) -> bool:
        return isinstance(other, AcquisitionSnapshot) and (
            self.snapshot_id == other.snapshot_id)

    def __hash__(self) -> int:
        return hash(self.snapshot_id)

    @classmethod
    def from_payload(cls, payload: Any) -> "AcquisitionSnapshot":
        """Rebuild a snapshot from a persisted canonical payload,
        fail-closed against schema drift (P14: pure read, zero network)."""
        if not isinstance(payload, Mapping):
            raise RuntimeContractError("snapshot payload must be a mapping")
        if payload.get("schemaVersion") != SCHEMA_VERSION:
            raise RuntimeContractError(
                f"unsupported snapshot schema "
                f"{payload.get('schemaVersion')!r}")
        providers_raw = payload.get("providers")
        if not isinstance(providers_raw, list):
            raise RuntimeContractError("providers payload must be a list")
        providers = []
        for item in providers_raw:
            if not isinstance(item, Mapping):
                raise RuntimeContractError(
                    "provider payload member must be a mapping")
            providers.append(ProviderResult(
                provider=item.get("provider"),
                state=ProviderResultState(item.get("state")),
                elapsed_ms=item.get("elapsedMs"),
                evidence=item.get("evidence"),
                observed_at=item.get("observedAt"),
                error_class=item.get("errorClass"),
            ))
        state_raw = payload.get("state")
        if state_raw not in {s.value for s in AcquisitionState}:
            raise RuntimeContractError(
                f"invalid snapshot state {state_raw!r}")
        request_payload = payload.get("request")
        if not isinstance(request_payload, Mapping):
            raise RuntimeContractError("request payload must be a mapping")
        runtime_payload = payload.get("runtime")
        if not isinstance(runtime_payload, Mapping):
            raise RuntimeContractError("runtime payload must be a mapping")
        return cls(
            request_fingerprint=payload.get("requestFingerprint"),
            request=MappingProxyType(dict(request_payload)),
            chain_id=payload.get("chainId"),
            contract_address=payload.get("contractAddress"),
            started_at=payload.get("startedAt"),
            completed_at=payload.get("completedAt"),
            state=AcquisitionState(state_raw),
            providers=tuple(providers),
            runtime_metadata=MappingProxyType(dict(runtime_payload)),
            economic_asset_uid=payload.get("economicAssetUid"),
        )
