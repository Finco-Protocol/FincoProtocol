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
          activated="no F3 collection", result=result, independent="no facility identities are applicable", is_baseline=True,
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
          activated="F3 collection activated by the Run (authority recorded)", result=result, required=C.FT_ALL,
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
    assert after.last_runtime_snapshot_id == before.last_runtime_snapshot_id and after.dirty == before.dirty
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
          activated="no investor agreement", independent="no investor identities applicable", result=C.reconcile(entry), is_baseline=True)


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
              activated="agreement bound and reconciled by the Run", result=result, required=C.IV_ALL,
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
          modification="ownership 60/40 with contributions 50/50", activated="agreement bound by the Run", result=result, required=C.IV_ALL,
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
          activated="contract book saved and applied by the Run", result=result, required=C.RC_ALL,
          independent="price, indexation by operating year, allocation, residual merchant and window recomputed per period",
          explanation="Revenue differences follow the declared contract terms; price/volume/window identities reconcile.")
    return entry


def test_P0_legacy_single_ppa_baseline(env):
    record = env.create("solar")
    entry = C.commit(env, record)
    assert "revenue_multistream_audit" not in (entry.runtime_summary or {}) or not entry.runtime_summary["revenue_multistream_audit"]
    C.row("P0", family="PPA", entry=entry, baseline=C.scalars(entry), baseline_entry=entry, modification="none (legacy single PPA)",
          activated="legacy path", independent="legacy revenue path, not multistream", result=C.reconcile(entry), is_baseline=True)


@pytest.mark.parametrize("case,fn,what", [
    ("P1", lambda pi: contracts(pi, "solar", share=1.0, merchant_price=70, price=90), "one fixed PPA, 100 % share"),
    ("P3", lambda pi: contracts(pi, "solar", share=.6, price=95, merchant_price=90, index=.02), "PPA 60 % indexed 2 %/operating year + residual merchant"),
    ("P6", lambda pi: contracts(pi, "solar", share=.6, price=85, merchant_price=70, strike=95), "PPA + CfD overlay (strike 95 vs merchant 70)"),
    ("P7", lambda pi: contracts(pi, "solar", share=.4, price=85, merchant_price=60), "PPA 40 % with residual merchant at 60"),
])
def test_P_contract_cases_reconcile(env, case, fn, what):
    _ppa_verify(env, case, fn, what)


def _operating(pi):
    from financial_engine.adapters.project_inputs import from_project_inputs
    from financial_engine.orchestrator import _build_period_engine
    return [x for x in _build_period_engine(from_project_inputs(pi)).periods() if x.is_operation]


def test_P2_two_ppas_with_residual_merchant(env):
    def two(pi):
        p = contracts(pi, "solar", share=.3, price=85, merchant_price=70)
        extra = deepcopy(p["streams"][0]); extra.update(id="ppa-2", price_eur_mwh=92, volume_share=.3)
        p["streams"].insert(1, extra)
        return p
    _ppa_verify(env, "P2", two, "two PPAs 30 % + 30 % with residual merchant 40 %")


