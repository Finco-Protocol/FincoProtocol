"""M3 — two-driver sensitivity matrix and threshold/bracket analysis.

Pure projection tests, real Solar / Wind / Data Center canonical-run parity against INDEPENDENTLY constructed
combined-shock runs, route security and rejection tests, failure handling, and a no-persistence proof.
"""
from __future__ import annotations

import re
from dataclasses import replace
from types import SimpleNamespace

import pytest

from app.v2 import sensitivity_matrix_projection as proj
from app.v2.sensitivity_matrix_projection import (
    MatrixRequestError, build_matrix, classify, drivers_for, format_delta, parse_levels, parse_threshold,
    resolve_pair,
)
from tests.test_model_decision_workspace_v2 import env  # noqa: F401  (fixture)

USER = "decision-user"
RUN = "/v2/workbook/sensitivity/matrix/run"
FORM = "/v2/workbook/decision/sensitivity"      # the Sensitivity sheet hosts the matrix form


# ── pure projection ─────────────────────────────────────────────────────────────────────────────────────────────
def test_levels_defaults_sorted_unique_bounded():
    spec = proj.DRIVERS["capex"]
    assert parse_levels("", spec) == (-10, 0, 10)                       # 3 x 3 is the default
    assert parse_levels("", spec, 5) == (-20, -10, 0, 10, 20)           # 5 x 5 only as an explicit choice
    assert parse_levels("", proj.DRIVERS["interest_rate"]) == (-100, 0, 100)
    assert parse_levels("", proj.DRIVERS["generation"]) == (-5, 0, 5)
    assert proj.parse_grid_size(None) == 3 and proj.parse_grid_size("5") == 5
    with pytest.raises(MatrixRequestError) as bad_grid:
        proj.parse_grid_size("4")
    assert bad_grid.value.code == "MATRIX_GRID_INVALID"
    assert parse_levels("10, -10, 0", spec) == (-10, 0, 10)             # ascending regardless of input order
    for bad, code in (("1,2", "MATRIX_LEVEL_COUNT"), ("1,2,3,4,5,6", "MATRIX_LEVEL_COUNT"),
                      ("1,1,2", "MATRIX_LEVEL_DUPLICATE"), ("a,b,c", "MATRIX_LEVEL_INVALID"),
                      ("-10,0,51", "MATRIX_LEVEL_OUT_OF_BOUNDS"), ("nan,0,1", "MATRIX_LEVEL_INVALID"),
                      ("-100,0,10", "MATRIX_LEVEL_OUT_OF_BOUNDS")):
        with pytest.raises(MatrixRequestError) as exc:
            parse_levels(bad, spec)
        assert exc.value.code == code


def test_pair_rules_by_vertical():
    assert {d.key for d in drivers_for("data_center")} >= {"capex", "opex", "dc_pue", "interest_rate", "gearing"}
    assert "tariff" not in {d.key for d in drivers_for("data_center")}
    assert "dc_pue" not in {d.key for d in drivers_for("solar")}
    for a, b, v, code in (("capex", "capex", "solar", "MATRIX_DRIVER_DUPLICATE"),
                          ("capex", "nope", "solar", "MATRIX_DRIVER_UNSUPPORTED"),
                          ("tariff", "capex", "data_center", "MATRIX_DRIVER_UNSUPPORTED"),
                          ("capex", "opex", None, "MATRIX_VERTICAL_UNSUPPORTED")):
        with pytest.raises(MatrixRequestError) as exc:
            resolve_pair(a, b, v)
        assert exc.value.code == code
    assert proj.vertical_key("EV Charging") is None


def test_threshold_units_and_classification():
    assert parse_threshold("9", "pct") == pytest.approx(0.09)
    assert parse_threshold("1.2x", "ratio") == pytest.approx(1.2)
    assert parse_threshold("", "pct") is None
    with pytest.raises(MatrixRequestError):
        parse_threshold("abc", "pct")
    assert classify(0.09, 0.09) == proj.TH_PASS and classify(0.0899, 0.09) == proj.TH_FAIL
    assert classify(None, 0.09) == proj.TH_UNAVAILABLE and classify(0.5, None) == proj.TH_NONE
    assert format_delta(0.0125, "pct") == "+1.25 pp" and format_delta(-0.5, "ratio") == "-0.500x"
    assert format_delta(1234.0, "keur") == "+1,234 kEUR" and format_delta(None, "pct") == "—"


def _outputs(values):
    return {(i, j): ({"kpis": {"equity_irr": v}} if not isinstance(v, str) else {"error": v})
            for (i, j), v in values.items()}


