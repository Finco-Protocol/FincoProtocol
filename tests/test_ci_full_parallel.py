"""P2 parallel FULL controller: exact plan coverage, adaptive workers, and the strict record's fail-closed attack matrix (synthetic data)."""
import copy
import hashlib
import io
import json
import subprocess
import zipfile
from pathlib import Path

import pytest

from tools import ci_full_parallel as F
from tools.ci_v4_nodes import ids_digest, junit_address

ROOT = Path(__file__).resolve().parents[1]
SHA, TREE = "a" * 40, "b" * 40
RUN, ATTEMPT = 4242, 1
CONFTESTS = {"c" * 64: "tests/", "d" * 64: "tests/sub/"}
PROFILE_BODY = {"pytest": "9", "python": "3.12.16", "implementation": "CPython", "autoload_disabled": True,
                "registrations": [{"module": "_pytest.main", "registration": "main", "implementation": "module", "file_sha256": "m" * 64},
                                  {"module": "conftest", "registration": "<conftest>", "implementation": "module", "file_sha256": "c" * 64},
                                  {"module": "conftest", "registration": "<conftest>", "implementation": "module", "file_sha256": "d" * 64}]}
PROFILE = F.canonical_digest(PROFILE_BODY)


SCOPED_NODE = "tests/test_b.py::test_x"      # synthetic: ONE node of a module whose sibling (test_skip) is never scoped


def policy(**over):
    p = json.loads((ROOT / "docs/ci_v4/p2_full/full_parallel_policy.json").read_text())
    p = copy.deepcopy(p)
    p["min_collected_nodes"] = 1
    p["workers"].update({"min": 2, "max": 4, "per_worker_overhead_s": 10, "target_test_critical_path_s": 1, "min_gain_s_per_extra_worker": 1})
    p["node_split"]["modules"]["tests/test_big.py"] = {"verdict": "SPLIT_SAFE", "isolation_proof": "synthetic: no shared state between nodes, each node is independent",
                                                         "source": "test"}
    p["node_split"]["target_unit_s"] = 60
    p["scoped_modules"] = {"tests/test_a.py": {"verdict": "READ_ONLY_PER_TEST_SCOPE_SAFE", "proof": "synthetic: " + "x" * 80}}
    p["scoped_nodes"] = {SCOPED_NODE: {"verdict": "READ_ONLY_PER_NODE_SCOPE_SAFE", "proof": "synthetic: " + "y" * 80, "source": "docs/ci_v4/p2_full/test"}}
    p.update(over)
    return F.validate_policy(p)


def inventory(skip_modules=("tests/test_ui_browser.py",)):
    mods = {"tests/test_a.py": ["tests/test_a.py::test_%d" % i for i in range(3)],
            "tests/test_b.py": ["tests/test_b.py::test_x", "tests/test_b.py::test_skip"],
            "tests/test_big.py": ["tests/test_big.py::test_%d" % i for i in range(6)],
            "tests/sub/test_c.py": ["tests/sub/test_c.py::TestK::test_p[1]", "tests/sub/test_c.py::TestK::test_p[2]"]}
    inv = {"schema": F.INVENTORY_SCHEMA, "tested_sha": SHA, "tested_tree": TREE, "plugin_sha256": "f" * 64, "profile": PROFILE_BODY, "profile_digest": PROFILE,
           "modules": {m: {"node_ids": ids, "count": len(ids), "digest": ids_digest(ids)} for m, ids in mods.items()},
           "collection_skips": {m: "Skipped: playwright not installed in this workflow" for m in skip_modules},
           "node_count": sum(len(v) for v in mods.values())}
    return F.seal(inv)


WEIGHTS = {"nodes": {**{"tests/test_big.py::test_%d" % i: 40.0 for i in range(6)}, "tests/test_a.py::test_0": 30.0}, "modules": {}, "sources": ["t"]}


def make_plan(pol=None, inv=None):
    return F.make_plan(inv or inventory(), pol or policy(), WEIGHTS, RUN, ATTEMPT, "refs/heads/main", "workflow_dispatch", "Finco-Protocol/FincoProtocol")


def junit(cases):
    body = "".join(cases)
    return ('<?xml version="1.0" encoding="utf-8"?><testsuites><testsuite name="pytest" tests="%d">%s</testsuite></testsuites>'
            % (len(cases), body)).encode()


def case(nodeid, status="passed"):
    cls, name = junit_address(nodeid)
    inner = {"passed": "", "skipped": '<skipped type="pytest.skip" message="skip">reason</skipped>',
             "failed": '<failure message="boom">x</failure>'}[status]
    return '<testcase classname="%s" name="%s" time="0.1">%s</testcase>' % (cls, name, inner)


