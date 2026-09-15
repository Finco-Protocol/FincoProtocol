"""Networked R1 proof for canonical Stock Token identity and reference binding."""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Mapping

import httpx

from finco_radar.assets.adapters.robinhood import RobinhoodAssetRegistryAdapter
from finco_radar.assets.contracts import AssetKey, RegistryAssetStatus

CHAIN_ID = 4663
ROBINHOOD_API = "https://api.robinhood.com/rhj"


def _deployment_keys(row: Mapping[str, Any]) -> tuple[AssetKey, ...]:
    deployments = row.get("deployments")
    if not isinstance(deployments, list):
        raise RuntimeError("validated reference row lost deployment evidence")
    keys = tuple(
        AssetKey(
            chain_id=int(deployment["chainId"]),
            contract_address=str(deployment["contractAddress"]),
        )
        for deployment in deployments
    )
    if len(set(keys)) != len(keys):
        raise RuntimeError("validated reference row contains duplicate deployment keys")
    return keys


def run() -> dict[str, Any]:
    timeout = httpx.Timeout(25.0)
    try:
        with httpx.Client(
            base_url=ROBINHOOD_API,
            timeout=timeout,
            headers={"accept": "application/json"},
        ) as client:
            adapter = RobinhoodAssetRegistryAdapter(client=client)
            snapshot = adapter.fetch_snapshot()
            chain_assets = [
                asset for asset in snapshot.assets if asset.deployment_for_chain(CHAIN_ID) is not None
            ]
            active_assets = [
                asset for asset in chain_assets if asset.status is RegistryAssetStatus.ACTIVE
            ]
            if not active_assets:
                return {
                    "status": "BLOCKED",
                    "reason": "no active canonical assets on target chain",
                    "chainId": CHAIN_ID,
                }
            selected = sorted(
                active_assets,
                key=lambda asset: asset.deployment_for_chain(CHAIN_ID).canonical_id,
            )[0]
            key = selected.deployment_for_chain(CHAIN_ID)
            assert key is not None
            binding, price_row = adapter.fetch_bound_reference(snapshot, key)
            reference_keys = _deployment_keys(price_row)
            matching_keys = [candidate for candidate in reference_keys if candidate == binding.asset_key]
            if len(matching_keys) != 1:
                raise RuntimeError("bound reference did not retain exactly one canonical deployment")
            matched_key = matching_keys[0]

            symbol_collision_count = sum(
                1
                for symbol in {asset.token_symbol for asset in snapshot.assets}
                if len(snapshot.find_by_symbol(symbol)) > 1
            )
            pending_count = sum(
                1 for asset in snapshot.assets if asset.pending_multiplier is not None
            )
            return {
                "status": "PASS",
                "source": snapshot.source,
                "observedAt": snapshot.observed_at.isoformat(),
                "assetCount": len(snapshot.assets),
                "assetUidCount": snapshot.asset_uid_count,
                "canonicalKeyCount": snapshot.canonical_key_count,
                "deploymentCount": sum(len(asset.deployments) for asset in snapshot.assets),
                "targetChainAssetCount": len(chain_assets),
                "symbolCollisionCount": symbol_collision_count,
                "pendingMultiplierCount": pending_count,
                "selected": {
                    "assetUid": selected.asset_uid,
                    "canonicalKey": key.canonical_id,
                    "tokenSymbol": selected.token_symbol,
                    "tokenName": selected.token_name,
                    "status": selected.status.value,
                    "currentMultiplier": str(selected.current_multiplier),
                    "pendingMultiplier": (
                        str(selected.pending_multiplier)
                        if selected.pending_multiplier is not None
                        else None
                    ),
                    "pendingMultiplierEffectiveAt": (
                        selected.pending_multiplier_effective_at.isoformat()
                        if selected.pending_multiplier_effective_at is not None
                        else None
                    ),
                },
                "referenceBinding": {
                    "assetUid": binding.asset_uid,
                    "canonicalKey": binding.asset_key.canonical_id,
                    "matchedCanonicalKey": matched_key.canonical_id,
                    "referenceDeploymentKeys": [item.canonical_id for item in reference_keys],
                    "referenceSymbol": binding.reference_symbol,
                    "pricePath": binding.price_path,
                    "referenceGeneratedAt": price_row.get("generatedAt"),
                    "referenceTradingHalt": price_row.get("isTradingHalt"),
                },
                "identitySemantics": (
                    "chain_id + contract_address is canonical; official asset uid binds deployments "
                    "across chains; ticker is discovery/reference metadata only"
                ),
            }
    except Exception as exc:
        return {
            "status": "BLOCKED",
            "chainId": CHAIN_ID,
            "reason": f"{type(exc).__name__}:{exc}",
        }


def main() -> int:
    result = run()
    path = Path(
        os.getenv(
            "RADAR_R1_EVIDENCE_PATH",
            "artifacts/radar_r1_canonical_asset_registry.json",
        )
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps({"status": result["status"], "evidence": str(path)}, sort_keys=True))
    return 0 if result["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