def test_matrix_projection_deltas_thresholds_brackets_and_unavailable():
    a, b = proj.DRIVERS["capex"], proj.DRIVERS["tariff"]
    la, lb = (-10.0, 0.0, 10.0), (-10.0, 0.0, 10.0)
    values = {(0, 0): 0.07, (1, 0): 0.08, (2, 0): 0.09, (0, 1): 0.085, (1, 1): 0.10, (2, 1): 0.11,
              (0, 2): "CALCULATION_TIMEOUT", (1, 2): None, (2, 2): 0.12}
    outs = _outputs({k: v for k, v in values.items()})
    outs[(1, 2)] = {"kpis": {}}                                   # metric missing -> UNAVAILABLE, never zero
    view = build_matrix(spec_a=a, spec_b=b, levels_a=la, levels_b=lb, metric_key="equity_irr", cell_outputs=outs,
                        base_output=outs[(1, 1)], threshold=0.085, shock_info={})
    by = {(c["i"], c["j"]): c for c in view["cells"]}
    assert by[(1, 1)]["is_base"] and by[(1, 1)]["delta"] == 0
    assert by[(2, 1)]["delta"] == pytest.approx(0.01) and by[(2, 1)]["delta_display"] == "+1.00 pp"
    assert by[(0, 2)]["status"] == "FAILED" and by[(0, 2)]["display"] == "—"
    assert by[(1, 2)]["status"] == "UNAVAILABLE" and by[(1, 2)]["raw"] is None
    assert by[(0, 0)]["threshold_status"] == "FAIL" and by[(2, 0)]["threshold_status"] == "PASS"
    assert by[(0, 1)]["threshold_status"] == "PASS" and by[(0, 2)]["threshold_status"] == "UNAVAILABLE"
    assert view["counts"] == {"OK": 7, "FAILED": 1, "UNAVAILABLE": 1}
    # brackets = adjacent definite PASS/FAIL pairs only; unavailable/failed neighbours never bracket
    pairs = {(b_["from"], b_["to"]) for b_ in view["brackets"]}
    assert (("Base", "−10 %"), ("−10 %", "−10 %")) not in pairs
    assert all({b_["from_status"], b_["to_status"]} == {"PASS", "FAIL"} for b_ in view["brackets"])
    assert any(b_["axis"] == "A" for b_ in view["brackets"]) and all("no boundary value" in b_["note"] for b_ in view["brackets"])
    assert view["threshold"]["origin"].startswith("User-provided")


def test_matrix_without_threshold_has_no_classification_or_brackets():
    a, b = proj.DRIVERS["capex"], proj.DRIVERS["opex"]
    outs = _outputs({(i, j): 0.1 + i * .01 for i in range(3) for j in range(3)})
    view = build_matrix(spec_a=a, spec_b=b, levels_a=(-10, 0, 10), levels_b=(-10, 0, 10), metric_key="equity_irr",
                        cell_outputs=outs, base_output=outs[(1, 1)], threshold=None, shock_info={})
    assert view["threshold"] is None and view["brackets"] == []
    assert {c["threshold_status"] for c in view["cells"]} == {"NOT_SET"}


def test_missing_base_gives_no_deltas():
    a, b = proj.DRIVERS["capex"], proj.DRIVERS["opex"]
    outs = _outputs({(i, j): 0.1 for i in range(3) for j in range(3)})
    view = build_matrix(spec_a=a, spec_b=b, levels_a=(-10, 0, 10), levels_b=(-10, 0, 10), metric_key="equity_irr",
                        cell_outputs=outs, base_output={"error": "x"}, threshold=None, shock_info={})
    assert view["base"]["status"] == "FAILED" and all(c["delta"] is None for c in view["cells"])


# ── metrics: supported / unsupported / legitimately unavailable ─────────────────────────────────────────────────
def test_metric_catalog_excludes_what_the_canonical_run_cannot_supply():
    keys = {m["key"] for m in proj.supported_metrics()}
    assert "total_cfads_keur" not in keys and "total_cfads_keur" in proj.UNSUPPORTED_METRICS
    assert {"project_irr", "equity_irr", "sponsor_irr", "min_dscr", "avg_dscr", "min_llcr", "senior_debt_keur",
            "total_ebitda_keur", "sponsor_moic", "pure_equity_moic", "project_npv_keur"} <= keys
    notes = {m["key"]: m["note"] for m in proj.supported_metrics()}
    assert notes["project_npv_keur"] and notes["min_llcr"] and not notes["project_irr"]
    with pytest.raises(MatrixRequestError) as exc:
        proj.resolve_metric("total_cfads_keur")
    assert exc.value.code == "MATRIX_METRIC_UNSUPPORTED" and "not recomputed" in exc.value.message


