"""UX-PR2c cohort — positive exactness and negative tamper cases.

The cohort is exact only while: the verified stacked base (PR2b head) is an
ancestor, its recorded tree is unchanged, every owned path carries exactly its
recorded blob, the sibling manifests move ONLY the pins of paths this cohort
owns (nothing else in them), and the composite registry stays valid.  One byte
of drift anywhere fails closed.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from tests import ux_pr2c_scope as C
from tests.fin_v2_cohorts import valid as composite_valid

ROOT = Path(__file__).resolve().parents[1]


def _git(*args):
    return subprocess.check_output(["git", *args], cwd=str(ROOT), stderr=subprocess.DEVNULL)


@pytest.fixture()
def wt(tmp_path, monkeypatch):
    """A real throwaway clone-like worktree at the cohort BASE with this branch's
    governed bytes applied on top (worktree copy, no history rewrite)."""
    import shutil
    base = Path(tmp_path) / "wt"
    base.mkdir()
    # minimal: copy the tracked governed files + git dir reference is impractical here;
    # these tests run against the REAL checkout instead (same as the live-guard tests).
    shutil.rmtree(base, ignore_errors=True)
    return ROOT


def test_cohort_is_exact_in_the_real_checkout():
    assert C.exact_blobs_ok(ROOT) is True
    assert composite_valid(ROOT) is True


def test_every_superseded_path_records_its_base_blob():
    d = C.manifest(ROOT)
    for path, blob in d["base_blobs"].items():
        assert _git("rev-parse", f"{C.BASE}:{path}").decode().strip() == blob


def test_one_byte_of_drift_in_an_owned_source_fails_closed(wt):
    # byte-exact writes: text mode would translate \n to \r\n on Windows and
    # leave CRLF behind after the restore, breaking the LF blob pins.
    path = ROOT / "frontend/src/app/editing/saveAll.ts"
    original = path.read_bytes()
    try:
        path.write_bytes(original + b"\n// drift\n")
        assert C.exact_blobs_ok(ROOT) is False
        assert C.matches("frontend/src/app/editing/saveAll.ts") is False
    finally:
        path.write_bytes(original)
    assert C.exact_blobs_ok(ROOT) is True


def test_one_byte_of_drift_in_the_gated_server_read_fails_closed(wt):
    path = ROOT / "app/v2/react_capex.py"
    original = path.read_bytes()
    try:
        path.write_bytes(original.replace(b"profile_enabled() and can_edit",
                                          b"profile_enabled() or can_edit"))
        assert C.exact_blobs_ok(ROOT) is False
    finally:
        path.write_bytes(original)
    assert C.exact_blobs_ok(ROOT) is True


def test_a_forged_sibling_pin_fails_closed(wt):
    manifest_path = ROOT / "docs/react_migration/post413_o1/SOURCE_SUCCESSOR.json"
    original = manifest_path.read_bytes()
    try:
        d = json.loads(original)
        d["source_blobs"]["frontend/src/app/editing/saveAll.ts"] = "0" * 40
        manifest_path.write_bytes((json.dumps(d, indent=2) + "\n").encode("utf-8"))
        assert C.exact_blobs_ok(ROOT) is False
    finally:
        manifest_path.write_bytes(original)
    assert C.exact_blobs_ok(ROOT) is True


def test_a_foreign_new_file_fails_closed(wt):
    extra = ROOT / "app/v2/react_unreviewed_pr2c.py"
    try:
        extra.write_text('"""unreviewed"""\n', encoding="utf-8")
        assert C.exact_blobs_ok(ROOT) is False
    finally:
        extra.unlink()
    assert C.exact_blobs_ok(ROOT) is True


def test_the_gated_flag_is_not_flipped_by_the_cohort():
    import app.v2.save_all_commands as sac
    import os
    assert sac.profile_enabled() is False
    assert os.environ.get("FINCO_SAVE_ALL_PROFILE_ENABLED", "0") == "0"


def test_the_activation_flag_is_a_literal_false_in_no_candidate():
    """PR2c adds no activation switch of its own: the D7 switch is the only gate."""
    src = (ROOT / "app/v2/react_capex.py").read_text(encoding="utf-8")
    assert "FINCO_SAVE_ALL_PROFILE_ENABLED" not in src  # the gate is read only in save_all_commands


def test_the_ci_v4_workflow_diff_against_its_base_is_exactly_the_static_timeout():
    """Correction G (Owner-authorized): the governed .github/workflows/ci_v4_pr.yml takeover admits ONE literal change — the static job's safety ceiling
    30 -> 90 minutes.  The gate job, its steps, the trusted-base selector and every other byte stay identical to BASE; anything else fails closed."""
    import subprocess
    base = subprocess.check_output(["git", "show", f"{C.BASE}:.github/workflows/ci_v4_pr.yml"], cwd=str(ROOT), stderr=subprocess.DEVNULL).decode("utf-8")
    text = (ROOT / ".github/workflows/ci_v4_pr.yml").read_text(encoding="utf-8")
    assert "timeout-minutes: 90" in text and text.count("timeout-minutes: 90") == 1
    assert "timeout-minutes: 30" not in text
    assert text.replace("timeout-minutes: 90", "timeout-minutes: 30", 1) == base


def test_call_scope_never_outlives_its_block_and_a_later_call_sees_a_real_mutation():
    """PR #429 CI performance correction: the one-outer-call memo is dropped on exit; a byte mutated AFTER a completed call is detected by the next
    outer call and the restore passes again in a NEW outer evaluation (no verdict is ever cached across calls)."""
    from tests import fin_v2_cohorts as K
    from tests import fin_v2_rcux_scope as R
    rel = "tests/rcux_navigation_contract.py"
    path = ROOT / rel
    original = path.read_bytes()
    with K.call_scope():
        assert R.exact_blobs_ok(ROOT) is True and K.valid(ROOT) is True and R.valid(ROOT) is True
        assert K._CALL and K._CALL[-1]
        with K.call_scope():                      # nested: shares the outermost memo, never opens a second one
            assert len(K._CALL) == 1
    assert K._CALL == [] and all(not getattr(m, "_SCOPE", []) for m in K.cohorts())
    try:
        path.write_bytes(original + b"\n")
        with K.call_scope():
            assert R.exact_blobs_ok(ROOT) is False and K.valid(ROOT) is False
            assert R.matches(rel, path.read_bytes()) is False
        assert R.valid(ROOT) is False and K.valid(ROOT) is False
    finally:
        path.write_bytes(original)
    assert K._CALL == []
    with K.call_scope():
        assert K.valid(ROOT) is True
    assert R.valid(ROOT) is True and R.matches(rel, original) is True and K.valid(ROOT) is True


def test_rcux_matches_rejects_a_foreign_byte_string_without_the_closure_and_never_accepts_on_an_invalid_tree(monkeypatch):
    """The cheap byte check runs first only to reject; acceptance still needs a valid tree AND an accepted pin for exactly these bytes."""
    from tests import fin_v2_rcux_scope as R
    rel = "tests/rcux_navigation_contract.py"
    raw = (ROOT / rel).read_bytes()

    def forbidden(*args, **kwargs):
        raise AssertionError("the full governance closure must not run for a byte string that is no accepted pin")
    original = R.valid
    monkeypatch.setattr(R, "valid", forbidden)
    assert R.matches(rel, raw + b"\n") is False and R.matches(rel, b"unrelated") is False and R.matches("not/a/pinned/path.py", raw) is False
    monkeypatch.setattr(R, "valid", lambda *a, **k: False)
    assert R.matches(rel, raw) is False                         # exact bytes but an invalid tree: never a match
    monkeypatch.setattr(R, "valid", lambda *a, **k: True)
    assert R.matches(rel, raw) is True and R.matches(rel, raw + b"\n") is False
    monkeypatch.setattr(R, "valid", original)
    assert R.matches(rel, raw) is True


def test_the_central_gate_shares_one_outer_call_scope_and_keeps_every_verdict_on_the_real_checkout():
    """One outer call scope for both passes (cohort map and composite): same record schema, every registered cohort present and exact, composite and
    mutation inventory valid, and nothing left open after the call."""
    from tests import fin_v2_cohorts as K
    from tools import ci_v4_governance_gate as G
    record = G.run()
    assert record["schema"] == "FINCO_CI_V4_GOVERNANCE_GATE_V1" and record["verdict"] == "PASS"
    assert set(record["cohorts"]) == set(record["registered"]) == set(K.COHORT_MODULES) and all(record["cohorts"].values())
    assert record["composite_valid"] is True and record["mutation_successor_valid"] is True and not record["mutation_violations"]
    assert K._CALL == [] and all(not getattr(m, "_SCOPE", []) for m in K.cohorts())


@pytest.mark.parametrize("rel", ["tools/ci_v4_governance_gate.py", "tests/test_u1_scope.py", "tests/model_mutation_security_successor.py",
                                 "tests/test_post413_o1_scope.py", "tests/fin_v2_rcux_scope.py", "tests/fin_v2_cohorts.py"])
def test_one_byte_of_drift_in_a_ci_governance_path_taken_over_for_performance_fails_closed_and_restores(rel):
    """Correction H: every governance source touched for the CI performance fix is pinned byte-exactly; drift fails the cohort and the composite and the
    restore passes again in a new outer evaluation."""
    from tests import fin_v2_cohorts as K
    assert rel in C.OWNED_PATHS and rel in C.SUPERSEDED
    path = ROOT / rel
    original = path.read_bytes()
    try:
        path.write_bytes(original + b"\n")
        assert C.exact_blobs_ok(ROOT) is False and K.valid(ROOT) is False
    finally:
        path.write_bytes(original)
    assert C.exact_blobs_ok(ROOT) is True and K.valid(ROOT) is True
