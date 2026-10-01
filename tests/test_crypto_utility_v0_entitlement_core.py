"""Crypto Utility V0 / Agent A — token identity, balance observation, entitlement policy and decision.

Every amount, address and chain id below is TEST_ONLY. None of them is, or may become, a production
default: production ships with zero deployments, gating OFF and no thresholds.
"""
from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from app.protocol import entitlement_policy as ep
from app.protocol.balance_observation import (
    JsonRpcTokenBalanceReader, ObservationStatus, RawBalance, observe_finco_balance,
)
from app.protocol.entitlement_evaluator import (
    NO_WALLET, Decision, WalletContext, decide_resource_access, evaluate_all_resources,
    evaluate_resource_access,
)
from app.protocol.token_deployments import (
    DEPLOYMENTS_ENV, DeploymentRegistry, DeploymentStatus, ResolutionStatus, TokenDeployment,
)

NOW = datetime(2026, 10, 1, 12, 0, tzinfo=timezone.utc)
TEST_ONLY_CHAIN = 31337
TEST_ONLY_OTHER_CHAIN = 31338
TEST_ONLY_TOKEN = "0x" + "ab" * 20
TEST_ONLY_OTHER_TOKEN = "0x" + "cd" * 20
TEST_ONLY_WALLET = "0x" + "12" * 20
TEST_ONLY_DECIMALS = 6
TEST_ONLY_THRESHOLD = Decimal("100")           # TEST_ONLY — never a production value
RAW_THRESHOLD = 100 * 10 ** TEST_ONLY_DECIMALS


def deployment(**kw) -> TokenDeployment:
    base = dict(chain_id=TEST_ONLY_CHAIN, contract_address=TEST_ONLY_TOKEN, decimals=TEST_ONLY_DECIMALS,
                provenance="TEST_ONLY fixture")
    base.update(kw)
    return TokenDeployment(**base)


def registry(*entries) -> DeploymentRegistry:
    return DeploymentRegistry(entries or (deployment(),))


def policies(*, enabled=True, minimum=TEST_ONLY_THRESHOLD, gating=True, chain_id=None, keys=None):
    table = ep.default_policies()
    for key in keys or [k for k, p in table.items() if p.access_mode is ep.AccessMode.FINCO_HOLDER]:
        table[key] = ep.EntitlementPolicy(key, ep.AccessMode.FINCO_HOLDER, minimum, True, enabled, chain_id)
    return ep.PolicySet(table, gating_enabled=gating)


class FakeReader:
    def __init__(self, balance=RAW_THRESHOLD, status=ObservationStatus.OBSERVED, age=0, raises=False):
        self.balance, self.status, self.age, self.raises = balance, status, age, raises
        self.calls: list[tuple] = []

    async def get_balance(self, chain_id, contract_address, wallet_address):
        self.calls.append((chain_id, contract_address, wallet_address))
        if self.raises:
            raise RuntimeError("provider exploded https://secret.example/key")
        if self.status is not ObservationStatus.OBSERVED:
            return RawBalance(self.status, reason="TEST_ONLY")
        return RawBalance(ObservationStatus.OBSERVED, self.balance, 123, NOW - timedelta(seconds=self.age))


def run(resource, wallet=WalletContext(TEST_ONLY_WALLET, True), *, policy_set=None, reg=None, reader=None):
    return asyncio.run(evaluate_resource_access(
        resource, wallet, policy_set=policy_set or policies(), registry=reg or registry(),
        reader=reader or FakeReader(), now=NOW))


HOLDER = ep.YIELD_HISTORY
VERIFIED = WalletContext(TEST_ONLY_WALLET, True)


# ── production defaults: nothing is active ───────────────────────────────────────────────────────
def test_production_defaults_are_unconfigured_off_and_unthresholded():
    assert DeploymentRegistry.from_environment({}).deployments == ()
    policy_set = ep.load_policy_set({})
    assert policy_set.gating_enabled is False and policy_set.config_error is False
    for key, policy in policy_set.policies.items():
        if policy.access_mode is ep.AccessMode.FINCO_HOLDER:
            assert (policy.enabled, policy.minimum_balance) == (False, None), key
    assert set(policy_set.policies) == set(ep.RESOURCE_KEYS)
    decision = run(HOLDER, policy_set=policy_set, reg=DeploymentRegistry.from_environment({}))
    assert decision.decision is Decision.INACTIVE and not decision.allowed


