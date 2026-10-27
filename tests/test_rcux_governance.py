"""RC-UX Completion V1 — additive successor layer (``RC_UX_SUCCESSORS``) and the protected-path scope guard.

Strict negatives only; no activation or Financial-Owner assertion.  The layer lives in ``tests/model_mutation_security_successor.py``
next to the original, FIN-VAL, D-029, Overnight B and RC-M layers, none of which is edited.
"""
import re
import subprocess

import pytest

from tests import model_mutation_security_successor as S

SOURCES = {p: (S.ROOT / p).read_text(encoding="utf-8") for p in S.BLOBS}
LAYER = S.RC_UX_SUCCESSORS
BASE = "f79e251903621c1a5c88501d51d6971960b612d3"       # main containing #388, the RC-UX branch point
MAIN = "70bcf693bdb2547fc1c0e5af685835689eb44d3e"       # main containing the FIN-V2 Integration RC (#395): the accepted parent RC-UX is judged against
#: RC-UX may re-pin only React presentation surfaces: the adapter mount, the workspace view, the rebuilt bundle, the React views and the browser
#: acceptance bodies.  A security, CSRF, financial or governance test can never enter this layer.
ALLOWED = re.compile(r"^(app/v2/react_[a-z_]+\.py|frontend/src/.+\.(ts|tsx|css)|static/react/finco-react\.(js|css)|"
                     r"tests/model_react_[a-z0-9_]+_acceptance\.py|tests/test_model_workspace_consolidation_browser\.py)$")


def _git(*args):
    return subprocess.check_output(["git", *args], cwd=S.ROOT, stderr=subprocess.DEVNULL).decode("utf-8")


def test_layer_is_a_subset_of_the_reviewed_surfaces_and_every_current_source_is_exactly_pinned():
    assert all(ALLOWED.match(path) for path in LAYER), [p for p in LAYER if not ALLOWED.match(p)]
    assert "static/react/finco-react.js" in LAYER
    for path, blob in LAYER.items():
        assert path in S.BLOBS and len(blob) == 40 and re.fullmatch(r"[0-9a-f]{40}", blob)
        assert blob not in {S.BLOBS[path], S.RC_M_SUCCESSORS.get(path)}                # a NEW reviewed state, never a repin
        assert S.git_blob(SOURCES[path]) == blob                                       # strict equality with the current source
    assert S.violations(SOURCES) == [] and S.current_mutation_successor_valid()


@pytest.mark.parametrize("path", sorted(LAYER))
def test_one_byte_of_drift_in_a_layer_path_fails_closed(path):
    changed = dict(SOURCES)
    changed[path] += "\n"
    assert S.violations(changed)


@pytest.mark.parametrize("path", sorted(LAYER))
def test_the_rc_m_state_of_each_layer_path_remains_individually_admitted(path):
    changed = dict(SOURCES)
    blob = S.RC_M_SUCCESSORS.get(path, S.BLOBS[path])                                  # the state before RC-UX
    changed[path] = subprocess.check_output(["git", "cat-file", "blob", blob], cwd=S.ROOT).decode("utf-8")
    assert not [e for e in S.violations(changed) if e.startswith(path + ": unreviewed")]


def test_no_historical_layer_was_edited_by_rc_ux():
    for name in ("RC_M_SUCCESSORS", "FINVAL_RATE_SUCCESSORS", "FINVAL_F01_COMPLETE_SUCCESSORS", "REACT_MVP_CORRECTION_SUCCESSORS"):
        current = getattr(S, name)
        original_source = _git("show", f"{BASE}:tests/model_mutation_security_successor.py")
        for path, blob in current.items():
            assert blob in original_source and path in original_source, (name, path)       # the pin line exists verbatim at the base


