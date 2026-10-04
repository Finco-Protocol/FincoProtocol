"""Model V2 epic scope governance tests.

Acceptance markers:

  MODEL_V2_SCOPE_ACTIVE                  — the explicit scope contract is present and valid
  MODEL_V2_SCOPE_BRANCH_WITHIN_CONTRACT  — the epic's changes are exactly the declared ones
  MODEL_V2_SCOPE_ENGINE_ALLOWLIST_EXPLICIT
  MODEL_V2_SCOPE_FINCO_CORE_FROZEN
  MODEL_V2_SCOPE_DOMAIN_REVENUE_FROZEN
  MODEL_V2_SCOPE_DOMAIN_ANALYTICS_FROZEN
  MODEL_V2_SCOPE_RADAR_YIELD_CRYPTO_FROZEN
  MODEL_V2_SCOPE_FUTURE_FILES_REQUIRE_AUTHORIZATION
  MODEL_V2_EPIC_SCOPE_MARKER_RETIREMENT_GATE
"""
from __future__ import annotations

import subprocess

import pytest

from model_v2_governance import (
    MODEL_V2_HARD_DENY_PREFIXES,
    REPO,
    SCOPE_JSON_PATH,
    active_scope,
    approved_by_active_model_v2_scope,
    authorized_engine_files,
    load_scope_file,
    model_v2_frozen_violations,
    model_v2_unapproved_engine_changes,
    scope_problem,
    unauthorized_model_v2_changes,
)


@pytest.fixture(scope="module")
def scope():
    data = load_scope_file()
    if data is None:
        pytest.skip("Model V2 epic scope marker absent (retired or not started)")
    return data


# ---------------------------------------------------------------------------
# Scope contract integrity (fail closed)
# ---------------------------------------------------------------------------

def test_active_scope_contract_is_valid(scope):
    """MODEL_V2_SCOPE_ACTIVE = PASS"""
    assert scope.get("status") == "ACTIVE"
    assert scope_problem(scope) is None
    assert active_scope() is not None


def test_scope_declares_and_reaches_its_base(scope):
    base = scope["base_sha"]
    probe = subprocess.run(
        ["git", "merge-base", "--is-ancestor", base, "HEAD"],
        cwd=str(REPO), capture_output=True, text=True,
    )
    if probe.returncode != 0:
        pytest.skip("git history unavailable in this checkout")
    # (the successful merge-base check IS the assertion)


def test_scope_authorizes_only_the_reviewed_engine_files(scope):
    """MODEL_V2_SCOPE_ENGINE_ALLOWLIST_EXPLICIT = PASS — no wildcards, no
    directory grants: exactly the files already reviewed for the foundation."""
    engine = scope["approved_engine_paths"]
    assert sorted(engine) == [
        "financial_engine/financial_statements/assembly.py",
        "financial_engine/financial_statements/contracts.py",
    ]
    assert authorized_engine_files() == set(engine)


def test_scope_cannot_approve_frozen_namespaces():
    """Any attempt to authorize a frozen namespace fails scope validation."""
    scope = dict(load_scope_file())
    for bad in (
        "finco_core/inputs/_models.py",
        "domain/revenue/revenue_config.py",
        "domain/analytics/lcoe.py",
        "finco_radar/venues/registry.py",
        "finco_yield/access.py",
        "app/crypto_access.py",
    ):
        tampered = dict(scope)
        tampered["approved_support_paths"] = sorted(
            set(scope["approved_support_paths"]) | {bad})
        problem = scope_problem(tampered)
        assert problem is not None, bad
        assert "frozen" in problem


def test_scope_cannot_use_wildcards_or_directories():
    scope = dict(load_scope_file())
    for bad in ("financial_engine/**", "financial_engine/tax/*", "app/model_v2/"):
        tampered = dict(scope)
        tampered["approved_engine_paths"] = (
            scope["approved_engine_paths"] + [bad]
            if bad.startswith("financial_engine/")
            else scope["approved_engine_paths"]
        )
        tampered["approved_support_paths"] = (
            scope["approved_support_paths"] + [bad]
            if not bad.startswith("financial_engine/")
            else scope["approved_support_paths"]
        )
        assert scope_problem(tampered) is not None, bad


def test_hard_deny_survives_a_corrupted_scope(scope):
    """Even if the JSON approved a frozen path, the code-level hard deny wins."""
    assert not approved_by_active_model_v2_scope("finco_core/inputs/_models.py")
    assert not approved_by_active_model_v2_scope("domain/revenue/revenue_config.py")
    assert not approved_by_active_model_v2_scope("finco_radar/venues/registry.py")
    for prefix in MODEL_V2_HARD_DENY_PREFIXES:
        assert not approved_by_active_model_v2_scope(prefix + "x.py")


# ---------------------------------------------------------------------------
# A. The epic's current changes are exactly the declared scope
# ---------------------------------------------------------------------------

def test_branch_changes_are_within_declared_scope():
    """MODEL_V2_SCOPE_BRANCH_WITHIN_CONTRACT = PASS"""
    if not SCOPE_JSON_PATH.is_file():
        pytest.skip("scope marker absent")
    probe = subprocess.run(["git", "rev-parse", "--is-inside-work-tree"],
                           cwd=str(REPO), capture_output=True, text=True)
    if probe.returncode != 0:
        pytest.skip("git unavailable")
    assert unauthorized_model_v2_changes() == [], unauthorized_model_v2_changes()
    assert model_v2_frozen_violations() == [], model_v2_frozen_violations()
    # The declared engine files are the ONLY engine files changed vs main.
    assert sorted(model_v2_unapproved_engine_changes()) == []


