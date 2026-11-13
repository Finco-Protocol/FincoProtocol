"""F03 exact-source successor: positive identity, tamper, mode and history refusals."""
import json
import subprocess
from pathlib import Path

from tests import f03_financing_scope as F

ROOT = Path(__file__).resolve().parents[1]

def _git(*args):
    return subprocess.check_output(["git", *args], cwd=ROOT).decode().strip()

def test_f03_immutable_base_and_exact_source_registration():
    d = F.manifest()
    assert d and set(d["source_blobs"]) == F.OWNED_PATHS
    assert set(d["base_blobs"]) == F.SUPERSEDED
    assert _git("rev-parse", F.BASE + "^{tree}") == F.BASE_TREE
    assert F.signature_ok() and F.exact_blobs_ok()
    assert F.reviewed_edits_ok() and set(F.HANDOFFS) == {
        F.REGISTRY, F.PREDECESSOR, F.BESS_MODULE, F.PERF_TEST, F.BESS_TEST, F.R02_TEST, F.POST432_TEST, F.PR2B_TEST}
    assert F.CI_PATHS == frozenset((".github/workflows/finval_f01_acceptance.yml", ".github/workflows/ci_v4_f01_job.yml"))
    assert not any(p.startswith(F.FORBIDDEN) and p not in F.CI_PATHS for p in F.OWNED_PATHS)
    assert F.reviewed_workflow_ok()
    assert F.MAP_KEYS == (F.REGISTRY, "static/react/finco-react.js")

def test_f03_current_maps_are_only_the_two_moved_pins():
    pins = F.manifest()["source_blobs"]
    for p in F.CURRENT_MAPS:
        old = json.loads(_git("show", F.BASE + ":" + p))
        current = json.loads((ROOT / p).read_text())
        assert set(old) == set(current)
        assert all(old[k] == current[k] for k in old if k != "source_blobs")
        assert set(old["source_blobs"]) == set(current["source_blobs"])
        changed = {k for k in old["source_blobs"] if old["source_blobs"][k] != current["source_blobs"][k]}
        assert changed <= set(F.map_keys())
        for k in changed:
            assert current["source_blobs"][k] == F.effective_pins()[k]      # a key a reviewed successor moved again follows its pin


def test_f03_f01_workflow_is_exactly_the_reviewed_45_minute_successor():
    # Read raw git bytes without strip(): trailing LF is part of the governed blob.
    old = subprocess.check_output(["git", "show", F.BASE + ":" + F.CI_WORKFLOW], cwd=ROOT).decode()
    current = (ROOT / F.CI_WORKFLOW).read_text()
    reviewed = old
    for before, after in F.WORKFLOW_EDITS:
        assert reviewed.count(before) == 1
        reviewed = reviewed.replace(before, after)
    assert reviewed == current
    assert "    timeout-minutes: 45\n" in current
    assert "    timeout-minutes: 25\n" in old
    assert "assert len(cases)==20" in current
    assert "assert len([c for c in cases if c.get('classname','').endswith('finval_f01_browser_acceptance')]) == 4" in current
    assert current.count("--durations=20") == 2
    assert F.reviewed_workflow_ok()


def test_f03_f01_workflow_tamper_is_rejected_even_with_other_valid_sources():
    current = (ROOT / F.CI_WORKFLOW).read_bytes()
    assert F.reviewed_workflow_ok(actual=current)
    for bad in (
        current + b"\\n# unexpected CI-policy change\\n",
        current.replace(b"timeout-minutes: 45", b"timeout-minutes: 450", 1),
        current.replace(b"assert len(cases)==20", b"assert len(cases)>=0", 1),
        current.replace(b"docker build -f docs/ci_v3/phase4/runtime/Dockerfile", b"docker build -f Dockerfile", 1),
    ):
        assert bad != current
        assert not F.reviewed_workflow_ok(actual=bad)


def test_f03_only_exact_f01_ci_handoffs_are_admitted():
    assert set(F.REVIEWED_CI_HANDOFFS) == {
        "tests/ci_v4_scope.py", "tests/ux_pr2b_scope.py", "tests/ux_pr2c_scope.py"
    }
    assert F.reviewed_ci_handoffs_ok()
    for p in sorted(F.REVIEWED_CI_HANDOFFS):
        raw = (ROOT / p).read_bytes()
        assert F.reviewed_ci_handoffs_ok(path=p, actual=raw)
        assert not F.reviewed_ci_handoffs_ok(path=p, actual=raw + b"\\n# unreviewed\\n")
    assert not F.reviewed_ci_handoffs_ok(path=".github/workflows/ci_v4_pr.yml")


