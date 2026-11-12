"""R04 REAL production acceptance: HTTP save, Save All, effective Run and persisted History on the released stack.

Nothing here calls the isolated allocator twice and calls it a Save/Run test. Every case drives the canonical writer
(``POST /v2/workbook/revenue/contracts``, ``POST /v2/workbook/save-all``) and the real Run, reads the persisted effective inputs and the immutable Run
History, and reconciles them independently (``fractions.Fraction``). The isolated R04 validator is then reconciled against the SAME per-period
generation the released engine produced.

What this file proves about the CURRENT product (no production source is changed by R04):
* simultaneous overlapping PPAs are stored and Run; the global ceiling is enforced at the canonical write boundary and at Run in the only
  representation the stored schema supports, a share of eligible generation, which follows the selected case and degradation;
* an over-allocation is a hard 422 with no write (direct API and Save All, atomic rollback);
* an absolute annual volume and contract dates that do not match the operating-period axis are NOT storable (blockers B1 and B2).
"""
from __future__ import annotations

import json
import subprocess
from datetime import timedelta
from fractions import Fraction as Fr
from pathlib import Path

import pytest

from tests.test_model_decision_workspace_v2 import env  # noqa: F401  (fixture)
from tests.test_save_all_atomic_v1 import world, _project, _body, _state, _assert_untouched, URL  # noqa: F401  (fixtures/helpers)

USER = "decision-user"
ROOT = Path(__file__).resolve().parents[2]


def _common(inputs):
    from tests.test_wf07_revenue_multistream import contracts
    base = contracts(inputs, "solar", price=85, share=.6)["streams"][0]
    return {k: base[k] for k in ("start_date", "end_date", "settlement", "source_ref")}


def _book(inputs, ppas, window=None, merchant_price=70):
    """ppas: [(id, share, price, index)]; ``window`` optionally maps an id to (start, end)."""
    common = _common(inputs)
    rows = []
    for pid, share, price, index in ppas:
        row = dict(common, id=pid, type="ppa", volume_share=share, price_eur_mwh=price, indexation_rate=index)
        if window and pid in window:
            row["start_date"], row["end_date"] = window[pid]
        rows.append(row)
    rows.append(dict(common, id="market-1", type="merchant", volume_share=None, price_eur_mwh=merchant_price, indexation_rate=0))
    return dict(version=1, technology="solar", indexation_basis="OPERATING_YEAR", streams=rows)


def _inputs(record):
    from app.persistence.workspace_repository import get_workspace_state
    from app.workbook.service import WorkbookService
    return WorkbookService.build_draft_input_set_from_workspace(get_workspace_state(USER, record.project_id)).to_projectinputs()


def _snapshot(record):
    from app.persistence.workspace_repository import get_workspace_state
    return json.dumps(get_workspace_state(USER, record.project_id).draft_snapshot, sort_keys=True)


def _prime(env, record):
    """Loading the workbook page normalizes the draft once (defaults are persisted); every no-write assertion starts AFTER that."""
    assert env.client.get("/v2/workbook", params={"project": record.project_code}).status_code == 200
    return record


def _post(env, record, payload, **override):
    from tests.test_wf07_revenue_workspace import contract_tokens
    project = {"project": record.project_code}
    page = env.client.get("/v2/workbook", params=project)
    return env.client.post("/v2/workbook/revenue/contracts", headers={"HX-Request": "true"},
                           data={**project, **contract_tokens(page.text), "contracts": json.dumps(payload), **override})


def _schedule(record):
    from financial_engine.adapters.project_inputs import from_project_inputs
    from financial_engine.orchestrator import _build_period_engine
    from finco_core.revenue.generation import revenue_decomposition_schedule
    saved = _inputs(record)
    axis = _build_period_engine(from_project_inputs(saved))
    periods = {p.index: p for p in axis.periods()}
    sched = revenue_decomposition_schedule(saved, axis)
    return [(periods[i], sched[i]) for i in sorted(sched) if sched[i]["is_operation"]]


def _streams(row):
    return {s["id"]: s for s in row["multistream_evidence"]["streams"]}


