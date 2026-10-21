"""Turn current collection and standalone-module attempts into an UNREVIEWED isolation and nonpass proposal.

Every attempt is preserved with its exact evidence. A module is proposed `runner-private` only when all of its
attempts are clean and consistent. A module that ever failed, timed out, was killed for capacity, or returned an
inconsistent verdict stays `blocked`; later uncontended PASSes never unlock it. The single exception is repeated
PASSes at the equivalent target concurrency (identical image and source, N concurrent worker-sized containers),
which still leaves the prior failure recorded and `reviewed` false. Nothing here is an owner approval."""
from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
import re
import tarfile
import xml.etree.ElementTree as ET

from tools.ci_v3_schema import ContractError, read_json, require, seal, write_json

TARGET_WORKERS = 3
MIN_TARGET_CPUS = 1.33   # 4 vCPU shared by three worker-sized containers; a hosted worker has its own runner, so this is conservative
MIN_TARGET_PASSES = 5
CAPACITY_EXIT = {-9, 137}          # SIGKILL / OOM kill
CAPACITY_MARKERS = ("MemoryError", "No space left on device", "Cannot allocate memory", "Too many open files")
RESOLVED = ("stable-pass", "target-concurrency-stability-validated", "not-collected-helper", "collection-skipped")


def load_attempts(directory, expect=None):
    """Read one probe run directory (meta.json + lane-*/results.jsonl). `expect` binds image id and source tree."""
    directory = Path(directory)
    meta = read_json(directory / "meta.json")
    require(meta["kind"] in ("first", "uncontended", "target"), "unknown attempt kind")
    if expect and not meta.get("historical"):
        require(meta["image_id"] == expect["image_id"] and meta["tree"] in expect["trees"], "attempt was not executed on the evidence image/source")
    files = sorted(directory.glob("lane-*/results.jsonl")) or [directory / "results.jsonl"]   # raw lanes, or the packed form
    records = [json.loads(line) for f in files if f.exists() for line in f.read_text().splitlines()]
    require(records, "empty attempt evidence: " + str(directory))
    return meta, records


def collect(runs, expect=None):
    """module -> list of attempt records, each carrying its run meta. Duplicate (run, module, tag) is rejected."""
    result, seen = {}, set()
    for directory in runs:
        meta, records = load_attempts(directory, expect)
        for item in records:
            key = (meta["label"], item["module"], item.get("tag"))
            require(key not in seen, "duplicate attempt evidence: " + "/".join(map(str, key)))
            seen.add(key)
            result.setdefault(item["module"], []).append({**item, "kind": meta["kind"], "label": meta["label"],
                "concurrency": meta["concurrency"], "cpus": float(meta.get("cpus_per_container") or 0), "image_id": meta["image_id"], "tree": meta["tree"],
                "historical": bool(meta.get("historical"))})
    return result


def status(attempt, expected):
    """Verdict of one attempt; the strictest reading wins."""
    if attempt["timed_out"]:
        return "timeout"
    if attempt["exit_code"] in CAPACITY_EXIT or any(m in (attempt.get("tail") or "") for m in CAPACITY_MARKERS):
        return "capacity"
    if attempt["exit_code"] != 0 or attempt["failures"] or attempt["errors"]:
        return "fail"
    if attempt["tests"] != expected:
        return "coverage-mismatch"
    return "pass-with-nonpass" if attempt["skipped"] else "pass"


SHA256 = re.compile(r"[0-9a-f]{64}")


def exclusion(attempt, current_sha):
    """Why an attempt cannot be counted, or None. Positive evidence needs the exact current module blob identity."""
    if attempt.get("historical"):
        if current_sha is not None and attempt.get("module_sha256") == current_sha and status(attempt, attempt["tests"]) not in ("pass", "pass-with-nonpass"):
            return None            # a historical FAILURE on an unchanged module still counts against it
        return "historical-evidence"
    if current_sha is None or not SHA256.fullmatch(current_sha):
        return "current-module-identity-unavailable"
    recorded = attempt.get("module_sha256")
    if recorded is None:
        return "missing-module-sha256"
    if not isinstance(recorded, str) or not SHA256.fullmatch(recorded):
        return "malformed-module-sha256"
    if recorded != current_sha:
        return "stale-or-mismatched-module-sha256"
    return None


