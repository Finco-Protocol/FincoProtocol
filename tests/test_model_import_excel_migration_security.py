"""Excel migration V3 — route-level security and financial-safety negatives.

Tickets are bound to owner/project/scenario/composite CAS; a rejected request leaves NO partial write; structured,
formula and unresolved-scenario data never enter scalar Apply; reconciliation never invents parity.
"""
from __future__ import annotations

from tests.model_mutation_csrf import post_valid_mutation

import html
import re

import pytest
from itsdangerous import URLSafeTimedSerializer

from app.auth import COOKIE_NAME, SECRET_KEY, create_session_token, generate_csrf_token
from app.persistence.run_history_repository import get_run_history
from tests import migration_fixtures as F
from tests.migration_routes_support import (
    FIELDS, OWNER, apply, ids_for, assess, confirm, err, evidence, full_apply, hidden, journey_workbook, recon_detail,
    reconcile, review_slice, run_model, selection, slice_ticket, ws_of,
)
from tests.test_model_decision_workspace_v2 import env  # noqa: F401
from tests.test_model_financing_f2 import save


@pytest.fixture(autouse=True)
def _routes(env):
    from app.v2.import_router import router
    if not any(getattr(r, "path", "") == "/v2/workbook/import/assess" for r in env.client.app.routes):
        env.client.app.include_router(router, prefix="/v2")


def reviewed_slice(env, project, key="upside", data=None):
    assessed = assess(env, project, data or journey_workbook())
    reviewed = review_slice(env, project, slice_ticket(assessed, key), hidden(assessed, "manifest_token"))
    assert reviewed.status_code == 200, err(reviewed)
    return assessed, reviewed


# ── assess is read-only and gated ─────────────────────────────────────────────────────────────────────────────
def test_assess_writes_nothing_runs_nothing_and_executes_nothing(env):
    project = env.create("solar")
    before = evidence(project)
    vba = F.build_vba_container(["ThisWorkbook", "Switch"])
    data = F.to_xlsm(F.add_external_link(journey_workbook()), vba)
    response = assess(env, project, data, "model.xlsm")
    assert response.status_code == 200, err(response)
    for needle in ("Macro-bearing", "VBA project (metadata only)", "Switch", "External links", "never opened", "macro present"):
        assert needle.lower() in response.text.lower(), needle
    assert evidence(project) == before


def test_assess_requires_login_owner_csrf_and_bounded_upload(env):
    project = env.create("solar")
    bad_csrf = assess(env, project, journey_workbook(), csrf="forged")
    assert bad_csrf.status_code == 403 and "IMPORT_CSRF_INVALID" in bad_csrf.text
    big = assess(env, project, b"PK" + b"0" * (2 * 1024 * 1024 + 10))
    assert big.status_code == 422 and "IMPORT_FILE_SIZE_INVALID" in big.text
    csv = assess(env, project, b"a,b", "x.csv")
    assert csv.status_code == 422 and "IMPORT_FORMAT_UNSUPPORTED" in csv.text
    env.client.cookies.set(COOKIE_NAME, create_session_token(user_id="import-intruder", username="admin"))
    foreign = env.client.post("/v2/workbook/import/assess", follow_redirects=False, data={
        "project": project.project_code, "csrf_token": generate_csrf_token()},
        files={"upload": ("m.xlsx", journey_workbook(), "application/octet-stream")})
    assert foreign.status_code in (302, 303, 307)
    env.client.cookies.clear()
    anonymous = env.client.post("/v2/workbook/import/assess", follow_redirects=False, data={
        "project": project.project_code, "csrf_token": generate_csrf_token()},
        files={"upload": ("m.xlsx", journey_workbook(), "application/octet-stream")})
    assert anonymous.status_code in (302, 303, 307) and "/login" in anonymous.headers.get("location", "")


def test_oversize_body_gate_covers_the_assess_route():
    from pathlib import Path
    gate = Path("main_web.py").read_text(encoding="utf-8")
    assert '"/v2/workbook/import/assess"' in gate.split("_model_import_content_length_gate", 1)[1][:400]


