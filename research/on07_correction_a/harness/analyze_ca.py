#!/usr/bin/env python3
"""Correction A analysis: runs/identities table, ON-05 oracle reconciliation, output exposure, true-route baseline CSV.
Reads capture JSON only. The ON-05 oracle (user-supplied, stdlib only, read before use) is loaded by path.
python -I analyze_ca.py --repo R --template TPL --oracle ON05/harness/oracle.py --groups LABEL:ROUTE_CLASS:dir1[,dir2..] ... --out DIR"""
import argparse, csv, importlib.util, json, math, os, sys
from datetime import date
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import on07_common as C
ap = argparse.ArgumentParser(); ap.add_argument("--repo", required=True); ap.add_argument("--template", required=True); ap.add_argument("--oracle", required=True)
ap.add_argument("--group", action="append", required=True, help="ROUTE_CLASS|run_label|fixture|dir1,dir2,dir3 (dirs = independent DB repeats)"); ap.add_argument("--out", required=True); a = ap.parse_args()
C.repo_setup(a.repo); os.makedirs(a.out, exist_ok=True)
spec = importlib.util.spec_from_file_location("on05_oracle", a.oracle); O = importlib.util.module_from_spec(spec); sys.modules["on05_oracle"] = O; spec.loader.exec_module(O)
from app.workbook import dscr_contract_terms as T
TOL, RATIO = 1e-6, 1e-7

def senior(cap): return (cap.get("integrity_evidence") or {}).get("senior_debt", {}).get("periods") or []

