"""Release gate: FULL PASS on the identical SHA/tree, verified against the GitHub run; every gap blocks."""
import copy
import datetime as dt
import hashlib
import json
from pathlib import Path

import pytest

from tools import ci_v4_release_gate as G

ROOT = Path(__file__).resolve().parents[1]
POLICY = json.loads((ROOT / "docs/ci_v4/ci-v4-policy.json").read_text())
SLUG = "Finco-Protocol/FincoProtocol"
SHA, TREE = "1" * 40, "2" * 40
N = POLICY["release_gate"]["full_min_collected_nodes"]


@pytest.fixture()
def junit(tmp_path):
    p = tmp_path / "results.xml"
    p.write_text("<testsuite>" + "".join("<testcase classname='tests.test_s' name='t%d'/>" % i for i in range(N)) + "</testsuite>")
    return p


def _record(junit, **over):
    r = {"schema": "FINCO_CI_V4_FULL_RECORD_V1", "tier": "full", "tested_sha": SHA, "tested_tree": TREE, "conclusion": "pass",
         "run_id": 77, "run_attempt": 1, "finished_at": dt.datetime.now(dt.timezone.utc).isoformat(), "collected_nodes": N,
         "executed_nodes": N, "counts": {"passed": N, "failed": 0, "error": 0, "skipped": 0}, "skipped_ids": [],
         "plan_digest": "x", "junit_sha256": [hashlib.sha256(junit.read_bytes()).hexdigest()]}
    r.update(over)
    return r


def _run(**over):
    r = {"id": 77, "head_sha": SHA, "status": "completed", "conclusion": "success", "path": ".github/workflows/ci_v4_full.yml",
         "event": "workflow_dispatch", "run_attempt": 1, "repository": {"full_name": SLUG}, "head_repository": {"full_name": SLUG}}
    r.update(over)
    return r


def test_exact_full_pass_allows_release(junit):
    out = G.gate(_record(junit), _run(), [junit], SHA, TREE, SLUG, POLICY)
    assert out["verdict"] == "RELEASE_ALLOWED"


def _skip_junit(tmp_path, skipped):
    p = tmp_path / "skips.xml"
    rows = ["<testcase classname='%s' name='%s'><skipped/></testcase>" % tuple(s.split("::")) for s in skipped]
    rows += ["<testcase classname='tests.test_s' name='t%d'/>" % i for i in range(N - len(skipped))]
    p.write_text("<testsuite>" + "".join(rows) + "</testsuite>")
    return p


def test_reviewed_baseline_skips_are_listed_and_allowed_but_new_or_extra_skips_block(tmp_path):
    baseline = json.loads((ROOT / POLICY["release_gate"]["skip_baseline"]).read_text())["skipped_nodes"]
    assert sum(baseline.values()) == 603
    node = sorted(baseline)[0]
    j = _skip_junit(tmp_path, [node])
    rec = _record(j, counts={"passed": N - 1, "failed": 0, "error": 0, "skipped": 1}, skipped_ids=[node])
    assert G.gate(rec, _run(), [j], SHA, TREE, SLUG, POLICY, baseline)["skipped_ids"] == [node]
    with pytest.raises(G.GateError, match="baseline"):                       # same skip without the reviewed baseline
        G.gate(rec, _run(), [j], SHA, TREE, SLUG, POLICY, {})
    over = [node] * (baseline[node] + 1)                                     # more occurrences than reviewed
    j2 = _skip_junit(tmp_path, over)
    rec2 = _record(j2, counts={"passed": N - len(over), "failed": 0, "error": 0, "skipped": len(over)}, skipped_ids=over)
    with pytest.raises(G.GateError, match="baseline"):
        G.gate(rec2, _run(), [j2], SHA, TREE, SLUG, POLICY, baseline)


@pytest.mark.parametrize("over,msg", [
    ({"tested_sha": "3" * 40}, "different sha"),
    ({"tested_tree": "4" * 40}, "tree"),
    ({"conclusion": "fail"}, "did not pass"),
    ({"tier": "risk"}, "not a FULL"),
    ({"collected_nodes": 100, "executed_nodes": 100}, "floor"),
    ({"counts": {"passed": N - 1, "failed": 1, "error": 0, "skipped": 0}}, "failures"),
    ({"counts": {"passed": N - 1, "failed": 0, "error": 0, "skipped": 1}, "skipped_ids": ["x"]}, "baseline"),
    ({"junit_sha256": ["0" * 64]}, "digests"),
    ({"finished_at": "2020-01-01T00:00:00+00:00"}, "older"),
    ({"schema": "SOMETHING_ELSE"}, "not a CI V4"),
])
def test_record_negatives_block(junit, over, msg):
    with pytest.raises(G.GateError, match=msg):
        G.gate(_record(junit, **over), _run(), [junit], SHA, TREE, SLUG, POLICY)


@pytest.mark.parametrize("over", [
    {"head_sha": "3" * 40}, {"conclusion": "failure"}, {"status": "in_progress"}, {"path": ".github/workflows/ci_v4_pr.yml"},
    {"event": "pull_request"}, {"repository": {"full_name": "evil/fork"}}, {"head_repository": {"full_name": "evil/fork"}},
    {"id": 78}, {"run_attempt": 2},
])
def test_forged_or_wrong_run_blocks(junit, over):
    with pytest.raises(G.GateError):
        G.gate(_record(junit), _run(**over), [junit], SHA, TREE, SLUG, POLICY)


def test_record_counts_contradicted_by_junit_block(junit, tmp_path):
    other = tmp_path / "other.xml"
    other.write_text("<testsuite><testcase classname='a' name='b'><failure/></testcase></testsuite>")
    rec = _record(junit, junit_sha256=sorted([hashlib.sha256(junit.read_bytes()).hexdigest(), hashlib.sha256(other.read_bytes()).hexdigest()]))
    with pytest.raises(G.GateError):
        G.gate(rec, _run(), [junit, other], SHA, TREE, SLUG, POLICY)


def test_short_sha_or_branch_name_is_refused(junit):
    with pytest.raises(G.GateError):
        G.gate(_record(junit, tested_sha="main"), _run(head_sha="main"), [junit], "main", TREE, SLUG, POLICY)


def test_cli_blocks_without_github_verification(junit, tmp_path, monkeypatch):
    rec = tmp_path / "rec.json"; rec.write_text(json.dumps(_record(junit)))
    monkeypatch.delenv("GH_TOKEN", raising=False)
    head = __import__("subprocess").check_output(["git", "rev-parse", "HEAD"], cwd=ROOT).decode().strip()
    out = tmp_path / "gate.json"
    rc = G.main(["--sha", head, "--repo-slug", SLUG, "--policy", str(ROOT / "docs/ci_v4/ci-v4-policy.json"), "--record", str(rec),
                 "--junit-dir", str(junit.parent), "--output", str(out), "--git-dir", str(ROOT)])
    assert rc == 1 and json.loads(out.read_text())["verdict"] == "RELEASE_BLOCKED"
