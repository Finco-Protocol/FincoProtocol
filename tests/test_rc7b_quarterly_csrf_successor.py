"""Quarterly CSRF recognition is exact, fail-closed and never financial approval."""
import ast
from pathlib import Path
import sqlite3
import subprocess

import pytest

from tests import rc7b_quarterly_csrf_successor as S
from tests.test_trust_readiness_controls import test_known_gap_state_changing_posts_have_no_csrf_token as inventory_test
from tests.test_model_decision_workspace_v2 import env, tokens  # noqa: F401

SOURCE = (S.ROOT / S.ROUTER).read_text(encoding="utf-8")


def test_exact_router_and_security_structure():
    assert S.source_blob(SOURCE) == S.ROUTER_BLOB
    assert S.violations(SOURCE) == []
    assert S.current_quarterly_csrf_successor_valid()
    fn = next(n for n in ast.parse(SOURCE).body if isinstance(n, ast.AsyncFunctionDef))
    calls = {ast.unparse(n.func): n for n in ast.walk(fn) if isinstance(n, ast.Call)}
    write = calls["WorkbookUpdateService.apply_draft_update"]
    for name in ("resolve_request_session", "resolve_accessible_project", "validate_csrf_token",
                 "is_protected_reference", "config.require_admitted", "config.apply_config"):
        assert calls[name].lineno < write.lineno
    kwargs = {k.arg: ast.unparse(k.value) for k in write.keywords}
    assert kwargs == {"ws": "ws", "field_id": "config.FIELD_ID", "raw_value": "raw",
                      "content_hash": "form['content_hash']", "workbook_version": "form['workbook_version']",
                      "project_record": "record"}


def test_inventory_requires_the_exact_successor(monkeypatch):
    inventory_test()
    monkeypatch.setattr(S, "current_quarterly_csrf_successor_valid", lambda: False)
    with pytest.raises(AssertionError):
        inventory_test()


@pytest.mark.parametrize("old,new", [
    ('if not validate_csrf_token(form["csrf_token"]):', 'if False:'),
    ('status_code=403', 'status_code=200'),
    ('if owner != user.user_id or is_protected_reference(record):', 'if False:'),
    ('resolve_request_session(request)', 'None'),
    ('resolve_accessible_project(user.user_id, form["project"])', '(None, None)'),
    ('config.apply_config(working, raw, record.project_type)', 'None'),
    ('content_hash=form["content_hash"]', 'content_hash="ignored"'),
    ('if form["frequency"] != "6/6" and not config.ACTIVATION_ENABLED:', 'if False:'),
    ('@router.post("/workbook/calendar/operating-frequency")', '@router.get("/workbook/calendar/operating-frequency")'),
    ('field_id=config.FIELD_ID', 'field_id="debt.senior.target_dscr"'),
])
def test_security_and_route_mutations_fail_with_or_without_byte_check(old, new):
    assert old in SOURCE
    changed = SOURCE.replace(old, new)
    assert S.violations(changed)
    assert S.violations(changed, check_pin=False)


@pytest.mark.parametrize("extra", [
    '\n# Unreviewed byte\n',
    '\n' + '@router.post("/extra")\nasync def extra():\n    return None\n',
    '\nsave_workspace(None)\n',
    '\nrun_clean_production(None)\n',
])
def test_no_extra_content_route_writer_or_run(extra):
    assert S.violations(SOURCE + extra)


def test_missing_provenance_or_opened_activation_fails_closed(tmp_path, monkeypatch):
    (tmp_path / S.ROUTER).parent.mkdir(parents=True)
    (tmp_path / S.ROUTER).write_text(SOURCE, encoding="utf-8")
    (tmp_path / S.ACTIVATION_PATH).parent.mkdir(parents=True, exist_ok=True)
    (tmp_path / S.ACTIVATION_PATH).write_text("ACTIVATION_ENABLED = False\n", encoding="utf-8")
    assert not S.current_quarterly_csrf_successor_valid(repo=tmp_path)  # no Git provenance
    def missing(*args, **kwargs):
        raise subprocess.CalledProcessError(128, args)
    monkeypatch.setattr(S.subprocess, "run", missing)
    assert not S.current_quarterly_csrf_successor_valid()


def test_literal_closed_activation_is_required(monkeypatch):
    original = Path.read_text
    def altered(path, *args, **kwargs):
        if str(path).replace("\\", "/").endswith(S.ACTIVATION_PATH):
            return "ACTIVATION_ENABLED = True\n"
        return original(path, *args, **kwargs)
    monkeypatch.setattr(Path, "read_text", altered)
    assert not S.current_quarterly_csrf_successor_valid()


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
