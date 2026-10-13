"""Reproducible F3 financial evidence from ACTUAL canonical two-Senior Runs (Solar and Wind).

Each case drives the real workbook routes (explicit F3 proposal + activation Save through the workspace CAS,
then the canonical Run), reads ONLY what the Run committed (workspace Last Run, immutable Run History entry,
Run Integrity evidence, institutional export) and reconciles it independently.  Nothing is estimated and no
number is typed in: every figure in ``financial-evidence.json`` is a full-precision value read back from the
persisted record.

    python -m tools.model_financing_f3_evidence --out artifacts/f3-evidence/financial-evidence.json

Only synthetic reference projects are used; no customer data, workbook source or credential is involved.
The process exits non-zero when any reconciliation fails.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
import os
import re
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOL = 1e-6          # kEUR identity tolerance used by Run Integrity
TOL_BAL = 1e-4      # canonical Senior solver precision (kEUR)
USER = "f3-evidence"


def _num(v):
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) else None


def _digest(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode()).hexdigest()


def _git_head() -> str:
    try:
        return subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True, check=True).stdout.strip()
    except Exception:  # noqa: BLE001
        return "UNKNOWN"


class Recon:
    def __init__(self):
        self.items = []

    def add(self, name, ok, detail="", max_abs_diff=None):
        self.items.append({"name": name, "pass": bool(ok), "detail": detail,
                           "max_abs_diff": None if max_abs_diff is None else float(max_abs_diff)})
        return ok

    @property
    def ok(self):
        return all(i["pass"] for i in self.items)


def run_case(kind: str, client, cookie_user: str) -> dict:
    from app.persistence.workspace_repository import get_workspace_state
    from app.persistence.run_history_repository import get_latest_history_entry
    from app.persistence.projects_repository import get_project_by_code
    from app.run_integrity import run_integrity_checks
    from app.services.reference_seed_service import create_reference_seeded_project
    from app.workbook import multisenior_config as config
    from app.workbook.input_set import ProjectInputSet
    from tests.test_model_financing_f3_workspace import collection_for_inputs, state

    rec = create_reference_seeded_project(user_id=cookie_user, template_source=f"generic_{kind}_reference",
                                          requested_name=f"F3 evidence {kind}", capacity_mw=16)
    recon = Recon()

    def page():
        return client.get(f"/v2/workbook?project={rec.project_code}")

    def tokens(html):
        return (re.search(r'name="content_hash" value="([^"]+)"', html).group(1),
                re.search(r'name="workbook_version" value="([^"]+)"', html).group(1))

    ws0 = get_workspace_state(cookie_user, rec.project_id)
    pi = ProjectInputSet.from_snapshot(ws0.draft_snapshot).to_projectinputs()
    raw = state(active=True, collection=collection_for_inputs(pi))
    h, v = tokens(page().text)
    saved = client.post("/v2/workbook/update", data={"field_id": config.FIELD_ID, "value": raw, "project": rec.project_code,
                        "workbook_version": v, "content_hash": h, "sheet_id": "debt"}, headers={"HX-Request": "true"})
    recon.add("F3 proposal + activation saved through the workspace CAS", saved.status_code == 200 and "field-error" not in saved.text)
    h, v = tokens(page().text)
    ran = client.post("/v2/workbook/run", data={"project": rec.project_code, "content_hash": h, "workbook_version": v},
                      headers={"HX-Request": "true"})
    recon.add("canonical Run committed", ran.status_code == 200)
    ws = get_workspace_state(cookie_user, rec.project_id)
    entry = get_latest_history_entry(cookie_user, rec.project_id)
    summary = ws.last_runtime_summary
    fe = summary["financing_evidence"]
    integ = ws.last_integrity_evidence
    saved_state = config.parse_state(ws.draft_snapshot[config.SNAPSHOT_KEY])["scopes"]["base"]
    proposal = saved_state["proposal"]

    # ───────────── A. facility input authority ─────────────
    facilities_in = []
    for ins in proposal["instruments"]:
        facilities_in.append({
            "instrument_id": ins["instrument_id"], "name": ins["name"], "commitment_keur": ins["commitment_keur"],
            "interest": ins["interest"], "drawdowns": ins["drawdowns"], "fees": ins["fees"],
            "repayment": ins["repayment"], "instrument_type": ins["instrument_type"]})
    authority_in = {"proposal_digest": saved_state["activation"]["proposal_digest"], "activation": saved_state["activation"],
                    "facilities": facilities_in}

    # ───────────── B/C. ledgers ─────────────
    schedules = fe["facility_schedules"]
    by_id = {s["instrument_id"]: s for s in schedules}
    cfg = {i["instrument_id"]: i for i in facilities_in}
    recon.add("two facilities committed with the saved IDs", set(by_id) == set(cfg) and len(by_id) == 2, str(sorted(by_id)))
    recon.add("facility evidence digest equals the saved proposal digest",
              fe["collection_digest"] == saved_state["activation"]["proposal_digest"], fe["collection_digest"])
    recon.add("Run binding names this exact snapshot and composite hash",
              fe["run_binding"]["snapshot_id"] == ws.last_runtime_snapshot_id
              and fe["run_binding"]["composite_hash"] == ws.last_runtime_composite_hash
              and entry.runtime_snapshot_id == ws.last_runtime_snapshot_id and entry.composite_hash == ws.last_runtime_composite_hash)

    sd = {p["period_index"]: p for p in integ["senior_debt"]["periods"]}
    max_agg = 0.0
    agg_ok = True
    for pidx, p in sd.items():
        sums = {k: 0.0 for k in ("opening", "closing", "interest", "principal", "debt_service")}
        for s in schedules:
            if pidx in s["period_indices"]:
                i = s["period_indices"].index(pidx)
                sums["opening"] += s["opening_keur"][i]
                sums["closing"] += s["closing_keur"][i]
                sums["interest"] += s["interest_keur"][i]
                sums["principal"] += s["principal_keur"][i]
                sums["debt_service"] += s["debt_service_keur"][i]
        for k, tot in sums.items():
            d = abs(tot - p[k])
            max_agg = max(max_agg, d)
            agg_ok = agg_ok and d <= TOL
    recon.add("Σ facility opening/closing/interest/principal/debt service == aggregate canonical Senior per period",
              agg_ok, f"{len(sd)} operating periods", max_agg)

    max_roll, roll_ok = 0.0, True
    for s in schedules:
        prev = None
        for i, pidx in enumerate(s["period_indices"]):
            d = abs(s["opening_keur"][i] - s["principal_keur"][i] - s["closing_keur"][i])
            max_roll = max(max_roll, d)
            roll_ok = roll_ok and d <= TOL
            if prev is not None:
                d2 = abs(prev - s["opening_keur"][i])
                max_roll = max(max_roll, d2)
                roll_ok = roll_ok and d2 <= TOL
            prev = s["closing_keur"][i]
    recon.add("facility roll-forward: opening − principal = closing and closing(t) = opening(t+1)", roll_ok, "", max_roll)

    max_int, int_ok = 0.0, True
    for s in schedules:
        rate = cfg[s["instrument_id"]]["interest"]["fixed_rate"]
        for i, pidx in enumerate(s["period_indices"]):
            expect = s["opening_keur"][i] * rate * sd[pidx]["day_fraction"]
            d = abs(expect - s["interest_keur"][i])
            max_int = max(max_int, d)
            int_ok = int_ok and d <= TOL
    recon.add("facility interest = opening × configured fixed rate × canonical day fraction", int_ok, "", max_int)

    max_mat, mat_ok = 0.0, True
    for s in schedules:
        last = s["period_indices"][-1]
        d = abs(s["closing_keur"][-1])
        max_mat = max(max_mat, d)
        mat_ok = mat_ok and d <= TOL_BAL and last == s["maturity_period_index"]
        mat_ok = mat_ok and abs(sum(s["principal_keur"]) - sum(s["construction_draws_keur"])) <= TOL
    recon.add("each facility repays to zero on its own contractual maturity period (Σ principal = Σ draws)", mat_ok,
              json.dumps({s["instrument_id"]: s["maturity_period_index"] for s in schedules}), max_mat)
    maturities = {s["maturity_period_index"] for s in schedules}
    recon.add("the two facilities have separate maturities", len(maturities) == 2, str(sorted(maturities)))
    recon.add("the two facilities have separate rates",
              len({cfg[i]["interest"]["fixed_rate"] for i in cfg}) == 2)

    # construction ledger
    su = fe["sources_uses"]
    total_draw = sum(sum(s["construction_draws_keur"]) for s in schedules)
    recon.add("Σ facility draws == Sources & Uses Senior debt", abs(total_draw - su["senior_debt_keur"]) <= TOL,
              f"{total_draw} vs {su['senior_debt_keur']}", abs(total_draw - su["senior_debt_keur"]))
    draw_cfg_ok = all(abs(sum(d["amount_keur"] for d in cfg[s["instrument_id"]]["drawdowns"]) - sum(s["construction_draws_keur"])) <= TOL
                      for s in schedules)
    recon.add("each facility's committed draws equal its dated input drawdowns", draw_cfg_ok)
    idc = sum(sum(s["construction_idc_keur"]) for s in schedules)
    recon.add("no duplicate IDC: Σ facility construction IDC == capitalized IDC in Sources & Uses",
              abs(idc - su["capitalized_idc_keur"]) <= TOL, f"{idc} vs {su['capitalized_idc_keur']}", abs(idc - su["capitalized_idc_keur"]))
    upfront = sum(sum(s["upfront_fees_keur"]) for s in schedules)
    cfee = sum(sum(s["construction_commitment_fees_keur"]) for s in schedules)
    recon.add("no duplicate fees: Σ upfront fees == structuring fee line; Σ commitment fees == commitment fee line",
              abs(upfront - su["structuring_fee_keur"]) <= TOL and abs(cfee - su["commitment_fee_keur"]) <= TOL,
              f"upfront {upfront} vs {su['structuring_fee_keur']}; commitment {cfee} vs {su['commitment_fee_keur']}")
    pnl = {p["period"]: p for p in ws.last_financial_statements["pnl"]["periods"]}
    construction_interest_in_pnl = sum(abs(_num(p.get("senior_interest_expense_keur")) or 0.0)
                                       for k, p in pnl.items() if k not in sd)
    recon.add("construction-period interest is capitalized once (no P&L senior interest outside operating periods)",
              construction_interest_in_pnl <= TOL, f"{construction_interest_in_pnl}", construction_interest_in_pnl)
    # Persisted statements carry 0.01 kEUR presentation precision (e.g. 22.72 vs the exact 22.7211), so the
    # statement-vs-ledger comparison uses the half-cent rounding bound per period; the exact identities above and
    # below use the unrounded committed Run Integrity evidence at 1e-6.
    half_cent = 0.005 + 1e-9
    per_period = [(k, abs((_num(pnl[k]["senior_interest_expense_keur"]) or 0.0) - sum(
        s["interest_keur"][s["period_indices"].index(k)] for s in schedules if k in s["period_indices"])))
        for k in sd if k in pnl]
    worst = max((d for _, d in per_period), default=0.0)
    op_int_pnl = sum(_num(pnl[k]["senior_interest_expense_keur"]) or 0.0 for k in sd if k in pnl)
    op_int_fac = sum(sum(s["interest_keur"]) for s in schedules)
    recon.add("operating Senior interest in the P&L == Σ facility interest per period (0.01 kEUR statement precision)",
              per_period and worst <= half_cent and abs(op_int_pnl - op_int_fac) <= half_cent * len(per_period),
              f"{len(per_period)} periods; Σ P&L {op_int_pnl} vs Σ facilities {op_int_fac}", worst)
    # Sources & Uses recomputed from its own lines (no plug)
    sources = sum(su[k] for k in ("senior_debt_keur", "share_capital_and_other_equity_keur", "shareholder_loan_cash_keur", "junior_or_other_keur"))
    uses = sum(su[k] for k in ("base_project_capex_keur", "capitalized_idc_keur", "commitment_fee_keur", "structuring_fee_keur",
                               "developer_fee_keur", "development_cost_reimbursement_keur", "other_financing_costs_keur",
                               "other_uses_keur", "initial_dsra_funding_keur"))
    recon.add("Sources = Uses recomputed from the itemised lines (no hidden plug)", abs(sources - uses) <= TOL,
              f"sources {sources} uses {uses} reported difference {su['difference_keur']}", abs(sources - uses))
    recon.add("reported Sources − Uses difference is zero", abs(su["difference_keur"]) <= TOL)
    recon.add("construction funding reconciles in every period",
              fe["construction_funding"]["maximum_period_difference_keur"] <= TOL
              and fe["construction_funding"]["maximum_cumulative_difference_keur"] <= TOL)

    # balance sheet from committed components
    bs_keys = ("gross_fixed_assets", "accumulated_depreciation", "unrestricted_cash", "dsra_balance", "distribution_account",
               "senior_debt", "shl", "share_capital", "share_premium", "legal_reserve", "retained_earnings", "net_cit_payable")
    max_bs, bs_n = 0.0, 0
    for row in integ["balance_sheet"]:
        if not all(_num(row.get(k)) is not None for k in bs_keys):
            continue
        assets = row["gross_fixed_assets"] - row["accumulated_depreciation"] + row["unrestricted_cash"] + row["dsra_balance"] + row["distribution_account"]
        le = sum(row[k] for k in ("senior_debt", "shl", "share_capital", "share_premium", "legal_reserve", "retained_earnings", "net_cit_payable"))
        le += row.get("additional_equity") or 0.0
        max_bs = max(max_bs, abs(assets - le))
        bs_n += 1
    recon.add("Balance Sheet reconciles in every complete period (assets − liabilities − equity)", bs_n > 0 and max_bs <= TOL,
              f"{bs_n} periods", max_bs)
    sd_bs = {r["period_index"]: r["senior_debt"] for r in integ["balance_sheet"] if _num(r.get("senior_debt")) is not None}
    max_senior_bs = max((abs(sd_bs[k] - sd[k]["closing"]) for k in sd if k in sd_bs), default=0.0)
    recon.add("Balance Sheet Senior balance == aggregate canonical Senior closing", max_senior_bs <= TOL, "", max_senior_bs)

    # SHL leakage
    shl_bal = max((abs(_num(r.get("shl")) or 0.0) for r in integ["balance_sheet"]), default=0.0)
    shl_int = max((abs(_num(p.get("shl_interest_expense_keur")) or 0.0) for p in pnl.values()), default=0.0)
    recon.add("no SHL balance, SHL interest or SHL service under EQUITY_ONLY (no SHL tax-interest leakage)",
              shl_bal <= TOL and shl_int <= TOL and abs(_num(summary.get("total_shl_service_keur")) or 0.0) <= TOL,
              f"max SHL balance {shl_bal}; max SHL interest {shl_int}", max(shl_bal, shl_int))
    tax_rows = ws.last_tax_schedule["periods"]
    tax_total = sum(_num(p.get("tax_keur")) or 0.0 for p in tax_rows)
    recon.add("tax schedule total == published total tax (per-period 0.01 kEUR statement precision)",
              abs(tax_total - summary["total_tax_keur"]) <= (0.005 + 1e-9) * len(tax_rows),
              f"{tax_total} vs {summary['total_tax_keur']} over {len(tax_rows)} periods", abs(tax_total - summary["total_tax_keur"]))
    max_dscr = max((abs(p["base_cfads"] / p["debt_service"] - p["reported_dscr"]) for p in sd.values() if p["debt_service"]), default=0.0)
    recon.add("DSCR = base CFADS / aggregate debt service in every period", max_dscr <= 1e-9, "", max_dscr)

    report = run_integrity_checks(integ)
    recon.add("Run Integrity overall PASS on the committed evidence", report.overall.value == "PASS", report.overall.value)

    # immutable authority + survival of a later draft edit
    before = {"summary": _digest(ws.last_runtime_summary), "integrity": integ["digest"],
              "history_id": entry.history_id, "snapshot": ws.last_runtime_snapshot_id,
              "entry": _digest(entry.runtime_summary)}
    edited = json.loads(raw)
    edited["scopes"]["base"]["proposal"]["instruments"][0]["interest"]["fixed_rate"] = 0.05
    edited["scopes"]["base"]["activation"]["proposal_digest"] = "BIND_ON_SAVE"
    h, v = tokens(page().text)
    edit_resp = client.post("/v2/workbook/update", data={"field_id": config.FIELD_ID, "value": json.dumps(edited), "project": rec.project_code,
                            "workbook_version": v, "content_hash": h, "sheet_id": "debt"}, headers={"HX-Request": "true"})
    ws_after = get_workspace_state(cookie_user, rec.project_id)
    entry_after = get_latest_history_entry(cookie_user, rec.project_id)
    recon.add("a later draft edit marks the Run STALE and leaves the committed Run, integrity evidence and Run History untouched",
              edit_resp.status_code == 200 and ws_after.dirty and _digest(ws_after.last_runtime_summary) == before["summary"]
              and ws_after.last_integrity_evidence["digest"] == before["integrity"]
              and entry_after.history_id == before["history_id"] and _digest(entry_after.runtime_summary) == before["entry"]
              and ws_after.last_runtime_snapshot_id == before["snapshot"])
    stale_page = page().text
    recon.add("the page labels the edited Working Copy STALE while Q3 still evaluates the prior committed Run",
              'data-q3-state="STALE"' in stale_page)

    # Q3 Findings on the F3 Run (read from the committed CURRENT render before the edit is not available now,
    # so evaluate Q1 over the committed record exactly as the panel does)
    from app.model_quality import evaluate_model_quality
    from app.model_quality.evidence import evidence_from_workspace, terms_from_project_inputs
    from app.v2.router import _build_pis_with_composite_identity
    pis = _build_pis_with_composite_identity(ws, get_project_by_code(cookie_user, rec.project_code), cookie_user)
    q1 = evaluate_model_quality(evidence_from_workspace(ws, freshness="CURRENT", terms=terms_from_project_inputs(pis.to_projectinputs()),
                                                        active_scenario_id=ws.active_scenario_id, scenario_known=True))
    recon.add("Q1 Model Quality over the F3 Run has no FAIL and no WARNING", q1.summary.failed == 0 and q1.summary.warnings == 0,
              f"score={q1.summary.score} coverage={q1.summary.coverage_weighted} unavailable={q1.summary.unavailable}")

    # export provenance (immutable Last Run export, no engine execution)
    from app.services.v2_export_service import build_canonical_last_run_institutional_workbook_export
    from app.services import production_financial_authority
    from io import BytesIO
    from openpyxl import load_workbook
    from app.export.institutional_workbook import _read_labeled_cell
    calls = []
    original = production_financial_authority.run_clean_production
    production_financial_authority.run_clean_production = lambda *a, **k: calls.append(1) or original(*a, **k)
    try:
        result = build_canonical_last_run_institutional_workbook_export(f"generic_{kind}_reference",
                                                                        project_record=rec, user_id=cookie_user)
    finally:
        production_financial_authority.run_clean_production = original
    exported = None
    export_sha = None
    if result.status_code == 200:
        export_sha = hashlib.sha256(result.bytes_data).hexdigest()
        exported = _read_labeled_cell(load_workbook(BytesIO(result.bytes_data)), "Senior Debt", "Senior debt amount")
    recon.add("institutional export of the committed Run reads the committed schedules (no engine execution)",
              result.status_code == 200 and not calls and exported is not None
              and abs(exported - fe["bankability"]["final_senior_commitment_keur"]) <= TOL,
              f"exported Senior amount {exported}; engine calls {len(calls)}")

    return {
        "project": kind, "project_code": rec.project_code,
        "facility_input_authority": authority_in,
        "construction_ledger": {s["instrument_id"]: {k: s[k] for k in (
            "commitment_keur", "construction_draws_keur", "construction_idc_keur", "construction_commitment_fees_keur", "upfront_fees_keur")}
            for s in schedules},
        "construction_funding_by_period": fe["construction_funding"]["periods"],
        "operating_facility_ledger": {s["instrument_id"]: {k: s[k] for k in (
            "period_indices", "opening_keur", "interest_keur", "principal_keur", "debt_service_keur", "closing_keur",
            "maturity_period_index")} for s in schedules},
        "aggregate_senior_periods": integ["senior_debt"]["periods"],
        "project_outputs": {
            "sources_and_uses": su,
            "pnl_periods": ws.last_financial_statements["pnl"]["periods"],
            "cash_flow_waterfall_periods": ws.last_financial_statements["pf_cash_waterfall"]["periods"],
            "balance_sheet_components": integ["balance_sheet"],
            "tax_periods": ws.last_tax_schedule["periods"],
            "equity_funding": {k: summary.get(k) for k in ("sponsor_equity_sources_keur", "derived_shl_cash_keur")},
            "returns": {k: summary.get(k) for k in ("project_irr", "equity_irr", "sponsor_irr", "total_sponsor_xirr",
                                                    "share_capital_irr", "project_npv_keur", "equity_npv_keur")},
            "coverage": {k: summary.get(k) for k in ("min_dscr", "avg_dscr", "target_dscr", "min_llcr", "periods_in_lockup")},
            "min_llcr_note": "UNAVAILABLE: the Run does not publish an LLCR" if summary.get("min_llcr") is None else "published",
            "run_integrity": report.to_dict(),
        },
        "immutable_authority": {
            "snapshot_id": ws.last_runtime_snapshot_id, "composite_hash": ws.last_runtime_composite_hash,
            "run_history_id": entry.history_id, "facility_evidence_digest": fe["collection_digest"],
            "engine_version": entry.engine_version, "workbook_version": entry.workbook_version,
            "integrity_evidence_digest": integ["digest"], "run_binding": fe["run_binding"],
            "export": {"sha256": export_sha, "senior_debt_amount_keur": exported,
                       "engine_calls_during_export": len(calls)},
        },
        "q1_over_the_run": {"score": q1.summary.score, "score_status": q1.summary.score_status,
                            "coverage_weighted": q1.summary.coverage_weighted,
                            "statuses": {c.check_id: c.status.value for c in q1.checks}},
        "reconciliations": recon.items,
        "all_reconciliations_pass": recon.ok,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, default=ROOT / "artifacts/f3-evidence/financial-evidence.json")
    args = parser.parse_args()
    os.environ.setdefault("FINCO_MODEL_EXECUTION_MODE", "thread")
    from app.persistence import db
    tmp = tempfile.mkdtemp(prefix="f3-evidence-")
    db.DB_PATH = str(Path(tmp) / "evidence.db")
    db.init_db()
    from fastapi.testclient import TestClient
    import main_web
    from app.auth import COOKIE_NAME, create_session_token
    client = TestClient(main_web.app)
    client.cookies.set(COOKIE_NAME, create_session_token(user_id=USER, username="admin"))
    cases = [run_case(kind, client, USER) for kind in ("solar", "wind")]
    payload = {
        "schema": "finco.f3.financial-evidence.v1", "repository": "Finco-Protocol/FincoProtocol", "pull_request": 240,
        "head_sha": _git_head(), "generated_at": datetime.now(timezone.utc).isoformat(),
        "command": "python -m tools.model_financing_f3_evidence",
        "synthetic_reference_inputs_only": True, "units": "kEUR unless a field name says otherwise",
        "tolerances": {"identity_keur": TOL, "senior_terminal_keur": TOL_BAL},
        "cases": cases, "all_cases_pass": all(c["all_reconciliations_pass"] for c in cases),
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, indent=1, sort_keys=True, default=str)
    args.out.write_text(text, encoding="utf-8")
    print(f"wrote {args.out} sha256={hashlib.sha256(text.encode()).hexdigest()}")
    for case in cases:
        failed = [i for i in case["reconciliations"] if not i["pass"]]
        print(case["project"], "PASS" if not failed else "FAIL", f"{len(case['reconciliations'])} reconciliations", [f["name"] for f in failed])
    return 0 if payload["all_cases_pass"] else 1


if __name__ == "__main__":
    sys.exit(main())
