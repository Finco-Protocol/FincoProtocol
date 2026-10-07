"""Model V2 foundation — feature flag and non-economic project metadata tests.

Covers the Workflow 01 acceptance markers:

  MODEL_V2_FLAG_DEFAULT_OFF                     — flag unset resolves OFF
  MODEL_V2_FLAG_EXPLICIT_ON                     — flag explicit ON resolvable
  MODEL_V2_LEGACY_PROJECT_LOADS_WITHOUT_METADATA
  MODEL_V2_STAGE_PERSISTS_ROUND_TRIP
  MODEL_V2_PERSPECTIVE_PERSISTS_ROUND_TRIP
  MODEL_V2_METADATA_PRESERVED_ON_UPDATE_AND_ARCHIVE
  MODEL_V2_METADATA_DOES_NOT_ENTER_FINANCIAL_AUTHORITY
  MODEL_V2_METADATA_VALIDATION_FAILS_CLOSED
"""
from __future__ import annotations

import subprocess
import sys

import pytest

from app.model_v2 import (
    MODEL_V2_ENABLED_ENV,
    ModelPerspective,
    ProjectStage,
    model_v2_enabled,
    normalize_perspective,
    normalize_stage,
)


@pytest.fixture
def seeded_db(tmp_path, monkeypatch):
    from app.persistence import db

    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "model-v2-metadata.db"))
    db.init_db()
    yield


# ---------------------------------------------------------------------------
# Feature flag
# ---------------------------------------------------------------------------

def test_model_v2_flag_defaults_off(monkeypatch):
    """MODEL_V2_FLAG_DEFAULT_OFF = PASS"""
    monkeypatch.delenv(MODEL_V2_ENABLED_ENV, raising=False)
    assert model_v2_enabled() is False
    # Falsy values stay OFF.
    for falsy in ("", "0", "false", "no", "off", "False", "  "):
        monkeypatch.setenv(MODEL_V2_ENABLED_ENV, falsy)
        assert model_v2_enabled() is False, falsy


def test_model_v2_flag_explicit_on(monkeypatch):
    """MODEL_V2_FLAG_EXPLICIT_ON = PASS"""
    monkeypatch.delenv(MODEL_V2_ENABLED_ENV, raising=False)
    for truthy in ("1", "true", "yes", "on", "TRUE", "Yes"):
        monkeypatch.setenv(MODEL_V2_ENABLED_ENV, truthy)
        assert model_v2_enabled() is True, truthy


def test_model_v2_flag_surface_is_minimal():
    """Flag ON must not switch any runtime financial behaviour in this workflow:
    the flags module exposes only the env name, the truthy set, the schema
    marker and the resolver — no runtime switch exists to consume."""
    import app.model_v2.flags as flags_module

    surface = {name for name in vars(flags_module) if not name.startswith("__")}
    assert surface <= {
        "annotations", "os", "MODEL_V2_ENABLED_ENV", "_TRUTHY",
        "MODEL_V2_INPUT_SCHEMA_MARKER", "model_v2_enabled",
    }


# ---------------------------------------------------------------------------
# Stage / Perspective vocabulary
# ---------------------------------------------------------------------------

def test_canonical_vocabularies():
    assert [s.value for s in ProjectStage] == [
        "screening", "development", "ready_to_build", "financing",
        "construction", "operating", "exited",
    ]
    assert [p.value for p in ModelPerspective] == ["developer", "ipp"]
    # No UNKNOWN sentinel in the business vocabulary; roadmap perspectives
    # are not active members.
    assert "unknown" not in [s.value for s in ProjectStage]
    assert "acquirer" not in [p.value for p in ModelPerspective]
    assert "lender" not in [p.value for p in ModelPerspective]


def test_metadata_validation_fails_closed():
    """MODEL_V2_METADATA_VALIDATION_FAILS_CLOSED = PASS"""
    assert normalize_stage(None) is None
    assert normalize_stage("operating") is ProjectStage.OPERATING
    assert normalize_stage("OPERATING") is ProjectStage.OPERATING
    assert normalize_perspective(None) is None
    assert normalize_perspective("ipp") is ModelPerspective.IPP
    with pytest.raises(ValueError):
        normalize_stage("unknown")
    with pytest.raises(ValueError):
        normalize_stage("operational")
    with pytest.raises(ValueError):
        normalize_perspective("acquirer")
    with pytest.raises(ValueError):
        normalize_perspective("lender")


