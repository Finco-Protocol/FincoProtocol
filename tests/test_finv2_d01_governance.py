"""FIN-V2-D01 governance: one additive, exact-blob successor for the one-driver sensitivity route.

Historical pin layers stay immutable and individually admitted; the change is confined to one handler of
``app/v2/router.py``; the operation-bound CSRF gates, the protected-reference guard and the D-029 run order are untouched.
"""
import ast
import subprocess

import pytest

from tests import finval_f01_scope as F01
from tests import model_mutation_security_successor as S

BASELINE = "128bf0c2"             # main after merged PR #389 (F01)
D01_SOURCE_HEAD = "f951174b8f55d25b758a3acae3d331cbdd30da8c"        # the reviewed FIN-V2-D01/D02 source head (PR #392)
FIN_V2_3_SOURCE_HEAD = "65a04560592d84daf6439c0dc09a34456f5707a3"   # the reviewed FIN-V2-3 source head (PR #391)
ROUTER = "app/v2/router.py"
HANDLER = "v2_scenario_sensitivity_run"
SOURCES = {p: (S.ROOT / p).read_text(encoding="utf-8") for p in S.BLOBS}


def _git(*args):
    return subprocess.check_output(["git", *args], cwd=S.ROOT, stderr=subprocess.DEVNULL).decode("utf-8")


def _base():
    """Only what THIS branch changed: the merge-base with main, so a forward merge of newer reviewed main is not attributed here."""
    try:
        return _git("merge-base", "HEAD", "origin/main").strip()
    except subprocess.CalledProcessError:
        return BASELINE


def _is_ancestor(commit):
    return subprocess.run(["git", "merge-base", "--is-ancestor", commit, "HEAD"], cwd=S.ROOT, capture_output=True).returncode == 0


def _composed_parent_router():
    """The router this change is applied on top of. Standalone: main at the merge-base. Integrated with the separately reviewed FIN-V2-3 PR: that PR's
    reviewed router (its changes are attributed to its own exact-blob cohort, never to this change)."""
    if _is_ancestor(FIN_V2_3_SOURCE_HEAD):
        return _git("show", FIN_V2_3_SOURCE_HEAD + ":" + ROUTER)
    return _git("show", _base() + ":" + ROUTER)


def _cohort_matches(path, source):
    try:
        from tests.fin_v2_cohorts import matches
    except ImportError:
        return False
    return matches(path, source)


def _blob_source(blob):
    return subprocess.check_output(["git", "cat-file", "blob", blob], cwd=S.ROOT).decode("utf-8")


def test_layer_is_exactly_one_additive_path_and_the_current_router_is_admitted():
    assert set(S.FINV2_D01_SENSITIVITY_SUCCESSORS) == {ROUTER} == set(F01.SUCCESSORS)
    blob = S.FINV2_D01_SENSITIVITY_SUCCESSORS[ROUTER]
    assert len(blob) == 40 and blob == F01.SUCCESSORS[ROUTER]
    assert blob not in {S.BLOBS[ROUTER], S.FINVAL_B2C1_SUCCESSORS[ROUTER], S.D029_RUN_INTENT_SUCCESSORS[ROUTER],
                        S.FINVAL_RATE_SUCCESSORS[ROUTER], S.FINVAL_F01_COMPLETE_SUCCESSORS[ROUTER]}    # a NEW reviewed state
    # the D01 state, or — once the separately reviewed FIN-V2-3 changes are integrated — the exact composed router pinned by the cohort registry
    assert S.git_blob(SOURCES[ROUTER]) == blob or _cohort_matches(ROUTER, SOURCES[ROUTER])
    assert S.violations(SOURCES) == [] and S.current_mutation_successor_valid()
    assert F01.valid()


def test_one_byte_of_drift_in_the_router_fails_closed_in_both_registers():
    changed = dict(SOURCES)
    changed[ROUTER] += "\n"
    assert S.violations(changed)
    assert not F01.valid(sources={**{p: (S.ROOT / p).read_bytes() for p in F01.SOURCES}, ROUTER: changed[ROUTER].encode()})


