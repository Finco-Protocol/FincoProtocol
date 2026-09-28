"""Feature-gated Jev boundary for one blinded probabilistic RWA forecast."""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Mapping, Protocol

from finco_radar.authority.contracts import AuthorityState

from .contracts import RwaReflexState
from .features import OUTBOUND_FIELD_ALLOWLIST, build_parity_feature_state
from .interpretation import InterpretationState, ReflexInterpretation, normalized_usage


JEV_REQUEST_SCHEMA_VERSION = "RWA_REFLEX_JEV_REQUEST_V2"
OUTCOME_POLICY_VERSION = "RWA_REFLEX_OUTCOME_POLICY_V2"


class JevTransport(Protocol):
    def evaluate(self, request: Mapping[str, object]) -> Mapping[str, object]: ...


@dataclass(frozen=True)
class JevReflexConfig:
    enabled: bool = False
    provider: str = "TYPESAFE_JEV"
    model: str = "jev-latest"

    def __post_init__(self) -> None:
        if not self.provider.strip() or not self.model.strip():
            raise ValueError("provider and model must be non-empty")


def _number(value: Decimal | None) -> str | None:
    return str(value) if value is not None else None


def _time(value) -> str | None:
    return value.isoformat() if value is not None else None


def _evidence_payload(state: RwaReflexState) -> dict[str, object]:
    """Local reconstruction material. Never sent to TypeSafe."""
    provenance = state.provenance
    return {
        "schema_version": state.schema_version,
        "economic_asset_uid": state.economic_asset_uid,
        "canonical_token": state.canonical_token.canonical_id,
        "authority_state": state.state.value,
        "market_session": state.market_session.value,
        "underlying_reference_usd": _number(state.underlying_reference_usd),
        "token_reference_usd": _number(state.token_reference_usd),
        "reference_premium_bps": _number(state.reference_premium_bps),
        "execution_impact_bps": _number(state.execution_impact_bps),
        "effective_gap_bps": _number(state.effective_gap_bps),
        "basis_z_score": _number(state.basis_z_score),
        "structural_premium_bps": _number(state.structural_premium_bps),
        "premium_deviation_bps": _number(state.premium_deviation_bps),
        "liquidity_usd": _number(state.liquidity_usd),
        "depth_1pct_usd": _number(state.depth_1pct_usd),
        "observed_at": _time(state.observed_at),
        "evidence_sources": list(state.evidence_sources),
        "context_warnings": list(state.context_warnings),
        "provenance": None if provenance is None else {
            "registry_source": provenance.registry_source,
            "registry_observed_at": _time(provenance.registry_observed_at),
            "history_source": provenance.history_source,
            "history_observed_at": _time(provenance.history_observed_at),
            "history_window": provenance.history_window,
            "history_sample_count": provenance.history_sample_count,
            "history_mean_bps": _number(provenance.history_mean_bps),
            "history_std_bps": _number(provenance.history_std_bps),
            "history_median_bps": _number(provenance.history_median_bps),
            "history_methodology_version": provenance.history_methodology_version,
            "liquidity_source": provenance.liquidity_source,
            "liquidity_observed_at": _time(provenance.liquidity_observed_at),
            "liquidity_methodology_version": provenance.liquidity_methodology_version,
            "liquidity_venue_id": provenance.liquidity_venue_id,
            "session_source": provenance.session_source,
            "session_resolver_version": provenance.session_resolver_version,
            "context_builder_version": provenance.context_builder_version,
        },
    }


