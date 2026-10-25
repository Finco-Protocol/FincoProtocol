"""Stream A (RC-UX): one coherent result state after a Run (UX-001, UX-002).

After a successful Run every surface that states the Last Run must show the SAME committed Run: the toolbar chip, the header, the persistent
strip and the Trust sheet. Freshness (CURRENT / STALE / NOT RUN) and integrity (PASS / FAIL / UNAVAILABLE) stay independent. Nothing is
calculated here: the projection only arranges values the existing authorities already produced.
"""

from tests.run_clone_csrf import post_valid_csrf
import re

import pytest

from tests.test_post_run_request_context import _args, _capture, _edit, seed_database, state_db  # noqa: F401  (fixtures)


def _fragment(html, dom_id):
    """The out-of-band fragment whose root element carries ``id=dom_id`` (None when it is not in the response)."""
    match = re.search(r'<(\w+)[^>]*\bid="%s"[^>]*hx-swap-oob="true"' % re.escape(dom_id), html) or \
        re.search(r'<(\w+)[^>]*hx-swap-oob="true"[^>]*\bid="%s"' % re.escape(dom_id), html)
    if not match:
        return None
    nxt = html.find('hx-swap-oob="true"', match.end())            # the next out-of-band root ends this fragment
    end = html.rfind("<", match.end(), nxt) if nxt != -1 else len(html)
    return html[match.start():end if end > match.start() else len(html)]


@pytest.mark.parametrize("case", ["solar", "wind"])
def test_a_run_response_refreshes_the_trust_sheet_and_the_strip_with_the_committed_run(state_db, case):  # noqa: F811
    from app.persistence.workspace_repository import get_workspace_state
    from app.v2.post_run_ui import build_post_run_ui_state
    pr = state_db[case]
    ws = get_workspace_state(pr.user_id, pr.project_id)
    html = build_post_run_ui_state(**_args(pr, ws))
    trust = _fragment(html, "v2-sheet-trust")
    strip = _fragment(html, "v2-hybrid-status")
    assert trust is not None, "UX-001: the Trust sheet is not refreshed after a Run"
    assert strip is not None, "UX-002: the persistent strip is not refreshed after a Run"
    assert "No committed Last Run" not in trust
    snapshot = ws.last_runtime_snapshot_id
    assert snapshot and snapshot in trust                                   # the Trust sheet names THIS Run
    assert 'data-testid="hybrid-run-state"' in strip and "CURRENT" in strip.split('data-testid="hybrid-last-run"')[0]
    from app.v2.router import _fmt_runtime_at
    stamp = _fmt_runtime_at(ws.last_runtime_at)
    assert stamp and stamp in strip                                              # same time the toolbar shows
    toolbar = _fragment(html, "v2-toolbar-runtime-state")
    assert toolbar is not None and stamp in toolbar


def test_the_trust_sheet_and_the_strip_cannot_name_an_older_run_than_the_toolbar(state_db):  # noqa: F811
    """Two consecutive committed Runs (no reload): the second response names the second Run everywhere, never the first."""
    from app.persistence.workspace_repository import get_workspace_state
    from app.v2.post_run_ui import build_post_run_ui_state
    pr = state_db["solar"]
    first = get_workspace_state(pr.user_id, pr.project_id)
    first_html = build_post_run_ui_state(**_args(pr, first))
    first_snapshot = first.last_runtime_snapshot_id
    assert first_snapshot in _fragment(first_html, "v2-sheet-trust")
    # the second committed Run replaces the persisted evidence: emulate it through the real Run route on the same project
    from fastapi.testclient import TestClient
    import main_web
    from app.auth import COOKIE_NAME, create_session_token
    from tests.test_post_run_request_context import _tokens
    with TestClient(main_web.app) as client:
        cookies = {COOKIE_NAME: create_session_token(user_id=pr.user_id, username="admin")}
        content_hash, version = _tokens(client, cookies, pr.project_code)
        response = post_valid_csrf(client, "/v2/workbook/run", cookies=cookies, headers={"HX-Request": "true"},
                               data={"project": pr.project_code, "content_hash": content_hash, "workbook_version": version})
    assert response.status_code == 200
    second = get_workspace_state(pr.user_id, pr.project_id)
    assert second.last_runtime_snapshot_id != first_snapshot
    body = response.text
    trust = _fragment(body, "v2-sheet-trust")
    assert trust is not None and second.last_runtime_snapshot_id in trust
    assert first_snapshot not in trust                                      # UX-001: the stale Run must be gone
    strip = _fragment(body, "v2-hybrid-status")
    assert strip is not None
    from app.v2.router import _fmt_runtime_at
    assert _fmt_runtime_at(second.last_runtime_at) in strip


