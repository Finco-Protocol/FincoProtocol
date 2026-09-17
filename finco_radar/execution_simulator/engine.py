"""Deterministic R8 execution-simulation engine.

Converts exact R0/R2/R3 executable evidence into gross execution edge, typed
provider-cost resolution, settlement adjustments and a completeness-typed net
executable edge. Consumes — never redefines — frozen R2 GAP semantics, and
never deducts R0 size impact twice (it is diagnostic evidence only).

READ-ONLY pre-trade simulation: no transaction preparation, no wallet,
no recommendations, no R8→profit claims beyond the typed states themselves.
"""
from __future__ import annotations

import hashlib
from datetime import datetime
from decimal import Decimal
from typing import Any, Mapping, Sequence

from finco_radar.assets.contracts import AssetKey
from finco_radar.liquidity.contracts import CostTreatmentState
from finco_radar.quotes.contracts import QuoteSide

from .contracts import (
    RECONSTRUCTION_TOLERANCE_BPS,
    ExecutionMode,
    ExecutionScenario,
    ExecutionSimulationError,
    ExecutionSimulationResult,
    ExecutionSimulationSnapshot,
    ExecutionSimulationStatus,
    GrossExecutionEconomics,
    NetEdgeBlocker,
    NetEdgeState,
    ProviderCostResolution,
    ScenarioQuoteEvidence,
    ClosedLoopState,
    SettlementAdjustmentEvidence,
    SettlementAdjustmentState,
    SettlementResolution,
    SimulationTimingPolicy,
    _scenario_order,
    SizeSensitivity,
    _require_aware,
    canonical_evidence_bytes,
    compute_snapshot_digest,
)


def compute_gross_execution_economics(
    quote_evidence: ScenarioQuoteEvidence,
) -> GrossExecutionEconomics:
    """Exact USD gross execution edge with the mandatory R2 handshake.

    benchmark_value_usd = token_amount x reference_price_usd_per_token
    BUY:  gross_execution_edge_usd = benchmark - settlement_amount_usd
    SELL: gross_execution_edge_usd = settlement_amount_usd - benchmark

    The resulting bps MUST equal the side-correct transformation of the frozen
    R2 gap (BUY = -gap, SELL = +gap) within pure arithmetic-reconstruction
    tolerance; any larger deviation fails closed (UPSTREAM_ECONOMICS_MISMATCH).
    """
    evidence = quote_evidence
    benchmark = evidence.token_amount * evidence.reference_price_usd_per_token
    if not benchmark.is_finite() or benchmark <= 0:
        raise ExecutionSimulationError(
            "benchmark value must be positive and finite",
            ExecutionSimulationStatus.NON_FINITE_ECONOMICS,
        )
    if evidence.side is QuoteSide.BUY:
        gross_usd = benchmark - evidence.settlement_amount_usd
        side_adjusted_gap = -evidence.r2_gap_bps
    else:
        gross_usd = evidence.settlement_amount_usd - benchmark
        side_adjusted_gap = evidence.r2_gap_bps
    gross_bps = gross_usd / benchmark * Decimal(10000)
    if abs(gross_bps - side_adjusted_gap) > RECONSTRUCTION_TOLERANCE_BPS:
        raise ExecutionSimulationError(
            f"R2 economics handshake failed: computed gross {gross_bps} bps vs "
            f"side-adjusted R2 gap {side_adjusted_gap} bps",
            ExecutionSimulationStatus.UPSTREAM_ECONOMICS_MISMATCH,
        )
    return GrossExecutionEconomics(
        benchmark_value_usd=benchmark,
        settlement_amount_usd=evidence.settlement_amount_usd,
        token_amount=evidence.token_amount,
        reference_price_usd_per_token=evidence.reference_price_usd_per_token,
        r2_gap_bps=evidence.r2_gap_bps,
        gross_execution_edge_usd=gross_usd,
        gross_execution_edge_bps=gross_bps,
        side_adjusted_gap_bps=side_adjusted_gap,
    )


