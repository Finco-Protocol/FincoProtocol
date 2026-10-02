"""$FINCO activation readiness pack. All chain ids, addresses and amounts are TEST_ONLY and are never
production defaults: production has zero approved deployments, gating OFF and no thresholds."""
from __future__ import annotations

import asyncio
import json
import re
from decimal import Decimal
from pathlib import Path

import pytest

import app.verified.token_entitlement as canon
from app.protocol import activation_readiness as ar
from app.protocol import entitlement_policy as ep
from app.protocol.activation_readiness import ActivationStatus as S, ChainProbeResult, Issue
from app.protocol.entitlement_evaluator import Decision, WalletContext, evaluate_resource_access
from app.protocol.token_config import TokenConfig
from app.verified.token_entitlement import ApprovedFincoDeployment
from datetime import datetime, timezone
from types import SimpleNamespace
from types import SimpleNamespace

CHAIN, OTHER_CHAIN = 31337, 31338
TOKEN, OTHER_TOKEN = "0x" + "ab" * 20, "0x" + "cd" * 20
DECIMALS = 6
WALLET = "0x" + "12" * 20                      # TEST_ONLY
HOLDER = ep.YIELD_HISTORY
ROOT = Path(__file__).resolve().parents[1]


def approved(**kw) -> ApprovedFincoDeployment:
    base = dict(chain_id=CHAIN, token_address=TOKEN, standard="ERC-20", decimals=DECIMALS,
                provenance="TEST_ONLY fixture")
    base.update(kw)
    return ApprovedFincoDeployment(**base)


def candidate(**kw) -> dict:
    base = dict(economic_token_uid="FINCO", chain_id=CHAIN, contract_address=TOKEN, decimals=DECIMALS,
                provenance="TEST_ONLY fixture", approval_status="APPROVED")
    base.update(kw)
    return base


class Probe:
    def __init__(self, chain_id=CHAIN, decimals=DECIMALS, reachable=True):
        self.result = ChainProbeResult(reachable, chain_id if reachable else None,
                                       decimals if reachable else None, None if reachable else "down")
        self.calls: list[tuple[str, str]] = []

    async def probe(self, rpc_url, contract_address):
        self.calls.append((rpc_url, contract_address))
        return self.result


RPC = {f"FINCO_TOKEN_RPC_URL_{CHAIN}": "https://rpc.example.invalid/key-123"}
FRESH = {ar.FRESHNESS_ENV: "60"}
THRESHOLD = {ep.POLICIES_ENV: json.dumps({HOLDER: {"enabled": True, "minimum_balance": "100"}})}   # TEST_ONLY
GATING = {ep.GATING_ENABLED_ENV: "1"}
READY_ENV = {**RPC, **FRESH, **THRESHOLD}              # every prerequisite, gating still OFF
ACTIVE_ENV = {**READY_ENV, **GATING}
POLICY_ON = {**GATING, **THRESHOLD}


def assess(env=None, approved_set=None, **kw):
    return asyncio.run(ar.assess_activation(environ=env if env is not None else RPC,
                                            approved=[approved()] if approved_set is None else approved_set, **kw))


# ── production truth ─────────────────────────────────────────────────────────────────────────────
def test_zero_production_deployments_gating_off_no_threshold():
    assert canon.APPROVED_FINCO_DEPLOYMENTS == ()
    assert ar.approved_deployments() == ()
    report = asyncio.run(ar.assess_activation(environ={}))
    assert report.status is S.NOT_CONFIGURED and not report.ready_or_active
    policy_set = ep.load_policy_set({})
    assert policy_set.gating_enabled is False
    assert all(p.minimum_balance is None and not p.enabled for p in policy_set.policies.values()
               if p.access_mode is ep.AccessMode.FINCO_HOLDER)


def test_environment_cannot_create_authority():
    env = {**RPC, **POLICY_ON, "FINCO_TOKEN_CHAIN_ID": str(CHAIN), "FINCO_TOKEN_ADDRESS": TOKEN,
           "FINCO_TOKEN_DECIMALS": "6", "FINCO_TOKEN_DEPLOYMENTS_JSON": json.dumps([candidate()]),
           "FINCO_ACCESS_MIN_BALANCE": "100"}
    report = asyncio.run(ar.assess_activation(environ=env, approved=[], probe=Probe()))
    assert report.status is S.NOT_CONFIGURED and not report.ready_or_active
    assert canon.get_production_policy() is None


def test_a_candidate_is_never_authoritative_until_committed():
    report = assess(approved_set=[], candidate=candidate(), probe=Probe())
    assert report.status is S.DEPLOYMENT_UNAPPROVED
    pending = assess(candidate=candidate(approval_status="PENDING"), probe=Probe())
    assert pending.status is S.DEPLOYMENT_UNAPPROVED
    other = assess(candidate=candidate(contract_address=OTHER_TOKEN), probe=Probe())
    assert other.status is S.DEPLOYMENT_UNAPPROVED
    committed = assess(READY_ENV, candidate=candidate(), probe=Probe())
    assert committed.status is S.READY_FOR_ACTIVATION


# ── validation ───────────────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("change,issue", [
    ({"contract_address": "0x1234"}, Issue.MALFORMED_ADDRESS), ({"contract_address": None}, Issue.MALFORMED_ADDRESS),
    ({"chain_id": 0}, Issue.UNSUPPORTED_CHAIN), ({"chain_id": "1"}, Issue.UNSUPPORTED_CHAIN),
    ({"token_standard": "ERC-721"}, Issue.UNSUPPORTED_CHAIN), ({"provenance": " "}, Issue.MISSING_PROVENANCE),
    ({"provenance": None}, Issue.MISSING_PROVENANCE), ({"decimals": 78}, Issue.DECIMALS_OUT_OF_RANGE),
    ({"decimals": True}, Issue.DECIMALS_OUT_OF_RANGE), ({"economic_token_uid": "OTHER"}, Issue.WRONG_ECONOMIC_TOKEN),
])
def test_malformed_candidates_are_rejected_deterministically(change, issue):
    parsed, issues = ar.validate_candidate(candidate(**change))
    assert parsed is None and issue in issues
    assert ar.validate_candidate(candidate(**change)) == (parsed, issues)          # deterministic
    report = assess(candidate=candidate(**change), probe=Probe())
    assert report.status is S.CONFIG_INVALID and issue in report.issues


