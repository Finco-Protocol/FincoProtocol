"""UX-FINAL-01 exact-source successor (after the accepted R04 leaf): positive identity and adversarial fail-closed controls.

Every negative runs in an ISOLATED clone (a committed variant, or a mutated working tree that is restored afterwards); the evaluated checkout is
never edited and no verdict is cached across mutations. A UX-specific block proves the change is presentation only: no backend, engine, workflow,
flag or stylesheet path moves, the CSS bundle stays byte-identical to accepted main, and the sources add no request.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path

import pytest

from tests import f03_financing_scope as F
from tests import fin_v2_cohorts as C
from tests import f04_financing_scope as Q
from tests import r04_ppa_scope as P
from tests import ux_final01_scope as T

ROOT = Path(__file__).resolve().parents[1]
CHANGED_SOURCE = "frontend/src/app/financing/pr3b2/FinancingEditing.tsx"
SECOND_SOURCE = "frontend/src/app/financing/pr3b1/runEvidence.ts"
BUNDLE = "static/react/finco-react.js"
TAIL = ("tests.f03_financing_scope", "tests.t01e_remediation_scope", "tests.r03_ppa_scope", "tests.f04_financing_scope", "tests.r04_ppa_scope",
        "tests.ux_final01_scope")


def _git(*args, cwd=ROOT):
    return subprocess.check_output(["git", *args], cwd=cwd).decode().strip()


@pytest.fixture(scope="module")
def clone(tmp_path_factory):
    root = tmp_path_factory.mktemp("ux-final01-gov") / "repo"
    subprocess.check_call(["git", "clone", "-q", "--no-hardlinks", str(ROOT), str(root)])
    subprocess.check_call(["git", "checkout", "-q", "--detach", _git("rev-parse", "HEAD")], cwd=root)
    return root


def _g(root, *args):
    return subprocess.check_output(["git", "-c", "user.name=t", "-c", "user.email=t@t", "-c", "commit.gpgsign=false", *args], cwd=root)


def _variant(root, edits=None, mode=None, remove=(), symlink=None):
    """Commit one mutated copy of the evaluated HEAD in the isolated clone and return its sha; the clone is restored afterwards."""
    base = _g(root, "rev-parse", "HEAD").decode().strip()
    try:
        for path, fn in (edits or {}).items():
            f = root / path
            f.write_bytes(fn(f.read_bytes()))
        for path in remove:
            (root / path).unlink()
        if symlink:
            (root / symlink).unlink()
            os.symlink("/etc/hostname", root / symlink)
        _g(root, "add", "-A")
        if mode:
            _g(root, "update-index", "--chmod=+x", mode)
        _g(root, "commit", "-q", "--allow-empty", "-m", "variant")
        return _g(root, "rev-parse", "HEAD").decode().strip()
    finally:
        _g(root, "checkout", "-q", "-f", base)
        _g(root, "clean", "-fdxq")


class _WorkingTree:
    """Mutate the clone's WORKING TREE only (HEAD stays the accepted commit) and always restore it, so ``ref=None`` verdicts are judged on disk."""

    def __init__(self, root):
        self.root = root

    def __enter__(self):
        return self.root

    def __exit__(self, *exc):
        _g(self.root, "checkout", "-q", "-f", "HEAD")
        _g(self.root, "clean", "-fdxq")


def _tamper(root, path, fn):
    f = root / path
    f.write_bytes(fn(f.read_bytes()))


# ---------------------------------------------------------------- positive identity
def test_manifest_schema_pins_and_immutable_base():
    d = T.manifest()
    assert d and d["schema_version"] == T.SCHEMA and d["base"] == T.BASE and d["base_tree"] == T.BASE_TREE
    assert set(d["source_blobs"]) == T.OWNED_PATHS and set(d["base_blobs"]) == T.SUPERSEDED
    assert _git("rev-parse", T.BASE + "^{tree}") == T.BASE_TREE
    assert _git("merge-base", "--is-ancestor", T.BASE, "HEAD") == ""
    assert not set(d["base_blobs"]) & T.NEW


