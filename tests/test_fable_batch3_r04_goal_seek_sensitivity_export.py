"""FINCO 36 Correction H — Goal Seek, Sensitivity and real-route exports on SAVED dated R04 books (real routes, no mocks).

Proves:
1. On a dated R04 explicit-contract book, scalar tariff Goal Seek and scalar tariff sensitivity fail closed with the
   exact typed refusal (HTTP 422, code=INVALID_REQUEST, CONTRACTED_PRICE_SHOCK_REFUSAL, no result/apply/candidate),
   while preserving zero writes, zero revision/runtime mutation, and zero History side effects.
2. Supported dated-book sensitivity (CAPEX driver) matches both the committed dated Run at 0% shock and an
   independently executed canonical run_clean_production candidate at a non-zero shock (+10% CAPEX); a neighboring
   supported scalar-tariff Goal Seek (legacy Solar) matches an independently executed canonical candidate and target
   residual tolerance. Negative controls prove wrong refusals and wrong candidates fail.
3. Real authenticated XLSX export routes (GET /v2/workbook/run-history/export, POST /v2/workbook/export) for both
   dated Solar and dated Wind (with off-boundary COD and final stub) and an unchanged legacy Solar reference produce
   valid openpyxl workbooks carrying the exact final date with no omission/duplication, units, reconciled totals
   including the final stub, and full financial parity against sealed History and independent accounting identities.
   Unsupported investor export (GET /v2/workbook/investor/export) returns a precise typed 409 refusal.
   After draft edits AND a subsequent Run, re-exporting the ORIGINAL history_id preserves the financial payload
   bit-for-bit across all financial sheets. Negative controls prove omission, duplication, or figure tampering fails.
"""
from __future__ import annotations

from dataclasses import replace
import io
import json
from types import SimpleNamespace

import openpyxl
import pytest

from app.persistence.run_history_repository import get_run_history
from app.persistence.workspace_repository import get_workspace_state
from app.services.goal_seek import DEFAULT_TARGET_TOLERANCE
from app.services.production_financial_authority import run_clean_production
from app.services.sensitivity_service import CONTRACTED_PRICE_SHOCK_REFUSAL
from app.workbook.mutation_csrf import mutation_token
from app.workbook.service import WorkbookService
from tests.test_fable_batch3_r04_review_route import MERCHANT, _ppa, book
from tests.test_model_react_rcm_goal_seek_v1 import (  # noqa: F401
    BASE,
    HDR,
    baseline_irr_pct,
    call,
    env,
    run_canonical,
    state,
    with_sensitivity,
)


def _save_dated_book(
    env,
    record,
    amount=1000,
    *,
    start_date="2031-03-01",
    end_date="2032-03-01",
    merchant_end_date="2056-03-01",
):
    tok = env.client.get("/v2/model-react/revenue", params={"project": record.project_code}).json()["save"]
    tech = (getattr(record, "project_type", None) or "solar").strip().lower()
    merchant = {**MERCHANT, "start_date": start_date, "end_date": merchant_end_date}
    payload = json.dumps(
        {
            "version": 2,
            "technology": tech,
            "indexation_basis": "OPERATING_YEAR",
            "streams": [_ppa("a", start_date, end_date, amount), merchant],
        },
        separators=(",", ":"),
    )
    resp = env.client.post(
        "/v2/workbook/revenue/contracts",
        data={
            "project": record.project_code,
            "csrf_token": tok["csrf_token"],
            "content_hash": tok["content_hash"],
            "contracts": payload,
            "action": "save",
        },
        follow_redirects=False,
    )
    assert resp.status_code in (200, 303), resp.text[:200]


def _history(record):
    return [e.history_id for e in get_run_history(record.user_id, record.project_id)]


