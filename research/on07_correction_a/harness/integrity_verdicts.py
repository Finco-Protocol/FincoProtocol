#!/usr/bin/env python3
"""Repo Run Integrity verdicts on CAPTURED evidence (read-only; app.run_integrity.run_integrity_checks). Reported separately from accounting identities; a low-DSCR
credit observation is NOT turned into a financial-identity failure here. python -I integrity_verdicts.py --repo R --out JSON --cap label=path ..."""
import argparse, json, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__))); import on07_common as C
ap = argparse.ArgumentParser(); ap.add_argument("--repo", required=True); ap.add_argument("--out", required=True); ap.add_argument("--cap", action="append", required=True); a = ap.parse_args(); C.repo_setup(a.repo)
from app.run_integrity import run_integrity_checks
out = {}
for spec in a.cap:
    label, path = spec.split("=", 1); c = json.load(open(path)); ev = c["integrity_evidence"]
    try:
        rep = run_integrity_checks(ev)
        d = rep.to_dict() if hasattr(rep, "to_dict") else (rep if isinstance(rep, dict) else {"repr": repr(rep)[:2000]})
        checks = d.get("checks") or d.get("results") or []
        out[label] = {"overall": d.get("overall") or d.get("status") or str(getattr(rep, "overall", getattr(rep, "status", "?"))),
                      "non_pass": [{k: ch.get(k) for k in ("check_id", "id", "title", "status", "detail")} for ch in checks if str(ch.get("status")) not in ("PASS", "CheckStatus.PASS")][:12]}
    except Exception as e:
        out[label] = {"error": f"{type(e).__name__}: {str(e)[:300]}"}
    print(label, json.dumps(out[label])[:400])
json.dump(out, open(a.out, "w"), indent=1, default=str)
