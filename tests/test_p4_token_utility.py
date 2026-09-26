"""P4 FINCO Token Utility V1 — focused test suite.

Tests A–T as specified.  All cryptographic test keys are ephemeral
(generated fresh inside each test scope) and never committed.
"""
from __future__ import annotations

import asyncio
import os
import time
import uuid
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ────────────────────────────────────────────────────────────────────────────
# A. Utility registry
# ────────────────────────────────────────────────────────────────────────────

class TestUtilityRegistry:
    """A. Utility registry — 3 utilities defined, stable identifiers, single source of truth."""

    def test_exactly_three_utilities(self):
        from app.protocol.utility_registry import UTILITY_REGISTRY
        assert len(UTILITY_REGISTRY) == 3

    def test_stable_identifiers_present(self):
        from app.protocol.utility_registry import (
            UTILITY_REGISTRY,
            FINCO_COMPUTE,
            FINCO_VERIFY_PUBLISH,
            FINCO_INTELLIGENCE,
        )
        assert FINCO_COMPUTE in UTILITY_REGISTRY
        assert FINCO_VERIFY_PUBLISH in UTILITY_REGISTRY
        assert FINCO_INTELLIGENCE in UTILITY_REGISTRY

    def test_identifier_strings_exact(self):
        from app.protocol.utility_registry import (
            FINCO_COMPUTE, FINCO_VERIFY_PUBLISH, FINCO_INTELLIGENCE
        )
        assert FINCO_COMPUTE == "FINCO_COMPUTE"
        assert FINCO_VERIFY_PUBLISH == "FINCO_VERIFY_PUBLISH"
        assert FINCO_INTELLIGENCE == "FINCO_INTELLIGENCE"

    def test_registry_has_required_fields(self):
        from app.protocol.utility_registry import UTILITY_REGISTRY
        for uid, util in UTILITY_REGISTRY.items():
            assert util.identifier == uid
            assert util.display_name
            assert util.description

    def test_display_names(self):
        from app.protocol.utility_registry import UTILITY_REGISTRY, FINCO_COMPUTE, FINCO_VERIFY_PUBLISH, FINCO_INTELLIGENCE
        assert UTILITY_REGISTRY[FINCO_COMPUTE].display_name == "Compute"
        assert UTILITY_REGISTRY[FINCO_VERIFY_PUBLISH].display_name == "Verify & Publish"
        assert UTILITY_REGISTRY[FINCO_INTELLIGENCE].display_name == "Intelligence"


# ────────────────────────────────────────────────────────────────────────────
# B. Wallet challenge — issued correctly
# ────────────────────────────────────────────────────────────────────────────

class TestWalletChallenge:
    """B. Challenge contains required fields and is bound to user."""

    def _make_challenge_text(self, wallet, nonce, chain_id=1, domain="test.domain"):
        from app.protocol.wallet_auth import build_challenge_text
        now = datetime.now(timezone.utc)
        expires = now + timedelta(seconds=300)
        return build_challenge_text(
            wallet_address=wallet,
            nonce=nonce,
            chain_id=chain_id,
            issued_at=now,
            expires_at=expires,
            domain=domain,
        )

    def test_challenge_contains_nonce(self):
        nonce = str(uuid.uuid4())
        text = self._make_challenge_text("0xabc" + "0" * 37, nonce)
        assert nonce in text

    def test_challenge_contains_wallet(self):
        wallet = "0x" + "a" * 40
        text = self._make_challenge_text(wallet, str(uuid.uuid4()))
        assert wallet in text

    def test_challenge_no_internal_user_id(self):
        """FINCO_WALLET_CHALLENGE_NO_INTERNAL_USER_ID — internal user_id must not appear in signed challenge text."""
        internal_user_id = "user_internal_123"
        text = self._make_challenge_text("0x" + "b" * 40, str(uuid.uuid4()))
        assert internal_user_id not in text
        assert "User:" not in text
        assert "user_id" not in text

    def test_challenge_contains_chain_id(self):
        text = self._make_challenge_text("0x" + "c" * 40, str(uuid.uuid4()), chain_id=137)
        assert "137" in text

    def test_challenge_contains_domain(self):
        from app.protocol.wallet_auth import build_challenge_text
        now = datetime.now(timezone.utc)
        text = build_challenge_text(
            wallet_address="0x" + "d" * 40,
            nonce=str(uuid.uuid4()),
            chain_id=1,
            issued_at=now,
            expires_at=now + timedelta(minutes=5),
            domain="test.example.com",
        )
        assert "test.example.com" in text

    def test_domain_explicit_no_default(self, tmp_path, monkeypatch):
        """FINCO_WALLET_DOMAIN_EXPLICIT — issue_challenge() domain is required (no localhost default)."""
        import inspect
        from app.protocol.wallet_auth import issue_challenge
        sig = inspect.signature(issue_challenge)
        domain_param = sig.parameters.get("domain")
        assert domain_param is not None, "domain param missing from issue_challenge"
        assert domain_param.default is inspect.Parameter.empty, (
            "domain must be a required arg; no default prevents localhost leaking into production"
        )

    def test_challenge_issue_stores_in_db(self, tmp_path, monkeypatch):
        monkeypatch.setenv("FINCO_DB_PATH", str(tmp_path / "test.db"))
        from app.protocol.wallet_auth import issue_challenge
        result = issue_challenge(
            user_id="testuser",
            wallet_address="0x" + "e" * 40,
            chain_id=1,
            domain="test.fincoprotocol.com",
        )
        assert "nonce" in result
        assert "challenge_text" in result
        assert "expires_at" in result
        assert len(result["nonce"]) > 10

    def test_server_side_user_binding_preserved(self, tmp_path, monkeypatch):
        """FINCO_WALLET_SERVER_SIDE_USER_BINDING — user_id stored in DB even though absent from challenge text."""
        monkeypatch.setenv("FINCO_DB_PATH", str(tmp_path / "test.db"))
        from app.protocol.wallet_auth import issue_challenge
        import app.persistence.db as _db_mod
        result = issue_challenge(
            user_id="internal_user_456",
            wallet_address="0x" + "f" * 40,
            chain_id=1,
            domain="test.fincoprotocol.com",
        )
        # user_id is NOT in the signed text
        assert "internal_user_456" not in result["challenge_text"]
        # user_id IS stored in the DB for server-side isolation
        conn = _db_mod.get_connection()
        row = conn.execute(
            "SELECT user_id FROM wallet_challenges WHERE nonce = ?", (result["nonce"],)
        ).fetchone()
        conn.close()
        assert row is not None
        assert row["user_id"] == "internal_user_456"


