"""Run Integrity Checks: deterministic recomputation over committed Last Run evidence.

Every check recomputes its identity from the recorded facts and compares it with what
the run reported. There is no model call, no market data, no LLM and no fuzzy matching.
Missing or malformed evidence is UNAVAILABLE (never PASS); a broken identity is FAIL.
"""
from __future__ import annotations

from datetime import date
import math
from typing import Any, Callable, Mapping

from app.run_integrity.contracts import (
    EVIDENCE_SCHEMA,
    TOL_KEUR,
    TOL_RATIO,
    TOL_XIRR,
    CheckStatus,
    IntegrityCheck,
    RunIntegrityReport,
)
from app.run_integrity.evidence import evidence_digest


def _unavailable(check_id: str, title: str, reason: str, detail: str = "") -> IntegrityCheck:
    return IntegrityCheck(check_id, title, CheckStatus.UNAVAILABLE, reason, detail=detail)


def _verdict(check_id, title, deviations, tolerance, fail_reason, *, evaluated, detail="") -> IntegrityCheck:
    worst = max(deviations, default=0.0)
    if worst > tolerance:
        return IntegrityCheck(check_id, title, CheckStatus.FAIL, fail_reason, evaluated,
                              worst, tolerance, detail)
    return IntegrityCheck(check_id, title, CheckStatus.PASS, None, evaluated, worst, tolerance, detail)


def _section(evidence: Mapping[str, Any], *path: str) -> Any:
    node: Any = evidence
    for key in path:
        if not isinstance(node, Mapping) or key not in node:
            return None
        node = node[key]
    return node


def _complete(row: Mapping[str, Any], *keys: str) -> bool:
    return all(isinstance(row.get(k), (int, float)) and not isinstance(row.get(k), bool) for k in keys)


# ── EVIDENCE: digest of what was recorded at commit ─────────────────────────

def check_evidence_digest(evidence: Mapping[str, Any]) -> IntegrityCheck:
    cid, title = "EVIDENCE_DIGEST", "Committed evidence is unaltered since commit"
    if evidence.get("schema") != EVIDENCE_SCHEMA:
        return _unavailable(cid, title, "EVIDENCE_SCHEMA_UNSUPPORTED")
    recorded = evidence.get("digest")
    if not recorded:
        return _unavailable(cid, title, "EVIDENCE_DIGEST_MISSING")
    if recorded != evidence_digest(dict(evidence)):
        return IntegrityCheck(cid, title, CheckStatus.FAIL, "EVIDENCE_DIGEST_MISMATCH",
                              detail="The recorded evidence no longer matches its commit-time digest.")
    return IntegrityCheck(cid, title, CheckStatus.PASS, evaluated=1)


# ── 1. Sources = Uses ───────────────────────────────────────────────────────

_USE_KEYS = ("base_project_capex_keur", "capitalized_idc_keur", "commitment_fee_keur",
             "structuring_fee_keur", "other_financing_costs_keur", "initial_dsra_funding_keur",
             "other_uses_keur", "development_cost_reimbursement_keur", "developer_fee_keur")
_DEVELOPER_USE_KEYS = ("development_cost_reimbursement_keur", "developer_fee_keur")
_SOURCE_KEYS = ("senior_debt_keur", "junior_or_other_keur", "share_capital_and_other_equity_keur",
                "shareholder_loan_cash_keur")