def annotate(attempts, current_sha):
    """Every attempt is preserved verbatim; the annotation says whether it counts and why not."""
    return [{**a, "counts": (reason := exclusion(a, current_sha)) is None, "exclusion": reason} for a in attempts]


def relevant(attempts, current_sha):
    return [a for a in attempts if exclusion(a, current_sha) is None]


def decide(attempts, expected, min_target=MIN_TARGET_PASSES, current_sha=None):
    """Return (mode, category, reason) from every relevant attempt."""
    reasons = sorted({r for a in attempts if (r := exclusion(a, current_sha)) and not a.get("historical")})
    attempts = relevant(attempts, current_sha)
    if not any(not a.get("historical") for a in attempts):
        why = f" ({', '.join(reasons)})" if reasons else ""
        return "blocked", "no-standalone-evidence", "no attempt with the exact current module identity on the evidence image and source" + why
    verdicts = [status(a, expected) for a in attempts]
    for bad, category in (("timeout", "timeout"), ("capacity", "capacity-exhaustion"), ("coverage-mismatch", "coverage-mismatch")):
        if bad in verdicts:
            return "blocked", category, f"{bad} in attempt(s) " + ", ".join(a["label"] for a, v in zip(attempts, verdicts) if v == bad)
    passing = {"pass", "pass-with-nonpass"}
    if all(v in passing for v in verdicts):
        if len({a["skipped"] for a in attempts}) > 1:
            return "blocked", "inconsistent-verdicts", "attempts disagree on the number of runtime skips/xfails"
        if verdicts[0] == "pass-with-nonpass":
            return "blocked", "nonpass-approval-required", f"{attempts[0]['skipped']} runtime skip/xfail record(s); owner must approve the exact nonpass policy"
        return "runner-private", "stable-pass", f"{len(attempts)} consistent PASS attempt(s), {expected} nodes, no skips"
    if all(v == "fail" for v in verdicts):
        return "blocked", "standalone-failure", f"failed in all {len(attempts)} attempt(s)"
    target = [(a, v) for a, v in zip(attempts, verdicts)
              if a["kind"] == "target" and a["concurrency"] == TARGET_WORKERS and a.get("cpus", MIN_TARGET_CPUS) >= MIN_TARGET_CPUS]
    if any(v == "fail" for _, v in target):
        return "blocked", "inconsistent-verdicts", "failed at the equivalent target concurrency"
    passes = sum(1 for _, v in target if v in passing)
    if passes >= min_target and all(a["skipped"] == 0 for a, _ in target):
        starved = sorted({a["cpus"] for a, v in zip(attempts, verdicts) if v == "fail" and a.get("cpus")})
        constraint = f"; resource constraint: failed at {starved} CPU, validated at >= {MIN_TARGET_CPUS} CPU per worker" if starved else ""
        return "runner-private", "target-concurrency-stability-validated", (
            f"earlier failure retained; {passes} consecutive PASSes at {TARGET_WORKERS}-way concurrency{constraint}; owner must review the prior failure")
    return "blocked", "load-sensitive-unproven", (
        f"failed once, later passes do not prove stability: {passes}/{min_target} target-concurrency PASSes "
        f"({sum(a['kind'] == 'uncontended' for a in attempts)} uncontended rerun(s) are not equivalent evidence)")


def junit_blobs(directory):
    """Raw JUnit bytes of one attempt directory (lane files or the packed junit.tar.xz), in a stable order."""
    directory = Path(directory)
    packed = directory / "junit.tar.xz"
    if packed.exists():
        with tarfile.open(packed) as tar:
            return [tar.extractfile(m).read() for m in sorted(tar.getmembers(), key=lambda m: m.name) if m.isfile()]
    return [f.read_bytes() for f in sorted(directory.glob("lane-*/*.xml"))]


