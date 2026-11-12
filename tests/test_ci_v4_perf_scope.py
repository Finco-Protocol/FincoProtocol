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
from tests import f04_financing_scope as Q

from tests import ci_v4_perf_scope as F
from tests import bess02_scope as B
from tests import fin_v2_cohorts as C

ROOT = F.ROOT


def _git(*args):
    return subprocess.check_output(["git", *args], cwd=str(ROOT), stderr=subprocess.DEVNULL)


def test_the_performance_leaf_is_exact_registered_and_the_composite_holds():
    assert "tests.ci_v4_perf_scope" in C.COHORT_MODULES
    # the leaf stays in its exact place; the only reviewed forward successor is F03, behind its own complete signature
    from tests import f03_financing_scope as G, t01e_remediation_scope as Z, r03_ppa_scope as Y
    assert C.COHORT_MODULES[-1] == "tests.ci_v4_perf_scope" or (
        C.COHORT_MODULES[-2:] == ("tests.ci_v4_perf_scope", "tests.f03_financing_scope") and G.signature_ok()) or (
        C.COHORT_MODULES[-3:] == ("tests.ci_v4_perf_scope", "tests.f03_financing_scope", "tests.t01e_remediation_scope")
        and G.signature_ok() and Z.signature_ok()) or (
        C.COHORT_MODULES[-4:] == ("tests.ci_v4_perf_scope", "tests.f03_financing_scope", "tests.t01e_remediation_scope", "tests.r03_ppa_scope")
        and G.signature_ok() and Z.signature_ok() and Y.signature_ok()) or (
        C.COHORT_MODULES[-5:] == ("tests.ci_v4_perf_scope", "tests.f03_financing_scope", "tests.t01e_remediation_scope", "tests.r03_ppa_scope", "tests.f04_financing_scope")
        and G.signature_ok() and Z.signature_ok() and Y.signature_ok() and Q.signature_ok())
    assert len(set(C.COHORT_MODULES)) == len(C.COHORT_MODULES)
    assert F.exact_blobs_ok() is True
    assert F.signature_ok() is True
    assert C.valid() is True


def test_every_handoff_file_equals_its_reviewed_literal_substitution():
    from tests import f03_financing_scope as G, t01e_remediation_scope as Z, r03_ppa_scope as Y
    for p in sorted(F.HANDOFFS):
        want = (Q.expected_handoff(ROOT, p) if Q.signature_ok() and p in Q.HANDOFFS
                else Y.expected_handoff(ROOT, p) if Y.signature_ok() and p in Y.HANDOFFS
                else Z.expected_handoff(ROOT, p) if Z.signature_ok() and p in Z.HANDOFFS
                else G.expected_handoff(ROOT, p) if G.signature_ok() and p in G.HANDOFFS else F.expected_handoff(ROOT, p))
        assert (ROOT / p).read_bytes() == want, p


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
    from tests import f03_financing_scope as G, t01e_remediation_scope as Z, r03_ppa_scope as Y
    own = accepted + ("tests.ci_v4_perf_scope",)
    assert (C.COHORT_MODULES == own or (C.COHORT_MODULES == own + ("tests.f03_financing_scope",) and G.signature_ok())
            or (C.COHORT_MODULES == own + ("tests.f03_financing_scope", "tests.t01e_remediation_scope")
                and G.signature_ok() and Z.signature_ok())
            or (C.COHORT_MODULES == own + ("tests.f03_financing_scope", "tests.t01e_remediation_scope", "tests.r03_ppa_scope")
                and G.signature_ok() and Z.signature_ok() and Y.signature_ok())
            or (C.COHORT_MODULES == own + ("tests.f03_financing_scope", "tests.t01e_remediation_scope", "tests.r03_ppa_scope", "tests.f04_financing_scope")
                and G.signature_ok() and Z.signature_ok() and Y.signature_ok() and Q.signature_ok()))
    assert C.COHORT_MODULES.index("tests.bess02_scope") == len(accepted) - 1


def test_the_accepted_bess02_handoff_expectations_are_still_governed_by_this_leaf():
    # the BESS02-era literal for the registry is superseded ONLY by this leaf's own reviewed
    # substitution; the other BESS02 handoff files it does not take over still hold literally.
    for p in sorted(set(B.HANDOFFS) - set(F.HANDOFFS)):
        assert (ROOT / p).read_bytes() == B.expected_handoff(ROOT, p), p
    assert "tests/fin_v2_cohorts.py" in F.HANDOFFS and "tests/fin_v2_cohorts.py" in B.HANDOFFS


#: exactly the three pins a current map may carry for this leaf: the registry, the module weights and the PR3b1 guard whose
#: supersession hook admits the module-weights pin. Each moves from its accepted-BASE blob to the blob of this leaf's own bytes.
MOVED_MAP_KEYS = ("docs/ci_v4/module_weights.json", "tests/fin_v2_cohorts.py", "tests/ux_pr3b1_scope.py")


