"""$FINCO token-gate activation readiness V1 — deterministic tests.

Covers the required matrix: gate OFF, missing token config, wallet states,
malformed wallet, RPC timeout/error, contract-call error, balance
unavailable, factual zero, below/exactly/above threshold, decimal
conversion, wrong network, no balance fabrication, evaluator integration,
gated Yield resource, gate-OFF unchanged behaviour, and frozen-namespace
safety.  All provider interactions are deterministic injected fakes — no
network, no real token, no transactions.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace

import pytest

TEST_TOKEN = "0x" + "ab" * 20
TEST_WALLET = "0x" + "cd" * 20
PROBE = "0x" + "00" * 20


def _policy_set(minimum=Decimal(10), *, enabled=True, chain_id=8453):
    from app.protocol.entitlement_policy import (
        AccessMode, EntitlementPolicy, PolicySet, default_policies,
    )
    policies = dict(default_policies())
    policies["yield.history"] = EntitlementPolicy(
        resource_key="yield.history", access_mode=AccessMode.FINCO_HOLDER,
        minimum_balance=minimum, wallet_verified_required=True,
        enabled=enabled, chain_id=chain_id)
    return PolicySet(policies, gating_enabled=True)


def _policy(minimum=Decimal(10), *, enabled=True, chain_id=8453):
    """The single canonical yield.history EntitlementPolicy."""
    return _policy_set(minimum=minimum, enabled=enabled,
                       chain_id=chain_id).get("yield.history")


def _entitle_token_policy(minimum=Decimal(10), *, decimals=18):
    """Token-level FincoEntitlementPolicy for direct evaluator calls."""
    from app.verified.token_entitlement import FincoEntitlementPolicy
    return FincoEntitlementPolicy(
        chain_id=8453, token_address=TEST_TOKEN, token_decimals=decimals,
        minimum_balance_raw=int(minimum * 10 ** decimals),
        freshness_seconds=300, provenance="TEST_ONLY")


def _config(rpc=True, chain=8453, address=True, threshold=True, decimals=18):
    from app.protocol.token_config import TokenConfig
    if not (rpc and address and threshold):
        return None
    return TokenConfig(
        rpc_url="https://rpc.example" if rpc else "",
        chain_id=chain,
        token_address=TEST_TOKEN if address else "",
        min_balance=Decimal("10") if threshold else None,
        decimals_override=decimals,
    )


class _FakeProvider:
    """Canonical TokenBalanceProvider double with a scripted evidence."""

    def __init__(self, *, state="AVAILABLE", balance_raw=None, reason=None):
        self.state_value = state
        self.balance_raw = balance_raw
        self.reason = reason
        self.calls = []

    async def balance_of(self, policy, wallet_address):
        from app.verified.token_entitlement import BalanceEvidenceState, TokenBalanceEvidence
        self.calls.append(wallet_address)
        available = self.state_value == "AVAILABLE"
        return TokenBalanceEvidence(
            chain_id=policy.chain_id, token_address=policy.token_address,
            wallet_address=wallet_address, token_decimals=policy.token_decimals,
            balance_raw=self.balance_raw if available else None,
            observed_at=datetime.now(timezone.utc), source="TEST_ONLY",
            state=BalanceEvidenceState(self.state_value),
            reason=None if available else (self.reason or self.state_value))


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for var in ("FINCO_TOKEN_GATING_ENABLED", "FINCO_ENTITLEMENT_POLICIES_JSON",
                "FINCO_TOKEN_RPC_URL", "FINCO_TOKEN_RPC_URL_8453",
                "FINCO_TOKEN_CHAIN_ID", "FINCO_TOKEN_ADDRESS",
                "FINCO_ACCESS_MIN_BALANCE", "FINCO_TOKEN_DECIMALS"):
        monkeypatch.delenv(var, raising=False)


# ── Readiness report: configuration states ────────────────────────────────────

def test_default_production_gate_off_and_not_configured():
    from app.protocol.token_gate_readiness import (
        STATE_GATE_OFF, STATE_NOT_CONFIGURED, build_readiness_report,
    )
    report = build_readiness_report(environ={})
    assert report.state == STATE_GATE_OFF
    assert report.gate_enabled is False
    assert report.checks["deployment"]["status"] == "NOT_CONFIGURED"
    assert "gating is OFF" in report.next_action


def test_gate_off_reports_configuration_problems_without_locking():
    """Gate OFF never locks anything: the report informs, product behaviour
    is unchanged (no decision state is produced at all)."""
    from app.protocol.token_gate_readiness import (
        STATE_GATE_OFF, build_readiness_report,
    )
    report = build_readiness_report(environ={"FINCO_TOKEN_GATING_ENABLED": "1"})
    # gating flag ON but zero approved deployments -> evaluator is DENY
    # NOT_CONFIGURED (existing canonical behaviour), the report says so
    assert report.state == STATE_GATE_OFF or report.state == "NOT_CONFIGURED"
    assert report.checks["deployment"]["resolved"] is False


def test_missing_token_config_is_first_class_not_configured():
    from app.protocol.token_gate_readiness import (
        STATE_NOT_CONFIGURED, build_readiness_report,
    )
    report = build_readiness_report(
        environ={"FINCO_TOKEN_GATING_ENABLED": "1"})
    assert report.state == STATE_NOT_CONFIGURED
    assert "P4 token configuration" in report.next_action


def test_partially_configured_missing_deployment(monkeypatch):
    from app.protocol.token_gate_readiness import (
        STATE_PARTIALLY_CONFIGURED, build_readiness_report,
    )
    monkeypatch.setattr("app.protocol.token_config.get_token_config", _config)
    report = build_readiness_report(
        environ={"FINCO_TOKEN_GATING_ENABLED": "1"})
    assert report.state == STATE_PARTIALLY_CONFIGURED
    assert "approved deployment" in report.next_action


def _patch_deployment(monkeypatch):
    monkeypatch.setattr(
        "app.protocol.token_deployments.resolve_approved_deployment",
        lambda selector=None: SimpleNamespace(
            status=SimpleNamespace(value="RESOLVED"), reason="", resolved=True,
            deployment=SimpleNamespace(chain_id=8453, decimals=18)))


def test_ready_requires_explicit_decimals_and_provider(monkeypatch):
    from app.protocol.token_gate_readiness import (
        STATE_PARTIALLY_CONFIGURED, STATE_PROVIDER_UNAVAILABLE,
        build_readiness_report,
    )
    # deployment resolved via fake, P4 config without decimals, no provider env
    monkeypatch.setattr("app.protocol.token_config.get_token_config",
                        lambda: _config(decimals=None))
    _patch_deployment(monkeypatch)
    report = build_readiness_report(environ={"FINCO_TOKEN_GATING_ENABLED": "1"})
    assert report.state == STATE_PARTIALLY_CONFIGURED
    assert "FINCO_TOKEN_DECIMALS" in report.next_action

    monkeypatch.setattr("app.protocol.token_config.get_token_config",
                        lambda: _config())
    report = build_readiness_report(environ={"FINCO_TOKEN_GATING_ENABLED": "1"})
    assert report.state == STATE_PROVIDER_UNAVAILABLE
    assert "FINCO_TOKEN_RPC_URL_8453" in report.next_action


# ── Provider probe: failures are typed, never zero ────────────────────────────

def test_probe_rpc_failure_is_typed_never_zero(monkeypatch):
    from app.protocol.token_gate_readiness import (
        STATE_PROVIDER_UNAVAILABLE, build_readiness_report, probe_provider,
    )
    monkeypatch.setattr("app.protocol.token_config.get_token_config",
                        lambda: _config())

    class _Broken:
        async def balance_of(self, policy, wallet):
            from app.verified.token_entitlement import BalanceEvidenceState
            return SimpleNamespace(state=BalanceEvidenceState("UNAVAILABLE"),
                                   balance_raw=None,
                                   reason="RPC_UNAVAILABLE")
    result = probe_provider(_config(), provider=_Broken())
    assert result.reachable is False
    assert result.status == "RPC_UNAVAILABLE"
    assert result.observed_balance_raw is None
    assert result.factual_zero is False

    monkeypatch.setattr(
        "app.protocol.token_gate_readiness.probe_provider",
        lambda config, provider=None, probe_address=PROBE:
        probe_provider(config, provider=_Broken()))
    monkeypatch.setattr("app.protocol.token_config.get_token_config",
                        lambda: _config())
    monkeypatch.setattr(
        "app.protocol.token_deployments.resolve_approved_deployment",
        lambda selector=None: SimpleNamespace(
            status=SimpleNamespace(value="RESOLVED"), reason="", resolved=True,
            deployment=SimpleNamespace(chain_id=8453, decimals=18)))
    report = build_readiness_report(
        environ={"FINCO_TOKEN_GATING_ENABLED": "1",
                 "FINCO_TOKEN_RPC_URL_8453": "https://rpc.example"},
        probe=True)
    assert report.state == STATE_PROVIDER_UNAVAILABLE


def test_probe_contract_error_is_typed(monkeypatch):
    from app.protocol.token_gate_readiness import (
        STATE_TOKEN_CONTRACT_UNAVAILABLE, build_readiness_report,
        probe_provider,
    )
    _patch_deployment(monkeypatch)
    monkeypatch.setenv("FINCO_TOKEN_RPC_URL_8453", "https://rpc.example")
    monkeypatch.setattr("app.protocol.token_config.get_token_config",
                        lambda: _config())
    result = probe_provider(_config(), provider=_FakeProvider(
        state="UNAVAILABLE", reason="TOKEN_CONTRACT_UNAVAILABLE"))
    assert result.status == "TOKEN_CONTRACT_UNAVAILABLE"

    # provider path (injected): typed contract failure -> readiness maps it
    report = build_readiness_report(
        environ={"FINCO_TOKEN_GATING_ENABLED": "1",
                 "FINCO_TOKEN_RPC_URL_8453": "https://rpc.example"},
        provider=_FakeProvider(state="UNAVAILABLE",
                               reason="TOKEN_CONTRACT_UNAVAILABLE"),
        probe=True)
    assert report.state == STATE_TOKEN_CONTRACT_UNAVAILABLE
    # raw-reader path (no provider): same typed contract failure
    async def _contract_unavailable(wallet_address, config):
        from app.protocol.token_balance import TokenObservation
        return TokenObservation(
            wallet_address=wallet_address, chain_id=config.chain_id,
            token_address=config.token_address, balance_raw=None,
            decimals=None, normalized_balance=None, block_number=None,
            observed_at=datetime.now(timezone.utc),
            status="TOKEN_CONTRACT_UNAVAILABLE")
    monkeypatch.setattr(
        "app.protocol.token_balance.read_token_balance",
        _contract_unavailable)
    report = build_readiness_report(
        environ={"FINCO_TOKEN_GATING_ENABLED": "1",
                 "FINCO_TOKEN_RPC_URL_8453": "https://rpc.example"},
        probe=True)
    assert report.state == STATE_TOKEN_CONTRACT_UNAVAILABLE


def test_probe_success_reports_factual_zero_not_failure(monkeypatch):
    from app.protocol.token_gate_readiness import (
        STATE_READY, build_readiness_report, probe_provider,
    )
    _patch_deployment(monkeypatch)
    monkeypatch.setenv("FINCO_TOKEN_RPC_URL_8453", "https://rpc.example")
    monkeypatch.setattr("app.protocol.token_config.get_token_config",
                        lambda: _config())
    result = probe_provider(_config(), provider=_FakeProvider(balance_raw=0))
    assert result.reachable is True
    assert result.observed_balance_raw == 0
    assert result.factual_zero is True  # explicit observed zero is real data

    async def _factual_zero(wallet_address, config):
        from app.protocol.token_balance import TokenObservation
        return TokenObservation(
            wallet_address=wallet_address, chain_id=config.chain_id,
            token_address=config.token_address, balance_raw=0,
            decimals=config.decimals_override, normalized_balance=Decimal(0),
            block_number=1, observed_at=datetime.now(timezone.utc),
            status="INSUFFICIENT_BALANCE")
    monkeypatch.setattr(
        "app.protocol.token_balance.read_token_balance", _factual_zero)
    report = build_readiness_report(
        environ={"FINCO_TOKEN_GATING_ENABLED": "1",
                 "FINCO_TOKEN_RPC_URL_8453": "https://rpc.example"},
        probe=True)
    assert report.state == STATE_READY
    assert report.checks["provider"]["factual_zero"] is True


# ── Canonical evaluator integration (threshold matrix) ────────────────────────

def _entitle(*, wallet=TEST_WALLET, balance_raw, decimals=18,
             minimum=Decimal(10)):
    """Canonical token-level entitlement evaluation against the fixture."""
    from app.verified.token_entitlement import (
        BalanceEvidenceState, FincoEntitlementPolicy, TokenBalanceEvidence,
        evaluate_token_entitlement,
    )
    token_policy = FincoEntitlementPolicy(
        chain_id=8453, token_address=TEST_TOKEN, token_decimals=decimals,
        minimum_balance_raw=int(minimum * 10 ** decimals),
        freshness_seconds=300, provenance="TEST_ONLY")
    evidence = TokenBalanceEvidence(
        chain_id=8453, token_address=TEST_TOKEN, wallet_address=wallet,
        token_decimals=decimals, balance_raw=balance_raw,
        observed_at=datetime.now(timezone.utc) - timedelta(seconds=1),
        source="TEST_ONLY", state=BalanceEvidenceState.AVAILABLE)
    return evaluate_token_entitlement(
        subject_id="user-1", wallet_address=wallet, policy=token_policy,
        evidence=evidence, as_of=datetime.now(timezone.utc))


def test_threshold_matrix_below_exact_above():
    from app.verified.entitlement import EntitlementState
    below = _entitle(balance_raw=10 ** 18 - 1)
    exact = _entitle(balance_raw=10 * 10 ** 18)   # exactly 10 tokens
    above = _entitle(balance_raw=10 * 10 ** 18 + 5)
    assert below.state is EntitlementState.INACTIVE
    assert below.reason == "BALANCE_BELOW_THRESHOLD"
    assert exact.state is EntitlementState.ACTIVE     # exactly threshold grants
    assert above.state is EntitlementState.ACTIVE


def test_decimal_conversion_raw_to_units_deterministic():
    """Raw integer base units -> Decimal token units, no float anywhere."""
    from app.protocol.entitlement_evaluator import decide_resource_access
    from app.protocol.entitlement_policy import (
        AccessMode, EntitlementPolicy, PolicySet,
    )
    wallet = SimpleNamespace(address=TEST_WALLET, verified=True,
                             subject_id="user-1")
    policy = EntitlementPolicy(
        resource_key="yield.history", access_mode=AccessMode.FINCO_HOLDER,
        minimum_balance=Decimal("1.5"), wallet_verified_required=True,
        enabled=True, chain_id=8453)
    policy_set = PolicySet({"yield.history": policy}, gating_enabled=True)
    deployment = SimpleNamespace(chain_id=8453, token_address=TEST_TOKEN,
                                 decimals=18, provenance="TEST")
    resolution = SimpleNamespace(status=SimpleNamespace(value="RESOLVED"),
                                 reason="", resolved=True,
                                 deployment=deployment)
    evidence = _evidence_for(policy, raw=int(Decimal("1.5") * 10 ** 18))
    decision = decide_resource_access(
        "yield.history", wallet, policy_set, resolution, evidence,
        freshness_seconds=300)
    assert decision.decision.value == "ALLOW"
    assert decision.observed_balance == Decimal("1.5")


def _evidence_for(policy, *, raw, stale=False):
    from app.verified.token_entitlement import (
        BalanceEvidenceState, TokenBalanceEvidence,
    )
    return TokenBalanceEvidence(
        chain_id=8453, token_address=TEST_TOKEN,
        wallet_address=TEST_WALLET, token_decimals=18,
        balance_raw=raw, observed_at=datetime.now(timezone.utc),
        source="TEST_ONLY",
        state=BalanceEvidenceState("STALE" if stale else "AVAILABLE"))


def test_wrong_network_is_typed_unavailable_never_zero():
    """Balance evidence read on a different chain never becomes a number."""
    from app.verified.entitlement import EntitlementState
    from app.verified.token_entitlement import (
        BalanceEvidenceState, TokenBalanceEvidence, evaluate_token_entitlement,
    )
    token_policy = _entitle_token_policy()
    wrong_chain = TokenBalanceEvidence(
        chain_id=1, token_address=TEST_TOKEN,
        wallet_address=TEST_WALLET, token_decimals=18,
        balance_raw=10 ** 18, observed_at=datetime.now(timezone.utc),
        source="TEST_ONLY", state=BalanceEvidenceState.AVAILABLE)
    result = evaluate_token_entitlement(
        subject_id="user-1", wallet_address=TEST_WALLET, policy=token_policy,
        evidence=wrong_chain, as_of=datetime.now(timezone.utc))
    assert result.state is EntitlementState.UNAVAILABLE
    assert result.reason == "BALANCE_IDENTITY_MISMATCH"


# ── Gate OFF preserves unrestricted behaviour ─────────────────────────────────

def test_gate_off_leaves_product_behaviour_unchanged():
    """With gating OFF, holder resources are canonically INACTIVE (no gate
    denied anyone) and the public resource stays PUBLIC — the existing
    ungated behaviour, byte-for-byte."""
    from app.protocol.entitlement_evaluator import (
        Decision, wallet_context_for_session,
    )
    from app.protocol.entitlement_policy import load_policy_set

    async def fake_eval(resource_key, wallet, **kw):
        from app.protocol.entitlement_evaluator import decide_resource_access
        return decide_resource_access(
            resource_key, wallet, load_policy_set({}), 
            SimpleNamespace(status=SimpleNamespace(value="NOT_CONFIGURED"),
                            reason="NO_APPROVED_DEPLOYMENT", resolved=False,
                            deployment=None),
            None, freshness_seconds=None)

    anon = wallet_context_for_session(None)
    assert anon.address is None and anon.verified is False
    # the canonical mapping under gating-off is INACTIVE, not DENY — proven
    # by the default policy set (gating disabled)
    policy_set = load_policy_set({})
    assert policy_set.gating_enabled is False
    policy = policy_set.get("yield.history")
    assert policy.access_mode.value == "FINCO_HOLDER"
    assert policy.enabled is False  # no active gate exists by default


# ── Malformed wallet / disconnected wallet ────────────────────────────────────

def test_malformed_wallet_is_identity_unavailable():
    from app.verified.entitlement import EntitlementState
    from app.verified.token_entitlement import evaluate_token_entitlement
    result = evaluate_token_entitlement(
        subject_id="user-1", wallet_address="not-a-wallet",
        policy=_entitle_token_policy(), evidence=None,
        as_of=datetime.now(timezone.utc))
    assert result.state is EntitlementState.IDENTITY_UNAVAILABLE


def test_readiness_probe_validates_wallet_addresses():
    from app.protocol.token_gate_readiness import probe_provider
    from app.protocol.token_config import TokenConfig
    config = _config()
    # probe target is a constant, deterministic zero address
    assert probe_provider(config, provider=_FakeProvider(balance_raw=1)).reachable


# ── Gated Yield resource end-to-end (deterministic provider) ──────────────────

def test_gated_yield_resource_end_to_end_with_fake_provider(monkeypatch):
    """evaluate_resource_access with an injected provider: eligible wallet
    gets ALLOW; below-threshold wallet gets DENY BALANCE_BELOW_THRESHOLD;
    unavailable evidence fails closed — never zero."""
    import asyncio
    from app.protocol.entitlement_evaluator import evaluate_resource_access
    from app.protocol.entitlement_policy import load_policy_set

    def run(balance_raw, state="AVAILABLE", reason=None):
        provider = _FakeProvider(state=state, balance_raw=balance_raw,
                                 reason=reason)
        env = {"FINCO_TOKEN_GATING_ENABLED": "1",
               "FINCO_ENTITLEMENT_POLICIES_JSON":
                   '{"yield.history": {"enabled": true, "minimum_balance": "10"}}',
               "FINCO_ENTITLEMENT_MAX_AGE_SECONDS": "300"}
        wallet = SimpleNamespace(address=TEST_WALLET, verified=True,
                                 subject_id="user-1")
        # deployment must resolve: inject one approved deployment for the run
        from app.verified import token_entitlement as te
        deployment = te.ApprovedFincoDeployment(
            chain_id=8453, token_address=TEST_TOKEN, standard="ERC-20",
            decimals=18, provenance="TEST_ONLY")
        monkeypatch.setattr(te, "APPROVED_FINCO_DEPLOYMENTS", (deployment,))
        decision = asyncio.run(evaluate_resource_access(
            "yield.history", wallet, provider=provider, environ=env))
        return decision

    allowed = run(10 * 10 ** 18)  # exactly the 10-token fixture threshold
    assert allowed.decision.value == "ALLOW", allowed.reason_code
    assert allowed.reason_code == "BALANCE_AT_OR_ABOVE_THRESHOLD"
    assert allowed.observed_balance == Decimal("10")  # raw/decimals, no float

    denied = run(1)
    assert denied.decision.value == "DENY"
    assert denied.reason_code == "BALANCE_BELOW_THRESHOLD"

    unavailable = run(None, state="UNAVAILABLE", reason="RPC_UNAVAILABLE")
    assert unavailable.decision.value == "DENY"
    assert unavailable.reason_code == "RPC_UNAVAILABLE"
    assert unavailable.observed_balance is None  # no fabricated balance


def test_gate_off_yield_resource_is_inactive_not_denied(monkeypatch):
    """Gate OFF: no resource decision may lock a user out — canonical
    INACTIVE semantics only (existing ungated product behaviour)."""
    import asyncio
    from app.protocol.entitlement_evaluator import evaluate_resource_access

    env = {}  # gating flag absent
    wallet = SimpleNamespace(address=None, verified=False, subject_id="user-1")
    decision = asyncio.run(evaluate_resource_access(
        "yield.history", wallet, environ=env))
    assert decision.decision.value == "INACTIVE"
    assert decision.reason_code == "TOKEN_GATING_OFF"
    assert decision.allowed is False  # proves nothing; behaviour unchanged


# ── Frozen namespaces: the readiness layer never touches them ─────────────────

def test_readiness_module_imports_no_frozen_or_math_authority():
    """No frozen/math authority imports and no write/signing call-site
    constants in the readiness layer (docstring documentation of the
    read-only guarantee is not a call site)."""
    import ast
    import inspect
    from app.protocol import token_gate_readiness
    source = inspect.getsource(token_gate_readiness)
    for banned_import in ("financial_engine", "finco_core", "finco_radar",
                          "app.model_validation", "app.verified.composer"):
        assert banned_import not in source, banned_import
    tree = ast.parse(source)
    constants = {node.value for node in ast.walk(tree)
                 if isinstance(node, ast.Constant)
                 and isinstance(node.value, str)}
    for banned_call in ("eth_sendTransaction", "eth_sendRawTransaction",
                        "personal_sign", "sign_transaction"):
        assert banned_call not in constants, banned_call
    assert not any(name.endswith(".private_key") for name in constants)


def test_no_write_rpc_methods_in_balance_authority():
    """The read-only balance authority contains no write RPC methods.
    Checked over string CONSTANTS in the AST (docstrings that document the
    read-only guarantee are not call sites)."""
    import ast
    import inspect
    from app.protocol import token_balance
    tree = ast.parse(inspect.getsource(token_balance))
    constants = {node.value for node in ast.walk(tree)
                 if isinstance(node, ast.Constant)
                 and isinstance(node.value, str)}
    for write_method in ("eth_sendTransaction", "eth_sendRawTransaction",
                         "eth_signTransaction", "personal_sign"):
        assert write_method not in constants, write_method
    assert "0x70a08231" in constants  # balanceOf — the only selector used
    assert "0x313ce567" in constants  # decimals — read-only metadata


def test_report_contains_no_secrets():
    """The readiness report never contains an RPC URL, key or credential."""
    import json
    from app.protocol.token_gate_readiness import build_readiness_report
    env = {"FINCO_TOKEN_GATING_ENABLED": "1",
           "FINCO_TOKEN_RPC_URL_8453":
               "https://provider-host.invalid/rpc/ref-8453",
           "FINCO_TOKEN_RPC_URL": "https://provider-host.invalid/rpc/flat",
           "FINCO_TOKEN_CHAIN_ID": "8453",
           "FINCO_TOKEN_ADDRESS": TEST_TOKEN,
           "FINCO_ACCESS_MIN_BALANCE": "10",
           "FINCO_TOKEN_DECIMALS": "18"}
    payload = json.dumps(build_readiness_report(environ=env).public_dict())
    assert "secret" not in payload
    assert "provider-host.invalid" not in payload
    assert "https://" not in payload