def checks(cap):
    r = {}
    fe = cap["financing_evidence"]; su = fe["sources_uses"]; P = senior(cap)
    srcs_full = su["total_sources_keur"]; uses_full = su["total_uses_keur"]
    r["IDENT-01 sources=uses (FULL PRECISION, financing_evidence.sources_uses)"] = ("PASS" if abs(uses_full - srcs_full) <= TOL and abs(su["difference_keur"]) <= TOL else "FAIL",
        {"total_uses": uses_full, "total_sources": srcs_full, "abs_diff": abs(uses_full - srcs_full), "engine_reported_difference": su["difference_keur"], "tolerance": TOL})
    p6 = cap["sources_uses"]; comp = sum(p6[k] for k in ("senior_debt_keur", "junior_or_other_keur", "share_capital_and_other_equity_keur", "shareholder_loan_cash_keur"))
    r["INFO payload sources_uses is 6-dp quantised"] = ("INFO", {"recomputed_from_6dp_components_abs_diff": abs(p6["total_uses_keur"] - comp), "explains_prior_6dp_edge": abs(p6["total_uses_keur"] - comp) > 5e-7})
    rates = [p["annual_rate"] for p in P]; fracs = [p["day_fraction"] for p in P]
    rep = O.identity_report(P, committed_debt=su["senior_debt_keur"], rates=rates, fracs=fracs, tol=TOL)
    for k, v in rep["worst"].items(): r[f"ON05 identity_report.{k}"] = ("PASS" if v <= (TOL if k != "dscr" else O.TOL_RATIO * 100) else "FAIL", {"worst_abs_dev": v})
    # independent re-sculpting from the ENGINE'S OWN rate/day-fraction/CFADS(bank)/target/availability inputs
    idx = [p["period_index"] for p in P]; live = [p["period_index"] for p in P if p["debt_service"] > 1e-6]
    rows = O.sculpted_roll(P[0]["opening"], idx, rates, fracs, [p["bank_cfads"] for p in P], [p["target_dscr"] or 0.0 for p in P], [p["availability"] for p in P], min(live), max(live))
    dev_p = max(abs(x.principal - p["principal"]) for x, p in zip(rows, P)); dev_c = max(abs(x.closing - p["closing"]) for x, p in zip(rows, P))
    r["ON05 sculpted_roll reproduces engine principal/closing (bank CFADS, target, availability)"] = ("PASS" if max(dev_p, dev_c) <= TOL else "DEVIATION_RECORDED", {"max_abs_principal_dev": dev_p, "max_abs_closing_dev": dev_c, "tolerance": TOL,
        "note": "definition identity assumed: ds_t=bank_cfads/target*availability, principal=clip(ds-interest,0,opening); a deviation is reported, not forced"})
    e3 = max([abs(p["base_cfads"] / p["debt_service"] - p["reported_dscr"]) for p in P if p["debt_service"] > 1e-6] or [0])
    mn = min(p["reported_dscr"] for p in P if p["debt_service"] > 1e-6)
    r["DSCR min profile = kpis.min_dscr"] = ("PASS" if abs(mn - cap["kpis"]["min_dscr"]) <= RATIO else "FAIL", {"profile_min": mn, "kpi": cap["kpis"]["min_dscr"], "dscr_numerator_denominator_max_dev": e3})
    fc_ = P[-1]["closing"]; balloon = cap["integrity_evidence"]["senior_debt"].get("permit_terminal_balloon")
    r["IDENT-02d final senior closing vs 1e-6 ladder"] = ("PASS" if abs(fc_) <= TOL else "RESIDUAL_ABOVE_1E-6_RECORDED", {"final_closing_keur": fc_, "ladder": TOL, "permit_terminal_balloon": balloon,
        "note": "repo integrity check (app/run_integrity/checks.py:194) requires a ~zero terminal balance only when permit_terminal_balloon is false; not re-labelled as a pass at a wider tolerance"})
    sp = cap["integrity_evidence"]["sponsor"]["periods"]; s = cap["sponsor_schedule"]["summary"]
    net = math.fsum(x["total_sponsor_net"] for x in sp); want = s["total_sponsor_receipts_keur"] - s["total_sponsor_contributed_keur"]
    r["SPONSOR sum(total_sponsor_net) = receipts - contributions"] = ("PASS" if abs(net - want) <= TOL else "FAIL", {"sum_net": net, "receipts_minus_contributions": want})
    flows = [x["total_sponsor_net"] for x in sp]; dts = [date.fromisoformat(x["date"][:10]) for x in sp]
    ox = O.xirr(flows, dts); ex = cap["kpis"]["total_sponsor_xirr"]
    r["ON05 xirr vs engine Total Sponsor XIRR (ACT/365 bisection)"] = ("PASS" if ox is not None and abs(ox - ex) <= 1e-9 else "DEVIATION_RECORDED", {"oracle_xirr": ox, "engine_xirr": ex, "abs_dev": None if ox is None else abs(ox - ex), "tolerance": 1e-9, "note": "flows/dates = integrity_evidence.sponsor.periods; engine date convention not proven identical"})
    cf = fe["construction_funding"]["periods"]
    ncf = fe["construction_funding"]["non_construction_fc_use"]
    sd = math.fsum(c["senior_draw_keur"] for c in cf) + ncf["senior_draw_keur"]
    r["IDENT periodic senior draws + non-construction FC senior draw = senior commitment"] = ("PASS" if abs(sd - su["senior_debt_keur"]) <= TOL else "FAIL", {"periodic_draws": math.fsum(c["senior_draw_keur"] for c in cf), "non_construction_fc_senior_draw": ncf["senior_draw_keur"], "sum": sd, "commitment": su["senior_debt_keur"]})
    cu = math.fsum(c["project_cash_uses_keur"] for c in cf) + ncf["uses_keur"]
    r["IDENT periodic uses + non-construction FC uses = total_audit_uses"] = ("PASS" if abs(cu - fe["construction_funding"]["total_audit_uses_keur"]) <= TOL else "FAIL", {"sum": cu, "audit_total": fe["construction_funding"]["total_audit_uses_keur"]})
    pn = cap["financial_statements"]["pnl"]["periods"]
    eb = math.fsum(x["revenues_keur"] - x["operating_expenses_keur"] for x in pn)
    bound = 0.01 * len(pn)  # two series per period, each quantised to 2 dp (<=0.005) -> <=0.01 per period
    r["IDENT sum(pnl revenue-opex) = kpis.total_ebitda (2-dp quantisation bound)"] = ("PASS_WITHIN_2DP_QUANTISATION" if abs(eb - cap["kpis"]["total_ebitda_keur"]) <= bound else "DEVIATION_RECORDED", {"pnl_sum": eb, "kpi": cap["kpis"]["total_ebitda_keur"], "abs_dev": abs(eb - cap["kpis"]["total_ebitda_keur"]), "bound": bound, "note": "NOT a 1e-6 identity: the pnl payload is rounded to 2 dp; full-precision EBITDA per period is not exposed"})
    r["IDENT-04 cash conservation"] = ("NOT_EVALUATED", "no machine-readable template identity; not invented")
    return r, rep

