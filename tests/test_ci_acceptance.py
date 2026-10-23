"""CI partition/aggregate adversarial tests; no financial runtime changes."""
from copy import deepcopy
import argparse
import json
from pathlib import Path
import subprocess
import sys

import pytest

from tools.ci_acceptance import EvidenceError, attest, compare_records, partition_modules, weights_from_junit
from tools.ci_browser_job import REQUIRED, SELECTIONS, manifest, validate_browser_records, validate_consolidation
from tools.ci_acceptance import run_command
from tools.ci_measurement import distribution


HEAD = "a" * 40
TREE = "b" * 40
NODES = ["tests/test_one.py::test_a", "tests/test_one.py::test_b", "tests/test_two.py::test_c"]


def proof():
    control = {"schema": 1, "head": HEAD, "tree": TREE, "pytest_exit": 0,
               "collected": NODES, "selected": NODES, "deselected": [],
               "collection_skips": [["tests/test_browser.py", "Playwright not installed"]],
               "collection_errors": [], "shard": None,
               "outcomes": {node: {"status": "passed", "reason": ""} for node in NODES}}
    shards = []
    for slot, selected in enumerate((NODES[:2], NODES[2:])):
        shard = deepcopy(control)
        shard.update(shard=slot, selected=selected, deselected=sorted(set(NODES) - set(selected)),
                     outcomes={node: control["outcomes"][node] for node in selected})
        shards.append(shard)
    processes = [{"head": HEAD, "tree": TREE, "exit_code": 0, "normal_exit": True,
                  "junit_sha256": "digest", "junit_failures": 0, "environment_sha256": "environment",
                  "elapsed_seconds": 10.0} for _ in range(3)]
    return control, shards, processes


def verify(control, shards, processes, results=None):
    return compare_records(control, shards, processes, HEAD, TREE, results or ["success"] * 3)


def test_valid_complete_whole_module_shadow_proof():
    assert verify(*proof())["equivalent"] is True


@pytest.mark.parametrize("status", ["failure", "cancelled", "timed_out", "skipped", "", None, "in_progress"])
def test_non_success_job_fails_required_aggregate(status):
    with pytest.raises(EvidenceError, match="job"):
        verify(*proof(), ["success", status, "success"])


def test_missing_shard_fails():
    control, shards, processes = proof()
    with pytest.raises(EvidenceError, match="Missing shard"):
        verify(control, shards[:1], processes)


def test_missing_process_artifact_fails():
    control, shards, processes = proof()
    with pytest.raises(EvidenceError, match="process artifact"):
        verify(control, shards, processes[:2])


@pytest.mark.parametrize("field,value", [("head", "wrong"), ("tree", "wrong"), ("pytest_exit", 1),
                                        ("collection_errors", [["module", "ImportError"]]),
                                        ("selected", []), ("shard", 1)])
def test_invalid_shard_attestation_or_collection_fails(field, value):
    control, shards, processes = proof()
    shards[0][field] = value
    with pytest.raises(EvidenceError):
        verify(control, shards, processes)


@pytest.mark.parametrize("field,value", [("exit_code", 124), ("normal_exit", False), ("head", "wrong"),
                                        ("tree", "wrong"), ("junit_sha256", ""), ("junit_failures", 1),
                                        ("environment_sha256", "different")])
def test_invalid_process_or_artifact_fails(field, value):
    control, shards, processes = proof()
    processes[1][field] = value
    with pytest.raises(EvidenceError):
        verify(control, shards, processes)


def test_duplicate_node_fails():
    control, shards, processes = proof()
    shards[0]["selected"].append(NODES[0])
    with pytest.raises(EvidenceError, match="Duplicate"):
        verify(control, shards, processes)


def test_missing_node_outcome_fails():
    control, shards, processes = proof()
    del shards[0]["outcomes"][NODES[0]]
    with pytest.raises(EvidenceError, match="outcomes"):
        verify(control, shards, processes)


def test_unexpected_skip_reason_fails():
    control, shards, processes = proof()
    shards[0]["outcomes"][NODES[0]] = {"status": "skipped", "reason": "unexpected"}
    with pytest.raises(EvidenceError, match="skip/xfail"):
        verify(control, shards, processes)


def test_unexpected_collection_skip_fails():
    control, shards, processes = proof()
    shards[0]["collection_skips"].append(["extra", "missing dependency"])
    with pytest.raises(EvidenceError, match="collection skips"):
        verify(control, shards, processes)


def test_split_module_fixtures_rejected_even_if_node_union_matches():
    control, shards, processes = proof()
    for slot, selected in enumerate(([NODES[0]], NODES[1:])):
        shards[slot]["selected"] = selected
        shards[slot]["deselected"] = sorted(set(NODES) - set(selected))
        shards[slot]["outcomes"] = {node: control["outcomes"][node] for node in selected}
    with pytest.raises(EvidenceError, match="Module fixture split"):
        verify(control, shards, processes)


def test_control_selection_cannot_be_weakened():
    control, shards, processes = proof()
    control["deselected"] = [NODES[0]]
    with pytest.raises(EvidenceError, match="Control unexpectedly"):
        verify(control, shards, processes)


