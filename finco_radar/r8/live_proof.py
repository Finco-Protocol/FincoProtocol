"""Networked R8 proof: execution simulation over the frozen R0-R7 authority.

One canonical asset, one coherent live chain: the exact R0 quotes feed the R2
gap observations and the R3 liquidity snapshot, whose evidence builds the R7
cross-market snapshot whose digest R8 binds. Scenarios cover the currently
authoritative BUY/SELL $100/$1,000 quote matrix with REFERENCE_RELATIVE
execution. No underlying, FX or second-venue data is invented.

Honest cost discipline: the live LiFi provider cost treatment is
EVIDENCE_ONLY_INCLUSION_UNRESOLVED, so the live artifact legitimately reports
gross execution economics with netExecutableEdge = null and
COST_TREATMENT_UNRESOLVED. That is a successful R8 state, not a failure.
"""
from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

import httpx

from finco_radar.assets.adapters.robinhood import RobinhoodAssetRegistryAdapter
from finco_radar.assets.contracts import RegistryAssetStatus
from finco_radar.cross_market.contracts import (
    CrossMarketPolicy,
    EconomicIdentityBinding,
    LayerObservation,
    LayerObservationStatus,
    LayerType,
    SettlementContext,
    TokenRepresentation,
    VenueObservation,
)
from finco_radar.cross_market.engine import build_cross_market_snapshot
from finco_radar.execution_simulator.contracts import (
    CostTreatmentState,
    ExecutionMode,
    ExecutionScenario,
    ExecutionSimulationStatus,
    ScenarioQuoteEvidence,
    SimulationTimingPolicy,
)
from finco_radar.execution_simulator.engine import build_execution_simulation
from finco_radar.gap.contracts import GapComparisonPolicy
from finco_radar.gap.engine import build_bound_reference_price, compute_directional_gap
from finco_radar.liquidity.contracts import LiquidityComparisonPolicy
from finco_radar.liquidity.engine import build_liquidity_snapshot
from finco_radar.quotes.adapters.lifi import LifiExecutionQuoteAdapter
from finco_radar.quotes.contracts import AssetRef, QuoteRequest, QuoteSide, QuoteStatus
from finco_radar.r3.live_proof import (
    CHAIN_ID,
    CANDIDATE_SYMBOLS,
    LIFI_API,
    NOTIONALS,
    ROBINHOOD_API,
    TAKER,
    _discover_settlement,
    _erc20_decimals,
    _git_head,
)
from finco_radar.reference_state.adapters.robinhood import RobinhoodCorporateActionAdapter
from finco_radar.reference_state.contracts import (
    MarketSessionEvidence,
    MarketSessionState,
    ReferenceStatePolicy,
)
from finco_radar.reference_state.engine import (
    build_reference_state_snapshot,
    match_corporate_actions,
)

EVIDENCE_PATH = "artifacts/radar_r8_execution_simulator_evidence.json"
SHA256_PATH = "artifacts/radar_r8_execution_simulator_evidence.sha256"
MANIFEST_PATH = "artifacts/radar_r8_execution_simulator_manifest.json"

R8_MAX_COST_EVIDENCE_AGE_SECONDS = Decimal(
    os.getenv("RADAR_R8_MAX_COST_EVIDENCE_AGE_SECONDS", "600")
)
R8_MAX_SETTLEMENT_EVIDENCE_AGE_SECONDS = Decimal(
    os.getenv("RADAR_R8_MAX_SETTLEMENT_EVIDENCE_AGE_SECONDS", "600")
)


def _canonical_digest(payload: Any) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode(
            "utf-8"
        )
    ).hexdigest()