def test_enrich_kpis_projects_only_existing_summary_fields_never_computes():
    from app.services.sensitivity_matrix import enrich_kpis
    result = {"kpis": {"project_irr": 0.1, "min_llcr": None, "sponsor_irr": 0.09},
              "debt_schedule": {"summary": {"min_llcr": 1.8, "target_dscr": 1.2}},
              "sponsor_schedule": {"summary": {"total_sponsor_xirr": 0.5, "total_sponsor_moic": 2.5,
                                               "pure_equity_moic": 3.5}}}
    kpis = enrich_kpis(result)
    assert kpis["min_llcr"] == 1.8 and kpis["target_dscr"] == 1.2          # debt summary, source-key mapped
    assert kpis["sponsor_moic"] == 2.5 and kpis["pure_equity_moic"] == 3.5
    assert kpis["sponsor_irr"] == 0.09                                      # canonical kpi is never overwritten
    bare = enrich_kpis({"kpis": {"project_irr": 0.1}})                      # absent -> None, never 0
    assert bare.get("min_llcr") is None and bare["sponsor_moic"] is None and "total_cfads_keur" not in bare
    assert enrich_kpis({"kpis": {"min_llcr": 2.0}, "debt_schedule": {"summary": {"min_llcr": 9.9}}})["min_llcr"] == 2.0


def test_unsupported_metric_is_rejected_by_the_route_and_not_offered(env, fake):
    record = env.create("solar")
    f = fake()
    r = _post(env, record, driver_a="capex", driver_b="opex", metric="total_cfads_keur")
    assert r.status_code == 422 and 'data-code="MATRIX_METRIC_UNSUPPORTED"' in r.text and f.calls == []
    form = env.client.get(FORM, params={"project": record.project_code})
    assert 'value="total_cfads_keur"' not in form.text and 'value="sponsor_moic"' in form.text


def test_legitimately_unavailable_metric_is_unavailable_not_zero(env, fake):
    record = env.create("solar")
    fake(outputs=lambda n: [{"kpis": {"project_npv_keur": None, "min_llcr": None}} for _ in range(n)])
    for metric in ("project_npv_keur", "min_llcr"):
        r = _post(env, record, driver_a="capex", driver_b="opex", metric=metric, threshold="1")
        cells = _cells(r.text)
        assert set(cells.values()) == {("UNAVAILABLE", "UNAVAILABLE")}
        assert "0.00" not in _cell_values(r.text)[(0, 0)]


def test_real_run_supplies_sponsor_and_schedule_metrics_from_the_same_run(env):
    from app.api.project_runner import run_project  # noqa: F401  (oracle uses it)
    record = env.create("solar")
    sponsor = _post(env, record, driver_a="capex", driver_b="opex", metric="pure_equity_moic")
    cells = _cells(sponsor.text)
    assert sponsor.status_code == 200 and cells[(1, 1)][0] == "OK", sponsor.text[:300]
    oracle = _oracle_result(record, "Solar", [])
    expected = oracle["sponsor_schedule"]["summary"]["pure_equity_moic"]
    shown = float(_cell_values(sponsor.text)[(1, 1)].rstrip("x"))
    assert shown == pytest.approx(expected, abs=0.006)


# ── canonical-run parity (independent construction) ─────────────────────────────────────────────────────────────
def _canonical_pi(record):
    """Independent oracle: the canonical Run input chain, applied WITHOUT the matrix service."""
    from app.persistence.workspace_repository import get_workspace_state
    from app.services.capex_sub_lines_integration import apply_user_sub_lines_replacing_base
    from app.services.opex_sub_lines_integration import apply_user_sub_lines_to_opex
    from app.workbook.bankability_config import SNAPSHOT_KEY, assert_materialized_fee_authority
    from app.workbook.multisenior_config import SNAPSHOT_KEY as F3, apply_state
    from app.workbook.service import WorkbookService

    ws = get_workspace_state(USER, record.project_id)
    pis = WorkbookService.build_draft_input_set_from_workspace(ws)
    return pis, WorkbookService.to_projectinputs(pis), (apply_user_sub_lines_replacing_base,
                                                          apply_user_sub_lines_to_opex, SNAPSHOT_KEY,
                                                          assert_materialized_fee_authority, F3, apply_state)


def _oracle(record, runtime_key, shocks, *, field_overrides=None):
    return _oracle_result(record, runtime_key, shocks, field_overrides=field_overrides)["kpis"]


