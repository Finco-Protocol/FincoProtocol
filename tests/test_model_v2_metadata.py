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