def test_owned_set_is_finite_literal_and_has_no_forbidden_path():
    assert T.SOURCE_PATHS == frozenset((
        "frontend/src/app/financing/pr3b1/runEvidence.ts", "frontend/src/app/financing/pr3b2/FinancingEditing.tsx", BUNDLE))
    assert T.NEW == frozenset((
        "docs/react_migration/ux_final01/screen_contract.csv", "frontend/src/app/financing/pr3b1/__tests__/uxFinal01.test.mjs",
        "tests/test_ux_final01_browser.py", "tests/test_ux_final01_scope.py", "tests/ux_final01_scope.py"))
    assert T.HANDOFF_PATHS == frozenset((
        "tests/r04_ppa_scope.py", "tests/fin_v2_cohorts.py", "tests/test_bess02_scope.py", "tests/test_ci_v4_perf_scope.py",
        "tests/test_r02_ppa_ux_scope.py", "tests/test_post432_l01_l02_scope.py", "tests/test_f03_financing_scope.py",
        "tests/test_t01e_remediation_scope.py", "tests/test_r03_ppa_scope.py", "tests/test_f04_financing_scope.py", "tests/test_r04_ppa_scope.py"))
    assert len(T.CURRENT_MAPS) == 8 and set(T.HANDOFFS) == T.HANDOFF_PATHS and T.MAP_KEYS == ("tests/fin_v2_cohorts.py", BUNDLE)
    assert not any(p.startswith(T.FORBIDDEN) or "*" in p or ".." in p.split("/") for p in T.OWNED_PATHS | {T.MANIFEST})
    assert T.PREDECESSOR == "tests/r04_ppa_scope.py"


def test_signature_exactness_and_reviewed_substitutions_hold():
    assert T.signature_ok() and T.exact_blobs_ok() and T.reviewed_edits_ok()
    for p in T.HANDOFFS:
        assert (ROOT / p).read_bytes() == T.expected_handoff(ROOT, p)
        assert T._blob((ROOT / p).read_bytes()) == T.manifest()["source_blobs"][p]


def test_registered_exactly_once_as_the_terminal_cohort_after_r04():
    assert C.COHORT_MODULES[-6:] == TAIL
    assert C.COHORT_MODULES.count("tests.ux_final01_scope") == 1


def test_current_maps_move_only_the_registry_and_bundle_keys():
    pins = T.manifest()["source_blobs"]
    for p in T.CURRENT_MAPS:
        old = json.loads(_git("show", T.BASE + ":" + p))
        cur = json.loads((ROOT / p).read_text())
        assert set(old) == set(cur) and all(old[k] == cur[k] for k in old if k != "source_blobs")
        changed = {k for k in old["source_blobs"] if old["source_blobs"][k] != cur["source_blobs"][k]}
        assert changed <= set(T.MAP_KEYS)
        for k in changed:
            assert cur["source_blobs"][k] == pins[k]


def test_historical_manifests_and_accepted_chain_files_are_byte_identical_to_the_accepted_base():
    for p in T.FROZEN:
        assert (ROOT / p).read_bytes() == subprocess.check_output(["git", "show", T.BASE + ":" + p], cwd=ROOT), p


def test_the_whole_chain_is_exact_and_the_composite_is_valid_on_the_committed_head(clone):
    with C.call_scope():
        assert T.exact_blobs_ok(clone, "HEAD") and P.exact_blobs_ok(clone, "HEAD") and Q.exact_blobs_ok(clone, "HEAD")
        assert F.exact_blobs_ok(clone, "HEAD") and C.valid(clone, "HEAD")


