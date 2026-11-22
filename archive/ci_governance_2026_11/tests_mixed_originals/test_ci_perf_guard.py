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
            self.jobs[rid] = [self.job(rid, G.MANDATORY_JOBS[w["name"]], 1, 20)]
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
            steps = [{"name": "Run the planned shard (selected modules only)", "status": "completed", "conclusion": "success", "started_at": iso(start + 1),
                      "completed_at": (T0 + dt.timedelta(minutes=start + 1, seconds=test_s)).isoformat().replace("+00:00", "Z")}]
        return {"id": hash((run_id, name)) & 0xffffff, "run_id": run_id, "head_sha": SHA, "run_attempt": attempt, "name": name,
                "status": "completed", "conclusion": "success", "started_at": iso(start), "completed_at": iso(end), "steps": steps}

    def put_artifact(self, i, blob, digest=None):
        aid = 5000 + i
        self.blobs[aid] = blob
        job = next(j for j in self.jobs[self.ci["id"]] if j["name"] == f"shard-{i}")
        self.artifacts[self.ci["id"]] = [a for a in self.artifacts[self.ci["id"]] if a["name"] != "ci-v4-shard-%d" % i] + [{
            "id": aid, "name": "ci-v4-shard-%d" % i, "size_in_bytes": len(blob), "expired": False,
            "created_at": job["completed_at"],
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
    job = w.jobs[w.ci["id"]][2]
    job["steps"][0]["completed_at"] = (T0 + dt.timedelta(minutes=2, seconds=seconds)).isoformat().replace("+00:00", "Z")
    job["completed_at"] = (T0 + dt.timedelta(minutes=3, seconds=seconds)).isoformat().replace("+00:00", "Z")
    w.put_artifact(1, shard_zip(1, w.cases[1]))


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


def test_the_repository_policy_is_the_40_minute_budget_with_no_node_exception():
    assert POLICY["limits"]["end_to_end_seconds"] == 2400 and POLICY["limits"]["shard_job_seconds"] <= 2040
    assert POLICY["limits"]["node_fail_seconds"] == 600 and POLICY["limits"]["node_regression_fraction"] == 0.2
    # the former U1 waiver (976.9 s, run 44147228493) is retired: the node measured 80.8 s on run 44269408688 (#458 head 8726d206)
    assert POLICY["exceptions"] == []


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
    assert set(on) == {"workflow_run", "schedule", "workflow_dispatch"}
    assert on["workflow_dispatch"] is None
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
    sweep = next(s for s in job["steps"] if s.get("run") == "python -I tools/ci_perf_guard.py sweep")
    assert sweep["if"] == "github.event_name == 'schedule' || github.event_name == 'workflow_dispatch'"
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


def test_the_repository_baseline_is_two_authenticated_hosted_runs_and_not_the_frozen_node_weights():
    assert POLICY["baseline"]["file"] == "docs/ci_v4/performance_baseline.json"
    b = json.loads((ROOT / POLICY["baseline"]["file"]).read_text())
    assert b["schema"] == "FINCO_CI_PERFORMANCE_BASELINE_V1" and "source" not in b
    assert [(s["run_id"], s["head_sha"]) for s in b["sources"]] == [
        (44147228493, "ac84868ece17122b5a03e78b00dbd6f79b3e1869"), (44269408688, "8726d20616be097d95eb3289905679a19c2a0e62")]
    assert [[a["artifact_sha256"] for a in s["artifacts"]] for s in b["sources"]] == [
        ["be50fb829d265e7f57b044b5556f1b51e14af3cfff53891a5f0b1277b0648e7c", "40004f31d3c12ad84bdb7d40b361f3cd6268fdc271609a87e995f39a4688b983",
         "cb555d74d72564f768c722f8199de0daa52f3806dc017b0cb816ad975cac2f2e"],
        ["0aaec754842a20151aa6ddf6c344385bbcdc7b4032b4d914f70dfc2c5d56d857", "0e5595710a193f6193250b2b2ef2e2ae8a968bf10ef67bb4e79e8ad4552a9f30",
         "2d958b559252cb9e135a3b2ec93c5abaa0970a95921aedbaa17883723ddf5936"]]
    assert [sum(a["testcases"] for a in s["artifacts"]) for s in b["sources"]] == [2284, 1903]
    assert len(b["nodes"]) == 2433                         # union; a node measured by the later run carries the later value
    assert b["nodes"]["tests/test_u1_scope.py::test_an_older_cohort_accepts_a_superseded_blob_only_through_the_exact_cohort"] < 120
    caps = {e["node"]: e["max_seconds"] for e in POLICY["exceptions"]}
    over = {n: t for n, t in b["nodes"].items() if t > caps.get(n, POLICY["limits"]["node_fail_seconds"])}
    assert over == {}, over
    assert G.load_baseline(ROOT / POLICY["baseline"]["file"]) == {k: float(v) for k, v in b["nodes"].items()}


# ── Correction A: public-safety reconciliation of the measured node ids ────────────────────────────────────────────────────────────
AT = chr(64)
DECORATOR_IDS = (
    'tests/test_rc7b_quarterly_csrf_successor.py::test_no_extra_content_route_writer_or_run[\\n' + AT + 'router.post("/extra")\\n'
    'async def extra():\\n    return None\\n]',
    'tests/test_rc7b_quarterly_csrf_successor.py::test_security_and_route_mutations_fail_with_or_without_byte_check['
    + AT + 'router.post("/workbook/calendar/operating-frequency")-' + AT + 'router.get("/workbook/calendar/operating-frequency")]',
)
MEASURED = ("docs/ci_v4/node_weights.json", "docs/ci_v4/performance_baseline.json")


@pytest.mark.parametrize("rel", MEASURED)
def test_the_measured_node_files_pass_the_unchanged_public_safety_scanner_raw(rel):
    from tools import public_safety_scan as P
    raw = (ROOT / rel).read_bytes()
    assert AT.encode() not in raw and P.scan_file(rel, ROOT) == []


@pytest.mark.parametrize("rel", MEASURED)
def test_the_escaped_files_decode_to_the_exact_hosted_node_ids(rel):
    data = json.loads((ROOT / rel).read_text())
    nodes = data["nodes"] if "nodes" in data else data
    # the two decorator-parametrised ids (hosted JUnit of CI V4 PR run 44147228493, shard artifact sha256 cb555d74...) survive byte-exact
    assert all(n in nodes for n in DECORATOR_IDS)
    assert sum(AT in n for n in nodes) == len(DECORATOR_IDS)
    # JSON escaping is the only change: re-escaping the decoded object reproduces the committed bytes
    canonical = json.dumps(data, indent=1, sort_keys=True) + "\n"
    assert canonical.replace(AT, "\\u0040").encode() == (ROOT / rel).read_bytes()


def test_a_real_email_like_identifier_still_fails_the_unchanged_scanner(tmp_path):
    from tools import public_safety_scan as P
    assert P.EMAIL_RE.pattern == rb"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"
    leak = ("someone.private" + AT + "finco-internal.org").encode()
    (tmp_path / "x.json").write_bytes(b'{"owner": "' + leak + b'"}')
    assert P.scan_file("x.json", tmp_path) != []
    # escaping is NOT a bypass for a real address in a JSON string value of these files: the guarded tests above pin the exact count
    escaped = leak.replace(AT.encode(), b"\\u0040")
    assert json.loads(b'{"owner": "' + escaped + b'"}')["owner"].encode() == leak


# ── Correction A: guard security review (each finding is one attack) ──────────────────────────────────────────────────────────────
def test_a_required_run_created_in_the_future_is_unverified_not_pending(w):
    for r in w.runs:                                   # the clock starts at the EARLIEST creation, so every run is in the future
        r["created_at"] = iso(60)
    v = w.judge(minutes_now=10)
    assert v["state"] == "failure" and "created in the future" in v["description"]


def test_a_job_finishing_before_it_starts_or_in_the_future_is_unverified(w):
    j = w.jobs[w.runs[0]["id"]][0]
    j["completed_at"], j["started_at"] = iso(1), iso(5)
    assert "inconsistent timestamps" in w.judge()["description"]
    w2 = World()
    w2.jobs[w2.runs[0]["id"]][0]["completed_at"] = iso(200)
    assert "inconsistent timestamps" in w2.judge(minutes_now=40)["description"]


def test_a_job_started_before_the_first_run_was_created_is_unverified(w):
    w.jobs[w.runs[0]["id"]][0]["started_at"] = iso(-30)
    assert "inconsistent timestamps" in w.judge()["description"]


def test_a_cancelled_newest_run_is_failure_and_an_older_duplicate_never_shortens_the_clock(w):
    old = dict(w.ci, id=1, created_at=iso(-20), status="completed", conclusion="success")
    w.runs.append(old)
    v = w.judge(minutes_now=40)
    assert v["details"]["first_created_at"].startswith((T0 - dt.timedelta(minutes=20)).isoformat()[:16])   # older duplicate: earlier start
    assert v["state"] == "failure" and "OVER_BUDGET" in v["description"]                                     # 26 + 20 > 40 min
    w2 = World()
    w2.runs.append(dict(w2.ci, id=99999, created_at=iso(1), conclusion="cancelled"))
    assert "REQUIRED_WORKFLOW_NOT_SUCCESS" in w2.judge()["description"]


def _zip(members):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as z:
        for name, data in members:
            z.writestr(name, data)
    return buf.getvalue()


def test_a_shard_zip_with_duplicate_members_is_unverified(w):
    good = zipfile.ZipFile(io.BytesIO(w.blobs[5000]))
    members = [(n, good.read(n)) for n in good.namelist()]
    import warnings
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        w.put_artifact(0, _zip(members + [("junit-shard-0.xml", b"<testsuites/>")]))
    assert "duplicate member" in w.judge()["description"]


def test_a_shard_zip_with_an_encrypted_member_is_unverified(w):
    blob = bytearray(w.blobs[5000])
    # set the "encrypted" general-purpose flag on every local and central header (the bytes stay otherwise intact)
    for sig, off in ((b"PK\x03\x04", 6), (b"PK\x01\x02", 8)):
        i = blob.find(sig)
        while i >= 0:
            blob[i + off] |= 0x1
            i = blob.find(sig, i + 4)
    w.put_artifact(0, bytes(blob))
    assert "encrypted member" in w.judge()["description"]


def test_zip_slip_member_names_are_never_extracted_and_a_bomb_is_capped(w):
    src = (ROOT / "tools/ci_perf_guard.py").read_text()
    assert "extract" not in src and "open(" not in src.split("def _read_shard", 1)[1].split("\ndef ", 1)[0]
    cfg = dict(POLICY["junit"], max_member_bytes=1000)
    bomb = _zip([("junit-shard-0.xml", b"<testsuites>" + b" " * 10_000_000 + b"</testsuites>"), ("shard-0.json", b"{}"),
                 ("../../etc/passwd", b"x")])
    assert len(bomb) < 100_000
    with pytest.raises(G.GuardError, match="too large"):
        G._read_shard(bomb, 0, cfg)


class _Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class _Opener:
    def __init__(self, body=b"{}", exc=None):
        self.body, self.exc, self.seen = body, exc, []

    def open(self, req, timeout=None):
        self.seen.append(req)
        if self.exc:
            raise self.exc
        return _Resp(self.body)


def _http_error(code, headers=None):
    import email.message
    import urllib.error
    m = email.message.Message()
    for k, v in (headers or {}).items():
        m[k] = v
    return urllib.error.HTTPError("https://api.github.com/x", code, "x", m, None)


@pytest.mark.parametrize("code,headers,kind", [
    (429, {}, "TransientError"), (500, {}, "TransientError"), (502, {}, "TransientError"),
    (403, {"X-RateLimit-Remaining": "0"}, "TransientError"), (403, {"Retry-After": "60"}, "TransientError"),
    (403, {}, "GuardError"), (404, {}, "GuardError"), (410, {}, "GuardError"), (401, {}, "GuardError")])
def test_api_failures_are_transient_only_when_retryable_and_never_success(code, headers, kind):
    gh = G.GitHub("o/r", "t", opener=_Opener(exc=_http_error(code, headers)))
    with pytest.raises(getattr(G, kind)):
        gh.runs_for(SHA)


def test_a_network_failure_is_transient():
    import urllib.error
    gh = G.GitHub("o/r", "t", opener=_Opener(exc=urllib.error.URLError("down")))
    with pytest.raises(G.TransientError):
        gh.open_pull_heads()


def test_an_oversized_api_response_or_artifact_download_is_refused():
    gh = G.GitHub("o/r", "t", opener=_Opener(body=b"x" * 2048))
    with pytest.raises(G.GuardError, match="larger than"):
        gh.download({"id": 1}, limit=1024)


def test_only_api_paths_are_requested_and_the_token_never_follows_a_cross_host_redirect():
    import urllib.request
    gh = G.GitHub("o/r", "t", opener=_Opener())
    with pytest.raises(G.GuardError):
        gh._req("GET", "https://evil.example/steal")
    h = G._NoCredentialRedirect()
    req = urllib.request.Request("https://api.github.com/repos/o/r/actions/artifacts/1/zip", headers={"Authorization": "Bearer t"})
    new = h.redirect_request(req, None, 302, "Found", {}, "https://blob.store.example/signed?sig=1")
    assert all(k.lower() != "authorization" for k in new.headers) and "Authorization" not in new.unredirected_hdrs
    same = h.redirect_request(req, None, 302, "Found", {}, "https://api.github.com/other")
    assert any(k.lower() == "authorization" for k in same.headers)


class _FakeGH:
    """main() against a fake API: records written statuses."""

    def __init__(self, heads, status=None, verdict=None, transient_on=None):
        self.repo, self.heads, self.cur, self.written, self.verdict, self.transient_on = "o/r", heads, status, [], verdict, transient_on

    def open_pull_heads(self):
        if self.transient_on == "pulls":
            raise G.TransientError("429")
        return list(self.heads)

    def status(self, sha, ctx):
        return self.cur

    def set_status(self, sha, state, desc, ctx, url):
        if self.transient_on == "status":
            raise G.TransientError("503")
        self.written.append((sha, state, desc))


def _run_main(monkeypatch, tmp_path, fake, mode, head=SHA, verdict=None):
    monkeypatch.setenv("GITHUB_REPOSITORY", "o/r")
    monkeypatch.setenv("GH_TOKEN", "t")
    monkeypatch.setattr(G, "GitHub", lambda repo, token: fake)
    monkeypatch.setattr(G, "judge", verdict or (lambda gh, p, sha, now, b: G._verdict("success", "ok", {"first_created_at": "x"})))
    ev = tmp_path / "event.json"
    ev.write_text(json.dumps({"workflow_run": {"event": "pull_request", "head_sha": head}}))
    return G.main([mode, "--event-path", str(ev), "--summary", str(tmp_path / "summary.md")])


def test_an_event_for_a_head_that_is_not_an_open_pull_requests_current_head_writes_nothing(monkeypatch, tmp_path):
    fake = _FakeGH(heads=["b" * 40])
    assert _run_main(monkeypatch, tmp_path, fake, "event") == 0 and fake.written == []
    fake2 = _FakeGH(heads=[SHA])
    _run_main(monkeypatch, tmp_path, fake2, "event")
    assert fake2.written == [(SHA, "success", "ok")]


def test_the_sweep_reverifies_success_written_by_anyone_and_keeps_failure_terminal(monkeypatch, tmp_path):
    spoof = _FakeGH(heads=[SHA], status={"state": "success"})
    _run_main(monkeypatch, tmp_path, spoof, "sweep",
              verdict=lambda gh, p, sha, now, b: G._verdict("failure", "OVER_BUDGET: real", {"first_created_at": "x"}))
    assert spoof.written == [(SHA, "failure", "OVER_BUDGET: real")]
    done = _FakeGH(heads=[SHA], status={"state": "failure"})
    _run_main(monkeypatch, tmp_path, done, "sweep")
    assert done.written == []


def test_a_transient_api_failure_writes_no_status_and_fails_the_guard_run_visibly(monkeypatch, tmp_path):
    fake = _FakeGH(heads=[SHA])

    def boom(gh, p, sha, now, b):
        raise G.TransientError("GitHub API 429 (retry later)")
    assert _run_main(monkeypatch, tmp_path, fake, "sweep", verdict=boom) == 1 and fake.written == []
    assert _run_main(monkeypatch, tmp_path, _FakeGH(heads=[SHA], transient_on="pulls"), "event") == 1
    assert _run_main(monkeypatch, tmp_path, _FakeGH(heads=[SHA], transient_on="status"), "sweep") == 1


def test_a_permanent_api_failure_is_failure_never_success(monkeypatch, tmp_path):
    fake = _FakeGH(heads=[SHA])

    def gone(gh, p, sha, now, b):
        raise G.GuardError("GitHub API 404")
    _run_main(monkeypatch, tmp_path, fake, "event", verdict=gone)
    assert fake.written == [(SHA, "failure", "PERFORMANCE_UNVERIFIED: GitHub API 404")]


def test_untrusted_node_ids_cannot_break_out_of_the_run_summary(monkeypatch, tmp_path):
    fake = _FakeGH(heads=[SHA])
    _run_main(monkeypatch, tmp_path, fake, "event", verdict=lambda gh, p, sha, now, b: G._verdict(
        "failure", "NODE_OVER_LIMIT x```\n# injected", {"first_created_at": "x", "top20": [["a```b", 1]]}))
    text = (tmp_path / "summary.md").read_text()
    assert text.count("```") == 2


# ── Correction B: pagination truncation and symlink members ────────────────────────────────────────────────────────────────────────
class _PagedOpener:
    """Serves list pages: ``pages`` is a list of item lists; ``total`` is GitHub's total_count (None: omitted)."""

    def __init__(self, key, pages, total=None):
        self.key, self.pages, self.total, self.seen = key, pages, total, []

    def open(self, req, timeout=None):
        import urllib.parse
        q = urllib.parse.parse_qs(urllib.parse.urlsplit(req.full_url).query)
        page = int(q["page"][0])
        self.seen.append(page)
        items = self.pages[page - 1] if page <= len(self.pages) else []
        body = {self.key: items}
        if self.total is not None:
            body["total_count"] = self.total
        return _Resp(json.dumps(body).encode())


def test_a_job_list_shorter_than_githubs_total_count_is_unverified_never_a_shorter_clock():
    jobs = [{"id": i} for i in range(100)]
    gh = G.GitHub("o/r", "t", opener=_PagedOpener("jobs", [jobs, jobs[:5]], total=180))
    with pytest.raises(G.GuardError, match="incomplete"):
        gh.jobs_for({"id": 1, "run_attempt": 1})
    ok = G.GitHub("o/r", "t", opener=_PagedOpener("jobs", [jobs, jobs[:5]], total=105))
    assert len(ok.jobs_for({"id": 1, "run_attempt": 1})) == 105


def test_a_list_that_hits_the_page_cap_is_truncated_and_refused():
    full = [{"id": i} for i in range(100)]
    gh = G.GitHub("o/r", "t", opener=_PagedOpener("workflow_runs", [full] * 25))
    with pytest.raises(G.GuardError, match="truncated"):
        gh.runs_for(SHA)
    pulls = G.GitHub("o/r", "t", opener=_PagedOpener("unused", []))
    pulls._req = lambda method, path, **k: [{"head": {"sha": SHA}}] * 100
    with pytest.raises(G.GuardError, match="truncated"):
        pulls.open_pull_heads()


def test_a_shard_zip_with_a_symlink_member_is_unverified(w):
    good = zipfile.ZipFile(io.BytesIO(w.blobs[5000]))
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for n in good.namelist():
            info = zipfile.ZipInfo(n)
            if n.startswith("junit"):
                info.external_attr = (0o120777 << 16)
                z.writestr(info, b"/etc/passwd")
            else:
                z.writestr(info, good.read(n))
    w.put_artifact(0, buf.getvalue())
    assert "symlink member" in w.judge()["description"]


def full_run_timestamps():
    return {"run_attempt": 1, "created_at": iso(0), "run_started_at": iso(1), "updated_at": iso(45)}


def full_jobs_fixture(run, seconds=2399):
    def stamp(s):
        return iso(s / 60)

    phases = [("plan", 70, 120), ("recollect", 130, 200), ("f01 / f01", 65, 2050)]
    phases += [("shard-%d" % i, 125, 2180) for i in range(8)]
    phases += [("record", 2200, seconds)]
    return [{"id": i, "name": name, "run_id": run["id"], "run_attempt": 1, "head_sha": run["head_sha"],
             "head_branch": "main", "workflow_name": "CI V4 FULL", "status": "completed", "conclusion": "success",
             "started_at": stamp(start), "completed_at": stamp(end)}
            for i, (name, start, end) in enumerate(phases, 1)]


@pytest.mark.parametrize("seconds,state,target", [(2100, "success", "TARGET_MET"),
    (2101, "success", "TARGET_WARNING"), (2400, "success", "TARGET_WARNING"), (2401, "failure", "TARGET_WARNING")])
def test_operational_target_does_not_change_the_hard_pr_limit(w, seconds, state, target):
    w.jobs[w.ci["id"]][-1]["completed_at"] = iso(seconds / 60)
    verdict = w.judge(minutes_now=41)
    assert verdict["state"] == state
    assert verdict["details"]["target_state"] == target
    assert verdict["details"]["trend"] == "TREND_UNVERIFIED"


@pytest.mark.parametrize("conclusion", ["skipped", "neutral", "cancelled", None])
def test_green_workflow_does_not_mask_a_mandatory_job(w, conclusion):
    other = next(run for run in w.runs if run["name"] != CI)
    w.jobs[other["id"]][0]["conclusion"] = conclusion
    assert "mandatory job" in w.judge()["description"]


@pytest.mark.parametrize("change", ["drop", "duplicate", "attempt", "sha", "skipped", "ordering", "timezone", "missing"])
def test_full_runtime_requires_complete_ordered_same_attempt_jobs(change):
    run = {"id": 77, "head_sha": SHA, **full_run_timestamps()}
    jobs = full_jobs_fixture(run)
    if change == "drop":
        jobs.pop(3)
    elif change == "duplicate":
        jobs[3]["id"] = jobs[2]["id"]
    elif change == "attempt":
        jobs[3]["run_attempt"] = 2
    elif change == "sha":
        jobs[3]["head_sha"] = "b" * 40
    elif change == "skipped":
        jobs[3]["conclusion"] = "skipped"
    elif change == "ordering":
        jobs[-1]["started_at"] = iso(3)
    elif change == "timezone":
        jobs[-1]["completed_at"] = "2026-11-18T10:39:59"
    else:
        del run["created_at"]
    with pytest.raises(G.GuardError, match="FULL_RUNTIME_UNVERIFIED"):
        G.verify_full_runtime(run, jobs)


@pytest.mark.parametrize("response", [{"jobs": []}, {"jobs": [], "total_count": 1}])
def test_full_jobs_requires_complete_api_pagination(monkeypatch, response):
    gh = G.GitHub("owner/repo", "unused")
    monkeypatch.setattr(gh, "_req", lambda method, path: response)
    with pytest.raises(G.GuardError, match="total_count|incomplete"):
        gh.full_jobs({"id": 77, "run_attempt": 1})


@pytest.mark.parametrize("variant", ["good", "other_head", "wrong_producer", "pending", "stale", "budget_failed"])
def test_v5_deferral_consumes_commit_status_and_rechecks_the_budget(monkeypatch, variant):
    gh = G.GitHub("owner/repo", "unused")
    base = "b" * 40
    status = {"sha": SHA, "statuses": [{"context": G.PERFORMANCE_CONTEXT, "state": "success", "created_at": iso(30),
               "target_url": "https://github.com/owner/repo/actions/runs/9"}]}
    run = {"id": 9, "path": ".github/workflows/ci_perf_guard.yml", "head_branch": "main", "head_sha": base,
           "event": "workflow_run", "status": "completed", "conclusion": "success", "created_at": iso(29), "updated_at": iso(32),
           "repository": {"full_name": gh.repo}, "head_repository": {"full_name": gh.repo}}
    if variant == "other_head":
        status["sha"] = base
    if variant == "wrong_producer":
        run["path"] = ".github/workflows/lookalike.yml"
    if variant == "pending":
        status["statuses"][0]["state"] = "pending"
    if variant == "stale":
        status["statuses"][0]["created_at"] = iso(28)
    def get(_method, path):
        return run if path.endswith("/runs/9") else status
    monkeypatch.setattr(gh, "_req", get)
    verdict = {"state": "success", "details": {"end_to_end_s": 1200, "first_created_at": iso(0)}}
    if variant == "budget_failed":
        verdict = {"state": "failure", "description": "OVER_BUDGET"}
    monkeypatch.setattr(G, "judge", lambda *a: verdict)
    ok, findings = G.verify_budget_for_deferral(gh, SHA, base, T0 + dt.timedelta(minutes=45))
    assert ok == (variant == "good") and bool(findings) != ok


def test_skipped_planned_shard_cannot_hide_its_missing_artifact(w):
    shard = next(job for job in w.jobs[w.ci["id"]] if job["name"] == "shard-1")
    shard["conclusion"] = "skipped"
    w.artifacts[w.ci["id"]] = w.artifacts[w.ci["id"]][:1]
    assert "unsuccessful planned shard 1" in w.judge()["description"]


def test_authentic_but_old_junit_cannot_satisfy_a_new_attempt(w):
    w.ci["run_attempt"] = 2
    for job in w.jobs[w.ci["id"]]:
        job["run_attempt"] = 2
    w.artifacts[w.ci["id"]][0]["created_at"] = iso(0.5)
    verdict = w.judge()
    assert verdict["state"] == "failure"
    assert "latest attempt" in verdict["description"]
