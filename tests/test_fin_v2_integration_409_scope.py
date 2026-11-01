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
# The seal's historical identity (its union, ledger rows and pinned bytes) is asserted at the immutable integration commit it sealed (PR #409's merge),
# not at whatever later reviewed successor (PR #410's closed WF-06B cohort) extends the tree; that successor is verified by tests/test_wf06b_scope.py.
INTEGRATED = "b7bfc4ed0fd224618e42f80dcacb3e1076e772ff"


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
    changed = set(git("diff", "--name-only", "--no-renames", INT.MAIN, INTEGRATED, "--").splitlines())
    assert changed == set(owners) | INT.SEAL_PATHS
    assert not any(p.startswith(INT._PROTECTED_PREFIXES) for p in changed)
    assert INT.PINNED_PATHS <= set(owners) | INT.SEAL_PATHS
    assert not any("*" in p for p in INT.PINNED_PATHS | INT.SEAL_PATHS)


def test_every_non_pinned_union_path_is_the_single_owner_pr_bytes():
    for path, who in INT._union(ROOT).items():
        if path in INT.PINNED_PATHS or path in INT.SEAL_PATHS:
            continue
        assert len(who) == 1, path
        assert git("rev-parse", f"{INTEGRATED}:{path}") == git("rev-parse", f"{INT.SOURCES[who[0]][0]}:{path}"), path


def test_every_pinned_path_has_one_blob_and_a_ledger_row_matching_git():
    data = INT.manifest()
    rows = {r["path"]: r for r in data["repin_ledger"]}
    assert set(rows) == INT.PINNED_PATHS and len(data["repin_ledger"]) == len(INT.PINNED_PATHS)
    for path, row in rows.items():
        assert row["integrated_blob"] == data["source_blobs"][path] == git("rev-parse", f"{INTEGRATED}:{path}")
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


def test_4_generated_ci_evidence_is_tolerated_only_as_untracked_non_executable_evidence(wt):
    (wt / "evidence").mkdir(exist_ok=True)
    (wt / "evidence" / "merge-tree.json").write_text("{}")
    assert INT.exact_blobs_ok(wt) is True                                                  # what the hosted workflows write before the tests run
    (wt / "evidence" / "run.py").write_text("x = 1\n")
    assert INT.exact_blobs_ok(wt) is False                                                 # executable extension under evidence/ is not tolerated
    (wt / "evidence" / "run.py").unlink()
    (wt / "elsewhere.json").write_text("{}")
    assert INT.exact_blobs_ok(wt) is False                                                 # evidence tolerance is not a general untracked allowance


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


# ── PR #409 Correction B: delegation precedence — the seal never substitutes for a broken WF-06A cohort ─────────────────────────────────────────

WF06A_PATH = "frontend/src/app/InputsGuide.tsx"                                           # owned by the closed WF-06A cohort
WF06A_PATHS = (WF06A_PATH, "static/react/finco-react.js", "docs/react_migration/wf06a_ux/SOURCE_SUCCESSOR.json")
SEAL_ONLY_PATH = INT.MANIFEST                                                             # owned by no older cohort: eligible through the seal only
B1_PATH = "app/services/sensitivity_service.py"                                           # PR #407 path (WF-03/B1 layer owns it)


def head_blob(path):
    return git("rev-parse", f"HEAD:{path}")


def test_correction_b_positive_on_the_genuine_integrated_head():
    from tests import wf04_scope as W
    for path in WF06A_PATHS + (SEAL_ONLY_PATH, B1_PATH, "main_web.py"):
        assert W._downstream_allows(path, W.ROOT, None) is True, path
    for path in (WF06A_PATH, "static/react/finco-react.js", B1_PATH, "main_web.py"):         # the exact reviewed pin of each pinned path passes
        assert W._downstream_pin(path, head_blob(path), W.ROOT, None) is True, path       # (a manifest never pins itself, so none is probed here)


def test_correction_b_seal_never_owns_or_admits_a_wf06a_owned_path():
    for path in WF06A_PATHS:
        assert INT.exact_blobs_ok() is True
        assert INT.allowed_path(path) is False and INT.owns(path) is False, path
        assert INT.admits_pin(path, head_blob(path)) is False, path
    assert INT.allowed_path(SEAL_ONLY_PATH) is True and INT.owns(SEAL_ONLY_PATH) is True


