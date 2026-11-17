"""CI Performance Budget guard (tools/ci_perf_guard.py, .github/workflows/ci_perf_guard.yml, docs/ci_v4/performance_budget_policy.json).

Every attack is its own test: a verdict may be SUCCESS only on complete, authentic evidence within budget; missing or forged evidence is
FAILURE (PERFORMANCE_UNVERIFIED), never PASS; PENDING exists only inside the budget window.
"""
import ast
import copy
import datetime as dt
import hashlib
import io
import json
import re
import zipfile
from pathlib import Path

import pytest
import yaml

from tools import ci_perf_guard as G

ROOT = Path(__file__).resolve().parents[1]
SHA = "a" * 40
T0 = dt.datetime(2026, 11, 18, 10, 0, 0, tzinfo=dt.timezone.utc)
POLICY = G.load_policy()
CI = POLICY["junit"]["workflow"]


def iso(minutes):
    return (T0 + dt.timedelta(minutes=minutes)).isoformat().replace("+00:00", "Z")


def shard_zip(index, cases, sha=SHA, modules=("tests/test_x.py",), exit_code=0, extra_xml=b""):
    xml = b'<?xml version="1.0"?>' + extra_xml + b"<testsuites><testsuite>" + b"".join(
        ('<testcase classname="%s" name="%s" time="%s"/>' % (c.rsplit("::", 1)[0][:-3].replace("/", "."), c.rsplit("::", 1)[1], t)).encode()
        for c, t in cases) + b"</testsuite></testsuites>"
    meta = {"sha": sha, "shard": index, "pytest_exit": exit_code, "modules": list(modules), "tree": "b" * 40}
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("junit-shard-%d.xml" % index, xml)
        z.writestr("shard-%d.json" % index, json.dumps(meta))
    return buf.getvalue()


class World:
    """A complete, valid evidence set for one head: six required runs, CI V4 PR with two shards."""

    def __init__(self):
        self.runs, self.jobs, self.artifacts, self.blobs = [], {}, {}, {}
        rid = 1000
        for w in POLICY["required_workflows"]:
            rid += 1
            self.runs.append({"id": rid, "name": w["name"], "path": w["path"], "head_sha": SHA, "event": "pull_request", "run_attempt": 1,
                              "status": "completed", "conclusion": "success", "created_at": iso(0)})
            self.jobs[rid] = [self.job(rid, "build", 1, 20)]
        self.ci = next(r for r in self.runs if r["name"] == CI)
        self.cases = {0: [("tests/test_x.py::test_a", 550.0), ("tests/test_x.py::test_b", 300.0)],
                      1: [("tests/test_x.py::test_c", 450.0)]}
        self.jobs[self.ci["id"]] = [self.job(self.ci["id"], "plan", 0, 1)]
        self.artifacts[self.ci["id"]] = []
        for i, cases in self.cases.items():
            secs = sum(t for _, t in cases)
            self.jobs[self.ci["id"]].append(self.job(self.ci["id"], "shard-%d" % i, 1, 2 + secs / 60.0 + 1, test_s=secs))
            self.put_artifact(i, shard_zip(i, cases))
        self.jobs[self.ci["id"]].append(self.job(self.ci["id"], "CI V4 gate", 25, 26))
        self.baseline = {n: t for cs in self.cases.values() for n, t in cs}

    def job(self, run_id, name, start, end, test_s=None, attempt=1):
        steps = []
        if test_s is not None:
            steps = [{"name": "Run the planned shard (selected modules only)", "started_at": iso(start + 1),
                      "completed_at": (T0 + dt.timedelta(minutes=start + 1, seconds=test_s)).isoformat().replace("+00:00", "Z")}]
        return {"id": hash((run_id, name)) & 0xffffff, "run_id": run_id, "head_sha": SHA, "run_attempt": attempt, "name": name,
                "status": "completed", "conclusion": "success", "started_at": iso(start), "completed_at": iso(end), "steps": steps}

    def put_artifact(self, i, blob, digest=None):
        aid = 5000 + i
        self.blobs[aid] = blob
        self.artifacts[self.ci["id"]] = [a for a in self.artifacts[self.ci["id"]] if a["name"] != "ci-v4-shard-%d" % i] + [{
            "id": aid, "name": "ci-v4-shard-%d" % i, "size_in_bytes": len(blob), "expired": False,
            "digest": digest or "sha256:" + hashlib.sha256(blob).hexdigest(), "workflow_run": {"id": self.ci["id"], "head_sha": SHA}}]

    def judge(self, minutes_now=40, policy=None, baseline=None):
        return G.evaluate(policy or POLICY, SHA, self.runs, self.jobs, self.artifacts, T0 + dt.timedelta(minutes=minutes_now),
                          self.baseline if baseline is None else baseline, lambda a: self.blobs[a["id"]])