def _build_live_snapshot() -> tuple[dict[str, Any], dict[str, Any]]:
    git_head = _git_head()
    failures: list[dict[str, str]] = []
    timeout = httpx.Timeout(25.0)
    with httpx.Client(timeout=timeout, headers={"accept": "application/json"}) as common:
        settlement = _discover_settlement(common)
        with httpx.Client(base_url=ROBINHOOD_API, timeout=timeout,
                          headers={"accept": "application/json"}) as rh, \
             httpx.Client(base_url=LIFI_API, timeout=timeout,
                          headers={"accept": "application/json"}) as lifi, \
             RobinhoodCorporateActionAdapter(client=rh) as ca_adapter:
            registry = RobinhoodAssetRegistryAdapter(client=rh)
            registry_snapshot = registry.fetch_snapshot()
            ca_rows, ca_observed_at = ca_adapter.fetch_rows()
            quote_adapter = LifiExecutionQuoteAdapter(client=lifi)
            for requested_symbol in CANDIDATE_SYMBOLS:
                try:
                    matches = registry_snapshot.find_by_symbol(requested_symbol)
                    if len(matches) != 1:
                        raise RuntimeError(f"symbol discovery returned {len(matches)} matches")
                    asset = matches[0]
                    if asset.status is not RegistryAssetStatus.ACTIVE:
                        raise RuntimeError("canonical asset is not ACTIVE")
                    key = asset.deployment_for_chain(CHAIN_ID)
                    if key is None:
                        raise RuntimeError("canonical deployment unavailable")
                    binding_row, price_row = registry.fetch_bound_reference(registry_snapshot, key)
                    reference = build_bound_reference_price(asset, binding_row, price_row)
                    token_ref = AssetRef(
                        CHAIN_ID, key.contract_address, symbol=asset.token_symbol,
                        decimals=_erc20_decimals(common, key.contract_address),
                    )
                    quotes = []
                    for side in (QuoteSide.BUY, QuoteSide.SELL):
                        for notional in NOTIONALS:
                            quote = quote_adapter.quote(QuoteRequest(
                                token=token_ref, settlement=settlement, side=side,
                                requested_notional_usd=notional, taker_address=TAKER,
                                token_sizing_reference_usd=(
                                    reference.token_midpoint_usd_per_token
                                    if side is QuoteSide.SELL else None
                                ),
                                token_sizing_reference_source=(
                                    "R8_BOUND_REFERENCE_MIDPOINT_SIZING_ONLY"
                                    if side is QuoteSide.SELL else None
                                ),
                            ))
                            if quote.status is not QuoteStatus.QUOTE_OK:
                                raise RuntimeError(
                                    f"{side.value}-{notional} quote status {quote.status.value}"
                                )
                            quotes.append(quote)
                    gap_observations = [compute_directional_gap(
                        reference, quote,
                        policy=GapComparisonPolicy(max_evidence_skew_seconds=120),
                    ) for quote in quotes]
                    produced_at = datetime.now(timezone.utc)
                    r3 = build_liquidity_snapshot(
                        asset=asset, asset_key=key, quotes=quotes,
                        gap_observations=gap_observations,
                        policy=LiquidityComparisonPolicy(max_quote_pair_skew_seconds=120),
                        git_head=git_head, produced_at=produced_at,
                    )
                    r4 = build_reference_state_snapshot(
                        asset=asset, reference=reference,
                        corporate_actions=match_corporate_actions(
                            ca_rows, asset=asset, asset_key=key
                        ),
                        session_evidence=MarketSessionEvidence(
                            state=MarketSessionState.UNRESOLVED,
                            source="R4_MARKET_SESSION_AUTHORITY_REQUIRED",
                        ),
                        policy=ReferenceStatePolicy(
                            max_live_reference_age_seconds=120,
                            max_session_evidence_age_seconds=86400,
                            max_clock_skew_seconds=5,
                        ),
                        as_of=produced_at,
                        registry_observed_at=registry_snapshot.observed_at,
                        corporate_actions_observed_at=ca_observed_at,
                    )

                    # Frozen R7 authority: cross-market snapshot bound by digest.
                    economic_binding = EconomicIdentityBinding(
                        economic_asset_uid=asset.token_symbol,
                        canonical_keys=tuple(asset.deployments),
                        reference_identifiers=(asset.token_symbol,),
                        source=registry.source_name,
                        raw_evidence={"assetUid": asset.asset_uid},
                    )
                    underlying = LayerObservation(
                        layer=LayerType.UNDERLYING,
                        status=LayerObservationStatus.SOURCE_UNAVAILABLE,
                        source="UNDERLYING_SOURCE_UNAVAILABLE",
                    )
                    oracle_layer = LayerObservation(
                        layer=LayerType.ORACLE_REFERENCE,
                        status=LayerObservationStatus.AVAILABLE,
                        source=r4.reference_source,
                        price=((r4.raw_bid + r4.raw_ask) / 2) * r4.current_multiplier,
                        currency=r4.currency,
                        observed_at=r4.reference_generated_at,
                        instrument=asset.token_symbol,
                        multiplier=r4.current_multiplier,
                        usable=r4.reference_usable,
                        # R7 economic-identity namespace (binding-checked); the
                        # canonical R1 hex UID travels in raw_evidence lineage.
                        asset_uid=economic_binding.economic_asset_uid,
                        asset_key=r4.canonical_key,
                        raw_evidence={"r1RegistryAssetUid": r4.asset_uid},
                    )
                    token_representation = TokenRepresentation(
                        economic_asset_uid=asset.token_symbol,
                        asset_key=key,
                        symbol=asset.token_symbol,
                        multiplier=r4.current_multiplier,
                        representation_status=asset.status.value,
                        reference_usable=r4.reference_usable,
                    )
                    venue_rows = []
                    for side, side_of in ((QuoteSide.BUY, r3.buy), (QuoteSide.SELL, r3.sell)):
                        for size_label, spread, gap, route in (
                            ("small", r3.spread_small, side_of.small_gap_observation,
                             side_of.small_route_signature),
                            ("large", r3.spread_large, side_of.large_gap_observation,
                             side_of.large_route_signature),
                        ):
                            quote = (
                                side_of.small_quote if size_label == "small"
                                else side_of.large_quote
                            )
                            price = (
                                spread.buy_execution_price_usd_per_token
                                if side is QuoteSide.BUY
                                else spread.sell_execution_price_usd_per_token
                            )
                            venue_rows.append(VenueObservation(
                                venue=r3.lineage.quote_source,
                                side=side,
                                notional_usd=spread.notional_usd,
                                price=price,
                                currency="USD",
                                observed_at=quote.quoted_at,
                                source="R0_EXECUTION_QUOTE_VIA_R3_LIQUIDITY",
                                asset_key=r3.canonical_key,
                                gap_bps=gap.gap_bps,
                                route_signature=route.canonical_form(),
                                raw_evidence={"size": size_label, "synthetic": False},
                            ))
                    r7_snapshot = build_cross_market_snapshot(
                        binding=economic_binding,
                        policy=CrossMarketPolicy(
                            comparison_currency="USD",
                            material_dislocation_bps=Decimal("50"),
                            max_layer_skew_seconds=Decimal("120"),
                            stale_layer_seconds=Decimal("600"),
                        ),
                        as_of=datetime.now(timezone.utc),
                        token=token_representation,
                        underlying=underlying,
                        fx=None,
                        oracle_reference=oracle_layer,
                        venues=venue_rows,
                        settlement=SettlementContext(
                            settlement_asset_symbol="USDG",
                            chain_id=CHAIN_ID,
                            contract_address=settlement.asset.contract_address,
                            settlement_currency="USD",
                            transfer_required=None,
                            authority_status="CONTEXT_ONLY_R8_PENDING",
                            resolved=True,
                        ),
                        synthetic=False,
                        generated_at=datetime.now(timezone.utc),
                        git_head=git_head,
                    )
                    r7_evidence = r7_snapshot.to_evidence_dict()

                    # ---- R8 scenarios from the exact R3 evidence ------------
                    scenario_quotes: list[ScenarioQuoteEvidence] = []
                    scenario_list: list[ExecutionScenario] = []
                    evidence_rows = _scenario_rows_from_r3(r3, venue_source=r3.lineage.quote_source)
                    for row in evidence_rows:
                        label = (
                            f"ORACLE_REFERENCE→VENUE[{row.venue}:{row.side.value}:"
                            f"{row.requested_notional_usd}]"
                        )
                        scenario_quotes.append(row)
                        scenario_list.append(ExecutionScenario(
                            economic_asset_uid=asset.token_symbol,
                            canonical_asset_key=key,
                            side=row.side,
                            requested_notional_usd=row.requested_notional_usd,
                            quote_source=r3.lineage.quote_source,
                            execution_mode=ExecutionMode.REFERENCE_RELATIVE,
                            r7_component_label=label,
                            as_of=datetime.now(timezone.utc),
                        ))

                    r8_policy = SimulationTimingPolicy(
                        max_cost_evidence_age_seconds=R8_MAX_COST_EVIDENCE_AGE_SECONDS,
                        max_settlement_evidence_age_seconds=R8_MAX_SETTLEMENT_EVIDENCE_AGE_SECONDS,
                    )
                    theoretical = {
                        c.label: c.delta_bps
                        for c in r7_snapshot.dislocation_components
                        if c.material
                    }
                    component_labels = {c.label for c in r7_snapshot.dislocation_components}
                    r7_digest = r7_snapshot.r7_snapshot_digest

                    r2_evidence = {
                        "gapSemantics": (
                            "frozen R2 directional gap; BUY compares the "
                            "multiplier-adjusted official ASK, SELL the BID"
                        ),
                        "gapObservations": [
                            {
                                "side": side.value,
                                "notionalUsd": str(notional),
                                "gapBps": str(gap.gap_bps),
                            }
                            for (side, notional), gap in _gap_by_slot(gap_observations).items()
                        ],
                    }
                    r0_evidence = {
                        "quoteSource": r3.lineage.quote_source,
                        "quoteCount": len(quotes),
                    }
                    upstream_evidence = {
                        "r7CrossMarketEvidence": r7_evidence,
                        "r3LiquidityEvidence": r3.to_evidence_dict(),
                        "r3LiquidityStatus": r3.status.value,
                        "r2GapEvidence": r2_evidence,
                        "r0QuoteEvidence": r0_evidence,
                    }
                    snapshot = build_execution_simulation(
                        economic_asset_uid=asset.token_symbol,
                        canonical_asset_key=key,
                        scenarios=scenario_list,
                        quote_evidence=scenario_quotes,
                        settlement_adjustment=None,
                        policy=r8_policy,
                        theoretical_dislocations=theoretical,
                        r7_snapshot_digest=r7_digest,
                        r7_component_labels=component_labels,
                        upstream_evidence=upstream_evidence,
                        source_digests={
                            "r7CrossMarketDigest": _canonical_digest(r7_evidence),
                            "r3LiquidityDigest": _canonical_digest(r3.to_evidence_dict()),
                            "r2GapEvidenceDigest": _canonical_digest(r2_evidence),
                            "r0QuoteEvidenceDigest": _canonical_digest(r0_evidence),
                        },
                        synthetic=False,
                        generated_at=datetime.now(timezone.utc),
                        git_head=git_head,
                    )
                    evidence = snapshot.to_evidence_dict()
                    return evidence, {
                        "selectedSymbol": asset.token_symbol,
                        "skippedCandidates": failures,
                    }
                except Exception as exc:
                    status = getattr(getattr(exc, "status", None), "value", "INFRASTRUCTURE_ERROR")
                    failures.append(
                        {"symbol": requested_symbol, "status": status,
                         "detail": f"{type(exc).__name__}:{exc}"}
                    )
    raise RuntimeError(f"no live candidate produced an R8 simulation: {failures}")


