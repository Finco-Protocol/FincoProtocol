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
    for path, pin in cohort.effective_pins().items():
        assert _git_blob(path) == pin, path


INTEGRATION_MANIFESTS = (
    "docs/ci_v4/SOURCE_SUCCESSOR.json",
    "docs/react_migration/g10_d8/G10_D8_EXACT_SOURCE.json",
    "docs/react_migration/post413_o1/SOURCE_SUCCESSOR.json",
    "docs/react_migration/post413_r1/SOURCE_SUCCESSOR.json",
    "docs/react_migration/post413_r17/SOURCE_SUCCESSOR.json",
    "docs/react_migration/post413_r18/SOURCE_SUCCESSOR.json",
    "docs/react_migration/u2_workbench/U2_EXACT_SOURCE.json",
)


def test_shared_composite_registry_blob_is_re_pinned_only_in_the_current_integration_manifests():
    """Exactly the seven manifests the newest accepted integration (PR3b-2) re-pins carry the NEW composite-registry blob;
    every other historical manifest is byte-identical to BASE (no historical pin is ever rewritten)."""
    import glob

    current = _git_blob("tests/fin_v2_cohorts.py")
    for path in INTEGRATION_MANIFESTS:
        pin = json.loads(Path(path).read_text(encoding="utf-8"))["source_blobs"]["tests/fin_v2_cohorts.py"]
        assert pin == current, path
    rewritten = []
    for path in glob.glob("docs/**/*.json", recursive=True):
        path = path.replace("\\", "/")
        if path in INTEGRATION_MANIFESTS or path == cohort.MANIFEST:
            continue
        head = subprocess.run(["git", "rev-parse", "HEAD:" + path], capture_output=True, text=True).stdout.strip()
        base = subprocess.run(["git", "rev-parse", cohort.BASE + ":" + path], capture_output=True, text=True)
        if base.returncode == 0 and base.stdout.strip() != head:
            rewritten.append(path)
    assert rewritten == [], f"historical manifests rewritten since BASE: {rewritten}"


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


# -- bounded successor hook: PR3b-2 follows this cohort for exactly the superseded governance paths --
def _pr3b2():
    from tests import ux_pr3b2_scope

    return ux_pr3b2_scope


def test_pr3b2_follows_this_cohort_only_for_its_superseded_blobs():
    S = _pr3b2()
    for path in sorted(cohort.SUPERSEDED):
        blob = _git_blob(path)
        assert cohort.supersedes(path, blob) is True
        assert S.effective_pins().get(path) == blob  # the known successor blob is accepted through the chain
    assert S.exact_blobs_ok() is True
    assert S.allowed_path("tax_reference_registry/loader.py") is True
    # not a wildcard: a neighbouring path and a financial path stay refused
    assert S.allowed_path("tax_reference_registry/other.py") is False
    assert S.allowed_path("app/v2/router.py") is False


def test_successor_rejects_forged_unknown_and_cross_path_blobs():
    S = _pr3b2()
    path = "tests/ux_pr3b2_scope.py"
    good = _git_blob(path)
    assert S.supersedes(path, "0" * 40) is False  # forged / unknown
    assert S.supersedes(path, _git_blob("tests/fin_v2_cohorts.py")) is False  # a real blob pinned for ANOTHER path
    assert S.supersedes("tests/not_superseded.py", good) is False  # path outside the closed set
    assert cohort.supersedes("tests/ux_pr3b2_scope.py", _git_blob("tests/ux_pr3b1_scope.py")) is False  # cross-path


def test_successor_rejects_wrong_ancestor_and_tampered_cohort(restored_manifest):
    S = _pr3b2()
    # wrong ancestry: judged at the accepted parent the successor does not exist, so it contributes nothing
    assert cohort.exact_blobs_ok(ref=cohort.BASE) is False
    assert S.effective_pins(ref=cohort.BASE).get("tests/fin_v2_cohorts.py") != _git_blob("tests/fin_v2_cohorts.py")
    # a forged pin in this cohort's manifest makes it inexact, so the chain falls back to the historical pins only
    data = json.loads((ROOT / cohort.MANIFEST).read_text(encoding="utf-8"))
    data["source_blobs"]["tests/fin_v2_cohorts.py"] = "0" * 40
    (ROOT / cohort.MANIFEST).write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    assert cohort.exact_blobs_ok() is False
    assert S.effective_pins().get("tests/fin_v2_cohorts.py") != _git_blob("tests/fin_v2_cohorts.py")
    assert S.exact_blobs_ok() is False


def test_signature_ignores_unrelated_drift_but_full_exactness_does_not():
    target = ROOT / "app" / "v2" / "react_opex_lines.py"
    raw = target.read_bytes()
    try:
        target.write_bytes(raw + b"\n")
        assert cohort.signature_ok() is True
        assert cohort.exact_blobs_ok() is False  # a protected-prefix change is never admitted
    finally:
        target.write_bytes(raw)
    assert cohort.exact_blobs_ok() is True
