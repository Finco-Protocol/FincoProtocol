"""Crypto Access Integration V1 — canonical entitlement extended to Tokenized Markets and the crypto API.

No second entitlement system exists: every decision below flows through
``app.protocol.entitlement_evaluator.evaluate_resource_access``. Amounts, addresses and chain ids are TEST_ONLY.
"""
from __future__ import annotations

import asyncio
import json
import re
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest

import app.crypto_resource_access as cra
import app.verified.token_entitlement as canon
from app.crypto_api_access import api_denial_payload, resolve_api_access
from app.crypto_resource_access import CryptoAccessState as S, from_resource_decision, map_deny_reason
from app.protocol import entitlement_policy as ep
from app.protocol.entitlement_evaluator import (
    FRESHNESS_ENV, Decision, WalletContext, evaluate_resource_access,
)
from app.protocol.token_deployments import ResolutionStatus, resolve_approved_deployment
from app.tokenized_access import TokenizedResource as R, denial_payload, resolve_tokenized_access
from app.verified.token_entitlement import ApprovedFincoDeployment, BalanceEvidenceState, TokenBalanceEvidence

ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 10, 3, 12, 0, tzinfo=timezone.utc)
CHAIN = 31337
TOKEN, OTHER_TOKEN = "0x" + "ab" * 20, "0x" + "cd" * 20
WALLET, OTHER_WALLET = "0x" + "12" * 20, "0x" + "99" * 20
DECIMALS = 6
THRESHOLD = Decimal("100")                 # TEST_ONLY — never a production value
RAW = 100 * 10 ** DECIMALS
ENV = {FRESHNESS_ENV: "60"}
VERIFIED = WalletContext(WALLET, True, "user-1")
HOLDERS = (R.HISTORY, R.DISLOCATION)


def approved():
    return ApprovedFincoDeployment(chain_id=CHAIN, token_address=TOKEN, standard="ERC-20", decimals=DECIMALS,
                                   provenance="TEST_ONLY fixture")


def policies(*, enabled=True, minimum=THRESHOLD, gating=True):
    table = ep.default_policies()
    for key, policy in list(table.items()):
        if policy.access_mode is ep.AccessMode.FINCO_HOLDER:
            table[key] = ep.EntitlementPolicy(key, ep.AccessMode.FINCO_HOLDER, minimum, True, enabled)
    return ep.PolicySet(table, gating_enabled=gating)


def evidence(raw=RAW, *, state=BalanceEvidenceState.AVAILABLE, age=0, **kw):
    base = dict(chain_id=CHAIN, token_address=TOKEN, wallet_address=WALLET, token_decimals=DECIMALS,
                balance_raw=None if state is not BalanceEvidenceState.AVAILABLE else raw,
                observed_at=NOW - timedelta(seconds=age), source="TEST_ONLY", state=state,
                reason=None if state is BalanceEvidenceState.AVAILABLE else "RPC_UNAVAILABLE")
    base.update(kw)
    return TokenBalanceEvidence(**base)


class FakeProvider:
    def __init__(self, value=None):
        self.value, self.calls = value if value is not None else evidence(), []

    async def balance_of(self, policy, wallet_address):
        self.calls.append((policy.chain_id, policy.token_address, wallet_address))
        return self.value


@pytest.fixture()
def session(monkeypatch):
    """Authenticated request whose wallet binding is injected (the wallet store itself is not under test)."""
    state = SimpleNamespace(wallet=VERIFIED, session_calls=0, store_down=False)

    def resolve_session(request):
        state.session_calls += 1
        return SimpleNamespace(user_id="user-1", session_type="user")

    def wallet_for(session_obj):
        if state.store_down:
            raise OSError("wallet store unavailable")
        return state.wallet

    monkeypatch.setattr("app.auth.resolve_request_session", resolve_session)
    monkeypatch.setattr(cra, "wallet_context_for_session", wallet_for)
    return state


def resolve(resource, *, policy_set=None, provider=None, deployments=None, env=ENV):
    return asyncio.run(resolve_tokenized_access(
        object(), resource, policy_set=policy_set or policies(), provider=provider or FakeProvider(),
        approved=[approved()] if deployments is None else deployments, environ=env, now=NOW))


# ── resource policy ──────────────────────────────────────────────────────────────────────────────
def test_tokenized_basic_is_public_and_needs_no_session_or_wallet(session):
    d = resolve(R.BASIC, deployments=[], policy_set=ep.load_policy_set({}))
    assert (d.state, d.access_allowed, d.token_entitled, d.gate_active) == (S.PUBLIC, True, False, False)
    assert session.session_calls == 0                       # public surface never touches the session/wallet


