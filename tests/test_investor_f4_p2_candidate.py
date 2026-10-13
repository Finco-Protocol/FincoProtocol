"""Pure synthetic, release-closed F4/P2 independent Decimal evidence tests.

No source/user economics, no production Run and no P1 executable mutation.
Full FINCO checkout regression remains mandatory after publishing Draft PR.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal, getcontext
from pathlib import Path
import copy
import json
import sys

import pytest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from app.model_v2.investor_f4_candidate.p2_contracts import parse_contract, P2ContractError
from app.model_v2.investor_f4_candidate.p2_evaluator import (
    CANONICAL_RECEIPT_SOURCE, evaluate_p2_candidate, validate_candidate_projection,
)

getcontext().prec=45
D=Decimal
POLICIES={
    "preferred_method":"SIMPLE_ON_UNRETURNED_CAPITAL", "day_count":"ACT_365_FIXED",
    "accrual_start":"EACH_CONTRIBUTION_DATE","accrual_stop":"EACH_RETURN_OF_CAPITAL_DATE",
    "partial_return":"REDUCE_FUTURE_ACCRUAL_BASE","cash_shortfall":"CARRY_UNPAID_ENTITLEMENT",
    "hurdle_basis":"CUMULATIVE_UNPAID_PREF_NOT_IRR","negative_distribution":"REJECT",
}
BINDING={"owner_id":"test-owner","project_id":"test-project","scenario_id":None,
         "snapshot_id":"test-synthetic-snapshot","composite_hash":"sha256-synthetic"}

def stage(kind,cls=None,beneficiary=None,cap=None,fraction=None):
    return {"kind":kind,"class_id":cls,"beneficiary_id":beneficiary,
            "lifetime_cap_keur":cap,"fraction":fraction}

def agreement(*,classes=None,investors=None,contributions=None,stages=None):
    return {"schema_version":2,"approval":"CANDIDATE_NOT_AUTHORIZED",
        "agreement_id":"SYNTHETIC_AGREEMENT","version":1,"currency":"EUR","unit":"kEUR",
        **POLICIES,
        "classes":classes if classes is not None else [{"id":"ORD","preferred_rate_pa":None}],
        "investors":investors if investors is not None else [
            {"id":"A","class_id":"ORD","ownership_fraction":"0.7","commitment_keur":"200"},
            {"id":"B","class_id":"ORD","ownership_fraction":"0.3","commitment_keur":"200"}],
        "contributions":contributions if contributions is not None else [
            {"investor_id":"A","date":"2030-01-01","amount_keur":"60"},
            {"investor_id":"B","date":"2030-01-01","amount_keur":"40"}],
        "stages":stages if stages is not None else [stage("RETURN_OF_CAPITAL","ORD"),stage("RESIDUAL")],
    }

def receipts(*rows, status="OK"):
    # synthetic canonical-boundary-shape payload; NOT an attested real G2C run.
    return {"schema_version":1,"source":CANONICAL_RECEIPT_SOURCE,"return_status":status,
        "periods":[{"date":dt,"paid_in_keur":paid,"gross_dividend_keur":cash,
                    "dividend_wht_keur":"0","net_equity_receipt_keur":cash}
                   for dt,paid,cash in rows]}

def xirr_decimal(flows, dates):
    # Independent monotone discount equation with Decimal bisection, NOT a
    # cloned production utility. Only used to validate synthetic magnitudes.
    ds=[D(str(v)) for v in flows]
    t0=dates[0]
    def npv(rate):
        return sum((v/(D(1)+rate)**(D((t-t0).days)/D(365)) for v,t in zip(ds,dates)),D(0))
    lo=D("-0.95")
    hi=D(16)
    if npv(lo)*npv(hi)>=0:return None
    for _ in range(180):
        mid=(lo+hi)/2
        if npv(lo)*npv(mid)<=0:hi=mid
        else:lo=mid
    return float((lo+hi)/2)

def run(document,source,**kw):
    return evaluate_p2_candidate(json.dumps(document),source,binding=BINDING,
                                 xirr_calculator=xirr_decimal,**kw)

def row(result,iid):
    return next(r for r in result["investors"] if r["id"]==iid)

def test_common_equity_explicit_roc_then_residual_conservation_and_unequal_shares():
    result=run(agreement(),receipts(("2030-01-01","100","0"),
                                    ("2031-01-01","0","50"),
                                    ("2032-01-01","0","100")))
    a,b=row(result,"A"),row(result,"B")
    assert D(a["returned_capital_keur"])==D(60)
    assert D(b["returned_capital_keur"])==D(40)
    assert D(a["residual_keur"])==D(35)
    assert D(b["residual_keur"])==D(15)
    assert D(a["total_distributed_keur"])==D(95)
    assert D(b["total_distributed_keur"])==D(55)
    assert D(result["total_distributed_keur"])==D(150)
    assert result["conservation_residual_keur"]=="0"
    assert all(x["unallocated_keur"]=="0" for x in result["period_trace"])
    assert all(x["cash_after_keur"]=="0" for x in result["period_trace"][-1]["stages"][-1:])
    assert result["release_status"]=="CANDIDATE_NOT_AUTHORIZED"
    assert result["run_history_binding"]=="NOT_COMMITTED"
    assert result["production_export"]=="BLOCKED"
    validate_candidate_projection(result)


def test_two_common_investors_p1_residual_only_exact_decimal_parity():
    """Pure-equity stage omission yields the same legal fraction arithmetic as P1."""
    doc=agreement(stages=[stage("RESIDUAL")])
    source=receipts(("2030-01-01","100","0"), ("2031-01-01","0","101.25"))
    result=run(doc,source)
    expected_a=D("101.25")*D("0.7")
    expected_b=D("101.25")*D("0.3")
    assert D(row(result,"A")["residual_keur"])==expected_a
    assert D(row(result,"B")["residual_keur"])==expected_b
    assert all(D(r["returned_capital_keur"])==0 for r in result["investors"])
    # Not a replacement for full existing F4/P1 tests on the canonical checkout.


def test_multiple_dates_paid_in_real_not_commitment_and_dpi_realized():
    doc=agreement(contributions=[
        {"investor_id":"A","date":"2030-01-01","amount_keur":"30"},
        {"investor_id":"B","date":"2030-01-01","amount_keur":"40"},
        {"investor_id":"A","date":"2031-01-01","amount_keur":"30"}],
        stages=[stage("RESIDUAL")])
    result=run(doc,receipts(("2030-01-01","70","0"),
                            ("2031-01-01","30","10"),
                            ("2032-01-01","0","110")))
    assert D(row(result,"A")["paid_in_keur"])==60
    assert D(row(result,"A")["total_distributed_keur"])==84
    assert D(row(result,"A")["dpi"])==D("1.4")
    assert D(row(result,"B")["total_distributed_keur"])==36
    assert D(row(result,"B")["dpi"])==D("0.9")
    assert D(row(result,"A")["unreturned_capital_keur"])==60  # residual is NOT ROC


def test_multiple_classes_simple_pref_partial_roc_catchup_carry_and_residual():
    doc=agreement(
        classes=[{"id":"P","preferred_rate_pa":"0.10"},{"id":"C","preferred_rate_pa":None}],
        investors=[{"id":"A","class_id":"P","ownership_fraction":"0.5","commitment_keur":"100"},
                   {"id":"B","class_id":"C","ownership_fraction":"0.5","commitment_keur":"100"}],
        contributions=[{"investor_id":"A","date":"2030-01-01","amount_keur":"100"},
                       {"investor_id":"B","date":"2030-01-01","amount_keur":"100"}],
        stages=[stage("RETURN_OF_CAPITAL","P"),stage("PREFERRED_RETURN","P"),
                stage("RETURN_OF_CAPITAL","C"),stage("CATCH_UP",beneficiary="B",cap="10"),
                stage("CARRY",beneficiary="B",fraction="0.2"),stage("RESIDUAL")])
    # 2030->2031 365 days. First 150: ROC A 100, pref A 10, ROC B 40.
    # 2032: ROC B 60, catchup B 10, carry B (200-70)*20%=26,
    # residual 104 split 52/52.
    result=run(doc,receipts(("2030-01-01","200","0"),
                            ("2031-01-01","0","150"),
                            ("2032-01-01","0","200")))
    a,b=row(result,"A"),row(result,"B")
    assert [D(a[key]) for key in ("returned_capital_keur","paid_preference_keur","residual_keur")] == [D(100),D(10),D(52)]
    assert [D(b[key]) for key in ("returned_capital_keur","catch_up_keur","carry_keur","residual_keur")] == [D(100),D(10),D(26),D(52)]
    assert D(result["total_distributed_keur"])==350
    assert a["unreturned_capital_keur"]=="0" and b["unreturned_capital_keur"]=="0"
    assert a["accrued_unpaid_preference_keur"]=="0"
    assert result["period_trace"][1]["stages"][1]["paid_keur"]=="10.00"


def test_shortfall_pref_accrues_unpaid_without_imaginary_cash():
    doc=agreement(classes=[{"id":"ORD","preferred_rate_pa":"0.12"}],
                  stages=[stage("PREFERRED_RETURN","ORD"),stage("RETURN_OF_CAPITAL","ORD"),stage("RESIDUAL")])
    result=run(doc,receipts(("2030-01-01","100","0"),
                            ("2031-01-01","0","5"),
                            ("2032-01-01","0","0")))
    assert sum(D(r["paid_preference_keur"]) for r in result["investors"])==D(5)
    # Two years, 12% on full 100 =24, paid 5, unpaid 19.
    assert sum(D(r["accrued_unpaid_preference_keur"]) for r in result["investors"])==D(19)
    assert sum(D(r["returned_capital_keur"]) for r in result["investors"])==0


def test_actual_cash_flow_xirr_reconciles_to_independent_decimal_reference():
    doc=agreement(investors=[{"id":"A","class_id":"ORD","ownership_fraction":"1","commitment_keur":"100"}],
                  contributions=[{"investor_id":"A","date":"2030-01-01","amount_keur":"100"}],
                  stages=[stage("RESIDUAL")])
    result=run(doc,receipts(("2030-01-01","100","0"),("2031-01-01","0","110")))
    actual=row(result,"A")
    assert abs(actual["xirr"]-0.1)<1e-12
    assert actual["xirr_status"]=="OK"
    assert D(actual["realized_cash_moic"])==D("1.1")


def test_zero_cash_no_automatic_return_of_principal_and_honest_status():
    result=run(agreement(),receipts(("2030-01-01","100","0"),
                                    ("2031-01-01","0","0")))
    assert all(r["xirr"] is None and r["xirr_status"]=="NO_POSITIVE_CASHFLOW" for r in result["investors"])
    assert result["total_distributed_keur"]=="0"


@pytest.mark.parametrize("edit,code",[
    (lambda x: x.update(approval="ACTIVE"),"P2_POLICY_UNAPPROVED"),
    (lambda x: x.update(preferred_method="IRR_HURDLE"),"P2_POLICY_UNAPPROVED"),
    (lambda x: x.update(day_count="ACT_360"),"P2_POLICY_UNAPPROVED"),
    (lambda x: x.update(negative_distribution="ZERO_FLOOR"),"P2_POLICY_UNAPPROVED"),
    (lambda x: x["classes"].append(dict(x["classes"][0])),"P2_CLASS_DUPLICATE"),
    (lambda x: x["investors"].append(dict(x["investors"][0])),"P2_INVESTOR_DUPLICATE"),
    (lambda x: x["investors"][0].update(class_id="UNDECLARED"),"P2_CLASS_UNDECLARED"),
    (lambda x: x["investors"][0].update(ownership_fraction="0.8"),"P2_OWNERSHIP_INVALID"),
    (lambda x: x["investors"][0].update(commitment_keur="20"),"P2_COMMITMENT_EXCEEDED"),
    (lambda x: x["stages"].pop(),"P2_RESIDUAL_INVALID"),
    (lambda x: x["stages"].insert(0, stage("CARRY",beneficiary="B")),"P2_AMOUNT_TYPE"),
    (lambda x: x["stages"].insert(0,stage("PREFERRED_RETURN","ORD")),"P2_PREFERENCE_INCOMPLETE"),
    (lambda x: x["stages"].insert(0,stage("CATCH_UP",beneficiary="B",cap="0")),"P2_CATCHUP_INCOMPLETE"),
    (lambda x: x["stages"].insert(0,stage("CARRY",beneficiary="B",fraction="1")),"P2_CARRY_INCOMPLETE"),
])
def test_invalid_and_unsupported_contracts_fail_closed(edit,code):
    obj=agreement()
    edit(obj)
    with pytest.raises(P2ContractError) as exc:
        parse_contract(json.dumps(obj))
    assert exc.value.code==code


def test_duplicate_json_key_and_nonfinite_input_rejected():
    src=json.dumps(agreement()).replace('"approval": "CANDIDATE_NOT_AUTHORIZED",',
            '"approval": "CANDIDATE_NOT_AUTHORIZED", "approval": "ACTIVE",')
    with pytest.raises(P2ContractError):parse_contract(src)
    src=json.dumps(agreement()).replace('"commitment_keur": "200"', '"commitment_keur": NaN',1)
    with pytest.raises(P2ContractError):parse_contract(src)


@pytest.mark.parametrize("mutate,code",[
    (lambda x: x["periods"][1].update(net_equity_receipt_keur="-1"),"P2_CANONICAL_AMOUNT_INVALID"),
    (lambda x: x["periods"][1].update(net_equity_receipt_keur=None),"P2_CANONICAL_AMOUNT_INVALID"),
    (lambda x: x["periods"][1].update(net_equity_receipt_keur="900"),"P2_GROSS_WHT_NET"),
    (lambda x: x["periods"][0].update(paid_in_keur="0"),"P2_PAID_IN_MISMATCH"),
    (lambda x: x["periods"][1].update(date="2030-01-01"),"P2_PERIOD_ORDER"),
    (lambda x: x.update(source="CFADS"),"P2_RECEIPT_AUTHORITY"),
    (lambda x: x.update(return_status=None),"P2_RETURN_STATUS_MISSING"),
])
def test_unverified_invalid_canonical_receipt_rejected(mutate,code):
    src=receipts(("2030-01-01","100","0"),("2031-01-01","0","100"))
    mutate(src)
    with pytest.raises(P2ContractError) as exc:run(agreement(),src)
    assert exc.value.code==code


def test_binding_identity_and_evidence_digest_mutations_fail_closed():
    src=receipts(("2030-01-01","100","0"),("2031-01-01","0","100"))
    doc=agreement()
    with pytest.raises(P2ContractError, match="P2_BINDING_INVALID"):
        evaluate_p2_candidate(json.dumps(doc),src,binding={"owner_id":"no"})
    result=run(doc,src)
    for key,value in [("production_export","ENABLED"),("release_status","APPROVED"),
                      ("total_distributed_keur","1"),("agreement_digest","tampered")]:
        altered=copy.deepcopy(result)
        altered[key]=value
        with pytest.raises(P2ContractError):validate_candidate_projection(altered)
    assert validate_candidate_projection(result)==result


def test_original_agreement_not_mutated_and_idempotent_digest():
    obj=agreement()
    before=copy.deepcopy(obj)
    src=receipts(("2030-01-01","100","0"),("2031-01-01","0","100"))
    a,b=run(obj,src),run(obj,src)
    assert obj==before and a==b and a["digest"]==b["digest"]


def test_real_engine_authority_paths_are_not_imported_or_activated():
    source=(ROOT/"app/model_v2/investor_f4_candidate/p2_evaluator.py").read_text()
    contract=(ROOT/"app/model_v2/investor_f4_candidate/p2_contracts.py").read_text()
    assert "run_operating_model" not in (source+contract)
    assert "v2_atomic_run_commit" not in (source+contract)
    assert "evaluate_p2_candidate" not in (ROOT/"app/model_v2/investor_f4_candidate/p2_contracts.py").read_text()
    assert '"production_export":"BLOCKED"' in source  # explicit release gate
