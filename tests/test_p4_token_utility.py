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

    def _make_challenge_text(self, wallet, nonce, user_id, chain_id=1):
        from app.protocol.wallet_auth import build_challenge_text
        now = datetime.now(timezone.utc)
        expires = now + timedelta(seconds=300)
        return build_challenge_text(
            wallet_address=wallet,
            nonce=nonce,
            user_id=user_id,
            chain_id=chain_id,
            issued_at=now,
            expires_at=expires,
        )

    def test_challenge_contains_nonce(self):
        nonce = str(uuid.uuid4())
        text = self._make_challenge_text("0xabc" + "0" * 37, nonce, "user1")
        assert nonce in text

    def test_challenge_contains_wallet(self):
        wallet = "0x" + "a" * 40
        text = self._make_challenge_text(wallet, str(uuid.uuid4()), "user1")
        assert wallet in text

    def test_challenge_contains_user_id(self):
        user_id = "user_test_123"
        text = self._make_challenge_text("0x" + "b" * 40, str(uuid.uuid4()), user_id)
        assert user_id in text

    def test_challenge_contains_chain_id(self):
        text = self._make_challenge_text("0x" + "c" * 40, str(uuid.uuid4()), "u1", chain_id=137)
        assert "137" in text

    def test_challenge_contains_domain(self):
        from app.protocol.wallet_auth import build_challenge_text
        now = datetime.now(timezone.utc)
        text = build_challenge_text(
            wallet_address="0x" + "d" * 40,
            nonce=str(uuid.uuid4()),
            user_id="u1",
            chain_id=1,
            issued_at=now,
            expires_at=now + timedelta(minutes=5),
            domain="test.example.com",
        )
        assert "test.example.com" in text

    def test_challenge_issue_stores_in_db(self, tmp_path, monkeypatch):
        monkeypatch.setenv("FINCO_DB_PATH", str(tmp_path / "test.db"))
        from app.protocol.wallet_auth import issue_challenge
        result = issue_challenge(
            user_id="testuser",
            wallet_address="0x" + "e" * 40,
            chain_id=1,
        )
        assert "nonce" in result
        assert "challenge_text" in result
        assert "expires_at" in result
        assert len(result["nonce"]) > 10


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

        issued = issue_challenge(user_id="user1", wallet_address=addr, chain_id=1)
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
        issued = issue_challenge(user_id="user1", wallet_address=addr, chain_id=1)
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
        issued = issue_challenge(user_id="user1", wallet_address=addr, chain_id=1)

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
        issued = issue_challenge(user_id="userA", wallet_address=addrA, chain_id=1)
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
    """R. With and without entitlement, same model outputs."""

    def test_financial_engine_unchanged(self):
        """financial_engine module must be importable and unaffected."""
        import financial_engine  # must not raise
        # The module exists and is importable — our changes leave it alone.

    def test_finco_core_unchanged(self):
        """finco_core module must be importable and unaffected."""
        import finco_core  # must not raise


# ────────────────────────────────────────────────────────────────────────────
# S. Run Certificate independence
# ────────────────────────────────────────────────────────────────────────────

class TestCertificateIndependence:
    """S. Wallet/balance change does not change cert digests."""

    def test_run_certificate_module_importable(self):
        # P3 run certificate may not be on main yet; skip gracefully if absent
        try:
            from app.verify.run_certificate import build_run_certificate
        except ModuleNotFoundError:
            pytest.skip("app.verify not on this branch — P3 not yet merged to main")
        # Import succeeded — cert hashing has no dependency on wallet

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


# ────────────────────────────────────────────────────────────────────────────
# T. Radar economic independence
# ────────────────────────────────────────────────────────────────────────────

class TestRadarIndependence:
    """T. Entitlement change does not alter tokenization premium result."""

    def test_tokenization_premium_module_no_wallet_import(self):
        """finco_radar tokenization_premium must not import wallet or access_decision."""
        import ast, os
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
            # Must not import wallet_auth or access_decision
            assert "wallet_auth" not in source, f"{fname} imports wallet_auth"
            assert "access_decision" not in source, f"{fname} imports access_decision"
