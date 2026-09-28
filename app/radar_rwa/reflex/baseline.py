"""Frozen pre-period probabilistic control for the RWA Reflex experiment."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Mapping

from finco_radar.authority.contracts import AuthorityState

from .contracts import RwaReflexState
from .features import build_parity_feature_state, feature_cell_key


BASELINE_SCHEMA_VERSION = "RWA_REFLEX_TRANSIENT_BASELINE_V2"
INFORMATION_PARITY_MARKER = "RWA_REFLEX_JEV_BASELINE_INFORMATION_PARITY"


@dataclass(frozen=True)
class EmpiricalTransientBaselineConfig:
    """Pre-period empirical rates; callers must freeze this before a sample begins.

    ``cell_counts`` maps the exact blinded feature-cell key to
    ``(transient_count, total_count)``. Sparse cells shrink toward the frozen
    global pre-period rate; no post-t0 outcomes may update this config in-place.
    """

    training_cutoff: datetime | None = None
    training_source: str = "UNCONFIGURED"
    cell_counts: Mapping[str, tuple[int, int]] = field(default_factory=dict)
    global_transient_count: int = 0
    global_total_count: int = 0
    minimum_global_observations: int = 20
    minimum_cell_observations: int = 5
    shrinkage_strength: Decimal = Decimal("10")

    def __post_init__(self) -> None:
        if self.training_cutoff is not None and (
            self.training_cutoff.tzinfo is None or self.training_cutoff.utcoffset() is None
        ):
            raise ValueError("training_cutoff must be timezone-aware")
        if not self.training_source.strip():
            raise ValueError("training_source is required")
        if min(self.global_transient_count, self.global_total_count, self.minimum_global_observations,
               self.minimum_cell_observations) < 0:
            raise ValueError("baseline counts must be nonnegative")
        if self.global_transient_count > self.global_total_count:
            raise ValueError("global transient count cannot exceed total")
        if not self.shrinkage_strength.is_finite() or self.shrinkage_strength < 0:
            raise ValueError("shrinkage_strength must be finite and nonnegative")
        for key, counts in self.cell_counts.items():
            if not isinstance(key, str) or not key.strip() or len(counts) != 2:
                raise ValueError("baseline cells require named keys and (success,total)")
            successes, total = counts
            if min(successes, total) < 0 or successes > total:
                raise ValueError("invalid baseline cell counts")


def evaluate_transient_baseline(
    state: RwaReflexState,
    *,
    config: EmpiricalTransientBaselineConfig,
) -> dict[str, object]:
    """Return P(transient) using exactly the same blinded information as Jev."""
    if state.state is not AuthorityState.AVAILABLE:
        return {
            "schema_version": BASELINE_SCHEMA_VERSION,
            "state": "UNAVAILABLE",
            "reason": state.reason or "REFLEX_STATE_NOT_AVAILABLE",
            "transient_probability": None,
            "information_parity": INFORMATION_PARITY_MARKER,
        }
    if config.training_cutoff is None or config.global_total_count < config.minimum_global_observations:
        return {
            "schema_version": BASELINE_SCHEMA_VERSION,
            "state": "UNAVAILABLE",
            "reason": "FROZEN_PREPERIOD_BASELINE_INSUFFICIENT",
            "transient_probability": None,
            "information_parity": INFORMATION_PARITY_MARKER,
        }
    if state.observed_at is not None and config.training_cutoff >= state.observed_at:
        raise ValueError("baseline training cutoff must precede prediction")

    features = build_parity_feature_state(state)
    cell = feature_cell_key(features)
    successes, total = config.cell_counts.get(cell, (0, 0))
    global_rate = Decimal(config.global_transient_count) / Decimal(config.global_total_count)
    if total >= config.minimum_cell_observations:
        numerator = Decimal(successes) + config.shrinkage_strength * global_rate
        denominator = Decimal(total) + config.shrinkage_strength
        probability = numerator / denominator if denominator else global_rate
        mode = "CELL_SHRUNK_TO_GLOBAL"
    else:
        probability = global_rate
        mode = "GLOBAL_FALLBACK"

    return {
        "schema_version": BASELINE_SCHEMA_VERSION,
        "state": "AVAILABLE",
        "reason": None,
        "transient_probability": str(probability),
        "feature_state": features,
        "cell_key": cell,
        "cell_transient_count": successes,
        "cell_total_count": total,
        "global_transient_count": config.global_transient_count,
        "global_total_count": config.global_total_count,
        "training_cutoff": config.training_cutoff.isoformat(),
        "training_source": config.training_source,
        "mode": mode,
        "information_parity": INFORMATION_PARITY_MARKER,
    }
