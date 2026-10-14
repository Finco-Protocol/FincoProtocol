"""Review-only successor proof; no release guard imports this proposal."""
from copy import deepcopy

import pytest

from tests import m7_bess_successor_proposal as P


@pytest.fixture(scope="module")
def facts():
    return P.collect()


def test_exact_candidate_and_immutable_rc2_checkpoint_are_preserved(facts):
    from tests.test_rc2_integration_manifest import RC2_EXACT_BLOBS, RC2_PINNED_UNCHANGED, RC2_CI_WORKFLOW, RC2_CI_WORKFLOW_CANDIDATE_BLOB
    assert P.violations(facts) == []
    for path, blob in {**RC2_EXACT_BLOBS, **RC2_PINNED_UNCHANGED,
                       RC2_CI_WORKFLOW: RC2_CI_WORKFLOW_CANDIDATE_BLOB}.items():
        assert P.git("rev-parse", f"{P.BASE}:{path}") == blob
    assert P.source_at(P.BASE, "tests/test_rc2_integration_manifest.py") == facts["historical_manifest"]


def test_original_rc2_validator_accepts_only_actual_immutable_checkpoint_facts(facts):
    from tests import test_rc2_integration_manifest as M
    rows = [r.split() for r in P.git("rev-list", "--merges", "--parents", f"{M.RC2_BASE_MAIN}..{P.BASE}").splitlines()]
    historical = {
        "merges": {pr: tuple(next(r for r in rows if len(r) == 3 and r[2] == head)) for pr, head in M.RC2_SOURCE_HEADS},
        "ancestor": {pr: P.subprocess.run(["git", "merge-base", "--is-ancestor", head, P.BASE], cwd=P.ROOT,
                                          capture_output=True).returncode == 0 for pr, head in M.RC2_SOURCE_HEADS},
        "status": [tuple(r.split("\t", 1)) for r in P.git("diff", "--name-status", "--no-renames", M.RC2_BASE_MAIN, P.BASE).splitlines()],
        "call_sites": P.csrf_sites(facts["historical_sources"]),
        "blobs": {p: P.git("rev-parse", f"{P.BASE}:{p}") for p in (*M.RC2_EXACT_BLOBS, *M.RC2_PINNED_UNCHANGED)},
        "ci_workflow_base_blob": P.git("rev-parse", f"{M.RC2_BASE_MAIN}:{M.RC2_CI_WORKFLOW}"),
        "ci_workflow_head_blob": P.git("rev-parse", f"{P.BASE}:{M.RC2_CI_WORKFLOW}"),
        "ci_workflow_base": P.source_at(M.RC2_BASE_MAIN, M.RC2_CI_WORKFLOW),
        "ci_workflow_head": P.source_at(P.BASE, M.RC2_CI_WORKFLOW),
        "router_base": P.source_at(M.RC2_BASE_MAIN, "app/v2/router.py"),
        "router_head": P.source_at(P.BASE, "app/v2/router.py"),
        "flag_sources": {p: P.source_at(P.BASE, p) for p in M.RC2_ACTIVATION_FLAG_FILES},
    }
    assert M.rc2_violations(historical) == []
    for path in historical["blobs"]:
        bad = deepcopy(historical)
        bad["blobs"][path] = "0" * 40
        assert M.rc2_violations(bad)


@pytest.mark.parametrize("path", sorted(P.PROTECTED_PROPOSAL))
@pytest.mark.parametrize("fault", ["altered", "missing", "source-claim"])
def test_every_financial_blob_mutation_is_rejected(facts, path, fault):
    bad = deepcopy(facts)
    if fault == "altered": bad["actual_blobs"][path] = "0" * 40
    elif fault == "missing": bad["actual_blobs"].pop(path)
    else: bad["candidate_blobs"][path] = bad["actual_blobs"][path] = "0" * 40
    assert P.violations(bad)


@pytest.mark.parametrize("path", sorted(P.CSRF_PROPOSAL))
def test_csrf_content_and_removed_validation_fail_closed(facts, path):
    bad = deepcopy(facts)
    bad["actual_blobs"][path] = "0" * 40
    assert P.violations(bad)
    bad = deepcopy(facts)
    bad["current_sources"][path] = bad["current_sources"][path].replace("validate_csrf_token(", "unapproved_token_check(")
    assert P.violations(bad)


@pytest.mark.parametrize("path,name", sorted(P.FLAGS.items()))
@pytest.mark.parametrize("value", ["True", "bool(0)", "False\nACTIVATION_ENABLED = True"])
def test_activation_mutations_are_rejected(facts, path, name, value):
    bad = deepcopy(facts)
    assert name + " = False" in bad["current_sources"][path]
    replacement = value.replace("ACTIVATION_ENABLED", name)
    bad["current_sources"][path] = bad["current_sources"][path].replace(name + " = False", name + " = " + replacement, 1)
    assert P.violations(bad)


@pytest.mark.parametrize("path", [
    "financial_engine/unreviewed.py", "finco_core/unreviewed.py", "domain/unreviewed.py",
    "app/workbook/run_commit.py", "app/auth.py", "app/v2/unreviewed_save.py",
    ".github/workflows/ci_public_job.yml", "tests/model_v2_governance.py",
    "tests/test_trust_readiness_controls.py", "app/trust_readiness/registry.py",
])
def test_unrelated_paths_and_guard_registry_changes_remain_blocked(facts, path):
    bad = deepcopy(facts)
    bad["current_paths"].add(path)
    bad["immutable_changed"].add(path)
    assert P.violations(bad)


