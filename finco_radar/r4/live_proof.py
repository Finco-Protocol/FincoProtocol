"""Networked R4 proof: reference-state classification on canonical Stock Tokens.

One canonical asset: the R1 registry row, the exact bound R2 official price and
the R4 corporate-action evidence for the selected candidate all refer to one
canonical deployment. Nothing is stitched across candidates.

Market-session authority: the official source surface used here exposes only
trading *capabilities*, not current session state (capability != session). The
live proof therefore evaluates with an explicit UNRESOLVED session-evidence
boundary (`R4_MARKET_SESSION_AUTHORITY_REQUIRED`); freshness EXPECTED_STATIC is
never fabricated from clock time. A fresh reference needs no session authority
and classifies CURRENT; an old one classifies UNRESOLVED and blocks usability
honestly.
"""
from __future__ import annotations

import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import httpx

from finco_radar.assets.adapters.robinhood import RobinhoodAssetRegistryAdapter
from finco_radar.assets.contracts import RegistryAssetStatus
from finco_radar.gap.contracts import GapComputationError
from finco_radar.gap.engine import build_bound_reference_price
from finco_radar.reference_state.adapters.robinhood import RobinhoodCorporateActionAdapter
from finco_radar.reference_state.contracts import (
    MarketSessionEvidence,
    MarketSessionState,
    ReferenceStateError,
    ReferenceStatePolicy,
)
from finco_radar.reference_state.engine import build_reference_state_snapshot, match_corporate_actions

CHAIN_ID = 4663
ROBINHOOD_API = "https://api.robinhood.com/rhj"
CANDIDATE_SYMBOLS = ("AAPL", "NVDA", "TSLA", "MSFT", "AMZN", "META", "GOOGL")

# Explicit caller-supplied policy (the engine itself has no defaults).
R4_MAX_LIVE_REFERENCE_AGE_SECONDS = int(os.getenv("RADAR_R4_MAX_LIVE_REFERENCE_AGE_SECONDS", "120"))
R4_MAX_SESSION_EVIDENCE_AGE_SECONDS = int(
    os.getenv("RADAR_R4_MAX_SESSION_EVIDENCE_AGE_SECONDS", "86400")
)
R4_MAX_CLOCK_SKEW_SECONDS = int(os.getenv("RADAR_R4_MAX_CLOCK_SKEW_SECONDS", "5"))

SESSION_AUTHORITY_NOTE = "R4_MARKET_SESSION_AUTHORITY_REQUIRED"
SESSION_EVIDENCE = MarketSessionEvidence(
    state=MarketSessionState.UNRESOLVED,
    source=(
        "NO_CURRENT_SESSION_SOURCE_AVAILABLE: official surfaces expose trading "
        "capabilities only (capability != current session state); "
        "R4_MARKET_SESSION_AUTHORITY_REQUIRED"
    ),
)


def _git_head() -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        return result.stdout.strip() if result.returncode == 0 else "UNKNOWN"
    except Exception:
        return "UNKNOWN"


