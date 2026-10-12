"""F3.7 instrument-level Sources & Uses: real persisted Runs, fixtures for tamper cases, isolation."""
from __future__ import annotations

import copy
import json
import re
from types import SimpleNamespace

import pytest

from app.v2.financing_instrument_reconciliation import build_instrument_reconciliation
from app.v2.financing_sources_uses_projection import FinancingEvidenceInvalid, build_sources_uses_projection
from app.workbook import junior_debt_config as junior_config, multisenior_config as config
from app.workbook.runtime_projection import thaw_runtime_payload
from tests.test_financing_f3_junior_workspace import state as junior_state, working_case
from tests.test_model_decision_workspace_v2 import env  # noqa: F401
from tests.test_model_financing_f2 import run, save
from tests.test_model_financing_f3_workspace import collection_for_inputs, state


def _page(env, record, **params):
    from app.v2.financing_sources_uses_router import router
    if not any(getattr(r, "path", "") == "/v2/financing/sources-uses" for r in env.client.app.routes):
        env.client.app.include_router(router, prefix="/v2")
    return env.client.get("/v2/financing/sources-uses", params={"project": record.project_code, **params})


def _two_senior_run(env, monkeypatch, kind):
    from app.persistence.workspace_repository import get_workspace_state
    from app.workbook.input_set import ProjectInputSet
    monkeypatch.setattr(config, "ACTIVATION_ENABLED", True)
    record = env.create(kind)
    ws = get_workspace_state("decision-user", record.project_id)
    pi = ProjectInputSet.from_snapshot(ws.draft_snapshot).to_projectinputs()
    assert "field-error-banner" not in save(env, record, state(active=True, collection=collection_for_inputs(pi)),
                                            field=config.FIELD_ID).text
    committed, rr = run(env, record)
    return record, committed, rr


def _junior_run(env, monkeypatch, kind="wind"):
    from app.persistence.workspace_repository import get_workspace_state
    monkeypatch.setattr(config, "ACTIVATION_ENABLED", True)
    monkeypatch.setattr(junior_config, "ACTIVATION_ENABLED", True)     # controlled synthetic fixture only
    record = env.create(kind)
    ws = get_workspace_state("decision-user", record.project_id)
    assert "field-error-banner" not in save(env, record, junior_state(working_case(ws)), field=config.FIELD_ID).text
    committed, rr = run(env, record)
    return record, committed, rr


def _evidence(rr):
    return thaw_runtime_payload(rr.runtime_summary["financing_evidence"])


def _view(evidence):
    rr = SimpleNamespace(runtime_summary={"financing_evidence": evidence}, debt_schedule=None, sponsor_schedule=None)
    return build_sources_uses_projection(runtime_result=rr, freshness="CURRENT")["instrument_view"]


@pytest.mark.parametrize("kind", ["solar", "wind"])
def test_two_senior_instruments_reconcile_to_canonical_su_and_ui(env, monkeypatch, kind):
    record, committed, rr = _two_senior_run(env, monkeypatch, kind)
    ev = _evidence(rr)
    su = ev["sources_uses"]
    iv = _view(ev)
    assert iv["available"] and iv["mode"] == "TWO_SENIOR" and iv["status"] == "RECONCILED"
    assert [f["role"] for f in iv["instruments"]] == ["Senior", "Senior"]
    assert sum(f["drawn"].value for f in iv["instruments"]) == pytest.approx(su["senior_debt_keur"], abs=1e-6)
    assert sum(f["idc"].value for f in iv["instruments"]) == pytest.approx(su["capitalized_idc_keur"], abs=1e-6)
    assert sum(f["upfront"].value for f in iv["instruments"]) == pytest.approx(su["structuring_fee_keur"], abs=1e-6)
    assert sum(f["commitment_fee"].value for f in iv["instruments"]) == pytest.approx(su["commitment_fee_keur"], abs=1e-6)
    assert su["total_sources_keur"] - su["total_uses_keur"] == pytest.approx(su["difference_keur"], abs=1e-6)
    assert all(r["ok"] for r in iv["period_checks"])
    page = _page(env, record)
    assert page.status_code == 200
    for ident in (f["instrument_id"] for f in iv["instruments"]):
        assert f'data-instrument="{ident}"' in page.text
    assert 'data-testid="su-instruments"' in page.text and "RECONCILED" in page.text
    assert "Open Capital Stack Workspace" in page.text