def resolve_provider_costs(
    quote_evidence: ScenarioQuoteEvidence,
) -> ProviderCostResolution:
    """Typed provider-cost resolution. Never guesses; never treats absent as zero.

    SOURCE_PROVEN_INCLUDED -> incremental 0 (already inside the quote amounts;
        never subtracted again).
    SOURCE_PROVEN_EXCLUDED -> incremental = fee + gas; both amounts required,
        otherwise COST_EVIDENCE_INCOMPLETE.
    EVIDENCE_ONLY_INCLUSION_UNRESOLVED -> incremental None; the net edge must
        remain unavailable (COST_TREATMENT_UNRESOLVED).
    """
    treatment = quote_evidence.provider_cost_treatment
    fee, gas = quote_evidence.provider_fee_usd, quote_evidence.provider_gas_usd
    if treatment is CostTreatmentState.SOURCE_PROVEN_INCLUDED:
        return ProviderCostResolution(
            treatment=treatment,
            provider_fee_usd=fee,
            provider_gas_usd=gas,
            provider_incremental_cost_usd=Decimal(0),
            state=ExecutionSimulationStatus.EXECUTION_SIMULATION_OK,
        )
    if treatment is CostTreatmentState.SOURCE_PROVEN_EXCLUDED:
        if fee is None or gas is None:
            return ProviderCostResolution(
                treatment=treatment,
                provider_fee_usd=fee,
                provider_gas_usd=gas,
                provider_incremental_cost_usd=None,
                state=ExecutionSimulationStatus.COST_EVIDENCE_INCOMPLETE,
            )
        return ProviderCostResolution(
            treatment=treatment,
            provider_fee_usd=fee,
            provider_gas_usd=gas,
            provider_incremental_cost_usd=fee + gas,
            state=ExecutionSimulationStatus.EXECUTION_SIMULATION_OK,
        )
    # EVIDENCE_ONLY_INCLUSION_UNRESOLVED: evidence only — never added,
    # never subtracted, never treated as zero.
    return ProviderCostResolution(
        treatment=treatment,
        provider_fee_usd=fee,
        provider_gas_usd=gas,
        provider_incremental_cost_usd=None,
        state=ExecutionSimulationStatus.COST_TREATMENT_UNRESOLVED,
    )


def resolve_settlement_adjustment(
    adjustment: SettlementAdjustmentEvidence | None,
    *,
    as_of: datetime,
    policy: SimulationTimingPolicy,
) -> SettlementResolution:
    """Typed settlement-adjustment resolution. Context, never invented costs.

    NOT_REQUIRED / SOURCE_PROVEN_INCLUDED -> incremental 0.
    SOURCE_PROVEN_EXCLUDED -> incremental = amount_usd (must be present).
    UNAVAILABLE / UNRESOLVED / STALE -> incremental None (net stays partial).
    A stale or future adjustment cannot authorize a settlement deduction.
    """
    if adjustment is None:
        return SettlementResolution(
            adjustment=None,
            settlement_incremental_cost_usd=None,
            state=ExecutionSimulationStatus.SETTLEMENT_ADJUSTMENT_UNAVAILABLE,
        )
    # Correction A (F3): materially distinct causes never collapse.
    #   UNRESOLVED  -> SETTLEMENT_ADJUSTMENT_UNRESOLVED
    #   UNAVAILABLE -> SETTLEMENT_ADJUSTMENT_UNAVAILABLE
    #   STALE       -> TIMING_INVALID
    # Every state capable of resolving net economics (NOT_REQUIRED,
    # SOURCE_PROVEN_INCLUDED, SOURCE_PROVEN_EXCLUDED) requires auditable
    # timing evidence: a timezone-aware observed_at. A source-proven excluded
    # adjustment with an amount but no valid timestamp must NOT authorize the
    # deduction. A future or stale timestamp fails closed (TIMING_INVALID).
    state = adjustment.state
    resolving_timing = None
    if state in (
        SettlementAdjustmentState.NOT_REQUIRED,
        SettlementAdjustmentState.SOURCE_PROVEN_INCLUDED,
        SettlementAdjustmentState.SOURCE_PROVEN_EXCLUDED,
    ):
        if adjustment.observed_at is None:
            return SettlementResolution(
                adjustment=adjustment,
                settlement_incremental_cost_usd=None,
                state=ExecutionSimulationStatus.TIMING_INVALID,
            )
        _require_aware(adjustment.observed_at, "settlement adjustment observed_at")
        age = Decimal(str((as_of - adjustment.observed_at).total_seconds()))
        if age < 0 or age > policy.max_settlement_evidence_age_seconds:
            return SettlementResolution(
                adjustment=adjustment,
                settlement_incremental_cost_usd=None,
                state=ExecutionSimulationStatus.TIMING_INVALID,
            )
    if state is SettlementAdjustmentState.NOT_REQUIRED:
        resolving_timing = Decimal(0)
    elif state is SettlementAdjustmentState.SOURCE_PROVEN_INCLUDED:
        resolving_timing = Decimal(0)
    elif state is SettlementAdjustmentState.SOURCE_PROVEN_EXCLUDED:
        if adjustment.amount_usd is None:
            return SettlementResolution(
                adjustment=adjustment,
                settlement_incremental_cost_usd=None,
                state=ExecutionSimulationStatus.COST_EVIDENCE_INCOMPLETE,
            )
        resolving_timing = adjustment.amount_usd
    elif state is SettlementAdjustmentState.UNAVAILABLE:
        return SettlementResolution(
            adjustment=adjustment,
            settlement_incremental_cost_usd=None,
            state=ExecutionSimulationStatus.SETTLEMENT_ADJUSTMENT_UNAVAILABLE,
        )
    elif state is SettlementAdjustmentState.STALE:
        return SettlementResolution(
            adjustment=adjustment,
            settlement_incremental_cost_usd=None,
            state=ExecutionSimulationStatus.TIMING_INVALID,
        )
    else:
        # Unknown/forward state: conservative unresolved.
        return SettlementResolution(
            adjustment=adjustment,
            settlement_incremental_cost_usd=None,
            state=ExecutionSimulationStatus.SETTLEMENT_ADJUSTMENT_UNRESOLVED,
        )
    return SettlementResolution(
        adjustment=adjustment,
        settlement_incremental_cost_usd=resolving_timing,
        state=ExecutionSimulationStatus.EXECUTION_SIMULATION_OK,
    )


