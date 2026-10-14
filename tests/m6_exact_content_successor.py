"""M6 exact-content governance SUCCESSOR PROPOSAL, not independent approval."""
import ast
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RC2 = "6fc77de98bc0562fb51efdbf96e1803a29b5b148"
# --- LITERAL REVIEW-PROPOSAL PINS, NOT runtime-calculated baselines ---
M6_EXACT_BLOBS = {
    'app/api/project_runner.py': 'd4a83683b42c275c61a452dd09914ad064585e6e',
    'app/model_v2/acquisition/__init__.py': '1451248660d8936e418d1b8b5f6f7fdcac64f22a',
    'app/model_v2/acquisition/csrf_binding.py': '1ed3053bbfdaa87f3448e7d318f95917cc36a8b0',
    'app/model_v2/acquisition/economics.py': '10a2216cbb0f88b6150245e4001dc995886c285c',
    'app/model_v2/acquisition/evidence.py': '8eb5f04c9ca84cb489b2f34c1737680d2cb52576',
    'app/persistence/acquisition_repository.py': 'e565f7937063d81fdf552d599abfb03ad8f45630',
    'app/templates/v2/acquisition.html': '7641b56faed9244452b3a11c6dc70a7d5b8a8b75',
    'app/templates/v2/developer_decision.html': '7565104459a013e727932dfb3b9726be988e2144',
    'app/v2/acquisition_router.py': '5d9ae751848d6810e67eacb91b170b7ee2f74552',
    'app/v2/router.py': '89f77a32b73d3745e83f4b73bae588498f6f065a',
    'docs/model_v2/M6_INSTITUTIONAL_ACQUISITION_CANDIDATE.md': 'e070aad00d9501a0ff0bb53553e583308600151d',
    'main_web.py': '1957c6c2668e3bc759f016008e1f112cc7d22980',
    'tests/m6_economic_parity.py': '775c3c4e808eaeaad4ef1dc3d7c681db8ce23fef',
    'tests/test_cost_batch_save_v1.py': 'c18a8365bbed9053600c9d82885441c6669d71fe',
    'tests/test_investor_f4_workspace.py': '0aa2d0fc376a5867c88f9f82df14c0056f366469',
    'tests/test_m6_exact_content_successor.py': '8bc6d786d9a0713b733b25d2196960b1853dfba4',
    'tests/test_m6_institutional_acquisition_candidate.py': '605ec5f5a1e145df265489889c27d00b0663f435',
    'tests/test_rc2_integration_manifest.py': '8848c9d870a2968ac3aa548d16ad40db8fbd22f6',
    'tests/test_trust_readiness_controls.py': '2dc078f9abbda3fea7d3876375ef80b52cea6928',
    'tests/test_trust_readiness_registry.py': '920732a47f77cf6ff3c5e484cff114132bae7f61',
}  # populated only with --pin-manifest after checks
M6_CHANGED_PATHS = frozenset(('app/api/project_runner.py', 'app/model_v2/acquisition/__init__.py', 'app/model_v2/acquisition/csrf_binding.py', 'app/model_v2/acquisition/economics.py', 'app/model_v2/acquisition/evidence.py', 'app/persistence/acquisition_repository.py', 'app/templates/v2/acquisition.html', 'app/templates/v2/developer_decision.html', 'app/v2/acquisition_router.py', 'app/v2/router.py', 'docs/model_v2/M6_INSTITUTIONAL_ACQUISITION_CANDIDATE.md', 'main_web.py', 'tests/m6_economic_parity.py', 'tests/m6_exact_content_successor.py', 'tests/test_cost_batch_save_v1.py', 'tests/test_investor_f4_workspace.py', 'tests/test_m6_exact_content_successor.py', 'tests/test_m6_institutional_acquisition_candidate.py', 'tests/test_rc2_integration_manifest.py', 'tests/test_trust_readiness_controls.py', 'tests/test_trust_readiness_registry.py'))  # full explicit expected HEAD diff
M6_SELF_GUARD = "tests/m6_exact_content_successor.py"
M6_VALIDATOR_SITES = frozenset({
    "main_web.py", "app/v2/import_router.py", "app/v2/grid_router.py",
    "app/crypto_ui.py", "app/v2/router.py", "app/v2/investor_f4_router.py",
    "app/v2/developer_decision_router.py", "app/v2/acquisition_router.py",
})

