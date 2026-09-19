"""Composition root for the Radar v1 UI (P1-P3 of Post-R12 P2).

Combines exactly three things:

1. the canonical P1 acquisition runtime (immutable snapshots);
2. frozen Radar authority surfaces wired as P1 provider callables
   (public frozen adapters + engines only — private ``live_proof``
   helpers are NEVER called from browser-reachable composition);
3. presentation-only view models.

ONE canonical configured asset in this PR (P3): identified by chain +
contract deployment + economic UID, never ticker alone.  The deployment
address/decimals are configuration (env-overridable) pinned to the
canonical Radar live-path asset.

The USDG settlement resolver is an INJECTABLE one-line wiring point:
frozen settlement parsing lives inside the frozen proof modules and is
deliberately not duplicated here; until a settlement adapter is injected
the execution section reports explicitly UNAVAILABLE (P5/P9) — never a
fabricated fallback.
"""
from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any, Callable, Mapping

import httpx

from app.radar_runtime.contracts import (
    AcquisitionRequest,
    RuntimeContractError,
)
from app.radar_runtime.service import AcquisitionService, ServiceConfig
from app.radar_runtime.snapshot_store import SnapshotStore
from app.radar_ui.quote_context import (
    QuoteContext,
    SettlementContextError,
    build_settlement_reference,
    quote_taker_address,
    resolve_quote_context,
)

PROVIDER_NAME = "radar-core"

DIRECTIONS = ("BUY", "SELL")
SIZES = ("100", "1000")

# The configured provider/source set for the canonical asset acquisition.
# Composition-level configuration (env-extensible, test-seamable) — the
# P1 request fingerprint binds this set, so extending it changes the
# request identity by design.
_CONFIGURED_EXTRA_SOURCES: "tuple[str, ...]" = ()


def set_configured_sources(extra: "tuple[str, ...]") -> None:
    """Test/diagnostic seam: extend the configured source set (the
    canonical provider is always first and cannot be removed)."""
    global _CONFIGURED_EXTRA_SOURCES
    _CONFIGURED_EXTRA_SOURCES = tuple(extra)


def configured_sources() -> "tuple[str, ...]":
    env_extra = tuple(
        s.strip() for s in
        os.getenv("RADAR_V1_EXTRA_SOURCES", "").split(",") if s.strip())
    return (PROVIDER_NAME,) + _CONFIGURED_EXTRA_SOURCES + env_extra

REFERENCE_IDENTITY_MISMATCH = "REFERENCE_IDENTITY_MISMATCH"


class ReferenceIdentityMismatch(RuntimeContractError):
    """A3: the frozen registry/reference authority did not resolve to the
    EXACT requested canonical identity (economic UID + chain + contract
    deployment).  The reference section fails closed."""


def bind_reference_identity(asset_record, key, *, economic_asset_uid: str,
                            chain_id: int, contract_address: str) -> None:
    """A3: prove the resolved registry asset/deployment IS the requested
    canonical identity before any reference authority becomes AVAILABLE.

    Uses the frozen canonical identity semantics (exact economic UID
    equality; exact chain equality; case-insensitive EVM contract address
    equality matching the frozen deployment normalization).  Ticker
    equality alone is never sufficient.  Raises
    :class:`ReferenceIdentityMismatch` on any mismatch."""
    resolved_uid = getattr(asset_record, "asset_uid", None)
    if resolved_uid != economic_asset_uid:
        raise ReferenceIdentityMismatch(
            f"registry asset uid {resolved_uid!r} != requested "
            f"economic uid {economic_asset_uid!r}")
    resolved_chain = getattr(key, "chain_id", None)
    if resolved_chain != chain_id:
        raise ReferenceIdentityMismatch(
            f"resolved deployment chain {resolved_chain!r} != requested "
            f"chain {chain_id!r}")
    resolved_address = str(getattr(key, "contract_address", ""))
    if resolved_address.lower() != str(contract_address).lower():
        raise ReferenceIdentityMismatch(
            f"resolved deployment contract {resolved_address!r} != "
            f"requested contract {contract_address!r}")