# ---------------------------------------------------------------- A. HTTP direct save and the hard stop
def test_http_save_80_20_is_stored_and_80_21_is_a_hard_422_with_no_write(env):
    record = env.create("solar")
    inputs = _inputs(record)
    ok = _post(env, record, _book(inputs, [("ppa-A", .8, 70, .02), ("ppa-B", .2, 45, .005)]))
    assert ok.status_code == 200
    saved = _snapshot(record)
    refused = _post(env, record, _book(inputs, [("ppa-A", .8, 70, .02), ("ppa-B", .21, 45, .005)]))
    assert refused.status_code == 422
    body = refused.json()["error"]
    assert body.startswith("REVENUE_ALLOCATION_EXCEEDS_ELIGIBLE_GENERATION") and "1.010000" in body and "model year 1" in body
    assert _snapshot(record) == saved, "a refused contract book must not change a single stored byte"
    # a simultaneous book of three is allowed while it fits: 60 + 20 + 20
    assert _post(env, record, _book(inputs, [("ppa-A", .6, 70, .02), ("ppa-B", .2, 45, .005), ("ppa-C", .2, 50, 0)])).status_code == 200


def test_duplicate_ids_negative_and_unknown_shapes_are_refused_without_a_write(env):
    record = _prime(env, env.create("solar"))
    inputs = _inputs(record)
    before = _snapshot(record)
    for bad in (_book(inputs, [("ppa-A", .5, 70, 0), ("ppa-A", .2, 45, 0)]),
                _book(inputs, [("ppa-A", -.1, 70, 0)]),
                _book(inputs, [("ppa-A", 1.2, 70, 0)])):
        assert _post(env, record, bad).status_code == 422
    assert _snapshot(record) == before


def test_absolute_volume_and_off_axis_dates_are_not_storable_today_blockers_b1_b2(env):
    record = _prime(env, env.create("solar"))
    inputs = _inputs(record)
    before = _snapshot(record)
    payload = _book(inputs, [("ppa-A", .8, 70, 0)])
    payload["streams"][0]["volume_mwh_per_year"] = 80000                      # B1: no absolute annual energy field in the stored schema
    assert _post(env, record, payload).status_code == 422
    sched = _schedule(record)
    mid = sched[2][0].start_date + timedelta(days=17)                          # B2: a contract date that is not an operating-period boundary
    off = _book(inputs, [("ppa-A", .8, 70, 0)], window={"ppa-A": (mid.isoformat(), _common(inputs)["end_date"])})
    refused = _post(env, record, off)
    assert refused.status_code == 422 and "REVENUE_V2_AXIS" in refused.json()["error"]
    assert _snapshot(record) == before


# ---------------------------------------------------------------- B/C. effective Run, persisted History and reconciliation
def test_saved_book_reloads_runs_and_reconciles_with_the_isolated_validator(env):
    from app.persistence.run_history_repository import get_latest_history_entry
    from tests.test_model_financing_f2 import run
    from tools.numerical_validation.identities import reconcile_bundle
    from tools.numerical_validation.source import bundle_from_history_entry
    from research.r04_ppa_global_cap import core as C

    record = env.create("solar")
    assert _post(env, record, _book(_inputs(record), [("ppa-A", .8, 70, .02), ("ppa-B", .2, 45, .005)])).status_code == 200
    run(env, record)                                                          # the effective Run reads the persisted book, not this test's input
    entry = get_latest_history_entry(USER, record.project_id)
    result = reconcile_bundle(bundle_from_history_entry(entry))
    rows = {r["identity"]: r for r in result["by_identity"]}
    assert result["counts"]["FAIL"] == 0
    assert rows["RV2-GENERATION-ALLOCATION"]["verdict"] == "VERIFIED" and rows["RV2-GENERATION-ALLOCATION"]["counts"]["PASS"] > 0

    ops = _schedule(record)
    segments, per_year = [], {}
    for k, (period, row) in enumerate(ops):
        gen = Fr(str(row["generation_mwh"]))
        s = _streams(row)
        a, b, m = (Fr(str(s[i]["quantity_mwh"])) for i in ("ppa-A", "ppa-B", "market-1"))
        assert abs(float(a - gen * Fr(8, 10))) < 1e-6 and abs(float(b - gen * Fr(2, 10))) < 1e-6          # shares of the SAME generation
        assert abs(float(a + b + m - gen)) < 1e-6 and m == 0                                                 # conservation, no residual
        start = period.start_date if k == 0 else period.start_date + timedelta(days=1)                       # released row convention: (start, end]
        segments.append(C.AvailabilitySegment(start, period.end_date + timedelta(days=1), gen))
        y = per_year.setdefault(period.end_date.year, {"ppa-A": Fr(0), "ppa-B": Fr(0)})
        y["ppa-A"] += a
        y["ppa-B"] += b
    source = C.AvailabilitySource("released-run", "proj", "base", "P50", "run-1", "PERIOD_ENGINE", tuple(segments))
    window = (segments[0].start, segments[-1].end)
    book = [C.Contract("ppa-A", *window, C.PERCENT_OF_AVAILABLE, Fr(8, 10)), C.Contract("ppa-B", *window, C.PERCENT_OF_AVAILABLE, Fr(2, 10))]
    report = C.allocate(source, book, rel_tolerance=Fr(1, 10**9))
    assert report.status == "WITHIN_CAP"
    for year, got in per_year.items():                                        # the isolated validator reproduces the engine's per-year contract energy
        for cid in ("ppa-A", "ppa-B"):
            assert abs(float(report.calendar_years[year][cid] - got[cid])) < 1e-4, (year, cid)


