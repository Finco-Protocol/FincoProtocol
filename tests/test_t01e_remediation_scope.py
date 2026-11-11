"""Governance tests for the T01-E remediation exact-source cohort."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from tests import t01e_remediation_scope as cohort

ROOT = Path(__file__).resolve().parents[1]


def _git(*args):
    return subprocess.check_output(["git", *args], cwd=ROOT).decode().strip()


def _manifest_json():
    return json.loads((ROOT / cohort.MANIFEST).read_text(encoding="utf-8"))


def _write_manifest(data):
    (ROOT / cohort.MANIFEST).write_text(
        json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


@pytest.fixture()
def restored_manifest():
    original = (ROOT / cohort.MANIFEST).read_bytes()
    yield
    (ROOT / cohort.MANIFEST).write_bytes(original)


@pytest.fixture()
def restored_remediation():
    target = ROOT / "tax_reference_registry" / "remediation.py"
    original = target.read_bytes()
    yield target
    target.write_bytes(original)


def test_manifest_schema_and_pins():
    data = _manifest_json()
    assert data["schema_version"] == cohort.SCHEMA
    assert data["base"] == cohort.BASE
    assert data["base_tree"] == cohort.BASE_TREE
    assert set(data["source_blobs"]) == cohort.OWNED_PATHS
    assert data["base_blobs"] == {}


def test_accepted_parent_is_ancestor():
    assert _git("merge-base", "--is-ancestor", cohort.BASE, "HEAD") == ""
    assert _git("rev-parse", cohort.BASE + "^{tree}") == cohort.BASE_TREE


def test_exact_blobs_ok():
    assert cohort.exact_blobs_ok() is True


def test_cohort_registered():
    from tests.fin_v2_cohorts import COHORT_MODULES
    assert cohort.__name__ in COHORT_MODULES


def test_tampered_remediation_fails(restored_remediation):
    target = ROOT / "tax_reference_registry" / "remediation.py"
    target.write_bytes(target.read_bytes() + b"\n# tampered\n")
    assert cohort.exact_blobs_ok() is False


def test_forged_manifest_fails(restored_manifest):
    data = _manifest_json()
    data["source_blobs"]["tax_reference_registry/remediation.py"] = "f" * 40
    _write_manifest(data)
    assert cohort.exact_blobs_ok() is False


def test_foreign_path_not_admitted():
    assert not cohort.allowed_path("financial_engine/tax/engine.py")
    assert not cohort.allowed_path("app/v2/router.py")
    assert cohort.protected_blobs() == {}


def test_activation_guards_present():
    from tax_reference_registry import (
        ActivationBlockedError,
        activate_country,
        get_effective_run_profile,
    )
    with pytest.raises(ActivationBlockedError):
        activate_country("ZZ")
    with pytest.raises(ActivationBlockedError):
        get_effective_run_profile("ZZ")
