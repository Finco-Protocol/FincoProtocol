"""CI V5 SHADOW lane, split by TRUST BOUNDARY (observational; never required here; V4 stays authoritative).

Three entry points, each meant for its OWN workflow job so that no PR-head code ever runs where the V5 verdict is computed or published:

  ``verdict``  (job 1) reads Git OBJECTS only: V5 integrity verdict + B5 report. Runs trusted-base tools. Executes NO code from the checkout.
  ``v4``       (job 2) runs the accepted V4 one-pass central gate FROM THE CHECKOUT (PR-head Python). Isolated; writes one artifact; judges nothing.
  ``compare``  (job 3) trusted code only: reads the two artifacts as DATA, writes the comparison record and the job summary.

The vocabulary is honest: ``integrity`` (INTEGRITY_PASS / INTEGRITY_FAIL / UNKNOWN) is separate from ``authorization`` (NOT_EVALUATED here) and
``enforcement`` (SHADOW here). A V5 integrity pass can never suppress a V4 failure and is never merge authorization.
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

VERDICT_FILE, B5_FILE, V4_FILE, COMPARISON_FILE = "v5_verdict.json", "b5_report.json", "v4_result.json", "shadow_comparison.json"
V4_RAW_FILE = "v4_governance_gate.json"


def run_v4_gate(repo, out_path, timeout):
    """The accepted V4 central one-pass governance gate, run from the checkout under test (PR-head code: job 2 ONLY). Bounded; any problem is UNAVAILABLE, never PASS."""
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


def _v5_state(v5):
    """Map the V5 integrity vocabulary onto the three states the comparison reasons about."""
    return {"INTEGRITY_PASS": "PASS", "INTEGRITY_FAIL": "FAIL"}.get(v5.get("integrity"), "UNKNOWN")


def compare(v4, v5):
    """Relation of the two verdicts. Parity is NEVER declared from one run: it needs the owner-approved multi-PR window. A V4 verdict that is not
    present, not ``PASS``/``FAIL`` or not from the same head is INCOMPARABLE and is counted nowhere."""
    a, b = v4.get("verdict"), _v5_state(v5)
    if a not in ("PASS", "FAIL") or b == "UNKNOWN":
        relation = "INCOMPARABLE"
    elif a == b:
        relation = "MATCH_" + a
    elif a == "FAIL" and b == "PASS":
        relation = "MISMATCH_V5_WOULD_ADMIT_V4_FAIL"
    else:
        relation = "MISMATCH_V5_STRICTER_THAN_V4"
    return {"relation": relation, "parity": "PARITY_NOT_ESTABLISHED", "v4_remains_authoritative": True, "v5_authoritative": bool(v5.get("trust", {}).get("authoritative")),
            "v4_failure_attribution": ({"composite_valid": v4.get("composite_valid"), "non_exact_cohorts": len(v4.get("non_exact_cohorts", [])),
                                        "mutation_violations": v4.get("mutation_violations"), "successor_valid": v4.get("mutation_successor_valid")}
                                       if a == "FAIL" else None),
            "v4_ownership_failure_is_reported_separately_from_semantic_violations": True,
            "note": ("V5 would have admitted a head that V4 rejects: V5 must never override V4; classify the V4 failure (changed-path ownership vs semantic "
                     "violation) before any activation") if relation == "MISMATCH_V5_WOULD_ADMIT_V4_FAIL" else ""}


def summary(rec, b5_text):
    v5, v4, cmp_ = rec["v5"], rec["v4"], rec["comparison"]
    t = v5["trust"]
    L = ["## CI V5 shadow (observational - integrity is NOT authorization, NOT a required check)", "",
         "| | |", "|---|---|",
         "| **integrity** | **%s** (`effective`: %s) |" % (v5["integrity"], v5["effective"]),
         "| authorization / enforcement | `%s` / `%s` |" % (v5["authorization"], v5["enforcement"]),
         "| transition | `%s` |" % v5["transition"],
         "| **V4_VERDICT** (accepted one-pass central gate, separate job) | **%s** (%ss) |" % (v4.get("verdict"), v4.get("wall_s")),
         "| comparison | `%s` / `%s` |" % (cmp_["relation"], cmp_["parity"]),
         "| head SHA / tree | `%s` / `%s` |" % (v5["source_head_sha"], v5.get("source_tree")),
         "| trusted base tip | `%s` (%s) |" % (v5["base_sha"], t["base_state"]),
         "| tool source / epoch / guard | `%s` / `%s` / `%s` |" % (t["tool_source"], t["epoch_state"], t["guard_mode"]),
         "| guarded paths / delta changes | %d / %d |" % (v5["full_guard_count"], v5["delta_changes"]),
         "| epoch_sha / delta_digest | `%s` / `%s` |" % (v5.get("epoch_sha"), v5.get("delta_digest")),
         "| classes of changed paths | `%s` |" % json.dumps(v5.get("classes", {}), sort_keys=True), ""]
    if t["tool_source"] != "TRUSTED_BASE" or t["epoch_state"] != "TRUSTED_BASE":
        L += ["> **Not authoritative:** tool source `%s`, epoch `%s`. V5 is informational only; V4 decides." % (t["tool_source"], t["epoch_state"]), ""]
    if cmp_["note"]:
        L += ["> **%s** - %s" % (cmp_["relation"], cmp_["note"]), ""]
    if cmp_["v4_failure_attribution"]:
        L += ["V4 failure attribution (ownership vs semantics, never one raw count): `%s`" % json.dumps(cmp_["v4_failure_attribution"], sort_keys=True), ""]
    if v5["semantic_gaps"]:
        L += ["**Semantic gaps (V4 stays authoritative)** - %d, first 8: %s" % (len(v5["semantic_gaps"]), ", ".join("`%s`" % g for g in v5["semantic_gaps"][:8])), ""]
    if v5["failures"] or v5["unknowns"]:
        L += ["**V5 findings** (first 12):"] + ["- `%s` %s" % (f["code"], f["detail"][:140]) for f in (v5["failures"] + v5["unknowns"])[:12]] + [""]
    if rec.get("harness_errors"):
        L += ["**Harness errors:** " + "; ".join(rec["harness_errors"]), ""]
    L += ["---", b5_text, "", "_Labels: MEASURED_LOCAL = this runner, this process; SIMULATION = prediction; nothing here is merge approval._"]
    return "\n".join(L)


def _dump(path, obj):
    with open(path, "w") as fh:
        fh.write(json.dumps(obj, indent=2, sort_keys=True) + "\n")


def cmd_verdict(a):
    """Job 1: Git objects only. The only code that runs is the (trusted-base) evaluator and the B5 adapter; nothing from the checkout is imported or executed."""
    os.makedirs(a.out_dir, exist_ok=True)
    v5 = E.verify(a.repo, a.head_sha, a.base_tip_sha, trusted_ref_tip=a.base_tip_sha, tool_source=a.tools_provenance, check_worktree=True)
    b5 = B5.build(a.repo, a.base_tip_sha, a.head_sha, a.b3_report)
    errors = [] if b5.get("status") == "OK" else ["B5 report unavailable: %s" % b5.get("reason")]
    _dump(os.path.join(a.out_dir, VERDICT_FILE), v5)
    _dump(os.path.join(a.out_dir, B5_FILE), b5)
    _dump(os.path.join(a.out_dir, "verdict_harness.json"), {"harness_errors": errors})
    print("INTEGRITY=%s AUTHORIZATION=%s ENFORCEMENT=%s TRANSITION=%s tool_source=%s epoch=%s" % (
        v5["integrity"], v5["authorization"], v5["enforcement"], v5["transition"], v5["trust"]["tool_source"], v5["trust"]["epoch_state"]))
    for err in errors:
        print("::error::shadow harness: %s" % err)
    return 1 if errors else 0


def cmd_v4(a):
    """Job 2: PR-head code runs HERE and only here; the result is an artifact the compare job reads as data."""
    os.makedirs(a.out_dir, exist_ok=True)
    rec = run_v4_gate(a.repo, os.path.join(a.out_dir, V4_RAW_FILE), a.v4_timeout)
    rec["head_sha"] = a.head_sha
    _dump(os.path.join(a.out_dir, V4_FILE), rec)
    print("V4_VERDICT=%s head=%s" % (rec["verdict"], a.head_sha))
    return 0


def _load(path):
    try:
        return json.loads(open(path).read()), None
    except (OSError, ValueError) as exc:
        return None, "%s: %s" % (os.path.basename(path), type(exc).__name__)


def cmd_compare(a):
    """Job 3: trusted code only. A missing or foreign-head artifact is INCOMPARABLE / UNAVAILABLE, never PASS."""
    os.makedirs(a.out_dir, exist_ok=True)
    errors = []
    v5, err = _load(os.path.join(a.verdict_dir, VERDICT_FILE))
    if v5 is None:
        errors.append(err)
        v5 = {"integrity": "UNKNOWN", "authorization": "UNVERIFIED", "enforcement": "UNVERIFIED", "transition": "UNKNOWN", "source_head_sha": a.head_sha, "source_tree": None,
              "base_sha": None, "effective": "UNAVAILABLE", "full_guard_count": 0, "delta_changes": 0, "classes": {}, "semantic_gaps": [], "failures": [], "unknowns": [],
              "trust": {"tool_source": "UNAVAILABLE", "epoch_state": "UNAVAILABLE", "base_state": "UNAVAILABLE", "guard_mode": "UNAVAILABLE", "authoritative": False}}
    b5, err = _load(os.path.join(a.verdict_dir, B5_FILE))
    if b5 is None:
        errors.append(err)
        b5 = {"status": "UNAVAILABLE", "reason": "artifact missing"}
    elif b5.get("status") != "OK":
        errors.append("B5 report unavailable: %s" % b5.get("reason"))
    v4, err = _load(os.path.join(a.v4_dir, V4_FILE))
    if v4 is None:
        errors.append(err)
        v4 = {"verdict": "UNAVAILABLE", "error": "artifact missing"}
    elif v4.get("head_sha") != a.head_sha or v5.get("source_head_sha") != a.head_sha:
        errors.append("artifact head SHA does not match the evaluated head")      # a foreign or stale artifact is never compared
        v4 = {"verdict": "UNAVAILABLE", "error": "head SHA mismatch"}
    rec = {"schema": "FINCO_CI_V5_SHADOW_V2", "v4": v4, "v5": v5, "comparison": compare(v4, v5), "harness_errors": errors, "label": "OBSERVATIONAL_SHADOW"}
    _dump(os.path.join(a.out_dir, COMPARISON_FILE), rec)
    text = summary(rec, B5.summary_markdown(b5))
    if a.summary:
        with open(a.summary, "a") as fh:
            fh.write(text + "\n")
    print("V4=%s INTEGRITY=%s comparison=%s" % (v4.get("verdict"), v5["integrity"], rec["comparison"]["relation"]))
    for err in errors:
        print("::error::shadow harness: %s" % err)
    return 1 if errors else 0


def main(argv=None):
    ap = argparse.ArgumentParser(description="CI V5 shadow lane (observational), one subcommand per job.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    v = sub.add_parser("verdict")
    v.add_argument("--repo", default=".")
    v.add_argument("--head-sha", required=True)
    v.add_argument("--base-tip-sha", required=True, help="current tip of the protected ref (the base is never a caller-supplied merge-base)")
    v.add_argument("--out-dir", required=True)
    v.add_argument("--b3-report", required=True)
    v.add_argument("--tools-provenance", choices=("TRUSTED_BASE", "UNTRUSTED_TOOL_SOURCE"), required=True)
    g = sub.add_parser("v4")
    g.add_argument("--repo", default=".")
    g.add_argument("--head-sha", required=True)
    g.add_argument("--out-dir", required=True)
    g.add_argument("--v4-timeout", type=int, default=300)
    c = sub.add_parser("compare")
    c.add_argument("--head-sha", required=True)
    c.add_argument("--verdict-dir", required=True)
    c.add_argument("--v4-dir", required=True)
    c.add_argument("--out-dir", required=True)
    c.add_argument("--summary")
    a = ap.parse_args(argv)
    return {"verdict": cmd_verdict, "v4": cmd_v4, "compare": cmd_compare}[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main())
