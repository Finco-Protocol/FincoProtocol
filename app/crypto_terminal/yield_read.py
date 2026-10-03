"""Shared Yield read model for the Explore surface and the crypto API.

Composes the EXISTING canonical Yield authorities — no new mathematics:

    registry / snapshot   finco_yield.registry + finco_yield.snapshot
    canonical history     finco_yield.history (read-only)
    market intelligence   finco_yield.market (movers / sigma / spread)
    per-pool intelligence finco_yield.intelligence
    treasury benchmark    finco_yield.treasury
"""
from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any

from finco_yield.history import YieldHistoryStore
from finco_yield.intelligence import IntelligenceStatus, build_intelligence
from finco_yield.market import MOVER_MIN_TVL_USD, build_market_view
from finco_yield.snapshot import load_active_registry
from finco_yield.treasury import latest_treasury


def _history_path() -> str:
    return os.getenv("FINCO_YIELD_HISTORY_PATH", "").strip()


def market_snapshot(*, now: datetime | None = None,
                    include_market: bool = True) -> dict[str, Any]:
    """One canonical history read -> registry + market view + treasury.

    Returns the raw authorities so both the UI and the API can serialize
    from the SAME objects (never two independent recomputations).
    ``include_market=False`` skips building the history-derived market view
    entirely — used when a caller is not entitled to it, so the protected
    payload is never constructed (not built-then-redacted)."""
    now = now or datetime.now(timezone.utc)
    registry, source_status = load_active_registry()
    path = _history_path()
    treasury = latest_treasury()
    if not path or not include_market:
        # No configured history: canonical market intelligence is unavailable
        # (the registry alone is identity, never market-current values).
        from finco_yield.market import MarketView
        market = MarketView(as_of=now, tvl_floor=MOVER_MIN_TVL_USD,
                            pools_observed=0, pools_above_floor=0,
                            movers={"24h": [], "7d": []}, pools={},
                            median_apy=None, best_apy=None, treasury=treasury)
        return {"registry": registry, "source_status": source_status,
                "store_path": None, "market": market, "treasury": treasury,
                "as_of": now}
    store = YieldHistoryStore(path)
    market = build_market_view(store, registry, as_of=now,
                               tvl_floor=MOVER_MIN_TVL_USD, treasury=treasury)
    return {"registry": registry, "source_status": source_status,
            "store_path": path, "market": market, "treasury": treasury,
            "as_of": now}


def pool_rows(view: dict[str, Any]) -> list[dict[str, Any]]:
    """Per-pool serialization shared by the API and usable by the UI."""
    market: Any = view["market"]
    rows = []
    for opportunity in view["registry"].all():
        intel = market.pools.get(opportunity.uid)
        observation = opportunity.observation
        native_30d = observation.apy_total_30d_avg
        fallback_30d = None
        if native_30d is None and intel is not None and intel.sigma_30d is not None:
            # FINCO_HISTORICAL fallback belongs to intelligence; only expose
            # it when the canonical market view actually derived values.
            pass
        rows.append({
            "canonical_id": opportunity.uid,
            "name": opportunity.name,
            "protocol": opportunity.protocol,
            "chain_id": opportunity.chain_id,
            "underlying_symbol": opportunity.underlying_symbol,
            "data_origin": opportunity.data_origin,
            "apy_total": (float(observation.apy_total)
                          if observation.apy_total is not None else None),
            "tvl_usd": (float(observation.tvl_usd)
                        if observation.tvl_usd is not None else None),
            "apy_total_30d_avg": (float(native_30d)
                                  if native_30d is not None else None),
            "apy_30d_avg_source": observation.apy_30d_avg_source,
            "latest_apy": (float(intel.latest_apy)
                           if intel is not None and intel.latest_apy is not None
                           else None),
            "latest_tvl": (float(intel.latest_tvl)
                           if intel is not None and intel.latest_tvl is not None
                           else None),
            "currentness": intel.currentness if intel is not None else "UNAVAILABLE",
            "delta_24h_bps": (_float_or_none(intel.deltas.get("24h"))
                              if intel is not None else None),
            "delta_24h_direction": (intel.directions.get("24h", "UNAVAILABLE")
                                    if intel is not None else "UNAVAILABLE"),
            "delta_7d_bps": (_float_or_none(intel.deltas.get("7d"))
                             if intel is not None else None),
            "delta_7d_direction": (intel.directions.get("7d", "UNAVAILABLE")
                                   if intel is not None else "UNAVAILABLE"),
            "sigma_30d": (_float_or_none(intel.sigma_30d)
                          if intel is not None else None),
            "sigma_source": (intel.sigma_source or None)
                            if intel is not None else None,
            "spread_bps": (_float_or_none(intel.spread_bps)
                           if intel is not None else None),
            "spread_source": (intel.spread_source or None)
                             if intel is not None else None,
            "sparkline": (list(intel.sparkline)
                          if intel is not None else []),
        })
    return rows


def summary(view: dict[str, Any]) -> dict[str, Any]:
    market: Any = view["market"]
    treasury = view["treasury"]
    source_status = view["source_status"]
    return {
        "provenance": {
            "source_status_origin": source_status.origin,
            "source_status_reason": source_status.reason,
            "source_status_generated_at": source_status.generated_at,
            "source_status_live_rows": source_status.live_rows,
            "source_status_reference_rows": source_status.reference_rows,
        },
        "pools_observed": market.pools_observed,
        "pools_above_floor": market.pools_above_floor,
        "tvl_floor": str(market.tvl_floor),
        "median_apy": _float_or_none(market.median_apy),
        "best_apy": ({"canonical_id": market.best_apy["uid"],
                      "name": market.best_apy["name"],
                      "apy": _float_or_none(market.best_apy["apy"])}
                     if market.best_apy else None),
        "treasury": {
            "source": treasury.source,
            "state": treasury.state,
            "yield_percent": _float_or_none(treasury.yield_percent),
            "period": treasury.period,
        },
    }