# ── public resource ──────────────────────────────────────────────────────────────────────────────
def test_public_resource_is_public_for_everyone_even_with_no_deployment_and_no_wallet():
    for wallet in (NO_WALLET, WalletContext(TEST_ONLY_WALLET, False), VERIFIED):
        d = run(ep.YIELD_BASIC, wallet, reg=DeploymentRegistry(()), policy_set=ep.load_policy_set({}))
        assert d.decision is Decision.ALLOW and d.reason_code == "PUBLIC_RESOURCE"


# ── wallet states ────────────────────────────────────────────────────────────────────────────────
def test_no_wallet_and_unverified_wallet_are_denied_without_any_balance_read():
    reader = FakeReader()
    assert run(HOLDER, NO_WALLET, reader=reader).reason_code == "WALLET_NOT_CONNECTED"
    d = run(HOLDER, WalletContext(TEST_ONLY_WALLET, False), reader=reader)
    assert (d.decision, d.reason_code) == (Decision.DENY, "WALLET_NOT_VERIFIED")
    assert reader.calls == []                                   # an unverified wallet is never even queried


def test_execution_preflight_requires_a_verified_wallet():
    p = ep.default_policies()[ep.YIELD_EXECUTION_PREFLIGHT]
    assert p.wallet_verified_required and p.access_mode is ep.AccessMode.FINCO_HOLDER
    with pytest.raises(ValueError):
        ep.EntitlementPolicy("x", ep.AccessMode.FINCO_HOLDER, None, False, True)


# ── deployment identity ──────────────────────────────────────────────────────────────────────────
def test_no_deployment_configured_denies():
    d = run(HOLDER, reg=DeploymentRegistry(()))
    assert (d.decision, d.reason_code) == (Decision.DENY, "NO_ACTIVE_DEPLOYMENT")


@pytest.mark.parametrize("bad", [
    dict(contract_address="0x1234"), dict(contract_address="not-an-address"), dict(chain_id=0),
    dict(chain_id="1"), dict(decimals=-1), dict(decimals=78), dict(provenance=" "),
    dict(token_standard="ERC-721"),
])
def test_malformed_deployment_is_rejected_and_poisons_the_registry(bad):
    raw = dict(chain_id=TEST_ONLY_CHAIN, contract_address=TEST_ONLY_TOKEN, decimals=TEST_ONLY_DECIMALS,
               provenance="TEST_ONLY")
    raw.update(bad)
    reg = DeploymentRegistry([raw])
    assert reg.resolve().status is ResolutionStatus.MALFORMED
    d = run(HOLDER, reg=reg)
    assert (d.decision, d.reason_code) == (Decision.DENY, "DEPLOYMENT_CONFIG_MALFORMED")


def test_env_deployment_without_provenance_cannot_activate_access():
    env = {DEPLOYMENTS_ENV: json.dumps([{"chain_id": TEST_ONLY_CHAIN, "contract_address": TEST_ONLY_TOKEN,
                                         "decimals": 6}])}
    assert DeploymentRegistry.from_environment(env).resolve().status is ResolutionStatus.MALFORMED
    assert DeploymentRegistry.from_environment({DEPLOYMENTS_ENV: "{not json"}).resolve().status \
        is ResolutionStatus.MALFORMED


def test_unsupported_chain_has_no_provider_and_denies():
    reader = JsonRpcTokenBalanceReader({TEST_ONLY_OTHER_CHAIN: "https://rpc.example.invalid"})
    obs = asyncio.run(observe_finco_balance(TEST_ONLY_WALLET, registry(), reader))
    assert obs.status is ObservationStatus.UNSUPPORTED_CHAIN and obs.balance_raw is None
    d = run(HOLDER, reader=reader)
    assert d.decision is Decision.DENY and d.reason_code == "UNSUPPORTED_CHAIN"


def test_conflicting_deployments_fail_safely():
    reg = registry(deployment(), deployment(contract_address=TEST_ONLY_OTHER_TOKEN))
    assert reg.resolve().status is ResolutionStatus.CONFLICT
    assert reg.resolve(TEST_ONLY_CHAIN).status is ResolutionStatus.CONFLICT
    assert run(HOLDER, reg=reg).reason_code == "CONFLICTING_DEPLOYMENTS"
    same_chain_decimals = registry(deployment(), deployment(decimals=18))
    assert same_chain_decimals.resolve().status is ResolutionStatus.CONFLICT


def test_identical_duplicate_entries_are_not_a_conflict():
    assert registry(deployment(), deployment()).resolve().resolved


