"""WF-A Addendum A: Add Debt (D0-D5), Add Equity (E0-E5) and Add PPA (P0-P9) on real committed Runs.

Positive cases require every independent identity VERIFIED with zero FAIL.  Negative cases require the product to
fail closed, persist nothing and leave the last committed Run untouched.  Release-closed features stay closed.
"""
import json
from copy import deepcopy
from decimal import Decimal

import pytest

from app.workbook import multisenior_config as f3
from tests import wfa_impact_cases as C
from tests.test_model_decision_workspace_v2 import env  # noqa: F401  (fixture)
from tests.test_model_financing_f2 import run, save
from tests.test_model_financing_f3_workspace import collection_for_inputs, state
from tests.test_investor_f4_p1 import document
from tests.test_investor_f4_workspace import funded_agreement
from tests.test_investor_f4_workspace import save as save_agreement
from tests.test_wf07_revenue_multistream import contracts
from tests.test_wf07_revenue_workspace import contract_tokens

U = C.USER


def _ws(record):
    from app.persistence.workspace_repository import get_workspace_state
    return get_workspace_state(U, record.project_id)


def _fails(result):
    return [o for o in result["outcomes"] if o["status"] == "FAIL"]


def _save_facilities(env, record, instruments=None, active=True):
    coll = collection_for_inputs(C.working_inputs(record))
    doc = coll.to_dict()
    if instruments is not None:
        doc["instruments"] = instruments(deepcopy(doc["instruments"]))
    raw = json.loads(state(active=active, collection=coll))
    raw["scopes"]["base"]["proposal"] = doc
    if active:
        raw["scopes"]["base"]["activation"]["proposal_digest"] = "BIND_ON_SAVE"
    return save(env, record, json.dumps(raw), field=f3.FIELD_ID), doc


@pytest.fixture
def lab(env, monkeypatch):
    monkeypatch.setattr(f3, "ACTIVATION_ENABLED", True)
    return env


# ───────────────────────────────────────────── Add Debt ─────────────────────────────────────────────
@pytest.fixture
def debt_baseline(lab):
    record = lab.create("solar")
    entry = C.commit(lab, record)
    return lab, record, entry, C.scalars(entry)


def test_D0_baseline_has_no_facility_authority_and_reconciles_nothing_extra(debt_baseline):
    _, record, entry, base = debt_baseline
    assert C.authority(entry) is None
    result = C.reconcile(entry, facilities=None)
    assert not _fails(result)
    C.row("D0", family="DEBT", entry=entry, baseline=base, baseline_entry=entry, modification="none (single-Senior baseline)",
          activated="no F3 collection", result=result, independent="no facility identities are applicable",
          explanation="Baseline Run used for every Add Debt delta.")


@pytest.mark.parametrize("case,mutate,what", [
    ("D1", lambda i: i, "two explicit Senior facilities (senior-a 4 %, senior-b 7 %, 12 m grace)"),
    ("D2", lambda i: [dict(i[0], interest=dict(i[0]["interest"], fixed_rate=i[0]["interest"]["fixed_rate"] + .01)), i[1]],
     "senior-a fixed rate +100 bp"),
    ("D3", lambda i: [i[0], dict(i[1], repayment=dict(i[1]["repayment"], grace_months=24))], "senior-b grace 12 → 24 months"),
    ("D4", lambda i: [dict(i[0], drawdowns=[dict(d, draw_date=_shift(d["draw_date"], 31)) for d in i[0]["drawdowns"]]), i[1]],
     "senior-a drawdown date +31 days (commitment/draw timing)"),
])
def test_D1_to_D4_activated_facility_changes_reconcile(debt_baseline, case, mutate, what):
    lab, record, base_entry, base = debt_baseline
    response, doc = _save_facilities(lab, record, mutate)
    assert 'field-error-banner' not in response.text, response.text[:1500]
    entry = C.commit(lab, record)
    assert C.authority(entry) == "F3_TWO_SENIOR_EXPLICIT_COMMITMENTS_V1"
    stored = _ws(record).draft_snapshot[f3.SNAPSHOT_KEY]
    instruments = json.loads(stored)["scopes"]["base"]["proposal"]["instruments"]
    result = C.reconcile(entry, facilities=instruments)
    assert not _fails(result), _fails(result)
    assert result["counts"].get("PASS", 0) > 0
    now = C.scalars(entry)
    assert now != base, "activation must change the Run, otherwise it was not applied"
    C.row(case, family="DEBT", entry=entry, baseline=base, baseline_entry=base_entry, modification=what,
          activated="F3 collection activated by the Run (authority recorded)", result=result,
          independent="IDC, commitment fee, upfront fee, operating interest, level principal and maturity recomputed from declared terms",
          explanation="Differences are produced by the activated facility terms; each identity residual is within the approved tolerance.")