def nonpass_proposal(junit_documents, nodeids):
    """Observed standalone skip/xfail records keyed by exact original node id (proposal; owners approve)."""
    modules = {n.split("::", 1)[0] for n in nodeids}; known = set(nodeids)
    proposal, unmatched = {}, []
    for document in junit_documents:
        require(b"<!DOCTYPE" not in document.upper() and b"<!ENTITY" not in document.upper(), "JUnit DTD/entity")
        for case in ET.fromstring(document).iter("testcase"):
            node = case.find("skipped")
            if node is None:
                continue
            parts = case.get("classname", "").split(".")
            nodeid = None
            for cut in range(len(parts), 0, -1):
                module = "/".join(parts[:cut]) + ".py"
                if module in modules:
                    nodeid = "::".join([module, *parts[cut:], case.get("name")]); break
            reason = node.get("message") or "no reason recorded"
            record = {"status": "xfail" if node.get("type") == "pytest.xfail" else "skipped", "reason": reason}
            if nodeid in known:
                require(proposal.get(nodeid, record) == record, "inconsistent nonpass observations for " + nodeid)
                proposal[nodeid] = record
            else:
                unmatched.append({"classname": case.get("classname"), "name": case.get("name"), "reason": reason})
    return proposal, unmatched


def classify(prepared, attempts, skipped_modules=frozenset(), min_target=MIN_TARGET_PASSES):
    inventory, isolation = prepared["inventory"], prepared["isolation"]
    expected = Counter(n["module"] for n in inventory["nodes"])
    modules, summary = {}, Counter()
    for name, base in isolation["modules"].items():
        record = dict(base); history = attempts.get(name, [])
        if name in skipped_modules:
            mode, category, reason = "blocked", "collection-skipped", "whole module skipped at collection (missing optional runtime); allowed only if the control skips it identically"
        elif name not in expected:
            mode, category, reason = "blocked", "not-collected-helper", "no collected nodes; helper or collection-skipped file"
        else:
            mode, category, reason = decide(history, expected[name], min_target, base.get("sha256"))
        record.update(mode=mode, category=category, reason=reason, rationale=reason, reviewed=False, attempts=annotate(history, base.get("sha256")))
        modules[name] = record; summary[category] += 1
    proposal = seal({**{k: v for k, v in isolation.items() if k not in ("digest", "modules")},
                     "modules": modules, "authority": "evidence-proposal-unreviewed"})
    unresolved = sorted(n for n, r in modules.items() if r["category"] not in RESOLVED)
    return proposal, {"modules": len(modules), "categories": dict(summary), "unresolved_blocking_admission": len(unresolved),
                      "unresolved_modules": unresolved}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prepared", required=True); parser.add_argument("--attempt", required=True, nargs="+", help="probe run directories")
    parser.add_argument("--output", required=True); parser.add_argument("--image-id"); parser.add_argument("--tree", nargs="+", help="accepted executed trees (baseline plus targeted re-runs)")
    parser.add_argument("--min-target-passes", type=int, default=MIN_TARGET_PASSES)
    args = parser.parse_args(argv)
    prepared = {k: read_json(Path(args.prepared) / (k + ".json")) for k in ("inventory", "isolation", "collection")}
    skipped = {r["nodeid"] for r in prepared["collection"]["skips"]}
    expect = {"image_id": args.image_id, "trees": args.tree} if args.image_id else None
    try:
        proposal, summary = classify(prepared, collect(args.attempt, expect), skipped, args.min_target_passes)
        junit = [blob for d in args.attempt if not (json.loads((Path(d) / "meta.json").read_text()).get("historical")) for blob in junit_blobs(d)]
        allowed, unmatched = nonpass_proposal(junit, [n["nodeid"] for n in prepared["inventory"]["nodes"]])
    except ContractError as exc:
        print("CI_V3_CLASSIFY_REJECTED: " + str(exc)); return 1
    out = Path(args.output); out.mkdir(parents=True, exist_ok=False)
    summary.update(collection_skipped_modules=sorted(skipped), observed_runtime_nonpass=len(allowed), unmatched_nonpass=len(unmatched))
    write_json(out / "isolation-proposal.json", proposal); write_json(out / "summary.json", summary)
    write_json(out / "allowed-nonpass-proposal.json", {"authority": "evidence-proposal-unreviewed", "records": allowed, "unmatched": unmatched})
    print(json.dumps({k: v for k, v in summary.items() if k not in ("unresolved_modules", "collection_skipped_modules")})); return 0


if __name__ == "__main__":
    raise SystemExit(main())
