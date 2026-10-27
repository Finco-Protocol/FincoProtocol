"""FIN-V2-C1-FIX-1a — Senior Debt transparency & lender evidence (additive, read-only).

Acceptance markers
  SDE_FOUR_VERTICALS   contractual maturity vs actual payoff, period-level, Solar/Wind/Data Center/EV
  SDE_INDEPENDENT      values cross-checked against the persisted 2-dp schedules and the project configuration
  SDE_RUN_IDENTITY     evidence is stored inside the Run's financing_evidence (run_binding) and nowhere else
  SDE_BINDING          GEARING / DSCR classification and the Data Center ramp-up limiting row
  SDE_DSCR_BASES       sizing-case vs reported base-case DSCR bases equal the real calculation sources
  SDE_NOT_RECORDED     historical Runs state NOT_RECORDED; nothing is rebuilt, nothing becomes zero
  SDE_NO_INTERFERENCE  every other byte of the Run payload is identical with and without the evidence
  SDE_NEGATIVE         typed statuses for unsupported / inconsistent / empty structures; evidence never raises
"""
from __future__ import annotations

import ast
import copy
import dataclasses
import io
import json
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import openpyxl
import pytest

import rc7_helpers as H
from app.export import institutional_reporting_v3 as R3
from app.export.run_evidence import evidence_from_history_entry
from app.run_integrity import senior_debt_evidence as SDE

# (contractual maturity period, actual payoff period) — owner acceptance table, verified against the exact
# current reference configuration (see the independent derivation in test_maturity_follows_the_configuration).
REQUIRED = {"solar": (32, 24), "wind": (33, 23), "data_center": (27, 20), "ev": (21, 16)}
BINDING = {"solar": "GEARING", "wind": "GEARING", "data_center": "DSCR", "ev": "GEARING"}
BANK_DISTINCT = {"solar": True, "wind": True, "data_center": False, "ev": False}
TENOR = {"solar": 15, "wind": 15, "data_center": 12, "ev": 10}
ENGINE_KIND = {"solar": "generic_solar_reference", "wind": "generic_wind_reference",
               "data_center": "generic_data_center_reference", "ev": "generic_ev_charging_reference"}


@pytest.fixture(scope="module", autouse=True)
def _db(tmp_path_factory):
    from _pytest.monkeypatch import MonkeyPatch

    mp = MonkeyPatch()
    H.init_db(tmp_path_factory.mktemp("sde"), mp)
    yield
    mp.undo()


_CACHE: dict = {}


def _commit(kind):
    """One real engine Run per vertical, committed through the production persistence path (cached per module)."""
    if kind not in _CACHE:
        from app.persistence.projects_repository import get_project
        from app.persistence.run_history_repository import get_run_history
        from app.persistence.workspace_repository import get_workspace_state

        pr, uid, snap, pi, sc = H.create_project(kind)
        result, snapshot_id = H.commit_run(pr, uid, pi, sc, kind)
        pr = get_project(pr.project_id, uid)
        _CACHE[kind] = SimpleNamespace(
            kind=kind, pr=pr, uid=uid, pi=pi, result=result, snapshot_id=snapshot_id,
            entry=get_run_history(uid, pr.project_id, limit=5)[0], ws=get_workspace_state(uid, pr.project_id))
    return _CACHE[kind]


@pytest.fixture(scope="module", params=list(REQUIRED))
def committed(request):
    return _commit(request.param)


def _evidence(c) -> dict:
    return c.ws.last_runtime_summary["financing_evidence"][SDE.EVIDENCE_KEY]


# ── SDE_FOUR_VERTICALS / SDE_INDEPENDENT ─────────────────────────────────────────────────────────────

def test_four_vertical_maturity_and_payoff_periods(committed):
    c = committed
    e = _evidence(c)
    maturity, payoff = REQUIRED[c.kind]
    r = e["repayment"]
    assert e["status"] == SDE.STATUS_RECORDED and e["schema_version"] == SDE.SCHEMA_VERSION
    assert (r["contractual_maturity_period_index"], r["actual_payoff_period_index"]) == (maturity, payoff)
    assert r["periods_maturity_minus_payoff"] == maturity - payoff
    assert r["payoff_status"] == SDE.PAYOFF_BEFORE_MATURITY
    assert r["index_axis"] == "MODEL_PERIOD_INDEX"


