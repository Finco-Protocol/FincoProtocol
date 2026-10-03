"""Crypto Utility V0 / Agent A — resource policy layer over the canonical token-entitlement authority.

Authority chain under test:
  wallet binding -> approved deployment (app.verified.token_entitlement) -> read-only balance evidence
  (P4ReadOnlyBalanceProvider / TokenBalanceEvidence) -> canonical evaluate_token_entitlement
  -> resource policy -> ALLOW / DENY / INACTIVE.

Every amount, address and chain id here is TEST_ONLY. None is, or may become, a production default:
production ships with ZERO approved deployments, gating OFF and no thresholds.
"""
from __future__ import annotations

import asyncio
import json
import re
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

import app.verified.token_entitlement as canon
from app.protocol import entitlement_policy as ep
from app.protocol.entitlement_evaluator import (
    FRESHNESS_ENV, NO_WALLET, Decision, WalletContext, decide_resource_access, evaluate_all_resources,
    evaluate_resource_access,
)
from app.protocol.token_deployments import ResolutionStatus, resolve_approved_deployment
from app.verified.token_entitlement import ApprovedFincoDeployment, BalanceEvidenceState, TokenBalanceEvidence

NOW = datetime(2026, 10, 1, 12, 0, tzinfo=timezone.utc)
CHAIN, OTHER_CHAIN = 31337, 31338
TOKEN, OTHER_TOKEN = "0x" + "ab" * 20, "0x" + "cd" * 20
WALLET, OTHER_WALLET = "0x" + "12" * 20, "0x" + "99" * 20
DECIMALS = 6
THRESHOLD = Decimal("100")                     # TEST_ONLY — never a production value
RAW = 100 * 10 ** DECIMALS
ENV = {FRESHNESS_ENV: "60"}
HOLDER = ep.YIELD_HISTORY
VERIFIED = WalletContext(WALLET, True, "user-1")


def approved(**kw) -> ApprovedFincoDeployment:
    base = dict(chain_id=CHAIN, token_address=TOKEN, standard="ERC-20", decimals=DECIMALS,
                provenance="TEST_ONLY fixture")
    base.update(kw)
    return ApprovedFincoDeployment(**base)


def policies(*, enabled=True, minimum=THRESHOLD, gating=True, chain_id=None):
    table = ep.default_policies()
    for key, policy in list(table.items()):
        if policy.access_mode is ep.AccessMode.FINCO_HOLDER:
            table[key] = ep.EntitlementPolicy(key, ep.AccessMode.FINCO_HOLDER, minimum, True, enabled, chain_id)
    return ep.PolicySet(table, gating_enabled=gating)


def evidence(raw=RAW, *, state=BalanceEvidenceState.AVAILABLE, age=0, **kw) -> TokenBalanceEvidence:
    base = dict(chain_id=CHAIN, token_address=TOKEN, wallet_address=WALLET, token_decimals=DECIMALS,
                balance_raw=None if state is not BalanceEvidenceState.AVAILABLE else raw,
                observed_at=NOW - timedelta(seconds=age), source="TEST_ONLY", state=state,
                reason=None if state is BalanceEvidenceState.AVAILABLE else "RPC_UNAVAILABLE")
    base.update(kw)
    return TokenBalanceEvidence(**base)


class FakeProvider:
    """A canonical TokenBalanceProvider test double (the real one is P4ReadOnlyBalanceProvider)."""

    def __init__(self, value=None, raises=False):
        self.value, self.raises, self.calls = value if value is not None else evidence(), raises, []

    async def balance_of(self, policy, wallet_address):
        self.calls.append((policy.chain_id, policy.token_address, wallet_address))
        if self.raises:
            raise RuntimeError("provider exploded https://secret.example/key")
        return self.value


def run(resource=HOLDER, wallet=VERIFIED, *, policy_set=None, provider=None, deployments=None, env=ENV):
    return asyncio.run(evaluate_resource_access(
        resource, wallet, policy_set=policy_set or policies(),
        provider=provider or FakeProvider(), approved=[approved()] if deployments is None else deployments,
        environ=env, now=NOW))


# ── existing authority preservation ──────────────────────────────────────────────────────────────
def test_production_authority_is_unchanged_zero_approved_deployments_gating_off_no_thresholds():
    assert canon.APPROVED_FINCO_DEPLOYMENTS == ()
    assert canon.get_production_policy() is None
    assert resolve_approved_deployment().status is ResolutionStatus.NOT_CONFIGURED
    policy_set = ep.load_policy_set({})
    assert policy_set.gating_enabled is False and policy_set.config_error is False
    for policy in policy_set.policies.values():
        if policy.access_mode is ep.AccessMode.FINCO_HOLDER:
            assert (policy.enabled, policy.minimum_balance) == (False, None)
    d = asyncio.run(evaluate_resource_access(HOLDER, VERIFIED, environ={}, now=NOW))
    assert d.decision is Decision.INACTIVE and not d.allowed       # nothing is granted merely by existing


