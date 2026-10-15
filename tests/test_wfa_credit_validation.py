"""WF-A credit validation: independent DSCR / gearing / sizing / lock-up identities on real committed Runs.

Positive tests run the four verticals and the F3 two-Senior case through the real product.  Negative tests tamper a
copy of the persisted evidence and require a FAIL (or fail-closed NOT_COMPARABLE) — a successful Run is never a PASS
by itself.  Nothing here changes the engine, tolerances or goldens.
"""
from copy import deepcopy
from decimal import Decimal

import pytest

from tests import wfa_cases as C
from tests import wfa_support as S
from tools.numerical_validation import credit
from tools.numerical_validation.reconcile import ReconciliationInputError


@pytest.fixture(scope="module")
def lab(tmp_path_factory):
    lab = S.make_lab(tmp_path_factory)
    yield lab
    lab.patch.undo()


@pytest.fixture(scope="module")
def solar(lab):
    case = C.build_case(lab, "solar", "base", "combined", "base")
    assert case.committed, case.reason
    return case


def fails(result, identity=None):
    return [o for o in result["outcomes"] if o["status"] == "FAIL" and (identity is None or o["identity"] == identity)]


def reseal(evidence):
    import hashlib
    from tools.numerical_validation.reconcile import canonical_bytes
    evidence["sha256"] = hashlib.sha256(canonical_bytes({k: v for k, v in evidence.items() if k != "sha256"})).hexdigest()
    return evidence


def recredit(case, bundle=None, evidence=None):
    return credit.reconcile_credit(bundle or case.bundle, evidence or case.credit)


@pytest.mark.parametrize("kind", ["solar", "wind", "data_center", "ev_charging"])
def test_real_run_credit_identities_have_no_fail(lab, kind):
    case = C.build_case(lab, kind, "base", "combined", "base")
    assert case.committed, case.reason
    assert not fails(case.result), fails(case.result)[:3]
    passed = {o["identity"] for o in case.result["outcomes"] if o["status"] == "PASS" and o["identity"].startswith("CR-")}
    assert {"CR-GEARING-DEF", "CR-DSCR-MIN", "CR-DSCR-AVG", "CR-LOCKUP-COUNT"} <= passed


def test_two_senior_run_reports_sized_debt_not_comparable_never_a_false_pass(lab, monkeypatch):
    from app.workbook import multisenior_config as f3
    from tests.test_model_financing_f3_workspace import collection_for_inputs, state
    from tests.test_model_financing_f2 import save
    monkeypatch.setattr(f3, "ACTIVATION_ENABLED", True)
    record = S.project("solar", "two-senior")
    from app.persistence.workspace_repository import get_workspace_state
    from app.workbook.input_set import ProjectInputSet
    pi = ProjectInputSet.from_snapshot(get_workspace_state(S.USER, record.project_id).draft_snapshot).to_projectinputs()
    env = type("E", (), {"client": lab.client})()
    # reuse the F3 save helper through the lab client (full app mounts the same /v2 routes)
    save(env, record, state(active=True, collection=collection_for_inputs(pi)), field=f3.FIELD_ID)
    entry = S.commit_run(lab, record)
    from tools.numerical_validation.source import bundle_from_history_entry
    bundle = bundle_from_history_entry(entry)
    ev = credit.credit_evidence_from_entry(entry, bundle, declared={"lockup_dscr": C.declared_lockup(record)})
    result = credit.reconcile_credit(bundle, ev)
    assert not fails(result)
    sized = [o for o in result["outcomes"] if o["identity"] == "CR-SIZED-DEBT"]
    assert sized and all(o["status"] == "NOT_COMPARABLE" for o in sized)


# ───────────── negative: tamper a copy of the persisted evidence ─────────────
def test_tampered_min_dscr_fails(solar):
    ev = deepcopy(solar.credit)
    ev["summary"]["min_dscr"] = str(Decimal(ev["summary"]["min_dscr"]) + Decimal("0.01"))
    assert fails(recredit(solar, evidence=reseal(ev)), "CR-DSCR-MIN")


def test_tampered_average_dscr_fails(solar):
    ev = deepcopy(solar.credit)
    ev["summary"]["avg_dscr"] = str(Decimal(ev["summary"]["avg_dscr"]) * 2)
    assert fails(recredit(solar, evidence=reseal(ev)), "CR-DSCR-AVG")


