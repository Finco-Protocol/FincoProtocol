"""WF-09 CSRF-inventory successor: positive proof, and every drift that must fail closed."""
from __future__ import annotations

import pytest

from tests import wf09_csrf_successor as wf09
from tests.test_trust_readiness_controls import test_known_gap_state_changing_posts_have_no_csrf_token as inventory_test

SOURCE = (wf09.ROOT / wf09.ROUTER).read_text(encoding="utf-8")


def test_the_reviewed_router_is_exactly_the_pinned_content_and_structure():
    assert wf09.source_blob(SOURCE) == wf09.ROUTER_BLOB
    assert wf09.violations(SOURCE) == []
    assert wf09.current_wf09_successor_valid() is True


def test_inventory_admits_the_router_only_while_the_successor_holds(monkeypatch):
    inventory_test()                                                   # real router: exact inventory incl. the WF-09 router
    monkeypatch.setattr(wf09, "current_wf09_successor_valid", lambda: False)
    with pytest.raises(AssertionError):                                # not proven -> the router is an unapproved CSRF consumer
        inventory_test()


SAVE_DEF = "async def capex_spending_profiles_save("
PREVIEW_DEF = "async def capex_spending_profiles_preview("


def _in(handler_def, fn):
    """Apply ``fn`` only inside one handler's source (from its def to the next top-level decorator)."""
    def apply(src):
        start = src.index(handler_def)
        end = src.find("\n@profile_router", start)
        end = len(src) if end < 0 else end
        return src[:start] + fn(src[start:end]) + src[end:]
    return apply


CSRF_CHECK = "if not validate_csrf_token(csrf_token):"
MUTATIONS = {
    "preview validator disabled": _in(PREVIEW_DEF, lambda h: h.replace(CSRF_CHECK, "if False:")),
    "save validator disabled": _in(SAVE_DEF, lambda h: h.replace(CSRF_CHECK, "if False:")),
    "preview validator bypassed by truthy literal": _in(PREVIEW_DEF, lambda h: h.replace(CSRF_CHECK, "if not (validate_csrf_token(csrf_token) or True):")),
    "save validator bypassed by truthy literal": _in(SAVE_DEF, lambda h: h.replace(CSRF_CHECK, "if not (validate_csrf_token(csrf_token) or True):")),
    "preview failure no longer 403": _in(PREVIEW_DEF, lambda h: h.replace("status_code=403", "status_code=200", 1)),
    "save failure no longer 403": _in(SAVE_DEF, lambda h: h.replace("status_code=403", "status_code=200", 1)),
    "preview check moved after form read": _in(PREVIEW_DEF, lambda h: h.replace(CSRF_CHECK, "form = await request.form()\n    " + CSRF_CHECK, 1)),
    "save check moved after the write": _in(SAVE_DEF, lambda h: h.replace(CSRF_CHECK, "if False:").replace(
        "    outcome = ", "    if not validate_csrf_token(csrf_token):\n        return None\n    outcome = ")),
    "preview token optional": _in(PREVIEW_DEF, lambda h: h.replace("csrf_token: str = Form(...)", "csrf_token: str = Form('')")),
    "save token optional": _in(SAVE_DEF, lambda h: h.replace("csrf_token: str = Form(...)", "csrf_token: str = Form('')")),
    "save CAS token optional": _in(SAVE_DEF, lambda h: h.replace("content_hash: str = Form(...)", "content_hash: str = Form('')")),
    "save token removed": _in(SAVE_DEF, lambda h: h.replace("csrf_token: str = Form(...),", "", 1)),
    "authentication guard removed": _in(SAVE_DEF, lambda h: h.replace("guard = _guard(request, project)", "guard = (None, None, None, None)", 1)),
    "ownership resolution removed": lambda s: s.replace("resolve_accessible_project(user.user_id, project)", "(None, None)"),
    "can_edit gate removed": _in(SAVE_DEF, lambda h: h.replace('if not ctx["can_edit"]:', "if False:")),
    "second validator call site": lambda s: s + "\n\ndef _extra(token):\n    return validate_csrf_token(token)\n",
    "extra POST route": lambda s: s + '\n\n@profile_router.post("/spending-profiles/apply")\nasync def apply(request: Request):\n    return None\n',
    "PUT route": lambda s: s + '\n\n@profile_router.put("/spending-profiles/save")\nasync def put(request: Request):\n    return None\n',
    "extra GET route": lambda s: s + '\n\n@profile_router.get("/spending-profiles/export")\nasync def export(request: Request):\n    return None\n',
    "preview becomes GET": lambda s: s.replace('@profile_router.post("/spending-profiles/preview"', '@profile_router.get("/spending-profiles/preview"'),
    "save becomes GET": lambda s: s.replace('@profile_router.post("/spending-profiles/save"', '@profile_router.get("/spending-profiles/save"'),
    "preview reaches the writer": _in(PREVIEW_DEF, lambda h: h.replace("    form = await request.form()", "    save_profiles(owner=owner, project_id=record.project_id, expected_hash='', raw='')\n    form = await request.form()", 1)),
    "writer called twice": lambda s: s + "\n\ndef _again(owner, project_id):\n    return save_profiles(owner=owner, project_id=project_id, expected_hash='', raw='')\n",
    "workspace writer reference": lambda s: s + "\n# apply_batch_draft_update(...)\n",
    "run reference": lambda s: s + "\n# run_project(...)\n",
    "raw SQL reference": lambda s: s + "\n# cur.execute(\n",
    "harmless comment (any byte change needs re-review)": lambda s: s + "\n# note\n",
    "syntax broken": lambda s: s + "\ndef (:\n",
}


@pytest.mark.parametrize("name", sorted(MUTATIONS))
def test_every_drift_is_rejected(name):
    mutated = MUTATIONS[name](SOURCE)
    assert mutated != SOURCE, f"mutation {name!r} did not change the router (stale fixture)"
    assert wf09.violations(mutated), name


def test_a_structurally_valid_but_unreviewed_router_still_fails_on_the_pin():
    harmless = SOURCE + "\n# note\n"
    assert wf09.violations(harmless, check_pin=False) == []            # structure alone is not enough ...
    assert wf09.violations(harmless) == ["router content is not the exact reviewed blob"]   # ... the pin is