def test_environment_configuration_alone_cannot_create_a_deployment_authority(monkeypatch):
    env = {"FINCO_TOKEN_DEPLOYMENTS_JSON": json.dumps([{"chain_id": CHAIN, "contract_address": TOKEN,
                                                        "decimals": 6, "provenance": "TEST_ONLY"}]),
           "FINCO_TOKEN_CHAIN_ID": str(CHAIN), "FINCO_TOKEN_ADDRESS": TOKEN, "FINCO_TOKEN_DECIMALS": "6",
           "FINCO_TOKEN_RPC_URL": "https://rpc.example.invalid", f"FINCO_TOKEN_RPC_URL_{CHAIN}": "https://x.invalid",
           "FINCO_ACCESS_MIN_BALANCE": "100", FRESHNESS_ENV: "60", ep.GATING_ENABLED_ENV: "1",
           ep.POLICIES_ENV: json.dumps({HOLDER: {"enabled": True, "minimum_balance": "100"}})}
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    assert canon.get_production_policy() is None                  # the existing B2.2 guarantee still holds
    assert resolve_approved_deployment().status is ResolutionStatus.NOT_CONFIGURED
    d = asyncio.run(evaluate_resource_access(HOLDER, VERIFIED, provider=FakeProvider(), now=NOW))
    assert (d.decision, d.reason_code) == (Decision.DENY, "NO_APPROVED_DEPLOYMENT") and not d.allowed


def test_only_the_approved_tuple_supplies_identity_the_modules_have_no_env_deployment_parsing():
    import app.protocol.entitlement_evaluator as ev
    import app.protocol.entitlement_policy as pol
    import app.protocol.token_deployments as td
    for module in (ev, pol, td):
        source = open(module.__file__, encoding="utf-8").read()
        assert "DEPLOYMENTS_JSON" not in source and not re.findall(r"0x[0-9a-fA-F]{40}", source)
        assert "eth_call" not in source and "httpx" not in source      # no second JSON-RPC stack


def test_no_signing_keys_transactions_or_execution_in_the_new_modules():
    import app.protocol.entitlement_evaluator as ev
    import app.protocol.entitlement_policy as pol
    import app.protocol.token_deployments as td
    banned = ("eth_sendTransaction", "eth_sign", "private_key", "personal_sign", "sendRawTransaction",
              "financial_engine", "finco_core", "finco_radar", "app.run_integrity")
    for module in (ev, pol, td):
        source = open(module.__file__, encoding="utf-8").read()
        imports = [ln for ln in source.splitlines() if ln.lstrip().startswith(("import ", "from "))]
        assert not [ln for ln in imports if any(b in ln for b in banned)], module.__name__
        for needle in ("eth_sendTransaction", "eth_sign", "private_key", "sendRawTransaction"):
            assert needle not in source


# ── deployment selection (multi-chain over the approved set) ─────────────────────────────────────
def test_zero_one_and_many_approved_deployments():
    assert resolve_approved_deployment(approved=[]).status is ResolutionStatus.NOT_CONFIGURED
    one = resolve_approved_deployment(approved=[approved()])
    assert one.resolved and one.deployment.token_address == TOKEN
    many = [approved(), approved(chain_id=OTHER_CHAIN, token_address=OTHER_TOKEN)]
    assert resolve_approved_deployment(approved=many).status is ResolutionStatus.AMBIGUOUS
    chosen = resolve_approved_deployment(OTHER_CHAIN, many)
    assert chosen.resolved and chosen.deployment.token_address == OTHER_TOKEN
    assert resolve_approved_deployment(999, many).status is ResolutionStatus.NOT_FOUND


def test_conflicting_approved_deployments_fail_safely():
    conflict = [approved(), approved(token_address=OTHER_TOKEN)]
    assert resolve_approved_deployment(approved=conflict).status is ResolutionStatus.CONFLICT
    assert resolve_approved_deployment(CHAIN, conflict).status is ResolutionStatus.CONFLICT
    assert resolve_approved_deployment(approved=[approved(), approved(decimals=18)]).status \
        is ResolutionStatus.CONFLICT
    assert run(deployments=conflict).reason_code == "CONFLICTING_DEPLOYMENTS"
    assert resolve_approved_deployment(approved=[approved(), approved()]).resolved   # identical duplicate


