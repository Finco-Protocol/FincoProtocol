"""CI V5 SHADOW lane orchestrator (observational; never required; V4 stays authoritative).

One bounded pass at the exact PR head: (1) trusted base = merge-base(base tip, head); (2) V5 epoch verdict (trust state decided by WHERE the epoch is
read from); (3) the accepted V4 one-pass central governance gate for comparison (never the historical per-cohort tests); (4) the B5 report;
(5) a comparison record + job summary. A V5 PASS can never suppress a V4 FAIL, and in bootstrap the V5 verdict is non-authoritative.
Exit 0 unless the HARNESS itself failed (evaluator crash / missing artifact): visible, never a false green.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ci_v5_b5 as B5  # noqa: E402
import ci_v5_epoch as E  # noqa: E402


def run_v4_gate(repo, out_path, timeout):
    """The accepted V4 central one-pass governance gate, run from the checkout under test. Bounded; any problem is UNAVAILABLE, never PASS."""
    t0 = time.monotonic()
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    try:
        p = subprocess.run([sys.executable, "-m", "tools.ci_v4_governance_gate", "--output", out_path], cwd=repo, env=env, capture_output=True, timeout=timeout)
        rec = json.loads(open(out_path).read())
        verdict = rec.get("verdict") if rec.get("verdict") in ("PASS", "FAIL") else "UNAVAILABLE"
        return {"verdict": verdict, "exit_code": p.returncode, "wall_s": round(time.monotonic() - t0, 1),
                "non_exact_cohorts": sorted(k for k, v in rec.get("cohorts", {}).items() if not v), "composite_valid": rec.get("composite_valid"),
                "mutation_violations": len(rec.get("mutation_violations", [])), "mutation_successor_valid": rec.get("mutation_successor_valid"),
                "error": rec.get("error")}
    except subprocess.TimeoutExpired:
        return {"verdict": "UNAVAILABLE", "error": "timeout after %ds" % timeout, "wall_s": round(time.monotonic() - t0, 1)}
    except (OSError, ValueError) as exc:
        return {"verdict": "UNAVAILABLE", "error": "%s: %s" % (type(exc).__name__, exc), "wall_s": round(time.monotonic() - t0, 1)}


def compare(v4, v5):
    """Relation of the two verdicts. Parity is NEVER declared from one run: it needs the owner-approved multi-PR window."""
    a, b = v4["verdict"], v5["verdict"]
    if a == "UNAVAILABLE" or b == "UNKNOWN":
        relation = "INCOMPARABLE"
    elif a == b:
        relation = "MATCH_" + a
    elif a == "FAIL" and b == "PASS":
        relation = "MISMATCH_V5_WOULD_ADMIT_V4_FAIL"
    else:
        relation = "MISMATCH_V5_STRICTER_THAN_V4"
    return {"relation": relation, "parity": "PARITY_NOT_ESTABLISHED", "v4_remains_authoritative": True, "v5_authoritative": v5["authoritative"],
            "v4_failure_attribution": ({"composite_valid": v4.get("composite_valid"), "non_exact_cohorts": len(v4.get("non_exact_cohorts", [])),
                                        "mutation_violations": v4.get("mutation_violations"), "successor_valid": v4.get("mutation_successor_valid")}
                                       if a == "FAIL" else None),
            "note": ("V5 would have admitted a head that V4 rejects: V5 must never override V4; classify the V4 failure (e.g. changed-path ownership "
                     "= LEGACY_GOVERNANCE_BLOCKED) before any activation") if relation == "MISMATCH_V5_WOULD_ADMIT_V4_FAIL" else ""}


def summary(rec, b5_text):
    v5, v4, cmp_ = rec["v5"], rec["v4"], rec["comparison"]
    cov = v5.get("coverage", {})
    L = ["## CI V5 shadow (observational, NOT a required check)", "",
         "| | |", "|---|---|",
         "| **V4_VERDICT** (accepted one-pass central gate) | **%s** (%ss) |" % (v4["verdict"], v4.get("wall_s")),
         "| **V5_VERDICT** | **%s** - trust `%s`, authoritative=%s (%ss, %s git processes) |" % (v5["verdict"], v5["trust_state"], v5["authoritative"], v5["metrics"]["wall_s"], v5["metrics"]["git_children"]),
         "| comparison | `%s` / `%s` |" % (cmp_["relation"], cmp_["parity"]),
         "| head SHA / tree | `%s` / `%s` |" % (v5["head_sha"], v5.get("head_tree")),
         "| trusted base (merge-base) | `%s` |" % v5["base_sha"],
         "| epoch | %s |" % (("`%s` from `%s`, %d entries" % (v5["epoch"]["id"], v5["epoch"]["source"], v5["epoch"]["entries"])) if v5.get("epoch") else "none"),
         "| delta | %d explicit protected changes |" % v5["delta_changes"],
         "| tools provenance | `%s` |" % rec["tools_provenance"], ""]
    if v5["trust_state"] != "TRUSTED_BASE":
        L += ["> **Bootstrap:** the epoch is `%s`; it cannot authorise the PR that carries it. V5 is informational only; V4 decides." % v5["trust_state"], ""]
    if cmp_["note"]:
        L += ["> **%s** - %s" % (cmp_["relation"], cmp_["note"]), ""]
    if cmp_["v4_failure_attribution"]:
        L += ["V4 failure attribution: `%s`" % json.dumps(cmp_["v4_failure_attribution"], sort_keys=True), ""]
    if cov:
        L += ["Coverage gaps (V4 stays authoritative for these): `%s`" % (", ".join(cov.get("not_covered", [])) or "none"), ""]
    if v5["failures"] or v5["unknowns"]:
        L += ["**V5 findings** (first 12):"] + ["- `%s` %s" % (f["code"], f["detail"][:140]) for f in (v5["failures"] + v5["unknowns"])[:12]] + [""]
    if rec.get("delta_paths"):
        L += ["**Protected delta for REVIEW** (%d):" % len(rec["delta_paths"])] + ["- `%s %s`" % (o, p) for o, p in rec["delta_paths"][:30]] + [""]
    L += ["---", b5_text, "", "_Labels: MEASURED_LOCAL = this runner, this process; SIMULATION = prediction; CANDIDATE_UNTRUSTED = not trust-anchored; nothing here is merge approval._"]
    return "\n".join(L)


def main(argv=None):
    ap = argparse.ArgumentParser(description="CI V5 shadow lane (observational).")
    ap.add_argument("--repo", default=".")
    ap.add_argument("--head-sha", required=True)
    ap.add_argument("--base-tip-sha", required=True)
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--b3-report", required=True)
    ap.add_argument("--tools-provenance", choices=("TRUSTED_BASE", "HEAD_CANDIDATE_UNTRUSTED"), required=True)
    ap.add_argument("--v4-timeout", type=int, default=300)
    ap.add_argument("--skip-v4", action="store_true", help="tests only")
    ap.add_argument("--summary")
    a = ap.parse_args(argv)
    os.makedirs(a.out_dir, exist_ok=True)
    harness_errors = []
    git = E.Git(a.repo)
    try:
        base = git.run("merge-base", a.base_tip_sha, a.head_sha).decode().strip() if E.SHA40.fullmatch(a.base_tip_sha) and E.SHA40.fullmatch(a.head_sha) else a.base_tip_sha
    except E.GitError:
        base = a.base_tip_sha
        harness_errors.append("no merge-base between the base tip and the head")
    v5 = E.verify(a.repo, a.head_sha, base, check_worktree=True)            # BEFORE any code from the checkout runs: attests a clean, exact-head worktree
    v4 = ({"verdict": "UNAVAILABLE", "error": "skipped (--skip-v4)"} if a.skip_v4 else run_v4_gate(a.repo, os.path.join(a.out_dir, "v4_governance_gate.json"), a.v4_timeout))
    delta_paths = []
    try:
        head_inv = E.read_inventory(git, a.head_sha)
        if E.DELTA_PATH in head_inv:
            delta_paths = [[c["op"], c["path"]] for c in json.loads(git.run("cat-file", "blob", head_inv[E.DELTA_PATH][1]))["changes"]]
    except (E.GitError, ValueError, KeyError, TypeError):
        pass
    b5 = B5.build(a.repo, base, a.head_sha, a.b3_report)
    if b5.get("status") != "OK":
        harness_errors.append("B5 report unavailable: %s" % b5.get("reason"))
    rec = {"schema": "FINCO_CI_V5_SHADOW_V1", "tools_provenance": a.tools_provenance, "v4": v4, "v5": v5, "comparison": compare(v4, v5),
           "delta_paths": delta_paths, "harness_errors": harness_errors, "label": "OBSERVATIONAL_SHADOW"}
    for name, obj in (("v5_verdict.json", v5), ("b5_report.json", b5), ("shadow_comparison.json", rec)):
        with open(os.path.join(a.out_dir, name), "w") as fh:
            fh.write(json.dumps(obj, indent=2, sort_keys=True) + "\n")
    text = summary(rec, B5.summary_markdown(b5))
    if a.summary:
        with open(a.summary, "a") as fh:
            fh.write(text + "\n")
    print("V4_VERDICT=%s V5_VERDICT=%s (%s, authoritative=%s) comparison=%s" % (v4["verdict"], v5["verdict"], v5["trust_state"], v5["authoritative"], rec["comparison"]["relation"]))
    for err in harness_errors:
        print("::error::shadow harness: %s" % err)
    return 1 if harness_errors else 0


if __name__ == "__main__":
    sys.exit(main())
