"""A1 Radar API — adapter layer bridging registry + equity authority.

Identity resolution:
  economic_asset_uid (0x hex) → CanonicalAssetRecord (registry)
                              → token_symbol
                              → EquityFundamentalsBundle / EquityCompanyHistoryBundle

Fail-closed contract:
- normalize_asset_uid() rejects any non-canonical UID format immediately.
- No ticker fallback: an UID not in the registry is NOT_FOUND, never retried
  via ticker lookup.
- Registry unavailable → RegistryUnavailableError (HTTP 503).
- Equity DB unavailable → SOURCE_UNAVAILABLE state in envelope (not a 5xx).
- EquityDBModeError → FUNDAMENTALS_CONFIG_INVALID state in envelope (not a 5xx).

Test seam:
  set_registry_factory(factory) / clear_registry_factory()
  Same pattern as app.radar_ui.composition._registry_factory_override so
  tests can inject a fake registry without network I/O.
"""
from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional, Tuple

import httpx

from finco_radar.assets.contracts import (
    CanonicalAssetRecord,
    RegistryConflictError,
    RegistrySourceError,
    normalize_asset_uid,
)
from finco_radar.equity.models import (
    AvailabilityState,
    EquityCompanyHistoryBundle,
    EquityFundamentalsBundle,
    FundamentalsFreshness,
)
from finco_radar.equity.service import (
    EquityDBModeError,
    get_equity_company_history,
    get_equity_fundamentals,
)

from app.api.v1.errors import (
    AssetNotFoundError,
    AssetUidInvalidError,
    RegistryUnavailableError,
)

_TARGET_CHAIN_ID = 4663

# ── test seam ─────────────────────────────────────────────────────────────────

_registry_factory_override: Optional[Callable] = None


def set_registry_factory(factory: Optional[Callable]) -> None:
    """Inject a fake registry factory for tests. Pass None to clear."""
    global _registry_factory_override
    _registry_factory_override = factory


def clear_registry_factory() -> None:
    global _registry_factory_override
    _registry_factory_override = None


def _get_registry():
    """Return a registry adapter instance, honouring the test seam."""
    if _registry_factory_override is not None:
        return _registry_factory_override()
    from finco_radar.assets.adapters.robinhood import RobinhoodAssetRegistryAdapter
    return RobinhoodAssetRegistryAdapter(timeout_seconds=4.0)


# ── registry helpers ──────────────────────────────────────────────────────────

def _fetch_snapshot():
    """Fetch the current registry snapshot.

    Raises RegistryUnavailableError on expected network/parse failures.
    Programming errors (AttributeError, TypeError, etc.) propagate as-is.
    Registry adapter close() is always called when the adapter was created.
    """
    registry = None
    try:
        registry = _get_registry()
        return registry.fetch_snapshot()
    except (httpx.HTTPError, RegistrySourceError, RegistryConflictError) as exc:
        raise RegistryUnavailableError(
            "Asset registry is temporarily unavailable."
        ) from exc
    finally:
        if registry is not None:
            close = getattr(registry, "close", None)
            if callable(close):
                close()


def validate_uid(raw_uid: str) -> str:
    """Validate and normalise an economic_asset_uid. Raises AssetUidInvalidError on failure."""
    try:
        return normalize_asset_uid(raw_uid)
    except RegistrySourceError as exc:
        raise AssetUidInvalidError(raw_uid, str(exc)) from exc


def resolve_asset(uid: str) -> Tuple[str, "CanonicalAssetRecord"]:
    """Validate UID and resolve it to a canonical asset record.

    Returns (normalised_uid, record).
    Raises AssetUidInvalidError, AssetNotFoundError, or RegistryUnavailableError.
    """
    normalised = validate_uid(uid)
    snapshot = _fetch_snapshot()
    record = snapshot.get_by_uid(normalised)
    if record is None:
        raise AssetNotFoundError(normalised)
    return normalised, record


def list_assets() -> List["CanonicalAssetRecord"]:
    """Return all canonical assets from the current registry snapshot."""
    snapshot = _fetch_snapshot()
    return list(snapshot.assets)


# ── equity identity binding ───────────────────────────────────────────────────

def bind_equity_identity(record: "CanonicalAssetRecord", bundle: Any) -> str:
    """Validate that the equity bundle's asset identity matches the registry record.

    Truth table:
      E1 contract missing
        → permitted (BOUND when symbol matches)
      E1 contract present + chain-4663 deployment exists + addresses match
        → BOUND
      E1 contract present + chain-4663 deployment exists + addresses differ
        → IDENTITY_MISMATCH
      E1 contract present + NO chain-4663 deployment
        → IDENTITY_MISMATCH (fail-closed; ticker alone must not authorize a contract)

    Returns one of: BOUND, IDENTITY_MISMATCH, NOT_FOUND, SOURCE_UNAVAILABLE,
    FUNDAMENTALS_CONFIG_INVALID, NOT_AVAILABLE.
    BOUND is an internal result; it must never appear in a public response field.
    """
    av: AvailabilityState = bundle.availability
    if av not in (
        AvailabilityState.AVAILABLE,
        AvailabilityState.PARTIAL,
        AvailabilityState.NOT_AVAILABLE,
    ):
        return av.value
    asset = bundle.asset
    if asset is None:
        return av.value
    if asset.robinhood_token_symbol.upper() != record.token_symbol.upper():
        return "IDENTITY_MISMATCH"
    if asset.token_contract_address:
        dep = record.deployment_for_chain(_TARGET_CHAIN_ID)
        if dep is None:
            # E1 supplies a contract but the registry has no chain-4663 deployment:
            # ticker alone must not authorize the supplied contract address.
            return "IDENTITY_MISMATCH"
        if asset.token_contract_address.lower() != dep.contract_address.lower():
            return "IDENTITY_MISMATCH"
    return "BOUND"