def _gap_by_slot(gap_observations):
    result = {}
    for gap in gap_observations:
        result[(gap.side, gap.requested_notional_usd)] = gap
    return result


def _scenario_rows_from_r3(r3, *, venue_source: str):
    """Extract exact R0/R2/R3 evidence rows for the four canonical scenarios."""
    rows: list[ScenarioQuoteEvidence] = []
    cost_slots = list(r3.cost_evidence)  # BUY small, BUY large, SELL small, SELL large
    sides = (
        (QuoteSide.BUY, r3.buy, 0, 1),
        (QuoteSide.SELL, r3.sell, 2, 3),
    )
    for side, side_of, small_idx, large_idx in sides:
        for size_label, gap, quote, cost_idx in (
            ("small", side_of.small_gap_observation, side_of.small_quote, small_idx),
            ("large", side_of.large_gap_observation, side_of.large_quote, large_idx),
        ):
            cost = cost_slots[cost_idx]
            rows.append(ScenarioQuoteEvidence(
                side=side,
                requested_notional_usd=quote.requested_notional_usd,
                token_amount=gap.token_amount,
                reference_price_usd_per_token=gap.reference_price_usd_per_token,
                settlement_amount_usd=gap.settlement_amount_usd,
                r2_gap_bps=gap.gap_bps,
                quote_observed_at=quote.quoted_at,
                reference_generated_at=gap.reference_generated_at,
                settlement_observed_at=quote.settlement_reference.observed_at,
                canonical_asset_key=r3.canonical_key,
                venue=venue_source,
                route_signature=(
                    side_of.small_route_signature.canonical_form()
                    if size_label == "small"
                    else side_of.large_route_signature.canonical_form()
                ),
                route_changed=(
                    side_of.route_changed if hasattr(side_of, "route_changed") else False
                ),
                provider_fee_usd=cost.fee_cost_usd,
                provider_gas_usd=cost.gas_cost_usd,
                provider_cost_treatment=cost.cost_treatment_state,
                r0_quote_evidence={
                    "source": quote.source,
                    "requestedNotionalUsd": str(quote.requested_notional_usd),
                    "rawAmountIn": str(quote.raw_amount_in),
                    "rawAmountOut": str(quote.raw_amount_out),
                    "settlementAsset": quote.settlement_reference.asset.symbol,
                },
                r2_gap_evidence={
                    "referenceSide": gap.reference_side.value,
                    "referencePriceUsdPerToken": str(gap.reference_price_usd_per_token),
                    "executionPriceUsdPerToken": str(gap.execution_price_usd_per_token),
                    "gapBps": str(gap.gap_bps),
                },
            ))
    return rows