def test_partition_is_deterministic_and_preserves_modules():
    weights = {"tests/test_one.py": 30, "tests/test_two.py": 20}
    plan = partition_modules(NODES, weights)
    assert plan == partition_modules(reversed(NODES), weights)
    assert plan == {"tests/test_one.py": 0, "tests/test_two.py": 1}


def test_unknown_modules_still_partition_without_omission():
    assert set(partition_modules(NODES, {})) == {"tests/test_one.py", "tests/test_two.py"}


def test_source_junit_weights_are_instrumentation_not_financial_inputs(tmp_path):
    xml = tmp_path / "results.xml"
    xml.write_text('<testsuite><testcase classname="tests.test_one.TestClass" time="2.5"/>\n'
                   '<testcase classname="tests.test_one.TestClass" time="3.0"/></testsuite>', encoding="utf-8")
    weights = weights_from_junit(xml, "source-run")
    assert weights["modules"] == {"tests/test_one.py": 5.5}
    assert len(weights["junit_sha256"]) == 64


def test_wrong_git_head_rejected(monkeypatch):
    monkeypatch.setattr("tools.ci_acceptance.git_value", lambda *args: "actual")
    with pytest.raises(EvidenceError, match="Wrong tested SHA"):
        attest("expected")


def test_plugin_real_collection_outcomes_and_module_partition(tmp_path):
    paths = []
    for index in range(2):
        path = tmp_path / f"test_synthetic_{index}.py"
        path.write_text("import pytest\ndef test_pass(): assert True\n"
                        "@pytest.mark.skip(reason='synthetic reason')\ndef test_skip(): pass\n", encoding="utf-8")
        paths.append(str(path))
    weights = tmp_path / "weights.json"
    weights.write_text('{"modules": {}}', encoding="utf-8")
    records = []
    for slot in (None, 0, 1):
        output = tmp_path / f"inventory-{slot}.json"
        command = [sys.executable, "-m", "pytest", "-q", "--confcutdir", str(tmp_path),
                   "-p", "tools.ci_pytest_inventory", f"--ci-inventory={output}",
                   f"--ci-weights={weights}", *paths]
        if slot is not None:
            command.append(f"--ci-shard={slot}")
        result = subprocess.run(command, capture_output=True, text=True, timeout=60)
        assert result.returncode == 0, result.stdout + result.stderr
        records.append(json.loads(output.read_text(encoding="utf-8")))
    assert len(records[0]["selected"]) == 4
    assert {v["status"] for v in records[0]["outcomes"].values()} == {"passed", "skipped"}
    assert set(records[1]["selected"]).isdisjoint(records[2]["selected"])
    assert set(records[1]["selected"] + records[2]["selected"]) == set(records[0]["selected"])


_F3_5_REVIEWED_PROTECTED_PATHS = frozenset({
    "financial_engine/book_basis.py",
    "financial_engine/financial_statements/assembly.py",
    "financial_engine/financial_statements/contracts.py",
    "financial_engine/financing/generic_product_policy.py",
    "financial_engine/financing/junior_debt.py",
    "financial_engine/financing/project.py",
    "financial_engine/financing/project_uses.py",
    "financial_engine/project_returns/contracts.py",
    "financial_engine/project_returns/model.py",
    "financial_engine/senior_debt/project_adapter.py",
    "financial_engine/shareholder_waterfall/contracts.py",
    "financial_engine/shareholder_waterfall/model.py",
    "finco_core/inputs/_models.py",
    "finco_core/inputs/junior_debt.py",
    "finco_core/inputs/serialization.py",
})


