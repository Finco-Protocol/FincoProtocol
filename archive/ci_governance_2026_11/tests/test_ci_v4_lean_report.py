"""CI V4 Lean B1 report: the measurement / SIMULATION / WARN-ONLY helpers never gate, never mutate the repository and never present a local
measurement or a simulation as hosted evidence. Risk protected: an informational tool silently becoming a blocking gate or a fake PASS."""
import json
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from tests import ci_v4_lean_report as R

ROOT = Path(__file__).resolve().parents[1]


def _junit(tmp_path, cases, name="j.xml"):
    rows = "".join("<testcase classname='%s' name='%s' time='%s'/>" % c for c in cases)
    p = tmp_path / name
    p.write_text("<testsuites><testsuite>%s</testsuite></testsuites>" % rows)
    return p


def test_git_subprocess_counter_counts_only_git_and_restores_popen():
    before = subprocess.Popen.__init__
    with R.git_subprocess_counter() as c:
        subprocess.run(["git", "--version"], capture_output=True)
        subprocess.run(["git", "--version"], capture_output=True)
        subprocess.run([sys.executable, "-c", "pass"], capture_output=True)
    assert c == {"git": 2, "other": 1}
    assert subprocess.Popen.__init__ is before            # nothing stays patched


def test_every_report_is_labelled_and_a_simulation_is_never_hosted_evidence():
    sim = R.simulate_workers(["tests/a.py", "tests/b.py", "tests/c.py"], {"tests/a.py": 30.0, "tests/b.py": 20.0, "tests/c.py": 10.0}, weights_source="unit")
    assert sim["label"] == "SIMULATION" and "NOT hosted evidence" in sim["disclaimer"]
    assert [r["workers"] for r in sim["rows"]] == list(R.SIM_WORKERS) == [3, 4, 5, 6, 8]
    assert R.admission_report([])["label"] == "WARN_ONLY" and R.budget_warnings([])["label"] == "WARN_ONLY"
    assert set(R.LABELS) == {"MEASURED_LOCAL", "SIMULATION", "WARN_ONLY"}


def test_simulation_is_deterministic_conserves_work_and_prices_unknown_modules_conservatively():
    w = {"tests/a.py": 100.0, "tests/b.py": 100.0, "tests/c.py": 50.0}
    mods = ["tests/c.py", "tests/a.py", "tests/b.py", "tests/new_unweighted.py"]
    one = R.simulate_workers(mods, w, weights_source="unit")
    two = R.simulate_workers(list(reversed(mods)), w, weights_source="unit")
    assert one == two                                            # order-independent, deterministic tie-breaks
    assert one["unknown_modules"] == ["tests/new_unweighted.py"]  # never silently zero
    assert one["total_weight_s"] == 100 + 100 + 50 + one["default_module_s_for_unknown"]
    for row in one["rows"]:
        assert row["runner_s"] == one["total_weight_s"]           # LPT only moves work between workers, it never loses any


def test_simulation_with_the_recorded_weights_names_its_provenance():
    sim = R.simulate_workers(["tests/test_ci_v4_aggregate.py"])
    assert sim["weights_source"] and sim["weights_source"] != "supplied" and sim["rows"]


def test_collection_output_parser_reads_node_ids_and_errors():
    nodes, errors = R.parse_collect_output(textwrap.dedent("""\
        tests/test_a.py::test_one
        tests/test_a.py::test_two[param-1]
        ERROR tests/test_bad.py
        2 tests collected, 1 error in 0.1s
        """))
    assert nodes == ["tests/test_a.py::test_one", "tests/test_a.py::test_two[param-1]"] and errors == ["ERROR tests/test_bad.py"]


def test_collection_digest_is_stable_and_order_independent_for_a_real_module():
    a = R.collection_digest(["tests/test_ci_v4_lean_report.py"])
    b = R.collection_digest(["tests/test_ci_v4_lean_report.py"])
    assert a["label"] == "MEASURED_LOCAL" and a["collected_nodes"] >= 8 and a["collection_errors"] == []
    assert a["node_id_sha256"] == b["node_id_sha256"] and a["collected_nodes"] == b["collected_nodes"]
    assert "NOT derived from collection" in a["note"]            # collected is never reported as selected / executed / passed


def test_weights_proposal_is_not_active_deterministic_and_keeps_unknown_unknown(tmp_path):
    j = _junit(tmp_path, [("tests.test_ci_v4_aggregate", "test_one", 2.5), ("tests.test_ci_v4_aggregate", "test_two", 1.5)])
    cur = {"tests/test_ci_v4_aggregate.py": 99.0, "tests/test_ci_v4_select.py": 7.0}
    before = (ROOT / "docs/ci_v4/module_weights.json").read_bytes()
    p1 = R.propose_weights([j], cur, "unit-provenance", "run-1")
    p2 = R.propose_weights([j], cur, "unit-provenance", "run-1")
    assert p1 == p2 and p1["status"] == "PROPOSAL_NOT_ACTIVE"
    assert p1["modules"]["tests/test_ci_v4_aggregate.py"] == 4.0
    assert p1["modules"]["tests/test_ci_v4_select.py"] == 7.0 and p1["kept_previous_weight"] == ["tests/test_ci_v4_select.py"]
    assert (ROOT / "docs/ci_v4/module_weights.json").read_bytes() == before      # the active weights file is never written