def coll_skip(module):
    return ('<testcase classname="" name="%s" time="0.000"><skipped message="collection skipped">(\'/w/%s\', 18, '
            '\'Skipped: playwright not installed in this workflow\')</skipped></testcase>' % (module[:-3].replace("/", "."), module))


SKIPPED_NODES = {"tests/test_b.py::test_skip"}


def artifacts(plan, inv, status=None):
    status = status or {}
    contents = {"plan": {"plan.json": json.dumps(plan).encode(), "inventory.json": json.dumps(inv).encode()},
                "recollect": {"inventory.json": json.dumps(inv).encode()},
                "f01": {"financial-browser.xml": junit([case("tests/finval_f01_browser_acceptance.py::test_v%d" % i) for i in range(4)]
                                                       + [case("tests/test_finval_f01_complete.py::test_c")]),
                        "native.xml": junit([case("tests/test_finval_f01_native_identity.py::test_n%d" % i) for i in range(20)])}}
    for a in plan["assignments"]:
        i = a["shard"]
        want = [n for m in sorted(a["modules"]) for n in a["modules"][m]["keep"]]
        st = {n: status.get(n, "skipped" if n in SKIPPED_NODES else "passed") for n in want}
        ev = {"schema": "FINCO_CI_V4_NODE_EVIDENCE_V1", "complete": True, "exitstatus": 0,
              "binding": {"tested_sha": SHA, "tested_tree": TREE, "plan_digest": plan["digest"], "shard": i},
              "profile": F.expected_shard_profile(PROFILE_BODY, a["order"], CONFTESTS),
              "profile_digest": F.canonical_digest(F.expected_shard_profile(PROFILE_BODY, a["order"], CONFTESTS)),
              "collected": {m: {"count": e["count"], "digest": e["digest"]} for m, e in a["modules"].items()}, "kept": want,
              "nodes": {n: {"outcome": st[n], "phases": {}, "duration": 1.0} for n in want}}
        rec = F.seal({"schema": F.SHARD_SCHEMA, "shard": i, "tested_sha": SHA, "tested_tree": TREE, "plan_digest": plan["digest"],
                      "run_id": RUN, "run_attempt": ATTEMPT, "plugin_sha256": "f" * 64, "pytest_exit": 0, "timed_out": False, "limit_s": 3000, "wall_s": 12.0, "targets": []})
        phases = {"passed": {"setup": "passed", "call": "passed", "teardown": "passed"}, "skipped": {"setup": "skipped", "teardown": "passed"},
                  "failed": {"setup": "passed", "call": "failed", "teardown": "passed"}}
        ph = {"schema": F.RECORDER_SCHEMA, "complete": True, "exitstatus": 0, "scoped_modules": sorted(set(a["modules"]) & set(plan["scoped_modules"])),
              "scoped_calls": 0, "nodes": {n: {"phases": phases[st[n]], "duration": 1.0} for n in want}}
        sn = F.shard_scoped_nodes(plan, a)
        ph["scoped_nodes"] = sn
        ph["scoped_node_calls"] = [n for n in sn if "call" in ph["nodes"][n]["phases"]]
        ph["scoped_calls"] = len(ph["scoped_node_calls"])
        contents["shard-%d" % i] = {"shard-%d.json" % i: json.dumps(rec).encode(), "nodes-%d.json" % i: json.dumps(ev).encode(),
                                    "phases-%d.json" % i: json.dumps(ph).encode(),
                                    "junit-%d.xml" % i: junit([case(n, st[n]) for n in want] + [coll_skip(m) for m in a["collection_skips"]])}
    return contents


BASELINE = {"tests.test_b::test_skip": 1, "::tests.test_ui_browser": 8}
RESULTS = {"plan": "success", "recollect": "success", "shards": "success", "f01": "success"}


def record(contents, plan, pol=None, baseline=BASELINE, sha=SHA, results=RESULTS):
    return F.build_record(contents, {}, pol or policy(), baseline, sha, TREE, RUN, ATTEMPT, results, CONFTESTS)


# ── plan ─────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────

def test_plan_union_is_exactly_the_inventory_disjoint_and_sealed():
    inv, plan = inventory(), make_plan()
    assert F.verify_plan_against_inventory(plan, inv)
    planned = [n for a in plan["assignments"] for e in a["modules"].values() for n in e["keep"]]
    assert sorted(planned) == sorted(n for s in inv["modules"].values() for n in s["node_ids"]) and len(planned) == len(set(planned))
    assert plan["split_modules"] == ["tests/test_big.py"]          # only the literal allowlisted heavy module is split
    assert {r["workers"] for r in plan["simulation"]} >= {8, 10, 12, 16}