def check_sources_equal_uses(evidence: Mapping[str, Any]) -> IntegrityCheck:
    cid, title = "SOURCES_EQUAL_USES", "Sources equal Uses (no plug)"
    su = _section(evidence, "sources_uses", "summary")
    if not isinstance(su, Mapping):
        return _unavailable(cid, title, "SOURCES_USES_EVIDENCE_MISSING")
    # RUN_INTEGRITY_EVIDENCE_V1 may be missing separately itemised developer
    # uses in old persisted runs.  Neither a matching digest nor missing values
    # prove that Developer Economics was inactive.  Never default them to zero
    # or modify the historical evidence; report the unverifiable check.
    if any(key not in su for key in _DEVELOPER_USE_KEYS):
        return _unavailable(cid, title, "DEVELOPER_USES_EVIDENCE_MISSING")
    if any(
        not isinstance(su[key], (int, float))
        or isinstance(su[key], bool)
        or not math.isfinite(su[key])
        or su[key] < 0.0
        for key in _DEVELOPER_USE_KEYS
    ):
        return _unavailable(cid, title, "DEVELOPER_USES_EVIDENCE_INVALID")
    if not _complete(su, "total_uses_keur", "total_sources_keur",
                     *_USE_KEYS, *_SOURCE_KEYS):
        return _unavailable(cid, title, "SOURCES_USES_EVIDENCE_MISSING")
    uses = sum(su[k] for k in _USE_KEYS)
    sources = sum(su[k] for k in _SOURCE_KEYS)
    deviations = [abs(uses - su["total_uses_keur"]), abs(sources - su["total_sources_keur"]),
                  abs(sources - uses)]
    periods = _section(evidence, "sources_uses", "construction_periods") or []
    for p in periods:
        if not _complete(p, "uses", "sources"):
            return _unavailable(cid, title, "SOURCES_USES_PERIOD_EVIDENCE_MISSING")
        deviations.append(abs(p["sources"] - p["uses"]))
    return _verdict(cid, title, deviations, TOL_KEUR, "SOURCES_USES_MISMATCH",
                    evaluated=1 + len(periods),
                    detail="components sum to totals, Sources equal Uses in total and per construction period")


# ── 2. Balance sheet ────────────────────────────────────────────────────────

_BS_KEYS = ("gross_fixed_assets", "accumulated_depreciation", "unrestricted_cash", "dsra_balance",
            "distribution_account", "senior_debt", "shl", "share_capital", "share_premium",
            "legal_reserve", "retained_earnings", "net_cit_payable")


def check_balance_sheet(evidence: Mapping[str, Any]) -> IntegrityCheck:
    cid, title = "BALANCE_SHEET_BALANCES", "Assets = Liabilities + Equity"
    rows = _section(evidence, "balance_sheet")
    debt_periods = _section(evidence, "senior_debt", "periods")
    if not isinstance(rows, list) or not rows:
        return _unavailable(cid, title, "BALANCE_SHEET_EVIDENCE_MISSING")
    deviations, evaluated, evaluated_indices = [], 0, set()
    f3 = evidence.get("financing_authority") == "F3_TWO_SENIOR_EXPLICIT_COMMITMENTS_V1"
    for row in rows:
        if not _complete(row, *_BS_KEYS):
            continue  # construction / incomplete columns carry no balance identity
        assets = (row["gross_fixed_assets"] - row["accumulated_depreciation"]
                  + row["unrestricted_cash"] + row["dsra_balance"] + row["distribution_account"])
        liabilities_equity = (row["senior_debt"] + row["shl"] + row["share_capital"]
                              + row["share_premium"] + row["legal_reserve"]
                              + row["retained_earnings"] + row["net_cit_payable"])
        if f3:
            if not _complete(row, "additional_equity"):
                return _unavailable(cid, title, "F3_EQUITY_COMPONENTS_MISSING")
            liabilities_equity += row["additional_equity"]
        deviations.append(abs(assets - liabilities_equity))
        evaluated += 1
        evaluated_indices.add(row["period_index"])
    if not evaluated:
        return _unavailable(cid, title, "BALANCE_SHEET_COMPONENTS_MISSING")
    if isinstance(debt_periods, list):
        missing = [p["period_index"] for p in debt_periods if p.get("period_index") not in evaluated_indices]
        if missing:
            return _unavailable(cid, title, "BALANCE_SHEET_COVERAGE_INCOMPLETE",
                                f"{len(missing)} debt period(s) have no complete balance sheet column")
    return _verdict(cid, title, deviations, TOL_KEUR, "BALANCE_SHEET_IMBALANCE", evaluated=evaluated,
                    detail="assets recomputed from components; net CIT payable on the liabilities side")


# ── 3. Senior debt roll-forward ─────────────────────────────────────────────

def _debt_rows(evidence):
    rows = _section(evidence, "senior_debt", "periods")
    return rows if isinstance(rows, list) else None