def _stepped(pi):
    """Revenue V2 exact-period curve: one explicit price at EVERY active operating-period start, three steps, no indexation."""
    ops = _operating(pi)
    p = contracts(pi, "solar", share=.6, price=80, merchant_price=70)
    third = max(1, len(ops) // 3)
    p["streams"][0]["price_curve"] = [
        {"period_start": op.start_date.isoformat(), "price_eur_mwh": 80.0 if i < third else 90.0 if i < 2 * third else 100.0}
        for i, op in enumerate(ops)]
    p["streams"][0]["indexation_rate"] = 0
    p["version"] = 2
    return p


def test_P4_scheduled_stepped_price_curve_executes_and_reconciles_period_by_period(env):
    record, base_entry, base, payload, response = _ppa_case(env, _stepped)
    assert response.status_code == 200, response.text[:800]
    entry = C.commit(env, record)
    result = C.reconcile(entry, contracts=payload)
    assert not _fails(result), _fails(result)
    price = {r["identity"]: r for r in result["by_identity"]}["RC-PRICE"]
    assert price["counts"]["PASS"] >= len(payload["streams"][0]["price_curve"]) and not price["counts"].get("UNAVAILABLE")
    # the curve is really a curve: three distinct recorded PPA prices, in the declared order, not one flat or indexed price
    recorded = [o for o in result["outcomes"] if o["identity"] == "RC-PRICE" and o["status"] == "PASS"]
    assert len({o["expected"] for o in recorded}) >= 3
    assert C.scalars(entry) != base
    C.row("P4", family="PPA", entry=entry, baseline=base, baseline_entry=base_entry, required=C.RC_ALL,
          modification="PPA 60 % with explicit stepped price_curve 80 / 90 / 100 EUR/MWh (one price per operating period), residual merchant 70",
          activated="Revenue V2 contract book (version 2, exact-period curve) saved and applied by the Run", result=result,
          independent="declared price at each operating-period start compared with the recorded stream price; no interpolation, no indexation",
          explanation="Distinct declared steps are reproduced period by period; revenue and sized debt differences follow the declared prices.",
          extra={"curve_points": len(payload["streams"][0]["price_curve"]), "distinct_declared_prices": sorted({p["price_eur_mwh"] for p in payload["streams"][0]["price_curve"]})})


def test_P5_expiry_then_merchant(env):
    def expiry(pi):
        ops = _operating(pi)
        p = contracts(pi, "solar", share=.6, price=90, merchant_price=70)
        p["streams"][0]["end_date"] = ops[len(ops) // 2].start_date.isoformat()
        p["streams"][1]["start_date"] = ops[0].start_date.isoformat()
        return p
    _ppa_verify(env, "P5", expiry, "PPA expires mid-life; residual merchant continues")


def test_P8_p50_and_p90_lender_cases_are_both_saved_executed_and_compared(env):
    from app.workbook import bankability_config as bc
    record = env.create("solar")
    base_entry = C.commit(env, record)                     # comparable baseline: legacy single PPA, default lender configuration
    base = C.scalars(base_entry)
    payload = contracts(C.working_inputs(record), "solar", share=.6, price=60, merchant_price=45)
    assert _post_contracts(env, record, payload).status_code == 200
    entries = {}
    for case in ("P_50", "P90-10y"):
        resp = save(env, record, json.dumps({"version": 1, "lender_case": case}), field=bc.FIELD_ID)
        assert 'field-error-banner' not in resp.text, resp.text[:600]
        assert json.loads(_ws(record).draft_snapshot[bc.SNAPSHOT_KEY])["lender_case"] == case     # the saved authority
        entries[case] = C.commit(env, record)
    p50, p90 = entries["P_50"], entries["P90-10y"]
    ids = {k: C.identity(e) for k, e in entries.items()}
    assert ids["P_50"]["run_key"] != ids["P90-10y"]["run_key"] and ids["P_50"]["snapshot_id"] != ids["P90-10y"]["snapshot_id"]
    bank = lambda e: e.runtime_summary["financing_evidence"]["bankability"]  # noqa: E731
    # the selected lender case really reached each Run: the DSCR capacity is computed on a different (lower) sizing case
    assert bank(p90)["dscr_debt_capacity_keur"] < bank(p50)["dscr_debt_capacity_keur"]
    from tools.numerical_validation.source import bundle_from_history_entry
    series = lambda e, k: bundle_from_history_entry(e)["series"][k]["values"]  # noqa: E731
    # lender assumptions are separate from operating assumptions: operating generation and revenue are identical
    assert series(p50, "rev.generation_display") == series(p90, "rev.generation_display")
    m50, m90 = C.scalars(p50), C.scalars(p90)
    assert m50["total_ebitda"] == m90["total_ebitda"]
    comparison = {
        "dscr_debt_capacity_keur": {"P_50": bank(p50)["dscr_debt_capacity_keur"], "P90-10y": bank(p90)["dscr_debt_capacity_keur"]},
        "final_senior_commitment_keur": {"P_50": bank(p50)["final_senior_commitment_keur"], "P90-10y": bank(p90)["final_senior_commitment_keur"]},
        "binding_constraint": {"P_50": bank(p50)["binding_senior_constraint"], "P90-10y": bank(p90)["binding_senior_constraint"]},
        "senior_debt": {"P_50": str(m50["senior_debt"]), "P90-10y": str(m90["senior_debt"])},
        "min_dscr": {"P_50": str(m50["min_dscr"]), "P90-10y": str(m90["min_dscr"])},
        "equity_irr": {"P_50": None if m50["equity_irr"] is None else str(m50["equity_irr"]),
                       "P90-10y": None if m90["equity_irr"] is None else str(m90["equity_irr"])},
        "total_ebitda_identical": True, "generation_identical": True,
        "not_comparable": ["CFADS-at-P90 is not persisted as a separate series (the P90 sizing CFADS is internal to the solver); only its effect "
                           "on DSCR capacity and sized debt is observable"]}
    for key, entry, tag in (("P_50", p50, "P8-P50"), ("P90-10y", p90, "P8-P90")):
        result = C.reconcile(entry, contracts=payload)
        assert not _fails(result)
        C.row(tag, family="PPA", entry=entry, baseline=base, baseline_entry=base_entry, required=C.RC_ALL,
              modification=f"PPA 60 % at 60 EUR/MWh, merchant 45, lender case {key} saved through the F2 bankability configuration",
              activated=f"contract book + lender_case={key} applied by the Run", result=result,
              independent="per-period price/allocation recomputed; lender case verified by the Run's DSCR capacity and unchanged operating generation",
              explanation="A price downside Run alone is not a P50/P90 comparison; see P8-compare for the paired evidence.",
              extra={"lender_case": key})
    C.emit({"case": "P8-compare", "family": "PPA", "baseline_run": C.identity(base_entry), "run_p50": ids["P_50"], "run_p90": ids["P90-10y"],
            "input_modification": "same PPA downside contract book, lender case P_50 then P90-10y", "actual_activation": "both lender cases saved and executed",
            "comparison": comparison, "verdict": "VERIFIED_PAIRED_COMPARISON",
            "explanation": "Operating generation and EBITDA are identical across the two Runs; only sizing capacity and the sized debt differ."})


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


# Historical provenance of WF-A (PR #287): its authorised scope was validation tooling and tests only. The check is pinned to the reviewed WF-A range, so it
# stays true after WF-A merged and does not misclassify later, separately authorised UI or financial PRs as WF-A violations.
WFA_BASE = "03e2b9638e9324bb18ea8420ce8f9823f4f0a676"       # main before WF-A
WFA_REVIEWED_HEAD = "d4431bc3f0b6f51b5042e69ea62b9d67184c5e4b"   # the reviewed WF-A head (merged by 38018e9a190715023568b68512fe766576a5be89)
WFA_PROTECTED_PATHS = ("financial_engine", "finco_core", "domain", "app/v2", "app/templates", "static")


def _git(*args):
    import subprocess
    return subprocess.run(["git", *args], capture_output=True, text=True)


def test_release_closed_features_and_engine_boundary_unchanged():
    for commit in (WFA_BASE, WFA_REVIEWED_HEAD):
        # Provenance must be establishable: a missing object (for example a shallow checkout) is a failure, never a silent skip.
        found = _git("cat-file", "-e", f"{commit}^{{commit}}")
        assert found.returncode == 0, f"WF-A provenance commit {commit} is not available in this checkout (full history required): {found.stderr.strip()}"
    diff = _git("diff", "--name-only", WFA_BASE, WFA_REVIEWED_HEAD, "--", *WFA_PROTECTED_PATHS)
    assert diff.returncode == 0, diff.stderr
    assert diff.stdout.strip() == "", f"WF-A must not have touched the engine, domain or UI: {diff.stdout.strip()}"


def test_case_verdict_requires_feature_specific_identities():
    """Many existing F3.9 PASS results must never give a feature case the VERIFIED verdict."""
    def outcome(identity, **counts):
        return {"identity": identity, "counts": {"PASS": 0, "FAIL": 0, "UNAVAILABLE": 0, "NOT_COMPARABLE": 0, **counts}}
    f39 = [outcome(f"REV-{i}", PASS=40) for i in range(20)]
    feature_missing = {"counts": {"PASS": 800, "FAIL": 0, "UNAVAILABLE": 16, "NOT_COMPARABLE": 0},
                       "by_identity": f39 + [outcome(i, UNAVAILABLE=1) for i in C.FT_ALL]}
    assert C.classify(feature_missing, C.FT_ALL) == "INCOMPLETE_FEATURE_IDENTITIES_NOT_EVALUATED"
    assert C.classify({"counts": feature_missing["counts"], "by_identity": f39}, C.RC_ALL) == "INCOMPLETE_FEATURE_IDENTITIES_NOT_EVALUATED"
    partial = {"counts": {"PASS": 800, "FAIL": 0, "UNAVAILABLE": 1, "NOT_COMPARABLE": 0},
               "by_identity": f39 + [outcome(i, PASS=3) for i in C.IV_ALL[:-1]] + [outcome(C.IV_ALL[-1], UNAVAILABLE=1)]}
    assert C.classify(partial, C.IV_ALL) == "INCOMPLETE_FEATURE_IDENTITIES_NOT_EVALUATED"
    nc = {"counts": {"PASS": 800, "FAIL": 0, "UNAVAILABLE": 0, "NOT_COMPARABLE": 1},
          "by_identity": f39 + [outcome(i, PASS=3) for i in C.RC_ALL[:-1]] + [outcome(C.RC_ALL[-1], NOT_COMPARABLE=1)]}
    assert C.classify(nc, C.RC_ALL) == "NOT_COMPARABLE"
    good = {"counts": {"PASS": 900, "FAIL": 0, "UNAVAILABLE": 0, "NOT_COMPARABLE": 0}, "by_identity": f39 + [outcome(i, PASS=3) for i in C.RC_ALL]}
    assert C.classify(good, C.RC_ALL) == "VERIFIED"
    bad = {"counts": {"PASS": 900, "FAIL": 1, "UNAVAILABLE": 0, "NOT_COMPARABLE": 0}, "by_identity": good["by_identity"]}
    assert C.classify(bad, C.RC_ALL) == "FAIL"
    assert C.classify(feature_missing, (), baseline=True) == "BASELINE_VERIFIED"
    with pytest.raises(ValueError):
        C.classify(good, ())
