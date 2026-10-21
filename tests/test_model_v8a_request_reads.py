"""O6: safe elimination of a redundant workspace read from reference validation."""
from types import SimpleNamespace

from app.api.v1_1 import institutional


def test_reference_validation_skips_mutable_workspace_but_still_checks_tenant(monkeypatch):
    from app.persistence import projects_repository, workspace_repository

    calls = []

    def owned_project(project_id, user_id):
        calls.append((project_id, user_id))
        return SimpleNamespace(project_type="Unknown vertical")

    def forbidden_workspace_read(*_args, **_kwargs):
        raise AssertionError("Reference validation must not load unused Working Copy")

    monkeypatch.setattr(projects_repository, "get_project", owned_project)
    monkeypatch.setattr(workspace_repository, "get_workspace_state", forbidden_workspace_read)

    state, evidence = institutional.get_institutional_validation("tenant-a", "project-1")
    assert calls == [("project-1", "tenant-a")]
    assert state == institutional.STATE_UNAVAILABLE
    assert evidence["reason"] == "VALIDATION_UNAVAILABLE"


def test_reference_validation_does_not_query_workspace_for_absent_owned_project(monkeypatch):
    from app.persistence import projects_repository, workspace_repository

    monkeypatch.setattr(projects_repository, "get_project", lambda project_id, user_id: None)

    def forbidden_workspace_read(*_args, **_kwargs):
        raise AssertionError("An absent owned project cannot trigger a workspace read")

    monkeypatch.setattr(workspace_repository, "get_workspace_state", forbidden_workspace_read)
    state, evidence = institutional.get_institutional_validation("tenant-a", "missing")
    assert state == institutional.STATE_UNAVAILABLE
    assert evidence == {"reason": "PROJECT_NOT_FOUND"}
