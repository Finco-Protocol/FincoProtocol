"""Overnight B — additive successor layer for the twelve pinned paths changed by the React MVP correction.

Strict negatives only; no activation or Financial-Owner assertion.  The layer lives in
``tests/model_mutation_security_successor.py`` (``REACT_MVP_CORRECTION_SUCCESSORS``) next to the original, FIN-VAL and D-029 layers.
"""
import re
import subprocess

import pytest

from tests import model_mutation_security_successor as S

BASELINE = "6f10f3927b33a5715ac6313da200d0f96c023524"          # main when the correction started
SOURCES = {p: (S.ROOT / p).read_text(encoding="utf-8") for p in S.BLOBS}
LAYER = S.REACT_MVP_CORRECTION_SUCCESSORS
EXPECTED = {
    "app/v2/react_workspace_router.py", "frontend/src/app/FinancialResults.tsx", "frontend/src/app/WorkspaceView.tsx",
    "frontend/src/app/types.ts", "frontend/src/app/workflow/ModelExportView.tsx", "frontend/src/app/workflow/ScenarioWorkspace.tsx",
    "frontend/src/app/workflow/workflowShared.tsx", "static/react/finco-react.css", "static/react/finco-react.js",
    "tests/model_react_mvp_acceptance.py", "tests/model_react_wf2_browser_acceptance.py",
    "tests/test_model_workspace_consolidation_browser.py",
}


def _git(*args):
    return subprocess.check_output(["git", *args], cwd=S.ROOT, stderr=subprocess.DEVNULL).decode("utf-8")


def _blob_source(blob):
    return subprocess.check_output(["git", "cat-file", "blob", blob], cwd=S.ROOT).decode("utf-8")


def test_layer_is_exactly_twelve_additive_paths_and_every_current_source_is_admitted():
    assert set(LAYER) == EXPECTED
    assert len(S.BLOBS) == 112 and S.SOURCE_HEAD == "1800bf6092af650f18aa6ae70e9df221797090fd"
    for path, blob in LAYER.items():
        assert path in S.BLOBS and len(blob) == 40
        assert blob not in {S.BLOBS[path], S.FINVAL_B2C1_SUCCESSORS.get(path), S.D029_RUN_INTENT_SUCCESSORS.get(path)}   # a NEW reviewed state
        # strict equality, as before: the current source is exactly the Overnight B state, or — only for a path the separately reviewed
        # RC-M layer also covers — exactly that later pinned state (never "either one")
        from tests.fin_v2_cohorts import matches as fin_v2_3_matches
        assert S.git_blob(SOURCES[path]) == S.WSV2_ACCEPTANCE_SUCCESSORS.get(path, S.WSV2_PRESENTATION_SUCCESSORS.get(path, S.WSV2_BROWSER_SUCCESSORS.get(path, S.RC_UX_SUCCESSORS.get(path, S.RC_M_SUCCESSORS.get(path, blob))))) or fin_v2_3_matches(path, SOURCES[path])   # or the exact FIN-V2-3 cohort state
    assert S.violations(SOURCES) == []
    assert S.current_mutation_successor_valid()


@pytest.mark.parametrize("path", sorted(EXPECTED))
def test_one_byte_of_drift_in_a_layer_path_fails_closed(path):
    changed = dict(SOURCES)
    changed[path] += "\n"
    assert S.violations(changed)


@pytest.mark.parametrize("path", sorted(EXPECTED))
def test_every_earlier_admitted_blob_remains_individually_admitted(path):
    earlier = {S.BLOBS[path], S.FINVAL_B2C1_SUCCESSORS.get(path), S.D029_RUN_INTENT_SUCCESSORS.get(path)} - {None}
    for blob in earlier:
        changed = dict(SOURCES)
        changed[path] = _blob_source(blob)
        assert not [e for e in S.violations(changed) if e.startswith(path + ": unreviewed")]


def test_router_and_csrf_token_module_are_not_in_the_layer_and_keep_their_pins():
    from tests.fin_v2_cohorts import matches as fin_v2_3_matches
    assert "app/v2/router.py" not in LAYER and S.TOKEN_MODULE not in LAYER
    assert S.git_blob(SOURCES["app/v2/router.py"]) in {S.BLOBS["app/v2/router.py"], S.FINVAL_B2C1_SUCCESSORS["app/v2/router.py"],
                                                       S.D029_RUN_INTENT_SUCCESSORS["app/v2/router.py"], S.FINVAL_RATE_SUCCESSORS["app/v2/router.py"],
                                                       S.FINVAL_F01_COMPLETE_SUCCESSORS["app/v2/router.py"],
                                                       S.FINV2_D01_SENSITIVITY_SUCCESSORS["app/v2/router.py"]} or fin_v2_3_matches('app/v2/router.py',SOURCES['app/v2/router.py'])
    assert S.git_blob(SOURCES[S.TOKEN_MODULE]) == S.BLOBS[S.TOKEN_MODULE]


