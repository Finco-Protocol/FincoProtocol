"""One-shot, read-only R-LIVE collection for cron, systemd, or a job runner.

Run with ``python -m app.radar_rwa.r_live_collect``. There is deliberately no
schedule, wallet, signing, or trading path in this process.
"""
from __future__ import annotations

import json
import os
import argparse
from functools import partial
from datetime import datetime, timezone
from typing import Callable

from finco_radar.authority.contracts import AuthorityState

from .bnb_history import BnbIntelligenceHistoryStore
from .r_live_service import RLiveResult, collect_aapl_r_live, collect_r_live
from finco_radar.authority.r_live_policy import AAPL_KEY, APPROVED_BY_CANONICAL_ID


def collect_once(
    *, rpc_url: str | None = None, as_of: datetime | None = None,
    history: BnbIntelligenceHistoryStore | None = None,
    acquire: Callable[..., RLiveResult] = collect_aapl_r_live,
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
            return {"state": state, "reason": premium.reason or result.onchain.reason,
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
        return {"state": "UNAVAILABLE", "reason": "R_LIVE_COLLECTION_UNAVAILABLE",
                "history_digest": None}
    finally:
        if owned_history and ledger is not None:
            ledger.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="One-shot reviewed R-LIVE collection")
    parser.add_argument("--asset-key", default=AAPL_KEY.canonical_id,
                        help="exact approved chain:contract AssetKey (default: AAPL)")
    args = parser.parse_args()
    if args.asset_key not in APPROVED_BY_CANONICAL_ID:
        status = {"state": "UNAVAILABLE", "reason": "ASSETKEY_NOT_APPROVED", "history_digest": None}
    elif args.asset_key == AAPL_KEY.canonical_id:
        status = collect_once()
    else:
        status = collect_once(acquire=partial(collect_r_live, canonical_asset_id=args.asset_key))
    print(json.dumps(status, sort_keys=True, separators=(",", ":")))
    return 0 if status["state"] == "AVAILABLE" else 1


if __name__ == "__main__":
    raise SystemExit(main())
