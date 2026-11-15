"""CI V4 Lean B1: opt-in measurement, worker SIMULATION and WARN-ONLY test-admission report.

Nothing here selects, schedules, skips, gates or blocks anything. Every number carries an evidence label so a local measurement or a simulation can
never be read as hosted proof:

* ``MEASURED_LOCAL``  - observed on this machine, by this process (wall / CPU seconds, Git subprocess counts, collected node ids).
* ``SIMULATION``      - computed from recorded module weights with the accepted LPT function of ``tools/ci_v4_schedule.py``; never hosted truth.
* ``WARN_ONLY``       - a test-admission observation from Fable's PROPOSED policy; it never fails a run and the exit code stays 0.

Run it explicitly (``python -m tests.ci_v4_lean_report <command>``); it is never imported by the CI V4 plan, selector, scheduler or aggregator.
Only public-safe test file names and counters are written - no private inputs, no client material.
"""
from __future__ import annotations

import argparse
import ast
import contextlib
import hashlib
import json
import re
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = "FINCO_CI_V4_LEAN_REPORT_V1"
LABELS = ("MEASURED_LOCAL", "SIMULATION", "WARN_ONLY")
# Fable C3-A PROPOSED budgets (05_TEST_ADMISSION_AND_RETIREMENT_POLICY_V1): NOT owner approved, never enforced.
PROPOSED_BUDGETS = {"enforced": False, "approved_by_owner": False,
                    "node_seconds": {"target": 60, "warn": 120, "exception": 300},
                    "module_minutes": {"target": 5, "warn": 10, "exception": 15},
                    "critical_path_minutes": {"target": 35, "warn": 45, "exception": 60}}
SIM_WORKERS = (3, 4, 5, 6, 8)


# ----------------------------------------------------------------------------------------------------- Git subprocess counting
@contextlib.contextmanager
def git_subprocess_counter():
    """Count every ``git`` child process started by this interpreter inside the block (restored on exit; no global state is kept)."""
    counts = {"git": 0, "other": 0}
    original = subprocess.Popen.__init__

    def counted(self, args, *a, **k):
        first = args[0] if isinstance(args, (list, tuple)) and args else str(args)
        counts["git" if first == "git" else "other"] += 1
        return original(self, args, *a, **k)

    subprocess.Popen.__init__ = counted
    try:
        yield counts
    finally:
        subprocess.Popen.__init__ = original


def measure_gate(root=ROOT):
    """One central governance gate verdict, measured: wall, CPU, Git subprocesses. Runs the repository's own ``run()`` unchanged."""
    root = Path(root).resolve()
    sys.path.insert(0, str(root))
    try:
        from tools import ci_v4_governance_gate as G
        with git_subprocess_counter() as counts:
            wall, cpu = time.monotonic(), time.process_time()
            try:
                record = G.run()
                error = None
            except Exception as exc:                                   # fail closed, report the exception honestly
                record, error = {"verdict": "FAIL"}, "%s: %s" % (type(exc).__name__, exc)
            wall, cpu = time.monotonic() - wall, time.process_time() - cpu
    finally:
        sys.path.remove(str(root))
    return {"label": "MEASURED_LOCAL", "what": "central governance gate (one pass)", "verdict": record.get("verdict"),
            "cohorts_checked": len(record.get("cohorts", {})), "wall_s": round(wall, 2), "cpu_s": round(cpu, 2),
            "git_subprocesses": counts["git"], "other_subprocesses": counts["other"], "error": error}


# ----------------------------------------------------------------------------------------------------- collection evidence
_NODE = re.compile(r"^(?P<id>[\w./-]+\.py::\S.*)$")


def parse_collect_output(text):
    """Node ids, errors and the summary line from ``pytest --collect-only -q`` output."""
    nodes, errors = [], []
    for line in text.splitlines():
        line = line.rstrip()
        m = _NODE.match(line)
        if m:
            nodes.append(m.group("id"))
        elif line.startswith("ERROR "):
            errors.append(line)
    return nodes, errors


