#!/usr/bin/env python3
"""Post-process real captures -> ON07_LOCAL_BASELINE.csv, ACCOUNTING_IDENTITIES.csv, WF04_COVENANT_EVALUATION.json.
Reads only capture JSON files (never invents values). python -I analyze_captures.py --repo R --template ON07_OUTPUT_COMPARISON_TEMPLATE.csv --captures dir [dir...] --out dir"""
import argparse, csv, json, math, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import on07_common as C
FIX = ["SOL-01", "SOL-02", "WND-01", "WND-02"]
TOL = 1e-6  # kEUR ladder (template: KEUR_FULL 1e-6); ratio 1e-7

def sd_periods(cap): return (cap.get("integrity_evidence") or {}).get("senior_debt", {}).get("periods") or []

def identities_full(cap):
    out = {}
    su = cap.get("sources_uses") or {}
    srcs = sum(su.get(k, 0) or 0 for k in ("senior_debt_keur", "junior_or_other_keur", "share_capital_and_other_equity_keur", "shareholder_loan_cash_keur"))
    d = abs(su.get("total_uses_keur", math.nan) - srcs)
    # Payload components are quantised to 6 dp, so a recomputed sum may differ by exactly one quantum (1e-6); the engine's own
    # reported difference must still be <= 1e-6. Exact-quantum cases are labelled, never silently passed.
    st = "PASS" if d <= TOL * (1 + 1e-6) and abs(su.get("difference_keur", math.nan)) <= TOL else "FAIL"
    if st == "PASS" and d > TOL * 0.5: st = "PASS_AT_6DP_QUANTUM_EDGE"
    out["IDENT-01 sources_equal_uses"] = (st, {"total_uses": su.get("total_uses_keur"), "sum_sources": srcs, "recomputed_abs_diff": d, "reported_difference": su.get("difference_keur")})
    P = sd_periods(cap)
    if P:
        e1 = max(abs(p["debt_service"] - p["interest"] - p["principal"]) for p in P)
        e2 = max(abs(p["opening"] - p["principal"] - p["closing"]) for p in P)
        e3 = max([abs(a["closing"] - b["opening"]) for a, b in zip(P, P[1:])] or [0])
        live = [p for p in P if p["debt_service"] > 1e-6]
        e4 = max([abs(p["base_cfads"] / p["debt_service"] - p["reported_dscr"]) for p in live if p.get("reported_dscr") is not None] or [0])
        out["IDENT-02a interest_plus_principal_equals_debt_service"] = ("PASS" if e1 <= TOL else "FAIL", {"max_abs_err": e1, "periods": len(P)})
        out["IDENT-02b opening_minus_principal_equals_closing"] = ("PASS" if e2 <= TOL else "FAIL", {"max_abs_err": e2})
        out["IDENT-02c closing_t_equals_opening_t+1"] = ("PASS" if e3 <= TOL else "FAIL", {"max_abs_err": e3})
        out["IDENT-02d final_closing_zero"] = ("PASS" if abs(P[-1]["closing"]) <= TOL else "FAIL", {"final_closing": P[-1]["closing"]})
        out["IDENT-03 dscr_equals_base_cfads_over_debt_service"] = ("PASS" if e4 <= 1e-7 else "FAIL", {"max_abs_err": e4, "periods": len(live)})
        mn = min(p["reported_dscr"] for p in live if p.get("reported_dscr") is not None)
        out["DSCR min_profile_equals_kpi"] = ("PASS" if abs(mn - cap["kpis"]["min_dscr"]) <= 1e-7 else "FAIL", {"profile_min": mn, "kpi_min_dscr": cap["kpis"]["min_dscr"]})
        out["DEBT senior_drawn_equals_sources_senior"] = ("NOT_EVALUATED", "construction-draw schedule is not exposed in the run payload; not evaluated")
    sp = cap.get("sponsor_schedule") or {}
    try:
        net = math.fsum(p["total_sponsor_net"] for p in cap["integrity_evidence"]["sponsor"]["periods"]); s = sp["summary"]
        want = s["total_sponsor_receipts_keur"] - s["total_sponsor_contributed_keur"]
        out["SPONSOR sum(total_sponsor_net)=receipts-contributed"] = ("PASS" if abs(net - want) <= TOL else "FAIL", {"sum_net": net, "receipts_minus_contributed": want})
    except Exception as e:
        out["SPONSOR sum(total_sponsor_net)=receipts-contributed"] = ("NOT_EVALUATED", repr(e))
    out["IDENT-04 cash_conservation"] = ("NOT_EVALUATED", "no single exposed cash-waterfall identity defined in the run payload; template formula note not machine-readable")
    return out