def _saved_project_inputs(record):
    from app.services.capex_sub_lines_integration import apply_user_sub_lines_replacing_base
    from app.services.opex_sub_lines_integration import apply_user_sub_lines_to_opex

    ws = get_workspace_state(record.user_id, record.project_id)
    pis = WorkbookService.build_draft_input_set_from_workspace(ws)
    pi = WorkbookService.to_projectinputs(pis)
    folded_capex = apply_user_sub_lines_replacing_base(pi.capex, project_id=record.project_id, scenario_overrides=None)
    if folded_capex is not pi.capex:
        pi = replace(pi, capex=folded_capex)
    folded_opex = apply_user_sub_lines_to_opex(pi.opex, project_id=record.project_id, scenario_overrides=None)
    if folded_opex is not pi.opex:
        pi = replace(pi, opex=folded_opex)
    return pi


def _scale_capex(pi, factor: float):
    updates = {}
    for code in pi.capex._CAPEX_ITEM_FIELDS:
        item = getattr(pi.capex, code)
        if item.amount_keur:
            updates[code] = replace(item, amount_keur=item.amount_keur * factor)
    return replace(pi, capex=replace(pi.capex, **updates))


# ── Decisive assertion helpers + negative controls (Task 1a) ─────────────────


def _assert_explicit_book_tariff_refusal(status_code: int, body: dict) -> None:
    """Decisive route-level contract for scalar tariff Goal Seek on an explicit-contract book."""
    assert status_code == 422, f"Expected HTTP 422 typed refusal, got {status_code}: {body}"
    assert body.get("ok") is False, f"Expected ok=False, got {body}"
    assert body.get("code") == "INVALID_REQUEST", f"Unexpected code: {body}"
    assert CONTRACTED_PRICE_SHOCK_REFUSAL in str(body.get("message", "")), f"Missing refusal text: {body}"
    assert "result" not in body, f"Refusal must not carry a solve result: {body}"
    assert "apply" not in body, f"Refusal must not carry an apply token: {body}"
    assert body.get("candidate") is None, f"Refusal must not carry a candidate: {body}"


def _assert_goal_seek_numeric_parity(
    pi,
    *,
    project_type: str,
    target_ratio: float,
    solved_tariff: float,
    achieved_ratio: float,
) -> None:
    """Verify a solved tariff candidate against an independent canonical run and target residual."""
    candidate_pi = replace(pi, revenue=replace(pi.revenue, ppa_base_tariff=float(solved_tariff)))
    independent = run_clean_production(candidate_pi, "Base", project_type=project_type)
    indep_irr = float(independent.g2c_result.return_summary.project.project_xirr)
    assert abs(indep_irr - float(achieved_ratio)) <= 1e-6, (
        f"Goal Seek achieved IRR {achieved_ratio:.8f} != independent canonical IRR {indep_irr:.8f}"
    )
    assert abs(indep_irr - float(target_ratio)) <= DEFAULT_TARGET_TOLERANCE + 1e-6, (
        f"Independent canonical IRR {indep_irr:.8f} exceeds tolerance around target {target_ratio:.8f}"
    )


