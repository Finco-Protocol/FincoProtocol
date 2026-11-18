"""Finite P0 candidate admission: positive closure and independent tamper controls.

No workflow is activated, no old manifest is repinned, no historical test is
removed. Committed variants are data; the mutated Python is never executed.
"""
import json
from pathlib import Path
import subprocess

import pytest
from tests import ci_v4_p0_scope as T
from tests import ci_v4_full_recovery_scope as F
from tests import fin_v2_cohorts as C

ROOT = Path(__file__).resolve().parents[1]
MODULE = "tests/ci_v4_p0_scope.py"


def git(root, *args):
    return subprocess.check_output(["git", "-c", "user.name=scope-test", "-c",
        "user.email=noreply@users.noreply.github.com", "-c", "commit.gpgsign=false", *args], cwd=root)


@pytest.fixture(scope="module")
def subject(tmp_path_factory):
    root = tmp_path_factory.mktemp("p0-source") / "subject"
    git(ROOT, "clone", "--quiet", "--shared", str(ROOT), str(root))
    return root


def rejected(root, path, transform=None, mode=False, remove=False, symlink=False):
    head = git(root, "rev-parse", "HEAD").decode().strip()
    f = root / path
    try:
        if remove: f.unlink()
        elif symlink: f.unlink(); f.symlink_to("README.md")
        elif mode: f.chmod(f.stat().st_mode | 0o111)
        else: f.write_bytes(transform(f.read_bytes()))
        git(root, "add", "-A")
        git(root, "commit", "--quiet", "--allow-empty", "-m", "negative variant")
        ref = git(root, "rev-parse", "HEAD").decode().strip()
        with C.call_scope():
            return not T.exact_blobs_ok(root, ref) and not C.valid(root, ref)
    finally:
        git(root, "reset", "--hard", "--quiet", head)
        git(root, "clean", "-fdxq")


def test_current_source_has_one_registered_terminal_successor():
    assert C.COHORT_MODULES == T.BASE_COHORTS + (T.__name__,)
    assert C.COHORT_MODULES.count(T.__name__) == 1
    assert F._next() is T and F.SUCCESSOR == T.__name__
    assert T.BASE == "955952c1bc16b21ce342121c5224a19d3e105aa7"
    assert git(ROOT, "rev-parse", T.BASE + "^{tree}").decode().strip() == T.BASE_TREE
    with C.call_scope():
        assert T.signature_ok() and T.reviewed_edits_ok() and T.exact_blobs_ok()
        assert all(m.exact_blobs_ok() for m in C.cohorts())
        assert C.valid()


def test_literal_file_set_modes_handoffs_and_frozen_control_sources():
    d = T.manifest()
    assert set(d["source_blobs"]) == T.OWNED_PATHS
    assert set(d["base_blobs"]) == T.SUPERSEDED
    assert set(T.HANDOFFS) == T.HANDOFF_PATHS
    assert T.REPLACED == {'tests/test_rc7c_candidate_successor.py', 'tests/test_v9p2a_odr_successor.py',
                          'docs/ci_v4/node_split_policy.json', 'docs/ci_v4/node_weights.json',
                          'tests/test_ci_v4_nodes.py', 'tests/test_ci_v4_activate.py', '.github/workflows/ci_v4_full.yml'}
    assert T.CI_PATHS == {'.github/workflows/ci_perf_guard.yml', 'tools/ci_perf_guard.py',      # literal, never a pattern
                          '.github/workflows/ci_v4_full.yml', 'tools/ci_full_parallel.py'}   # P2: the FULL workflow + its parallel controller
    assert '.github/workflows/ci_v4_full.yml' not in T.FROZEN and set(T.FROZEN) & T.OWNED_PATHS == set()
    assert 'tests/conftest.py' not in T.OWNED_PATHS      # a protected, unowned path of the historical U1/U2/WF-06B guards
    assert not any(p.startswith(T.FORBIDDEN) or "*" in p for p in T.OWNED_PATHS)
    for p in T.HANDOFFS:
        assert (ROOT / p).read_bytes() == T.expected_handoff(ROOT, p)
    for p in T.FROZEN:
        assert (ROOT / p).read_bytes() == git(ROOT, "show", T.BASE + ":" + p)
    for p in T.CURRENT_MAPS:
        assert (ROOT / p).read_bytes() == T.expected_map(ROOT, p)
    assert not T.allowed_path("docs/ci_v5/epoch.json")
    assert not T.allowed_path("tools/ci_v4_extra.py")