def test_new_modules_never_touch_disk_network_or_the_engine():
    from pathlib import Path
    for name in ("workbook_inspect", "migration_scenarios", "migration_plan", "migration_portfolio", "migration_reconcile"):
        src = Path("app/model_import", f"{name}.py").read_text(encoding="utf-8")
        for needle in ("open(", ".write(", "tempfile", "NamedTemporaryFile", "extractall(", "shutil", "subprocess", "os.system",
                       "eval(", "exec(", "requests", "urllib", "socket", "httpx", ".apply_batch_draft_update(", "run_project("):
            assert needle not in src, (name, needle)


# ── unresolved scenarios and non-importable classes have no Apply path ────────────────────────────────────────
def test_unresolved_scenario_slice_has_no_ticket_and_no_review_button(env):
    project = env.create("solar")
    response = assess(env, project, F.save(F.selector_only_workbook()))
    assert response.status_code == 200
    assert "SCENARIO_LOGIC_UNRESOLVED" in response.text and 'data-testid="slice-blocked"' in response.text
    unresolved = re.search(r'data-slice="unresolved_selected_case".*?</div>', response.text, re.S).group(0)
    assert "slice_ticket" not in unresolved and "Review" not in unresolved
    # the only offered slice is the case-independent one
    assert 'data-testid="review-slice-COMMON"' in response.text


def test_structured_formula_and_output_rows_cannot_be_forced_into_scalar_apply(env):
    project = env.create("solar")
    _, reviewed = reviewed_slice(env, project, "base_case")
    before = evidence(project)
    ticket = hidden(reviewed, "preview_ticket")
    rows = {label: ids_for(reviewed, label)[0] for label in ("Transformer", "Target leverage", "Audit and legal")}
    # a formula result can never be approved, whatever field or manual value is forged onto it
    formula = confirm(env, project, ticket, **{f"keep_{rows['Target leverage']}": "on",
                                               f"field_{rows['Target leverage']}": "debt.senior.interest_rate_pct",
                                               f"manual_{rows['Target leverage']}": "9"})
    assert formula.status_code == 422 and "IMPORT_FORMULA_NOT_AUTHORITATIVE" in formula.text
    assert evidence(project) == before
    # a structured cost line is not a scalar row: the checkbox is disabled and no suggestion exists...
    assert re.search(r'name="keep_%s"[^>]*disabled' % rows["Transformer"], reviewed.text)
    unmapped = confirm(env, project, ticket, **{f"keep_{rows['Transformer']}": "on"})
    assert unmapped.status_code == 422 and "IMPORT_MAPPING_UNRESOLVED" in unmapped.text
    assert evidence(project) == before
    for forged, code in (("revenue.multistream.contracts", "UNSUPPORTED_FOR_APPLY"), ("debt.financing.instruments", "UNSUPPORTED_FOR_APPLY"),
                         ("project_setup.technical.capacity_mw", "BATCH_FIELD_REQUIRES_ATOMIC_CASCADE_SUPPORT")):
        r = confirm(env, project, ticket, **{f"keep_{rows['Audit and legal']}": "on", f"field_{rows['Audit and legal']}": forged,
                                             f"manual_{rows['Audit and legal']}": "1"})
        assert r.status_code == 422 and code in r.text
    assert evidence(project) == before


# ── tickets ───────────────────────────────────────────────────────────────────────────────────────────────────
def test_slice_ticket_tampered_foreign_project_and_wrong_kind_are_refused(env):
    project = env.create("solar")
    other = env.create("wind")
    assessed = assess(env, project, journey_workbook())
    ticket = slice_ticket(assessed, "upside")
    before = evidence(project)
    tampered = review_slice(env, project, ticket[:-3] + "xyz")
    assert tampered.status_code == 422 and "IMPORT_REVIEW_EXPIRED_OR_TAMPERED" in tampered.text
    cross = review_slice(env, other, ticket)                       # a ticket sealed for another project
    assert cross.status_code == 422 and "IMPORT_REVIEW_OWNER_MISMATCH" in cross.text
    flat = env.client.post("/v2/workbook/import/preview", data={"project": project.project_code, "csrf_token": generate_csrf_token(),
                                                                "encoding": "utf-8"},
                           files={"upload": ("flat.csv", b"Assumption\tValue\tUnit\nCost of debt\t5,25 %\t\n", "text/csv")})
    not_a_slice = review_slice(env, project, hidden(flat, "preview_ticket"))
    assert not_a_slice.status_code == 422 and "IMPORT_REVIEW_TICKET_NOT_A_MIGRATION_SLICE" in not_a_slice.text
    csrf = env.client.post("/v2/workbook/import/review-slice", data={"project": project.project_code, "csrf_token": "forged",
                                                                     "slice_ticket": ticket})
    assert csrf.status_code == 403
    env.client.cookies.set(COOKIE_NAME, create_session_token(user_id="import-intruder", username="admin"))
    foreign = env.client.post("/v2/workbook/import/review-slice", follow_redirects=False, data={
        "project": project.project_code, "csrf_token": generate_csrf_token(), "slice_ticket": ticket})
    assert foreign.status_code in (302, 303, 307)
    env.client.cookies.set(COOKIE_NAME, create_session_token(user_id=OWNER, username="admin"))
    assert evidence(project) == before


