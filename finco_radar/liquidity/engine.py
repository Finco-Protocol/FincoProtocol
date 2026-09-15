"""Fail-closed executable liquidity evidence over R0 quotes and R2 observations.

R3 owns three economically distinct measurements and keeps them separate:
  1. R0 size impact   — canonical router-level rate delta (consumed, not recomputed);
  2. R2 GAP delta     — directional gap size evidence from the R2 authority;
  3. executable spread — R3-owned cross-side quote spread at each notional.

R3 emits no composite score, no classification and no signal.
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Sequence

from finco_radar.assets.contracts import AssetKey, CanonicalAssetRecord
from finco_radar.gap.contracts import DirectionalGapObservation
from finco_radar.quotes.contracts import ExecutionQuote, QuoteSide, QuoteStatus
from finco_radar.quotes.normalization import quote_size_impact_bps

from .contracts import (
    R0_FORMULA_AUTHORITY,
    R1_IDENTITY_AUTHORITY,
    R2_OBSERVATION_AUTHORITY,
    LiquidityComparisonPolicy,
    LiquidityComputationError,
    LiquidityLineage,
    LiquiditySideSnapshot,
    LiquiditySnapshot,
    LiquiditySpreadSnapshot,
    LiquidityStatus,
    LiquidityTemporalEvidence,
    ProviderCostEvidence,
    RouteSignature,
)

SMALL_NOTIONAL_USD = Decimal("100")
LARGE_NOTIONAL_USD = Decimal("1000")

#: The exact observation matrix R3 accepts — nothing more, nothing less.
REQUIRED_MATRIX: tuple[tuple[QuoteSide, Decimal], ...] = (
    (QuoteSide.BUY, SMALL_NOTIONAL_USD),
    (QuoteSide.BUY, LARGE_NOTIONAL_USD),
    (QuoteSide.SELL, SMALL_NOTIONAL_USD),
    (QuoteSide.SELL, LARGE_NOTIONAL_USD),
)

BUY_SIZE_PAIR = "BUY_SIZE_PAIR"
SELL_SIZE_PAIR = "SELL_SIZE_PAIR"
CROSS_SIDE_100 = "CROSS_SIDE_100"
CROSS_SIDE_1000 = "CROSS_SIDE_1000"


def _slot_label(side: QuoteSide, notional: Decimal) -> str:
    size = "100" if notional == SMALL_NOTIONAL_USD else "1000"
    return f"{side.value}_{size}"


def _required_slot(quote_like: object) -> tuple[QuoteSide, Decimal] | None:
    """Map an item onto a required matrix slot by (side, notional); None if off-matrix."""
    side = getattr(quote_like, "side")
    notional = getattr(quote_like, "requested_notional_usd")
    for required_side, required_notional in REQUIRED_MATRIX:
        if side is required_side and notional == required_notional:
            return (required_side, required_notional)
    return None


def _key_of(ref: object) -> AssetKey | None:
    try:
        return AssetKey(ref.chain_id, ref.contract_address)  # type: ignore[attr-defined]
    except ValueError:
        return None


def _quote_key(quote: ExecutionQuote) -> AssetKey | None:
    try:
        return AssetKey(quote.chain_id, quote.token_address)
    except ValueError:
        return None


def build_route_signature(quote: ExecutionQuote) -> RouteSignature:
    """Deterministic ordered (tool, from_asset, to_asset) identity from R0 evidence.

    Raw leg amounts are deliberately excluded: they must never determine route
    identity. A quote without route evidence yields the degenerate NO_ROUTE_EVIDENCE
    signature, which is still deterministic and comparable.
    """
    legs: list[tuple[str, str, str]] = []
    if quote.evidence is not None:
        for leg in quote.evidence.route:
            legs.append((str(leg.tool), str(leg.from_asset), str(leg.to_asset)))
    return RouteSignature(legs=tuple(legs))


def normalize_provider_cost(quote: ExecutionQuote) -> ProviderCostEvidence:
    """Normalize provider-reported fee/gas as fail-safe evidence for one quote.

    The treatment state defaults to EVIDENCE_ONLY_INCLUSION_UNRESOLVED and is
    never guessed. Invalid amounts (negative or non-finite) fail typed.
    """
    return ProviderCostEvidence(
        requested_notional_usd=quote.requested_notional_usd,
        fee_cost_usd=quote.fee_cost_usd,
        gas_cost_usd=quote.gas_cost_usd,
    )


def execution_price_usd_per_token(quote: ExecutionQuote) -> Decimal:
    """Settlement-converted execution price, matching the frozen R2 formula.

    BUY:  P = (settlement_in  × USD_per_settlement) / token_out
    SELL: P = (settlement_out × USD_per_settlement) / token_in

    Provider-reported fee/gas amounts are never part of this price.
    """
    if quote.status is not QuoteStatus.QUOTE_OK:
        raise LiquidityComputationError(
            f"execution price requires QUOTE_OK, got {quote.status.value}",
            LiquidityStatus.QUOTE_UNAVAILABLE,
        )
    usd_per_asset = quote.settlement_reference.usd_per_asset
    if usd_per_asset is None or not usd_per_asset.is_finite() or usd_per_asset <= 0:
        raise LiquidityComputationError(
            "settlement USD reference must be positive and finite",
            LiquidityStatus.NON_FINITE_ECONOMICS,
        )
    if quote.side is QuoteSide.BUY:
        settlement_amount = quote.normalized_amount_in
        token_amount = quote.normalized_amount_out
    else:
        settlement_amount = quote.normalized_amount_out
        token_amount = quote.normalized_amount_in
    for name, value in (("settlement amount", settlement_amount), ("token amount", token_amount)):
        if value is None or not value.is_finite() or value <= 0:
            raise LiquidityComputationError(
                f"{name} must be positive and finite",
                LiquidityStatus.NON_FINITE_ECONOMICS,
            )
    settlement_amount_usd = settlement_amount * usd_per_asset
    price = settlement_amount_usd / token_amount
    if not price.is_finite() or price <= 0:
        raise LiquidityComputationError(
            "execution price must be positive and finite",
            LiquidityStatus.NON_FINITE_ECONOMICS,
        )
    return price


def executable_spread_evidence(
    buy_quote: ExecutionQuote | None,
    sell_quote: ExecutionQuote | None,
) -> LiquiditySpreadSnapshot | None:
    """R3-owned executable cross-side quote spread at one notional.

    Returns None when either side is missing or not QUOTE_OK — no spread exists
    without both sides. Broken economics on two present sides fail typed closed
    instead of emitting a bogus number. Not realized slippage; not an order-book
    bid/ask spread.
    """
    if buy_quote is None or sell_quote is None:
        return None
    if buy_quote.status is not QuoteStatus.QUOTE_OK or sell_quote.status is not QuoteStatus.QUOTE_OK:
        return None
    if buy_quote.side is not QuoteSide.BUY or sell_quote.side is not QuoteSide.SELL:
        raise LiquidityComputationError(
            "executable spread requires a BUY quote and a SELL quote",
            LiquidityStatus.QUOTE_MATRIX_INCOMPLETE,
        )
    if buy_quote.requested_notional_usd != sell_quote.requested_notional_usd:
        raise LiquidityComputationError(
            "executable spread requires matching notionals on both sides",
            LiquidityStatus.QUOTE_MATRIX_INCOMPLETE,
        )
    p_buy = execution_price_usd_per_token(buy_quote)
    p_sell = execution_price_usd_per_token(sell_quote)
    p_mid = (p_buy + p_sell) / Decimal("2")
    if not p_mid.is_finite() or p_mid <= 0:
        raise LiquidityComputationError(
            "executable mid must be positive and finite",
            LiquidityStatus.NON_FINITE_ECONOMICS,
        )
    spread_bps = ((p_buy - p_sell) / p_mid) * Decimal("10000")
    if not spread_bps.is_finite():
        raise LiquidityComputationError(
            "executable spread is not finite",
            LiquidityStatus.NON_FINITE_ECONOMICS,
        )
    return LiquiditySpreadSnapshot(
        notional_usd=buy_quote.requested_notional_usd,
        buy_execution_price_usd_per_token=p_buy,
        sell_execution_price_usd_per_token=p_sell,
        execution_mid_price_usd_per_token=p_mid,
        execution_spread_bps=spread_bps,
    )


def _build_quote_matrix(
    quotes: Sequence[ExecutionQuote],
) -> dict[tuple[QuoteSide, Decimal], ExecutionQuote]:
    matrix: dict[tuple[QuoteSide, Decimal], ExecutionQuote] = {}
    for quote in quotes:
        slot = _required_slot(quote)
        if slot is None:
            raise LiquidityComputationError(
                f"quote {quote.side.value} {quote.requested_notional_usd}USD is outside "
                "the required $100/$1,000 BUY/SELL matrix",
                LiquidityStatus.QUOTE_MATRIX_INCOMPLETE,
            )
        if slot in matrix:
            raise LiquidityComputationError(
                f"duplicate quote for slot {slot[0].value} {slot[1]}USD",
                LiquidityStatus.QUOTE_MATRIX_INCOMPLETE,
            )
        matrix[slot] = quote
    missing = [slot for slot in REQUIRED_MATRIX if slot not in matrix]
    if missing:
        raise LiquidityComputationError(
            f"missing quote matrix rows: {[_slot_label(s, n) for s, n in missing]}",
            LiquidityStatus.QUOTE_MATRIX_INCOMPLETE,
        )
    return matrix


def _build_observation_matrix(
    observations: Sequence[DirectionalGapObservation],
) -> dict[tuple[QuoteSide, Decimal], DirectionalGapObservation]:
    matrix: dict[tuple[QuoteSide, Decimal], DirectionalGapObservation] = {}
    for observation in observations:
        slot = _required_slot(observation)
        if slot is None:
            raise LiquidityComputationError(
                f"R2 observation {observation.side.value} "
                f"{observation.requested_notional_usd}USD is outside the required matrix",
                LiquidityStatus.R2_LINEAGE_MISMATCH,
            )
        if slot in matrix:
            raise LiquidityComputationError(
                f"duplicate R2 observation for slot {slot[0].value} {slot[1]}USD",
                LiquidityStatus.R2_LINEAGE_MISMATCH,
            )
        matrix[slot] = observation
    missing = [slot for slot in REQUIRED_MATRIX if slot not in matrix]
    if missing:
        raise LiquidityComputationError(
            f"missing R2 observation rows: {[_slot_label(s, n) for s, n in missing]}",
            LiquidityStatus.R2_LINEAGE_MISMATCH,
        )
    return matrix


def _validate_quote_identity(
    quote: ExecutionQuote,
    *,
    asset_key: AssetKey,
    settlement_key: AssetKey,
    quote_source: str,
) -> None:
    def mismatch(detail: str) -> LiquidityComputationError:
        return LiquidityComputationError(
            f"{_slot_label(quote.side, quote.requested_notional_usd)}: {detail}",
            LiquidityStatus.IDENTITY_MISMATCH,
        )

    if quote.chain_id != asset_key.chain_id:
        raise mismatch("quote chain does not match the canonical deployment chain")
    if _quote_key(quote) != asset_key:
        raise mismatch("quote token address does not match the canonical deployment address")
    if quote.settlement_reference.asset.chain_id != asset_key.chain_id:
        raise mismatch("settlement chain does not match the canonical deployment chain")
    if _key_of(quote.settlement_reference.asset) != settlement_key:
        raise mismatch("settlement asset identity differs across the quote matrix")
    token_key = _key_of(quote.input_asset if quote.side is QuoteSide.SELL else quote.output_asset)
    settlement_leg_key = _key_of(
        quote.output_asset if quote.side is QuoteSide.SELL else quote.input_asset
    )
    if token_key != asset_key:
        raise mismatch("quote route orientation does not carry the canonical token")
    if settlement_leg_key != settlement_key:
        raise mismatch("quote route orientation does not carry the canonical settlement asset")
    if not quote.source or quote.source != quote_source:
        raise mismatch("quote source lineage differs across the quote matrix")


def _validate_observation_lineage(
    observation: DirectionalGapObservation,
    quote: ExecutionQuote,
    *,
    asset: CanonicalAssetRecord,
    asset_key: AssetKey,
    derived_price: Decimal,
) -> None:
    def lineage_error(detail: str) -> LiquidityComputationError:
        return LiquidityComputationError(
            f"R2 observation {_slot_label(observation.side, observation.requested_notional_usd)}: "
            f"{detail}",
            LiquidityStatus.R2_LINEAGE_MISMATCH,
        )

    if observation.asset_uid != asset.asset_uid:
        raise lineage_error("asset UID does not match the canonical asset")
    if observation.asset_key != asset_key:
        raise lineage_error("asset key does not match the canonical deployment")
    if observation.side is not quote.side:
        raise lineage_error("side does not match the bound quote")
    if observation.requested_notional_usd != quote.requested_notional_usd:
        raise lineage_error("requested notional does not match the bound quote")
    if observation.quoted_at != quote.quoted_at:
        raise lineage_error("quoted_at does not match the bound quote")
    if observation.quote_source != quote.source:
        raise lineage_error("quote source does not match the bound quote")
    if observation.execution_price_usd_per_token != derived_price:
        raise lineage_error(
            "execution price was not derived from the bound quote economics"
        )


def _pair_skew_seconds(first: datetime, second: datetime) -> Decimal:
    if first.tzinfo is None or second.tzinfo is None:
        raise LiquidityComputationError(
            "quote timestamps must be timezone-aware",
            LiquidityStatus.EVIDENCE_TIME_MISMATCH,
        )
    return Decimal(str(abs((first - second).total_seconds())))


def build_liquidity_snapshot(
    *,
    asset: CanonicalAssetRecord,
    asset_key: AssetKey,
    quotes: Sequence[ExecutionQuote],
    gap_observations: Sequence[DirectionalGapObservation],
    policy: LiquidityComparisonPolicy,
    git_head: str,
    produced_at: datetime,
) -> LiquiditySnapshot:
    """Build the R3 LiquiditySnapshot, or raise a typed LiquidityComputationError.

    All four quotes and all four R2 observations must refer to one exact R1
    canonical deployment and share one quote lineage. Quote-pair timing must be
    inside the mandatory caller-supplied policy. Nothing here guesses.
    """
    if asset_key not in asset.deployments:
        raise LiquidityComputationError(
            "canonical asset does not own the bound deployment key",
            LiquidityStatus.IDENTITY_MISMATCH,
        )
    if produced_at.tzinfo is None:
        raise LiquidityComputationError(
            "produced_at must be timezone-aware",
            LiquidityStatus.EVIDENCE_TIME_MISMATCH,
        )

    quote_matrix = _build_quote_matrix(quotes)

    # Quote availability before any economics: non-QUOTE_OK rows fail typed.
    for slot, quote in quote_matrix.items():
        if quote.status is not QuoteStatus.QUOTE_OK:
            status = (
                LiquidityStatus.INSUFFICIENT_LIQUIDITY
                if quote.status is QuoteStatus.INSUFFICIENT_LIQUIDITY
                else LiquidityStatus.QUOTE_UNAVAILABLE
            )
            raise LiquidityComputationError(
                f"{_slot_label(*slot)}: quote status is {quote.status.value}",
                status,
            )

    # One coherent quote set: identity and shared source lineage.
    settlement_key = _key_of(quote_matrix[REQUIRED_MATRIX[0]].settlement_reference.asset)
    if settlement_key is None:
        raise LiquidityComputationError(
            "settlement asset identity is malformed",
            LiquidityStatus.IDENTITY_MISMATCH,
        )
    quote_source = quote_matrix[REQUIRED_MATRIX[0]].source
    if not quote_source:
        raise LiquidityComputationError(
            "quote source lineage must be non-empty",
            LiquidityStatus.IDENTITY_MISMATCH,
        )
    for slot in REQUIRED_MATRIX:
        _validate_quote_identity(
            quote_matrix[slot],
            asset_key=asset_key,
            settlement_key=settlement_key,
            quote_source=quote_source,
        )

    # R2 observation matrix and per-slot lineage against the bound quotes.
    observation_matrix = _build_observation_matrix(gap_observations)
    derived_prices: dict[tuple[QuoteSide, Decimal], Decimal] = {}
    for slot in REQUIRED_MATRIX:
        derived_prices[slot] = execution_price_usd_per_token(quote_matrix[slot])
    for slot in REQUIRED_MATRIX:
        _validate_observation_lineage(
            observation_matrix[slot],
            quote_matrix[slot],
            asset=asset,
            asset_key=asset_key,
            derived_price=derived_prices[slot],
        )

    # Quote-to-quote temporal coherence (R3 authority; R2 reference-time
    # coherence remains R2's own gate inside compute_directional_gap).
    buy_small, buy_large = quote_matrix[(QuoteSide.BUY, SMALL_NOTIONAL_USD)], quote_matrix[
        (QuoteSide.BUY, LARGE_NOTIONAL_USD)
    ]
    sell_small, sell_large = quote_matrix[(QuoteSide.SELL, SMALL_NOTIONAL_USD)], quote_matrix[
        (QuoteSide.SELL, LARGE_NOTIONAL_USD)
    ]
    pair_skews: list[tuple[str, Decimal]] = [
        (BUY_SIZE_PAIR, _pair_skew_seconds(buy_small.quoted_at, buy_large.quoted_at)),
        (SELL_SIZE_PAIR, _pair_skew_seconds(sell_small.quoted_at, sell_large.quoted_at)),
        (CROSS_SIDE_100, _pair_skew_seconds(buy_small.quoted_at, sell_small.quoted_at)),
        (CROSS_SIDE_1000, _pair_skew_seconds(buy_large.quoted_at, sell_large.quoted_at)),
    ]
    for label, skew in pair_skews:
        if skew > policy.max_quote_pair_skew_seconds:
            raise LiquidityComputationError(
                f"{label} skew {skew}s exceeds policy {policy.max_quote_pair_skew_seconds}s",
                LiquidityStatus.EVIDENCE_TIME_MISMATCH,
            )

    # Canonical R0 size impact — consumed, never recomputed from R2 GAP values.
    try:
        buy_size_impact = quote_size_impact_bps(buy_small, buy_large)
        sell_size_impact = quote_size_impact_bps(sell_small, sell_large)
    except ValueError as exc:
        raise LiquidityComputationError(
            f"canonical R0 size impact refused the quote pair: {exc}",
            LiquidityStatus.NON_FINITE_ECONOMICS,
        ) from exc

    # R2 directional GAP deltas — side-specific evidence from the R2 authority.
    buy_gap_delta = (
        observation_matrix[(QuoteSide.BUY, LARGE_NOTIONAL_USD)].gap_bps
        - observation_matrix[(QuoteSide.BUY, SMALL_NOTIONAL_USD)].gap_bps
    )
    sell_gap_delta = (
        observation_matrix[(QuoteSide.SELL, LARGE_NOTIONAL_USD)].gap_bps
        - observation_matrix[(QuoteSide.SELL, SMALL_NOTIONAL_USD)].gap_bps
    )
    if not buy_gap_delta.is_finite() or not sell_gap_delta.is_finite():
        raise LiquidityComputationError(
            "directional GAP delta must be finite",
            LiquidityStatus.NON_FINITE_ECONOMICS,
        )

    # R3-owned executable spreads at each notional plus the size delta.
    spread_small = executable_spread_evidence(buy_small, sell_small)
    spread_large = executable_spread_evidence(buy_large, sell_large)
    if spread_small is None or spread_large is None:
        raise LiquidityComputationError(
            "executable spread requires both sides QUOTE_OK at each notional",
            LiquidityStatus.QUOTE_UNAVAILABLE,
        )
    spread_delta = spread_large.execution_spread_bps - spread_small.execution_spread_bps
    if not spread_delta.is_finite():
        raise LiquidityComputationError(
            "executable spread delta must be finite",
            LiquidityStatus.NON_FINITE_ECONOMICS,
        )

    cost_evidence = tuple(
        normalize_provider_cost(quote_matrix[slot]) for slot in REQUIRED_MATRIX
    )

    max_skew = max(skew for _, skew in pair_skews)
    temporal = LiquidityTemporalEvidence(
        policy=policy,
        quote_pair_skews=tuple(pair_skews),
        max_observed_pair_skew_seconds=max_skew,
    )
    lineage = LiquidityLineage(
        r0_formula_authority=R0_FORMULA_AUTHORITY,
        r2_observation_authority=R2_OBSERVATION_AUTHORITY,
        r1_canonical_identity=R1_IDENTITY_AUTHORITY,
        quote_source=quote_source,
        git_head=git_head,
        produced_at=produced_at,
    )

    return LiquiditySnapshot(
        status=LiquidityStatus.LIQUIDITY_OK,
        asset_uid=asset.asset_uid,
        canonical_key=asset_key,
        symbol=asset.token_symbol,
        small_notional_usd=SMALL_NOTIONAL_USD,
        large_notional_usd=LARGE_NOTIONAL_USD,
        buy=LiquiditySideSnapshot(
            side=QuoteSide.BUY,
            small_quote=buy_small,
            large_quote=buy_large,
            small_gap_observation=observation_matrix[(QuoteSide.BUY, SMALL_NOTIONAL_USD)],
            large_gap_observation=observation_matrix[(QuoteSide.BUY, LARGE_NOTIONAL_USD)],
            r0_size_impact_bps=buy_size_impact,
            directional_gap_delta_bps=buy_gap_delta,
            small_route_signature=build_route_signature(buy_small),
            large_route_signature=build_route_signature(buy_large),
        ),
        sell=LiquiditySideSnapshot(
            side=QuoteSide.SELL,
            small_quote=sell_small,
            large_quote=sell_large,
            small_gap_observation=observation_matrix[(QuoteSide.SELL, SMALL_NOTIONAL_USD)],
            large_gap_observation=observation_matrix[(QuoteSide.SELL, LARGE_NOTIONAL_USD)],
            r0_size_impact_bps=sell_size_impact,
            directional_gap_delta_bps=sell_gap_delta,
            small_route_signature=build_route_signature(sell_small),
            large_route_signature=build_route_signature(sell_large),
        ),
        spread_small=spread_small,
        spread_large=spread_large,
        spread_delta_bps=spread_delta,
        cost_evidence=cost_evidence,
        temporal=temporal,
        lineage=lineage,
    )


__all__ = [
    "BUY_SIZE_PAIR",
    "CROSS_SIDE_100",
    "CROSS_SIDE_1000",
    "LARGE_NOTIONAL_USD",
    "R0_FORMULA_AUTHORITY",
    "R1_IDENTITY_AUTHORITY",
    "R2_OBSERVATION_AUTHORITY",
    "REQUIRED_MATRIX",
    "SELL_SIZE_PAIR",
    "SMALL_NOTIONAL_USD",
    "build_liquidity_snapshot",
    "build_route_signature",
    "executable_spread_evidence",
    "execution_price_usd_per_token",
    "normalize_provider_cost",
]
