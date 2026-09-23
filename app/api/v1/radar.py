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

Test seam:
  set_registry_factory(factory) / clear_registry_factory()
  Same pattern as app.radar_ui.composition._registry_factory_override so
  tests can inject a fake registry without network I/O.
"""
from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional, Tuple

from finco_radar.assets.contracts import (
    CanonicalAssetRecord,
    RegistrySourceError,
    normalize_asset_uid,
)
from finco_radar.equity.models import AvailabilityState, EquityFundamentalsBundle
from finco_radar.equity.service import (
    get_equity_company_history,
    get_equity_fundamentals,
)

from app.api.v1.errors import (
    AssetNotFoundError,
    AssetUidInvalidError,
    RegistryUnavailableError,
)

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
    """Fetch the current registry snapshot. Raises RegistryUnavailableError on failure."""
    try:
        registry = _get_registry()
        return registry.fetch_snapshot()
    except Exception as exc:
        raise RegistryUnavailableError(
            f"Asset registry is unavailable: {type(exc).__name__}: {exc}"
        ) from exc


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


# ── equity authority helpers ──────────────────────────────────────────────────

def _availability_str(bundle: "EquityFundamentalsBundle") -> str:
    return bundle.availability.value


def get_fundamentals_bundle(token_symbol: str) -> "EquityFundamentalsBundle":
    """Fetch the full fundamentals bundle for a token symbol from the equity DB.

    Returns a bundle whose availability field describes the data state.
    Never raises for normal unavailability (DB missing, symbol not found).
    """
    return get_equity_fundamentals(token_symbol)


def get_history_bundle(token_symbol: str):
    """Fetch the full company history bundle for a token symbol from the equity DB."""
    return get_equity_company_history(token_symbol)


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
    equity_asset,
) -> Dict[str, Any]:
    from app.api.v1.schemas import deployment_out, equity_identity_out
    return {
        "token_symbol": record.token_symbol,
        "token_name": record.token_name,
        "status": record.status.value,
        "deployments": [deployment_out(k) for k in record.deployments],
        "equity_identity": equity_identity_out(equity_asset),
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


def build_financials_data(history_bundle) -> Dict[str, Any]:
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
