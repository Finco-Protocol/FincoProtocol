"""Governance tests for the T01-D tax-reference-registry exact-source cohort.

Positives: the cohort's manifest pins exact blobs for exactly the registry
paths, the accepted parent (main after #430) is an authenticated ancestor, the
cohort is registered in the composite registry, and every changed registry path
is admitted. Negatives: an unsigned byte, a path addition, a forged manifest,
a wrong schema/base/tree, an unrelated protected module, a wrong-ref source
and an absent activation guard all fail closed.

State note: the composite registry on main is legitimately in a
between-integrations drift state (other workstreams re-pin their own
manifests). This cohort therefore asserts its OWN exactness and admission -
never a global valid() verdict it does not own.

Blob semantics: pins and working-tree comparisons use git's own hashing
(`git hash-object`, clean filters applied), so a verdict is identical on LF
and CRLF checkouts and always equals the ls-tree blob.

Low level only: git objects and this cohort's manifest. No financial runtime.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from tests import tax_reference_registry_scope as cohort

ROOT = Path(__file__).resolve().parents[1]


def _git(*args):
    return subprocess.check_output(["git", *args], cwd=ROOT).decode().strip()


def _git_blob(path):
    return subprocess.check_output(
        ["git", "hash-object", str(ROOT / path)], cwd=ROOT
    ).decode().strip()


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
def restored_registry_file():
    target = ROOT / "tax_reference_registry" / "records.py"
    original = target.read_bytes()
    yield target
    target.write_bytes(original)


# -- positives --
def test_manifest_schema_and_pins_complete():
    data = _manifest_json()
    assert data["schema_version"] == cohort.SCHEMA
    assert data["base"] == cohort.BASE
    assert data["base_tree"] == cohort.BASE_TREE
    assert set(data["source_blobs"]) == cohort.OWNED_PATHS - {cohort.MANIFEST}
    assert set(data["base_blobs"]) == cohort.SUPERSEDED


def test_accepted_parent_is_ancestor_with_recorded_tree():
    assert _git("merge-base", "--is-ancestor", cohort.BASE, "HEAD") == ""
    assert _git("rev-parse", cohort.BASE + "^{tree}") == cohort.BASE_TREE


def test_cohort_is_registered_in_the_composite_registry():
    from tests.fin_v2_cohorts import COHORT_MODULES

    assert cohort.__name__ in COHORT_MODULES


def test_exact_blobs_ok_on_head():
    assert cohort.exact_blobs_ok() is True


def test_every_owned_pin_equals_the_current_blob():
    for path, pin in _manifest_json()["source_blobs"].items():
        assert _git_blob(path) == pin, path


def test_shared_composite_registry_blob_is_re_pinned_everywhere():
    """The one shared file this cohort moved is pinned at the SAME new blob in
    every sibling manifest that pins it (the established integration re-pin
    pattern; historical blobs stay in git history and in base_blobs)."""
    import glob

    current = _git_blob("tests/fin_v2_cohorts.py")
    stale = []
    for path in glob.glob("docs/**/*.json", recursive=True):
        try:
            data = json.loads(Path(path).read_text(encoding="utf-8"))
        except (ValueError, OSError):
            continue
        if not isinstance(data, dict):
            continue
        pin = (data.get("source_blobs") or {}).get("tests/fin_v2_cohorts.py")
        if pin is not None and pin != current:
            stale.append(path)
    assert stale == [], f"stale shared-registry pins: {stale}"


def test_registry_paths_admitted_and_financing_paths_not():
    assert cohort.allowed_path("tax_reference_registry/loader.py")
    assert cohort.allowed_path("tests/tax_reference_registry/test_schema_and_currency.py")
    assert cohort.allowed_path(cohort.MANIFEST)
    assert cohort.allowed_path("tests/fin_v2_cohorts.py")
    # #430 Financing paths are never owned by this cohort:
    assert not cohort.allowed_path("frontend/src/app/financing/FinancingStudio.tsx")
    assert not cohort.allowed_path("tests/fin_v2_cohorts.py.bak")


def test_supersedes_only_for_the_composite_registry_at_its_exact_pin():
    current_blob = _git_blob("tests/fin_v2_cohorts.py")
    assert cohort.supersedes("tests/fin_v2_cohorts.py", current_blob) is True
    assert cohort.supersedes("tests/fin_v2_cohorts.py", "0" * 40) is False
    assert cohort.supersedes("tax_reference_registry/loader.py", current_blob) is False


def test_base_blob_records_the_pre_integration_state():
    assert cohort.base_blob("tests/fin_v2_cohorts.py") == _git(
        "rev-parse", cohort.BASE + ":tests/fin_v2_cohorts.py"
    )


# -- negatives --
def test_unsigned_byte_fails_exact_check(restored_registry_file):
    target = ROOT / "tax_reference_registry" / "records.py"
    current = target.read_bytes()
    target.write_bytes(current + b"\n# tampered\n")
    assert cohort.exact_blobs_ok() is False


def test_path_addition_fails_allowed_path():
    assert cohort.allowed_path("tax_reference_registry/extra_module.py") is False
    assert cohort.allowed_path("tests/tax_reference_registry/extra_test.py") is False


def test_forged_manifest_blob_fails(restored_manifest):
    data = _manifest_json()
    data["source_blobs"]["tax_reference_registry/loader.py"] = "f" * 40
    _write_manifest(data)
    assert cohort.exact_blobs_ok() is False


def test_forged_base_fails(restored_manifest):
    data = _manifest_json()
    data["base"] = "9" * 40
    _write_manifest(data)
    assert cohort.manifest() == {}  # schema/base mismatch -> empty manifest
    assert cohort.exact_blobs_ok() is False


def test_forged_base_tree_fails(restored_manifest):
    data = _manifest_json()
    data["base_tree"] = "9" * 40
    _write_manifest(data)
    assert cohort.manifest() == {}
    assert cohort.exact_blobs_ok() is False


def test_wrong_schema_fails(restored_manifest):
    data = _manifest_json()
    data["schema_version"] = "SOME_OTHER_COHORT_V1"
    _write_manifest(data)
    assert cohort.manifest() == {}


def test_wrong_ref_source_fails():
    # At the accepted parent the manifest did not exist yet -> empty manifest.
    assert cohort.manifest(ref=cohort.BASE) == {}
    assert cohort.exact_blobs_ok(ref=cohort.BASE) is False


def test_unrelated_protected_module_never_owned():
    assert not cohort.allowed_path("financial_engine/tax/engine.py")
    assert not cohort.allowed_path("finco_core/inputs/_models.py")
    assert not cohort.allowed_path("app/v2/router.py")
    assert cohort.protected_blobs() == {}


def test_activation_guards_present_in_owned_package():
    from tax_reference_registry import (
        ActivationBlockedError,
        activate_country,
        get_effective_run_profile,
    )
    with pytest.raises(ActivationBlockedError):
        activate_country("ZZ")
    with pytest.raises(ActivationBlockedError):
        get_effective_run_profile("ZZ")