def test_new_holder_resources_ship_disabled_unthresholded_and_inactive_by_default(session):
    table = ep.default_policies()
    for key in (ep.TOKENIZED_HISTORY, ep.TOKENIZED_DISLOCATION, ep.CRYPTO_API):
        policy = table[key]
        assert policy.access_mode is ep.AccessMode.FINCO_HOLDER
        assert (policy.enabled, policy.minimum_balance, policy.wallet_verified_required) == (False, None, True)
    assert table[ep.TOKENIZED_BASIC].access_mode is ep.AccessMode.PUBLIC
    for resource in HOLDERS:
        d = asyncio.run(resolve_tokenized_access(object(), resource, environ={}, now=NOW))
        assert d.state is S.TOKEN_ENTITLEMENT_FEATURE_INACTIVE


def test_gating_off_is_inactive_ungated_and_never_token_truth(session):
    provider = FakeProvider()
    for resource in HOLDERS:
        d = resolve(resource, policy_set=policies(gating=False), provider=provider)
        assert d.state is S.TOKEN_ENTITLEMENT_FEATURE_INACTIVE
        assert d.access_allowed is True                       # existing ungated behaviour is preserved
        assert d.token_entitled is False and d.gate_active is False   # but entitlement truth stays False
    assert provider.calls == []                                # nothing was read


@pytest.mark.parametrize("resource", HOLDERS)
def test_verified_wallet_with_valid_evidence_is_entitled(session, resource):
    d = resolve(resource)
    assert (d.state, d.access_allowed, d.token_entitled, d.gate_active) == (S.ENTITLED, True, True, True)
    assert d.wallet_address == WALLET


def test_below_threshold_denies(session):
    d = resolve(R.HISTORY, provider=FakeProvider(evidence(RAW - 1)))
    assert (d.state, d.access_allowed, d.token_entitled) == (S.ENTITLEMENT_NOT_SATISFIED, False, False)
    assert d.reason == "BALANCE_BELOW_THRESHOLD"


def test_stale_balance_denies_fail_closed(session):
    d = resolve(R.HISTORY, provider=FakeProvider(evidence(age=3600)))
    assert (d.access_allowed, d.token_entitled) == (False, False)
    assert d.state is S.ENTITLEMENT_AUTHORITY_UNAVAILABLE and d.reason == "BALANCE_STALE"


def test_unavailable_evidence_denies_and_is_not_zero(session):
    d = resolve(R.DISLOCATION, provider=FakeProvider(evidence(state=BalanceEvidenceState.UNAVAILABLE)))
    assert (d.access_allowed, d.token_entitled) == (False, False)
    assert d.state is S.ENTITLEMENT_AUTHORITY_UNAVAILABLE
    assert d.upstream.observed_balance is None                # missing != zero


def test_explicit_zero_balance_is_a_number_and_below_threshold_not_unavailable(session):
    d = resolve(R.HISTORY, provider=FakeProvider(evidence(0)))
    assert d.upstream.observed_balance == Decimal(0)
    assert d.state is S.ENTITLEMENT_NOT_SATISFIED


@pytest.mark.parametrize("override", [
    dict(chain_id=CHAIN + 1), dict(token_address=OTHER_TOKEN), dict(wallet_address=OTHER_WALLET)])
def test_wrong_chain_token_or_wallet_identity_denies(session, override):
    d = resolve(R.HISTORY, provider=FakeProvider(evidence(**override)))
    assert (d.access_allowed, d.token_entitled) == (False, False)
    assert d.state is S.ENTITLEMENT_AUTHORITY_UNAVAILABLE


def test_no_approved_deployment_is_typed_not_configured(session):
    d = resolve(R.HISTORY, deployments=[])
    assert (d.state, d.access_allowed, d.token_entitled) == (S.TOKEN_DEPLOYMENT_NOT_CONFIGURED, False, False)


def test_wallet_not_connected_and_unverified_are_typed(session):
    session.wallet = WalletContext(None, False, "user-1")
    assert resolve(R.HISTORY).state is S.WALLET_UNAVAILABLE
    session.wallet = WalletContext(WALLET, False, "user-1")
    assert resolve(R.HISTORY).state is S.WALLET_UNVERIFIED


