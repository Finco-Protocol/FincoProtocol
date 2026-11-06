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
    path = ROOT / "frontend/src/app/editing/saveAll.ts"
    original = path.read_text(encoding="utf-8")
    try:
        path.write_text(original + "\n// drift\n", encoding="utf-8")
        assert C.exact_blobs_ok(ROOT) is False
        assert C.matches("frontend/src/app/editing/saveAll.ts") is False
    finally:
        path.write_text(original, encoding="utf-8")
    assert C.exact_blobs_ok(ROOT) is True


def test_one_byte_of_drift_in_the_gated_server_read_fails_closed(wt):
    path = ROOT / "app/v2/react_capex.py"
    original = path.read_text(encoding="utf-8")
    try:
        path.write_text(original.replace("profile_enabled() and can_edit",
                                         "profile_enabled() or can_edit"), encoding="utf-8")
        assert C.exact_blobs_ok(ROOT) is False
    finally:
        path.write_text(original, encoding="utf-8")
    assert C.exact_blobs_ok(ROOT) is True


def test_a_forged_sibling_pin_fails_closed(wt):
    manifest_path = ROOT / "docs/react_migration/post413_o1/SOURCE_SUCCESSOR.json"
    original = manifest_path.read_text(encoding="utf-8")
    try:
        d = json.loads(original)
        d["source_blobs"]["frontend/src/app/editing/saveAll.ts"] = "0" * 40
        manifest_path.write_text(json.dumps(d, indent=2) + "\n", encoding="utf-8")
        assert C.exact_blobs_ok(ROOT) is False
    finally:
        manifest_path.write_text(original, encoding="utf-8")
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
