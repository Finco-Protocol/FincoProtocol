"""Quarterly CSRF recognition is exact, fail-closed and never financial approval."""
import ast
from pathlib import Path
import sqlite3
import subprocess

import pytest

from tests.test_model_decision_workspace_v2 import env, tokens  # noqa: F401


@pytest.fixture(autouse=True, scope="module")
def _finco47_legacy_ssr_rollback():
    """Module-scoped so module/session fixtures that seed over HTTP see the legacy SSR
    surface this module still exercises; default production flag stays React ON and the
    environment is restored exactly when the module finishes."""
    patch = pytest.MonkeyPatch()
    patch.setenv("FINCO_MODEL_REACT_V1", "0")
    try:
        yield
    finally:
        patch.undo()


@pytest.mark.parametrize("identity,status", [("anonymous", 401), ("other-owner", 404), ("reference", 403)])
def test_real_endpoint_security_preserves_workspace_and_history(env, monkeypatch, identity, status):
    from app.auth import COOKIE_NAME, create_session_token, generate_csrf_token
    from app.persistence.projects_repository import create_project_record
    from app.persistence.workspace_repository import get_workspace_state, save_workspace_state
    from app.persistence.run_history_repository import get_run_history
    from app.runtime import model_execution
    project = env.create("solar")
    owner = "decision-user"
    if identity == "reference":
        ws = get_workspace_state(owner, project.project_id)
        project = create_project_record(user_id=owner, project_code="rc7b-security-reference",
            project_name="Synthetic protected reference", project_type="Solar", project_origin="factory_template",
            template_source="generic_solar_reference", baseline_snapshot=dict(ws.draft_snapshot), is_readonly=False)
        # Bootstrap the reference's workspace while it is still a writable draft, THEN seal it read-only. WF-03 (intended) forbids any
        # post-creation write to a read-only/protected user-owned project, so sealing last is the supported order.
        save_workspace_state(user_id=owner, project_id=project.project_id, project_code=project.project_code,
                             draft_snapshot=dict(ws.draft_snapshot), saved_snapshot=dict(ws.saved_snapshot))
        from app.persistence.db import get_cursor
        with get_cursor() as cur:
            cur.execute("UPDATE projects SET is_readonly=1 WHERE project_id=?", (project.project_id,))
        # Direct negative: once sealed, a repository write to the reference is refused by the lifecycle fence and changes nothing.
        sealed = get_workspace_state(owner, project.project_id)
        with pytest.raises(sqlite3.IntegrityError, match="WF03_LIFECYCLE_CONFLICT"):
            save_workspace_state(user_id=owner, project_id=project.project_id, project_code=project.project_code,
                                 draft_snapshot=dict(ws.draft_snapshot), saved_snapshot=dict(ws.saved_snapshot))
        assert get_workspace_state(owner, project.project_id) == sealed
    def forbidden(*args, **kwargs):
        raise AssertionError("No financial calculation is authorized by opening or saving frequency")
    monkeypatch.setattr(model_execution, "run_model_process", forbidden)
    page = env.client.get("/v2/workbook", params={"project": project.project_code})
    assert page.status_code == 200
    before = get_workspace_state(owner, project.project_id)
    body = {"project": project.project_code, "csrf_token": generate_csrf_token(),
            "frequency": "6/6", "financing_structure": "", **tokens(page.text)}
    if identity == "anonymous":
        env.client.cookies.clear()
    elif identity == "other-owner":
        env.client.cookies.set(COOKIE_NAME, create_session_token(user_id="quarterly-other-owner", username="admin"))
    response = env.client.post("/v2/workbook/calendar/operating-frequency", data=body, follow_redirects=False)
    assert response.status_code == status
    assert get_workspace_state(owner, project.project_id) == before
    assert get_run_history(owner, project.project_id) == []