@pytest.mark.parametrize("state,integrity,expected", [
    ("CURRENT", "PASS", ("CURRENT", "PASS")), ("CURRENT", "FAIL", ("CURRENT", "FAIL")),
    ("STALE", "PASS", ("STALE", "PASS")), ("STALE", "UNAVAILABLE", ("STALE", "UNAVAILABLE")),
    ("NOT_RUN", "UNAVAILABLE", ("NOT RUN", "UNAVAILABLE")),
])
def test_freshness_and_integrity_are_independent_fields(state, integrity, expected):
    from app.v2.result_status import build_result_status
    pack = {"integrity": {"state": "AVAILABLE" if integrity != "UNAVAILABLE" else "UNAVAILABLE", "overall": integrity}}
    status = build_result_status(runtime_state=state, has_runtime=state != "NOT_RUN", last_runtime_at_display="15 Oct 2026 04:00",
                                 active_scenario_name="Upside", trust_pack=pack)
    assert (status.freshness_label, status.integrity) == expected
    assert status.scenario_name == "Upside"
    assert status.run_at_display == ("15 Oct 2026 04:00" if state != "NOT_RUN" else "")


def test_the_projection_never_invents_a_run_or_a_scenario():
    from app.v2.result_status import build_result_status
    status = build_result_status(runtime_state="NOT_RUN", has_runtime=False, last_runtime_at_display="15 Oct 2026 04:00",
                                 active_scenario_name="", trust_pack=None)
    assert status.run_at_display == "" and status.integrity == "UNAVAILABLE" and status.scenario_name == "Base"
    garbage = build_result_status(runtime_state="WEIRD", has_runtime=True, last_runtime_at_display="x",
                                  active_scenario_name=None, trust_pack={"integrity": "not-a-mapping"})
    assert garbage.freshness_label == "NOT RUN" and garbage.integrity == "UNAVAILABLE"


def test_the_strip_template_reads_only_the_projection():
    from app.v2.router import _templates
    status_ns = dict(project_name="P", project_type="Solar", project_editable=True,
                     result_status=__import__("app.v2.result_status", fromlist=["x"]).build_result_status(
                         runtime_state="STALE", has_runtime=True, last_runtime_at_display="1 Jan 2026 10:00",
                         active_scenario_name="Upside", trust_pack={"integrity": {"state": "AVAILABLE", "overall": "FAIL"}}))
    html = _templates.get_template("partials/_hybrid_status.html").render(status_ns)
    assert 'id="v2-hybrid-status"' in html
    assert "STALE" in html and "Integrity: FAIL" in html and "Scenario: Upside" in html and "1 Jan 2026 10:00" in html


def test_a_renamed_active_scenario_label_is_read_from_the_scenario_record(state_db):  # noqa: F811
    """UX-020: the workspace row keeps a copied label; after a rename the render-time label follows the scenario record."""
    from app.persistence.scenarios_repository import add_scenario, get_or_create_base_case_scenario, rename_scenario, select_scenario
    from app.persistence.workspace_repository import get_workspace_state
    from app.v2.result_status import with_current_scenario_label
    pr = state_db["solar"]
    base = get_or_create_base_case_scenario(
        user_id=pr.user_id, project_id=pr.project_id, project_code="ux-a", project_name="UX A", project_type="solar",
        source_project_template="", base_input_set={}, governance_state={})
    sc = add_scenario(
        user_id=pr.user_id, project_id=pr.project_id, project_code="ux-a", scenario_name="Old name",
        parent_scenario_id=base.scenario_id, base_input_set={}, overrides={})
    select_scenario(user_id=pr.user_id, project_id=pr.project_id, scenario_id=sc.scenario_id)
    ws = get_workspace_state(pr.user_id, pr.project_id)
    assert ws.active_scenario_name == "Old name"
    rename_scenario(user_id=pr.user_id, scenario_id=sc.scenario_id, new_name="New name")
    stale = get_workspace_state(pr.user_id, pr.project_id)
    assert stale.active_scenario_name == "Old name"                     # the copied label is stale in storage
    assert with_current_scenario_label(stale, pr.user_id).active_scenario_name == "New name"