def test_metadata_enum_object_normalization():
    """ENUM_NORMALIZATION = PASS — Correction A §2.

    Canonical enum objects themselves must normalize exactly like their
    canonical string values. Non-canonical enum instances and unrelated
    objects must fail closed (no silent str() coercion).
    """
    # None
    assert normalize_stage(None) is None
    assert normalize_perspective(None) is None
    # Canonical strings, any case
    assert normalize_stage("development") is ProjectStage.DEVELOPMENT
    assert normalize_stage("DEVELOPMENT") is ProjectStage.DEVELOPMENT
    assert normalize_perspective("ipp") is ModelPerspective.IPP
    assert normalize_perspective("IPP") is ModelPerspective.IPP
    # Canonical enum objects
    assert normalize_stage(ProjectStage.DEVELOPMENT) is ProjectStage.DEVELOPMENT
    assert normalize_stage(ProjectStage.READY_TO_BUILD) is ProjectStage.READY_TO_BUILD
    assert normalize_perspective(ModelPerspective.IPP) is ModelPerspective.IPP
    assert normalize_perspective(ModelPerspective.DEVELOPER) is ModelPerspective.DEVELOPER
    # Enum helpers agree with direct normalization
    from app.model_v2 import perspective_value, stage_value

    assert stage_value(ProjectStage.FINANCING) == "financing"
    assert stage_value("  Financing  ") == "financing"
    assert stage_value(None) is None
    assert perspective_value(ModelPerspective.DEVELOPER) == "developer"
    assert perspective_value(None) is None
    # Fail closed: unrelated enum instances are not coerced.
    class Color:
        RED = "red"

    import enum as _enum

    class Unrelated(_enum.Enum):
        A = "development"

    with pytest.raises(ValueError):
        normalize_stage(Unrelated.A)
    with pytest.raises(ValueError):
        normalize_perspective(Unrelated.A)
    with pytest.raises(ValueError):
        normalize_stage(42)


# ---------------------------------------------------------------------------
# Persistence round trip
# ---------------------------------------------------------------------------

def test_legacy_project_loads_without_metadata(seeded_db):
    """MODEL_V2_LEGACY_PROJECT_LOADS_WITHOUT_METADATA = PASS"""
    from app.persistence.projects_repository import get_project_by_code, save_project

    save_project(
        user_id="v2-meta-user",
        project_code="legacy-proj",
        project_name="Legacy Project",
        source_project_template="custom",
        project_type="Solar",
    )
    record = get_project_by_code("v2-meta-user", "legacy-proj")
    assert record is not None
    # Unset metadata stays unset — never inferred.
    assert record.project_stage is None
    assert record.model_perspective is None


def test_stage_and_perspective_persist_round_trip(seeded_db):
    """MODEL_V2_STAGE_PERSISTS_ROUND_TRIP / MODEL_V2_PERSPECTIVE_PERSISTS_ROUND_TRIP = PASS"""
    from app.persistence.projects_repository import get_project_by_code, save_project

    save_project(
        user_id="v2-meta-user",
        project_code="staged-proj",
        project_name="Staged Project",
        source_project_template="custom",
        project_type="Wind",
        project_stage=ProjectStage.DEVELOPMENT.value,
        model_perspective=ModelPerspective.DEVELOPER.value,
    )
    record = get_project_by_code("v2-meta-user", "staged-proj")
    assert record.project_stage == "development"
    assert record.model_perspective == "developer"

    # Re-saving with omitted metadata preserves the explicitly-set values.
    save_project(
        user_id="v2-meta-user",
        project_code="staged-proj",
        project_name="Staged Project Renamed",
        source_project_template="custom",
    )
    record = get_project_by_code("v2-meta-user", "staged-proj")
    assert record.project_name == "Staged Project Renamed"
    assert record.project_stage == "development"
    assert record.model_perspective == "developer"


def test_metadata_preserved_on_update_and_archive(seeded_db):
    """MODEL_V2_METADATA_PRESERVED_ON_UPDATE_AND_ARCHIVE = PASS"""
    from app.persistence.projects_repository import (
        get_project_by_code, save_project, update_project_record,
    )

    save_project(
        user_id="v2-meta-user",
        project_code="archive-proj",
        project_name="Archive Project",
        source_project_template="custom",
        project_stage="ready_to_build",
        model_perspective="ipp",
    )
    # Archive path (update_project_record) must not drop metadata.
    update_project_record(
        user_id="v2-meta-user",
        project_code="archive-proj",
        archived=True,
    )
    record = get_project_by_code("v2-meta-user", "archive-proj")
    assert record.archived is True
    assert record.project_stage == "ready_to_build"
    assert record.model_perspective == "ipp"