def _assert_frozen_financial_namespace_authority(root, *, baseline="origin/main", ref="HEAD", authorities=None):
    from model_v2_governance import F3_5_A_JUNIOR_AUTHORITIES, PERMANENT_HARD_DENY_PREFIXES

    reviewed = F3_5_A_JUNIOR_AUTHORITIES
    assert set(reviewed) == _F3_5_REVIEWED_PROTECTED_PATHS, "Incomplete or extra F3.5 release authority"
    pins = reviewed if authorities is None else authorities
    assert pins == reviewed, "Release authority differs from independently reviewed pins"

    def git(*args):
        result = subprocess.run(["git", *args], cwd=root, capture_output=True, text=True)
        assert result.returncode == 0, f"Git authority unavailable: {args}: {result.stderr}"
        return result.stdout.strip()

    base = git("rev-parse", "--verify", f"{baseline}^{{commit}}")
    head = git("rev-parse", "--verify", f"{ref}^{{commit}}")
    git("merge-base", "--is-ancestor", base, head)
    changed = set(filter(None, git("diff", "--name-only", "-z", "--no-renames", base, head).split("\0")))
    from r_live_lifecycle_governance import reviewed_radar_authority_matches

    # PR #237: only the three exact reviewed Radar paths at their exact reviewed
    # blobs (proven at the tested commit) are exempt from the permanent hard deny.
    # Every other hard-deny path, and any other content at a pinned path, is denied.
    denied = {
        path for path in changed
        if path.startswith(PERMANENT_HARD_DENY_PREFIXES)
        and not reviewed_radar_authority_matches(path, repo=root, ref=head)
    }
    assert not denied, f"Permanent hard-deny changes: {sorted(denied)}"
    protected = {path for path in changed if path.startswith(("financial_engine/", "finco_core/", "domain/"))}
    # An unchanged baseline remains valid; any release diff must be the complete reviewed slice.
    if not protected:
        return
    # Revenue V2 Correction C: exact one-path, one-content successor authority.
    # Keep F3.5-A's complete historical release slice and pins untouched.
    from model_v2_governance import REVENUE_V2_ADVANCED_AUTHORITIES
    if protected == set(REVENUE_V2_ADVANCED_AUTHORITIES):
        for path, pin in REVENUE_V2_ADVANCED_AUTHORITIES.items():
            actual = git("rev-parse", "--verify", f"{head}:{path}")
            assert git("cat-file", "-t", actual) == "blob", f"Missing Revenue V2 authority blob: {path}"
            assert actual == pin, f"Unreviewed Revenue V2 content: {path}"
        return
    # RC-2 Revenue V3: reviewer-conditional, release-closed candidate successor. Exactly this three-path slice at
    # exactly these three blobs; any extra/missing protected path or any other content still fails below.
    from model_v2_governance import REVENUE_V3_CANDIDATE_AUTHORITIES
    if protected == set(REVENUE_V3_CANDIDATE_AUTHORITIES):
        for path, pin in REVENUE_V3_CANDIDATE_AUTHORITIES.items():
            actual = git("rev-parse", "--verify", f"{head}:{path}")
            assert git("cat-file", "-t", actual) == "blob", f"Missing Revenue V3 authority blob: {path}"
            assert actual == pin, f"Unreviewed Revenue V3 content: {path}"
        return
    # RC-3 C2: the PPA-01 candidate slice - exactly these three paths at exactly these three blobs. This recognises CONTENT only (a release-closed
    # candidate); it is not financial approval or release (see tests/ppa01_candidate_authority.py). Any extra/missing path or other content fails.
    from ppa01_candidate_authority import PPA01_CANDIDATE_AUTHORITIES
    if protected == set(PPA01_CANDIDATE_AUTHORITIES):
        for path, pin in PPA01_CANDIDATE_AUTHORITIES.items():
            actual = git("rev-parse", "--verify", f"{head}:{path}")
            assert git("cat-file", "-t", actual) == "blob", f"Missing PPA-01 candidate blob: {path}"
            assert actual == pin, f"Unreviewed PPA-01 candidate content: {path}"
        return
    # RC-7B: the twelve-blob quarterly candidate slice is recognised ONLY while the merged release-closed candidate is exactly present (PR #320 merge
    # ancestry, exact blobs, literal ACTIVATION_ENABLED=False) or a complete Gate R is active. Recognition of bytes only: no financial approval,
    # admission, release or merge. Otherwise this slice falls through to the failure below, exactly as before.
    from rc7b_quarterly_candidate_authority import RC7B_CANDIDATE_AUTHORITIES
    from quarterly_candidate_recognition import candidate_blobs, candidate_recognized
    if protected == set(RC7B_CANDIDATE_AUTHORITIES) and candidate_recognized(repo=root, ref=head):
        for path, pin in candidate_blobs(repo=root, ref=head).items():
            actual = git("rev-parse", "--verify", f"{head}:{path}")
            assert git("cat-file", "-t", actual) == "blob", f"Missing RC-7B candidate blob: {path}"
            assert actual == pin, f"Unreviewed RC-7B candidate content: {path}"
        return
    # RC-7C: against a main that already carries the merged RC-7B candidate, the release-closed RC-7C candidate changes exactly four of the twelve
    # blobs. Recognised only while the whole RC-7C contract holds (eight unchanged RC-7B blobs, four pinned RC-7C blobs, no other protected change,
    # closed flag, merge ancestry). Bytes only: not financial approval, admission or release. Any other four-path diff falls through to the failure.
    from rc7c_candidate_successor import RC7C_CANDIDATE_AUTHORITIES, RC7C_CHANGED_PATHS, rc7c_recognized
    if protected == set(RC7C_CHANGED_PATHS) and rc7c_recognized(repo=root, ref=head):
        for path in sorted(protected):
            actual = git("rev-parse", "--verify", f"{head}:{path}")
            assert git("cat-file", "-t", actual) == "blob", f"Missing RC-7C candidate blob: {path}"
            assert actual == RC7C_CANDIDATE_AUTHORITIES[path], f"Unreviewed RC-7C candidate content: {path}"
        return
    # V9-P2a OD-R: against a main that carries RC-7C, the release-closed OD-R successor changes exactly six protected paths (four blobs under the
    # Financial Owner's exact-content decision, two carried). Recognised only while the whole OD-R contract holds (RC-7C checkpoints, exact blobs,
    # no other protected change, pinned hub, closed flags). Bytes only: not merge authorisation, activation or release. Any other diff falls through.
    from v9p2a_odr_successor import ODR_AUTHORITIES, odr_recognized
    if protected == set(ODR_AUTHORITIES) and odr_recognized(repo=root, ref=head):
        for path in sorted(protected):
            actual = git("rev-parse", "--verify", f"{head}:{path}")
            assert git("cat-file", "-t", actual) == "blob", f"Missing OD-R successor blob: {path}"
            assert actual == ODR_AUTHORITIES[path], f"Unreviewed OD-R content: {path}"
        return
    assert protected == _F3_5_REVIEWED_PROTECTED_PATHS, f"Unapproved or incomplete protected diff: {sorted(protected)}"
    for path in sorted(protected):
        actual = git("rev-parse", "--verify", f"{head}:{path}")
        assert git("cat-file", "-t", actual) == "blob", f"Missing approved blob: {path}"
        assert actual == pins[path], f"Unreviewed financial blob: {path}"