def test_goal_seek_and_sensitivity_on_a_dated_book_are_read_only_and_typed(with_sensitivity):
    env = with_sensitivity
    record = env.create()
    env.client.get("/v2/workbook", params={"project": record.project_code})
    _save_dated_book(env, record)
    run_canonical(env, record.project_code)
    committed = _history(record)
    assert len(committed) == 1
    before = state(record)

    # 1. Unsupported explicit-book scalar tariff Goal Seek -> decisive typed 422 refusal, no candidate.
    solve = call(env.client, "solve", project=record.project_code, target_metric="project_irr", target_value="8")
    _assert_explicit_book_tariff_refusal(solve.status_code, solve.json())

    # 2. Unsupported explicit-book scalar tariff sensitivity -> every non-zero shocked row is refused with CONTRACTED_PRICE_SHOCK_REFUSAL.
    tariff_strip = env.client.get(
        "/v2/model-react/analysis/sensitivity/strip",
        params={"project": record.project_code, "driver": "tariff"},
        headers=HDR,
    )
    assert tariff_strip.status_code == 200, tariff_strip.text[:300]
    t_body = tariff_strip.json()
    nonzero_rows = [row for row in t_body["rows"] if abs(float(row["level"])) > 1e-9]
    assert len(nonzero_rows) >= 2
    for row in nonzero_rows:
        assert row.get("status") != "OK", f"Tariff shock row {row['level']} must be refused on explicit contract book: {row}"
        assert "REVENUE_V2_CONTRACTS_UNSUPPORTED" in json.dumps(row) or CONTRACTED_PRICE_SHOCK_REFUSAL in json.dumps(row)
        assert row.get("values", {}).get("project_irr", {}).get("raw") is None

    # 3. Supported dated-book sensitivity (CAPEX driver) -> exact numeric parity at 0% AND non-zero (+10%) shock.
    capex_resp = env.client.get(
        "/v2/model-react/analysis/sensitivity/strip",
        params={"project": record.project_code, "driver": "capex"},
        headers=HDR,
    )
    assert capex_resp.status_code == 200, capex_resp.text[:300]
    c_body = capex_resp.json()
    base_irr = c_body["base"]["values"]["project_irr"]["raw"]
    assert base_irr is not None

    plus10 = next(row for row in c_body["rows"] if abs(float(row["level"]) - 10.0) < 1e-9)
    shocked_irr = float(plus10["values"]["project_irr"]["raw"])
    assert abs(shocked_irr - base_irr) > 1e-4, "CAPEX +10% shock must materially change Project IRR"

    saved_pi = _saved_project_inputs(record)
    indep_plus10 = run_clean_production(_scale_capex(saved_pi, 1.10), "Base", project_type="solar")
    indep_plus10_irr = float(indep_plus10.g2c_result.return_summary.project.project_xirr)
    assert shocked_irr == pytest.approx(indep_plus10_irr, abs=1e-6)

    # 4. Read-only guarantees: no draft/saved/dirty/runtime change, no History row from previews.
    after = state(record)
    assert after == before
    assert _history(record) == committed

    # 5. Negative controls: wrong refusal or wrong candidate MUST fail the verifiers.
    with pytest.raises(AssertionError):
        _assert_explicit_book_tariff_refusal(200, {"ok": True, "result": {"solved": True}})
    with pytest.raises(AssertionError):
        _assert_explicit_book_tariff_refusal(422, {"ok": False, "code": "INVALID_REQUEST", "message": "wrong reason"})
    with pytest.raises(AssertionError):
        _assert_explicit_book_tariff_refusal(
            422,
            {"ok": False, "code": "INVALID_REQUEST", "message": CONTRACTED_PRICE_SHOCK_REFUSAL, "apply": {"value": "99"}},
        )
    with pytest.raises(AssertionError):
        assert shocked_irr == pytest.approx(base_irr, abs=1e-6)


def test_supported_neighboring_goal_seek_numeric_parity_and_negative_control(with_sensitivity):
    """Supported scalar-tariff Goal Seek on a legacy Solar working copy matches an independent canonical candidate."""
    env = with_sensitivity
    record = env.create(kind="solar", name="GS Legacy Neighbor")
    env.client.get("/v2/workbook", params={"project": record.project_code})
    run_canonical(env, record.project_code)
    committed = _history(record)
    before = state(record)

    base_pct = baseline_irr_pct(env, record)
    target_pct = round(base_pct + 1.0, 2)
    solve = call(
        env.client,
        "solve",
        project=record.project_code,
        target_metric="project_irr",
        target_value=f"{target_pct:.2f}",
    )
    assert solve.status_code == 200, solve.text[:300]
    sbody = solve.json()
    assert sbody["ok"] is True and sbody["preview_only"] is True and sbody["committed"] is False
    assert sbody["result"]["solved"] is True
    assert sbody["apply"] is not None and sbody["apply"]["field_id"] == "revenue.ppa.base_tariff"

    solved_tariff = float(sbody["result"]["solved_input_value"])
    achieved_ratio = float(sbody["result"]["achieved_metric_value"])
    saved_pi = _saved_project_inputs(record)

    _assert_goal_seek_numeric_parity(
        saved_pi,
        project_type="solar",
        target_ratio=target_pct / 100.0,
        solved_tariff=solved_tariff,
        achieved_ratio=achieved_ratio,
    )

    # Negative control: perturbing the solved tariff by +5 EUR/MWh fails numeric parity / residual check.
    with pytest.raises(AssertionError):
        _assert_goal_seek_numeric_parity(
            saved_pi,
            project_type="solar",
            target_ratio=target_pct / 100.0,
            solved_tariff=solved_tariff + 5.0,
            achieved_ratio=achieved_ratio,
        )

    assert state(record) == before
    assert _history(record) == committed


