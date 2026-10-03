"""One-shot Tokenized Markets live collector.

Runtime architecture:
existing reviewed provider -> bounded exact collector -> MarketObservation
-> append-only VenueMarketStore.

No browser route imports this module. No scheduler lives in-process; systemd
(or another job runner) invokes it. No trading, wallet, signing, or custody.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import json
import os
import time
from typing import Callable, Iterable

from app.radar_rwa.r_live_service import (
    collect_r_live,
    collect_r_live_batch,
    format_r_live_result,
)
from finco_radar.authority.r_live_policy import APPROVED_BY_CANONICAL_ID
from finco_radar.venues.health import TokenizedCollectorHealthStore
from finco_radar.venues.registry import VenueRegistry
from finco_radar.venues.robinhood_live import market_observation_from_r_live
from finco_radar.venues.store import VenueMarketStore

_MAX_UNIVERSE = 32
_MAX_RETRIES = 2
_MAX_BACKOFF_SECONDS = 5.0


class TokenizedCollectorConfigError(ValueError):
    pass


def _enabled(env: dict[str, str]) -> bool:
    return env.get("FINCO_TOKENIZED_COLLECTOR_ENABLED", "").strip().lower() in {
        "1", "true", "yes", "on"
    }


def _int_env(env: dict[str, str], name: str, default: int, *, low: int, high: int) -> int:
    raw = env.get(name, "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        raise TokenizedCollectorConfigError(f"{name}_INVALID") from None
    if not low <= value <= high:
        raise TokenizedCollectorConfigError(f"{name}_OUT_OF_RANGE")
    return value


def _float_env(env: dict[str, str], name: str, default: float,
               *, low: float, high: float) -> float:
    raw = env.get(name, "").strip()
    if not raw:
        return default
    try:
        value = float(raw)
    except ValueError:
        raise TokenizedCollectorConfigError(f"{name}_INVALID") from None
    if not low <= value <= high:
        raise TokenizedCollectorConfigError(f"{name}_OUT_OF_RANGE")
    return value


def _target_ids(registry: VenueRegistry, *, max_assets: int) -> tuple[str, ...]:
    """Reviewed R-LIVE AssetKeys intersected with exact active venue identity."""
    approved = tuple(sorted(APPROVED_BY_CANONICAL_ID))
    if len(approved) > max_assets:
        raise TokenizedCollectorConfigError("TOKENIZED_COLLECTOR_UNIVERSE_LIMIT_EXCEEDED")
    targets: list[str] = []
    for canonical_id in approved:
        chain_text, contract = canonical_id.split(":", 1)
        policy = APPROVED_BY_CANONICAL_ID[canonical_id]
        matches = [
            (entry, status)
            for entry, status in registry.representation_by_contract(
                chain_id=int(chain_text), contract_address=contract)
            if (entry.platform == "robinhood"
                and status.value == "ACTIVE"
                and entry.underlying_symbol is not None
                and entry.underlying_symbol.strip().upper() == policy.symbol)
        ]
        if len(matches) == 1:
            targets.append(canonical_id)
    return tuple(targets)


def _retry_one(
    canonical_id: str,
    *,
    rpc_url: str,
    as_of: datetime,
    retries: int,
    backoff_seconds: float,
    acquire_one: Callable = collect_r_live,
    sleeper: Callable[[float], None] = time.sleep,
) -> tuple[str, str, dict]:
    last = (canonical_id, "UNAVAILABLE", {"reason": "RADAR_AUTHORITY_UNAVAILABLE"})
    for attempt in range(retries + 1):
        if attempt:
            sleeper(min(
                backoff_seconds * (2 ** (attempt - 1)),
                _MAX_BACKOFF_SECONDS,
            ))
        try:
            result = acquire_one(
                canonical_asset_id=canonical_id,
                rpc_url=rpc_url,
                as_of=as_of,
                persist_history=False,
            )
            state, data = format_r_live_result(canonical_id, result)
            last = (canonical_id, state, data)
            if state != "UNAVAILABLE":
                return last
        except Exception:
            last = (canonical_id, "UNAVAILABLE",
                    {"reason": "RADAR_AUTHORITY_UNAVAILABLE"})
    return last


def collect_once(
    *,
    rpc_url: str,
    as_of: datetime | None = None,
    registry: VenueRegistry | None = None,
    store: VenueMarketStore | None = None,
    health: TokenizedCollectorHealthStore | None = None,
    batch_provider: Callable[..., Iterable[tuple[str, str, dict]]] = collect_r_live_batch,
    acquire_one: Callable = collect_r_live,
    max_assets: int = 32,
    workers: int = 2,
    retries: int = 1,
    backoff_seconds: float = 0.25,
    sleeper: Callable[[float], None] = time.sleep,
) -> tuple[dict, int]:
    """Run one bounded collection cycle.

    Asset failures are isolated. Available exact observations are persisted in
    one append-only batch. A failed provider cannot delete or overwrite prior
    history. Health metadata is operational only.
    """
    now = as_of or datetime.now(timezone.utc)
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("TOKENIZED_COLLECTION_CLOCK_MUST_BE_AWARE")
    now = now.astimezone(timezone.utc)

    report = {
        "schema": "FINCO_TOKENIZED_LIVE_INTELLIGENCE_V1",
        "state": "UNAVAILABLE",
        "attempted": 0,
        "available": 0,
        "stale": 0,
        "unavailable": 0,
        "quarantined": 0,
        "persisted": 0,
        "duplicates": 0,
        "provider": "R_LIVE",
        "provider_failures": 0,
    }

    health_error = False
    if health is not None:
        try:
            health.record_attempt(now=now)
        except Exception:
            health_error = True

    try:
        registry = registry or VenueRegistry.load()
        store = store or VenueMarketStore()
        targets = _target_ids(registry, max_assets=max_assets)
    except TokenizedCollectorConfigError as exc:
        if health is not None:
            try:
                health.record_failure(str(exc), now=now)
            except Exception:
                health_error = True
        raise
    except Exception:
        report["reason"] = "TOKENIZED_COLLECTOR_INITIALIZATION_UNAVAILABLE"
        if health is not None:
            try:
                health.record_failure(report["reason"], now=now)
            except Exception:
                health_error = True
        if health_error:
            report["health_state"] = "UNAVAILABLE"
        return report, 2

    report["attempted"] = len(targets)

    if not targets:
        report["reason"] = "TOKENIZED_COLLECTOR_EMPTY_EXACT_UNIVERSE"
        if health is not None:
            try:
                health.record_failure(report["reason"], now=now)
            except Exception:
                health_error = True
        return report, 2

    target_set = set(targets)
    rows: dict[str, tuple[str, str, dict]] = {}
    try:
        # Existing batch authority owns shared registry/RPC efficiency and
        # per-asset isolation. The approved universe is bounded above before
        # this call and every returned row is exact-key filtered below.
        for canonical_id, state, data in batch_provider(
                rpc_url=rpc_url, workers=workers, as_of=now):
            if canonical_id in target_set and canonical_id not in rows:
                rows[canonical_id] = (canonical_id, state, data)
    except Exception:
        report["provider_failures"] += 1

    # Missing or typed-unavailable rows get a bounded exact-asset retry. A
    # healthy/stale sibling never waits on or inherits another asset's state.
    retry_ids = [
        canonical_id for canonical_id in targets
        if canonical_id not in rows or rows[canonical_id][1] == "UNAVAILABLE"
    ]
    if retry_ids:
        with ThreadPoolExecutor(max_workers=min(workers, len(retry_ids))) as pool:
            futures = {
                pool.submit(
                    _retry_one,
                    canonical_id,
                    rpc_url=rpc_url,
                    as_of=now,
                    retries=retries,
                    backoff_seconds=backoff_seconds,
                    acquire_one=acquire_one,
                    sleeper=sleeper,
                ): canonical_id
                for canonical_id in retry_ids
            }
            for future in as_completed(futures):
                canonical_id = futures[future]
                try:
                    rows[canonical_id] = future.result()
                except Exception:
                    rows[canonical_id] = (
                        canonical_id, "UNAVAILABLE",
                        {"reason": "RADAR_AUTHORITY_UNAVAILABLE"})
                    report["provider_failures"] += 1

    observations = []
    for canonical_id in targets:
        _cid, state, data = rows.get(
            canonical_id,
            (canonical_id, "UNAVAILABLE",
             {"reason": "RADAR_AUTHORITY_UNAVAILABLE"}),
        )
        if state == "AVAILABLE":
            report["available"] += 1
        elif state == "STALE":
            report["stale"] += 1
        else:
            report["unavailable"] += 1
        try:
            observation = market_observation_from_r_live(
                canonical_id=canonical_id,
                state=state,
                data=data,
                registry=registry,
                collected_at=now,
            )
        except Exception:
            observation = None
        if state == "AVAILABLE" and observation is None:
            # Provider-level availability is insufficient if canonical
            # normalization cannot produce usable exact market evidence.
            report["available"] -= 1
            report["unavailable"] += 1
            report["provider_failures"] += 1
        if observation is not None:
            if observation.observation_status.value == "QUARANTINED":
                # Quarantined evidence is persisted for inspection/history
                # but never counted as active AVAILABLE pricing.
                report["available"] -= 1
                report["quarantined"] += 1
            observations.append(observation)

    try:
        created = store.append_many_batched(observations)
    except Exception:
        report["reason"] = "TOKENIZED_HISTORY_PERSISTENCE_UNAVAILABLE"
        if health is not None:
            try:
                health.record_failure(
                    report["reason"], attempted=len(targets), now=now)
            except Exception:
                health_error = True
        return report, 2

    report["persisted"] = sum(1 for _digest, was_created in created if was_created)
    report["duplicates"] = len(created) - report["persisted"]
    degraded = bool(
        report["stale"] or report["unavailable"] or report["quarantined"]
        or report["provider_failures"])
    report["state"] = "PARTIAL" if degraded else "AVAILABLE"

    if health is not None:
        try:
            health.record_complete(
                attempted=len(targets),
                available=report["available"],
                stale=report["stale"],
                unavailable=report["unavailable"],
                quarantined=report["quarantined"],
                persisted=report["persisted"],
                duplicates=report["duplicates"],
                degraded=degraded,
                now=now,
            )
        except Exception:
            health_error = True

    if health_error:
        report["health_state"] = "UNAVAILABLE"
        return report, 2
    return report, 3 if degraded else 0


def main(argv=None, *, env: dict[str, str] | None = None, out=None) -> int:
    env = dict(os.environ if env is None else env)
    out = out or __import__("sys").stdout
    if not _enabled(env):
        out.write(json.dumps({
            "schema": "FINCO_TOKENIZED_LIVE_INTELLIGENCE_V1",
            "state": "DISABLED",
        }, sort_keys=True) + "\n")
        return 4

    rpc_url = env.get("ROBINHOOD_RPC_URL", "").strip()
    if not rpc_url:
        out.write(json.dumps({
            "schema": "FINCO_TOKENIZED_LIVE_INTELLIGENCE_V1",
            "state": "CONFIG_ERROR",
            "reason": "RPC_NOT_CONFIGURED",
        }, sort_keys=True) + "\n")
        return 4

    try:
        max_assets = _int_env(
            env, "FINCO_TOKENIZED_COLLECTOR_MAX_ASSETS", 32,
            low=1, high=_MAX_UNIVERSE)
        workers = _int_env(
            env, "FINCO_TOKENIZED_COLLECTOR_WORKERS", 2, low=1, high=4)
        retries = _int_env(
            env, "FINCO_TOKENIZED_COLLECTOR_RETRIES", 1,
            low=0, high=_MAX_RETRIES)
        backoff = _float_env(
            env, "FINCO_TOKENIZED_COLLECTOR_BACKOFF_SECONDS", 0.25,
            low=0.0, high=_MAX_BACKOFF_SECONDS)
    except TokenizedCollectorConfigError as exc:
        out.write(json.dumps({
            "schema": "FINCO_TOKENIZED_LIVE_INTELLIGENCE_V1",
            "state": "CONFIG_ERROR",
            "reason": str(exc),
        }, sort_keys=True) + "\n")
        return 4

    health = None
    health_unavailable = False
    try:
        health = TokenizedCollectorHealthStore()
    except Exception:
        health_unavailable = True
    try:
        report, code = collect_once(
            rpc_url=rpc_url,
            health=health,
            max_assets=max_assets,
            workers=workers,
            retries=retries,
            backoff_seconds=backoff,
        )
    except TokenizedCollectorConfigError as exc:
        report, code = ({
            "schema": "FINCO_TOKENIZED_LIVE_INTELLIGENCE_V1",
            "state": "CONFIG_ERROR",
            "reason": str(exc),
        }, 4)
    except Exception:
        report, code = ({
            "schema": "FINCO_TOKENIZED_LIVE_INTELLIGENCE_V1",
            "state": "UNAVAILABLE",
            "reason": "TOKENIZED_COLLECTOR_RUNTIME_UNAVAILABLE",
        }, 2)
    finally:
        if health is not None:
            try:
                health.close()
            except Exception:
                health_unavailable = True
    if health_unavailable:
        report["health_state"] = "UNAVAILABLE"
        report["health_reason"] = "TOKENIZED_COLLECTOR_HEALTH_UNAVAILABLE"
        code = 2
    out.write(json.dumps(report, sort_keys=True) + "\n")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