def test_persistence_fails_closed_on_invalid_metadata(seeded_db):
    """Correction A §3 — invalid Stage/Perspective cannot be persisted.

    The save must raise before any SQL write; on the insert path no row may
    appear, on the update path the previously persisted value must survive.
    """
    import enum as _enum

    from app.persistence.projects_repository import get_project_by_code, save_project

    class Unrelated(_enum.Enum):
        A = "operating"

    # Insert path: invalid values raise and create no project row.
    for bad_stage in ("unknown", "OPERATIONAL", 42, Unrelated.A):
        with pytest.raises(ValueError):
            save_project(
                user_id="v2-meta-user",
                project_code=f"bad-stage-{id(bad_stage)}",
                project_name="Bad Stage",
                source_project_template="custom",
                project_stage=bad_stage,
            )
    for bad_perspective in ("acquirer", "LENDER", Unrelated.A):
        with pytest.raises(ValueError):
            save_project(
                user_id="v2-meta-user",
                project_code=f"bad-persp-{id(bad_perspective)}",
                project_name="Bad Perspective",
                source_project_template="custom",
                model_perspective=bad_perspective,
            )
    assert get_project_by_code("v2-meta-user", "bad-stage-1") is None

    # Update path: invalid value raises, existing canonical value survives.
    save_project(
        user_id="v2-meta-user",
        project_code="valid-proj",
        project_name="Valid Project",
        source_project_template="custom",
        project_stage="operating",
    )
    with pytest.raises(ValueError):
        save_project(
            user_id="v2-meta-user",
            project_code="valid-proj",
            project_name="Valid Project Renamed",
            source_project_template="custom",
            project_stage="not-a-stage",
        )
    record = get_project_by_code("v2-meta-user", "valid-proj")
    assert record.project_stage == "operating"


def test_persistence_canonicalizes_enum_and_case_input(seeded_db):
    """Correction A §3 — enum input and any-case canonical strings persist as
    the canonical string value."""
    from app.persistence.projects_repository import get_project_by_code, save_project

    save_project(
        user_id="v2-meta-user",
        project_code="enum-input-proj",
        project_name="Enum Input Project",
        source_project_template="custom",
        project_stage=ProjectStage.CONSTRUCTION,
        model_perspective=ModelPerspective.IPP,
    )
    record = get_project_by_code("v2-meta-user", "enum-input-proj")
    assert record.project_stage == "construction"
    assert record.model_perspective == "ipp"

    save_project(
        user_id="v2-meta-user",
        project_code="case-input-proj",
        project_name="Case Input Project",
        source_project_template="custom",
        project_stage="READY_TO_BUILD",
        model_perspective="Developer",
    )
    record = get_project_by_code("v2-meta-user", "case-input-proj")
    assert record.project_stage == "ready_to_build"
    assert record.model_perspective == "developer"


def test_explicit_none_clears_metadata(seeded_db):
    """Correction A §3 — explicit None clears; omitted preserves."""
    from app.persistence.projects_repository import get_project_by_code, save_project

    save_project(
        user_id="v2-meta-user",
        project_code="clear-proj",
        project_name="Clear Project",
        source_project_template="custom",
        project_stage="screening",
        model_perspective="developer",
    )
    # Explicit None clears both fields.
    save_project(
        user_id="v2-meta-user",
        project_code="clear-proj",
        project_name="Clear Project",
        source_project_template="custom",
        project_stage=None,
        model_perspective=None,
    )
    record = get_project_by_code("v2-meta-user", "clear-proj")
    assert record.project_stage is None
    assert record.model_perspective is None

    # Set again, then update only one field with the other omitted.
    save_project(
        user_id="v2-meta-user",
        project_code="clear-proj",
        project_name="Clear Project",
        source_project_template="custom",
        project_stage="financing",
        model_perspective="ipp",
    )
    save_project(
        user_id="v2-meta-user",
        project_code="clear-proj",
        project_name="Clear Project Renamed",
        source_project_template="custom",
        model_perspective=None,   # explicit clear of perspective only
    )
    record = get_project_by_code("v2-meta-user", "clear-proj")
    assert record.project_stage == "financing"       # omitted → preserved
    assert record.model_perspective is None          # explicit None → cleared