def cov(cap):
    P = senior(cap); dates = {p["period"]: p["date"] for p in cap["debt_schedule"]["periods"]}; rows = T.test_rows(P, dates)
    mk = lambda snap: T.read_run_terms({T.IDENTITY_KEY: T.capture(snap)})
    f = T.evaluate(mk({}), rows)
    return {"achieved_min": f["achieved_min_dscr"].get("min"), "coverage": f["coverage"]["status"], "eod": f["eod"]["status"], "covenant": f["covenant"]["status"]}

runs, ident, base, exposure_seen = [], [], [], {}
tpl = list(csv.DictReader(open(a.template, newline="")))
def val(m, cap, cv):
    k = cap["kpis"]; fe = cap["financing_evidence"]; P = senior(cap); pn = cap["financial_statements"]["pnl"]["periods"]; cf = fe["construction_funding"]["periods"]
    j = json.dumps
    ext = {
     "EBITDA-02": ("ENGINE_AVAILABLE_BUT_HARNESS_MISSING", j([[x["date"], x["revenues_keur"] - x["operating_expenses_keur"]] for x in pn]), "financial_statements.pnl.periods[] revenues_keur - operating_expenses_keur (derived; 2-dp)"),
     "OPEX-02": ("ENGINE_AVAILABLE_BUT_HARNESS_MISSING", j([[x["date"], x["operating_expenses_keur"]] for x in pn]), "financial_statements.pnl.periods[].operating_expenses_keur (2-dp)"),
     "CAPEX-02": ("ENGINE_AVAILABLE_BUT_HARNESS_MISSING", j([[c["period_index"], c["project_cash_uses_keur"]] for c in cf]), "financing_evidence.construction_funding.periods[].project_cash_uses_keur (full precision)"),
     "DEBT-01": ("ENGINE_AVAILABLE_BUT_HARNESS_MISSING", j([[c["period_index"], c["senior_draw_keur"]] for c in cf]), "financing_evidence.construction_funding.periods[].senior_draw_keur"),
     "RES-02": ("ENGINE_AVAILABLE_BUT_HARNESS_MISSING", j([[x["date"], x["dsra_contribution_keur"]] for x in cap["debt_schedule"]["periods"]]), "debt_schedule.periods[].dsra_contribution_keur (net contribution only; top-up/draw/release split NOT exposed)"),
     "STATE-01": ("ENGINE_AVAILABLE_BUT_HARNESS_MISSING", j({"digest": C.sha(cap["financial_statements"]), "pnl_periods": len(pn)}), "financial_statements (pnl, balance_sheet, pf_cash_waterfall) digest; full payload in capture"),
     "WARN-01": ("ENGINE_AVAILABLE_BUT_HARNESS_MISSING", j({"binding_senior_constraint": fe["bankability"]["binding_senior_constraint"], "diagnostics_binding_constraint": cap["integrity_evidence"]["senior_debt"]["diagnostics"]["binding_constraint"]}), "financing_evidence.bankability.binding_senior_constraint; integrity_evidence.senior_debt.diagnostics"),
     "WARN-02": ("ENGINE_AVAILABLE_BUT_HARNESS_MISSING", j(cap.get("messages")), "run payload messages (the /api/v1/validate warnings list is a v1-API surface, not run in this study)"),
     "TAX-03": ("NOT_EXPOSED_BY_PAYLOAD", j([[x["date"], x["taxable_profit_keur"]] for x in cap["tax_schedule"]["periods"]]), "tax_schedule.periods[].taxable_profit_keur present; loss-ledger/audit fields (tax_loss_*_audit_keur) are null -> loss ledger NOT exposed"),
     "NPV-01": ("NOT_CONFIGURED", "", "financing_evidence.financial_core_v1.valuation_summary.project_npv.status = NOT_CONFIGURED (no valuation policy/discount rate); kpis.project_npv_keur None"),
     "NPV-02": ("NOT_CONFIGURED", "", "equity NPV: valuation policy absent; kpis.equity_npv_keur None; sponsor_npv status see financial_core_v1.sponsor_npv"),
     "LLCR-01": ("NOT_CONFIGURED", "", "valuation_summary.lender_coverage.llcr.status = COVERAGE_CFADS_CASE_NOT_CONFIGURED; senior llcr_inputs.llcr_status = NOT_COMPUTED_BY_THIS_EVIDENCE"),
     "PLCR-01": ("NOT_COMPUTED", "", "kpis.plcr None; tables.returns carries 'n/a' rows; no PLCR vector in payload"),
     "DSCR-04": ("PERSISTED_RUN_AVAILABLE", j(cv), "PURE evaluation of app.workbook.dscr_contract_terms on sealed per-period evidence; fixtures carry NO contractual terms (NOT_CONFIGURED); Run-bound verdict exists only for a committed Run (last_runtime_identity.dscr_contract_terms)"),
     "PROV-01": ("PERSISTED_RUN_AVAILABLE", cap["input_fingerprint"], "local sha256(repr(effective ProjectInputs)); engine EngineProvenance.input_fingerprint / composite_hash / history_id exist only for a committed Run"),
     "PROV-02": ("ENGINE_AVAILABLE_BUT_HARNESS_MISSING", "", "tools/numerical_validation/reconcile.py state vocabulary not executed in this study"),
     "IDENT-02": ("ENGINE_AVAILABLE_BUT_HARNESS_MISSING", "see identity table", "computed here from integrity_evidence.senior_debt (see FIXTURE_RUNS_AND_IDENTITIES.csv)"),
     "IDENT-03": ("ENGINE_AVAILABLE_BUT_HARNESS_MISSING", "see identity table", "DSCR = base_cfads/debt_service, full precision"),
     "IDENT-04": ("NOT_EXPOSED_BY_PAYLOAD", "", "no template-defined cash-conservation identity is machine-readable; not invented"),
    }
    return ext.get(m)

