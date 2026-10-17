"""Read-only Diagnostics over ONE canonical Quality evaluation and committed evidence.

No scorer, financial output assembly or replacement validator lives here. Local checks
call the existing Integrity validator on a restricted evidence view. Senior continuity
uses prefix scope (including initial funding and the terminal boundary on the last
prefix). Sources/Uses and sculpting retain their global prerequisites explicitly.
Those scopes are visible, never misrepresented as independent single-period checks.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Mapping

from app.model_quality.contracts import QualityReport
from app.run_integrity import checks as integrity
from app.v2.output_workspace_projection import _num, period_label
from app.services.model_performance import observed


@dataclass(frozen=True)
class RunIdentity:
    snapshot_id: str | None
    composite_hash: str | None
    run_at: str | None
    engine_version: str | None
    scenario_id: str | None


@dataclass(frozen=True)
class PeriodEvidence:
    check_id: str
    snapshot_id: str | None
    run_identity: RunIdentity
    period_index: int
    date: str | None
    applicable: bool | None
    status: str
    scope: str
    residual: float | None = None
    tolerance: float | None = None
    observed: float | None = None
    expected: float | None = None
    evidence_source: str = ""
    reason: str | None = None


# Registry identities, not a second registry: rules are the original pure validators.
PERIOD_VALIDATORS = {
    "QM-ACC-001": integrity.check_balance_sheet,
    "QM-SU-001": integrity.check_sources_equal_uses,
    "QM-SD-001": integrity.check_senior_rollforward,
    "QM-SD-002": integrity.check_interest_and_debt_service,
    "QM-SD-003": integrity.check_dscr_identity,
    "QM-SD-004": integrity.check_dscr_feasibility,
    "QM-CASH-001": integrity.check_no_unfunded_deficit,
}
GLOBAL_CHECKS = frozenset({"QM-ACC-004", "QM-SD-005", "QM-CASH-002", "QM-COV-004",
                          "QM-CAP-001", "QM-SU-003", "QM-PRV-001", "QM-PRV-002",
                          "QM-PRV-003", "QM-PRV-004", "QM-PRV-005"})
MAX_RENDERED_PERIODS = 600


def _rows(container: Any, section: str | None = None) -> list[Mapping]:
    if section:
        container = container.get(section) if isinstance(container, Mapping) else None
    if isinstance(container, Mapping):
        container = container.get("periods")
    return [r for r in container if isinstance(r, Mapping)] if isinstance(container, list) else []


def _index(row: Mapping) -> int | None:
    value = row.get("period_index", row.get("period"))
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _axis(ws: Any, evidence: Mapping) -> tuple[list[dict], int]:
    # Dates come from persisted schedules, never the editable Working Copy calendar.
    dates: dict[int, str | None] = {}
    statements = getattr(ws, "last_financial_statements", None) or {}
    for rows in (_rows(statements, "pnl"), _rows(statements, "balance_sheet"),
                 _rows(statements, "pf_cash_waterfall"), _rows(evidence, "sponsor"),
                 _rows(evidence, "senior_debt"), _rows(evidence, "balance_sheet"),
                 _rows(evidence, "cash"), (evidence.get("sources_uses") or {}).get("construction_periods", [])):
        for row in rows:
            if not isinstance(row, Mapping) or _index(row) is None:
                continue
            i = _index(row)
            date = str(row.get("date") or "") or None
            if i not in dates or dates[i] is None:
                dates[i] = date
    indices = sorted(dates)
    return [{"index": i, "date": dates[i],
             "label": f"P{i} · {period_label(dates[i])}" if dates[i] else f"P{i} · date unavailable"}
            for i in indices[:MAX_RENDERED_PERIODS]], len(indices)


def _restricted(check_id: str, ev: Mapping, index: int) -> tuple[dict | None, str]:
    """Select facts only. Do not synthesize amounts or alter canonical tolerances."""
    view = dict(ev)
    senior = ev.get("senior_debt") or {}
    debt_rows = _rows(senior)
    matching = [r for r in debt_rows if _index(r) == index]
    if check_id.startswith("QM-SD-"):
        if len(matching) != 1:
            return None, "PERIOD_EVIDENCE_MISSING_OR_DUPLICATE"
        if check_id == "QM-SD-001":
            position = debt_rows.index(matching[0])
            # Original order is retained: continuity is NOT lost by filtering to one row.
            view["senior_debt"] = {**senior, "periods": debt_rows[:position + 1]}
            return view, "CUMULATIVE_THROUGH_PERIOD"
        view["senior_debt"] = {**senior, "periods": matching}
        return view, "PERIOD_AND_SOLVER_AUTHORITY" if check_id == "QM-SD-004" else "PERIOD"
    if check_id == "QM-SU-001":
        su = ev.get("sources_uses") or {}
        matching = [r for r in su.get("construction_periods", []) if _index(r) == index]
        if len(matching) != 1:
            return None, "PERIOD_EVIDENCE_MISSING_OR_DUPLICATE"
        view["sources_uses"] = {**su, "construction_periods": matching}
        return view, "PERIOD_AND_GLOBAL_SOURCES_USES"
    bs = [r for r in _rows(ev, "balance_sheet") if _index(r) == index]
    if check_id == "QM-ACC-001":
        if len(bs) != 1:
            return None, "PERIOD_EVIDENCE_MISSING_OR_DUPLICATE"
        view["balance_sheet"] = bs
        view["senior_debt"] = {**senior, "periods": matching}
        return view, "PERIOD"
    cash = [r for r in _rows(ev, "cash") if _index(r) == index]
    if len(cash) != 1:
        return None, "PERIOD_EVIDENCE_MISSING_OR_DUPLICATE"
    view.update(cash=cash, balance_sheet=bs)
    return view, "PERIOD"


def _period(check, ev: Mapping, column: dict, identity: RunIdentity, digest_ok: bool) -> PeriodEvidence:
    base = dict(check_id=check.check_id, snapshot_id=identity.snapshot_id, run_identity=identity, period_index=column["index"],
                date=column["date"], applicable=None, evidence_source=check.evidence_source)
    if check.check_id not in PERIOD_VALIDATORS:
        classification = ("UNAVAILABLE" if check.status.value == "UNAVAILABLE" else
                          "NOT_PERIODIC" if check.check_id in GLOBAL_CHECKS else "AGGREGATE_ONLY")
        return PeriodEvidence(**base, status=classification, scope=classification,
                              reason="NO_PERIOD_VALIDATOR" if classification != "UNAVAILABLE" else check.reason_code)
    if not digest_ok:
        return PeriodEvidence(**base, status="UNAVAILABLE", scope="UNAVAILABLE", reason="EVIDENCE_DIGEST_NOT_INTACT")
    if check.status.value == "NOT_APPLICABLE":
        # Whole-run inapplicability is independently established by the original
        # validator (e.g. a genuinely absent Senior facility), not by missing rows.
        return PeriodEvidence(**{**base, "applicable": False}, status="NOT_APPLICABLE",
                              scope="WHOLE_RUN_NOT_APPLICABLE", reason=check.reason_code)
    restricted, scope = _restricted(check.check_id, ev, column["index"])
    if restricted is None:
        return PeriodEvidence(**base, status="UNAVAILABLE", scope="UNAVAILABLE", reason=scope)
    try:
        if check.check_id == "QM-SD-001":
            result = integrity.check_senior_rollforward(restricted, terminal_boundary_is_present=(
                len(_rows(restricted, "senior_debt")) == len(_rows(ev, "senior_debt"))))
        else:
            result = PERIOD_VALIDATORS[check.check_id](restricted)
    except Exception:
        return PeriodEvidence(**base, status="UNAVAILABLE", scope=scope, reason="PERIOD_EVIDENCE_MALFORMED")
    status = result.status.value
    base["applicable"] = None if status == "UNAVAILABLE" else status != "NOT_APPLICABLE"
    # Raw observed/expected facts are only available for the construction equality.
    observed = expected = None
    if check.check_id == "QM-SU-001":
        row = restricted["sources_uses"]["construction_periods"][0]
        observed, expected = _num(row.get("sources")), _num(row.get("uses"))
    return PeriodEvidence(**base, status=status, scope=scope, residual=result.max_abs_deviation,
                          tolerance=result.tolerance, observed=observed, expected=expected,
                          reason=result.reason_code)


def _waterfall(ws: Any, columns: list[dict], *, integrity_evidence: Mapping, digest_ok: bool) -> list[dict]:
    statements = getattr(ws, "last_financial_statements", None) or {}
    # Copy persisted lines; no netting, aggregation, new waterfall or output calculations.
    lines = (("Revenue", "pnl", "revenues_keur"), ("OPEX", "pnl", "operating_expenses_keur"),
             ("EBITDA", "pf_cash_waterfall", "ebitda_cash_keur"),
             ("Cash taxes", "pf_cash_waterfall", "cash_tax_keur"),
             ("CFADS", "pf_cash_waterfall", "fcf_banks_keur"),
             ("Senior service", "pf_cash_waterfall", "senior_total_ds_keur"),
             ("Junior service", "pf_cash_waterfall", "junior_debt_service_keur"),
             ("DSRA funding", "pf_cash_waterfall", "dsra_funding_keur"),
             ("DSRA release", "pf_cash_waterfall", "dsra_release_keur"),
             ("SHL interest", "integrity_sponsor", "shl_cash_interest"),
             ("SHL principal", "integrity_sponsor", "shl_principal"),
             ("Equity distributions", "pf_cash_waterfall", "net_dividends_keur"),
             ("Cash balance", "balance_sheet", "cash_keur"))
    out = []
    for label, section, key in lines:
        rows = (_rows(integrity_evidence, "sponsor") if digest_ok else []) if section == "integrity_sponsor" else _rows(statements, section)
        source = (f"Last Run.integrity_evidence.sponsor.periods.{key}" if section == "integrity_sponsor" else
                  f"Last Run.financial_statements.{section}.{key}")
        values = []
        for column in columns:
            match = [r for r in rows if _index(r) == column["index"] and
                     str(r.get("date") or "") == str(column["date"] or "")]
            values.append(_num(match[0].get(key)) if len(match) == 1 else None)
        out.append({"label": label, "source": source,
                    "values": values, "unit": "kEUR"})
    return out


def build_diagnostics_summary(ws: Any, report: QualityReport, *, score: dict, scenario_name: str) -> dict:
    """Same canonical whole-Run summary, without period/DX evaluation or history reads."""
    by_id = {check.check_id: check for check in report.checks}
    return {"state": report.freshness, "available": True, "identity": report.run_identity,
            "scenario_name": scenario_name, "score": score, "blocking_count": len(report.blocking_findings),
            "integrity": integrity.run_integrity_checks(getattr(ws, "last_integrity_evidence", None) or {}).to_dict(),
            "top_issues": [by_id[cid].to_dict() for cid in report.top_issues[:5]], "summary_only": True}


@observed("diagnostics")
def build_diagnostics(ws: Any, report: QualityReport, *, score: dict, scenario_name: str, evidence: Any = None,
                      history_quality: Any = None) -> dict:
    ev = getattr(ws, "last_integrity_evidence", None) or {}
    integrity_report = integrity.run_integrity_checks(ev)
    digest_ok = any(c.check_id == "EVIDENCE_DIGEST" and c.status.value == "PASS" for c in integrity_report.checks)
    columns, total_periods = _axis(ws, ev)
    checks = []
    priority = {cid: n for n, cid in enumerate(report.top_issues)}
    identity = RunIdentity(**report.run_identity)
    ordered = sorted(report.checks, key=lambda c: (not c.blocking, c.status.value not in ("FAIL", "WARNING"),
                                                  priority.get(c.check_id, 999), c.check_id))
    for check in ordered:
        row = check.to_dict()
        row["periods"] = [asdict(_period(check, ev, column, identity, digest_ok))
                          for column in columns]
        row["period_scope"] = (row["periods"][0]["scope"] if row["periods"] else "UNAVAILABLE")
        row["global_component"] = None
        if check.check_id == "QM-SU-001" and digest_ok:
            global_ev = {**ev, "sources_uses": {**ev.get("sources_uses", {}), "construction_periods": []}}
            row["global_component"] = integrity.check_sources_equal_uses(global_ev).to_dict()
        elif check.check_id == "QM-SD-004":
            row["global_component"] = dict(ev.get("senior_debt", {}).get("diagnostics") or {})
        elif check.check_id == "QM-SD-001":
            row["global_component"] = {"scope": "Initial commitment, adjacent-period continuity and final maturity; cells validate cumulative prefixes."}
        if check.check_id in PERIOD_VALIDATORS and check.status.value == "FAIL" and not any(
                p["status"] == "FAIL" for p in row["periods"]):
            # Missing/unrendered periods or an uncovered global boundary must never
            # leave an aggregate FAIL next to an unexplained all-green matrix.
            row["global_component"] = {"status": "FAIL", "scope": "AGGREGATE_OR_UNRENDERED_BOUNDARY",
                "reason": check.reason_code, "residual": check.measured_value,
                "tolerance": check.threshold_value, "detail": check.detail}
        checks.append(row)
    groups = []
    for check in checks:
        group = next((g for g in groups if g["category"] == check["category"]), None)
        if group is None:
            group = {"category": check["category"], "checks": []}
            groups.append(group)
        group["checks"].append(check)
    result = {"state": report.freshness, "available": True, "identity": report.run_identity,
              "scenario_name": scenario_name, "score": score, "blocking_count": len(report.blocking_findings),
              "integrity": integrity_report.to_dict(), "checks": checks, "groups": groups, "columns": columns,
              "total_periods": total_periods, "truncated": total_periods > len(columns),
              "top_issues": [next(r for r in checks if r["check_id"] == cid) for cid in report.top_issues[:5]],
              "waterfall": _waterfall(ws, columns, integrity_evidence=ev, digest_ok=digest_ok)}
    if evidence is not None:
        # V2 is additive: a malformed V2 evidence set must never hide the V1 verdicts.
        try:
            from app.v2.diagnostics_v2_projection import build_diagnostics_v2
            result["v2"] = build_diagnostics_v2(ws, result, evidence=evidence, report=report, history_quality=history_quality)
        except Exception:  # noqa: BLE001 - fail closed to an explicit UNAVAILABLE block
            result["v2"] = {"state": "UNAVAILABLE", "available": False}
    return result