def _settlement_timing_blockers(
    adjustment: SettlementAdjustmentEvidence | None,
    *,
    as_of: datetime,
    policy: SimulationTimingPolicy,
) -> list[ExecutionSimulationStatus]:
    """Fail-closed timing for R8-only settlement evidence (never invents data)."""
    if adjustment is None or adjustment.observed_at is None:
        return []
    _require_aware(adjustment.observed_at, "settlement adjustment observed_at")
    age = Decimal(str((as_of - adjustment.observed_at).total_seconds()))
    blockers: list[ExecutionSimulationStatus] = []
    if age < 0:
        # A future observation is never fresh evidence.
        blockers.append(ExecutionSimulationStatus.TIMING_INVALID)
    if age > policy.max_settlement_evidence_age_seconds:
        # Stale settlement evidence cannot authorize a deduction, whatever its
        # declared state.
        blockers.append(ExecutionSimulationStatus.TIMING_INVALID)
    return blockers


def _cost_timing_blockers(
    quote_evidence: ScenarioQuoteEvidence,
    *,
    as_of: datetime,
    policy: SimulationTimingPolicy,
) -> list[ExecutionSimulationStatus]:
    """Cost evidence must not be stale relative to the evaluation instant."""
    blockers: list[ExecutionSimulationStatus] = []
    if quote_evidence.provider_fee_usd is not None or quote_evidence.provider_gas_usd is not None:
        age = Decimal(str((as_of - quote_evidence.quote_observed_at).total_seconds()))
        if age < 0 or age > policy.max_cost_evidence_age_seconds:
            blockers.append(ExecutionSimulationStatus.TIMING_INVALID)
    return blockers


