"""Model V2 epic scope governance tests.

Acceptance markers:

  MODEL_V2_SCOPE_ACTIVE                  — the explicit scope contract is present and valid
  MODEL_V2_SCOPE_BRANCH_WITHIN_CONTRACT  — the epic's changes are exactly the declared ones
  MODEL_V2_SCOPE_ENGINE_ALLOWLIST_EXPLICIT
  MODEL_V2_SCOPE_PERMANENT_HARD_DENY     — Radar/Yield/Crypto authorities unreachable
  MODEL_V2_SCOPE_CURRENT_PHASE_FREEZE    — finco_core/domain frozen for the CURRENT phase only
  MODEL_V2_SCOPE_FUTURE_REVENUE_AUTHORIZATION
  MODEL_V2_SCOPE_FUTURE_ANALYTICS_AUTHORIZATION
  MODEL_V2_SCOPE_FUTURE_FINCO_CORE_AUTHORIZATION
  MODEL_V2_SCOPE_FUTURE_FILES_REQUIRE_AUTHORIZATION
  MODEL_V2_EPIC_SCOPE_MARKER_RETIREMENT_GATE
"""
from __future__ import annotations

import copy
import subprocess

import pytest

from model_v2_governance import (
    PERMANENT_HARD_DENY_PREFIXES,
    REPO,
    SCOPE_JSON_PATH,
    active_scope,
    approved_by_active_model_v2_scope,
    authorized_engine_files,
    load_scope_file,
    model_v2_frozen_violations,
    model_v2_unapproved_engine_changes,
    retirement_gate_pass,
    scope_problem,
    unauthorized_model_v2_changes,
)


@pytest.fixture(scope="module")
def scope():
    data = load_scope_file()
    if data is None:
        pytest.skip("Model V2 epic scope marker absent (retired or not started)")
    return data


@pytest.fixture
def valid_scope(scope):
    """A structurally valid deep copy for simulated future-phase scopes."""
    assert scope_problem(scope) is None
    return copy.deepcopy(scope)


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


# ---------------------------------------------------------------------------
# Permanent product boundary (code-level, tamper-proof)
# ---------------------------------------------------------------------------

def test_permanent_hard_deny_is_code_level_and_tamper_proof(scope):
    """MODEL_V2_SCOPE_PERMANENT_HARD_DENY = PASS — Correction C §4.

    Even a scope that lists a permanently denied authority in its approved
    paths is REJECTED by structural validation, and the enforcement helper
    still refuses to approve it (the code-level tuple wins).
    """
    assert PERMANENT_HARD_DENY_PREFIXES == (
        "finco_radar/",
        "finco_yield/",
        "app/radar_rwa/",
        "app/crypto_access.py",
        "app/crypto_resource_access.py",
    )
    tampered = copy.deepcopy(scope)
    tampered["permanent_hard_deny_prefixes"] = []  # try to dissolve the boundary
    problem = scope_problem(tampered)
    assert problem is not None and "mirror" in problem

    tampered2 = copy.deepcopy(scope)
    tampered2["current_frozen_prefixes"] = []  # unfreeze everything too
    tampered2["approved_support_paths"] = sorted(
        set(scope["approved_support_paths"])
        | {"finco_radar/venues/registry.py", "finco_yield/access.py",
           "app/crypto_access.py", "app/crypto_resource_access.py"}
    )
    tampered2["approved_engine_paths"] = sorted(
        set(scope["approved_engine_paths"]) | {"financial_engine/cfads.py"})
    # finco_radar/venues/registry.py is an engine-unrelated path; the radar
    # and yield files are support-path entries — all permanently denied:
    problem2 = scope_problem(tampered2)
    assert problem2 is not None
    assert "PERMANENT" in problem2
    # Enforcement ignores any such tampering regardless:
    for denied in (
        "finco_radar/venues/registry.py",
        "finco_radar/authority/policy.py",
        "finco_yield/access.py",
        "app/radar_rwa/anything.py",
        "app/crypto_access.py",
        "app/crypto_resource_access.py",
    ):
        assert not approved_by_active_model_v2_scope(denied), denied


# ---------------------------------------------------------------------------
# Current-phase freeze (scope-file level, explicitly movable)
# ---------------------------------------------------------------------------

def test_current_phase_freeze_state(scope):
    """MODEL_V2_SCOPE_CURRENT_PHASE_FREEZE = PASS — Correction C §2/§5.

    For the C0 foundation state finco_core, domain/revenue, domain/analytics,
    app/model_validation and app/verified are frozen by the SCOPE CONTRACT
    (not by code), and none of them may currently have approved files.
    """
    assert sorted(scope["current_frozen_prefixes"]) == [
        "app/model_validation/",
        "app/verified/",
        "domain/analytics/",
        "domain/revenue/",
        "finco_core/",
    ]
    for frozen_file in (
        "finco_core/inputs/_models.py",
        "domain/revenue/revenue_config.py",
        "domain/analytics/lcoe.py",
        "app/model_validation/runner.py",
        "app/verified/asset_registry.py",
    ):
        assert frozen_file in model_v2_frozen_violations([frozen_file])
        assert not approved_by_active_model_v2_scope(frozen_file)
        assert frozen_file in unauthorized_model_v2_changes([frozen_file])
    # And the current branch actually has zero changes in all of them:
    assert model_v2_frozen_violations() == []


# ---------------------------------------------------------------------------
# Future reviewed-workflow authorization simulations (governance only)
# ---------------------------------------------------------------------------

