#!/usr/bin/env python3
"""Builds TRUE_ROUTE_INPUT_LEDGER.csv, COST_LINE_ALLOCATION_LEDGER.csv, OUTPUT_EXPOSURE_REGISTER.csv and the isolated revised copies. Reads captures + original package only."""
import argparse, csv, json, os, re, collections
ap = argparse.ArgumentParser(); [ap.add_argument(f"--{x}", required=True) for x in ("pkg", "ca", "prior_baseline", "out")]; a = ap.parse_args()
os.makedirs(a.out, exist_ok=True); os.makedirs(os.path.join(a.out, "isolated_revised_copies"), exist_ok=True)
fx = list(csv.DictReader(open(os.path.join(a.pkg, "ON07_PROJECT_FIXTURES.csv"), newline="")))
RUNS = [("TR", "tr1", "SOL-01"), ("TR", "tr1", "SOL-02"), ("TR", "tr1", "WND-01"), ("TR_ORIGINAL", "tr1", "WND-02"), ("TR_REPLACEMENT_WND-02-R", "wr1", "WND-02")]
def cap(d, f): return json.load(open(os.path.join(a.ca, d, f + ".json")))
AT_CREATION = {"project_name", "country_market", "capacity_mw"}
led = []
for label, d, fid in RUNS:
    c = cap(d, fid); ie = c.get("intended_vs_effective", {}); eff = c.get("effective_inputs", {}); sc = c.get("scalar_cells", {})
    rows = [dict(r) for r in fx if r["fixture_id"] == fid]
    for r in rows:
        k = r["fixture_key"]; ov = c.get("overrides", {}).get(k)
        intended = ov if ov is not None else r["intended_value"]
        if k in AT_CREATION: mech, out, mc = "SEEDED_AT_PROJECT_CREATION", "create_reference_seeded_project", "MATCH_AT_CREATION" if ie.get(k, {}).get("verdict", "MATCH") == "MATCH" else "MISMATCH"
        elif k == "currency": mech, out, mc = "NOT_ENTERED", "display-only label; engine EUR", "NOT_ENTERED_DISPLAY_ONLY"
        elif k == "project_type": mech, out, mc = "TEMPLATE_LOCKED", "reference template", "TEMPLATE_LOCKED"
        elif k == "scenario": mech, out, mc = "ACTIVE_SCENARIO_NONE_BASE_CASE", "no scenario created; Run uses Base", "BASE_CASE_NO_SCENARIO"
        elif k == "financial_close":
            if ov is None and "WND-02-R" in label: intended = "2029-11-01"
            mech, out, mc = "DERIVED", f"effective={eff.get('financial_close')}", "DERIVED_CHECKED" if str(eff.get("financial_close", ""))[:10] == intended[:10] else "DERIVED_DIFFERS"
        elif k in ("total_capex_keur", "opex_y1_keur"):
            kind = "capex" if k.startswith("total_capex") else "opex"; mech = "COST_LINE_ALLOCATION (save_all cost_lines, PROPORTIONAL_RESCALE_OF_SEEDED_LINES)"; out = c.get("cost_lines_outcome", "")
            mc = "MATCH_ALLOCATED_LINES" if ie.get(k, {}).get("verdict") == "MATCH" else "MISMATCH"
        elif k == "operating_hours_p90_10y": mech, out, mc = "NOT_SETTABLE (no registry field; derived 0.9*P50)", "p90_probe.json", "MATCH_DERIVED_NOT_SETTABLE" if ie.get(k, {}).get("verdict") == "MATCH" else "MISMATCH_DERIVED_NOT_SETTABLE"
        elif k in sc: mech, out = "SAVE_ALL_CELL", sc[k].get("outcome", ""); mc = ("MATCH_ENTERED" if ie.get(k, {}).get("verdict") == "MATCH" else "MISMATCH") if out == "SAVED_VIA_SAVE_ALL" else "NOT_ENTERED:" + out
        elif r["source_class"] == "ENGINE_DEFAULT": mech, out = "ENGINE_DEFAULT_NOT_INJECTED", ""; mc = "DEFAULT_READ_BACK_" + ("MATCH" if eff.get(k) is not None and ie.get(k) is None else "NOT_PROBED") if k in eff else "DEFAULT_NOT_READ_BACK"
        else: mech, out, mc = ("EXCLUDED_BY_FIXTURE" if r["source_class"] == "EXCLUDED" else "OTHER"), "", "EXCLUDED" if r["source_class"] == "EXCLUDED" else "UNCLASSIFIED"
        led.append({"route_class": "USER_CREATED_CORE_RUN", "run_label": label, "fixture": fid, "fixture_key": k, "source_class": r["source_class"], "intended_value": intended[:90], "changed_from_original": "YES" if ov is not None else "",
                    "entry_mechanism": mech, "mechanism_outcome": out[:120], "effective_value": str(eff.get(k, ""))[:90], "mismatch_class": mc, "finco_field_id": r["finco_field_id"]})
