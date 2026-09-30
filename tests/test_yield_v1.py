from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from finco_yield.evidence_v1 import build_evidence, canonical_hash, canonical_json, YieldPostTradeReceiptV1
from finco_yield.execution import ExecutionIntent, ExecutionValidationError, MAX_UINT256, build_direct_erc4626_deposit, build_pre_trade_evidence, validate_quote
from finco_yield.explore import ExploreFilters, compare, explore
from finco_yield.freshness import evaluate_freshness
from finco_yield.onchain import Erc4626DirectObservation
from finco_yield.providers import EnsoClient, ProviderValidationError, ZeroXClient
from finco_yield.readiness import ChainReadinessState, robinhood_chain_readiness
from finco_yield.registry import RegistryError, load_bundled_registry
from finco_yield.schema import EvidenceConfidence, SourceReference, YieldObservation
from finco_yield.underwriting import NetApyAssumptions, position_net_apy, run_scenario
from finco_yield.web import router

WALLET="0x3333333333333333333333333333333333333333"
OTHER="0x4444444444444444444444444444444444444444"
ROUTER="0x5555555555555555555555555555555555555555"
ALLOWANCE="0x6666666666666666666666666666666666666666"

def _registry(): return load_bundled_registry()
def _direct(binding,amount=1_000_000,asset=None,share=None):
    return Erc4626DirectObservation(binding.chain_id,123,datetime.now(timezone.utc),binding.contract_address,asset or binding.underlying_asset,share or binding.share_token,18,10**12,10**18,1_000_000,1,amount,amount*10**12,amount*10**12,amount)

def test_canonical_registry_unknown_uid_rejected():
    r=_registry(); o=r.all()[0]; assert r.resolve(o.uid)==o
    with pytest.raises(RegistryError): r.execution_binding("USDC")

def test_execution_intent_cannot_define_economic_destination():
    i=ExecutionIntent(_registry().all()[0].uid,1,WALLET)
    for name in ("destination_contract","share_token","protocol","underlying_asset"):
        assert not hasattr(i,name)

def test_direct_plan_resolves_canonical_destination_and_minimal_approval():
    r=_registry(); o=r.all()[0]; b=r.execution_binding(o.uid); i=ExecutionIntent(o.uid,1_000_000,WALLET)
    p=build_direct_erc4626_deposit(i,registry=r,direct_observation=_direct(b),current_allowance=0,allowance_block_number=123)
    assert p.quote.destination_contract==b.contract_address and p.quote.expected_output_token==b.share_token
    assert p.quote.receiver==WALLET.lower(); assert p.approvals[0].amount==i.amount and not p.approvals[0].unlimited
    assert p.transactions[0].purpose=="EXACT_ERC20_APPROVAL" and p.transactions[-1].purpose=="ERC4626_DEPOSIT"
    assert p.user_signable is False and p.protection_state=="UNPROTECTED_PREVIEW_ONLY"
    validate_quote(i,p,registry=r)

def test_destination_substitution_rejected():
    r=_registry(); o=r.all()[0]; b=r.execution_binding(o.uid); i=ExecutionIntent(o.uid,1_000_000,WALLET); p=build_direct_erc4626_deposit(i,registry=r,direct_observation=_direct(b),current_allowance=i.amount)
    with pytest.raises(ExecutionValidationError): validate_quote(i,replace(p,quote=replace(p.quote,destination_contract=OTHER)),registry=r)

def test_underlying_substitution_rejected():
    r=_registry(); o=r.all()[0]; b=r.execution_binding(o.uid)
    with pytest.raises(ExecutionValidationError): build_direct_erc4626_deposit(ExecutionIntent(o.uid,1_000_000,WALLET,funding_token=OTHER),registry=r,direct_observation=_direct(b),current_allowance=0)

def test_share_substitution_rejected():
    r=_registry(); o=r.all()[0]; b=r.execution_binding(o.uid); i=ExecutionIntent(o.uid,1_000_000,WALLET); p=build_direct_erc4626_deposit(i,registry=r,direct_observation=_direct(b),current_allowance=0)
    with pytest.raises(ExecutionValidationError): validate_quote(i,replace(p,quote=replace(p.quote,expected_output_token=OTHER)),registry=r)