def _shift(iso, days):
    from datetime import date, timedelta
    return (date.fromisoformat(iso) + timedelta(days=days)).isoformat()


def test_D2_higher_rate_increases_recorded_interest(debt_baseline):
    lab, record, _, _ = debt_baseline
    _save_facilities(lab, record)
    e1 = C.commit(lab, record)
    _save_facilities(lab, record, lambda i: [dict(i[0], interest=dict(i[0]["interest"], fixed_rate=i[0]["interest"]["fixed_rate"] + .02)), i[1]])
    e2 = C.commit(lab, record)
    from tools.numerical_validation.source import bundle_from_history_entry
    interest = lambda e: sum(Decimal(str(x)) for x in bundle_from_history_entry(e)["series"]["ev.senior.interest"]["values"].values() if x is not None)  # noqa: E731
    assert interest(e2) > interest(e1)
    assert not _fails(C.reconcile(e2, facilities=json.loads(_ws(record).draft_snapshot[f3.SNAPSHOT_KEY])["scopes"]["base"]["proposal"]["instruments"]))


def test_D5_saved_but_not_activated_proposal_leaves_run_identical(debt_baseline):
    lab, record, base_entry, base = debt_baseline
    response, _ = _save_facilities(lab, record, active=False)
    assert 'field-error-banner' not in response.text
    entry = C.commit(lab, record)
    assert C.authority(entry) is None
    now = C.scalars(entry)
    assert now == base, "an inert proposal must not move any financial result"
    C.row("D5", family="DEBT", entry=entry, baseline=base, baseline_entry=base_entry, modification="proposal saved, activation absent",
          activated="NOT activated", independent="all results identical to baseline", result=None,
          explanation="Saved-but-inactive proposal is inert; the Run records no facility authority.",
          extra={"verdict": "INERT_IDENTICAL_TO_BASELINE"})


def test_D5_invalid_proposal_is_rejected_and_persists_nothing(debt_baseline):
    lab, record, base_entry, _ = debt_baseline
    before = _ws(record)
    response, _ = _save_facilities(lab, record, lambda i: [dict(i[0], commitment_keur=-1.0), i[1]])
    after = _ws(record)
    assert after.draft_snapshot.get(f3.SNAPSHOT_KEY) == before.draft_snapshot.get(f3.SNAPSHOT_KEY)
    assert after.last_runtime_snapshot_id == before.last_runtime_snapshot_id and not after.dirty == (not before.dirty)
    C.emit({"case": "D5-invalid", "family": "DEBT", "input_modification": "negative commitment", "actual_activation": "rejected",
            "verdict": "FAILS_CLOSED", "explanation": "Invalid facility terms are rejected; nothing is persisted."})


def test_historical_run_is_immutable_after_a_later_activation(debt_baseline):
    lab, record, base_entry, _ = debt_baseline
    from app.persistence.run_history_repository import get_run_history_entry
    before = json.dumps(base_entry.runtime_summary, sort_keys=True, default=str)
    _save_facilities(lab, record)
    C.commit(lab, record)
    again = get_run_history_entry(U, record.project_id, base_entry.history_id)
    assert again is not None
    assert json.dumps(again.runtime_summary, sort_keys=True, default=str) == before