@pytest.mark.parametrize("attack", ["drop_node", "duplicate_node", "foreign_node", "tamper_seal", "drop_collection_skip", "other_inventory"])
def test_plan_attacks_fail_closed(attack):
    inv, plan = inventory(), make_plan()
    a0 = plan["assignments"][0]
    mod = sorted(a0["modules"])[0]
    if attack == "drop_node":
        a0["modules"][mod]["keep"] = a0["modules"][mod]["keep"][1:] or a0["modules"][mod]["keep"]
        if len(a0["modules"][mod]["keep"]) == inv["modules"][mod]["count"]:
            a0["modules"][mod]["keep"].pop()
    elif attack == "duplicate_node":
        plan["assignments"][1]["modules"].setdefault(mod, dict(a0["modules"][mod], keep=[]))["keep"].append(a0["modules"][mod]["keep"][0])
    elif attack == "foreign_node":
        a0["modules"][mod]["keep"].append(mod + "::test_foreign")
    elif attack == "drop_collection_skip":
        for a in plan["assignments"]:
            a["collection_skips"] = []
    elif attack == "other_inventory":
        inv = inventory(skip_modules=())
    if attack != "tamper_seal" and attack != "other_inventory":
        plan = F.seal(plan)
    else:
        plan["workers"] = plan["workers"] if attack == "other_inventory" else plan["workers"] + 0
        if attack == "tamper_seal":
            plan["tested_sha"] = "c" * 40
    with pytest.raises(F.FullError):
        F.verify_plan_against_inventory(plan, inv)


def test_worker_count_is_adaptive_not_fixed():
    units = F.units_for(inventory(), policy(), WEIGHTS)
    many = policy(); many["workers"].update({"min": 1, "max": 6, "target_test_critical_path_s": 10 ** 6})
    assert F.choose_workers(units, many) == 1            # target already met: no runner is wasted
    tight = policy(); tight["workers"].update({"min": 1, "max": 6, "target_test_critical_path_s": 1, "min_gain_s_per_extra_worker": 10 ** 6})
    assert F.choose_workers(units, tight) == 1            # one more runner must buy at least the stated gain
    grow = policy(); grow["workers"].update({"min": 1, "max": 6, "target_test_critical_path_s": 1, "min_gain_s_per_extra_worker": 1})
    assert F.choose_workers(units, grow) > 1


def test_indivisible_shard_does_not_hide_avoidable_overruns_on_other_shards():
    pol = policy()
    pol["workers"]["min"] = 2
    pol["workers"]["target_test_critical_path_s"] = 1500
    units = [{"id": str(i), "seconds": duration}
             for i, duration in enumerate((3866, 1700, 1700, 1700))]
    _, loads_at_two = F.lpt(units, 2)
    chosen = F.choose_workers(units, pol)
    _, loads_at_choice = F.lpt(units, chosen)
    assert max(loads_at_choice) == 3866
    assert sum(load > pol["shard_timeout_s"] for load in loads_at_choice) == 1
    assert sum(max(0, load - pol["shard_timeout_s"]) for load in loads_at_choice) < sum(
        max(0, load - pol["shard_timeout_s"]) for load in loads_at_two)


def test_partial_collection_below_the_floor_is_refused():
    with pytest.raises(F.FullError, match="policy floor"):
        make_plan(pol=policy(min_collected_nodes=10 ** 6))


@pytest.mark.parametrize("mutate", [lambda p: p.update(schema="X"), lambda p: p["workers"].update(min=0),
                                    lambda p: p.update(skip_baseline="docs/other.json"),
                                    lambda p: p["node_split"]["modules"].update({"tests/*.py": {"verdict": "SPLIT_SAFE", "isolation_proof": "x" * 50}}),
                                    lambda p: p["node_split"]["modules"].update({"tests/test_q.py": {"verdict": "SPLIT_SAFE", "isolation_proof": "short"}}),
                                    lambda p: p["f01"].update(native_cases=19),
                                    lambda p: p["scoped_modules"].update({"tests/test_x*.py": {"verdict": "READ_ONLY_PER_TEST_SCOPE_SAFE", "proof": "x" * 90}}),
                                    lambda p: p["scoped_modules"].update({"tests/test_x.py": {"verdict": "READ_ONLY_PER_TEST_SCOPE_SAFE", "proof": "short"}}),
                                    lambda p: p.pop("scoped_modules"),
                                    lambda p: p.pop("scoped_nodes"),
                                    lambda p: p["scoped_nodes"].update({"tests/test_x.py": {"verdict": "READ_ONLY_PER_NODE_SCOPE_SAFE", "proof": "x" * 90, "source": "docs/ci_v4/p2_full/x"}}),
                                    lambda p: p["scoped_nodes"].update({"tests/test_x.py::test_*": {"verdict": "READ_ONLY_PER_NODE_SCOPE_SAFE", "proof": "x" * 90, "source": "docs/ci_v4/p2_full/x"}}),
                                    lambda p: p["scoped_nodes"].update({"tests/test_x.py::test_[ab]": {"verdict": "READ_ONLY_PER_NODE_SCOPE_SAFE", "proof": "x" * 90, "source": "docs/ci_v4/p2_full/x"}}),
                                    lambda p: p["scoped_nodes"].update({"tests/test_x.py::": {"verdict": "READ_ONLY_PER_NODE_SCOPE_SAFE", "proof": "x" * 90, "source": "docs/ci_v4/p2_full/x"}}),
                                    lambda p: p["scoped_nodes"].update({"tests/test_x.py::test_y": {"verdict": "READ_ONLY_PER_NODE_SCOPE_SAFE", "proof": "short", "source": "docs/ci_v4/p2_full/x"}}),
                                    lambda p: p["scoped_nodes"].update({"tests/test_x.py::test_y": {"verdict": "READ_ONLY_PER_TEST_SCOPE_SAFE", "proof": "x" * 90, "source": "docs/ci_v4/p2_full/x"}}),
                                    lambda p: p["scoped_nodes"].update({"tests/test_x.py::test_y": {"verdict": "READ_ONLY_PER_NODE_SCOPE_SAFE", "proof": "x" * 90, "source": "elsewhere"}}),
                                    lambda p: p["scoped_nodes"].update({sorted(p["scoped_modules"])[0] + "::test_z": {"verdict": "READ_ONLY_PER_NODE_SCOPE_SAFE", "proof": "x" * 90, "source": "docs/ci_v4/p2_full/x"}})])