@pytest.mark.parametrize("path", sorted(T.OWNED_PATHS | {T.MANIFEST}))
def test_one_byte_in_each_owned_file_fails_closed(subject, path):
    assert rejected(subject, path, lambda b: b + b"\n"), path


@pytest.mark.parametrize("attack", ["base", "tree", "pin", "mode", "extra", "authorization"])
def test_forged_source_manifest_is_rejected(subject, attack):
    def change(raw):
        d = json.loads(raw)
        if attack == "base": d["base"] = "0" * 40
        elif attack == "tree": d["base_tree"] = "0" * 40
        elif attack == "pin": d["source_blobs"][MODULE] = "0" * 40
        elif attack == "mode": d["source_modes"][MODULE] = "100755"
        elif attack == "extra": d["source_blobs"]["app/unapproved.py"] = "0" * 40
        elif attack == "authorization": d["authorization"] += " broader"
        return (json.dumps(d, indent=2, sort_keys=True) + "\n").encode()
    assert rejected(subject, T.MANIFEST, change)


@pytest.mark.parametrize("attack", ["mode", "delete", "symlink"])
def test_file_identity_changes_rejected(subject, attack):
    assert rejected(subject, MODULE, mode=attack == "mode", remove=attack == "delete", symlink=attack == "symlink")


@pytest.mark.parametrize("name", ["duplicate", "missing", "swapped"])
def test_terminal_registry_attacks_rejected(subject, name):
    def change(raw):
        tail = b"'tests.ci_v4_full_recovery_scope', 'tests.ci_v4_p0_scope')"
        assert raw.count(tail) == 1
        new = {"duplicate": tail[:-1] + b", 'tests.ci_v4_p0_scope')",
               "missing": b"'tests.ci_v4_full_recovery_scope')",
               "swapped": b"'tests.ci_v4_p0_scope', 'tests.ci_v4_full_recovery_scope')"}[name]
        return raw.replace(tail, new)
    assert rejected(subject, T.REGISTRY, change)


def test_positive_negative_restoration_and_ref_separation(subject):
    doc = "docs/ci_v4/p0_40min/candidate/full_coverage.py"
    raw = (subject / doc).read_bytes()
    with C.call_scope(): assert T.exact_blobs_ok(subject)
    try:
        (subject / doc).write_bytes(raw + b"\n")
        with C.call_scope():
            assert not T.exact_blobs_ok(subject)
            assert T.exact_blobs_ok(subject, "HEAD")
        assert not C._CALL
    finally: (subject / doc).write_bytes(raw)
    with C.call_scope(): assert T.exact_blobs_ok(subject)
    assert not C._CALL


def test_foreign_path_fails_full_closure(subject):
    p = "docs/ci_v4/p0_40min/UNAPPROVED.md"
    try:
        (subject / p).write_text("synthetic negative control\n")
        with C.call_scope():
            assert T.signature_ok(subject)
            assert not T.exact_blobs_ok(subject) and not C.valid(subject)
    finally: (subject / p).unlink()


# ── P1 Correction A: the literal P0 hooks in historical cohorts admit nothing but the exact P0 pins ──────────────────────────────────
P1_HOOKED = ("tests.ci_v4_lean_b1_scope", "tests.ci_v4_lean_b2_scope", "tests.ci_v4_lean_b3_scope", "tests.ci_v5_bootstrap_scope",
             "tests.ci_v5_hardening_scope", "tests.ci_v5_gate_scope", "tests.ci_v4_full_recovery_scope")