def _git(*args):
    return subprocess.check_output(("git", *args), cwd=ROOT, text=True).strip()

def _sites():
    sites = set()
    for p in [*ROOT.joinpath("app").rglob("*.py"), ROOT / "main_web.py"]:
        rel = p.relative_to(ROOT).as_posix()
        if not rel.startswith("app/trust_readiness/") and re.search(
                r"(?<!def )validate_csrf_token\(", p.read_text()):
            sites.add(rel)
    return frozenset(sites)

def violations(*, ancestry, changed, blobs, sites, economics, router):
    bad = []
    if not ancestry:
        bad.append("RC-2 accepted checkpoint ancestry invalid")
    if set(changed) != set(M6_CHANGED_PATHS):
        bad.append("M6 changed path set differs from exact reviewed proposal")
    if not M6_EXACT_BLOBS or set(blobs) != set(M6_EXACT_BLOBS):
        bad.append("M6 exact blob inventory missing/extended")
    elif blobs != M6_EXACT_BLOBS:
        bad.append("M6 application or governance blob differs")
    if frozenset(sites) != M6_VALIDATOR_SITES:
        bad.append("M6 CSRF inventory differs")
    try:
        t = ast.parse(economics)
        assignments = [n for n in t.body if isinstance(n, ast.Assign)
                       and any(isinstance(x, ast.Name) and x.id == "ACTIVATION_ENABLED"
                               for x in n.targets)]
        if len(assignments) != 1 or not isinstance(assignments[0].value, ast.Constant) or assignments[0].value.value is not False:
            bad.append("M6 acquisition activation is not literal False")
    except (SyntaxError, TypeError, AttributeError):
        bad.append("M6 financial candidate source invalid")
    try:
        t = ast.parse(router)
        endpoints = {}
        for node in t.body:
            if isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef)):
                for dec in node.decorator_list:
                    if (isinstance(dec, ast.Call) and isinstance(dec.func, ast.Attribute)
                            and isinstance(dec.func.value, ast.Name) and dec.func.value.id == "router"
                            and dec.func.attr in {"get", "post", "put", "patch", "delete"}):
                        if not dec.args or not isinstance(dec.args[0], ast.Constant):
                            bad.append("M6 route path is nonliteral")
                        else:
                            endpoints[(dec.func.attr, dec.args[0].value)] = node
        expected = {("get", "/valuation-acquisition"),
                    ("post", "/valuation-acquisition/save"),
                    ("post", "/valuation-acquisition/review-candidate")}
        if set(endpoints) != expected:
            bad.append("M6 route handler inventory differs")
        for method, path in sorted(expected - {("get", "/valuation-acquisition")}):
            node = endpoints.get((method, path))
            if node is None:
                continue
            calls = {n.func.id for n in ast.walk(node)
                     if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
            if not {"validate_csrf_token", "extract_bound_token"} <= calls:
                bad.append("M6 POST handler lacks session-bound canonical CSRF")
        if "_review_gate(request)" not in router or "is_protected_reference(record)" not in router:
            bad.append("M6 review or protected-reference gate absent")
    except (SyntaxError, TypeError, AttributeError):
        bad.append("M6 acquisition router source invalid")
    return bad

def current_m6_successor_valid():
    try:
        _git("merge-base", "--is-ancestor", RC2, "HEAD")
        if not M6_EXACT_BLOBS or not M6_CHANGED_PATHS:
            return False
        # No unknown added/modified file, including tests, docs or financial code.
        actual = set(_git("diff", "--name-only", RC2, "HEAD").splitlines())
        blobs = {p: _git("hash-object", f"--path={p}", p)
                 for p in M6_EXACT_BLOBS}
        root = ROOT
        return not violations(
            ancestry=True, changed=actual, blobs=blobs, sites=_sites(),
            economics=(root / "app/model_v2/acquisition/economics.py").read_text(),
            router=(root / "app/v2/acquisition_router.py").read_text())
    except (OSError, subprocess.CalledProcessError, ValueError, TypeError):
        return False
