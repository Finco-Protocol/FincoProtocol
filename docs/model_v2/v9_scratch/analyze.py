import json, glob, re, sys
R = {}
for f in sorted(glob.glob("m_part*.json")) + ["m_r1.json", "m_r2.json", "m_r3.json"]:
    R.update(json.load(open(f)))
for name, row in json.load(open("m_noD.json")).items():
    R[name]["variants"]["FULLnoD"] = row["variants"]["FULLnoD"]
    R[name]["variants"]["FULLnoD"]["_own_baseline_s"] = row["baseline_s"]
NUM = re.compile(r"[-+]?\d+\.\d+(?:[eE][-+]?\d+)?")
def code(msg):
    m = re.search(r"([A-Z][A-Z0-9_]{6,}):", msg or "")
    inner = re.findall(r"([A-Z][A-Z0-9_]{8,})", msg or "")
    return inner[-1] if inner else None
def classify(row, v):
    c = row["variants"][v]
    bexc = row["baseline_exc"]; cexc = c["exc"]
    bmsg = row["baseline_summary"].get("exception") if bexc else None
    if bexc and cexc:
        bm = row.get("_bmsg")
        if c["n_categorical"] == 0:
            return "SAME-FAIL-CODE/DIFF-EVIDENCE" if c.get("text_numeric") else "IDENTICAL-FAIL"
        return "SAME-FAIL-CODE/DIFF-EVIDENCE" if code(c["categorical"][0][1]) == code(c["categorical"][0][2]) else "DIFFERENT-FAIL"
    if bexc != bool(cexc):
        return "FEASIBILITY-FLIP"
    if c["n_categorical"] or c["n_structural"]:
        return "CATEGORICAL"
    if c["identical"] == c["floats"] and not c.get("text_numeric"):
        return "BIT-IDENTICAL"
    return "WITHIN-1e-7" if c["max_abs"] <= 1e-7 else ("WITHIN-1e-6" if c["max_abs"] <= 1e-6 else "NUMERIC>1e-6")
vs = ["B1", "D", "BA", "BW", "BG", "B1+D", "B", "C", "FULL", "FULLnoD"]
from collections import Counter, defaultdict
tot = defaultdict(Counter)
print(f"{'case':26s} {'base':>7s} " + " ".join(f"{v:>14s}" for v in vs))
for name, row in R.items():
    cells = []
    for v in vs:
        k = classify(row, v); tot[v][k] += 1
        c = row["variants"][v]
        sp = row["baseline_s"] / max(c["s"], 1e-9)
        tag = {"BIT-IDENTICAL": "=", "WITHIN-1e-7": "~", "WITHIN-1e-6": "~6", "IDENTICAL-FAIL": "F=",
               "SAME-FAIL-CODE/DIFF-EVIDENCE": "F~", "FEASIBILITY-FLIP": "FLIP", "CATEGORICAL": "CAT",
               "DIFFERENT-FAIL": "F!", "NUMERIC>1e-6": ">6"}[k]
        cells.append(f"{tag:>4s} x{sp:5.2f} {c['max_abs']:.0e}"[:14])
    print(f"{name:26s} {row['baseline_s']:6.2f}s " + " ".join(f"{x:>14s}" for x in cells))
print()
for v in vs: print(v, dict(tot[v]))
