"""Import V2 review/Apply security and financial-safety negatives, through the real routes.

An unapproved suggestion is never persisted; forged, structured, cascade or inapplicable targets never reach the
canonical batch writer; tickets are bound to owner/project/composite CAS; Apply is all-or-nothing.
"""
from __future__ import annotations

import html
import re

import pytest

from app.auth import COOKIE_NAME, create_session_token, generate_csrf_token
from app.persistence.run_history_repository import get_run_history
from app.persistence.workspace_repository import get_workspace_state
from app.workbook.input_set import ProjectInputSet
from app.workbook.registry import WORKBOOK
from app.workbook.workbook_identity import assemble_consistent_for_get
from tests.test_model_decision_workspace_v2 import env  # noqa: F401
from tests.test_model_financing_f2 import save

OWNER = "decision-user"
CSV = (
    "Assumption\tValue\tUnit\n"
    "Grid interconnection cost\t1200,5\tkEUR\n"           # 0 ranked CAPEX
    "Insurance (annual)\t42,5\tkEUR/yr\n"                  # 1 ranked OPEX
    "Merchant price curve\t55\tEUR/MWh\n"                  # 2 structured, read-only
    "Guard services\t18000\tEUR/yr\n"                      # 3 unmapped
)


@pytest.fixture(autouse=True)
def _routes(env):
    from app.v2.import_router import router
    if not any(getattr(r, "path", "") == "/v2/workbook/import/preview" for r in env.client.app.routes):
        env.client.app.include_router(router, prefix="/v2")


def _ws(project):
    return get_workspace_state(OWNER, project.project_id)


def _hash(project):
    return assemble_consistent_for_get(OWNER, project.project_id, WORKBOOK.version).composite_hash


def _evidence(project):
    ws = _ws(project)
    return (ws.draft_snapshot, ws.saved_snapshot, ws.dirty, ws.last_runtime_snapshot_id, _hash(project),
            tuple(h.history_id for h in get_run_history(OWNER, project.project_id)))


def _preview(env, project, text=CSV):
    response = env.client.post(
        "/v2/workbook/import/preview", data={"project": project.project_code, "csrf_token": generate_csrf_token(),
                                             "encoding": "utf-8"},
        files={"upload": ("synthetic.csv", text.encode("utf-8"), "text/csv")})
    assert response.status_code == 200, response.text[:500]
    ticket = html.unescape(re.search(r'name="preview_ticket" value="([^"]+)"', response.text).group(1))
    return response, ticket


def _confirm(env, project, ticket, **selection):
    data = {"project": project.project_code, "csrf_token": generate_csrf_token(), "preview_ticket": ticket}
    data.update(selection)
    return env.client.post("/v2/workbook/import/confirm", data=data)


def _approved_ticket(response):
    return html.unescape(re.search(r'name="approved_ticket" value="([^"]+)"', response.text).group(1))


def _apply(env, project, approved):
    return env.client.post("/v2/workbook/import/apply", data={
        "project": project.project_code, "csrf_token": generate_csrf_token(), "approved_ticket": approved})


def test_review_shows_suggestions_but_nothing_is_persisted_or_approved(env):
    project = env.create("solar")
    before = _evidence(project)
    response, _ = _preview(env, project)
    text = response.text
    assert "ranked_candidate" in text and "UNSUPPORTED_FOR_APPLY" in text and 'data-testid="select-validated"' in text
    assert 'name="keep_0" value="on"' in text and 'name="keep_0" value="on" aria-label="Approve proposal 1" checked' not in text
    assert _evidence(project) == before                         # upload + review write nothing, run nothing


def test_unapproved_suggestions_are_never_persisted(env):
    project = env.create("solar")
    before = _evidence(project)
    _, ticket = _preview(env, project)
    rejected = _confirm(env, project, ticket)                    # nothing checked
    assert rejected.status_code == 422 and "IMPORT_APPROVED_FIELD_COUNT_INVALID" in rejected.text
    assert _evidence(project) == before


