"""CI V5-2B: lane separation, honest B5 / comparison vocabulary, the generators, and the repository's own V5 artifacts. Hermetic (temporary Git repositories).

Companion of ``tests/test_ci_v5_foundation.py`` (the A/B/A evaluator matrix). Nothing here needs the network, a token or a pytest sub-run.
"""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import ci_v5_b5 as B5            # noqa: E402
import ci_v5_candidate as CAND   # noqa: E402
import ci_v5_epoch as E          # noqa: E402
import ci_v5_shadow as SH        # noqa: E402

B3_REPORT = str(ROOT / "tests" / "ci_v4_lean_report.py")
FAIL, UNK, PASS = "INTEGRITY_FAIL", "UNKNOWN", "INTEGRITY_PASS"


class Repo:
    def __init__(self, path):
        self.path = Path(path)
        self.path.mkdir(parents=True, exist_ok=True)
        self.git("init", "-q", "-b", "main")

    def git(self, *a):
        p = subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t\x40test.invalid", "-c", "commit.gpgsign=false", *a], cwd=self.path, capture_output=True, text=True)
        assert p.returncode == 0, (a, p.stderr)
        return p.stdout.strip()

    def write(self, rel, text):
        f = self.path / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(text)

    def commit(self, msg="c"):
        self.git("add", "-A")
        self.git("commit", "-q", "--allow-empty", "-m", msg)
        return self.git("rev-parse", "HEAD")


@pytest.fixture(scope="module")
def world(tmp_path_factory):
    r = Repo(tmp_path_factory.mktemp("v5h"))
    for rel, text in {"app/main.py": "MAIN = 1\n", "financial_engine/calc.py": "CALC = 1\n", "tests/test_calc.py": "def test_calc():\n    assert True\n",
                      "README.md": "x\n", "tools/ci_gate.py": "GATE = 1\n", ".gitignore": "__pycache__/\n"}.items():
        r.write(rel, text)
    base = r.commit("accepted main")
    epoch = E.make_epoch(E.Git(r.path), base, epoch_id="h", full_run={"status": "PASS", "run_id": "1", "sha": base})
    r.write(E.TRUSTED_EPOCH_PATH, E.canonical(epoch).decode())
    tip = r.commit("promoted")
    r.write("app/main.py", "MAIN = 2\n")
    r.write("tests/test_new.py", "def test_new():\n    assert True\n")
    r.write("README.md", "y\n")
    pre = r.commit("change")
    delta = E.make_delta(E.read_inventory(E.Git(r.path), tip), E.read_inventory(E.Git(r.path), pre), tip, r.git("rev-parse", tip + "^{tree}"))
    r.write(E.DELTA_PATH, E.canonical(delta).decode())
    head = r.commit("delta")
    return {"r": r, "tip": tip, "head": head, "base": base}


# --------------------------------------------------------------------------------------------------------------------------------- generators
def test_generators_are_pure_functions_of_git_objects_and_canonical(world, tmp_path):
    r = world["r"]
    out = tmp_path / "d.json"
    assert CAND.main(["delta", "--repo", str(r.path), "--base-sha", world["tip"], "--head-sha", world["head"], "--output", str(out)]) == 0
    doc = json.loads(out.read_text())
    assert out.read_bytes() == E.canonical(doc) and doc["schema"] == E.DELTA_SCHEMA and doc["base_sha"] == world["tip"]
    assert {c["path"] for c in doc["changes"]} == {"app/main.py", "tests/test_new.py", "README.md"} and all(set(c) == E.CHANGE_KEYS for c in doc["changes"])
    assert E.DELTA_PATH not in {c["path"] for c in doc["changes"]}                      # the delta never declares itself
    cand = tmp_path / "e.json"
    assert CAND.main(["candidate", "--repo", str(r.path), "--commit", world["base"], "--output", str(cand), "--full-run-id", "42"]) == 0
    epoch, problems = E.load_epoch(cand.read_bytes())
    assert epoch is not None and epoch["guard"]["mode"] == "ALL_TRACKED" and epoch["full_run"]["run_id"] == "42", problems
    blocked = tmp_path / "blocked.json"
    assert CAND.main(["candidate", "--repo", str(r.path), "--commit", world["base"], "--output", str(blocked), "--full-run-blocked-reason", "TIMEOUT_19200S",
                      "--full-run-last-observed", "43828509961"]) == 0
    ep2, problems = E.load_epoch(blocked.read_bytes())
    assert ep2 is not None and ep2["full_run"]["status"] == "FULL_PROVENANCE_BLOCKED" and not E.epoch_full_provenance(ep2)[0], problems   # honest, never a pass
    assert E.epoch_full_provenance(epoch)[0] and not E.epoch_full_provenance({**epoch, "full_run": {**epoch["full_run"], "sha": "0" * 40}})[0]
    with pytest.raises(SystemExit):
        CAND.main(["candidate", "--repo", str(r.path), "--commit", world["base"], "--output", str(blocked), "--full-run-id", "1", "--full-run-blocked-reason", "x"])
    for bad in ("HEAD", "main", "$(true)", ""):
        with pytest.raises(SystemExit):
            CAND.candidate(str(r.path), bad)
        with pytest.raises(SystemExit):
            CAND.delta(str(r.path), bad, world["head"])