def test_frozen_financial_namespaces_unmodified():
    _assert_frozen_financial_namespace_authority(Path(__file__).resolve().parents[1])


@pytest.fixture
def reviewed_financial_git_repo(tmp_path):
    from model_v2_governance import F3_5_A_JUNIOR_AUTHORITIES

    def git(*args):
        return subprocess.run(["git", *args], cwd=tmp_path, capture_output=True, check=True).stdout

    git("init")
    git("config", "core.autocrlf", "false")
    git("config", "user.name", "Synthetic Governance")
    git("config", "user.email", "synthetic.invalid")
    for path in F3_5_A_JUNIOR_AUTHORITIES:
        target = tmp_path / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"Synthetic historical baseline\n")
    git("add", ".")
    git("commit", "-m", "Synthetic baseline")
    git("update-ref", "refs/remotes/origin/main", "HEAD")
    root = Path(__file__).resolve().parents[1]
    for path, blob in F3_5_A_JUNIOR_AUTHORITIES.items():
        source = subprocess.run(["git", "cat-file", "blob", blob], cwd=root, capture_output=True, check=True).stdout
        (tmp_path / path).write_bytes(source)
    git("add", ".")
    git("commit", "-m", "Exact reviewed release")
    return tmp_path, git


def test_financial_namespace_guard_accepts_exact_reviewed_content(reviewed_financial_git_repo):
    root, _ = reviewed_financial_git_repo
    _assert_frozen_financial_namespace_authority(root)


def test_financial_namespace_guard_accepts_unchanged_baseline(reviewed_financial_git_repo):
    root, _ = reviewed_financial_git_repo
    _assert_frozen_financial_namespace_authority(root, ref="origin/main")


@pytest.mark.parametrize("path", [
    "financial_engine/financing/unapproved.py", "finco_core/inputs/unapproved.py",
    "financial_engine/financing/junior_debt.py.extra", "domain/unapproved.py",
    "finco_radar/unapproved.py", "finco_yield/unapproved.py", "app/radar_rwa/unapproved.py",
    "app/crypto_access.py", "app/crypto_resource_access.py",
])
def test_financial_namespace_guard_rejects_unrelated_or_hard_denied_path(reviewed_financial_git_repo, path):
    root, git = reviewed_financial_git_repo
    target = root / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(b"Synthetic unauthorized content\n")
    git("add", path)
    git("commit", "-m", "Unreviewed path")
    with pytest.raises(AssertionError, match="hard-deny|protected diff"):
        _assert_frozen_financial_namespace_authority(root)


def _commit_pinned_radar_blobs(root, git, *, alter=None):
    from radar_authority_governance import REVIEWED_RADAR_AUTHORITY_BLOBS

    original = Path(__file__).resolve().parents[1]
    for path, blob in REVIEWED_RADAR_AUTHORITY_BLOBS.items():
        source = subprocess.run(["git", "cat-file", "blob", blob], cwd=original,
                                capture_output=True, check=True).stdout
        if path == alter:
            source += b"\n"
        target = root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(source)
    git("add", ".")
    git("commit", "-m", "Radar release")


def test_financial_namespace_guard_accepts_exact_reviewed_radar_blobs(reviewed_financial_git_repo):
    root, git = reviewed_financial_git_repo
    _commit_pinned_radar_blobs(root, git)
    _assert_frozen_financial_namespace_authority(root)


@pytest.mark.parametrize("path", [
    "app/radar_rwa/r_live_service.py",
    "finco_radar/venues/intelligence.py",
    "finco_radar/venues/robinhood_live.py",
])
def test_financial_namespace_guard_rejects_one_byte_change_to_reviewed_radar_blob(
        reviewed_financial_git_repo, path):
    root, git = reviewed_financial_git_repo
    _commit_pinned_radar_blobs(root, git, alter=path)
    with pytest.raises(AssertionError, match="hard-deny"):
        _assert_frozen_financial_namespace_authority(root)