def collection_digest(modules, root=ROOT, extra_args=()):
    """Exact collected node ids of ``modules`` from a FRESH pytest process (the same profile the CI uses: root pytest.ini, no cache plugin)."""
    cmd = [sys.executable, "-m", "pytest", "--collect-only", "-q", "-p", "no:cacheprovider", *extra_args, *modules]
    start = time.monotonic()
    proc = subprocess.run(cmd, cwd=str(root), capture_output=True, text=True)
    nodes, errors = parse_collect_output(proc.stdout)
    digest = hashlib.sha256("\n".join(sorted(nodes)).encode()).hexdigest()
    return {"label": "MEASURED_LOCAL", "what": "pytest --collect-only", "modules": sorted(modules), "collected_nodes": len(nodes),
            "node_id_sha256": digest, "collection_errors": errors, "returncode": proc.returncode,
            "collect_wall_s": round(time.monotonic() - start, 2),
            "note": "selected / executed / skipped / deselected are NOT derived from collection; they come only from a run's JUnit"}


# ----------------------------------------------------------------------------------------------------- weights + SIMULATION
def load_recorded_weights(path=None):
    from tools import ci_v4_schedule as sched
    weights = sched.load_weights(path)
    try:
        source = json.loads(Path(path or ROOT / "docs/ci_v4/module_weights.json").read_text()).get("source", "unknown")
    except (OSError, ValueError):
        source = "unknown"
    return weights, source


def simulate_workers(modules, weights=None, counts=SIM_WORKERS, weights_source="supplied"):
    """LPT SIMULATION of whole-module scheduling for ``counts`` workers. A module without a recorded weight is priced at the conservative
    default of the accepted scheduler and listed as ``unknown_modules`` (never silently zero). Result is a SIMULATION, not hosted proof."""
    from tools import ci_v4_schedule as sched
    mods = sorted(set(modules))
    if weights is None:
        weights, weights_source = load_recorded_weights()
    unknown = [m for m in mods if m not in weights]
    total = sum(sched.weight_of(m, weights) for m in mods)
    rows = []
    for k in counts:
        _, loads = sched.lpt(mods, weights, k)
        rows.append({"workers": k, "critical_path_s": round(max(loads), 1) if loads else 0.0, "runner_s": round(sum(loads), 1),
                     "imbalance_ratio": round(max(loads) / (sum(loads) / k), 3) if loads and sum(loads) else None})
    return {"label": "SIMULATION", "what": "whole-module LPT over recorded weights", "modules": len(mods), "total_weight_s": round(total, 1),
            "weights_source": weights_source, "unknown_modules": unknown, "default_module_s_for_unknown": sched.DEFAULT_MODULE_SECONDS,
            "rows": rows, "disclaimer": "NOT hosted evidence; weights are historical and a schedule is only a prediction until a hosted run confirms it"}


def read_junit_module_seconds(junit_paths):
    """module path -> summed testcase seconds, from JUnit XML (classname ``tests.test_x`` -> ``tests/test_x.py``)."""
    seconds, nodes = {}, {}
    for p in junit_paths:
        for case in ET.parse(p).getroot().iter("testcase"):
            cls = case.get("classname", "")
            parts = cls.split(".")
            # pytest classnames are dotted module paths, optionally followed by a test class name
            path = None
            for i in range(len(parts), 0, -1):
                cand = "/".join(parts[:i]) + ".py"
                if (ROOT / cand).is_file():
                    path = cand
                    break
            if path is None:
                continue
            seconds[path] = seconds.get(path, 0.0) + float(case.get("time", 0) or 0)
            nodes[path] = nodes.get(path, 0) + 1
    return seconds, nodes


def propose_weights(junit_paths, current_weights, provenance, run_ref=""):
    """A weights PROPOSAL from one run's JUnit. It never writes ``docs/ci_v4/module_weights.json`` and is NOT active: activation needs the trusted-base
    flow and hosted proof. A module absent from the JUnit keeps its previous weight (or stays unknown); ties sort lexically. Deterministic."""
    seconds, nodes = read_junit_module_seconds(sorted(junit_paths))
    modules = {m: round(seconds.get(m, current_weights.get(m, 0.0)), 3) for m in sorted(set(seconds) | set(current_weights))}
    kept = sorted(m for m in current_weights if m not in seconds)
    return {"label": "MEASURED_LOCAL", "status": "PROPOSAL_NOT_ACTIVE", "provenance": provenance, "run_ref": run_ref,
            "refreshed_modules": len(seconds), "kept_previous_weight": kept[:50], "kept_previous_weight_count": len(kept),
            "modules": modules, "nodes": {m: nodes[m] for m in sorted(nodes)},
            "rule": "must come from the last ACCEPTED main-run JUnit; unknown stays unknown (conservative default applies); trusted-base activation required"}