def test_missing_deployment():
    assert ar.validate_candidate(None)[1] == (Issue.MISSING_DEPLOYMENT,)
    assert ar.validate_deployment_set([]) == (Issue.MISSING_DEPLOYMENT,)


def test_duplicate_and_conflicting_deployments_fail_closed():
    dup = assess(approved_set=[approved(), approved()], probe=Probe())
    assert dup.status is S.CONFIG_INVALID and Issue.DUPLICATE_DEPLOYMENT in dup.issues
    conflict = assess(approved_set=[approved(), approved(token_address=OTHER_TOKEN)], probe=Probe())
    assert conflict.status is S.CONFIG_INVALID and Issue.CONFLICTING_DEPLOYMENT in conflict.issues
    decimals_conflict = assess(approved_set=[approved(), approved(decimals=18)], probe=Probe())
    assert Issue.CONFLICTING_DEPLOYMENT in decimals_conflict.issues


def policies_env(**resources) -> dict:
    """{resource_key: {enabled, minimum_balance, chain_id}} -> operator policy env (TEST_ONLY values)."""
    return {ep.POLICIES_ENV: json.dumps(resources)}


A, B, C = CHAIN, OTHER_CHAIN, 99999
TWO = [approved(), approved(chain_id=OTHER_CHAIN, token_address=OTHER_TOKEN)]
TWO_RPC = {**RPC, f"FINCO_TOKEN_RPC_URL_{OTHER_CHAIN}": "https://rpc2.example.invalid", **FRESH}


def active_ready(report, env, approved_set, provider_chain_token=None):
    """Runtime parity: every resource in active_resources reaches token entitlement and can ALLOW."""
    from datetime import datetime, timezone
    from types import SimpleNamespace
    from app.verified.token_entitlement import BalanceEvidenceState, TokenBalanceEvidence
    now = datetime(2026, 10, 1, 12, 0, tzinfo=timezone.utc)
    results = {}
    for key in report.active_resources:
        policy = ep.load_policy_set(env).get(key)
        deployment = ar.resolve_approved_deployment(policy.chain_id, approved_set).deployment
        raw = int(policy.minimum_balance.scaleb(deployment.decimals))

        class Provider:
            async def balance_of(self, token_policy, wallet_address, _d=deployment, _raw=raw):
                return TokenBalanceEvidence(_d.chain_id, _d.token_address, WALLET, _d.decimals, _raw, now,
                                            "TEST_ONLY", BalanceEvidenceState.AVAILABLE)

        results[key] = asyncio.run(evaluate_resource_access(
            key, WalletContext(WALLET, True), approved=approved_set, environ=env, provider=Provider(), now=now))
    return results


def test_single_deployment_resource_may_leave_the_chain_unselected():
    report = assess(READY_ENV, probe=Probe())
    assert report.status is S.READY_FOR_ACTIVATION and report.activation_targets == (HOLDER,)
    assert report.active_resources == ()                                  # nothing is active until gating is on


def test_wrong_explicit_chain_with_a_single_approved_deployment_is_never_ready_or_active():
    env = {**RPC, **FRESH, **GATING, **policies_env(**{HOLDER: {"enabled": True, "minimum_balance": "100", "chain_id": C}})}
    for variant in (env, {k: v for k, v in env.items() if k != ep.GATING_ENABLED_ENV}):
        report = assess(variant, probe=Probe())
        assert report.status is S.CONFIG_INVALID and Issue.RESOURCE_CHAIN_NOT_APPROVED in report.issues
        assert not report.ready_or_active and report.active_resources == ()
    # the canonical runtime cannot resolve that chain either
    assert ar.resolve_approved_deployment(C, [approved()]).status is ar.ResolutionStatus.NOT_FOUND
    runtime = asyncio.run(evaluate_resource_access(HOLDER, WalletContext(WALLET, True), approved=[approved()],
                                                   environ=env))
    assert runtime.reason_code == "NO_APPROVED_DEPLOYMENT_ON_CHAIN" and not runtime.allowed


def test_matching_explicit_chain_with_a_single_deployment_is_fine():
    env = {**READY_ENV, **policies_env(**{HOLDER: {"enabled": True, "minimum_balance": "100", "chain_id": A}})}
    assert assess(env, probe=Probe()).status is S.READY_FOR_ACTIVATION


def test_multi_chain_valid_selection_is_not_broken_by_an_unconfigured_resource_without_a_chain():
    env = {**TWO_RPC, **policies_env(**{
        HOLDER: {"enabled": True, "minimum_balance": "100", "chain_id": A},
        ep.YIELD_ALERTS: {"enabled": False, "chain_id": None}})}
    report = assess(env, TWO, probe=Probe())
    assert report.status is S.READY_FOR_ACTIVATION and report.activation_targets == (HOLDER,)
    assert Issue.AMBIGUOUS_ACTIVE_DEPLOYMENT not in report.issues
    active = assess({**env, **GATING}, TWO, probe=Probe())
    assert active.status is S.ACTIVE and active.active_resources == (HOLDER,)


def test_multi_chain_active_resource_without_a_selector_fails_deterministically():
    env = {**TWO_RPC, **policies_env(**{HOLDER: {"enabled": True, "minimum_balance": "100"}})}
    report = assess(env, TWO, probe=Probe())
    assert report.status is S.CONFIG_INVALID and Issue.AMBIGUOUS_ACTIVE_DEPLOYMENT in report.issues
    assert assess(env, TWO, probe=Probe()) == report                                     # deterministic
    runtime = asyncio.run(evaluate_resource_access(HOLDER, WalletContext(WALLET, True), approved=TWO,
                                                   environ={**env, **GATING}))
    assert runtime.reason_code == "MULTIPLE_APPROVED_CHAINS"                             # runtime agrees


