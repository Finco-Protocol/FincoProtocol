"""R10 comparability resolution and model-vs-market comparisons.

Decimal-only comparison arithmetic.  Frozen model functions may return
float: their values enter R10 through decimal_from_authority() (canonical
textual representation) and never through Decimal(binary_float).

Signed semantics are descriptive: positive bps means the market observation
is above the model value basis, for BOTH BUY and SELL.  These fields are
never named upside/downside/profit/opportunity and are not the R8 favorable
executable edge.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from finco_radar.assets.contracts import AssetKey

from .contracts import (
    ComparabilityDimension,
    ComparabilityDimensionResult,
    ComparabilityState,
    ModelComparability,
    ModelEvidence,
    ModelRadarError,
    ModelRadarGapKind,
    ModelRadarStatus,
    ModelRadarTimingPolicy,
    ModelUnitBasis,
    ModelValueKind,
    PER_UNIT_BASES,
    TOTAL_BASES,
    _require_aware,
)

BPS_SCALE = Decimal(10000)


@dataclass(frozen=True)
class MarketComparabilityContext:
    """Source-proven market context used only to judge comparability."""
    reference_price: Decimal | None
    reference_currency: str | None
    reference_source: str | None
    reference_observed_at: datetime | None

    def __post_init__(self) -> None:
        if self.reference_observed_at is not None:
            _require_aware(self.reference_observed_at, "reference_observed_at")


def _dimension_ok(dimension: ComparabilityDimension) -> ComparabilityDimensionResult:
    return ComparabilityDimensionResult(dimension=dimension, ok=True)


def _dimension_fail(
    dimension: ComparabilityDimension,
    gap_kind: ModelRadarGapKind,
    detail: str,
) -> ComparabilityDimensionResult:
    return ComparabilityDimensionResult(
        dimension=dimension, ok=False, gap_kind=gap_kind, detail=detail)


def model_value_per_unit(model_evidence: ModelEvidence) -> Decimal:
    """Resolve the comparable per-unit model value.

    A TOTAL-kind value is only normalized when a source-proven unit
    multiplier exists on the model evidence (the explicit count of economic
    units the total is distributed over).  The multiplier is never assumed
    to be 1 and never inferred from token supply.
    """
    if model_evidence.unit_basis in TOTAL_BASES:
        if model_evidence.unit_multiplier is None:
            raise ModelRadarError(
                "TOTAL-kind model value has no source-proven unit multiplier",
                ModelRadarStatus.MODEL_RADAR_INPUT_INVALID,
            )
        if model_evidence.unit_multiplier <= 0:
            raise ModelRadarError(
                "source-proven unit multiplier must be positive",
                ModelRadarStatus.MODEL_RADAR_INPUT_INVALID,
            )
        return model_evidence.value / model_evidence.unit_multiplier
    return model_evidence.value


def resolve_comparability(
    *,
    model_evidence: ModelEvidence,
    market_context: MarketComparabilityContext,
    timing_policy: ModelRadarTimingPolicy,
    now: datetime,
) -> ModelComparability:
    """Validate ALL required comparability dimensions explicitly."""
    _require_aware(now, "now")
    results = []
    reference_observed = market_context.reference_observed_at or now

    # 1. Economic identity is enforced structurally by the bridge (binding
    #    + R9 lineage); recorded here as satisfied for the record.
    results.append(_dimension_ok(ComparabilityDimension.ECONOMIC_IDENTITY))

    # 2. Value kind: only an explicit per-economic-unit value is directly
    #    price-comparable.  Return/operating metrics and TOTAL kinds are
    #    preserved as evidence but never silently classified as price.
    if model_evidence.value <= 0:
        # Spec 63: zero or negative model value is a typed non-comparable
        # state; no market/model division is ever attempted.
        results.append(_dimension_fail(
            ComparabilityDimension.VALUE_KIND,
            ModelRadarGapKind.MODEL_VALUE_NONPOSITIVE,
            f"model value {model_evidence.value} is not strictly positive; "
            "reference/model bps require a positive model basis",
        ))
    elif model_evidence.value_kind is ModelValueKind.VALUE_PER_ECONOMIC_UNIT:
        results.append(_dimension_ok(ComparabilityDimension.VALUE_KIND))
    elif (
        model_evidence.value_kind is not ModelValueKind.NON_PRICE_METRIC
        and model_evidence.unit_multiplier is not None
    ):
        # A TOTAL value with a source-proven unit multiplier resolves to the
        # same economic unit as the market price; that authority is exactly
        # what the missing-denominator gap demanded.
        results.append(_dimension_ok(ComparabilityDimension.VALUE_KIND))
    else:
        results.append(_dimension_fail(
            ComparabilityDimension.VALUE_KIND,
            ModelRadarGapKind.VALUE_KIND_MISMATCH,
            f"model value kind {model_evidence.value_kind.value} is not a "
            "per-economic-unit value",
        ))

    # 3. Unit basis: explicit denominator required; TOTAL kinds additionally
    #    require a source-proven unit multiplier.
    if model_evidence.unit_basis in PER_UNIT_BASES:
        results.append(_dimension_ok(ComparabilityDimension.UNIT_BASIS))
    elif model_evidence.unit_basis in TOTAL_BASES:
        if model_evidence.unit_multiplier is None:
            results.append(_dimension_fail(
                ComparabilityDimension.UNIT_BASIS,
                ModelRadarGapKind.MULTIPLIER_UNAVAILABLE,
                "TOTAL-kind model value carries no source-proven unit "
                "multiplier; no implicit total-to-per-unit bridge exists",
            ))
        else:
            results.append(_dimension_ok(ComparabilityDimension.UNIT_BASIS))
    else:
        results.append(_dimension_fail(
            ComparabilityDimension.UNIT_BASIS,
            ModelRadarGapKind.UNIT_BASIS_UNAVAILABLE,
            "model unit basis unavailable",
        ))

    # 4. Currency: same-currency comparison only; no implicit FX, no
    #    stablecoin==USD assumption.  R10 v1 consumes no new FX authority.
    if not model_evidence.currency:
        results.append(_dimension_fail(
            ComparabilityDimension.CURRENCY,
            ModelRadarGapKind.CURRENCY_UNAVAILABLE,
            "model currency unavailable",
        ))
    elif market_context.reference_currency is None:
        results.append(_dimension_fail(
            ComparabilityDimension.CURRENCY,
            ModelRadarGapKind.CURRENCY_UNAVAILABLE,
            "market reference currency unavailable",
        ))
    elif model_evidence.currency.upper() != market_context.reference_currency.upper():
        results.append(_dimension_fail(
            ComparabilityDimension.CURRENCY,
            ModelRadarGapKind.CURRENCY_MISMATCH,
            f"model currency {model_evidence.currency} differs from market "
            f"reference currency {market_context.reference_currency}; no "
            "source-proven FX authority is consumed by R10 v1",
        ))
        results.append(_dimension_fail(
            ComparabilityDimension.CURRENCY,
            ModelRadarGapKind.FX_AUTHORITY_UNAVAILABLE,
            "no explicit FX conversion authority exists for this pair",
        ))
    else:
        results.append(_dimension_ok(ComparabilityDimension.CURRENCY))

    # 5. Timing: aware timestamps, no future valuation, explicit age and
    #    model-market skew policy.
    timing_failures = []
    if model_evidence.valuation_as_of > now:
        # Spec 30: a future valuation timestamp is a hard TIMING_INVALID.
        raise ModelRadarError(
            "model valuation timestamp is in the future relative to the "
            "comparison authority",
            ModelRadarStatus.MODEL_RADAR_TIMING_INVALID,
        )
    age_seconds = Decimal(str(
        (now - model_evidence.valuation_as_of).total_seconds()))
    if age_seconds > timing_policy.max_model_age_seconds:
        timing_failures.append(_dimension_fail(
            ComparabilityDimension.TIMING,
            ModelRadarGapKind.MODEL_STALE,
            f"model age {age_seconds}s exceeds policy "
            f"{timing_policy.max_model_age_seconds}s; a stale model is "
            "never relabeled current",
        ))
    if (market_context.reference_observed_at is not None
            and abs((
                model_evidence.valuation_as_of - reference_observed
            ).total_seconds()) > float(timing_policy.max_model_market_skew_seconds)):
        timing_failures.append(_dimension_fail(
            ComparabilityDimension.TIMING,
            ModelRadarGapKind.TIMING_SKEW_INVALID,
            "model-market timestamp skew exceeds "
            "max_model_market_skew_seconds",
        ))
    if timing_failures:
        results.extend(timing_failures)
    else:
        results.append(_dimension_ok(ComparabilityDimension.TIMING))

    # 6. Reference availability: model evidence can never backfill a missing
    #    market reference.
    if market_context.reference_price is None:
        results.append(_dimension_fail(
            ComparabilityDimension.REFERENCE_AVAILABILITY,
            ModelRadarGapKind.REFERENCE_UNAVAILABLE,
            "market reference price unavailable; model evidence does not "
            "replace reference authority",
        ))
    else:
        results.append(_dimension_ok(
            ComparabilityDimension.REFERENCE_AVAILABILITY))

    dimensions = tuple(results)
    hard_gaps = [d for d in dimensions if not d.ok]
    if not hard_gaps:
        state = ComparabilityState.COMPARABLE
    elif all(d.dimension is ComparabilityDimension.REFERENCE_AVAILABILITY
             for d in hard_gaps):
        # Everything else may be fine but there is nothing to compare with.
        state = ComparabilityState.PARTIALLY_COMPARABLE
    else:
        state = ComparabilityState.NOT_COMPARABLE
    return ModelComparability(state=state, dimensions=dimensions)


def compute_reference_comparison(
    *,
    model_value_per_unit: Decimal,
    reference_price: Decimal,
    reference_source: str,
    model_observed_at: datetime,
    reference_observed_at: datetime,
):
    """referenceMinusModelValue and referenceVsModelBps in exact Decimal.

    Division only when the model value is strictly positive.
    """
    from .contracts import ReferenceComparison

    if model_value_per_unit <= 0:
        raise ModelRadarError(
            "model value must be strictly positive for bps comparison",
            ModelRadarStatus.MODEL_RADAR_INPUT_INVALID,
        )
    if reference_price <= 0:
        raise ModelRadarError(
            "reference price must be strictly positive for bps comparison",
            ModelRadarStatus.MODEL_RADAR_INPUT_INVALID,
        )
    minus = reference_price - model_value_per_unit
    bps = (reference_price / model_value_per_unit - 1) * BPS_SCALE
    return ReferenceComparison(
        model_value=model_value_per_unit,
        reference_price=reference_price,
        reference_source=reference_source,
        reference_minus_model_value=minus,
        reference_vs_model_bps=bps,
        model_observed_at=model_observed_at,
        reference_observed_at=reference_observed_at,
    )


def compute_execution_comparison(
    *,
    model_value_per_unit: Decimal,
    execution_price: Decimal,
    side: str,
    requested_notional_usd: str,
    quote_source: str,
    r8_net_edge_state: str,
    r8_scenario_index: int,
):
    """executionMinusModelValue and executionVsModelBps in exact Decimal.

    Identical sign semantics for BUY and SELL; `side` stays descriptive
    metadata.  R8 economics are consumed, never recomputed or deducted.
    """
    from .contracts import ExecutionComparison

    if model_value_per_unit <= 0:
        raise ModelRadarError(
            "model value must be strictly positive for bps comparison",
            ModelRadarStatus.MODEL_RADAR_INPUT_INVALID,
        )
    if execution_price <= 0:
        raise ModelRadarError(
            "execution price must be strictly positive",
            ModelRadarStatus.MODEL_RADAR_INPUT_INVALID,
        )
    minus = execution_price - model_value_per_unit
    bps = (execution_price / model_value_per_unit - 1) * BPS_SCALE
    return ExecutionComparison(
        model_value=model_value_per_unit,
        execution_price=execution_price,
        execution_minus_model_value=minus,
        execution_vs_model_bps=bps,
        side=side,
        requested_notional_usd=requested_notional_usd,
        quote_source=quote_source,
        r8_net_edge_state=r8_net_edge_state,
        r8_scenario_index=r8_scenario_index,
    )