# ────────────────────────────────────────────────────────────────────────────
# C. Signature verification — valid EIP-191 accepted
# ────────────────────────────────────────────────────────────────────────────

class TestSignatureVerification:
    """C. Valid EIP-191 signature accepted."""

    def test_sign_and_verify_roundtrip(self):
        from app.protocol._evm_crypto import (
            generate_keypair, sign_personal_message, recover_eip191_signer,
            private_key_to_address,
        )
        kp = generate_keypair()
        addr = private_key_to_address(kp.private_key)
        msg = "test verification message abc"
        sig = sign_personal_message(msg, kp.private_key)
        recovered = recover_eip191_signer(msg, sig)
        assert recovered is not None
        assert recovered.lower() == addr.lower()

    def test_keccak256_empty_vector(self):
        """keccak256('') must equal the known Ethereum vector."""
        from app.protocol._evm_crypto import keccak256
        result = keccak256(b"")
        assert result.hex() == "c5d2460186f7233c927e7db2dcc703c0e500b653ca82273b7bfad8045d85a470"

    def test_wrong_signature_does_not_match(self):
        from app.protocol._evm_crypto import (
            generate_keypair, sign_personal_message, recover_eip191_signer,
            private_key_to_address,
        )
        kp1 = generate_keypair()
        kp2 = generate_keypair()
        addr1 = private_key_to_address(kp1.private_key)
        msg = "some challenge"
        sig = sign_personal_message(msg, kp2.private_key)  # signed by kp2, not kp1
        recovered = recover_eip191_signer(msg, sig)
        assert recovered is not None
        assert recovered.lower() != addr1.lower()

    def test_full_verify_challenge_success(self, tmp_path, monkeypatch):
        monkeypatch.setenv("FINCO_DB_PATH", str(tmp_path / "test.db"))
        from app.protocol._evm_crypto import generate_keypair, sign_personal_message, private_key_to_address
        from app.protocol.wallet_auth import issue_challenge, verify_challenge

        kp = generate_keypair()
        addr = private_key_to_address(kp.private_key)

        issued = issue_challenge(user_id="user1", wallet_address=addr, chain_id=1, domain="test.finco.local")
        sig = sign_personal_message(issued["challenge_text"], kp.private_key)

        result = verify_challenge(
            user_id="user1",
            wallet_address=addr,
            nonce=issued["nonce"],
            signature=sig,
        )
        assert result.lower() == addr.lower()


# ────────────────────────────────────────────────────────────────────────────
# D. Nonce replay — second use rejected
# ────────────────────────────────────────────────────────────────────────────

class TestNonceReplay:
    """D. Second use of same nonce rejected."""

    def test_nonce_replay_rejected(self, tmp_path, monkeypatch):
        monkeypatch.setenv("FINCO_DB_PATH", str(tmp_path / "test.db"))
        from app.protocol._evm_crypto import generate_keypair, sign_personal_message, private_key_to_address
        from app.protocol.wallet_auth import issue_challenge, verify_challenge, WalletVerifyError

        kp = generate_keypair()
        addr = private_key_to_address(kp.private_key)
        issued = issue_challenge(user_id="user1", wallet_address=addr, chain_id=1, domain="test.finco.local")
        sig = sign_personal_message(issued["challenge_text"], kp.private_key)

        # First use succeeds
        verify_challenge(user_id="user1", wallet_address=addr, nonce=issued["nonce"], signature=sig)

        # Second use fails
        with pytest.raises(WalletVerifyError) as exc_info:
            verify_challenge(user_id="user1", wallet_address=addr, nonce=issued["nonce"], signature=sig)
        assert exc_info.value.reason_code == "NONCE_ALREADY_USED"


# ────────────────────────────────────────────────────────────────────────────
# E. Challenge expiration — expired challenge rejected
# ────────────────────────────────────────────────────────────────────────────

class TestChallengeExpiration:
    """E. Expired challenge rejected."""

    def test_expired_challenge_rejected(self, tmp_path, monkeypatch):
        monkeypatch.setenv("FINCO_DB_PATH", str(tmp_path / "test.db"))
        from app.protocol._evm_crypto import generate_keypair, sign_personal_message, private_key_to_address
        from app.protocol.wallet_auth import issue_challenge, WalletVerifyError
        from app.protocol import wallet_auth as _wallet_auth_mod
        import app.persistence.db as _db_mod
        import sqlite3

        kp = generate_keypair()
        addr = private_key_to_address(kp.private_key)
        issued = issue_challenge(user_id="user1", wallet_address=addr, chain_id=1, domain="test.finco.local")

        # Manually expire the challenge in DB
        conn = _db_mod.get_connection()
        past = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        conn.execute(
            "UPDATE wallet_challenges SET expires_at = ? WHERE nonce = ?",
            (past, issued["nonce"]),
        )
        conn.commit()
        conn.close()

        sig = sign_personal_message(issued["challenge_text"], kp.private_key)
        from app.protocol.wallet_auth import verify_challenge
        with pytest.raises(WalletVerifyError) as exc_info:
            verify_challenge(user_id="user1", wallet_address=addr, nonce=issued["nonce"], signature=sig)
        assert exc_info.value.reason_code == "CHALLENGE_EXPIRED"


# ────────────────────────────────────────────────────────────────────────────
# F. Cross-user wallet isolation
# ────────────────────────────────────────────────────────────────────────────

class TestCrossUserIsolation:
    """F. Challenge for user A cannot authenticate user B."""

    def test_cross_user_challenge_rejected(self, tmp_path, monkeypatch):
        monkeypatch.setenv("FINCO_DB_PATH", str(tmp_path / "test.db"))
        from app.protocol._evm_crypto import generate_keypair, sign_personal_message, private_key_to_address
        from app.protocol.wallet_auth import issue_challenge, verify_challenge, WalletVerifyError

        kpA = generate_keypair()
        addrA = private_key_to_address(kpA.private_key)

        # Issue challenge for user A
        issued = issue_challenge(user_id="userA", wallet_address=addrA, chain_id=1, domain="test.finco.local")
        sig = sign_personal_message(issued["challenge_text"], kpA.private_key)

        # User B tries to use user A's nonce
        with pytest.raises(WalletVerifyError) as exc_info:
            verify_challenge(
                user_id="userB",  # different user
                wallet_address=addrA,
                nonce=issued["nonce"],
                signature=sig,
            )
        assert exc_info.value.reason_code == "USER_MISMATCH"


# ────────────────────────────────────────────────────────────────────────────
# F2. Atomic nonce
# ────────────────────────────────────────────────────────────────────────────