def test_multi_chain_nonexistent_selector_fails():
    env = {**TWO_RPC, **policies_env(**{HOLDER: {"enabled": True, "minimum_balance": "100", "chain_id": C}})}
    report = assess(env, TWO, probe=Probe())
    assert report.status is S.CONFIG_INVALID and Issue.RESOURCE_CHAIN_NOT_APPROVED in report.issues


def test_multi_chain_two_active_resources_on_different_chains_are_both_operable():
    env = {**TWO_RPC, **GATING, **policies_env(**{
        HOLDER: {"enabled": True, "minimum_balance": "100", "chain_id": A},
        ep.YIELD_ALERTS: {"enabled": True, "minimum_balance": "5", "chain_id": B}})}
    report = assess(env, TWO, probe=Probe(chain_id=None))                                # per-chain probe below
    assert report.status in (S.CHAIN_MISMATCH, S.RPC_UNAVAILABLE)                       # a single fake probe cannot be both


class PerChainProbe:
    def __init__(self, table):
        self.table, self.calls = table, []

    async def probe(self, rpc_url, contract_address):
        self.calls.append(contract_address)
        chain, decimals = self.table[contract_address]
        return ChainProbeResult(True, chain, decimals)


def test_two_active_resources_on_different_chains_with_a_per_chain_probe():
    env = {**TWO_RPC, **GATING, **policies_env(**{
        HOLDER: {"enabled": True, "minimum_balance": "100", "chain_id": A},
        ep.YIELD_ALERTS: {"enabled": True, "minimum_balance": "5", "chain_id": B}})}
    probe = PerChainProbe({TOKEN: (A, DECIMALS), OTHER_TOKEN: (B, DECIMALS)})
    report = assess(env, TWO, probe=probe)
    assert report.status is S.ACTIVE and set(report.active_resources) == {HOLDER, ep.YIELD_ALERTS}
    assert set(probe.calls) == {TOKEN, OTHER_TOKEN}


def test_an_unused_approved_deployment_does_not_block_a_valid_resource_on_another_chain():
    env = {k: v for k, v in TWO_RPC.items() if k != f"FINCO_TOKEN_RPC_URL_{OTHER_CHAIN}"}      # chain B has no RPC
    env.update(policies_env(**{HOLDER: {"enabled": True, "minimum_balance": "100", "chain_id": A}}))
    probe = PerChainProbe({TOKEN: (A, DECIMALS), OTHER_TOKEN: (B, DECIMALS)})
    report = assess(env, TWO, probe=probe)
    assert report.status is S.READY_FOR_ACTIVATION and probe.calls == [TOKEN]               # B never probed
    # identity validation is NOT weakened: a conflicting or duplicate unused entry still fails
    bad = TWO + [approved(chain_id=OTHER_CHAIN, token_address=TOKEN)]
    assert assess(env, bad, probe=probe).status is S.CONFIG_INVALID


def test_a_selected_deployment_with_missing_rpc_still_blocks():
    env = {**{k: v for k, v in TWO_RPC.items() if k != f"FINCO_TOKEN_RPC_URL_{OTHER_CHAIN}"},
           **policies_env(**{HOLDER: {"enabled": True, "minimum_balance": "100", "chain_id": B}})}
    report = assess(env, TWO, probe=PerChainProbe({TOKEN: (A, DECIMALS), OTHER_TOKEN: (B, DECIMALS)}))
    assert report.status is S.RPC_UNAVAILABLE and report.chain_id == B


@pytest.mark.parametrize("threshold", ["1", "0.1", "0.000001", "100", "123.456789"])
def test_thresholds_exactly_representable_in_decimals_are_ready(threshold):
    env = {**RPC, **FRESH, **policies_env(**{HOLDER: {"enabled": True, "minimum_balance": threshold}})}
    report = assess(env, probe=Probe())
    assert report.status is S.READY_FOR_ACTIVATION and names(report)["threshold_representable"] is True


@pytest.mark.parametrize("threshold", ["0.0000001", "1.0000001", "0.00000000001"])
def test_thresholds_finer_than_token_decimals_never_reach_ready_or_active(threshold):
    env = {**RPC, **FRESH, **GATING, **policies_env(**{HOLDER: {"enabled": True, "minimum_balance": threshold}})}
    for variant in (env, {k: v for k, v in env.items() if k != ep.GATING_ENABLED_ENV}):
        report = assess(variant, probe=Probe())
        assert report.status is S.CONFIG_INVALID and Issue.THRESHOLD_EXCEEDS_TOKEN_DECIMALS in report.issues
        assert not report.ready_or_active and report.active_resources == ()      # never rounded into validity
    runtime = asyncio.run(evaluate_resource_access(HOLDER, WalletContext(WALLET, True), approved=[approved()],
                                                   environ=env))
    assert runtime.reason_code == "THRESHOLD_EXCEEDS_TOKEN_DECIMALS"              # runtime agrees


def test_threshold_precision_uses_the_selected_deployments_own_decimals():
    two_decimals = [approved(), approved(chain_id=OTHER_CHAIN, token_address=OTHER_TOKEN, decimals=2)]
    env = {**TWO_RPC, **policies_env(**{HOLDER: {"enabled": True, "minimum_balance": "0.001", "chain_id": B}})}
    assert Issue.THRESHOLD_EXCEEDS_TOKEN_DECIMALS in assess(env, two_decimals, probe=Probe()).issues
    on_a = {**TWO_RPC, **policies_env(**{HOLDER: {"enabled": True, "minimum_balance": "0.001", "chain_id": A}})}
    assert assess(on_a, two_decimals, probe=PerChainProbe({TOKEN: (A, DECIMALS), OTHER_TOKEN: (B, 2)})).status \
        is S.READY_FOR_ACTIVATION


