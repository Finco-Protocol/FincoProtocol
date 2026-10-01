"""Read-only BNB RWA market presentation over typed provider observations."""
from __future__ import annotations

from decimal import Decimal
import os
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Mapping

from finco_radar.assets.contracts import AssetKey
from finco_radar.assets.adapters.robinhood import RobinhoodAssetRegistryAdapter
from finco_radar.authority.contracts import AuthorityPolicy, AuthorityState
from finco_radar.authority.cross_chain import CrossChainIdentityBinding
from finco_radar.gap.engine import build_bound_reference_price

from .bnb_coingecko import CoinGeckoBnbRwaProvider
from .bnb_contracts import BnbRwaMarketObservation, BnbRwaMarketSnapshot
from .bnb_identity import BnbCrossChainIdentityService
from .bnb_intelligence import BnbAuthorityEvidence, compose_bnb_intelligence, unavailable_intelligence
from .bnb_history import BnbIntelligenceHistoryStore, DEFAULT_DB_PATH, make_history_point


_CATEGORY_URL = "https://www.coingecko.com/en/categories/tokenized-products"
_MARKETS_DOC_URL = "https://docs.coingecko.com/reference/coins-markets"
_DEPLOYMENTS_DOC_URL = "https://docs.coingecko.com/reference/coins-list"


def _decimal(value: Decimal | None) -> str | None:
    return str(value) if value is not None else None


def _money(value: Decimal | None) -> str:
    if value is None:
        return "Unavailable"
    for threshold, suffix in (
        (Decimal("1000000000000"), "T"),
        (Decimal("1000000000"), "B"),
        (Decimal("1000000"), "M"),
        (Decimal("1000"), "K"),
    ):
        if abs(value) >= threshold:
            return f"${value / threshold:,.2f}{suffix}"
    return f"${value:,.2f}"


def _percent(value: Decimal | None) -> str:
    return "Unavailable" if value is None else f"{value:+.2f}%"


def _identity_block(binding: CrossChainIdentityBinding | None, key: AssetKey | None) -> dict:
    if binding is None:
        binding = CrossChainIdentityBinding(
            AuthorityState.IDENTITY_UNAVAILABLE, key, None, (), None, None,
            "BNB_DEPLOYMENT_UNAVAILABLE" if key is None else "CANONICAL_IDENTITY_EVIDENCE_UNAVAILABLE",
        )
    return {
        "state": binding.state.value,
        "economic_asset_uid": binding.economic_asset_uid,
        "canonical_deployments": [
            {"chain_id": item.chain_id, "contract_address": item.contract_address,
             "canonical_id": item.canonical_id}
            for item in binding.canonical_deployments
        ],
        "authority_source": binding.authority_source,
        "observed_at": binding.observed_at.isoformat() if binding.observed_at else None,
        "reason": binding.reason,
    }


def _capabilities(
    row_state: AuthorityState,
    key: AssetKey | None,
    identity_state: str,
    intelligence: dict,
) -> dict:
    """Compact capability model for presentation (pure field-presence derivation).

    No ticker/symbol/name/fuzzy/provider-ID/LLM inference anywhere: every
    capability is derived ONLY from evidence fields already resolved by the
    fail-closed authority layers.

      MARKET DATA        AVAILABLE / STALE / UNAVAILABLE   (observed market row)
      BNB DEPLOYMENT     AVAILABLE / UNAVAILABLE           (exact chain-56 AssetKey)
      RH IDENTITY        BOUND / UNBOUND                   (exact source-proven binding)
      REFERENCE PREMIUM  AVAILABLE / NOT SUPPORTED / UNAVAILABLE
                         NOT SUPPORTED = capability cannot exist without a bound
                         Robinhood basis (market-only row); UNAVAILABLE = bound
                         but evidence currently missing.
      EXECUTION          AVAILABLE / NOT SUPPORTED / UNAVAILABLE
                         NOT SUPPORTED = no execution route authority exists for
                         this row; a BNB contract alone never implies execution.
    """
    premium_state = intelligence.get("reference_premium", {}).get("state")
    execution_state = intelligence.get("execution_gap", {}).get("state")
    bound = identity_state == "AVAILABLE"
    premium = ("AVAILABLE" if premium_state == "AVAILABLE"
               else "NOT_SUPPORTED" if not bound
               else "UNAVAILABLE")
    execution = ("AVAILABLE" if execution_state == "AVAILABLE"
                 else "NOT_SUPPORTED" if not bound
                 else "UNAVAILABLE")
    return {
        "market_data": row_state.value,
        "bnb_deployment": "AVAILABLE" if key is not None else "UNAVAILABLE",
        "rh_identity": "BOUND" if bound else "UNBOUND",
        "reference_premium": premium,
        "execution": execution,
    }


