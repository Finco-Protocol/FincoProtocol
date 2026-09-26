"""FINCO Token Balance Reader — read-only ERC-20 balance via JSON-RPC.

Uses httpx for async HTTP.  All RPC calls are read-only (eth_call, eth_chainId,
eth_blockNumber).  Write methods (eth_sendTransaction, eth_sign, etc.) are
never called.

The token contract address comes from server-side config only.  No user-supplied
RPC URL or contract address is ever accepted.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any

import httpx

from app.protocol.token_config import TokenConfig

logger = logging.getLogger(__name__)


# ── Result dataclass ─────────────────────────────────────────────────────────

@dataclass
class TokenObservation:
    wallet_address: str
    chain_id: int
    token_address: str
    balance_raw: int | None
    decimals: int | None
    normalized_balance: Decimal | None
    block_number: int | None
    observed_at: datetime
    status: str  # see STATUS_* constants below


# Status codes
STATUS_ENTITLED = "ENTITLED"
STATUS_INSUFFICIENT = "INSUFFICIENT_BALANCE"
STATUS_RPC_UNAVAILABLE = "RPC_UNAVAILABLE"
STATUS_CHAIN_ID_MISMATCH = "CHAIN_ID_MISMATCH"
STATUS_TOKEN_CONTRACT_UNAVAILABLE = "TOKEN_CONTRACT_UNAVAILABLE"
STATUS_BALANCE_UNAVAILABLE = "BALANCE_UNAVAILABLE"
STATUS_NOT_CONFIGURED = "NOT_CONFIGURED"


# ── ABI encoding helpers ─────────────────────────────────────────────────────

def _encode_balanceof(wallet_address: str) -> str:
    """Encode balanceOf(address) call data.
    Selector: 0x70a08231
    ABI: address padded to 32 bytes.
    """
    addr_hex = wallet_address.lower().removeprefix("0x").zfill(64)
    return "0x70a08231" + addr_hex


def _encode_decimals() -> str:
    """Encode decimals() call data. Selector: 0x313ce567."""
    return "0x313ce567"


def _decode_uint(hex_result: str) -> int | None:
    """Decode a 32-byte uint from eth_call result."""
    v = hex_result.strip()
    if not v or v == "0x":
        return None
    try:
        return int(v, 16)
    except ValueError:
        return None


# ── JSON-RPC helpers ─────────────────────────────────────────────────────────

_RPC_ID = 1


async def _rpc_call(client: httpx.AsyncClient, rpc_url: str, method: str, params: list) -> Any:
    """Make a single eth JSON-RPC call.  Returns the 'result' field or raises."""
    payload = {
        "jsonrpc": "2.0",
        "id": _RPC_ID,
        "method": method,
        "params": params,
    }
    resp = await client.post(rpc_url, json=payload, timeout=10.0)
    resp.raise_for_status()
    data = resp.json()
    if "error" in data:
        raise ValueError(f"RPC error: {data['error']}")
    return data.get("result")


# ── Public API ───────────────────────────────────────────────────────────────

async def read_token_balance(
    wallet_address: str,
    config: TokenConfig,
) -> TokenObservation:
    """Read ERC-20 balance for wallet_address using server-side config.

    wallet_address is trusted (already verified as owned by the session user).
    Token contract address comes from server config only.

    Failures are explicit — RPC errors are never silently converted to zero.
    """
    observed_at = datetime.now(timezone.utc)

    def _unavailable(status: str, **kw) -> TokenObservation:
        return TokenObservation(
            wallet_address=wallet_address,
            chain_id=config.chain_id,
            token_address=config.token_address,
            balance_raw=None,
            decimals=None,
            normalized_balance=None,
            block_number=None,
            observed_at=observed_at,
            status=status,
            **kw,
        )

    try:
        async with httpx.AsyncClient() as client:
            # 1. Verify chain ID
            try:
                chain_id_hex = await _rpc_call(
                    client, config.rpc_url, "eth_chainId", []
                )
                actual_chain_id = int(chain_id_hex, 16)
            except Exception as exc:
                logger.warning("eth_chainId failed: %s", exc)
                return _unavailable(STATUS_RPC_UNAVAILABLE)

            if actual_chain_id != config.chain_id:
                logger.warning(
                    "Chain ID mismatch: expected %d got %d",
                    config.chain_id,
                    actual_chain_id,
                )
                return TokenObservation(
                    wallet_address=wallet_address,
                    chain_id=actual_chain_id,
                    token_address=config.token_address,
                    balance_raw=None,
                    decimals=None,
                    normalized_balance=None,
                    block_number=None,
                    observed_at=observed_at,
                    status=STATUS_CHAIN_ID_MISMATCH,
                )

            # 2. Get decimals (override or from contract)
            if config.decimals_override is not None:
                decimals = config.decimals_override
            else:
                try:
                    dec_result = await _rpc_call(
                        client,
                        config.rpc_url,
                        "eth_call",
                        [
                            {
                                "to": config.token_address,
                                "data": _encode_decimals(),
                            },
                            "latest",
                        ],
                    )
                    decimals = _decode_uint(dec_result)
                    if decimals is None:
                        logger.warning("decimals() returned empty/invalid result")
                        return _unavailable(STATUS_TOKEN_CONTRACT_UNAVAILABLE)
                except Exception as exc:
                    logger.warning("decimals() call failed: %s", exc)
                    return _unavailable(STATUS_TOKEN_CONTRACT_UNAVAILABLE)

            # 3. Read balanceOf
            try:
                bal_result = await _rpc_call(
                    client,
                    config.rpc_url,
                    "eth_call",
                    [
                        {
                            "to": config.token_address,
                            "data": _encode_balanceof(wallet_address),
                        },
                        "latest",
                    ],
                )
                balance_raw = _decode_uint(bal_result)
                if balance_raw is None:
                    return _unavailable(STATUS_BALANCE_UNAVAILABLE)
            except Exception as exc:
                logger.warning("balanceOf() call failed: %s", exc)
                return _unavailable(STATUS_BALANCE_UNAVAILABLE)

            # 4. Record block number
            block_number: int | None = None
            try:
                block_hex = await _rpc_call(
                    client, config.rpc_url, "eth_blockNumber", []
                )
                block_number = int(block_hex, 16)
            except Exception:
                pass  # non-fatal — just omit block number

            # Normalize balance
            try:
                normalized = Decimal(balance_raw) / Decimal(10 ** decimals)
            except (InvalidOperation, OverflowError, ZeroDivisionError):
                return _unavailable(STATUS_BALANCE_UNAVAILABLE)

            return TokenObservation(
                wallet_address=wallet_address,
                chain_id=config.chain_id,
                token_address=config.token_address,
                balance_raw=balance_raw,
                decimals=decimals,
                normalized_balance=normalized,
                block_number=block_number,
                observed_at=observed_at,
                status=STATUS_ENTITLED
                if normalized >= config.min_balance
                else STATUS_INSUFFICIENT,
            )

    except Exception as exc:
        logger.warning("Unexpected error reading token balance: %s", exc)
        return _unavailable(STATUS_RPC_UNAVAILABLE)
