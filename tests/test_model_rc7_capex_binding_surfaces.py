"""RC-7: every surface that re-materialises Run inputs either binds the saved monthly CAPEX profile or fails closed - none may silently
run default (semester) timing next to a Working Copy that carries a profile."""
from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

from app.capex_profiles import config
from app.capex_profiles.runtime import guard_snapshot_builder, refuse_unbound_surface
from app.input_adapter import SnapshotInputError

ROOT = Path(__file__).resolve().parents[1]
CALL = re.compile(r"\bapply_user_sub_lines_replacing_base\s*\(|\b_apply_capex\s*\(|\b_apply_capex_opex_folds\s*\(")

# files that fold CAPEX and re-run / re-materialise the engine inputs -> they must bind the profile or refuse it
BINDS = {
    "app/v2/router.py": "apply_snapshot_profiles",                     # Run, one-driver sensitivity, Goal Seek
    "app/services/sensitivity_matrix.py": "apply_snapshot_profiles",     # two-driver matrix (materialise_financing)
    "app/services/export_service.py": "refuse_unbound_surface",         # Last Run export refuses; working-preview export binds
    # RC-M React Goal Seek: the same fold -> apply_snapshot_profiles -> engine order as the Legacy route, proven effective and equal to it in
    # tests/test_model_react_rcm_capex_profile_v1.py (profile changes the solve; React == Legacy on a profiled Working Copy)
    "app/v2/react_goal_seek.py": "apply_snapshot_profiles",
}
# files that fold CAPEX but never run the engine (definitions or display) - reviewed, not bound
NO_ENGINE_RUN = {
    "app/persistence/capex_sub_lines.py": "definition of the fold",
    "app/services/capex_sub_lines_integration.py": "definition of the fold",
    "app/ui/capex_view_model.py": "CAPEX grid display",
    "app/workbook/bankability_config.py": "fee-editability hint (reads, never runs)",
    "app/capex_profiles/runtime.py": "the binder itself",
    "app/capex_profiles/projection.py": "planner catalogue (reads, never runs)",
    "app/capex_profiles/service.py": "Save validation (materialises, never runs the engine)",
    "app/services/run_service.py": "legacy /run routes: refused through the guarded snapshot builder (main_web)",
}


def _folding_files():
    return sorted(p.relative_to(ROOT).as_posix() for p in (ROOT / "app").rglob("*.py") if CALL.search(p.read_text(encoding="utf-8")))


def test_every_capex_folding_surface_is_classified():
    unknown = [f for f in _folding_files() if f not in BINDS and f not in NO_ENGINE_RUN]
    assert unknown == [], f"new CAPEX-folding surface(s) must bind the profile, refuse it, or be reviewed as non-engine: {unknown}"
    for path, marker in BINDS.items():
        assert marker in (ROOT / path).read_text(encoding="utf-8"), (path, marker)


def test_the_primary_run_binds_after_the_folds_and_before_the_engine():
    src = (ROOT / "app/v2/router.py").read_text(encoding="utf-8")
    run = src[src.index("async def v2_workbook_run("):]
    assert run.index("apply_user_sub_lines_replacing_base(") < run.index("apply_profiles(") < run.index("await run_model_process(")


def test_unbound_legacy_surface_is_refused_not_run_on_default_timing():
    seen = []
    builder = guard_snapshot_builder(lambda snap, *a, **k: seen.append(snap) or "inputs", "the legacy test route")
    assert builder({"capacity_mw": "16"}) == "inputs" and seen == [{"capacity_mw": "16"}]          # no profile: untouched pass-through
    with pytest.raises(SnapshotInputError) as exc:
        builder({"capacity_mw": "16", config.SNAPSHOT_KEY: '{"version":1,"profiles":[]}'})
    assert "CAPEX_PROFILE_UNBOUND_SURFACE" in str(exc.value) and len(seen) == 1                  # the wrapped builder never ran
    refuse_unbound_surface({}, "x")
    refuse_unbound_surface({config.SNAPSHOT_KEY: ""}, "x")
    with pytest.raises(SnapshotInputError):
        refuse_unbound_surface({config.SNAPSHOT_KEY: "{}"}, "the Last Run export")


def test_the_legacy_entry_points_use_the_guarded_builder():
    main_web = (ROOT / "main_web.py").read_text(encoding="utf-8")
    assert "_guard_capex_profile_surface(" in main_web
    assert "from app.input_adapter import build_projectinputs_from_snapshot" not in main_web          # no unguarded local re-import
    # B1 deliberately replaced the old snapshot-builder seam. Verify its
    # actual call graph; real signed HTML/CSV/XLSX, monthly cash vectors and
    # canonical HTTP-Run equivalence are executed in the B1 profile tests.
    def function(path, name):
        tree = ast.parse((ROOT / path).read_text(encoding="utf-8"))
        return next(n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == name)
    def calls(node, name):
        return sorted(n.lineno for n in ast.walk(node) if isinstance(n, ast.Call)
                      and isinstance(n.func, ast.Name) and n.func.id == name)
    service = "app/services/sensitivity_service.py"
    resolve = function(service, "resolve_sensitivity_source")
    assert calls(resolve, "pre_financing_inputs")[0] < calls(resolve, "materialise_financing")[0]
    assert not calls(resolve, "build_projectinputs_from_snapshot")
    delegate = function(service, "_resolve_sensitivity_project")
    assert calls(delegate, "resolve_sensitivity_source")
    bind = function("app/services/sensitivity_matrix.py", "materialise_financing")
    assert calls(bind, "apply_state")[0] < calls(bind, "apply_snapshot_profiles")[0]
    returned = next(n.value for n in ast.walk(bind) if isinstance(n, ast.Return))
    assert isinstance(returned, ast.Call) and returned.func.id == "apply_snapshot_profiles"
    kw = {k.arg: k.value for k in returned.keywords}
    assert ast.unparse(kw["project_id"]) == "basis.project_id"
    assert ast.unparse(kw["scenario_overrides"]) == "basis.scenario_overrides"
    request = function("main_web.py", "_sensitivity_request")
    assert calls(request, "resolve_sensitivity_source")
    for endpoint in ("scenario_sensitivity_endpoint", "scenario_sensitivity_export_endpoint"):
        route = function("main_web.py", endpoint)
        assert calls(route, "_sensitivity_request")[0] < calls(route, "_run_model_thread")[0]
        assert any(isinstance(n, ast.Attribute) and n.attr == "profile_basis" for n in ast.walk(route))
    grid = function(service, "run_sensitivity")
    point = next(n for n in ast.walk(grid) if isinstance(n, ast.For) and isinstance(n.target, ast.Name) and n.target.id == "level")
    assert calls(point, "_apply_shock")[0] < calls(point, "materialise_financing")[0] < calls(point, "_run_once")[0]


def test_default_projects_are_untouched_by_every_binder_entry_point():
    from app.capex_profiles.runtime import apply_profiles, apply_snapshot_profiles
    sentinel = object()
    assert apply_snapshot_profiles(sentinel, {}, project_id="p") is sentinel
    assert apply_snapshot_profiles(sentinel, {config.SNAPSHOT_KEY: ""}, project_id="p") is sentinel
    assert apply_profiles(sentinel, None, project_id="p") is sentinel
    assert apply_profiles(sentinel, "", project_id="p") is sentinel