with open(os.path.join(a.out, "TRUE_ROUTE_INPUT_LEDGER.csv"), "w", newline="") as f:
    w = csv.DictWriter(f, fieldnames=list(led[0])); w.writeheader(); w.writerows(led)
print(collections.Counter(r["mismatch_class"] for r in led))
cl = []
for label, d, fid in RUNS:
    c = cap(d, fid)
    for kind, v in c["cost_line_plan"].items():
        for l in v["lines"]: cl.append({"run_label": label, "fixture": fid, "kind": kind, "business_code": l["code"], "label": l["label"], "seed_keur": l["seed"], "allocated_keur": l["allocated"], "target_total_keur": v["target"], "seed_total_keur": v["seed_total"], "rule": v["rule"],
                                       "semantics": "CAPEX: replace-by-category fold (apply_user_sub_lines_replacing_base)" if kind == "capex" else "OPEX: seeded rows replace the aggregate; custom rows additive (apply_user_sub_lines_to_opex)"})
with open(os.path.join(a.out, "COST_LINE_ALLOCATION_LEDGER.csv"), "w", newline="") as f:
    w = csv.DictWriter(f, fieldnames=list(cl[0])); w.writeheader(); w.writerows(cl)
# exposure register
base = list(csv.DictReader(open(os.path.join(a.ca, "out", "ON07_LOCAL_BASELINE_TRUE_ROUTE.csv"), newline="")))
prior = list(csv.DictReader(open(a.prior_baseline, newline="")))
prior_not = collections.Counter(r["metric_id"] for r in prior if r["local_status"] == "NOT_EXTRACTED_BY_HARNESS_OR_NOT_EXPOSED")
by = collections.defaultdict(lambda: collections.defaultdict(set)); path = {}; haveval = collections.defaultdict(bool)
for b in base:
    if b["exposure_class"] in ("REFUSED_NO_RUN",): continue
    by[b["metric_id"]][b["exposure_class"]].add(b["run_label"]); path.setdefault((b["metric_id"], b["exposure_class"]), b["extraction_path"]); haveval[(b["metric_id"], b["exposure_class"])] |= bool(b["finco_local_value"])
reg = []
for m in [r["metric_id"] for r in csv.DictReader(open(os.path.join(a.pkg, "ON07_OUTPUT_COMPARISON_TEMPLATE.csv"), newline=""))]:
    for cls, labs in by[m].items():
        reg.append({"metric_id": m, "prior_rows_NOT_EXTRACTED": prior_not.get(m, 0), "exposure_class": cls, "value_extracted_in_correction_A": "YES" if haveval[(m, cls)] else "NO", "evidence_path": path[(m, cls)][:240], "runs": ";".join(sorted(labs))})
with open(os.path.join(a.out, "OUTPUT_EXPOSURE_REGISTER.csv"), "w", newline="") as f:
    w = csv.DictWriter(f, fieldnames=list(reg[0])); w.writeheader(); w.writerows(reg)
print("prior unextracted rows:", sum(prior_not.values()), dict(prior_not)); print(collections.Counter(r["exposure_class"] for r in reg))
# isolated revised copies
iso = os.path.join(a.out, "isolated_revised_copies")
mech = {}
for r in led:
    if r["run_label"] == "TR": mech.setdefault(r["fixture_key"], (r["entry_mechanism"], r["mismatch_class"]))
hdr = list(fx[0]) + ["true_route_entry_mechanism", "true_route_mismatch_class", "changed_from_original"]
rev = []
for r in fx:
    m = mech.get(r["fixture_key"], ("", ""))
    rev.append({**r, "true_route_entry_mechanism": m[0], "true_route_mismatch_class": m[1], "changed_from_original": ""})