def test_policy_cannot_be_weakened(mutate):
    p = json.loads((ROOT / "docs/ci_v4/p2_full/full_parallel_policy.json").read_text())
    mutate(p)
    with pytest.raises(F.FullError):
        F.validate_policy(p)


EVIDENCE = "docs/ci_v4/p2_full/ISOLATION_EVIDENCE.json"


def _evidence(module):
    d = json.loads((ROOT / EVIDENCE).read_text())
    rows = [r for r in d["evidence"] if r["module"] == module]
    assert len(rows) == 1, module
    return rows[0]


def test_real_policy_splits_only_isolation_proven_modules():
    p = F.load_policy()
    accepted = json.loads((ROOT / "docs/ci_v4/node_split_policy.json").read_text())["modules"]
    for m, spec in p["node_split"]["modules"].items():
        if m in accepted:                                   # the accepted, owner-reviewed verdicts, copied verbatim
            assert spec["isolation_proof"] == accepted[m]["isolation_proof"] and spec["verdict"] == accepted[m]["verdict"]
            continue
        assert spec["source"] == EVIDENCE                   # a P2 addition needs recorded local evidence: every node passes ALONE
        ev = _evidence(m)
        alone = [r for r in ev["runs"] if r["label"].startswith("node")]
        assert sorted(n for r in alone for n in r["outcomes"]) == sorted(ev["node_ids"]) and len(alone) == len(ev["node_ids"])
        assert all(r["rc"] == 0 and list(r["outcomes"].values()) == ["passed"] for r in alone)


def test_real_policy_scopes_only_modules_with_scoped_equals_plain_evidence():
    p = F.load_policy()
    assert p["scoped_modules"], "the allowlist is literal and non-empty only with evidence"
    for m, spec in p["scoped_modules"].items():
        assert spec["source"] == EVIDENCE
        ev = _evidence(m)
        runs = {r["label"]: r for r in ev["runs"]}
        assert runs["whole_scoped"]["outcomes"] == runs["whole_plain"]["outcomes"] and runs["whole_scoped"]["rc"] == runs["whole_plain"]["rc"] == 0
        assert runs["whole_scoped"]["scoped_calls"] == len(ev["node_ids"]) and runs["whole_plain"]["scoped_calls"] == 0
    assert p["min_collected_nodes"] >= json.loads((ROOT / "docs/ci_v4/ci-v4-policy.json").read_text())["release_gate"]["full_min_collected_nodes"]


# ── record: positive and the attack matrix ──────────────────────────────────────────────────────────────────────────────────────────

def test_complete_authentic_run_passes_and_satisfies_the_unchanged_release_gate(tmp_path):
    inv, plan = inventory(), make_plan()
    contents = artifacts(plan, inv)
    rec, problems = record(contents, plan)
    assert problems == [] and rec["conclusion"] == "pass"
    assert rec["executed_nodes"] == rec["collected_nodes"] == inv["node_count"] + 1
    assert rec["counts"] == {"passed": inv["node_count"] - 1, "failed": 0, "error": 0, "skipped": 2}
    from tools.ci_v4_release_gate import verify_record
    files = []
    for i in range(plan["workers"]):
        f = tmp_path / ("junit-%d.xml" % i)
        f.write_bytes(contents["shard-%d" % i]["junit-%d.xml" % i]); files.append(f)
    cfg = dict(json.loads((ROOT / "docs/ci_v4/ci-v4-policy.json").read_text())["release_gate"], full_min_collected_nodes=1)
    assert verify_record(rec, SHA, TREE, files, cfg, skip_baseline=BASELINE)