def test_admission_report_is_warn_only_and_flags_the_proposed_checklist_items(tmp_path):
    f = tmp_path / "test_sample.py"
    f.write_text(textwrap.dedent('''\
        import subprocess
        import pytest

        @pytest.mark.skip
        def test_reads_source(tmp_path):
            text = (tmp_path / "x.py").read_text()
            assert "needle" in text

        def test_git_in_a_loop():
            for p in ("a", "b"):
                subprocess.check_output(["git", "status", p])
        '''))
    rep = R.admission_report([str(f)])
    codes = {x["code"] for x in rep["findings"]}
    assert {"ADM-RISK", "ADM-SOURCE-TEXT", "ADM-GIT-LOOP", "ADM-SKIP"} <= codes
    assert rep["label"] == "WARN_ONLY" and rep["budgets"]["enforced"] is False and rep["budgets"]["approved_by_owner"] is False
    assert all(x["severity"] == "WARN" for x in rep["findings"])


def test_a_documented_clean_test_has_no_admission_warning(tmp_path):
    f = tmp_path / "test_clean.py"
    f.write_text('"""Risk protected: a negative control that fails closed."""\n\ndef test_ok():\n    assert 1 + 1 == 2\n')
    assert R.admission_report([str(f)])["findings"] == []


def test_budget_warnings_use_the_proposed_not_approved_thresholds(tmp_path):
    j = _junit(tmp_path, [("tests.t", "fast", 59), ("tests.t", "slow", 130), ("tests.t", "huge", 310)])
    rep = R.budget_warnings([j])
    levels = {r["id"]: r["level"] for r in rep["findings"] if r["kind"] == "node"}
    assert levels == {"tests.t::slow": "WARN", "tests.t::huge": "EXCEPTION"} and rep["enforced"] is False


def test_the_cli_never_gates_even_when_it_finds_warnings(tmp_path):
    f = tmp_path / "test_bad.py"
    f.write_text("def test_x():\n    assert True\n")
    out = tmp_path / "o.json"
    assert R.main(["admission", "--output", str(out), str(f)]) == 0
    data = json.loads(out.read_text())
    assert data["schema"] == R.SCHEMA and data["warnings"] >= 1 and data["exit_code_policy"].startswith("always 0")
    r = subprocess.run([sys.executable, "-m", "tests.ci_v4_lean_report", "admission", str(f)], cwd=ROOT, capture_output=True, text=True)
    assert r.returncode == 0 and "WARN_ONLY" in r.stdout


def test_the_report_module_is_not_wired_into_selection_scheduling_or_aggregation():
    """It must stay opt-in: none of the CI V4 tools imports it, and it writes no tracked file by default."""
    for tool in ("ci_v4_select", "ci_v4_schedule", "ci_v4_aggregate", "ci_v4_governance_gate", "ci_v4_activate", "ci_v4_shard", "ci_v4_nodes"):
        assert "ci_v4_lean_report" not in (ROOT / "tools" / (tool + ".py")).read_text(), tool
    workflows = "".join(p.read_text() for p in (ROOT / ".github/workflows").glob("ci_v4_*.yml"))
    assert "ci_v4_lean_report" not in workflows


# -------------------------------------------------------------------------------------------- B3 test-admission report (targeted cases)
from tests import ci_v4_lean_report as _B3R

_ADM_META = 'Admission: risk=probe-only, nearest=none, witness=red-before-green missing, tier=fast, owner=ci, retire=when-flaky'


@pytest.fixture()
def b3_repo(tmp_path):
    root = tmp_path / "b3repo"
    subprocess.check_call(["git", "clone", "-q", "--no-hardlinks", str(ROOT), str(root)])
    subprocess.check_call(["git", "config", "user.name", "t"], cwd=root)
    subprocess.check_call(["git", "config", "user.email", "t-at-test-placeholder"], cwd=root)
    subprocess.check_call(["git", "checkout", "-q", "-b", "b3-probe"], cwd=root)
    return root


def _b3_commit(root, msg="probe"):
    subprocess.check_call(["git", "add", "-A"], cwd=root)
    subprocess.check_call(["git", "commit", "-q", "--allow-empty", "-m", msg], cwd=root)
    return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root).decode().strip()


