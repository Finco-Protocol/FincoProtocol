"""Internal-only experiment harness for FINCO RWA Reflex."""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from finco_radar.authority.contracts import AuthoritySnapshot

from .baseline import EmpiricalTransientBaselineConfig, evaluate_transient_baseline
from .contracts import RwaReflexContext, RwaReflexState
from .interpretation import InterpretationState, ReflexInterpretation
from .jev import JEV_REQUEST_SCHEMA_VERSION, JevReflexConfig, JevTransport, interpret_reflex_with_jev, reflex_input_fingerprint
from .state import build_reflex_state


EXPERIMENT_SCHEMA_VERSION = "RWA_REFLEX_EXPERIMENT_V2"
AUTHORITY_BOUNDARY = "FINCO_CANONICAL_AUTHORITY_ONLY"


def _number(value: Decimal | None) -> str | None:
    return str(value) if value is not None else None


def _time(value) -> str | None:
    return value.isoformat() if value is not None else None


def serialize_reflex_state(state: RwaReflexState) -> dict[str, object]:
    provenance = state.provenance
    return {
        "schema_version": state.schema_version,
        "state": state.state.value,
        "reason": state.reason,
        "economic_asset_uid": state.economic_asset_uid,
        "canonical_token": {
            "chain_id": state.canonical_token.chain_id,
            "contract_address": state.canonical_token.contract_address,
            "canonical_id": state.canonical_token.canonical_id,
        },
        "market_session": state.market_session.value,
        "underlying_reference_usd": _number(state.underlying_reference_usd),
        "token_reference_usd": _number(state.token_reference_usd),
        "reference_premium_bps": _number(state.reference_premium_bps),
        "structural_premium_bps": _number(state.structural_premium_bps),
        "premium_deviation_bps": _number(state.premium_deviation_bps),
        "execution_impact_bps": _number(state.execution_impact_bps),
        "effective_gap_bps": _number(state.effective_gap_bps),
        "basis_z_score": _number(state.basis_z_score),
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
            "regular_session_date": provenance.regular_session_date,
            "regular_session_open_at": _time(provenance.regular_session_open_at),
            "regular_session_close_at": _time(provenance.regular_session_close_at),
            "context_builder_version": provenance.context_builder_version,
        },
    }


def serialize_reflex_interpretation(result: ReflexInterpretation) -> dict[str, object]:
    return {
        "schema_version": result.schema_version,
        "state": result.state.value,
        "input_fingerprint": result.input_fingerprint,
        "request_schema_version": result.request_schema_version,
        "likely_transient_probability": _number(result.likely_transient_probability),
        "provider": result.provider,
        "requested_model": result.requested_model,
        "resolved_model": result.resolved_model,
        "provider_request_id": result.provider_request_id,
        "latency_ms": _number(result.latency_ms),
        "attempt_count": result.attempt_count,
        "usage": dict(result.usage),
        "reason": result.reason,
        "failure_category": result.failure_category,
    }


class ReflexExperimentService:
    def __init__(
        self,
        *,
        jev_transport: JevTransport | None = None,
        jev_config: JevReflexConfig = JevReflexConfig(),
        baseline_config: EmpiricalTransientBaselineConfig = EmpiricalTransientBaselineConfig(),
    ) -> None:
        self.jev_transport = jev_transport
        self.jev_config = jev_config
        self.baseline_config = baseline_config

    def evaluate(
        self,
        authority: AuthoritySnapshot,
        *,
        as_of: datetime,
        context: RwaReflexContext | None = None,
        max_context_age_seconds: int = 300,
    ) -> dict[str, object]:
        state = build_reflex_state(
            authority,
            as_of=as_of,
            context=context,
            max_context_age_seconds=max_context_age_seconds,
        )
        baseline = evaluate_transient_baseline(state, config=self.baseline_config)
        if self.jev_transport is None:
            enabled = self.jev_config.enabled
            interpretation = ReflexInterpretation(
                state=(InterpretationState.UNAVAILABLE if enabled else InterpretationState.DISABLED),
                input_fingerprint=reflex_input_fingerprint(state),
                request_schema_version=(JEV_REQUEST_SCHEMA_VERSION if enabled else None),
                provider=self.jev_config.provider,
                requested_model=self.jev_config.model,
                reason=("JEV_TRANSPORT_NOT_CONFIGURED" if enabled else "JEV_REFLEX_DISABLED"),
                failure_category=("NETWORK" if enabled else None),
            )
        else:
            interpretation = interpret_reflex_with_jev(state, self.jev_transport, config=self.jev_config)

        return {
            "schema_version": EXPERIMENT_SCHEMA_VERSION,
            "experimental": True,
            "authority_boundary": AUTHORITY_BOUNDARY,
            "reflex_state": serialize_reflex_state(state),
            "baseline": baseline,
            "interpretation": serialize_reflex_interpretation(interpretation),
        }