def test_junior_evidence_reconciles_without_double_counting_idc(env, monkeypatch):
    record, committed, rr = _junior_run(env, monkeypatch)
    ev = _evidence(rr)
    su = ev["sources_uses"]
    iv = _view(ev)
    assert iv["mode"] == "JUNIOR" and iv["status"] == "RECONCILED"
    senior = next(f for f in iv["instruments"] if f["role"] == "Senior")
    junior = next(f for f in iv["instruments"] if f["role"] == "Junior")
    assert senior["drawn"].value == pytest.approx(su["senior_debt_keur"], abs=1e-6)
    assert junior["drawn"].value == pytest.approx(su["junior_or_other_keur"], abs=1e-6)
    # Each cost has exactly one home: Senior IDC -> capitalised IDC, Junior IDC -> other financing costs.
    assert senior["idc"].value == pytest.approx(su["capitalized_idc_keur"], abs=1e-6)
    assert junior["idc"].value == pytest.approx(su["other_financing_costs_keur"], abs=1e-6)
    assert su["capitalized_idc_keur"] + su["other_financing_costs_keur"] == pytest.approx(
        senior["idc"].value + junior["idc"].value, abs=1e-6)
    page = _page(env, record)
    assert "Junior" in page.text and "RECONCILED" in page.text
    assert junior_config.ACTIVATION_ENABLED is True            # only inside this controlled fixture
    monkeypatch.undo()
    assert junior_config.ACTIVATION_ENABLED is False


def test_single_senior_and_legacy_runs_stay_truthful_no_instrument_split(env):
    record = env.create("solar")
    committed, rr = run(env, record)
    ev = _evidence(rr)
    assert "facility_schedules" not in ev and "junior_facility" not in ev
    iv = _view(ev)
    assert not iv["available"] and iv["status"] == "UNAVAILABLE" and iv["instruments"] == ()
    page = _page(env, record)
    assert 'data-testid="su-instruments-unavailable"' in page.text and "not proof of funding drawn" in page.text
    legacy = build_sources_uses_projection(
        runtime_result=SimpleNamespace(runtime_summary={"senior_debt_keur": 1.0}, debt_schedule=None, sponsor_schedule=None),
        freshness="STALE", run_kind="HISTORICAL_RUN")
    assert legacy["instrument_view"] is None and legacy["legacy_financing"]


def test_tampered_instrument_numbers_differ_and_are_never_plugged(env, monkeypatch):
    _, _, rr = _two_senior_run(env, monkeypatch, "solar")
    ev = _evidence(rr)
    tampered = copy.deepcopy(ev)
    tampered["facility_schedules"][0]["construction_idc_keur"][0] += 5.0
    iv = _view(tampered)
    assert iv["status"] == "DIFFERS"
    bad = next(c for c in iv["checks"] if c["label"].startswith("Senior IDC"))
    assert bad["status"] == "DIFFERS" and bad["difference"].value == pytest.approx(5.0)
    drawn = copy.deepcopy(ev)
    drawn["facility_schedules"][1]["construction_draws_keur"][0] -= 1.0
    assert _view(drawn)["status"] == "DIFFERS"
    assert any(not r["ok"] for r in _view(drawn)["period_checks"])


@pytest.mark.parametrize("mutate", [
    lambda e: e["facility_schedules"][0].__setitem__("construction_draws_keur", [float("nan")] * 3),
    lambda e: e["facility_schedules"][0].__setitem__("construction_idc_keur", [0.0]),               # wrong length
    lambda e: e["facility_schedules"][0].__setitem__("construction_draws_keur", [10 ** 9, 0.0, 0.0]),  # overdrawn
    lambda e: e["facility_schedules"][1].__setitem__("instrument_id", e["facility_schedules"][0]["instrument_id"]),
    lambda e: e["facility_schedules"][0].__setitem__("commitment_keur", "780"),
    lambda e: e["facility_schedules"][0].pop("construction_commitment_fees_keur"),
])
def test_malformed_instrument_evidence_is_rejected(env, monkeypatch, mutate):
    _, _, rr = _two_senior_run(env, monkeypatch, "solar")
    ev = copy.deepcopy(_evidence(rr))
    mutate(ev)
    with pytest.raises(FinancingEvidenceInvalid):
        _view(ev)


def test_incomplete_junior_evidence_is_rejected(env, monkeypatch):
    _, _, rr = _junior_run(env, monkeypatch)
    ev = copy.deepcopy(_evidence(rr))
    del ev["junior_facility"]
    with pytest.raises(FinancingEvidenceInvalid):
        _view(ev)


