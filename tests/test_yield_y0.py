from dataclasses import replace
from datetime import timedelta
from decimal import Decimal
import pytest
from finco_yield.flags import yield_enabled, execution_enabled
from finco_yield.identity import YieldIdentity, canonical_address, yield_opportunity_uid
from finco_yield.schema import YieldObservation, ComponentState, ScenarioState
from finco_yield.underwriting import decompose, run_scenario
from finco_yield.verify import YieldEvidenceRecord, sha256_canonical
from finco_yield.execution import ExecutionIntent, Approval, build_direct_erc4626_deposit, validate_quote, assert_connected_receiver, ExecutionValidationError
from finco_yield.ingestion import load_bundled_sample
from finco_yield.web import prototype

A="0x1111111111111111111111111111111111111111"; B="0x2222222222222222222222222222222222222222"; W="0x3333333333333333333333333333333333333333"; O="0x4444444444444444444444444444444444444444"

def test_flags_default_off(monkeypatch):
    monkeypatch.delenv("FINCO_YIELD_ENABLED",raising=False); monkeypatch.delenv("FINCO_YIELD_EXECUTION_ENABLED",raising=False)
    assert not yield_enabled() and not execution_enabled()

def test_identity_exact_and_deterministic():
    x=YieldIdentity(8453,"Morpho","morpho_vault",A,(B,),A); y=YieldIdentity(8453,"morpho","morpho_vault",A,(B,),A)
    assert yield_opportunity_uid(x)==yield_opportunity_uid(y)
    assert yield_opportunity_uid(x)!=yield_opportunity_uid(YieldIdentity(1,"morpho","morpho_vault",A,(B,),A))

@pytest.mark.parametrize("bad",["USDC","0x1234","",None])
def test_no_symbol_fuzzy_identity(bad):
    with pytest.raises((ValueError,TypeError)): canonical_address(bad)

def test_missing_not_zero_and_component_math():
    assert YieldObservation(None,None).apy_total is None
    o=YieldObservation(Decimal("100"),Decimal(".08"),Decimal(".05"),Decimal(".02"),Decimal(".01"),Decimal(".005"))
    d=decompose(o); assert d.state==ComponentState.AVAILABLE and d.organic_share==Decimal(".75") and d.reward_dependency==Decimal(".25") and d.reward_off_apy==Decimal(".055")

def test_missing_components_and_not_modelled():
    o=YieldObservation(Decimal("100"),Decimal(".08"))
    assert decompose(o).state==ComponentState.COMPONENTS_UNAVAILABLE
    assert run_scenario("REWARDS_OFF",o).state==ScenarioState.NOT_MODELLED

def test_scenarios():
    o=YieldObservation(Decimal("100"),Decimal(".08"),Decimal(".05"),Decimal(".02"),Decimal(".01"))
    assert run_scenario("REWARDS_OFF",o).apy==Decimal(".06")
    assert run_scenario("REWARDS_MINUS_50",o).apy==Decimal(".07")

def test_evidence_hash_determinism():
    assert sha256_canonical({"b":2,"a":1})==sha256_canonical({"a":1,"b":2})
    r=YieldEvidenceRecord("x",{"a":1},{"apy":".04"},{"days":30},{"out":".03"},"y0.1")
    assert r.canonical_output_hash==r.canonical_output_hash

def _intent(): return ExecutionIntent(8453,"yld",A,B,A,1_000_000,W)

def test_unsigned_direct_and_validation():
    i=_intent(); p=build_direct_erc4626_deposit(i)
    assert p.transactions[0].data.startswith("0x6e553f65") and not hasattr(p,"signature")
    validate_quote(i,p)

def test_substitution_and_mutation_rejected():
    i=_intent(); p=build_direct_erc4626_deposit(i)
    with pytest.raises(ExecutionValidationError): assert_connected_receiver(replace(i,receiver=O),W)
    with pytest.raises(ExecutionValidationError): validate_quote(replace(i,amount=i.amount+1),p)
    with pytest.raises(ExecutionValidationError): validate_quote(replace(i,chain_id=1),p)
    with pytest.raises(ExecutionValidationError): validate_quote(i,replace(p,route=("TAMPERED",)))
    with pytest.raises(ExecutionValidationError): validate_quote(i,p,now=p.quote.expires_at+timedelta(seconds=1))

def test_unlimited_approval_rejected():
    i=_intent(); p=build_direct_erc4626_deposit(i)
    with pytest.raises(ExecutionValidationError): validate_quote(i,replace(p,approvals=(Approval(B,A,(1<<256)-1,True),)))

def test_live_sample_14_exact_native_enriched():
    rows=load_bundled_sample(); assert len(rows)==14 and {r["chain_id"] for r in rows}=={1,8453}
    for r in rows: assert len(r["contract_address"])==42 and r["source_type"]=="NATIVE_ENRICHED" and r["apy_base"] is None

def test_ui_boundary():
    html=prototype(); assert "NO BROADCAST" in html and "Non-custodial" in html and "connected wallet only" in html