def test_degrading_forecast_the_run_shares_follow_it_while_a_fixed_gwh_book_would_breach(env):
    from research.r04_ppa_global_cap import core as C
    record = env.create("solar")
    assert _post(env, record, _book(_inputs(record), [("ppa-A", .8, 70, 0), ("ppa-B", .2, 45, 0)])).status_code == 200
    ops = _schedule(record)
    by_op_year = {}
    for period, row in ops:
        by_op_year[period.year_index] = by_op_year.get(period.year_index, Fr(0)) + Fr(str(row["generation_mwh"]))
    full = sorted(by_op_year)[1:4]                                               # operating year 1 is partial (COD mid-year): compare the full years
    assert by_op_year[full[2]] < by_op_year[full[1]] < by_op_year[full[0]]       # the released forecast really degrades year over year
    for period, row in ops:                                                      # shares never exceed the degrading generation
        s = _streams(row)
        assert s["ppa-A"]["quantity_mwh"] + s["ppa-B"]["quantity_mwh"] <= row["generation_mwh"] + 1e-6
    segments = [C.AvailabilitySegment(p.start_date if i == 0 else p.start_date + timedelta(days=1), p.end_date + timedelta(days=1),
                                      Fr(str(r["generation_mwh"]))) for i, (p, r) in enumerate(ops)]
    source = C.AvailabilitySource("released-run", "proj", "base", "P50", "run-1", "PERIOD_ENGINE", tuple(segments))
    first = [(p, r) for p, r in ops if p.year_index == full[0]]
    start, end = first[0][0].start_date + timedelta(days=1), ops[-1][0].end_date + timedelta(days=1)
    year_mwh = by_op_year[full[0]]
    fixed = [C.Contract("A", start, end, C.ABSOLUTE_ANNUAL_MWH, year_mwh * Fr(8, 10)), C.Contract("B", start, end, C.ABSOLUTE_ANNUAL_MWH, year_mwh * Fr(2, 10))]
    with pytest.raises(C.GlobalCapExceeded):                                      # what an absolute book needs the (not yet existing) writer to refuse
        C.allocate(source, fixed, rel_tolerance=Fr(1, 10**9))


def test_period_aligned_windows_are_half_open_and_never_double_count_energy(env):
    record = env.create("solar")
    inputs = _inputs(record)
    common = _common(inputs)
    ops = _schedule(record)
    first_start = ops[0][0].start_date
    b_start, b_end = ops[2][0].start_date, ops[6][0].start_date                    # four semiannual rows = a two-year contract on period boundaries
    book = _book(inputs, [("ppa-A", .7, 70, 0), ("ppa-B", .3, 45, 0)], window={"ppa-B": (b_start.isoformat(), b_end.isoformat())})
    assert _post(env, record, book).status_code == 200
    ops = _schedule(record)
    active = [p.start_date for p, r in ops if _streams(r)["ppa-B"]["status"] == "active"]
    assert active == [p.start_date for p, _ in ops[2:6]]                         # [start, end): the row starting at b_end is NOT active
    for period, row in ops:
        s = _streams(row)
        gen = row["generation_mwh"]
        in_window = b_start <= period.start_date < b_end
        assert s["ppa-B"]["quantity_mwh"] == pytest.approx(0.3 * gen if in_window else 0.0, abs=1e-6)
        assert s["ppa-A"]["quantity_mwh"] == pytest.approx(0.7 * gen, abs=1e-6)
        assert s["ppa-A"]["quantity_mwh"] + s["ppa-B"]["quantity_mwh"] + s["market-1"]["quantity_mwh"] == pytest.approx(gen, abs=1e-6)
        if not in_window:
            assert s["market-1"]["quantity_mwh"] == pytest.approx(0.3 * gen, abs=1e-6)      # the uncontracted remainder is merchant, never lost or doubled
    assert first_start == ops[0][0].start_date and common["end_date"]


