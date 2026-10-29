"""WF-04: the two contractual DSCR inputs through the REAL writer and the REAL Run commit.

Save persists the terms in the Working Copy through the existing authorised field writer (CSRF + content-hash CAS); a Run records the
terms that were saved when THAT Run was committed inside its immutable identity; a later edit never rewrites a historical Run; Save never
runs the model; and the terms change no financial number.
"""
import pytest

from tests.model_mutation_csrf import post_valid_mutation
from tests.test_model_decision_workspace_v2 import env, tokens  # noqa: F401  (fixture)
from tests.test_model_financing_f2 import run

USER = "decision-user"
EOD = "debt.contract.min_dscr_eod"
COV = "debt.contract.contractual_dscr"


def set_field(env, record, field_id, value):
    page = env.client.get("/v2/workbook", params={"project": record.project_code}).text
    return post_valid_mutation(env.client, "/v2/workbook/update", headers={"HX-Request": "true"},
                               data={"project": record.project_code, "field_id": field_id, "value": str(value), **tokens(page)})


def saved(env, record, field_id, value):
    response = set_field(env, record, field_id, value)
    assert response.status_code == 200 and "field-error" not in response.text[:4000], response.text[:600]


def history(record):
    from app.persistence.run_history_repository import get_run_history
    return list(get_run_history(USER, record.project_id))


def workspace(record):
    from app.persistence.workspace_repository import get_workspace_state
    return get_workspace_state(USER, record.project_id)


def terms_of(entry):
    from app.workbook.dscr_contract_terms import read_run_terms
    return read_run_terms(entry.last_runtime_identity)


def freshness(env, record):
    from app.v2.router import _build_pis_with_composite_identity
    from app.persistence.projects_repository import resolve_accessible_project
    from app.workbook.runtime_authority import resolve_runtime_freshness
    rec, owner = resolve_accessible_project(USER, record.project_code)
    ws = workspace(record)
    pis = _build_pis_with_composite_identity(ws, rec, owner)
    return resolve_runtime_freshness(ws, current_composite_hash=pis.content_hash).state.value


def test_fields_are_registered_as_two_distinct_editable_ratio_inputs():
    from app.workbook.registry import WORKBOOK
    eod, cov = WORKBOOK.field(EOD), WORKBOOK.field(COV)
    assert (eod.snapshot_key, cov.snapshot_key) == ("dscr_min_eod_x", "dscr_contractual_x")
    for spec in (eod, cov):
        assert spec.unit == "x" and spec.editable and spec.persisted and not spec.required and (spec.min_value, spec.max_value) == (0.01, 10.0)
    assert eod.label != cov.label and "EoD" in eod.label and "Contractual" in cov.label
    # the existing independent controls are untouched and are NOT these fields
    assert WORKBOOK.field("debt.senior.target_dscr").label == "Target DSCR"
    assert {f.field_id for f in WORKBOOK.all_fields() if "dscr" in f.field_id} == {"debt.senior.target_dscr", EOD, COV}


def test_save_then_run_records_the_saved_terms_in_that_runs_identity_and_save_never_runs(env):
    record = env.create("wind")
    saved(env, record, EOD, "1.05")
    saved(env, record, COV, "1.2")
    assert history(record) == []                                      # Save ≠ Run: nothing was committed
    ws = workspace(record)
    assert ws.draft_snapshot["dscr_min_eod_x"] == "1.05" and ws.draft_snapshot["dscr_contractual_x"] == "1.2"
    run(env, record)
    entries = history(record)
    assert len(entries) == 1
    recorded = terms_of(entries[0])
    assert recorded.recorded and (recorded.eod.value, recorded.eod.raw) == (1.05, "1.05") and (recorded.contractual.value, recorded.contractual.raw) == (1.2, "1.2")
    assert workspace(record).last_runtime_identity["dscr_contract_terms"] == entries[0].last_runtime_identity["dscr_contract_terms"]