#: The ONLY wording changes RC-UX made inside the pinned router: display strings shown to financial users (Addendum B product language).
#: No key, number, route, token or logic changed; the test rebuilds the current file from the #388 router and these pairs exactly.
ROUTER_WORDING = (
    ("This metric is not persisted by the committed Run.", "This metric is not available in the saved Run."),
    ("This Run persisted no such statement.", "This Run has no such statement."),
    ("This Run persisted no debt schedule.", "This Run has no debt schedule."),
    ("No facility schedule persisted.", "No facility schedule is available for this Run."),
    ("The persisted Run evidence could not be projected; nothing is estimated.", "The saved Run results could not be displayed; nothing is estimated."),
    ("Line requests require session/project/operation-bound CSRF, composite CAS and row versions.",
     "Line changes are protected: another change made in the meantime is never overwritten."),
    ('"note": "Exports the inputs and results of the last committed Run, "\n                                 "not the current Working Copy edits."}',
     '"note": "Exports the inputs and results of the last Run, "\n                                 "not edits made since."}'),
    ("Pinned canonical reference regression only; not validation of this Working Copy or its Run.",
     "Reference regression only; it is not a validation of this project or its Run."),
    ('"note": "The Working Copy side shows no Run of its own. Each committed Run is "\n                                          "shown against the scenario it was committed under; see Run history."}}',
     '"note": "The project itself has no Run of its own. Each Run is "\n                                          "shown against the scenario it was run under; see Run history."}}'),
    ('"note": "Run initiation stays on the canonical route; success redirects "\n                                 "(303) to the workbook, failures redirect with ?v2_err=. "\n                                 "Save NEVER triggers a Run."},',
     '"note": "Saving never runs the model; a Run starts only when you press Run model."},'),
    ('"base": {"label": f"Working Copy / {ws.active_scenario_name or \'Base Case\'}",', '"base": {"label": f"Project / {ws.active_scenario_name or \'Base Case\'}",'),
)


def test_the_workspace_router_changes_only_by_the_one_rcux_include_and_reviewed_wording():
    source = SOURCES["app/v2/react_workspace_router.py"]
    tail = source[source.index("# ───────────────────────────── RC-UX: React adapters"):]
    assert re.findall(r"^router\.include_router\((\w+)\)$", tail, flags=re.M) == ["_rcux_router"]
    assert re.findall(r"^from app\.v2\.(\w+) import router as (\w+)", tail, flags=re.M) == [("react_rcux", "_rcux_router")]
    rebuilt = _git("show", f"{BASE}:app/v2/react_workspace_router.py")
    for old, new in ROUTER_WORDING:
        assert rebuilt.count(old) == 1, old
        rebuilt = rebuilt.replace(old, new)
    assert source == rebuilt.rstrip("\n") + "\n\n\n" + tail.rstrip("\n") + "\n"


def test_the_rcux_aggregator_lists_exactly_the_adapter_modules_it_mounts():
    text = (S.ROOT / "app/v2/react_rcux.py").read_text(encoding="utf-8")
    mounted = re.findall(r"^from app\.v2\.(react_\w+) import router as _\w+", text, flags=re.M)
    from app.v2 import react_rcux
    assert tuple(mounted) == react_rcux.RCUX_ADAPTERS
    for module in mounted:
        assert (S.ROOT / "app/v2" / f"{module}.py").is_file()


def test_the_rcux_adapters_add_no_calculation_authority_and_never_import_the_engine():
    forbidden = ("financial_engine", "finco_core", "def solve_", "def irr", "def npv", "numpy", "scipy", "brentq", "newton(", "run_project(")
    from app.v2 import react_rcux
    for module in react_rcux.RCUX_ADAPTERS:
        text = (S.ROOT / "app/v2" / f"{module}.py").read_text(encoding="utf-8")
        assert not [needle for needle in forbidden if needle in text], module
    for path in (S.ROOT / "frontend/src/app/runs").glob("*.ts*"):
        text = path.read_text(encoding="utf-8")
        assert not re.search(r"(?<![-\w])(irr|npv|dscr|llcr)\s*=\s*[^=>{]|Math\.(pow|log|exp)\(", text, flags=re.I), path


