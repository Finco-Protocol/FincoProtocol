"""RC-M — the atomic request-keyed project creation is PREPARED, TESTED and held back until FIN-VAL F01 (#389) merges.

The creation authority files (``projects_repository``, ``project_library_service``) overlap #389.  The reviewed change set is therefore stored as
``atomic_create/ATOMIC_CREATE_AFTER_F01.patch`` and applied only after #389 is on ``main``.  Until then the React New Project create is fenced by the
adapter-level ledger and stays release-gated.  This tripwire proves the patch is still applicable to the current sources (so the preparation
cannot rot) — or, once applied, that it is fully integrated — and that the release gate is still closed.
"""
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PATCH = ROOT / "docs/react_migration/rc_m_integrated/atomic_create/ATOMIC_CREATE_AFTER_F01.patch"
INCLUDE = ["--include=app/*"]


def _integrated() -> bool:
    return "ux_projects_user_create_request" in (ROOT / "app/persistence/db.py").read_text(encoding="utf-8")


def _apply(*flags):
    return subprocess.run(["git", "apply", "--check", *flags, *INCLUDE, str(PATCH)], cwd=ROOT, capture_output=True, text=True)


def test_the_prepared_patch_exists_and_covers_exactly_the_reviewed_creation_authority_files():
    text = PATCH.read_text(encoding="utf-8")
    touched = sorted(line.split(" b/", 1)[1] for line in text.splitlines() if line.startswith("diff --git "))
    app_files = [p for p in touched if p.startswith("app/")]
    assert app_files == ["app/persistence/db.py", "app/persistence/projects_repository.py", "app/services/project_library_service.py",
                         "app/services/reference_seed_service.py", "app/v2/react_new_project.py", "app/v2/react_request_claims.py"]
    assert not any(p.startswith(("financial_engine/", "finco_core/", ".github/", "app/workbook/", "app/runtime/")) for p in touched)


def test_the_patch_is_either_still_applicable_or_already_integrated():
    result = _apply("-R") if _integrated() else _apply()
    assert result.returncode == 0, result.stderr[-800:]


def test_until_integration_the_adapter_states_it_is_not_production_ready_and_the_react_flag_defaults_off(monkeypatch):
    if not _integrated():
        assert "NOT labelled\nproduction-ready" in (ROOT / "app/v2/react_new_project.py").read_text(encoding="utf-8").replace("is therefore ", "")
    monkeypatch.delenv("FINCO_MODEL_REACT_V1", raising=False)
    from app.v2.react_poc_router import react_poc_enabled

    assert react_poc_enabled() is False
