"""Chainlink Stock Token oracle leg (ORACLE evidence role) — read-only, fail closed, pinned to one block.

MARKET != OFFICIAL_REFERENCE != ORACLE. This module produces ONLY the oracle leg for one exact reviewed Stock Token:
no market or reference value is read, borrowed or substituted, and no fresh oracle can make another leg current.

Value semantics: the Chainlink Stock Token feed already returns ``underlying share price x Stock Token multiplier``
(the value of ONE Stock Token). ``uiMultiplier()`` is NEVER applied again.

Checks, in order (first failure wins, each with a typed reason):
  binding (exact identity, official provenance) -> heartbeat reviewed -> chain block recent -> L2 sequencer UP past its
  grace period -> ``oraclePaused()`` false -> feed description/decimals -> round sanity -> heartbeat age.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Mapping

from finco_radar.authority.contracts import AuthorityState
from finco_radar.authority.r_live_onchain import (
    Rpc, RpcUnavailable, _BadEvidence, _abi_string, _call, _signed, _uint, _words,
)
from finco_radar.authority.r_live_policy import (
    APPROVED_BY_CANONICAL_ID, MAX_BLOCK_AGE_SECONDS, MAX_BLOCK_FUTURE_SKEW_SECONDS, SUPPORTED_CHAIN_ID,
)

from .keccak import selector
from .stock_token_oracle_registry import FeedBinding, OracleRegistry, SequencerBinding

ORACLE_SOURCE_AUTHORITY = "CHAINLINK_STOCK_TOKEN_PRICE_FEED"
ORACLE_UNIT = "USD_PER_STOCK_TOKEN"

SEL_DECIMALS = selector("decimals()")                  # 0x313ce567
SEL_DESCRIPTION = selector("description()")            # 0x7284e416
SEL_LATEST_ROUND = selector("latestRoundData()")       # 0xfeaf968c
SEL_ORACLE_PAUSED = selector("oraclePaused()")

MIN_DECIMALS, MAX_DECIMALS = 1, 36


@dataclass(frozen=True)
class OracleObservation:
    state: AuthorityState
    reason: str | None
    canonical_id: str
    feed_proxy: str | None = None
    value: Decimal | None = None
    source_timestamp: datetime | None = None
    decimals: int | None = None
    heartbeat_seconds: int | None = None
    age_seconds: int | None = None
    evidence: Mapping[str, Any] = field(default_factory=dict)


def _fail(canonical_id: str, reason: str, *, state: AuthorityState = AuthorityState.UNAVAILABLE,
          binding: FeedBinding | None = None, evidence: Mapping[str, Any] | None = None) -> OracleObservation:
    return OracleObservation(
        state, reason, canonical_id,
        feed_proxy=binding.feed_proxy if binding else None,
        heartbeat_seconds=binding.heartbeat_seconds if binding else None,
        evidence=dict(evidence or {}))


@dataclass(frozen=True)
class OracleBlockContext:
    """One immutable pinned chain state for an oracle cycle: every oracle read uses ``tag``, never ``latest``."""

    number: int
    tag: str            # exact hex block tag, e.g. "0x3e8"
    block_hash: str
    timestamp: int


@dataclass(frozen=True)
class OracleBlockFailure:
    reason: str         # typed: ORACLE_RPC_UNAVAILABLE / ORACLE_CHAIN_BLOCK_STALE


def pin_oracle_block(rpc: Rpc, *, as_of: datetime) -> OracleBlockContext | OracleBlockFailure:
    """Read ``latest`` exactly once, validate canonical block freshness once, and return the pinned context."""
    try:
        head = rpc.call("eth_getBlockByNumber", ["latest", False])
        if not isinstance(head, dict):
            raise _BadEvidence("BLOCK_UNAVAILABLE")
        number = _uint(head.get("number"))
        timestamp = _uint(head.get("timestamp"))
        block_hash = head.get("hash")
        if not isinstance(block_hash, str):
            raise _BadEvidence("BLOCK_UNAVAILABLE")
    except (_BadEvidence, RpcUnavailable, ValueError, TypeError):
        return OracleBlockFailure("ORACLE_RPC_UNAVAILABLE")
    if int(as_of.timestamp()) - timestamp > MAX_BLOCK_AGE_SECONDS:
        return OracleBlockFailure("ORACLE_CHAIN_BLOCK_STALE")
    return OracleBlockContext(number, f"0x{number:x}", block_hash, timestamp)


def verify_oracle_block(rpc: Rpc, block: OracleBlockContext) -> bool:
    """Re-read the pinned block BY EXACT TAG; False when its hash changed (reorg) or it cannot be read."""
    try:
        again = rpc.call("eth_getBlockByNumber", [block.tag, False])
    except (RpcUnavailable, ValueError, TypeError):
        return False
    return isinstance(again, dict) and again.get("hash") == block.block_hash


@dataclass(frozen=True)
class SequencerStatus:
    ok: bool
    reason: str | None
    evidence: Mapping[str, Any]
    block_hash: str | None = None   # the pinned block this status was evaluated at


def check_sequencer(rpc: Rpc, sequencer: SequencerBinding | None, block: OracleBlockContext) -> SequencerStatus:
    """Official Chainlink L2 Sequencer Uptime Feed at the PINNED block: answer 0 = UP, 1 = DOWN."""
    if sequencer is None:
        return SequencerStatus(False, "ORACLE_SEQUENCER_AUTHORITY_UNAVAILABLE", {}, block.block_hash)
    try:
        round_id, answer, started_at, updated_at, answered_in = _words(
            _call(rpc, sequencer.feed_proxy, SEL_LATEST_ROUND, block.tag), 5)
        answer = _signed(answer)
    except (_BadEvidence, RpcUnavailable, ValueError, TypeError):
        return SequencerStatus(False, "ORACLE_SEQUENCER_AUTHORITY_UNAVAILABLE", {}, block.block_hash)
    evidence = {"sequencerFeed": sequencer.feed_proxy, "sequencerAnswer": answer,
                "sequencerStartedAt": started_at, "sequencerGraceSeconds": sequencer.grace_period_seconds}
    if (round_id <= 0 or started_at <= 0 or started_at > block.timestamp + MAX_BLOCK_FUTURE_SKEW_SECONDS
            or answer not in (0, 1)):
        return SequencerStatus(False, "ORACLE_SEQUENCER_AUTHORITY_UNAVAILABLE", evidence, block.block_hash)
    if answer == 1:
        return SequencerStatus(False, "ORACLE_SEQUENCER_DOWN", evidence, block.block_hash)
    if block.timestamp - started_at <= sequencer.grace_period_seconds:
        return SequencerStatus(False, "ORACLE_SEQUENCER_GRACE_PERIOD", evidence, block.block_hash)
    return SequencerStatus(True, None, evidence, block.block_hash)


def read_stock_token_oracle(
    *, rpc: Rpc, registry: OracleRegistry, canonical_id: str, as_of: datetime,
    block: OracleBlockContext | OracleBlockFailure | None = None,
    sequencer: SequencerStatus | None = None,
) -> OracleObservation:
    """One exact reviewed Stock Token -> its oracle leg.

    ``block`` / ``sequencer`` may be shared across all assets of one cycle (one pinned block, one sequencer reading at that
    block). Called alone, this function pins its own block and evaluates the sequencer at the SAME block. ``latest`` is never
    read again: sequencer, ``oraclePaused()`` and feed description/decimals/latestRoundData all use the pinned tag."""
    if as_of.tzinfo is None or as_of.utcoffset() is None:
        raise ValueError("ORACLE_CLOCK_MUST_BE_AWARE")
    policy = APPROVED_BY_CANONICAL_ID.get(canonical_id)
    if policy is None:
        return _fail(canonical_id, "ORACLE_ASSET_NOT_APPROVED", state=AuthorityState.IDENTITY_UNAVAILABLE)
    binding = registry.binding_for(canonical_id)
    if binding is None:
        return _fail(canonical_id, "ORACLE_FEED_NOT_REVIEWED")
    if (binding.chain_id != SUPPORTED_CHAIN_ID or binding.canonical_id != canonical_id
            or binding.token_contract != policy.asset_key.contract_address.lower()):
        return _fail(canonical_id, "ORACLE_BINDING_IDENTITY_MISMATCH",
                     state=AuthorityState.IDENTITY_UNAVAILABLE, binding=binding)
    if binding.heartbeat_seconds is None:
        return _fail(canonical_id, "ORACLE_HEARTBEAT_NOT_REVIEWED", binding=binding)

    pinned = block if block is not None else pin_oracle_block(rpc, as_of=as_of)
    if isinstance(pinned, OracleBlockFailure):
        return _fail(canonical_id, pinned.reason, binding=binding)
    tag = pinned.tag

    status = sequencer if sequencer is not None else check_sequencer(rpc, registry.sequencer, pinned)
    if status.block_hash != pinned.block_hash:
        return _fail(canonical_id, "ORACLE_SEQUENCER_BLOCK_MISMATCH", binding=binding)
    if not status.ok:
        return _fail(canonical_id, status.reason or "ORACLE_SEQUENCER_AUTHORITY_UNAVAILABLE",
                     binding=binding, evidence=status.evidence)

    try:
        paused = _words(_call(rpc, binding.token_contract, SEL_ORACLE_PAUSED, tag), 1)[0]
    except (_BadEvidence, RpcUnavailable, ValueError, TypeError):
        return _fail(canonical_id, "ORACLE_PAUSE_STATE_UNAVAILABLE", binding=binding)
    if paused not in (0, 1):
        return _fail(canonical_id, "ORACLE_PAUSE_STATE_UNAVAILABLE", binding=binding)
    if paused == 1:
        return _fail(canonical_id, "ORACLE_CORPORATE_ACTION_PAUSED", binding=binding,
                     evidence={"oraclePaused": True, "blockNumber": pinned.number})

    try:
        description = _abi_string(_call(rpc, binding.feed_proxy, SEL_DESCRIPTION, tag))
        decimals = _words(_call(rpc, binding.feed_proxy, SEL_DECIMALS, tag), 1)[0]
        round_id, raw_answer, started_at, updated_at, answered_in = _words(
            _call(rpc, binding.feed_proxy, SEL_LATEST_ROUND, tag), 5)
        raw_answer = _signed(raw_answer)
    except (_BadEvidence, RpcUnavailable, ValueError, TypeError):
        return _fail(canonical_id, "ORACLE_RPC_UNAVAILABLE", binding=binding)
    if not verify_oracle_block(rpc, pinned):          # reorg protection: the pinned block must still be canonical
        return _fail(canonical_id, "ORACLE_BLOCK_REORG_OR_MISMATCH", binding=binding)
    block_time, number, block_hash = pinned.timestamp, pinned.number, pinned.block_hash

    evidence: dict[str, Any] = {
        "feedProxy": binding.feed_proxy, "feedDescription": description, "feedDecimals": decimals,
        "heartbeatSeconds": binding.heartbeat_seconds, "roundId": str(round_id), "answerRaw": str(raw_answer),
        "answeredInRound": str(answered_in), "updatedAtEpoch": updated_at, "startedAtEpoch": started_at,
        "blockNumber": number, "blockHash": block_hash, "blockTimestamp": block_time,
        "oraclePaused": False, "multiplierApplied": False, "unit": ORACLE_UNIT,
        "bindingProvenance": binding.provenance.source, "bindingReviewedAt": binding.provenance.reviewed_at,
        **dict(status.evidence),
    }
    if description != binding.feed_description:
        return _fail(canonical_id, "ORACLE_FEED_DESCRIPTION_MISMATCH", binding=binding, evidence=evidence)
    if not MIN_DECIMALS <= decimals <= MAX_DECIMALS or (
            binding.reviewed_decimals is not None and decimals != binding.reviewed_decimals):
        return _fail(canonical_id, "ORACLE_FEED_DECIMALS_MISMATCH", binding=binding, evidence=evidence)
    if round_id <= 0 or answered_in < round_id:
        return _fail(canonical_id, "ORACLE_ROUND_INCOMPLETE", binding=binding, evidence=evidence)
    if raw_answer <= 0:
        return _fail(canonical_id, "ORACLE_ANSWER_NOT_POSITIVE", binding=binding, evidence=evidence)
    if updated_at <= 0:
        return _fail(canonical_id, "ORACLE_UPDATED_AT_INVALID", binding=binding, evidence=evidence)
    if updated_at > block_time + MAX_BLOCK_FUTURE_SKEW_SECONDS:
        return _fail(canonical_id, "ORACLE_UPDATED_AT_IN_FUTURE", binding=binding, evidence=evidence)

    age = max(0, block_time - updated_at)
    value = Decimal(raw_answer) / (Decimal(10) ** decimals)
    source_timestamp = datetime.fromtimestamp(updated_at, timezone.utc)
    stale = age > binding.heartbeat_seconds
    return OracleObservation(
        AuthorityState.STALE if stale else AuthorityState.AVAILABLE,
        "ORACLE_HEARTBEAT_EXCEEDED" if stale else None,
        canonical_id, feed_proxy=binding.feed_proxy, value=value, source_timestamp=source_timestamp,
        decimals=decimals, heartbeat_seconds=binding.heartbeat_seconds, age_seconds=age, evidence=evidence)
