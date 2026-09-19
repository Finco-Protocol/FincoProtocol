"""P3: read-only quote context — settlement reference + taker address.

Closes the P2 composition limitation ``SETTLEMENT_RESOLVER_NOT_WIRED``.

Design invariants:

- **No fabricated settlement authority.**  The settlement identity and
  value are OPERATOR CONFIGURATION (environment), never invented here.
  Nothing assumes ``1 settlement token = 1 USD``; the configured
  ``usd_per_asset`` and its ``source`` label are required, and the frozen
  ``SettlementReferenceState`` must be explicitly configured.
- **Fail closed.**  Missing or malformed configuration produces stable
  product-layer reasons (``SETTLEMENT_NOT_CONFIGURED``,
  ``SETTLEMENT_IDENTITY_INVALID``, ``SETTLEMENT_CHAIN_MISMATCH``,
  ``SETTLEMENT_REFERENCE_INVALID``, ``SETTLEMENT_REFERENCE_UNUSABLE``,
  ``QUOTE_TAKER_ADDRESS_NOT_CONFIGURED``, ``QUOTE_TAKER_ADDRESS_INVALID``)
  and the LI.FI quote authority is never invoked.
- **One canonical ownership path (P6).**  The resolved context is bound
  into the P1 ``AcquisitionRequest.provider_config`` fingerprint material
  (safe, public, deterministic identity only) and the provider callable
  reconstructs its settlement/taker context from THAT SAME material —
  no config split-brain, and any context change changes the fingerprint.
- **The quote taker address is public, non-secret routing context** used
  only as the frozen ``QuoteRequest.taker_address`` for read-only quote
  retrieval.  It is not a connected wallet, not custody, not
  authorization, and no private key/seed/signature exists anywhere in
  this flow.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping

from app.radar_runtime.contracts import RuntimeContractError
from finco_radar.quotes.contracts import (
    AssetRef,
    SettlementReference,
    SettlementReferenceState,
)

SETTLEMENT_NOT_CONFIGURED = "SETTLEMENT_NOT_CONFIGURED"
SETTLEMENT_IDENTITY_INVALID = "SETTLEMENT_IDENTITY_INVALID"
SETTLEMENT_CHAIN_MISMATCH = "SETTLEMENT_CHAIN_MISMATCH"
SETTLEMENT_REFERENCE_INVALID = "SETTLEMENT_REFERENCE_INVALID"
SETTLEMENT_REFERENCE_UNUSABLE = "SETTLEMENT_REFERENCE_UNUSABLE"
QUOTE_TAKER_ADDRESS_NOT_CONFIGURED = "QUOTE_TAKER_ADDRESS_NOT_CONFIGURED"
QUOTE_TAKER_ADDRESS_INVALID = "QUOTE_TAKER_ADDRESS_INVALID"

_EVM_ADDRESS_RE = re.compile(r"0x[0-9a-fA-F]{40}")


class SettlementContextError(RuntimeContractError):
    """Typed fail-closed settlement-context error carrying the stable
    product-layer reason (never a raw parser exception)."""


@dataclass(frozen=True)
class QuoteContext:
    """Immutable, deterministic read-only quote context resolved from
    product configuration.  ``problems`` carries stable fail-closed
    reasons; an empty tuple means the context is fully usable."""

    settlement_chain_id: "int | None"
    settlement_contract_address: "str | None"
    settlement_symbol: "str | None"
    settlement_decimals: "int | None"
    settlement_state: "str | None"
    settlement_usd_per_asset: "str | None"
    settlement_source: "str | None"
    settlement_observed_at: "str | None"
    quote_taker_address: "str | None"
    problems: "tuple[str, ...]" = ()

    def fingerprint_material(self) -> dict[str, Any]:
        """Safe, public, deterministic identity bound into the P1 request
        fingerprint.  NO transient values (timestamps, observed prices,
        raw payloads) and NO secrets."""
        return {
            "settlementChainId": self.settlement_chain_id,
            "settlementContractAddress": self.settlement_contract_address,
            "settlementSymbol": self.settlement_symbol,
            "settlementDecimals": self.settlement_decimals,
            "settlementState": self.settlement_state,
            "settlementUsdPerAsset": self.settlement_usd_per_asset,
            "settlementSourceId": self.settlement_source,
            "quoteTakerAddress": self.quote_taker_address,
            "problems": list(self.problems),
        }

    @classmethod
    def from_material(cls, material: Any) -> "QuoteContext":
        """Reconstruct the context from the fingerprint material carried
        by the P1 request (P6: the provider callable consumes exactly the
        configuration that was fingerprinted)."""
        if not isinstance(material, Mapping):
            material = {}
        problems = material.get("problems")
        # P1 deep-freeze persists lists as tuples — accept both
        if isinstance(problems, (list, tuple)):
            problems = tuple(problems)
        else:
            problems = ()
        return cls(
            settlement_chain_id=material.get("settlementChainId"),
            settlement_contract_address=material.get(
                "settlementContractAddress"),
            settlement_symbol=material.get("settlementSymbol"),
            settlement_decimals=material.get("settlementDecimals"),
            settlement_state=material.get("settlementState"),
            settlement_usd_per_asset=material.get("settlementUsdPerAsset"),
            settlement_source=material.get("settlementSourceId"),
            settlement_observed_at=None,
            quote_taker_address=material.get("quoteTakerAddress"),
            problems=problems,
        )


def _env(name: str) -> "str | None":
    value = os.getenv(name)
    return value if value not in (None, "") else None


def resolve_quote_context(*, expected_chain_id: "int | None" = None) -> QuoteContext:
    """Resolve the read-only quote context from product configuration.

    Collects stable fail-closed problems; NEVER fabricates a settlement
    identity, value, state or source."""
    problems: list[str] = []

    # -- quote taker address (public, non-secret routing context) --------
    taker = _env("RADAR_V1_QUOTE_TAKER_ADDRESS")
    if taker is None:
        problems.append(QUOTE_TAKER_ADDRESS_NOT_CONFIGURED)
    elif not _EVM_ADDRESS_RE.fullmatch(taker):
        # malformed configured values are KEPT in the context so the
        # typed reason carries through; they never reach LI.FI
        problems.append(QUOTE_TAKER_ADDRESS_INVALID)

    # -- settlement identity / value authority ---------------------------
    raw_address = _env("RADAR_V1_SETTLEMENT_ADDRESS")
    raw_usd = _env("RADAR_V1_SETTLEMENT_USD_PER_ASSET")
    raw_source = _env("RADAR_V1_SETTLEMENT_SOURCE")
    raw_state = _env("RADAR_V1_SETTLEMENT_STATE")
    raw_symbol = _env("RADAR_V1_SETTLEMENT_SYMBOL")
    raw_decimals = _env("RADAR_V1_SETTLEMENT_DECIMALS")
    raw_chain = _env("RADAR_V1_SETTLEMENT_CHAIN_ID")

    settlement_chain_id: "int | None" = None
    settlement_contract_address: "str | None" = None
    settlement_symbol: "str | None" = raw_symbol
    settlement_decimals: "int | None" = None
    settlement_state: "str | None" = raw_state
    settlement_usd_per_asset: "str | None" = raw_usd
    settlement_source: "str | None" = raw_source

    if all(v is None for v in (raw_address, raw_usd, raw_source, raw_state)):
        problems.append(SETTLEMENT_NOT_CONFIGURED)
    else:
        if any(v is None for v in (raw_address, raw_usd, raw_source,
                                   raw_state)):
            # partial configuration is not usable and not silently completed
            problems.append(SETTLEMENT_NOT_CONFIGURED)
        if raw_address is not None:
            if not _EVM_ADDRESS_RE.fullmatch(raw_address):
                # malformed identity is kept for reason fidelity and
                # re-validated (typed) at SettlementReference construction
                problems.append(SETTLEMENT_IDENTITY_INVALID)
                settlement_contract_address = raw_address
            else:
                settlement_contract_address = raw_address
        if raw_chain is not None:
            try:
                settlement_chain_id = int(raw_chain)
            except (TypeError, ValueError):
                problems.append(SETTLEMENT_IDENTITY_INVALID)
                settlement_chain_id = None
        elif expected_chain_id is not None:
            settlement_chain_id = expected_chain_id
        if raw_decimals is not None:
            try:
                decimals = int(raw_decimals)
            except (TypeError, ValueError):
                decimals = -1
            if not 0 <= decimals <= 255:
                problems.append(SETTLEMENT_IDENTITY_INVALID)
            else:
                settlement_decimals = decimals
        if raw_state is not None and raw_state not in {
            s.value for s in SettlementReferenceState
        }:
            problems.append(SETTLEMENT_REFERENCE_INVALID)
        if raw_usd is not None:
            try:
                usd = Decimal(raw_usd)
            except (InvalidOperation, TypeError, ValueError):
                usd = None
            if usd is None or not usd.is_finite() or usd <= 0:
                problems.append(SETTLEMENT_REFERENCE_INVALID)
        if (expected_chain_id is not None and settlement_chain_id is not None
                and settlement_chain_id != expected_chain_id):
            problems.append(SETTLEMENT_CHAIN_MISMATCH)

    return QuoteContext(
        settlement_chain_id=settlement_chain_id,
        settlement_contract_address=settlement_contract_address,
        settlement_symbol=settlement_symbol,
        settlement_decimals=settlement_decimals,
        settlement_state=settlement_state,
        settlement_usd_per_asset=settlement_usd_per_asset,
        settlement_source=settlement_source,
        settlement_observed_at=None,
        quote_taker_address=taker,
        problems=tuple(problems),
    )


def quote_taker_address(context: QuoteContext) -> str:
    """Return the validated public taker routing address, or raise the
    stable typed reason.  The frozen QuoteRequest re-validates with its
    own normalization; this pre-check guarantees LI.FI is never invoked
    with missing/malformed context."""
    taker = context.quote_taker_address
    if taker is None:
        raise SettlementContextError(QUOTE_TAKER_ADDRESS_NOT_CONFIGURED)
    if not _EVM_ADDRESS_RE.fullmatch(taker):
        raise SettlementContextError(QUOTE_TAKER_ADDRESS_INVALID)
    return taker


def build_settlement_reference(context: QuoteContext,
                               *, expected_chain_id: int) -> SettlementReference:
    """Build the FROZEN ``SettlementReference`` from the fingerprint-bound
    context, fail-closed with stable reasons.  The frozen ``usable``
    semantics (state + positive value) decide final usability — never a
    product-layer override."""
    if (context.settlement_contract_address is None
            or context.settlement_state is None
            or context.settlement_usd_per_asset is None
            or context.settlement_source is None):
        raise SettlementContextError(SETTLEMENT_NOT_CONFIGURED)
    if context.settlement_chain_id is None:
        raise SettlementContextError(SETTLEMENT_IDENTITY_INVALID)
    if context.settlement_chain_id != expected_chain_id:
        raise SettlementContextError(SETTLEMENT_CHAIN_MISMATCH)
    if context.settlement_state not in {
        s.value for s in SettlementReferenceState
    }:
        raise SettlementContextError(SETTLEMENT_REFERENCE_INVALID)
    try:
        usd = Decimal(context.settlement_usd_per_asset)
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise SettlementContextError(SETTLEMENT_REFERENCE_INVALID) from exc
    if not usd.is_finite() or usd <= 0:
        raise SettlementContextError(SETTLEMENT_REFERENCE_INVALID)
    try:
        settlement_asset = AssetRef(
            chain_id=context.settlement_chain_id,
            contract_address=context.settlement_contract_address,
            symbol=context.settlement_symbol,
            decimals=context.settlement_decimals,
        )
    except ValueError as exc:
        raise SettlementContextError(SETTLEMENT_IDENTITY_INVALID) from exc
    observed_at = None
    if context.settlement_observed_at:
        observed_at = datetime.fromisoformat(context.settlement_observed_at)
    settlement = SettlementReference(
        asset=settlement_asset,
        state=SettlementReferenceState(context.settlement_state),
        usd_per_asset=usd,
        source=context.settlement_source,
        observed_at=observed_at,
    )
    if not settlement.usable:
        raise SettlementContextError(SETTLEMENT_REFERENCE_UNUSABLE)
    return settlement
