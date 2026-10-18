"""RC-7: every surface that re-materialises Run inputs either binds the saved monthly CAPEX profile or fails closed - none may silently
run default (semester) timing next to a Working Copy that carries a profile."""
from __future__ import annotations

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
    return sorted(str(p.relative_to(ROOT)) for p in (ROOT / "app").rglob("*.py") if CALL.search(p.read_text(encoding="utf-8")))


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
    sens = (ROOT / "app/services/sensitivity_service.py").read_text(encoding="utf-8")
    assert "guard_snapshot_builder(_build," in sens


def test_default_projects_are_untouched_by_every_binder_entry_point():
    from app.capex_profiles.runtime import apply_profiles, apply_snapshot_profiles
    sentinel = object()
    assert apply_snapshot_profiles(sentinel, {}, project_id="p") is sentinel
    assert apply_snapshot_profiles(sentinel, {config.SNAPSHOT_KEY: ""}, project_id="p") is sentinel
    assert apply_profiles(sentinel, None, project_id="p") is sentinel
    assert apply_profiles(sentinel, "", project_id="p") is sentinel
