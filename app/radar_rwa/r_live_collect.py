"""One-shot R-LIVE history writer for cron, systemd, or a job runner.

No argument collects every reviewed exact AssetKey. ``--asset-key`` restricts
one diagnostic run. There is no scheduler, wallet, signing, or trading path.
"""
from __future__ import annotations

import json
import os
import argparse
import re
from functools import partial
from datetime import datetime, timezone
from typing import Callable

from finco_radar.authority.contracts import AuthorityState

from .bnb_history import BnbIntelligenceHistoryStore
from .r_live_service import RLiveResult, collect_aapl_r_live, collect_r_live
from finco_radar.authority.r_live_policy import AAPL_KEY, APPROVED_BY_CANONICAL_ID
from finco_radar.authority.r_live_onchain import JsonRpc


def _safe_reason(value: object) -> str | None:
    """Only stable typed reasons may cross into journald/CLI output."""
    if value is None:
        return None
    return value if isinstance(value, str) and re.fullmatch(r"[A-Z][A-Z0-9_]{0,95}", value) else "R_LIVE_COLLECTION_UNAVAILABLE"


def _check_rpc_health(url: str) -> None:
    """Process-only transport/chain preflight; never supplies price evidence."""
    rpc = JsonRpc(url)
    try:
        chain_id = rpc.call("eth_chainId", [])
        if not isinstance(chain_id, str) or int(chain_id, 16) != 4663:
            raise ValueError("RPC_CHAIN_UNAVAILABLE")
    finally:
        rpc.close()


def collect_once(
    *, rpc_url: str | None = None, as_of: datetime | None = None,
    history: BnbIntelligenceHistoryStore | None = None,
    acquire: Callable[..., RLiveResult] = collect_aapl_r_live,
    process_errors: list[str] | None = None,
) -> dict:
    """Return a credential-free status; only AVAILABLE evidence may be stored."""
    url = rpc_url if rpc_url is not None else os.getenv("ROBINHOOD_RPC_URL")
    if not url:
        return {"state": "UNAVAILABLE", "reason": "RPC_NOT_CONFIGURED", "history_digest": None}
    owned_history = history is None
    ledger = history
    try:
        if ledger is None:
            ledger = BnbIntelligenceHistoryStore(allowed_chain_id=4663)
        result = acquire(rpc_url=url, as_of=as_of, persist_history=True, history=ledger)
        premium = result.authority.premium
        if premium.state is not AuthorityState.AVAILABLE:
            state = "STALE" if (premium.state is AuthorityState.STALE
                                or result.onchain.state is AuthorityState.STALE) else "UNAVAILABLE"
            return {"state": state, "reason": _safe_reason(result.onchain.reason or premium.reason),
                    "history_digest": None}
        if result.history_digest is None:
            return {"state": "UNAVAILABLE", "reason": "HISTORY_PERSISTENCE_UNAVAILABLE",
                    "history_digest": None}
        return {"state": "AVAILABLE", "reason": None,
                "history_digest": result.history_digest,
                "economic_asset_uid": result.authority.economic_asset_uid,
                "asset_key": result.authority.canonical_token.canonical_id,
                "observed_at": result.onchain.observed_at.isoformat(),
                "retrieved_at": (as_of or datetime.now(timezone.utc)).isoformat()}
    except Exception:
        if process_errors is not None:
            process_errors.append("R_LIVE_ACQUISITION_RUNTIME_UNAVAILABLE")
        return {"state": "UNAVAILABLE", "reason": "R_LIVE_COLLECTION_UNAVAILABLE",
                "history_digest": None}
    finally:
        if owned_history and ledger is not None:
            ledger.close()


def collect_all_approved(
    *, rpc_url: str | None = None, as_of: datetime | None = None,
    acquire: Callable[..., RLiveResult] = collect_r_live,
    history_factory: Callable[..., BnbIntelligenceHistoryStore] = BnbIntelligenceHistoryStore,
    rpc_healthcheck: Callable[[str], None] = _check_rpc_health,
) -> tuple[dict, int]:
    """Serial batch over the canonical registry; market states do not abort it.

    Exit 0 means the batch operated, not that every market was AVAILABLE.
    Configuration, ledger initialization/persistence/close or registry failure
    are process-level nonzero outcomes. No credential or exception is emitted.
    """
    try:
        keys = tuple(APPROVED_BY_CANONICAL_ID)
        if not keys:
            raise ValueError("empty reviewed registry")
    except Exception:
        return {"mode": "all_approved", "asset_count": 0, "results": [],
                "summary": {"available": 0, "stale": 0, "unavailable": 0},
                "process_error": "APPROVED_REGISTRY_UNAVAILABLE"}, 1
    summary = {"available": 0, "stale": 0, "unavailable": 0}
    response = {"mode": "all_approved", "asset_count": len(keys),
                "results": [], "summary": summary}
    url = rpc_url if rpc_url is not None else os.getenv("ROBINHOOD_RPC_URL")
    if not url:
        response["process_error"] = "RPC_NOT_CONFIGURED"
        return response, 1
    try:
        rpc_healthcheck(url)
    except Exception:
        response["process_error"] = "RPC_UNAVAILABLE"
        return response, 1
    try:
        ledger = history_factory(allowed_chain_id=4663)
        if ledger is None:
            raise ValueError("history store missing")
    except Exception:
        response["process_error"] = "HISTORY_STORE_UNAVAILABLE"
        return response, 1
    persistence_failed = False
    invalid_result = False
    process_errors: list[str] = []
    try:
        for key in keys:
            status = collect_once(
                rpc_url=url, as_of=as_of, history=ledger,
                acquire=partial(acquire, canonical_asset_id=key),
                process_errors=process_errors,
            )
            state = status.get("state") if isinstance(status, dict) else None
            if state not in ("AVAILABLE", "STALE", "UNAVAILABLE"):
                invalid_result = True
                break
            summary[state.lower()] += 1
            response["results"].append({
                "asset_key": key, "state": state, "reason": status.get("reason"),
                "history_digest": status.get("history_digest"),
            })
            if status.get("reason") == "HISTORY_PERSISTENCE_UNAVAILABLE":
                persistence_failed = True
    finally:
        try:
            ledger.close()
        except Exception:
            persistence_failed = True
    if persistence_failed:
        response["process_error"] = "HISTORY_STORE_UNAVAILABLE"
        return response, 1
    if invalid_result:
        response["process_error"] = "COLLECTOR_RESULT_INVALID"
        return response, 1
    if process_errors:
        response["process_error"] = "R_LIVE_ACQUISITION_RUNTIME_UNAVAILABLE"
        return response, 1
    return response, 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="One-shot reviewed R-LIVE collection")
    parser.add_argument("--asset-key",
                        help="one exact approved chain:contract AssetKey; omit for all approved")
    args = parser.parse_args(argv)
    if args.asset_key is None:
        status, exit_code = collect_all_approved()
    elif args.asset_key not in APPROVED_BY_CANONICAL_ID:
        status = {"state": "UNAVAILABLE", "reason": "ASSETKEY_NOT_APPROVED", "history_digest": None}
        exit_code = 1
    elif args.asset_key == AAPL_KEY.canonical_id:
        status = collect_once()
        exit_code = 0 if status["state"] == "AVAILABLE" else 1
    else:
        status = collect_once(acquire=partial(collect_r_live, canonical_asset_id=args.asset_key))
        exit_code = 0 if status["state"] == "AVAILABLE" else 1
    print(json.dumps(status, sort_keys=True, separators=(",", ":")))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