def test_committed_ref_verdict_equals_the_working_tree_verdict(clone):
    assert T.manifest(clone, "HEAD") and T.manifest(clone, "HEAD") == T.manifest(clone)
    assert T.exact_blobs_ok(clone) is T.exact_blobs_ok(clone, "HEAD") is True
    assert not T.exact_blobs_ok(clone, "0" * 40) and not T.exact_blobs_ok(clone, T.BASE) and not T.manifest(clone, T.BASE)


# ---------------------------------------------------------------- presentation-only proof (UX-specific)
def _changed_vs_base():
    return set(_git("diff", "--name-only", "--no-renames", T.BASE).splitlines())


def test_the_change_set_is_the_owned_set_and_touches_no_backend_engine_workflow_or_stylesheet_path():
    changed = _changed_vs_base()
    assert changed <= T.OWNED_PATHS | {T.MANIFEST}
    for p in changed:
        assert not p.startswith(("app/", "financial_engine/", "finco_core/", "domain/", ".github/", "tools/", "migrations/", "research/", "main_web.py")), p
        assert not p.endswith(".css") and p != "static/react/finco-react.css", p
    assert "frontend/src/app/workflow/PpaContractsEditor.tsx" not in changed     # R04 Phase 1 stays isolated: no revenue wiring
    for p in ("static/react/finco-react.css", "frontend/package.json", "frontend/package-lock.json", "frontend/vite.config.ts", "constraints.txt"):
        assert (ROOT / p).read_bytes() == subprocess.check_output(["git", "show", T.BASE + ":" + p], cwd=ROOT), p


def test_the_frontend_diff_adds_no_request_writer_or_calculation():
    for p in T.SOURCE_PATHS - {BUNDLE}:
        diff = _git("diff", "--unified=0", T.BASE, "--", p)
        added = [l[1:] for l in diff.splitlines() if l.startswith("+") and not l.startswith("+++")]
        joined = "\n".join(added)
        for forbidden in ("fetch(", "XMLHttpRequest", "method:", "POST", "PUT", "localStorage", "Math.", "toFixed", "parseFloat", "reduce("):
            assert forbidden not in joined, (p, forbidden)


def test_not_run_stays_a_distinct_gate_with_no_run_values():
    text = (ROOT / SECOND_SOURCE).read_text()
    m = re.search(r"return \{state:'NOT_RUN',showRun:false,reason:'([^']+)',assurance:'NOT_PROVEN'\}", text)
    assert m and m.group(1).startswith("No committed Run for this project yet.") and "NOT_RUN" not in m.group(1)


CONTRACT = "docs/react_migration/ux_final01/screen_contract.csv"
CONTRACT_HEADER = ["screen", "status", "workstream", "acceptance", "source_path", "note"]
# One CLOSED, explicit vocabulary. CODED / BROWSER_VERIFIED / SOURCE_BYTE_INTEGRATED / HOSTED_CI_VERIFIED are verification levels (a row states the highest one it has
# evidence for); PARTIAL, DEPENDENCY_PENDING, BLOCKED and MISSING are open states; CURRENT is pre-existing behaviour kept; DO_NOT_CHANGE is a boundary.
# Anything else (PASS, DONE, COMPLETE, a lower-case or padded variant, an empty cell) is refused: widening this set needs a reviewed change to this test.
CLOSED_STATUSES = frozenset(("CURRENT", "CODED", "BROWSER_VERIFIED", "SOURCE_BYTE_INTEGRATED", "HOSTED_CI_VERIFIED", "PARTIAL", "DEPENDENCY_PENDING", "BLOCKED",
                             "DO_NOT_CHANGE", "MISSING"))