@pytest.fixture
def w():
    return World()


def test_complete_authentic_evidence_within_budget_is_success(w):
    v = w.judge()
    assert v["state"] == "success", v
    assert v["details"]["nodes"] == 3 and v["details"]["end_to_end_s"] == 26 * 60 and len(v["description"]) <= 140


# ── terminal conditions: pending only inside the budget ─────────────────────────────────────────────────────────────────────────────
def test_missing_required_run_is_pending_inside_the_budget_and_failure_after_it(w):
    w.runs = [r for r in w.runs if r["name"] != "Protocol UI Browser Acceptance"]
    assert w.judge(minutes_now=30)["state"] == "pending"
    v = w.judge(minutes_now=41)
    assert v["state"] == "failure" and "OVER_BUDGET" in v["description"] and "Protocol UI Browser Acceptance" in v["description"]


def test_unfinished_run_is_pending_inside_the_budget_and_failure_after_it(w):
    w.runs[0].update(status="in_progress", conclusion=None)
    assert w.judge(minutes_now=39)["state"] == "pending"
    assert w.judge(minutes_now=40.5)["state"] == "failure"


def test_no_required_run_at_all_is_pending_without_a_start_time(w):
    w.runs = []
    v = w.judge()
    assert v["state"] == "pending" and "first_created_at" not in v["details"]


def test_a_renamed_copy_with_a_foreign_path_is_not_a_required_run(w):
    w.runs[0]["path"] = ".github/workflows/fake_fast_copy.yml"
    assert w.judge(minutes_now=45)["state"] == "failure"


def test_runs_of_another_head_or_event_are_ignored(w):
    for r in w.runs:
        if r["name"] == "Governance Full History":
            r["head_sha"] = "c" * 40
    assert "Governance Full History" in w.judge(minutes_now=45)["description"]
    w2 = World()
    w2.runs[1]["event"] = "workflow_dispatch"
    assert w2.judge(minutes_now=45)["state"] == "failure"


def test_failed_required_workflow_is_failure(w):
    w.runs[2]["conclusion"] = "failure"
    v = w.judge()
    assert v["state"] == "failure" and "REQUIRED_WORKFLOW_NOT_SUCCESS" in v["description"]


# ── end-to-end clock: GitHub timestamps, queue and every attempt included ──────────────────────────────────────────────────────────
def test_end_to_end_over_40_minutes_is_failure(w):
    w.jobs[w.ci["id"]][-1]["completed_at"] = iso(41)
    v = w.judge(minutes_now=50)
    assert v["state"] == "failure" and v["description"].startswith("OVER_BUDGET")


def test_queue_time_counts_from_the_first_run_creation(w):
    for r in w.runs:
        r["created_at"] = iso(-20)            # 20 minutes queued before anything started
    assert w.judge(minutes_now=50)["state"] == "failure"


def test_a_rerun_never_resets_the_clock(w):
    rerun = dict(w.ci, id=9999, run_attempt=1, created_at=iso(30))
    w.runs.append(rerun)                        # a second CI V4 PR run for the same head, created 30 min later
    w.jobs[9999] = [dict(j, run_id=9999, started_at=iso(31), completed_at=iso(45)) for j in w.jobs[w.ci["id"]]]
    w.artifacts[9999] = [dict(a, workflow_run={"id": 9999, "head_sha": SHA}) for a in w.artifacts[w.ci["id"]]]
    v = w.judge(minutes_now=50)
    assert v["state"] == "failure" and "OVER_BUDGET" in v["description"]


