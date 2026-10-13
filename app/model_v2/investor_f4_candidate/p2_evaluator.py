"""OFFLINE F4/P2 candidate: deterministic contractual-stage attribution only.

Never imported by F4/P1 Save/Run/export. Caller-supplied receipts must already be
canonical G2C net legal equity cash; this module cannot attest their Run provenance.
No tax, SHL, debt, valuation, NAV, or institutional policy activation is implied.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal, InvalidOperation, Context, localcontext
from hashlib import sha256
import json
import math

from .p2_contracts import Contract, P2ContractError, canonical, dte, need, parse_contract

D = Decimal
CANONICAL_RECEIPT_SOURCE = "CovenantGatedWaterfallResult.net_dividend_received_keur"
P1_CASH_TOLERANCE_KEUR = D("0.000001")  # mirror P1 read-only bridge; not a changed engine tolerance
ALLOWED_UPSTREAM_STATUSES = frozenset({"OK", "NO_NEGATIVE_CASHFLOW", "NO_POSITIVE_CASHFLOW",
    "ZERO_CONTRIBUTION", "NON_CONVERGENT", "UNDEFINED",
    "UPSTREAM_FINANCIAL_FEEDBACK_NOT_CLOSED", "UNPAID_SHL_AT_CONTRACTUAL_MATURITY"})


def _canonical_amount(raw, label):
    """Permit native FINCO float output, but reject bool, NaN, negatives or missing."""
    need(type(raw) in (str, int, float, Decimal), "P2_CANONICAL_AMOUNT_INVALID", label)
    try:
        value = D(str(raw))
    except InvalidOperation as exc:
        raise P2ContractError("P2_CANONICAL_AMOUNT_INVALID", label) from exc
    need(value.is_finite() and value >= 0, "P2_CANONICAL_AMOUNT_INVALID", label)
    return value


def _receipt_axis(receipt, contract):
    need(type(receipt) is dict and receipt.get("schema_version") == 1 and
         receipt.get("source") == CANONICAL_RECEIPT_SOURCE and
         type(receipt.get("periods")) is list and bool(receipt["periods"]),
         "P2_RECEIPT_AUTHORITY", "P1/G2C net equity receipt payload required")
    periods = []
    previous = None
    expected_contrib = {}
    for c in contract.contributions:
        expected_contrib[c.when] = expected_contrib.get(c.when, D(0)) + c.amount
    for raw in receipt["periods"]:
        need(type(raw) is dict and set(raw) == {"date", "paid_in_keur", "net_equity_receipt_keur",
                                                      "gross_dividend_keur", "dividend_wht_keur"},
             "P2_RECEIPT_SCHEMA", "canonical G2C period fields")
        when = dte(raw["date"], "cashflow date")
        need(previous is None or when > previous, "P2_PERIOD_ORDER", "strictly ordered unique dates")
        previous = when
        paid = _canonical_amount(raw["paid_in_keur"], "actual paid-in")
        cash = _canonical_amount(raw["net_equity_receipt_keur"], "net legal equity cash")
        gross = _canonical_amount(raw["gross_dividend_keur"], "gross legal equity cash")
        wht = _canonical_amount(raw["dividend_wht_keur"], "upstream WHT")
        need(abs(gross-wht-cash) <= P1_CASH_TOLERANCE_KEUR,
             "P2_GROSS_WHT_NET", "canonical gross less WHT must equal net")
        need(abs(paid-expected_contrib.get(when,D(0))) <= P1_CASH_TOLERANCE_KEUR,
             "P2_PAID_IN_MISMATCH", "agreement paid-in must match actual dated G2C funds")
        periods.append((when,paid,cash,gross,wht))
    need(set(expected_contrib) <= {p[0] for p in periods}, "P2_CONTRIBUTION_OFF_AXIS",
         "actual contribution cash date not on G2C axis")
    need(type(receipt.get("return_status")) is str and receipt["return_status"] in ALLOWED_UPSTREAM_STATUSES,
         "P2_RETURN_STATUS_MISSING", "upstream dated return status must be an approved enum value")
    return tuple(periods)


def _alloc_pro_rata(pool, entitlements):
    """Capped, simultaneous pro-rata awards, with exact Decimal conservation."""
    entitlements = {k:v for k,v in entitlements.items() if v>0}
    if pool == 0 or not entitlements:
        return {k:D(0) for k in entitlements}
    total=sum(entitlements.values(), D(0))
    paid=min(pool,total)
    names=sorted(entitlements)
    result={k:paid*entitlements[k]/total for k in names[:-1]}
    result[names[-1]]=paid-sum(result.values(),D(0))
    return result


def _post_format(value):
    return ('0' if value == 0 else format(value,'f')) if isinstance(value,D) else value


def _run_xirr(flows,dates,xirr_calculator):
    if not any(v<0 for v in flows):
        return None, "NO_NEGATIVE_CASHFLOW"
    if not any(v>0 for v in flows):
        return None, "NO_POSITIVE_CASHFLOW"
    try:
        if xirr_calculator is None:
            from finco_core.sponsor.xirr import robust_xirr
            xirr_calculator=robust_xirr
        result=xirr_calculator([float(v) for v in flows],dates)
    except ImportError:
        return None, "CANONICAL_XIRR_UNAVAILABLE"
    if result is None or not math.isfinite(result):
        return None, "NON_CONVERGENT"
    return result, "OK"


def _evaluate_p2_candidate(contract: Contract | str, receipt: dict, *, binding: dict,
                           xirr_calculator=None) -> dict:
    """Pure pre-approval projection; NOT an F4/P1 replacement or Run evidence.

    A valid binding is checked for structure only. No attestation of upstream
    execution is possible offline and the result is NEVER export-approved.
    """
    if type(contract) is str:
        contract=parse_contract(contract)
    need(isinstance(contract,Contract), "P2_CONTRACT_REQUIRED", "typed candidate agreement required")
    # A caller can manually instantiate a frozen dataclass. A typed object is
    # NEVER authority to bypass the canonical versioned JSON/policy validator.
    independently_parsed = parse_contract(contract.document)
    need(independently_parsed == contract, "P2_CONTRACT_FORGED",
         "typed agreement differs from its independently validated content/digest")
    expected_binding={"owner_id", "project_id", "scenario_id", "snapshot_id", "composite_hash"}
    need(type(binding) is dict and set(binding)==expected_binding and
         all(type(binding[k]) is str and bool(binding[k].strip()) for k in
             expected_binding-{"scenario_id"}) and
         (binding["scenario_id"] is None or type(binding["scenario_id"]) is str),
         "P2_BINDING_INVALID", "explicit owner/project/scenario/snapshot/hash required")
    periods=_receipt_axis(receipt,contract)
    ids={i.id:i for i in contract.investors}
    classes={c.id:c for c in contract.classes}
    accounts={key:{"paid":D(0),"principal":D(0),"pref_due":D(0),"roc":D(0),
                    "pref_paid":D(0),"catchup":D(0),"carry":D(0),"residual":D(0),
                    "events":[]} for key in ids}
    caps={i:D(0) for i,s in enumerate(contract.stages) if s.kind=="CATCH_UP"}
    contributions={}
    for c in contract.contributions:
        contributions[(c.when,c.investor_id)] = contributions.get((c.when,c.investor_id),D(0))+c.amount
    last=None
    period_trace=[]
    for when, actual_paid,available,gross,wht in periods:
        # Accrual to this exact payment date; contributions on date start earning
        # only after the event. Return of capital reduces future principal.
        days=0 if last is None else (when-last).days
        if last is not None:
            for iid, account in accounts.items():
                rate=classes[ids[iid].class_id].preferred_rate
                if rate is not None:
                    account["pref_due"]+=account["principal"]*rate*D(days)/D(365)
        last=when
        fresh={iid:contributions.get((when,iid),D(0)) for iid in ids}
        for iid, value in fresh.items():
            accounts[iid]["paid"]+=value
            accounts[iid]["principal"]+=value
        allocations={iid:{kind:D(0) for kind in ("RETURN_OF_CAPITAL","PREFERRED_RETURN","CATCH_UP","CARRY","RESIDUAL")}
                     for iid in ids}
        left=available
        stage_trace=[]
        for n, stage in enumerate(contract.stages):
            before=left
            if stage.kind in ("RETURN_OF_CAPITAL", "PREFERRED_RETURN"):
                eligible={iid:(a["principal"] if stage.kind=="RETURN_OF_CAPITAL" else a["pref_due"])
                          for iid,a in accounts.items() if ids[iid].class_id==stage.class_id}
                awards=_alloc_pro_rata(left,eligible)
            elif stage.kind=="CATCH_UP":
                awards={stage.beneficiary_id:min(left,stage.cap-caps[n])}
            elif stage.kind=="CARRY":
                awards={stage.beneficiary_id:left*stage.fraction}
            else:
                awards={iid:left*i.ownership for iid,i in ids.items()}
                # Close Decimal division residual in the final deterministic ID.
                last_id=sorted(ids)[-1]
                awards[last_id]=left-sum((v for k,v in awards.items() if k!=last_id),D(0))
            debit=sum(awards.values(),D(0))
            need(all(v>=0 for v in awards.values()) and debit <= left,
                 "P2_CASH_VIOLATION", "candidate stage created or reversed cash")
            for iid, cash in awards.items():
                allocations[iid][stage.kind]+=cash
                account=accounts[iid]
                if stage.kind=="RETURN_OF_CAPITAL":
                    account["principal"]-=cash
                    account["roc"]+=cash
                elif stage.kind=="PREFERRED_RETURN":
                    account["pref_due"]-=cash
                    account["pref_paid"]+=cash
                elif stage.kind=="CATCH_UP":
                    account["catchup"]+=cash
                elif stage.kind=="CARRY":
                    account["carry"]+=cash
                else:
                    account["residual"]+=cash
            if stage.kind=="CATCH_UP":
                caps[n]+=debit
            left-=debit
            stage_trace.append({"order":n,"kind":stage.kind,"class_id":stage.class_id,
                                "beneficiary_id":stage.beneficiary_id,
                                "cash_before_keur":_post_format(before),
                                "paid_keur":_post_format(debit),"cash_after_keur":_post_format(left)})
        need(left==0 and sum((sum(v.values(),D(0)) for v in allocations.values()),D(0))==available,
             "P2_CASH_VIOLATION", "legal equity receipts must fully reconcile")
        for iid, a in accounts.items():
            v=allocations[iid]
            incoming=sum(v.values(),D(0))
            a["events"].append({"date":when.isoformat(),"contribution_keur":_post_format(fresh[iid]),
                "returned_capital_keur":_post_format(v["RETURN_OF_CAPITAL"]),
                "preferred_return_keur":_post_format(v["PREFERRED_RETURN"]),
                "catch_up_keur":_post_format(v["CATCH_UP"]),"carry_keur":_post_format(v["CARRY"]),
                "residual_keur":_post_format(v["RESIDUAL"]),"distribution_keur":_post_format(incoming),
                "net_cash_keur":_post_format(incoming-fresh[iid]),
                "unreturned_principal_keur":_post_format(a["principal"]),
                "unpaid_preference_keur":_post_format(a["pref_due"])})
        period_trace.append({"date":when.isoformat(),"canonical_gross_keur":_post_format(gross),
            "canonical_wht_keur":_post_format(wht),"available_net_equity_keur":_post_format(available),
            "allocated_keur":_post_format(available-left),"unallocated_keur":_post_format(left),
            "stages":stage_trace})
    output_investors=[]
    for iid, a in sorted(accounts.items()):
        i=ids[iid]
        dist=a["roc"]+a["pref_paid"]+a["catchup"]+a["carry"]+a["residual"]
        flows=[D(e["net_cash_keur"]) for e in a["events"]]
        dates=[date.fromisoformat(e["date"]) for e in a["events"]]
        xirr,status=_run_xirr(flows,dates,xirr_calculator) if receipt["return_status"]=="OK" else (None,receipt["return_status"])
        multiple=(dist/a["paid"] if a["paid"]>0 else None)
        output_investors.append({"id":iid,"class_id":i.class_id,"ownership_fraction":_post_format(i.ownership),
            "commitment_keur":_post_format(i.commitment),"paid_in_keur":_post_format(a["paid"]),
            "returned_capital_keur":_post_format(a["roc"]),"unreturned_capital_keur":_post_format(a["principal"]),
            "accrued_unpaid_preference_keur":_post_format(a["pref_due"]),
            "paid_preference_keur":_post_format(a["pref_paid"]),"catch_up_keur":_post_format(a["catchup"]),
            "carry_keur":_post_format(a["carry"]),"residual_keur":_post_format(a["residual"]),
            "total_distributed_keur":_post_format(dist),"dpi":_post_format(multiple),
            "realized_cash_moic":_post_format(multiple),"xirr":xirr,"xirr_status":status,
            "cash_events":a["events"]})
    total=sum((D(row["total_distributed_keur"]) for row in output_investors),D(0))
    source_cash=sum((p[2] for p in periods),D(0))
    need(total==source_cash,"P2_CASH_VIOLATION","lifetime investor allocations differ from actual net equity")
    evidence={"schema_version":2,"release_status":"CANDIDATE_NOT_AUTHORIZED",
        "source_attestation":"UNVERIFIED_OFFLINE_CALLER_INPUT",
        "run_history_binding":"NOT_COMMITTED", "production_export":"BLOCKED",
        "agreement_id":contract.agreement_id,"agreement_digest":contract.digest,
        "binding":dict(binding),"receipt_source":CANONICAL_RECEIPT_SOURCE,
        "currency":"EUR","unit":"kEUR","investors":output_investors,
        "period_trace":period_trace,"total_distributed_keur":_post_format(total),
        "total_upstream_net_equity_keur":_post_format(source_cash),
        "conservation_residual_keur":"0"}
    evidence["digest"]=sha256(canonical(evidence).encode()).hexdigest()
    return evidence



def evaluate_p2_candidate(contract: Contract | str, receipt: dict, *, binding: dict,
                          xirr_calculator=None) -> dict:
    """Stable Decimal arithmetic independent of ambient host precision changes."""
    with localcontext(Context(prec=50)):
        return _evaluate_p2_candidate(contract, receipt, binding=binding,
                                      xirr_calculator=xirr_calculator)

def validate_candidate_projection(evidence: dict) -> dict:
    need(type(evidence) is dict and evidence.get("schema_version")==2 and
         evidence.get("release_status")=="CANDIDATE_NOT_AUTHORIZED" and
         evidence.get("source_attestation")=="UNVERIFIED_OFFLINE_CALLER_INPUT" and
         evidence.get("receipt_source")==CANONICAL_RECEIPT_SOURCE and
         evidence.get("production_export")=="BLOCKED" and
         evidence.get("run_history_binding")=="NOT_COMMITTED", "P2_EXPORT_NOT_AUTHORIZED",
         "P2 candidate cannot be presented as persisted Run/approved export")
    d={k:v for k,v in evidence.items() if k!="digest"}
    need(sha256(canonical(d).encode()).hexdigest()==evidence.get("digest"),
         "P2_EVIDENCE_TAMPERED","read-only candidate content digest mismatch")
    need(type(evidence.get("investors")) is list and
         type(evidence.get("period_trace")) is list, "P2_EVIDENCE_TAMPERED", "missing read-only ledgers")
    individual_cash=sum((D(i["total_distributed_keur"]) for i in evidence["investors"]),D(0))
    period_cash=sum((D(p["allocated_keur"]) for p in evidence["period_trace"]),D(0))
    source_cash=sum((D(p["available_net_equity_keur"]) for p in evidence["period_trace"]),D(0))
    need(individual_cash == period_cash == source_cash == D(evidence["total_distributed_keur"])
         == D(evidence["total_upstream_net_equity_keur"]) and
         all(D(p["unallocated_keur"])==0 for p in evidence["period_trace"]),
         "P2_CASH_VIOLATION", "read-only investor/period/receipt cash invariant")
    for investor in evidence["investors"]:
        total=sum((D(investor[key]) for key in
                   ("returned_capital_keur", "paid_preference_keur", "catch_up_keur", "carry_keur", "residual_keur")),D(0))
        event_total=sum((D(e["distribution_keur"]) for e in investor["cash_events"]),D(0))
        need(total==event_total==D(investor["total_distributed_keur"]),
             "P2_CASH_VIOLATION", "investor subledger inconsistency")
    for p in evidence["period_trace"]:
        paid=sum((D(s["paid_keur"]) for s in p["stages"]),D(0))
        need(paid==D(p["allocated_keur"]),
             "P2_CASH_VIOLATION", "period stage trace inconsistency")
    return evidence