def test_cli_exit_codes_follow_the_integrity_vocabulary(world, tmp_path):
    r = world["r"]
    r.git("checkout", "-q", "--detach", world["head"])
    out = tmp_path / "v.json"
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")

    def run(head, base, tip="same", source=("--tool-source", "TRUSTED_BASE")):
        cmd = [sys.executable, "-I", str(ROOT / "tools" / "ci_v5_epoch.py"), "--repo", str(r.path), "--head-sha", head, "--base-sha", base, "--output", str(out), *source]
        return subprocess.run(cmd + ["--trusted-ref-tip", base if tip == "same" else tip], capture_output=True, text=True, env=env)

    p = run(world["head"], world["tip"])
    assert p.returncode == 0 and "CI V5 INTEGRITY_PASS" in p.stdout and "authorization=NOT_EVALUATED" in p.stdout, p.stdout + p.stderr
    p = run(world["head"], world["tip"], source=())                                      # the default tool source is UNTRUSTED: UNKNOWN -> exit 2
    assert p.returncode == 2 and "UNKNOWN" in p.stdout
    assert run("f" * 40, world["tip"]).returncode == 2                                    # absent head object: UNKNOWN
    p = run("HEAD", world["tip"])
    assert p.returncode == 1 and "INTEGRITY_FAIL" in p.stdout                              # symbolic ref: BAD_REF -> FAIL


# --------------------------------------------------------------------------------------------------------------------------------- lane split
def test_verdict_job_reads_git_objects_only_and_runs_no_checkout_code(world, tmp_path):
    """The ``verdict`` entry point must not import or execute anything from the checkout: poison every plausible import target in the repository."""
    r = world["r"]
    for rel in ("tools/ci_v4_governance_gate.py", "tests/__init__.py", "tests/conftest.py", "sitecustomize.py", "usercustomize.py", "ci_v5_epoch.py", "tools/ci_v5_epoch.py"):
        r.write(rel, "raise SystemExit('PR-HEAD CODE EXECUTED')\n")
    poisoned = r.commit("poison")
    out = tmp_path / "out"
    marker = tmp_path / "marker"           # nothing may create it
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    p = subprocess.run([sys.executable, "-I", str(ROOT / "tools" / "ci_v5_shadow.py"), "verdict", "--repo", str(r.path), "--head-sha", poisoned, "--base-tip-sha", world["tip"],
                        "--out-dir", str(out), "--b3-report", B3_REPORT, "--tools-provenance", "TRUSTED_BASE"], cwd=str(r.path), capture_output=True, text=True, env=env)
    assert "PR-HEAD CODE EXECUTED" not in p.stdout + p.stderr and not marker.exists()
    v5 = json.loads((out / SH.VERDICT_FILE).read_text())
    assert v5["integrity"] == FAIL and v5["trust"]["tool_source"] == "TRUSTED_BASE"        # the poison files are undeclared guarded adds: failure, not execution
    assert (out / SH.B5_FILE).exists() and not (out / SH.V4_FILE).exists() and not (out / SH.V4_RAW_FILE).exists()
    r.git("reset", "-q", "--hard", world["head"])