def test_scenario_cas_a_ticket_for_one_scenario_cannot_review_or_apply_in_another(env):
    project = env.create("solar")
    post_valid_mutation(env.client, "/v2/workbook/scenarios/create", data={"project": project.project_code, "scenario_name": "Upside"})
    upside_id = ws_of(project).active_scenario_id
    assessed, reviewed = reviewed_slice(env, project, "upside")
    ticket, approved_ticket = hidden(reviewed, "preview_ticket"), None
    confirmed = confirm(env, project, ticket, **selection(reviewed))
    approved_ticket = hidden(confirmed, "approved_ticket")
    # the user switches to a different scenario (the Base Case) before the ticket is used
    scenarios = re.findall(r'name="scenario_id" value="([^"]+)"', env.client.get("/v2/workbook", params={"project": project.project_code}).text)
    other = next(s for s in scenarios if s != upside_id)
    assert post_valid_mutation(env.client, "/v2/workbook/scenarios/select", data={"project": project.project_code, "scenario_id": other}).status_code in (200, 303)
    assert ws_of(project).active_scenario_id == other
    before = evidence(project)
    stale_review = review_slice(env, project, slice_ticket(assessed, "upside"))
    assert stale_review.status_code == 409 and "IMPORT_PREVIEW_STALE" in stale_review.text
    stale_confirm = confirm(env, project, ticket, **selection(reviewed))
    assert stale_confirm.status_code == 409 and "IMPORT_PREVIEW_STALE" in stale_confirm.text
    stale_apply = apply(env, project, approved_ticket)
    assert stale_apply.status_code in (409, 422) and "Import Apply result" not in stale_apply.text
    assert evidence(project) == before                        # nothing reached ANY scenario


def test_replayed_migration_ticket_cannot_apply_twice(env):
    project = env.create("solar")
    _, reviewed = reviewed_slice(env, project)
    confirmed = confirm(env, project, hidden(reviewed, "preview_ticket"), **selection(reviewed))
    approved = hidden(confirmed, "approved_ticket")
    assert apply(env, project, approved).status_code == 200
    after = evidence(project)
    replay = apply(env, project, approved)
    assert replay.status_code in (409, 422) and "Import Apply result" not in replay.text
    assert evidence(project) == after
    tampered = apply(env, project, approved[:-3] + "xyz")
    assert tampered.status_code == 422 and "IMPORT_REVIEW_EXPIRED_OR_TAMPERED" in tampered.text


def test_stale_composite_after_concurrent_edit_rejects_everything(env):
    project = env.create("solar")
    _, reviewed = reviewed_slice(env, project)
    confirmed = confirm(env, project, hidden(reviewed, "preview_ticket"), **selection(reviewed))
    approved = hidden(confirmed, "approved_ticket")
    assert save(env, project, "7", field="debt.senior.tenor_years").status_code in (200, 422)
    after = evidence(project)
    result = apply(env, project, approved)
    assert result.status_code in (409, 422) and "Import Apply result" not in result.text
    assert evidence(project) == after