class TestAtomicNonce:
    """FINCO_WALLET_NONCE_ATOMIC_SINGLE_USE, FINCO_WALLET_CONCURRENT_REPLAY_REJECTED,
    FINCO_WALLET_INVALID_SIGNATURE_CONSUMES_NONCE, FINCO_WALLET_EXPIRED_CHALLENGE_CONSUMES_NONCE."""

    def test_atomic_first_use_succeeds(self, tmp_path, monkeypatch):
        """FINCO_WALLET_NONCE_ATOMIC_SINGLE_USE — first use of a valid nonce succeeds."""
        monkeypatch.setenv("FINCO_DB_PATH", str(tmp_path / "test.db"))
        from app.protocol._evm_crypto import generate_keypair, sign_personal_message, private_key_to_address
        from app.protocol.wallet_auth import issue_challenge, verify_challenge

        kp = generate_keypair()
        addr = private_key_to_address(kp.private_key)
        issued = issue_challenge(user_id="u1", wallet_address=addr, chain_id=1, domain="test.local")
        sig = sign_personal_message(issued["challenge_text"], kp.private_key)
        result = verify_challenge(user_id="u1", wallet_address=addr, nonce=issued["nonce"], signature=sig)
        assert result.lower() == addr.lower()

    def test_atomic_replay_rejected(self, tmp_path, monkeypatch):
        """FINCO_WALLET_NONCE_ATOMIC_SINGLE_USE — second use of same nonce is rejected atomically."""
        monkeypatch.setenv("FINCO_DB_PATH", str(tmp_path / "test.db"))
        from app.protocol._evm_crypto import generate_keypair, sign_personal_message, private_key_to_address
        from app.protocol.wallet_auth import issue_challenge, verify_challenge, WalletVerifyError

        kp = generate_keypair()
        addr = private_key_to_address(kp.private_key)
        issued = issue_challenge(user_id="u1", wallet_address=addr, chain_id=1, domain="test.local")
        sig = sign_personal_message(issued["challenge_text"], kp.private_key)

        verify_challenge(user_id="u1", wallet_address=addr, nonce=issued["nonce"], signature=sig)
        with pytest.raises(WalletVerifyError) as exc_info:
            verify_challenge(user_id="u1", wallet_address=addr, nonce=issued["nonce"], signature=sig)
        assert exc_info.value.reason_code == "NONCE_ALREADY_USED"

    def test_invalid_signature_consumes_nonce(self, tmp_path, monkeypatch):
        """FINCO_WALLET_INVALID_SIGNATURE_CONSUMES_NONCE — bad sig → SIGNATURE_INVALID, then nonce is spent."""
        monkeypatch.setenv("FINCO_DB_PATH", str(tmp_path / "test.db"))
        from app.protocol._evm_crypto import generate_keypair, private_key_to_address
        from app.protocol.wallet_auth import issue_challenge, verify_challenge, WalletVerifyError

        kp = generate_keypair()
        addr = private_key_to_address(kp.private_key)
        issued = issue_challenge(user_id="u1", wallet_address=addr, chain_id=1, domain="test.local")

        # Use a signature that recovers to None (r=0, s=0)
        bad_sig = "0x" + "00" * 64 + "1b"
        with pytest.raises(WalletVerifyError) as exc_info:
            verify_challenge(user_id="u1", wallet_address=addr, nonce=issued["nonce"], signature=bad_sig)
        assert exc_info.value.reason_code in ("SIGNATURE_INVALID", "SIGNER_MISMATCH")

        # Nonce must now be spent — any second attempt raises NONCE_ALREADY_USED
        with pytest.raises(WalletVerifyError) as exc_info2:
            verify_challenge(user_id="u1", wallet_address=addr, nonce=issued["nonce"], signature=bad_sig)
        assert exc_info2.value.reason_code == "NONCE_ALREADY_USED"

    def test_expired_challenge_consumes_nonce(self, tmp_path, monkeypatch):
        """FINCO_WALLET_EXPIRED_CHALLENGE_CONSUMES_NONCE — expired challenge uses up nonce."""
        monkeypatch.setenv("FINCO_DB_PATH", str(tmp_path / "test.db"))
        from app.protocol._evm_crypto import generate_keypair, sign_personal_message, private_key_to_address
        from app.protocol.wallet_auth import issue_challenge, verify_challenge, WalletVerifyError
        import app.persistence.db as _db_mod

        kp = generate_keypair()
        addr = private_key_to_address(kp.private_key)
        issued = issue_challenge(user_id="u1", wallet_address=addr, chain_id=1, domain="test.local")

        # Manually expire the challenge
        conn = _db_mod.get_connection()
        past = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        conn.execute("UPDATE wallet_challenges SET expires_at = ? WHERE nonce = ?", (past, issued["nonce"]))
        conn.commit()
        conn.close()

        sig = sign_personal_message(issued["challenge_text"], kp.private_key)
        with pytest.raises(WalletVerifyError) as exc_info:
            verify_challenge(user_id="u1", wallet_address=addr, nonce=issued["nonce"], signature=sig)
        assert exc_info.value.reason_code == "CHALLENGE_EXPIRED"

        # Nonce must now be spent
        with pytest.raises(WalletVerifyError) as exc_info2:
            verify_challenge(user_id="u1", wallet_address=addr, nonce=issued["nonce"], signature=sig)
        assert exc_info2.value.reason_code == "NONCE_ALREADY_USED"

    def test_concurrent_replay_rejected(self, tmp_path, monkeypatch):
        """FINCO_WALLET_CONCURRENT_REPLAY_REJECTED — nonce pre-consumed (simulated race) → NONCE_ALREADY_USED."""
        monkeypatch.setenv("FINCO_DB_PATH", str(tmp_path / "test.db"))
        from app.protocol._evm_crypto import generate_keypair, sign_personal_message, private_key_to_address
        from app.protocol.wallet_auth import issue_challenge, verify_challenge, WalletVerifyError
        import app.persistence.db as _db_mod

        kp = generate_keypair()
        addr = private_key_to_address(kp.private_key)
        issued = issue_challenge(user_id="u1", wallet_address=addr, chain_id=1, domain="test.local")

        # Simulate concurrent consumer: mark nonce used=1 directly (race winner)
        conn = _db_mod.get_connection()
        conn.execute("UPDATE wallet_challenges SET used = 1 WHERE nonce = ?", (issued["nonce"],))
        conn.commit()
        conn.close()

        sig = sign_personal_message(issued["challenge_text"], kp.private_key)
        with pytest.raises(WalletVerifyError) as exc_info:
            verify_challenge(user_id="u1", wallet_address=addr, nonce=issued["nonce"], signature=sig)
        assert exc_info.value.reason_code == "NONCE_ALREADY_USED"