def test_compare_job_uses_artifacts_as_data_and_never_pairs_foreign_heads(world, tmp_path):
    vdir, gdir, odir = tmp_path / "v", tmp_path / "g", tmp_path / "o"
    for d in (vdir, gdir):
        d.mkdir()
    v5 = E.verify(world["r"].path, world["head"], world["tip"], trusted_ref_tip=world["tip"], tool_source="TRUSTED_BASE")
    (vdir / SH.VERDICT_FILE).write_text(json.dumps(v5))
    (vdir / SH.B5_FILE).write_text(json.dumps({"status": "UNAVAILABLE", "reason": "test"}))
    (gdir / SH.V4_FILE).write_text(json.dumps({"verdict": "PASS", "head_sha": world["head"], "wall_s": 1.0}))
    summary = tmp_path / "summary.md"
    args = ["compare", "--head-sha", world["head"], "--verdict-dir", str(vdir), "--v4-dir", str(gdir), "--out-dir", str(odir), "--summary", str(summary)]
    assert SH.main(args) == 1                                                             # B5 UNAVAILABLE is a visible harness error, never silently dropped
    rec = json.loads((odir / SH.COMPARISON_FILE).read_text())
    assert rec["comparison"]["relation"] == "MATCH_PASS" and rec["comparison"]["parity"] == "PARITY_NOT_ESTABLISHED"
    text = summary.read_text()
    assert "integrity is NOT authorization" in text and "authorization / enforcement | `NOT_EVALUATED` / `SHADOW`" in text and "B5" in text
    (gdir / SH.V4_FILE).write_text(json.dumps({"verdict": "PASS", "head_sha": "e" * 40}))      # V4 artifact from ANOTHER head: never compared
    SH.main(args)
    rec = json.loads((odir / SH.COMPARISON_FILE).read_text())
    assert rec["v4"]["verdict"] == "UNAVAILABLE" and rec["comparison"]["relation"] == "INCOMPARABLE" and "artifact head SHA" in " ".join(rec["harness_errors"])
    (vdir / SH.VERDICT_FILE).unlink()                                                     # a missing verdict artifact is UNKNOWN / UNAVAILABLE, never a pass
    SH.main(args)
    rec = json.loads((odir / SH.COMPARISON_FILE).read_text())
    assert rec["v5"]["integrity"] == UNK and rec["v5"]["authorization"] == "UNVERIFIED" and rec["comparison"]["relation"] == "INCOMPARABLE"


def test_v4_job_runs_only_the_gate_and_stamps_its_head(world, tmp_path):
    out = tmp_path / "o"
    assert SH.main(["v4", "--repo", str(tmp_path), "--head-sha", world["head"], "--out-dir", str(out), "--v4-timeout", "30"]) == 0
    rec = json.loads((out / SH.V4_FILE).read_text())
    assert rec["verdict"] == "UNAVAILABLE" and rec["head_sha"] == world["head"]            # no gate in that directory: UNAVAILABLE, not PASS


@pytest.mark.parametrize("v4,v5,relation", [
    ("PASS", PASS, "MATCH_PASS"), ("FAIL", FAIL, "MATCH_FAIL"), ("FAIL", PASS, "MISMATCH_V5_WOULD_ADMIT_V4_FAIL"), ("PASS", FAIL, "MISMATCH_V5_STRICTER_THAN_V4"),
    ("UNAVAILABLE", PASS, "INCOMPARABLE"), ("PASS", UNK, "INCOMPARABLE"), (None, PASS, "INCOMPARABLE")])
def test_comparison_never_lets_v5_suppress_a_v4_failure_and_never_claims_parity(v4, v5, relation):
    out = SH.compare({"verdict": v4, "non_exact_cohorts": ["x"]}, {"integrity": v5, "trust": {"authoritative": False}})
    assert out["relation"] == relation and out["parity"] == "PARITY_NOT_ESTABLISHED" and out["v4_remains_authoritative"] is True
    assert (out["v4_failure_attribution"] is not None) == (v4 == "FAIL") and out["v5_authoritative"] is False


def test_v4_gate_runner_never_reports_pass_for_a_missing_or_failed_gate(tmp_path):
    assert SH.run_v4_gate(str(tmp_path), str(tmp_path / "o.json"), 30)["verdict"] == "UNAVAILABLE"