def variant(root, edits):
    """Commit a negative variant (edits: {path: callable(bytes)->bytes | 'chmod' | 'new:<bytes>'}); return (ref, restore)."""
    head = git(root, "rev-parse", "HEAD").decode().strip()
    for path, how in edits.items():
        f = root / path
        if how == "chmod":
            f.chmod(f.stat().st_mode | 0o111)
        elif isinstance(how, bytes):
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_bytes(how)
        else:
            f.write_bytes(how(f.read_bytes()))
    git(root, "add", "-A")
    git(root, "commit", "--quiet", "--allow-empty", "-m", "negative variant")
    ref = git(root, "rev-parse", "HEAD").decode().strip()

    def restore():
        git(root, "reset", "--hard", "--quiet", head)
        git(root, "clean", "-fdxq")
    return ref, restore


def verdicts(root, ref, names):
    import importlib
    with C.call_scope():
        return {n: importlib.import_module(n).exact_blobs_ok(root, ref) for n in names}, C.valid(root, ref)


def test_p1_hooks_are_literal_in_every_historical_cohort():
    for name in P1_HOOKED:
        path = "tests/%s.py" % name.split(".")[1]
        src = (ROOT / path).read_text()
        assert src.count("def _p0_pins_frozen_edit(") == 1 and src.count("_p0_pins_frozen_edit(p, current.get(p), root, ref)") == 1, path
        assert "p in ('docs/ci_v4/node_split_policy.json', 'docs/ci_v4/node_weights.json', '.github/workflows/ci_v4_full.yml')" in src, path
    v4 = (ROOT / "tests/ci_v4_scope.py").read_text()
    assert "out = out | (P0.CI_PATHS if P0.exact_blobs_ok(root, ref) else frozenset())" in v4
    assert ("if path in ('docs/ci_v4/node_split_policy.json', 'docs/ci_v4/node_weights.json', 'tests/test_ci_v4_activate.py', "
            "'tests/test_ci_v4_nodes.py', '.github/workflows/ci_v4_full.yml'):") in v4 and "return path in P0.REPLACED and P0.supersedes(path, value, root, ref)" in v4
    gate = (ROOT / "tests/ci_v5_gate_scope.py").read_text()
    assert "if nxt and path == 'tests/ci_v4_scope.py' and _p0_owns_handoff(path, root, ref):" in gate
    assert T.P1_FROZEN_EDITS == ('docs/ci_v4/node_split_policy.json', 'docs/ci_v4/node_weights.json')
    assert T.P2_FROZEN_EDITS == ('.github/workflows/ci_v4_full.yml',)
    assert T.CI_PATHS - T.REPLACED <= T.NEW and T.CI_PATHS & T.REPLACED == set(T.P2_FROZEN_EDITS)      # P2: exactly one REPLACED CI path


@pytest.mark.parametrize("path", ["docs/ci_v4/node_weights.json", "docs/ci_v4/node_split_policy.json", ".github/workflows/ci_v4_full.yml"])
def test_a_foreign_control_blob_is_rejected_by_every_hooked_historical_cohort(subject, path):
    ref, restore = variant(subject, {path: lambda b: b.replace(b'"', b'"', 1) + b"\n"})
    try:
        each, ok = verdicts(subject, ref, P1_HOOKED + ("tests.ci_v4_scope", T.__name__))
        assert not ok and not any(each.values()), each
    finally:
        restore()


def test_a_third_frozen_control_path_is_never_admitted(subject):
    ref, restore = variant(subject, {"docs/ci_v4/ci-v4-policy.json": lambda b: b + b"\n"})
    try:
        each, ok = verdicts(subject, ref, P1_HOOKED)
        assert not ok and not any(each.values()), each
    finally:
        restore()