@pytest.mark.parametrize("sibling", [
    "finco_radar/venues/unreviewed_sibling.py",
    "app/radar_rwa/unreviewed_sibling.py",
    "finco_yield/unreviewed.py",
    "app/crypto_access.py",
    "app/crypto_resource_access.py",
])
def test_financial_namespace_guard_denies_unreviewed_sibling_even_with_reviewed_radar_blobs(
        reviewed_financial_git_repo, sibling):
    root, git = reviewed_financial_git_repo
    _commit_pinned_radar_blobs(root, git)
    target = root / sibling
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(b"Synthetic unauthorized content\n")
    git("add", sibling)
    git("commit", "-m", "Unreviewed sibling")
    with pytest.raises(AssertionError, match="hard-deny"):
        _assert_frozen_financial_namespace_authority(root)


@pytest.mark.parametrize("content", ["altered", "historical"])
def test_financial_namespace_guard_rejects_altered_approved_blob(reviewed_financial_git_repo, content):
    root, git = reviewed_financial_git_repo
    path = "financial_engine/book_basis.py"
    target = root / path
    if content == "historical":
        from model_v2_governance import DEVELOPER_ECONOMICS_V1_AUTHORITIES

        original = Path(__file__).resolve().parents[1]
        source = subprocess.run(["git", "cat-file", "blob", DEVELOPER_ECONOMICS_V1_AUTHORITIES[path]],
                                cwd=original, capture_output=True, check=True).stdout
        target.write_bytes(source)
    else:
        target.write_bytes(target.read_bytes() + b"\n# Synthetic unreviewed alteration.\n")
    git("add", path)
    git("commit", "-m", "Unreviewed blob")
    with pytest.raises(AssertionError, match="Unreviewed financial blob"):
        _assert_frozen_financial_namespace_authority(root)


def test_financial_namespace_guard_rejects_missing_approved_blob(reviewed_financial_git_repo):
    root, git = reviewed_financial_git_repo
    git("rm", "financial_engine/book_basis.py")
    git("commit", "-m", "Missing reviewed blob")
    with pytest.raises(AssertionError, match="Git authority unavailable"):
        _assert_frozen_financial_namespace_authority(root)


@pytest.mark.parametrize("change", ["partial", "extra", "altered-pin"])
def test_financial_namespace_guard_rejects_incomplete_or_changed_pin_map(reviewed_financial_git_repo, change):
    from model_v2_governance import F3_5_A_JUNIOR_AUTHORITIES

    root, _ = reviewed_financial_git_repo
    pins = dict(F3_5_A_JUNIOR_AUTHORITIES)
    if change == "partial":
        pins.pop("financial_engine/book_basis.py")
    elif change == "extra":
        pins["domain/unapproved.py"] = "a" * 40
    else:
        pins["financial_engine/book_basis.py"] = "a" * 40
    with pytest.raises(AssertionError, match="reviewed pins"):
        _assert_frozen_financial_namespace_authority(root, authorities=pins)


def test_financial_namespace_guard_rejects_incomplete_actual_release(reviewed_financial_git_repo):
    root, git = reviewed_financial_git_repo
    path = "financial_engine/book_basis.py"
    (root / path).write_bytes(git("show", f"origin/main:{path}"))
    git("add", path)
    git("commit", "-m", "Partial release")
    with pytest.raises(AssertionError, match="incomplete protected diff"):
        _assert_frozen_financial_namespace_authority(root)


@pytest.mark.parametrize("change", ["partial", "extra"])
def test_financial_namespace_guard_rejects_tampered_release_map(reviewed_financial_git_repo, monkeypatch, change):
    import model_v2_governance as governance

    root, _ = reviewed_financial_git_repo
    pins = dict(governance.F3_5_A_JUNIOR_AUTHORITIES)
    if change == "partial":
        pins.pop("financial_engine/book_basis.py")
    else:
        pins["domain/unapproved.py"] = "a" * 40
    monkeypatch.setattr(governance, "F3_5_A_JUNIOR_AUTHORITIES", pins)
    with pytest.raises(AssertionError, match="Incomplete or extra F3.5 release authority"):
        _assert_frozen_financial_namespace_authority(root)


def test_financial_namespace_guard_rejects_missing_review_ref(reviewed_financial_git_repo):
    root, _ = reviewed_financial_git_repo
    with pytest.raises(AssertionError, match="Git authority unavailable"):
        _assert_frozen_financial_namespace_authority(root, ref="missing-reviewed-ref")


@pytest.mark.parametrize("role", list(REQUIRED))
def test_missing_mandatory_browser_capture_fails(role, tmp_path):
    (tmp_path / "artifacts").mkdir()
    with pytest.raises(EvidenceError, match="Missing mandatory"):
        manifest(role, tmp_path)


@pytest.mark.parametrize("status", ["failure", "cancelled", "skipped", "", None])
def test_browser_matrix_non_success_cannot_pass(status, tmp_path):
    with pytest.raises(EvidenceError, match="Browser matrix"):
        validate_browser_records(tmp_path, HEAD, TREE, status)


def test_browser_missing_artifact_cannot_pass(tmp_path):
    with pytest.raises(FileNotFoundError):
        validate_browser_records(tmp_path, HEAD, TREE, "success")