def check_senior_rollforward(evidence: Mapping[str, Any]) -> IntegrityCheck:
    cid, title = "SENIOR_DEBT_ROLLFORWARD", "Opening + draws - principal = closing"
    rows = _debt_rows(evidence)
    su = _section(evidence, "sources_uses", "summary")
    if rows is None or not isinstance(su, Mapping) or not _complete(su, "senior_debt_keur"):
        return _unavailable(cid, title, "SENIOR_DEBT_EVIDENCE_MISSING")
    if not rows:
        if abs(su["senior_debt_keur"]) <= TOL_KEUR:
            return IntegrityCheck(cid, title, CheckStatus.NOT_APPLICABLE, "NO_SENIOR_DEBT")
        return IntegrityCheck(cid, title, CheckStatus.FAIL, "SENIOR_DEBT_SCHEDULE_MISSING",
                              detail="senior debt is committed but the schedule is empty")
    if not all(_complete(r, "opening", "principal", "closing") for r in rows):
        return _unavailable(cid, title, "SENIOR_DEBT_EVIDENCE_MISSING")
    deviations = []
    for row in rows:  # operating periods draw nothing: draws are committed before COD
        deviations.append(abs(row["opening"] - row["principal"] - row["closing"]))
        if row["principal"] < -TOL_KEUR or row["closing"] < -TOL_KEUR:
            deviations.append(abs(min(row["principal"], row["closing"])))
    for previous, current in zip(rows, rows[1:]):
        deviations.append(abs(current["opening"] - previous["closing"]))
    deviations.append(abs(rows[0]["opening"] - su["senior_debt_keur"]))  # draws sum to the commitment
    result = _verdict(cid, title, deviations, TOL_KEUR, "SENIOR_ROLLFORWARD_BREAK", evaluated=len(rows),
                      detail="period roll-forward, opening-to-closing chain, and first opening = committed senior debt")
    if result.status is CheckStatus.PASS and not _section(evidence, "senior_debt", "permit_terminal_balloon"):
        if rows[-1]["closing"] > TOL_KEUR:
            return IntegrityCheck(cid, title, CheckStatus.FAIL, "SENIOR_TERMINAL_BALANCE_UNREPAID",
                                  len(rows), rows[-1]["closing"], TOL_KEUR)
    return result


# ── 4. Interest and debt service ────────────────────────────────────────────

def check_interest_and_debt_service(evidence: Mapping[str, Any]) -> IntegrityCheck:
    cid, title = "INTEREST_DEBT_SERVICE_CONSISTENCY", "Interest = opening x rate x day fraction; DS = interest + principal"
    rows = _debt_rows(evidence)
    if rows is None:
        return _unavailable(cid, title, "SENIOR_DEBT_EVIDENCE_MISSING")
    if not rows:
        return IntegrityCheck(cid, title, CheckStatus.NOT_APPLICABLE, "NO_SENIOR_DEBT")
    if not all(_complete(r, "opening", "interest", "principal", "debt_service", "annual_rate", "day_fraction")
               for r in rows):
        return _unavailable(cid, title, "INTEREST_INPUT_EVIDENCE_MISSING")
    deviations = []
    for row in rows:
        deviations.append(abs(row["interest"] - row["opening"] * row["annual_rate"] * row["day_fraction"]))
        deviations.append(abs(row["debt_service"] - row["interest"] - row["principal"]))
    return _verdict(cid, title, deviations, TOL_KEUR, "INTEREST_OR_DEBT_SERVICE_MISMATCH", evaluated=len(rows))


# ── 5. DSCR = CFADS / debt service ──────────────────────────────────────────

def check_dscr_identity(evidence: Mapping[str, Any]) -> IntegrityCheck:
    cid, title = "DSCR_EQUALS_CFADS_OVER_DEBT_SERVICE", "Reported DSCR = base CFADS / debt service"
    rows = _debt_rows(evidence)
    if rows is None:
        return _unavailable(cid, title, "SENIOR_DEBT_EVIDENCE_MISSING")
    due = [r for r in rows if isinstance(r.get("debt_service"), (int, float)) and r["debt_service"] > TOL_KEUR]
    if not due:
        return IntegrityCheck(cid, title, CheckStatus.NOT_APPLICABLE, "NO_DEBT_SERVICE_DUE")
    if not all(_complete(r, "base_cfads", "reported_dscr") for r in due):
        return _unavailable(cid, title, "DSCR_INPUT_EVIDENCE_MISSING")
    deviations = [abs(r["reported_dscr"] - r["base_cfads"] / r["debt_service"]) for r in due]
    return _verdict(cid, title, deviations, TOL_RATIO * 100, "DSCR_MISMATCH", evaluated=len(due))


