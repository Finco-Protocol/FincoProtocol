"""Composition root for the Radar v1 UI (P1-P3 of Post-R12 P2).

Combines exactly three things:

1. the canonical P1 acquisition runtime (immutable snapshots);
2. frozen Radar authority surfaces wired as P1 provider callables
   (public frozen adapters + engines only — private ``live_proof``
   helpers are NEVER called from browser-reachable composition);
3. presentation-only view models.

Multi-asset: the dynamic Robinhood asset universe is discovered at the
APP COMPOSITION layer via the existing frozen RobinhoodAssetRegistryAdapter.
Asset identity is always UID-first; ticker is presentation only.  Token
decimals are derived from the official registry raw_evidence.

The USDG settlement resolver is an INJECTABLE one-line wiring point:
frozen settlement parsing lives inside the frozen proof modules and is
deliberately not duplicated here; until a settlement adapter is injected
the execution section reports explicitly UNAVAILABLE (P5/P9) — never a
fabricated fallback.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
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

_TARGET_CHAIN_ID = 4663

TOKEN_DECIMALS_UNAVAILABLE = "TOKEN_DECIMALS_UNAVAILABLE"
TOKEN_DECIMALS_AUTHORITY_MISMATCH = "TOKEN_DECIMALS_AUTHORITY_MISMATCH"
TOKEN_DECIMALS_AUTHORITY_UNBOUND = "TOKEN_DECIMALS_AUTHORITY_UNBOUND"

# The configured provider/source set for the canonical asset acquisition.
_CONFIGURED_EXTRA_SOURCES: "tuple[str, ...]" = ()


def set_configured_sources(extra: "tuple[str, ...]") -> None:
    """Test/diagnostic seam: extend the configured source set."""
    global _CONFIGURED_EXTRA_SOURCES
    _CONFIGURED_EXTRA_SOURCES = tuple(extra)


def configured_sources() -> "tuple[str, ...]":
    env_extra = tuple(
        s.strip() for s in
        os.getenv("RADAR_V1_EXTRA_SOURCES", "").split(",") if s.strip())
    return (PROVIDER_NAME,) + _CONFIGURED_EXTRA_SOURCES + env_extra


# Test/diagnostic seam: override the registry factory used by
# fetch_robinhood_asset_universe and composition_radar_source.
_registry_factory_override: "Callable[[], Any] | None" = None


def set_registry_factory(factory: "Callable[[], Any] | None") -> None:
    """Test seam: inject a fake registry factory for offline universe
    discovery and reference resolution.  Pass None to clear."""
    global _registry_factory_override
    _registry_factory_override = factory


class TokenDecimalsUnavailable(RuntimeContractError):
    """Token decimals are absent, invalid, or out of range [0, 255] in the
    registry raw evidence.  The reference section fails closed."""


class TokenDecimalsMismatch(RuntimeContractError):
    """Live registry tokenDecimals differ from the fingerprint-bound value.
    The reference section fails closed — stale decimals authority rejected."""


class TokenDecimalsUnbound(RuntimeContractError):
    """Fingerprint-bound tokenDecimals are absent or malformed.
    The reference section fails closed — no substitution of live decimals."""


def _parse_token_decimals(raw) -> int:
    """Parse and validate tokenDecimals from registry raw_evidence.

    Accepts a non-negative integer or an integer-valued string in [0, 255].
    Rejects: None, bool, float, negative, >255, non-numeric strings.
    Raises :class:`TokenDecimalsUnavailable` on any rejection."""
    if raw is None or isinstance(raw, bool):
        raise TokenDecimalsUnavailable(TOKEN_DECIMALS_UNAVAILABLE)
    if isinstance(raw, float):
        raise TokenDecimalsUnavailable(TOKEN_DECIMALS_UNAVAILABLE)
    if isinstance(raw, int):
        value = raw
    elif isinstance(raw, str):
        if not raw.isascii() or not raw.isdigit():
            raise TokenDecimalsUnavailable(TOKEN_DECIMALS_UNAVAILABLE)
        value = int(raw)
    else:
        raise TokenDecimalsUnavailable(TOKEN_DECIMALS_UNAVAILABLE)
    if value < 0 or value > 255:
        raise TokenDecimalsUnavailable(TOKEN_DECIMALS_UNAVAILABLE)
    return value


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
    """Fallback configured asset (env-overridable).  Used only when no
    selected_asset is supplied to build_request (backward compat / tests)."""
    return {
        "economicAssetUid": os.getenv("RADAR_V1_ASSET_UID", "AAPL"),
        "symbol": os.getenv("RADAR_V1_ASSET_SYMBOL", "AAPL"),
        "chainId": int(os.getenv("RADAR_V1_ASSET_CHAIN_ID", "4663")),
        "contractAddress": os.getenv(
            "RADAR_V1_ASSET_ADDRESS",
            "0xaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"),
        "decimals": int(os.getenv("RADAR_V1_ASSET_DECIMALS", "18")),
    }


@dataclass(frozen=True)
class SelectedAsset:
    """Server-resolved asset identity for one browser Radar acquisition.

    Every field is authoritative from the official Robinhood registry.
    Clients supply only the economic_asset_uid; the server derives all
    other fields from the live registry snapshot."""
    economic_asset_uid: str
    token_symbol: str
    token_name: str
    chain_id: int
    contract_address: str
    token_decimals: int


def fetch_robinhood_asset_universe(
    registry_factory: "Callable[[], Any] | None" = None,
    *,
    target_chain_id: int = _TARGET_CHAIN_ID,
) -> "list[SelectedAsset]":
    """Discover the live Robinhood Stock Token universe for target_chain_id.

    Uses the existing frozen RobinhoodAssetRegistryAdapter.  Returns a
    deterministically sorted list of SelectedAsset objects for every asset
    that has a canonical deployment on target_chain_id and valid
    tokenDecimals in its raw registry evidence.

    Fails with a plain exception (caller wraps in try/except) if the
    registry is unavailable."""
    from finco_radar.assets.adapters.robinhood import (
        RobinhoodAssetRegistryAdapter,
    )

    factory = registry_factory or _registry_factory_override or (
        lambda: RobinhoodAssetRegistryAdapter())
    registry = factory()
    try:
        snapshot = registry.fetch_snapshot()
    finally:
        close = getattr(registry, "close", None)
        if callable(close):
            close()

    result: list[SelectedAsset] = []
    for asset in snapshot.assets:
        deployment = asset.deployment_for_chain(target_chain_id)
        if deployment is None:
            continue
        try:
            decimals = _parse_token_decimals(
                getattr(asset, "raw_evidence", {}).get("tokenDecimals"))
        except TokenDecimalsUnavailable:
            continue
        result.append(SelectedAsset(
            economic_asset_uid=asset.asset_uid,
            token_symbol=asset.token_symbol,
            token_name=asset.token_name,
            chain_id=deployment.chain_id,
            contract_address=deployment.contract_address,
            token_decimals=decimals,
        ))

    # Deterministic sort: symbol then uid
    result.sort(key=lambda a: (a.token_symbol, a.economic_asset_uid))
    return result


def build_request(direction: str, size: str,
                  selected_asset: "SelectedAsset | None" = None,
                  ) -> AcquisitionRequest:
    """Build the canonical acquisition request.

    If selected_asset is provided the request is bound to that exact
    UID/chain/contract identity.  Without it the legacy asset_config()
    fallback is used (backward compat for existing tests and bookmarks).

    Only the reviewed quote directions (BUY/SELL) and the two sized
    notional controls ($100 / $1,000) are accepted; everything else is a
    typed rejection.

    P5/P6: the read-only quote context (settlement identity/value/state +
    taker routing address) is resolved HERE and bound into the P1 request
    fingerprint material."""
    if direction not in DIRECTIONS:
        raise RuntimeContractError(
            f"direction must be one of {list(DIRECTIONS)}, got {direction!r}")
    if size not in SIZES:
        raise RuntimeContractError(
            f"size must be one of {list(SIZES)}, got {size!r}")

    if selected_asset is not None:
        chain_id = selected_asset.chain_id
        contract_address = selected_asset.contract_address
        economic_asset_uid = selected_asset.economic_asset_uid
        token_decimals = selected_asset.token_decimals
    else:
        asset = asset_config()
        chain_id = asset["chainId"]
        contract_address = asset["contractAddress"]
        economic_asset_uid = asset["economicAssetUid"]
        token_decimals = asset["decimals"]

    quote_context = resolve_quote_context(expected_chain_id=chain_id)
    return AcquisitionRequest(
        chain_id=chain_id,
        contract_address=contract_address,
        direction=direction,
        sources=configured_sources(),
        purpose="radar-v1-panel",
        notional_usd=size,
        economic_asset_uid=economic_asset_uid,
        provider_config={
            "radarCore": quote_context.fingerprint_material(),
            "targetAsset": {"tokenDecimals": token_decimals},
        },
    )


def composition_radar_source(
    *,
    settlement_resolver: "Callable[[], Any] | None" = None,
    registry_factory: "Callable[[], Any] | None" = None,
    quote_adapter_factory: "Callable[[], Any] | None" = None,
) -> "Callable[[AcquisitionRequest], Mapping[str, Any]]":
    """Production provider callable composing FROZEN Radar authority
    surfaces (public adapters/engines only):

    - ``RobinhoodAssetRegistryAdapter``  (R1 registry, bound reference rows)
    - ``build_bound_reference_price``    (frozen R2/R7 reference engine)
    - ``LifiExecutionQuoteAdapter``      (frozen R0 quote authority)
    - ``compute_directional_gap``        (frozen R2 GAP engine)

    Asset identity is derived from request.economic_asset_uid via a fresh
    registry snapshot on every acquisition — the same long-lived service
    instance safely processes any number of different assets.  Token
    decimals are taken from the official registry raw_evidence[tokenDecimals].

    The USDG settlement is supplied by the injectable settlement_resolver;
    without it the execution/gap sections report explicitly UNAVAILABLE —
    no fabricated fallback."""
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

    def _reg_factory():
        return (registry_factory or _registry_factory_override
                or (lambda: RobinhoodAssetRegistryAdapter()))()

    def _unavailable(reason: str) -> dict[str, Any]:
        return {"available": False, "reason": reason}

    def source(request: AcquisitionRequest) -> Mapping[str, Any]:
        observed_at = datetime.now(timezone.utc).isoformat()
        evidence: dict[str, Any] = {
            "asset": {
                "symbol": request.economic_asset_uid,
                "economicAssetUid": request.economic_asset_uid,
                "chainId": request.chain_id,
                "contractAddress": request.contract_address,
            },
            "observedAt": observed_at,
        }
        reference_authority = None
        quote_authority = None
        _resolved_decimals: "int | None" = None

        # -- reference: frozen R1 registry + R2/R7 bound-reference engine
        try:
            registry = _reg_factory()
            try:
                registry_snapshot = registry.fetch_snapshot()
                # UID-based resolution: canonical identity, not ticker
                asset_record = registry_snapshot.get_by_uid(
                    request.economic_asset_uid)
                if asset_record is None:
                    raise RuntimeError(
                        "economic asset uid not found in registry snapshot")
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
                # Token decimals from official registry raw evidence
                _resolved_decimals = _parse_token_decimals(
                    getattr(asset_record, "raw_evidence", {}).get(
                        "tokenDecimals"))
                # C3 / B01: fingerprint-bound decimals are MANDATORY.
                # targetAsset.tokenDecimals must exist and parse correctly;
                # missing or malformed → fail closed, no live-decimals sub.
                _target_asset = (request.provider_config or {}).get(
                    "targetAsset")
                if (not isinstance(_target_asset, Mapping)
                        or "tokenDecimals" not in _target_asset):
                    raise TokenDecimalsUnbound(TOKEN_DECIMALS_AUTHORITY_UNBOUND)
                try:
                    _bound_dec = _parse_token_decimals(
                        _target_asset["tokenDecimals"])
                except TokenDecimalsUnavailable:
                    raise TokenDecimalsUnbound(TOKEN_DECIMALS_AUTHORITY_UNBOUND)
                if _bound_dec != _resolved_decimals:
                    raise TokenDecimalsMismatch(
                        TOKEN_DECIMALS_AUTHORITY_MISMATCH)
                binding_row, price_row = registry.fetch_bound_reference(
                    registry_snapshot, key)
                reference_authority = build_bound_reference_price(
                    asset_record, binding_row, price_row)
                # The preserved evidence identity represents the BOUND
                # snapshot identity, never a mixture with request fields.
                evidence["asset"] = {
                    "symbol": asset_record.token_symbol,
                    "economicAssetUid": asset_record.asset_uid,
                    "chainId": key.chain_id,
                    "contractAddress": key.contract_address,
                }
                evidence["reference"] = {
                    "available": True,
                    "symbol": reference_authority.symbol,
                    "price": str(
                        reference_authority.token_midpoint_usd_per_token),
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
        except TokenDecimalsUnavailable:
            evidence["reference"] = _unavailable(TOKEN_DECIMALS_UNAVAILABLE)
        except TokenDecimalsUnbound:
            evidence["reference"] = _unavailable(
                TOKEN_DECIMALS_AUTHORITY_UNBOUND)
        except TokenDecimalsMismatch:
            evidence["reference"] = _unavailable(
                TOKEN_DECIMALS_AUTHORITY_MISMATCH)
        except ReferenceIdentityMismatch:
            evidence["reference"] = _unavailable(REFERENCE_IDENTITY_MISMATCH)
        except Exception as exc:  # noqa: BLE001 - explicit section state
            evidence["reference"] = _unavailable(type(exc).__name__)

        # -- execution: frozen R0 quote authority for the requested side/size
        try:
            quote_context = QuoteContext.from_material(
                (request.provider_config or {}).get("radarCore"))
            if quote_context.problems:
                evidence["execution"] = _unavailable(
                    quote_context.problems[0])
            elif reference_authority is None:
                evidence["execution"] = _unavailable("REFERENCE_UNAVAILABLE")
            else:
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
                    quote_authority = quote_adapter.quote(QuoteRequest(
                        token=AssetRef(
                            request.chain_id, request.contract_address,
                            symbol=evidence["asset"]["symbol"],
                            decimals=_resolved_decimals),
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