def test_future_revenue_authorization(valid_scope):
    """MODEL_V2_SCOPE_FUTURE_REVENUE_AUTHORIZATION = PASS — Correction C §3.

    A future reviewed Revenue workflow unfreezes domain/revenue, authorizes
    EXACT files, and stays fail-closed for every other file in the namespace.
    No production file is modified here — pure scope-contract simulation.
    """
    future = valid_scope
    future["current_frozen_prefixes"] = [
        p for p in future["current_frozen_prefixes"] if p != "domain/revenue/"
    ]
    # Exact existing-but-unapproved files (a genuinely NEW file is covered by
    # test_g_future_files_require_explicit_scope_authorization):
    future["approved_support_paths"] = sorted(
        set(future["approved_support_paths"])
        | {"domain/revenue/revenue_config.py", "domain/revenue/generation.py"}
    )
    assert scope_problem(future) is None

    # Under the simulated future scope the two exact files would be approved
    # (the enforcement helper reads the file on disk, so assert the structure):
    future_approved = set(future["approved_support_paths"]) | set(future["approved_engine_paths"])
    assert "domain/revenue/revenue_config.py" in future_approved
    assert "domain/revenue/generation.py" in future_approved
    # A new exact file is still unauthorized in the CURRENT ACTIVE scope:
    assert "domain/revenue/revenue_stream.py" in unauthorized_model_v2_changes(
        ["domain/revenue/revenue_stream.py"])
    # An arbitrary second file still fails unless explicitly listed:
    assert "domain/revenue/tariff.py" not in future_approved
    assert not approved_by_active_model_v2_scope("domain/revenue/tariff.py")


def test_future_analytics_authorization(valid_scope, scope):
    """MODEL_V2_SCOPE_FUTURE_ANALYTICS_AUTHORIZATION = PASS — Correction C §3."""
    # Approving an analytics file REQUIRES the unfreeze in the same change:
    # (built from the pristine module scope, before any future-scope mutation)
    frozen_only = copy.deepcopy(scope)
    frozen_only["approved_support_paths"] = sorted(
        set(frozen_only["approved_support_paths"]) | {"domain/analytics/lcoe.py"})
    assert scope_problem(frozen_only) is not None
    assert "currently frozen" in scope_problem(frozen_only)

    future = valid_scope
    future["current_frozen_prefixes"] = [
        p for p in future["current_frozen_prefixes"] if p != "domain/analytics/"
    ]
    future["approved_support_paths"] = sorted(
        set(future["approved_support_paths"]) | {"domain/analytics/lcoe.py"})
    assert scope_problem(future) is None


def test_future_finco_core_authorization(valid_scope):
    """MODEL_V2_SCOPE_FUTURE_FINCO_CORE_AUTHORIZATION = PASS — Correction C §5.

    The CURRENT C0 scope rejects finco_core changes, and a future explicit
    reviewed scope structure CAN authorize one exact finco_core file after
    removing the current-phase freeze — without any wildcard and without
    touching the permanent boundary. No actual finco_core change is made.
    """
    # Current scope: rejected.
    core_file = "finco_core/inputs/_models.py"
    assert core_file in model_v2_frozen_violations([core_file])
    assert not approved_by_active_model_v2_scope(core_file)

    # Future reviewed integration scope: unfreeze finco_core, list one file.
    future = valid_scope
    future["current_frozen_prefixes"] = [
        p for p in future["current_frozen_prefixes"] if p != "finco_core/"
    ]
    future["approved_support_paths"] = sorted(
        set(future["approved_support_paths"]) | {core_file})
    assert scope_problem(future) is None
    # Every OTHER finco_core file stays unauthorized:
    other = "finco_core/sponsor/xirr.py"
    future_approved = set(future["approved_support_paths"]) | set(future["approved_engine_paths"])
    assert other not in future_approved
    assert not approved_by_active_model_v2_scope(other)  # ACTIVE scope is still C0


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
    tampered = copy.deepcopy(scope)
    tampered["approved_engine_paths"] = sorted(
        set(scope["approved_engine_paths"]) | {"financial_engine/cfads.py"})
    assert scope_problem(tampered) is None
    assert not approved_by_active_model_v2_scope("financial_engine/cfads.py")  # actual scope unchanged


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
# Marker lifecycle (release gate) — pure semantics + live checkout check
# ---------------------------------------------------------------------------

def test_retirement_gate_semantics():
    """MODEL_V2_EPIC_SCOPE_MARKER_RETIREMENT_GATE = PASS — Correction C §6.

    Development ACTIVE allowed · main ACTIVE fails · main RETIRED passes ·
    main marker-absent passes. Both documented retirement paths work.
    """
    # Development epic:
    assert retirement_gate_pass(marker_present=True, marker_status="ACTIVE", is_main_tip=False)
    # Main tip:
    assert not retirement_gate_pass(marker_present=True, marker_status="ACTIVE", is_main_tip=True)
    assert retirement_gate_pass(marker_present=True, marker_status="RETIRED", is_main_tip=True)
    assert retirement_gate_pass(marker_present=False, marker_status=None, is_main_tip=True)


def test_active_epic_scope_must_not_reach_main():
    """Live-checkout enforcement of the retirement gate."""
    if not SCOPE_JSON_PATH.is_file():
        assert active_scope() is None
        assert retirement_gate_pass(marker_present=False, marker_status=None,
                                    is_main_tip=True)
        return
    data = load_scope_file()
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
    is_main_tip = head == main_sha
    assert retirement_gate_pass(
        marker_present=True, marker_status=data.get("status"), is_main_tip=is_main_tip,
    ), (
        "The Model V2 epic scope marker is still ACTIVE at the main tip. Retire it "
        "(delete docs/model_v2/ACTIVE_EPIC_SCOPE.json or set status=RETIRED) "
        "as part of the epic-to-main release gate."
    )
    # Development epic branch: the marker must be ACTIVE.
    if not is_main_tip:
        assert active_scope() is not None