def test_existing_browser_selection_is_not_weakened():
    assert SELECTIONS["protocol"] == [
        "tests/test_ui_protocol_shell.py", "tests/test_protocol_roadmap_browser.py",
        "tests/test_crypto_navigation_browser.py", "tests/test_ev_charging_browser.py",
        "tests/test_yield_browser.py", "-k", "not test_api_b04_placeholders_not_links"]
    # The original Import C suite is kept first and unchanged; the Import V2 module was ADDED to the same role.
    assert SELECTIONS["import"][0] == "tests/test_model_ai_import_browser_c.py"
    assert SELECTIONS["import"] == ["tests/test_model_ai_import_browser_c.py", "tests/test_model_import_v2_browser.py",
                                    "tests/test_model_import_excel_migration_browser.py",
                                    "tests/test_model_wf09_capex_profile_browser.py"]
    assert "artifacts/model-ai-import/*.png" in REQUIRED["import"] and "artifacts/model-import-v2/*.png" in REQUIRED["import"]
    assert SELECTIONS["grid"] == ["tests/test_model_hybrid_inputs_grid_routes.py", "tests/test_model_hybrid_inputs_grid_browser.py"]
    assert SELECTIONS["q4"] == ["tests/test_model_q4_browser.py"]
    assert SELECTIONS["consolidation"] == ["tests/test_model_workspace_consolidation_browser.py"]
    assert REQUIRED["consolidation"] == ["artifacts/workspace-consolidation/prb-*.png"]


def test_required_gate_triggers_do_not_depend_on_changed_paths():
    root = Path(__file__).resolve().parents[1]
    for name in ("public_safety_and_smoke", "protocol_ui_browser", "pr_compile_and_safety", "governance_history", "dependency_security_audit"):
        text = (root / ".github" / "workflows" / (name + ".yml")).read_text(encoding="utf-8")
        assert "pull_request:" in text
        assert "paths:" not in text
        assert "head.sha" in text


def _workflow(name):
    import yaml
    path = Path(__file__).resolve().parents[1] / ".github/workflows" / name
    return yaml.safe_load(path.read_text(encoding="utf-8")), path.read_text(encoding="utf-8")


def test_shadow_does_not_replace_unsharded_gate_or_merge_coverage():
    """Retained full sequential control and independently verified protected route.

    Sequential remains ONE unsharded, undeselected invocation. The activated
    alternative preserves complete original coverage and independently verifies
    all workers; neither route may rerun a selected failure into success.
    """
    public, public_text = _workflow("public_safety_and_smoke.yml")
    reusable, reusable_text = _workflow("ci_public_job.yml")
    jobs = public["jobs"]
    assert set(jobs) == {"source-safety", "safety-and-smoke", "mandatory-evidence"}      # seven-job budget, no shards
    control = jobs["safety-and-smoke"]
    assert control["uses"].endswith("ci_v3_required_job.yml") and control["with"]["mode"] == "control"
    router, _ = _workflow("ci_v3_required_job.yml")
    assert router["jobs"]["sequential"]["uses"].endswith("ci_public_job.yml")
    assert router["jobs"]["sequential"]["with"]["mode"] == "control"
    assert "tools.ci_v3_mandatory verify" in "\n".join(s.get("run", "") for s in router["jobs"]["aggregate"]["steps"])
    assert {"merge-sha", "pr-number", "tested-sha"} <= set(control["with"])
    gate = jobs["mandatory-evidence"]
    assert gate["if"] == "always()" and set(gate["needs"]) == {"source-safety", "safety-and-smoke"}
    gate_runs = "\n".join(step.get("run", "") for step in gate["steps"])
    assert "tools.ci_single_gate" in gate_runs and "--source-result" in gate_runs and "--control-result" in gate_runs
    assert "continue-on-error" not in public_text and "continue-on-error" not in reusable_text

    steps = reusable["jobs"]["tests"]["steps"]
    runs = [step.get("run", "") for step in steps]
    index = lambda needle: next(i for i, r in enumerate(runs) if needle in r)   # noqa: E731
    guard, install, pytest_step = index("ci_merge_tree_guard"), index("pip install"), index("ci_pytest_runner.py")
    assert guard < install < pytest_step, "tree equality must be proven before dependencies and before pytest"
    invocation = runs[pytest_step].split("ci_pytest_runner.py", 1)[1]      # pytest's own arguments only
    import re
    assert not re.search(r"(?<!\S)(-k|-m|-x|--lf|--deselect|--ignore|--maxfail|--ci-shard)\b", invocation), invocation
    assert "--ci-inventory=artifacts/inventory.json" in invocation and "--junitxml=artifacts/results.xml" in invocation
    assert "$MODE" not in runs[pytest_step] and "shard" not in invocation, "no per-mode selection branches"
    assert "ci_pytest_runner.py" in runs[pytest_step]                           # the supervisor stays authoritative


def test_ci_workflows_do_not_reintroduce_shadow_or_duplicate_execution_paths():
    public, _ = _workflow("public_safety_and_smoke.yml")
    reusable, reusable_text = _workflow("ci_public_job.yml")
    assert "--ci-shard" not in reusable_text and "shadow" not in "".join(public["jobs"])
    assert not any(name in public["jobs"] for name in ("merge-result-integration", "shadow-shards"))


