"""RC-SEC reviewed CSRF successor positive and negative governance contracts."""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from tests import rc_sec_csrf_successor as S
from tests.test_trust_readiness_controls import (
    test_known_gap_state_changing_posts_have_no_csrf_token as inventory_test,
)

SOURCES = {path: (S.ROOT / path).read_text(encoding="utf-8") for path in S.BLOBS}


def test_exact_reviewed_run_clone_and_helper_contract():
    historical = {name: subprocess.check_output(["git", "show", f"{S.SOURCE_HEAD}:{name}"], cwd=S.ROOT).decode("utf-8") for name in S.BLOBS}
    for name, source in historical.items():
        assert S.git_blob(source) == S.BLOBS[name], name
    assert S.violations(historical) == []
    from tests.model_mutation_security_successor import current_mutation_successor_valid
    assert (S.violations(SOURCES) == []) or current_mutation_successor_valid()
    assert S.current_rc_sec_csrf_successor_valid() is True
    inventory_test()


def test_inventory_rejects_unproven_rc_sec_while_preserving_other_successors(monkeypatch):
    inventory_test()
    monkeypatch.setattr(S, "current_rc_sec_csrf_successor_valid", lambda: False)
    with pytest.raises(AssertionError):
        inventory_test()


@pytest.mark.parametrize("path,old,new", [
    (S.RUN_ROUTER, 'not validate_csrf_token(extract_bound_token(', 'not bool(extract_bound_token('),
    (S.RUN_ROUTER, 'csrf_token or run_csrf_token, purpose="workbook-run-v1"',
     'csrf_token or run_csrf_token, purpose="capital-stack-save-v1"'),
    (S.RUN_ROUTER, 'user = _get_current_user(request)', 'user = None'),
    (S.RUN_ROUTER, 'resolve_accessible_project(user.user_id, project)', '(None, None)'),
    (S.RUN_ROUTER, '"Invalid or missing CSRF token"}, status_code=403',
     '"Invalid or missing CSRF token"}, status_code=200'),
    (S.RUN_ROUTER, 'if current_identity.composite_hash != content_hash:',
     'if False:'),
    (S.RUN_ROUTER, 'if is_protected_reference(project_record):', 'if False:'),
    (S.RUN_ROUTER, 'if (csrf_token and run_csrf_token and csrf_token != run_csrf_token)',
     'if False'),
    (S.CLONE_ROUTER, 'not validate_csrf_token(extract_bound_token(', 'not bool(extract_bound_token('),
    (S.CLONE_ROUTER, 'csrf_token, purpose="library-clone-v1"',
     'csrf_token, purpose="capital-stack-save-v1"'),
    (S.CLONE_ROUTER, 'user = _get_current_user(request)', 'user = None'),
    (S.CLONE_ROUTER, 'get_canonical_reference_by_id(source_project_id) is None', 'False'),
    (S.CLONE_ROUTER, '"Project not found"}, status_code=404',
     '"Project not found"}, status_code=200'),
    (S.BINDING_MODULE, 'hmac.compare_digest(', 'str.__eq__('),
    (S.BINDING_MODULE, 'capital-stack-save-v1', 'capital-stack-other-v1'),
])
def test_security_and_source_drift_fails_closed_without_byte_pin(path, old, new):
    source = SOURCES[path]
    # Mutate the reviewed handler, not unrelated earlier routes with shared
    # helper/ownership names in the multi-route workbook module.
    section = ("@router.post(\"/workbook/run\")" if path == S.RUN_ROUTER else
               "@router.post(\"/library/clone/{source_project_id}\")" if path == S.CLONE_ROUTER else None)
    if section:
        prefix, marker, handler = source.partition(section)
        assert marker and old in handler, (path, old)
        modified = prefix + marker + handler.replace(old, new, 1)
    else:
        assert old in source, (path, old)
        modified = source.replace(old, new, 1)
    altered = dict(SOURCES)
    altered[path] = modified
    assert S.violations(altered), (path, old)
    assert S.violations(altered, check_pin=False), (path, old)


@pytest.mark.parametrize("path", list(S.BLOBS))
def test_even_nonsemantic_router_or_helper_change_needs_review(path):
    altered = dict(SOURCES)
    altered[path] += "\n# Unreviewed source change\n"
    assert S.violations(altered), path


def test_missing_provenance_and_removed_files_fail_closed(tmp_path, monkeypatch):
    for path, source in SOURCES.items():
        dest = tmp_path / path
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(source, encoding="utf-8")
    assert not S.current_rc_sec_csrf_successor_valid(repo=tmp_path)
    (tmp_path / S.CLONE_ROUTER).unlink()
    assert not S.current_rc_sec_csrf_successor_valid(repo=tmp_path)
    monkeypatch.setattr(S.subprocess, "run",
                        lambda *a, **k: (_ for _ in ()).throw(subprocess.CalledProcessError(128, a)))
    assert not S.current_rc_sec_csrf_successor_valid()


def test_positive_csrf_helper_never_patches_client_or_server():
    helper = SOURCES[S.POSITIVE_HELPER]
    assert "def post_valid_csrf(" in helper
    assert "client.post(url, *args, **kwargs)" in helper
    assert "issue_token(request, data.get(\"project\", \"\"), purpose=\"workbook-run-v1\")" in helper
    assert 'issue_token(request, "", purpose="library-clone-v1")' in helper
    assert 'effective.headers.get("cookie", "")' in helper
    for forbidden in ("TestClient.post =", "validate_csrf_token =", "monkeypatch", "setattr(client", "pytest.skip"):
        assert forbidden not in helper


@pytest.mark.parametrize("path,handler", [
    (S.RUN_ROUTER, S.RUN_HANDLER),
    (S.CLONE_ROUTER, S.CLONE_HANDLER),
])
def test_validator_reordered_after_mutation_fails_without_byte_pin(path, handler):
    import ast
    tree = ast.parse(SOURCES[path])
    fn = next(n for n in tree.body
              if isinstance(n, ast.AsyncFunctionDef) and n.name == handler)
    gates = [n for n in fn.body if isinstance(n, ast.If)
             and any(isinstance(c, ast.Call) and isinstance(c.func, ast.Name)
                     and c.func.id == "validate_csrf_token" for c in ast.walk(n.test))]
    assert len(gates) == 1
    fn.body.remove(gates[0])
    fn.body.append(gates[0])  # intentionally AFTER all effects
    altered = dict(SOURCES)
    altered[path] = ast.unparse(tree)
    assert S.violations(altered, check_pin=False)