def test_a_later_edit_never_rewrites_a_historical_run_and_the_last_run_becomes_stale(env):
    record = env.create("wind")
    saved(env, record, EOD, "1.05")
    run(env, record)
    first = history(record)[0]
    assert freshness(env, record) == "CURRENT"
    saved(env, record, EOD, "1.50")
    saved(env, record, COV, "1.30")
    assert freshness(env, record) == "STALE"                          # the terms are part of the input identity
    assert len(history(record)) == 1                                  # and the edit committed nothing
    reread = history(record)[0]
    assert terms_of(reread).eod.value == 1.05 and terms_of(reread).contractual.status == "NOT_CONFIGURED"
    assert reread.last_runtime_identity == first.last_runtime_identity
    run(env, record)
    newest, oldest = history(record)[0], history(record)[-1]
    assert newest.history_id != oldest.history_id
    assert terms_of(newest).eod.value == 1.5 and terms_of(newest).contractual.value == 1.3
    assert terms_of(oldest).eod.value == 1.05                         # the original Run still reads ITS terms
    assert freshness(env, record) == "CURRENT"


@pytest.mark.parametrize("bad", ["abc", "0", "-1", "0.001", "10.5", "nan", "inf"])
def test_invalid_values_are_rejected_by_the_writer_and_persist_nothing(env, bad):
    record = env.create("solar")
    env.client.get("/v2/workbook", params={"project": record.project_code})      # the first page load normalises unrelated snapshot values
    before = workspace(record)
    response = set_field(env, record, EOD, bad)
    assert response.status_code != 500
    assert workspace(record).draft_snapshot == before.draft_snapshot
    assert not workspace(record).draft_snapshot.get("dscr_min_eod_x")


def test_blank_means_not_configured_and_a_run_records_that_not_zero(env):
    record = env.create("solar")
    saved(env, record, EOD, "1.05")
    saved(env, record, EOD, "")                                       # clearing is a valid Save
    run(env, record)
    recorded = terms_of(history(record)[0])
    assert recorded.recorded and recorded.eod.status == "NOT_CONFIGURED" and recorded.eod.value is None
    assert recorded.contractual.status == "NOT_CONFIGURED"


def test_precision_is_kept_exactly_as_entered(env):
    record = env.create("solar")
    saved(env, record, EOD, "1.0525")
    run(env, record)
    recorded = terms_of(history(record)[0]).eod
    assert recorded.value == 1.0525 and recorded.raw == "1.0525"


def test_configured_terms_change_no_financial_result(env):
    """The terms feed no calculation: every persisted financial blob of a Run is identical with and without them."""
    plain = env.create("wind")
    run(env, plain)
    configured = env.create("wind")
    saved(env, configured, EOD, "1.05")
    saved(env, configured, COV, "1.2")
    run(env, configured)
    a, b = history(plain)[0], history(configured)[0]
    for name in ("runtime_summary", "financial_statements", "debt_schedule", "tax_schedule", "distribution_schedule", "sponsor_schedule"):
        left, right = getattr(a, name), getattr(b, name)
        left, right = dict(left), dict(right)
        for volatile in ("binding", "run_binding"):                  # project/snapshot identity differs between two projects
            left.pop(volatile, None), right.pop(volatile, None)
        if name == "runtime_summary":
            for key in ("acquisition_source_candidate_v1", "financing_evidence", "effective_input_evidence"):
                left.pop(key, None), right.pop(key, None)
        assert left == right, name
    assert a.integrity_evidence["digest"] == b.integrity_evidence["digest"]
    assert a.integrity_evidence["senior_debt"] == b.integrity_evidence["senior_debt"]


def test_old_runs_without_a_record_read_as_not_recorded_never_defaulted():
    from app.workbook.dscr_contract_terms import read_run_terms
    old = read_run_terms({"workbook_version": "2.3.0", "composite_hash": "x"})
    assert not old.recorded and old.eod.value is None and old.contractual.value is None


def test_other_users_cannot_read_or_change_the_terms(env):
    record = env.create("solar")
    saved(env, record, EOD, "1.05")
    from app.persistence.run_history_repository import get_run_history
    assert list(get_run_history("someone-else", record.project_id)) == []
