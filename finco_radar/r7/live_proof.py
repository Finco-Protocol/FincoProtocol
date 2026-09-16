"""Networked R7 proof: cross-market observation stack on one economic asset.

Consumes the frozen R1→R5 live authority chain (registry, bound reference,
execution quotes, liquidity/reference-state snapshots) and builds the R7
cross-market evidence on top: layers, timing diagnostics, price-path
decomposition, dislocation attribution and comparability.

Honest live-data discipline (spec §26): the frozen source set provides NO
underlying-market source and NO FX authority, so those layers are declared
explicitly unavailable and the snapshot is PARTIALLY_COMPARABLE. Nothing is
invented to make the stack look complete.

Evidence contract (spec §24): canonical JSON, deterministic ordering, digest
reconstruction, tamper detection. The evidence is serialized twice and both
byte sequences must be identical.
"""
from __future__ import annotations

import hashlib
import json
import os
from dataclasses import replace
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

import httpx

from finco_radar.assets.adapters.robinhood import RobinhoodAssetRegistryAdapter
from finco_radar.assets.contracts import AssetKey, RegistryAssetStatus
from finco_radar.cross_market.contracts import (
    CrossMarketPolicy,
    EconomicIdentityBinding,
    LayerObservation,
    LayerObservationStatus,
    LayerType,
    SettlementContext,
    TokenRepresentation,
    VenueObservation,
    canonical_evidence_bytes,
)
from finco_radar.cross_market.engine import build_cross_market_snapshot
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

# Explicit caller-supplied R7 policy (the engine itself has no defaults).
R7_MATERIAL_DISLOCATION_BPS = Decimal(os.getenv("RADAR_R7_MATERIAL_DISLOCATION_BPS", "50"))
R7_MAX_LAYER_SKEW_SECONDS = Decimal(os.getenv("RADAR_R7_MAX_LAYER_SKEW_SECONDS", "120"))
R7_STALE_LAYER_SECONDS = Decimal(os.getenv("RADAR_R7_STALE_LAYER_SECONDS", "600"))
R7_COMPARISON_CURRENCY = os.getenv("RADAR_R7_COMPARISON_CURRENCY", "USD")

EVIDENCE_PATH = "artifacts/radar_r7_cross_market_evidence.json"
SHA256_PATH = "artifacts/radar_r7_cross_market_evidence.sha256"
MANIFEST_PATH = "artifacts/radar_r7_cross_market_manifest.json"

UNDERLYING_UNAVAILABLE_NOTE = (
    "UNDERLYING_SOURCE_UNAVAILABLE: no official underlying-market authority "
    "exists in the frozen R0-R6 source set"
)


def _canonical_digest(payload: Any) -> str:
    return hashlib.sha256(canonical_evidence_bytes(payload)).hexdigest()