def test_wallet_store_outage_never_grants_and_never_500s(session):
    session.store_down = True
    assert resolve(R.HISTORY).state is S.WALLET_UNAVAILABLE                      # gate active -> denied
    off = resolve(R.HISTORY, policy_set=policies(gating=False))
    assert off.state is S.TOKEN_ENTITLEMENT_FEATURE_INACTIVE and off.token_entitled is False


def test_unknown_resource_fails_closed(session):
    d = asyncio.run(cra.resolve_crypto_access(object(), "tokenized.nonexistent", policy_set=policies(),
                                              environ=ENV, now=NOW))
    assert (d.access_allowed, d.token_entitled) == (False, False)
    assert d.state is S.ENTITLEMENT_AUTHORITY_UNAVAILABLE and d.reason == "UNKNOWN_RESOURCE"


# ── API and UI share the one authority ───────────────────────────────────────────────────────────
def test_api_and_ui_adapters_consume_the_same_authority(session, monkeypatch):
    calls = []
    real = cra.evaluate_resource_access

    async def spy(resource_key, wallet, **kw):
        calls.append(resource_key)
        return await real(resource_key, wallet, **kw)

    monkeypatch.setattr(cra, "evaluate_resource_access", spy)
    kw = dict(policy_set=policies(), provider=FakeProvider(), approved=[approved()], environ=ENV, now=NOW)
    ui = asyncio.run(resolve_tokenized_access(object(), R.HISTORY, **kw))
    api = asyncio.run(resolve_api_access(object(), **kw))
    assert calls == [ep.TOKENIZED_HISTORY, ep.CRYPTO_API]
    assert ui.state is api.state is S.ENTITLED
    assert type(ui.upstream) is type(api.upstream)
    assert (ui.upstream.chain_id, ui.upstream.token_address) == (api.upstream.chain_id, api.upstream.token_address)


def test_api_default_configuration_is_inactive_and_not_activated(session):
    d = asyncio.run(resolve_api_access(object(), environ={}, now=NOW))
    assert d.upstream is not None and d.upstream.decision is Decision.INACTIVE
    assert (d.state, d.access_allowed, d.token_entitled, d.gate_active) == (
        S.TOKEN_ENTITLEMENT_FEATURE_INACTIVE, False, False, False)


def test_api_valid_holder_evidence_allows_access(session):
    d = asyncio.run(resolve_api_access(
        object(), policy_set=policies(), provider=FakeProvider(), approved=[approved()], environ=ENV, now=NOW))
    assert d.upstream is not None and d.upstream.decision is Decision.ALLOW
    assert (d.state, d.access_allowed, d.token_entitled, d.gate_active) == (S.ENTITLED, True, True, True)


@pytest.mark.parametrize(("value", "reason"), [
    (evidence(RAW - 1), "BALANCE_BELOW_THRESHOLD"),
    (evidence(age=3600), "BALANCE_STALE"),
    (evidence(state=BalanceEvidenceState.UNAVAILABLE), "RPC_UNAVAILABLE"),
])
def test_api_insufficient_stale_or_unavailable_evidence_denies(session, value, reason):
    d = asyncio.run(resolve_api_access(
        object(), policy_set=policies(), provider=FakeProvider(value), approved=[approved()], environ=ENV, now=NOW))
    assert d.upstream is not None and d.upstream.decision is Decision.DENY
    assert d.access_allowed is False and d.token_entitled is False and d.reason == reason


def test_api_no_approved_deployment_is_typed_not_configured_and_denied(session):
    d = asyncio.run(resolve_api_access(
        object(), policy_set=policies(), provider=FakeProvider(), approved=[], environ=ENV, now=NOW))
    assert d.upstream is not None and d.upstream.decision is Decision.DENY
    assert (d.state, d.access_allowed, d.token_entitled) == (S.TOKEN_DEPLOYMENT_NOT_CONFIGURED, False, False)

def test_api_denial_payload_exposes_only_safe_fields(session):
    d = asyncio.run(resolve_api_access(
        object(), policy_set=policies(), provider=FakeProvider(evidence(RAW - 1)), approved=[approved()],
        environ={**ENV, "FINCO_TOKEN_RPC_URL_31337": "https://secret.example/key-123"}, now=NOW))
    body = api_denial_payload(d)
    assert set(body) == {"error", "resource", "access_state", "reason"}
    assert body["resource"] == "crypto.api" and body["access_state"] == "ENTITLEMENT_NOT_SATISFIED"
    text = json.dumps(body)
    assert "secret.example" not in text and "key-123" not in text and TOKEN not in text and WALLET not in text
    ui = denial_payload(resolve(R.HISTORY, provider=FakeProvider(evidence(RAW - 1))))
    assert set(ui) == {"error", "resource", "access_state", "reason"}


