"""RC-M — additive successor layer for the six pinned paths the React adapters changed, and the protected-path scope guard.

Strict negatives only; no activation or Financial-Owner assertion.  The layer lives in ``tests/model_mutation_security_successor.py``
(``RC_M_SUCCESSORS``) next to the original, FIN-VAL, D-029 and Overnight B layers.
"""
import re
import subprocess

import pytest

from tests import model_mutation_security_successor as S

SOURCES = {p: (S.ROOT / p).read_text(encoding="utf-8") for p in S.BLOBS}
LAYER = S.RC_M_SUCCESSORS
EXPECTED = {"app/v2/react_workspace_router.py", "frontend/src/app/WorkspaceView.tsx", "static/react/finco-react.css", "static/react/finco-react.js",
            "tests/test_model_workspace_consolidation_browser.py", "app/v2/react_poc_router.py"}


def _git(*args):
    return subprocess.check_output(["git", *args], cwd=S.ROOT, stderr=subprocess.DEVNULL).decode("utf-8")


def _blob_source(blob):
    return subprocess.check_output(["git", "cat-file", "blob", blob], cwd=S.ROOT).decode("utf-8")


def _earlier(path):
    return {S.BLOBS[path], S.FINVAL_B2C1_SUCCESSORS.get(path), S.D029_RUN_INTENT_SUCCESSORS.get(path),
            S.REACT_MVP_CORRECTION_SUCCESSORS.get(path)} - {None}


