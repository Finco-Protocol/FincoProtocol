"""Markdown tables for the report from the matrix JSON files (no engine runs)."""
import json, glob, re
from collections import Counter, defaultdict
R = {}
for f in sorted(glob.glob("m_part*.json")) + ["m_r1.json", "m_r2.json", "m_r3.json"]:
    R.update(json.load(open(f)))
for f, v in [("m_noD.json", "FULLnoD")] + [(x, "CBW") for x in sorted(glob.glob("m_cbw_*.json"))]:
    for name, row in json.load(open(f)).items():
        R[name]["variants"][v] = row["variants"][v]
# fail-closed cases re-run with canonical re-decision (current prototype code)
for f in ("m_fail.json", "m_fail2.json"):
    for name, row in json.load(open(f)).items():
        for v, c in row["variants"].items():
            R[name]["variants"][v] = c
VS = ["B1", "BA", "BW", "BG", "B", "D", "C", "CBW", "FULLnoD", "FULL"]
def cls(row, v):
    c = row["variants"].get(v)
    if c is None:
        return "n/a"
    bexc, cexc = row["baseline_exc"], c["exc"]
    if bexc and cexc:
        if c["n_categorical"]:
            return "FAIL≠"
        return "FAIL~" if c.get("text_numeric") else "FAIL="
    if bexc != bool(cexc):
        return "FLIP"
    if c["n_categorical"] or c["n_structural"]:
        return "CAT"
    if c["identical"] == c["floats"] and not c.get("text_numeric"):
        return "BIT"
    return f"{c['max_abs']:.0e}"
def code(row):
    s = row["baseline_summary"]
    if row["baseline_exc"]:
        return "fail-closed"
    return s.get("binding_senior_constraint") or "?"
lines = ["| Case | Baseline | Outcome | " + " | ".join(VS) + " |", "|---|---:|---|" + "---|" * len(VS)]
tot = defaultdict(Counter)
worst = defaultdict(float)
for name, row in R.items():
    cells = []
    for v in VS:
        k = cls(row, v)
        bucket = k if not k[0].isdigit() else ("≤1e-8" if row["variants"][v]["max_abs"] <= 1e-8 else ("≤1e-7" if row["variants"][v]["max_abs"] <= 1e-7 else ("≤1e-6" if row["variants"][v]["max_abs"] <= 1e-6 else ">1e-6")))
        tot[v][bucket] += 1
        if not row["baseline_exc"] and v in row["variants"] and not row["variants"][v]["exc"]:
            worst[v] = max(worst[v], row["variants"][v]["max_abs"])
        cells.append(k)
    lines.append(f"| {name} | {row['baseline_s']:.2f} s | {code(row)} | " + " | ".join(cells) + " |")
print("\n".join(lines))
print()
print("| Candidate | " + " | ".join(["BIT", "≤1e-8", "≤1e-7", "≤1e-6", ">1e-6", "FAIL=", "FAIL~", "FAIL≠", "FLIP", "CAT"]) + " | worst feasible max abs (kEUR) |")
print("|---|" + "---:|" * 11)
for v in VS:
    t = tot[v]
    print(f"| {v} | " + " | ".join(str(t.get(k, 0)) for k in ["BIT", "≤1e-8", "≤1e-7", "≤1e-6", ">1e-6", "FAIL=", "FAIL~", "FAIL≠", "FLIP", "CAT"]) + f" | {worst[v]:.2e} |")
print("\ncases:", len(R), "feasible:", sum(1 for r in R.values() if not r["baseline_exc"]))
