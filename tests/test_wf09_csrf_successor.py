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


CSRF_GATE = '''    if not validate_csrf_token(csrf_token):
        ctx["error"] = "CAPEX_PROFILE_CSRF_INVALID"
        return _templates.TemplateResponse(request=request, name="capex_spending_profiles.html", context=ctx, status_code=403)
'''
FORM_READ = "    form = await request.form()\n"
MUTATIONS = {
    "validator call removed": lambda s: s.replace("if not validate_csrf_token(csrf_token):", "if False:"),
    "validator bypassed by truthy literal": lambda s: s.replace("if not validate_csrf_token(csrf_token):", "if not (validate_csrf_token(csrf_token) or True):"),
    "failure no longer 403": lambda s: s.replace("context=ctx, status_code=403)", "context=ctx, status_code=200)"),
    "check moved after form read": lambda s: s.replace(CSRF_GATE, "").replace(FORM_READ, FORM_READ + CSRF_GATE),
    "check moved after plan build": lambda s: s.replace(CSRF_GATE, "").replace("    ctx[\"form_rows\"] = form_rows\n", CSRF_GATE + "    ctx[\"form_rows\"] = form_rows\n"),
    "token optional": lambda s: s.replace("csrf_token: str = Form(...)", "csrf_token: str = Form('')"),
    "token no longer a parameter": lambda s: s.replace("csrf_token: str = Form(...),", ""),
    "authentication guard removed": lambda s: s.replace("    guard = _guard(request, project)\n    if isinstance(guard, RedirectResponse):\n        return guard\n    user, record, ws = guard\n    pis = WorkbookService.build_draft_input_set_from_workspace(ws)\n    ctx =", "    user, record, ws = None, None, None\n    pis = None\n    ctx =", 1),
    "ownership resolution removed": lambda s: s.replace("resolve_accessible_project(user.user_id, project)", "(None, None)"),
    "second validator call site": lambda s: s + "\n\ndef _extra(token):\n    return validate_csrf_token(token)\n",
    "second POST route": lambda s: s + '\n\n@profile_router.post("/spending-profiles/save")\nasync def save(request: Request):\n    return None\n',
    "PUT route": lambda s: s + '\n\n@profile_router.put("/spending-profiles/preview")\nasync def put(request: Request):\n    return None\n',
    "extra GET route": lambda s: s + '\n\n@profile_router.get("/spending-profiles/export")\nasync def export(request: Request):\n    return None\n',
    "preview becomes GET": lambda s: s.replace('@profile_router.post("/spending-profiles/preview"', '@profile_router.get("/spending-profiles/preview"'),
    "writer reference added": lambda s: s + "\n# apply_batch_draft_update(...)\n",
    "run reference added": lambda s: s + "\n# run_project(...)\n",
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