def test_multiple_chains_need_an_explicit_selection():
    reg = registry(deployment(), deployment(chain_id=TEST_ONLY_OTHER_CHAIN, contract_address=TEST_ONLY_OTHER_TOKEN))
    assert reg.resolve().status is ResolutionStatus.AMBIGUOUS
    assert run(HOLDER, reg=reg).reason_code == "MULTIPLE_ACTIVE_CHAINS"
    selected = run(HOLDER, reg=reg, policy_set=policies(chain_id=TEST_ONLY_OTHER_CHAIN),
                   reader=FakeReader())
    assert selected.decision is Decision.ALLOW and selected.chain_id == TEST_ONLY_OTHER_CHAIN
    assert selected.contract_address == TEST_ONLY_OTHER_TOKEN
    assert reg.resolve(999).status is ResolutionStatus.NOT_FOUND


def test_inactive_deployment_is_not_used():
    reg = registry(deployment(status=DeploymentStatus.INACTIVE))
    assert reg.resolve().status is ResolutionStatus.NOT_CONFIGURED


def test_ticker_and_name_never_define_identity():
    a = deployment(display_symbol="FINCO", display_name="Finco")
    b = deployment(display_symbol="TOTALLY-DIFFERENT", display_name="x")
    assert a == b and a.identity == b.identity
    impostor = deployment(contract_address=TEST_ONLY_OTHER_TOKEN, display_symbol="FINCO", display_name="FINCO")
    assert impostor != a
    # a token that merely CALLS itself FINCO at another contract is not the configured deployment
    obs = asyncio.run(observe_finco_balance(TEST_ONLY_WALLET, registry(a), FakeReader()))
    spoofed = type(obs)(**{**obs.__dict__, "contract_address": impostor.contract_address})
    d = decide_resource_access(HOLDER, VERIFIED, policies(), registry(a), spoofed, now=NOW)
    assert (d.decision, d.reason_code) == (Decision.DENY, "OBSERVATION_IDENTITY_MISMATCH")


def test_wrong_contract_or_chain_or_wallet_or_decimals_observation_cannot_grant_access():
    good = asyncio.run(observe_finco_balance(TEST_ONLY_WALLET, registry(), FakeReader(balance=10 ** 12)))
    assert decide_resource_access(HOLDER, VERIFIED, policies(), registry(), good, now=NOW).allowed
    for change in (dict(contract_address=TEST_ONLY_OTHER_TOKEN), dict(chain_id=TEST_ONLY_OTHER_CHAIN),
                   dict(wallet_address="0x" + "99" * 20), dict(decimals=18)):
        bad = type(good)(**{**good.__dict__, **change})
        d = decide_resource_access(HOLDER, VERIFIED, policies(), registry(), bad, now=NOW)
        assert (d.decision, d.reason_code) == (Decision.DENY, "OBSERVATION_IDENTITY_MISMATCH"), change


# ── balance observation semantics ────────────────────────────────────────────────────────────────
def test_observed_zero_is_distinct_from_unavailable():
    zero = asyncio.run(observe_finco_balance(TEST_ONLY_WALLET, registry(), FakeReader(balance=0)))
    assert zero.observed and zero.observed_zero
    assert (zero.balance_raw, zero.normalized_balance) == (0, Decimal(0))
    for status in (ObservationStatus.RPC_UNAVAILABLE, ObservationStatus.BALANCE_UNAVAILABLE,
                   ObservationStatus.CHAIN_ID_MISMATCH):
        obs = asyncio.run(observe_finco_balance(TEST_ONLY_WALLET, registry(), FakeReader(status=status)))
        assert not obs.observed and obs.balance_raw is None and obs.normalized_balance is None
        assert obs.status is status


def test_unconfigured_missing_and_raising_reader_never_become_zero():
    for reg in (DeploymentRegistry(()), DeploymentRegistry([{"chain_id": 0}])):
        obs = asyncio.run(observe_finco_balance(TEST_ONLY_WALLET, reg, FakeReader()))
        assert obs.balance_raw is None and obs.normalized_balance is None and not obs.observed
    raised = asyncio.run(observe_finco_balance(TEST_ONLY_WALLET, registry(), FakeReader(raises=True)))
    assert raised.status is ObservationStatus.RPC_UNAVAILABLE and raised.balance_raw is None
    assert "secret.example" not in repr(raised)
    bad_wallet = asyncio.run(observe_finco_balance("nope", registry(), FakeReader()))
    assert bad_wallet.status is ObservationStatus.WALLET_MALFORMED and bad_wallet.balance_raw is None


def test_a_reader_claiming_success_without_proof_is_not_observed():
    class Liar:
        async def get_balance(self, *a):
            return RawBalance(ObservationStatus.OBSERVED, None, None, None)

    obs = asyncio.run(observe_finco_balance(TEST_ONLY_WALLET, registry(), Liar()))
    assert not obs.observed and obs.status is ObservationStatus.BALANCE_UNAVAILABLE


