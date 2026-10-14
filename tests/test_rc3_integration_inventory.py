"""RC-3 combined integration inventory (REVIEW PROPOSAL - not an approval of any financial authority).

Binds the integrated HEAD to the union of the five reviewed source heads. The oracle is live Git state of the pinned source commits
and the pinned base, NOT values generated from the current tree:

 1. exact integration base (commit + tree) and the historical RC-1/RC-2 checkpoints;
 2. the five pinned source heads, present and ancestors of HEAD;
 3. the five ordered ``--no-ff`` merge commits: first parent chain from the base, second parent == the pinned source head;
 4. inclusion of every source tree: each path a source changed carries that source's blob at HEAD, unless it is a DOCUMENTED shared
    path (auto-merge paths must equal an independent ``git merge-file`` of the sources; hand-resolved paths are pinned);
 5. exact integrated path/status inventory == union of the source diffs + the explicit INTEGRATION_ADDED / INTEGRATION_EDITED lists;
 6. exact financial / security / model-authority blobs: every change under a frozen namespace is a source-owned M7 path whose blob
    equals the reviewed M7 head, and the eleven protected blobs of the M7 candidate manifest match;
 7. no unexplained source-content replacement (the multi-source overlap set must equal the documented shared set);
 8. documented shared-file resolutions keep every source's distinguishing markers;
 9. protected workflows, test selection, tolerances and goldens are byte-identical to the base;
10. release-closed flags are literal ``False`` and the M7 candidate manifest stays ``release_approved:false``.

Passing this file is NOT a financial approval: M7 candidate acceptance and production activation are separate decisions that are
still pending (see docs/rc3/RC3_INTEGRATION_CORRECTION_A.md). The owner gates over financial authority stay red until then.
"""
import copy
import json
import subprocess
import tempfile
from pathlib import Path

import pytest

from tests.test_rc2_integration_manifest import (
    RC2_ACCEPTED_HEAD, RC2_ACTIVATION_FLAG_FILES, RC2_BASE_MAIN, RC2_CI_WORKFLOW, RC2_CI_WORKFLOW_CANDIDATE_BLOB, RC2_MERGE_COMMIT,
    activation_state,
)
from tests.test_trust_readiness_registry import RC1_BASE_MAIN, RC1_MERGED_CHECKPOINT, RC1_MERGED_PARENTS

ROOT = Path(__file__).resolve().parent.parent
BASE = RC2_MERGE_COMMIT                                    # 6fc77de - the integration base (current main)
BASE_TREE = "4fdcd03b5e0ed3c4b87d9016f2522bfe50bf0d05"
SOURCES = (                                                # merge order; PR number -> reviewed head
    (280, "8378e5df30ec10b4de2b2f5330491837a7cd1ffb"),
    (279, "9f93dc843eed8f2f2cf7f11cf409fffd003ce70f"),
    (281, "5c6963879d8bdf0a16458011a5cfe6011fd36021"),
    (282, "63f1ded39ab90db24f3503c9fe62e9d7029ea017"),
    (283, "62424a8b777133631f4253d75848ba8c846f83e6"),
)
M7_PR = 283
STREAM_TIP = "f2a1e386481b11a0a2b5fb8a73206403c839a480"   # merge of #282: every non-financial stream, not M7
FROZEN_PREFIXES = ("financial_engine/", "finco_core/", "domain/", "finco_radar/", "finco_yield/", "app/radar_rwa/")
GUARDED_PREFIXES = (".github/",)
GUARDED_FILES = ("pytest.ini", "requirements.txt", "requirements-ci-tests.txt", "constraints.txt", "pyproject.toml")
GUARDED_NAME_PARTS = ("tolerance", "golden")                # financial tolerances / goldens: byte-identical to the base
M7_MANIFEST = "docs/model_v2/M7_BESS_FINANCIAL_CANDIDATE_MANIFEST.json"
FLAG_FILES = {**RC2_ACTIVATION_FLAG_FILES, "app/workbook/bess_config.py": "ACTIVATION_ENABLED",
              "app/model_v2/acquisition/economics.py": "ACTIVATION_ENABLED"}