def _attack(name, contents, plan, inv):
    sh0 = contents["shard-0"]
    first = next(iter(sorted(plan["assignments"][0]["modules"])))
    node0 = plan["assignments"][0]["modules"][first]["keep"][0]
    if name == "single_case_forged_junit":
        sh0["junit-0.xml"] = junit([case(node0)])
    elif name == "missing_shard":
        del contents["shard-%d" % (plan["workers"] - 1)]
    elif name == "stale_sha":
        return {"sha": "c" * 40}
    elif name == "duplicate_node_across_shards":
        sh1 = contents["shard-1"]
        ev = json.loads(sh1["nodes-1.json"]); ev["nodes"][node0] = {"outcome": "passed", "phases": {}, "duration": 1}; ev["kept"].append(node0)
        sh1["nodes-1.json"] = json.dumps(ev).encode()
    elif name == "skipped_reported_as_pass":
        ph = json.loads(sh0["phases-0.json"]); ph["nodes"][node0]["phases"] = {"setup": "skipped", "teardown": "passed"}
        sh0["phases-0.json"] = json.dumps(ph).encode()
    elif name == "new_skip_outside_baseline":
        return {"rebuild": {node0: "skipped"}}
    elif name == "failure":
        return {"rebuild": {node0: "failed"}}
    elif name == "artifact_replay_other_run":
        p = json.loads(contents["plan"]["plan.json"]); p["run_id"] = RUN + 1; contents["plan"]["plan.json"] = json.dumps(F.seal(p)).encode()
    elif name == "shard_record_replayed_from_other_attempt":
        r = json.loads(sh0["shard-0.json"]); r["run_attempt"] = ATTEMPT + 1; sh0["shard-0.json"] = json.dumps(F.seal(r)).encode()
    elif name == "shard_ran_other_plugin":
        r = json.loads(sh0["shard-0.json"]); r["plugin_sha256"] = "0" * 64; sh0["shard-0.json"] = json.dumps(F.seal(r)).encode()
    elif name == "shard_timeout":
        r = json.loads(sh0["shard-0.json"]); r.update(timed_out=True, pytest_exit=124); sh0["shard-0.json"] = json.dumps(F.seal(r)).encode()
    elif name == "shard_record_unsealed_edit":
        r = json.loads(sh0["shard-0.json"]); r["pytest_exit"] = 0; r["wall_s"] = 1; sh0["shard-0.json"] = json.dumps(r).encode()
    elif name == "incomplete_node_evidence":
        ev = json.loads(sh0["nodes-0.json"]); ev["complete"] = False; sh0["nodes-0.json"] = json.dumps(ev).encode()
    elif name == "node_never_completed":
        ph = json.loads(sh0["phases-0.json"]); ph["nodes"][node0]["phases"] = {"setup": "passed", "teardown": "passed"}
        sh0["phases-0.json"] = json.dumps(ph).encode()
    elif name == "phase_record_lost_setup":
        ph = json.loads(sh0["phases-0.json"]); ph["nodes"][node0]["phases"] = {"call": "passed", "teardown": "passed"}
        sh0["phases-0.json"] = json.dumps(ph).encode()
    elif name == "phase_recorded_twice":
        ph = json.loads(sh0["phases-0.json"]); ph["nodes"][node0]["phases"]["call"] = "duplicate"
        sh0["phases-0.json"] = json.dumps(ph).encode()
    elif name == "recorder_missing_node":
        ph = json.loads(sh0["phases-0.json"]); del ph["nodes"][node0]; sh0["phases-0.json"] = json.dumps(ph).encode()
    elif name == "scope_allowlist_widened":
        ph = json.loads(sh0["phases-0.json"]); ph["scoped_modules"] = sorted(set(ph["scoped_modules"]) | {"tests/test_b.py"})
        sh0["phases-0.json"] = json.dumps(ph).encode()
    elif name in ("scoped_node_allowlist_widened", "scoped_node_allowlist_dropped", "scoped_node_call_missing", "scoped_node_call_forged",
                  "scoped_node_call_duplicated"):
        k = next("shard-%d" % a["shard"] for a in plan["assignments"] if F.shard_scoped_nodes(plan, a))
        sh = contents[k]
        f = next(x for x in sh if x.startswith("phases-"))
        ph = json.loads(sh[f])
        if name == "scoped_node_allowlist_widened":
            ph["scoped_nodes"] = sorted(set(ph["scoped_nodes"]) | {"tests/test_b.py::test_skip"})
        elif name == "scoped_node_allowlist_dropped":
            ph["scoped_nodes"] = []
        elif name == "scoped_node_call_missing":
            ph["scoped_node_calls"] = []
        elif name == "scoped_node_call_forged":
            ph["scoped_node_calls"] = ph["scoped_node_calls"] + ["tests/test_b.py::test_skip"]
        else:
            ph["scoped_node_calls"] = ph["scoped_node_calls"] * 2
        sh[f] = json.dumps(ph).encode()
    elif name == "recorder_incomplete":
        ph = json.loads(sh0["phases-0.json"]); ph["exitstatus"] = 1; sh0["phases-0.json"] = json.dumps(ph).encode()
    elif name == "other_plugin_profile":
        ev = json.loads(sh0["nodes-0.json"]); ev["profile"]["registrations"].append({"module": "evil", "registration": "evil",
                                                                                     "implementation": "module", "file_sha256": None})
        ev["profile_digest"] = F.canonical_digest(ev["profile"]); sh0["nodes-0.json"] = json.dumps(ev).encode()
    elif name == "foreign_conftest_loaded":
        ev = json.loads(sh0["nodes-0.json"]); ev["profile"] = copy.deepcopy(PROFILE_BODY)
        if F.expected_shard_profile(PROFILE_BODY, plan["assignments"][0]["order"], CONFTESTS) == PROFILE_BODY:
            ev["profile"]["registrations"][1]["file_sha256"] = "e" * 64
        ev["profile_digest"] = F.canonical_digest(ev["profile"]); sh0["nodes-0.json"] = json.dumps(ev).encode()
    elif name == "recollection_differs":
        contents["recollect"]["inventory.json"] = json.dumps(inventory(skip_modules=())).encode()
    elif name == "plan_seal_tampered":
        p = json.loads(contents["plan"]["plan.json"]); p["workers"] += 1; contents["plan"]["plan.json"] = json.dumps(p).encode()
    elif name == "f01_native_missing":
        contents["f01"]["native.xml"] = junit([case("tests/test_finval_f01_native_identity.py::test_n%d" % i) for i in range(19)])
    elif name == "f01_browser_skipped":
        contents["f01"]["financial-browser.xml"] = junit([case("tests/finval_f01_browser_acceptance.py::test_v%d" % i, "skipped") for i in range(4)])
    elif name == "job_not_success":
        return {"results": dict(RESULTS, shards="cancelled")}
    elif name == "lost_artifact_member":
        del sh0["nodes-0.json"]
    elif name == "collection_skip_dropped":
        for a in plan["assignments"]:
            if a["collection_skips"]:
                k = "shard-%d" % a["shard"]
                xml = contents[k]["junit-%d.xml" % a["shard"]].decode()
                contents[k]["junit-%d.xml" % a["shard"]] = xml.replace(coll_skip(a["collection_skips"][0]), "").encode()
    elif name == "junit_dtd_entity":
        sh0["junit-0.xml"] = b'<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "b">]>' + sh0["junit-0.xml"].split(b"?>", 1)[1]
    else:
        raise AssertionError(name)
    return {}


