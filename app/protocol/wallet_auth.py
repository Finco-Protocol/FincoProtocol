"""FINCO Wallet Auth — EIP-191 signed challenge / ownership verification.

Challenge/Verify flow:
  1. POST /protocol/finco/wallet/challenge  → server issues a signed challenge string
  2. Browser wallet signs the challenge via personal_sign (EIP-191)
  3. POST /protocol/finco/wallet/verify     → server recovers signer, binds wallet to user

Security properties:
  - No private key ever touches the server
  - No transaction signing or arbitrary calldata
  - Nonce is single-use (consumed regardless of verify outcome)
  - Challenge expires in CHALLENGE_TTL_SECONDS (5 minutes)
  - Cross-user isolation: challenge nonce binds to issuing user_id
  - Wallet address is persisted to DB; subsequent reads come from DB (not request body)
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone, timedelta

from app.protocol._evm_crypto import recover_eip191_signer

logger = logging.getLogger(__name__)

CHALLENGE_TTL_SECONDS = 300  # 5 minutes


# ── Challenge text builder ────────────────────────────────────────────────────

def build_challenge_text(
    wallet_address: str,
    nonce: str,
    user_id: str,
    chain_id: int,
    issued_at: datetime,
    expires_at: datetime,
    domain: str,
) -> str:
    """Build the EIP-191 challenge message text.

    The challenge binds: domain, wallet address, user id, nonce, timestamps,
    and chain id.  The browser wallet signs this exact string.
    """
    return (
        f"FINCO Protocol wants you to verify wallet ownership.\n\n"
        f"Domain: {domain}\n"
        f"Wallet: {wallet_address}\n"
        f"User: {user_id}\n"
        f"Chain ID: {chain_id}\n"
        f"Nonce: {nonce}\n"
        f"Issued At: {issued_at.isoformat()}\n"
        f"Expires At: {expires_at.isoformat()}"
    )


# ── DB helpers ────────────────────────────────────────────────────────────────

def _ensure_challenge_table(conn) -> None:
    """Create wallet_challenges table if absent (idempotent)."""
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS wallet_challenges (
            nonce      TEXT PRIMARY KEY,
            user_id    TEXT NOT NULL,
            wallet_address TEXT NOT NULL,
            challenge_text TEXT NOT NULL,
            issued_at  TEXT NOT NULL,
            expires_at TEXT NOT NULL,
            used       INTEGER NOT NULL DEFAULT 0
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_challenges_user ON wallet_challenges(user_id)"
    )


def _ensure_wallet_table(conn) -> None:
    """Create user_wallets table if absent (idempotent)."""
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS user_wallets (
            user_id        TEXT PRIMARY KEY,
            wallet_address TEXT NOT NULL,
            verified_at    TEXT NOT NULL
        )
        """
    )


# ── Issue challenge ───────────────────────────────────────────────────────────

def issue_challenge(
    user_id: str,
    wallet_address: str,
    chain_id: int,
    domain: str = "localhost",
) -> dict:
    """Create a challenge nonce and store it in the DB.

    Returns a dict with challenge_text and nonce for the response.
    """
    from app.persistence.db import get_connection

    nonce = str(uuid.uuid4())
    now = datetime.now(timezone.utc)
    expires = now + timedelta(seconds=CHALLENGE_TTL_SECONDS)

    text = build_challenge_text(
        wallet_address=wallet_address,
        nonce=nonce,
        user_id=user_id,
        chain_id=chain_id,
        issued_at=now,
        expires_at=expires,
        domain=domain,
    )

    conn = get_connection()
    try:
        _ensure_challenge_table(conn)
        conn.execute(
            """
            INSERT INTO wallet_challenges
              (nonce, user_id, wallet_address, challenge_text, issued_at, expires_at, used)
            VALUES (?, ?, ?, ?, ?, ?, 0)
            """,
            (nonce, user_id, wallet_address, text, now.isoformat(), expires.isoformat()),
        )
        conn.commit()
    finally:
        conn.close()

    return {
        "nonce": nonce,
        "challenge_text": text,
        "expires_at": expires.isoformat(),
    }