# Paths touched by two or more sources whose union is produced by an independent three-way merge (no hand edits allowed).
AUTO_MERGED = {
    "app/api/project_runner.py": (282, 283),
    "app/v2/router.py": (282, 283),
    "app/templates/v2/workbook.html": (281, 283),
}
# Paths that needed a hand resolution. Their final content is a reviewed literal pin plus mandatory markers of every source.
HAND_RESOLVED = {
    "tests/test_rc2_integration_manifest.py": {
        "markers": ("R4_REVIEWED_HEAD", "R4_SUCCESSOR_BLOBS", "RC2_ACCEPTED_HEAD", "duplicate cumulative diff entry"),
    },
    "tests/test_trust_readiness_controls.py": {
        "markers": ("current_m6_successor_valid", "current_m7_successor_valid", "app/v2/acquisition_router.py", "CSRF_PROPOSAL"),
    },
    "tests/test_trust_readiness_registry.py": {
        "markers": ("_m6_exact_successor_valid", "_m7_successor_valid", "_csrf_call_sites_at", "_rc1_collect_post"),
    },
}
# Markers every auto-merged file must keep from EACH side (both sources' distinguishing content).
AUTO_MARKERS = {
    "app/api/project_runner.py": ("acquisition_source_candidate_v1", "bess_operating_audit"),
    "app/v2/router.py": ("bind_acquisition_source", "bess_candidate_router", "bess_workspace_router"),
    "app/templates/v2/workbook.html": ("model_diagnostics_v2.js", "model_bess_workspace.js"),
}
# Files the INTEGRATION itself added (not in any source) or edited on top of the sources. Literal reviewed blobs; the two files
# that cannot pin themselves (this test and its helper) are listed by path and reviewed as exact commit files.
INTEGRATION_ADDED = frozenset({
    "tests/test_rc3_r5_successor.py",
    "tests/rc3_historical_anchor.py",
    "tests/test_rc3_integration_inventory.py",
    "docs/rc3/RC3_INTEGRATION_CORRECTION_A.md",
})
INTEGRATION_SELF = frozenset({"tests/test_rc3_integration_inventory.py", "tests/rc3_historical_anchor.py"})


def git(*args):
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, check=True).stdout.strip()


def _tree(ref):
    """path -> blob for every file at ``ref`` (one Git call)."""
    out = {}
    for line in git("ls-tree", "-r", ref).splitlines():
        meta, path = line.split("\t", 1)
        out[path] = meta.split()[2]
    return out


def _status(a, b):
    rows = {}
    for line in git("diff", "--name-status", "--no-renames", a, b).splitlines():
        status, path = line.split("\t", 1)
        rows.setdefault(path, []).append(status)
    return rows


def _show(ref, path):
    return git("show", f"{ref}:{path}")


def _auto_merge_blob(path, a_pr, b_pr, heads):
    with tempfile.TemporaryDirectory() as tmp:
        files = {}
        for name, ref in (("a", heads[a_pr]), ("base", BASE), ("b", heads[b_pr])):
            target = Path(tmp) / name
            target.write_bytes(subprocess.run(["git", "show", f"{ref}:{path}"], cwd=ROOT, capture_output=True, check=True).stdout)
            files[name] = str(target)
        merged = subprocess.run(["git", "merge-file", "-p", files["a"], files["base"], files["b"]], cwd=ROOT, capture_output=True)
        if merged.returncode != 0:
            return None                                          # a conflict: no clean independent merge exists
        return subprocess.run(["git", "hash-object", "--stdin"], cwd=ROOT, input=merged.stdout, capture_output=True,
                              check=True).stdout.decode().strip()