@pytest.mark.parametrize("path", WF06A_PATHS)
def test_correction_b_a_broken_wf06a_cohort_admits_none_of_its_paths_even_with_an_exact_seal(monkeypatch, path):  # noqa: E501
    from tests import fin_v2_wf06a_scope as WF06A
    from tests import wf04_scope as W
    monkeypatch.setattr(WF06A, "exact_blobs_ok", lambda *a, **k: False)
    assert INT.exact_blobs_ok() is True                                                    # the seal alone is still exact ...
    from tests import wf06b_scope as WF06B
    # ... and may not rescue the WF-06A-owned path. Only a path the exact, separately reviewed WF-06B successor ALSO owns (it extends WF-06A's reviewed
    # presentation bytes) stays admitted - through that cohort alone, never through the seal or the broken cohort.
    assert W._downstream_allows(path, W.ROOT, None) is (WF06B.allowed_path(path) and WF06B.exact_blobs_ok(W.ROOT, None)), path
    if path != "docs/react_migration/wf06a_ux/SOURCE_SUCCESSOR.json":                          # a manifest never pins itself
        assert W._downstream_pin(path, head_blob(path), W.ROOT, None) is WF06B.supersedes(path, head_blob(path), W.ROOT, None), path


def test_correction_b_a_broken_wf06a_cohort_does_not_block_integration_only_paths(monkeypatch):
    from tests import fin_v2_wf06a_scope as WF06A
    from tests import wf04_scope as W
    monkeypatch.setattr(WF06A, "exact_blobs_ok", lambda *a, **k: False)
    assert W._downstream_allows(SEAL_ONLY_PATH, W.ROOT, None) is True                      # sealed integration-only path stays eligible
    assert W._downstream_allows(B1_PATH, W.ROOT, None) is True                             # owned by the B1/WF-03 layer, unaffected


def test_correction_b_an_invalid_seal_fails_the_composition_closed(monkeypatch):
    """The composition needs BOTH contracts: with the seal invalid, the integration-only path is refused and WF-06A (which relies on the seal for the
    foreign pins of the shared manifests) is no longer exact either, so its paths are refused too. Nothing is rescued in either direction."""
    from tests import fin_v2_wf06a_scope as WF06A
    from tests import wf04_scope as W
    monkeypatch.setattr(INT, "exact_blobs_ok", lambda *a, **k: False)
    assert W._downstream_allows(SEAL_ONLY_PATH, W.ROOT, None) is False
    assert INT.owns(SEAL_ONLY_PATH) is False
    assert WF06A.exact_blobs_ok() is False
    for path in WF06A_PATHS:
        assert W._downstream_allows(path, W.ROOT, None) is False, path


@pytest.mark.parametrize("path", WF06A_PATHS + (B1_PATH, "main_web.py"))
def test_correction_b_a_mutated_or_missing_pin_value_is_refused(path):
    from tests import wf04_scope as W
    assert W._downstream_pin(path, "0" * 40, W.ROOT, None) is False
    assert W._downstream_pin(path, "", W.ROOT, None) is False
    assert W._downstream_pin(path, head_blob(path)[:-1] + ("0" if head_blob(path)[-1] != "0" else "1"), W.ROOT, None) is False


@pytest.mark.parametrize("path", ["frontend/src/app/Unreviewed.tsx", "financial_engine/unreviewed.py", "finco_core/unreviewed.py",
                                  "domain/unreviewed.py", ".github/workflows/unreviewed.yml", "app/unreviewed.py"])
def test_correction_b_unknown_and_protected_paths_are_refused_by_both_hooks(path):
    from tests import wf04_scope as W
    assert W._downstream_allows(path, W.ROOT, None) is False
    assert W._downstream_pin(path, "1" * 40, W.ROOT, None) is False


def test_correction_b_followed_manifest_controls_stay_active_in_the_wf06a_cohort(monkeypatch):
    """The recorded-predecessor control must not be skipped because the seal is exact: forging it still invalidates WF-06A (read-level forgery,
    so the seal itself stays untouched and exact)."""
    from tests import fin_v2_wf06a_scope as W6
    assert W6.exact_blobs_ok() is True and INT.exact_blobs_ok() is True
    reader = W6._read

    def forged(root, path, ref):
        raw = reader(root, path, ref)
        if path == W6.MANIFEST and ref is None:
            data = json.loads(raw)
            data["predecessor_pins"][W6.WSV2_CORE_MANIFEST]["frontend/src/app/RunFailureNotice.tsx"] = "0" * 40
            return json.dumps(data).encode()
        return raw

    monkeypatch.setattr(W6, "_read", forged)
    assert INT.exact_blobs_ok() is True
    assert W6.exact_blobs_ok() is False