def test_current_stale_and_history_are_separate_and_history_is_immutable(env, monkeypatch):
    from app.persistence.run_history_repository import get_run_history
    from app.persistence.workspace_repository import get_workspace_state
    record, committed, rr = _two_senior_run(env, monkeypatch, "solar")
    entries = get_run_history("decision-user", record.project_id, limit=1)
    section = lambda t: t.split('data-testid="su-instruments"')[1].split('data-testid="su-bankability"')[0]  # noqa: E731
    cur = _page(env, record)
    assert 'data-testid="su-freshness">CURRENT' in cur.text
    hist_before = section(_page(env, record, history_id=entries[0].history_id).text)
    newer = json.loads(state(active=True, collection=collection_for_inputs(
        __import__("app.workbook.input_set", fromlist=["ProjectInputSet"]).ProjectInputSet.from_snapshot(
            get_workspace_state("decision-user", record.project_id).draft_snapshot).to_projectinputs())))
    newer["scopes"]["base"]["proposal"]["instruments"][0]["interest"]["fixed_rate"] = .07
    newer["scopes"]["base"]["activation"]["proposal_digest"] = "BIND_ON_SAVE"
    save(env, record, json.dumps(newer), field=config.FIELD_ID)
    stale = _page(env, record)
    assert 'data-testid="su-freshness">STALE' in stale.text and "prior Run" in stale.text
    table = lambda t: section(t).split('data-testid="su-instrument-table"')[1]  # noqa: E731
    assert table(stale.text) == table(cur.text)                          # Last Run evidence itself is unchanged
    run(env, record)
    hist_after = section(_page(env, record, history_id=entries[0].history_id).text)
    assert hist_after == hist_before and "immutable historical Run" in hist_after
    assert 'data-testid="su-freshness">HISTORICAL' in _page(env, record, history_id=entries[0].history_id).text


def test_other_user_and_other_project_cannot_read_instrument_evidence(env, monkeypatch):
    from app.auth import COOKIE_NAME, create_session_token
    record, _, _ = _two_senior_run(env, monkeypatch, "solar")
    other = env.create("wind")
    own_other = _page(env, other)
    assert own_other.status_code == 200 and "senior-a" not in own_other.text and "senior-b" not in own_other.text
    env.client.cookies.set(COOKIE_NAME, create_session_token(user_id="f37-intruder", username="admin"))
    denied = _page(env, record)
    assert denied.status_code == 404 and "senior-a" not in denied.text


def test_page_is_read_only_no_balance_action_and_no_engine(env, monkeypatch):
    from app.services import production_financial_authority
    record, _, _ = _two_senior_run(env, monkeypatch, "solar")
    monkeypatch.setattr(production_financial_authority, "run_clean_production",
                        lambda *a, **k: pytest.fail("S&U page executed the engine"))
    page = _page(env, record).text
    assert "Apply not enabled" in page
    assert not re.search(r"<form", page.split('data-testid="su-instruments"')[1].split("</section>")[0], re.I)


def test_module_imports_no_engine_core_persistence_or_writer():
    import ast, pathlib
    import app.v2.financing_instrument_reconciliation as module
    tree = ast.parse(pathlib.Path(module.__file__).read_text(encoding="utf-8"))
    names = {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module}
    assert not [m for m in names if m.startswith(("financial_engine", "finco_core", "app.persistence", "app.workbook"))]


# ── Correction A: strict facility authority and Junior IDC completeness ───────────────────────────
def _redigest(cash):
    import hashlib
    payload = (cash["instrument_id"], cash["collection_digest"], tuple(float(v) for v in cash["capitalized_cash_by_period_keur"]),
               cash["book_life_years"])
    cash["evidence_digest"] = hashlib.sha256(json.dumps(payload, separators=(",", ":")).encode()).hexdigest()


@pytest.fixture()
def two_senior_evidence(env, monkeypatch):
    return copy.deepcopy(_evidence(_two_senior_run(env, monkeypatch, "solar")[2]))


@pytest.fixture()
def junior_evidence(env, monkeypatch):
    return copy.deepcopy(_evidence(_junior_run(env, monkeypatch)[2]))


def test_authorities_match_the_canonical_serializer_strings(two_senior_evidence, junior_evidence):
    assert two_senior_evidence["facility_authority"] == "F3_TWO_SENIOR_EXPLICIT_COMMITMENTS_V1"
    assert junior_evidence["facility_authority"] == "F3_SINGLE_SENIOR_JUNIOR_EXPLICIT_V1"
    assert _view(two_senior_evidence)["status"] == "RECONCILED" and _view(junior_evidence)["status"] == "RECONCILED"