ATTACKS = ["single_case_forged_junit", "missing_shard", "stale_sha", "duplicate_node_across_shards", "skipped_reported_as_pass",
           "new_skip_outside_baseline", "failure", "artifact_replay_other_run", "shard_record_replayed_from_other_attempt", "shard_ran_other_plugin", "shard_timeout",
           "shard_record_unsealed_edit", "incomplete_node_evidence", "node_never_completed", "phase_record_lost_setup", "phase_recorded_twice",
           "recorder_missing_node", "recorder_incomplete", "scope_allowlist_widened", "other_plugin_profile", "recollection_differs",
           "foreign_conftest_loaded", "plan_seal_tampered", "f01_native_missing", "f01_browser_skipped", "job_not_success", "lost_artifact_member", "collection_skip_dropped",
           "junit_dtd_entity", "scoped_node_allowlist_widened", "scoped_node_allowlist_dropped", "scoped_node_call_missing",
           "scoped_node_call_forged", "scoped_node_call_duplicated"]


@pytest.mark.parametrize("name", ATTACKS)
def test_record_attack_matrix_fails_closed(name):
    inv, plan = inventory(), make_plan()
    contents = artifacts(plan, inv)
    kw = _attack(name, contents, plan, inv)
    if "rebuild" in kw:
        contents = artifacts(plan, inv, status=kw["rebuild"])
    rec, problems = record(contents, plan, sha=kw.get("sha", SHA), results=kw.get("results", RESULTS))
    assert rec["conclusion"] == "fail" and problems, name


def test_old_record_accepted_a_single_forged_case_the_new_record_does_not(tmp_path):
    """The audit weakness of tools/ci_v4_full_record.py: ONE synthetic passing testcase produced a ``pass`` record."""
    from tools import ci_v4_full_record as OLD
    f = tmp_path / "e" / "results.xml"; f.parent.mkdir()
    f.write_bytes(junit([case("tests/test_a.py::test_0")]))
    old = OLD.build(SHA, TREE, OLD.collect(tmp_path / "e"), {"v3": "success", "f01": "success"}, RUN, ATTEMPT)
    assert old["conclusion"] == "pass" and old["executed_nodes"] == 1
    inv, plan = inventory(), make_plan()
    contents = artifacts(plan, inv)
    _attack("single_case_forged_junit", contents, plan, inv)
    assert record(contents, plan)[0]["conclusion"] == "fail"


