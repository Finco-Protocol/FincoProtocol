"""Strict negatives for the RC-M React adapter CSRF-inventory successor (review proposal, not approval)."""
import re

import pytest

from tests import rcm_adapter_csrf_successor as S

SOURCES = {path: (S.ROOT / path).read_text(encoding="utf-8") for path in S.ROUTERS}
NP, GS = "app/v2/react_new_project.py", "app/v2/react_goal_seek.py"


def test_the_successor_covers_exactly_the_two_reviewed_adapters():
    assert set(S.ROUTERS) == {NP, GS}


@pytest.mark.parametrize("path", S.ROUTERS)
def test_exact_reviewed_module_is_recognised(path):
    assert S.source_blob(SOURCES[path]) == S.SPECS[path]["blob"] and len(S.SPECS[path]["blob"]) == 40
    assert S.violations(path, SOURCES[path]) == [] and S.current_rcm_adapter_valid(path)


@pytest.mark.parametrize("path", S.ROUTERS)
def test_one_byte_of_drift_fails_closed_until_re_reviewed(path):
    assert S.violations(path, SOURCES[path] + "\n")
    assert S.violations(path, SOURCES[path], check_pin=False) == []      # the structural proof is independent of the pin
    assert not S.current_rcm_adapter_valid(path, repo=S.ROOT / "tests")


COMMON = [
    ("gate removed", lambda s: s.replace("not validate_csrf_token(", "validate_csrf_token(")),
    ("gate answers 200", lambda s: re.sub(r'(_json\(\{"ok": False, "code": "CSRF_INVALID"\}), 403\)', r"\1, 200)", s)),
    ("unbound token", lambda s: re.sub(r"extract_bound_token\(request, [\w.]+, [\w.]+, purpose=PURPOSE\)", "body.csrf_token", s)),
    ("second validator", lambda s: s + "\n\ndef x(t):\n    return validate_csrf_token(t)\n"),
    ("extra POST", lambda s: s + '\n\n@router.post("/model-react/x/other")\nasync def other(request: Request):\n    return _json({})\n'),
    ("extra GET", lambda s: s + '\n\n@router.get("/model-react/x/other")\nasync def other(request: Request):\n    return _json({})\n'),
    ("sql reference", lambda s: s + "\n_SQL = 'INSERT INTO projects'\n"),
    ("cursor reference", lambda s: s + "\n_x = get_cursor\n"),
    ("auth removed", lambda s: s.replace("resolve_request_session", "resolve_something_else")),
]


@pytest.mark.parametrize("path", S.ROUTERS)
@pytest.mark.parametrize("name,mutate", COMMON)
def test_structural_drift_is_rejected_even_when_the_pin_is_ignored(path, name, mutate):
    mutated = mutate(SOURCES[path])
    assert mutated != SOURCES[path], name
    assert S.violations(path, mutated, check_pin=False), name


@pytest.mark.parametrize("path,writer", [(NP, "update_project_record"), (GS, "apply_draft_update")])
def test_a_writer_call_before_the_gate_is_rejected(path, writer):
    gate = "    if not _REQUEST_ID.match(body.request_id) or not validate_csrf_token(" if path == NP else "    if not validate_csrf_token("
    assert gate in SOURCES[path]
    early = f"    {writer}(user_id='x', project_code='y')\n" if path == NP else "    WorkbookUpdateService.apply_draft_update(ws=None)\n"
    assert S.violations(path, SOURCES[path].replace(gate, early + gate, 1), check_pin=False)


def test_each_canonical_writer_is_referenced_exactly_where_reviewed():
    assert len(re.findall(r"\bcreate_reference_seeded_project\(", SOURCES[NP])) == 1
    assert len(re.findall(r"\bupdate_project_record\(", SOURCES[NP])) == 1
    assert len(re.findall(r"\bapply_draft_update\(", SOURCES[GS])) == 1