def _oracle_result(record, runtime_key, shocks, *, field_overrides=None):
    """Combined-shock canonical run through the ORIGINAL legacy typed shock service and run_project."""
    from app.api.project_runner import run_project
    from app.services.sensitivity_service import _apply_shock

    pis, pi, (fold_capex, fold_opex, bank_key, assert_fee, f3_key, apply_state) = _canonical_pi(record)
    for field_id, value in (field_overrides or {}).items():
        pis = pis.with_value(field_id, str(value))
    from app.workbook.service import WorkbookService
    pi = WorkbookService.to_projectinputs(pis)
    folded = fold_capex(pi.capex, project_id=record.project_id, scenario_overrides=None)
    pi = replace(pi, capex=folded) if folded is not pi.capex else pi
    folded_opex = fold_opex(pi.opex, project_id=record.project_id, scenario_overrides=None)
    pi = replace(pi, opex=folded_opex) if folded_opex is not pi.opex else pi
    for shock, level in shocks:
        pi = _apply_shock(pi, shock, level)
    assert_fee(pi, pis.snapshot_origin.get(bank_key))
    pi = apply_state(pi, pis.snapshot_origin.get(f3_key), "base", bankability_raw=pis.snapshot_origin.get(bank_key))
    return run_project(runtime_key, "Base", project_inputs_override=pi)


def _cells(html):
    out = {}
    for m in re.finditer(r'data-testid="matrix-cell" data-a="(\d+)" data-b="(\d+)" data-status="(\w+)" '
                         r'data-threshold="(\w+)"', html):
        out[(int(m.group(1)), int(m.group(2)))] = (m.group(3), m.group(4))
    return out


def _cell_values(html):
    vals = {}
    for m in re.finditer(r'data-a="(\d+)" data-b="(\d+)".*?<span class="v2-matrix-value">([^<]*)</span>', html, re.S):
        vals[(int(m.group(1)), int(m.group(2)))] = m.group(3).strip()
    return vals


def _post(env, record, **fields):
    data = dict(project=record.project_code, metric="equity_irr", levels_a="-10,0,10", levels_b="-10,0,10")
    data.update(fields)
    return env.client.post(RUN, data=data)


def _pct(text):
    return float(text.rstrip("%")) / 100.0


@pytest.mark.parametrize("kind,key,a,b,shock_a,shock_b", [
    ("solar", "Solar", "capex", "tariff", ("capex",), ("ppa_price",)),
    # generation is the workbook's canonical P50-hours FIELD driver (as in the one-driver route): the oracle
    # applies it through with_value, not through the legacy typed yield shock (a different, older mechanism).
    ("wind", "Wind", "opex", "generation", ("opex",), ("FIELD:project_setup.technical.p50_hours",)),
])
def test_cells_match_independent_combined_shock_runs(env, kind, key, a, b, shock_a, shock_b):
    record = env.create(kind)
    response = _post(env, record, driver_a=a, driver_b=b)
    assert response.status_code == 200, response.text[:300]
    cells, values = _cells(response.text), _cell_values(response.text)
    assert set(cells) == {(i, j) for i in range(3) for j in range(3)} and all(s == "OK" for s, _ in cells.values())
    levels = (-10.0, 0.0, 10.0)
    for (i, j) in ((0, 0), (2, 2), (0, 2), (2, 0), (1, 1)):          # corners (both shocks live) + Base/Base
        shocks, fields = [], {}
        for name, level in ((shock_a[0], levels[i]), (shock_b[0], levels[j])):
            if name.startswith("FIELD:"):
                field_id = name[6:]
                original = float(_canonical_pi(record)[0].values[field_id])
                fields[field_id] = original * (1.0 + level / 100.0)
            else:
                shocks.append((name, level))
        oracle = _oracle(record, key, shocks, field_overrides=fields)
        assert _pct(values[(i, j)]) == pytest.approx(oracle["equity_irr"], abs=6e-5), (i, j)   # display = 2dp %
    # both shocks truly applied: a corner differs from each single-shock edge cell and from Base
    assert len({values[(0, 0)], values[(2, 0)], values[(0, 2)], values[(1, 1)]}) == 4


def test_base_cell_equals_unshocked_base_and_is_reused(env):
    record = env.create("solar")
    html = _post(env, record, driver_a="capex", driver_b="opex").text
    assert "Base is the Base/Base cell." in html
    base = re.search(r'data-testid="matrix-base">([^<(]*)', html).group(1).strip()
    assert _cell_values(html)[(1, 1)] == base
    assert _pct(base) == pytest.approx(_oracle(record, "Solar", [])["equity_irr"], abs=6e-5)


