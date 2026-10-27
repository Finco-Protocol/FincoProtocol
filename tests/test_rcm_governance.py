"""RC-M — additive successor layer for the four pinned paths the React adapters changed, and the protected-path scope guard.

Strict negatives only; no activation or Financial-Owner assertion.  The layer lives in ``tests/model_mutation_security_successor.py``
(``RC_M_SUCCESSORS``) next to the original, FIN-VAL, D-029 and Overnight B layers.
"""
import re
import subprocess

import pytest

from tests import model_mutation_security_successor as S

SOURCES = {p: (S.ROOT / p).read_text(encoding="utf-8") for p in S.BLOBS}
LAYER = S.RC_M_SUCCESSORS
EXPECTED = {"app/v2/react_workspace_router.py", "frontend/src/app/WorkspaceView.tsx", "static/react/finco-react.css", "static/react/finco-react.js"}


def _git(*args):
    return subprocess.check_output(["git", *args], cwd=S.ROOT, stderr=subprocess.DEVNULL).decode("utf-8")


def _blob_source(blob):
    return subprocess.check_output(["git", "cat-file", "blob", blob], cwd=S.ROOT).decode("utf-8")


def _earlier(path):
    return {S.BLOBS[path], S.FINVAL_B2C1_SUCCESSORS.get(path), S.D029_RUN_INTENT_SUCCESSORS.get(path),
            S.REACT_MVP_CORRECTION_SUCCESSORS.get(path)} - {None}


def test_layer_is_exactly_four_additive_paths_and_the_current_sources_are_admitted():
    assert set(LAYER) == EXPECTED
    assert len(S.BLOBS) == 112 and S.SOURCE_HEAD == "1800bf6092af650f18aa6ae70e9df221797090fd"
    for path, blob in LAYER.items():
        assert path in S.BLOBS and len(blob) == 40 and blob not in _earlier(path)          # a NEW reviewed state, never a repin
        assert S.git_blob(SOURCES[path]) == blob
    assert S.violations(SOURCES) == [] and S.current_mutation_successor_valid()


@pytest.mark.parametrize("path", sorted(EXPECTED))
def test_one_byte_of_drift_in_a_layer_path_fails_closed(path):
    changed = dict(SOURCES)
    changed[path] += "\n"
    assert S.violations(changed)


@pytest.mark.parametrize("path", sorted(EXPECTED))
def test_every_earlier_admitted_blob_remains_individually_admitted(path):
    for blob in _earlier(path):
        changed = dict(SOURCES)
        changed[path] = _blob_source(blob)
        assert not [e for e in S.violations(changed) if e.startswith(path + ": unreviewed")]


def test_the_router_and_csrf_token_module_keep_their_pins():
    assert "app/v2/router.py" not in LAYER and S.TOKEN_MODULE not in LAYER
    assert S.git_blob(SOURCES[S.TOKEN_MODULE]) == S.BLOBS[S.TOKEN_MODULE]


def test_layer_is_additive_and_no_historical_pin_line_was_removed():
    original = _git("show", "6b779fb52f918ec079995924df3198269d09786e:tests/model_mutation_security_successor.py")
    current = (S.ROOT / "tests/model_mutation_security_successor.py").read_text(encoding="utf-8")
    for path, blob in re.findall(r'^\s*"([^"]+)"\s*:\s*"([0-9a-f]{40})"', original, flags=re.M):
        assert '"%s": "%s"' % (path, blob) in current or '"%s":"%s"' % (path, blob) in current


def test_the_workspace_router_changes_only_by_the_adapter_includes():
    """The pinned router gained exactly one block that mounts the five adapter modules (their own files hold the behaviour)."""
    source = SOURCES["app/v2/react_workspace_router.py"]
    tail = source[source.index("# ───────────────────────────── RC-M: React adapters"):]
    assert re.findall(r"^router\.include_router\((\w+)\)$", tail, flags=re.M) == [
        "_new_project_router", "_analysis_router", "_goal_seek_router", "_financing_router", "_investors_router"]
    assert re.findall(r"^from app\.v2\.(\w+) import router as (\w+)", tail, flags=re.M) == [
        ("react_analysis", "_analysis_router"), ("react_financing", "_financing_router"), ("react_goal_seek", "_goal_seek_router"),
        ("react_investors", "_investors_router"), ("react_new_project", "_new_project_router")]


def test_the_adapters_use_only_the_canonical_services_and_add_no_calculation_authority():
    forbidden = ("financial_engine", "finco_core", "def solve_", "def irr", "numpy", "scipy", "brentq", "newton(")
    for module in ("app/v2/react_new_project.py", "app/v2/react_analysis.py", "app/v2/react_goal_seek.py", "app/v2/react_financing.py",
                   "app/v2/react_investors.py"):
        text = (S.ROOT / module).read_text(encoding="utf-8")
        assert not [needle for needle in forbidden if needle in text], module
    # the browser carries no financial arithmetic: the new React sources contain no engine call, solver or IRR/NPV formula
    for folder in ("frontend/src/app/newProject", "frontend/src/app/analysis", "frontend/src/app/financing"):
        for path in (S.ROOT / folder).glob("*.ts*"):
            text = path.read_text(encoding="utf-8")
            assert not re.search(r"(?<![-\w])(irr|npv|dscr)\s*=\s*[^=>{]|Math\.(pow|log|exp)\(", text, flags=re.I), path


def test_the_rcm_changes_touch_no_protected_financial_path():
    try:
        try:
            base = _git("merge-base", "HEAD", "origin/main").strip()
        except subprocess.CalledProcessError:
            base = "cf7056de4078ca66afcf52265a9bacafe35586f7"
        changed = set(_git("diff", "--name-only", base, "HEAD").split())
        changed |= set(_git("diff", "--name-only").split()) | set(_git("diff", "--name-only", "--cached").split())
    except subprocess.CalledProcessError:
        pytest.skip("baseline commit not available in this checkout")
    forbidden = ("app/input_adapter.py", "app/persistence/projects_repository.py", "app/services/project_library_service.py",
                 "app/runtime/model_execution.py", "app/v2/router.py", "app/v2/react_poc_router.py", "app/v2/returns_projection.py",
                 "app/services/run_intent_service.py", "app/persistence/run_intent_repository.py", "app/persistence/run_history_repository.py",
                 "app/services/run_service.py", "app/services/reference_seed_service.py", "app/services/goal_seek.py",
                 "app/services/sensitivity_matrix.py", "app/services/projects_create_service.py", "main_web.py")
    prefixes = ("financial_engine/", "finco_core/", "domain/", ".github/", "app/workbook/", "app/capex_profiles/")
    hits = [p for p in changed if p in forbidden or p.startswith(prefixes)]
    assert hits == [], hits
    golden = [p for p in changed if re.search(r"golden|baseline_snapshot|expected_outputs", p)]
    assert golden == [], golden


def test_only_the_two_reviewed_adapters_add_a_state_changing_route_and_the_other_three_are_read_only():
    for module in ("app/v2/react_analysis.py", "app/v2/react_financing.py", "app/v2/react_investors.py"):
        text = (S.ROOT / module).read_text(encoding="utf-8")
        assert not re.search(r"@router\.(post|put|patch|delete)\(", text), module
        assert "validate_csrf_token(" not in text, module
        assert not re.search(r"\b(apply_draft_update|save_agreement|create_reference_seeded_project|update_project_record)\(", text), module