# ────────────────────────────────────────────────────────────────────────────
# G. Correct chain passes
# ────────────────────────────────────────────────────────────────────────────

class TestChainId:
    """G. Correct chain_id passes; H. Wrong chain_id → CHAIN_ID_MISMATCH."""

    def _make_config(self, chain_id: int = 1):
        from app.protocol.token_config import TokenConfig
        return TokenConfig(
            rpc_url="http://localhost:8545",
            chain_id=chain_id,
            token_address="0x" + "a" * 40,
            min_balance=Decimal("1"),
            decimals_override=18,
        )

    @pytest.mark.asyncio
    async def test_correct_chain_passes(self):
        config = self._make_config(chain_id=1)
        rpc_responses = {
            "eth_chainId": "0x1",      # 1
            "eth_call_decimals": hex(18),
            "eth_call_balance": hex(10 ** 18 * 5),  # 5 tokens
            "eth_blockNumber": "0x100",
        }

        async def mock_post(url, json=None, timeout=None):
            method = json["method"]
            resp = MagicMock()
            resp.raise_for_status = MagicMock()
            if method == "eth_chainId":
                resp.json.return_value = {"result": rpc_responses["eth_chainId"]}
            elif method == "eth_call":
                data = json["params"][0]["data"]
                if data.startswith("0x313ce567"):
                    resp.json.return_value = {"result": rpc_responses["eth_call_decimals"]}
                else:
                    resp.json.return_value = {"result": rpc_responses["eth_call_balance"]}
            elif method == "eth_blockNumber":
                resp.json.return_value = {"result": rpc_responses["eth_blockNumber"]}
            return resp

        with patch("httpx.AsyncClient") as mock_client_cls:
            instance = mock_client_cls.return_value.__aenter__.return_value
            instance.post = AsyncMock(side_effect=mock_post)

            from app.protocol.token_balance import read_token_balance
            obs = await read_token_balance("0x" + "b" * 40, config)

        from app.protocol.token_balance import STATUS_ENTITLED
        assert obs.status == STATUS_ENTITLED
        assert obs.chain_id == 1

    @pytest.mark.asyncio
    async def test_chain_id_mismatch(self):
        """H. Wrong chain_id → CHAIN_ID_MISMATCH."""
        config = self._make_config(chain_id=1)

        async def mock_post(url, json=None, timeout=None):
            resp = MagicMock()
            resp.raise_for_status = MagicMock()
            resp.json.return_value = {"result": "0x89"}  # polygon (137)
            return resp

        with patch("httpx.AsyncClient") as mock_client_cls:
            instance = mock_client_cls.return_value.__aenter__.return_value
            instance.post = AsyncMock(side_effect=mock_post)

            from app.protocol.token_balance import read_token_balance, STATUS_CHAIN_ID_MISMATCH
            obs = await read_token_balance("0x" + "b" * 40, config)

        assert obs.status == STATUS_CHAIN_ID_MISMATCH


# ────────────────────────────────────────────────────────────────────────────
# I. Balance read — mock RPC, correct normalized balance
# ────────────────────────────────────────────────────────────────────────────

class TestBalanceRead:
    """I. Mock RPC returns correct normalized balance."""

    def _make_config(self, min_balance=Decimal("1"), decimals_override=18):
        from app.protocol.token_config import TokenConfig
        return TokenConfig(
            rpc_url="http://localhost:8545",
            chain_id=1,
            token_address="0x" + "a" * 40,
            min_balance=min_balance,
            decimals_override=decimals_override,
        )

    @pytest.mark.asyncio
    async def test_balance_normalized_18_decimals(self):
        """J. 18 decimals — 5 * 10^18 raw → 5.0 normalized."""
        raw_balance = 5 * (10 ** 18)
        config = self._make_config(min_balance=Decimal("1"), decimals_override=18)

        async def mock_post(url, json=None, timeout=None):
            resp = MagicMock()
            resp.raise_for_status = MagicMock()
            method = json["method"]
            if method == "eth_chainId":
                resp.json.return_value = {"result": "0x1"}
            elif method == "eth_call":
                resp.json.return_value = {"result": hex(raw_balance)}
            elif method == "eth_blockNumber":
                resp.json.return_value = {"result": "0x1"}
            return resp

        with patch("httpx.AsyncClient") as mock_client_cls:
            instance = mock_client_cls.return_value.__aenter__.return_value
            instance.post = AsyncMock(side_effect=mock_post)

            from app.protocol.token_balance import read_token_balance
            obs = await read_token_balance("0x" + "c" * 40, config)

        assert obs.normalized_balance == Decimal("5")
        assert obs.decimals == 18

    @pytest.mark.asyncio
    async def test_balance_normalized_6_decimals(self):
        """J. 6 decimals (USDC-like) — 1_000_000 raw → 1.0 normalized."""
        raw_balance = 1_000_000
        config = self._make_config(min_balance=Decimal("1"), decimals_override=6)

        async def mock_post(url, json=None, timeout=None):
            resp = MagicMock()
            resp.raise_for_status = MagicMock()
            method = json["method"]
            if method == "eth_chainId":
                resp.json.return_value = {"result": "0x1"}
            elif method == "eth_call":
                resp.json.return_value = {"result": hex(raw_balance)}
            elif method == "eth_blockNumber":
                resp.json.return_value = {"result": "0x1"}
            return resp

        with patch("httpx.AsyncClient") as mock_client_cls:
            instance = mock_client_cls.return_value.__aenter__.return_value
            instance.post = AsyncMock(side_effect=mock_post)

            from app.protocol.token_balance import read_token_balance
            obs = await read_token_balance("0x" + "d" * 40, config)

        assert obs.normalized_balance == Decimal("1")
        assert obs.decimals == 6


# ────────────────────────────────────────────────────────────────────────────
# K. RPC failure → OBSERVATION_UNAVAILABLE (not zero)
# ────────────────────────────────────────────────────────────────────────────

class TestRpcFailure:
    """K. RPC failure → OBSERVATION_UNAVAILABLE, not zero balance."""

    @pytest.mark.asyncio
    async def test_rpc_network_error(self):
        from app.protocol.token_config import TokenConfig
        config = TokenConfig(
            rpc_url="http://nonexistent.local:8545",
            chain_id=1,
            token_address="0x" + "a" * 40,
            min_balance=Decimal("1"),
            decimals_override=18,
        )

        import httpx

        async def mock_post(*args, **kwargs):
            raise httpx.ConnectError("Connection refused")

        with patch("httpx.AsyncClient") as mock_client_cls:
            instance = mock_client_cls.return_value.__aenter__.return_value
            instance.post = AsyncMock(side_effect=mock_post)

            from app.protocol.token_balance import read_token_balance, STATUS_RPC_UNAVAILABLE
            obs = await read_token_balance("0x" + "b" * 40, config)

        assert obs.status == STATUS_RPC_UNAVAILABLE
        # Must NOT silently convert to zero balance
        assert obs.balance_raw is None
        assert obs.normalized_balance is None