def test_one_invalid_row_rejects_the_whole_slice_atomically(env):
    project = env.create("solar")
    _, reviewed = reviewed_slice(env, project)
    before = evidence(project)
    rows = selection(reviewed)
    insurance = re.search(r'name="keep_(\d+)"[^>]*>(?:(?!</tr>).)*Insurance \(annual\)', reviewed.text, re.S)
    bad = {**rows, f"manual_{[k for k in rows if rows[k] == 'opex.lines.insurance'][0].split('_')[1]}": "not-a-number"}
    response = confirm(env, project, hidden(reviewed, "preview_ticket"), **bad)
    assert response.status_code == 422 and insurance
    assert evidence(project) == before
    # a unit decision that would be a 1000x error is also refused, not guessed
    cost = {k: v for k, v in rows.items() if v in ("capex.C.grid_connection",)}
    rid = next(k for k in cost).split("_")[1]
    unitless = confirm(env, project, hidden(reviewed, "preview_ticket"), **{f"keep_{rid}": "on", f"field_{rid}": "capex.C.grid_connection", f"unit_{rid}": ""})
    assert unitless.status_code == 422 and "IMPORT_CURRENCY_UNIT_REQUIRED" in unitless.text
    assert evidence(project) == before


def test_duplicate_targets_in_a_slice_are_refused(env):
    project = env.create("solar")
    book = F.scenario_columns_workbook()
    book["Common"].append(["Insurance (annual)", 99, "kEUR/yr"])
    book["Common"].append(["Insurance (annual)", 98, "kEUR/yr"])
    assessed = assess(env, project, F.save(book))
    reviewed = review_slice(env, project, slice_ticket(assessed, "upside"))
    ids = ids_for(reviewed, "Insurance (annual)")
    assert len(ids) >= 3                      # the scenario column row plus the two case-independent duplicates
    before = evidence(project)
    r = confirm(env, project, hidden(reviewed, "preview_ticket"), **{f"keep_{ids[0]}": "on", f"field_{ids[0]}": "opex.lines.insurance",
                                                                    f"keep_{ids[1]}": "on", f"field_{ids[1]}": "opex.lines.insurance"})
    assert r.status_code == 422 and "IMPORT_DUPLICATE_TARGET" in r.text
    assert evidence(project) == before


def test_scenario_confirmation_cannot_be_skipped_by_posting_the_ticket_directly(env):
    project = env.create("solar")
    _, reviewed = reviewed_slice(env, project)
    before = evidence(project)
    r = confirm(env, project, hidden(reviewed, "preview_ticket"), scenario_confirmed=False, **selection(reviewed))
    assert r.status_code == 422 and "IMPORT_SCENARIO_CONFIRMATION_REQUIRED" in r.text
    assert evidence(project) == before


def test_protected_reference_projects_cannot_be_targeted(env, monkeypatch):
    project = env.create("solar")
    monkeypatch.setattr("app.v2.import_router.is_protected_reference", lambda record: True)
    before = evidence(project)
    for path, extra in (("assess", {"upload": ("m.xlsx", journey_workbook(), "application/octet-stream")}),):
        r = env.client.post(f"/v2/workbook/import/{path}", follow_redirects=False,
                            data={"project": project.project_code, "csrf_token": generate_csrf_token()}, files=extra)
        assert r.status_code in (302, 303, 307) and "/library" in r.headers["location"]
    for path, data in (("review-slice", {"slice_ticket": "x"}), ("reconcile", {"applied_ticket": "x"}),
                       ("manifest", {"manifest_token": "x"})):
        r = env.client.post(f"/v2/workbook/import/{path}", follow_redirects=False,
                            data={"project": project.project_code, "csrf_token": generate_csrf_token(), **data})
        assert r.status_code in (302, 303, 307) and "/library" in r.headers["location"], path
    assert evidence(project) == before


# ── reconciliation gates ──────────────────────────────────────────────────────────────────────────────────────
def applied_state(env, project):
    _, applied = full_apply(env, project, key="base_case")
    return hidden(applied, "applied_ticket")


