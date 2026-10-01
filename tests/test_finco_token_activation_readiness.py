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
from app.verified.token_entitlement import ApprovedFincoDeployment

CHAIN, OTHER_CHAIN = 31337, 31338
TOKEN, OTHER_TOKEN = "0x" + "ab" * 20, "0x" + "cd" * 20
DECIMALS = 6
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
POLICY_ON = {ep.GATING_ENABLED_ENV: "1",
             ep.POLICIES_ENV: json.dumps({HOLDER: {"enabled": True, "minimum_balance": "100"}})}   # TEST_ONLY


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
    committed = assess(candidate=candidate(), probe=Probe())
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


def test_ambiguous_active_deployment_needs_explicit_chain_selection():
    two = [approved(), approved(chain_id=OTHER_CHAIN, token_address=OTHER_TOKEN)]
    env = {**RPC, f"FINCO_TOKEN_RPC_URL_{OTHER_CHAIN}": "https://rpc2.example.invalid"}
    ambiguous = assess(env, two, probe=Probe())
    assert ambiguous.status is S.CONFIG_INVALID and Issue.AMBIGUOUS_ACTIVE_DEPLOYMENT in ambiguous.issues
    selected = {key: {"chain_id": CHAIN} for key in ep.RESOURCE_KEYS[1:]}
    policy_set = ep.load_policy_set({ep.POLICIES_ENV: json.dumps(selected)})
    resolved = asyncio.run(ar.assess_activation(environ=env, approved=two, probe=Probe(), policy_set=policy_set))
    assert resolved.status is not S.CONFIG_INVALID


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


# ── ready != active ──────────────────────────────────────────────────────────────────────────────
def test_explicit_approved_test_only_deployment_is_ready_but_not_active():
    report = assess(probe=Probe())
    assert report.status is S.READY_FOR_ACTIVATION and report.reason == "READY_GATING_NOT_ACTIVE"
    assert report.active_resources == () and report.chain_id == CHAIN
    by_name = {c.name: c.passed for c in report.checks}
    assert by_name["gating_explicitly_enabled"] is False and by_name["fail_closed_behavior"] is True
    assert by_name["resource_threshold_configured"] is False
    # and the runtime really is still inactive: ready never switched anything on
    decision = asyncio.run(evaluate_resource_access(HOLDER, WalletContext("0x" + "12" * 20, True),
                                                    approved=[approved()], environ=RPC))
    assert decision.decision is Decision.INACTIVE and not decision.allowed


def test_gating_flag_without_any_threshold_is_still_not_active():
    report = assess({**RPC, ep.GATING_ENABLED_ENV: "1"}, probe=Probe())
    assert report.status is S.READY_FOR_ACTIVATION and report.active_resources == ()


def test_active_requires_explicit_gating_and_a_configured_threshold():
    report = assess({**RPC, **POLICY_ON}, probe=Probe())
    assert report.status is S.ACTIVE and report.active_resources == (HOLDER,)
    threshold_only = assess({**RPC, ep.POLICIES_ENV: POLICY_ON[ep.POLICIES_ENV]}, probe=Probe())
    assert threshold_only.status is S.READY_FOR_ACTIVATION                  # no explicit flag -> not active


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