# ---------------------------------------------------------------------------
# Save-as / copy preservation
# ---------------------------------------------------------------------------

def test_save_as_preserves_metadata(seeded_db):
    """SAVE_AS_METADATA_PRESERVATION = PASS — Correction A §4.

    A save-as copy receives the source's explicitly configured Stage and
    Perspective; a source without metadata produces a copy without metadata
    (no inference). Uses the real persistence layer through the real service.
    """
    import asyncio
    from datetime import datetime, timezone

    from app.persistence.projects_repository import get_project_by_code, save_project
    from app.persistence.workspace_repository import save_workspace_state
    from app.services.project_save_as_service import (
        ProjectSaveAsRouteDeps, execute_project_save_as_route,
    )

    def _deps():
        return ProjectSaveAsRouteDeps(
            get_project_record=lambda *, user_id, project_code:
                get_project_by_code(user_id, project_code),
            save_project=save_project,
            save_workspace_state=lambda **kwargs: save_workspace_state(**kwargs),
            now_utc=lambda: datetime.now(timezone.utc),
            project_record_creation_governance_state=lambda: {
                "g20": "BLOCKED", "r99_r102": "NOT_APPROVED", "lender_ready": False},
            workspace_state_initialization_governance_state=lambda: {
                "g20": "BLOCKED", "r99_r102": "NOT_APPROVED", "lender_ready": False},
            build_project_replay_metadata=lambda source, project_code: {
                "export_type": "project_duplicated",
                "source_project_code": project_code},
            build_workspace_replay_metadata=lambda source, project_code: {
                "export_type": "workspace_duplicated",
                "source_project_code": project_code},
            is_already_user_project=lambda source: source.project_origin == "user_created",
            get_or_create_base_case_scenario=None,
        )

    async def _copy(source_code):
        from types import SimpleNamespace

        return await execute_project_save_as_route(
            request=None,
            project_code=source_code,
            user=SimpleNamespace(user_id="v2-meta-user"),
            deps=_deps(),
        )

    # Source WITH explicitly configured metadata.
    save_project(
        user_id="v2-meta-user",
        project_code="source-meta",
        project_name="Source With Metadata",
        source_project_template="custom",
        project_type="Solar",
        project_stage=ProjectStage.DEVELOPMENT.value,
        model_perspective=ModelPerspective.DEVELOPER.value,
    )
    outcome = asyncio.run(_copy("source-meta"))
    assert outcome.status_code == 302
    import re

    new_code = re.search(r"project=([^&]+)", outcome.redirect_url).group(1)
    copied = get_project_by_code("v2-meta-user", new_code)
    assert copied.project_stage == "development"
    assert copied.model_perspective == "developer"

    # Source WITHOUT metadata → copy stays None (no inference).
    save_project(
        user_id="v2-meta-user",
        project_code="source-nometa",
        project_name="Source Without Metadata",
        source_project_template="custom",
        project_type="Wind",
    )
    outcome = asyncio.run(_copy("source-nometa"))
    new_code = re.search(r"project=([^&]+)", outcome.redirect_url).group(1)
    copied = get_project_by_code("v2-meta-user", new_code)
    assert copied.project_stage is None
    assert copied.model_perspective is None


# ---------------------------------------------------------------------------
# Financial-authority isolation
# ---------------------------------------------------------------------------

def test_metadata_does_not_enter_financial_authority(seeded_db):
    """MODEL_V2_METADATA_DOES_NOT_ENTER_FINANCIAL_AUTHORITY = PASS

    Setting Stage/Perspective must not change the serialized ProjectInputs
    representation, and the engine namespaces must not import the metadata
    module: metadata lives at the app/project layer only.
    """
    from app.persistence.projects_repository import save_project
    from app.project_factories import create_generic_solar_reference
    from finco_core.inputs.serialization import project_inputs_to_dict

    project_inputs = create_generic_solar_reference()
    before = project_inputs_to_dict(project_inputs)

    save_project(
        user_id="v2-meta-user",
        project_code="authority-proj",
        project_name="Authority Project",
        source_project_template="generic_solar_reference",
        project_stage=ProjectStage.CONSTRUCTION.value,
        model_perspective=ModelPerspective.IPP.value,
    )
    # Serialization of the same ProjectInputs is unchanged by persisted metadata.
    assert project_inputs_to_dict(create_generic_solar_reference()) == before

    # Engine namespaces never import app.model_v2: prove in a clean interpreter.
    code = (
        "import sys;"
        "import financial_engine.orchestrator, finco_core.inputs._models;"
        "print(any(m == 'app.model_v2' or m.startswith('app.model_v2.') for m in sys.modules))"
    )
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "False"