def _venues_from_r3(r3, venue_source: str) -> list[VenueObservation]:
    """Extract venue observations from the frozen R3 liquidity authority."""
    rows: list[VenueObservation] = []
    for side, side_snapshot in ((QuoteSide.BUY, r3.buy), (QuoteSide.SELL, r3.sell)):
        for spread, size_label, side_of_chain in (
            (r3.spread_small, "small", side_snapshot),
            (r3.spread_large, "large", side_snapshot),
        ):
            quote = (
                side_of_chain.small_quote if size_label == "small" else side_of_chain.large_quote
            )
            gap = (
                side_of_chain.small_gap_observation
                if size_label == "small"
                else side_of_chain.large_gap_observation
            )
            route = (
                side_of_chain.small_route_signature
                if size_label == "small"
                else side_of_chain.large_route_signature
            )
            price = (
                spread.buy_execution_price_usd_per_token
                if side is QuoteSide.BUY
                else spread.sell_execution_price_usd_per_token
            )
            rows.append(
                VenueObservation(
                    venue=venue_source,
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
                )
            )
    return rows


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
                    key: AssetKey | None = asset.deployment_for_chain(CHAIN_ID)
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
                                    "R7_BOUND_REFERENCE_MIDPOINT_SIZING_ONLY"
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

                    # ---- R7 cross-market stack ------------------------------
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
                        source=UNDERLYING_UNAVAILABLE_NOTE,
                    )
                    oracle_reference = LayerObservation(
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
                        raw_evidence={
                            "r1RegistryAssetUid": r4.asset_uid,
                            "rawBidUsdPerShare": str(r4.raw_bid),
                            "rawAskUsdPerShare": str(r4.raw_ask),
                            "currentMultiplier": str(r4.current_multiplier),
                            "referenceGeneratedAt": r4.reference_generated_at.isoformat(),
                            "isTradingHalt": r4.is_trading_halt,
                            "semantics": (
                                "canonical oracle/reference midpoint = "
                                "(raw_bid + raw_ask) / 2 x currentMultiplier; "
                                "R4 remains the reference authority"
                            ),
                        },
                    )
                    token_representation = TokenRepresentation(
                        economic_asset_uid=asset.token_symbol,
                        asset_key=key,
                        symbol=asset.token_symbol,
                        multiplier=r4.current_multiplier,
                        representation_status=asset.status.value,
                        reference_usable=r4.reference_usable,
                        raw_evidence={"assetUid": asset.asset_uid},
                    )
                    venue_rows = _venues_from_r3(r3, r3.lineage.quote_source)
                    settlement_context = SettlementContext(
                        settlement_asset_symbol=(
                            r3.buy.small_quote.settlement_reference.asset.symbol or "UNKNOWN"
                        ),
                        chain_id=r3.buy.small_quote.settlement_reference.asset.chain_id,
                        contract_address=(
                            r3.buy.small_quote.settlement_reference.asset.contract_address
                        ),
                        settlement_currency=R7_COMPARISON_CURRENCY,
                        transfer_required=None,
                        authority_status="CONTEXT_ONLY_R8_PENDING",
                        resolved=True,
                        raw_evidence={"source": "R0_SETTLEMENT_REFERENCE"},
                    )
                    r7_policy = CrossMarketPolicy(
                        comparison_currency=R7_COMPARISON_CURRENCY,
                        material_dislocation_bps=R7_MATERIAL_DISLOCATION_BPS,
                        max_layer_skew_seconds=R7_MAX_LAYER_SKEW_SECONDS,
                        stale_layer_seconds=R7_STALE_LAYER_SECONDS,
                    )
                    as_of = datetime.now(timezone.utc)
                    r4_evidence = r4.to_evidence_dict()
                    source_digests = {
                        "r4ReferenceStateDigest": _canonical_digest(r4_evidence),
                    }
                    live_disclosures = {
                        "underlyingSource": "UNDERLYING_SOURCE_UNAVAILABLE",
                        "fxAuthority": "FX_AUTHORITY_UNAVAILABLE",
                        "settlementAuthority": "CONTEXT_ONLY_R8_PENDING",
                        "externalOracle": "NOT_OBSERVED_IN_THIS_PROOF",
                    }
                    snapshot = build_cross_market_snapshot(
                        binding=economic_binding,
                        policy=r7_policy,
                        as_of=as_of,
                        token=token_representation,
                        underlying=underlying,
                        fx=None,
                        oracle_reference=oracle_reference,
                        venues=venue_rows,
                        settlement=settlement_context,
                        upstream_evidence={
                            "r4ReferenceState": r4_evidence,
                            "r3LiquidityStatus": r3.status.value,
                        },
                        source_digests=source_digests,
                        live_disclosures=live_disclosures,
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
    raise RuntimeError(f"no live candidate produced a cross-market stack: {failures}")


def main() -> int:
    evidence, audit = _build_live_snapshot()
    # Deterministic serialization: the same snapshot must serialize to
    # identical bytes every time (spec §24/§30).
    first = json.dumps(evidence, indent=2, sort_keys=True, ensure_ascii=False)
    second = json.dumps(json.loads(first), indent=2, sort_keys=True, ensure_ascii=False)
    if first != second:
        raise RuntimeError("R7 evidence serialization is not byte-deterministic")
    evidence_path = Path(os.getenv("RADAR_R7_EVIDENCE_PATH", EVIDENCE_PATH))
    evidence_path.parent.mkdir(parents=True, exist_ok=True)
    evidence_path.write_text(first + "\n", encoding="utf-8")
    digest = hashlib.sha256(evidence_path.read_bytes()).hexdigest()
    Path(os.getenv("RADAR_R7_SHA256_PATH", SHA256_PATH)).write_text(
        f"{digest}  {evidence_path.name}\n", encoding="utf-8"
    )
    manifest = {
        "schemaVersion": evidence["schemaVersion"],
        "phase": evidence["phase"],
        "gitHead": evidence["gitHead"],
        "producedAt": evidence["generatedAt"],
        "r7SnapshotDigest": evidence["r7SnapshotDigest"],
        "evidenceJsonSha256": digest,
        "sourceDigests": evidence["sourceDigests"],
        "candidateAudit": audit,
        "note": (
            "GitHub artifact archive hash is separate from the canonical R7 "
            "evidence digest and is recorded in CI, not here."
        ),
    }
    Path(os.getenv("RADAR_R7_MANIFEST_PATH", MANIFEST_PATH)).write_text(
        json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8"
    )
    print(json.dumps({
        "status": evidence["status"],
        "attributionState": evidence["attributionState"],
        "comparabilityState": evidence["comparabilityState"],
        "digest": digest,
        "evidence": str(evidence_path),
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