def collect(ref="HEAD"):
    heads = dict(SOURCES)
    trees = {pr: _tree(sha) for pr, sha in SOURCES}
    head_tree, base_tree = _tree(ref), _tree(BASE)
    source_status = {pr: {p: s[0] for p, s in _status(BASE, sha).items()} for pr, sha in SOURCES}
    merge_rows = [r.split() for r in git("rev-list", "--first-parent", "--merges", "--reverse", "--parents", f"{BASE}..{ref}").splitlines()]
    return {
        "base": git("rev-parse", f"{BASE}^{{commit}}"), "base_tree": git("rev-parse", f"{BASE}^{{tree}}"),
        "base_parents": tuple(git("rev-list", "--parents", "-n", "1", BASE).split()[1:]),
        "rc1_parents": tuple(git("rev-list", "--parents", "-n", "1", RC1_MERGED_CHECKPOINT).split()[1:]),
        "heads": heads,
        "head_resolves": {pr: subprocess.run(["git", "cat-file", "-e", f"{sha}^{{commit}}"], cwd=ROOT).returncode == 0
                          for pr, sha in SOURCES},
        "ancestors": {pr: subprocess.run(["git", "merge-base", "--is-ancestor", sha, ref], cwd=ROOT).returncode == 0
                      for pr, sha in SOURCES},
        "merges": merge_rows,                                   # [merge, parent0, parent1] oldest first
        "source_status": source_status,
        "source_blobs": {pr: {p: trees[pr].get(p) for p in source_status[pr]} for pr, _ in SOURCES},
        "head_status": {p: s[0] for p, s in _status(BASE, ref).items()},
        "head_blobs": head_tree, "base_blobs": base_tree,
        "m7_manifest": json.loads(_show(ref, M7_MANIFEST)),
        "m7_manifest_at_source": json.loads(_show(heads[M7_PR], M7_MANIFEST)),
        "auto_merge_oracle": {p: _auto_merge_blob(p, a, b, heads) for p, (a, b) in AUTO_MERGED.items()},
        "texts": {p: _show(ref, p) for p in {**AUTO_MARKERS, **HAND_RESOLVED}},
        "flag_sources": {p: _show(ref, p) + "\n" for p in FLAG_FILES},
        "stream_tip_status": {p: s[0] for p, s in _status(BASE, STREAM_TIP).items()},
    }