# ── authenticated transport ─────────────────────────────────────────────────────────────────────────────────────────────────────────

def _zip(members, symlink=None):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for k, v in members.items():
            z.writestr(k, v)
        if symlink:
            info = zipfile.ZipInfo(symlink); info.external_attr = 0o120777 << 16
            z.writestr(info, "/etc/passwd")
    return buf.getvalue()


class FakeGH:
    repo = "Finco-Protocol/FincoProtocol"

    def __init__(self, arts, blobs, fail=None):
        self.arts, self.blobs, self.fail = arts, blobs, fail

    def _pages(self, path, key):
        if self.fail:
            raise self.fail
        return self.arts

    def download(self, a, limit=None):
        return self.blobs[a["id"]]


def _api(workers, tamper=None):
    names = F.expected_artifact_names(workers, ATTEMPT)
    arts, blobs = [], {}
    for i, (logical, name) in enumerate(sorted(names.items())):
        blob = _zip({"x.json": b"{}"})
        blobs[i] = blob
        arts.append({"id": i, "name": name, "digest": "sha256:" + hashlib.sha256(blob).hexdigest(), "workflow_run": {"id": RUN}})
    if tamper == "digest":
        blobs[0] = blobs[0] + b"x"
    elif tamper == "missing":
        arts.pop()
    elif tamper == "duplicate":
        arts.append(dict(arts[0], id=99)); blobs[99] = blobs[0]
    elif tamper == "other_run":
        arts[0]["workflow_run"] = {"id": RUN + 7}
    return arts, blobs


def test_fetch_requires_exactly_the_expected_artifacts_with_github_digests():
    arts, blobs = _api(2)
    contents, prov = F.fetch_artifacts(FakeGH(arts, blobs), RUN, ATTEMPT, 2)
    assert set(contents) == {"plan", "recollect", "f01", "shard-0", "shard-1"}
    assert all(p["digest"].startswith("sha256:") for p in prov.values())


@pytest.mark.parametrize("tamper", ["digest", "missing", "duplicate", "other_run"])
def test_fetch_attacks_fail_closed(tamper):
    arts, blobs = _api(2, tamper)
    with pytest.raises(F.FullError):
        F.fetch_artifacts(FakeGH(arts, blobs), RUN, ATTEMPT, 2)


def test_api_outage_is_never_a_pass():
    from tools.ci_perf_guard import TransientError
    with pytest.raises(TransientError):
        F.fetch_artifacts(FakeGH([], {}, fail=TransientError("GitHub API 503")), RUN, ATTEMPT, 2)


@pytest.mark.parametrize("members", [{"../evil.json": b"{}"}, {"/abs.json": b"{}"}])
def test_unsafe_zip_members_are_refused(members):
    with pytest.raises(F.FullError):
        F.safe_members(_zip(members), "t")


def test_symlink_zip_member_is_refused():
    with pytest.raises(F.FullError):
        F.safe_members(_zip({"a.json": b"{}"}, symlink="link"), "t")


# ── the real workflow ───────────────────────────────────────────────────────────────────────────────────────────────────────────────

def test_full_workflow_structure():
    wf = (ROOT / ".github/workflows/ci_v4_full.yml").read_text()
    import yaml
    d = yaml.safe_load(wf)
    on = d.get("on", d.get(True))
    assert set(on) == {"schedule", "workflow_dispatch"}                      # never a pull_request trigger: PR bytes cannot produce a FULL
    assert d["permissions"] == {"contents": "read", "actions": "read"}
    jobs = d["jobs"]
    assert set(jobs) == {"plan", "recollect", "shards", "f01", "record"}
    assert jobs["f01"]["uses"] == "./.github/workflows/ci_v4_f01_job.yml" and jobs["f01"]["with"]["run-native"] is True
    assert jobs["record"]["if"] == "always()" and set(jobs["record"]["needs"]) == {"plan", "recollect", "shards", "f01"}
    assert jobs["shards"]["strategy"]["fail-fast"] is False
    names = F.expected_artifact_names(3, 1)
    assert "ci-full-plan-attempt-${{ github.run_attempt }}" in wf and "ci-full-recollect-attempt-${{ github.run_attempt }}" in wf
    assert "ci-full-shard-${{ matrix.index }}-attempt-${{ github.run_attempt }}" in wf and names["f01"] == "ci-v4-f01-1"
    assert "name: ci-v4-full-record" in wf                                    # the unchanged release gate's artifact name
    assert "secrets." not in wf and "pull_request" not in wf
    for job in jobs.values():
        for step in job.get("steps", []):
            if "actions/checkout" in step.get("uses", ""):
                assert step["with"]["persist-credentials"] is False and step["with"]["ref"] == "${{ github.sha }}"


