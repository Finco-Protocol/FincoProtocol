#!/usr/bin/env python3
"""Per-fixture, per-field intended-vs-effective binding audit from real captures + the ON-07 fixtures CSV.
python -I build_fixture_binding_audit.py --fixtures CSV --captures dir [dir...] --out csv"""
import argparse, csv, json, os
ap = argparse.ArgumentParser(); ap.add_argument("--fixtures", required=True); ap.add_argument("--captures", nargs="+", required=True); ap.add_argument("--out", required=True); a = ap.parse_args()
fx = {}
for r in csv.DictReader(open(a.fixtures, newline="")): fx.setdefault(r["fixture_id"], []).append(r)
def num(x):
    try: return float(str(x).split()[0])
    except Exception: return None
rows = []
for cdir in a.captures:
    variant = os.path.basename(cdir.rstrip("/"))
    for fid, frs in fx.items():
        p = os.path.join(cdir, fid + ".json")
        if not os.path.exists(p): continue
        cap = json.load(open(p)); bc = cap.get("binding_check", {}); eff = cap.get("effective_inputs", {})
        for r in frs:
            k = r["fixture_key"]; sc = r["source_class"]
            if cap["status"] not in ("RUN_OK",) and "effective_inputs" not in cap:
                verdict, detail, effv = "NOT_TESTED", f"run did not reach input materialisation: {cap.get('error','')[:120]}", ""
            elif sc == "EXPLICIT" and k in bc:
                verdict, detail, effv = bc[k]["verdict"], bc[k]["detail"], eff.get(k, "")
            elif sc == "EXPLICIT":
                verdict, detail, effv = ("APPLIED_NOT_READ_BACK", "no read-back probe for this key (identity/display/derived)", "")
            elif sc == "ENGINE_DEFAULT" and k in eff:
                e, i = num(eff[k]), num(r["intended_value"])
                scale = 100 if k in ("cit_rate_pct",) else 1
                verdict = "DEFAULT_AS_STATED" if (e is not None and i is not None and abs(e * scale - i) < 1e-9 * max(1, abs(i))) else "DEFAULT_DIFFERS_FROM_STATED"
                detail, effv = f"stated default {r['intended_value']} vs effective {eff[k]}", eff[k]
            elif sc == "ENGINE_DEFAULT":
                verdict, detail, effv = "DEFAULT_NOT_READ_BACK", "no probe", ""
            else:
                verdict, detail, effv = "EXCLUDED_BY_FIXTURE", r["intended_value"], ""
            rows.append([variant, fid, k, sc, r["intended_value"][:80], effv if not isinstance(effv, list) else str(effv)[:80], verdict, detail[:200], r["finco_field_id"]])
w = csv.writer(open(a.out, "w", newline="")); w.writerow(["variant", "fixture_id", "fixture_key", "source_class", "intended_value", "effective_value", "verdict", "detail", "finco_field_id"]); w.writerows(rows)
from collections import Counter; print(Counter((r[0], r[6]) for r in rows))