def test_f03_older_ci_guard_rejects_unreviewed_workflow_pins():
    from tests import ci_v4_scope as V
    current = (ROOT / F.CI_WORKFLOW).read_bytes()
    assert F.reviewed_workflow_ok(actual=current)
    assert not F.reviewed_workflow_ok(actual=current.replace(b"timeout-minutes: 45", b"timeout-minutes: 450"))
    assert not V._f03_ci_owns(".github/workflows/ci_v4_pr.yml", F.ROOT, None)


# ---- BESS02 -> F03 finite forward successor: positive and adversarial controls (every variant is an isolated clone commit) ----
import pytest
from tests import c06_cost_workspace_scope as C06_APPROVAL
from tests import f04_financing_scope as Q
from tests import r04_ppa_scope as W
from tests import bess02_scope as B, r02_ppa_ux_scope as R, fin_v2_cohorts as C

BESS_ACCEPTED_MAIN = "01a26f9a87a12548c4f151caebe8ee933db7445c"


@pytest.fixture(scope="module")
def clone(tmp_path_factory):
    root = tmp_path_factory.mktemp("f03-gov") / "repo"
    subprocess.check_call(["git", "clone", "-q", "--no-hardlinks", str(ROOT), str(root)])
    return root


def _variant(root, edits=None, mode=None, remove=()):
    """Commit one mutated copy of the evaluated HEAD in the isolated clone and return its sha; the clone is restored afterwards."""
    base = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root).decode().strip()
    g = lambda *a: subprocess.check_output(["git", "-c", "user.name=t", "-c", "user.email=t@t", "-c", "commit.gpgsign=false", *a], cwd=root)
    try:
        for path, fn in (edits or {}).items():
            f = root / path
            f.write_bytes(fn(f.read_bytes()))
        for path in remove:
            (root / path).unlink()
        if mode:
            (root / mode).chmod(0o755)
        g("add", "-A")
        g("update-index", "--chmod=+x", mode) if mode else None
        g("commit", "-q", "--allow-empty", "-m", "variant")
        return g("rev-parse", "HEAD").decode().strip()
    finally:
        g("checkout", "-q", "-f", base)
        g("clean", "-fdxq")


def test_valid_descendant_chain_is_exact_at_the_reviewed_head(clone):
    ref = "HEAD"
    assert F.signature_ok(clone, ref) and F.exact_blobs_ok(clone, ref)
    assert B.signature_ok(clone, ref) and B.exact_blobs_ok(clone, ref) and R.signature_ok(clone, ref)
    assert (C.COHORT_MODULES[-3:] == ("tests.bess02_scope", "tests.ci_v4_perf_scope", "tests.f03_financing_scope") or (
        C.COHORT_MODULES[-4:] == ("tests.bess02_scope", "tests.ci_v4_perf_scope", "tests.f03_financing_scope", "tests.t01e_remediation_scope")) or (
        C.COHORT_MODULES[-5:] == ("tests.bess02_scope", "tests.ci_v4_perf_scope", "tests.f03_financing_scope", "tests.t01e_remediation_scope",
                                  "tests.r03_ppa_scope")) or (
        C.COHORT_MODULES[-6:] == ("tests.bess02_scope", "tests.ci_v4_perf_scope", "tests.f03_financing_scope", "tests.t01e_remediation_scope", "tests.r03_ppa_scope", "tests.f04_financing_scope") and Q.signature_ok()) or (
        C.COHORT_MODULES[-7:] == ("tests.bess02_scope", "tests.ci_v4_perf_scope", "tests.f03_financing_scope", "tests.t01e_remediation_scope", "tests.r03_ppa_scope", "tests.f04_financing_scope", "tests.r04_ppa_scope")
        and Q.signature_ok() and W.signature_ok())) or (C.COHORT_MODULES == C06_APPROVAL.BASE_COHORTS + (C06_APPROVAL.__name__,) and C06_APPROVAL.signature_ok())