def test_shard_profile_keeps_only_ancestor_conftests():
    only_top = F.expected_shard_profile(PROFILE_BODY, ["tests/test_a.py"], CONFTESTS)
    both = F.expected_shard_profile(PROFILE_BODY, ["tests/test_a.py", "tests/sub/test_c.py"], CONFTESTS)
    assert [r["file_sha256"] for r in only_top["registrations"]] == ["m" * 64, "c" * 64]
    assert both == PROFILE_BODY
    with pytest.raises(F.FullError, match="unknown conftest"):
        F.expected_shard_profile(PROFILE_BODY, ["tests/test_a.py"], {"c" * 64: "tests/"})


def test_conftest_map_of_the_real_checkout():
    m = F.conftest_dirs(ROOT)
    assert sorted(m.values()) == ["tests/", "tests/tax_reference_registry/"]


def test_recorder_scope_is_literal_per_call_and_never_outlives_a_test():
    src = F.RECORDER_SOURCE
    assert 'os.environ.pop("FINCO_CI_FULL_SCOPED"' in src and 'os.environ.pop("FINCO_CI_FULL_RECORDER"' in src
    assert "def pytest_runtest_call(item):" in src and "hookwrapper=True" in src
    assert "stack.enter_context(C.call_scope())" in src and "stack.enter_context(M.scope())" in src
    body = src.split("def pytest_runtest_call(item):")[1].split("\ndef ")[0]
    assert "pytest_runtest_setup" not in src and "pytest_runtest_teardown" not in src
    assert "session" not in body and "_S[\"scoped\"] =" not in body      # the hook never widens its allowlist or keeps state across tests


# ── per-node scope (post-#460): exact node ids only, each present in the current complete collection, bound plan → shard → recorder ─────
def test_scoped_node_is_planned_only_as_its_exact_id_and_never_widens_to_its_module():
    plan = make_plan()
    assert plan["scoped_nodes"] == [SCOPED_NODE]
    holders = [a for a in plan["assignments"] if F.shard_scoped_nodes(plan, a)]
    assert len(holders) == 1 and F.shard_scoped_nodes(plan, holders[0]) == [SCOPED_NODE]
    assert "tests/test_b.py" not in plan["scoped_modules"]


def test_a_scoped_node_missing_from_the_current_collection_refuses_the_plan():
    pol = policy()
    pol["scoped_nodes"]["tests/test_b.py::test_x_renamed"] = dict(pol["scoped_nodes"][SCOPED_NODE])
    with pytest.raises(F.FullError, match="not in the current collection"):
        make_plan(pol=F.validate_policy(pol))


def test_positive_record_binds_the_scoped_nodes():
    inv, plan = inventory(), make_plan()
    rec, problems = record(artifacts(plan, inv), plan)
    assert problems == [] and rec["strict"]["scoped_nodes"] == [SCOPED_NODE]


def test_recorder_per_node_scope_is_exact_and_fails_closed_on_a_leaked_scope():
    src = F.RECORDER_SOURCE
    assert 'os.environ.pop("FINCO_CI_FULL_SCOPED_NODES"' in src
    body = src.split("def pytest_runtest_call(item):")[1].split("\ndef ")[0]
    assert 'exact = item.nodeid in _S.get("scoped_nodes", ())' in body
    assert body.count('raise RuntimeError(') == 2                    # an open scope before, or a scope outliving, the call is an error
    assert '_S["scoped_nodes"] =' not in body and "startswith" not in body and "fnmatch" not in body


def test_real_policy_scopes_only_nodes_with_scoped_equals_plain_evidence():
    p = F.load_policy()
    ev = json.loads((ROOT / "docs/ci_v4/p2_full/NODE_SCOPE_EVIDENCE.json").read_text())
    assert ev["schema"] == "FINCO_CI_FULL_NODE_SCOPE_EVIDENCE_V1"
    assert set(p["scoped_nodes"]) == set(ev["nodes"]) and p["scoped_nodes"]
    for n, spec in p["scoped_nodes"].items():
        assert spec["source"] == "docs/ci_v4/p2_full/NODE_SCOPE_EVIDENCE.json"
        r = ev["nodes"][n]
        assert r["plain"]["outcome"] == r["scoped"]["outcome"] == "passed" and r["plain"]["rc"] == r["scoped"]["rc"] == 0
        assert r["scoped"]["scoped_node_calls"] == [n] and r["plain"]["scoped_node_calls"] == []
        assert r["mutation_between_calls_detected"] is True and r["sibling_modules_not_scoped"] is True