@pytest.mark.parametrize("decimals,raw,expected", [(6, 1_500_000, "1.5"), (18, 10 ** 18, "1"), (0, 7, "7"),
                                                   (8, 1, "1E-8")])
def test_decimals_normalisation_uses_the_canonical_deployment_decimals(decimals, raw, expected):
    reg = registry(deployment(decimals=decimals))
    obs = asyncio.run(observe_finco_balance(TEST_ONLY_WALLET, reg, FakeReader(balance=raw)))
    assert obs.normalized_balance == Decimal(expected) and obs.decimals == decimals


def test_json_rpc_reader_distinguishes_empty_answer_from_zero(monkeypatch):
    import app.protocol.balance_observation as bo

    async def fake_rpc(_client, _url, method, _params):
        return {"eth_chainId": hex(TEST_ONLY_CHAIN), "eth_call": "0x", "eth_blockNumber": "0x1"}[method]

    monkeypatch.setattr(bo, "_rpc_call", fake_rpc)
    reader = JsonRpcTokenBalanceReader({TEST_ONLY_CHAIN: "https://rpc.example.invalid"})
    raw = asyncio.run(reader.get_balance(TEST_ONLY_CHAIN, TEST_ONLY_TOKEN, TEST_ONLY_WALLET))
    assert raw.status is ObservationStatus.BALANCE_UNAVAILABLE and raw.balance_raw is None

    async def zero_rpc(_c, _u, method, _p):
        return {"eth_chainId": hex(TEST_ONLY_CHAIN), "eth_call": "0x" + "0" * 64, "eth_blockNumber": "0x1"}[method]

    monkeypatch.setattr(bo, "_rpc_call", zero_rpc)
    zero = asyncio.run(reader.get_balance(TEST_ONLY_CHAIN, TEST_ONLY_TOKEN, TEST_ONLY_WALLET))
    assert zero.status is ObservationStatus.OBSERVED and zero.balance_raw == 0

    async def wrong_chain(_c, _u, method, _p):
        return hex(1) if method == "eth_chainId" else "0x" + "0" * 64

    monkeypatch.setattr(bo, "_rpc_call", wrong_chain)
    mismatch = asyncio.run(reader.get_balance(TEST_ONLY_CHAIN, TEST_ONLY_TOKEN, TEST_ONLY_WALLET))
    assert mismatch.status is ObservationStatus.CHAIN_ID_MISMATCH and mismatch.balance_raw is None


# ── threshold decisions (TEST_ONLY thresholds) ───────────────────────────────────────────────────
def test_below_exactly_and_above_threshold():
    below = run(HOLDER, reader=FakeReader(balance=RAW_THRESHOLD - 1))
    assert (below.decision, below.reason_code) == (Decision.DENY, "BALANCE_BELOW_THRESHOLD")
    exact = run(HOLDER, reader=FakeReader(balance=RAW_THRESHOLD))
    assert (exact.decision, exact.reason_code) == (Decision.ALLOW, "BALANCE_AT_OR_ABOVE_THRESHOLD")
    above = run(HOLDER, reader=FakeReader(balance=RAW_THRESHOLD + 1))
    assert above.allowed and above.observed_balance == Decimal("100.000001")


def test_observed_zero_is_denied_below_threshold_not_treated_as_missing():
    d = run(HOLDER, reader=FakeReader(balance=0))
    assert (d.decision, d.reason_code, d.observed_balance) == (Decision.DENY, "BALANCE_BELOW_THRESHOLD", Decimal(0))


def test_protected_resource_fails_closed_when_balance_cannot_be_proven():
    for status in (ObservationStatus.RPC_UNAVAILABLE, ObservationStatus.BALANCE_UNAVAILABLE,
                   ObservationStatus.CHAIN_ID_MISMATCH):
        d = run(HOLDER, reader=FakeReader(status=status))
        assert d.decision is Decision.DENY and d.reason_code == status.value and not d.allowed
    assert run(HOLDER, reader=FakeReader(raises=True)).reason_code == "RPC_UNAVAILABLE"
    assert decide_resource_access(HOLDER, VERIFIED, policies(), registry(), None, now=NOW).reason_code \
        == "BALANCE_NOT_OBSERVED"


def test_stale_observation_is_denied():
    d = run(HOLDER, reader=FakeReader(age=10_000))
    assert (d.decision, d.reason_code) == (Decision.DENY, "BALANCE_STALE")