@pytest.mark.parametrize("name,fn", [
    ("duplicate_f03", lambda b: b.replace(b"'tests.f03_financing_scope', 'tests.t01e_remediation_scope'", b"'tests.f03_financing_scope', 'tests.f03_financing_scope', 'tests.t01e_remediation_scope'")),
    ("fake_extra", lambda b: b.replace(b"'tests.r04_ppa_scope', 'tests.c06_cost_workspace_scope')", b"'tests.r04_ppa_scope', 'tests.c06_cost_workspace_scope', 'tests.fake_scope')")),
    ("swapped_perf_f03", lambda b: b.replace(b"'tests.ci_v4_perf_scope', 'tests.f03_financing_scope'", b"'tests.f03_financing_scope', 'tests.ci_v4_perf_scope'")),
    ("swapped_bess_perf", lambda b: b.replace(b"'tests.bess02_scope', 'tests.ci_v4_perf_scope'", b"'tests.ci_v4_perf_scope', 'tests.bess02_scope'")),
    ("perf_removed", lambda b: b.replace(b"'tests.ci_v4_perf_scope', ", b"")),
    ("bess_removed", lambda b: b.replace(b"'tests.bess02_scope', ", b"")),
    ("f03_missing", lambda b: b.replace(b", 'tests.f03_financing_scope', 'tests.t01e_remediation_scope'", b", 'tests.t01e_remediation_scope'")),
    ("r02_removed", lambda b: b.replace(b"'tests.r02_ppa_ux_scope', ", b"")),
    ("earlier_reordered", lambda b: b.replace(b"'tests.fin_v2_3_scope', 'tests.fin_v2_ci_scope'", b"'tests.fin_v2_ci_scope', 'tests.fin_v2_3_scope'")),
])
def test_registry_mutations_are_rejected_by_f03_and_by_the_bess_chain(clone, name, fn):
    ref = _variant(clone, {F.REGISTRY: fn})
    assert F.REGISTRY in subprocess.check_output(["git", "diff", "--name-only", "HEAD", ref], cwd=clone).decode().splitlines()
    assert not F.signature_ok(clone, ref), name
    assert not B.exact_blobs_ok(clone, ref), name


@pytest.mark.parametrize("path", sorted(F.HANDOFFS))
def test_one_byte_in_any_reviewed_handoff_is_rejected_everywhere(clone, path):
    ref = _variant(clone, {path: lambda b: b + b"\n"})
    assert not F.signature_ok(clone, ref) and not B.signature_ok(clone, ref) and not B.exact_blobs_ok(clone, ref)


@pytest.mark.parametrize("path", [
    "app/services/bess_standalone_candidate.py", "app/services/bess_setup_preview.py", "app/workbook/bess_config.py",
    "docs/bess02/SOURCE_SUCCESSOR.json", "docs/react_migration/r02_ppa_ux/SOURCE_SUCCESSOR.json", "docs/bess_setup/SOURCE_SUCCESSOR.json"])
def test_bess_product_default_off_flag_and_historical_manifests_must_stay_byte_identical(clone, path):
    ref = _variant(clone, {path: lambda b: b + b"\n"})
    assert not F.signature_ok(clone, ref) and not B.exact_blobs_ok(clone, ref)
    assert b"ACTIVATION_ENABLED = False" in (ROOT / "app/workbook/bess_config.py").read_bytes()


def test_wrong_ancestor_mode_and_tampered_pins_are_rejected(clone):
    assert not F.signature_ok(clone, F.BASE)                              # BASE itself carries no successor manifest
    assert not F.signature_ok(clone, "c26b968683f1de63f73f92789dcef947e912822e")   # a pre-BESS ancestor is the wrong parent
    assert not F.signature_ok(clone, _variant(clone, mode="tests/bess02_scope.py"))
    assert not F.signature_ok(clone, _variant(clone, {F.MANIFEST: lambda b: b.replace(b'"base_tree": "7f8335fa', b'"base_tree": "1f8335fa', 1)}))
    forged = _variant(clone, {F.MANIFEST: lambda b: b.replace(b'"tests/bess02_scope.py": "', b'"tests/bess02_scope.py": "0000', 1)})
    assert not F.signature_ok(clone, forged) and not B.signature_ok(clone, forged)


def test_current_map_tamper_and_unknown_protected_path_are_rejected(clone):
    ref = _variant(clone, {"docs/ci_v4/SOURCE_SUCCESSOR.json": lambda b: b.replace(b'"tests/fin_v2_cohorts.py": "', b'"tests/fin_v2_cohorts.py": "0000', 1)})
    # a foreign map's bytes are judged only by the full closure (the accepted leaf rule): the signature survives, the exactness does not
    assert F.signature_ok(clone, ref) and not F.exact_blobs_ok(clone, ref) and not B.exact_blobs_ok(clone, ref)
    unknown = _variant(clone, {"app/v2/react_financing.py": lambda b: b + b"\n"})
    assert not F.signature_ok(clone, unknown) and not F.exact_blobs_ok(clone, unknown)


def test_ci_and_f01_policy_edits_are_rejected(clone):
    for path in (F.CI_WORKFLOW, "tests/ci_v4_scope.py", "tests/ux_pr2b_scope.py", "tests/ux_pr2c_scope.py"):
        assert not F.signature_ok(clone, _variant(clone, {path: lambda b: b + b"\n"})), path