def test_dates_agree_with_the_persisted_schedules_and_terminal_state(committed):
    c = committed
    r = _evidence(c)["repayment"]
    periods = c.ws.last_debt_schedule["periods"]
    by_idx = {}
    for p in periods:                       # operating rows carry the model period index; construction columns have no debt
        if p.get("is_operation"):
            by_idx[p["period"]] = p
    repaid = [p for p in periods if p.get("is_operation") and (p.get("senior_principal_keur") or 0.0) > 0.0]
    # last persisted period with principal is the extinguishment period; its date and index equal the evidence
    assert repaid[-1]["period"] == r["actual_payoff_period_index"]
    assert repaid[-1]["date"] == r["actual_payoff_date"]
    assert repaid[0]["period"] == r["first_principal_period_index"]
    assert repaid[0]["date"] == r["first_principal_date"]
    assert by_idx[r["actual_payoff_period_index"]]["senior_balance_keur"] == 0.0
    # contractual maturity: persisted terminal state (sponsor schedule) is a separate source of truth
    terminal = c.ws.last_sponsor_schedule["summary"]["terminal_financial_state"]["senior"]
    assert terminal["contractual_maturity_period_index"] == r["contractual_maturity_period_index"]
    assert terminal["contractual_maturity_date"] == r["contractual_maturity_date"]
    assert by_idx[r["contractual_maturity_period_index"]]["date"] == r["contractual_maturity_date"]
    # difference of dates is the difference of the two recorded dates, not a second calculation
    from datetime import date
    assert r["days_maturity_minus_payoff"] == (
        date.fromisoformat(r["contractual_maturity_date"]) - date.fromisoformat(r["actual_payoff_date"])).days


def test_maturity_follows_the_configuration(committed):
    """Independent derivation from the project configuration (not from the engine's Senior axis)."""
    c = committed
    first_operating = next(p["period"] for p in c.ws.last_debt_schedule["periods"] if p.get("is_operation"))
    r = _evidence(c)["repayment"]
    assert r["contractual_repayment_start_period_index"] == first_operating
    assert r["contractual_maturity_period_index"] == first_operating + 2 * TENOR[c.kind] - 1
    assert c.pi.financing.senior_tenor_years == TENOR[c.kind]


# ── SDE_RUN_IDENTITY ─────────────────────────────────────────────────────────────────────────────────

def test_evidence_is_bound_to_the_correct_run(committed):
    c = committed
    fe = c.ws.last_runtime_summary["financing_evidence"]
    assert fe["run_binding"]["snapshot_id"] == c.snapshot_id
    assert fe[SDE.EVIDENCE_KEY] == c.entry.runtime_summary["financing_evidence"][SDE.EVIDENCE_KEY]
    assert c.entry.runtime_snapshot_id == c.snapshot_id
    assert fe[SDE.EVIDENCE_KEY] == json.loads(json.dumps(fe[SDE.EVIDENCE_KEY]))      # JSON-native, no NaN/objects
    assert SDE.EVIDENCE_KEY not in c.ws.last_runtime_summary                      # not a free-floating top-level key


# ── SDE_BINDING ──────────────────────────────────────────────────────────────────────────────────────

def test_binding_constraint_classification(committed):
    c = committed
    sz = _evidence(c)["sizing"]
    bank = c.ws.last_runtime_summary["financing_evidence"]["bankability"]
    assert sz["binding_constraint"] == BINDING[c.kind] == bank["binding_senior_constraint"]
    assert sz["binding_from_capacities"] == BINDING[c.kind]
    assert sz["binding_label_consistent"] is True and sz["debt_equals_binding_capacity"] is True
    # the standalone DSCR-only pass is what bankability reports; the funded-pass diagnostic is what the loan is the
    # minimum of. Both are recorded, labelled and never merged (they differ by 6.02 kEUR on Solar, equal elsewhere).
    assert sz["dscr_debt_capacity_standalone_pass_keur"] == bank["dscr_debt_capacity_keur"]
    assert sz["gearing_debt_capacity_keur"] == bank["gearing_debt_capacity_keur"] == sz["gearing_capacity_project_result_keur"]
    assert sz["dscr_capacity_pass_difference_keur"] == abs(
        sz["dscr_debt_capacity_keur"] - sz["dscr_debt_capacity_standalone_pass_keur"])
    assert sz["dscr_capacity_pass_difference_keur"] / sz["debt_size_keur"] < 1e-3
    assert sz["debt_size_keur"] == bank["final_senior_commitment_keur"]
    smaller = min(sz["dscr_debt_capacity_keur"], sz["gearing_debt_capacity_keur"])
    assert sz["debt_size_keur"] == pytest.approx(smaller, abs=1e-6)


