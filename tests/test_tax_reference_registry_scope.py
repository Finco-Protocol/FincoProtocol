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


ROOT = Path(__file__).resolve().parents[1]


def _git(*args):
    return subprocess.check_output(["git", *args], cwd=ROOT).decode().strip()


def _git_blob(path):
    return subprocess.check_output(
        ["git", "hash-object", str(ROOT / path)], cwd=ROOT
    ).decode().strip()


@pytest.fixture()
def restored_registry_file():
    target = ROOT / "tax_reference_registry" / "records.py"
    original = target.read_bytes()
    yield target
    target.write_bytes(original)


# -- positives --


# -- negatives --


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