def simulate_execution_scenario(
    *,
    scenario: ExecutionScenario,
    quote_evidence: ScenarioQuoteEvidence,
    settlement_adjustment: SettlementAdjustmentEvidence | None = None,
    policy: SimulationTimingPolicy,
    theoretical_dislocation_bps: Decimal | None = None,
) -> ExecutionSimulationResult:
    """Simulate exactly one executable scenario, or raise a typed error."""
    if scenario.side is not quote_evidence.side:
        raise ExecutionSimulationError(
            "scenario side does not match the bound quote evidence side",
            ExecutionSimulationStatus.R3_LINEAGE_MISMATCH,
        )
    if scenario.requested_notional_usd != quote_evidence.requested_notional_usd:
        raise ExecutionSimulationError(
            f"no exact executable quote for notional {scenario.requested_notional_usd}: "
            f"bound evidence covers {quote_evidence.requested_notional_usd}",
            ExecutionSimulationStatus.EXECUTION_QUOTE_UNAVAILABLE,
        )
    if scenario.canonical_asset_key != quote_evidence.canonical_asset_key:
        raise ExecutionSimulationError(
            "scenario canonical asset key does not match the bound quote evidence",
            ExecutionSimulationStatus.IDENTITY_MISMATCH,
        )
    if scenario.execution_mode is ExecutionMode.CLOSED_LOOP:
        raise ExecutionSimulationError(
            "CLOSED_LOOP execution is not proven by the available evidence; "
            "reference-relative simulation only",
            ExecutionSimulationStatus.CLOSED_LOOP_NOT_PROVEN,
        )
    if theoretical_dislocation_bps is not None and not theoretical_dislocation_bps.is_finite():
        raise ExecutionSimulationError(
            "theoretical dislocation must be finite when supplied",
            ExecutionSimulationStatus.NON_FINITE_ECONOMICS,
        )

    cost_timing_blockers = _cost_timing_blockers(
        quote_evidence, as_of=scenario.as_of, policy=policy
    )
    settlement_timing_blockers = _settlement_timing_blockers(
        settlement_adjustment, as_of=scenario.as_of, policy=policy
    )
    timing_blockers: list[ExecutionSimulationStatus] = list(cost_timing_blockers)
    timing_blockers.extend(settlement_timing_blockers)

    gross = compute_gross_execution_economics(quote_evidence)
    provider = resolve_provider_costs(quote_evidence)
    settlement = resolve_settlement_adjustment(
        settlement_adjustment, as_of=scenario.as_of, policy=policy
    )
    # Correction B discipline: timing-invalid evidence is retained as evidence
    # but can never contribute a resolved value to the net edge.
    from dataclasses import replace as _replace

    if cost_timing_blockers:
        provider = _replace(provider, provider_incremental_cost_usd=None)
    if settlement_timing_blockers:
        settlement = _replace(settlement, settlement_incremental_cost_usd=None)

    blockers: list[ExecutionSimulationStatus] = []
    if provider.provider_incremental_cost_usd is None:
        blockers.append(
            ExecutionSimulationStatus.TIMING_INVALID
            if cost_timing_blockers
            else provider.state
        )
    if settlement.settlement_incremental_cost_usd is None:
        # The resolver's typed status carries the materially distinct cause
        # (UNRESOLVED / UNAVAILABLE / TIMING_INVALID) — never collapsed.
        blockers.append(settlement.state)
    blockers.extend(timing_blockers)

    unique_blockers = tuple(
        blocker
        for blocker in dict.fromkeys(blockers)
        if blocker is not ExecutionSimulationStatus.EXECUTION_SIMULATION_OK
    )

    if provider.provider_incremental_cost_usd is not None and (
        settlement.settlement_incremental_cost_usd is not None
    ):
        net_edge_state = NetEdgeState.COMPLETE
        net_usd = (
            gross.gross_execution_edge_usd
            - provider.provider_incremental_cost_usd
            - settlement.settlement_incremental_cost_usd
        )
        net_bps = net_usd / gross.benchmark_value_usd * Decimal(10000)
        if not net_bps.is_finite() or not net_usd.is_finite():
            raise ExecutionSimulationError(
                "net edge economics are not finite",
                ExecutionSimulationStatus.NON_FINITE_ECONOMICS,
            )
        if unique_blockers:
            net_edge_state = NetEdgeState.PARTIAL
    else:
        net_edge_state = NetEdgeState.PARTIAL
        net_usd = None
        net_bps = None

    if not unique_blockers:
        unique_blockers = (ExecutionSimulationStatus.EXECUTION_SIMULATION_OK,)

    return ExecutionSimulationResult(
        status=ExecutionSimulationStatus.EXECUTION_SIMULATION_OK,
        scenario=scenario,
        net_edge_state=net_edge_state,
        net_edge_blockers=unique_blockers,
        theoretical_dislocation_bps=theoretical_dislocation_bps,
        r2_gap_bps=quote_evidence.r2_gap_bps,
        gross_execution_edge_bps=gross.gross_execution_edge_bps,
        gross_execution_edge_usd=gross.gross_execution_edge_usd,
        benchmark_value_usd=gross.benchmark_value_usd,
        provider_fee_usd=quote_evidence.provider_fee_usd,
        provider_gas_usd=quote_evidence.provider_gas_usd,
        provider_cost_treatment=provider.treatment,
        provider_incremental_cost_usd=provider.provider_incremental_cost_usd,
        settlement_adjustment_state=(
            settlement.adjustment.state if settlement.adjustment is not None else None
        ),
        settlement_incremental_cost_usd=settlement.settlement_incremental_cost_usd,
        net_executable_edge_bps=net_bps,
        net_executable_edge_usd=net_usd,
        route_signature=quote_evidence.route_signature,
        route_changed=quote_evidence.route_changed,
        quote_source=scenario.quote_source,
        quote_observed_at=quote_evidence.quote_observed_at,
        reference_generated_at=quote_evidence.reference_generated_at,
        timing_blockers=tuple(timing_blockers),
        r0_quote_evidence=quote_evidence.r0_quote_evidence,
        r2_gap_evidence=quote_evidence.r2_gap_evidence,
    )