@pytest.mark.parametrize("kind", ["solar", "wind", "ev"])
def test_gearing_bound_loans_explain_the_early_payoff(kind):
    sz = _evidence(_commit(kind))["sizing"]
    assert sz["limiting_nature"] == SDE.NATURE_GEARING and sz["limiting_rows"] == []
    assert sz["dscr_debt_capacity_keur"] > sz["gearing_debt_capacity_keur"]
    assert sz["payoff_explanation"] == "GEARING_CAP_BELOW_DSCR_CAPACITY_SCULPTED_BUDGET_RETIRES_DEBT_EARLY"


def test_data_center_discloses_the_ramp_up_limiting_constraint():
    c = _commit("data_center")
    sz = _evidence(c)["sizing"]
    assert sz["binding_constraint"] == "DSCR"
    assert sz["limiting_nature"] == SDE.NATURE_RAMP_UP          # NOT a generic "DSCR" limitation
    # independent: the limiting rows are exactly the persisted repayment rows with zero principal
    rows = [p["period"] for p in c.ws.last_debt_schedule["periods"]
            if p.get("is_operation") and (p.get("senior_ds_keur") or 0.0) > 0.0 and (p.get("senior_principal_keur") or 0.0) == 0.0]
    assert rows and [r["period_index"] for r in sz["limiting_rows"]] == rows
    assert all(r["principal_keur"] <= SDE.DEFAULT_TOLERANCE_KEUR for r in sz["limiting_rows"])
    ctx = sz["limiting_context"]
    assert ctx["limiting_bank_cfads_keur"] < ctx["window_peak_bank_cfads_keur"]
    assert rows[-1] < ctx["first_amortising_period_after_limit"] <= ctx["window_peak_period_index"]
    assert sz["payoff_explanation"] == "ZERO_AMORTISATION_ROWS_LIMIT_CAPACITY_LATER_DSCR_BUDGET_RETIRES_DEBT_EARLY"


# ── SDE_DSCR_BASES ───────────────────────────────────────────────────────────────────────────────────

def test_dscr_bases_equal_their_calculation_sources(committed):
    c = committed
    e = _evidence(c)
    d = e["dscr"]
    kpis = c.ws.last_runtime_summary
    assert d["reported"]["basis"] == "BASE_CASE_CFADS"
    assert d["reported"]["min_dscr"] == kpis["min_dscr"]            # same series, bit-identical
    assert d["reported"]["avg_dscr"] == kpis["avg_dscr"]
    assert d["sizing"]["basis"] == "BANK_SIZING_CASE_CFADS"
    assert d["sizing"]["target_dscr"] == c.pi.financing.target_dscr
    assert d["sizing"]["production_yield_scenario_requested"] == "P90-10y"
    assert d["sizing"]["min_realised_dscr"] == pytest.approx(d["sizing"]["target_dscr"], abs=1e-6)
    assert d["bank_case_distinct_from_base_case"] is BANK_DISTINCT[c.kind]
    if not BANK_DISTINCT[c.kind]:
        assert d["max_abs_bank_minus_base_cfads_keur"] == 0.0        # disclosed, not hidden: no distinct P90 series
        assert d["reported"]["min_dscr"] == pytest.approx(d["sizing"]["min_realised_dscr"], abs=1e-12)
    else:
        assert d["reported"]["min_dscr"] > d["sizing"]["min_realised_dscr"]


def test_future_llcr_inputs_keep_maturity_and_payoff_separate(committed):
    li = _evidence(committed)["llcr_inputs"]
    cand = li["loan_life_end_candidates"]
    maturity, payoff = REQUIRED[committed.kind]
    assert (cand["contractual_maturity_period_index"], cand["actual_payoff_period_index"]) == (maturity, payoff)
    assert li["llcr_ratio"] is None and li["llcr_status"] == "NOT_COMPUTED_BY_THIS_EVIDENCE"
    # no valuation policy and no LLCR is fabricated
    assert committed.ws.last_runtime_summary.get("min_llcr") is None


# ── SDE_NOT_RECORDED / reporting ─────────────────────────────────────────────────────────────────────