def test_state_mapping_has_exact_parity_with_the_yield_adapter():
    from finco_yield.access import YieldAccessState, _map_deny_reason
    assert {s.value for s in S} == {s.value for s in YieldAccessState}
    for reason in ("WALLET_NOT_CONNECTED", "WALLET_NOT_VERIFIED", "WALLET_IDENTITY_UNAVAILABLE",
                   "NO_APPROVED_DEPLOYMENT", "NO_APPROVED_DEPLOYMENT_ON_CHAIN", "TOKEN_CONFIGURATION_UNAVAILABLE",
                   "RPC_UNAVAILABLE", "BALANCE_EVIDENCE_UNAVAILABLE", "BALANCE_STALE", "BALANCE_IDENTITY_MISMATCH",
                   "BALANCE_BELOW_THRESHOLD", "POLICY_THRESHOLD_UNSET", "POLICY_CONFIG_INVALID",
                   "UNKNOWN_RESOURCE", "SOMETHING_NEW"):
        assert map_deny_reason(reason).value == _map_deny_reason(reason).value, reason


def test_unknown_decision_value_is_denied():
    fake = SimpleNamespace(decision="MAYBE", reason_code="X", wallet_address=None)
    d = from_resource_decision("tokenized.history", fake)
    assert d.access_allowed is False and d.token_entitled is False


# ── authority preservation / no new surface ──────────────────────────────────────────────────────
def test_production_deployment_authority_stays_empty_and_env_cannot_create_one(monkeypatch):
    assert canon.APPROVED_FINCO_DEPLOYMENTS == ()
    assert resolve_approved_deployment().status is ResolutionStatus.NOT_CONFIGURED
    monkeypatch.setenv("FINCO_TOKEN_DEPLOYMENTS_JSON", json.dumps(
        [{"chain_id": CHAIN, "contract_address": TOKEN, "decimals": 6, "provenance": "TEST_ONLY"}]))
    monkeypatch.setenv("FINCO_TOKEN_ADDRESS", TOKEN)
    monkeypatch.setenv(ep.GATING_ENABLED_ENV, "1")
    monkeypatch.setenv(ep.POLICIES_ENV, json.dumps({ep.TOKENIZED_HISTORY: {"enabled": True, "minimum_balance": "1"}}))
    monkeypatch.setenv(FRESHNESS_ENV, "60")
    d = asyncio.run(evaluate_resource_access(ep.TOKENIZED_HISTORY, VERIFIED, now=NOW))
    assert d.decision is Decision.DENY and d.reason_code == "NO_APPROVED_DEPLOYMENT"
    assert canon.APPROVED_FINCO_DEPLOYMENTS == ()


def test_operator_policy_override_accepts_new_keys_and_still_rejects_unknown_or_public():
    ok = ep.load_policy_set({ep.POLICIES_ENV: json.dumps({"crypto.api": {"enabled": True, "minimum_balance": "5"}})})
    assert ok.config_error is False and ok.policies["crypto.api"].minimum_balance == Decimal("5")
    for bad in ({"tokenized.basic": {"enabled": False}}, {"tokenized.unknown": {"enabled": True}}):
        assert ep.load_policy_set({ep.POLICIES_ENV: json.dumps(bad)}).config_error is True


def test_adapters_hold_no_rpc_balance_threshold_signing_or_custody_logic():
    forbidden = ("balance_of", "read_token_balance", "eth_call", "send_raw", "private_key", "sign_message",
                 "sign_transaction", "web3", "httpx", "requests", "urllib", "token_balance", "token_deployments",
                 "minimum_balance", "APPROVED_FINCO_DEPLOYMENTS", "FINCO_TOKEN_RPC_URL")
    for rel in ("app/crypto_resource_access.py", "app/tokenized_access.py", "app/crypto_api_access.py"):
        source = (ROOT / rel).read_text()
        code = "\n".join(line for line in source.splitlines() if not line.lstrip().startswith("#"))
        code = re.sub(r'"""[\s\S]*?"""', "", code)
        for token in forbidden:
            assert token not in code, (rel, token)


def test_no_market_data_module_consults_access_authority():
    for rel in ("finco_radar/venues",):
        base = ROOT / rel
        if not base.exists():
            continue
        for path in base.rglob("*.py"):
            text = path.read_text()
            assert "crypto_resource_access" not in text and "evaluate_resource_access" not in text, path