# ----------------------------------------------------------------------------------------------------- WARN-ONLY admission report
_WARNINGS = {
    "ADM-RISK": "module docstring does not name the protected risk (policy item 1)",
    "ADM-SOURCE-TEXT": "a test reads another file's text/bytes and asserts on it; acceptable only when that text is an approved contract (policy item 8)",
    "ADM-COPIED-MATRIX": "large parametrization over owned paths looks like a per-cohort copy of a tamper matrix; extend the central matrix instead (policy item 8)",
    "ADM-GIT-LOOP": "subprocess / git helper called inside a loop or comprehension; measure the Git subprocess count per node (policy item 5)",
    "ADM-SKIP": "skip/xfail present: a skipped node is never PASS (policy item 3)",
}


def _call_name(node):
    f = node.func
    return f.attr if isinstance(f, ast.Attribute) else getattr(f, "id", "")


def admission_report(paths, root=ROOT):
    """WARN-ONLY observations about test files (purely static, AST). Never raises for a finding; never changes an exit code."""
    findings = []
    for rel in sorted(paths):
        p = Path(root) / rel
        try:
            tree = ast.parse(p.read_text(encoding="utf-8"))
        except (OSError, SyntaxError, UnicodeDecodeError) as exc:
            findings.append({"path": rel, "code": "ADM-UNREADABLE", "line": 0, "severity": "WARN", "message": "could not parse: %s" % type(exc).__name__})
            continue
        doc = ast.get_docstring(tree) or ""
        if rel.rsplit("/", 1)[-1].startswith("test_") and not re.search(r"\brisk|protect|invariant|negative|tamper|fail[- ]closed|never\b", doc, re.I):
            findings.append({"path": rel, "code": "ADM-RISK", "line": 1, "severity": "WARN", "message": _WARNINGS["ADM-RISK"]})
        for fn in [n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name.startswith("test_")]:
            calls = [c for c in ast.walk(fn) if isinstance(c, ast.Call)]
            names = {_call_name(c) for c in calls}
            has_assert = any(isinstance(n, ast.Assert) for n in ast.walk(fn))
            if has_assert and names & {"read_text", "read_bytes"} and any(isinstance(n, (ast.Compare,)) and any(isinstance(o, (ast.In, ast.NotIn)) for o in n.ops)
                                                                         for n in ast.walk(fn)):
                findings.append({"path": rel, "code": "ADM-SOURCE-TEXT", "line": fn.lineno, "severity": "WARN", "message": _WARNINGS["ADM-SOURCE-TEXT"]})
            for loop in [n for n in ast.walk(fn) if isinstance(n, (ast.For, ast.While, ast.ListComp, ast.GeneratorExp, ast.SetComp))]:
                inner = {_call_name(c) for c in ast.walk(loop) if isinstance(c, ast.Call)}
                if inner & {"check_output", "run", "Popen", "git", "_git"}:
                    findings.append({"path": rel, "code": "ADM-GIT-LOOP", "line": fn.lineno, "severity": "WARN", "message": _WARNINGS["ADM-GIT-LOOP"]})
                    break
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and _call_name(node) == "parametrize" and node.args:
                values = node.args[-1]
                n = len(values.elts) if isinstance(values, (ast.List, ast.Tuple)) else 0
                if n >= 20 or (isinstance(values, ast.Call) and "OWNED_PATHS" in ast.unparse(values)):
                    findings.append({"path": rel, "code": "ADM-COPIED-MATRIX", "line": node.lineno, "severity": "WARN", "message": _WARNINGS["ADM-COPIED-MATRIX"]})
            if isinstance(node, (ast.Attribute, ast.Name)) and getattr(node, "attr", getattr(node, "id", "")) in ("skip", "xfail", "skipif"):
                findings.append({"path": rel, "code": "ADM-SKIP", "line": getattr(node, "lineno", 0), "severity": "WARN", "message": _WARNINGS["ADM-SKIP"]})
    return {"label": "WARN_ONLY", "what": "test-admission observations (Fable policy V1, PROPOSED)", "files": len(set(paths)), "warnings": len(findings),
            "findings": findings, "budgets": PROPOSED_BUDGETS, "exit_code_policy": "always 0: informational, never a gate"}