def test_explicit_chain_selection_in_the_policy_picks_the_right_contract():
    many = [approved(), approved(chain_id=OTHER_CHAIN, token_address=OTHER_TOKEN)]
    assert run(deployments=many).reason_code == "MULTIPLE_APPROVED_CHAINS"
    provider = FakeProvider(evidence(chain_id=OTHER_CHAIN, token_address=OTHER_TOKEN))
    d = run(deployments=many, policy_set=policies(chain_id=OTHER_CHAIN), provider=provider)
    assert d.allowed and (d.chain_id, d.token_address) == (OTHER_CHAIN, OTHER_TOKEN)


def test_malformed_deployment_cannot_even_be_constructed_in_the_canonical_authority():
    for bad in (dict(token_address="0x1234"), dict(chain_id=0), dict(decimals=78), dict(provenance=" "),
                dict(standard="ERC-721")):
        with pytest.raises(ValueError):
            approved(**bad)


# ── resource policy ──────────────────────────────────────────────────────────────────────────────
def test_public_resource_is_public_for_everyone_with_no_deployment_and_no_wallet():
    for wallet in (NO_WALLET, WalletContext(WALLET, False), VERIFIED):
        d = run(ep.YIELD_BASIC, wallet, deployments=[], policy_set=ep.load_policy_set({}))
        assert (d.decision, d.reason_code) == (Decision.ALLOW, "PUBLIC_RESOURCE")


def test_resource_keys_and_default_modes():
    table = ep.default_policies()
    # The Yield vocabulary is unchanged; Tokenized Markets / crypto API keys extend (never replace) it.
    assert set(ep.YIELD_RESOURCE_KEYS) == {
        "yield.basic", "yield.history", "yield.advanced_compare", "yield.alerts", "yield.execution_preflight"}
    assert set(table) == set(ep.RESOURCE_KEYS) == set(ep.YIELD_RESOURCE_KEYS) | {
        "tokenized.basic", "tokenized.history", "tokenized.dislocation", "crypto.api"}
    public_keys = {ep.YIELD_BASIC, ep.TOKENIZED_BASIC}
    for key in public_keys:
        assert table[key].access_mode is ep.AccessMode.PUBLIC
    for key in set(ep.RESOURCE_KEYS) - public_keys:
        assert table[key].access_mode is ep.AccessMode.FINCO_HOLDER and table[key].wallet_verified_required
    with pytest.raises(ValueError):
        ep.EntitlementPolicy("x", ep.AccessMode.FINCO_HOLDER, None, False, True)


def test_gating_off_or_policy_disabled_is_inactive_and_never_reads_a_balance():
    provider = FakeProvider()
    assert run(policy_set=policies(gating=False), provider=provider).reason_code == "TOKEN_GATING_OFF"
    assert run(policy_set=policies(enabled=False), provider=provider).reason_code == "POLICY_DISABLED"
    assert provider.calls == []


def test_enabled_policy_without_threshold_or_freshness_config_fails_closed():
    assert run(policy_set=policies(minimum=None)).reason_code == "POLICY_THRESHOLD_UNSET"
    d = run(env={})
    assert (d.decision, d.reason_code) == (Decision.DENY, "TOKEN_CONFIGURATION_UNAVAILABLE")


def test_below_exactly_and_above_threshold():
    below = run(provider=FakeProvider(evidence(RAW - 1)))
    assert (below.decision, below.reason_code, below.entitlement_state) == (
        Decision.DENY, "BALANCE_BELOW_THRESHOLD", "INACTIVE")
    exact = run(provider=FakeProvider(evidence(RAW)))
    assert (exact.decision, exact.entitlement_state) == (Decision.ALLOW, "ACTIVE")
    above = run(provider=FakeProvider(evidence(RAW + 1)))
    assert above.allowed and above.observed_balance == Decimal("100.000001")


def test_entitled_wallet_reaches_every_gated_resource_and_the_public_one():
    decisions = asyncio.run(evaluate_all_resources(
        VERIFIED, policy_set=policies(), provider=FakeProvider(), approved=[approved()],
        environ=ENV, now=NOW))
    assert all(decisions[key].allowed for key in ep.RESOURCE_KEYS)


def test_threshold_finer_than_token_decimals_is_misconfiguration_not_rounding():
    d = run(policy_set=policies(minimum=Decimal("0.0000001")))
    assert (d.decision, d.reason_code) == (Decision.DENY, "THRESHOLD_EXCEEDS_TOKEN_DECIMALS")