@pytest.mark.parametrize("forged,code", [
    ("revenue.multistream.contracts", "UNSUPPORTED_FOR_APPLY"),
    ("debt.financing.instruments", "UNSUPPORTED_FOR_APPLY"),
    ("debt.bankability.configuration", "UNSUPPORTED_FOR_APPLY"),
    ("revenue.merchant.price_curve_json", "UNSUPPORTED_FOR_APPLY"),
    ("project_setup.technical.capacity_mw", "BATCH_FIELD_REQUIRES_ATOMIC_CASCADE_SUPPORT"),
    ("revenue.data_center.occupancy_y1", "BATCH_FIELD_NOT_APPLICABLE"),
    ("not.a.real.field", "IMPORT_UNKNOWN_FIELD"),
])
def test_forged_structured_cascade_or_inapplicable_targets_are_rejected_before_any_write(env, forged, code):
    project = env.create("solar")
    before = _evidence(project)
    _, ticket = _preview(env, project)
    response = _confirm(env, project, ticket, keep_0="on", field_0=forged, manual_0="1")
    assert response.status_code == 422 and code in response.text, response.text[:400]
    assert _evidence(project) == before


def test_read_only_rows_cannot_be_approved_without_a_deliberate_scalar_mapping(env):
    project = env.create("solar")
    before = _evidence(project)
    _, ticket = _preview(env, project)
    response = _confirm(env, project, ticket, keep_2="on")       # structured row: no field selected
    assert response.status_code == 422 and "IMPORT_MAPPING_UNRESOLVED" in response.text
    assert _evidence(project) == before


def test_mixed_accept_reject_apply_is_exact_and_leaves_run_history_untouched(env):
    project = env.create("solar")
    history = tuple(h.history_id for h in get_run_history(OWNER, project.project_id))
    _, ticket = _preview(env, project)
    # approve rows 0 and 1, reject 2 (structured) and 3 (unmapped, not chosen); user-modified mapping for row 3
    confirm = _confirm(env, project, ticket, keep_0="on", field_0="capex.C.grid_connection", unit_0="kEUR",
                       keep_1="on", field_1="opex.lines.insurance", unit_1="kEUR/yr")
    assert confirm.status_code == 200 and "Final confirmation" in confirm.text and "USER" not in confirm.text
    result = _apply(env, project, _approved_ticket(confirm))
    assert result.status_code == 200 and "Import Apply result" in result.text and "USER_CONFIRMED_REVIEW" in result.text
    pis = ProjectInputSet.from_snapshot(_ws(project).draft_snapshot, workbook=WORKBOOK)
    assert float(pis.get("capex.C.grid_connection")) == pytest.approx(1200.5)
    assert float(pis.get("opex.lines.insurance")) == pytest.approx(42.5)
    assert pis.get("opex.lines.security") != "18"                # the unapproved row was not applied
    assert tuple(h.history_id for h in get_run_history(OWNER, project.project_id)) == history   # no Run


def test_one_invalid_approved_row_rejects_the_whole_set_all_or_nothing(env):
    project = env.create("solar")
    before = _evidence(project)
    _, ticket = _preview(env, project)
    response = _confirm(env, project, ticket, keep_0="on", field_0="capex.C.grid_connection", unit_0="kEUR",
                        keep_1="on", field_1="opex.lines.insurance", unit_1="kEUR/yr", manual_1="not-a-number")
    assert response.status_code == 422
    assert _evidence(project) == before


def test_stale_composite_between_review_and_apply_rejects_everything(env):
    project = env.create("solar")
    _, ticket = _preview(env, project)
    confirm = _confirm(env, project, ticket, keep_0="on", field_0="capex.C.grid_connection", unit_0="kEUR")
    approved = _approved_ticket(confirm)
    page = env.client.get("/v2/workbook", params={"project": project.project_code})   # a concurrent edit elsewhere
    assert save(env, project, "7", field="debt.senior.tenor_years").status_code in (200, 422)
    changed = _ws(project)
    after_concurrent = _evidence(project)
    result = _apply(env, project, approved)
    assert result.status_code in (409, 422) and "Import Apply result" not in result.text
    assert _evidence(project) == after_concurrent
    assert page is not None and changed is not None