def test_bess_supersession_is_pin_exact_and_cross_path_safe():
    pins = F.manifest()["source_blobs"]
    reg = F.effective_pins()[F.REGISTRY]                   # the CURRENT registry pin (a reviewed successor's while its signature holds)
    assert B.supersedes(F.REGISTRY, reg) and B.effective_pins()[F.REGISTRY] == reg
    assert not B.supersedes(F.REGISTRY, "0" * 40)
    assert not B.supersedes(F.REGISTRY, pins[F.PREDECESSOR])           # a real blob pinned for another path
    assert not B.supersedes("tests/not_superseded.py", reg)            # outside the closed set
    assert not B.supersedes(F.REGISTRY, F.manifest()["base_blobs"][F.REGISTRY])       # the accepted BESS-only blob is no longer current under F03


def test_no_verdict_is_cached_across_refs_or_mutations(clone):
    bad = _variant(clone, {F.REGISTRY: lambda b: b.replace(b", 'tests.f03_financing_scope', 'tests.t01e_remediation_scope'", b", 'tests.t01e_remediation_scope'")})
    with F.scoped(), B.scoped():
        assert F.signature_ok(clone, "HEAD") and B.exact_blobs_ok(clone, "HEAD")
        assert not F.signature_ok(clone, bad) and not B.exact_blobs_ok(clone, bad)    # same process, same scope, other ref
    assert F.signature_ok(clone, "HEAD")                                             # and the positive verdict was never poisoned


# ---- CI V4 internal F01 job: exactly one reviewed line (25 -> 45 minutes), nothing else under .github/ ----
def test_ci_v4_internal_f01_job_is_exactly_the_one_line_timeout_successor():
    old = subprocess.check_output(["git", "show", F.BASE + ":" + F.CI_JOB], cwd=ROOT).decode()
    current = (ROOT / F.CI_JOB).read_text()
    assert "    timeout-minutes: 25\n" in old and "    timeout-minutes: 45\n" in current
    assert old.replace("    timeout-minutes: 25\n", "    timeout-minutes: 45\n", 1) == current          # no other byte moved
    # every acceptance assertion the standalone workflow keeps is still in the internal job, untouched
    for needle in ("== 4", "assert len(cases)==20", "test \"$(id -u)\" -ne 0", "--network none", "run-native"):
        assert needle in current
    assert F.reviewed_job_ok() and F.reviewed_job_ok(actual=current.encode())


def test_ci_v4_internal_f01_job_drift_is_rejected():
    current = (ROOT / F.CI_JOB).read_bytes()
    for bad in (
        current.replace(b"timeout-minutes: 45", b"timeout-minutes: 450", 1),
        current.replace(b"timeout-minutes: 45", b"timeout-minutes: 25", 1),
        current.replace(b"assert len(cases)==20", b"assert len(cases)>=0", 1),
        current.replace(b"--network none", b"--network host", 1),
        current + b"\n# extra\n",
    ):
        assert bad != current and not F.reviewed_job_ok(actual=bad)


def test_ci_v4_f01_job_edit_is_rejected_by_f03_and_by_the_ci_v4_guard(clone):
    from tests import ci_v4_scope as V
    # One read of immutable explicit refs; dropped before any later test or mutation.
    with C.call_scope():
        good = _variant(clone)
        assert F.signature_ok(clone, good)
        bad = _variant(clone, {F.CI_JOB: lambda b: b.replace(b"timeout-minutes: 45", b"timeout-minutes: 90", 1)})
        assert not F.signature_ok(clone, bad) and not V.exact_blobs_ok(clone, bad)
        other = _variant(clone, {".github/workflows/ci_v4_pr.yml": lambda b: b + b"\n# unreviewed\n"})
        assert not F.exact_blobs_ok(clone, other) and not V.exact_blobs_ok(clone, other)


def test_ci_v4_hook_admits_only_two_literal_source_paths():
    from tests import ci_v4_scope as V
    # Same unmodified tree throughout this bounded read.
    with C.call_scope():
        pins = F.manifest()["source_blobs"]
        assert V._pr2c_supersedes(F.CI_JOB, pins[F.CI_JOB], F.ROOT, None)
        assert not V._pr2c_supersedes(F.CI_JOB, "0" * 40, F.ROOT, None)
        assert not V._pr2c_supersedes(".github/workflows/ci_v4_pr.yml", pins[F.CI_JOB], F.ROOT, None)
        assert not V._pr2c_supersedes(F.CI_WORKFLOW, pins[F.CI_JOB], F.ROOT, None)