def movers(view: dict[str, Any], horizon: str) -> list[dict[str, Any]]:
    return [{
        "canonical_id": m.uid,
        "name": m.name,
        "apy_total": _float_or_none(m.apy_total),
        "delta_bps": _float_or_none(m.delta_bps),
        "direction": m.direction,
        "tvl_usd": _float_or_none(m.tvl_usd),
        "rank": m.rank,
    } for m in view["market"].movers.get(horizon, [])]


def pool_detail(canonical_id: str, *, now: datetime | None = None,
                include_history_intelligence: bool = True,
                history_access: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """One pool: BASIC identity/current fields, plus — ONLY when
    ``include_history_intelligence`` is True (YieldResource.HISTORY
    access_allowed) — the canonical-history-derived intelligence
    (horizons, deltas, sigma, spread, sparkline).  When False, the
    protected payload is never built: ``build_intelligence`` is not called
    and the history-derived market view is not constructed."""
    now = now or datetime.now(timezone.utc)
    view = market_snapshot(now=now,
                           include_market=include_history_intelligence)
    opportunity = next((o for o in view["registry"].all() if o.uid == canonical_id),
                       None)
    if opportunity is None:
        return None
    intel = view["market"].pools.get(canonical_id) if include_history_intelligence else None
    intelligence = build_intelligence(
        YieldHistoryStore(view["store_path"]), canonical_id, as_of=now) \
        if (include_history_intelligence and view["store_path"]) else None
    horizons = []
    if intelligence is not None and intelligence.status == IntelligenceStatus.AVAILABLE:
        for h in intelligence.horizons:
            horizons.append({
                "horizon": h.horizon,
                "coverage": h.coverage.value,
                "apy_delta_bps": _float_or_none(h.apy_delta.delta_bps),
                "apy_direction": h.apy_delta.direction.value,
                "apy_sigma": _float_or_none(h.apy_sigma),
                "apy_sigma_source": h.apy_sigma_source,
                "observation_count": h.observation_count,
            })
    source_status = view["source_status"]
    detail = {
        "canonical_id": canonical_id,
        "name": opportunity.name,
        "protocol": opportunity.protocol,
        "chain_id": opportunity.chain_id,
        "underlying_symbol": opportunity.underlying_symbol,
        "provider": opportunity.provider,
        "data_origin": opportunity.data_origin,
        "origin": ("LIVE" if opportunity.data_origin == "SOURCE_OBSERVED"
                   else "REFERENCE"),
        "provenance": {
            "source_status_origin": source_status.origin,
            "source_status_reason": source_status.reason,
            "source_status_generated_at": source_status.generated_at,
            "source_status_live_rows": source_status.live_rows,
            "source_status_reference_rows": source_status.reference_rows,
        },
        "observed_at": (opportunity.observed_at.isoformat()
                        if opportunity.observed_at else None),
        "current_apy": _float_or_none(opportunity.observation.apy_total),
        "tvl_usd": _float_or_none(opportunity.observation.tvl_usd),
        "base_apy": _float_or_none(opportunity.observation.apy_base),
        "rewards_apy": _float_or_none(opportunity.observation.apy_rewards),
        "apy_30d_avg": _float_or_none(opportunity.observation.apy_total_30d_avg),
        "apy_30d_avg_source": opportunity.observation.apy_30d_avg_source,
        "intel": ({"status": intelligence.status.value,
                   "freshness": (intelligence.freshness.state
                                 if intelligence.freshness else "UNAVAILABLE"),
                   "latest_observed_at": (
                       intelligence.latest.observed_at.isoformat()
                       if intelligence is not None and intelligence.latest
                       else None),
                   "horizons": horizons}
                  if intelligence is not None else
                  ({"status": "INSUFFICIENT_HISTORY", "horizons": []}
                   if include_history_intelligence else None)),
        "market": ({"currentness": intel.currentness,
                    "latest_apy": _float_or_none(intel.latest_apy),
                    "latest_apy_observed_at": (
                        intel.latest_apy_observed_at.isoformat()
                        if intel is not None and intel.latest_apy_observed_at
                        else None),
                    "latest_apy_currentness": (
                        intel.latest_apy_currentness if intel is not None
                        else "UNAVAILABLE"),
                    "delta_24h_bps": (_float_or_none(intel.deltas.get("24h"))
                                      if intel is not None else None),
                    "delta_7d_bps": (_float_or_none(intel.deltas.get("7d"))
                                     if intel is not None else None),
                    "sigma_30d": (_float_or_none(intel.sigma_30d)
                                  if intel is not None else None),
                    "sigma_source": (intel.sigma_source or None)
                                    if intel is not None else None,
                    "spread_bps": (_float_or_none(intel.spread_bps)
                                   if intel is not None else None),
                    "spread_source": (intel.spread_source or None)
                                     if intel is not None else None,
                    "sparkline": list(intel.sparkline)
                                 if intel is not None else []}
                   if intel is not None else None),
        "history_intelligence_included": include_history_intelligence,
    }
    return detail


def _float_or_none(value):
    return None if value is None else float(value)