def covenant(cap, fixture_terms=None, synthetic=None):
    from app.workbook import dscr_contract_terms as T
    dates = {p["period"]: p["date"] for p in cap["debt_schedule"]["periods"]}
    rows = T.test_rows(sd_periods(cap), dates)
    def mk(snapshot): return T.read_run_terms({T.IDENTITY_KEY: T.capture(snapshot)})
    res = {"fixture_terms(snapshot has none)": T.evaluate(mk({}), rows)}
    if synthetic: res["SYNTHETIC_ILLUSTRATION_NOT_FIXTURE " + json.dumps(synthetic)] = T.evaluate(mk(synthetic), rows)
    return res

def metric_value(m, cap):
    k, su, ds = cap["kpis"], cap.get("sources_uses") or {}, cap["debt_schedule"]["periods"]
    P = sd_periods(cap); ev = cap.get("derivation_evidence") or {}
    rp = (ev.get("revenue") or {}).get("revenue_periods")
    arr = lambda xs: json.dumps(xs)
    t = {
     "GEN-01": lambda: (math.fsum(p["generation_mwh"] for p in rp), "derivation_evidence.revenue.revenue_periods[].generation_mwh (sum)"),
     "GEN-02": lambda: (arr([[p["period_label"], p["generation_mwh"]] for p in rp]), "derivation_evidence.revenue.revenue_periods[]"),
     "REV-01": lambda: (k["total_revenue_keur"], "kpis.total_revenue_keur"),
     "REV-02": lambda: (arr([[p["period_label"], p["revenue_keur"]] for p in rp]), "derivation_evidence.revenue.revenue_periods[]"),
     "EBITDA-01": lambda: (k["total_ebitda_keur"], "kpis.total_ebitda_keur"),
     "CAPEX-01": lambda: (k["total_capex_keur"], "kpis.total_capex_keur"),
     "OPEX-01": lambda: (k["total_opex_keur"], "kpis.total_opex_keur"),
     "TAX-01": lambda: (k["total_tax_keur"], "kpis.total_tax_keur"),
     "TAX-02": lambda: (arr([[p["date"], p["corporate_tax_cash_keur"]] for p in cap["tax_schedule"]["periods"]]), "tax_schedule.periods[].corporate_tax_cash_keur (payload rounded 2dp)"),
     "CFADS-01": lambda: (arr([[p["period_index"], p["base_cfads"]] for p in P]), "integrity_evidence.senior_debt.periods[].base_cfads"),
     "CFADS-02": lambda: (arr([[p["period_index"], p["bank_cfads"]] for p in P]), "integrity_evidence.senior_debt.periods[].bank_cfads"),
     "DEBT-01": lambda: (json.dumps({x: su.get(x) for x in ("capitalized_idc_keur", "commitment_fee_keur", "structuring_fee_keur", "senior_debt_keur")}), "sources_uses (construction draw schedule not exposed)"),
     "DEBT-02": lambda: (k["senior_debt_keur"], "kpis.senior_debt_keur"),
     "DEBT-03": lambda: (arr([[p["period_index"], p["interest"]] for p in P]), "integrity_evidence.senior_debt.periods[].interest"),
     "DEBT-04": lambda: (arr([[p["period_index"], p["principal"]] for p in P]), "integrity_evidence.senior_debt.periods[].principal"),
     "DEBT-05": lambda: (arr([[p["period_index"], p["closing"]] for p in P]), "integrity_evidence.senior_debt.periods[].closing"),
     "DSCR-01": lambda: (arr([[p["period_index"], p["reported_dscr"]] for p in P if p["debt_service"] > 1e-6]), "integrity_evidence.senior_debt.periods[].reported_dscr (debt-service periods)"),
     "DSCR-02": lambda: (json.dumps({"min_dscr": k["min_dscr"], "avg_dscr": k["avg_dscr"]}), "kpis.min_dscr, kpis.avg_dscr"),
     "DSCR-03": lambda: (arr([[p["period_index"], p["bank_cfads"] / p["debt_service"]] for p in P if p["debt_service"] > 1e-6]), "derived bank_cfads/debt_service from integrity evidence (bank_sizing_dscr array not exposed)"),
     "EQU-01": lambda: (json.dumps({x: su.get(x) for x in ("share_capital_and_other_equity_keur", "shareholder_loan_cash_keur")}), "sources_uses"),
     "EQU-02": lambda: (k["total_distributions_keur"], "kpis.total_distributions_keur"),
     "RET-01": lambda: (json.dumps({"equity_irr": k["equity_irr"], "share_capital_irr": k["share_capital_irr"], "status": k["share_capital_irr_status"]}), "kpis"),
     "RET-02": lambda: (json.dumps({"total_sponsor_xirr": k["total_sponsor_xirr"], "status": k["total_sponsor_xirr_status"]}), "kpis"),
     "RET-03": lambda: (k["project_irr"], "kpis.project_irr"),
     "NPV-01": lambda: (k["project_npv_keur"], "kpis.project_npv_keur (None = not computed in payload)"),
     "NPV-02": lambda: (k["equity_npv_keur"], "kpis.equity_npv_keur (None = not computed in payload)"),
     "LLCR-01": lambda: (k["min_llcr"], "kpis.min_llcr (None = not computed in payload)"),
     "RES-01": lambda: (arr([[p["date"], p["dsra_balance_keur"]] for p in ds]), "debt_schedule.periods[].dsra_balance_keur (payload 2dp)"),
     "RES-03": lambda: (json.dumps({"initial_dsra_funding_keur": su.get("initial_dsra_funding_keur")}), "sources_uses.initial_dsra_funding_keur (C.18 reserve detail not exposed)"),
     "IDENT-01": lambda: (su.get("difference_keur"), "sources_uses.difference_keur"),
     "WARN-03": lambda: (json.dumps({"messages": cap.get("messages"), "authority": (cap.get("runtime_authority") or {}).get("classification")}), "run payload runtime_authority"),
     "PROV-01": lambda: (cap["input_fingerprint"], "sha256(repr(effective ProjectInputs)) - local stable fingerprint; NOT the engine EngineProvenance fingerprint or Run-history composite_hash"),
    }.get(m)
    return t() if t else None