def test_interest_rate_and_gearing_use_canonical_field_inputs_and_commute(env):
    record = env.create("solar")
    ab = _post(env, record, driver_a="interest_rate", driver_b="gearing", levels_a="-100,0,100", levels_b="-5,0,5")
    ba = _post(env, record, driver_a="gearing", driver_b="interest_rate", levels_a="-5,0,5", levels_b="-100,0,100")
    assert ab.status_code == ba.status_code == 200
    va, vb = _cell_values(ab.text), _cell_values(ba.text)
    for (i, j), text in va.items():                 # transposed grid: identical numbers, ordering irrelevant
        assert vb[(j, i)] == text
    pis, _pi, _f = _canonical_pi(record)
    rate0 = float(pis.values["debt.senior.interest_rate_pct"]) * 100.0        # seeded snapshot value is a RATIO
    gear0 = float(pis.values["debt.senior.gearing_pct"])
    oracle = _oracle(record, "Solar", [], field_overrides={"debt.senior.interest_rate_pct": rate0 + 1.0,
                                                           "debt.senior.gearing_pct": gear0 - 5.0})
    assert _pct(va[(2, 0)]) == pytest.approx(oracle["equity_irr"], abs=6e-5)   # +100 bps, -5 pp


def test_interest_rate_shock_is_in_basis_points_of_the_typed_rate(env):
    """Seeded snapshots store the rate as a ratio (0.055) while with_value takes percent: +100 bps must give 6.5 %."""
    from app.persistence.workspace_repository import get_workspace_state
    from app.services import sensitivity_matrix as svc
    record = env.create("solar")
    ws = get_workspace_state(USER, record.project_id)
    basis = svc.resolve_basis(workspace_owner=USER, project_record=record, ws=ws, scenario_id=None)
    spec = proj.DRIVERS["interest_rate"]
    for bps, expected in ((-100, 0.045), (0, 0.055), (100, 0.065), (200, 0.075)):
        pi, _pis, info = svc.pre_financing_inputs(basis, [(spec, float(bps))])
        rates = list(pi.financing.senior_debt_interest_config.rate_schedule.explicit_all_in_rates)
        assert rates and all(r == pytest.approx(expected) for r in rates), (bps, rates[:2])
    assert info["interest_rate"]["original"] == pytest.approx(5.5) and info["interest_rate"]["shocked"] == pytest.approx(7.5)


def test_calibrated_rate_schedule_fails_closed(env, monkeypatch):
    from app.persistence.workspace_repository import get_workspace_state
    from app.services import sensitivity_matrix as svc
    import app.input_adapter as adapter
    record = env.create("solar")
    basis = svc.resolve_basis(workspace_owner=USER, project_record=record,
                              ws=get_workspace_state(USER, record.project_id), scenario_id=None)
    monkeypatch.setattr(adapter, "senior_rate_authority", lambda pi: ("CALIBRATED", None, 3))
    with pytest.raises(svc.CellBuildError) as exc:
        svc.pre_financing_inputs(basis, [(proj.DRIVERS["interest_rate"], 100.0)])
    assert exc.value.code == "SENIOR_RATE_SCHEDULE_CALIBRATED"


def test_interest_rate_driver_refused_when_bankability_owns_the_rate(env, fake, monkeypatch):
    import app.input_adapter as adapter
    record = env.create("solar")
    f = fake()
    def owned(pis, field_id):
        raise ValueError("The bankability configuration owns this input. Edit or reset that configuration first.")
    monkeypatch.setattr(adapter, "assert_debt_scalar_edit_allowed", owned)
    r = _post(env, record, driver_a="interest_rate", driver_b="capex")
    assert r.status_code == 422 and 'data-code="MATRIX_DRIVER_NOT_APPLICABLE"' in r.text and f.calls == []


def test_capex_opex_typed_pair_is_order_independent(env):
    record = env.create("solar")
    ab = _cell_values(_post(env, record, driver_a="capex", driver_b="opex").text)
    ba = _cell_values(_post(env, record, driver_a="opex", driver_b="capex").text)
    assert all(ba[(j, i)] == v for (i, j), v in ab.items())


def test_data_center_pair_runs_and_renewable_drivers_are_rejected(env):
    record = env.create("data_center")
    ok = _post(env, record, driver_a="capex", driver_b="dc_pue", levels_a="-10,0,10", levels_b="-5,0,5")
    cells = _cells(ok.text)
    assert ok.status_code == 200 and set(s for s, _ in cells.values()) <= {"OK", "FAILED"}
    assert cells[(1, 1)][0] == "OK" and sum(1 for s, _ in cells.values() if s == "OK") >= 4
    if any(s == "FAILED" for s, _ in cells.values()):        # canonical engine fail-closed errors stay per-cell
        assert "PR8_CLEAN_ENGINE_FAIL_CLOSED" in ok.text
    bad = _post(env, record, driver_a="capex", driver_b="tariff")
    assert bad.status_code == 422 and 'data-code="MATRIX_DRIVER_UNSUPPORTED"' in bad.text