# ── 6. No unfunded cash deficit ─────────────────────────────────────────────

def check_no_unfunded_deficit(evidence: Mapping[str, Any]) -> IntegrityCheck:
    cid, title = "NO_UNFUNDED_CASH_DEFICIT", "No negative cash or reserve without a funding source"
    cash = _section(evidence, "cash")
    bs = _section(evidence, "balance_sheet")
    if not isinstance(cash, list) or not cash or not isinstance(bs, list):
        return _unavailable(cid, title, "CASH_EVIDENCE_MISSING")
    if not all(_complete(c, "cash_after_senior_before_reserves") for c in cash):
        return _unavailable(cid, title, "CASH_EVIDENCE_MISSING")
    worst, evaluated = 0.0, 0
    for c in cash:
        worst = max(worst, -c["cash_after_senior_before_reserves"])
        evaluated += 1
    for row in bs:
        for key in ("unrestricted_cash", "dsra_balance", "distribution_account"):
            value = row.get(key)
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                worst = max(worst, -value)
                evaluated += 1
    if worst > TOL_KEUR:
        return IntegrityCheck(cid, title, CheckStatus.FAIL, "NEGATIVE_CASH_WITHOUT_FUNDING_SOURCE",
                              evaluated, worst, TOL_KEUR,
                              "a negative balance would imply an unmodelled source of funds")
    return IntegrityCheck(cid, title, CheckStatus.PASS, None, evaluated, max(worst, 0.0), TOL_KEUR)


# ── 7. DSCR sculpting feasibility ───────────────────────────────────────────

def check_dscr_feasibility(evidence: Mapping[str, Any]) -> IntegrityCheck:
    cid, title = "DSCR_SCULPTING_FEASIBLE", "Sculpted debt service fits inside CFADS / target DSCR"
    diagnostics = _section(evidence, "senior_debt", "diagnostics")
    rows = _debt_rows(evidence)
    if not isinstance(diagnostics, Mapping) or rows is None:
        return _unavailable(cid, title, "SENIOR_DEBT_EVIDENCE_MISSING")
    if not rows:
        return IntegrityCheck(cid, title, CheckStatus.NOT_APPLICABLE, "NO_SENIOR_DEBT")
    if diagnostics.get("termination_reason") != "CONVERGED" or diagnostics.get("is_authoritative") is not True:
        return IntegrityCheck(cid, title, CheckStatus.FAIL, "DSCR_SCULPTING_NOT_AUTHORITATIVE",
                              detail=f"termination_reason={diagnostics.get('termination_reason')!r}")
    if not all(_complete(r, "debt_service", "bank_cfads", "target_dscr", "availability") for r in rows):
        return _unavailable(cid, title, "DSCR_FEASIBILITY_EVIDENCE_MISSING")
    excess = []
    for r in rows:
        allowed = max(0.0, r["bank_cfads"] / r["target_dscr"]) * r["availability"]
        excess.append(max(0.0, r["debt_service"] - allowed))
    return _verdict(cid, title, excess, TOL_KEUR, "DSCR_SCULPTING_INFEASIBLE_SCHEDULE", evaluated=len(rows),
                    detail="scheduled debt service <= allowed debt service in every period; result is authoritative")


# ── 8. Sponsor-return inputs ────────────────────────────────────────────────

def _xirr(cashflows: list[float], dates: list[date]) -> float | None:
    from finco_core.sponsor.xirr import xirr

    try:
        return xirr(cashflows, dates)
    except Exception:  # noqa: BLE001 - a non-converging recomputation is reported, not raised
        return None


