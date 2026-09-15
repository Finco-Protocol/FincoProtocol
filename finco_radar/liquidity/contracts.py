"""Typed contracts for FINCO Radar R3 executable liquidity evidence."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Any

from finco_radar.assets.contracts import AssetKey
from finco_radar.gap.contracts import DirectionalGapObservation
from finco_radar.quotes.contracts import ExecutionQuote, QuoteSide

# Authority provenance labels. R3 consumes upstream authorities; it never
# reimplements them. These strings name the frozen source of each metric.
R0_FORMULA_AUTHORITY = "finco_radar.quotes.normalization.quote_size_impact_bps"
R2_OBSERVATION_AUTHORITY = (
    "finco_radar.gap.contracts.DirectionalGapObservation via "
    "finco_radar.gap.engine.compute_directional_gap"
)
R1_IDENTITY_AUTHORITY = (
    "finco_radar.assets.contracts.AssetKey (chain_id + contract_address); "
    "ticker is metadata only"
)

# R2 semantics are side-specific and must never be generalized across sides.
BUY_DELTA_INTERPRETATION = (
    "positive = larger BUY is worse (the $1,000 purchase is more expensive relative to "
    "the multiplier-adjusted official ASK than the $100 purchase); "
    "negative = larger BUY is better"
)
SELL_DELTA_INTERPRETATION = (
    "positive = larger SELL is better (the $1,000 sale is richer relative to the "
    "multiplier-adjusted official BID than the $100 sale); "
    "negative = larger SELL is worse"
)


class LiquidityStatus(str, Enum):
    """Typed fail-closed status for each R3 liquidity computation attempt.

    Materially different causes must not collapse to a generic BLOCKED.
    Infrastructure/network errors remain separate from economic/authority
    statuses and are classified by the caller (live proof), never by R3.
    """

    LIQUIDITY_OK = "LIQUIDITY_OK"
    QUOTE_MATRIX_INCOMPLETE = "QUOTE_MATRIX_INCOMPLETE"
    QUOTE_UNAVAILABLE = "QUOTE_UNAVAILABLE"
    INSUFFICIENT_LIQUIDITY = "INSUFFICIENT_LIQUIDITY"
    IDENTITY_MISMATCH = "IDENTITY_MISMATCH"
    R2_LINEAGE_MISMATCH = "R2_LINEAGE_MISMATCH"
    EVIDENCE_TIME_MISMATCH = "EVIDENCE_TIME_MISMATCH"
    NON_FINITE_ECONOMICS = "NON_FINITE_ECONOMICS"
    COST_EVIDENCE_INVALID = "COST_EVIDENCE_INVALID"


class LiquidityComputationError(ValueError):
    """Raised when executable liquidity evidence cannot be produced without guessing.

    Always carries a typed LiquidityStatus so callers can categorize the failure
    without inspecting free-form message text.
    """

    def __init__(
        self,
        message: str,
        status: LiquidityStatus = LiquidityStatus.NON_FINITE_ECONOMICS,
    ) -> None:
        super().__init__(message)
        self.status = status


class CostTreatmentState(str, Enum):
    """Fail-safe classification of provider-reported fee/gas cost treatment.

    Unless the quote source explicitly proves that reported fee/gas amounts are
    economically excluded from (or included in) the normalized route
    fromAmount/toAmount economics, the state stays EVIDENCE_ONLY_INCLUSION_UNRESOLVED
    and the amounts are never added to execution economics. The R2 boundary
    avoided double counting; R3 preserves that boundary by default.
    """

    EVIDENCE_ONLY_INCLUSION_UNRESOLVED = "EVIDENCE_ONLY_INCLUSION_UNRESOLVED"
    SOURCE_PROVEN_INCLUDED = "SOURCE_PROVEN_INCLUDED"
    SOURCE_PROVEN_EXCLUDED = "SOURCE_PROVEN_EXCLUDED"


@dataclass(frozen=True)
class LiquidityComparisonPolicy:
    """Mandatory caller-supplied quote-to-quote temporal coherence policy.

    R3 compares multiple quotes against each other, so quote-pair timing must be
    explicit. There is no default and no hidden threshold inside the engine: no
    liquidity comparison is produced until the caller names the maximum allowed
    quote-pair skew. R2 reference-time coherence remains R2 authority.
    """

    max_quote_pair_skew_seconds: int

    def __post_init__(self) -> None:
        if self.max_quote_pair_skew_seconds <= 0:
            raise ValueError("max_quote_pair_skew_seconds must be positive")


@dataclass(frozen=True)
class RouteSignature:
    """Deterministic ordered route identity built from R0 QuoteEvidence.route.

    Preserves ordered legs as (tool, from_asset, to_asset) at minimum. Raw leg
    amounts may be retained separately as evidence but never determine route
    identity. A changed route is evidence only: R3 does not interpret it as bad
    liquidity and assigns it no penalty score.
    """

    legs: tuple[tuple[str, str, str], ...]

    def canonical_form(self) -> str:
        if not self.legs:
            return "NO_ROUTE_EVIDENCE"
        return "|".join(f"{tool}:{src}>{dst}" for tool, src, dst in self.legs)


def _cost_valid(value: Decimal | None, field_name: str) -> None:
    if value is None:
        return
    if not value.is_finite() or value < 0:
        raise LiquidityComputationError(
            f"{field_name} must be non-negative and finite when present",
            LiquidityStatus.COST_EVIDENCE_INVALID,
        )


@dataclass(frozen=True)
class ProviderCostEvidence:
    """Provider-reported fee/gas evidence normalized against requested notional.

    Evidence only by default: while cost_treatment_state is
    EVIDENCE_ONLY_INCLUSION_UNRESOLVED the normalized bps values are never added
    to execution prices or spreads. reported_cost_bps requires BOTH amounts so a
    missing value is never silently treated as zero.
    """

    requested_notional_usd: Decimal
    fee_cost_usd: Decimal | None
    gas_cost_usd: Decimal | None
    cost_treatment_state: CostTreatmentState = CostTreatmentState.EVIDENCE_ONLY_INCLUSION_UNRESOLVED

    def __post_init__(self) -> None:
        if (
            not self.requested_notional_usd.is_finite()
            or self.requested_notional_usd <= 0
        ):
            raise LiquidityComputationError(
                "requested_notional_usd must be positive and finite",
                LiquidityStatus.COST_EVIDENCE_INVALID,
            )
        _cost_valid(self.fee_cost_usd, "fee_cost_usd")
        _cost_valid(self.gas_cost_usd, "gas_cost_usd")

    @property
    def fee_bps_of_notional(self) -> Decimal | None:
        if self.fee_cost_usd is None:
            return None
        return self.fee_cost_usd / self.requested_notional_usd * Decimal("10000")

    @property
    def gas_bps_of_notional(self) -> Decimal | None:
        if self.gas_cost_usd is None:
            return None
        return self.gas_cost_usd / self.requested_notional_usd * Decimal("10000")

    @property
    def reported_cost_bps(self) -> Decimal | None:
        if self.fee_cost_usd is None or self.gas_cost_usd is None:
            return None
        return (
            (self.fee_cost_usd + self.gas_cost_usd)
            / self.requested_notional_usd
            * Decimal("10000")
        )


@dataclass(frozen=True)
class LiquiditySideSnapshot:
    """Per-side liquidity evidence retained with the exact quote objects used.

    r0_size_impact_bps comes from the canonical R0 helper; directional_gap_delta_bps
    comes from the R2 DirectionalGapObservation authority. The two metrics remain
    distinct and must be allowed to differ numerically.
    """

    side: QuoteSide
    small_quote: ExecutionQuote
    large_quote: ExecutionQuote
    small_gap_observation: DirectionalGapObservation
    large_gap_observation: DirectionalGapObservation
    r0_size_impact_bps: Decimal
    directional_gap_delta_bps: Decimal
    small_route_signature: RouteSignature
    large_route_signature: RouteSignature

    def __post_init__(self) -> None:
        if not self.r0_size_impact_bps.is_finite():
            raise LiquidityComputationError(
                "r0_size_impact_bps must be finite",
                LiquidityStatus.NON_FINITE_ECONOMICS,
            )
        if not self.directional_gap_delta_bps.is_finite():
            raise LiquidityComputationError(
                "directional_gap_delta_bps must be finite",
                LiquidityStatus.NON_FINITE_ECONOMICS,
            )

    @property
    def route_changed(self) -> bool:
        return (
            self.small_route_signature.canonical_form()
            != self.large_route_signature.canonical_form()
        )


@dataclass(frozen=True)
class LiquiditySpreadSnapshot:
    """Executable cross-side quote spread at one notional.

    Computed from independently routed BUY and SELL execution quotes. This is
    not realized slippage and not an order-book bid/ask spread.
    """

    notional_usd: Decimal
    buy_execution_price_usd_per_token: Decimal
    sell_execution_price_usd_per_token: Decimal
    execution_mid_price_usd_per_token: Decimal
    execution_spread_bps: Decimal

    def __post_init__(self) -> None:
        for name in (
            "buy_execution_price_usd_per_token",
            "sell_execution_price_usd_per_token",
            "execution_mid_price_usd_per_token",
        ):
            value = getattr(self, name)
            if not value.is_finite() or value <= 0:
                raise LiquidityComputationError(
                    f"{name} must be positive and finite",
                    LiquidityStatus.NON_FINITE_ECONOMICS,
                )
        if not self.execution_spread_bps.is_finite():
            raise LiquidityComputationError(
                "execution_spread_bps must be finite",
                LiquidityStatus.NON_FINITE_ECONOMICS,
            )


@dataclass(frozen=True)
class LiquidityTemporalEvidence:
    """Quote-to-quote timing evidence for every R3 comparison."""

    policy: LiquidityComparisonPolicy
    quote_pair_skews: tuple[tuple[str, Decimal], ...]
    max_observed_pair_skew_seconds: Decimal


@dataclass(frozen=True)
class LiquidityLineage:
    """Authority and provenance lineage for one R3 snapshot.

    The boundary declarations are structural: R3 does not classify reference
    state (R4), does not emit signals (R5) and is not a terminal surface (R6).
    """

    r0_formula_authority: str
    r2_observation_authority: str
    r1_canonical_identity: str
    quote_source: str
    git_head: str
    produced_at: datetime
    reference_state_authority: str = "R4_NOT_YET_APPLIED"
    signal_authority: str = "R5_NOT_YET_APPLIED"
    terminal_authority: str = "R6_NOT_YET_APPLIED"

    def __post_init__(self) -> None:
        if self.produced_at.tzinfo is None:
            raise LiquidityComputationError(
                "produced_at must be timezone-aware",
                LiquidityStatus.EVIDENCE_TIME_MISMATCH,
            )


@dataclass(frozen=True)
class LiquiditySnapshot:
    """Successful R3 output: liquidity evidence and typed analytics.

    R3 exposes measurements only. There is no composite liquidity score, no
    HIGH/LOW/GOOD/BAD/graded classification, and no trading signal anywhere in
    the snapshot or its serialization.
    """

    status: LiquidityStatus
    asset_uid: str
    canonical_key: AssetKey
    symbol: str
    small_notional_usd: Decimal
    large_notional_usd: Decimal
    buy: LiquiditySideSnapshot
    sell: LiquiditySideSnapshot
    spread_small: LiquiditySpreadSnapshot
    spread_large: LiquiditySpreadSnapshot
    spread_delta_bps: Decimal
    cost_evidence: tuple[ProviderCostEvidence, ...]
    temporal: LiquidityTemporalEvidence
    lineage: LiquidityLineage

    def __post_init__(self) -> None:
        if self.status is not LiquidityStatus.LIQUIDITY_OK:
            raise LiquidityComputationError(
                "a LiquiditySnapshot is only produced for LIQUIDITY_OK; "
                "failures travel as typed LiquidityComputationError",
                LiquidityStatus.NON_FINITE_ECONOMICS,
            )
        if not self.spread_delta_bps.is_finite():
            raise LiquidityComputationError(
                "spread_delta_bps must be finite",
                LiquidityStatus.NON_FINITE_ECONOMICS,
            )
        if len(self.cost_evidence) != 4:
            raise LiquidityComputationError(
                "cost evidence must cover exactly the four quote slots",
                LiquidityStatus.QUOTE_MATRIX_INCOMPLETE,
            )

    def _quote_evidence_dict(self, label: str, quote: ExecutionQuote) -> dict[str, Any]:
        settlement = quote.settlement_reference
        route_legs: list[dict[str, Any]] = []
        if quote.evidence is not None:
            route_legs = [
                {
                    "tool": str(leg.tool),
                    "fromAsset": str(leg.from_asset),
                    "toAsset": str(leg.to_asset),
                    "fromAmountRaw": leg.from_amount_raw,
                    "toAmountRaw": leg.to_amount_raw,
                }
                for leg in quote.evidence.route
            ]
        return {
            "slot": label,
            "status": quote.status.value,
            "side": quote.side.value,
            "requestedNotionalUsd": str(quote.requested_notional_usd),
            "normalizedAmountIn": (
                str(quote.normalized_amount_in)
                if quote.normalized_amount_in is not None
                else None
            ),
            "normalizedAmountOut": (
                str(quote.normalized_amount_out)
                if quote.normalized_amount_out is not None
                else None
            ),
            "source": quote.source,
            "quotedAt": quote.quoted_at.isoformat(),
            "feeCostUsd": str(quote.fee_cost_usd) if quote.fee_cost_usd is not None else None,
            "gasCostUsd": str(quote.gas_cost_usd) if quote.gas_cost_usd is not None else None,
            "routeLegs": route_legs,
            "settlementEvidence": {
                "chainId": settlement.asset.chain_id,
                "contractAddress": settlement.asset.contract_address,
                "symbol": settlement.asset.symbol,
                "decimals": settlement.asset.decimals,
                "usdPerAsset": (
                    str(settlement.usd_per_asset) if settlement.usd_per_asset is not None else None
                ),
                "state": settlement.state.value,
                "source": settlement.source,
                "observedAt": (
                    settlement.observed_at.isoformat()
                    if settlement.observed_at is not None
                    else None
                ),
            },
        }

    def to_evidence_dict(self) -> dict[str, Any]:
        """Full reconstructible serialization; camelCase keys per R3 contract."""
        quote_labels = (
            ("BUY_100", self.buy.small_quote),
            ("BUY_1000", self.buy.large_quote),
            ("SELL_100", self.sell.small_quote),
            ("SELL_1000", self.sell.large_quote),
        )
        cost_labels = (
            (QuoteSide.BUY, self.small_notional_usd),
            (QuoteSide.BUY, self.large_notional_usd),
            (QuoteSide.SELL, self.small_notional_usd),
            (QuoteSide.SELL, self.large_notional_usd),
        )
        return {
            "status": self.status.value,
            "asset": {
                "assetUid": self.asset_uid,
                "canonicalKey": self.canonical_key.canonical_id,
                "symbol": self.symbol,
                "chainId": self.canonical_key.chain_id,
                "contractAddress": self.canonical_key.contract_address,
            },
            "observationNotionals": {
                "smallNotionalUsd": str(self.small_notional_usd),
                "largeNotionalUsd": str(self.large_notional_usd),
            },
            "sizeImpactEvidence": {
                "buySizeImpactBps": str(self.buy.r0_size_impact_bps),
                "sellSizeImpactBps": str(self.sell.r0_size_impact_bps),
                "authority": R0_FORMULA_AUTHORITY,
                "semantics": (
                    "Canonical R0 router-level quote-rate delta over the same $100/$1,000 "
                    "quote pair used for every R3 metric. Positive = larger quote has a worse "
                    "output/input rate; may include route switching; not realized slippage "
                    "and not same-pool AMM depth. R3 consumes the metric; it does not "
                    "redefine it."
                ),
            },
            "gapEvidence": {
                "buyGapBpsAt100": str(self.buy.small_gap_observation.gap_bps),
                "buyGapBpsAt1000": str(self.buy.large_gap_observation.gap_bps),
                "sellGapBpsAt100": str(self.sell.small_gap_observation.gap_bps),
                "sellGapBpsAt1000": str(self.sell.large_gap_observation.gap_bps),
                "buyDirectionalGapDeltaBps": str(self.buy.directional_gap_delta_bps),
                "buyDeltaInterpretation": BUY_DELTA_INTERPRETATION,
                "sellDirectionalGapDeltaBps": str(self.sell.directional_gap_delta_bps),
                "sellDeltaInterpretation": SELL_DELTA_INTERPRETATION,
                "authority": R2_OBSERVATION_AUTHORITY,
            },
            "spreadEvidence": {
                "at100": {
                    "buyExecutionPriceUsdPerToken": str(
                        self.spread_small.buy_execution_price_usd_per_token
                    ),
                    "sellExecutionPriceUsdPerToken": str(
                        self.spread_small.sell_execution_price_usd_per_token
                    ),
                    "executionMidPriceUsdPerToken": str(
                        self.spread_small.execution_mid_price_usd_per_token
                    ),
                    "executionSpreadBps": str(self.spread_small.execution_spread_bps),
                },
                "at1000": {
                    "buyExecutionPriceUsdPerToken": str(
                        self.spread_large.buy_execution_price_usd_per_token
                    ),
                    "sellExecutionPriceUsdPerToken": str(
                        self.spread_large.sell_execution_price_usd_per_token
                    ),
                    "executionMidPriceUsdPerToken": str(
                        self.spread_large.execution_mid_price_usd_per_token
                    ),
                    "executionSpreadBps": str(self.spread_large.execution_spread_bps),
                },
                "executionSpreadDeltaBps": str(self.spread_delta_bps),
                "semantics": (
                    "Executable cross-side quote spread from independently routed BUY and "
                    "SELL execution quotes: ((P_buy - P_sell) / P_exec_mid) * 10000. It is "
                    "not realized slippage and not an order-book bid/ask spread."
                ),
            },
            "routeEvidence": {
                "buy": {
                    "smallRouteSignature": self.buy.small_route_signature.canonical_form(),
                    "largeRouteSignature": self.buy.large_route_signature.canonical_form(),
                    "buyRouteChanged": self.buy.route_changed,
                },
                "sell": {
                    "smallRouteSignature": self.sell.small_route_signature.canonical_form(),
                    "largeRouteSignature": self.sell.large_route_signature.canonical_form(),
                    "sellRouteChanged": self.sell.route_changed,
                },
                "semantics": (
                    "Deterministic ordered (tool, from, to) route identities from R0 "
                    "QuoteEvidence.route. A changed route is evidence only: it is not "
                    "automatically poor liquidity and carries no penalty score."
                ),
            },
            "costEvidence": [
                {
                    "side": side.value,
                    "requestedNotionalUsd": str(notional),
                    "feeCostUsd": (
                        str(item.fee_cost_usd) if item.fee_cost_usd is not None else None
                    ),
                    "gasCostUsd": (
                        str(item.gas_cost_usd) if item.gas_cost_usd is not None else None
                    ),
                    "feeBpsOfNotional": (
                        str(item.fee_bps_of_notional)
                        if item.fee_bps_of_notional is not None
                        else None
                    ),
                    "gasBpsOfNotional": (
                        str(item.gas_bps_of_notional)
                        if item.gas_bps_of_notional is not None
                        else None
                    ),
                    "reportedCostBps": (
                        str(item.reported_cost_bps)
                        if item.reported_cost_bps is not None
                        else None
                    ),
                    "costTreatmentState": item.cost_treatment_state.value,
                }
                for (side, notional), item in zip(cost_labels, self.cost_evidence)
            ],
            "costSemantics": (
                "Provider-reported fee/gas amounts are evidence normalized against the "
                "requested notional. Default cost-treatment state is "
                "EVIDENCE_ONLY_INCLUSION_UNRESOLVED: unresolved amounts are never added to "
                "execution prices or spreads (no double counting). SOURCE_PROVEN_* states "
                "require explicit source proof of economic inclusion or exclusion."
            ),
            "temporalEvidence": {
                "policy": {
                    "maxQuotePairSkewSeconds": self.temporal.policy.max_quote_pair_skew_seconds,
                    "authority": "R3_QUOTE_TO_QUOTE_COMPARISON_COHERENCE_ONLY",
                },
                "quoteTimestamps": {
                    label: quote.quoted_at.isoformat() for label, quote in quote_labels
                },
                "observedPairSkews": {
                    label: str(skew) for label, skew in self.temporal.quote_pair_skews
                },
                "maxObservedPairSkewSeconds": str(
                    self.temporal.max_observed_pair_skew_seconds
                ),
            },
            "quoteMatrixEvidence": [
                self._quote_evidence_dict(label, quote) for label, quote in quote_labels
            ],
            "lineage": {
                "r0FormulaAuthority": self.lineage.r0_formula_authority,
                "r2ObservationAuthority": self.lineage.r2_observation_authority,
                "r1CanonicalIdentity": self.lineage.r1_canonical_identity,
                "quoteSource": self.lineage.quote_source,
                "gitHead": self.lineage.git_head,
                "producedAt": self.lineage.produced_at.isoformat(),
            },
            "boundaries": {
                "referenceStateAuthority": self.lineage.reference_state_authority,
                "signalAuthority": self.lineage.signal_authority,
                "terminalAuthority": self.lineage.terminal_authority,
            },
        }