def test_ev_charging_is_rejected_not_substituted(env):
    record = env.create("ev_charging")
    r = _post(env, record, driver_a="capex", driver_b="opex")
    assert r.status_code == 422 and 'data-code="MATRIX_VERTICAL_UNSUPPORTED"' in r.text


# ── route validation, security, failures (fast; executor faked) ─────────────────────────────────────────────────
class _Fake:
    def __init__(self, outputs=None, exc=None):
        self.calls, self.outputs, self.exc = [], outputs, exc

    async def __call__(self, fn, runtime_key, batch):
        self.calls.append((runtime_key, len(batch)))
        if self.exc:
            raise self.exc
        if self.outputs is not None:
            return self.outputs(len(batch))
        return [{"kpis": {"equity_irr": 0.10 + 0.001 * n}} for n in range(len(batch))]


@pytest.fixture()
def fake(monkeypatch):
    from app.runtime import model_execution

    def install(**kw):
        f = _Fake(**kw)
        monkeypatch.setattr(model_execution, "run_model_process", f)
        return f
    return install


def test_one_request_is_one_admitted_batch_with_deterministic_order(env, fake):
    record = env.create("solar")
    f = fake()
    r = _post(env, record, driver_a="capex", driver_b="opex", levels_a="-10,0,10", levels_b="-10,0,10")
    assert r.status_code == 200 and f.calls == [("Solar", 9)]             # 9 cells, Base reused, ONE executor call
    vals = _cell_values(r.text)
    assert vals[(0, 0)] == "10.00%" and vals[(2, 0)] == "10.20%" and vals[(0, 1)] == "10.30%"   # row-major (B then A)
    r2 = _post(env, record, driver_a="capex", driver_b="opex", levels_a="-10,10,5", levels_b="-10,0,10")
    assert f.calls[-1] == ("Solar", 10)                                   # no 0/0 cell -> one extra Base evaluation
    assert "Base was computed separately." in r2.text


@pytest.mark.parametrize("fields,code", [
    (dict(driver_a="capex", driver_b="capex"), "MATRIX_DRIVER_DUPLICATE"),
    (dict(driver_a="capex", driver_b="bogus"), "MATRIX_DRIVER_UNSUPPORTED"),
    (dict(driver_a="capex", driver_b="opex", levels_a="1,2"), "MATRIX_LEVEL_COUNT"),
    (dict(driver_a="capex", driver_b="opex", levels_b="-10,0,99"), "MATRIX_LEVEL_OUT_OF_BOUNDS"),
    (dict(driver_a="capex", driver_b="opex", metric="nope"), "MATRIX_METRIC_UNSUPPORTED"),
    (dict(driver_a="capex", driver_b="opex", threshold="abc"), "MATRIX_THRESHOLD_INVALID"),
])
def test_invalid_requests_are_rejected_without_running(env, fake, fields, code):
    record = env.create("solar")
    f = fake()
    r = _post(env, record, **fields)
    assert r.status_code == 422 and f'data-code="{code}"' in r.text and f.calls == []
    assert r.headers["X-Finco-Matrix-Error"] == "1" and r.headers["Cache-Control"] == "no-store"   # HTMX swaps it


def test_grid_size_ceiling_is_enforced_before_any_run(env, fake, monkeypatch):
    from app.services import sensitivity_execution
    record = env.create("solar")
    f = fake()
    monkeypatch.setattr(sensitivity_execution, "MAX_SENSITIVITY_EVALUATIONS", 8)
    r = _post(env, record, driver_a="capex", driver_b="opex")
    assert r.status_code == 422 and 'data-code="SENSITIVITY_GRID_TOO_LARGE"' in r.text and f.calls == []


def test_failed_and_unavailable_cells_do_not_block_valid_cells(env, fake):
    record = env.create("solar")

    def outputs(n):
        out = [{"kpis": {"equity_irr": 0.1 + 0.01 * k}} for k in range(n)]
        out[0] = {"error": "boom"}
        out[1] = {"kpis": {}}
        return out
    fake(outputs=outputs)
    r = _post(env, record, driver_a="capex", driver_b="opex", threshold="10")
    cells = _cells(r.text)
    assert cells[(0, 0)] == ("FAILED", "UNAVAILABLE") and cells[(1, 0)] == ("UNAVAILABLE", "UNAVAILABLE")
    assert sum(1 for s, _ in cells.values() if s == "OK") == 7
    assert "1 failed · 1 unavailable" in re.sub(r"\s+", " ", r.text)


