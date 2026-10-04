"""One-shot multi-source evidence acquisition: MARKET + OFFICIAL_REFERENCE + ORACLE for every reviewed Stock Token.

Not wired to any scheduler or startup path. Browser/read paths never call this module. ``--persist`` is the only write
and appends per-role rows; without it the run is read-only and just prints the acceptance matrix (no secrets).

    python -m app.radar_rwa.multi_source_collect            # matrix only
    python -m app.radar_rwa.multi_source_collect --persist  # matrix + append-only per-source persistence

Requires ROBINHOOD_RPC_URL (private; never printed). Existing R-LIVE acquisition is reused, not duplicated.
"""
from __future__ import annotations

import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Callable, Iterator, Mapping, Sequence

from finco_radar.authority.r_live_policy import APPROVED_BY_CANONICAL_ID

from .multi_source_evidence import (
    EvidenceLeg, EvidenceRole, SourceEvidenceStore, build_matrix, market_leg, oracle_leg, reference_leg,
)
from .stock_token_oracle import (
    OracleBlockContext, OracleBlockFailure, SequencerStatus, check_sequencer, pin_oracle_block,
    read_stock_token_oracle,
)
from .stock_token_oracle_registry import OracleRegistry, load_registry

# acquire_asset(canonical_id) -> (MARKET leg, OFFICIAL_REFERENCE leg). Both come from the existing R-LIVE authority.
AssetAcquirer = Callable[[str], tuple[EvidenceLeg, EvidenceLeg]]


def _unavailable_pair(canonical_id: str, reason: str) -> tuple[EvidenceLeg, EvidenceLeg]:
    from .multi_source_evidence import MARKET_SOURCE_AUTHORITY, REFERENCE_SOURCE_AUTHORITY, VALUE_UNIT
    return (
        EvidenceLeg(canonical_id, EvidenceRole.MARKET, MARKET_SOURCE_AUTHORITY, None, "UNAVAILABLE", None,
                    VALUE_UNIT, None, reason),
        EvidenceLeg(canonical_id, EvidenceRole.OFFICIAL_REFERENCE, REFERENCE_SOURCE_AUTHORITY, canonical_id,
                    "UNAVAILABLE", None, VALUE_UNIT, None, reason),
    )


@contextmanager
def r_live_acquirer(rpc_url: str, *, as_of: datetime) -> Iterator[AssetAcquirer]:
    """Reuse the existing R-LIVE acquisition glue: one registry snapshot, one shared RPC client, per-asset isolation."""
    import httpx
    from finco_radar.assets.adapters.robinhood import RobinhoodAssetRegistryAdapter
    from finco_radar.authority.r_live_onchain import JsonRpc
    from finco_radar.gap.engine import build_bound_reference_price
    from .r_live_service import compose_r_live

    client = httpx.Client(timeout=15)
    try:
        with RobinhoodAssetRegistryAdapter() as adapter:
            try:
                registry = adapter.fetch_snapshot()
            except Exception:
                registry = None

            def acquire(canonical_id: str) -> tuple[EvidenceLeg, EvidenceLeg]:
                policy = APPROVED_BY_CANONICAL_ID[canonical_id]
                key = policy.asset_key
                underlying = None
                if registry is not None:
                    asset = registry.get_by_key(key)
                    if asset is not None and asset.asset_uid == policy.economic_asset_uid:
                        try:
                            binding, row = adapter.fetch_bound_reference(registry, key)
                            underlying = build_bound_reference_price(asset, binding, row)
                        except Exception:
                            underlying = None
                try:
                    result = compose_r_live(registry=registry, underlying=underlying,
                                            rpc=JsonRpc(rpc_url, client=client), as_of=as_of, history=None, key=key)
                except Exception:
                    return _unavailable_pair(canonical_id, "RADAR_AUTHORITY_UNAVAILABLE")
                return market_leg(canonical_id, result.onchain), reference_leg(canonical_id, result.authority.underlying)

            yield acquire
    finally:
        client.close()