@pytest.mark.parametrize("authority", ["F3_FUTURE_V9", "", "f3_two_senior_explicit_commitments_v1", 7, ["x"]])
def test_unknown_facility_authority_is_rejected(two_senior_evidence, authority):
    two_senior_evidence["facility_authority"] = authority
    with pytest.raises(FinancingEvidenceInvalid, match="AUTHORITY_UNKNOWN"):
        _view(two_senior_evidence)


@pytest.mark.parametrize("fixture", ["two_senior_evidence", "junior_evidence"])
def test_missing_authority_is_rejected_for_an_instrument_level_claim(request, fixture):
    evidence = request.getfixturevalue(fixture)
    del evidence["facility_authority"]
    with pytest.raises(FinancingEvidenceInvalid, match="AUTHORITY_MISSING"):
        _view(evidence)


def test_exactly_two_senior_schedules_are_required(two_senior_evidence):
    one = copy.deepcopy(two_senior_evidence)
    one["facility_schedules"] = one["facility_schedules"][:1]
    three = copy.deepcopy(two_senior_evidence)
    extra = copy.deepcopy(three["facility_schedules"][0])
    extra["instrument_id"] = "senior-c"
    three["facility_schedules"].append(extra)
    for bad in (one, three):
        with pytest.raises(FinancingEvidenceInvalid, match="EXACTLY_TWO"):
            _view(bad)


def test_mixed_serializer_shapes_are_rejected(two_senior_evidence, junior_evidence):
    mixed_two = copy.deepcopy(two_senior_evidence)
    mixed_two["junior_facility"] = copy.deepcopy(junior_evidence["junior_facility"])
    with pytest.raises(FinancingEvidenceInvalid, match="MIXED"):
        _view(mixed_two)
    mixed_junior = copy.deepcopy(junior_evidence)
    mixed_junior["facility_schedules"] = copy.deepcopy(two_senior_evidence["facility_schedules"])
    with pytest.raises(FinancingEvidenceInvalid, match="MIXED"):
        _view(mixed_junior)
    # The authority string must agree with the shape.
    wrong = copy.deepcopy(junior_evidence)
    wrong["facility_authority"] = "F3_TWO_SENIOR_EXPLICIT_COMMITMENTS_V1"
    with pytest.raises(FinancingEvidenceInvalid):
        _view(wrong)


def test_junior_requires_one_senior_and_one_junior_block(junior_evidence):
    for missing in ("senior_facility", "junior_facility", "junior_cash_idc", "junior_policy_digest"):
        broken = copy.deepcopy(junior_evidence)
        del broken[missing]
        with pytest.raises(FinancingEvidenceInvalid, match="INCOMPLETE"):
            _view(broken)


def test_missing_junior_idc_ledger_is_rejected_never_reconciled(junior_evidence):
    broken = copy.deepcopy(junior_evidence)
    del broken["junior_cash_idc"]["capitalized_cash_by_period_keur"]
    with pytest.raises(FinancingEvidenceInvalid, match="CASH_IDC_LEDGER_INVALID"):
        _view(broken)
    broken = copy.deepcopy(junior_evidence)
    broken["junior_cash_idc"] = None
    with pytest.raises(FinancingEvidenceInvalid, match="CASH_IDC_MISSING"):
        _view(broken)


@pytest.mark.parametrize("ledger", [lambda v: v[:-1], lambda v: v + [0.0], lambda v: [float("nan")] + v[1:],
                                    lambda v: [-1.0] + v[1:], lambda v: ["1"] + v[1:], lambda v: [True] + v[1:]])
def test_wrong_length_nonfinite_or_malformed_junior_idc_ledger_is_rejected(junior_evidence, ledger):
    junior_evidence["junior_cash_idc"]["capitalized_cash_by_period_keur"] = ledger(
        list(junior_evidence["junior_cash_idc"]["capitalized_cash_by_period_keur"]))
    with pytest.raises(FinancingEvidenceInvalid, match="CASH_IDC_LEDGER_INVALID"):
        _view(junior_evidence)