def _row(
    row: BnbRwaMarketObservation,
    identities: Mapping[AssetKey, CrossChainIdentityBinding],
    intelligence: Mapping[AssetKey, dict],
    history: Mapping[AssetKey, list[dict]],
) -> dict:
    key = row.asset_key
    identity = _identity_block(identities.get(key) if key is not None else None, key)
    intel = intelligence.get(key, unavailable_intelligence(
        AuthorityState(identity["state"]) if identity["state"] != "AVAILABLE" else AuthorityState.UNAVAILABLE,
        identity["reason"] or "AUTHORITY_EVIDENCE_UNAVAILABLE",
    ))
    capabilities = _capabilities(row.state, key, identity["state"], intel)
    return {
        "provider_id": row.provider_id,
        "symbol": row.symbol,
        "name": row.name,
        "asset_key": None if key is None else {
            "chain_id": key.chain_id,
            "contract_address": key.contract_address,
            "canonical_id": key.canonical_id,
        },
        "deployment_reason": row.deployment_reason,
        "robinhood_binding": identity["state"],
        "canonical_identity": identity,
        "intelligence": intel,
        "capabilities": capabilities,
        "intelligence_history": history.get(key, []),
        "state": row.state.value,
        "observed_at": row.observed_at.isoformat() if row.observed_at else None,
        "price_usd": _decimal(row.price_usd),
        "market_cap_usd": _decimal(row.market_cap_usd),
        "volume_24h_usd": _decimal(row.volume_24h_usd),
        "price_change_24h_pct": _decimal(row.price_change_24h_pct),
        "circulating_supply": _decimal(row.circulating_supply),
        "total_supply": _decimal(row.total_supply),
        "unavailable_fields": list(row.unavailable_fields),
        "source": row.source,
        "provider_asset_id": row.provider_id,
        "market_endpoint": row.market_endpoint,
        "deployment_endpoint": row.deployment_endpoint,
        "classification": row.classification,
        "market_scope": row.market_scope,
        "price_display": _money(row.price_usd),
        "market_cap_display": _money(row.market_cap_usd),
        "volume_display": _money(row.volume_24h_usd),
        "change_display": _percent(row.price_change_24h_pct),
    }


def serialize_bnb_snapshot(
    snapshot: BnbRwaMarketSnapshot,
    identities: Mapping[AssetKey, CrossChainIdentityBinding] | None = None,
    intelligence: Mapping[AssetKey, dict] | None = None,
    history: Mapping[AssetKey, list[dict]] | None = None,
) -> dict:
    rows = [_row(row, identities or {}, intelligence or {}, history or {}) for row in snapshot.observations]
    rows.sort(key=lambda row: (
        row["state"] != "AVAILABLE",
        row["market_cap_usd"] is None,
        -(Decimal(row["market_cap_usd"]) if row["market_cap_usd"] is not None else Decimal(0)),
        row["provider_id"],
    ))
    return {
        "chain": {"name": "BNB Smart Chain", "chain_id": snapshot.chain_id},
        "state": snapshot.state.value,
        "retrieved_at": snapshot.retrieved_at.isoformat(),
        "category_id": snapshot.category_id,
        "category_source_url": _CATEGORY_URL,
        "selection": "Top 250 CoinGecko tokenized-products category rows by market cap; BNB-listed subset",
        "source": snapshot.source,
        "source_endpoints": list(snapshot.source_endpoints),
        "market_source_url": _MARKETS_DOC_URL,
        "deployment_source_url": _DEPLOYMENTS_DOC_URL,
        "market_scope": snapshot.market_scope,
        "observed_count": len(snapshot.observations),
        "deployment_available_count": snapshot.deployment_available_count,
        "deployment_unavailable_count": snapshot.deployment_unavailable_count,
        "current_count": snapshot.current_count,
        "stale_count": snapshot.stale_count,
        "observed_market_cap_usd": _decimal(snapshot.observed_market_cap_usd),
        "observed_volume_24h_usd": _decimal(snapshot.observed_volume_24h_usd),
        "observed_market_cap_display": _money(snapshot.observed_market_cap_usd),
        "observed_volume_24h_display": _money(snapshot.observed_volume_24h_usd),
        "market_cap_contributors": snapshot.market_cap_contributors,
        "volume_contributors": snapshot.volume_contributors,
        "rwa_tvl_usd": None,
        "rwa_tvl_reason": snapshot.rwa_tvl_reason,
        "degraded_reasons": list(snapshot.degraded_reasons),
        "reason": snapshot.reason,
        "observations": rows,
    }