def _select_evidence(
    evidence_rows: Sequence[ScenarioQuoteEvidence],
    *,
    scenario: ExecutionScenario,
) -> ScenarioQuoteEvidence:
    """Exact-match lookup. Never interpolated, never estimated.

    Correction A (F1): the venue/quote source is part of the evidence
    identity. A scenario claiming venue/source B must never consume evidence
    from venue/source A. Selection is deterministic: side + notional filter,
    then exact venue match; a canonical-key conflict on the exact slot fails
    closed with IDENTITY_MISMATCH instead of silently consuming foreign
    evidence. With no exact match the result is EXECUTION_QUOTE_UNAVAILABLE.
    """
    same_side_notional = [
        row
        for row in evidence_rows
        if row.side is scenario.side
        and row.requested_notional_usd == scenario.requested_notional_usd
    ]
    if not same_side_notional:
        raise ExecutionSimulationError(
            f"no exact executable quote evidence for {scenario.side.value} "
            f"{scenario.requested_notional_usd} USD",
            ExecutionSimulationStatus.EXECUTION_QUOTE_UNAVAILABLE,
        )
    venue_matched = [
        row for row in same_side_notional if row.venue == scenario.quote_source
    ]
    if not venue_matched:
        raise ExecutionSimulationError(
            f"no exact executable quote evidence from quote source "
            f"{scenario.quote_source} for {scenario.side.value} "
            f"{scenario.requested_notional_usd} USD",
            ExecutionSimulationStatus.EXECUTION_QUOTE_UNAVAILABLE,
        )
    for row in venue_matched:
        if row.canonical_asset_key != scenario.canonical_asset_key:
            raise ExecutionSimulationError(
                "evidence canonical asset key does not match the scenario "
                "canonical asset key",
                ExecutionSimulationStatus.IDENTITY_MISMATCH,
            )
    if len(venue_matched) > 1:
        raise ExecutionSimulationError(
            "ambiguous duplicate evidence rows for the same venue/side/notional",
            ExecutionSimulationStatus.INPUT_INVALID,
        )
    return venue_matched[0]