def test_sensitivity_strip_base_equals_the_committed_dated_run(with_sensitivity):
    env = with_sensitivity
    record = env.create()
    env.client.get("/v2/workbook", params={"project": record.project_code})
    _save_dated_book(env, record)
    run_canonical(env, record.project_code)
    entry = get_run_history(record.user_id, record.project_id)[0]
    committed_irr = entry.runtime_summary["project_irr"]  # the sealed Run's own persisted figure
    strip = env.client.get(
        "/v2/model-react/analysis/sensitivity/strip",
        params={"project": record.project_code, "driver": "capex"},
        headers=HDR,
    ).json()
    assert committed_irr is not None
    assert strip["base"]["values"]["project_irr"]["raw"] == pytest.approx(committed_irr, abs=1e-9)


# ── Real XLSX export parsing, verification & immutability (Task 1b) ──────────


def _parse_v3_periodic_sheet(ws) -> dict:
    """Parse a V3 historical/evidence periodic sheet (P&L, Cash Flow, Balance Sheet, Tax_Bridge, Debt_DSCR)."""
    header_row = None
    for r in range(1, min(ws.max_row + 1, 15)):
        if ws.cell(r, 1).value == "Metric" and ws.cell(r, 2).value == "Unit":
            header_row = r
            break
    assert header_row is not None, f"Could not locate Metric/Unit header row in sheet {ws.title}"
    # Column 5 is 'Periods persisted'; actual period columns start at column 6 ('P0 | YYYY-MM-DD').
    first_period_col = 5
    while first_period_col <= ws.max_column and "|" not in str(ws.cell(header_row, first_period_col).value or ""):
        first_period_col += 1
    period_headers = [str(ws.cell(header_row, c).value) for c in range(first_period_col, ws.max_column + 1)]
    rows: dict[str, dict] = {}
    for r in range(header_row + 1, ws.max_row + 1):
        metric = ws.cell(r, 1).value
        unit = ws.cell(r, 2).value
        basis = ws.cell(r, 3).value
        total = ws.cell(r, 4).value
        if metric is None or unit is None:
            continue
        values = [ws.cell(r, c).value for c in range(first_period_col, ws.max_column + 1)]
        rows[str(metric)] = {"unit": str(unit), "basis": str(basis), "total": total, "values": values}
    return {"headers": period_headers, "rows": rows}


def _extract_financial_payload_snapshot(wb: openpyxl.Workbook) -> dict:
    """Extract deterministic financial payload across all financial sheets, excluding volatile banners/timestamps."""
    snapshot: dict = {}
    for name in (
        "P&L",
        "Cash Flow",
        "Balance Sheet",
        "Tax_Bridge",
        "Debt_DSCR",
        "Reserves",
        "Returns",
        "Sources_Uses",
        "Construction_Funding",
        "Periods_Dates",
    ):
        ws = wb[name]
        # Rows 1-4 are title / RUN STATE banner / run metadata; financial tables start at row 6.
        table_rows = []
        for r in range(6, ws.max_row + 1):
            row_vals = [ws.cell(r, c).value for c in range(1, ws.max_column + 1)]
            if any(v is not None for v in row_vals):
                table_rows.append(row_vals)
        snapshot[name] = table_rows
    return snapshot