# --------------------------------------------------------------------------------------------------------------------------------- B5 provenance
def _junit(tmp_path, cases):
    body = "".join('<testcase classname="%s" name="%s" time="1.5">%s</testcase>' % (c, n, extra) for c, n, extra in cases)
    p = tmp_path / "j.xml"
    p.write_text('<testsuite>%s</testsuite>' % body)
    return str(p)


def test_b5_status_vocabulary_never_promotes_unverified_skipped_or_unselected_to_pass(tmp_path):
    sha = "a" * 40
    junit = _junit(tmp_path, [("tests.test_new", "test_a", ""), ("tests.test_new", "test_b", "<skipped/>")])
    known = {"tests/test_new.py"}
    assert B5.junit_evidence([junit], None, sha, known)[:3:2] == ("UNVERIFIED_INPUT", {})        # no attestation: no status, no seconds
    digest = B5._sha256(junit)

    def att(**over):
        p = tmp_path / "att.json"
        p.write_text(json.dumps({"kind": "hosted_run", "sha": sha, "run_id": "9", "lane": "TRUSTED_BASE", "junit_sha256": [digest], **over}))
        return str(p)
    assert B5.junit_evidence([junit], att(sha="0" * 40), sha, known)[0] == "UNVERIFIED_INPUT"          # another head
    assert B5.junit_evidence([junit], att(junit_sha256=["f" * 64]), sha, known)[0] == "UNVERIFIED_INPUT"  # other bytes
    assert B5.junit_evidence([junit], att(lane="PR_HEAD"), sha, known)[0] == "UNVERIFIED_INPUT"          # a PR-head lane may write any file it likes
    assert B5.junit_evidence([junit], att(lane=None), sha, known)[0] == "UNVERIFIED_INPUT"
    label, _why, st = B5.junit_evidence([junit], att(), sha, known)
    assert label == "OBSERVED_HOSTED" and st == {"tests/test_new.py": "SKIPPED"}                       # one skipped node: never plain PASS
    assert B5.junit_evidence([junit], att(conclusion="cancelled"), sha, known)[2] == {"tests/test_new.py": "CANCELLED"}
    assert B5.junit_evidence([], None, sha)[0] == "UNKNOWN"


def test_b5_report_is_honest_about_missing_plan_junit_and_collected_nodes(world, tmp_path):
    rep = B5.build(world["r"].path, world["tip"], world["head"], B3_REPORT)
    assert rep["status"] == "OK" and rep["head_sha"] == world["head"] and rep["node_delta_kind"].startswith("AST_FUNCTION_DELTA")
    assert rep["collected_nodes"]["status"] == "UNAVAILABLE"                                           # file/function deltas are NOT collected node counts
    mod = {m["path"]: m for m in rep["modules"]}["tests/test_new.py"]
    assert mod["change"] == "added" and mod["selection"] == "UNKNOWN" and mod["status"] == "UNKNOWN" and mod["seconds"] is None   # never a synthetic zero
    assert any(u.startswith("plan:") for u in rep["unavailable"]) and any(u.startswith("junit:") for u in rep["unavailable"])
    assert rep["junit"]["label"] == "UNKNOWN" and rep["simulation"]["label"] == "UNKNOWN" and rep["exit_code_policy"].startswith("always 0")
    plan = tmp_path / "plan.json"
    plan.write_text(json.dumps({"tested_sha": "e" * 40, "pytest_modules": ["tests/test_calc.py"]}))      # a plan for ANOTHER sha cannot claim NOT_SELECTED
    row = {m["path"]: m for m in B5.build(world["r"].path, world["tip"], world["head"], B3_REPORT, str(plan))["modules"]}["tests/test_new.py"]
    assert row["selection"] == "UNKNOWN" and row["status"] == "UNKNOWN"
    plan.write_text(json.dumps({"tested_sha": world["head"], "pytest_modules": ["tests/test_calc.py"]}))
    row = {m["path"]: m for m in B5.build(world["r"].path, world["tip"], world["head"], B3_REPORT, str(plan))["modules"]}["tests/test_new.py"]
    assert row["selection"] == "NOT_SELECTED" and row["status"] == "NOT_SELECTED" and row["status"] != "PASS"
    assert "NOT a pass" in B5.summary_markdown(B5.build(world["r"].path, "0" * 40, world["head"], B3_REPORT))   # failure is visible UNAVAILABLE