def test_the_rcux_changes_touch_no_protected_financial_security_or_ci_path():
    try:
        changed = set(_git("diff", "--name-only", MAIN, "HEAD").split())
        changed |= set(_git("diff", "--name-only").split()) | set(_git("diff", "--name-only", "--cached").split())
    except subprocess.CalledProcessError:
        pytest.skip("baseline commit not available in this checkout")
    forbidden = ("app/input_adapter.py", "app/api/project_runner.py", "app/runtime/model_execution.py", "app/v2/router.py",
                 "app/v2/returns_projection.py", "app/services/run_intent_service.py", "app/persistence/run_intent_repository.py",
                 "app/persistence/run_history_repository.py", "app/persistence/projects_repository.py", "app/services/run_service.py",
                 "app/services/goal_seek.py", "app/services/sensitivity_matrix.py", "main_web.py",
                 "app/workbook/mutation_csrf.py", "app/workbook/financing_csrf.py")
    prefixes = ("financial_engine/", "finco_core/", "domain/", ".github/", "app/workbook/", "app/capex_profiles/", "app/export/")
    hits = [p for p in changed if p in forbidden or p.startswith(prefixes)]
    assert hits == [], hits
    golden = [p for p in changed if re.search(r"golden|baseline_snapshot|expected_outputs", p)]
    assert golden == [], golden


# ── RC-UX adapters: read-only, no state-changing route, no token issuance of their own ──────────────────────────────────────────
def test_the_rcux_adapters_are_read_only_and_issue_no_mutation_authority_of_their_own():
    from app.v2 import react_rcux
    for module in react_rcux.RCUX_ADAPTERS:
        text = (S.ROOT / "app/v2" / f"{module}.py").read_text(encoding="utf-8")
        assert not re.search(r"@router\.(post|put|patch|delete)\(", text), module
        assert "validate_csrf_token(" not in text and "mutation_token(" not in text and "validate_mutation_token(" not in text, module
        assert not re.search(r"\b(apply_draft_update|save_profiles|save_agreement|create_reference_seeded_project|update_project_record|apply_batch_draft_update)\(", text), module


# ── RC-UX browser acceptance rides the EXISTING mandatory consolidation role (same pattern as RC-M) ─────────────────────────────
ROLE = "tests/test_model_workspace_consolidation_browser.py"
ACCEPTANCE = ("tests/model_react_rcux_runs_acceptance.py", "tests/model_react_rcux_capex_acceptance.py", "tests/model_react_rcux_product_acceptance.py", "tests/model_react_rcux_whatif_acceptance.py")


def test_the_consolidation_role_imports_exactly_the_rcux_acceptance_modules_and_adds_no_wrapper_of_its_own():
    tail = SOURCES[ROLE][SOURCES[ROLE].index("# RC-UX Completion V1"):]
    modules = re.findall(r"^from (tests\.\w+) import \*", tail, flags=re.M)
    assert modules == [m.removesuffix(".py").replace("/", ".") for m in ACCEPTANCE]
    assert tail.count("def ") == 0 and "importorskip" not in tail and "mark.skip" not in tail


@pytest.mark.parametrize("path", ACCEPTANCE)
def test_each_rcux_acceptance_module_is_not_collected_alone_exports_exactly_its_tests_and_has_no_skip(path):
    import ast

    file = S.ROOT / path
    assert not file.name.startswith("test_")
    source = file.read_text(encoding="utf-8")
    tree = ast.parse(source)
    exported = next(ast.literal_eval(n.value) for n in tree.body if isinstance(n, ast.Assign) and n.targets[0].id == "__all__")
    tests = [n.name for n in tree.body if isinstance(n, ast.FunctionDef) and n.name.startswith("test_")]
    fixtures = [n.name for n in tree.body if isinstance(n, ast.FunctionDef) and any("fixture" in ast.unparse(d) for d in n.decorator_list)]
    assert sorted(exported) == sorted(tests + fixtures) and len(set(exported)) == len(exported)
    for forbidden in ("importorskip", "pytest.skip", "mark.skip", "skipif", "xfail", "autouse", "from playwright", "import playwright"):
        assert forbidden not in source, forbidden