def contract_problems(text):
    """Every structural or vocabulary problem of a screen contract (empty list = valid)."""
    import csv as _csv
    import io as _io
    problems = []
    rows = list(_csv.reader(_io.StringIO(text)))
    if not rows or rows[0] != CONTRACT_HEADER:
        return ["header is not exactly " + ",".join(CONTRACT_HEADER)]
    seen = set()
    for n, row in enumerate(rows[1:], 2):
        if len(row) != len(CONTRACT_HEADER):
            problems.append("row %d has %d columns" % (n, len(row)))
            continue
        screen, status = row[0], row[1]
        if not screen.strip() or screen != screen.strip():
            problems.append("row %d screen is empty or padded" % n)
        if status not in CLOSED_STATUSES:
            problems.append("row %d status %r is outside the closed vocabulary" % (n, status))
        if screen in seen:
            problems.append("row %d duplicates screen %r" % (n, screen))
        seen.add(screen)
    return problems


def test_the_screen_contract_is_valid_and_uses_only_the_closed_status_vocabulary():
    text = (ROOT / CONTRACT).read_text()
    assert contract_problems(text) == []
    used = {r[1] for r in __import__("csv").reader(__import__("io").StringIO(text))} - {"status"}
    assert used <= CLOSED_STATUSES and "PARTIAL" in used and "DEPENDENCY_PENDING" in used      # the honest open states are really used
    assert not used & {"PASS", "DONE", "COMPLETE", "IMPLEMENTED", "IMPLEMENTED_SLICE_1"}


@pytest.mark.parametrize("bad", ["PASS", "DONE", "COMPLETE", "IMPLEMENTED", "partial", "PARTIAL ", "", "CURRENT|CODED"])
def test_the_status_validator_rejects_anything_outside_the_closed_vocabulary(bad):
    good = ",".join(CONTRACT_HEADER) + "\nscreen one,PARTIAL,UX-01,AC-01,path,note\n"
    assert contract_problems(good) == []
    forged = ",".join(CONTRACT_HEADER) + "\nscreen one,%s,UX-01,AC-01,path,note\n" % bad
    assert contract_problems(forged), bad


def test_the_contract_validator_rejects_structural_forgeries():
    h = ",".join(CONTRACT_HEADER)
    assert contract_problems("screen,status\nx,PARTIAL\n")                                     # wrong header
    assert contract_problems(h + "\nonly,PARTIAL,UX-01\n")                                     # missing columns
    assert contract_problems(h + "\ndup,PARTIAL,a,b,c,d\ndup,CURRENT,a,b,c,d\n")              # duplicate screen
    assert contract_problems(h + "\n ,PARTIAL,a,b,c,d\n")                                      # empty screen
    assert contract_problems("")                                                              # empty file


# ---------------------------------------------------------------- working-tree tamper is detected
@pytest.mark.parametrize("path", sorted(T.OWNED_PATHS - T.CURRENT_MAPS))
def test_one_byte_in_the_working_tree_of_any_owned_blob_fails_closed(clone, path):
    with _WorkingTree(clone):
        assert T.exact_blobs_ok(clone) and T.signature_ok(clone)
        _tamper(clone, path, lambda b: b + b"\n# tampered\n")
        assert T.exact_blobs_ok(clone) is False and not C.valid(clone), path
    assert T.exact_blobs_ok(clone)                               # restored: the verdict is not poisoned


def test_working_tree_tamper_of_the_source_is_detected_while_head_is_unchanged(clone):
    with _WorkingTree(clone):
        head = _g(clone, "rev-parse", "HEAD")
        _tamper(clone, CHANGED_SOURCE, lambda b: b + b"\n// tampered\n")
        assert _g(clone, "rev-parse", "HEAD") == head and _g(clone, "status", "--porcelain").decode().strip()
        assert T.exact_blobs_ok(clone) is False and T.exact_blobs_ok(clone, "HEAD") is True


def test_deleted_or_symlinked_or_executable_owned_file_fails_closed_in_the_working_tree(clone):
    with _WorkingTree(clone):
        (clone / CHANGED_SOURCE).unlink()
        assert not T.exact_blobs_ok(clone)
    with _WorkingTree(clone):
        (clone / CHANGED_SOURCE).unlink()
        os.symlink((clone / SECOND_SOURCE), clone / CHANGED_SOURCE)
        assert not T.exact_blobs_ok(clone)
    with _WorkingTree(clone):
        (clone / CHANGED_SOURCE).chmod(0o755)
        assert not T.exact_blobs_ok(clone)