def test_layer_is_exactly_six_additive_paths_and_the_current_sources_are_admitted():
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
    forbidden = ("app/input_adapter.py",
                 "app/runtime/model_execution.py", "app/v2/router.py", "app/v2/returns_projection.py",
                 "app/services/run_intent_service.py", "app/persistence/run_intent_repository.py", "app/persistence/run_history_repository.py",
                 "app/services/run_service.py", "app/services/goal_seek.py",
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


# ── RC-M browser acceptance rides the EXISTING mandatory consolidation role ─────────────────────────────────────────────────
ACCEPTANCE = {lane: f"tests/model_react_rcm_{lane}_acceptance.py" for lane in ("new_project", "analysis", "financing", "investors", "themes")}
ROLE = "tests/test_model_workspace_consolidation_browser.py"


def test_the_consolidation_role_imports_exactly_the_five_acceptance_modules_and_adds_no_wrapper_of_its_own():
    tail = SOURCES[ROLE][SOURCES[ROLE].index("# RC-M integrated React acceptance"):]
    assert re.findall(r"^from (tests\.\w+) import (\*|rcm_react_flag)", tail, flags=re.M) == [
        ("tests.model_react_rcm_support", "rcm_react_flag")] + [(f"tests.model_react_rcm_{lane}_acceptance", "*") for lane in ACCEPTANCE]
    assert tail.count("def ") == 0 and "importorskip" not in tail and "mark.skip" not in tail     # imports only: no function, no skip


@pytest.mark.parametrize("lane", sorted(ACCEPTANCE))
def test_each_acceptance_module_is_not_collected_alone_exports_exactly_its_tests_and_has_no_skip(lane):
    import ast

    path = S.ROOT / ACCEPTANCE[lane]
    assert not path.name.startswith("test_")                                 # pytest never collects it on its own
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    exported = next(ast.literal_eval(n.value) for n in tree.body if isinstance(n, ast.Assign) and n.targets[0].id == "__all__")
    tests = [n.name for n in tree.body if isinstance(n, ast.FunctionDef) and n.name.startswith("test_")]
    fixtures = [n.name for n in tree.body if isinstance(n, ast.FunctionDef) and any("fixture" in ast.unparse(d) for d in n.decorator_list)]
    assert sorted(exported) == sorted(tests + fixtures) and len(set(exported)) == len(exported)
    for forbidden in ("importorskip", "pytest.skip", "mark.skip", "skipif", "xfail", "playwright import", "autouse"):
        assert forbidden not in source, forbidden
    # nothing but the role may need a browser at import time
    assert "from playwright" not in source and "import playwright" not in source


def test_every_acceptance_test_name_is_unique_across_the_role_and_the_five_modules():
    import ast

    names: list[str] = []
    for path in [ROLE, *ACCEPTANCE.values()]:
        tree = ast.parse((S.ROOT / path).read_text(encoding="utf-8"))
        names += [n.name for n in tree.body if isinstance(n, ast.FunctionDef) and n.name.startswith("test_")]
    assert len(names) == len(set(names))


def test_the_flag_fixture_is_not_autouse_so_it_cannot_leak_into_the_other_role_tests():
    source = (S.ROOT / "tests/model_react_rcm_support.py").read_text(encoding="utf-8")
    assert "autouse" not in source and "@pytest.fixture\ndef rcm_react_flag" in source


def test_the_asset_router_differs_from_main_only_by_the_content_derived_cache_buster():
    """Correction B: ``react_poc_router.py`` may change ONLY to derive ``REACT_ASSET_VERSION`` from the bundle bytes."""
    try:
        base = _git("merge-base", "HEAD", "origin/main").strip()
        original = _git("show", f"{base}:app/v2/react_poc_router.py")
    except subprocess.CalledProcessError:
        pytest.skip("baseline commit not available in this checkout")
    current = SOURCES["app/v2/react_poc_router.py"]
    restored = current.replace("import hashlib\n", "", 1)
    start, end = restored.index("BASE_DIR = "), restored.index("_templates = ")
    base_dir_line = restored[start:restored.index("\n", start) + 1]
    restored = restored[:start] + 'REACT_ASSET_VERSION = "rc-sec-mutation-v1"\n\n' + base_dir_line + restored[end:]
    assert restored == original
    assert 'REACT_ASSET_VERSION = bundle_version()' in current and "hashlib.sha256" in current


def test_the_react_analysis_engine_submission_is_the_legacy_matrix_submission_and_the_only_one():
    """Correction C: native activation / bounded-worker parity of the Analysis previews (proof beside the exact activation inventory)."""
    import ast

    def shape(path):
        tree = ast.parse((S.ROOT / path).read_text(encoding="utf-8"))
        sites = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and getattr(node.func, "id", getattr(node.func, "attr", None)) == "native_result":
                inner = node.args[0]
                assert isinstance(inner, ast.Await)
                call = inner.value
                activated = call.args[0]
                sites.append((ast.unparse(call.func), ast.unparse(activated.func), ast.unparse(activated.args[0]), ast.unparse(call.args[1])))
        return sites

    legacy, react = shape("app/v2/sensitivity_matrix_router.py"), shape("app/v2/react_analysis.py")
    assert legacy == react == [("run_model_process", "activated", "svc.run_matrix_points", "svc.RUNTIME_KEYS[vertical]")]
    source = (S.ROOT / "app/v2/react_analysis.py").read_text(encoding="utf-8")
    assert source.count("run_model_process(") == 1                                  # the bounded executor is the only way an engine batch starts
    assert "ProcessPoolExecutor" not in source and "ThreadPoolExecutor" not in source and "multiprocessing" not in source
    for stateful in ("record_workspace_runtime", "save_run", "apply_draft_update", "save_workspace_state"):
        assert stateful not in source                                                # previews never write a Run, History or the Working Copy


def test_the_react_flag_defaults_off_and_creation_is_atomic_through_the_canonical_authority(monkeypatch):
    """Release gate stays closed; the keyed creator is the only way the adapter creates (no interim ledger remains)."""
    monkeypatch.delenv("FINCO_MODEL_REACT_V1", raising=False)
    from app.v2.react_poc_router import react_poc_enabled

    assert react_poc_enabled() is False
    assert not (S.ROOT / "app/v2/react_request_claims.py").exists()
    source = (S.ROOT / "app/v2/react_new_project.py").read_text(encoding="utf-8")
    assert "create_reference_seeded_project_once(" in source and "react_request_claims" not in source
    assert "ux_projects_user_create_request" in (S.ROOT / "app/persistence/db.py").read_text(encoding="utf-8")