def test_threshold_finer_than_token_decimals_is_misconfiguration_not_rounding():
    d = run(HOLDER, policy_set=policies(minimum=Decimal("0.0000001")), reader=FakeReader())
    assert (d.decision, d.reason_code) == (Decision.DENY, "THRESHOLD_EXCEEDS_TOKEN_DECIMALS")


# ── activation / configuration ───────────────────────────────────────────────────────────────────
def test_gating_off_or_policy_disabled_is_inactive_and_never_reads_a_balance():
    reader = FakeReader()
    assert run(HOLDER, policy_set=policies(gating=False), reader=reader).reason_code == "TOKEN_GATING_OFF"
    assert run(HOLDER, policy_set=policies(enabled=False), reader=reader).reason_code == "POLICY_DISABLED"
    assert reader.calls == []


def test_enabled_policy_without_threshold_fails_closed():
    d = run(HOLDER, policy_set=policies(minimum=None))
    assert (d.decision, d.reason_code) == (Decision.DENY, "POLICY_THRESHOLD_UNSET")


def test_operator_override_activates_without_code_changes():
    env = {ep.GATING_ENABLED_ENV: "1",
           ep.POLICIES_ENV: json.dumps({HOLDER: {"enabled": True, "minimum_balance": "100"}})}
    policy_set = ep.load_policy_set(env)
    assert policy_set.policies[HOLDER].minimum_balance == TEST_ONLY_THRESHOLD
    assert policy_set.policies[ep.YIELD_ALERTS].enabled is False        # untouched resources stay inactive
    reg = DeploymentRegistry.from_environment({DEPLOYMENTS_ENV: json.dumps([
        {"chain_id": TEST_ONLY_CHAIN, "contract_address": TEST_ONLY_TOKEN, "decimals": 6,
         "provenance": "TEST_ONLY"}])})
    assert run(HOLDER, policy_set=policy_set, reg=reg, reader=FakeReader(balance=RAW_THRESHOLD)).allowed


@pytest.mark.parametrize("override", [
    {"yield.basic": {"enabled": False}},                       # public resources are not configurable
    {"yield.unknown": {"enabled": True}},
    {HOLDER: {"access_mode": "PUBLIC"}},                       # access mode is not operator-configurable
    {HOLDER: {"enabled": "yes"}},
    {HOLDER: {"minimum_balance": "-1"}},
    {HOLDER: {"minimum_balance": "NaN"}},
])
def test_invalid_operator_policy_config_fails_gated_resources_closed_but_not_public(override):
    policy_set = ep.load_policy_set({ep.GATING_ENABLED_ENV: "1", ep.POLICIES_ENV: json.dumps(override)})
    assert policy_set.config_error
    assert run(HOLDER, policy_set=policy_set).reason_code == "POLICY_CONFIG_INVALID"
    assert run(ep.YIELD_BASIC, policy_set=policy_set).allowed


def test_unknown_resource_is_denied():
    assert run("yield.nope").reason_code == "UNKNOWN_RESOURCE"


# ── boundaries ───────────────────────────────────────────────────────────────────────────────────
def test_evaluate_all_resources_reads_the_balance_once_per_gated_resource_and_keeps_basic_public():
    decisions = asyncio.run(evaluate_all_resources(
        VERIFIED, policy_set=policies(), registry=registry(), reader=FakeReader(), now=NOW))
    assert decisions[ep.YIELD_BASIC].allowed
    assert all(decisions[k].allowed for k in ep.RESOURCE_KEYS)


def test_entitlement_modules_are_isolated_from_the_math_and_from_signing():
    import app.protocol.balance_observation as bo
    import app.protocol.entitlement_evaluator as ev
    import app.protocol.entitlement_policy as pol
    import app.protocol.token_deployments as td
    forbidden = ("financial_engine", "finco_core", "finco_radar", "app.verified", "app.run_integrity",
                 "eth_sendTransaction", "eth_sign", "private_key", "personal_sign")
    for module in (bo, ev, pol, td):
        source = open(module.__file__, encoding="utf-8").read()
        for needle in forbidden:
            lines = [ln for ln in source.splitlines() if needle in ln and not ln.lstrip().startswith(("#", '"'))]
            assert not [ln for ln in lines if "import" in ln], (module.__name__, needle)


def test_no_production_token_identity_is_committed():
    import app.protocol.token_deployments as td
    src = open(td.__file__, encoding="utf-8").read()
    import re
    assert not re.findall(r"0x[0-9a-fA-F]{40}", src)
    assert DeploymentRegistry().deployments == ()
