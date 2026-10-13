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
FORM = "/v2/workbook/sensitivity/matrix/form"


# ── pure projection ─────────────────────────────────────────────────────────────────────────────────────────────
def test_levels_defaults_sorted_unique_bounded():
    spec = proj.DRIVERS["capex"]
    assert parse_levels("", spec) == (-20, -10, 0, 10, 20)
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
    return run_project(runtime_key, "Base", project_inputs_override=pi)["kpis"]


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
    rate0 = float(pis.values["debt.senior.interest_rate_pct"])
    gear0 = float(pis.values["debt.senior.gearing_pct"])
    oracle = _oracle(record, "Solar", [], field_overrides={"debt.senior.interest_rate_pct": rate0 + 1.0,
                                                           "debt.senior.gearing_pct": gear0 - 5.0})
    assert _pct(va[(2, 0)]) == pytest.approx(oracle["equity_irr"], abs=6e-5)   # +100 bps, -5 pp


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


def test_no_engine_or_financial_authority_files_are_touched():
    import subprocess
    out = subprocess.run(["git", "diff", "--name-only", "origin/main...HEAD"], capture_output=True, text=True).stdout
    assert not [p for p in out.split() if p.startswith(("financial_engine/", "finco_core/", "domain/", ".github/"))]