def test_b3_admission_normal_addition_is_listed_with_labels(b3_repo):
    (b3_repo / "tests" / "test_b3_probe_normal.py").write_text(
        "'%s'\n\ndef test_b3_probe_normal():\n    assert True\n" % _ADM_META)
    head = _b3_commit(b3_repo)
    rep = _B3R.test_admission_report(base="HEAD~1", head=head, root=b3_repo)
    assert rep["modules"]["added"] == ["tests/test_b3_probe_normal.py"]
    row = rep["node_deltas"][0]
    assert row["added_nodes"] == ["test_b3_probe_normal"] and row["status"] == "AST_FUNCTION_DELTA"
    assert row["node_id_status"].startswith("UNKNOWN")      # function names are never reported as collected node ids
    assert row["selected"] == "UNKNOWN" and row["wall_label"] == "UNKNOWN" and row["git_process_count"] == "UNKNOWN"
    assert all(v != "UNKNOWN" for k, v in rep["admission_metadata"][0].items() if k != "module")


def test_b3_admission_duplicate_candidate_is_heuristic_warn_only(b3_repo):
    (b3_repo / "tests" / "test_b3_probe_dup.py").write_text(
        "def test_b3_probe_dup():\n    value = 1 + 1\n    assert value == 2\n")
    _b3_commit(b3_repo)
    (b3_repo / "tests" / "test_b3_probe_dup2.py").write_text(
        "def test_b3_probe_dup2():\n    value = 1 + 1\n    assert value == 2\n")
    head = _b3_commit(b3_repo)
    rep = _B3R.test_admission_report(base="HEAD~2", head=head, root=b3_repo)
    assert rep["duplicate_candidates"], "identical normalized bodies must surface as CANDIDATES"
    assert all(d["severity"] == "WARN" for d in rep["duplicate_candidates"])
    assert rep["label"] == "WARN_ONLY"


def test_b3_admission_missing_metadata_is_unknown_never_invented(b3_repo):
    (b3_repo / "tests" / "test_b3_probe_nodoc.py").write_text("def test_b3_probe_nodoc():\n    assert 1\n")
    head = _b3_commit(b3_repo)
    rep = _B3R.test_admission_report(base="HEAD~1", head=head, root=b3_repo)
    meta = rep["admission_metadata"][0]
    assert all(v == "UNKNOWN" for k, v in meta.items() if k != "module")
    assert any(f["code"] == "ADM-METADATA-UNKNOWN" for f in rep["findings"])


def test_b3_admission_new_skip_is_reported_never_pass(b3_repo):
    (b3_repo / "tests" / "test_b3_probe_skip.py").write_text(
        "import pytest\n\n\npytestmark = pytest.mark.skip(reason='probe')\ndef test_b3_probe_skip():\n    assert True\n")
    head = _b3_commit(b3_repo)
    rep = _B3R.test_admission_report(base="HEAD~1", head=head, root=b3_repo)
    assert [k["newness"][:11] for k in rep["new_skip_markers"]] == ["NEW_VS_BASE"], "a new skip must be visible; a skipped node is never PASS"
    assert any(f["code"] == "ADM-NEW-SKIP" for f in rep["findings"])


def test_b3_admission_tool_failure_is_reported_inside_json_never_as_exit(b3_repo):
    (b3_repo / "tests" / "test_b3_probe_broken.py").write_text("def broken(:\n")
    head = _b3_commit(b3_repo)
    rep = _B3R.test_admission_report(base="HEAD~1", head=head, root=b3_repo)
    assert rep["node_deltas"][0]["status"] == "UNKNOWN"      # unparsable source is UNKNOWN, never an empty lie
    assert rep["exit_code_policy"].startswith("always 0")


def test_b3_admission_unchanged_fast_path_is_empty(b3_repo):
    head = _b3_commit(b3_repo, "empty")
    rep = _B3R.test_admission_report(base="HEAD~1", head=head, root=b3_repo)
    assert rep["modules"]["added"] == [] and rep["modules"]["removed"] == [] and rep["modules"]["changed"] == []
    assert rep["node_deltas"] == [] and rep["growth"]["added_nodes"] == 0


def test_b3_admission_plan_status_selected_vs_not_selected(b3_repo):
    plan = {"pytest_modules": ["tests/test_b3_probe_in_plan.py"], "schedule": {"predicted_critical_path_s": None}}
    (b3_repo / "tests" / "test_b3_probe_in_plan.py").write_text("def test_in_plan():\n    assert True\n")
    (b3_repo / "tests" / "test_b3_probe_out_plan.py").write_text("def test_out_plan():\n    assert True\n")
    pf = b3_repo / "plan.json"
    pf.write_text(json.dumps(plan))
    head = _b3_commit(b3_repo)
    rep = _B3R.test_admission_report(base="HEAD~1", head=head, plan_path=str(pf), root=b3_repo)
    by_mod = {r["module"]: r for r in rep["node_deltas"]}
    assert by_mod["tests/test_b3_probe_in_plan.py"]["selected"] == "SELECTED"
    assert by_mod["tests/test_b3_probe_out_plan.py"]["selected"] == "NOT_SELECTED"
    assert rep["critical_path"]["plan_predicted_critical_path_s"] is None