def test_untracked_foreign_file_in_the_working_tree_fails_closed(clone):
    with _WorkingTree(clone):
        (clone / "app").mkdir(exist_ok=True)
        (clone / "app" / "unreviewed_ux_extra.py").write_text("x = 1\n")
        assert not T.exact_blobs_ok(clone)


def test_the_served_bundle_bytes_match_their_manifest_pin():
    """PINNED IDENTITY only: the committed bundle bytes hash to the manifest pin. Build REPRODUCIBILITY (sources -> bundle) is NOT proven here; the
    separate CI step `npm ci && npm run build && git diff --exit-code static/react` proves it, and neither gate substitutes for the other."""
    pin = T.manifest()["source_blobs"][BUNDLE]
    assert T._blob((ROOT / BUNDLE).read_bytes()) == pin


# ---------------------------------------------------------------- committed-ref adversarial variants
@pytest.mark.parametrize("path", sorted(T.OWNED_PATHS | {T.MANIFEST} - T.CURRENT_MAPS))
def test_one_byte_in_any_owned_committed_blob_is_rejected_by_the_chain_and_the_composite(clone, path):
    ref = _variant(clone, {path: lambda b: b + b"\n"})
    with C.call_scope():
        assert not T.exact_blobs_ok(clone, ref) and not C.valid(clone, ref), path


@pytest.mark.parametrize("path", sorted(T.CURRENT_MAPS))
def test_current_map_tamper_is_rejected_by_the_full_closure(clone, path):
    ref = _variant(clone, {path: lambda b: b + b"\n"})
    with C.call_scope():
        assert not T.exact_blobs_ok(clone, ref) and not C.valid(clone, ref), path


@pytest.mark.parametrize("name,fn", [
    ("duplicate_ux", lambda b: b.replace(b"'tests.r04_ppa_scope', 'tests.ux_final01_scope')", b"'tests.r04_ppa_scope', 'tests.ux_final01_scope', 'tests.ux_final01_scope')")),
    ("fake_extra", lambda b: b.replace(b"'tests.ux_final01_scope')", b"'tests.ux_final01_scope', 'tests.fake_scope')")),
    ("swapped_r04_ux", lambda b: b.replace(b"'tests.r04_ppa_scope', 'tests.ux_final01_scope')", b"'tests.ux_final01_scope', 'tests.r04_ppa_scope')")),
    ("ux_missing", lambda b: b.replace(b", 'tests.ux_final01_scope')", b")")),
    ("r04_removed", lambda b: b.replace(b"'tests.r04_ppa_scope', ", b"")),
    ("f04_removed", lambda b: b.replace(b"'tests.f04_financing_scope', ", b"")),
    ("r03_removed", lambda b: b.replace(b"'tests.r03_ppa_scope', ", b"")),
    ("earlier_reordered", lambda b: b.replace(b"'tests.fin_v2_3_scope', 'tests.fin_v2_ci_scope'", b"'tests.fin_v2_ci_scope', 'tests.fin_v2_3_scope'")),
])
def test_registry_mutations_are_rejected(clone, name, fn):
    ref = _variant(clone, {T.REGISTRY: fn})
    assert T.REGISTRY in subprocess.check_output(["git", "diff", "--name-only", "HEAD", ref], cwd=clone).decode().splitlines()
    with C.call_scope():
        assert not T.signature_ok(clone, ref) and not T.exact_blobs_ok(clone, ref) and not C.valid(clone, ref), name


@pytest.mark.parametrize("path", sorted(T.FROZEN))
def test_historical_and_accepted_chain_files_must_stay_byte_identical(clone, path):
    ref = _variant(clone, {path: lambda b: b + b"\n"})
    with C.call_scope():
        assert not T.signature_ok(clone, ref) and not T.exact_blobs_ok(clone, ref) and not C.valid(clone, ref), path


