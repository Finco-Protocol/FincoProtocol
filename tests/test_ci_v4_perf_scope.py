"""CI V4 Correction P leaf — positive exactness, predecessor handoff and adversarial tamper cases.

Every mutation case mutates the real checkout bytes, requires an IMMEDIATE fail-closed verdict
in a fresh evaluation, restores in a ``finally`` and requires a fresh passing verdict afterwards.
Nothing is cached across a mutation boundary; the predecessor BESS02 leaf must stay exact
through the reviewed forward handoff and reject any forged successor, pin or cohort.
"""
from __future__ import annotations

import ast
import json
import subprocess
from pathlib import Path

import pytest

from tests import ci_v4_perf_scope as F
from tests import bess02_scope as B
from tests import fin_v2_cohorts as C

ROOT = F.ROOT


def _git(*args):
    return subprocess.check_output(["git", *args], cwd=str(ROOT), stderr=subprocess.DEVNULL)


def test_the_performance_leaf_is_exact_registered_and_the_composite_holds():
    assert "tests.ci_v4_perf_scope" in C.COHORT_MODULES
    assert C.COHORT_MODULES[-1] == "tests.ci_v4_perf_scope"
    assert len(set(C.COHORT_MODULES)) == len(C.COHORT_MODULES)
    assert F.exact_blobs_ok() is True
    assert F.signature_ok() is True
    assert C.valid() is True


def test_every_handoff_file_equals_its_reviewed_literal_substitution():
    for p in sorted(F.HANDOFFS):
        assert (ROOT / p).read_bytes() == F.expected_handoff(ROOT, p), p


def test_the_accepted_bess02_leaf_stays_exact_through_the_forward_handoff():
    assert B.signature_ok() is True
    assert B.reviewed_edits_ok() is True
    assert B.exact_blobs_ok() is True
    assert B._next() is F
    # the BESS02 closure now covers exactly its own paths plus this leaf's
    assert B.closure_paths() == B.OWNED_PATHS | {B.MANIFEST} | F.closure_paths()
    assert "docs/ci_v4/module_weights.json" in B.closure_paths()


def test_the_registry_appends_exactly_one_reviewed_cohort_after_the_accepted_tail():
    registry = _git("show", F.BASE + ":tests/fin_v2_cohorts.py")
    accepted = next(ast.literal_eval(n.value) for n in ast.parse(registry).body
                    if isinstance(n, ast.Assign) and isinstance(n.targets[0], ast.Name)
                    and n.targets[0].id == "COHORT_MODULES")
    assert accepted[-1] == "tests.bess02_scope"  # the accepted BESS02 tail is intact
    assert C.COHORT_MODULES == accepted + ("tests.ci_v4_perf_scope",)
    assert C.COHORT_MODULES.index("tests.bess02_scope") == len(accepted) - 1


def test_the_accepted_bess02_handoff_expectations_are_still_governed_by_this_leaf():
    # the BESS02-era literal for the registry is superseded ONLY by this leaf's own reviewed
    # substitution; the other BESS02 handoff files it does not take over still hold literally.
    for p in sorted(set(B.HANDOFFS) - set(F.HANDOFFS)):
        assert (ROOT / p).read_bytes() == B.expected_handoff(ROOT, p), p
    assert "tests/fin_v2_cohorts.py" in F.HANDOFFS and "tests/fin_v2_cohorts.py" in B.HANDOFFS


def test_the_current_maps_manifests_carry_the_moved_registry_pin_in_canonical_form():
    nx = B._next_pins(ROOT, None)
    pins = B.manifest()["source_blobs"]
    cur = {p: nx.get(p, b) for p, b in pins.items()}
    moved = B._next_moved(ROOT, None)
    assert moved == {"tests/fin_v2_cohorts.py": F.effective_pins()["tests/fin_v2_cohorts.py"]}
    for p in sorted(B.CURRENT_MAPS):
        assert (ROOT / p).read_bytes() == B.expected_map(ROOT, p, cur, moved), p


def test_scheduler_weights_are_literal_projected_corrections_with_provenance():
    d = json.loads((ROOT / "docs/ci_v4/module_weights.json").read_text(encoding="utf-8"))
    assert d["modules"]["tests/test_ux_pr2c_scope.py"] == 1980.0  # measured #438 floor +5%
    assert d["modules"]["tests/test_rc_sec_csrf_successor.py"] == 600.0
    assert d["modules"]["tests/test_rc7b_quarterly_csrf_successor.py"] == 500.0
    assert d["modules"]["tests/test_finval_f01_fixture_integrity.py"] == 300.0
    assert "PROJECTED" in d["source"] and "42881247217" in d["source"]
    from tools.ci_v4_schedule import load_weights
    w = load_weights()
    assert w["tests/test_ux_pr2c_scope.py"] == 1980.0 and w["tests/test_rc_sec_csrf_successor.py"] == 600.0