def main() -> int:
    evidence, audit = _build_live_snapshot()
    first = json.dumps(evidence, indent=2, sort_keys=True, ensure_ascii=False)
    second = json.dumps(json.loads(first), indent=2, sort_keys=True, ensure_ascii=False)
    if first != second:
        raise RuntimeError("R8 evidence serialization is not byte-deterministic")
    evidence_path = Path(os.getenv("RADAR_R8_EVIDENCE_PATH", EVIDENCE_PATH))
    evidence_path.parent.mkdir(parents=True, exist_ok=True)
    evidence_path.write_text(first + "\n", encoding="utf-8")
    digest = hashlib.sha256(evidence_path.read_bytes()).hexdigest()
    Path(os.getenv("RADAR_R8_SHA256_PATH", SHA256_PATH)).write_text(
        f"{digest}  {evidence_path.name}\n", encoding="utf-8"
    )
    manifest = {
        "schemaVersion": evidence["schemaVersion"],
        "phase": evidence["phase"],
        "gitHead": evidence["gitHead"],
        "producedAt": evidence["generatedAt"],
        "r8SnapshotDigest": evidence["r8SnapshotDigest"],
        "evidenceJsonSha256": digest,
        "sourceDigests": evidence["sourceDigests"],
        "candidateAudit": audit,
        "note": (
            "GitHub artifact archive hash is separate from the canonical R8 "
            "evidence digest and is recorded in CI, not here."
        ),
    }
    Path(os.getenv("RADAR_R8_MANIFEST_PATH", MANIFEST_PATH)).write_text(
        json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8"
    )
    net_states = sorted({s["netEdgeState"] for s in evidence["scenarios"]})
    print(json.dumps({
        "status": evidence["status"],
        "netEdgeStates": net_states,
        "digest": digest,
        "evidence": str(evidence_path),
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