def test_predecessor_r04_scope_tamper_is_rejected_everywhere(clone):
    ref = _variant(clone, {T.PREDECESSOR: lambda b: b + b"\n"})
    with C.call_scope():
        assert not T.signature_ok(clone, ref) and not P.exact_blobs_ok(clone, ref) and not C.valid(clone, ref)


def test_partially_applied_handoff_is_rejected(clone):
    # registry registered but the R04 forward hook reverted to the accepted BASE bytes (and vice versa)
    old = subprocess.check_output(["git", "show", T.BASE + ":" + T.PREDECESSOR], cwd=ROOT)
    ref = _variant(clone, {T.PREDECESSOR: lambda b: old})
    with C.call_scope():
        assert not T.signature_ok(clone, ref) and not C.valid(clone, ref)
    old_reg = subprocess.check_output(["git", "show", T.BASE + ":" + T.REGISTRY], cwd=ROOT)
    ref = _variant(clone, {T.REGISTRY: lambda b: old_reg})
    with C.call_scope():
        assert not T.signature_ok(clone, ref) and not C.valid(clone, ref)


def test_forged_manifest_base_tree_pin_and_mode_are_rejected(clone):
    tree = T.BASE_TREE.encode()
    for fn in (lambda b: b.replace(b'"base_tree": "' + tree[:8], b'"base_tree": "1' + tree[1:8], 1),
               lambda b: b.replace(b'"base": "' + T.BASE.encode()[:8], b'"base": "3' + T.BASE.encode()[1:8], 1),
               lambda b: b.replace(CHANGED_SOURCE.encode() + b'": "', CHANGED_SOURCE.encode() + b'": "0000', 1),
               lambda b: b.replace(b'"tests/fin_v2_cohorts.py": "', b'"tests/fin_v2_cohorts.py": "0000', 1),
               lambda b: b.replace(b'"' + BUNDLE.encode() + b'": "', b'"' + BUNDLE.encode() + b'": "0000', 1)):
        ref = _variant(clone, {T.MANIFEST: fn})
        with C.call_scope():
            assert not T.signature_ok(clone, ref) and not T.exact_blobs_ok(clone, ref) and not C.valid(clone, ref)
    ref = _variant(clone, mode=CHANGED_SOURCE)
    assert not T.signature_ok(clone, ref) and not T.exact_blobs_ok(clone, ref)
    ref = _variant(clone, symlink=SECOND_SOURCE)
    assert not T.signature_ok(clone, ref) and not T.exact_blobs_ok(clone, ref)


def test_wrong_ancestor_and_unknown_protected_paths_are_rejected(clone):
    assert not T.signature_ok(clone, T.BASE)                       # the accepted base carries no successor manifest
    first = _g(clone, "rev-list", "--max-parents=0", "HEAD").decode().split()[0]
    assert not T.signature_ok(clone, first) and not T.exact_blobs_ok(clone, first)
    for path in ("app/v2/react_financing.py", "financial_engine/tax/engine.py", "finco_core/placeholder.py", ".github/workflows/ci_v4_pr.yml",
                 "static/react/finco-react.css", "frontend/src/app/workflow/PpaContractsEditor.tsx"):
        if (ROOT / path).exists():
            ref = _variant(clone, {path: lambda b: b + b"\n"})
        else:
            f = clone / path
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_text("x = 1\n")
            _g(clone, "add", "-A"); _g(clone, "commit", "-q", "-m", "unknown")
            ref = _g(clone, "rev-parse", "HEAD").decode().strip()
            _g(clone, "checkout", "-q", "-f", "HEAD~1"); _g(clone, "clean", "-fdxq")
        with C.call_scope():
            assert not T.exact_blobs_ok(clone, ref) and not C.valid(clone, ref), path