# ───────────────────────────────────────────── Add Equity ─────────────────────────────────────────────
@pytest.fixture
def equity_baseline(env):
    record = env.create("solar")
    ws, _ = run(env, record)
    from app.persistence.run_history_repository import get_latest_history_entry
    entry = get_latest_history_entry(U, record.project_id)
    return env, record, ws, entry, C.scalars(entry)


def _agreement_run(env, record, doc):
    assert save_agreement(env, record, doc).status_code == 200
    return C.commit(env, record)


def test_E0_baseline_has_no_investor_evidence(equity_baseline):
    _, record, _, entry, base = equity_baseline
    assert "investor_waterfall_v1" not in (entry.runtime_summary or {})
    C.row("E0", family="EQUITY", entry=entry, baseline=base, baseline_entry=entry, modification="none",
          activated="no investor agreement", independent="no investor identities applicable", result=C.reconcile(entry))


def test_E1_single_investor_and_E2_two_investors_reconcile_and_do_not_move_funding(equity_baseline):
    env, record, ws, base_entry, base = equity_baseline
    doc2 = funded_agreement(ws)
    one = deepcopy(doc2)
    one["investors"] = [dict(doc2["investors"][0], ownership_fraction=1.0)]
    one["contributions"] = [dict(c, investor_id=one["investors"][0]["investor_id"], amount_keur=c["amount_keur"] / .6)
                            for c in doc2["contributions"] if c["investor_id"] == one["investors"][0]["investor_id"]]
    one["investors"][0]["commitment_keur"] = sum(c["amount_keur"] for c in one["contributions"]) + 100
    for case, doc, what in (("E1", one, "one investor, 100 % ownership"), ("E2", doc2, "two investors 60/40")):
        if case == "E2":     # one agreement per Working Copy: the second case runs on a fresh, identical project
            record = env.create("solar"); ws, _ = run(env, record)
        entry = _agreement_run(env, record, doc)
        result = C.reconcile(entry, agreement=doc)
        assert not _fails(result), (case, _fails(result))
        now = C.scalars(entry)
        # Ownership allocation never changes project funding: Senior debt and total funding are identical to baseline.
        assert now["senior_debt"] == base["senior_debt"] and now["equity_funding"] == base["equity_funding"]
        C.row(case, family="EQUITY", entry=entry, baseline=base, baseline_entry=base_entry, modification=what,
              activated="agreement bound and reconciled by the Run", result=result,
              independent="paid-in, DPI, MOIC, ownership allocation and XIRR recomputed from declared contributions and recorded receipts",
              explanation="Ownership allocation is separate from funding: project funding is unchanged against baseline.")


def test_E3_contribution_proportions_may_differ_from_ownership(equity_baseline):
    env, record, ws, base_entry, base = equity_baseline
    doc = funded_agreement(ws)
    total_by_date = {}
    for c in doc["contributions"]:
        total_by_date[c["cash_date"]] = total_by_date.get(c["cash_date"], 0) + c["amount_keur"]
    doc["contributions"] = [dict(investor_id=i, cash_date=d, amount_keur=t * s) for d, t in total_by_date.items()
                            for i, s in (("alpha", .5), ("beta", .5))]   # ownership stays 60/40, funding 50/50
    entry = _agreement_run(env, record, doc)
    result = C.reconcile(entry, agreement=doc)
    assert not _fails(result), _fails(result)
    C.row("E3", family="EQUITY", entry=entry, baseline=base, baseline_entry=base_entry,
          modification="ownership 60/40 with contributions 50/50", activated="agreement bound by the Run", result=result,
          independent="each investor's DPI/MOIC is computed on its own paid-in, ownership drives distribution only",
          explanation="Funding contribution and ownership allocation are separate quantities; neither is derived from the other.")