@pytest.mark.parametrize("decimals,raw_value,minimum", [(18, 10 ** 18, "1"), (0, 7, "7"), (8, 150_000_000, "1.5")])
def test_decimals_normalisation_uses_the_approved_deployment_decimals(decimals, raw_value, minimum):
    d = run(deployments=[approved(decimals=decimals)], policy_set=policies(minimum=Decimal(minimum)),
            provider=FakeProvider(evidence(raw_value, token_decimals=decimals)))
    assert d.allowed and d.observed_balance == Decimal(raw_value).scaleb(-decimals)


# ── identity ─────────────────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("change", [dict(chain_id=OTHER_CHAIN), dict(token_address=OTHER_TOKEN),
                                    dict(wallet_address=OTHER_WALLET), dict(token_decimals=18)])
def test_wrong_chain_contract_wallet_or_decimals_evidence_is_denied(change):
    d = run(provider=FakeProvider(evidence(**change)))
    assert (d.decision, d.reason_code) == (Decision.DENY, "BALANCE_IDENTITY_MISMATCH") and not d.allowed


def test_ticker_and_name_cannot_grant_access():
    # identity is the exact (chain, contract); the approved type has no symbol/name field at all
    assert not {"symbol", "name", "ticker", "display_symbol"} & set(ApprovedFincoDeployment.__dataclass_fields__)
    impostor = FakeProvider(evidence(token_address=OTHER_TOKEN))          # a token that calls itself FINCO
    assert run(provider=impostor).reason_code == "BALANCE_IDENTITY_MISMATCH"


# ── evidence semantics ───────────────────────────────────────────────────────────────────────────
def test_explicit_observed_zero_stays_zero_and_is_below_threshold():
    d = run(provider=FakeProvider(evidence(0)))
    assert (d.decision, d.reason_code, d.observed_balance) == (Decision.DENY, "BALANCE_BELOW_THRESHOLD", Decimal(0))


def test_unavailable_evidence_stays_unavailable_never_zero():
    d = run(provider=FakeProvider(evidence(state=BalanceEvidenceState.UNAVAILABLE)))
    assert (d.decision, d.reason_code, d.observed_balance) == (Decision.DENY, "RPC_UNAVAILABLE", None)
    assert d.entitlement_state == "UNAVAILABLE"


def test_missing_evidence_or_a_raising_provider_never_becomes_zero():
    missing = run(provider=FakeProvider(raises=True))
    assert missing.decision is Decision.DENY and missing.observed_balance is None
    assert missing.entitlement_state == "UNAVAILABLE" and "secret.example" not in repr(missing)
    none = decide_resource_access(HOLDER, VERIFIED, policies(), resolve_approved_deployment(approved=[approved()]),
                                  None, freshness_seconds=60, now=NOW)
    assert none.decision is Decision.DENY and none.observed_balance is None


def test_stale_evidence_is_stale():
    assert run(provider=FakeProvider(evidence(age=61))).reason_code == "BALANCE_STALE"
    assert run(provider=FakeProvider(evidence(age=60))).allowed                     # boundary matches B2.2
    assert run(provider=FakeProvider(evidence(state=BalanceEvidenceState.STALE))).reason_code == "BALANCE_STALE"


def test_protected_resource_fails_closed_when_token_authority_is_unavailable():
    assert run(deployments=[]).decision is Decision.DENY
    assert run(provider=FakeProvider(raises=True)).decision is Decision.DENY
    assert run(env={}).decision is Decision.DENY


# ── wallet ───────────────────────────────────────────────────────────────────────────────────────
def test_no_wallet_and_unverified_wallet_are_denied_without_any_balance_read():
    provider = FakeProvider()
    assert run(wallet=NO_WALLET, provider=provider).reason_code == "WALLET_NOT_CONNECTED"
    d = run(wallet=WalletContext(WALLET, False), provider=provider)
    assert (d.decision, d.reason_code) == (Decision.DENY, "WALLET_NOT_VERIFIED")
    assert provider.calls == []


def test_verified_wallet_is_evaluated_through_the_canonical_provider():
    provider = FakeProvider()
    assert run(provider=provider).allowed
    assert provider.calls == [(CHAIN, TOKEN, WALLET)]