registry = {}
for g in a.group:
    route, label, fid, dirs = g.split("|"); dirs = dirs.split(",")
    caps = []
    for d in dirs:
        p = os.path.join(d, f"{fid}.json")
        if os.path.exists(p): caps.append(json.load(open(p)))
    cap = caps[0]; digests = {c.get("evidence_digest") for c in caps}
    row = {"record_type": "RUN", "route_class": route, "run_label": label, "fixture": fid, "db_repeats": len(caps), "status": cap["status"], "reproducible_across_repeats": (len(digests) == 1 and None not in digests) if cap["status"] == "RUN_OK" else ("same_refusal" if len({c.get("error") for c in caps}) == 1 else "REFUSAL_VARIES"),
           "evidence_digest": cap.get("evidence_digest", ""), "refusal": (cap.get("error") or "")[:200]}
    if cap["status"] == "RUN_OK":
        k = cap["kpis"]; ex = {x: v for x, v in cap.get("intended_vs_effective", {}).items()}
        ceil_ = next((v["intended"] for x, v in ex.items() if x == "gearing_pct"), "")
        row.update(input_gearing_ceiling_pct=ceil_, executed_gearing_pct=round(k["actual_gearing_pct"] * 100, 4), total_capex_keur=k["total_capex_keur"], senior_debt_keur=k["senior_debt_keur"],
                   min_dscr=k["min_dscr"], avg_dscr=k["avg_dscr"], equity_irr_share_capital=k["equity_irr"], total_sponsor_xirr=k["total_sponsor_xirr"], project_irr=k["project_irr"], periods_in_lockup=k["periods_in_lockup"],
                   input_mismatches=";".join(x for x, v in ex.items() if v["verdict"] != "MATCH") or "NONE")
        rr, rep = checks(cap); cv = cov(cap); row["covenant_eval"] = json.dumps(cv)
        for n, (s, d) in rr.items(): ident.append({"record_type": "IDENTITY", "route_class": route, "run_label": label, "fixture": fid, "identity": n, "status": s, "detail": json.dumps(d)})
        for t in tpl:
            m = t["metric_id"]; b = {"route_class": route, "run_label": label, "fixture_id": fid, "metric_id": m, "metric": t["metric"], "units": t["units"], "tolerance": t["tolerance"], "tolerance_authority": t["tolerance_authority"],
                 "finco_local_value": "", "extraction_path": "", "exposure_class": "", "obs_react": "", "obs_legacy": "", "obs_competitor": "", "discrepancy_class": "", "evidence_digest": cap["evidence_digest"]}
            e = val(m, cap, cv)
            if e: b["exposure_class"], b["finco_local_value"], b["extraction_path"] = e
            else:
                import analyze_captures as S
                v = S.metric_value(m, cap)
                if v is None: b["exposure_class"] = "UNCLASSIFIED_REVIEW"
                else: b["exposure_class"], b["finco_local_value"], b["extraction_path"] = "EXTRACTED_LOCAL_ENGINE", v[0], v[1]
            base.append(b); registry.setdefault(m, set()).add(b["exposure_class"])
    else:
        for t in tpl:
            base.append({"route_class": route, "run_label": label, "fixture_id": fid, "metric_id": t["metric_id"], "metric": t["metric"], "units": t["units"], "tolerance": t["tolerance"], "tolerance_authority": t["tolerance_authority"],
                         "finco_local_value": "", "extraction_path": "", "exposure_class": "REFUSED_NO_RUN", "obs_react": "", "obs_legacy": "", "obs_competitor": "", "discrepancy_class": "", "evidence_digest": ""})
    runs.append(row)