def _run(symbols: Iterable[str]) -> dict[str, Any]:
    produced_at = datetime.now(timezone.utc)
    git_head = _git_head()
    timeout = httpx.Timeout(25.0)
    failures: list[dict[str, str]] = []
    with httpx.Client(
        base_url=ROBINHOOD_API, timeout=timeout, headers={"accept": "application/json"}
    ) as client, RobinhoodCorporateActionAdapter(client=client) as ca_adapter:
        registry_adapter = RobinhoodAssetRegistryAdapter(client=client)
        snapshot = registry_adapter.fetch_snapshot()
        registry_observed_at = snapshot.observed_at
        ca_rows, ca_observed_at = ca_adapter.fetch_rows()

        for requested_symbol in symbols:
            try:
                matches = snapshot.find_by_symbol(requested_symbol)
                if len(matches) != 1:
                    raise RuntimeError(f"symbol discovery returned {len(matches)} matches")
                asset = matches[0]
                if asset.status is not RegistryAssetStatus.ACTIVE:
                    # R4 classifies lifecycle honestly: skip non-active candidates
                    # for the usable-reference proof, but record the attempt.
                    raise RuntimeError("canonical asset is not ACTIVE")
                key = asset.deployment_for_chain(CHAIN_ID)
                if key is None:
                    raise RuntimeError("canonical asset has no Robinhood Chain deployment")

                # Exact bound official price through the frozen R1/R2 authority.
                binding, price_row = registry_adapter.fetch_bound_reference(snapshot, key)
                reference = build_bound_reference_price(asset, binding, price_row)
                if reference.is_trading_halt:
                    raise RuntimeError("official reference is explicitly halted")

                # R4-owned corporate-action evidence for this exact asset.
                bound_rows = match_corporate_actions(ca_rows, asset=asset, asset_key=key)

                as_of = datetime.now(timezone.utc)
                snapshot_state = build_reference_state_snapshot(
                    asset=asset,
                    reference=reference,
                    corporate_actions=bound_rows,
                    session_evidence=SESSION_EVIDENCE,
                    policy=ReferenceStatePolicy(
                        max_live_reference_age_seconds=R4_MAX_LIVE_REFERENCE_AGE_SECONDS,
                        max_session_evidence_age_seconds=R4_MAX_SESSION_EVIDENCE_AGE_SECONDS,
                        max_clock_skew_seconds=R4_MAX_CLOCK_SKEW_SECONDS,
                    ),
                    as_of=as_of,
                    registry_observed_at=registry_observed_at,
                    corporate_actions_observed_at=ca_observed_at,
                )
                evidence = snapshot_state.to_evidence_dict()
                typed_status = evidence.pop("status")
                return {
                    "schemaVersion": "radar-r4-reference-state-v1",
                    "status": "PASS",
                    "typedStatus": typed_status,
                    "gitHead": git_head,
                    "producedAt": produced_at.isoformat(),
                    "chainId": CHAIN_ID,
                    "sessionAuthority": {
                        "note": SESSION_AUTHORITY_NOTE,
                        "liveEvaluationState": snapshot_state.market_session_state.value,
                        "semantics": (
                            "No official current-session source is available: "
                            "tradingCapabilities are capability evidence, not session "
                            "state. Fresh references classify CURRENT without session "
                            "authority; old references fail closed as UNRESOLVED and are "
                            "never labelled EXPECTED_STATIC without source-backed "
                            "CLOSED-session evidence."
                        ),
                    },
                    "evidenceProvenance": {
                        "registrySource": registry_adapter.source_name,
                        "corporateActionsSource": ca_adapter.source_name,
                        "referenceSource": snapshot_state.reference_source,
                    },
                    **evidence,
                    "candidateAttempts": {
                        "selectedSymbol": asset.token_symbol,
                        "skippedCandidates": list(failures),
                        "skippedCandidateCount": len(failures),
                        "semantics": (
                            "Audit-only. The selected candidate independently supplied "
                            "all reference-state evidence from one canonical asset; "
                            "evidence is never stitched across candidates."
                        ),
                    },
                }
            except ReferenceStateError as exc:
                failures.append(
                    {
                        "symbol": requested_symbol,
                        "status": exc.status.value,
                        "detail": str(exc),
                    }
                )
            except GapComputationError as exc:
                failures.append(
                    {
                        "symbol": requested_symbol,
                        "status": exc.status.value,
                        "detail": str(exc),
                    }
                )
            except Exception as exc:
                failures.append(
                    {
                        "symbol": requested_symbol,
                        "status": "INFRASTRUCTURE_ERROR",
                        "detail": f"{type(exc).__name__}:{exc}",
                    }
                )
    return {
        "schemaVersion": "radar-r4-reference-state-v1",
        "status": "BLOCKED",
        "typedStatus": failures[0]["status"] if failures else None,
        "sessionAuthority": {"note": SESSION_AUTHORITY_NOTE},
        "gitHead": git_head,
        "producedAt": produced_at.isoformat(),
        "chainId": CHAIN_ID,
        "policy": {
            "maxLiveReferenceAgeSeconds": R4_MAX_LIVE_REFERENCE_AGE_SECONDS,
            "maxSessionEvidenceAgeSeconds": R4_MAX_SESSION_EVIDENCE_AGE_SECONDS,
            "maxClockSkewSeconds": R4_MAX_CLOCK_SKEW_SECONDS,
        },
        "attempts": failures,
    }


def run(symbols: Iterable[str] = CANDIDATE_SYMBOLS) -> dict[str, Any]:
    try:
        return _run(symbols)
    except Exception as exc:
        return {
            "schemaVersion": "radar-r4-reference-state-v1",
            "status": "BLOCKED",
            "reason": f"INFRASTRUCTURE:{type(exc).__name__}:{exc}",
        }


def main() -> int:
    configured = os.getenv("RADAR_R4_SYMBOLS")
    symbols = (
        tuple(s.strip().upper() for s in configured.split(",") if s.strip())
        if configured
        else CANDIDATE_SYMBOLS
    )
    result = run(symbols)
    path = Path(
        os.getenv("RADAR_R4_EVIDENCE_PATH", "artifacts/radar_r4_reference_state_evidence.json")
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps({"status": result["status"], "evidence": str(path)}, sort_keys=True))
    return 0 if result["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