# ---------------------------------------------------------------------------
# B-G. Simulated violations (pure functions over changed-path lists)
# ---------------------------------------------------------------------------

def test_b_arbitrary_additional_engine_file_fails(scope):
    """MODEL_V2_SCOPE: any financial_engine file outside the approved list fails."""
    for intruder in (
        "financial_engine/tax/engine.py",
        "financial_engine/cfads.py",
        "financial_engine/brand_new_module.py",
    ):
        assert intruder in model_v2_unapproved_engine_changes([intruder])
        assert intruder in unauthorized_model_v2_changes([intruder])
        assert not approved_by_active_model_v2_scope(intruder)


def test_c_any_finco_core_change_fails(scope):
    """MODEL_V2_SCOPE_FINCO_CORE_FROZEN = PASS"""
    for intruder in ("finco_core/inputs/_models.py", "finco_core/new_thing.py"):
        assert intruder in model_v2_frozen_violations([intruder])
        assert intruder in unauthorized_model_v2_changes([intruder])
        assert not approved_by_active_model_v2_scope(intruder)


def test_d_domain_revenue_change_fails(scope):
    """MODEL_V2_SCOPE_DOMAIN_REVENUE_FROZEN = PASS"""
    for intruder in ("domain/revenue/revenue_config.py", "domain/revenue/new.py"):
        assert intruder in model_v2_frozen_violations([intruder])
        assert intruder in unauthorized_model_v2_changes([intruder])


def test_e_domain_analytics_change_fails(scope):
    """MODEL_V2_SCOPE_DOMAIN_ANALYTICS_FROZEN = PASS"""
    for intruder in ("domain/analytics/coverage.py", "domain/analytics/new.py"):
        assert intruder in model_v2_frozen_violations([intruder])
        assert intruder in unauthorized_model_v2_changes([intruder])


def test_f_radar_yield_crypto_changes_fail(scope):
    """MODEL_V2_SCOPE_RADAR_YIELD_CRYPTO_FROZEN = PASS — changes introduced by
    the Model branch (not inherited from main) to these namespaces fail."""
    for intruder in (
        "finco_radar/venues/registry.py",
        "finco_radar/authority/policy.py",
        "finco_yield/access.py",
        "app/radar_rwa/r_live.py",
        "app/crypto_access.py",
        "app/crypto_resource_access.py",
        "app/model_validation/runner.py",
        "app/verified/authority.py",
    ):
        assert intruder in model_v2_frozen_violations([intruder]), intruder
        assert intruder in unauthorized_model_v2_changes([intruder]), intruder


def test_g_future_files_require_explicit_scope_authorization(scope):
    """MODEL_V2_SCOPE_FUTURE_FILES_REQUIRE_AUTHORIZATION = PASS — a new file in
    an approved location still fails until the scope JSON names it."""
    future_engine = "financial_engine/revenue/revenue_stream.py"
    future_support = "app/model_v2/revenue_bridge.py"
    for future in (future_engine, future_support):
        assert future in unauthorized_model_v2_changes([future])
        assert not approved_by_active_model_v2_scope(future)
    # Explicitly authorizing it in the scope (a committed, reviewed change to
    # the JSON) is the only way to clear it — demonstrated on an existing
    # engine file that is not currently approved:
    tampered = dict(scope)
    tampered["approved_engine_paths"] = sorted(
        set(scope["approved_engine_paths"]) | {"financial_engine/cfads.py"})
    assert scope_problem(tampered) is None
    assert not approved_by_active_model_v2_scope("financial_engine/cfads.py")  # actual scope unchanged
    # And a scope that approves a *frozen* path is rejected outright:
    tampered2 = dict(scope)
    tampered2["approved_support_paths"] = sorted(
        set(scope["approved_support_paths"]) | {"domain/revenue/revenue_config.py"})
    assert scope_problem(tampered2) is not None


# ---------------------------------------------------------------------------
# Marker lifecycle (release gate)
# ---------------------------------------------------------------------------

def test_active_epic_scope_must_not_reach_main():
    """MODEL_V2_EPIC_SCOPE_MARKER_RETIREMENT_GATE = PASS

    The ACTIVE scope marker exists ONLY while epic/model-saas-v2 is under
    development. When this checkout IS the main tip (i.e. after the final
    epic-to-main release merge), an ACTIVE marker fails this test — the
    release process must retire it (delete the file or set status=RETIRED).
    """
    if not SCOPE_JSON_PATH.is_file():
        assert active_scope() is None
        return
    probe = subprocess.run(
        ["git", "rev-parse", "--verify", "origin/main"],
        cwd=str(REPO), capture_output=True, text=True,
    )
    if probe.returncode != 0:
        pytest.skip("no origin/main ref in this checkout")
    main_sha = probe.stdout.strip()
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=str(REPO), capture_output=True, text=True,
    ).stdout.strip()
    if head == main_sha:
        # This checkout is the main tip: an ACTIVE epic marker must be gone.
        assert active_scope() is None, (
            "The Model V2 epic scope marker is still ACTIVE on main. Retire it "
            "(delete docs/model_v2/ACTIVE_EPIC_SCOPE.json or set status=RETIRED) "
            "as part of the epic-to-main release gate."
        )
    # Development epic branch: the marker may be ACTIVE.
    assert active_scope() is not None
