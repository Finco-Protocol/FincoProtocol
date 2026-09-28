"""Versioned outcome labels and probabilistic scoring for RWA Reflex."""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal


EVALUATION_SCHEMA_VERSION = "RWA_REFLEX_EVALUATION_V2"
OUTCOME_POLICY_VERSION = "RWA_REFLEX_OUTCOME_POLICY_V2"


@dataclass(frozen=True)
class ReflexOutcomePolicy:
    target_horizon_seconds: int = 3600
    finalization_window_seconds: int = 300
    compression_ratio_threshold: Decimal = Decimal("0.50")
    minimum_initial_deviation_bps: Decimal = Decimal("100")
    probability_clip: Decimal = Decimal("0.000001")

    def __post_init__(self) -> None:
        if self.target_horizon_seconds <= 0 or self.finalization_window_seconds < 0:
            raise ValueError("outcome horizon must be positive with nonnegative finalization window")
        if not Decimal("0") < self.compression_ratio_threshold <= Decimal("1"):
            raise ValueError("compression ratio threshold must be in (0,1]")
        if not self.minimum_initial_deviation_bps.is_finite() or self.minimum_initial_deviation_bps <= 0:
            raise ValueError("minimum initial deviation must be positive and finite")
        if not Decimal("0") < self.probability_clip < Decimal("0.5"):
            raise ValueError("probability_clip must be in (0,0.5)")


def _decimal(value: object, name: str) -> Decimal:
    try:
        result = Decimal(str(value))
    except Exception as exc:
        raise ValueError(f"{name} must be decimal-like") from exc
    if not result.is_finite():
        raise ValueError(f"{name} must be finite")
    return result


def _probability(value: object, name: str) -> Decimal:
    result = _decimal(value, name)
    if not Decimal("0") <= result <= Decimal("1"):
        raise ValueError(f"{name} must be between 0 and 1")
    return result


def _score(probability: Decimal | None, actual: Decimal, clip: Decimal) -> tuple[str | None, float | None, str | None]:
    if probability is None:
        return None, None, None
    brier = (probability - actual) ** 2
    clipped = min(max(probability, clip), Decimal("1") - clip)
    p = float(clipped)
    y = float(actual)
    loss = -(y * math.log(p) + (1.0 - y) * math.log(1.0 - p))
    bucket = f"{int(float(probability) * 10) * 10:02d}-{min(100, int(float(probability) * 10) * 10 + 10):02d}%"
    return str(brier), loss, bucket


def _no_label(reason: str, horizon: object, policy: ReflexOutcomePolicy) -> dict[str, object]:
    return {
        "schema_version": EVALUATION_SCHEMA_VERSION,
        "outcome_policy_version": OUTCOME_POLICY_VERSION,
        "label": "NO_LABEL",
        "label_reason": reason,
        "horizon_seconds": horizon,
        "policy": _policy_payload(policy),
        "jev_likely_transient_probability": None,
        "baseline_transient_probability": None,
        "jev_brier": None,
        "jev_log_loss": None,
        "baseline_brier": None,
        "baseline_log_loss": None,
    }


def _policy_payload(policy: ReflexOutcomePolicy) -> dict[str, object]:
    return {
        "target_horizon_seconds": policy.target_horizon_seconds,
        "finalization_window_seconds": policy.finalization_window_seconds,
        "canonical_selector": "FIRST_AVAILABLE_AT_OR_AFTER_TARGET",
        "compression_ratio_threshold": str(policy.compression_ratio_threshold),
        "minimum_initial_deviation_bps": str(policy.minimum_initial_deviation_bps),
        "probability_clip": str(policy.probability_clip),
        "regular_session_only": True,
        "structural_level": "FROZEN_PRE_T0_TRAILING_5_REGULAR_SESSION_MEDIAN",
    }