def test_tampered_debt_service_denominator_fails(solar):
    b = deepcopy(solar.bundle)
    vals = b["series"]["ev.senior.debt_service"]["values"]
    k = next(k for k, v in vals.items() if v is not None and Decimal(str(v)) > 1)
    vals[k] = str(Decimal(str(vals[k])) * 3)
    r = recredit(solar, b)
    assert fails(r), "a changed DSCR denominator must be detected by at least one identity"


def test_tampered_senior_debt_fails_gearing_definition(solar):
    b = deepcopy(solar.bundle)
    b["scalars"]["su.senior_debt_keur"]["value"] = str(Decimal(b["scalars"]["su.senior_debt_keur"]["value"]) + 50)
    assert fails(recredit(solar, b), "CR-GEARING-DEF")


def test_tampered_binding_label_fails(solar):
    ev = deepcopy(solar.credit)
    # claim GEARING binds while the recorded gearing sits 5 points below the cap
    ev["diagnostics"]["binding_constraint"] = "GEARING"
    ev["summary"]["actual_gearing_pct"] = str(Decimal(ev["summary"]["gearing_cap_pct"]) - 5)
    assert fails(recredit(solar, evidence=reseal(ev)), "CR-BINDING")


def test_tampered_lockup_flag_and_distribution_fail(solar):
    ev = deepcopy(solar.credit)
    row = next(p for p in ev["distribution_periods"] if p["is_operation"] and p["lockup_active"] is False)
    row["lockup_active"] = True
    r = recredit(solar, evidence=reseal(ev))
    assert fails(r, "CR-LOCKUP-COUNT") or fails(r, "CR-LOCKUP-DIST"), "locking a paying period must be detected"


def test_tampered_lockup_count_fails(solar):
    ev = deepcopy(solar.credit)
    ev["periods_in_lockup"] = (ev["periods_in_lockup"] or 0) + 3
    assert fails(recredit(solar, evidence=reseal(ev)), "CR-LOCKUP-COUNT")


def test_unsealed_edit_wrong_identity_and_missing_evidence_fail_closed(solar):
    ev = deepcopy(solar.credit)
    ev["summary"]["min_dscr"] = "9"
    r = recredit(solar, evidence=ev)          # hash not resealed
    assert not fails(r), "an unsealed edit must fail closed, never produce a numerical verdict"
    statuses = {o["status"] for o in r["outcomes"] if o["identity"].startswith("CR-")}
    assert statuses == {"NOT_COMPARABLE"}
    ev2 = deepcopy(solar.credit)
    ev2["identity"]["run_key"] = "0" * 64
    r2 = recredit(solar, evidence=reseal(ev2))
    assert {o["status"] for o in r2["outcomes"] if o["identity"].startswith("CR-")} == {"NOT_COMPARABLE"}
    ev3 = deepcopy(solar.credit)
    ev3["distribution_periods"] = None
    r3 = recredit(solar, evidence=reseal(ev3))
    assert not fails(r3, "CR-LOCKUP-FLAG")
    assert any(o["status"] == "UNAVAILABLE" for o in r3["outcomes"] if o["identity"].startswith("CR-LOCKUP"))


def test_wrong_unit_and_shifted_periods_are_detected(solar):
    b = deepcopy(solar.bundle)
    vals = b["series"]["ev.senior.debt_service"]["values"]
    for k in vals:                       # MEUR instead of kEUR
        if vals[k] is not None:
            vals[k] = str(Decimal(str(vals[k])) / 1000)
    assert fails(recredit(solar, b))
    b2 = deepcopy(solar.bundle)
    vals = b2["series"]["ev.senior.base_cfads"]["values"]
    keys = sorted(vals)
    shifted = {keys[i]: vals[keys[i - 1]] for i in range(1, len(keys))}
    shifted[keys[0]] = vals[keys[0]]
    b2["series"]["ev.senior.base_cfads"]["values"] = shifted
    assert fails(recredit(solar, b2))


def test_unsupported_declared_inputs_are_rejected(solar):
    for bad in ({"llcr_floor": 1.2}, {"cash_sweep_pct": 50}, {"sizing_mode": "SCULPTED_LLCR"}):
        with pytest.raises(ReconciliationInputError):
            credit.credit_evidence_from_entry(solar.entry, solar.bundle, declared=bad)