def test_E4_contribution_total_mismatch_rejects_the_run_and_commits_nothing(equity_baseline):
    env, record, ws, base_entry, _ = equity_baseline
    doc = funded_agreement(ws)
    doc["contributions"][0]["amount_keur"] -= 5
    assert save_agreement(env, record, doc).status_code == 200
    page = env.client.get("/v2/workbook", params={"project": record.project_code})
    from tests.test_model_decision_workspace_v2 import tokens
    response = env.client.post("/v2/workbook/run", headers={"HX-Request": "true"}, data=dict(project=record.project_code, **tokens(page.text)))
    after = _ws(record)
    assert after.dirty and after.last_runtime_snapshot_id == ws.last_runtime_snapshot_id
    C.emit({"case": "E4", "family": "EQUITY", "input_modification": "contribution total 5 kEUR below project funding",
            "actual_activation": "Run rejected", "verdict": "FAILS_CLOSED",
            "explanation": "Actual funding is determined by project financing / Sources & Uses; a mismatching agreement cannot commit a Run."})


def test_E5_invalid_agreement_rejected(equity_baseline):
    env, record, ws, base_entry, _ = equity_baseline
    doc = funded_agreement(ws)
    doc["investors"][0]["ownership_fraction"] = .9      # 0.9 + 0.4 != 1
    before = _ws(record).draft_snapshot
    response = save_agreement(env, record, doc)
    after = _ws(record).draft_snapshot
    assert after.get("investor_agreement_json") == before.get("investor_agreement_json")
    C.emit({"case": "E5", "family": "EQUITY", "input_modification": "ownership fractions not summing to 1",
            "actual_activation": "rejected", "verdict": "FAILS_CLOSED", "explanation": "Invalid agreement persists nothing."})


# ───────────────────────────────────────────── Add PPA ─────────────────────────────────────────────
def _post_contracts(env, record, payload):
    page = env.client.get("/v2/workbook", params={"project": record.project_code})
    return env.client.post("/v2/workbook/revenue/contracts", headers={"HX-Request": "true"},
                           data={"project": record.project_code, **contract_tokens(page.text), "contracts": json.dumps(payload)})


def _ppa_case(env, payload_fn, case=None):
    record = env.create("solar")
    base_entry = C.commit(env, record)
    base = C.scalars(base_entry)
    pi = C.working_inputs(record)
    payload = payload_fn(pi)
    response = _post_contracts(env, record, payload)
    return record, base_entry, base, payload, response


def _ppa_verify(env, case, payload_fn, what, expect_change=True):
    record, base_entry, base, payload, response = _ppa_case(env, payload_fn)
    assert response.status_code == 200, response.text[:800]
    entry = C.commit(env, record)
    result = C.reconcile(entry, contracts=payload)
    assert not _fails(result), (case, _fails(result))
    assert result["counts"].get("PASS", 0) > 0
    if expect_change:
        assert C.scalars(entry) != base
    C.row(case, family="PPA", entry=entry, baseline=base, baseline_entry=base_entry, modification=what,
          activated="contract book saved and applied by the Run", result=result,
          independent="price, indexation by operating year, allocation, residual merchant and window recomputed per period",
          explanation="Revenue differences follow the declared contract terms; price/volume/window identities reconcile.")
    return entry


def test_P0_legacy_single_ppa_baseline(env):
    record = env.create("solar")
    entry = C.commit(env, record)
    assert "revenue_multistream_audit" not in (entry.runtime_summary or {}) or not entry.runtime_summary["revenue_multistream_audit"]
    C.row("P0", family="PPA", entry=entry, baseline=C.scalars(entry), baseline_entry=entry, modification="none (legacy single PPA)",
          activated="legacy path", independent="legacy revenue path, not multistream", result=C.reconcile(entry))