def test_same_total_altered_period_junior_idc_is_rejected_even_with_a_recomputed_digest(junior_evidence):
    cash = junior_evidence["junior_cash_idc"]
    values = list(cash["capitalized_cash_by_period_keur"])
    values[0], values[1] = values[1], values[0]                    # identical total, different periods
    assert sum(values) == pytest.approx(sum(cash["capitalized_cash_by_period_keur"]))
    cash["capitalized_cash_by_period_keur"] = values
    with pytest.raises(FinancingEvidenceInvalid, match="TAMPERED"):                  # stale self-digest
        _view(copy.deepcopy(junior_evidence))
    _redigest(cash)
    with pytest.raises(FinancingEvidenceInvalid, match="PERIOD_MISMATCH"):           # facility schedule disagrees
        _view(junior_evidence)


def test_junior_identity_and_collection_binding_mismatches_are_rejected(junior_evidence):
    wrong_instrument = copy.deepcopy(junior_evidence)
    wrong_instrument["junior_cash_idc"]["instrument_id"] = wrong_instrument["senior_facility"]["instrument_id"]
    _redigest(wrong_instrument["junior_cash_idc"])
    with pytest.raises(FinancingEvidenceInvalid, match="INSTRUMENT_MISMATCH"):
        _view(wrong_instrument)
    wrong_collection = copy.deepcopy(junior_evidence)
    wrong_collection["junior_cash_idc"]["collection_digest"] = "0" * 64
    _redigest(wrong_collection["junior_cash_idc"])
    with pytest.raises(FinancingEvidenceInvalid, match="COLLECTION_MISMATCH"):
        _view(wrong_collection)
    swapped = copy.deepcopy(junior_evidence)
    swapped["collection_digest"] = "f" * 64                          # run-level digest no longer matches the ledger
    with pytest.raises(FinancingEvidenceInvalid, match="COLLECTION_MISMATCH"):
        _view(swapped)


@pytest.mark.parametrize("fixture,path", [
    ("two_senior_evidence", ("collection_digest",)),
    ("junior_evidence", ("collection_digest",)),
    ("junior_evidence", ("junior_policy_digest",)),
    ("junior_evidence", ("junior_cash_idc", "collection_digest")),
    ("junior_evidence", ("junior_cash_idc", "evidence_digest")),
])
@pytest.mark.parametrize("bad", ["missing", "short", "not-hex", 5])
def test_missing_or_malformed_required_digests_are_rejected(request, fixture, path, bad):
    evidence = request.getfixturevalue(fixture)
    holder = evidence
    for key in path[:-1]:
        holder = holder[key]
    if bad == "missing":
        del holder[path[-1]]
    else:
        holder[path[-1]] = {"short": "abc", "not-hex": "z" * 64, 5: 5}[bad]
    # A required key that is absent is refused as an incomplete block; a present-but-bad digest as an invalid digest.
    with pytest.raises(FinancingEvidenceInvalid, match="DIGEST_INVALID|INCOMPLETE"):
        _view(evidence)


def test_junior_idc_and_senior_idc_remain_separate_categories_and_a_difference_stays_visible(junior_evidence):
    view = _view(junior_evidence)
    labels = {c["label"]: c for c in view["checks"]}
    assert labels["Senior IDC (capitalised once)"]["status"] == labels["Junior IDC (other financing costs)"]["status"] == "RECONCILED"
    assert labels["Junior cash IDC ledger"]["status"] == "RECONCILED"
    # An aggregate that no longer matches the instrument ledgers is DIFFERS, not repaired or ignored.
    junior_evidence["sources_uses"]["other_financing_costs_keur"] += 3.0
    junior_evidence["sources_uses"]["total_uses_keur"] += 3.0
    junior_evidence["sources_uses"]["difference_keur"] -= 3.0
    junior_evidence["construction_funding"]["total_audit_uses_keur"] += 3.0
    junior_evidence["construction_funding"]["total_audit_residual_keur"] -= 3.0
    rr = SimpleNamespace(runtime_summary={"financing_evidence": junior_evidence}, debt_schedule=None, sponsor_schedule=None)
    try:
        differing = build_sources_uses_projection(runtime_result=rr, freshness="CURRENT")["instrument_view"]
    except FinancingEvidenceInvalid:
        return                          # the F1 aggregate audit may already refuse the tampered aggregate: also never RECONCILED
    assert differing["status"] == "DIFFERS"


def test_aggregate_only_and_legacy_runs_stay_unavailable(env):
    record = env.create("wind")
    run(env, record)
    from app.persistence.workspace_repository import get_workspace_state
    from app.workbook.service import WorkbookService
    rr = WorkbookService.get_runtime_result(get_workspace_state("decision-user", record.project_id))
    evidence = _evidence(rr)
    assert "facility_authority" not in evidence
    assert _view(evidence)["status"] == "UNAVAILABLE"