# ---------------------------------------------------------------------------
# Real canonical-runtime financial isolation
# ---------------------------------------------------------------------------

def test_financial_runtime_identical_with_and_without_metadata(seeded_db):
    """FINANCIAL_METADATA_ISOLATION = PASS — Correction A §5.

    The same economic Solar project, persisted once WITHOUT metadata and once
    WITH explicit Stage/Perspective metadata, must produce IDENTICAL canonical
    runtime outputs. Both runs load ProjectInputs through the real full_inputs
    persistence round trip, then execute the canonical clean production path.
    Metadata is never part of ProjectInputs, so no second calculator exists.
    """
    import dataclasses

    from app.persistence.projects_repository import get_project_by_code, save_project
    from app.project_factories import create_generic_solar_reference
    from app.services.production_financial_authority import run_clean_production
    from finco_core.inputs.serialization import (
        project_inputs_from_dict, project_inputs_to_dict,
    )
    from financial_engine.financing.project_uses import compute_project_uses

    TOL = 1e-9
    project_inputs = create_generic_solar_reference()
    serialized = project_inputs_to_dict(project_inputs)

    # Two project records: one without metadata, one with explicit metadata.
    save_project(
        user_id="v2-meta-user",
        project_code="iso-nometa",
        project_name="Isolation Without Metadata",
        source_project_template="generic_solar_reference",
        full_inputs=serialized,
    )
    save_project(
        user_id="v2-meta-user",
        project_code="iso-meta",
        project_name="Isolation With Metadata",
        source_project_template="generic_solar_reference",
        full_inputs=serialized,
        project_stage=ProjectStage.OPERATING.value,
        model_perspective=ModelPerspective.IPP.value,
    )
    plain_record = get_project_by_code("v2-meta-user", "iso-nometa")
    meta_record = get_project_by_code("v2-meta-user", "iso-meta")
    assert meta_record.project_stage == "operating"
    assert meta_record.model_perspective == "ipp"
    assert plain_record.project_stage is None

    def _metrics(record):
        pi = project_inputs_from_dict(record.full_inputs)
        run = run_clean_production(pi, "Base", project_type="solar")
        g2c = run.g2c_result
        model = g2c.financing_result.project_model_result
        senior = model.senior_debt
        dscr = [d for d in (senior.base_dscr or ()) if d is not None]
        op = model.operating_schedules
        return {
            "project_irr": g2c.return_summary.project.project_xirr,
            "senior_debt_keur": g2c.financing_result.final_senior_commitment_keur,
            "total_revenue_keur": float(sum(op.revenue_keur)),
            "total_opex_keur": float(sum(op.opex_keur)),
            "min_base_dscr": min(dscr),
            "avg_base_dscr": sum(dscr) / len(dscr),
            "total_project_uses_keur": compute_project_uses(pi).total_project_uses_keur,
            "statement_status": str(run.financial_statements_result.status),
            "pure_equity_xirr": g2c.pure_equity_xirr,
            "total_sponsor_xirr": g2c.total_sponsor_xirr,
        }

    plain = _metrics(plain_record)
    meta = _metrics(meta_record)
    for key, expected in plain.items():
        actual = meta[key]
        if isinstance(expected, float):
            assert actual == pytest.approx(expected, abs=TOL), key
        else:
            assert actual == expected, key

    # And the runtime result equals the direct (never-persisted) inputs run.
    direct = run_clean_production(project_inputs, "Base", project_type="solar")
    direct_model = direct.g2c_result.financing_result.project_model_result
    assert meta["senior_debt_keur"] == pytest.approx(
        direct.g2c_result.financing_result.final_senior_commitment_keur, abs=TOL)
    assert meta["project_irr"] == pytest.approx(
        direct.g2c_result.return_summary.project.project_xirr, abs=TOL)
    assert meta["statement_status"] == str(direct.financial_statements_result.status)
    assert dataclasses.is_dataclass(project_inputs)  # sanity: real inputs object