@pytest.mark.parametrize("markers,expected", [(True, 0), (False, 1)])
def test_full_progress_is_not_normal_process_exit_proof(markers, expected, tmp_path, monkeypatch):
    monkeypatch.setattr("tools.ci_acceptance.attest", lambda value: {"head": HEAD, "tree": TREE})
    monkeypatch.setattr("tools.ci_acceptance.environment_digest", lambda: "environment")
    code = "# ci_pytest_runner.py\nprint('100%')\n"
    if markers:
        code += "print('PYTEST_MAIN_RETURNED FINCO_CI_MARKER after pytest.main rc=0')\n"
        code += "print('PYTHON_PROCESS_EXITED FINCO_CI_SUPERVISOR child exit code 0')\n"
    output = tmp_path / "process.json"
    result = run_command(argparse.Namespace(expected=HEAD, label="synthetic", output=output,
                                           junit=None, command=[sys.executable, "-c", code]))
    record = json.loads(output.read_text(encoding="utf-8"))
    assert result == expected
    assert record["normal_exit"] == markers


def test_measurement_nearest_rank_p90_does_not_invent_samples():
    assert distribution([]) is None
    assert distribution([1, 2, 3]) == {"samples": 3, "median": 2, "p90_nearest_rank": 3, "maximum": 3}


def test_accepted_consolidation_gates_both_browser_matrices():
    """CI V2 contract: ONE runner, SIX isolated supervised role processes, tree-equality instead of a second matrix.

    The #247 structure (two six-role matrices) is replaced; what it protected is asserted directly: every
    mandatory role (including the 17-node consolidation module) runs in its own fresh Python/pytest process
    with its own temp dir, a role failure fails the job, and the fail-closed aggregate runs after all roles.
    """
    browser, text = _workflow("protocol_ui_browser.yml")
    assert list(browser["jobs"]) == ["mandatory-browser-evidence"]                      # stable required context
    steps = {step.get("name", ""): step for step in browser["jobs"]["mandatory-browser-evidence"]["steps"]}
    roles = next(step for name, step in steps.items() if name.startswith("All SIX mandatory browser roles"))
    script = roles["run"]
    assert "for role in protocol import grid q4 outputs consolidation; do" in script
    assert set("protocol import grid q4 outputs consolidation".split()) == set(REQUIRED) == {
        *REQUIRED} and "consolidation" in SELECTIONS
    assert 'python -m tools.ci_browser_job "$role" --expected "$HEAD_SHA"' in script      # fresh process per role
    assert 'TMPDIR="$RUNNER_TEMP/finco-browser-$role"' in script                          # isolated temp per role
    assert 'mv artifacts "evidence/browser-$role"' in script                              # per-role evidence bundle
    assert script.index("done") < script.index("ci_browser_job aggregate")                 # aggregate after every role
    assert "set -euo pipefail" in script and "--job-result success" in script
    assert "continue-on-error" not in text and "merge-result-browser" not in browser["jobs"]
    names = list(steps)
    guard, install = (next(i for i, n in enumerate(names) if k in n) for k in ("synthetic merge tree", "Install and attest"))
    assert guard < install, "tree equality is proven before any dependency or Chromium installation"
    assert any(step.get("with", {}).get("name") == "model-workspace-consolidation-browser" for step in steps.values())
    assert any(step.get("with", {}).get("if-no-files-found") == "error" for step in steps.values())


def test_consolidation_missing_collection_rejected(tmp_path):
    with pytest.raises(EvidenceError, match="collection"):
        validate_consolidation(tmp_path, {"selected": [], "collected": [], "outcomes": {}},
                               {"normal_exit": True, "exit_code": 0})


@pytest.mark.parametrize("status", ["skipped", "xfail", "failed", "error", "xpass"])
def test_consolidation_non_pass_result_rejected(tmp_path, status):
    nodes = [f"tests/test_model_workspace_consolidation_browser.py::test_{i}" for i in range(17)]
    outcomes = {node: {"status": "passed"} for node in nodes}
    outcomes[nodes[-1]] = {"status": status}
    with pytest.raises(EvidenceError, match="failed/skipped"):
        validate_consolidation(tmp_path, {"selected": nodes, "collected": nodes,
                                         "deselected": [], "outcomes": outcomes},
                               {"normal_exit": True, "exit_code": 0})


def test_consolidation_missing_junit_fails_closed(tmp_path):
    nodes = [f"tests/test_model_workspace_consolidation_browser.py::test_{i}" for i in range(17)]
    with pytest.raises(EvidenceError, match="JUnit"):
        validate_consolidation(tmp_path, {"selected": nodes, "collected": nodes,
                                         "deselected": [], "outcomes": {n: {"status": "passed"} for n in nodes}},
                               {"normal_exit": True, "exit_code": 0})