def inventory_violations(f) -> list[str]:
    """Pure, fail-closed verifier over injected facts. [] means HEAD is exactly the documented union of the five sources."""
    try:
        bad = []
        # 1. base + historical checkpoints
        if f["base"] != BASE or f["base_tree"] != BASE_TREE:
            bad.append("integration base is not the exact reviewed main commit/tree")
        if f["base_parents"] != (RC2_BASE_MAIN, RC2_ACCEPTED_HEAD):
            bad.append("historical RC-2 merge provenance changed")
        if f["rc1_parents"] != RC1_MERGED_PARENTS or RC1_MERGED_CHECKPOINT != RC2_BASE_MAIN or RC1_BASE_MAIN not in RC1_MERGED_PARENTS:
            bad.append("historical RC-1 checkpoint provenance changed")
        # 2. sources
        if tuple(sorted(f["heads"].items())) != tuple(sorted(SOURCES)):
            bad.append("source head pins differ from the reviewed set")
        for pr, _ in SOURCES:
            if not f["head_resolves"].get(pr):
                bad.append(f"#{pr}: reviewed source head is missing from this checkout")
            if f["ancestors"].get(pr) is not True:
                bad.append(f"#{pr}: reviewed source head is not an ancestor of HEAD")
        # 3. ordered --no-ff merges
        merges = f["merges"]
        if len(merges) < len(SOURCES):
            bad.append("fewer first-parent merge commits than reviewed sources")
        else:
            previous = BASE
            for (pr, sha), row in zip(SOURCES, merges):
                if len(row) != 3 or row[2] != sha:
                    bad.append(f"#{pr}: merge second parent is not the pinned source head or merge is not a two-parent merge")
                if len(row) == 3 and row[1] != previous:
                    bad.append(f"#{pr}: merge first parent breaks the ordered --no-ff chain")
                previous = row[0]
        # 5/7. exact path+status inventory == union of sources + explicit integration lists
        owners = {}
        for pr, rows in f["source_status"].items():
            for path, status in rows.items():
                owners.setdefault(path, {})[pr] = status
        multi = {p for p, o in owners.items() if len(o) > 1}
        undocumented = multi - set(AUTO_MERGED) - set(HAND_RESOLVED)
        if undocumented:
            bad.append(f"paths changed by several sources without a documented resolution: {sorted(undocumented)}")
        expected_status = {}
        for path, o in owners.items():
            statuses = set(o.values())
            if statuses - {"A", "M"}:
                bad.append(f"{path}: source status {sorted(statuses)} is not an addition/modification")
            expected_status[path] = "A" if statuses == {"A"} else "M"
        for path in INTEGRATION_ADDED:
            if path in expected_status:
                bad.append(f"{path}: listed as integration-added but also changed by a source")
            expected_status[path] = "A"
        for path in PINNED_INTEGRATION_EDITS:                    # integration edits on top of main files or source files
            expected_status.setdefault(path, "M" if path in f["base_blobs"] else "A")
        actual = f["head_status"]
        for path in sorted(set(actual) - set(expected_status)):
            bad.append(f"{path}: not part of the reviewed union (unauthorized file)")
        for path in sorted(set(expected_status) - set(actual)):
            bad.append(f"{path}: reviewed path is missing from HEAD")
        for path, status in expected_status.items():
            if path in actual and actual[path] != status:
                bad.append(f"{path}: status {actual[path]} differs from reviewed {status}")
        # 4/7. content inclusion
        shared = set(AUTO_MERGED) | set(HAND_RESOLVED)
        for path, o in owners.items():
            if path in shared or path in PINNED_INTEGRATION_EDITS:
                continue
            blobs = {f["source_blobs"][pr].get(path) for pr in o}
            if len(blobs) != 1 or None in blobs:
                bad.append(f"{path}: source blobs disagree or are missing")
            elif f["head_blobs"].get(path) not in blobs:
                bad.append(f"{path}: source content replaced or altered at HEAD")
        for path in AUTO_MERGED:
            oracle = f["auto_merge_oracle"].get(path)
            if oracle is None:
                bad.append(f"{path}: no clean independent three-way merge exists (needs a documented resolution)")
            elif f["head_blobs"].get(path) != oracle:
                bad.append(f"{path}: differs from the independent three-way merge of its sources")
        # 8. markers
        for path, markers in {**AUTO_MARKERS, **{p: v["markers"] for p, v in HAND_RESOLVED.items()}}.items():
            for marker in markers:
                if marker not in f["texts"].get(path, ""):
                    bad.append(f"{path}: lost the marker {marker!r} of a source")
        for path, blob in PINNED_INTEGRATION_EDITS.items():
            if f["head_blobs"].get(path) != blob:
                bad.append(f"{path}: not the reviewed integration edit")
        # 6. financial / security / model-authority blobs
        m7 = f["source_status"][M7_PR]
        m7_frozen = {p for p in m7 if p.startswith(FROZEN_PREFIXES)}
        head_frozen = {p for p in actual if p.startswith(FROZEN_PREFIXES)}
        if head_frozen != m7_frozen:
            bad.append(f"frozen-namespace changes at HEAD differ from the reviewed M7 set: {sorted(head_frozen ^ m7_frozen)}")
        for path in m7_frozen:
            if f["head_blobs"].get(path) != f["source_blobs"][M7_PR].get(path):
                bad.append(f"{path}: financial blob differs from the reviewed M7 head")
        manifest = f["m7_manifest"]
        if manifest != f["m7_manifest_at_source"]:
            bad.append("M7 financial candidate manifest differs from the reviewed M7 head")
        if manifest.get("release_approved") is not False or manifest.get("status") != "CANDIDATE_REVIEW_ONLY":
            bad.append("M7 candidate manifest asserts a release it does not have")
        if len(manifest.get("protected_blobs", {})) != 11:
            bad.append("M7 candidate manifest does not list exactly the eleven protected blobs")
        for path, blob in manifest.get("protected_blobs", {}).items():
            if f["head_blobs"].get(path) != blob:
                bad.append(f"{path}: not the exact manifest-pinned M7 candidate blob")
        stream_tip_frozen = {p for p in f["stream_tip_status"] if p.startswith(FROZEN_PREFIXES)}
        if stream_tip_frozen:
            bad.append(f"the historical-stream anchor tip changes frozen namespaces: {sorted(stream_tip_frozen)}")
        # 9. protected workflows / test selection / tolerances / goldens
        guarded = [p for p in f["base_blobs"] if p.startswith(GUARDED_PREFIXES) or p in GUARDED_FILES
                   or any(part in p.lower() for part in GUARDED_NAME_PARTS)]
        for path in guarded:
            if f["head_blobs"].get(path) != f["base_blobs"].get(path):
                bad.append(f"{path}: protected workflow/selection/tolerance/golden file differs from the base")
        for path in actual:
            if (path.startswith(GUARDED_PREFIXES) or path in GUARDED_FILES) and path not in f["base_blobs"]:
                bad.append(f"{path}: unauthorized addition to a protected workflow/selection path")
        if f["head_blobs"].get(RC2_CI_WORKFLOW) != RC2_CI_WORKFLOW_CANDIDATE_BLOB:
            bad.append("the CI workflow is not the reviewed RC-2 two-line timeout successor")
        # 10. release-closed flags
        for path, name in FLAG_FILES.items():
            state = activation_state(f["flag_sources"][path], name)
            if state != "CLOSED":
                bad.append(f"{path}: {name} is not a literal release-closed False ({state})")
        return bad
    except (KeyError, TypeError, ValueError, AttributeError, IndexError) as exc:
        return [f"facts incomplete or malformed: {exc!r}"]