diff = []
for r in fx:
    if r["fixture_id"] != "WND-02": continue
    n = dict(r); n["fixture_id"] = "WND-02-R"; n["project_name"] = r["project_name"].replace("WND-02", "WND-02-R")
    ch = {"construction_months": "20", "horizon_years": "27", "total_capex_keur": "36000"}
    if r["fixture_key"] in ch:
        diff.append({"fixture_id": "WND-02-R", "fixture_key": r["fixture_key"], "original": r["intended_value"], "revised": ch[r["fixture_key"]], "reason": {"construction_months": "reference-consistent SHL maturity grid (reference Wind = 20 months / 27 y, stored SHL maturity index 57)", "horizon_years": "same", "total_capex_keur": "SHL repayability precondition: boundary ~38.4 MEUR (bisection); 36,000 chosen with margin"}[r["fixture_key"]]})
        n["intended_value"] = ch[r["fixture_key"]]
    if r["fixture_key"] == "financial_close": n["intended_value"] = "derived: cod_date - 20 months = 2029-11-01"; diff.append({"fixture_id": "WND-02-R", "fixture_key": "financial_close", "original": r["intended_value"], "revised": n["intended_value"], "reason": "derived from the two changes above"})
    rev.append({**n, "true_route_entry_mechanism": mech.get(r["fixture_key"], ("", ""))[0], "true_route_mismatch_class": "", "changed_from_original": "YES" if r["fixture_key"] in ch or r["fixture_key"] == "financial_close" else ""})
for r in rev:
    if r["fixture_key"] in ("total_capex_keur", "opex_y1_keur") and r["fixture_id"] != "WND-02-R": diff.append({"fixture_id": r["fixture_id"], "fixture_key": r["fixture_key"], "original": "source_class=EXPLICIT (totals)", "revised": "EXPLICIT_VIA_COST_LINES (totals derived from lines)", "reason": "React inputs contract: capex_opex_editable=False"})
    if r["fixture_key"] == "operating_hours_p90_10y" and r["fixture_id"] != "WND-02-R": diff.append({"fixture_id": r["fixture_id"], "fixture_key": r["fixture_key"], "original": "EXPLICIT (v1 schema field)", "revised": "DERIVED_NOT_SETTABLE on user route (= 0.9*P50)", "reason": "no registry field; p90_probe.json"})
with open(os.path.join(iso, "ON07_PROJECT_FIXTURES_REVISED.csv"), "w", newline="") as f:
    w = csv.DictWriter(f, fieldnames=hdr); w.writeheader(); w.writerows(rev)
with open(os.path.join(a.out, "ORIGINAL_VS_REVISED_FIXTURE_DIFF.csv"), "w", newline="") as f:
    w = csv.DictWriter(f, fieldnames=["fixture_id", "fixture_key", "original", "revised", "reason"]); w.writeheader(); w.writerows(diff)
# field mapping revised
fm = list(csv.DictReader(open(os.path.join(a.pkg, "ON07_FIELD_MAPPING.csv"), newline="")))
for r in fm:
    m = mech.get(r["input_key"], ("not exercised", ""))
    r["true_route_entry_mechanism"] = m[0]; r["true_route_outcome_class"] = m[1]
with open(os.path.join(iso, "ON07_FIELD_MAPPING_REVISED.csv"), "w", newline="") as f:
    w = csv.DictWriter(f, fieldnames=list(fm[0])); w.writeheader(); w.writerows(fm)
tp = list(csv.DictReader(open(os.path.join(a.pkg, "ON07_OUTPUT_COMPARISON_TEMPLATE.csv"), newline="")))
cls = collections.defaultdict(set)
for r in reg: cls[r["metric_id"]].add(r["exposure_class"])
for r in tp:
    r["exposure_class_local_engine"] = "|".join(sorted(cls.get(r["metric_id"], ["(no run)"])))
    if r["metric_id"] == "DSCR-04": r["finco_output_path"] = "Run-bound covenant verdict: persisted Run last_runtime_identity.dscr_contract_terms evaluated by app.workbook.dscr_contract_terms (PR #399 MERGED at db504f6). Fixtures carry no contractual terms -> NOT_CONFIGURED. [REVISED: previous text said NOT AVAILABLE on main]"
with open(os.path.join(iso, "ON07_OUTPUT_COMPARISON_TEMPLATE_REVISED.csv"), "w", newline="") as f:
    w = csv.DictWriter(f, fieldnames=list(tp[0])); w.writeheader(); w.writerows(tp)
print("diff rows", len(diff))