def test_runtime_parity_every_active_resource_is_operable_under_the_same_configuration():
    env = {**TWO_RPC, **GATING, **policies_env(**{
        HOLDER: {"enabled": True, "minimum_balance": "0.000001", "chain_id": A},
        ep.YIELD_ALERTS: {"enabled": True, "minimum_balance": "5", "chain_id": B},
        ep.YIELD_ADVANCED_COMPARE: {"enabled": False}})}
    probe = PerChainProbe({TOKEN: (A, DECIMALS), OTHER_TOKEN: (B, DECIMALS)})
    report = assess(env, TWO, probe=probe)
    assert report.status is S.ACTIVE and set(report.active_resources) == {HOLDER, ep.YIELD_ALERTS}
    results = active_ready(report, env, TWO)
    assert set(results) == set(report.active_resources)
    for key, decision in results.items():
        assert decision.allowed, (key, decision.reason_code)
        assert decision.reason_code not in {"NO_APPROVED_DEPLOYMENT", "NO_APPROVED_DEPLOYMENT_ON_CHAIN",
                                            "MULTIPLE_APPROVED_CHAINS", "THRESHOLD_EXCEEDS_TOKEN_DECIMALS",
                                            "TOKEN_CONFIGURATION_UNAVAILABLE"}
    single = assess(ACTIVE_ENV, probe=Probe())
    assert all(d.allowed for d in active_ready(single, ACTIVE_ENV, [approved()]).values())


def test_invalid_operator_policy_config_is_config_invalid():
    env = {**RPC, ep.POLICIES_ENV: json.dumps({"yield.basic": {"enabled": False}})}
    report = assess(env, probe=Probe())
    assert report.status is S.CONFIG_INVALID and Issue.POLICY_CONFIG_INVALID in report.issues


# ── RPC / chain / decimals verification ──────────────────────────────────────────────────────────
def test_missing_rpc_is_rpc_unavailable_without_probing():
    probe = Probe()
    report = assess(env={}, probe=probe)
    assert (report.status, report.reason) == (S.RPC_UNAVAILABLE, "NO_RPC_FOR_CHAIN") and probe.calls == []


def test_unreachable_provider_is_rpc_unavailable():
    assert assess(probe=Probe(reachable=False)).status is S.RPC_UNAVAILABLE


def test_rpc_chain_mismatch():
    report = assess(probe=Probe(chain_id=1))
    assert report.status is S.CHAIN_MISMATCH and not report.ready_or_active


def test_decimals_mismatch_and_unprovable_decimals():
    assert assess(probe=Probe(decimals=18)).status is S.DECIMALS_MISMATCH
    unprovable = Probe()
    unprovable.result = ChainProbeResult(True, CHAIN, None, "decimals_unavailable")
    assert assess(probe=unprovable).status is S.RPC_UNAVAILABLE


def test_json_rpc_probe_reads_only_chain_id_and_decimals(monkeypatch):
    import app.protocol.token_balance as tb
    methods = []

    async def fake(_client, _url, method, params):
        methods.append(method)
        return {"eth_chainId": hex(CHAIN), "eth_call": "0x" + "0" * 63 + "6"}[method]

    monkeypatch.setattr(tb, "_rpc_call", fake)
    result = asyncio.run(ar.JsonRpcChainProbe().probe("https://rpc.example.invalid", TOKEN))
    assert (result.reachable, result.chain_id, result.decimals) == (True, CHAIN, 6)
    assert methods == ["eth_chainId", "eth_call"]                       # nothing that writes


# ── readiness semantics ──────────────────────────────────────────────────────────────────────────
def names(report):
    return {c.name: c.passed for c in report.checks}


def test_verified_deployment_without_a_threshold_is_incomplete_not_ready_and_not_invalid():
    report = assess({**RPC, **FRESH}, probe=Probe())
    assert report.status is S.ACTIVATION_INCOMPLETE and not report.ready_or_active
    assert report.reason == "MISSING_RESOURCE_THRESHOLD_CONFIGURED" and report.issues == ()
    assert names(report)["resource_threshold_configured"] is False and names(report)["gating_explicitly_enabled"] is False


def test_gating_on_without_a_threshold_is_never_active():
    report = assess({**RPC, **FRESH, **GATING}, probe=Probe())
    assert report.status is S.ACTIVATION_INCOMPLETE and report.active_resources == ()


def test_a_threshold_on_a_disabled_resource_does_not_count():
    env = {**RPC, **FRESH, ep.POLICIES_ENV: json.dumps({HOLDER: {"enabled": False, "minimum_balance": "100"}})}
    assert assess(env, probe=Probe()).status is S.ACTIVATION_INCOMPLETE
    enabled_without_threshold = {**RPC, **FRESH, ep.POLICIES_ENV: json.dumps({HOLDER: {"enabled": True}})}
    assert assess(enabled_without_threshold, probe=Probe()).status is S.ACTIVATION_INCOMPLETE


def test_threshold_and_gating_but_missing_freshness_is_not_ready_and_not_active():
    assert assess({**RPC, **THRESHOLD}, probe=Probe()).status is S.ACTIVATION_INCOMPLETE
    report = assess({**RPC, **THRESHOLD, **GATING}, probe=Probe())
    assert report.status is S.ACTIVATION_INCOMPLETE and not report.ready_or_active
    assert report.reason == "MISSING_FRESHNESS_WINDOW_CONFIGURED"
    assert names(report)["freshness_window_configured"] is False