@pytest.fixture(scope="module")
def facts():
    return collect()


def test_the_integrated_head_is_exactly_the_documented_union_of_the_five_sources(facts):
    assert inventory_violations(facts) == []


def test_the_oracle_is_live_git_not_values_derived_from_the_current_tree(facts):
    # every expected content value comes from a pinned source commit or the pinned base, never from HEAD itself
    assert facts["head_resolves"] == {pr: True for pr, _ in SOURCES}
    assert set(facts["source_status"]) == {pr for pr, _ in SOURCES} and all(facts["source_status"].values())
    assert all(facts["auto_merge_oracle"].values())


def test_m7_candidate_acceptance_is_not_asserted_here(facts):
    """Candidate-content binding only. Approval and activation stay separate and closed."""
    assert facts["m7_manifest"]["release_approved"] is False
    assert activation_state(facts["flag_sources"]["app/workbook/bess_config.py"], "ACTIVATION_ENABLED") == "CLOSED"


# ── negative mutation tests ────────────────────────────────────────────────────────────────────────────────────
def _bad(facts, **changes):
    mutated = copy.deepcopy(facts)
    mutated.update(changes)
    problems = inventory_violations(mutated)
    assert problems, changes
    return problems


def test_a_changed_blob_of_any_source_content_is_rejected(facts):
    sample = [p for p, o in facts["head_status"].items() if p not in set(AUTO_MERGED) | set(HAND_RESOLVED)
              and p not in INTEGRATION_ADDED and p not in PINNED_INTEGRATION_EDITS][:25]
    for path in sample:
        _bad(facts, head_blobs={**facts["head_blobs"], path: "1" * 40})
    for path in AUTO_MERGED:
        assert any(path in p for p in _bad(facts, head_blobs={**facts["head_blobs"], path: "2" * 40}))


def test_every_financial_blob_change_or_forged_manifest_is_rejected(facts):
    for path in facts["m7_manifest"]["protected_blobs"]:
        assert any(path in p for p in _bad(facts, head_blobs={**facts["head_blobs"], path: "3" * 40}))
    forged = copy.deepcopy(facts["m7_manifest"])
    forged["release_approved"] = True
    _bad(facts, m7_manifest=forged, m7_manifest_at_source=forged)
    shorter = copy.deepcopy(facts["m7_manifest"])
    shorter["protected_blobs"].pop("financial_engine/bess.py")
    _bad(facts, m7_manifest=shorter, m7_manifest_at_source=shorter)


def test_missing_source_wrong_ancestry_or_wrong_merge_order_is_rejected(facts):
    for pr, _ in SOURCES:
        _bad(facts, head_resolves={**facts["head_resolves"], pr: False})
        _bad(facts, ancestors={**facts["ancestors"], pr: False})
        _bad(facts, heads={**facts["heads"], pr: "4" * 40})
    swapped = [facts["merges"][1], facts["merges"][0], *facts["merges"][2:]]
    _bad(facts, merges=swapped)
    _bad(facts, merges=facts["merges"][:-1])
    wrong_parent = copy.deepcopy(facts["merges"])
    wrong_parent[2][1] = "5" * 40
    _bad(facts, merges=wrong_parent)
    squashed = copy.deepcopy(facts["merges"])
    squashed[0] = squashed[0][:2]
    _bad(facts, merges=squashed)