cols = sorted({c for r in runs for c in r}, key=lambda c: (c != "record_type", list(runs[0]).index(c) if c in runs[0] else 99, c))
with open(os.path.join(a.out, "FIXTURE_RUNS_AND_IDENTITIES.csv"), "w", newline="") as f:
    w = csv.writer(f); allc = ["record_type", "route_class", "run_label", "fixture", "db_repeats", "status", "reproducible_across_repeats", "evidence_digest", "input_gearing_ceiling_pct", "executed_gearing_pct", "total_capex_keur", "senior_debt_keur", "min_dscr", "avg_dscr", "equity_irr_share_capital", "total_sponsor_xirr", "project_irr", "periods_in_lockup", "input_mismatches", "covenant_eval", "refusal", "identity", "identity_status", "identity_detail"]
    w.writerow(allc)
    for r in runs: w.writerow([r.get(c, "") for c in allc])
    for i in ident: w.writerow([i["record_type"], i["route_class"], i["run_label"], i["fixture"]] + [""] * 17 + [i["identity"], i["status"], i["detail"]])
bc = list(base[0]); csv.DictWriter(open(os.path.join(a.out, "ON07_LOCAL_BASELINE_TRUE_ROUTE.csv"), "w", newline=""), fieldnames=bc).writeheader()
with open(os.path.join(a.out, "ON07_LOCAL_BASELINE_TRUE_ROUTE.csv"), "w", newline="") as f:
    w = csv.DictWriter(f, fieldnames=bc); w.writeheader(); w.writerows(base)
from collections import Counter
print(Counter(i["status"] for i in ident)); print(Counter(b["exposure_class"] for b in base))
print([ (i["fixture"], i["run_label"], i["identity"][:50], i["status"]) for i in ident if i["status"] not in ("PASS","INFO","INFO_NOT_ASSERTED")][:20])