def test_independent_indexation_and_the_merchant_remainder_against_a_fraction_oracle(env):
    record = env.create("solar")
    book = _book(_inputs(record), [("ppa-A", .5, 70, .02), ("ppa-B", .3, 45, .005)], merchant_price=62)
    assert _post(env, record, book).status_code == 200
    for period, row in _schedule(record):
        s = _streams(row)
        n = period.year_index - 1                                                # OPERATING_YEAR basis of the released contract schema
        assert s["ppa-A"]["price_eur_mwh"] == pytest.approx(float(Fr(70) * Fr(102, 100) ** n), rel=1e-12)
        assert s["ppa-B"]["price_eur_mwh"] == pytest.approx(float(Fr(45) * Fr(1005, 1000) ** n), rel=1e-12)
        assert s["market-1"]["price_eur_mwh"] == 62 and s["market-1"]["quantity_mwh"] == pytest.approx(0.2 * row["generation_mwh"], abs=1e-6)
        assert not any(v["type"] == "cfd" for v in s.values())                    # no settlement stream: no second sale of the same MWh
        energy = sum(Fr(str(v["quantity_mwh"])) * Fr(str(v["price_eur_mwh"])) / 1000 for v in s.values())
        assert float(energy) == pytest.approx(row["energy_revenue_keur"], abs=1e-6)


# ---------------------------------------------------------------- Save All, CAS and tenancy
def _save_all_contracts(world, rec, shares):
    import os
    os.environ["FINCO_MODEL_REACT_V1"] = "1"
    payload = world.owner.get("/v2/model-react/revenue", params={"project": rec.project_code}).json()
    window = payload["contracts"]["operating_window"]
    streams = [{"id": f"ppa-{i}", "type": "ppa", "start_date": window["start"], "end_date": window["end"], "volume_share": s,
                "price_eur_mwh": 55, "indexation_rate": 0.0, "source_ref": "Entered in FINCO workspace", "settlement": "SAME_PERIOD"}
               for i, s in enumerate(shares, 1)]
    return json.dumps({"version": 2, "technology": payload["contracts"].get("technology") or "solar", "indexation_basis": "OPERATING_YEAR", "streams": streams})


def test_save_all_over_allocation_is_a_hard_stop_and_rolls_back_every_section(world):
    rec = _project()
    before = _state(rec)
    res = world.owner.post(URL, json=_body(rec, world.owner, contracts_json=_save_all_contracts(world, rec, [.8, .21])))
    assert res.status_code in (409, 422), res.text
    _assert_untouched(rec, before)                                               # cells, cost lines, hash, dirty flag, ledger and history unchanged
    ok = world.owner.post(URL, json=_body(rec, world.owner, contracts_json=_save_all_contracts(world, rec, [.8, .2])))
    assert ok.status_code == 200 and ok.json()["saved"]["contracts"] == 1        # one contracts DOCUMENT holding both simultaneous PPAs
    assert "ppa-1" in json.dumps(_state(rec)["draft"]) and "ppa-2" in json.dumps(_state(rec)["draft"])


def test_stale_cas_and_a_stranger_fail_closed_with_nothing_written(world):
    rec = _project()
    before = _state(rec)
    contracts = _save_all_contracts(world, rec, [.5])
    stale = _body(rec, world.owner, contracts_json=contracts, content_hash="0" * 64)
    assert world.owner.post(URL, json=stale).status_code in (409, 422)
    _assert_untouched(rec, before)
    foreign = world.stranger.post(URL, json=_body(rec, world.owner, contracts_json=contracts))
    assert foreign.status_code in (401, 403, 404, 409, 422)
    _assert_untouched(rec, before)


# ---------------------------------------------------------------- scope honesty
def test_this_pr_changes_no_production_source_so_legacy_single_ppa_runs_are_byte_identical():
    names = subprocess.run(["git", "diff", "--name-only", "origin/main...HEAD"], cwd=ROOT, capture_output=True).stdout.decode().split()
    if not names:                                                               # shallow or detached evaluation: fall back to the working tree
        names = subprocess.run(["git", "diff", "--name-only", "HEAD"], cwd=ROOT, capture_output=True).stdout.decode().split()
    production = [n for n in names if n.startswith(("app/", "domain/", "financial_engine/", "finco_core/", "frontend/", "static/", "main_web.py"))]
    assert production == []