def test_the_performance_edited_test_modules_are_owned_at_their_exact_bytes():
    for p in ("tests/test_trust_readiness_controls.py", "tests/test_rc_sec_csrf_successor.py",
              "tests/test_finval_f01_fixture_integrity.py"):
        assert p in F.OWNED_PATHS
        assert F.manifest()["source_blobs"][p] == F._blob((ROOT / p).read_bytes())


@pytest.mark.parametrize("path", sorted(F.OWNED_PATHS | {F.MANIFEST}))
def test_one_byte_of_drift_in_any_owned_path_fails_closed_and_restores(path):
    target = ROOT / path
    original = target.read_bytes()
    try:
        target.write_bytes(original + b"\n# drift\n")
        assert F.exact_blobs_ok() is False
        assert F.signature_ok() is False
        assert C.valid() is False
    finally:
        target.write_bytes(original)
    # a FRESH evaluation after the restore passes again; nothing was cached across the boundary
    assert F.exact_blobs_ok() is True
    assert C.valid() is True


def test_a_forged_pin_in_the_leaf_manifest_fails_closed_and_restores():
    original = (ROOT / F.MANIFEST).read_bytes()
    try:
        d = json.loads(original)
        key = "tests/test_trust_readiness_controls.py"
        d["source_blobs"][key] = "0" * 40
        (ROOT / F.MANIFEST).write_bytes((json.dumps(d, indent=2, sort_keys=True) + "\n").encode())
        assert F.exact_blobs_ok() is False
    finally:
        (ROOT / F.MANIFEST).write_bytes(original)
    assert F.exact_blobs_ok() is True


def test_an_extra_or_forged_cohort_in_the_registry_fails_the_leaf_and_the_composite():
    original = (ROOT / "tests/fin_v2_cohorts.py").read_bytes()
    text = original.decode()
    marker = "'tests.r02_ppa_ux_scope', 'tests.bess02_scope', 'tests.ci_v4_perf_scope')"
    assert text.count(marker) == 1
    try:
        (ROOT / "tests/fin_v2_cohorts.py").write_bytes(text.replace(marker, marker + ", 'tests.fake_perf_scope')").encode())
        assert F.reviewed_edits_ok() is False
        assert F.exact_blobs_ok() is False
        assert C.valid() is False
    finally:
        (ROOT / "tests/fin_v2_cohorts.py").write_bytes(original)
    assert F.exact_blobs_ok() is True and C.valid() is True


def test_a_registry_deletion_of_the_accepted_bess_tail_fails_closed():
    original = (ROOT / "tests/fin_v2_cohorts.py").read_bytes()
    text = original.decode()
    try:
        forged = text.replace(", 'tests.bess02_scope', 'tests.ci_v4_perf_scope')", ", 'tests.ci_v4_perf_scope')")
        assert forged != text
        (ROOT / "tests/fin_v2_cohorts.py").write_bytes(forged.encode())
        assert F.reviewed_edits_ok() is False and F.exact_blobs_ok() is False
        assert B.reviewed_edits_ok() is False  # the accepted BESS02 tail may never be erased
    finally:
        (ROOT / "tests/fin_v2_cohorts.py").write_bytes(original)
    assert F.exact_blobs_ok() is True and B.signature_ok() is True


def test_a_foreign_new_source_file_fails_the_closure_and_restores():
    extra = ROOT / "app/v2/react_unreviewed_correction_p.py"
    try:
        extra.write_text('"""unreviewed"""\n', encoding="utf-8")
        assert F.exact_blobs_ok() is False
        assert C.valid() is False
    finally:
        extra.unlink()
    assert F.exact_blobs_ok() is True and C.valid() is True


def test_the_scope_memo_never_survives_a_mutation_between_two_calls():
    from tests import fin_v2_cohorts as K
    rel = "tests/test_trust_readiness_controls.py"
    path = ROOT / rel
    original = path.read_bytes()
    with K.call_scope():
        assert F.exact_blobs_ok() is True and K.valid() is True
    try:
        path.write_bytes(original + b"\n")
        with K.call_scope():                       # fresh outer call AFTER the mutation
            assert F.exact_blobs_ok() is False and K.valid() is False
        assert K._CALL == [] and F._SCOPE == []
    finally:
        path.write_bytes(original)
    with K.call_scope():
        assert K.valid() is True


def test_no_forbidden_authority_joins_the_leaf():
    assert not any(p.startswith(F.FORBIDDEN_PREFIXES) for p in F.OWNED_PATHS | {F.MANIFEST})
    assert F.protected_blobs() == {}
    assert "tests/f03_financing_scope" not in C.COHORT_MODULES  # #438 stays on its own branch


def test_the_accepted_main_version_of_every_handoff_file_is_retrievable_and_distinct_from_the_takeover():
    for p in sorted(F.HANDOFFS):
        base_bytes = _git("show", F.BASE + ":" + p)
        now = (ROOT / p).read_bytes()
        assert base_bytes != now, p                       # the takeover is real, not a no-op
        assert F.expected_handoff(ROOT, p) == now         # and equals exactly the reviewed substitution