@pytest.mark.parametrize("fault", ["manifest", "release", "parent", "ancestry", "scope", "governance", "historical-source", "missing-historical-source", "csrf-extra", "csrf-old-removed"])
def test_missing_evidence_provenance_scope_and_authority_are_rejected(facts, fault):
    bad = deepcopy(facts)
    if fault == "manifest": bad.pop("manifest")
    elif fault == "release": bad["manifest"]["release_approved"] = True
    elif fault == "parent": bad["base_parents"] = tuple(reversed(P.BASE_PARENTS))
    elif fault == "ancestry": bad["ancestry"] = False
    elif fault == "scope": bad["current_paths"].remove("financial_engine/bess.py")
    elif fault == "governance": bad["current_governance"] += "\nUNREVIEWED = True\n"
    elif fault == "historical-source": bad["historical_manifest"] += "\nUNREVIEWED = True\n"
    elif fault == "missing-historical-source": bad.pop("historical_manifest")
    elif fault == "csrf-extra": bad["current_sources"]["app/v2/unreviewed.py"] = "validate_csrf_token('x')"
    else: bad["current_sources"]["app/v2/investor_f4_router.py"] = ""
    assert P.violations(bad)


def test_missing_git_reference_is_not_approval(monkeypatch):
    def missing(*args):
        raise P.subprocess.CalledProcessError(128, ["git", *args])
    monkeypatch.setattr(P, "git", missing)
    assert P.current_proposal_violations()


def test_candidate_is_not_inserted_into_any_release_authority(facts):
    from tests.model_v2_governance import released_engine_authority_matches
    assert facts["manifest"]["release_approved"] is False
    assert facts["current_governance"] == facts["historical_governance"]
    for path in ("financial_engine/bess.py", "financial_engine/adapters/project_inputs.py",
                 "financial_engine/orchestrator.py", "finco_core/inputs/bess_native.py"):
        assert not released_engine_authority_matches(path)
        assert not released_engine_authority_matches(path, ref="missing-reviewed-reference")


def test_ev_book_tax_and_other_non_bess_depreciation_are_bit_exact_to_rc2():
    from tests.test_m7_bess_boundaries import historical_module
    from app import project_factories as F
    from financial_engine.adapters.project_inputs import from_project_inputs
    from finco_core.debt.depreciation_schedule import build_depreciation_schedule
    old = historical_module("financial_engine/adapters/project_inputs.py", "financial_engine.adapters.m7_depreciation_before")
    for factory in (F.create_generic_solar_reference, F.create_generic_wind_reference,
                    F.create_generic_data_center_reference, F.create_generic_ev_charging_reference):
        pi = factory()
        assert old.from_project_inputs(pi).depreciation == from_project_inputs(pi).depreciation
    pi = F.create_generic_ev_charging_reference()
    dep = from_project_inputs(pi).depreciation
    for entries in (dep.book_capex_items_for_depreciation, dep.tax_capex_items_for_depreciation):
        assert next(e for e in entries if e.name == "Charging Equipment").useful_life_override == 10
    schedule = build_depreciation_schedule((pi.capex.production_units,), horizon_years=pi.info.horizon_years)
    assert all(schedule[y] == 400 for y in range(1, 11))
    assert sum(schedule.get(y, 0) for y in range(11, pi.info.horizon_years + 1)) == 0


def test_legacy_storage_adaptation_is_compatible_but_execution_stays_rejected():
    """Correction B: the adapter keeps the historical Storage metadata/depreciation behaviour; the unsupported legacy
    spread economics are rejected at the execution boundary (no financial authority added, no silent calculation)."""
    from tests.test_m7_bess_boundaries import historical_module
    from app.project_factories import create_generic_storage_reference
    from financial_engine.adapters.project_inputs import from_project_inputs
    from financial_engine.bess import LegacyBessTechnicalInput
    from financial_engine.orchestrator import run_operating_model
    old = historical_module("financial_engine/adapters/project_inputs.py", "financial_engine.adapters.m7_storage_before")
    source = create_generic_storage_reference()
    historical = old.from_project_inputs(source)
    current = from_project_inputs(source)
    assert next(e for e in current.depreciation.book_capex_items_for_depreciation
                if e.name == "BESS Cells").useful_life_override is None
    assert current.depreciation == historical.depreciation                       # identical metadata / depreciation
    assert isinstance(current.technical, LegacyBessTechnicalInput) and current.technical.bess_legacy_unsupported
    with pytest.raises(ValueError, match="BESS_NATIVE_CONTRACT_REQUIRED"):
        run_operating_model(current)                                              # execution is still rejected


def test_non_bess_adaptation_is_unchanged_and_native_contract_is_still_required_for_native_execution():
    from app.project_factories import create_generic_solar_reference, create_generic_wind_reference
    from financial_engine.adapters.project_inputs import from_project_inputs
    for factory in (create_generic_solar_reference, create_generic_wind_reference):
        technical = from_project_inputs(factory()).technical
        assert type(technical).__name__ == "TechnicalInput" and not getattr(technical, "bess_legacy_unsupported", False)