class BnbRwaDashboardService:
    def __init__(self, provider=None, identity_service=None, *, evidence_resolver=None,
                 token_reference_provider=None, execution_quote_provider=None,
                 authority_policy=None, history_store=None, now=None) -> None:
        self.provider = provider or CoinGeckoBnbRwaProvider()
        self.identity_service = identity_service or BnbCrossChainIdentityService()
        # There is no production-approved independent token-reference source yet.
        # An explicit resolver can supply typed evidence; market observations cannot.
        self.evidence_resolver = evidence_resolver
        self.token_reference_provider = token_reference_provider
        self.execution_quote_provider = execution_quote_provider
        self.authority_policy = authority_policy or AuthorityPolicy(
            3600, 120, 60, 60, frozenset(),
        )
        self.now = now or (lambda: datetime.now(timezone.utc))
        self._history_store = history_store
        self._history_lock = Lock()

    def _store(self, *, create: bool) -> BnbIntelligenceHistoryStore | None:
        with self._history_lock:
            location = os.getenv("RADAR_BNB_INTELLIGENCE_DB_PATH", DEFAULT_DB_PATH)
            if self._history_store is None and (create or Path(location).exists()):
                self._history_store = BnbIntelligenceHistoryStore()
            return self._history_store

    def read_history(self, economic_asset_uid: str, key: AssetKey) -> list[dict]:
        store = self._store(create=False)
        return store.read(economic_asset_uid, key) if store else []

    def _default_evidence(self, key: AssetKey, binding: CrossChainIdentityBinding) -> BnbAuthorityEvidence | None:
        """Official basis only; no implicit independent token or route source."""
        selected = getattr(self.identity_service, "selected_registry_snapshot", None)
        registry = selected() if callable(selected) else None
        if registry is None:
            return None
        underlying = None
        try:
            with RobinhoodAssetRegistryAdapter() as adapter:
                reference_binding, price_row = adapter.fetch_bound_reference(registry, key)
            underlying = build_bound_reference_price(registry.require_by_key(key), reference_binding, price_row)
        except Exception:
            pass  # bound-price failure remains typed unavailable in B1.0
        token_reference = None
        execution_quote = None
        if self.token_reference_provider is not None:
            try:
                token_reference = self.token_reference_provider(key, binding)
            except Exception:
                pass
        if self.execution_quote_provider is not None:
            try:
                execution_quote = self.execution_quote_provider(key, binding)
            except Exception:
                pass
        return BnbAuthorityEvidence(registry, underlying, token_reference,
                                    execution_quote, self.authority_policy)

    def read_payload(self) -> dict:
        snapshot = self.provider.read_snapshot()
        try:
            identities = self.identity_service.resolve_snapshot(snapshot)
        except Exception:  # identity failure cannot erase independent market observations
            identities = {}
        intelligence: dict[AssetKey, dict] = {}
        history: dict[AssetKey, list[dict]] = {}
        for row in snapshot.observations:
            key = row.asset_key
            if key is None:
                continue
            binding = identities.get(key)
            evidence = None
            if binding is not None and binding.state is AuthorityState.AVAILABLE:
                try:
                    evidence = (self.evidence_resolver or self._default_evidence)(key, binding)
                except Exception:  # evidence acquisition never becomes price authority
                    evidence = None
            try:
                result = compose_bnb_intelligence(key, binding, evidence, as_of=self.now())
            except Exception:  # invalid evidence fails closed without erasing market observations
                result = unavailable_intelligence(AuthorityState.UNAVAILABLE, "AUTHORITY_EVIDENCE_INVALID")
            intelligence[key] = result
            if binding is not None and binding.state is AuthorityState.AVAILABLE:
                premium_times = result["reference_premium"]["observed_at"]
                execution_time = result["execution"]["observed_at"] if result["execution_gap"]["state"] == "AVAILABLE" else None
                clocks = [datetime.fromisoformat(value) for value in
                          [*premium_times, *([execution_time] if execution_time else [])]]
                observed = max(clocks).astimezone(timezone.utc).isoformat() if clocks else None
                if observed is not None:
                    point = make_history_point(binding, result, observed)
                    if point is not None:
                        try:
                            store = self._store(create=True)
                            assert store is not None
                            store.put(point)
                        except Exception:
                            pass  # history failure cannot turn a valid live calculation into fabricated data
                try:
                    store = self._store(create=False)
                    history[key] = store.read(binding.economic_asset_uid, key) if store else []
                except Exception:
                    history[key] = []
        return serialize_bnb_snapshot(snapshot, identities, intelligence, history)
