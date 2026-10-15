"""WF-A credit validation cases: real committed Runs under bounded, reproducible, synthetic stresses.

Every stress goes through an existing released input route (see ``wfa_support``).  Each case is committed by the
product, bundled read-only, and validated by the independent credit identities.  No production code changes.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Callable

from tests import wfa_support as S

SIZING = {"combined": "COMBINED_MINIMUM", "dscr": "FLAT_DSCR_SCULPTED", "fixed": "GEARING_CAP"}


@dataclass
class Case:
    label: str
    kind: str
    sizing: str                       # key of SIZING
    delta: str                        # human-readable assumption delta against the sizing-mode baseline
    configuration: dict[str, Any]
    entry: Any = None
    bundle: dict | None = None
    credit: dict | None = None
    result: dict | None = None
    committed: bool = False
    reason: str = ""
    metrics: dict[str, Decimal | None] = field(default_factory=dict)


def _d(value: Any) -> Decimal | None:
    return None if value is None else Decimal(str(value))


def rates_vector(record, pct: float) -> list[float]:
    from app.persistence.workspace_repository import get_workspace_state
    from app.workbook.bankability_config import operating_axis
    from app.workbook.service import WorkbookService
    ws = get_workspace_state(S.USER, record.project_id)
    pi = WorkbookService.build_draft_input_set_from_workspace(ws).to_projectinputs()
    return [pct] * len(operating_axis(pi))


def declared_lockup(record) -> float:
    from app.persistence.workspace_repository import get_workspace_state
    from app.workbook.service import WorkbookService
    ws = get_workspace_state(S.USER, record.project_id)
    return float(WorkbookService.build_draft_input_set_from_workspace(ws).to_projectinputs().financing.lockup_dscr)


def metrics_of(entry: Any, bundle: dict) -> dict[str, Decimal | None]:
    sc = lambda k: _d(bundle["scalars"].get(k, {}).get("value"))  # noqa: E731
    series = lambda k: {d: _d(x) for d, x in (bundle["series"].get(k, {}).get("values") or {}).items()}  # noqa: E731
    debt, uses = sc("su.senior_debt_keur"), sc("su.total_uses_keur")
    service, bank = series("ev.senior.debt_service"), series("ev.senior.bank_cfads")
    sizing = [bank[k] / service[k] for k in service if service[k] is not None and service[k] > Decimal("1e-6")
              and bank.get(k) is not None]
    interest = [x for x in series("ev.senior.interest").values() if x is not None]
    return {
        "senior_debt": debt, "total_uses": uses, "equity_funding": None if None in (debt, uses) else uses - debt,
        "gearing": (debt / uses) if (debt is not None and uses) else None,
        "min_dscr": sc("summary.min_dscr"), "avg_dscr": sc("summary.avg_dscr"),
        "min_sizing_dscr": min(sizing) if sizing else None,
        "total_service": sc("summary.total_senior_ds_keur"), "total_interest": sum(interest) if interest else None,
        "total_ebitda": sc("summary.total_ebitda_keur"), "project_irr": sc("summary.project_irr"),
        "equity_irr": sc("summary.equity_irr"),
        "lockup_periods": _d(getattr(entry, "runtime_summary", {}).get("periods_in_lockup")),
        "base_capex": sc("su.base_project_capex_keur"), "idc": sc("su.capitalized_idc_keur"),
        "financing_fees": None if None in (sc("su.commitment_fee_keur"), sc("su.structuring_fee_keur"), sc("su.other_financing_costs_keur"))
        else sc("su.commitment_fee_keur") + sc("su.structuring_fee_keur") + sc("su.other_financing_costs_keur"),
        "initial_dsra": sc("su.initial_dsra_funding_keur"),
        "total_cfads": sum(x for x in series("stmt.pf.fcf_banks").values() if x is not None) if series("stmt.pf.fcf_banks") else None,
    }


def build_case(lab, kind: str, label: str, sizing: str, delta: str, setup: Callable[[Any], dict] | None = None,
               capacity_mw: float = 16) -> Case:
    """Create a project, apply ``setup`` (returns the configuration actually applied), commit a Run, validate it."""
    from app.persistence.run_history_repository import get_latest_history_entry
    from app.persistence.workspace_repository import get_workspace_state
    from tools.numerical_validation import credit
    from tools.numerical_validation.source import bundle_from_history_entry
    record = S.project(kind, label, capacity_mw)
    bank: dict[str, Any] = {}
    if sizing == "fixed":
        bank["sizing_mode"] = "gearing_cap"
    elif sizing == "dscr":
        bank["sizing_mode"] = "flat_dscr_sculpted"
    applied = {"sizing_mode": SIZING[sizing]}
    if setup is not None:
        extra = setup(record, bank) or {}
        applied.update(extra)
    if bank:
        S.set_bankability(lab, record, bank)
        applied["bankability"] = bank
    case = Case(label, kind, sizing, delta, applied)
    response = lab.client.post("/v2/workbook/run", headers={"HX-Request": "true"},
                               data={"project": record.project_code, **S.tokens(record)})
    ws = get_workspace_state(S.USER, record.project_id)
    if response.status_code != 200 or not ws.last_runtime_summary or ws.dirty:
        case.reason = _failure_reason(response.text)
        return case
    case.entry = get_latest_history_entry(S.USER, record.project_id)
    case.bundle = bundle_from_history_entry(case.entry)
    case.credit = credit.credit_evidence_from_entry(
        case.entry, case.bundle, declared={"lockup_dscr": declared_lockup(record), "sizing_mode": SIZING[sizing]})
    case.result = credit.reconcile_credit(case.bundle, case.credit)
    case.metrics = metrics_of(case.entry, case.bundle)
    case.committed = True
    return case


def _failure_reason(text: str) -> str:
    import re
    plain = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", text)).strip()
    for marker in ("integrity checks stopped this run", "could not", "not ready", "failed", "Cannot", "cannot"):
        i = plain.find(marker)
        if i >= 0:
            return plain[max(0, i - 80): i + 220]
    return plain[:300] or "RUN_NOT_COMMITTED_NO_DETAIL"


# ───────────────────────────── stress definitions (applied through released routes only) ─────────────────────────────
def hours(factor: float):
    def setup(record, bank):
        from app.persistence.workspace_repository import get_workspace_state
        base = float(get_workspace_state(S.USER, record.project_id).draft_snapshot["p50_hours"])
        S.update_field(S.LAB, record, "project_setup.technical.p50_hours", base * factor, "project_setup")
        return {"p50_hours": base * factor}
    return setup


def tariff(factor: float):
    def setup(record, bank):
        from app.persistence.workspace_repository import get_workspace_state
        snap = get_workspace_state(S.USER, record.project_id).draft_snapshot
        base = float(snap.get("rev_ppa_base_tariff") or snap["tariff_eur_mwh"])
        S.update_field(S.LAB, record, "revenue.ppa.base_tariff", base * factor, "revenue")
        return {"ppa_tariff": base * factor}
    return setup


def capex(pct: float):
    def setup(record, bank):
        S.set_contingency(S.LAB, record, "capex", pct)
        return {"capex_contingency_pct": pct}
    return setup


def opex(pct: float):
    def setup(record, bank):
        S.set_contingency(S.LAB, record, "opex", pct)
        return {"opex_contingency_pct": pct}
    return setup


def rate(pct: float):
    def setup(record, bank):
        bank["rates_pct"] = rates_vector(record, pct)
        bank["day_count"] = "act_360"
        return {"all_in_rate_pct": pct}
    return setup


def lender(case_name: str):
    def setup(record, bank):
        bank["lender_case"] = case_name
        return {"lender_case": case_name}
    return setup


def tenor(years: int):
    def setup(record, bank):
        S.update_field(S.LAB, record, "debt.senior.tenor_years", years)
        return {"tenor_years": years}
    return setup


def gearing(pct: float):
    def setup(record, bank):
        S.update_field(S.LAB, record, "debt.senior.gearing_pct", pct)
        return {"gearing_pct": pct}
    return setup


def combine(*setups):
    def setup(record, bank):
        applied: dict[str, Any] = {}
        for fn in setups:
            applied.update(fn(record, bank) or {})
        return applied
    return setup


def sizing_target(case: Case) -> Decimal | None:
    ev = case.bundle["series"].get("ev.senior.target_dscr", {}).get("values", {}) if case.bundle else {}
    values = [Decimal(v) for v in ev.values() if v is not None]
    return min(values) if values else None