# ───────────── boundaries ─────────────
def _period_dscr(case):
    b = case.bundle
    ds = b["series"]["ev.senior.debt_service"]["values"]
    base = b["series"]["ev.senior.base_cfads"]["values"]
    return {k: Decimal(str(base[k])) / Decimal(str(ds[k])) for k in ds
            if ds[k] is not None and Decimal(str(ds[k])) > credit.DEBT_SERVICE_FLOOR and base.get(k) is not None}


def test_lockup_threshold_is_strictly_below(solar):
    ratios = _period_dscr(solar)
    key, exact = min(ratios.items(), key=lambda kv: kv[1])
    import math
    at = Decimal(repr(math.floor(float(exact) * 1e9) / 1e9))      # declared thresholds are floats; this is <= the ratio
    base = credit.credit_evidence_from_entry(solar.entry, solar.bundle, declared={"lockup_dscr": float(at)})
    r_eq = credit.reconcile_credit(solar.bundle, base)
    flag_eq = [o for o in r_eq["outcomes"] if o["identity"] == "CR-LOCKUP-FLAG" and o["period"] == key]
    # threshold at (just under) the period DSCR: not below => gate is expected open => the persisted open gate passes
    assert flag_eq and all(o["status"] == "PASS" for o in flag_eq)
    above = credit.credit_evidence_from_entry(solar.entry, solar.bundle, declared={"lockup_dscr": float(at + Decimal("2e-9"))})
    r_above = credit.reconcile_credit(solar.bundle, above)
    flag_above = [o for o in r_above["outcomes"] if o["identity"] == "CR-LOCKUP-FLAG" and o["period"] == key]
    # just above: the gate would have to be closed; the persisted gate is open => detected, never silently passed
    assert flag_above and all(o["status"] == "FAIL" for o in flag_above)


def test_zero_debt_service_periods_report_no_dscr(solar):
    r = solar.result
    nods = [o for o in r["outcomes"] if o["identity"] == "CR-DSCR-NODS"]
    assert not [o for o in nods if o["status"] != "PASS"], "a period without debt service must never carry a reported DSCR"


def test_terminal_tolerance_and_floor_are_the_documented_constants():
    assert credit.TERMINAL_TOLERANCE_KEUR == Decimal("1e-4") and credit.DEBT_SERVICE_FLOOR == Decimal("1e-6")


def test_lender_case_rag_thresholds_boundaries():
    from types import SimpleNamespace
    from app.services import lender_case_service as L
    def rag(d):
        p = SimpleNamespace(is_operation=True, period=1, dscr=d, date=None)
        return L.build_covenant_periods(SimpleNamespace(periods=[p]))[0]["rag"]
    eps = 1e-9
    assert rag(None) == "na"
    assert rag(L.DSCR_EVENT_OF_DEFAULT - eps) == "breach" and rag(L.DSCR_EVENT_OF_DEFAULT) == "warning"
    assert rag(L.DSCR_LOCKUP - eps) == "warning" and rag(L.DSCR_LOCKUP) == "caution"
    assert rag(L.DSCR_DISTRIBUTION - eps) == "caution" and rag(L.DSCR_DISTRIBUTION) == "ok"


def test_unsupported_credit_metrics_are_never_derived(solar):
    caps = {u["capability"] for u in solar.credit["unsupported"]}
    assert {"llcr", "plcr", "event_of_default", "cash_sweep"} <= caps
    assert solar.credit["summary"]["min_llcr"] is None


def test_deterministic_reports(solar):
    a = credit.assessment_reports(credit.reconcile_credit(solar.bundle, solar.credit))
    b = credit.assessment_reports(credit.reconcile_credit(solar.bundle, solar.credit))
    assert a == b and a


def test_stale_working_copy_does_not_change_committed_run_evidence(lab, solar):
    from app.persistence.workspace_repository import get_workspace_state
    record = S.project("solar", "stale")
    entry = S.commit_run(lab, record)
    S.update_field(lab, record, "debt.senior.target_dscr", 1.5)
    from app.persistence.run_history_repository import get_latest_history_entry
    again = get_latest_history_entry(S.USER, record.project_id)
    assert again.runtime_summary == entry.runtime_summary
    assert get_workspace_state(S.USER, record.project_id).dirty