def test_jobs_of_another_attempt_or_run_are_unverified(w):
    w.jobs[w.ci["id"]][1]["run_attempt"] = 2
    assert "PERFORMANCE_UNVERIFIED" in w.judge()["description"]
    w2 = World()
    w2.jobs[w2.ci["id"]][1]["head_sha"] = "d" * 40
    assert "PERFORMANCE_UNVERIFIED" in w2.judge()["description"]


def test_skipped_jobs_do_not_extend_or_shorten_the_clock(w):
    w.jobs[w.ci["id"]].append(dict(w.jobs[w.ci["id"]][0], name="f01", conclusion="skipped", completed_at=iso(90)))
    assert w.judge()["state"] == "success"


def test_shard_job_over_the_shard_budget_is_failure(w):
    w.jobs[w.ci["id"]][1]["completed_at"] = iso(36)          # shard-0: 35 min (> 34) while end-to-end stays 37 min (< 40)
    w.jobs[w.ci["id"]][-1]["completed_at"] = iso(37)
    v = w.judge()
    assert v["details"]["end_to_end_s"] == 37 * 60
    assert v["state"] == "failure" and "SHARD_OVER_BUDGET" in v["description"]


# ── JUnit evidence is authenticated against GitHub, never trusted on its own ───────────────────────────────────────────────────────
def test_missing_shard_artifact_is_unverified(w):
    w.artifacts[w.ci["id"]] = [a for a in w.artifacts[w.ci["id"]] if a["name"] != "ci-v4-shard-1"]
    assert "PERFORMANCE_UNVERIFIED" in w.judge()["description"]


def test_artifact_bytes_not_matching_githubs_digest_are_unverified(w):
    w.put_artifact(0, shard_zip(0, w.cases[0]), digest="sha256:" + "0" * 64)
    assert "digest" in w.judge()["description"]


def test_artifact_of_another_run_or_head_is_unverified(w):
    w.artifacts[w.ci["id"]][0]["workflow_run"] = {"id": 1, "head_sha": SHA}
    assert "PERFORMANCE_UNVERIFIED" in w.judge()["description"]


def test_forged_faster_junit_disagrees_with_githubs_test_step(w):
    w.put_artifact(1, shard_zip(1, [("tests/test_x.py::test_c", 5.0)]))   # authentic digest of FORGED content written by PR code
    v = w.judge()
    assert v["state"] == "failure" and "disagrees with GitHub" in v["description"]


def test_inflated_junit_is_equally_unverified(w):
    w.put_artifact(1, shard_zip(1, [("tests/test_x.py::test_c", 2000.0)]))
    assert "disagrees with GitHub" in w.judge()["description"]


def test_duplicate_node_across_shards_is_unverified(w):
    cases = w.cases[1] + [("tests/test_x.py::test_a", 0.0)]
    w.put_artifact(1, shard_zip(1, cases))
    assert "twice" in w.judge()["description"]


def test_shard_metadata_for_another_head_or_failed_pytest_is_unverified(w):
    w.put_artifact(0, shard_zip(0, w.cases[0], sha="e" * 40))
    assert "another head" in w.judge()["description"]
    w2 = World()
    w2.put_artifact(0, shard_zip(0, w2.cases[0], exit_code=1))
    assert "pytest exit" in w2.judge()["description"]


def test_junit_with_a_dtd_or_entities_is_refused(w):
    w.put_artifact(0, shard_zip(0, w.cases[0], extra_xml=b'<!DOCTYPE x [<!ENTITY a "aaaa">]>'))
    assert "DTD" in w.judge()["description"]


def test_empty_or_corrupt_artifact_is_unverified(w):
    w.put_artifact(0, b"not a zip")
    assert w.judge()["state"] == "failure"