# ────────────────────────────────────────────────────────────────────────────
# L. Insufficient balance → INSUFFICIENT_BALANCE, allowed=False
# M. Entitled balance → ENTITLED, allowed=True
# ────────────────────────────────────────────────────────────────────────────

class TestAccessDecision:
    """L, M. Balance threshold decision."""

    def _obs(self, balance: Decimal, status: str):
        from app.protocol.token_balance import TokenObservation
        return TokenObservation(
            wallet_address="0x" + "a" * 40,
            chain_id=1,
            token_address="0x" + "b" * 40,
            balance_raw=int(balance * 10 ** 18),
            decimals=18,
            normalized_balance=balance,
            block_number=1000,
            observed_at=datetime.now(timezone.utc),
            status=status,
        )

    def _config(self, min_balance=Decimal("10")):
        from app.protocol.token_config import TokenConfig
        return TokenConfig(
            rpc_url="http://localhost:8545",
            chain_id=1,
            token_address="0x" + "b" * 40,
            min_balance=min_balance,
            decimals_override=18,
        )

    def test_insufficient_balance(self):
        """L. Balance below minimum → INSUFFICIENT_BALANCE, allowed=False."""
        from app.protocol.token_balance import STATUS_INSUFFICIENT
        from app.protocol.access_decision import get_access_decision
        from app.protocol.utility_registry import FINCO_COMPUTE

        obs = self._obs(Decimal("5"), STATUS_INSUFFICIENT)
        config = self._config(min_balance=Decimal("10"))
        dec = get_access_decision(FINCO_COMPUTE, "0x" + "a" * 40, config, obs)

        assert dec.status == "INSUFFICIENT_BALANCE"
        assert dec.allowed is False

    def test_entitled_balance(self):
        """M. Balance >= minimum → ENTITLED, allowed=True."""
        from app.protocol.token_balance import STATUS_ENTITLED
        from app.protocol.access_decision import get_access_decision
        from app.protocol.utility_registry import FINCO_COMPUTE

        obs = self._obs(Decimal("100"), STATUS_ENTITLED)
        config = self._config(min_balance=Decimal("10"))
        dec = get_access_decision(FINCO_COMPUTE, "0x" + "a" * 40, config, obs)

        assert dec.status == "ENTITLED"
        assert dec.allowed is True


# ────────────────────────────────────────────────────────────────────────────
# N. No hardcoded threshold — config missing min_balance → NOT_CONFIGURED
# ────────────────────────────────────────────────────────────────────────────

class TestNoHardcodedThreshold:
    """N. Missing min_balance env var → NOT_CONFIGURED (never a magic default)."""

    def test_missing_min_balance_is_not_configured(self, monkeypatch):
        monkeypatch.delenv("FINCO_ACCESS_MIN_BALANCE", raising=False)
        monkeypatch.setenv("FINCO_TOKEN_RPC_URL", "http://localhost:8545")
        monkeypatch.setenv("FINCO_TOKEN_CHAIN_ID", "1")
        monkeypatch.setenv("FINCO_TOKEN_ADDRESS", "0x" + "a" * 40)

        from importlib import reload
        import app.protocol.token_config as _tc
        reload(_tc)

        config = _tc.get_token_config()
        assert config is None

    def test_missing_rpc_url_is_not_configured(self, monkeypatch):
        monkeypatch.delenv("FINCO_TOKEN_RPC_URL", raising=False)
        monkeypatch.setenv("FINCO_TOKEN_CHAIN_ID", "1")
        monkeypatch.setenv("FINCO_TOKEN_ADDRESS", "0x" + "a" * 40)
        monkeypatch.setenv("FINCO_ACCESS_MIN_BALANCE", "1")

        from importlib import reload
        import app.protocol.token_config as _tc
        reload(_tc)

        config = _tc.get_token_config()
        assert config is None

    def test_not_configured_decision(self):
        """N. config=None → NOT_CONFIGURED, allowed=False."""
        from app.protocol.access_decision import get_access_decision
        from app.protocol.utility_registry import FINCO_INTELLIGENCE

        dec = get_access_decision(FINCO_INTELLIGENCE, "0x" + "a" * 40, None, None)
        assert dec.status == "NOT_CONFIGURED"
        assert dec.allowed is False


# ────────────────────────────────────────────────────────────────────────────
# O. JSON API — 200 with schema, 401 unauthenticated
# ────────────────────────────────────────────────────────────────────────────