def test_allowed_path_is_gated_by_the_cohort_signature_and_never_admits_foreign_paths(clone):
    for p in ("financial_engine/tax/engine.py", "app/v2/router.py", "static/react/finco-react.css"):
        assert not T.allowed_path(p)
    assert T.allowed_path(CHANGED_SOURCE) and T.allowed_path(T.MANIFEST) and T.protected_blobs() == {}
    tree = T.BASE_TREE.encode()
    bad = _variant(clone, {T.MANIFEST: lambda b: b.replace(b'"base_tree": "' + tree[:8], b'"base_tree": "1' + tree[1:8], 1)})
    assert not T.allowed_path(CHANGED_SOURCE, clone, bad)           # with a false signature even an owned path confers no authority


def test_supersession_is_pin_exact_and_cross_path_safe():
    pins = T.manifest()["source_blobs"]
    bundle, reg = pins[BUNDLE], pins[T.REGISTRY]
    assert T.supersedes(BUNDLE, bundle) and T.supersedes(T.REGISTRY, reg)
    # R04 owns NO bundle pin (not in its manifest, its SUPERSEDED set or, after the reviewed handoff, its BASELINE): it supersedes the bundle ONLY by
    # forwarding to this successor, and then only for the exact current pin. The same holds through the F04 and F03 links of the chain.
    assert BUNDLE not in P.SUPERSEDED and BUNDLE not in P.BASELINE and BUNDLE not in P.manifest()["source_blobs"]
    assert P.supersedes(BUNDLE, bundle) is True and Q.supersedes(BUNDLE, bundle) is True and F.supersedes(BUNDLE, bundle) is True
    stale = T.manifest()["base_blobs"][BUNDLE]                        # the bundle accepted on main (F04) is no longer current anywhere in the chain
    for link in (P, Q, F):
        assert link.supersedes(BUNDLE, stale) is False and link.supersedes(BUNDLE, "0" * 40) is False and link.supersedes(BUNDLE, reg) is False
    assert not T.supersedes(BUNDLE, "0" * 40)
    assert not T.supersedes(BUNDLE, reg)                              # a real blob pinned for another path
    assert not T.supersedes(BUNDLE, T.manifest()["base_blobs"][BUNDLE])      # the accepted F04 bundle is no longer current
    assert not T.supersedes("tests/not_superseded.py", reg)


def test_forwarded_bundle_supersession_needs_a_valid_successor_signature(clone):
    """The R04/F04/F03 answer for the bundle is the successor's alone: a committed variant whose successor signature is false confers nothing."""
    pin = T.manifest(clone, "HEAD")["source_blobs"][BUNDLE]
    with T.scoped(), P.scoped():
        assert P.supersedes(BUNDLE, pin, clone, "HEAD") is True and Q.supersedes(BUNDLE, pin, clone, "HEAD") is True
    tree = T.BASE_TREE.encode()
    for edit in (lambda b: b.replace(b'"base_tree": "' + tree[:8], b'"base_tree": "1' + tree[1:8], 1),          # forged base tree
                 lambda b: b.replace(b'"' + BUNDLE.encode() + b'": "', b'"' + BUNDLE.encode() + b'": "0000', 1)):   # forged bundle pin
        bad = _variant(clone, {T.MANIFEST: edit})
        with T.scoped(), P.scoped():
            assert P.supersedes(BUNDLE, pin, clone, bad) is False and Q.supersedes(BUNDLE, pin, clone, bad) is False


def test_no_verdict_is_cached_across_refs_or_mutations(clone):
    bad = _variant(clone, {T.REGISTRY: lambda b: b.replace(b", 'tests.ux_final01_scope')", b")")})
    with T.scoped(), P.scoped():
        assert T.signature_ok(clone, "HEAD") and P.exact_blobs_ok(clone, "HEAD")
        assert not T.signature_ok(clone, bad) and not P.exact_blobs_ok(clone, bad)     # same process, same scope, other ref
    assert T.signature_ok(clone, "HEAD")                                                # and the positive verdict was never poisoned