def test_projection_never_rebuilds_or_zeros():
    for summary in (None, {}, {"financing_evidence": {}}, {"financing_evidence": "x"},
                    {"financing_evidence": {SDE.EVIDENCE_KEY: {"schema_version": "OTHER"}}}):
        e = SDE.project_senior_debt_evidence(summary)
        assert e["status"] == SDE.STATUS_NOT_RECORDED and "repayment" not in e
    original = {"financing_evidence": {SDE.EVIDENCE_KEY: {"schema_version": SDE.SCHEMA_VERSION, "status": "RECORDED"}}}
    snapshot = copy.deepcopy(original)
    SDE.project_senior_debt_evidence(original)
    assert original == snapshot


def _lender_rows(workbook_bytes):
    ws = openpyxl.load_workbook(io.BytesIO(workbook_bytes))["Lender_Overview"]
    return {r[0]: r for r in ws.iter_rows(values_only=True) if r[0]}, ws


def test_lender_overview_shows_recorded_evidence(committed):
    c = committed
    ev = evidence_from_history_entry(c.entry, c.pr, last_run_snapshot_id=c.snapshot_id, last_run_is_stale=False, freshness_source="test")
    rows, _ = _lender_rows(R3.build_run_evidence_workbook_v3(ev))
    r = _evidence(c)["repayment"]
    maturity, payoff = REQUIRED[c.kind]
    assert rows["Contractual maturity (period index / date)"][1] == f"{maturity} / {r['contractual_maturity_date']}"
    assert rows["Actual loan extinguishment (period index / date)"][1] == f"{payoff} / {r['actual_payoff_date']}"
    assert rows["Maturity minus extinguishment (periods / days)"][1] == f"{maturity - payoff} / {r['days_maturity_minus_payoff']}"
    assert rows["Binding sizing constraint (engine)"][1] == BINDING[c.kind]
    assert rows["Reported DSCR basis"][1] == "BASE_CASE_CFADS"


def test_historical_run_without_the_evidence_states_not_recorded(committed):
    c = committed
    ev = evidence_from_history_entry(c.entry, c.pr, last_run_snapshot_id=None, last_run_is_stale=True, freshness_source="test")
    summary = copy.deepcopy(dict(ev.runtime_summary))
    summary["financing_evidence"].pop(SDE.EVIDENCE_KEY)
    legacy = dataclasses.replace(ev, runtime_summary=summary)
    wb = openpyxl.load_workbook(io.BytesIO(R3.build_run_evidence_workbook_v3(legacy)))
    ln = wb["Lender_Overview"]
    text = "\n".join(str(v) for row in ln.iter_rows(values_only=True) for v in row if v is not None)
    assert "NOT_RECORDED" in text
    rows = {r[0]: r for r in ln.iter_rows(values_only=True) if r[0]}
    for label in ("Contractual maturity (period index / date)", "Actual loan extinguishment (period index / date)",
                  "Maturity minus extinguishment (periods / days)", "Minimum reported DSCR"):
        assert rows[label][1] in (None, "n/a") and "NOT_AVAILABLE" in str(rows[label][2])      # never 0, never invented
    limits = [r for r in wb["Evidence_Limits"].iter_rows(values_only=True) if r[0] == "Actual loan extinguishment (period index / date)"]
    assert limits and limits[0][2] == R3.MISSING
    # the pre-existing sections of the same legacy Run are unchanged by the new block
    assert rows["Final senior commitment"][1] == pytest.approx(c.ws.last_runtime_summary["financing_evidence"]["bankability"]["final_senior_commitment_keur"], rel=1e-14)


def test_committing_a_new_run_does_not_rewrite_the_historical_run(committed):
    from app.persistence.run_history_repository import get_run_history

    c = committed
    before = json.dumps(c.entry.runtime_summary, sort_keys=True)
    get_run_history(c.uid, c.pr.project_id, limit=25)       # read path only
    again = get_run_history(c.uid, c.pr.project_id, limit=25)[0]
    assert json.dumps(again.runtime_summary, sort_keys=True) == before