def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--repo", required=True); ap.add_argument("--template", required=True); ap.add_argument("--captures", nargs="+", required=True); ap.add_argument("--out", required=True)
    a = ap.parse_args(); C.repo_setup(a.repo); os.makedirs(a.out, exist_ok=True)
    tpl = list(csv.DictReader(open(a.template, newline="")))
    base_rows, ident_rows, cov = [], [], {}
    for cdir in a.captures:
        variant = os.path.basename(cdir.rstrip("/"))
        for fid in FIX:
            path = os.path.join(cdir, fid + ".json")
            if not os.path.exists(path): continue
            cap = json.load(open(path)); ok = cap["status"] == "RUN_OK"
            if ok:
                for n, (s, d) in identities_full(cap).items(): ident_rows.append([variant, fid, n, s, json.dumps(d)])
                cov[f"{variant}/{fid}"] = covenant(cap, synthetic={"dscr_contractual_x": "1.50", "dscr_min_eod_x": "1.05"})
            else:
                ident_rows.append([variant, fid, "ALL", "NOT_EXECUTED", cap.get("error") or cap.get("status")])
            for t in tpl:
                m = t["metric_id"]; r = {"variant": variant, "fixture_id": fid, "metric_id": m, "metric": t["metric"], "units": t["units"], "tolerance": t["tolerance"],
                     "tolerance_authority": t["tolerance_authority"], "finco_output_path_template": t["finco_output_path"], "finco_local_value": "", "extraction_path": "",
                     "local_status": "", "run_status": cap["status"], "evidence_digest": cap.get("evidence_digest", ""), "obs_react": "", "obs_legacy": "", "obs_competitor": "", "discrepancy_class": "", "note": ""}
                if not ok:
                    r["local_status"] = "REFUSED_NO_VALUE" if cap["status"].startswith("REFUSED") else "NOT_EXECUTED"; r["note"] = cap.get("error", "")[:200]
                elif m == "DSCR-04":
                    r["local_status"] = "NOT_IN_RUN_PAYLOAD"; r["note"] = "Covenant status is a Run-bound v2 projection (see WF04_COVENANT_EVALUATION.json); fixtures carry no contractual DSCR terms -> NOT_CONFIGURED"
                else:
                    try: v = metric_value(m, cap)
                    except Exception as e: v = None; r["note"] = f"extractor error {type(e).__name__}"
                    if v is None: r["local_status"] = "NOT_EXTRACTED_BY_HARNESS_OR_NOT_EXPOSED"
                    else: r["finco_local_value"], r["extraction_path"], r["local_status"] = v[0], v[1], "EXECUTED_LOCAL_ENGINE"
                base_rows.append(r)
    cols = list(base_rows[0])
    w = csv.DictWriter(open(os.path.join(a.out, "ON07_LOCAL_BASELINE.csv"), "w", newline=""), fieldnames=cols); w.writeheader(); w.writerows(base_rows)
    csv.writer(open(os.path.join(a.out, "ACCOUNTING_IDENTITIES.csv"), "w", newline="")).writerows([["variant", "fixture", "identity", "status", "detail"]] + ident_rows)
    json.dump(cov, open(os.path.join(a.out, "WF04_COVENANT_EVALUATION.json"), "w"), indent=1, default=str)
    print(len(base_rows), "baseline rows;", len(ident_rows), "identity rows")
    from collections import Counter; print(Counter((r[3]) for r in ident_rows))

if __name__ == "__main__":
    main()