def check_sponsor_return_inputs(evidence: Mapping[str, Any]) -> IntegrityCheck:
    cid, title = "SPONSOR_RETURN_INPUTS_RECONCILE", "XIRR flows reconcile with committed sponsor cash flows"
    sponsor = _section(evidence, "sponsor")
    if not isinstance(sponsor, Mapping) or not sponsor.get("periods"):
        return _unavailable(cid, title, "SPONSOR_EVIDENCE_MISSING")
    rows = sponsor["periods"]
    parts = ("share_capital", "share_premium", "other_committed_equity", "additional_equity",
             "shl_contribution", "shl_cash_interest", "shl_principal", "legal_equity_distribution",
             "pure_equity_net", "total_sponsor_net")
    if not all(_complete(r, *parts) and r.get("date") for r in rows):
        return _unavailable(cid, title, "SPONSOR_EVIDENCE_MISSING")
    deviations = []
    for r in rows:
        contributions = r["share_capital"] + r["share_premium"] + r["other_committed_equity"] + r["additional_equity"]
        pure = r["legal_equity_distribution"] - contributions
        total = pure - r["shl_contribution"] + r["shl_cash_interest"] + r["shl_principal"]
        deviations.append(abs(pure - r["pure_equity_net"]))
        deviations.append(abs(total - r["total_sponsor_net"]))
    result = _verdict(cid, title, deviations, TOL_KEUR, "SPONSOR_FLOW_COMPONENT_MISMATCH", evaluated=len(rows),
                      detail="each sponsor flow is built once from its equity and shareholder-loan components")
    if result.status is not CheckStatus.PASS:
        return result

    reported = sponsor.get("reported") or {}
    dates = [date.fromisoformat(r["date"]) for r in rows]
    if dates != sorted(dates):
        return IntegrityCheck(cid, title, CheckStatus.FAIL, "SPONSOR_FLOW_DATES_NOT_CHRONOLOGICAL",
                              len(rows))
    reasons: list[str] = []
    worst = result.max_abs_deviation or 0.0
    for key, series in (("pure_equity_xirr", "pure_equity_net"), ("total_sponsor_xirr", "total_sponsor_net")):
        published = reported.get(key)
        status = reported.get(key + "_status")
        if status != "OK" or published is None:
            reasons.append(f"{key}:{status}")
            continue
        recomputed = _xirr([r[series] for r in rows], dates)
        if recomputed is None or abs(recomputed - published) > TOL_XIRR:
            return IntegrityCheck(cid, title, CheckStatus.FAIL, "XIRR_RECOMPUTATION_MISMATCH", len(rows),
                                  None if recomputed is None else abs(recomputed - published), TOL_XIRR,
                                  f"{key} does not reproduce from the committed flows")
        worst = max(worst, abs(recomputed - published))
    if reasons and len(reasons) == 2:
        return IntegrityCheck(cid, title, CheckStatus.NOT_APPLICABLE,
                              "RETURN_METRICS_NOT_PUBLISHED", len(rows), worst, TOL_KEUR,
                              "flows reconcile; no return was published to recompute: " + ", ".join(reasons))
    return IntegrityCheck(cid, title, CheckStatus.PASS, None, len(rows), worst, TOL_KEUR,
                          "flows reconcile and published XIRR values reproduce" + (
                              f" (not published: {', '.join(reasons)})" if reasons else ""))


CHECKS: tuple[Callable[[Mapping[str, Any]], IntegrityCheck], ...] = (
    check_evidence_digest,
    check_sources_equal_uses,
    check_balance_sheet,
    check_senior_rollforward,
    check_interest_and_debt_service,
    check_dscr_identity,
    check_no_unfunded_deficit,
    check_dscr_feasibility,
    check_sponsor_return_inputs,
)


def _identity(check: Callable[[Mapping[str, Any]], IntegrityCheck]) -> tuple[str, str]:
    """A check's own id and title (every check answers empty evidence with UNAVAILABLE)."""
    probe = check({})
    return probe.check_id, probe.title


def run_integrity_checks(evidence: Mapping[str, Any] | None) -> RunIntegrityReport:
    """Evaluate every check over committed evidence. Never raises; never re-runs the model."""
    if not isinstance(evidence, Mapping) or not evidence:
        return RunIntegrityReport(tuple(
            _unavailable(*_identity(check), "INTEGRITY_EVIDENCE_NOT_PERSISTED",
                         "this Last Run was committed before integrity evidence was recorded; "
                         "run and commit again")
            for check in CHECKS
        ))
    results = []
    for check in CHECKS:
        try:
            results.append(check(evidence))
        except Exception:  # noqa: BLE001 - malformed evidence must not become PASS or crash the surface
            results.append(_unavailable(*_identity(check), "CHECK_EVIDENCE_MALFORMED"))
    return RunIntegrityReport(tuple(results), evidence.get("digest"))