def test_layer_is_additive_in_the_validator_and_no_historical_pin_line_was_removed():
    original = _git("show", "6b779fb52f918ec079995924df3198269d09786e:tests/model_mutation_security_successor.py")
    current = (S.ROOT / "tests/model_mutation_security_successor.py").read_text(encoding="utf-8")
    for path, blob in re.findall(r'^\s*"([^"]+)"\s*:\s*"([0-9a-f]{40})"', original, flags=re.M):
        assert '"%s": "%s"' % (path, blob) in current or '"%s":"%s"' % (path, blob) in current


def test_consolidation_browser_original_node_ids_and_the_seven_d029_wrappers_are_preserved():
    path = "tests/test_model_workspace_consolidation_browser.py"
    names = lambda text: re.findall(r"^def (test_\w+)\(", text, flags=re.M)
    for base in ("36edeeb5d9a14749fdfafcd3b60a0d384cac73ba", BASELINE):
        assert set(names(_git("show", f"{base}:{path}"))) <= set(names(SOURCES[path]))
    assert len(re.findall(r"^def test_d029_", SOURCES[path], flags=re.M)) == 2
    assert all(f"'{n}'" in SOURCES[path] for n in (
        "check_react_run_sends_a_uuid_intent_and_consumes_it_on_commit",
        "check_react_lost_response_survives_reload_and_resumes_the_original_run",
        "check_react_resume_after_the_draft_changed_never_runs_against_the_new_draft",
        "check_react_typed_outcomes_keep_or_consume_the_intent",
        "check_legacy_run_carries_a_uuid_and_consumes_it_on_commit",
        "check_legacy_lost_response_reload_and_oob_refresh_keep_the_same_run",
        "check_legacy_queued_run_after_pending_save_keeps_one_key_and_the_saved_binding"))
    assert "pytest.mark.skip" not in "".join(l for l in SOURCES[path].splitlines() if "test_onb_" in l or "test_d029_" in l)


def test_the_correction_changes_no_protected_financial_path_since_the_baseline():
    try:
        # Only what THIS branch changed: relative to the merge-base with main, so a normal forward merge of newer main
        # commits (which carry other owners' reviewed changes) is not attributed to this correction.
        try:
            base = _git("merge-base", "HEAD", "origin/main").strip()
        except subprocess.CalledProcessError:
            base = BASELINE
        changed = set(_git("diff", "--name-only", base, "HEAD").split())
        changed |= set(_git("diff", "--name-only").split()) | set(_git("diff", "--name-only", "--cached").split())
    except subprocess.CalledProcessError:
        pytest.skip("baseline commit not available in this checkout")
    forbidden = ("app/input_adapter.py", "app/persistence/projects_repository.py", "app/runtime/model_execution.py",
                 "app/v2/router.py", "app/v2/react_poc_router.py", "app/v2/returns_projection.py", "app/services/run_intent_service.py",
                 "app/persistence/run_intent_repository.py", "app/persistence/run_history_repository.py", "app/services/run_service.py")
    prefixes = ("financial_engine/", "finco_core/", "domain/", ".github/", "app/workbook/")
    # A path is excepted ONLY when the separately reviewed RC-M layer pins its exact current blob (and tests/test_rcm_governance.py
    # proves the change itself, e.g. the router differs from main only by the content-derived asset version).
    hits = [p for p in changed if (p in forbidden and p not in S.RC_M_SUCCESSORS) or p.startswith(prefixes)]
    from tests import finval_f01_scope as F01
    # F01 is an independently authorized successor, attributed only when all exact source blobs and the current-main ancestry are present.
    if F01.valid():
        hits = [p for p in hits if p not in F01.SOURCES]
    # Reviewed FIN-V2 source cohorts (exact blobs, tests/fin_v2_cohorts.py) are attributed to their own reviewed successor, never to this correction.
    from tests.fin_v2_cohorts import matches as fin_v2_cohort_matches
    hits = [p for p in hits if not fin_v2_cohort_matches(p)]
    assert hits == [], hits