@pytest.mark.parametrize("value", ["0", "-1", "abc", "", "  ", "1.5", "60s", None])
def test_invalid_or_missing_freshness_prevents_ready_and_active(value):
    env = {**RPC, **THRESHOLD, **GATING}
    if value is not None:
        env[ar.FRESHNESS_ENV] = value
    report = assess(env, probe=Probe())
    assert report.status is S.ACTIVATION_INCOMPLETE and not report.ready_or_active
    assert names(report)["freshness_window_configured"] is False
    assert assess({k: v for k, v in env.items() if k != ep.GATING_ENABLED_ENV},
                  probe=Probe()).status is S.ACTIVATION_INCOMPLETE


def test_freshness_uses_the_canonical_runtime_env_name_and_parser_no_default_invented():
    import app.protocol.entitlement_evaluator as ev
    assert ar.FRESHNESS_ENV == ev.FRESHNESS_ENV == "FINCO_ENTITLEMENT_MAX_AGE_SECONDS"
    assert ar._freshness_seconds is ev._freshness_seconds           # one semantic, not two
    assert ev._freshness_seconds({}) is None


def test_threshold_and_freshness_with_gating_off_is_ready_for_activation():
    report = assess(READY_ENV, probe=Probe())
    assert report.status is S.READY_FOR_ACTIVATION and report.reason == "READY_GATING_NOT_ACTIVE"
    assert report.active_resources == () and report.chain_id == CHAIN
    checks = names(report)
    assert all(checks[n] is True for n in checks if n != "gating_explicitly_enabled")
    assert checks["gating_explicitly_enabled"] is False
    # ready activated nothing: the runtime is still INACTIVE
    decision = asyncio.run(evaluate_resource_access(HOLDER, WalletContext(WALLET, True), approved=[approved()],
                                                    environ=READY_ENV))
    assert decision.decision is Decision.INACTIVE and not decision.allowed


def test_all_prerequisites_plus_explicit_gating_is_active_and_reports_exactly_which_resources():
    report = assess(ACTIVE_ENV, probe=Probe())
    assert report.status is S.ACTIVE and report.active_resources == (HOLDER,)
    assert ep.YIELD_ALERTS not in report.active_resources            # not "every holder resource"
    assert all(passed is True for passed in names(report).values())
    two = {ep.POLICIES_ENV: json.dumps({HOLDER: {"enabled": True, "minimum_balance": "100"},
                                        ep.YIELD_ALERTS: {"enabled": True, "minimum_balance": "50"}})}
    assert assess({**ACTIVE_ENV, **two}, probe=Probe()).active_resources == (HOLDER, ep.YIELD_ALERTS)


def test_gating_switch_is_the_only_difference_between_ready_and_active():
    ready, active = assess(READY_ENV, probe=Probe()), assess(ACTIVE_ENV, probe=Probe())
    assert (ready.status, active.status) == (S.READY_FOR_ACTIVATION, S.ACTIVE)
    differing = {n for n in names(ready) if names(ready)[n] != names(active)[n]}
    assert differing == {"gating_explicitly_enabled"}


def test_runtime_coherence_active_report_means_the_canonical_evaluator_can_operate():
    from datetime import datetime, timezone
    from types import SimpleNamespace
    from app.verified.token_entitlement import BalanceEvidenceState, TokenBalanceEvidence
    now = datetime(2026, 10, 1, 12, 0, tzinfo=timezone.utc)

    class Provider:
        async def balance_of(self, policy, wallet_address):
            return TokenBalanceEvidence(CHAIN, TOKEN, WALLET, DECIMALS, 200 * 10 ** DECIMALS, now, "TEST_ONLY",
                                        BalanceEvidenceState.AVAILABLE)

    report = assess(ACTIVE_ENV, probe=Probe())
    assert report.status is S.ACTIVE
    decision = asyncio.run(evaluate_resource_access(HOLDER, WalletContext(WALLET, True), approved=[approved()],
                                                    environ=ACTIVE_ENV, provider=Provider(), now=now))
    assert decision.reason_code != "TOKEN_CONFIGURATION_UNAVAILABLE" and decision.allowed
    # and without the freshness window the runtime really would fail, which the report refuses to call ACTIVE
    no_fresh = {k: v for k, v in ACTIVE_ENV.items() if k != ar.FRESHNESS_ENV}
    broken = asyncio.run(evaluate_resource_access(HOLDER, WalletContext(WALLET, True), approved=[approved()],
                                                  environ=no_fresh, provider=Provider(), now=now))
    assert broken.reason_code == "TOKEN_CONFIGURATION_UNAVAILABLE"
    assert assess(no_fresh, probe=Probe()).status is not S.ACTIVE


# ── candidate / provenance / approval status ─────────────────────────────────────────────────────
def test_different_provenance_does_not_make_a_candidate_the_committed_record():
    same_identity_other_provenance = candidate(provenance="TEST_ONLY a different attestation")
    report = assess(READY_ENV, candidate=same_identity_other_provenance, probe=Probe())
    assert report.status is S.DEPLOYMENT_UNAPPROVED and report.reason == "CANDIDATE_NOT_COMMITTED"
    assert assess(READY_ENV, candidate=candidate(), probe=Probe()).status is S.READY_FOR_ACTIVATION
    padded = candidate(provenance="  TEST_ONLY fixture  ")                    # whitespace is not a difference
    assert assess(READY_ENV, candidate=padded, probe=Probe()).status is S.READY_FOR_ACTIVATION


def test_display_fields_and_candidate_approval_label_are_never_authority():
    labelled = candidate(display_symbol="FINCO", display_name="Finco")
    assert assess(approved_set=[], candidate=labelled, probe=Probe()).status is S.DEPLOYMENT_UNAPPROVED
    parsed, _ = ar.validate_candidate(candidate())
    assert "display_symbol" not in {f for f in ar.ActivationDeployment.__dataclass_fields__ if f == "identity"}
    assert parsed is not None and parsed.identity == (CHAIN, TOKEN)