# --------------------------------------------------------------------------------------------------------------------------------- workflow / artifacts
def test_shadow_workflow_is_split_by_trust_boundary_and_least_privilege():
    import yaml
    text = (ROOT / ".github/workflows/ci_v5_shadow.yml").read_text()
    wf = yaml.safe_load(text)
    on = wf.get("on", wf.get(True))
    assert wf["permissions"] == {"contents": "read"} and list(wf["jobs"]) == ["verdict", "v4-comparison", "compare"] and on["pull_request"]["branches"] == ["main"]
    for banned in ("pull_request_target", "secrets.", "continue-on-error: false", "workflow_run", "pull-requests: write", "contents: write"):
        assert banned not in text, banned
    jobs = wf["jobs"]
    runs = {k: "\n".join(s.get("run", "") for s in j["steps"]) for k, j in jobs.items()}
    # job 1 (the verdict) and job 3 (compare): trusted-base tools by ``git archive``, run OUTSIDE the checkout with isolated python; nothing from the checkout is run
    for k in ("verdict", "compare"):
        assert "git archive" in runs[k] and 'python -I "$TOOLS_DIR/tools/ci_v5_shadow.py"' in runs[k]
        assert "python tools/" not in runs[k] and "python -m" not in runs[k] and "pytest" not in runs[k] and "pip " not in runs[k] and "npm " not in runs[k]
        assert "origin/main" in runs[k] and "merge-base" not in runs[k], "the base is the protected tip, never a caller-supplied merge-base"
    assert "FINCO_CI_V5_DELTA_V2" in runs["verdict"] and "UNTRUSTED_TOOL_SOURCE" in runs["verdict"] and "TRUSTED_BASE" in runs["verdict"]
    # job 2 is the ONLY job that executes PR-head code, and it publishes only its own artifact
    assert "python tools/ci_v5_shadow.py v4" in runs["v4-comparison"]
    assert jobs["compare"]["needs"] == ["verdict", "v4-comparison"] and jobs["compare"]["if"] == "always()"
    assert not any("${{" in s.get("run", "") for j in jobs.values() for s in j["steps"]), "event/context values reach scripts only through env:"
    assert all(len(u.split("@")[1]) == 40 for u in (s["uses"] for j in jobs.values() for s in j["steps"] if "uses" in s))        # actions pinned by full SHA
    names = {s["with"]["name"] for j in jobs.values() for s in j["steps"] if "uses" in s and "artifact" in s["uses"]}
    assert names == {"ci-v5-verdict-${{ github.event.pull_request.head.sha }}", "ci-v5-v4gate-${{ github.event.pull_request.head.sha }}", "ci-v5-shadow-${{ github.event.pull_request.head.sha }}"}


def test_repository_artifacts_make_no_authority_claim():
    """The checkpoint ships with an HONEST blocked FULL witness (never authoritative), the legacy V1 candidate stays non-authoritative, and the delta is a V2 document."""
    epoch, problems = E.load_epoch((ROOT / E.TRUSTED_EPOCH_PATH).read_bytes())
    assert epoch is not None and epoch["full_run"]["status"] == "FULL_PROVENANCE_BLOCKED" and not E.epoch_full_provenance(epoch)[0], problems
    delta = json.loads((ROOT / E.DELTA_PATH).read_bytes())
    assert (ROOT / E.DELTA_PATH).read_bytes() == E.canonical(delta) and delta["schema"] == E.DELTA_SCHEMA and set(delta) == E.DELTA_KEYS
    assert E.SHA40.fullmatch(delta["base_sha"]) and E.SHA256.fullmatch(delta["result_inventory_sha256"])
    cand = ROOT / E.CANDIDATE_EPOCH_PATH
    legacy, problems = E.load_epoch(cand.read_bytes())
    assert legacy is not None and legacy["legacy"] is True, problems                      # LEGACY_NARROW_GUARD: never an approved FULL guard
    assert {r["status"] for r in legacy["atlas"]} <= {"COVERED", "GAP", "UNKNOWN"} and any(r["status"] != "COVERED" for r in legacy["atlas"])