def evaluate_recorded_outcome(
    prediction: dict[str, object],
    outcome: dict[str, object],
    *,
    policy: ReflexOutcomePolicy = ReflexOutcomePolicy(),
) -> dict[str, object]:
    """Score only the immutable canonical OUTCOME_POLICY_V2 finalization."""
    horizon = outcome.get("horizon_seconds")
    if outcome.get("canonical_finalization") is not True:
        return _no_label("OUTCOME_NOT_CANONICALLY_FINALIZED", horizon, policy)
    if outcome.get("outcome_policy_version") != OUTCOME_POLICY_VERSION:
        return _no_label("OUTCOME_POLICY_VERSION_MISMATCH", horizon, policy)
    if outcome.get("canonical_outcome_state") != "AVAILABLE":
        reason = outcome.get("canonical_reason")
        return _no_label(str(reason or "OUTCOME_ELIGIBLE_OBSERVATION_MISSING"), horizon, policy)
    if outcome.get("identity_conflict") is True:
        return _no_label("OUTCOME_IDENTITY_LINEAGE_CONFLICT", horizon, policy)

    event = prediction.get("event")
    interpretation = prediction.get("interpretation")
    baseline = prediction.get("baseline")
    if not isinstance(event, dict) or not isinstance(interpretation, dict) or not isinstance(baseline, dict):
        return _no_label("PREDICTION_EVENT_OR_CONTROL_MISSING", horizon, policy)
    if event.get("session") != "OPEN":
        return _no_label("PREDICTION_NOT_REGULAR_SESSION", horizon, policy)
    if outcome.get("market_session") != "OPEN":
        return _no_label("OUTCOME_SESSION_BOUNDARY", horizon, policy)
    if outcome.get("authority_state") != "AVAILABLE":
        return _no_label("OUTCOME_CANONICAL_NOT_AVAILABLE", horizon, policy)

    if not isinstance(horizon, int) or isinstance(horizon, bool) or horizon <= 0:
        return _no_label("OUTCOME_HORIZON_INVALID", horizon, policy)
    lower = policy.target_horizon_seconds
    upper = policy.target_horizon_seconds + policy.finalization_window_seconds
    if not lower <= horizon <= upper:
        return _no_label("OUTCOME_OUTSIDE_HORIZON_WINDOW", horizon, policy)

    close_raw = event.get("session_close_at")
    observed_raw = outcome.get("observed_at")
    if isinstance(close_raw, str) and isinstance(observed_raw, str):
        try:
            close_at = datetime.fromisoformat(close_raw)
            observed_at = datetime.fromisoformat(observed_raw)
            if observed_at > close_at:
                return _no_label("OUTCOME_SESSION_BOUNDARY", horizon, policy)
        except ValueError:
            return _no_label("OUTCOME_SESSION_EVIDENCE_INVALID", horizon, policy)

    structural_raw = event.get("structural_premium_bps")
    initial_dev_raw = event.get("initial_deviation_bps")
    premium_raw = outcome.get("reference_premium_bps")
    if structural_raw is None or initial_dev_raw is None or premium_raw is None:
        return _no_label("OUTCOME_PREMIUM_EVIDENCE_MISSING", horizon, policy)
    structural = _decimal(structural_raw, "structural premium")
    initial_deviation = _decimal(initial_dev_raw, "initial deviation")
    if abs(initial_deviation) < policy.minimum_initial_deviation_bps:
        return _no_label("INITIAL_DEVIATION_BELOW_EVENT_THRESHOLD", horizon, policy)
    outcome_premium = _decimal(premium_raw, "outcome premium")
    outcome_deviation = outcome_premium - structural
    compression_ratio = abs(outcome_deviation) / abs(initial_deviation)
    transient = compression_ratio <= policy.compression_ratio_threshold
    actual = Decimal("1") if transient else Decimal("0")

    jev_raw = interpretation.get("likely_transient_probability")
    jev_probability = None if jev_raw is None else _probability(jev_raw, "Jev transient probability")
    base_raw = baseline.get("transient_probability") if baseline.get("state") == "AVAILABLE" else None
    baseline_probability = None if base_raw is None else _probability(base_raw, "baseline transient probability")
    jev_brier, jev_loss, jev_bucket = _score(jev_probability, actual, policy.probability_clip)
    base_brier, base_loss, base_bucket = _score(baseline_probability, actual, policy.probability_clip)

    return {
        "schema_version": EVALUATION_SCHEMA_VERSION,
        "outcome_policy_version": OUTCOME_POLICY_VERSION,
        "label": "TRANSIENT" if transient else "NOT_TRANSIENT",
        "label_reason": "ABS_DEVIATION_COMPRESSED_BY_AT_LEAST_50_PERCENT" if transient else "ABS_DEVIATION_NOT_SUFFICIENTLY_COMPRESSED",
        "horizon_seconds": horizon,
        "structural_premium_bps": str(structural),
        "initial_deviation_bps": str(initial_deviation),
        "outcome_deviation_bps": str(outcome_deviation),
        "compression_ratio": str(compression_ratio),
        "policy": _policy_payload(policy),
        "jev_likely_transient_probability": None if jev_probability is None else str(jev_probability),
        "baseline_transient_probability": None if baseline_probability is None else str(baseline_probability),
        "jev_brier": jev_brier,
        "jev_log_loss": jev_loss,
        "jev_reliability_bucket": jev_bucket,
        "baseline_brier": base_brier,
        "baseline_log_loss": base_loss,
        "baseline_reliability_bucket": base_bucket,
    }