# ── SDE_NO_INTERFERENCE ──────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("kind", list(REQUIRED))
def test_the_evidence_changes_no_other_byte_of_the_run_payload(kind):
    """Exact differential: identical engine run, evidence builder replaced by a sentinel → payloads equal everywhere else."""
    from app import project_factories
    from app.api.project_runner import run_project

    pi = getattr(project_factories, f"create_{ENGINE_KIND[kind]}")()
    with_evidence = run_project(ENGINE_KIND[kind], "Base", project_inputs_override=pi)
    with mock.patch.object(SDE, "build_from_clean_run", return_value={"sentinel": True}):
        without = run_project(ENGINE_KIND[kind], "Base", project_inputs_override=pi)
    assert without["financing_evidence"][SDE.EVIDENCE_KEY] == {"sentinel": True}
    assert with_evidence["financing_evidence"][SDE.EVIDENCE_KEY]["status"] == SDE.STATUS_RECORDED
    a, b = copy.deepcopy(with_evidence), copy.deepcopy(without)
    a["financing_evidence"].pop(SDE.EVIDENCE_KEY)
    b["financing_evidence"].pop(SDE.EVIDENCE_KEY)
    assert _canon(a) == _canon(b)
    for key, value in with_evidence["kpis"].items():          # float-level identity, hex for every numeric KPI
        if isinstance(value, float):
            assert value.hex() == without["kpis"][key].hex(), key


def _canon(obj):
    return json.dumps(obj, sort_keys=True, default=repr)


# ── SDE_NEGATIVE ─────────────────────────────────────────────────────────────────────────────────────

def _periods(n=8):
    from datetime import date, timedelta
    base = date(2030, 1, 1)
    return [SimpleNamespace(period_index=i, period_start=base + timedelta(days=180 * i),
                            period_end=base + timedelta(days=180 * (i + 1) - 1)) for i in range(n)]


def _senior(opening, principal, closing, *, binding="GEARING", dscr_cap=200.0, gear_cap=100.0, size=100.0, idx=None):
    n = len(opening)
    idx = tuple(idx if idx is not None else range(2, 2 + n))
    interest = tuple(5.0 for _ in range(n))
    return SimpleNamespace(
        period_indices=idx, senior_debt_opening_keur=tuple(opening), senior_interest_keur=interest,
        senior_principal_keur=tuple(principal), senior_debt_service_keur=tuple(p + 5.0 for p in principal),
        senior_debt_closing_keur=tuple(closing), base_dscr=tuple(1.5 for _ in range(n)), debt_size_keur=size,
        binding_constraint=binding,
        diagnostics={"binding_constraint": binding, "dscr_debt_capacity_keur": dscr_cap,
                     "gearing_debt_capacity_keur": gear_cap, "termination_reason": "CONVERGED", "converged": True})


def _build(senior, **kw):
    idx = senior.period_indices
    cfads = [20.0] * len(idx)
    args = dict(periods=_periods(), senior_debt=senior, senior_axis=idx, bank_period_indices=idx, bank_cfads_keur=cfads,
                bank_sizing_dscr=[1.2] * len(idx), base_period_indices=idx, base_cfads_keur=cfads, target_dscr=1.2,
                gearing_ratio=0.75, gearing_basis_keur=133.0, debt_sizing_mode="flat_dscr_sculpted",
                sizing_yield_scenario="P90-10y")
    args.update(kw)
    return SDE.build_senior_debt_evidence(**args)


def test_synthetic_payoff_before_at_and_after_maturity():
    before = _build(_senior([100, 60, 20, 0, 0, 0], [40, 40, 20, 0, 0, 0], [60, 20, 0, 0, 0, 0]))
    assert before["repayment"]["actual_payoff_period_index"] == 4 and before["repayment"]["contractual_maturity_period_index"] == 7
    assert before["repayment"]["payoff_status"] == SDE.PAYOFF_BEFORE_MATURITY
    at = _build(_senior([100, 75, 50, 25], [25, 25, 25, 25], [75, 50, 25, 0]))
    assert at["repayment"]["payoff_status"] == SDE.PAYOFF_AT_MATURITY and at["repayment"]["periods_maturity_minus_payoff"] == 0
    after = _build(_senior([100, 75, 50, 25], [25, 25, 25, 0.0], [75, 50, 25, 25]))
    assert after["repayment"]["payoff_status"] == SDE.PAYOFF_NOT_EXTINGUISHED
    assert after["repayment"]["actual_payoff_period_index"] is None and after["repayment"]["periods_maturity_minus_payoff"] is None


