"""Reviewed per-asset Chainlink Stock Token oracle bindings (data authority, not discovery).

A binding ties ONE exact reviewed Stock Token deployment (chain + contract, already in APPROVED_BY_CANONICAL_ID)
to its official Chainlink feed proxy. Bindings are data: runtime never discovers, infers by ticker, or accepts a
third-party address as final authority. Anything not bound is ``ORACLE_FEED_NOT_REVIEWED``.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Mapping

from finco_radar.authority.r_live_policy import APPROVED_BY_CANONICAL_ID, SUPPORTED_CHAIN_ID

DEFAULT_REGISTRY_PATH = Path(__file__).with_name("data") / "stock_token_oracle_feeds.json"
SCHEMA_VERSION = "FINCO_STOCK_TOKEN_ORACLE_FEEDS_V1"

# Only these may be the FINAL authority for a binding.
OFFICIAL_SOURCES = frozenset({"CHAINLINK_OFFICIAL_FEED_CATALOG", "ROBINHOOD_CHAIN_OFFICIAL_DOCS"})

SOURCE_PROVEN = "SOURCE_PROVEN"
ORACLE_FEED_NOT_REVIEWED = "ORACLE_FEED_NOT_REVIEWED"

_ADDRESS = re.compile(r"^0x[0-9a-f]{40}$")


class OracleRegistryError(ValueError):
    """Registry data violates the authority contract (fail closed; nothing is loaded)."""


@dataclass(frozen=True)
class Provenance:
    source: str
    reference_url: str
    reviewed_at: str
    reviewer: str


@dataclass(frozen=True)
class FeedBinding:
    canonical_id: str            # exact AssetKey, "<chain>:<contract>"
    chain_id: int
    token_contract: str          # exact Stock Token deployment
    feed_proxy: str              # official Chainlink proxy
    feed_description: str        # official pair string, compared with description() on chain
    reviewed_decimals: int | None  # optional cross-check only; decimals() is always read from the proxy
    heartbeat_seconds: int | None  # official feed-specific heartbeat; None -> ORACLE_HEARTBEAT_NOT_REVIEWED
    provenance: Provenance


@dataclass(frozen=True)
class SequencerBinding:
    chain_id: int
    feed_proxy: str              # official Chainlink L2 Sequencer Uptime Feed
    grace_period_seconds: int
    provenance: Provenance


@dataclass(frozen=True)
class OracleRegistry:
    bindings: Mapping[str, FeedBinding]
    sequencer: SequencerBinding | None

    def status_for(self, canonical_id: str) -> str:
        return SOURCE_PROVEN if canonical_id in self.bindings else ORACLE_FEED_NOT_REVIEWED

    def binding_for(self, canonical_id: str) -> FeedBinding | None:
        return self.bindings.get(canonical_id)

    def coverage(self) -> dict[str, str]:
        return {cid: self.status_for(cid) for cid in sorted(APPROVED_BY_CANONICAL_ID)}


def _address(value, name: str) -> str:
    text = str(value or "").strip().lower()
    if not _ADDRESS.match(text):
        raise OracleRegistryError(f"{name}_INVALID_ADDRESS")
    return text


def _provenance(raw, name: str) -> Provenance:
    if not isinstance(raw, dict):
        raise OracleRegistryError(f"{name}_PROVENANCE_REQUIRED")
    source = str(raw.get("source") or "")
    if source not in OFFICIAL_SOURCES:
        raise OracleRegistryError(f"{name}_PROVENANCE_NOT_OFFICIAL")
    url = str(raw.get("reference_url") or "")
    if not url.startswith("https://"):
        raise OracleRegistryError(f"{name}_PROVENANCE_URL_REQUIRED")
    reviewed_at = str(raw.get("reviewed_at") or "")
    try:
        date.fromisoformat(reviewed_at)
    except ValueError:
        raise OracleRegistryError(f"{name}_PROVENANCE_DATE_INVALID") from None
    reviewer = str(raw.get("reviewer") or "").strip()
    if not reviewer:
        raise OracleRegistryError(f"{name}_PROVENANCE_REVIEWER_REQUIRED")
    return Provenance(source, url, reviewed_at, reviewer)


def _positive_int(value, name: str, *, allow_none: bool = False) -> int | None:
    if value is None and allow_none:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise OracleRegistryError(f"{name}_INVALID")
    return value


def parse_registry(raw: dict) -> OracleRegistry:
    if not isinstance(raw, dict) or raw.get("schema_version") != SCHEMA_VERSION:
        raise OracleRegistryError("ORACLE_REGISTRY_SCHEMA_INVALID")
    if raw.get("chain_id") != SUPPORTED_CHAIN_ID:
        raise OracleRegistryError("ORACLE_REGISTRY_CHAIN_INVALID")
    bindings: dict[str, FeedBinding] = {}
    proxies: set[str] = set()
    for item in raw.get("bindings") or []:
        if not isinstance(item, dict):
            raise OracleRegistryError("ORACLE_BINDING_INVALID")
        canonical_id = str(item.get("canonical_id") or "")
        policy = APPROVED_BY_CANONICAL_ID.get(canonical_id)
        if policy is None:
            raise OracleRegistryError("ORACLE_BINDING_ASSET_NOT_APPROVED")
        if item.get("chain_id") != SUPPORTED_CHAIN_ID:
            raise OracleRegistryError("ORACLE_BINDING_CHAIN_INVALID")
        token = _address(item.get("token_contract"), "ORACLE_BINDING_TOKEN")
        if token != policy.asset_key.contract_address.lower():
            raise OracleRegistryError("ORACLE_BINDING_TOKEN_CONTRACT_MISMATCH")
        proxy = _address(item.get("feed_proxy"), "ORACLE_BINDING_PROXY")
        if canonical_id in bindings:
            raise OracleRegistryError("ORACLE_BINDING_DUPLICATE_ASSET")
        if proxy in proxies:
            raise OracleRegistryError("ORACLE_BINDING_DUPLICATE_PROXY")  # one feed never serves two assets
        description = str(item.get("feed_description") or "").strip()
        if not description:
            raise OracleRegistryError("ORACLE_BINDING_DESCRIPTION_REQUIRED")
        proxies.add(proxy)
        bindings[canonical_id] = FeedBinding(
            canonical_id=canonical_id, chain_id=SUPPORTED_CHAIN_ID, token_contract=token,
            feed_proxy=proxy, feed_description=description,
            reviewed_decimals=_positive_int(item.get("reviewed_decimals"), "ORACLE_BINDING_DECIMALS", allow_none=True),
            heartbeat_seconds=_positive_int(item.get("heartbeat_seconds"), "ORACLE_BINDING_HEARTBEAT", allow_none=True),
            provenance=_provenance(item.get("provenance"), "ORACLE_BINDING"))
    sequencer = None
    seq_raw = raw.get("sequencer")
    if seq_raw is not None:
        if not isinstance(seq_raw, dict) or seq_raw.get("chain_id") != SUPPORTED_CHAIN_ID:
            raise OracleRegistryError("ORACLE_SEQUENCER_INVALID")
        sequencer = SequencerBinding(
            SUPPORTED_CHAIN_ID, _address(seq_raw.get("feed_proxy"), "ORACLE_SEQUENCER_PROXY"),
            _positive_int(seq_raw.get("grace_period_seconds"), "ORACLE_SEQUENCER_GRACE"),
            _provenance(seq_raw.get("provenance"), "ORACLE_SEQUENCER"))
        if sequencer.feed_proxy in proxies:
            raise OracleRegistryError("ORACLE_SEQUENCER_PROXY_COLLIDES_WITH_ASSET_FEED")
    return OracleRegistry(bindings, sequencer)


def load_registry(path: str | Path | None = None) -> OracleRegistry:
    target = Path(path) if path else DEFAULT_REGISTRY_PATH
    try:
        raw = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise OracleRegistryError("ORACLE_REGISTRY_UNREADABLE") from None
    return parse_registry(raw)