@pytest.mark.parametrize("layer", ["BLOBS", "FINVAL_B2C1_SUCCESSORS", "D029_RUN_INTENT_SUCCESSORS", "FINVAL_RATE_SUCCESSORS",
                                   "FINVAL_F01_COMPLETE_SUCCESSORS"])
def test_every_earlier_router_state_remains_individually_admitted(layer):
    historical = dict(SOURCES)
    historical[ROUTER] = _blob_source(getattr(S, layer)[ROUTER])
    assert not [e for e in S.violations(historical) if e.startswith(ROUTER + ": unreviewed")]


def test_f01_scope_keeps_every_other_path_pinned_to_its_f01_blob():
    assert set(F01.SUCCESSORS) <= set(F01.SOURCES)
    for path in F01.SOURCES:
        if path == ROUTER:
            continue
        sources = {p: (S.ROOT / p).read_bytes() for p in F01.SOURCES}
        sources[path] += b"\n"
        assert not F01.valid(sources=sources)


def test_the_router_change_is_confined_to_the_one_driver_sensitivity_handler():
    base = ast.parse(_composed_parent_router())
    now = ast.parse(SOURCES[ROUTER])

    def top(tree):
        return {(type(n).__name__, getattr(n, "name", None) or ast.dump(n)): ast.dump(n) for n in tree.body}

    old, new = top(base), top(now)
    assert set(old) == set(new)                                  # no handler/import/constant added or removed at module level
    changed = sorted(k for k in old if old[k] != new[k])
    expected = [("AsyncFunctionDef", HANDLER)]
    # WF-03 successor lineage: exactly two further handlers carry the archived / incomplete-creation guards, and only while the WF-03 cohort pins this
    # exact router blob. Nothing else may differ.
    from tests import wf03_lifecycle_scope as WF03
    if WF03.matches(ROUTER, SOURCES[ROUTER]):
        expected = sorted(expected + [("AsyncFunctionDef", "v2_workbook"), ("AsyncFunctionDef", "v2_workbook_run")])
    assert changed == expected


def test_d029_run_order_csrf_gates_and_protected_reference_guard_are_unchanged():
    assert S.d029_run_order_violations(SOURCES[ROUTER]) == []
    base_sources = dict(SOURCES)
    base_sources[ROUTER] = _composed_parent_router()
    assert S.d029_run_order_violations(base_sources[ROUTER]) == []
    old, new = ast.parse(base_sources[ROUTER]), ast.parse(SOURCES[ROUTER])
    gate_calls = lambda tree: sorted(ast.dump(n) for n in ast.walk(tree)
                                     if isinstance(n, ast.Call) and getattr(n.func, "id", getattr(n.func, "attr", "")) in
                                     ("validate_mutation_token", "validate_csrf_token", "is_protected_reference"))
    # the handler gained no new gate call and lost none
    handler = lambda tree: next(n for n in tree.body if getattr(n, "name", None) == HANDLER)
    assert gate_calls(handler(old)) == gate_calls(handler(new))


PROTECTED_UNTOUCHED = (
    "app/services/sensitivity_matrix.py", "app/v2/sensitivity_matrix_projection.py", "app/v2/react_workspace_router.py",
    "app/v2/react_poc_router.py", "app/input_adapter.py", "main_web.py", "app/runtime/model_execution.py",
)


@pytest.mark.parametrize("path", PROTECTED_UNTOUCHED)
def test_protected_financial_and_react_sources_are_byte_identical_to_main(path):
    current = (S.ROOT / path).read_text(encoding="utf-8")
    # identical to main, or exactly the bytes another reviewed cohort pins (never an unreviewed change)
    assert _git("rev-parse", _base() + ":" + path).strip() == S.git_blob(current) or _cohort_matches(path, current)


def test_no_engine_native_react_or_frontend_path_is_touched_by_this_change():
    changed = set(_git("diff", "--name-only", _base()).split()) | set(_git("ls-files", "--others", "--exclude-standard").split())
    forbidden = ("financial_engine/", "finco_core/", "domain/", "frontend/", "static/react/", ".github/")
    assert [p for p in changed if (p.startswith(forbidden) or p.startswith("app/v2/react_")) and not _cohort_matches(p, None)] == []