# ── per-node protection against slow tests ─────────────────────────────────────────────────────────────────────────────────────────
def _slow(w, seconds, node="tests/test_x.py::test_c"):
    w.cases[1] = [(node, seconds)]
    w.put_artifact(1, shard_zip(1, w.cases[1]))
    job = w.jobs[w.ci["id"]][2]
    job["steps"][0]["completed_at"] = (T0 + dt.timedelta(minutes=2, seconds=seconds)).isoformat().replace("+00:00", "Z")
    job["completed_at"] = (T0 + dt.timedelta(minutes=3, seconds=seconds)).isoformat().replace("+00:00", "Z")


def test_node_over_the_hard_limit_without_exception_is_failure(w):
    _slow(w, 700.0)
    w.baseline["tests/test_x.py::test_c"] = 690.0
    v = w.judge()
    assert v["state"] == "failure" and "NODE_OVER_LIMIT" in v["description"]


def test_exact_unexpired_exception_caps_a_known_heavy_node(w):
    p = copy.deepcopy(POLICY)
    p["exceptions"] = [{"node": "tests/test_x.py::test_c", "max_seconds": 1000, "expires": "2099-01-01", "reason": "r", "evidence": "e"}]
    _slow(w, 950.0)
    w.baseline["tests/test_x.py::test_c"] = 940.0
    assert w.judge(policy=p)["state"] == "success"
    _slow(w, 1050.0)
    w.baseline["tests/test_x.py::test_c"] = 1040.0
    assert "NODE_OVER_LIMIT" in w.judge(minutes_now=60, policy=p)["description"]


def test_expired_exception_no_longer_applies(w):
    p = copy.deepcopy(POLICY)
    p["exceptions"] = [{"node": "tests/test_x.py::test_c", "max_seconds": 1000, "expires": "2026-11-01", "reason": "r", "evidence": "e"}]
    _slow(w, 950.0)
    w.baseline["tests/test_x.py::test_c"] = 940.0
    assert "NODE_OVER_LIMIT" in w.judge(policy=p)["description"]


def test_regression_beyond_20_percent_and_120_seconds_is_failure(w):
    w.baseline["tests/test_x.py::test_c"] = 300.0          # 450 s now: +50 %, +150 s
    v = w.judge()
    assert v["state"] == "failure" and "NODE_REGRESSION" in v["description"]


def test_small_absolute_drift_is_not_a_regression(w):
    w.baseline["tests/test_x.py::test_b"] = 200.0          # 300 s now: +50 % but only +100 s
    assert w.judge()["state"] == "success"


def test_new_slow_node_without_a_trusted_baseline_is_failure(w):
    del w.baseline["tests/test_x.py::test_c"]
    v = w.judge()
    assert v["state"] == "failure" and "NODE_WITHOUT_BASELINE" in v["description"]


# ── policy and workflow invariants ─────────────────────────────────────────────────────────────────────────────────────────────────
def test_policy_cannot_raise_the_budget_or_hold_an_open_ended_exception():
    p = copy.deepcopy(POLICY)
    p["limits"]["end_to_end_seconds"] = 2401
    with pytest.raises(G.GuardError):
        G.validate_policy(p)
    p = copy.deepcopy(POLICY)
    p["exceptions"] = [{"node": "tests/test_x.py::test_c", "max_seconds": 1000, "reason": "r", "evidence": "e"}]
    with pytest.raises(G.GuardError):
        G.validate_policy(p)
    p = copy.deepcopy(POLICY)
    p["exceptions"] = [{"node": "tests/test_x.py", "max_seconds": 1000, "expires": "2099-01-01", "reason": "r", "evidence": "e"}]
    with pytest.raises(G.GuardError):
        G.validate_policy(p)


def test_the_repository_policy_is_the_40_minute_budget_with_one_exact_exception():
    assert POLICY["limits"]["end_to_end_seconds"] == 2400 and POLICY["limits"]["shard_job_seconds"] <= 2040
    assert POLICY["limits"]["node_fail_seconds"] == 600 and POLICY["limits"]["node_regression_fraction"] == 0.2
    assert [e["node"] for e in POLICY["exceptions"]] == [
        "tests/test_u1_scope.py::test_an_older_cohort_accepts_a_superseded_blob_only_through_the_exact_cohort"]