def test_tampered_replayed_and_foreign_tickets_are_refused(env):
    project = env.create("solar")
    _, ticket = _preview(env, project)
    tampered = _confirm(env, project, ticket[:-3] + "xyz", keep_0="on", field_0="capex.C.grid_connection", unit_0="kEUR")
    assert tampered.status_code == 422 and "IMPORT_REVIEW_EXPIRED_OR_TAMPERED" in tampered.text
    confirm = _confirm(env, project, ticket, keep_0="on", field_0="capex.C.grid_connection", unit_0="kEUR")
    approved = _approved_ticket(confirm)
    assert _apply(env, project, approved).status_code == 200
    replay = _apply(env, project, approved)                       # the composite identity has moved on
    assert replay.status_code in (409, 422) and "Import Apply result" not in replay.text
    env.client.cookies.set(COOKIE_NAME, create_session_token(user_id="import-intruder", username="admin"))
    foreign = _apply(env, project, approved)
    assert foreign.status_code in (302, 303, 307) or "Import Apply result" not in foreign.text


def test_formula_and_oversized_uploads_stay_rejected(env):
    project = env.create("solar")
    response, ticket = _preview(env, project, "Assumption\tValue\tUnit\nGrid interconnection cost\t=SUM(A1:A9)\tkEUR\n")
    assert "IMPORT_FORMULA_NOT_AUTHORITATIVE" in response.text
    refused = _confirm(env, project, ticket, keep_0="on", field_0="capex.C.grid_connection", unit_0="kEUR")
    assert refused.status_code == 422 and "IMPORT_FORMULA_NOT_AUTHORITATIVE" in refused.text
    big = env.client.post("/v2/workbook/import/preview", data={"project": project.project_code, "csrf_token": generate_csrf_token(),
                                                                "encoding": "utf-8"},
                          files={"upload": ("big.csv", b"a" * (2 * 1024 * 1024 + 10), "text/csv")})
    assert big.status_code == 422 and "IMPORT_FILE_SIZE_INVALID" in big.text


def test_unrecognized_numeric_scalar_can_be_manually_mapped_and_validated(env):
    project = env.create("solar")
    before = _evidence(project)
    response, ticket = _preview(env, project)
    # Guard services starts without a suggestion and is never auto-approved.
    guard = re.search(r'<tr class="review-row"[^>]*data-manual-scalar="true"[^>]*>.*?Guard services.*?</tr>', response.text, re.S)
    assert guard is not None
    assert 'name="keep_3"' in guard.group(0) and 'disabled' in guard.group(0)
    confirmed = _confirm(env, project, ticket, keep_3="on", field_3="opex.lines.security", unit_3="EUR/yr")
    assert confirmed.status_code == 200 and "manual_reviewed" in confirmed.text
    assert _evidence(project) == before
    applied = _apply(env, project, _approved_ticket(confirmed))
    assert applied.status_code == 200
    pis = ProjectInputSet.from_snapshot(_ws(project).draft_snapshot, workbook=WORKBOOK)
    assert float(pis.get("opex.lines.security")) == pytest.approx(18.0)


def test_structured_source_cannot_be_forged_to_a_scalar_target(env):
    project = env.create("solar")
    before = _evidence(project)
    _, ticket = _preview(env, project)
    # A valid canonical field does not make a source originally classified as a contract applyable.
    response = _confirm(env, project, ticket, keep_2="on", field_2="opex.lines.security",
                        unit_2="EUR/yr", manual_2="18")
    assert response.status_code == 422
    assert "IMPORT_SOURCE_ROW_NOT_APPLYABLE" in response.text
    assert _evidence(project) == before