def test_timeout_busy_and_executor_errors_are_typed(env, fake):
    from app.runtime.model_execution import ModelExecutionBusy, ModelExecutionTimeout
    record = env.create("solar")
    fake(exc=ModelExecutionBusy())
    busy = _post(env, record, driver_a="capex", driver_b="opex")
    assert busy.status_code == 429 and busy.headers["Retry-After"] == "5"
    fake(exc=ModelExecutionTimeout())
    timeout = _post(env, record, driver_a="capex", driver_b="opex")
    assert timeout.status_code == 200 and set(s for s, _ in _cells(timeout.text).values()) == {"FAILED"}
    assert "CALCULATION_TIMEOUT" in timeout.text
    fake(exc=RuntimeError("secret internal detail"))
    err = _post(env, record, driver_a="capex", driver_b="opex")
    assert "secret internal detail" not in err.text and "Calculation could not be completed." in err.text


def test_unapplied_shock_is_a_typed_failure_not_the_unshocked_result(env, fake):
    # Solar reference carries no merchant curve: the merchant shock changes nothing and must not masquerade.
    record = env.create("solar")
    fake()
    r = _post(env, record, driver_a="merchant_price", driver_b="capex")
    cells = _cells(r.text)
    shocked = [(i, j) for i in range(3) for j in range(3) if i != 1]
    if all(cells[k][0] == "FAILED" for k in shocked):
        assert "SHOCK_NOT_APPLIED" in r.text
        assert cells[(1, 1)][0] == "OK"                                   # zero level has nothing to apply
    else:                                                                # a curve exists: the shock is real
        assert all(cells[k][0] == "OK" for k in shocked)


def test_stale_context_discards_results(env, fake, monkeypatch):
    from app.v2.post_run_context import PostRunContextChanged, PostRunRequestContext
    record = env.create("solar")
    fake()

    def changed(self):
        raise PostRunContextChanged("changed")
    monkeypatch.setattr(PostRunRequestContext, "validate_current", changed)
    r = _post(env, record, driver_a="capex", driver_b="opex")
    assert r.status_code == 409 and 'data-code="MATRIX_CONTEXT_CHANGED"' in r.text and "matrix-table" not in r.text


def test_ownership_unknown_scenario_and_unauthenticated(env, fake):
    from app.auth import COOKIE_NAME, create_session_token
    record = env.create("solar")
    f = fake()
    assert _post(env, record, driver_a="capex", driver_b="opex", scenario_id="not-a-scenario").status_code == 404
    env.client.cookies.set(COOKIE_NAME, create_session_token(user_id="someone-else", username="intruder"))
    assert _post(env, record, driver_a="capex", driver_b="opex").status_code == 404
    env.client.cookies.clear()
    assert _post(env, record, driver_a="capex", driver_b="opex").status_code == 401
    assert env.client.get(FORM, params={"project": record.project_code}).status_code == 401
    assert f.calls == []


def test_no_persistence_and_no_last_run_mutation(env, fake):
    from app.persistence.run_history_repository import get_run_history
    from app.persistence.workspace_repository import get_workspace_state
    from tests.test_model_financing_f2 import run
    record = env.create("solar")
    run(env, record)
    ws0 = get_workspace_state(USER, record.project_id)
    history0 = [h.history_id for h in get_run_history(USER, record.project_id, limit=50)]
    fake()
    r = _post(env, record, driver_a="capex", driver_b="tariff", threshold="9")
    assert r.status_code == 200 and 'data-state="EPHEMERAL"' in r.text and 'data-state="CURRENT"' not in r.text
    ws1 = get_workspace_state(USER, record.project_id)
    for name in ("draft_snapshot", "last_runtime_summary", "last_runtime_snapshot_id", "last_runtime_composite_hash",
                 "active_scenario_id", "row_version"):
        assert getattr(ws1, name, None) == getattr(ws0, name, None), name
    assert [h.history_id for h in get_run_history(USER, record.project_id, limit=50)] == history0


# ── UI wiring and unchanged neighbours ──────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("kind,present,absent", [
    ("solar", "tariff", "dc_pue"), ("wind", "generation", "service_price"), ("data_center", "dc_pue", "tariff")])
def test_form_offers_only_supported_drivers_and_sensitivity_tab_hosts_it(env, kind, present, absent):
    record = env.create(kind)
    form = env.client.get(FORM, params={"project": record.project_code})
    assert form.status_code == 200 and f'value="{present}"' in form.text and f'value="{absent}"' not in form.text
    assert 'data-testid="matrix-run-btn"' in form.text
    page = env.client.get("/v2/workbook", params={"project": record.project_code}).text
    assert 'data-testid="matrix-region"' in page and "Two-driver matrices are not available" not in page


def test_ev_form_is_unsupported_and_offers_no_driver(env):
    record = env.create("ev_charging")
    form = env.client.get(FORM, params={"project": record.project_code})
    assert 'data-testid="matrix-unsupported"' in form.text and 'name="driver_a"' not in form.text