def test_amount_chain_receiver_route_output_and_expiry_mutations_rejected():
    r=_registry(); o=r.all()[0]; b=r.execution_binding(o.uid); i=ExecutionIntent(o.uid,1_000_000,WALLET); p=build_direct_erc4626_deposit(i,registry=r,direct_observation=_direct(b),current_allowance=0)
    mutations=[replace(p,quote=replace(p.quote,amount=2)),replace(p,quote=replace(p.quote,chain_id=1)),replace(p,quote=replace(p.quote,receiver=OTHER)),replace(p,route=("TAMPER",)),replace(p,quote=replace(p.quote,expected_output=(p.quote.expected_output or 0)+1))]
    for m in mutations:
        with pytest.raises(ExecutionValidationError): validate_quote(i,m,registry=r)
    with pytest.raises(ExecutionValidationError): validate_quote(i,p,registry=r,now=p.quote.expires_at+timedelta(seconds=1))

def test_unlimited_approval_rejected():
    r=_registry(); o=r.all()[0]; b=r.execution_binding(o.uid); i=ExecutionIntent(o.uid,1_000_000,WALLET); p=build_direct_erc4626_deposit(i,registry=r,direct_observation=_direct(b),current_allowance=0)
    bad=replace(p.approvals[0],amount=MAX_UINT256,unlimited=True)
    with pytest.raises(ExecutionValidationError): validate_quote(i,replace(p,approvals=(bad,)),registry=r)

def test_native_fixture_never_becomes_direct_authority():
    for o in _registry().all(): assert o.source_type==EvidenceConfidence.NATIVE_ENRICHED and o.block_number is None

def test_freshness_stale_future_and_direct_block_identity():
    now=datetime.now(timezone.utc)
    assert evaluate_freshness(SourceReference(EvidenceConfidence.NATIVE_ENRICHED,"x",now-timedelta(hours=2)),now=now).state=="STALE"
    assert evaluate_freshness(SourceReference(EvidenceConfidence.NATIVE_ENRICHED,"x",now+timedelta(minutes=10)),now=now).state=="FUTURE_TIMESTAMP"
    assert evaluate_freshness(SourceReference(EvidenceConfidence.DIRECT_ONCHAIN,"x",now),now=now).state=="INVALID"

def test_evidence_canonicalization_decimal_and_timezone():
    assert canonical_hash({"x":Decimal("1.0")})==canonical_hash({"x":Decimal("1.00")})
    a=datetime(2026,1,1,0,0,tzinfo=timezone.utc); b=datetime(2025,12,31,19,0,tzinfo=timezone(timedelta(hours=-5)))
    assert canonical_json({"t":a})==canonical_json({"t":b})

def test_typed_yield_evidence_and_pretrade_are_deterministic():
    r=_registry(); o=r.all()[0]; e1=build_evidence(o); e2=build_evidence(o)
    assert e1.schema_version=="YIELD_EVIDENCE_V1" and e1.canonical_input_hash==e2.canonical_input_hash and e1.canonical_output_hash==e2.canonical_output_hash
    b=r.execution_binding(o.uid); i=ExecutionIntent(o.uid,1_000_000,WALLET); p=build_direct_erc4626_deposit(i,registry=r,direct_observation=_direct(b),current_allowance=i.amount)
    pre=build_pre_trade_evidence(e1,p); assert pre.opportunity_uid==o.uid and pre.route_hash==p.quote.route_hash and len(pre.record_hash)==64

def test_net_apy_unavailable_unless_all_explicit_costs_exist():
    obs=YieldObservation(Decimal("100"),Decimal(".05"))
    missing=position_net_apy(obs,NetApyAssumptions(Decimal("1000"),30,Decimal("1"),Decimal("1"),Decimal("0"),None,Decimal("0"),Decimal("0")))
    assert missing.state=="NET_APY_UNAVAILABLE" and missing.net_apy is None
    full=position_net_apy(obs,NetApyAssumptions(Decimal("1000"),365,Decimal("1"),Decimal("1"),Decimal("1"),Decimal("1"),Decimal("1"),Decimal("1")))
    assert full.state=="AVAILABLE" and full.net_apy==Decimal(".044")