def _verify_v3_export_against_history(
    parsed_sheets: dict[str, dict],
    periods_dates_rows: list[list],
    entry,
    *,
    expected_final_date: str,
    expect_positive_terminal_revenue: bool = True,
) -> None:
    """Verify exported periodic sheets against sealed Run History, terminal date uniqueness, units, and totals."""
    pnl_hist = entry.financial_statements["pnl"]["periods"]
    cf_hist = entry.financial_statements["pf_cash_waterfall"]["periods"]
    bs_hist = entry.financial_statements["balance_sheet"]["periods"]
    tax_hist = entry.tax_schedule["periods"]
    expected_n = len(pnl_hist)

    # 1. Periods_Dates sheet must report the exact period count and final date for every persisted axis.
    axis_map = {str(row[0]): (row[1], str(row[3])) for row in periods_dates_rows if len(row) >= 4 and row[0]}
    for axis in ("debt_schedule", "income statement", "cash waterfall", "balance sheet", "tax_schedule"):
        assert axis in axis_map, f"Missing axis {axis} in Periods_Dates"
        assert axis_map[axis] == (expected_n, expected_final_date), (
            f"Axis {axis} expected ({expected_n}, {expected_final_date}), got {axis_map[axis]}"
        )

    # 2. Every periodic sheet has exactly expected_n columns and exactly ONE terminal column with expected_final_date.
    for sname in ("P&L", "Cash Flow", "Balance Sheet", "Tax_Bridge", "Debt_DSCR"):
        headers = parsed_sheets[sname]["headers"]
        assert len(headers) == expected_n, f"{sname}: expected {expected_n} period columns, got {len(headers)}"
        dates = [h.split("|")[-1].strip() for h in headers]
        assert dates[-1] == expected_final_date, f"{sname}: final date {dates[-1]} != {expected_final_date}"
        assert dates.count(expected_final_date) == 1, (
            f"{sname}: expected exactly 1 column for {expected_final_date}, found {dates.count(expected_final_date)}"
        )

    # 3. Units, terminal row figures vs sealed History, independent identities, and totals reconciliation.
    pnl = parsed_sheets["P&L"]["rows"]
    for label, hist_key in (
        ("Revenue", "revenues_keur"),
        ("OPEX", "operating_expenses_keur"),
        ("Depreciation", "depreciation_keur"),
        ("EBIT", "ebit_keur"),
        ("Senior interest", "senior_interest_expense_keur"),
        ("SHL interest", "shl_interest_expense_keur"),
        ("EBT", "earnings_before_tax_keur"),
        ("CIT accrual", "cit_accrual_keur"),
        ("Net income", "net_income_keur"),
        ("Net dividends", "net_dividends_keur"),
    ):
        row = pnl[label]
        assert row["unit"] == "kEUR" and row["basis"] == "Flow"
        assert float(row["values"][-1]) == pytest.approx(float(pnl_hist[-1][hist_key]), abs=0.01)
        numeric_sum = sum(float(v) for v in row["values"] if isinstance(v, (int, float)))
        assert float(row["total"]) == pytest.approx(numeric_sum, abs=0.05), (
            f"P&L {label} total {row['total']} != sum of all periods incl. final stub {numeric_sum}"
        )

    if expect_positive_terminal_revenue:
        assert float(pnl["Revenue"]["values"][-1]) > 0.0
        assert float(pnl["OPEX"]["values"][-1]) > 0.0
        assert float(pnl["Depreciation"]["values"][-1]) > 0.0

    # Independent P&L identity on terminal period: EBIT = Revenue - OPEX - Depreciation
    term_rev = float(pnl["Revenue"]["values"][-1])
    term_opex = float(pnl["OPEX"]["values"][-1])
    term_dep = float(pnl["Depreciation"]["values"][-1])
    term_ebit = float(pnl["EBIT"]["values"][-1])
    assert term_ebit == pytest.approx(term_rev - term_opex - term_dep, abs=0.02)

    # Cash Flow: terminal figures vs sealed History, EBITDA cash identity, and totals reconciliation
    cf = parsed_sheets["Cash Flow"]["rows"]
    for label, hist_key in (
        ("Revenue cash", "revenue_cash_keur"),
        ("OPEX cash", "opex_cash_keur"),
        ("EBITDA cash", "ebitda_cash_keur"),
        ("Cash tax", "cash_tax_keur"),
        ("FCF banks", "fcf_banks_keur"),
        ("Senior debt service", "senior_total_ds_keur"),
        ("Net dividends", "net_dividends_keur"),
    ):
        row = cf[label]
        assert row["unit"] == "kEUR" and row["basis"] == "Flow"
        assert float(row["values"][-1]) == pytest.approx(float(cf_hist[-1][hist_key]), abs=0.01)
        numeric_sum = sum(float(v) for v in row["values"] if isinstance(v, (int, float)))
        assert float(row["total"]) == pytest.approx(numeric_sum, abs=0.05)
    assert float(cf["EBITDA cash"]["values"][-1]) == pytest.approx(
        float(cf["Revenue cash"]["values"][-1]) - float(cf["OPEX cash"]["values"][-1]), abs=0.02
    )

    # Balance Sheet: stock units, no totalled stock balances, terminal balance check <= 0.01 kEUR
    bs = parsed_sheets["Balance Sheet"]["rows"]
    for label, hist_key in (
        ("Net fixed assets", "net_fixed_assets_keur"),
        ("Share capital", "share_capital_keur"),
        ("Retained earnings", "retained_earnings_keur"),
        ("Senior debt balance", "senior_balance_keur"),
        ("Balance check (runtime residual)", "balance_check_keur"),
    ):
        row = bs[label]
        assert row["unit"] == "kEUR" and row["basis"] == "Stock"
        assert float(row["values"][-1]) == pytest.approx(float(bs_hist[-1][hist_key]), abs=0.01)
    assert abs(float(bs["Balance check (runtime residual)"]["values"][-1])) <= 0.01

    # Tax_Bridge: terminal tax figures vs sealed History and totals reconciliation
    tb = parsed_sheets["Tax_Bridge"]["rows"]
    for label, hist_key in (("Taxable profit", "taxable_profit_keur"), ("Tax (period)", "tax_keur")):
        row = tb[label]
        assert row["unit"] == "kEUR" and row["basis"] == "Flow"
        assert float(row["values"][-1]) == pytest.approx(float(tax_hist[-1][hist_key]), abs=0.01)
        numeric_sum = sum(float(v) for v in row["values"] if isinstance(v, (int, float)))
        assert float(row["total"]) == pytest.approx(numeric_sum, abs=0.05)

    # Debt_DSCR: totals reconcile across all debt-active periods
    dd = parsed_sheets["Debt_DSCR"]["rows"]
    for label in ("Senior principal", "Senior interest", "Senior debt service"):
        row = dd[label]
        assert row["unit"] == "kEUR" and row["basis"] == "Flow"
        numeric_sum = sum(float(v) for v in row["values"] if isinstance(v, (int, float)))
        assert float(row["total"]) == pytest.approx(numeric_sum, abs=0.05)
    assert dd["DSCR"]["unit"] == "x"