@pytest.fixture
def reviewed_revenue_v2_git_repo(tmp_path):
    from model_v2_governance import REVENUE_V2_ADVANCED_AUTHORITIES

    def git(*args):
        return subprocess.run(["git", *args], cwd=tmp_path, capture_output=True, check=True).stdout

    assert set(REVENUE_V2_ADVANCED_AUTHORITIES) == {"domain/revenue/multistream_runtime.py"}
    git("init")
    git("config", "core.autocrlf", "false")
    git("config", "user.name", "Synthetic Revenue Governance")
    git("config", "user.email", "synthetic.invalid")
    path = "domain/revenue/multistream_runtime.py"
    target = tmp_path / path
    target.parent.mkdir(parents=True)
    target.write_bytes(b"Synthetic baseline Revenue runtime\\n")
    git("add", ".")
    git("commit", "-m", "Synthetic baseline")
    git("update-ref", "refs/remotes/origin/main", "HEAD")
    root = Path(__file__).resolve().parents[1]
    actual = subprocess.run(["git", "cat-file", "blob", REVENUE_V2_ADVANCED_AUTHORITIES[path]],
                            cwd=root, capture_output=True, check=True).stdout
    target.write_bytes(actual)
    git("add", path)
    git("commit", "-m", "Exact Revenue V2 accepted blob")
    return tmp_path, git


def test_frozen_guard_accepts_only_exact_revenue_v2_successor(reviewed_revenue_v2_git_repo):
    root, _ = reviewed_revenue_v2_git_repo
    _assert_frozen_financial_namespace_authority(root)


def test_frozen_guard_rejects_one_byte_changed_revenue_v2_successor(reviewed_revenue_v2_git_repo):
    root, git = reviewed_revenue_v2_git_repo
    path = "domain/revenue/multistream_runtime.py"
    target = root / path
    target.write_bytes(target.read_bytes() + b"x")
    git("add", path)
    git("commit", "-m", "Unapproved altered Revenue blob")
    with pytest.raises(AssertionError, match="Unreviewed Revenue V2 content"):
        _assert_frozen_financial_namespace_authority(root)


def test_frozen_guard_rejects_revenue_v2_plus_unapproved_domain_path(reviewed_revenue_v2_git_repo):
    root, git = reviewed_revenue_v2_git_repo
    path = root / "domain/revenue/unapproved.py"
    path.write_text("unauthorized = True\\n", encoding="utf-8")
    git("add", "domain/revenue/unapproved.py")
    git("commit", "-m", "Unapproved domain path")
    with pytest.raises(AssertionError, match="Unapproved or incomplete protected diff"):
        _assert_frozen_financial_namespace_authority(root)


@pytest.fixture
def revenue_v3_git_repo(tmp_path):
    from model_v2_governance import REVENUE_V3_CANDIDATE_AUTHORITIES

    def git(*args):
        return subprocess.run(["git", *args], cwd=tmp_path, capture_output=True, check=True).stdout

    git("init")
    git("config", "core.autocrlf", "false")
    git("config", "user.name", "Synthetic Governance")
    git("config", "user.email", "synthetic.invalid")
    for path in REVENUE_V3_CANDIDATE_AUTHORITIES:
        target = tmp_path / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"Synthetic historical baseline\n")
    git("add", ".")
    git("commit", "-m", "Synthetic baseline")
    git("update-ref", "refs/remotes/origin/main", "HEAD")
    root = Path(__file__).resolve().parents[1]
    for path, blob in REVENUE_V3_CANDIDATE_AUTHORITIES.items():
        (tmp_path / path).write_bytes(subprocess.run(["git", "cat-file", "blob", blob], cwd=root, capture_output=True, check=True).stdout)
    git("add", ".")
    git("commit", "-m", "Exact reviewed Revenue V3 candidate")
    return tmp_path, git


def test_revenue_v3_candidate_slice_is_accepted_only_at_the_exact_three_blobs(revenue_v3_git_repo):
    root, git = revenue_v3_git_repo
    _assert_frozen_financial_namespace_authority(root)
    for path in ("domain/revenue/advanced_products.py", "domain/revenue/multistream_runtime.py", "finco_core/revenue/generation.py"):
        (root / path).write_bytes((root / path).read_bytes() + b"# unreviewed\n")
        git("add", ".")
        git("commit", "-m", "Further edit " + path)
        with pytest.raises(AssertionError, match="Unreviewed Revenue V3 content"):
            _assert_frozen_financial_namespace_authority(root)
        git("reset", "--hard", "HEAD~1")
    # an additional protected path turns the slice into an unapproved diff
    extra = root / "financial_engine" / "unreviewed.py"
    extra.parent.mkdir(parents=True, exist_ok=True)
    extra.write_bytes(b"x = 1\n")
    git("add", ".")
    git("commit", "-m", "Extra protected path")
    with pytest.raises(AssertionError, match="Unapproved or incomplete protected diff"):
        _assert_frozen_financial_namespace_authority(root)
    git("reset", "--hard", "HEAD~1")
    # a missing path is an incomplete slice
    (root / "finco_core/revenue/generation.py").write_bytes(b"Synthetic historical baseline\n")
    git("add", ".")
    git("commit", "-m", "Revert one path")
    with pytest.raises(AssertionError, match="Unapproved or incomplete protected diff"):
        _assert_frozen_financial_namespace_authority(root)
