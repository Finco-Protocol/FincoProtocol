"""FINCO Access Decision — typed access-decision authority for P4 utilities.

The same get_access_decision() function serves ALL API and browser consumers.
It has ZERO awareness of model calculations, certificates, or Radar results.
Enforcement is additive: existing product access is NOT gated behind this rail.
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from app.protocol.token_config import TokenConfig
from app.protocol.token_balance import (
    TokenObservation,
    STATUS_ENTITLED,
    STATUS_INSUFFICIENT,
    STATUS_CHAIN_ID_MISMATCH,
    STATUS_RPC_UNAVAILABLE,
    STATUS_TOKEN_CONTRACT_UNAVAILABLE,
    STATUS_BALANCE_UNAVAILABLE,
    STATUS_NOT_CONFIGURED,
)
from app.protocol.utility_registry import UTILITY_REGISTRY

logger = logging.getLogger(__name__)

POLICY_VERSION = "V1"


# ── Result dataclass ─────────────────────────────────────────────────────────

@dataclass
class AccessDecision:
    utility: str                    # e.g. "FINCO_COMPUTE"
    status: str                     # ENTITLED / INSUFFICIENT_BALANCE / WALLET_NOT_CONNECTED / NOT_CONFIGURED / OBSERVATION_UNAVAILABLE
    allowed: bool
    access_mode: str                # "TOKEN_HOLDER" | "NOT_CONFIGURED" | "NO_WALLET" | etc.
    wallet_address: str | None
    observed_balance: Decimal | None
    required_balance: Decimal | None
    chain_id: int | None
    block_number: int | None
    observed_at: datetime | None
    policy_version: str
    reason_code: str


# ── Decision logic ────────────────────────────────────────────────────────────

def get_access_decision(
    utility: str,
    wallet_address: str | None,
    config: TokenConfig | None,
    observation: TokenObservation | None = None,
) -> AccessDecision:
    """Return a typed access decision for utility + wallet + config.

    Accepts an already-fetched TokenObservation to avoid redundant RPC calls
    when serving multiple utilities in one request.

    Decision precedence:
      1. config is None → NOT_CONFIGURED, allowed=False
      2. wallet_address is None → WALLET_NOT_CONNECTED, allowed=False
      3. observation is None → OBSERVATION_UNAVAILABLE, allowed=False
      4. observation.status is CHAIN_ID_MISMATCH / RPC_UNAVAILABLE / etc → OBSERVATION_UNAVAILABLE
      5. balance < min_balance → INSUFFICIENT_BALANCE, allowed=False
      6. balance >= min_balance → ENTITLED, allowed=True
    """
    if utility not in UTILITY_REGISTRY:
        return AccessDecision(
            utility=utility,
            status="NOT_CONFIGURED",
            allowed=False,
            access_mode="UNKNOWN_UTILITY",
            wallet_address=None,
            observed_balance=None,
            required_balance=None,
            chain_id=None,
            block_number=None,
            observed_at=None,
            policy_version=POLICY_VERSION,
            reason_code="UNKNOWN_UTILITY",
        )

    if config is None:
        return AccessDecision(
            utility=utility,
            status="NOT_CONFIGURED",
            allowed=False,
            access_mode="NOT_CONFIGURED",
            wallet_address=None,
            observed_balance=None,
            required_balance=None,
            chain_id=None,
            block_number=None,
            observed_at=None,
            policy_version=POLICY_VERSION,
            reason_code="TOKEN_ACCESS_NOT_CONFIGURED",
        )

    if not wallet_address:
        return AccessDecision(
            utility=utility,
            status="WALLET_NOT_CONNECTED",
            allowed=False,
            access_mode="NO_WALLET",
            wallet_address=None,
            observed_balance=None,
            required_balance=config.min_balance,
            chain_id=config.chain_id,
            block_number=None,
            observed_at=None,
            policy_version=POLICY_VERSION,
            reason_code="WALLET_NOT_CONNECTED",
        )

    if observation is None:
        return AccessDecision(
            utility=utility,
            status="OBSERVATION_UNAVAILABLE",
            allowed=False,
            access_mode="OBSERVATION_UNAVAILABLE",
            wallet_address=wallet_address,
            observed_balance=None,
            required_balance=config.min_balance,
            chain_id=config.chain_id,
            block_number=None,
            observed_at=None,
            policy_version=POLICY_VERSION,
            reason_code="OBSERVATION_NOT_FETCHED",
        )

    # Map observation status to decision
    obs_status = observation.status
    if obs_status not in (STATUS_ENTITLED, STATUS_INSUFFICIENT):
        # Any other status (RPC error, chain mismatch, etc.) → OBSERVATION_UNAVAILABLE
        return AccessDecision(
            utility=utility,
            status="OBSERVATION_UNAVAILABLE",
            allowed=False,
            access_mode="OBSERVATION_UNAVAILABLE",
            wallet_address=wallet_address,
            observed_balance=observation.normalized_balance,
            required_balance=config.min_balance,
            chain_id=observation.chain_id,
            block_number=observation.block_number,
            observed_at=observation.observed_at,
            policy_version=POLICY_VERSION,
            reason_code=obs_status,
        )

    if obs_status == STATUS_INSUFFICIENT or (
        observation.normalized_balance is not None
        and observation.normalized_balance < config.min_balance
    ):
        return AccessDecision(
            utility=utility,
            status="INSUFFICIENT_BALANCE",
            allowed=False,
            access_mode="TOKEN_HOLDER",
            wallet_address=wallet_address,
            observed_balance=observation.normalized_balance,
            required_balance=config.min_balance,
            chain_id=observation.chain_id,
            block_number=observation.block_number,
            observed_at=observation.observed_at,
            policy_version=POLICY_VERSION,
            reason_code="BALANCE_BELOW_MINIMUM",
        )

    return AccessDecision(
        utility=utility,
        status="ENTITLED",
        allowed=True,
        access_mode="TOKEN_HOLDER",
        wallet_address=wallet_address,
        observed_balance=observation.normalized_balance,
        required_balance=config.min_balance,
        chain_id=observation.chain_id,
        block_number=observation.block_number,
        observed_at=observation.observed_at,
        policy_version=POLICY_VERSION,
        reason_code="SUFFICIENT_BALANCE",
    )


async def get_all_access_decisions(
    wallet_address: str | None,
    config: TokenConfig | None,
) -> tuple[TokenObservation | None, dict[str, AccessDecision]]:
    """Fetch balance once, return decisions for all utilities.

    Returns (observation, {utility_id: AccessDecision}).
    observation may be None if config is missing or wallet is absent.
    """
    from app.protocol.utility_registry import UTILITY_REGISTRY

    observation: TokenObservation | None = None

    if config is not None and wallet_address:
        from app.protocol.token_balance import read_token_balance
        try:
            observation = await read_token_balance(wallet_address, config)
        except Exception as exc:
            logger.warning("read_token_balance failed: %s", exc)
            observation = None

    decisions = {
        uid: get_access_decision(uid, wallet_address, config, observation)
        for uid in UTILITY_REGISTRY
    }
    return observation, decisions