def test_reconcile_without_run_attestation_or_current_state_is_not_comparable(env):
    project = env.create("solar")
    ticket = applied_state(env, project)
    none = recon_detail(reconcile(env, project, ticket))
    assert none["Summary!B2"]["status"] == "NOT_COMPARABLE" and "RUN_NOT_CURRENT_FOR_APPLIED_INPUTS" in none["Summary!B2"]["reasons"]
    run_model(env, project)
    no_attest = recon_detail(reconcile(env, project, ticket, attested=False))
    assert no_attest["Summary!B2"]["status"] == "NOT_COMPARABLE" and "CONVENTIONS_NOT_ATTESTED" in no_attest["Summary!B2"]["reasons"]
    assert recon_detail(reconcile(env, project, ticket))["Summary!B2"]["status"] in ("PASS", "FAIL")
    # an input edited after the Run makes the committed Run non-current: never compared
    assert save(env, project, "7", field="debt.senior.tenor_years").status_code in (200, 422)
    stale = recon_detail(reconcile(env, project, ticket))
    assert stale["Summary!B2"]["status"] == "NOT_COMPARABLE"
    assert {"RUN_NOT_CURRENT_FOR_APPLIED_INPUTS"} <= set(stale["Summary!B2"]["reasons"])


def test_reconcile_output_depending_on_an_unapplied_scenario_is_not_comparable(env):
    project = env.create("solar")
    _, applied = full_apply(env, project, key="upside")             # the output formula reads the BASE column
    run_model(env, project)
    rows = recon_detail(reconcile(env, project, hidden(applied, "applied_ticket")))
    assert rows["Summary!B2"]["status"] == "NOT_COMPARABLE"
    assert "SOURCE_OUTPUT_DEPENDS_ON_UNMAPPED_OR_UNAPPLIED_INPUTS" in rows["Summary!B2"]["reasons"]
    # ...but reading the Upside column (which WAS applied) is comparable
    project2 = env.create("solar")
    _, applied2 = full_apply(env, project2, key="upside", data=journey_workbook(summary_ref="Inputs!C3"))
    run_model(env, project2)
    assert recon_detail(reconcile(env, project2, hidden(applied2, "applied_ticket")))["Summary!B2"]["status"] in ("PASS", "FAIL")


def test_reconcile_cross_project_run_and_forged_tickets_are_refused(env):
    project = env.create("solar")
    other = env.create("solar")
    ticket = applied_state(env, project)
    run_model(env, project)
    run_model(env, other)
    foreign_run = get_run_history(OWNER, other.project_id)[0].history_id
    bad = reconcile(env, project, ticket, history_id=foreign_run)
    assert bad.status_code == 422 and "RECONCILE_RUN_NOT_IN_THIS_PROJECT" in bad.text
    forged = reconcile(env, project, ticket[:-3] + "xyz")
    assert forged.status_code == 422 and "IMPORT_REVIEW_EXPIRED_OR_TAMPERED" in forged.text
    cross = reconcile(env, other, ticket)
    assert cross.status_code == 422 and "IMPORT_REVIEW_OWNER_MISMATCH" in cross.text
    preview_kind = reconcile(env, project, slice_ticket(assess(env, project, journey_workbook()), "upside"))
    assert preview_kind.status_code == 422                       # a different ticket kind is not applied evidence
    bad_tol = reconcile(env, project, ticket, abs_tol="-1")
    assert bad_tol.status_code == 422 and "RECONCILE_TOLERANCE_INVALID" in bad_tol.text
    assert reconcile(env, project, ticket, abs_tol="x").status_code == 422


def test_reconcile_never_starts_a_run_or_writes(env):
    project = env.create("solar")
    ticket = applied_state(env, project)
    before = evidence(project)
    response = reconcile(env, project, ticket)
    assert response.status_code == 200 and evidence(project) == before


def test_reconcile_uses_a_declared_tolerance_and_reports_actual_difference(env):
    project = env.create("solar")
    ticket = applied_state(env, project)
    run_model(env, project)
    strict = recon_detail(reconcile(env, project, ticket))["Summary!B2"]
    assert strict["status"] == "FAIL"
    loose = recon_detail(reconcile(env, project, ticket, abs_tol="1000000"))["Summary!B2"]
    assert loose["status"] == "PASS" and loose["cells"][4].split()[0] == strict["cells"][4].split()[0]   # same residual, now inside the declared tolerance
    assert "allowed 1000000" in loose["cells"][4] and "allowed 0" in strict["cells"][4]


