"""B5: automatic, cheap, read-only PR test-admission REPORT for the CI V5 shadow lane (WARN-ONLY; never a gate).

A thin adapter over the accepted B3 ``tests/ci_v4_lean_report.py::test_admission_report`` (loaded from an explicit path so the shadow lane can use
the TRUSTED-BASE copy; its logic is reused, not cloned). It adds: a public-safe JSON artifact, a concise job summary, same-SHA provenance for plan /
JUnit evidence, and an honest per-module status vocabulary (PASS / FAIL / NOT_SELECTED / SKIPPED / CANCELLED / UNKNOWN) that is never inferred from
file names. No GitHub token, no network, no pytest run, no recursion into governance.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import sys
import time
import xml.etree.ElementTree as ET

SCHEMA = "FINCO_CI_V5_B5_REPORT_V1"
STATUSES = ("PASS", "FAIL", "NOT_SELECTED", "SKIPPED", "CANCELLED", "UNKNOWN")
TRUSTED_LANE = "TRUSTED_BASE"              # the only lane whose JUnit attestation is accepted: a PR-head lane could write any file it likes


def load_b3(path):
    spec = importlib.util.spec_from_file_location("ci_v4_lean_report_b3", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _sha256(path):
    with open(path, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


_SEVERITY = {"PASS": 0, "SKIPPED": 1, "FAIL": 2}      # a module reports its WORST testcase: one skipped node means the module is never plain PASS


def junit_evidence(junit_paths, attestation_path, head_sha, known_modules=()):
    """(label, reason, {module: status}). OBSERVED_HOSTED only when an attestation binds THESE junit bytes to THIS head SHA; otherwise UNVERIFIED_INPUT
    and no per-module status or seconds are published. A JUnit file carries no commit identity, so a file name or a directory never proves anything.
    Class names are mapped only onto ``known_modules`` (the changed test modules); an unmappable testcase is ignored, never guessed."""
    if not junit_paths:
        return "UNKNOWN", "no JUnit supplied", {}
    att = None
    if attestation_path:
        try:
            att = json.loads(open(attestation_path).read())
        except (OSError, ValueError):
            att = None
    digests = sorted(_sha256(p) for p in junit_paths)
    bound = (isinstance(att, dict) and att.get("kind") == "hosted_run" and att.get("sha") == head_sha and att.get("run_id")
             and att.get("lane") == TRUSTED_LANE and sorted(att.get("junit_sha256", [])) == digests)
    if not bound:
        return "UNVERIFIED_INPUT", "JUnit is not bound by a matching attestation from a trusted lane (lane + sha + junit digests); statuses and seconds withheld", {}
    known, statuses = set(known_modules), {}
    for p in junit_paths:
        for case in ET.parse(p).getroot().iter("testcase"):
            parts = case.get("classname", "").split(".")
            path = next((c for c in ("/".join(parts[:i]) + ".py" for i in range(len(parts), 0, -1)) if c in known), None)
            if path is None:
                continue
            child = {c.tag for c in case}
            st = "FAIL" if child & {"failure", "error"} else ("SKIPPED" if "skipped" in child else "PASS")
            if path not in statuses or _SEVERITY[st] > _SEVERITY[statuses[path]]:
                statuses[path] = st
    if att.get("conclusion") == "cancelled":
        statuses = {m: "CANCELLED" for m in statuses}
    return "OBSERVED_HOSTED", "attestation binds %d JUnit file(s) to the head SHA (run %s); asserted by the workflow, not re-verifiable here" % (len(junit_paths), att.get("run_id")), statuses


def build(root, base_sha, head_sha, b3_path, plan=None, junit=(), attestation=None):
    t0, c0 = time.monotonic(), time.process_time()
    b3 = load_b3(b3_path)
    unavailable = []
    with b3.git_subprocess_counter() as counts:
        try:
            raw = b3.test_admission_report(base_sha, head_sha, plan, (), root=root)      # JUnit is handled here (provenance), never by B3's unverified path
        except Exception as exc:                                                         # visible, never a fabricated empty PASS
            return {"schema": SCHEMA, "label": "WARN_ONLY", "status": "UNAVAILABLE", "reason": "%s: %s" % (type(exc).__name__, str(exc)[:200]),
                    "head_sha": head_sha, "base_sha": base_sha, "exit_code_policy": "always 0: informational, never a gate"}
    known = set(raw["modules"]["added"]) | set(raw["modules"]["changed"]) | set(raw["modules"]["removed"]) | {r["to"] for r in raw["modules"]["renamed"]}
    label, reason, jstatus = junit_evidence(list(junit), attestation, head_sha, known)
    plan_bound = str(raw.get("plan_provenance", "")).startswith("SHA_BOUND_INPUT")
    mods = []
    for kind, paths in (("added", raw["modules"]["added"]), ("removed", raw["modules"]["removed"]), ("changed", raw["modules"]["changed"])):
        for p in paths:
            delta = next((d for d in raw["node_deltas"] if d["module"] == p), None)
            selection = (delta or {}).get("selected", "UNKNOWN")
            status = jstatus.get(p) or ("NOT_SELECTED" if (selection == "NOT_SELECTED" and plan_bound) else "UNKNOWN")
            mods.append({"path": p, "change": kind, "selection": selection if plan_bound else "UNKNOWN", "status": status,
                         "added_functions": (delta or {}).get("added_nodes", []), "removed_functions": (delta or {}).get("removed_nodes", []),
                         "node_delta_kind": "AST_FUNCTION_DELTA" if delta and delta.get("status") == "AST_FUNCTION_DELTA" else "UNKNOWN",
                         "seconds": None, "seconds_label": "UNKNOWN (no SHA-bound JUnit)" if label != "OBSERVED_HOSTED" else "OBSERVED_HOSTED (attested)"})
    for r in raw["modules"]["renamed"]:
        mods.append({"path": r["to"], "renamed_from": r["from"], "change": "renamed", "selection": "UNKNOWN", "status": "UNKNOWN",
                     "node_delta_kind": "UNKNOWN", "seconds": None})
    if not plan:
        unavailable.append("plan: no trusted-base plan supplied -> selection of every module is UNKNOWN")
    if label != "OBSERVED_HOSTED":
        unavailable.append("junit: %s" % reason)
    return {"schema": SCHEMA, "label": "WARN_ONLY", "status": "OK", "head_sha": head_sha, "head_tree": raw["head_tree"], "base_sha": base_sha,
            "head_binding": raw["head_binding"], "plan_provenance": raw["plan_provenance"], "junit": {"label": label, "reason": reason},
            "node_delta_kind": "AST_FUNCTION_DELTA (not collected pytest node ids; exact ids need a SHA-bound --collect-only of both trees)",
            "collected_nodes": {"status": "UNAVAILABLE", "reason": "no SHA-bound --collect-only of both trees: file/function deltas above are NOT collected node counts"},
            "modules": sorted(mods, key=lambda m: (m["change"], m["path"])),
            "admission_metadata": raw["admission_metadata"], "duplicate_candidates": raw["duplicate_candidates"],
            "duplicate_note": "CANDIDATES only (identical normalized AST body); never a finding, never automatic",
            "new_skip_markers": raw["new_skip_markers"], "growth": raw["growth"], "findings": raw["findings"],
            "simulation": {"label": "SIMULATION" if plan else "UNKNOWN", "predicted_critical_path": raw["critical_path"]},
            "unavailable": unavailable, "status_vocabulary": list(STATUSES),
            "runtime": {"label": "MEASURED_LOCAL", "wall_s": round(time.monotonic() - t0, 2), "cpu_s": round(time.process_time() - c0, 2),
                        "git_children": counts["git"], "other_children": counts["other"]},
            "exit_code_policy": "always 0: informational, never a gate"}


def summary_markdown(rep):
    if rep.get("status") != "OK":
        return "### B5 test-admission report: UNAVAILABLE\n\n`%s` - the report could not be produced; this is NOT a pass.\n" % rep.get("reason", "unknown")
    g, rows = rep["growth"], rep["modules"]
    L = ["### B5 test-admission report (WARN-ONLY, informational)", "",
         "`head %s` / tree `%s` / base `%s`  " % (rep["head_sha"][:12], (rep["head_tree"] or "")[:12], rep["base_sha"][:12]),
         "Test modules: **+%d** added, **-%d** removed, **%d** renamed, **%d** changed; function names +%d/-%d (`AST_FUNCTION_DELTA`, not pytest node ids)." % (
             g["added_modules"], g["removed_modules"], g["renamed_modules"], len([m for m in rows if m["change"] == "changed"]), g["added_nodes"], g["removed_nodes"]), ""]
    if rows:
        L += ["| module | change | selection | status |", "|---|---|---|---|"]
        L += ["| `%s` | %s | %s | %s |" % (m["path"], m["change"], m["selection"], m["status"]) for m in rows[:25]]
        if len(rows) > 25:
            L.append("| ... %d more in the JSON artifact | | | |" % (len(rows) - 25))
        L.append("")
    if rep["new_skip_markers"]:
        L.append("**New skip/xfail markers vs base: %d** (a skipped node is never PASS)." % len(rep["new_skip_markers"]))
    if rep["duplicate_candidates"]:
        L.append("Duplicate **candidates** (heuristic only): %d." % len(rep["duplicate_candidates"]))
    unk = [f for f in rep["findings"] if f.get("code") == "ADM-METADATA-UNKNOWN"]
    if unk:
        L.append("Admission metadata UNKNOWN fields: %d (risk / nearest / witness / tier / owner / retire are never invented)." % len(unk))
    L += ["", "Evidence: " + "; ".join(rep["unavailable"]) if rep["unavailable"] else "Evidence: plan and JUnit supplied.",
          "Runtime (MEASURED_LOCAL): %.1fs wall, %d git processes. Status vocabulary: %s." % (rep["runtime"]["wall_s"], rep["runtime"]["git_children"], " / ".join(STATUSES)), ""]
    return "\n".join(L)


def main(argv=None):
    ap = argparse.ArgumentParser(description="B5 PR test-admission report (read-only, always exit 0).")
    ap.add_argument("--repo", default=".")
    ap.add_argument("--base-sha", required=True)
    ap.add_argument("--head-sha", required=True)
    ap.add_argument("--b3-report", required=True, help="path of tests/ci_v4_lean_report.py to use (trusted-base copy in CI)")
    ap.add_argument("--plan")
    ap.add_argument("--junit", nargs="*", default=[])
    ap.add_argument("--junit-attestation")
    ap.add_argument("--output", required=True)
    ap.add_argument("--summary")
    a = ap.parse_args(argv)
    rep = build(a.repo, a.base_sha, a.head_sha, a.b3_report, a.plan, a.junit, a.junit_attestation)
    os.makedirs(os.path.dirname(os.path.abspath(a.output)), exist_ok=True)
    with open(a.output, "w") as fh:
        fh.write(json.dumps(rep, indent=2, sort_keys=True) + "\n")
    text = summary_markdown(rep)
    if a.summary:
        with open(a.summary, "a") as fh:
            fh.write(text)
    else:
        sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
