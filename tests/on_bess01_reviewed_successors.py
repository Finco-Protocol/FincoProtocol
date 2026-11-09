"""Correction B V1: explicit current-test successors, never historical normalization.

Accepted main owns the reviewed Revenue/O1 implementation. Literal whole-module
identity, independent AST identity, O1 provenance and closed BESS source governance
are all required. Historical comparison remains in the original test as fallback.
Bankability has two approved UI warnings; canonical stale refusal is independently
proved by the existing typed HX event and exact authoritative no-write readback.
"""
import ast
import json
from pathlib import Path
import subprocess

VERSION = 'ON_BESS01_CORRECTION_B_REVIEWED_TEST_SUCCESSORS_V2'
ACCEPTED_MAIN = '91e89bdd2127f5ec5d0e62833a1f9c3397ad5d14'
ACCEPTED_TREE = 'e9573d7802b319deb943dab60667778a431370e4'
F35B_BASE = 'cff1a7b19a72429636ec20325aadf5364365b12d'
ROUTER_PATH = 'app/v2/router.py'
ACCEPTED_ROUTER_BLOB = '58bdeaff5d511ffa62b077120871239ae4e6afa9'
HISTORICAL_ROUTER_BLOB = 'a2cd37c7df8e8dac881ba44d9f28df3bf25b913e'
TRUST_PATH = 'tests/test_trust_readiness_registry.py'
BANK_PATH = 'tests/model_react_rcm_financing_acceptance.py'
ORIGINAL_ASSERT = '    assert _revenue_critical_functions(source) == _revenue_critical_functions(_read_current("app/v2/router.py"))'
CURRENT_ASSERT = '    from tests.on_bess01_reviewed_successors import o1_revenue_authorized\n    assert (_revenue_critical_functions(source) == _revenue_critical_functions(_read_current("app/v2/router.py"))\n            or o1_revenue_authorized(source, _read_current("app/v2/router.py")))'
CURRENT_BANK_TEST = 'def test_a_changed_working_copy_is_refused_and_nothing_is_overwritten(live_server, fin_session):\n    from tests.on_bess01_reviewed_successors import bankability_refusal_valid\n    context, page, record, errors = fin_session("rcm-fin-stale")\n    open_tab(page, live_server, record.project_code, "bankability")\n    page.select_option("[data-bank=\'day_count\']", "act_365")\n    tokens = context.request.get(f"{live_server}/v2/model-react/fields/debt", params={"project": record.project_code}).json()["save"]\n    form = {"project": record.project_code, "field_id": FIELD,\n            "value": json.dumps({"version": 1, "day_count": "act_360"}),\n            "workbook_version": tokens["workbook_version"], "content_hash": tokens["content_hash"],\n            "sheet_id": "debt", "csrf_token": tokens["csrf_token"]}\n    other = context.request.post(f"{live_server}/v2/workbook/update", max_redirects=0, form=form)\n    assert other.status in (302, 303)\n    authoritative = draft_of(record)\n    assert json.loads(authoritative[0]["bankability_config_json"]) == {"version": 1, "day_count": "act_360"}\n    posts = []\n    page.on("request", lambda request: posts.append(request.url) if request.method == "POST" else None)\n    page.locator("[data-bank-save=\'true\']").click()\n    page.wait_for_selector("[data-wf-status=\'conflict\']", timeout=30000)\n    # Readback pumps the async refresh that can replace the preflight warning.\n    fresh = context.request.get(f"{live_server}/v2/model-react/fields/debt", params={"project": record.project_code}).json()["save"]\n    assert fresh["content_hash"] != tokens["content_hash"]\n    # Independent canonical CAS probe, deliberately outside the page: the same old\n    # identity must be rejected with the server\'s typed workbook-field-error event.\n    # This event uses conflict:true (NOT a fabricated FieldErrorClass/code).\n    refused = context.request.post(f"{live_server}/v2/workbook/update", max_redirects=0,\n                                   headers={"HX-Request": "true"}, form={**form, "value": json.dumps({"version": 1, "day_count": "act_365"})})\n    event = json.loads(refused.headers.get("hx-trigger", "{}"))\n    assert bankability_refusal_valid(\n        status=refused.status, event=event,\n        tone=page.locator("[data-wf-status=\'conflict\']").get_attribute("data-wf-status"),\n        warning=page.locator("[data-wf-status=\'conflict\']").inner_text(),\n        before=authoritative, after=draft_of(record), posts=posts,\n        local_day_count=page.locator("[data-bank=\'day_count\']").input_value())\n    assert unexpected(errors) == []\n'
ORIGINAL_SCOPE_BRANCH = '    if not any(p.startswith("app/trust_readiness/") for p in changed):\n        pytest.skip("trust pack not part of this diff")'
CURRENT_SCOPE_BRANCH = '    if not any(p.startswith("app/trust_readiness/") for p in changed):\n        from tests.on_bess01_reviewed_successors import nontrust_scope_authorized\n        if nontrust_scope_authorized(changed):\n            return      # V2: execute the closed current source review; no skip waiver.\n        pytest.skip("trust pack not part of this diff")'
APPROVED_WARNINGS = frozenset((
    'The project changed after this view loaded. Nothing was saved — reload to see the current values.',
    'Saved configuration changed. Your draft is retained; review the refreshed values before saving.',
))