# ── portfolio manifest ────────────────────────────────────────────────────────────────────────────────────────
def test_manifest_is_signed_value_free_bounded_and_owner_bound(env):
    project = env.create("solar")
    data = journey_workbook()
    first = assess(env, project, data)
    token = hidden(first, "manifest_token")
    assert token
    second = assess(env, project, F.save(F.selector_only_workbook()), manifest=token)
    token2 = hidden(second, "manifest_token")
    page = env.client.post("/v2/workbook/import/manifest", data={"project": project.project_code, "csrf_token": generate_csrf_token(),
                                                                   "manifest_token": token2})
    assert page.status_code == 200 and page.text.count("data-sha=") == 2
    dl = env.client.post("/v2/workbook/import/manifest", data={"project": project.project_code, "csrf_token": generate_csrf_token(),
                                                                 "manifest_token": token2, "download": "json"})
    assert dl.status_code == 200 and dl.headers["content-type"].startswith("application/json")
    body = dl.text
    for secret in ("1200000", "5,25", "=CHOOSE", "Inputs!B3", "slice_ticket"):
        assert secret not in body, secret                           # identities, counts and statuses only
    assert '"retention"' in body and "workbook_sha256" in body
    # same workbook twice -> still one entry
    again = assess(env, project, data, manifest=token2)
    assert again.text.count("data-sha=") == 2
    # tampering and foreign tokens
    forged = env.client.post("/v2/workbook/import/manifest", data={"project": project.project_code, "csrf_token": generate_csrf_token(),
                                                                     "manifest_token": token2[:-3] + "xyz"})
    assert forged.status_code == 422 and "MANIFEST_EXPIRED_OR_TAMPERED" in forged.text
    env.client.cookies.set(COOKIE_NAME, create_session_token(user_id="import-intruder", username="admin"))
    other_owner = env.client.post("/v2/workbook/import/manifest", follow_redirects=False, data={
        "project": project.project_code, "csrf_token": generate_csrf_token(), "manifest_token": token2})
    assert other_owner.status_code in (302, 303, 307)
    env.client.cookies.set(COOKIE_NAME, create_session_token(user_id=OWNER, username="admin"))
    # a bad token never blocks an assessment: it is reported and a fresh manifest starts
    recovered = assess(env, project, journey_workbook(), manifest="garbage")
    assert recovered.status_code == 200 and "MANIFEST_EXPIRED_OR_TAMPERED" in recovered.text and recovered.text.count("data-sha=") == 1


def test_manifest_entry_limit_is_enforced():
    from app.model_import.migration_portfolio import MAX_ENTRIES, ManifestError, empty_manifest, seal_manifest, unseal_manifest, upsert
    manifest = empty_manifest("u")
    for i in range(MAX_ENTRIES):
        manifest = upsert(manifest, {"workbook_sha256": f"{i:064x}"})
    with pytest.raises(ManifestError) as exc:
        upsert(manifest, {"workbook_sha256": "f" * 64})
    assert exc.value.code == "MANIFEST_ENTRY_LIMIT_EXCEEDED"
    oversized = {**manifest, "entries": manifest["entries"] + [{"workbook_sha256": "e" * 64}]}
    with pytest.raises(ManifestError):
        seal_manifest(oversized)
    token = seal_manifest(manifest)
    with pytest.raises(ManifestError):
        unseal_manifest(token, owner="someone-else")
    forged = URLSafeTimedSerializer("wrong-key", salt="finco-model-import-v1-manifest").dumps(manifest)
    with pytest.raises(ManifestError):
        unseal_manifest(forged, owner="u")
    wrong_salt = URLSafeTimedSerializer(SECRET_KEY, salt="finco-model-import-v1-preview").dumps(manifest)
    with pytest.raises(ManifestError):
        unseal_manifest(wrong_salt, owner="u")


def test_manifest_status_progression_is_server_observed(env):
    project = env.create("solar")
    assessed, applied = full_apply(env, project, key="base_case")
    token = hidden(applied, "manifest_token")
    page = env.client.post("/v2/workbook/import/manifest", data={"project": project.project_code, "csrf_token": generate_csrf_token(),
                                                                   "manifest_token": token})
    assert "scalars applied" in page.text.lower()
    run_model(env, project)
    reconciled = reconcile(env, project, hidden(applied, "applied_ticket"), manifest=token)
    assert 'data-testid="manifest-table"' in reconciled.text and "comparable of" in reconciled.text