def build_execution_simulation(
    *,
    economic_asset_uid: str,
    canonical_asset_key: AssetKey,
    scenarios: Sequence[ExecutionScenario],
    quote_evidence: Sequence[ScenarioQuoteEvidence],
    settlement_adjustment: SettlementAdjustmentEvidence | None = None,
    policy: SimulationTimingPolicy,
    theoretical_dislocations: dict[str, Decimal] | None = None,
    r7_snapshot_digest: str | None = None,
    upstream_evidence: dict | None = None,
    source_digests: dict | None = None,
    synthetic: bool = False,
    generated_at: datetime | None = None,
    git_head: str = "UNKNOWN",
) -> ExecutionSimulationSnapshot:
    """Build the deterministic R8 simulation snapshot, or raise typed errors.

    Correction B lineage discipline applied from initial implementation: any
    embedded upstream evidence must reconstruct its recorded source digest,
    and the R7 snapshot digest (when supplied) must be bound to the supplied
    component labels.
    """
    if r7_snapshot_digest is not None:
        if not r7_snapshot_digest.strip():
            raise ExecutionSimulationError(
                "R7 snapshot digest must be non-empty when supplied",
                ExecutionSimulationStatus.R7_LINEAGE_MISMATCH,
            )

    # Correction A (F1): snapshot-level identity binding for every scenario.
    for entered in scenarios:
        if entered.economic_asset_uid != economic_asset_uid:
            raise ExecutionSimulationError(
                "scenario economic asset UID does not match the snapshot "
                "economic asset UID",
                ExecutionSimulationStatus.IDENTITY_MISMATCH,
            )
        if entered.canonical_asset_key != canonical_asset_key:
            raise ExecutionSimulationError(
                "scenario canonical asset key does not match the snapshot "
                "canonical asset key",
                ExecutionSimulationStatus.IDENTITY_MISMATCH,
            )

    embedded = upstream_evidence or {}
    supplied_digests = source_digests or {}
    # Correction B lesson applied from initial implementation: every embedded
    # upstream evidence must reconstruct its recorded digest, and the core
    # R7/R3 lineage bindings are required, never optional.
    lineage_pairs = (
        ("r7CrossMarketDigest", "r7CrossMarketEvidence", True,
         ExecutionSimulationStatus.R7_LINEAGE_MISMATCH),
        ("r3LiquidityDigest", "r3LiquidityEvidence", True,
         ExecutionSimulationStatus.R3_LINEAGE_MISMATCH),
        ("r2GapEvidenceDigest", "r2GapEvidence", False,
         ExecutionSimulationStatus.R2_ECONOMICS_MISMATCH),
        ("r0QuoteEvidenceDigest", "r0QuoteEvidence", False,
         ExecutionSimulationStatus.R3_LINEAGE_MISMATCH),
    )
    # Pass 1: any SUPPLIED pair must be internally consistent (fail closed on
    # mismatch or one-sided lineage), checked per pair in canonical order.
    for digest_name, evidence_key, _required, mismatch_status in lineage_pairs:
        embedded_evidence = embedded.get(evidence_key)
        supplied = supplied_digests.get(digest_name)
        if embedded_evidence is None and supplied is None:
            continue
        if embedded_evidence is None or supplied is None:
            raise ExecutionSimulationError(
                f"incomplete upstream lineage pair for {digest_name}",
                mismatch_status,
            )
        recomputed = hashlib.sha256(canonical_evidence_bytes(embedded_evidence)).hexdigest()
        if recomputed != supplied:
            raise ExecutionSimulationError(
                f"{digest_name} does not match the canonical digest of the "
                f"embedded {evidence_key}",
                mismatch_status,
            )
    # Pass 2: the core R7/R3 lineage bindings are required for canonical R8
    # evidence (spec §23) and may never be silently omitted.
    for digest_name, evidence_key, required, mismatch_status in lineage_pairs:
        if not required:
            continue
        if embedded.get(evidence_key) is None or supplied_digests.get(digest_name) is None:
            raise ExecutionSimulationError(
                f"missing required upstream lineage: {digest_name} / {evidence_key}",
                mismatch_status,
            )

    # Correction A (F2): the embedded (digest-bound) R7 evidence is the SOLE
    # authority for component labels. Its own internal r7SnapshotDigest must
    # reconstruct under the frozen R7 verifier, the supplied r7_snapshot_digest
    # must equal it, and every scenario/theoretical label must exist among the
    # embedded dislocation components. A fake label, a wrong internal digest or
    # an inconsistent caller label set can never be legitimized by the outer
    # r8SnapshotDigest.
    embedded_r7 = embedded.get("r7CrossMarketEvidence")
    from finco_radar.cross_market.contracts import verify_serialized_evidence as _verify_r7

    if not isinstance(embedded_r7, Mapping) or not _verify_r7(embedded_r7):
        raise ExecutionSimulationError(
            "embedded R7 cross-market evidence does not reconstruct its own "
            "r7SnapshotDigest",
            ExecutionSimulationStatus.R7_LINEAGE_MISMATCH,
        )
    embedded_r7_internal_digest = embedded_r7.get("r7SnapshotDigest")
    if (
        r7_snapshot_digest is not None
        and r7_snapshot_digest != embedded_r7_internal_digest
    ):
        raise ExecutionSimulationError(
            "supplied r7_snapshot_digest differs from the embedded R7 evidence's "
            "internal r7SnapshotDigest",
            ExecutionSimulationStatus.R7_LINEAGE_MISMATCH,
        )
    # Correction B: canonical label -> deltaBps mapping derived ONLY from the
    # digest-verified embedded R7 evidence. Caller-supplied theoretical values
    # are treated as redundant evidence requiring exact equality.
    embedded_theoretical: dict[str, Decimal] = {}
    for component in embedded_r7.get("dislocationComponents", []):
        if not isinstance(component, Mapping):
            continue
        label = component.get("label")
        if not label:
            continue
        raw = component.get("deltaBps")
        embedded_theoretical[label] = (
            Decimal(str(raw)) if raw is not None else None
        )

    # Correction B (1): the embedded R7 snapshot must belong to THIS economic
    # asset and must list THIS canonical deployment exactly once.
    embedded_r7_uid = embedded_r7.get("economicAssetUid")
    if embedded_r7_uid != economic_asset_uid:
        raise ExecutionSimulationError(
            f"embedded R7 economicAssetUid {embedded_r7_uid} does not match the "
            f"R8 economic asset UID {economic_asset_uid}",
            ExecutionSimulationStatus.R7_LINEAGE_MISMATCH,
        )
    identity_binding = embedded_r7.get("identityBinding") or {}
    embedded_keys = identity_binding.get("canonicalKeys") or []
    target_chain = canonical_asset_key.chain_id
    target_address = canonical_asset_key.contract_address
    key_matches = 0
    for entry in embedded_keys:
        if not isinstance(entry, Mapping):
            continue
        if (
            entry.get("chainId") == target_chain
            and str(entry.get("contractAddress", "")).lower()
            == target_address
        ):
            key_matches += 1
    if key_matches != 1:
        raise ExecutionSimulationError(
            f"embedded R7 canonical keys list this R8 deployment {key_matches} "
            "times (expected exactly once)",
            ExecutionSimulationStatus.R7_LINEAGE_MISMATCH,
        )
    for entered in scenarios:
        label = entered.r7_component_label
        if label is not None and label not in embedded_theoretical:
            raise ExecutionSimulationError(
                f"scenario r7_component_label not present in the embedded R7 "
                f"evidence components: {label}",
                ExecutionSimulationStatus.R7_LINEAGE_MISMATCH,
            )
    for theo_label in (theoretical_dislocations or {}):
        if theo_label not in embedded_theoretical:
            raise ExecutionSimulationError(
                f"theoretical dislocation label not present in the embedded R7 "
                f"evidence components: {theo_label}",
                ExecutionSimulationStatus.R7_LINEAGE_MISMATCH,
            )

    # Correction B (3): bind the embedded R3 canonical deployment to R8. The
    # R3 digest being cryptographically valid is not sufficient if it belongs
    # to another asset; R3 assetUid is a different namespace from the R7/R8
    # economic UID and is never compared to it.
    embedded_r3 = embedded.get("r3LiquidityEvidence")
    if isinstance(embedded_r3, Mapping):
        asset_block = embedded_r3.get("asset")
        if not isinstance(asset_block, Mapping):
            raise ExecutionSimulationError(
                "embedded R3 liquidity evidence is missing its canonical asset block",
                ExecutionSimulationStatus.R3_LINEAGE_MISMATCH,
            )
        embedded_chain = asset_block.get("chainId")
        embedded_address = str(asset_block.get("contractAddress", "")).lower()
        if embedded_chain != canonical_asset_key.chain_id or (
            embedded_address != canonical_asset_key.contract_address
        ):
            raise ExecutionSimulationError(
                "embedded R3 liquidity evidence belongs to a different canonical "
                f"deployment: {embedded_chain}:{embedded_address}",
                ExecutionSimulationStatus.R3_LINEAGE_MISMATCH,
            )
        embedded_canonical_key = asset_block.get("canonicalKey")
        if embedded_canonical_key is not None and (
            str(embedded_canonical_key)
            != canonical_asset_key.canonical_id
        ):
            raise ExecutionSimulationError(
                "embedded R3 canonicalKey disagrees with its own chainId/"
                "contractAddress pair",
                ExecutionSimulationStatus.R3_LINEAGE_MISMATCH,
            )

    results: list[ExecutionSimulationResult] = []
    for scenario in scenarios:
        row = _select_evidence(quote_evidence, scenario=scenario)
        label = scenario.r7_component_label
        # Correction B (2): the theoretical value is DERIVED from the
        # digest-verified embedded R7 evidence — never trusted from the
        # caller. A caller-supplied value is treated as redundant evidence
        # requiring exact Decimal equality with the embedded component.
        theo = None
        if label is not None and label in embedded_theoretical:
            theo = embedded_theoretical[label]
        supplied = (theoretical_dislocations or {}).get(label)
        if supplied is not None:
            if theo is None or supplied != theo:
                raise ExecutionSimulationError(
                    f"caller theoretical dislocation {supplied} does not equal "
                    f"the embedded R7 component deltaBps {theo} for label {label}",
                    ExecutionSimulationStatus.R7_LINEAGE_MISMATCH,
                )
        results.append(
            simulate_execution_scenario(
                scenario=scenario,
                quote_evidence=row,
                settlement_adjustment=settlement_adjustment,
                policy=policy,
                theoretical_dislocation_bps=theo,
            )
        )
    ordered_results = tuple(sorted(results, key=_result_order))

    sensitivity = _size_sensitivity(ordered_results)

    snapshot = ExecutionSimulationSnapshot(
        status=ExecutionSimulationStatus.EXECUTION_SIMULATION_OK,
        economic_asset_uid=economic_asset_uid,
        canonical_asset_key=canonical_asset_key,
        scenarios=ordered_results,
        size_sensitivity=sensitivity,
        closed_loop_state=ClosedLoopState.CLOSED_LOOP_NOT_PROVEN,
        simulation_policy=policy,
        upstream_evidence=embedded,
        source_digests=supplied_digests,
        synthetic=synthetic,
        generated_at=generated_at,
        git_head=git_head,
        r7_cross_market_digest=r7_snapshot_digest or "",
        r8_snapshot_digest="",
    )
    from dataclasses import replace

    digest = compute_snapshot_digest(snapshot)
    snapshot = replace(snapshot, r8_snapshot_digest=digest)
    return snapshot