def test_required_workflows_exist_with_exact_names_and_run_on_every_pull_request():
    for wf in POLICY["required_workflows"]:
        doc = yaml.safe_load((ROOT / wf["path"]).read_text())
        assert doc["name"] == wf["name"], wf
        on = doc.get("on", doc.get(True))
        assert "pull_request" in on and not (isinstance(on["pull_request"], dict) and ("paths" in on["pull_request"]
                                                                                       or "paths-ignore" in on["pull_request"])), wf


def test_guard_workflow_runs_only_trusted_default_branch_code_with_least_privilege():
    text = (ROOT / ".github/workflows/ci_perf_guard.yml").read_text()
    doc = yaml.safe_load(text)
    on = doc.get("on", doc.get(True))
    assert set(on) == {"workflow_run", "schedule"}
    assert sorted(on["workflow_run"]["workflows"]) == sorted(w["name"] for w in POLICY["required_workflows"])
    assert on["workflow_run"]["types"] == ["completed"]
    assert doc["permissions"] == {}
    job = doc["jobs"]["judge"]
    assert job["permissions"] == {"actions": "read", "contents": "read", "pull-requests": "read", "statuses": "write"}
    assert 0 < job["timeout-minutes"] <= 10
    checkout = [s for s in job["steps"] if str(s.get("uses", "")).startswith("actions/checkout@")]
    assert len(checkout) == 1 and checkout[0]["with"] == {"ref": "${{ github.sha }}", "persist-credentials": False}
    assert "head_sha }}" not in json.dumps(checkout) and "pull_request_target" not in text and "head.ref" not in text
    assert re.search(r"test \"\$REF\" = \"\$DEFAULT\"", text)
    for s in job["steps"]:
        if "run" in s and "ci_perf_guard" in s["run"]:
            assert s["run"].startswith("python -I tools/ci_perf_guard.py ")


def test_the_guard_never_waits_polls_or_imports_repository_code():
    tree = ast.parse((ROOT / "tools/ci_perf_guard.py").read_text())
    names = {n.attr if isinstance(n, ast.Attribute) else getattr(n, "id", None) for n in ast.walk(tree)}
    assert "sleep" not in names and "subprocess" not in names and "exec" not in names and "eval" not in names
    imported = {a.name.split(".")[0] for n in ast.walk(tree) if isinstance(n, (ast.Import, ast.ImportFrom))
                for a in (n.names if isinstance(n, ast.Import) else [ast.alias(n.module or "")])}
    assert imported <= {"__future__", "argparse", "datetime", "hashlib", "io", "json", "os", "re", "sys", "urllib", "xml", "zipfile", "pathlib"}


def test_descriptions_fit_a_commit_status():
    w = World()
    w.runs = w.runs[:1]
    assert len(w.judge(minutes_now=45)["description"]) <= 140


def test_the_repository_baseline_is_one_authenticated_hosted_run_and_not_the_frozen_node_weights():
    assert POLICY["baseline"]["file"] == "docs/ci_v4/performance_baseline.json"
    b = json.loads((ROOT / POLICY["baseline"]["file"]).read_text())
    assert b["schema"] == "FINCO_CI_PERFORMANCE_BASELINE_V1" and b["source"]["run_id"] == 44147228493
    assert b["source"]["head_sha"] == "ac84868ece17122b5a03e78b00dbd6f79b3e1869"
    assert [a["artifact_sha256"] for a in b["source"]["artifacts"]] == [
        "be50fb829d265e7f57b044b5556f1b51e14af3cfff53891a5f0b1277b0648e7c", "40004f31d3c12ad84bdb7d40b361f3cd6268fdc271609a87e995f39a4688b983",
        "cb555d74d72564f768c722f8199de0daa52f3806dc017b0cb816ad975cac2f2e"]
    assert len(b["nodes"]) == sum(a["testcases"] for a in b["source"]["artifacts"]) == 2284
    caps = {e["node"]: e["max_seconds"] for e in POLICY["exceptions"]}
    over = {n: t for n, t in b["nodes"].items() if t > caps.get(n, POLICY["limits"]["node_fail_seconds"])}
    assert over == {}, over
    assert G.load_baseline(ROOT / POLICY["baseline"]["file"]) == {k: float(v) for k, v in b["nodes"].items()}