def asset_config() -> dict[str, Any]:
    """The ONE canonical configured Radar v1 asset (P3)."""
    return {
        "economicAssetUid": os.getenv("RADAR_V1_ASSET_UID", "AAPL"),
        "symbol": os.getenv("RADAR_V1_ASSET_SYMBOL", "AAPL"),
        "chainId": int(os.getenv("RADAR_V1_ASSET_CHAIN_ID", "4663")),
        "contractAddress": os.getenv(
            "RADAR_V1_ASSET_ADDRESS",
            "0xaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"),
        "decimals": int(os.getenv("RADAR_V1_ASSET_DECIMALS", "18")),
    }


def build_request(direction: str, size: str) -> AcquisitionRequest:
    """Build the canonical acquisition request for the configured asset.

    Only the reviewed quote directions (BUY/SELL) and the two sized
    notional controls ($100 / $1,000) supported by the frozen Radar path
    are accepted (P4); everything else is a typed rejection.

    P5/P6: the read-only quote context (settlement identity/value/state +
    taker routing address) is resolved HERE and bound into the P1 request
    fingerprint material — the provider callable consumes exactly this
    material, so any context change changes the acquisition identity and
    there is no config split-brain."""
    asset = asset_config()
    if direction not in DIRECTIONS:
        raise RuntimeContractError(
            f"direction must be one of {list(DIRECTIONS)}, got {direction!r}")
    if size not in SIZES:
        raise RuntimeContractError(
            f"size must be one of {list(SIZES)}, got {size!r}")
    quote_context = resolve_quote_context(
        expected_chain_id=asset["chainId"])
    return AcquisitionRequest(
        chain_id=asset["chainId"],
        contract_address=asset["contractAddress"],
        direction=direction,
        sources=configured_sources(),
        purpose="radar-v1-panel",
        notional_usd=size,
        economic_asset_uid=asset["economicAssetUid"],
        provider_config={"radarCore": quote_context.fingerprint_material()},
    )