def _result_order(result: ExecutionSimulationResult) -> tuple:
    return _scenario_order(result)


def _size_sensitivity(
    ordered: tuple[ExecutionSimulationResult, ...]
) -> tuple[SizeSensitivity, ...]:
    """Descriptive gross/net change across notionals per side. Never a cost."""
    by_side: dict[QuoteSide, list[ExecutionSimulationResult]] = {}
    for result in ordered:
        by_side.setdefault(result.scenario.side, []).append(result)
    sensitivity: list[SizeSensitivity] = []
    for side, results in sorted(by_side.items(), key=lambda item: item[0].value):
        if len(results) < 2:
            continue
        ordered_rows = sorted(results, key=lambda r: r.scenario.requested_notional_usd)
        small, large = ordered_rows[0], ordered_rows[-1]
        gross_change = (
            large.gross_execution_edge_bps - small.gross_execution_edge_bps
        )
        net_change: Decimal | None = None
        if (
            small.net_executable_edge_bps is not None
            and large.net_executable_edge_bps is not None
        ):
            net_change = (
                large.net_executable_edge_bps - small.net_executable_edge_bps
            )
        sensitivity.append(
            SizeSensitivity(
                side=side,
                small_notional_usd=small.scenario.requested_notional_usd,
                large_notional_usd=large.scenario.requested_notional_usd,
                gross_edge_change_bps=gross_change,
                net_edge_change_bps=net_change,
                route_changed=small.route_changed or large.route_changed,
            )
        )
    return tuple(sensitivity)