# ── the real read path is the EXISTING P4 reader (no second JSON-RPC stack) ───────────────────────
def test_default_provider_uses_the_existing_p4_reader_and_keeps_zero_and_unavailable_distinct(monkeypatch):
    import app.protocol.token_balance as tb

    async def fake_read(wallet_address, config):
        assert (config.chain_id, config.token_address, config.decimals_override) == (CHAIN, TOKEN, DECIMALS)
        return fake_read.result

    monkeypatch.setattr(tb, "read_token_balance", fake_read)
    env = {**ENV, f"FINCO_TOKEN_RPC_URL_{CHAIN}": "https://rpc.example.invalid"}

    def observation(status, raw=None):
        return tb.TokenObservation(WALLET, CHAIN, TOKEN, raw, DECIMALS,
                                   None if raw is None else Decimal(raw).scaleb(-DECIMALS), 1, NOW, status)

    def go():
        return asyncio.run(evaluate_resource_access(HOLDER, VERIFIED, policy_set=policies(), approved=[approved()],
                                                    environ=env, now=NOW))

    fake_read.result = observation(tb.STATUS_ENTITLED, RAW)
    assert go().allowed
    fake_read.result = observation(tb.STATUS_INSUFFICIENT, 0)
    zero = go()
    assert (zero.decision, zero.observed_balance, zero.reason_code) == (Decision.DENY, Decimal(0), "BALANCE_BELOW_THRESHOLD")
    fake_read.result = observation(tb.STATUS_RPC_UNAVAILABLE)
    down = go()
    assert (down.decision, down.observed_balance, down.reason_code) == (Decision.DENY, None, tb.STATUS_RPC_UNAVAILABLE)
    no_rpc = asyncio.run(evaluate_resource_access(HOLDER, VERIFIED, policy_set=policies(), approved=[approved()],
                                                  environ=ENV, now=NOW))
    assert no_rpc.decision is Decision.DENY and no_rpc.entitlement_state == "UNAVAILABLE"


# ── operator policy configuration ────────────────────────────────────────────────────────────────
def test_operator_policy_override_activates_thresholds_without_code_changes():
    policy_set = ep.load_policy_set({ep.GATING_ENABLED_ENV: "1",
                                     ep.POLICIES_ENV: json.dumps({HOLDER: {"enabled": True, "minimum_balance": "100"}})})
    assert policy_set.policies[HOLDER].minimum_balance == THRESHOLD
    assert policy_set.policies[ep.YIELD_ALERTS].enabled is False
    assert run(policy_set=policy_set).allowed


@pytest.mark.parametrize("override", [
    {"yield.basic": {"enabled": False}}, {"yield.unknown": {"enabled": True}},
    {HOLDER: {"access_mode": "PUBLIC"}}, {HOLDER: {"enabled": "yes"}},
    {HOLDER: {"minimum_balance": "-1"}}, {HOLDER: {"minimum_balance": "NaN"}},
])
def test_invalid_operator_policy_fails_gated_resources_closed_but_not_public(override):
    policy_set = ep.load_policy_set({ep.GATING_ENABLED_ENV: "1", ep.POLICIES_ENV: json.dumps(override)})
    assert policy_set.config_error
    assert run(policy_set=policy_set).reason_code == "POLICY_CONFIG_INVALID"
    assert run(ep.YIELD_BASIC, policy_set=policy_set).allowed


def test_unknown_resource_is_denied():
    assert run("yield.nope").reason_code == "UNKNOWN_RESOURCE"


# ── state mapping is explicit ────────────────────────────────────────────────────────────────────
def test_canonical_entitlement_states_map_to_exactly_one_resource_decision_each():
    from app.verified.entitlement import EntitlementState
    seen = {
        EntitlementState.ACTIVE: run(provider=FakeProvider(evidence(RAW))),
        EntitlementState.INACTIVE: run(provider=FakeProvider(evidence(RAW - 1))),
        EntitlementState.STALE: run(provider=FakeProvider(evidence(age=999))),
        EntitlementState.UNAVAILABLE: run(provider=FakeProvider(evidence(state=BalanceEvidenceState.UNAVAILABLE))),
        EntitlementState.TOKEN_CONFIGURATION_UNAVAILABLE: run(env={}),
    }
    assert seen[EntitlementState.ACTIVE].decision is Decision.ALLOW
    for state in (EntitlementState.INACTIVE, EntitlementState.STALE, EntitlementState.UNAVAILABLE):
        assert seen[state].decision is Decision.DENY and seen[state].entitlement_state == state.value
    assert seen[EntitlementState.TOKEN_CONFIGURATION_UNAVAILABLE].decision is Decision.DENY
    # resource-level INACTIVE means "gate off, nothing evaluated" and carries NO entitlement state
    off = run(policy_set=policies(gating=False))
    assert off.decision is Decision.INACTIVE and off.entitlement_state is None
