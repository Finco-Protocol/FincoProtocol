"""R10 comparability resolution and model-vs-market comparisons.

Decimal-only comparison arithmetic.  Frozen model functions may return
float: their values enter R10 through decimal_from_authority() (canonical
textual representation) and never through Decimal(binary_float).

Correction A:
- F1: a closed ModelValueKind x ModelUnitBasis compatibility authority.
  EV and project NPV are NEVER market-price comparable in v1, with or
  without a multiplier; only EQUITY_VALUE_TOTAL with a source-proven
  multiplier whose declared basis is a PER_UNIT basis may normalize.
- F2: the market denominator is explicit and source-proven.  R7/R8 observe
  USD-per-token-claim; a model value on another PER_UNIT basis is compared
  only through the exact frozen R7 conversion multiplier (oracle/token
  multipliers must agree), applied exactly once.  No implicit 1.
- F5: exactly one result per each of the seven dimensions; the currency
  result is unique (FX absence is surfaced as a snapshot gap, never a
  duplicated dimension row).
- F7b: timing arithmetic stays in exact Decimal, never float.

Signed semantics are descriptive: positive bps means the market observation
is above the model value basis, for BOTH BUY and SELL.  These fields are
never named upside/downside/profit/opportunity and are not the R8 favorable
executable edge.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal

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
MICROSECONDS = Decimal(10**6)

# F1: closed ModelValueKind x ModelUnitBasis normalization authority (v1).
# Nothing else normalizes; ENTERPRISE_VALUE_TOTAL and PROJECT_NPV_TOTAL have
# no EV->equity / NPV->ownership bridge authority and never become
# market-price comparable merely because a denominator exists.
NORMALIZATION_AUTHORITY: dict[ModelValueKind, ModelUnitBasis] = {
    ModelValueKind.EQUITY_VALUE_TOTAL: ModelUnitBasis.TOTAL_EQUITY,
}


def decimal_seconds(delta: timedelta) -> Decimal:
    """Exact Decimal seconds; no float conversion anywhere in timing."""
    micros = (
        Decimal(delta.days) * Decimal(86400) * MICROSECONDS
        + Decimal(delta.seconds) * MICROSECONDS
        + Decimal(delta.microseconds)
    )
    return micros / MICROSECONDS


@dataclass(frozen=True)
class MarketComparabilityContext:
    """Source-proven market context used only to judge comparability.

    F2: the market denominator is explicit.  Frozen R7/R8 authority observes
    prices per token claim (executionPriceUsdPerToken / multiplier-adjusted
    oracle reference).  ``market_unit_basis`` records that denominator;
    ``conversion_multiplier`` is the R7 oracle multiplier and is usable as
    the per-unit -> per-token-claim conversion authority only when it equals
    the R7 token-layer multiplier (``token_multiplier``).
    """
    reference_price: Decimal | None
    reference_currency: str | None
    reference_source: str | None
    reference_observed_at: datetime | None
    market_unit_basis: "ModelUnitBasis | None" = None
    conversion_multiplier: "Decimal | None" = None
    token_multiplier: "Decimal | None" = None

    def __post_init__(self) -> None:
        if self.reference_observed_at is not None:
            _require_aware(self.reference_observed_at, "reference_observed_at")
        if self.market_unit_basis is not None and self.market_unit_basis not in (
            PER_UNIT_BASES
        ):
            raise ModelRadarError(
                "market unit basis must be a PER_UNIT basis",
                ModelRadarStatus.MODEL_RADAR_INPUT_INVALID,
            )


def _ok(dimension: ComparabilityDimension) -> ComparabilityDimensionResult:
    return ComparabilityDimensionResult(dimension=dimension, ok=True)


def _fail(
    dimension: ComparabilityDimension,
    gap_kind: ModelRadarGapKind,
    detail: str,
) -> ComparabilityDimensionResult:
    return ComparabilityDimensionResult(
        dimension=dimension, ok=False, gap_kind=gap_kind, detail=detail)


def model_value_per_unit(model_evidence: ModelEvidence) -> Decimal:
    """Resolve the comparable per-unit model value.

    Only the F1 NORMALIZATION_AUTHORITY pairs normalize, and only with a
    source-proven multiplier whose declared basis is the PER_UNIT basis the
    total is distributed over.  The multiplier is never assumed to be 1 and
    never inferred from token supply.
    """
    if model_evidence.unit_basis in PER_UNIT_BASES:
        return model_evidence.value
    expected_total_basis = NORMALIZATION_AUTHORITY.get(model_evidence.value_kind)
    if (
        expected_total_basis is not None
        and model_evidence.unit_basis is expected_total_basis
        and model_evidence.unit_multiplier is not None
        and model_evidence.unit_multiplier_basis is not None
    ):
        return model_evidence.value / model_evidence.unit_multiplier
    raise ModelRadarError(
        f"value kind {model_evidence.value_kind.value} on unit basis "
        f"{model_evidence.unit_basis.value} has no normalization authority",
        ModelRadarStatus.MODEL_RADAR_INPUT_INVALID,
    )


def _value_kind_dimension(
    model_evidence: ModelEvidence,
) -> ComparabilityDimensionResult:
    if model_evidence.value <= 0:
        # Spec 63: zero or negative model value is a typed non-comparable
        # state; no market/model division is ever attempted.
        return _fail(
            ComparabilityDimension.VALUE_KIND,
            ModelRadarGapKind.MODEL_VALUE_NONPOSITIVE,
            f"model value {model_evidence.value} is not strictly positive; "
            "reference/model bps require a positive model basis",
        )
    if model_evidence.value_kind is ModelValueKind.VALUE_PER_ECONOMIC_UNIT:
        return _ok(ComparabilityDimension.VALUE_KIND)
    if model_evidence.value_kind is ModelValueKind.NON_PRICE_METRIC:
        return _fail(
            ComparabilityDimension.VALUE_KIND,
            ModelRadarGapKind.VALUE_KIND_MISMATCH,
            "model output is a return/operating metric (NON_PRICE_METRIC) "
            "and is never price-comparable",
        )
    if model_evidence.value_kind is ModelValueKind.ENTERPRISE_VALUE_TOTAL:
        return _fail(
            ComparabilityDimension.VALUE_KIND,
            ModelRadarGapKind.VALUE_KIND_MISMATCH,
            "ENTERPRISE_VALUE_TOTAL is not an equity/share/token value; no "
            "EV-to-equity bridge authority exists in R10 v1 and a naked "
            "unit multiplier is insufficient",
        )
    if model_evidence.value_kind is ModelValueKind.PROJECT_NPV_TOTAL:
        return _fail(
            ComparabilityDimension.VALUE_KIND,
            ModelRadarGapKind.VALUE_KIND_MISMATCH,
            "PROJECT_NPV_TOTAL is not a token/share value; no explicit "
            "ownership/equity-claim bridge authority exists in R10 v1 and "
            "a naked unit multiplier is insufficient",
        )
    if model_evidence.value_kind is ModelValueKind.NAV_TOTAL:
        return _fail(
            ComparabilityDimension.VALUE_KIND,
            ModelRadarGapKind.VALUE_KIND_MISMATCH,
            "NAV_TOTAL claim/unit semantics are not proven sufficient for "
            "the exact market unit being compared; fail closed",
        )
    # EQUITY_VALUE_TOTAL: normalizable only through the F1 authority.
    expected_basis = NORMALIZATION_AUTHORITY.get(model_evidence.value_kind)
    if (
        model_evidence.unit_basis is expected_basis
        and model_evidence.unit_multiplier is not None
        and model_evidence.unit_multiplier_basis is not None
    ):
        return _ok(ComparabilityDimension.VALUE_KIND)
    return _fail(
        ComparabilityDimension.VALUE_KIND,
        ModelRadarGapKind.VALUE_KIND_MISMATCH,
        "total equity value is market-price comparable only when its "
        "denominator is explicitly source-proven to be the relevant equity "
        "economic units (unit multiplier with declared PER_UNIT basis)",
    )


def _unit_basis_and_multiplier_dimensions(
    model_evidence: ModelEvidence,
    market_context: MarketComparabilityContext,
) -> tuple[ComparabilityDimensionResult, ComparabilityDimensionResult]:
    """F2: the UNIT_BASIS and MULTIPLIER dimensions.

    Market observations are per token claim.  A model value on
    PER_TOKEN_CLAIM compares directly.  A model value on another PER_UNIT
    basis converts only through the exact frozen R7 conversion multiplier
    (oracle multiplier, proven equal to the token multiplier), applied
    exactly once.  Missing or disagreeing multipliers fail closed.
    """
    if model_evidence.unit_basis in TOTAL_BASES:
        if model_evidence.unit_multiplier is None:
            return (
                _fail(
                    ComparabilityDimension.UNIT_BASIS,
                    ModelRadarGapKind.MULTIPLIER_UNAVAILABLE,
                    "TOTAL-kind model value carries no source-proven unit "
                    "multiplier; no implicit total-to-per-unit bridge exists",
                ),
                _fail(
                    ComparabilityDimension.MULTIPLIER,
                    ModelRadarGapKind.MULTIPLIER_UNAVAILABLE,
                    "no source-proven unit-multiplier authority for the "
                    "total value denominator",
                ),
            )
        if model_evidence.unit_multiplier_basis is None:
            return (
                _fail(
                    ComparabilityDimension.UNIT_BASIS,
                    ModelRadarGapKind.UNIT_BASIS_UNAVAILABLE,
                    "unit multiplier without a declared PER_UNIT basis",
                ),
                _fail(
                    ComparabilityDimension.MULTIPLIER,
                    ModelRadarGapKind.MULTIPLIER_UNAVAILABLE,
                    "unit multiplier basis undeclared",
                ),
            )
        # Normalized to unit_multiplier_basis units; the conversion question
        # is then the same as for a PER_UNIT model value.
        model_basis: ModelUnitBasis | None = model_evidence.unit_multiplier_basis
    else:
        model_basis = model_evidence.unit_basis

    if market_context.market_unit_basis is None:
        return (
            _fail(
                ComparabilityDimension.UNIT_BASIS,
                ModelRadarGapKind.UNIT_BASIS_UNAVAILABLE,
                "market denominator is not source-proven",
            ),
            _fail(
                ComparabilityDimension.MULTIPLIER,
                ModelRadarGapKind.MULTIPLIER_UNAVAILABLE,
                "no market unit authority to compare against",
            ),
        )
    if model_basis is market_context.market_unit_basis:
        return (
            _ok(ComparabilityDimension.UNIT_BASIS),
            _ok(ComparabilityDimension.MULTIPLIER),
        )
    # Different per-unit bases: conversion only via the exact frozen R7
    # multiplier authority, and only from a PER_ECONOMIC_UNIT/PER_SHARE
    # model basis to the token-claim market basis.
    conversion = market_context.conversion_multiplier
    token_multiplier = market_context.token_multiplier
    if conversion is None or token_multiplier is None:
        return (
            _fail(
                ComparabilityDimension.UNIT_BASIS,
                ModelRadarGapKind.UNIT_BASIS_MISMATCH,
                f"model denominator {model_basis.value} differs from the "
                f"market denominator "
                f"{market_context.market_unit_basis.value}",
            ),
            _fail(
                ComparabilityDimension.MULTIPLIER,
                ModelRadarGapKind.MULTIPLIER_UNAVAILABLE,
                "no exact frozen per-unit-to-token-claim conversion "
                "multiplier is available; the multiplier is never assumed "
                "to be 1 and never inferred from token supply",
            ),
        )
    if conversion != token_multiplier:
        return (
            _fail(
                ComparabilityDimension.UNIT_BASIS,
                ModelRadarGapKind.UNIT_BASIS_MISMATCH,
                "R7 oracle-reference multiplier and R7 token-representation "
                "multiplier disagree; unit conversion fails closed",
            ),
            _fail(
                ComparabilityDimension.MULTIPLIER,
                ModelRadarGapKind.MULTIPLIER_UNAVAILABLE,
                "conflicting multiplier authorities",
            ),
        )
    return (
        _ok(ComparabilityDimension.UNIT_BASIS),
        ComparabilityDimensionResult(
            dimension=ComparabilityDimension.MULTIPLIER,
            ok=True,
            detail=(
                f"exact frozen conversion multiplier {conversion} applied "
                "exactly once (model per-unit -> market per-token-claim)"
            ),
        ),
    )


def _currency_dimension(
    model_evidence: ModelEvidence,
    market_context: MarketComparabilityContext,
) -> ComparabilityDimensionResult:
    """F5: the single CURRENCY result; FX absence is surfaced by the bridge
    as a snapshot gap, never as a duplicated dimension row."""
    if not model_evidence.currency:
        return _fail(
            ComparabilityDimension.CURRENCY,
            ModelRadarGapKind.CURRENCY_UNAVAILABLE,
            "model currency unavailable",
        )
    if market_context.reference_currency is None:
        return _fail(
            ComparabilityDimension.CURRENCY,
            ModelRadarGapKind.CURRENCY_UNAVAILABLE,
            "market reference currency unavailable",
        )
    if model_evidence.currency.upper() != market_context.reference_currency.upper():
        return _fail(
            ComparabilityDimension.CURRENCY,
            ModelRadarGapKind.CURRENCY_MISMATCH,
            f"model currency {model_evidence.currency} differs from market "
            f"reference currency {market_context.reference_currency}; no "
            "source-proven FX authority is consumed by R10 v1",
        )
    return _ok(ComparabilityDimension.CURRENCY)


def _timing_dimension(
    model_evidence: ModelEvidence,
    market_context: MarketComparabilityContext,
    timing_policy: ModelRadarTimingPolicy,
    now: datetime,
) -> ComparabilityDimensionResult:
    _require_aware(now, "now")
    if model_evidence.valuation_as_of > now:
        # Spec 30: a future valuation timestamp is a hard TIMING_INVALID.
        raise ModelRadarError(
            "model valuation timestamp is in the future relative to the "
            "comparison authority",
            ModelRadarStatus.MODEL_RADAR_TIMING_INVALID,
        )
    age_seconds = decimal_seconds(now - model_evidence.valuation_as_of)
    if age_seconds > timing_policy.max_model_age_seconds:
        return _fail(
            ComparabilityDimension.TIMING,
            ModelRadarGapKind.MODEL_STALE,
            f"model age {age_seconds}s exceeds policy "
            f"{timing_policy.max_model_age_seconds}s; a stale model is "
            "never relabeled current",
        )
    if market_context.reference_observed_at is not None:
        skew = decimal_seconds(
            abs(model_evidence.valuation_as_of - market_context.reference_observed_at)
        )
        if skew > timing_policy.max_model_market_skew_seconds:
            return _fail(
                ComparabilityDimension.TIMING,
                ModelRadarGapKind.TIMING_SKEW_INVALID,
                f"model-market timestamp skew {skew}s exceeds "
                f"max_model_market_skew_seconds "
                f"{timing_policy.max_model_market_skew_seconds}",
            )
    return _ok(ComparabilityDimension.TIMING)


def _reference_dimension(
    market_context: MarketComparabilityContext,
) -> ComparabilityDimensionResult:
    if market_context.reference_price is None:
        return _fail(
            ComparabilityDimension.REFERENCE_AVAILABILITY,
            ModelRadarGapKind.REFERENCE_UNAVAILABLE,
            "market reference price unavailable; model evidence does not "
            "replace reference authority",
        )
    return _ok(ComparabilityDimension.REFERENCE_AVAILABILITY)


def resolve_comparability(
    *,
    model_evidence: ModelEvidence,
    market_context: MarketComparabilityContext,
    timing_policy: ModelRadarTimingPolicy,
    now: datetime,
) -> ModelComparability:
    """Validate ALL required comparability dimensions explicitly.

    F5: the result contains exactly one record per dimension — the seven
    required dimensions, no duplicates, no extras.
    """
    dimensions = (
        _ok(ComparabilityDimension.ECONOMIC_IDENTITY),
        _value_kind_dimension(model_evidence),
        *_unit_basis_and_multiplier_dimensions(model_evidence, market_context),
        _currency_dimension(model_evidence, market_context),
        _timing_dimension(model_evidence, market_context, timing_policy, now),
        _reference_dimension(market_context),
    )
    hard = [d for d in dimensions if not d.ok]
    if not hard:
        state = ComparabilityState.COMPARABLE
    elif all(
        d.dimension is ComparabilityDimension.REFERENCE_AVAILABILITY
        for d in hard
    ):
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
