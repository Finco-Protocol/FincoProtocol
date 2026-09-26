"""FINCO Token Configuration — chain-agnostic ERC-20 access token config.

Reads from environment variables.  Returns None (NOT_CONFIGURED) when any
required field is absent or invalid.  The RPC URL is NEVER sent to the browser.

Environment variables:
  FINCO_TOKEN_RPC_URL         — server-side only, never exposed to browser
  FINCO_TOKEN_CHAIN_ID        — integer chain id (e.g. 1 for mainnet)
  FINCO_TOKEN_ADDRESS         — ERC-20 contract address (0x + 40 hex chars)
  FINCO_ACCESS_MIN_BALANCE    — minimum balance in token units (not wei)
  FINCO_TOKEN_DECIMALS        — optional explicit decimal override; if absent,
                                 decimals are read from contract at query time
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation


# ── Dataclass ────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class TokenConfig:
    rpc_url: str           # server-side only — NEVER sent to browser
    chain_id: int
    token_address: str     # checksummed (or at minimum validated hex)
    min_balance: Decimal   # in token units, positive
    decimals_override: int | None  # None → read from contract


# ── Validation helpers ───────────────────────────────────────────────────────

def _validate_hex_address(value: str) -> str | None:
    """Return normalised 0x-prefixed 42-char hex address or None if invalid."""
    v = value.strip()
    if not v.startswith("0x") and not v.startswith("0X"):
        return None
    hex_part = v[2:]
    if len(hex_part) != 40:
        return None
    try:
        int(hex_part, 16)
    except ValueError:
        return None
    return "0x" + hex_part.lower()


# ── Public factory ───────────────────────────────────────────────────────────

def get_token_config() -> TokenConfig | None:
    """Return TokenConfig from environment, or None if misconfigured.

    Callers treat None as NOT_CONFIGURED — never raise or guess defaults.
    """
    rpc_url = os.getenv("FINCO_TOKEN_RPC_URL", "").strip()
    chain_id_raw = os.getenv("FINCO_TOKEN_CHAIN_ID", "").strip()
    address_raw = os.getenv("FINCO_TOKEN_ADDRESS", "").strip()
    min_balance_raw = os.getenv("FINCO_ACCESS_MIN_BALANCE", "").strip()
    decimals_raw = os.getenv("FINCO_TOKEN_DECIMALS", "").strip()

    if not rpc_url:
        return None

    # Chain ID
    try:
        chain_id = int(chain_id_raw)
        if chain_id <= 0:
            return None
    except (ValueError, TypeError):
        return None

    # Token address
    if not address_raw:
        return None
    address = _validate_hex_address(address_raw)
    if address is None:
        return None

    # Min balance — no default: if missing, NOT_CONFIGURED
    if not min_balance_raw:
        return None
    try:
        min_balance = Decimal(min_balance_raw)
        if min_balance <= 0:
            return None
    except InvalidOperation:
        return None

    # Optional decimals override
    decimals_override: int | None = None
    if decimals_raw:
        try:
            d = int(decimals_raw)
            if d < 0 or d > 77:
                return None
            decimals_override = d
        except (ValueError, TypeError):
            return None

    return TokenConfig(
        rpc_url=rpc_url,
        chain_id=chain_id,
        token_address=address,
        min_balance=min_balance,
        decimals_override=decimals_override,
    )
