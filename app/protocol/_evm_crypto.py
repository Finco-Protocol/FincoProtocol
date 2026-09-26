"""EVM cryptographic helpers — thin wrappers over eth-account.

Provides the same interface previously served by a hand-rolled implementation
so that existing callers (wallet_auth.py, tests) require minimal changes.

The FINCO server ONLY performs signature recovery / verification.
It never generates or holds production wallet private keys.

Test helpers (generate_keypair, sign_personal_message) are provided for use
inside test suites only and must never be called in production authentication
paths.
"""
from __future__ import annotations

from typing import NamedTuple

from eth_account import Account
from eth_account.messages import encode_defunct
from eth_keys.datatypes import PrivateKey as _EthPrivateKey


# ── Public interface ──────────────────────────────────────────────────────────

def recover_eip191_signer(message: str, signature_hex: str) -> str | None:
    """Recover the Ethereum address that signed an EIP-191 personal message.

    Returns the 0x-prefixed checksummed address (lowercased) or None on any
    failure (malformed signature, bad bytes, invalid r/s bounds, etc.).

    message: the raw challenge string (before EIP-191 prefix).
    signature_hex: '0x'-prefixed 130-char hex (65 bytes: r[32] s[32] v[1]).
    """
    try:
        msg = encode_defunct(text=message)
        recovered = Account.recover_message(msg, signature=signature_hex)
        return recovered.lower()
    except Exception:
        return None


# ── keccak256 — re-exported from eth_utils for any callers that import it ─────

def keccak256(data: bytes) -> bytes:
    """Compute Ethereum's Keccak-256 hash (delegates to eth-hash/eth-utils)."""
    from eth_utils import keccak
    return keccak(primitive=data)


# ── Test-only helpers ─────────────────────────────────────────────────────────
# These functions MUST NOT be used in any production authentication path.
# They exist solely to support ephemeral deterministic keys in test suites.

class Secp256k1Keypair(NamedTuple):
    """Ephemeral test keypair.  Never use private_key outside of tests."""
    private_key: bytes   # 32 raw bytes
    public_key: tuple[int, int]  # (x, y) — retained for interface compat


def generate_keypair() -> Secp256k1Keypair:
    """Generate a fresh ephemeral secp256k1 keypair for use in tests only."""
    acct = Account.create()
    priv_bytes = bytes.fromhex(acct.key.hex()[2:] if acct.key.hex().startswith("0x") else acct.key.hex())
    # Derive (x, y) for interface compatibility — not used in crypto ops
    pk = _EthPrivateKey(priv_bytes)
    pub = pk.public_key
    x = int.from_bytes(pub.to_bytes()[1:33], "big")
    y = int.from_bytes(pub.to_bytes()[33:65], "big")
    return Secp256k1Keypair(private_key=priv_bytes, public_key=(x, y))


def private_key_to_address(private_key: bytes | int) -> str:
    """Derive an Ethereum address from a private key (test helper only)."""
    if isinstance(private_key, int):
        private_key = private_key.to_bytes(32, "big")
    acct = Account.from_key(private_key)
    return acct.address.lower()


def sign_personal_message(message: str, private_key: bytes | int) -> str:
    """Sign an EIP-191 personal_sign message (test helper only).

    Returns the 0x-prefixed 130-char hex signature.
    """
    if isinstance(private_key, int):
        private_key = private_key.to_bytes(32, "big")
    msg = encode_defunct(text=message)
    signed = Account.sign_message(msg, private_key=private_key)
    return signed.signature.hex() if not signed.signature.hex().startswith("0x") else signed.signature.hex()