def budget_warnings(junit_paths):
    """WARN-ONLY: compare observed node/module seconds in a run's JUnit with the PROPOSED (not approved) budgets."""
    node_b, mod_b = PROPOSED_BUDGETS["node_seconds"], PROPOSED_BUDGETS["module_minutes"]
    rows, per_module = [], {}
    for p in junit_paths:
        for case in ET.parse(p).getroot().iter("testcase"):
            t = float(case.get("time", 0) or 0)
            per_module[case.get("classname", "")] = per_module.get(case.get("classname", ""), 0.0) + t
            for level in ("exception", "warn"):
                if t > node_b[level]:
                    rows.append({"kind": "node", "level": level.upper(), "id": "%s::%s" % (case.get("classname"), case.get("name")), "seconds": round(t, 1)})
                    break
    for cls, t in per_module.items():
        for level in ("exception", "warn"):
            if t / 60.0 > mod_b[level]:
                rows.append({"kind": "module", "level": level.upper(), "id": cls, "seconds": round(t, 1)})
                break
    return {"label": "WARN_ONLY", "enforced": False, "budgets": PROPOSED_BUDGETS, "findings": sorted(rows, key=lambda r: (r["kind"], -r["seconds"], r["id"]))}


# ----------------------------------------------------------------------------------------------------- CLI (explicit, opt-in)
def _emit(obj, output):
    obj = {"schema": SCHEMA, **obj}
    text = json.dumps(obj, indent=2, sort_keys=True) + "\n"
    if output:
        Path(output).parent.mkdir(parents=True, exist_ok=True)
        Path(output).write_text(text)
    else:
        sys.stdout.write(text)


