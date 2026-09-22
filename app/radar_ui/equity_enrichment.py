"""E2 equity enrichment bridge — selected Radar asset → E1 fundamentals bundle.

Sits between the Radar UI layer and the E1 public service.  Never imports
sqlite3; all DB access goes through finco_radar.equity.get_equity_fundamentals.

Responsibilities:
- selected Robinhood token_symbol + contract_address → E1 bundle
- identity validation (token symbol match + contract address match)
- typed enrichment state
- no formatting, no financial derivation
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Optional

from finco_radar.equity import AvailabilityState, EquityFundamentalsBundle
from finco_radar.equity import get_equity_fundamentals
from finco_radar.equity.config import EquityDBModeError


class EnrichmentState(str, Enum):
    AVAILABLE = "AVAILABLE"
    PARTIAL = "PARTIAL"
    NOT_FOUND = "NOT_FOUND"
    NOT_AVAILABLE = "NOT_AVAILABLE"
    SOURCE_UNAVAILABLE = "SOURCE_UNAVAILABLE"
    IDENTITY_MISMATCH = "IDENTITY_MISMATCH"
    FUNDAMENTALS_CONFIG_INVALID = "FUNDAMENTALS_CONFIG_INVALID"


@dataclass(frozen=True)
class EquityEnrichmentResult:
    """Typed result of an E1 enrichment lookup for one selected Radar asset."""

    state: EnrichmentState
    bundle: Optional[EquityFundamentalsBundle]
    identity_note: Optional[str]


_AVAILABILITY_TO_STATE: dict[AvailabilityState, EnrichmentState] = {
    AvailabilityState.AVAILABLE: EnrichmentState.AVAILABLE,
    AvailabilityState.PARTIAL: EnrichmentState.PARTIAL,
    AvailabilityState.NOT_AVAILABLE: EnrichmentState.NOT_AVAILABLE,
    AvailabilityState.NOT_FOUND: EnrichmentState.NOT_FOUND,
    AvailabilityState.SOURCE_UNAVAILABLE: EnrichmentState.SOURCE_UNAVAILABLE,
}


def _validate_identity(
    token_symbol: str,
    contract_address: str,
    bundle: EquityFundamentalsBundle,
) -> Optional[str]:
    """Return None when identity is consistent, or a reason string when not.

    Checks token symbol (case-normalised) and, when both sides supply a
    contract address, checks those too (case-insensitive).
    A missing E1 contract address is not treated as a mismatch.
    """
    if bundle.asset is None:
        return None
    if bundle.asset.robinhood_token_symbol.upper() != token_symbol.upper():
        return (
            f"TOKEN_SYMBOL_MISMATCH: E1={bundle.asset.robinhood_token_symbol!r} "
            f"selected={token_symbol!r}"
        )
    if bundle.asset.token_contract_address and contract_address:
        if bundle.asset.token_contract_address.lower() != contract_address.lower():
            return (
                f"CONTRACT_ADDRESS_MISMATCH: E1={bundle.asset.token_contract_address!r} "
                f"selected={contract_address!r}"
            )
    return None


def enrich_selected_asset(
    token_symbol: str,
    contract_address: str,
    *,
    db_path: Optional[Path] = None,
    db_mode: Optional[str] = None,
) -> EquityEnrichmentResult:
    """Look up E1 fundamentals for a selected Radar asset.

    Never raises — all failure modes are mapped to typed enrichment states so
    the rest of /radar remains usable when fundamentals are unavailable.

    Identity mismatch suppresses financial metrics (IDENTITY_MISMATCH state)
    but the bundle is still returned so the caller can inspect it if needed.

    EquityDBModeError (programmer config mistake) is mapped to
    FUNDAMENTALS_CONFIG_INVALID so /radar does not crash on bad env config.
    """
    try:
        bundle = get_equity_fundamentals(
            token_symbol,
            db_path=db_path,
            db_mode=db_mode,
        )
    except EquityDBModeError as exc:
        return EquityEnrichmentResult(
            state=EnrichmentState.FUNDAMENTALS_CONFIG_INVALID,
            bundle=None,
            identity_note=str(exc),
        )
    except Exception:  # noqa: BLE001
        return EquityEnrichmentResult(
            state=EnrichmentState.SOURCE_UNAVAILABLE,
            bundle=None,
            identity_note=None,
        )

    state = _AVAILABILITY_TO_STATE.get(
        bundle.availability, EnrichmentState.SOURCE_UNAVAILABLE
    )

    if state in (EnrichmentState.AVAILABLE, EnrichmentState.PARTIAL):
        mismatch = _validate_identity(token_symbol, contract_address, bundle)
        if mismatch is not None:
            return EquityEnrichmentResult(
                state=EnrichmentState.IDENTITY_MISMATCH,
                bundle=bundle,
                identity_note=mismatch,
            )

    return EquityEnrichmentResult(state=state, bundle=bundle, identity_note=None)