def test_historical_export_of_a_dated_run_is_immutable_after_a_draft_edit(with_sensitivity):
    """Real authenticated export routes (Historical XLSX, Last-Run XLSX, typed 409 Investor refusal) on dated Solar."""
    from app.v2.investor_f4_router import router as investor_router

    env = with_sensitivity
    env.app.include_router(investor_router, prefix="/v2")
    record = env.create(kind="solar", name="Dated Export Solar")
    env.client.get("/v2/workbook", params={"project": record.project_code})
    _save_dated_book(env, record, amount=1000, start_date="2031-03-01", end_date="2032-03-01")
    run_canonical(env, record.project_code)
    entry = get_run_history(record.user_id, record.project_id)[0]

    # Sealed History dictionary invariant (preserved)
    before_hist = json.dumps(
        [entry.financial_statements, entry.debt_schedule, entry.tax_schedule, entry.runtime_summary],
        sort_keys=True,
        default=str,
    )
    rows = entry.financial_statements["pnl"]["periods"]
    assert rows[-1]["date"] == "2056-02-29" and rows[-1]["revenues_keur"] > 0

    # 1. Real Historical XLSX export (GET /v2/workbook/run-history/export)
    hexp1 = env.client.get(
        "/v2/workbook/run-history/export",
        params={"project": record.project_code, "history_id": entry.history_id},
    )
    assert hexp1.status_code == 200
    assert hexp1.headers["content-type"].startswith("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    wb1 = openpyxl.load_workbook(io.BytesIO(hexp1.content), data_only=True)
    parsed1 = {s: _parse_v3_periodic_sheet(wb1[s]) for s in ("P&L", "Cash Flow", "Balance Sheet", "Tax_Bridge", "Debt_DSCR")}
    pd_rows1 = [[wb1["Periods_Dates"].cell(r, c).value for c in range(1, 5)] for r in range(6, wb1["Periods_Dates"].max_row + 1)]
    _verify_v3_export_against_history(parsed1, pd_rows1, entry, expected_final_date="2056-02-29")
    payload1 = _extract_financial_payload_snapshot(wb1)

    # 2. Real Canonical Last-Run XLSX export (POST /v2/workbook/export) carries the same final stub
    req_ns = SimpleNamespace(cookies=env.client.cookies, state=SimpleNamespace())
    lexp = env.client.post(
        "/v2/workbook/export",
        data={
            "project": record.project_code,
            "csrf_token": mutation_token(req_ns, record.project_code, "workbook-export"),
        },
    )
    assert lexp.status_code == 200
    assert lexp.headers["content-type"].startswith("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    wb_last = openpyxl.load_workbook(io.BytesIO(lexp.content), data_only=True)
    pd_last = [[wb_last["Periods_Dates"].cell(r, c).value for c in range(1, 5)] for r in range(6, wb_last["Periods_Dates"].max_row + 1)]
    axis_last = {str(r[0]): (r[1], str(r[3])) for r in pd_last if len(r) >= 4 and r[0]}
    assert axis_last["income statement"] == (len(rows), "2056-02-29")
    assert axis_last["tax_schedule"] == (len(rows), "2056-02-29")
    # V3 sheets inside Last-Run export also carry exact terminal column
    last_tb = _parse_v3_periodic_sheet(wb_last["Tax_Bridge"])
    assert last_tb["headers"][-1].endswith("2056-02-29")
    assert [h.split("|")[-1].strip() for h in last_tb["headers"]].count("2056-02-29") == 1

    # 3. Unsupported Investor export (GET /v2/workbook/investor/export) -> precise typed 409 refusal, never silent truncation
    iexp = env.client.get(
        "/v2/workbook/investor/export",
        params={"project": record.project_code, "history_id": entry.history_id},
    )
    assert iexp.status_code == 409
    assert iexp.json()["error"] == "Run-bound investor evidence is unavailable"

    # 4. Edit current draft AND execute a subsequent Run -> ORIGINAL history_id export remains financially immutable!
    _save_dated_book(env, record, amount=500, start_date="2031-03-01", end_date="2032-03-01")
    run_canonical(env, record.project_code)
    all_hist = get_run_history(record.user_id, record.project_id)
    assert len(all_hist) == 2
    orig_again = next(e for e in all_hist if e.history_id == entry.history_id)
    assert (
        json.dumps(
            [orig_again.financial_statements, orig_again.debt_schedule, orig_again.tax_schedule, orig_again.runtime_summary],
            sort_keys=True,
            default=str,
        )
        == before_hist
    )

    hexp_after = env.client.get(
        "/v2/workbook/run-history/export",
        params={"project": record.project_code, "history_id": entry.history_id},
    )
    assert hexp_after.status_code == 200
    wb_after = openpyxl.load_workbook(io.BytesIO(hexp_after.content), data_only=True)
    assert _extract_financial_payload_snapshot(wb_after) == payload1

    # 5. Negative controls: omitting, duplicating, or tampering with the terminal stub MUST fail the verifier.
    omitted = {k: {**v, "headers": list(v["headers"])[:-1]} if k == "P&L" else v for k, v in parsed1.items()}
    with pytest.raises(AssertionError):
        _verify_v3_export_against_history(omitted, pd_rows1, entry, expected_final_date="2056-02-29")

    duplicated = {
        k: {**v, "headers": list(v["headers"])[:-1] + [v["headers"][-1], v["headers"][-1]]} if k == "P&L" else v
        for k, v in parsed1.items()
    }
    with pytest.raises(AssertionError):
        _verify_v3_export_against_history(duplicated, pd_rows1, entry, expected_final_date="2056-02-29")

    tampered_pnl_rows = {
        m: ({**r, "values": list(r["values"])[:-1] + [float(r["values"][-1]) + 10.0]} if m == "Revenue" else r)
        for m, r in parsed1["P&L"]["rows"].items()
    }
    tampered = {**parsed1, "P&L": {**parsed1["P&L"], "rows": tampered_pnl_rows}}
    with pytest.raises(AssertionError):
        _verify_v3_export_against_history(tampered, pd_rows1, entry, expected_final_date="2056-02-29")


def test_real_route_export_dated_wind_and_unchanged_legacy_reference(with_sensitivity, monkeypatch):
    """Verify real XLSX export on dated Wind (off-boundary COD 2031-09-01 -> stub 2058-08-31) and legacy Solar (2055-12-31)."""
    env = with_sensitivity

    # 1. Dated Wind with off-boundary COD 2031-09-01 and 27y horizon -> final stub 2058-08-31
    wind = env.create(kind="wind", name="Dated Export Wind")
    env.client.get("/v2/workbook", params={"project": wind.project_code})
    _save_dated_book(
        env,
        wind,
        amount=2000,
        start_date="2031-09-01",
        end_date="2032-09-01",
        merchant_end_date="2058-09-01",
    )
    run_canonical(env, wind.project_code)
    w_entry = get_run_history(wind.user_id, wind.project_id)[0]
    w_exp = env.client.get(
        "/v2/workbook/run-history/export",
        params={"project": wind.project_code, "history_id": w_entry.history_id},
    )
    assert w_exp.status_code == 200
    wb_w = openpyxl.load_workbook(io.BytesIO(w_exp.content), data_only=True)
    parsed_w = {s: _parse_v3_periodic_sheet(wb_w[s]) for s in ("P&L", "Cash Flow", "Balance Sheet", "Tax_Bridge", "Debt_DSCR")}
    pd_w = [[wb_w["Periods_Dates"].cell(r, c).value for c in range(1, 5)] for r in range(6, wb_w["Periods_Dates"].max_row + 1)]
    _verify_v3_export_against_history(parsed_w, pd_w, w_entry, expected_final_date="2058-08-31")

    # 2. Unchanged legacy Solar reference (no R04 absolute contract) -> legacy final date 2055-12-31 (no stub).
    # FINCO45B: new Solar projects are OD-TIME-01/v1 by default; a LEGACY_CALENDAR/v0 project is created through the
    # explicit creation rollback so the retained legacy contract stays proved byte-for-byte here.
    monkeypatch.setenv("FINCO_NEW_PROJECT_DATE_AUTHORITY", "legacy")
    legacy = env.create(kind="solar", name="Legacy Export Solar")
    monkeypatch.delenv("FINCO_NEW_PROJECT_DATE_AUTHORITY")
    env.client.get("/v2/workbook", params={"project": legacy.project_code})
    run_canonical(env, legacy.project_code)
    l_entry = get_run_history(legacy.user_id, legacy.project_id)[0]
    l_exp = env.client.get(
        "/v2/workbook/run-history/export",
        params={"project": legacy.project_code, "history_id": l_entry.history_id},
    )
    assert l_exp.status_code == 200
    wb_l = openpyxl.load_workbook(io.BytesIO(l_exp.content), data_only=True)
    parsed_l = {s: _parse_v3_periodic_sheet(wb_l[s]) for s in ("P&L", "Cash Flow", "Balance Sheet", "Tax_Bridge", "Debt_DSCR")}
    pd_l = [[wb_l["Periods_Dates"].cell(r, c).value for c in range(1, 5)] for r in range(6, wb_l["Periods_Dates"].max_row + 1)]
    _verify_v3_export_against_history(parsed_l, pd_l, l_entry, expected_final_date="2055-12-31")