def main(argv=None):
    ap = argparse.ArgumentParser(description="CI V4 Lean B1 opt-in report (measurement / SIMULATION / WARN-ONLY). Never gates anything.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("measure-gate", "collect", "simulate", "weights-proposal", "admission", "budgets", "test-admission"):
        s = sub.add_parser(name)
        s.add_argument("--output")
        if name in ("collect", "simulate"):
            s.add_argument("modules", nargs="+")
        if name == "admission":
            s.add_argument("paths", nargs="+")
        if name in ("weights-proposal", "budgets"):
            s.add_argument("--junit", nargs="+", required=True)
        if name == "test-admission":
            s.add_argument("--junit", nargs="+")
        if name == "test-admission":
            s.add_argument("--base", default="origin/main")
            s.add_argument("--head", default="HEAD")
            s.add_argument("--plan", help="trusted-base plan JSON (from the plan job artifact), optional")
        if name == "weights-proposal":
            s.add_argument("--provenance", required=True, help="run id / commit of the ACCEPTED main run the JUnit came from")
    a = ap.parse_args(argv)
    if a.cmd == "measure-gate":
        _emit(measure_gate(), a.output)
    elif a.cmd == "collect":
        _emit(collection_digest(a.modules), a.output)
    elif a.cmd == "simulate":
        _emit(simulate_workers(a.modules), a.output)
    elif a.cmd == "weights-proposal":
        weights, _ = load_recorded_weights()
        _emit(propose_weights(a.junit, weights, a.provenance), a.output)
    elif a.cmd == "budgets":
        _emit(budget_warnings(a.junit), a.output)
    elif a.cmd == "test-admission":
        _emit(test_admission_report(a.base, a.head, a.plan, a.junit or ()), a.output)
    else:
        _emit(admission_report(a.paths), a.output)
    return 0            # informational by design; a measurement failure is reported inside the JSON, never as a gate


# ----------------------------------------------------------------------------------------------- B3 test-admission report (WARN-ONLY, opt-in)
ADMISSION_FIELDS = ("risk", "nearest", "witness", "tier", "owner", "retire")


def _git_name_status(base, head, root):
    """Added/removed/renamed/changed test-module paths vs the trusted base (rename detection ON)."""
    out = subprocess.check_output(["git", "-c", "core.quotepath=false", "diff", "--name-status", "-M", base, head,
                                   "--", "tests/"], cwd=root).decode("utf-8", "replace")
    added, removed, renamed, changed = [], [], [], []
    for line in out.splitlines():
        parts = line.split("\t")
        if not parts or not parts[0]:
            continue
        st, p = parts[0], parts[-1]
        if st.startswith("A"):
            added.append(p)
        elif st.startswith("D"):
            removed.append(p)
        elif st.startswith("R") and len(parts) >= 3:
            renamed.append({"from": parts[1], "to": parts[2]})
        elif st.startswith("M"):
            changed.append(p)
    return added, removed, renamed, changed


def _test_node_names(src):
    try:
        tree = ast.parse(src)
    except (SyntaxError, ValueError):
        return None                                    # unparsable -> UNKNOWN, never an empty lie
    return sorted(n.name for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name.startswith("test_"))


def _body_hashes(src):
    """Cheap duplicate-candidate heuristic: normalized AST-dump hash per test function (a CANDIDATE, never a finding)."""
    try:
        tree = ast.parse(src)
    except (SyntaxError, ValueError):
        return {}
    out = {}
    for n in ast.walk(tree):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name.startswith("test_"):
            body = ast.dump(ast.Module(body=n.body, type_ignores=[]))
            out[n.name] = hashlib.sha1(body.encode()).hexdigest()
    return out


def _admission_metadata(rel, root):
    """Parse the module docstring's 'Admission:' directives; every missing field is UNKNOWN, never invented."""
    try:
        doc = ast.get_docstring(ast.parse((Path(root) / rel).read_text(encoding="utf-8"))) or ""
    except (OSError, SyntaxError, UnicodeDecodeError):
        return {}
    meta = {}
    for line in doc.splitlines():
        if line.strip().lower().startswith("admission:"):
            for item in line.split(":", 1)[1].split(","):
                if "=" in item:
                    k, v = item.split("=", 1)
                    meta[k.strip().lower()] = v.strip()
    return {f: meta.get(f, "UNKNOWN") for f in ADMISSION_FIELDS}


def test_admission_report(base="origin/main", head="HEAD", plan_path=None, junit_paths=(), root=ROOT):
    """B3 WARN-ONLY test-admission report over the trusted-base diff. Read-only: it never gates, never writes
    repo files, and every unavailable measurement is UNKNOWN with its label — never zero, never a fabricated PASS."""
    root = Path(root)
    added, removed, renamed, changed = _git_name_status(base, head, root)
    is_test = lambda p: p.startswith("tests/") and p.rsplit("/", 1)[-1].startswith("test_") and p.endswith(".py")
    added, removed, changed = sorted(filter(is_test, added)), sorted(filter(is_test, removed)), sorted(filter(is_test, changed))

    node_deltas, growth = [], {"added_modules": len(added), "removed_modules": len(removed), "renamed_modules": len(renamed),
                               "added_nodes": 0, "removed_nodes": 0}
    plan, selected_set = None, None
    if plan_path:
        try:
            plan = json.loads(Path(plan_path).read_text())
            selected_set = set(plan.get("pytest_modules", []))
        except (OSError, ValueError):
            plan = None
    junit_secs, _jnodes = read_junit_module_seconds(sorted(junit_paths)) if junit_paths else ({}, {})

    new_skips, duplicates, meta_rows = [], [], []
    existing_hashes = {}
    for rel in sorted(set(added) | set(changed)):
        src_now = (root / rel).read_text(encoding="utf-8", errors="replace")
        now_nodes = _test_node_names(src_now)
        try:
            src_base = subprocess.check_output(["git", "show", "%s:%s" % (base, rel)], cwd=root).decode("utf-8", "replace")
            base_nodes = _test_node_names(src_base)
        except subprocess.CalledProcessError:
            src_base, base_nodes = None, []
        if now_nodes is None or (src_base is not None and base_nodes is None):
            status, added_n, removed_n = "UNKNOWN", [], []
        else:
            added_n = [n for n in (now_nodes or []) if n not in (base_nodes or [])]
            removed_n = [n for n in (base_nodes or []) if n not in (now_nodes or [])]
            status = "MEASURED_LOCAL"
        growth["added_nodes"] += len(added_n)
        growth["removed_nodes"] += len(removed_n)
        node_deltas.append({"module": rel, "status": status, "added_nodes": added_n, "removed_nodes": removed_n,
                            "selected": ("SELECTED" if (selected_set is not None and rel in selected_set)
                                         else ("NOT_SELECTED" if selected_set is not None else "UNKNOWN")),
                            "wall_s": (round(junit_secs[rel], 3) if rel in junit_secs else None),
                            "wall_label": ("OBSERVED_HOSTED" if rel in junit_secs else "UNKNOWN"),
                            "git_process_count": "UNKNOWN"})
        if rel in added:
            meta_rows.append({"module": rel, **_admission_metadata(rel, root)})
        marks = [ln.strip() for ln in src_now.splitlines() if re.search(r"\b(skip|xfail|skipif)\b", ln) and ln.strip().startswith(("@", "pytest.mark"))]
        new_skips += [{"module": rel, "marker": m[:120]} for m in marks[:3]]
        if rel in added:
            hashes = _body_hashes(src_now)
            for existing in sorted((root / "tests").glob("test_*.py")):
                erel = existing.as_posix()
                if erel == rel:
                    continue
                if erel not in existing_hashes:
                    existing_hashes[erel] = _body_hashes(existing.read_text(encoding="utf-8", errors="replace"))
                for name, h in sorted(hashes.items()):
                    for name2, h2 in sorted(existing_hashes[erel].items()):
                        if h == h2:
                            duplicates.append({"candidate": "%s::%s" % (rel, name), "existing": "%s::%s" % (erel, name2),
                                               "heuristic": "identical-normalized-AST-body", "severity": "WARN"})

    budget = budget_warnings(sorted(junit_paths)) if junit_paths else {"label": "WARN_ONLY", "enforced": False, "findings": [],
                                                                       "note": "UNKNOWN (no junit supplied)"}
    crit = {"label": "UNKNOWN (no plan supplied)"}
    if plan and plan.get("schedule", {}).get("predicted_critical_path_s") is not None:
        crit = {"plan_predicted_critical_path_s": plan["schedule"]["predicted_critical_path_s"],
                "label": "SIMULATION (weights: measured accepted)", "enforced": False}

    findings = []
    for row in meta_rows:
        for f, v in row.items():
            if f != "module" and v == "UNKNOWN":
                findings.append({"path": row["module"], "code": "ADM-METADATA-UNKNOWN", "field": f, "severity": "WARN",
                                 "message": "admission metadata field is UNKNOWN: " + f})
    for d in duplicates:
        findings.append({"path": d["candidate"], "code": "ADM-DUPLICATE-CANDIDATE", "severity": "WARN",
                         "message": "duplicate CANDIDATE (heuristic only, never automatic): %s" % d["existing"]})
    if new_skips:
        findings.append({"code": "ADM-NEW-SKIP", "severity": "WARN",
                         "message": "new skip/xfail markers present: a skipped node is never PASS (%d markers)" % len(new_skips)})

    return {"label": "WARN_ONLY", "what": "B3 test-admission report over the trusted-base diff",
            "base": base, "head": head, "tested_sha_from_plan": (plan or {}).get("tested_sha", "UNKNOWN"),
            "modules": {"added": added, "removed": removed, "renamed": renamed, "changed": changed},
            "node_deltas": node_deltas, "growth": growth,
            "admission_metadata": meta_rows, "duplicate_candidates": duplicates, "new_skip_markers": new_skips,
            "critical_path": crit, "budgets": budget, "findings": findings,
            "labels_used": ["MEASURED_LOCAL", "OBSERVED_HOSTED", "SIMULATION", "UNKNOWN", "WARN_ONLY"],
            "exit_code_policy": "always 0: informational, never a gate"}


if __name__ == "__main__":
    sys.exit(main())
