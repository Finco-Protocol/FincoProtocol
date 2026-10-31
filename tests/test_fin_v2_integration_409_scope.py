"""PR #409 integration seal: positive provenance and the mandatory negative tamper matrix.

Every tamper runs in a DISPOSABLE git worktree of the evaluated HEAD, never in the live tree. A single extra path, one flipped byte or one wrong SHA
must invalidate the seal; the older cohorts that delegate to it must then refuse as well.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from tests import fin_v2_integration_409_scope as INT

ROOT = INT.ROOT


def git(*args, cwd=ROOT):
    return subprocess.check_output(["git", *args], cwd=cwd, stderr=subprocess.DEVNULL).decode().strip()


@pytest.fixture(scope="module")
def wt(tmp_path_factory):
    path = tmp_path_factory.mktemp("int409") / "wt"
    subprocess.check_call(["git", "worktree", "add", "-q", "--detach", str(path), "HEAD"], cwd=ROOT)
    yield path
    subprocess.call(["git", "worktree", "remove", "--force", str(path)], cwd=ROOT)


@pytest.fixture(autouse=True)
def pristine(request):
    if "wt" in request.fixturenames:
        path = request.getfixturevalue("wt")
        subprocess.check_call(["git", "checkout", "-q", "--", "."], cwd=path)
        subprocess.check_call(["git", "reset", "-q"], cwd=path)
        subprocess.check_call(["git", "clean", "-fdq"], cwd=path)
    yield


def flip(path: Path):
    path.write_bytes(path.read_bytes() + b"\n")


def restore(wt, path):
    subprocess.check_call(["git", "checkout", "-q", "--", str(path)], cwd=wt)


# ── positive provenance ──────────────────────────────────────────────────────────────────────────────────

def test_seal_is_exact_and_authenticates_main_and_the_three_literal_heads():
    assert INT.exact_blobs_ok()
    assert git("rev-parse", INT.MAIN + "^{tree}") == INT.MAIN_TREE
    for name, (sha, tree) in INT.SOURCES.items():
        assert git("rev-parse", sha + "^{tree}") == tree, name
        subprocess.check_call(["git", "merge-base", "--is-ancestor", sha, "HEAD"], cwd=ROOT)
    subprocess.check_call(["git", "merge-base", "--is-ancestor", INT.MAIN, "HEAD"], cwd=ROOT)


def test_authorised_set_is_exactly_the_union_of_the_three_reviewed_diffs_plus_the_literal_seal():
    owners = INT._union(ROOT)
    changed = set(git("diff", "--name-only", "--no-renames", INT.MAIN, "HEAD", "--").splitlines())
    assert changed == set(owners) | INT.SEAL_PATHS
    assert not any(p.startswith(INT._PROTECTED_PREFIXES) for p in changed)
    assert INT.PINNED_PATHS <= set(owners) | INT.SEAL_PATHS
    assert not any("*" in p for p in INT.PINNED_PATHS | INT.SEAL_PATHS)


def test_every_non_pinned_union_path_is_the_single_owner_pr_bytes():
    for path, who in INT._union(ROOT).items():
        if path in INT.PINNED_PATHS or path in INT.SEAL_PATHS:
            continue
        assert len(who) == 1, path
        assert git("rev-parse", f"HEAD:{path}") == git("rev-parse", f"{INT.SOURCES[who[0]][0]}:{path}"), path


def test_every_pinned_path_has_one_blob_and_a_ledger_row_matching_git():
    data = INT.manifest()
    rows = {r["path"]: r for r in data["repin_ledger"]}
    assert set(rows) == INT.PINNED_PATHS and len(data["repin_ledger"]) == len(INT.PINNED_PATHS)
    for path, row in rows.items():
        assert row["integrated_blob"] == data["source_blobs"][path] == git("rev-parse", f"HEAD:{path}")
        assert row["resolution"]
        for name, (sha, _t) in INT.SOURCES.items():
            try:
                expected = git("rev-parse", f"{sha}:{path}")
            except subprocess.CalledProcessError:
                expected = None
            assert row[name.lower() + "_blob"] == expected, (path, name)


def test_shared_predecessor_manifests_keep_main_identity_history_and_ledger_prefix():
    for path in INT.HISTORY_MANIFESTS:
        old, cur = json.loads(git("show", f"{INT.MAIN}:{path}")), json.loads((ROOT / path).read_text())
        for k in ("schema_version", "base", "base_tree", "parent", "parent_tree"):
            if k in old:
                assert cur[k] == old[k], (path, k)
        assert all(cur.get("historical_source_blobs", {}).get(k) == v for k, v in old.get("historical_source_blobs", {}).items()), path
        assert cur.get("path_ledger", [])[:len(old.get("path_ledger", []))] == old.get("path_ledger", []), path


def test_composite_registry_is_valid_with_the_seal_registered():
    from tests import fin_v2_cohorts as C
    assert "tests.fin_v2_integration_409_scope" in C.COHORT_MODULES
    assert C.valid()


# ── negative tamper matrix (1-8) ─────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("path", [
    "frontend/src/app/InputsGuide.tsx",                    # PR #406
    "app/services/sensitivity_service.py",                 # PR #407
    "app/services/on08_shl_index_authority.py",            # PR #408
    "app/v2/router.py",                                    # PR #408
    "main_web.py",                                         # PR #407
])
def test_1_one_byte_mutation_or_missing_source_of_each_pr_is_rejected(wt, path):
    assert INT.exact_blobs_ok(wt) is True
    flip(wt / path)
    assert INT.exact_blobs_ok(wt) is False
    restore(wt, path)
    (wt / path).unlink()
    assert INT.exact_blobs_ok(wt) is False


@pytest.mark.parametrize("path", sorted(INT.HISTORY_MANIFESTS))
def test_2_one_byte_mutation_of_a_shared_predecessor_manifest_is_rejected(wt, path):
    flip(wt / path)
    assert INT.exact_blobs_ok(wt) is False


def test_2_wrong_missing_and_stale_final_pin_are_rejected(wt):
    manifest = wt / INT.MANIFEST
    original = json.loads(manifest.read_text())
    victim = "tests/wf03_lifecycle_scope.py"

    def wrong(d): d["source_blobs"][victim] = "0" * 40

    def missing(d): d["source_blobs"].pop(victim)

    def stale(d): d["repin_ledger"][0]["integrated_blob"] = "f" * 40

    for mutate in (wrong, missing, stale):
        data = json.loads(json.dumps(original))
        mutate(data)
        manifest.write_text(json.dumps(data))
        assert INT.exact_blobs_ok(wt) is False, mutate.__name__
        restore(wt, INT.MANIFEST)


def test_3_truncated_reordered_or_rewritten_history_is_rejected(wt):
    """The WF-03 manifest carries main's 193-row ledger; the d01/wf04/wsv2_core manifests carry main's historical_source_blobs maps."""
    ledger_rel = "docs/react_migration/wf03_project_lifecycle/SOURCE_SUCCESSOR.json"
    map_rels = ("docs/financial_validation/finv2_d01_d02/SOURCE_SUCCESSOR.json",
                "docs/financial_validation/wf04_debt_metrics/SOURCE_SUCCESSOR.json",
                "docs/react_migration/wsv2_core/SOURCE_SUCCESSOR.json")
    assert json.loads((wt / ledger_rel).read_text())["path_ledger"], "fixture assumption: the WF-03 ledger has history"

    def drop_first(d): d["path_ledger"].pop(0)

    def reorder(d): d["path_ledger"].reverse()

    def rewrite_row(d): d["path_ledger"][0] = {**d["path_ledger"][0], "after_blob": "0" * 40}

    def truncate(d): del d["path_ledger"][-1]

    for mutate in (drop_first, reorder, rewrite_row, truncate):
        path = wt / ledger_rel
        data = json.loads(path.read_text())
        mutate(data)
        path.write_text(json.dumps(data, indent=2) + "\n")
        assert INT.exact_blobs_ok(wt) is False, mutate.__name__
        restore(wt, ledger_rel)

    for rel in map_rels:
        path = wt / rel
        data = json.loads(path.read_text())
        assert data["historical_source_blobs"], rel
        key = next(iter(data["historical_source_blobs"]))
        data["historical_source_blobs"][key] = {}                                          # rewritten historical map
        path.write_text(json.dumps(data, indent=2) + "\n")
        assert INT.exact_blobs_ok(wt) is False, rel
        restore(wt, rel)
        data = json.loads(path.read_text())
        data["historical_source_blobs"].pop(key)                                           # deleted historical map entry
        path.write_text(json.dumps(data, indent=2) + "\n")
        assert INT.exact_blobs_ok(wt) is False, rel
        restore(wt, rel)


def test_4_extra_unreviewed_path_or_wildcard_is_rejected(wt):
    (wt / "app" / "unreviewed_extra.py").write_text("x = 1\n")
    assert INT.exact_blobs_ok(wt) is False                                                 # untracked
    subprocess.check_call(["git", "add", "app/unreviewed_extra.py"], cwd=wt)
    assert INT.exact_blobs_ok(wt) is False                                                 # staged
    assert INT.allowed_path("app/unreviewed_extra.py", wt) is False
    assert INT.allowed_path("app/*", wt) is False and INT.allowed_path("app/", wt) is False
    assert INT.admits_pin("app/unreviewed_extra.py", git("hash-object", "app/unreviewed_extra.py", cwd=wt), wt) is False


def test_5_substituted_parent_wrong_tree_or_missing_ancestor_is_rejected(wt):
    manifest = wt / INT.MANIFEST
    original = json.loads(manifest.read_text())

    def head(d): d["sources"]["PR407"]["head"] = "1" * 40

    def tree(d): d["sources"]["PR406"]["tree"] = "2" * 40

    def main_tree(d): d["main_tree"] = "3" * 40

    def main(d): d["main"] = "4" * 40

    for mutate in (head, tree, main_tree, main):
        data = json.loads(json.dumps(original))
        mutate(data)
        manifest.write_text(json.dumps(data))
        assert INT.exact_blobs_ok(wt) is False, mutate.__name__
        restore(wt, INT.MANIFEST)
    # an evaluated head that does not contain all three literal PR heads as ancestors (PR #407 alone) is not the integration
    assert INT.exact_blobs_ok(wt, INT.SOURCES["PR407"][0]) is False


def test_6_missing_or_forged_seal_is_rejected(wt):
    manifest = wt / INT.MANIFEST
    manifest.unlink()
    assert INT.exact_blobs_ok(wt) is False and INT.manifest(wt) == {}
    manifest.write_text(json.dumps({"schema_version": INT.SCHEMA}))
    assert INT.exact_blobs_ok(wt) is False
    restore(wt, INT.MANIFEST)
    data = json.loads(manifest.read_text())
    data["repin_ledger"][0]["resolution"] = ""                                             # a changed seal without its provenance receipt
    manifest.write_text(json.dumps(data))
    assert INT.exact_blobs_ok(wt) is False


@pytest.mark.parametrize("path", [
    "financial_engine/orchestrator.py",
    "finco_core/inputs/_models.py",
    "domain/inputs.py",
    ".github/workflows/ci_public_job.yml",
    "app/runtime/model_execution.py",
])
def test_7_changed_engine_core_domain_workflow_or_security_source_is_rejected(wt, path):
    assert (wt / path).exists()
    flip(wt / path)
    assert INT.exact_blobs_ok(wt) is False
    assert INT.allowed_path(path, wt) is False and INT.admits_pin(path, git("hash-object", path, cwd=wt), wt) is False


def test_8_one_cohorts_allowed_path_cannot_authorise_another_cohorts_unreviewed_bytes(wt):
    from tests import fin_v2_wf06a_scope as W6
    from tests import wf03_lifecycle_scope as W3
    victim = "app/services/sensitivity_service.py"                                         # PR #407's reviewed file
    flip(wt / victim)
    assert INT.exact_blobs_ok(wt) is False
    assert W6.exact_blobs_ok(wt) is False                                                  # WF-06A delegates to the seal -> refuses
    assert W3.valid(wt) is False
    restore(wt, victim)
    # WF-06A's own allowed_path never extends to a PR #407/#408 path, and the seal admits no value other than that path's single reviewed blob
    assert W6.allowed_path(victim, wt) is False
    assert INT.admits_pin(victim, "0" * 40, wt) is False
    assert INT.admits_pin(victim, git("rev-parse", f"HEAD:{victim}", cwd=wt), wt) is True