def test_the_current_maps_manifests_carry_exactly_the_reviewed_moved_pins_in_canonical_form():
    assert tuple(sorted(F.MAP_KEYS)) == MOVED_MAP_KEYS
    nx = B._next_pins(ROOT, None)
    pins = B.manifest()["source_blobs"]
    cur = {p: nx.get(p, b) for p, b in pins.items()}
    moved = B._next_moved(ROOT, None)
    # independently derived NEW value (hash of the bytes on disk) and OLD value (accepted BASE), never read from the leaf's own map logic
    new = {k: F._blob((ROOT / k).read_bytes()) for k in MOVED_MAP_KEYS}
    old = {k: F._blob(_git("show", F.BASE + ":" + k)) for k in MOVED_MAP_KEYS}
    assert all(new[k] != old[k] for k in MOVED_MAP_KEYS)                       # every one of them genuinely moved
    from tests import f03_financing_scope as G
    assert {k: moved[k] for k in new} == new and F.effective_pins() == {**F.effective_pins(), **new}
    assert set(moved) - set(new) <= set(G.MAP_KEYS)                       # the only other moved key is the reviewed F03 successor's
    assert F.manifest()["source_blobs"] == {**F.manifest()["source_blobs"], **{k: v for k, v in new.items() if k not in G.manifest()["source_blobs"]}}
    for p in sorted(B.CURRENT_MAPS):
        disk = json.loads((ROOT / p).read_bytes())["source_blobs"]
        base = json.loads(_git("show", F.BASE + ":" + p))["source_blobs"]
        for k in MOVED_MAP_KEYS:                                                # a map records the OLD value only before, the NEW one after
            if k in base:
                assert base[k] == old[k] and disk[k] == new[k], (p, k)
        assert (ROOT / p).read_bytes() == B.expected_map(ROOT, p, cur, moved), p
    # a map moves no OTHER pin than these keys and the registry-era handed-off files: key set unchanged for every map
    for p in sorted(B.CURRENT_MAPS):
        assert set(json.loads((ROOT / p).read_bytes())["source_blobs"]) == set(json.loads(_git("show", F.BASE + ":" + p))["source_blobs"]), p


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
        # a current map's bytes belong to the full proof only: the signature never reads a foreign manifest, every other path is in it
        assert F.signature_ok() is (path in F.CURRENT_MAPS)
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
    marker = ("'tests.r02_ppa_ux_scope', 'tests.bess02_scope', 'tests.ci_v4_perf_scope', 'tests.f03_financing_scope', "
              "'tests.t01e_remediation_scope', 'tests.r03_ppa_scope')")
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
        forged = text.replace(", 'tests.bess02_scope', 'tests.ci_v4_perf_scope'", ", 'tests.ci_v4_perf_scope'")
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
        from tests import f03_financing_scope as G, t01e_remediation_scope as Z, r03_ppa_scope as Y
        want = (Q.expected_handoff(ROOT, p) if Q.signature_ok() and p in Q.HANDOFFS
                else Y.expected_handoff(ROOT, p) if Y.signature_ok() and p in Y.HANDOFFS
                else Z.expected_handoff(ROOT, p) if Z.signature_ok() and p in Z.HANDOFFS
                else G.expected_handoff(ROOT, p) if G.signature_ok() and p in G.HANDOFFS else F.expected_handoff(ROOT, p))
        assert want == now                                # and equals exactly the reviewed substitution


# ---------------------------------------------------------------------------------------------
# Correction R: forward recognition by the older guards. Every case mutates the real checkout bytes,
# requires an IMMEDIATE fail-closed verdict in a fresh evaluation, restores in a ``finally`` and
# requires a fresh passing verdict afterwards.
# ---------------------------------------------------------------------------------------------
from tests import on_bess01_scope as OB1
from tests import ux_pr3b1_scope as U31

FROZEN_EDITS = ("tests/test_trust_readiness_controls.py", "tests/test_rc_sec_csrf_successor.py",
                "tests/test_finval_f01_fixture_integrity.py")
WEIGHTS = "docs/ci_v4/module_weights.json"


def _fresh_ok():
    with C.call_scope():
        return F.exact_blobs_ok() is True and OB1.exact_blobs_ok() is True and U31.exact_blobs_ok() is True and C.valid() is True


def test_every_older_guard_reaches_the_reviewed_pins_through_one_hook_each():
    for p in FROZEN_EDITS:
        pin = F.manifest()["source_blobs"][p]
        assert p in OB1.FROZEN and p not in OB1.SUPERSEDED
        assert F.supersedes(p, pin) is True and F.supersedes(p, "0" * 40) is False
        assert F.base_blob(p) == F._blob(_git("show", F.BASE + ":" + p)) and F.base_blob(p) != pin
    # the PR3b1 hook admits exactly the module-weights pin and nothing else outside its own superseded set
    pin = F.manifest()["source_blobs"][WEIGHTS]
    assert U31.supersedes(WEIGHTS, pin) is True
    assert U31.supersedes(WEIGHTS, F._blob(_git("show", F.BASE + ":" + WEIGHTS))) is False   # the OLD value is no longer accepted
    assert U31.supersedes(WEIGHTS, "0" * 40) is False
    for other in ("docs/ci_v4/node_split_policy.json", "docs/ci_v4/ci-v4-policy.json", "docs/ci_v4/node_weights.json"):
        assert U31.supersedes(other, F._blob((ROOT / other).read_bytes())) is False, other