def composition_radar_source(
    *,
    asset: "Mapping[str, Any] | None" = None,
    settlement_resolver: "Callable[[], Any] | None" = None,
    registry_factory: "Callable[[], Any] | None" = None,
    quote_adapter_factory: "Callable[[], Any] | None" = None,
) -> Callable[[AcquisitionRequest], Mapping[str, Any]]:
    """Production provider callable composing FROZEN Radar authority
    surfaces (public adapters/engines only):

    - ``RobinhoodAssetRegistryAdapter``  (R1 registry, bound reference rows)
    - ``build_bound_reference_price``    (frozen R2/R7 reference engine)
    - ``LifiExecutionQuoteAdapter``      (frozen R0 quote authority)
    - ``compute_directional_gap``        (frozen R2 GAP engine)

    The USDG settlement is supplied by the injectable
    ``settlement_resolver``; without it the execution/gap sections report
    explicitly UNAVAILABLE — no fabricated fallback (P5/P8/P9).
    Section-level failures stay explicit inside the evidence; the runtime
    classifies the overall observation (P5)."""
    from decimal import Decimal

    from finco_radar.assets.adapters.robinhood import (
        RobinhoodAssetRegistryAdapter,
    )
    from finco_radar.gap.contracts import GapComparisonPolicy
    from finco_radar.gap.engine import (
        build_bound_reference_price,
        compute_directional_gap,
    )
    from finco_radar.quotes.adapters.lifi import LifiExecutionQuoteAdapter
    from finco_radar.quotes.contracts import (
        AssetRef,
        QuoteRequest,
        QuoteSide,
        QuoteStatus,
    )

    config = dict(asset or asset_config())

    def _unavailable(reason: str) -> dict[str, Any]:
        return {"available": False, "reason": reason}

    def source(request: AcquisitionRequest) -> Mapping[str, Any]:
        observed_at = datetime.now(timezone.utc).isoformat()
        evidence: dict[str, Any] = {
            "asset": {
                "symbol": config["symbol"],
                "economicAssetUid": config["economicAssetUid"],
                "chainId": request.chain_id,
                "contractAddress": request.contract_address,
            },
            "observedAt": observed_at,
        }
        reference_authority = None
        quote_authority = None

        # -- reference: frozen R1 registry + R2/R7 bound-reference engine
        try:
            registry = (registry_factory or (lambda: (
                RobinhoodAssetRegistryAdapter(client=httpx.Client(
                    base_url="https://api.robinhood.com", timeout=10.0,
                    headers={"accept": "application/json"})))))()
            try:
                registry_snapshot = registry.fetch_snapshot()
                matches = registry_snapshot.find_by_symbol(config["symbol"])
                if len(matches) != 1:
                    raise RuntimeError(
                        "symbol discovery did not resolve exactly one "
                        "canonical asset")
                asset_record = matches[0]
                key = asset_record.deployment_for_chain(request.chain_id)
                if key is None:
                    raise RuntimeError("canonical deployment unavailable")
                # A3: bind the resolved registry asset/deployment to the
                # EXACT requested canonical identity before the reference
                # may become AVAILABLE.
                bind_reference_identity(
                    asset_record, key,
                    economic_asset_uid=request.economic_asset_uid,
                    chain_id=request.chain_id,
                    contract_address=request.contract_address)
                binding_row, price_row = registry.fetch_bound_reference(
                    registry_snapshot, key)
                reference_authority = build_bound_reference_price(
                    asset_record, binding_row, price_row)
                # The preserved evidence identity represents the BOUND
                # snapshot identity, never a mixture with config.
                evidence["asset"] = {
                    "symbol": asset_record.token_symbol,
                    "economicAssetUid": asset_record.asset_uid,
                    "chainId": key.chain_id,
                    "contractAddress": key.contract_address,
                }
                evidence["reference"] = {
                    "available": True,
                    "symbol": reference_authority.symbol,
                    "price": str(reference_authority.token_midpoint_usd_per_token),
                    "bid": str(reference_authority.token_bid_usd_per_token),
                    "ask": str(reference_authority.token_ask_usd_per_token),
                    "source": f"FROZEN::{type(reference_authority).__name__}",
                    "observedAt": reference_authority.generated_at.isoformat(),
                    "isTradingHalt": reference_authority.is_trading_halt,
                }
            finally:
                close = getattr(registry, "close", None)
                if callable(close):
                    close()
        except ReferenceIdentityMismatch:
            # A3: stable closed composition reason for identity mismatch
            evidence["reference"] = _unavailable(REFERENCE_IDENTITY_MISMATCH)
        except Exception as exc:  # noqa: BLE001 - explicit section state
            evidence["reference"] = _unavailable(type(exc).__name__)

        # -- execution: frozen R0 quote authority for the requested side/size
        try:
            # P5/P6: the settlement/taker context comes from the
            # fingerprint-bound request material — never re-read from a
            # different configuration source.
            quote_context = QuoteContext.from_material(
                (request.provider_config or {}).get("radarCore"))
            if quote_context.problems:
                evidence["execution"] = _unavailable(
                    quote_context.problems[0])
            elif reference_authority is None:
                evidence["execution"] = _unavailable("REFERENCE_UNAVAILABLE")
            else:
                # P3: frozen SettlementReference built from the bound
                # context; chain/usable validation fails closed BEFORE
                # LI.FI is invoked.
                settlement_authority = build_settlement_reference(
                    quote_context, expected_chain_id=request.chain_id)
                taker_address = quote_taker_address(quote_context)
                evidence["settlement"] = {
                    "configured": True,
                    "chainId": settlement_authority.asset.chain_id,
                    "contractAddress":
                        settlement_authority.asset.contract_address,
                    "state": settlement_authority.state.value,
                    "source": settlement_authority.source,
                    "symbol": settlement_authority.asset.symbol,
                    "usdPerAsset": str(settlement_authority.usd_per_asset),
                }
                quote_adapter = (quote_adapter_factory or (lambda: (
                    LifiExecutionQuoteAdapter(client=httpx.Client(
                        base_url="https://li.quest", timeout=10.0)))))()
                try:
                    # P7: the frozen QuoteRequest is constructed with ALL
                    # required arguments, including the validated public
                    # taker routing address.  Quote-only: any transaction
                    # payload fields remain inert evidence.
                    quote_authority = quote_adapter.quote(QuoteRequest(
                        token=AssetRef(
                            request.chain_id, request.contract_address,
                            symbol=config["symbol"],
                            decimals=config["decimals"]),
                        settlement=settlement_authority,
                        side=(QuoteSide.BUY if request.direction == "BUY"
                              else QuoteSide.SELL),
                        requested_notional_usd=Decimal(request.notional_usd),
                        taker_address=taker_address,
                        token_sizing_reference_usd=(
                            reference_authority.token_midpoint_usd_per_token
                            if request.direction == "SELL" else None),
                        token_sizing_reference_source=(
                            "R8_BOUND_REFERENCE_MIDPOINT_SIZING_ONLY"
                            if request.direction == "SELL" else None),
                    ))
                finally:
                    close = getattr(quote_adapter, "close", None)
                    if callable(close):
                        close()
                evidence["execution"] = {
                    "available": quote_authority.status is QuoteStatus.QUOTE_OK,
                    "side": request.direction,
                    "notionalUsd": request.notional_usd,
                    "status": quote_authority.status.value,
                    "rawAmountIn": (
                        str(quote_authority.raw_amount_in)
                        if quote_authority.raw_amount_in is not None
                        else None),
                    "rawAmountOut": (
                        str(quote_authority.raw_amount_out)
                        if quote_authority.raw_amount_out is not None
                        else None),
                    "normalizedAmountOut": (
                        str(quote_authority.normalized_amount_out)
                        if quote_authority.normalized_amount_out is not None
                        else None),
                    "effectivePrice": (
                        str(quote_authority.effective_output_per_input)
                        if quote_authority.effective_output_per_input
                        is not None else None),
                    "source": quote_authority.source,
                    "quotedAt": quote_authority.quoted_at.isoformat(),
                    "unavailableReason": quote_authority.unavailable_reason,
                }
        except SettlementContextError as exc:
            # P3: typed fail-closed settlement context reason
            evidence["settlement"] = {
                "configured": False, "reason": str(exc),
            }
            evidence["execution"] = _unavailable(str(exc))
        except Exception as exc:  # noqa: BLE001 - explicit section state
            evidence["execution"] = _unavailable(type(exc).__name__)

        # -- gap: frozen R2 directional GAP engine over the authority objects
        try:
            if (reference_authority is None or quote_authority is None
                    or quote_authority.status is not QuoteStatus.QUOTE_OK):
                evidence["gap"] = _unavailable(
                    "GAP_REQUIRES_EXECUTION_AND_REFERENCE")
            else:
                gap = compute_directional_gap(
                    reference_authority, quote_authority,
                    policy=GapComparisonPolicy(max_evidence_skew_seconds=120))
                evidence["gap"] = {
                    "available": True,
                    "side": request.direction,
                    "gapBps": str(gap.gap_bps),
                    "gapToMidBps": str(gap.gap_to_mid_bps),
                    "executionPrice": str(gap.execution_price_usd_per_token),
                    "referencePrice": str(gap.reference_price_usd_per_token),
                    "referenceSide": gap.reference_side.value,
                    "source": f"FROZEN::{type(gap).__name__}",
                    "quotedAt": gap.quoted_at.isoformat(),
                }
        except Exception as exc:  # noqa: BLE001 - explicit section state
            evidence["gap"] = _unavailable(type(exc).__name__)

        return {"evidence": evidence, "observedAt": observed_at}

    return source


def build_service(
    *,
    store: "SnapshotStore | None" = None,
    providers: "Mapping[str, Callable[[AcquisitionRequest], Any]] | None" = None,
    config: "ServiceConfig | None" = None,
) -> AcquisitionService:
    """Build the canonical P1 acquisition service for the Radar UI.

    ``providers`` replaces the default composition wiring — the UI tests
    inject deterministic offline fakes through exactly this seam."""
    resolved = providers
    if resolved is None:
        resolved = {PROVIDER_NAME: composition_radar_source()}
    return AcquisitionService(
        store or SnapshotStore(),
        resolved,
        config=config,
    )