def _function(raw, name):
    nodes = [n for n in ast.parse(raw).body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == name]
    if len(nodes) != 1:
        raise ValueError('missing/duplicate reviewed function')
    return nodes[0]


def reviewed_edits_ok(read, base_read):
    """One Revenue assertion, a bounded current scope branch and one Browser case."""
    old = base_read(TRUST_PATH).decode()
    if (old.count(ORIGINAL_ASSERT) != 1 or old.count(ORIGINAL_SCOPE_BRANCH) != 1
            or read(TRUST_PATH).decode() != old.replace(ORIGINAL_ASSERT, CURRENT_ASSERT).replace(ORIGINAL_SCOPE_BRANCH, CURRENT_SCOPE_BRANCH)):
        return False
    old = base_read(BANK_PATH).decode()
    n = _function(old, 'test_a_changed_working_copy_is_refused_and_nothing_is_overwritten')
    selected = '\n'.join(old.splitlines()[n.lineno-1:n.end_lineno]) + '\n'
    return read(BANK_PATH).decode() == old.replace(selected, CURRENT_BANK_TEST)


def revenue_structure_ok(source, accepted_source):
    """Pin-independent full AST check: auth, CSRF, reference, token and writer order.

    This compares to actual immutable accepted O1 source, never makes altered
    source look historical. Comments/formatting are handled by the separate pin.
    """
    try:
        return ast.dump(ast.parse(source)) == ast.dump(ast.parse(accepted_source))
    except (SyntaxError, ValueError, TypeError):
        return False


def o1_revenue_authorized(historical, current):
    from tests import on_bess01_scope as B
    from tests import post413_o1_scope as O1
    root = B.ROOT
    try:
        git = lambda *args: subprocess.check_output(['git', *args], cwd=root, stderr=subprocess.DEVNULL)
        if git('rev-parse', ACCEPTED_MAIN + '^{tree}').decode().strip() != ACCEPTED_TREE:
            return False
        git('merge-base', '--is-ancestor', ACCEPTED_MAIN, 'HEAD')
        old = git('show', F35B_BASE + ':' + ROUTER_PATH)
        accepted = git('show', ACCEPTED_MAIN + ':' + ROUTER_PATH)
        raw = (root / ROUTER_PATH).read_bytes()
        if (git('rev-parse', F35B_BASE + ':' + ROUTER_PATH).decode().strip() != HISTORICAL_ROUTER_BLOB
                or git('rev-parse', ACCEPTED_MAIN + ':' + ROUTER_PATH).decode().strip() != ACCEPTED_ROUTER_BLOB
                or historical != old.decode().strip() or current != raw.decode()
                or raw != accepted or not revenue_structure_ok(current, accepted)):
            return False
        # O1 proves its immutable base/tree/history and every current source pin;
        # B proves the bounded test edits, modes and complete changed-path closure.
        return O1.exact_blobs_ok(root) and B.exact_blobs_ok(root)
    except (OSError, ValueError, TypeError, subprocess.CalledProcessError):
        return False


def bankability_refusal_valid(*, status, event, tone, warning, before, after, posts, local_day_count):
    """No selector-only acceptance: typed canonical refusal + all state invariants."""
    expected = {'field_id': 'debt.bankability.configuration', 'message':
        'Draft changed since page loaded, so your edit was not saved. Reload the page to see the current value, then enter it again.',
        'error_class': None, 'conflict': True}
    try:
        return (status == 200 and event == {'workbook-field-error': expected}
                and tone == 'conflict' and warning in APPROVED_WARNINGS
                and before == after and posts == [] and local_day_count == 'act_365'
                and json.loads(after[0]['bankability_config_json']) == {'version': 1, 'day_count': 'act_360'})
    except (ValueError, TypeError, KeyError, IndexError):
        return False


def nontrust_scope_authorized(changed, repo=None):
    """Execute the original no-engine/writer/Radar obligation for this exact cohort.

    The immutable BASE diff must be the real main merge-base diff, not an
    invented trust-pack trigger. Exact BESS closure checks every foreign BASE
    byte/mode and the reviewed read-only BESS routes. Every registered cohort
    and the composite must also pass. Failure retains the historical fallback;
    the unchanged no-skip CI contract then refuses that outcome.
    """
    from tests import on_bess01_scope as B, fin_v2_cohorts as C
    root = Path(repo) if repo is not None else B.ROOT
    try:
        git = lambda *args: subprocess.check_output(['git', *args], cwd=root, stderr=subprocess.DEVNULL).decode().strip()
        if git('merge-base', 'origin/main', 'HEAD') != B.BASE:
            return False
        actual = git('diff', B.BASE, '--name-only').splitlines()
        if (not actual or sorted(changed) != sorted(actual)
                or not set(actual) <= B.OWNED_PATHS | {B.MANIFEST}):
            return False
        with C.call_scope():
            return B.exact_blobs_ok(root) and C.valid(root)
    except (OSError, ValueError, TypeError, subprocess.CalledProcessError):
        return False