def test_a_mode_change_of_an_admitted_control_blob_is_rejected(subject):
    ref, restore = variant(subject, {"docs/ci_v4/node_weights.json": "chmod"})
    try:
        each, ok = verdicts(subject, ref, P1_HOOKED)
        assert not ok and not any(each.values()), each
    finally:
        restore()


@pytest.mark.parametrize("path", [".github/workflows/ci_perf_guard_fast.yml", "tools/ci_perf_guard2.py", "tools/ci_v5_epoch_helper.py",
                                  ".github/workflows/ci_v4_full_fast.yml", "tools/ci_full_parallel_helper.py"])
def test_a_ci_path_outside_the_two_literal_guard_paths_is_rejected(subject, path):
    ref, restore = variant(subject, {path: b"# synthetic negative control\n"})
    try:
        each, ok = verdicts(subject, ref, ("tests.ci_v4_scope", T.__name__))
        assert not ok and not each["tests.ci_v4_scope"], each
    finally:
        restore()


def test_one_byte_in_the_p0_reviewed_ci_v4_scope_hook_is_rejected(subject):
    ref, restore = variant(subject, {"tests/ci_v4_scope.py": lambda b: b.replace(b"P0.CI_PATHS if", b"P0.CI_PATHS  if", 1)})
    try:
        each, ok = verdicts(subject, ref, ("tests.ci_v5_gate_scope", T.__name__))
        assert not ok and not each[T.__name__], each
    finally:
        restore()


# ── Correction B: one read-only verdict = one call scope (function boundary); nothing outlives a call, nothing masks a mutation ──────────
def _no_scope_open():
    from tests import u1_scope as U, ci_v4_scope as V4
    return not C._CALL and not C._ENTERING and not U._SCOPE and not U._JOINING and not V4._SCOPE


def test_cb_hooks_are_literal_and_bounded():
    u1 = (ROOT / "tests/u1_scope.py").read_text()
    assert u1.count("outer.enter_context(_C.call_scope())") == 1 and u1.count("_JOINING = []") == 1
    v4 = (ROOT / "tests/ci_v4_scope.py").read_text()
    assert v4.count("with _C.call_scope():      # Correction B (#458)") == 1


def test_cb_no_scope_state_outlives_a_verdict():
    from tests import wf06b_scope as W, ci_v4_scope as V4, u1_scope as U
    assert _no_scope_open()
    assert W.exact_blobs_ok() and _no_scope_open()
    assert V4.exact_blobs_ok() and _no_scope_open()
    assert U.exact_blobs_ok() and _no_scope_open()


def test_cb_an_exception_inside_the_u1_scope_closes_every_scope():
    from tests import u1_scope as U

    class Boom(Exception):
        pass
    with pytest.raises(Boom):
        with U.scoped():
            assert C._CALL and U._SCOPE
            raise Boom()
    assert _no_scope_open()


def test_cb_a_mutation_between_two_verdicts_is_always_seen(subject):
    from tests import wf06b_scope as W, ci_v4_scope as V4
    with C.call_scope():
        assert W.exact_blobs_ok(subject) and V4.exact_blobs_ok(subject)
    for path, mod in (("tests/wf06b_scope.py", W), ("tests/ci_v4_scope.py", V4)):
        f = subject / path
        raw = f.read_bytes()
        try:
            assert mod.exact_blobs_ok(subject)                  # fresh call: its own scope
            f.write_bytes(raw + b"\n# unreviewed\n")
            assert not mod.exact_blobs_ok(subject), path       # the next call opens a NEW scope: the mutation is never masked
            assert _no_scope_open()
        finally:
            f.write_bytes(raw)
        assert mod.exact_blobs_ok(subject) and _no_scope_open()