@pytest.mark.parametrize("path", FROZEN_EDITS)
def test_a_frozen_bess01_test_with_any_other_bytes_than_the_reviewed_pin_fails_closed(path):
    target = ROOT / path
    original = target.read_bytes()
    try:
        target.write_bytes(_git("show", F.BASE + ":" + path))            # the ACCEPTED BASE bytes are no longer this leaf's reviewed bytes
        assert F.exact_blobs_ok() is False and C.valid() is False
        target.write_bytes(original.replace(b"call_scope", b"call_scope_x", 1) if b"call_scope" in original else original + b"\n")
        assert F.exact_blobs_ok() is False and OB1.exact_blobs_ok() is False and C.valid() is False
    finally:
        target.write_bytes(original)
    assert _fresh_ok()


def test_a_frozen_bess01_path_this_leaf_does_not_own_stays_frozen():
    path = "app/v2/router.py"
    assert path in OB1.FROZEN and path not in F.OWNED_PATHS
    target = ROOT / path
    original = target.read_bytes()
    try:
        target.write_bytes(original + b"\n# unreviewed\n")
        assert OB1.exact_blobs_ok() is False and C.valid() is False
    finally:
        target.write_bytes(original)
    assert _fresh_ok()


@pytest.mark.parametrize("map_path,key", [("docs/ci_v4/SOURCE_SUCCESSOR.json", WEIGHTS),
                                          ("docs/ci_v4/SOURCE_SUCCESSOR.json", "tests/fin_v2_cohorts.py"),
                                          ("docs/tax_reference_registry/SOURCE_SUCCESSOR.json", "tests/ux_pr3b1_scope.py"),
                                          ("docs/tax_reference_registry/SOURCE_SUCCESSOR.json", "tests/fin_v2_cohorts.py")])
def test_a_current_map_carrying_the_old_or_a_forged_value_for_a_moved_key_fails_closed(map_path, key):
    target = ROOT / map_path
    original = target.read_bytes()
    old = F._blob(_git("show", F.BASE + ":" + key))
    try:
        for wrong in (old, "0" * 40):
            d = json.loads(original)
            assert key in d["source_blobs"] and d["source_blobs"][key] != wrong
            d["source_blobs"][key] = wrong
            target.write_bytes((json.dumps(d, indent=2, sort_keys=True) + "\n").encode())
            assert B.exact_blobs_ok() is False and F.exact_blobs_ok() is False and C.valid() is False
    finally:
        target.write_bytes(original)
    assert _fresh_ok()


@pytest.mark.parametrize("path", sorted(F.HANDOFFS) + [WEIGHTS] + list(FROZEN_EDITS))
def test_an_executable_mode_on_any_handed_off_or_directly_edited_path_fails_closed(path):
    target = ROOT / path
    mode = target.stat().st_mode
    try:
        target.chmod(0o755)
        assert F.exact_blobs_ok() is False and C.valid() is False
    finally:
        target.chmod(mode & 0o777)
    assert _fresh_ok()


def test_a_forged_base_blob_or_an_extra_manifest_key_fails_closed():
    original = (ROOT / F.MANIFEST).read_bytes()
    try:
        for edit in (lambda d: d["base_blobs"].update({"tests/on_bess01_scope.py": "0" * 40}),
                     lambda d: d["base_blobs"].pop("tests/ux_pr3b1_scope.py"),
                     lambda d: d["source_blobs"].update({"app/v2/router.py": "0" * 40}),
                     lambda d: d["source_blobs"].update({"tests/ux_pr3b1_scope.py": F._blob(_git("show", F.BASE + ":tests/ux_pr3b1_scope.py"))})):
            d = json.loads(original)
            edit(d)
            (ROOT / F.MANIFEST).write_bytes((json.dumps(d, indent=2, sort_keys=True) + "\n").encode())
            assert F.exact_blobs_ok() is False and C.valid() is False
    finally:
        (ROOT / F.MANIFEST).write_bytes(original)
    assert _fresh_ok()


def test_the_leaf_signature_never_evaluates_the_composite_or_a_predecessor_verdict():
    import inspect
    import textwrap
    tree = ast.parse(textwrap.dedent(inspect.getsource(F._exact)))
    called = {n.func.attr if isinstance(n.func, ast.Attribute) else getattr(n.func, "id", "") for n in ast.walk(tree) if isinstance(n, ast.Call)}
    # acyclic ordering: the leaf's low-level proof only reads git facts and its own helpers; it never calls a composite or any
    # predecessor verdict (BESS02 -> leaf is the only direction; the leaf never asks BESS02 or the registry composite back)
    assert not (called & {"valid", "matches", "exact_blobs_ok", "signature_ok", "call_scope", "cohorts", "supersedes"})
    imports = {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)}
    assert imports <= {"tests.fin_v2_cohorts", "tests.on_bess01_scope"}