class TestJsonApi:
    """O. JSON API — 200 with schema when authenticated, 401 when not."""

    def test_unauthenticated_returns_401(self):
        from fastapi.testclient import TestClient
        from fastapi import FastAPI
        app_test = FastAPI()
        from app.protocol.router import router
        app_test.include_router(router)

        client = TestClient(app_test, raise_server_exceptions=True)
        # No session cookie → should return 401
        resp = client.get("/protocol/finco/access.json")
        assert resp.status_code == 401

    def test_authenticated_returns_schema(self, tmp_path, monkeypatch):
        """Authenticated user gets schema response."""
        monkeypatch.setenv("FINCO_DB_PATH", str(tmp_path / "test.db"))
        monkeypatch.delenv("FINCO_TOKEN_RPC_URL", raising=False)

        from fastapi.testclient import TestClient
        from fastapi import FastAPI
        app_test = FastAPI()
        from app.protocol.router import router
        app_test.include_router(router)

        from app.auth import create_session_token, COOKIE_NAME

        client = TestClient(app_test, raise_server_exceptions=False)
        token = create_session_token()
        resp = client.get(
            "/protocol/finco/access.json",
            cookies={COOKIE_NAME: token},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["schema"] == "FINCO_PROTOCOL_ACCESS_V1"
        assert "wallet" in data
        assert "token_observation" in data
        assert "utilities" in data
        # All 3 utilities present
        from app.protocol.utility_registry import FINCO_COMPUTE, FINCO_VERIFY_PUBLISH, FINCO_INTELLIGENCE
        assert FINCO_COMPUTE in data["utilities"]
        assert FINCO_VERIFY_PUBLISH in data["utilities"]
        assert FINCO_INTELLIGENCE in data["utilities"]


# ────────────────────────────────────────────────────────────────────────────
# Q. No sensitive data leakage — RPC URL not in JSON response
# ────────────────────────────────────────────────────────────────────────────

class TestNoSensitiveLeakage:
    """Q. RPC URL never appears in JSON API response."""

    def test_rpc_url_not_in_response(self, tmp_path, monkeypatch):
        monkeypatch.setenv("FINCO_DB_PATH", str(tmp_path / "test.db"))
        monkeypatch.setenv("FINCO_TOKEN_RPC_URL", "http://super-secret-rpc.internal:8545")
        monkeypatch.setenv("FINCO_TOKEN_CHAIN_ID", "1")
        monkeypatch.setenv("FINCO_TOKEN_ADDRESS", "0x" + "a" * 40)
        monkeypatch.setenv("FINCO_ACCESS_MIN_BALANCE", "1")

        from fastapi.testclient import TestClient
        from fastapi import FastAPI
        app_test = FastAPI()
        from app.protocol.router import router
        app_test.include_router(router)

        from app.auth import create_session_token, COOKIE_NAME
        client = TestClient(app_test, raise_server_exceptions=False)
        token = create_session_token()

        # Mock out balance read at the httpx level to avoid actual RPC call
        async def _mock_read_balance(wallet_address, config):
            from app.protocol.token_balance import TokenObservation, STATUS_RPC_UNAVAILABLE
            from datetime import datetime, timezone
            return TokenObservation(
                wallet_address=wallet_address,
                chain_id=config.chain_id,
                token_address=config.token_address,
                balance_raw=None,
                decimals=None,
                normalized_balance=None,
                block_number=None,
                observed_at=datetime.now(timezone.utc),
                status=STATUS_RPC_UNAVAILABLE,
            )

        with patch("app.protocol.token_balance.read_token_balance", side_effect=_mock_read_balance):
            resp = client.get(
                "/protocol/finco/access.json",
                cookies={COOKIE_NAME: token},
            )

        assert resp.status_code == 200
        raw = resp.text
        assert "super-secret-rpc" not in raw
        assert "8545" not in raw


# ────────────────────────────────────────────────────────────────────────────
# R. Model mathematical independence
# ────────────────────────────────────────────────────────────────────────────

class TestModelIndependence:
    """R. FINCO_TOKEN_NEVER_CHANGES_MODEL_MATH — run_project() outputs identical regardless of P4 access state."""

    def test_financial_engine_unchanged(self):
        """financial_engine module must be importable and unaffected."""
        import financial_engine  # must not raise

    def test_finco_core_unchanged(self):
        """finco_core module must be importable and unaffected."""
        import finco_core  # must not raise

    def test_model_math_independent_of_p4_access(self, tmp_path, monkeypatch):
        """FINCO_TOKEN_NEVER_CHANGES_MODEL_MATH — run_project() outputs are identical whether P4 token
        config is absent (NOT_CONFIGURED) or fully set (ENTITLED). The financial engine never reads
        FINCO_TOKEN_* env vars or any P4 access layer."""
        monkeypatch.setenv("FINCO_DB_PATH", str(tmp_path / "test.db"))
        for key in ("FINCO_TOKEN_RPC_URL", "FINCO_TOKEN_CHAIN_ID", "FINCO_TOKEN_ADDRESS", "FINCO_ACCESS_MIN_BALANCE"):
            monkeypatch.delenv(key, raising=False)

        from app.services.project_library_service import ensure_reference_models
        from app.api.project_runner import run_project
        ensure_reference_models()

        # Run 1: P4 NOT_CONFIGURED state (no token env vars)
        payload1 = run_project("Generic Solar Reference", "Base")
        irr1 = payload1["kpis"]["project_irr"]
        dscr1 = payload1["kpis"]["min_dscr"]
        debt1 = payload1["kpis"].get("senior_debt_keur")

        # Run 2: P4 ENTITLED state (all token env vars set)
        monkeypatch.setenv("FINCO_TOKEN_RPC_URL", "http://rpc.test.local:8545")
        monkeypatch.setenv("FINCO_TOKEN_CHAIN_ID", "1")
        monkeypatch.setenv("FINCO_TOKEN_ADDRESS", "0x" + "a" * 40)
        monkeypatch.setenv("FINCO_ACCESS_MIN_BALANCE", "1")

        payload2 = run_project("Generic Solar Reference", "Base")
        irr2 = payload2["kpis"]["project_irr"]
        dscr2 = payload2["kpis"]["min_dscr"]
        debt2 = payload2["kpis"].get("senior_debt_keur")

        # Model outputs must be identical — P4 token config has zero effect on math
        assert irr1 == irr2, f"project_irr changed with P4 token config: {irr1} → {irr2}"
        assert dscr1 == dscr2, f"min_dscr changed with P4 token config: {dscr1} → {dscr2}"
        assert debt1 == debt2, f"senior_debt_keur changed with P4 token config: {debt1} → {debt2}"


# ────────────────────────────────────────────────────────────────────────────
# S. Run Certificate independence
# ────────────────────────────────────────────────────────────────────────────

class TestCertificateIndependence:
    """S. FINCO_TOKEN_NEVER_CHANGES_RUN_CERTIFICATE — cert digests identical regardless of wallet state."""

    def test_run_certificate_module_importable(self):
        try:
            from app.verify.run_certificate import build_run_certificate
        except ModuleNotFoundError:
            pytest.skip("app.verify not on this branch — P3 not yet merged to main")

    def test_cert_builder_has_no_wallet_param(self):
        import inspect
        try:
            from app.verify.run_certificate import build_run_certificate
        except ModuleNotFoundError:
            pytest.skip("app.verify not on this branch — P3 not yet merged to main")
        sig = inspect.signature(build_run_certificate)
        param_names = list(sig.parameters.keys())
        assert "wallet" not in param_names
        assert "wallet_address" not in param_names
        assert "balance" not in param_names

    def test_cert_digests_independent_of_wallet_state(self, tmp_path, monkeypatch):
        """FINCO_TOKEN_NEVER_CHANGES_RUN_CERTIFICATE — building a cert before and after adding a wallet
        binding produces identical composite_hash, assumptions_sha256, outputs_sha256,
        certificate_digest_sha256, certificate_id and engine_version."""
        monkeypatch.setenv("FINCO_DB_PATH", str(tmp_path / "test.db"))
        try:
            from app.verify.run_certificate import build_run_certificate
        except ModuleNotFoundError:
            pytest.skip("app.verify not on this branch — P3 not yet merged to main")

        from app.services.project_library_service import ensure_reference_models, ensure_reference_canonical_last_runs
        from app.persistence.projects_repository import get_reference_by_template_source
        from app.persistence.workspace_repository import get_workspace_state

        ensure_reference_models()
        ensure_reference_canonical_last_runs()
        record = get_reference_by_template_source("generic_solar_reference")
        assert record is not None
        ws = get_workspace_state(record.user_id, record.project_id)
        assert ws is not None

        # Cert 1: no wallet binding
        cert1 = build_run_certificate(ws, record)

        # Add wallet binding (simulates P4 ENTITLED state)
        from app.protocol.wallet_auth import _ensure_wallet_table
        from app.persistence.db import get_connection
        conn = get_connection()
        _ensure_wallet_table(conn)
        conn.execute(
            "INSERT OR REPLACE INTO user_wallets (user_id, wallet_address, verified_at) VALUES (?, ?, ?)",
            (record.user_id, "0x" + "b" * 40, "2026-01-01T00:00:00+00:00"),
        )
        conn.commit()
        conn.close()

        # Cert 2: wallet binding present — workspace state unchanged, cert must be identical
        ws2 = get_workspace_state(record.user_id, record.project_id)
        cert2 = build_run_certificate(ws2, record)

        assert cert1["certificate_id"] == cert2["certificate_id"]
        assert cert1["identity"]["composite_hash"] == cert2["identity"]["composite_hash"]
        assert cert1["identity"]["assumptions_sha256"] == cert2["identity"]["assumptions_sha256"]
        assert cert1["identity"]["outputs_sha256"] == cert2["identity"]["outputs_sha256"]
        assert cert1["certificate_digest_sha256"] == cert2["certificate_digest_sha256"]
        assert cert1["model"]["engine_version"] == cert2["model"]["engine_version"]


# ────────────────────────────────────────────────────────────────────────────
# T. Radar economic independence
# ────────────────────────────────────────────────────────────────────────────

class TestRadarIndependence:
    """T. FINCO_TOKEN_NEVER_CHANGES_RADAR_ECONOMICS — tokenization premium identical regardless of P4 access state."""

    def test_tokenization_premium_module_no_wallet_import(self):
        """finco_radar tokenization_premium must not import wallet or access_decision."""
        import os
        radar_prem_dir = os.path.join(
            os.path.dirname(os.path.dirname(__file__)),
            "finco_radar", "tokenization_premium"
        )
        if not os.path.isdir(radar_prem_dir):
            pytest.skip("finco_radar/tokenization_premium not found — skipping")

        for fname in os.listdir(radar_prem_dir):
            if not fname.endswith(".py"):
                continue
            fpath = os.path.join(radar_prem_dir, fname)
            with open(fpath) as f:
                source = f.read()
            assert "wallet_auth" not in source, f"{fname} imports wallet_auth"
            assert "access_decision" not in source, f"{fname} imports access_decision"

    def test_radar_economics_independent_of_p4_access(self, monkeypatch):
        """FINCO_TOKEN_NEVER_CHANGES_RADAR_ECONOMICS — compute_tokenization_premium() returns identical
        observation before and after P4 entitlement state change. The radar engine accepts no wallet
        or access-decision arguments."""
        import os
        radar_prem_dir = os.path.join(
            os.path.dirname(os.path.dirname(__file__)),
            "finco_radar", "tokenization_premium"
        )
        if not os.path.isdir(radar_prem_dir):
            pytest.skip("finco_radar/tokenization_premium not found — skipping")

        from finco_radar.tokenization_premium.engine import compute_tokenization_premium
        from finco_radar.tokenization_premium.contracts import (
            TokenizationPremiumPolicy, ComplementIdentityStatus
        )

        now_iso = datetime.now(timezone.utc).isoformat()

        # Deterministic fixture: rawBid=9.00, rawAsk=11.00, multiplier=1, price=10.00
        # underlying_mid = (9+11)/2 = 10; recomputed_basis = 10*1 = 10 = price → lineage OK
        ref_evidence = {
            "available": True,
            "isTradingHalt": False,
            "price": "10.00",
            "rawBid": "9.00",
            "rawAsk": "11.00",
            "currentMultiplier": "1",
            "observedAt": now_iso,
        }
        buy_exec = {"available": True, "effectivePrice": "10.50", "quotedAt": now_iso}
        sell_exec = {"available": True, "effectivePrice": "9.50", "quotedAt": now_iso}
        policy = TokenizationPremiumPolicy(max_evidence_skew_seconds=300)

        # Observation 1: P4 NOT_CONFIGURED (no token env vars)
        for key in ("FINCO_TOKEN_RPC_URL", "FINCO_TOKEN_CHAIN_ID", "FINCO_TOKEN_ADDRESS", "FINCO_ACCESS_MIN_BALANCE"):
            monkeypatch.delenv(key, raising=False)
        obs1 = compute_tokenization_premium(
            reference_evidence=ref_evidence,
            buy_exec_evidence=buy_exec,
            sell_exec_evidence=sell_exec,
            policy=policy,
            complement_identity_status=ComplementIdentityStatus.MATCHED,
        )

        # Observation 2: P4 ENTITLED (all token env vars set)
        monkeypatch.setenv("FINCO_TOKEN_RPC_URL", "http://rpc.test.local:8545")
        monkeypatch.setenv("FINCO_TOKEN_CHAIN_ID", "1")
        monkeypatch.setenv("FINCO_TOKEN_ADDRESS", "0x" + "a" * 40)
        monkeypatch.setenv("FINCO_ACCESS_MIN_BALANCE", "1")
        obs2 = compute_tokenization_premium(
            reference_evidence=ref_evidence,
            buy_exec_evidence=buy_exec,
            sell_exec_evidence=sell_exec,
            policy=policy,
            complement_identity_status=ComplementIdentityStatus.MATCHED,
        )

        # All fields must be identical — P4 token state has zero effect on radar economics
        assert obs1.status == obs2.status
        assert obs1.tokenization_premium_bps == obs2.tokenization_premium_bps
        assert obs1.underlying_token_basis_usd_per_token == obs2.underlying_token_basis_usd_per_token
        assert obs1.buy_execution_premium_bps == obs2.buy_execution_premium_bps
        assert obs1.sell_execution_premium_bps == obs2.sell_execution_premium_bps


# ────────────────────────────────────────────────────────────────────────────
# Correction A tests — new tests added by P4 Correction A
# ────────────────────────────────────────────────────────────────────────────

class TestCorrectionA_StandardLibrary:
    """FINCO_WALLET_NO_HANDROLLED_CRYPTO, FINCO_WALLET_STANDARD_EIP191_LIBRARY."""

    def test_evm_crypto_uses_eth_account(self):
        """_evm_crypto must delegate to eth_account, not contain custom Keccak/EC code."""
        import inspect
        import app.protocol._evm_crypto as mod
        src = inspect.getsource(mod)
        assert "eth_account" in src
        assert "encode_defunct" in src or "eth_account.messages" in src

    def test_recover_uses_eth_account_recover_message(self):
        """recover_eip191_signer must be backed by eth_account.Account.recover_message."""
        import inspect
        import app.protocol._evm_crypto as mod
        src = inspect.getsource(mod.recover_eip191_signer)
        assert "Account.recover_message" in src or "recover_message" in src

    def test_malformed_signature_returns_none(self):
        """FINCO_WALLET_MALFORMED_SIGNATURE_FAILS_CLOSED — bad sig → None, not exception."""
        from app.protocol._evm_crypto import recover_eip191_signer
        assert recover_eip191_signer("test", "0xdeadbeef") is None
        assert recover_eip191_signer("test", "not_hex") is None
        assert recover_eip191_signer("test", "") is None
        assert recover_eip191_signer("test", "0x" + "00" * 64) is None  # 64 bytes, not 65

    def test_invalid_rs_bounds_fails_closed(self):
        """FINCO_WALLET_INVALID_RS_BOUNDS_REJECTED — r=0 or s=0 sig returns None."""
        from app.protocol._evm_crypto import recover_eip191_signer
        # r=0, s=0, v=27 — invalid signature
        invalid = "0x" + "00" * 64 + "1b"
        result = recover_eip191_signer("test message", invalid)
        assert result is None

    def test_sign_recover_roundtrip_via_eth_account(self):
        """Full sign-then-recover roundtrip using eth_account-backed helpers."""
        from app.protocol._evm_crypto import (
            generate_keypair, sign_personal_message, recover_eip191_signer,
            private_key_to_address,
        )
        kp = generate_keypair()
        addr = private_key_to_address(kp.private_key)
        msg = "Correction A roundtrip test"
        sig = sign_personal_message(msg, kp.private_key)
        recovered = recover_eip191_signer(msg, sig)
        assert recovered is not None
        assert recovered.lower() == addr.lower()

    def test_keccak256_known_vector(self):
        """keccak256('') must equal known Ethereum vector — now via eth_utils."""
        from app.protocol._evm_crypto import keccak256
        result = keccak256(b"")
        assert result.hex() == "c5d2460186f7233c927e7db2dcc703c0e500b653ca82273b7bfad8045d85a470"


class TestCorrectionB_NoChallengeChainDefault:
    """FINCO_WALLET_CHALLENGE_NOT_CONFIGURED_FAILS_CLOSED, FINCO_TOKEN_NO_HARDCODED_CHAIN."""

    def test_challenge_not_configured_returns_503(self, tmp_path, monkeypatch):
        """Challenge endpoint returns NOT_CONFIGURED (503) when token config is absent."""
        monkeypatch.setenv("FINCO_DB_PATH", str(tmp_path / "test.db"))
        monkeypatch.delenv("FINCO_TOKEN_RPC_URL", raising=False)
        monkeypatch.delenv("FINCO_TOKEN_CHAIN_ID", raising=False)
        monkeypatch.delenv("FINCO_TOKEN_ADDRESS", raising=False)
        monkeypatch.delenv("FINCO_ACCESS_MIN_BALANCE", raising=False)
        monkeypatch.delenv("FINCO_APP_DOMAIN", raising=False)

        import main_web
        from starlette.testclient import TestClient
        from app.auth import create_demo_session_token, new_demo_user_id
        client = TestClient(main_web.app, raise_server_exceptions=False)
        token = create_demo_session_token(new_demo_user_id())
        client.cookies.set("finco_demo", token)

        resp = client.post(
            "/protocol/finco/wallet/challenge",
            json={"wallet_address": "0x" + "a" * 40},
        )
        assert resp.status_code == 503
        data = resp.json()
        assert data.get("code") == "NOT_CONFIGURED"

    def test_router_no_hardcoded_chain_1(self):
        """router.py must NOT contain the literal fallback 'chain_id = config.chain_id if config else 1'."""
        import os
        router_path = os.path.join(
            os.path.dirname(os.path.dirname(__file__)),
            "app", "protocol", "router.py"
        )
        with open(router_path) as f:
            src = f.read()
        assert "else 1" not in src, "Hardcoded chain_id fallback to 1 found in router.py"
        assert "chain_id if config else 1" not in src, "Hardcoded chain_id fallback to 1 found"


class TestCorrectionD_TrustedDomain:
    """FINCO_WALLET_DOMAIN_TRUSTED_AUTHORITY."""

    def test_domain_not_from_host_header(self):
        """_get_trusted_domain must not read from request Host header."""
        import inspect
        import app.protocol.router as router_mod
        src = inspect.getsource(router_mod._get_trusted_domain)
        assert "request" not in src
        assert "headers" not in src
        assert "host" not in src.lower() or "FINCO_APP_DOMAIN" in src

    def test_domain_from_env_var(self, monkeypatch):
        """FINCO_APP_DOMAIN env var is the domain authority."""
        monkeypatch.setenv("FINCO_APP_DOMAIN", "test.fincoprotocol.com")
        from app.protocol.router import _get_trusted_domain
        domain = _get_trusted_domain()
        assert domain == "test.fincoprotocol.com"

    def test_domain_none_when_not_set(self, monkeypatch):
        """_get_trusted_domain returns None when FINCO_APP_DOMAIN is absent."""
        monkeypatch.delenv("FINCO_APP_DOMAIN", raising=False)
        from app.protocol.router import _get_trusted_domain
        domain = _get_trusted_domain()
        assert domain is None

    def test_challenge_not_configured_when_domain_missing(self, tmp_path, monkeypatch):
        """Challenge endpoint returns NOT_CONFIGURED when FINCO_APP_DOMAIN is absent."""
        monkeypatch.setenv("FINCO_DB_PATH", str(tmp_path / "test.db"))
        monkeypatch.setenv("FINCO_TOKEN_RPC_URL", "http://localhost:8545")
        monkeypatch.setenv("FINCO_TOKEN_CHAIN_ID", "1")
        monkeypatch.setenv("FINCO_TOKEN_ADDRESS", "0x" + "a" * 40)
        monkeypatch.setenv("FINCO_ACCESS_MIN_BALANCE", "1")
        monkeypatch.delenv("FINCO_APP_DOMAIN", raising=False)

        import main_web
        from starlette.testclient import TestClient
        from app.auth import create_demo_session_token, new_demo_user_id
        client = TestClient(main_web.app, raise_server_exceptions=False)
        token = create_demo_session_token(new_demo_user_id())
        client.cookies.set("finco_demo", token)

        resp = client.post(
            "/protocol/finco/wallet/challenge",
            json={"wallet_address": "0x" + "a" * 40},
        )
        assert resp.status_code == 503
        assert resp.json().get("code") == "NOT_CONFIGURED"