def test_unsupported_causal_scenarios_are_not_modelled():
    obs=YieldObservation(Decimal("100"),Decimal(".05"))
    for name in ("UTILIZATION_SHIFT","ASSET_DEPEG","LIQUIDITY_COMPRESSION"): assert run_scenario(name,obs).state.value=="NOT_MODELLED"

def test_explore_filters_and_compare_are_neutral():
    r=_registry(); o=r.all()[0]; rows=explore(r,filters=ExploreFilters(chain_id=o.chain_id,asset=o.underlying_symbol,minimum_tvl_usd=Decimal("1")))
    assert o in rows; comp=compare(r,[o.uid]); assert comp[0].opportunity_uid==o.uid
    with pytest.raises(ValueError): compare(r,[])
    with pytest.raises(ValueError): compare(r,[o.uid,o.uid])

def test_zero_x_normalization_requires_reviewed_targets(monkeypatch):
    monkeypatch.setenv("FINCO_YIELD_0X_APPROVAL_TARGETS_8453",ALLOWANCE); monkeypatch.setenv("FINCO_YIELD_0X_TRANSACTION_TARGETS_8453",ROUTER)
    c=ZeroXClient(api_key="x",client=object()); o=_registry().all()[0]
    q=c.normalize({"sellAmount":"100","buyAmount":"95","issues":{"allowance":{"spender":ALLOWANCE}},"transaction":{"to":ROUTER,"data":"0x12","value":"0"}},chain_id=8453,sell_token=OTHER,buy_token=o.underlying_address,sell_amount=100,taker=WALLET)
    assert q.provider=="0X_V2" and q.approval_target==ALLOWANCE.lower()
    with pytest.raises(ProviderValidationError): c.normalize({"transaction":{"to":OTHER,"data":"0x12","value":"0"}},chain_id=8453,sell_token=OTHER,buy_token=o.underlying_address,sell_amount=100,taker=WALLET)

def test_enso_normalization_requires_reviewed_target(monkeypatch):
    monkeypatch.setenv("FINCO_YIELD_ENSO_TRANSACTION_TARGETS_8453",ROUTER); c=EnsoClient(api_key="x",client=object()); o=_registry().all()[0]
    q=c.normalize({"tx":{"to":ROUTER,"data":"0xab","value":"0"},"amountOut":"123"},chain_id=8453,input_token=OTHER,output_token=o.share_token,amount=100,receiver=WALLET)
    assert q.provider=="ENSO"
    with pytest.raises(ProviderValidationError): c.normalize({"tx":{"to":OTHER,"data":"0xab","value":"0"}},chain_id=8453,input_token=OTHER,output_token=o.share_token,amount=100,receiver=WALLET)

def test_post_trade_receipt_design_and_robinhood_partial():
    receipt=YieldPostTradeReceiptV1("0x"+"ab"*32,123,"yld_x","v1",100,95,96,Decimal("10"),datetime.now(timezone.utc)); assert len(receipt.receipt_hash)==64
    readiness=robinhood_chain_readiness(); assert readiness.chain_id==4663 and readiness.state==ChainReadinessState.PARTIAL and "authoritative Enso chain 4663 support" in readiness.unproven

def test_no_private_key_sign_or_broadcast_api():
    import finco_yield.execution as e
    names=set(dir(e)); assert "private_key" not in names and "sign" not in names and "broadcast" not in names

def test_web_feature_flags(monkeypatch):
    app=FastAPI(); app.include_router(router); c=TestClient(app)
    monkeypatch.delenv("FINCO_YIELD_ENABLED",raising=False); assert c.get("/yield").status_code==404
    monkeypatch.setenv("FINCO_YIELD_ENABLED","1"); r=c.get("/yield"); assert r.status_code==200 and "Evidence-backed DeFi opportunities" in r.text and "does not rank a winner" in r.text
    monkeypatch.delenv("FINCO_YIELD_EXECUTION_ENABLED",raising=False); uid=_registry().all()[0].uid; assert c.post(f"/yield/{uid}/plan",data={"amount":"1"}).json()["code"]=="EXECUTION_DISABLED"