def test_existing_one_driver_sensitivity_is_unchanged(env):
    record = env.create("solar")
    r = env.client.post("/v2/workbook/scenarios/sensitivity/run",
                        data={"project": record.project_code, "driver": "interest_rate"})
    assert r.status_code == 200 and "sensitivity-range" in r.text or "v2-sens-table" in r.text


def _checked_git(*args):
    import subprocess
    result = subprocess.run(["git", *args], capture_output=True, text=True)
    return result.stdout.strip() if result.returncode == 0 else None


def reviewed_ci_workflow_candidate(path):
    """Exact-path, exact-blob recognition of the two reviewed CI workflow states (never a ``.github/`` exception).

    RC-2 candidate: the historical two-line budget change over the RC-2 base. RC-5 successor: the pinned owner-authorised budget workflow, accepted only
    when the RC-3 reference is independently verified at its fixed blob, HEAD and the worktree are both the fixed RC-5 blob, and the existing RC-5
    verifier confirms exactly the three authorised limit values (evidence, selection, permissions and every other step byte-identical).
    """
    import subprocess
    from pathlib import Path
    from tests.test_rc2_integration_manifest import (
        RC2_BASE_MAIN, RC2_CI_WORKFLOW, RC2_CI_WORKFLOW_BASE_BLOB,
        RC2_CI_WORKFLOW_CANDIDATE_BLOB, rc2_workflow_delta_valid,
    )
    if path != RC2_CI_WORKFLOW:
        return False
    root = Path(__file__).resolve().parents[1]
    current_path = root / path
    if not current_path.is_file():
        return False
    baseline = subprocess.run(["git", "show", f"{RC2_BASE_MAIN}:{path}"], capture_output=True, text=True)
    if (baseline.returncode == 0
            and _checked_git("rev-parse", f"{RC2_BASE_MAIN}:{path}") == RC2_CI_WORKFLOW_BASE_BLOB
            and _checked_git("rev-parse", f"HEAD:{path}") == RC2_CI_WORKFLOW_CANDIDATE_BLOB
            and _checked_git("hash-object", path) == RC2_CI_WORKFLOW_CANDIDATE_BLOB
            and rc2_workflow_delta_valid(baseline.stdout, current_path.read_text(encoding="utf-8"))):
        return True
    from tests.test_rc3_integration_inventory import (
        INTEGRATION_HEAD, RC3_CI_WORKFLOW_BLOB, RC5_CI_WORKFLOW_BLOB, rc5_workflow_successor_violations,
    )
    rc3 = subprocess.run(["git", "show", f"{INTEGRATION_HEAD}:{path}"], capture_output=True, text=True)
    return (
        rc3.returncode == 0
        and _checked_git("rev-parse", f"{INTEGRATION_HEAD}:{path}") == RC3_CI_WORKFLOW_BLOB
        and _checked_git("rev-parse", f"HEAD:{path}") == RC5_CI_WORKFLOW_BLOB
        and _checked_git("hash-object", path) == RC5_CI_WORKFLOW_BLOB
        and not rc5_workflow_successor_violations(rc3.stdout, current_path.read_text(encoding="utf-8"))
    )


def test_no_engine_or_financial_authority_files_are_touched():
    import subprocess
    from rc3_historical_anchor import anchored_head
    out = subprocess.run(["git", "diff", "--name-only", "origin/main..." + anchored_head()], capture_output=True, text=True).stdout
    # On the RC-2 integration branch the only permitted financial-path deltas are the three reviewer-conditional,
    # release-closed Revenue V3 candidate blobs of PR #275 (exact path AND exact blob); everything else still fails.
    from model_v2_governance import REVENUE_V3_CANDIDATE_AUTHORITIES as v3
    def reviewed_v3(path):
        head = subprocess.run(["git", "rev-parse", "HEAD:" + path], capture_output=True, text=True).stdout.strip()
        return v3.get(path) == head
    # M3's financial deny remains closed except for the exact reviewed Revenue V3 blobs.
    # RC-2 separately authorizes ONLY the two-line CI job change (proposed, not approved).
    reviewed_ci_workflow = reviewed_ci_workflow_candidate     # module-level, shared with the negative-control tests

    assert not [p for p in out.split() if p.startswith(("financial_engine/", "finco_core/", "domain/", ".github/"))
                and not (reviewed_v3(p) or reviewed_ci_workflow(p))]
    # Negative checks: another workflow and an unapproved financial path never inherit this exception.
    assert not reviewed_ci_workflow(".github/workflows/public_safety_and_smoke.yml")
    assert not reviewed_v3("finco_core/revenue/unreviewed.py")