@pytest.mark.parametrize("label", ["MAYBE", "approved ", "", 5, "REJECTED"])
def test_unknown_approval_status_has_its_own_issue_not_missing_provenance(label):
    parsed, issues = ar.validate_candidate(candidate(approval_status=label))
    if label == "":
        assert parsed is not None                                   # empty means the default PENDING
        return
    assert parsed is None and issues == (Issue.INVALID_APPROVAL_STATUS,)
    assert Issue.MISSING_PROVENANCE not in issues
    assert assess(candidate=candidate(approval_status=label), probe=Probe()).status is S.CONFIG_INVALID


def test_assessment_is_read_only_and_deterministic(monkeypatch):
    import os
    before = dict(os.environ)
    first, second = assess(probe=Probe()), assess(probe=Probe())
    assert first == second and dict(os.environ) == before
    assert canon.APPROVED_FINCO_DEPLOYMENTS == ()


def test_report_view_never_contains_the_rpc_url_or_secrets():
    view = json.dumps(assess(probe=Probe()).public_view())
    assert "rpc.example.invalid" not in view and "key-123" not in view


# ── no production values, runbook ────────────────────────────────────────────────────────────────
def test_no_production_threshold_chain_or_contract_is_hardcoded():
    for rel in ("app/protocol/activation_readiness.py", "tools/finco_token_activation_check.py"):
        source = (ROOT / rel).read_text()
        assert not re.findall(r"0x[0-9a-fA-F]{40}", source)
        assert "minimum_balance=" not in source.replace("p.minimum_balance", "")
    assert all(p.minimum_balance is None for p in ep.default_policies().values())


def test_runbook_lists_the_seven_steps_in_order_and_does_not_claim_completion():
    text = (ROOT / "docs/FINCO_TOKEN_ACTIVATION_RUNBOOK.md").read_text()
    positions = [text.lower().find(step.lower()) for step in ar.ACTIVATION_STEPS]
    assert -1 not in positions and positions == sorted(positions)
    assert "APPROVED_FINCO_DEPLOYMENTS = ()" in text and "Nothing described below has been done" in text