def collect_multi_source_once(
    *, acquire_asset: AssetAcquirer, oracle_rpc, oracle_registry: OracleRegistry, as_of: datetime,
    store: SourceEvidenceStore | None = None, canonical_ids: Sequence[str] | None = None, workers: int = 2,
) -> dict:
    """Collect all three roles for every reviewed asset. A leg failing never affects the other two."""
    if as_of.tzinfo is None or as_of.utcoffset() is None:
        raise ValueError("EVIDENCE_COLLECTION_CLOCK_MUST_BE_AWARE")
    if not 1 <= workers <= 4:
        raise ValueError("EVIDENCE_WORKERS_OUT_OF_RANGE")
    selected = list(canonical_ids) if canonical_ids is not None else sorted(APPROVED_BY_CANONICAL_ID)
    if len(selected) != len(set(selected)) or any(c not in APPROVED_BY_CANONICAL_ID for c in selected):
        raise ValueError("EVIDENCE_EXACT_ASSETKEY_NOT_APPROVED")

    # ONE pinned block per oracle cycle: validated once, the sequencer is evaluated at exactly that block, and every
    # bound asset reads oraclePaused()/description()/decimals()/latestRoundData() at that same tag (never ``latest`` again).
    pinned: OracleBlockContext | OracleBlockFailure | None = None
    sequencer: SequencerStatus | None = None
    if any(oracle_registry.binding_for(c) is not None for c in selected):
        pinned = pin_oracle_block(oracle_rpc, as_of=as_of)
        if isinstance(pinned, OracleBlockContext):
            sequencer = check_sequencer(oracle_rpc, oracle_registry.sequencer, pinned)

    def one(canonical_id: str) -> dict[EvidenceRole, EvidenceLeg]:
        legs: dict[EvidenceRole, EvidenceLeg] = {}
        try:
            market, reference = acquire_asset(canonical_id)
        except Exception:
            market, reference = _unavailable_pair(canonical_id, "RADAR_AUTHORITY_UNAVAILABLE")
        legs[EvidenceRole.MARKET], legs[EvidenceRole.OFFICIAL_REFERENCE] = market, reference
        try:
            observation = read_stock_token_oracle(
                rpc=oracle_rpc, registry=oracle_registry, canonical_id=canonical_id, as_of=as_of,
                block=pinned, sequencer=sequencer)
        except Exception:
            from .stock_token_oracle import OracleObservation
            from finco_radar.authority.contracts import AuthorityState
            observation = OracleObservation(AuthorityState.UNAVAILABLE, "ORACLE_ACQUISITION_UNAVAILABLE", canonical_id)
        legs[EvidenceRole.ORACLE] = oracle_leg(canonical_id, observation)
        return legs

    with ThreadPoolExecutor(max_workers=workers) as pool:
        collected = dict(zip(selected, pool.map(one, selected)))

    appended = duplicates = 0
    if store is not None:
        for canonical_id in selected:
            for leg in collected[canonical_id].values():
                if store.append(leg, collected_at=as_of):
                    appended += 1
                else:
                    duplicates += 1
    return {
        "schema": "FINCO_MULTI_SOURCE_EVIDENCE_V1",
        "as_of": as_of.astimezone(timezone.utc).isoformat(),
        "assets": len(selected),
        "persisted": appended, "duplicates": duplicates,
        "oracle_coverage": oracle_registry.coverage(),
        "matrix": build_matrix(collected, now=as_of, oracle_coverage=oracle_registry.coverage()),
    }


def main(argv: Sequence[str] | None = None, env: Mapping[str, str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    environ = os.environ if env is None else env
    persist = "--persist" in args
    rpc_url = environ.get("ROBINHOOD_RPC_URL", "").strip()
    if not rpc_url:
        print(json.dumps({"error": "ROBINHOOD_RPC_URL_REQUIRED"}))
        return 2
    from finco_radar.authority.r_live_onchain import JsonRpc
    as_of = datetime.now(timezone.utc)
    store = SourceEvidenceStore() if persist else None
    rpc = JsonRpc(rpc_url)
    try:
        with r_live_acquirer(rpc_url, as_of=as_of) as acquire:
            report = collect_multi_source_once(
                acquire_asset=acquire, oracle_rpc=rpc, oracle_registry=load_registry(), as_of=as_of, store=store)
    finally:
        rpc.close()
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