# ── equity authority helpers ──────────────────────────────────────────────────

def _empty_freshness() -> FundamentalsFreshness:
    return FundamentalsFreshness(
        ttm_period_end=None,
        ttm_filing_date=None,
        ttm_fetched_at=None,
        ttm_normalized_at=None,
        quarterly_period_end=None,
        quarterly_fetched_at=None,
        annual_period_end=None,
        annual_fetched_at=None,
        profile_fetched_at=None,
        asset_last_seen_at=None,
    )


def _make_config_invalid_bundle(token_symbol: str) -> "EquityFundamentalsBundle":
    return EquityFundamentalsBundle(
        robinhood_token_symbol=token_symbol,
        asset=None,
        company_profile=None,
        latest_ttm=None,
        latest_quarterly=None,
        latest_annual=None,
        recent_dividends=(),
        recent_splits=(),
        source_lineage_summary=(),
        availability=AvailabilityState.FUNDAMENTALS_CONFIG_INVALID,
        freshness=_empty_freshness(),
    )


def _make_config_invalid_history_bundle(token_symbol: str) -> "EquityCompanyHistoryBundle":
    return EquityCompanyHistoryBundle(
        robinhood_token_symbol=token_symbol,
        asset=None,
        company_profile=None,
        annual_history=(),
        quarterly_history=(),
        ttm_history=(),
        recent_dividends=(),
        recent_splits=(),
        source_lineage=(),
        availability=AvailabilityState.FUNDAMENTALS_CONFIG_INVALID,
        freshness=_empty_freshness(),
    )


def get_fundamentals_bundle(token_symbol: str) -> "EquityFundamentalsBundle":
    """Fetch the full fundamentals bundle for a token symbol from the equity DB.

    Returns a bundle whose availability field describes the data state.
    Never raises for normal unavailability (DB missing, symbol not found).
    Returns FUNDAMENTALS_CONFIG_INVALID bundle if DB mode env var is invalid.
    """
    try:
        return get_equity_fundamentals(token_symbol)
    except EquityDBModeError:
        return _make_config_invalid_bundle(token_symbol)


def get_history_bundle(token_symbol: str) -> "EquityCompanyHistoryBundle":
    """Fetch the full company history bundle for a token symbol from the equity DB."""
    try:
        return get_equity_company_history(token_symbol)
    except EquityDBModeError:
        return _make_config_invalid_history_bundle(token_symbol)


# ── response builders ─────────────────────────────────────────────────────────

def build_asset_list_data(records: List["CanonicalAssetRecord"]) -> Dict[str, Any]:
    from app.api.v1.schemas import deployment_out
    return {
        "assets": [
            {
                "economic_asset_uid": r.asset_uid,
                "token_symbol": r.token_symbol,
                "token_name": r.token_name,
                "status": r.status.value,
                "deployments": [deployment_out(k) for k in r.deployments],
            }
            for r in records
        ],
        "total": len(records),
    }


def build_identity_data(
    record: "CanonicalAssetRecord",
    bundle: "EquityFundamentalsBundle",
    binding: str,
) -> Dict[str, Any]:
    """Build the identity response data dict.

    fundamentals_state is NEVER 'BOUND' (BOUND is internal).
    When binding == 'BOUND': fundamentals_state = bundle.availability.value.
    Otherwise: fundamentals_state = binding (IDENTITY_MISMATCH or an availability state).

    equity_identity is populated only when identity is safely bound.
    """
    from app.api.v1.schemas import deployment_out, equity_identity_out
    fundamentals_state = bundle.availability.value if binding == "BOUND" else binding
    return {
        "token_symbol": record.token_symbol,
        "token_name": record.token_name,
        "status": record.status.value,
        "deployments": [deployment_out(k) for k in record.deployments],
        "fundamentals_state": fundamentals_state,
        "equity_identity": equity_identity_out(bundle.asset) if binding == "BOUND" else None,
    }


def build_fundamentals_data(bundle: "EquityFundamentalsBundle") -> Dict[str, Any]:
    from app.api.v1.schemas import snapshot_out, company_profile_out
    return {
        "availability": bundle.availability.value,
        "ttm": snapshot_out(bundle.latest_ttm),
        "quarterly": snapshot_out(bundle.latest_quarterly),
        "annual": snapshot_out(bundle.latest_annual),
        "company_profile": company_profile_out(bundle.company_profile),
    }


def build_financials_data(history_bundle: "EquityCompanyHistoryBundle") -> Dict[str, Any]:
    from app.api.v1.schemas import snapshot_out
    return {
        "availability": history_bundle.availability.value,
        "annual_history": [snapshot_out(s) for s in history_bundle.annual_history],
        "quarterly_history": [snapshot_out(s) for s in history_bundle.quarterly_history],
        "ttm_history": [snapshot_out(s) for s in history_bundle.ttm_history],
    }


def build_corporate_actions_data(bundle: "EquityFundamentalsBundle") -> Dict[str, Any]:
    from app.api.v1.schemas import dividend_out, split_out
    return {
        "availability": bundle.availability.value,
        "dividends": [dividend_out(d) for d in bundle.recent_dividends],
        "splits": [split_out(s) for s in bundle.recent_splits],
    }


def build_evidence_data(bundle: "EquityFundamentalsBundle") -> Dict[str, Any]:
    from app.api.v1.schemas import lineage_out
    return {
        "availability": bundle.availability.value,
        "source_lineage": [lineage_out(l) for l in bundle.source_lineage_summary],
    }