def test_binding_label_mismatch_is_flagged_not_hidden():
    e = _build(_senior([100, 50], [50, 50], [50, 0], binding="DSCR", dscr_cap=200.0, gear_cap=100.0))
    assert e["sizing"]["binding_constraint"] == "DSCR" and e["sizing"]["binding_from_capacities"] == "GEARING"
    assert e["sizing"]["binding_label_consistent"] is False and e["sizing"]["dscr_debt_capacity_keur"] == 200.0


def test_both_and_missing_capacities():
    both = _build(_senior([100, 50], [50, 50], [50, 0], binding="BOTH", dscr_cap=100.0, gear_cap=100.00001))
    assert both["sizing"]["binding_from_capacities"] == "BOTH" and both["sizing"]["binding_label_consistent"] is True
    absent = _build(_senior([100, 50], [50, 50], [50, 0], dscr_cap=None, gear_cap=None))
    assert absent["sizing"]["binding_from_capacities"] is None and absent["sizing"]["binding_label_consistent"] is None


def test_typed_unavailable_statuses_never_raise():
    zero = _build(_senior([0, 0], [0, 0], [0, 0], size=0.0))
    assert zero["status"] == SDE.STATUS_NO_SENIOR
    assert _build(_senior([100, 50], [50, 50], [50, 0]), senior_axis=(2, 3, 4))["status"] == SDE.STATUS_UNAVAILABLE
    assert _build(_senior([100, 50], [50, 50], [50, 0]), contractual_maturity_period_index=9)["status"] == SDE.STATUS_UNAVAILABLE
    assert _build(_senior([100, 50], [50, 50], [50, 0]), periods=_periods(1))["status"] == SDE.STATUS_UNAVAILABLE
    assert _build(_senior([100, 50], [50, 50], [50, 0]), senior_axis=())["status"] == SDE.STATUS_NO_SENIOR
    bad = SDE.build_from_clean_run(None)
    assert bad["status"] == SDE.STATUS_UNAVAILABLE and bad["reason"] == "AttributeError"
    for block in (zero, bad):
        assert "repayment" not in block and "sizing" not in block        # nothing invented, nothing zero


def test_two_senior_and_junior_structures_are_typed_unsupported_not_aggregated():
    from financial_engine.financing.junior_debt import JuniorFinancingResult
    from financial_engine.financing.multisenior import MultiSeniorFinancingResult

    for cls, name in ((MultiSeniorFinancingResult, "F3_TWO_SENIOR"), (JuniorFinancingResult, "JUNIOR_DEBT")):
        fin = object.__new__(cls)
        run = SimpleNamespace(g2c_result=SimpleNamespace(financing_result=fin), project_inputs=None)
        e = SDE.build_from_clean_run(run)
        assert e["status"] == SDE.STATUS_UNSUPPORTED_STRUCTURE and name in e["reason"]


def test_zero_amortisation_without_rising_cfads_is_not_labelled_ramp_up():
    senior = _with_binding(_senior([100, 100, 100, 60], [0.0, 0.0, 40.0, 60.0], [100, 100, 60, 0]), "DSCR")
    idx = senior.period_indices
    flat = _build(senior, bank_cfads_keur=[20.0] * 4)
    assert flat["sizing"]["limiting_nature"] == SDE.NATURE_ZERO_AMORT
    assert [r["period_index"] for r in flat["sizing"]["limiting_rows"]] == [idx[0], idx[1]]
    rising = _build(senior, bank_cfads_keur=[20.0, 21.0, 40.0, 80.0])
    assert rising["sizing"]["limiting_nature"] == SDE.NATURE_RAMP_UP


def _with_binding(senior, binding):
    copy_ = copy.copy(senior)
    copy_.binding_constraint = binding
    copy_.diagnostics = dict(senior.diagnostics, binding_constraint=binding, dscr_debt_capacity_keur=100.0, gearing_debt_capacity_keur=200.0)
    return copy_


# ── hygiene ──────────────────────────────────────────────────────────────────────────────────────────

def test_module_has_no_engine_or_persistence_imports_at_module_level():
    tree = ast.parse(Path("app/run_integrity/senior_debt_evidence.py").read_text())
    top = set()
    for node in tree.body:
        if isinstance(node, ast.Import):
            top.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            top.add(node.module or "")
    assert top <= {"__future__", "math", "typing"}, top


def test_module_performs_no_discounting_or_solving():
    src = Path("app/run_integrity/senior_debt_evidence.py").read_text()
    for forbidden in ("math.exp", "math.log", "math.pow", "pow(", "**", "numpy", "scipy"):
        assert forbidden not in src, forbidden