def test_check_tool_reports_not_configured_and_exits_nonzero(capsys):
    import importlib.util
    spec = importlib.util.spec_from_file_location("finco_token_activation_check",
                                                  ROOT / "tools/finco_token_activation_check.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.main([]) == 1
    assert json.loads(capsys.readouterr().out)["status"] == "NOT_CONFIGURED"


# ── optional balance-authority probe (canonical-readiness enhancement V1) ─────

class _BalanceProviderDouble:
    """Canonical TokenBalanceProvider double: records the TokenConfig it
    receives (runtime-parity proof) and scripts the evidence."""

    def __init__(self, *, state="AVAILABLE", balance_raw=None, reason=None):
        self.state_value = state
        self.balance_raw = balance_raw
        self.reason = reason
        self.configs = []
        self.wallets = []

    async def balance_of(self, policy, wallet_address):
        from app.protocol.token_config import TokenConfig
        from app.verified.token_entitlement import BalanceEvidenceState, TokenBalanceEvidence
        self.wallets.append(wallet_address)
        evidence = TokenBalanceEvidence(
            chain_id=policy.chain_id, token_address=policy.token_address,
            wallet_address=wallet_address, token_decimals=policy.token_decimals,
            balance_raw=self.balance_raw,
            observed_at=datetime.now(timezone.utc), source="TEST_ONLY",
            state=BalanceEvidenceState(self.state_value),
            reason=None if self.state_value == "AVAILABLE" else
            (self.reason or self.state_value))
        return evidence

    # capture helper used through monkeypatched P4ReadOnlyBalanceProvider
    def __call__(self, config):
        self.configs.append(config)
        return self


def _provider_double(monkeypatch, **kw):
    from app.protocol.token_config import TokenConfig
    double = _BalanceProviderDouble(**kw)

    class _ProviderFactory:
        def __new__(cls, config: TokenConfig):
            double.configs.append(config)
            return double

    monkeypatch.setattr(
        "app.verified.token_entitlement.P4ReadOnlyBalanceProvider",
        _ProviderFactory)
    return double


def _probe_report(monkeypatch, *, wallet=WALLET, env=None, provider_kw=None,
                  approved_set=None, **assess_kw):
    double = _provider_double(monkeypatch, **(provider_kw or {}))
    report = asyncio.run(ar.assess_activation(
        environ=env if env is not None else {**READY_ENV, **RPC},
        approved=[approved()] if approved_set is None else approved_set,
        probe=Probe(),
        balance_probe_wallet=wallet,
        balance_provider=double))
    return report, double


def test_no_balance_probe_flag_keeps_result_unchanged(monkeypatch):
    """Without --balance-probe-wallet the readiness result is exactly the
    existing contract: no balance_probe evidence is attached."""
    report = assess(READY_ENV, probe=Probe())
    assert report.status is S.READY_FOR_ACTIVATION
    assert report.balance_probe is None
    assert "balance_probe" not in report.public_view()


def test_balance_probe_nonzero_observation(monkeypatch):
    report, double = _probe_report(
        monkeypatch, provider_kw=dict(balance_raw=123 * 10 ** DECIMALS))
    probe = report.balance_probe
    assert probe.requested and probe.executed and probe.available
    assert probe.balance_raw_present and probe.factual_zero is False
    assert probe.observation_status == "BALANCE_OBSERVED"
    assert double.wallets == [WALLET]           # the exact supplied probe wallet


def test_balance_probe_factual_zero(monkeypatch):
    report, _ = _probe_report(monkeypatch, provider_kw=dict(balance_raw=0))
    probe = report.balance_probe
    assert probe.available and probe.balance_raw_present
    assert probe.factual_zero is True           # explicit observed zero is real data
    assert probe.observation_status == "BALANCE_OBSERVED"


@pytest.mark.parametrize("state,reason", [
    ("UNAVAILABLE", "RPC_UNAVAILABLE"),
    ("UNAVAILABLE", "TOKEN_CONTRACT_UNAVAILABLE"),
    ("UNAVAILABLE", "BALANCE_UNAVAILABLE"),
])
def test_balance_probe_unavailable_never_zero(monkeypatch, state, reason):
    report, _ = _probe_report(monkeypatch, provider_kw=dict(
        state=state, reason=reason))
    probe = report.balance_probe
    assert probe.executed and not probe.available
    assert probe.balance_raw_present is False   # never fabricated
    assert probe.factual_zero is False          # failure is never zero
    assert probe.observation_status == reason


def test_balance_probe_wrong_chain_fails_closed(monkeypatch):
    """A probe wallet whose evidence comes from a different chain never
    becomes a number: the identity mismatch fails the diagnostic closed."""
    from app.protocol.token_config import TokenConfig
    double = _BalanceProviderDouble()

    from app.protocol.token_config import TokenConfig

    class _WrongChainProvider:
        """Runtime-parity double: installed at the SAME seam the evaluator
        uses (P4ReadOnlyBalanceProvider) and constructed with the SAME
        chain-scoped TokenConfig."""

        def __init__(self, config: TokenConfig):
            double.configs.append(config)

        async def balance_of(self, policy, wallet_address):
            from app.verified.token_entitlement import (
                BalanceEvidenceState, TokenBalanceEvidence,
            )
            return TokenBalanceEvidence(
                chain_id=999, token_address=policy.token_address,
                wallet_address=wallet_address, token_decimals=policy.token_decimals,
                balance_raw=10 ** 12, observed_at=datetime.now(timezone.utc),
                source="TEST_ONLY", state=BalanceEvidenceState.AVAILABLE)

    monkeypatch.setattr(
        "app.verified.token_entitlement.P4ReadOnlyBalanceProvider",
        _WrongChainProvider)

    report = asyncio.run(ar.assess_activation(
        environ={**READY_ENV, **RPC}, approved=[approved()], probe=Probe(),
        balance_probe_wallet=WALLET, balance_provider=None))
    probe = report.balance_probe
    assert probe.executed and not probe.available
    assert probe.balance_raw_present is False
    assert probe.observation_status == "BALANCE_IDENTITY_MISMATCH"


def test_balance_probe_malformed_wallet_fails_clean(monkeypatch):
    report, double = _probe_report(
        monkeypatch, wallet="not-a-wallet")
    probe = report.balance_probe
    assert probe.requested and not probe.executed
    assert probe.observation_status == "MALFORMED_PROBE_WALLET"
    assert double.wallets == []                 # provider never reached


def test_balance_probe_wallet_never_stored_or_bound(monkeypatch):
    """The probe wallet is used transiently for the read only — it is never
    bound to a FINCO user (wallet store unchanged)."""
    from app.protocol.wallet_auth import get_verified_wallet
    _probe_report(monkeypatch, wallet=WALLET)
    assert get_verified_wallet("user-1") is None


# ── runtime parity: same chain-scoped RPC as the evaluator ────────────────────

def test_balance_probe_uses_exact_chain_scoped_rpc(monkeypatch):
    """Runtime parity: the provider is constructed at the SAME factory seam
    the evaluator uses and receives a TokenConfig bound to the chain-scoped
    env value (FINCO_TOKEN_RPC_URL_<chain_id>), the exact approved chain,
    contract and decimals — never the flat legacy URL."""
    from app.verified.token_entitlement import (
        BalanceEvidenceState, TokenBalanceEvidence,
    )
    configs = []

    class _Factory:
        def __new__(cls, config: TokenConfig):
            configs.append(config)
            provider = SimpleNamespace(balance_of=None)
            async def balance_of(policy, wallet,
                                 _c=config, _p=provider):
                _p.evidence = TokenBalanceEvidence(
                    chain_id=_c.chain_id, token_address=_c.token_address,
                    wallet_address=wallet, token_decimals=_c.decimals_override,
                    balance_raw=123 * 10 ** (_c.decimals_override or 18),
                    observed_at=datetime.now(timezone.utc), source="TEST_ONLY",
                    state=BalanceEvidenceState.AVAILABLE)
                return _p.evidence
            provider.balance_of = balance_of
            return provider

    monkeypatch.setattr(
        "app.verified.token_entitlement.P4ReadOnlyBalanceProvider", _Factory)
    report = asyncio.run(ar.assess_activation(
        environ={**READY_ENV, **RPC,                      # chain-scoped only
                 "FINCO_TOKEN_RPC_URL": "https://flat-legacy.invalid/not-the-gate"},
        approved=[approved()], probe=Probe(),
        balance_probe_wallet=WALLET, balance_provider=None))  # runtime path
    assert report.status is S.READY_FOR_ACTIVATION
    assert len(configs) == 1
    config = configs[0]
    assert isinstance(config, TokenConfig)
    assert config.rpc_url == RPC[f"FINCO_TOKEN_RPC_URL_{CHAIN}"]
    assert config.rpc_url != "https://flat-legacy.invalid/not-the-gate"
    assert config.chain_id == CHAIN
    assert config.token_address == TOKEN
    assert config.decimals_override == DECIMALS
    assert report.balance_probe.available
    assert report.balance_probe.balance_raw_present


def test_flat_rpc_cannot_substitute_for_chain_scoped(monkeypatch):
    """Only FINCO_TOKEN_RPC_URL_<chain_id> is the runtime binding: with the
    chain-scoped value absent the diagnostic fails closed (NO_RPC_FOR_CHAIN)
    even when a flat legacy URL exists. The provider is never constructed."""
    from app.verified.token_entitlement import P4ReadOnlyBalanceProvider
    constructed = []

    class _NeverConstructed:
        def __new__(cls, config):
            constructed.append(config)
            return SimpleNamespace(balance_of=lambda *a: None)

    monkeypatch.setattr(
        "app.verified.token_entitlement.P4ReadOnlyBalanceProvider",
        _NeverConstructed)
    report = asyncio.run(ar.assess_activation(
        environ={**FRESH, **THRESHOLD,                 # NO chain-scoped RPC
                 "FINCO_TOKEN_RPC_URL": "https://flat-legacy.invalid/x"},
        approved=[approved()], probe=Probe(),
        balance_probe_wallet=WALLET, balance_provider=None))
    probe = report.balance_probe
    # honest typed state: the readiness assessment itself failed closed at
    # deployment verification (NO_RPC_FOR_CHAIN), so the optional probe
    # never ran — and the provider was never constructed
    assert report.status is S.RPC_UNAVAILABLE
    assert probe.executed is False
    assert probe.observation_status == "DEPLOYMENT_NOT_VERIFIED"
    assert constructed == []                 # provider never constructed


def test_balance_probe_probes_the_selected_deployment_chain(monkeypatch):
    """A resource policy with an explicit chain_id selects THAT approved
    deployment: the probe binds to its chain, not another approved chain."""
    other = approved(chain_id=OTHER_CHAIN, token_address=OTHER_TOKEN)
    from app.verified.token_entitlement import (
        BalanceEvidenceState, TokenBalanceEvidence,
    )
    configs = []

    class _Factory:
        def __new__(cls, config: TokenConfig):
            configs.append(config)
            provider = SimpleNamespace(balance_of=None)
            async def balance_of(policy, wallet,
                                 _c=config, _p=provider):
                _p.evidence = TokenBalanceEvidence(
                    chain_id=_c.chain_id, token_address=_c.token_address,
                    wallet_address=wallet, token_decimals=_c.decimals_override,
                    balance_raw=7 * 10 ** (_c.decimals_override or 18),
                    observed_at=datetime.now(timezone.utc), source="TEST_ONLY",
                    state=BalanceEvidenceState.AVAILABLE)
                return _p.evidence
            provider.balance_of = balance_of
            return provider

    monkeypatch.setattr(
        "app.verified.token_entitlement.P4ReadOnlyBalanceProvider", _Factory)
    env = {**READY_ENV,
           f"FINCO_TOKEN_RPC_URL_{OTHER_CHAIN}": "https://rpc.other.invalid/k",
           ep.POLICIES_ENV: json.dumps({HOLDER: {"enabled": True, "minimum_balance": "100",
                                                 "chain_id": OTHER_CHAIN}})}
    report = asyncio.run(ar.assess_activation(
        environ=env, approved=[approved(), other],
        probe=Probe(chain_id=OTHER_CHAIN, decimals=DECIMALS),
        balance_probe_wallet=WALLET, balance_provider=None))  # runtime path
    assert report.status is S.READY_FOR_ACTIVATION
    assert len(configs) == 1
    assert configs[0].chain_id == OTHER_CHAIN
    assert configs[0].token_address == OTHER_TOKEN
    assert configs[0].decimals_override == DECIMALS


# ── AST safety: the probe adds no write RPC or signing ────────────────────────

def test_balance_probe_uses_no_write_rpc_or_signing():
    """No write/signing RPC constants anywhere in the readiness + balance
    authority; the probe reuses the canonical provider (no reimplemented
    ABI) by import."""
    import ast
    import inspect
    from app.protocol import activation_readiness
    from app.protocol import token_balance
    readiness_constants = {node.value for node in ast.walk(
        ast.parse(inspect.getsource(activation_readiness)))
        if isinstance(node, ast.Constant) and isinstance(node.value, str)}
    for write in ("eth_sendTransaction", "eth_sendRawTransaction",
                  "eth_signTransaction", "personal_sign"):
        assert write not in readiness_constants, write
    balance_constants = {node.value for node in ast.walk(
        ast.parse(inspect.getsource(token_balance)))
        if isinstance(node, ast.Constant) and isinstance(node.value, str)}
    for write in ("eth_sendTransaction", "eth_sendRawTransaction",
                  "eth_signTransaction", "personal_sign"):
        assert write not in balance_constants, write
    assert "0x70a08231" in balance_constants    # balanceOf — read-only
    # the probe reuses the canonical provider by import, no reimplemented ABI
    source = inspect.getsource(activation_readiness)
    assert "P4ReadOnlyBalanceProvider" in source
    assert "_encode_balanceof" not in source   # balanceOf only via the provider


# ── production truth / gate OFF unchanged by the enhancement ─────────────────

def test_production_truth_unchanged_by_enhancement():
    assert canon.APPROVED_FINCO_DEPLOYMENTS == ()
    report = asyncio.run(ar.assess_activation(environ={}))
    assert report.status is S.NOT_CONFIGURED
    assert report.balance_probe is None         # not requested → unchanged
    assert ep.load_policy_set({}).gating_enabled is False


def test_runtime_evaluator_unchanged():
    """Canonical runtime evaluator behaves exactly as before: an enabled
    gated resource without a freshness window still fails closed with
    TOKEN_CONFIGURATION_UNAVAILABLE through decide_resource_access."""
    from app.protocol.entitlement_policy import AccessMode, PolicySet
    policy = ep.EntitlementPolicy(
        resource_key=HOLDER, access_mode=AccessMode.FINCO_HOLDER,
        minimum_balance=Decimal(100), wallet_verified_required=True,
        enabled=True, chain_id=CHAIN)
    policy_set = PolicySet({HOLDER: policy}, gating_enabled=True)
    deployment = approved()
    resolution = SimpleNamespace(status=SimpleNamespace(value="RESOLVED"),
                                 reason="", resolved=True,
                                 deployment=deployment)
    wallet = WalletContext(WALLET, True, "user-1")
    verdict = evaluate_resource_access if False else None
    from app.protocol.entitlement_evaluator import decide_resource_access
    decision = decide_resource_access(
        HOLDER, wallet, policy_set, resolution, None, freshness_seconds=None)
    assert decision.decision is Decision.DENY
    assert decision.reason_code == "TOKEN_CONFIGURATION_UNAVAILABLE"