# ── Verify challenge ──────────────────────────────────────────────────────────

class WalletVerifyError(Exception):
    """Raised when wallet verification fails. Carries a reason_code."""
    def __init__(self, reason_code: str, message: str):
        super().__init__(message)
        self.reason_code = reason_code


def verify_challenge(
    user_id: str,
    wallet_address: str,
    nonce: str,
    signature: str,
) -> str:
    """Verify an EIP-191 wallet signature and bind wallet to user on success.

    Returns the verified wallet_address on success.
    Raises WalletVerifyError on any failure.

    The nonce is consumed (marked used) regardless of outcome.
    """
    from app.persistence.db import get_connection

    wallet_address_lower = wallet_address.strip().lower()

    conn = get_connection()
    try:
        _ensure_challenge_table(conn)
        _ensure_wallet_table(conn)

        row = conn.execute(
            """
            SELECT nonce, user_id, wallet_address, challenge_text,
                   issued_at, expires_at, used
            FROM wallet_challenges
            WHERE nonce = ?
            """,
            (nonce,),
        ).fetchone()

        # Consume nonce regardless of outcome
        if row is not None:
            conn.execute(
                "UPDATE wallet_challenges SET used = 1 WHERE nonce = ?",
                (nonce,),
            )
            conn.commit()

        if row is None:
            raise WalletVerifyError("NONCE_NOT_FOUND", "Challenge nonce not found.")

        if row["used"]:
            raise WalletVerifyError("NONCE_ALREADY_USED", "Challenge nonce already used.")

        # Cross-user isolation
        if row["user_id"] != user_id:
            raise WalletVerifyError(
                "USER_MISMATCH",
                "Challenge was not issued for this user.",
            )

        # Wallet address must match what challenge was issued for
        if row["wallet_address"].lower() != wallet_address_lower:
            raise WalletVerifyError(
                "ADDRESS_MISMATCH",
                "Wallet address does not match challenge.",
            )

        # Expiry check
        expires_at = datetime.fromisoformat(row["expires_at"])
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        if datetime.now(timezone.utc) > expires_at:
            raise WalletVerifyError("CHALLENGE_EXPIRED", "Challenge has expired.")

        # EIP-191 signature verification
        challenge_text = row["challenge_text"]
        recovered = recover_eip191_signer(challenge_text, signature)
        if recovered is None:
            raise WalletVerifyError(
                "SIGNATURE_INVALID",
                "Could not recover signer from signature.",
            )

        if recovered.lower() != wallet_address_lower:
            raise WalletVerifyError(
                "SIGNER_MISMATCH",
                f"Recovered signer {recovered} does not match wallet {wallet_address}.",
            )

        # Bind wallet to user
        verified_at = datetime.now(timezone.utc).isoformat()
        conn.execute(
            """
            INSERT INTO user_wallets (user_id, wallet_address, verified_at)
            VALUES (?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
              wallet_address = excluded.wallet_address,
              verified_at    = excluded.verified_at
            """,
            (user_id, wallet_address_lower, verified_at),
        )
        conn.commit()

        return wallet_address_lower

    finally:
        conn.close()


# ── Wallet lookup ─────────────────────────────────────────────────────────────

def get_verified_wallet(user_id: str) -> dict | None:
    """Return {'wallet_address': ..., 'verified_at': ...} or None."""
    from app.persistence.db import get_connection

    conn = get_connection()
    try:
        _ensure_wallet_table(conn)
        row = conn.execute(
            "SELECT wallet_address, verified_at FROM user_wallets WHERE user_id = ?",
            (user_id,),
        ).fetchone()
        if row is None:
            return None
        return {
            "wallet_address": row["wallet_address"],
            "verified_at": row["verified_at"],
        }
    finally:
        conn.close()