@pytest.mark.parametrize("forged", [False, True])
def test_cb_scoped_and_unscoped_verdicts_are_identical(subject, forged):
    from tests import wf06b_scope as W, ci_v4_scope as V4, u1_scope as U, post413_o1_scope as O
    f = subject / "static/react/finco-react.js"
    raw = f.read_bytes()
    try:
        if forged:
            f.write_bytes(raw + b"\n/* forged */\n")
        fresh = {m.__name__: m.exact_blobs_ok(subject) for m in (W, V4, U, O)}
        with C.call_scope():
            shared = {m.__name__: m.exact_blobs_ok(subject) for m in (W, V4, U, O)}
        assert fresh == shared
        if forged:
            assert not fresh["tests.wf06b_scope"] and not fresh["tests.u1_scope"]
        else:
            assert all(fresh.values()), fresh
    finally:
        f.write_bytes(raw)
    assert _no_scope_open()


# ── Correction B2 (post-#460): BOTH entry orders open exactly ONE outer call; the entry marker never outlives entry, even on an exception ───
def test_cb2_hooks_are_literal_and_bounded():
    reg = (ROOT / "tests/fin_v2_cohorts.py").read_text()
    u1 = (ROOT / "tests/u1_scope.py").read_text()
    assert reg.count("_ENTERING = []") == 1 and reg.count("_ENTERING.append(True)") == 1 and reg.count("_ENTERING.pop()") == 1
    assert reg.count("if _CALL or _ENTERING:") == 1
    assert u1.count("if not _C._CALL and not _C._ENTERING and not _JOINING:") == 1


def test_cb2_registry_first_entry_opens_exactly_one_outer_call():
    from tests import u1_scope as U
    assert _no_scope_open()
    with C.call_scope():
        assert len(C._CALL) == 1 and not C._ENTERING and len(U._SCOPE) == 1 and not U._JOINING
        assert U.exact_blobs_ok() and len(C._CALL) == 1
        with C.call_scope():
            assert len(C._CALL) == 1 and len(U._SCOPE) == 1
        with U.scoped():
            assert len(C._CALL) == 1 and len(U._SCOPE) == 1
    assert _no_scope_open()


def test_cb2_u1_first_entry_opens_exactly_one_outer_call():
    from tests import u1_scope as U
    assert _no_scope_open()
    with U.scoped():
        assert len(C._CALL) == 1 and not C._ENTERING and len(U._SCOPE) == 1 and not U._JOINING
        with C.call_scope():
            assert len(C._CALL) == 1 and len(U._SCOPE) == 1
    assert _no_scope_open()


@pytest.mark.parametrize("first", ["registry", "u1"])
def test_cb2_an_exception_in_the_block_unwinds_every_scope(first):
    from tests import u1_scope as U

    class Boom(Exception):
        pass
    with pytest.raises(Boom):
        with (C.call_scope() if first == "registry" else U.scoped()):
            assert len(C._CALL) == 1
            raise Boom()
    assert _no_scope_open()


def test_cb2_an_exception_while_entering_a_cohort_clears_the_marker_and_every_entered_scope(monkeypatch):
    from tests import u1_scope as U

    class Boom(Exception):
        pass

    def broken():
        raise Boom()
    monkeypatch.setattr(T, "scoped", broken)          # the LAST registered cohort: every earlier scope (U1 included) is already entered
    with pytest.raises(Boom):
        with C.call_scope():
            raise AssertionError("the block must never run when a cohort scope fails to enter")
    assert _no_scope_open()
    monkeypatch.undo()
    with C.call_scope():                              # the next call is a NEW, complete outer call
        assert len(C._CALL) == 1 and C.valid() is True
    assert _no_scope_open()


def test_cb2_a_mutation_between_two_registry_calls_is_seen(subject):
    from tests import u1_scope as U
    f = subject / "tests/u1_scope.py"
    raw = f.read_bytes()
    with C.call_scope():
        assert U.exact_blobs_ok(subject) and len(C._CALL) == 1
    try:
        f.write_bytes(raw + b"\n# unreviewed\n")
        with C.call_scope():
            assert len(C._CALL) == 1 and not U.exact_blobs_ok(subject)
        assert _no_scope_open()
    finally:
        f.write_bytes(raw)
    with C.call_scope():
        assert U.exact_blobs_ok(subject)
    assert _no_scope_open()