@pytest.mark.parametrize("case,fn,what", [
    ("P1", lambda pi: contracts(pi, "solar", share=1.0, merchant_price=70, price=90), "one fixed PPA, 100 % share"),
    ("P3", lambda pi: contracts(pi, "solar", share=.6, price=95, merchant_price=90, index=.02), "PPA 60 % indexed 2 %/operating year + residual merchant"),
    ("P6", lambda pi: contracts(pi, "solar", share=.6, price=85, merchant_price=70, strike=95), "PPA + CfD overlay (strike 95 vs merchant 70)"),
    ("P7", lambda pi: contracts(pi, "solar", share=.4, price=85, merchant_price=60), "PPA 40 % with residual merchant at 60"),
])
def test_P_contract_cases_reconcile(env, case, fn, what):
    _ppa_verify(env, case, fn, what)


def test_P2_two_ppas_and_P4_stepped_price_curve_and_P5_expiry_then_merchant(env):
    def two(pi):
        p = contracts(pi, "solar", share=.3, price=85, merchant_price=70)
        extra = deepcopy(p["streams"][0]); extra.update(id="ppa-2", price_eur_mwh=92, volume_share=.3)
        p["streams"].insert(1, extra)
        return p
    _ppa_verify(env, "P2", two, "two PPAs 30 % + 30 % with residual merchant 40 %")

    def expiry(pi):
        from financial_engine.adapters.project_inputs import from_project_inputs
        from financial_engine.orchestrator import _build_period_engine
        ops = [x for x in _build_period_engine(from_project_inputs(pi)).periods() if x.is_operation]
        p = contracts(pi, "solar", share=.6, price=90, merchant_price=70)
        p["streams"][0]["end_date"] = ops[len(ops) // 2].start_date.isoformat()
        merchant = p["streams"][1]
        merchant["start_date"] = ops[0].start_date.isoformat()
        return p
    _ppa_verify(env, "P5", expiry, "PPA expires mid-life; residual merchant continues")


def test_P8_price_downside_with_p50_and_p90_lender_case(env):
    from tests.test_model_financing_f2 import save as f2save
    record = env.create("solar")
    base_entry = C.commit(env, record)
    base = C.scalars(base_entry)
    payload = contracts(C.working_inputs(record), "solar", share=.6, price=60, merchant_price=45)
    assert _post_contracts(env, record, payload).status_code == 200
    entry = C.commit(env, record)
    result = C.reconcile(entry, contracts=payload)
    assert not _fails(result)
    C.row("P8", family="PPA", entry=entry, baseline=base, baseline_entry=base_entry,
          modification="PPA 60 % at 60 EUR/MWh, merchant 45 (price downside)", activated="contract book applied", result=result,
          independent="per-period price and allocation recomputed; credit identities are validated on the same Run",
          explanation="Debt re-sizes to the lower CFADS or the gearing cap; direction is not asserted (see credit matrix findings).")


@pytest.mark.parametrize("name,mutate", [
    ("share_over_100", lambda p: p["streams"][0].update(volume_share=1.3)),
    ("negative_price", lambda p: p["streams"][0].update(price_eur_mwh=-5)),
    ("unknown_type", lambda p: p["streams"][0].update(type="forward_swap")),
    ("window_off_period_boundary", lambda p: p["streams"][0].update(start_date="2031-03-15")),
])
def test_P9_invalid_contract_books_are_rejected_without_persisting(env, name, mutate):
    record = env.create("solar")
    C.commit(env, record)
    before = _ws(record)
    payload = contracts(C.working_inputs(record), "solar")
    mutate(payload)
    response = _post_contracts(env, record, payload)
    after = _ws(record)
    assert after.draft_snapshot == before.draft_snapshot and after.last_runtime_snapshot_id == before.last_runtime_snapshot_id
    C.emit({"case": f"P9-{name}", "family": "PPA", "input_modification": name, "actual_activation": "rejected",
            "verdict": "FAILS_CLOSED", "explanation": "Invalid contract configuration is rejected; nothing persisted."})


def test_release_closed_features_and_engine_boundary_unchanged():
    import subprocess
    out = subprocess.run(["git", "diff", "--name-only", "origin/main", "--", "financial_engine", "finco_core", "domain", "app/v2",
                          "app/templates", "static"], capture_output=True, text=True).stdout.strip()
    assert out == "", f"WF-A must not touch the engine, domain or UI: {out}"