def test_unauthorized_forged_missing_or_restatused_inventory_entries_are_rejected(facts):
    status = facts["head_status"]
    for path in ("financial_engine/new_unreviewed.py", "finco_core/rogue.py", "domain/rogue.py", "app/v2/unreviewed_router.py",
                 ".github/workflows/rogue.yml", "tests/unreviewed_test.py"):
        assert any(path in p for p in _bad(facts, head_status={**status, path: "A"}))
    victim = next(p for p in status if p not in INTEGRATION_ADDED)
    _bad(facts, head_status={k: v for k, v in status.items() if k != victim})
    _bad(facts, head_status={**status, victim: "D"})
    # forging the SOURCE inventory to excuse an extra file is also caught by the independent oracle comparison
    forged_sources = copy.deepcopy(facts["source_status"])
    forged_sources[283]["financial_engine/new_unreviewed.py"] = "A"
    _bad(facts, source_status=forged_sources)


def test_overlapping_sources_must_have_a_documented_resolution(facts):
    forged = copy.deepcopy(facts["source_status"])
    forged[280]["app/model_v2/acquisition/economics.py"] = "M"           # a second owner without documentation
    assert any("without a documented resolution" in p for p in _bad(facts, source_status=forged))


def test_lost_source_markers_in_shared_files_are_rejected(facts):
    for path, markers in {**AUTO_MARKERS, **{p: v["markers"] for p, v in HAND_RESOLVED.items()}}.items():
        for marker in markers:
            texts = {**facts["texts"], path: facts["texts"][path].replace(marker, "")}
            assert any(marker in p for p in _bad(facts, texts=texts)), (path, marker)


def test_changed_protected_workflow_selection_tolerance_or_golden_is_rejected(facts):
    base = facts["base_blobs"]
    guarded = [p for p in base if p.startswith(GUARDED_PREFIXES) or p in GUARDED_FILES]
    assert RC2_CI_WORKFLOW in guarded and "pytest.ini" in guarded
    for path in (RC2_CI_WORKFLOW, "pytest.ini", ".github/workflows/governance_history.yml"):
        _bad(facts, head_blobs={**facts["head_blobs"], path: "6" * 40})
    _bad(facts, head_blobs={k: v for k, v in facts["head_blobs"].items() if k != "pytest.ini"})


def test_opened_activation_flags_are_rejected(facts):
    for path, name in FLAG_FILES.items():
        source = facts["flag_sources"][path]
        assert f"{name} = False" in source
        for new in (f"{name} = True", f"{name} = not False", f"{name} = bool(0)"):
            _bad(facts, flag_sources={**facts["flag_sources"], path: source.replace(f"{name} = False", new, 1)})


def test_historical_checkpoint_forgery_or_a_financial_stream_anchor_is_rejected(facts):
    _bad(facts, base="7" * 40)
    _bad(facts, base_parents=(RC2_BASE_MAIN, "8" * 40))
    _bad(facts, rc1_parents=("9" * 40, RC1_MERGED_PARENTS[1]))
    _bad(facts, stream_tip_status={**facts["stream_tip_status"], "financial_engine/bess.py": "A"})


def test_missing_or_malformed_facts_never_authorise(facts):
    assert inventory_violations({})
    for key in facts:
        assert inventory_violations({k: v for k, v in facts.items() if k != key}), key
    _bad(facts, merges="not-a-list")


