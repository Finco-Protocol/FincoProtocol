"""Compare observed standalone skip/xfail records with the authoritative sequential (control) JUnit.

Output is a PROPOSED exact-content policy, never an approval: only records identical to the control (same exact
node id, status and reason) are proposed. Anything the control executes but the shadow environment skips is an
environment-driven coverage loss and is rejected; records unknown to the control need an owner decision. A failure
is never convertible into a skip because only skip/xfail elements from successfully completed standalone runs are read."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import xml.etree.ElementTree as ET

from tools.ci_v3_schema import ContractError, read_json, require, seal, write_json

OPTIONAL_RUNTIME_MARKERS = ("not installed", "not available", "unavailable", "could not import", "No module named")


def node_id(classname, name, modules):
    parts = (classname or "").split(".")
    for cut in range(len(parts), 0, -1):
        module = "/".join(parts[:cut]) + ".py"
        if module in modules:
            return "::".join([module, *parts[cut:], name])
    return None


def read_control(results_xml, modules=None):
    """-> (runtime nonpass records, collection skips, all executed case ids). Exact ids; duplicates rejected."""
    data = Path(results_xml).read_bytes()
    require(b"<!DOCTYPE" not in data.upper() and b"<!ENTITY" not in data.upper(), "control JUnit DTD/entity")
    root = ET.fromstring(data)
    cases = list(root.iter("testcase"))
    guessed = modules or {"/".join(c.get("classname").split(".")[:2]) + ".py" for c in cases if c.get("classname")}
    runtime, collection, executed = {}, [], set()
    for case in cases:
        skipped, classname = case.find("skipped"), case.get("classname") or ""
        if not classname:   # collection-level skip: the module was never expanded into nodes
            if skipped is not None:
                collection.append({"nodeid": case.get("name").replace(".", "/") + ".py", "reason": skipped.get("message") or ""})
            continue
        ident = node_id(classname, case.get("name"), guessed)
        require(ident is not None, "control case outside known modules: " + classname)
        require(ident not in executed, "duplicate control node id: " + ident)
        executed.add(ident)
        if skipped is not None:
            runtime[ident] = {"status": "xfail" if skipped.get("type") == "pytest.xfail" else "skipped", "reason": skipped.get("message") or ""}
    return runtime, collection, executed, hashlib.sha256(data).hexdigest()


def compare(observed, control_runtime, control_executed, collected_nodes):
    proposed, rejected, owner, matched = {}, {}, {}, set()
    for ident, record in sorted(observed.items()):
        require(isinstance(record, dict) and set(record) == {"status", "reason"}, "malformed observed record: " + ident)
        control = control_runtime.get(ident)
        entry = {**record, "environment_dependent": any(m in record["reason"] for m in OPTIONAL_RUNTIME_MARKERS)}
        if control == record:
            proposed[ident] = entry; matched.add(ident)
        elif control is not None:
            rejected[ident] = {**entry, "why": "changed", "control": control}
        elif ident in control_executed:
            rejected[ident] = {**entry, "why": "environment-coverage-loss: the control executes this node, the shadow environment skips it"}
        else:
            owner[ident] = {**entry, "why": "node is not in the control run's tree; owner decision required"}
    missing = {i: r for i, r in sorted(control_runtime.items()) if i not in observed and i in collected_nodes}
    return proposed, rejected, owner, missing


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--observed", required=True, help="allowed-nonpass-proposal.json from ci_v3_classify")
    parser.add_argument("--control-xml", required=True); parser.add_argument("--control-ref", required=True, help="run/artifact identity text")
    parser.add_argument("--inventory", required=True); parser.add_argument("--collection", required=True); parser.add_argument("--output", required=True)
    args = parser.parse_args(argv)
    inventory, collection = read_json(args.inventory), read_json(args.collection)
    nodes = [n["nodeid"] for n in inventory["nodes"]]
    modules = {n["module"] for n in inventory["nodes"]}
    try:
        runtime, ctl_collection, executed, digest = read_control(args.control_xml, modules | {s["nodeid"] for s in collection["skips"]})
    except ContractError as exc:
        print("CI_V3_NONPASS_REJECTED: " + str(exc)); return 1
    observed = read_json(args.observed)["records"]
    proposed, rejected, owner, missing = compare(observed, runtime, executed, set(nodes))
    ctl_skips = {s["nodeid"]: s["reason"] for s in ctl_collection}
    mine_skips = {s["nodeid"]: s["reason"] for s in collection["skips"]}
    coverage = {"control_cases": len(executed) + len(ctl_collection), "shadow_nodes_plus_collection_skips": len(nodes) + len(collection["skips"]),
                "control_only_nodes": sorted(executed - set(nodes))[:20], "shadow_only_nodes": sorted(set(nodes) - executed)[:20],
                "collection_skip_modules_identical": set(ctl_skips) == set(mine_skips), "collection_skip_modules": len(mine_skips),
                "collection_skip_reason_note": "the control JUnit records collection-level skips only as 'collection skipped'; module identities are compared, reasons come from the shadow adapter"}
    policy = seal({"schema": 1, "kind": "ci-v3-nonpass-policy-proposal", "authority": "proposal-not-approved", "approved": False,
        "control": {"reference": args.control_ref, "results_xml_sha256": digest, "runtime_nonpass": len(runtime), "collection_skips": len(ctl_collection)},
        "source": inventory["source"], "inventory_digest": inventory["digest"], "coverage_equivalence": coverage,
        "allowed_nonpass": proposed, "rejected": rejected, "needs_owner_decision": owner, "control_nonpass_not_reproduced": missing})
    out = Path(args.output); out.parent.mkdir(parents=True, exist_ok=True); write_json(out, policy)
    print(json.dumps({"proposed": len(proposed), "rejected": len(rejected), "owner_decision": len(owner), "not_reproduced": len(missing),
                      "coverage": {k: v for k, v in coverage.items() if k.endswith("only_nodes") is False}}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