def reflex_input_fingerprint(state: RwaReflexState) -> str:
    canonical = json.dumps(_evidence_payload(state), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def build_jev_request(
    state: RwaReflexState,
    *,
    config: JevReflexConfig = JevReflexConfig(),
) -> dict[str, object]:
    """Build a blinded System One request aligned exactly to OUTCOME_POLICY_V2."""
    if state.state is not AuthorityState.AVAILABLE:
        raise ValueError("Jev request requires AVAILABLE Reflex state")
    features = build_parity_feature_state(state)
    if set(features) != OUTBOUND_FIELD_ALLOWLIST:
        raise AssertionError("RWA_REFLEX_OUTBOUND_ALLOWLIST_VIOLATION")
    fingerprint = reflex_input_fingerprint(state)
    return {
        "state": {
            "request_schema_version": JEV_REQUEST_SCHEMA_VERSION,
            "outcome_policy_version": OUTCOME_POLICY_VERSION,
            "input_fingerprint": fingerprint,
            "features": features,
        },
        "model": config.model,
        "questions": {
            "likely_transient": {
                "type": "noul",
                "instructions": (
                    "Estimate the probability that this eligible regular-session dislocation event "
                    "will be TRANSIENT under RWA_REFLEX_OUTCOME_POLICY_V2: at the first eligible "
                    "canonical AVAILABLE observation around 60 regular-session minutes after event "
                    "start, the absolute premium deviation from the frozen pre-event structural "
                    "premium level is at most 50% of its initial absolute deviation. Use only the "
                    "supplied blinded feature buckets. Do not infer asset identity, recalculate "
                    "prices/premium, or produce investment advice."
                ),
                "criteria": {
                    "true": "The future OUTCOME_POLICY_V2 TRANSIENT event is more likely.",
                    "false": "The future OUTCOME_POLICY_V2 TRANSIENT event is not more likely.",
                },
            },
        },
    }


def _decimal(value: object, name: str) -> Decimal:
    if isinstance(value, bool):
        raise ValueError(f"{name} must be numeric")
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        raise ValueError(f"{name} must be numeric") from None
    if not parsed.is_finite():
        raise ValueError(f"{name} must be finite")
    return parsed


def _probability(value: object, name: str) -> Decimal:
    parsed = _decimal(value, name)
    if not Decimal("0") <= parsed <= Decimal("1"):
        raise ValueError(f"{name} must be between 0 and 1")
    return parsed


def _invalid(fingerprint: str, config: JevReflexConfig, reason: str) -> ReflexInterpretation:
    return ReflexInterpretation(
        state=InterpretationState.INVALID_RESPONSE,
        input_fingerprint=fingerprint,
        request_schema_version=JEV_REQUEST_SCHEMA_VERSION,
        provider=config.provider,
        requested_model=config.model,
        reason=reason,
    )


def _parse_response(
    response: Mapping[str, object], *, fingerprint: str, config: JevReflexConfig,
) -> ReflexInterpretation:
    model = response.get("model")
    answers = response.get("answers")
    if not isinstance(model, str) or not model.strip() or not isinstance(answers, Mapping):
        raise ValueError("JEV_RESPONSE_SHAPE_INVALID")
    if set(answers) != {"likely_transient"}:
        raise ValueError("JEV_UNEXPECTED_QUESTION_OUTPUT")
    answer = answers.get("likely_transient")
    if not isinstance(answer, Mapping) or answer.get("type") != "noul":
        raise ValueError("JEV_LIKELY_TRANSIENT_ANSWER_INVALID")

    meta = response.get("_transport_meta")
    meta = meta if isinstance(meta, Mapping) else {}
    latency_raw = meta.get("latency_ms")
    attempts_raw = meta.get("attempt_count")
    request_id = response.get("id") or response.get("request_id")
    if request_id is not None and not isinstance(request_id, str):
        request_id = None
    latency = None if latency_raw is None else _decimal(latency_raw, "transport latency")
    attempts = None
    if attempts_raw is not None:
        if isinstance(attempts_raw, bool):
            raise ValueError("JEV_ATTEMPT_COUNT_INVALID")
        attempts = int(attempts_raw)
        if attempts < 1:
            raise ValueError("JEV_ATTEMPT_COUNT_INVALID")

    return ReflexInterpretation(
        state=InterpretationState.AVAILABLE,
        input_fingerprint=fingerprint,
        request_schema_version=JEV_REQUEST_SCHEMA_VERSION,
        likely_transient_probability=_probability(answer.get("noul"), "transient probability"),
        provider=config.provider,
        requested_model=config.model,
        resolved_model=model,
        provider_request_id=request_id,
        latency_ms=latency,
        attempt_count=attempts,
        usage=normalized_usage(response.get("usage")),
    )


def interpret_reflex_with_jev(
    state: RwaReflexState,
    transport: JevTransport,
    *,
    config: JevReflexConfig = JevReflexConfig(),
) -> ReflexInterpretation:
    fingerprint = reflex_input_fingerprint(state)
    if not config.enabled:
        return ReflexInterpretation(
            state=InterpretationState.DISABLED,
            input_fingerprint=fingerprint,
            provider=config.provider,
            requested_model=config.model,
            reason="JEV_REFLEX_DISABLED",
        )
    if state.state is not AuthorityState.AVAILABLE:
        return ReflexInterpretation(
            state=InterpretationState.UNAVAILABLE,
            input_fingerprint=fingerprint,
            request_schema_version=JEV_REQUEST_SCHEMA_VERSION,
            provider=config.provider,
            requested_model=config.model,
            reason="REFLEX_STATE_NOT_AVAILABLE",
        )
    request = build_jev_request(state, config=config)
    try:
        response = transport.evaluate(request)
    except Exception:
        return ReflexInterpretation(
            state=InterpretationState.UNAVAILABLE,
            input_fingerprint=fingerprint,
            request_schema_version=JEV_REQUEST_SCHEMA_VERSION,
            provider=config.provider,
            requested_model=config.model,
            reason="JEV_TRANSPORT_UNAVAILABLE",
        )
    if not isinstance(response, Mapping):
        return _invalid(fingerprint, config, "JEV_RESPONSE_NOT_MAPPING")
    try:
        return _parse_response(response, fingerprint=fingerprint, config=config)
    except (ValueError, TypeError) as exc:
        return _invalid(fingerprint, config, str(exc) or "JEV_RESPONSE_INVALID")