# ── Reviewed integration edits (literal pins; generated once from the reviewed working tree, then frozen for review) ──────────
# Re-anchored historical-stream guards (tests/rc3_historical_anchor.py) and the successor modules anchored to their source heads.
PINNED_INTEGRATION_EDITS = {
    "tests/m6_exact_content_successor.py": "355c1b180e4c3e943a52cc2fc4f4472c86b9dcec",
    "tests/m7_bess_successor_proposal.py": "68976dc3367def588db343620cf1dd2cee77f569",
    "tests/test_crypto_p0_product_reality_reset.py": "12c5b96193456b9b5a2254bfcb6be3488bc86f4d",
    "tests/test_crypto_roadmap_q4_q1.py": "10ec5772ace6a672c85e6e31428ba0355a8e1c43",
    "tests/test_data_center_a3_1.py": "99a42f79501f8f29441445c776e6dc4e2bdc5384",
    "tests/test_m3_two_driver_sensitivity.py": "2f447efd18e2198c5d6805bc43636de9c15b28e6",
    "tests/test_m6_exact_content_successor.py": "4eda2579375045442c326395b6b7ea6ecf193f4b",
    "tests/test_m7_bess_successor_proposal.py": "b0b17ae9219686c1439e361dd29248608de3a132",
    "tests/test_model_market_bridge.py": "874c4e7c3ebe2853d6fa3f6c07a82f5f6cc96108",
    "tests/test_model_v2_assumption_trace_references.py": "02a5c27e2ac2e9ca69cf177c754e03f4987383bd",
    "tests/test_model_v2_cost_templates.py": "29ff769b7841c0b9da0c34fc3f4b0759ea0ed29b",
    "tests/test_model_v2_cost_templates_cd.py": "2c001b8f6d91d1608e00c67a2be357821bdab218",
    "tests/test_model_v2_revenue_runtime_parity.py": "e200112fd0b7078175ec8c7a75ca690b15f42b5e",
    "tests/test_multi_source_evidence_v2.py": "f4f2ece723086a8c2cd2a7e4f65e616e663b07a9",
    "tests/test_opus_c1_product_truth.py": "368e25cd61bb3d88db2c5883c037e4e9e8bda979",
    "tests/test_p0a_model_execution.py": "5d93732cf91418cff42486b90aaf1a5944c01dc1",
    "tests/test_p1_2_xlsx_export_reconciliation.py": "c106feb77de7199e2174650e17c10636c9d5bf22",
    "tests/test_p1_3_institutional_validation.py": "bc56c54ad057983532b1775488d03a4cef2d45ed",
    "tests/test_p3_run_certificate_v1.py": "2757a030f71c692d5fcd6c248f9642a6eab88baa",
    "tests/test_parallel_stream_frozen_diff.py": "585a2584cb00d42a81e3c6687bff53c3105d03cd",
    "tests/test_public_product_truth_sync.py": "f031f107cc19fab25667e19b0fe93e2a1e9a7789",
    "tests/test_radar_crypto_surface_coherence.py": "543b73fa192d4590301e99f38b935cc392df5ca8",
    "tests/test_radar_r3_deepstate_composition.py": "6be748f064ec3ae62cc798c524ae191a66c2edf3",
    "tests/test_radar_r4_tokenized_monitor_v2.py": "1efeb22a69d918db12f411935f9ccc9897f2277a",
    "tests/test_radar_tokenized_signal_lifecycle.py": "6ee72e35673d88c9ba1674843f92a5ce807c80e3",
    "tests/test_rc2_integration_manifest.py": "7f6a0b7adcf3848731fbec8a66947096c73dab0c",
    "tests/test_rc3_diagnostics_manifest.py": "d059db8872ef8d264ba2f9c5e4e867ac863aeb56",
    "tests/test_rc3_r5_successor.py": "3311c43fdbbea6331094d416874d50843380b2ab",
    "tests/test_rwa_integrity.py": "fc8e80bd075ac9b6e7fefcacdd388ca5acfe1ea6",
    "tests/test_staging_product_truth.py": "e403a97e78211320098061346a4b3de59fbe0510",
    "tests/test_stock_token_oracle_rejection.py": "42f7aa35aca055aa65e9b6593919ff799f22b4e1",
    "tests/test_tokenized_access_wiring.py": "093668b5c165dcc62d8ef06ca7547d2b3eecadec",
    "tests/test_tokenized_live_intelligence_v1.py": "d73438f270222e23adcb56dd2ab03aaeee0e4f70",
    "tests/test_tokenized_markets_composition.py": "c06a294f28a71b06643e75834998e380f467e4ab",
    "tests/test_trust_readiness_controls.py": "b662615b0106976d38b431bfc29dc0f2573118f2",
    "tests/test_trust_readiness_registry.py": "8bfd684d95358f94db15302385e310bedbcaea2e",
    "tests/test_yield_alerts_core.py": "ae01affe8673fa30c2a931f94846a8d0a279a8e6",
}
