"""RC-7C: numerical reconciliation of the released 6/6 project with the matched 3/3 candidate (v1 and v2) through the canonical engine path.

TEST-ONLY. Not a production engine. Every expected value is derived from dates with ``tests/rc7b_quarterly_oracle.py`` (Decimal) or from
the structural identities proven in ``tests/test_rc7c_quarterly_date_authority.py``; nothing is forced to agree and no golden is edited.

What may legitimately differ when only the operating/debt frequency changes, and why:

* Senior interest, principal, sizing and the DSCR series: actual accrual and service dates are quarterly instead of six-monthly.
* Project / Sponsor IRR: the same economics with earlier cash flows.
* Tax payments: one calendar-year ledger paid in the last row of the year (31 Dec) under both; amounts follow the interest and revenue above.
* D-02: the released six-month axis counts the COD day when COD is the first of a month; the 3/3 half-open rule does not (one day of the first row).
* D-05: the released six-month axis keeps a whole six-month row at the PPA tariff when the PPA expires inside it; the 3/3 axis switches to the
  merchant price at the quarter boundary on which the PPA actually expires (no intra-quarter split is invented).

Everything else (construction, CAPEX/IDC, the operating start and end dates, operating days, model years, production, OPEX, depreciation, the
Senior maturity date) must be identical. v1 does not satisfy that when COD is in the second quarter of a half-year (it adds a quarter).
"""
from __future__ import annotations

import dataclasses
import sys
from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from dateutil.relativedelta import relativedelta

import rc7b_quarterly_oracle as oracle
from finco_core.engine.calendar_policy import quarterly_candidate_policy_v1, quarterly_candidate_policy_v2
from finco_core.inputs.senior_rate_schedule import SeniorDayCountConvention as DayCount
from test_rc7b_quarterly_funding_statements import build as _base_build, canonical_run

D = Decimal


@dataclass(frozen=True)
class Case:
    kind: str                     # "solar" | "wind"
    cod: date
    months: int = 12              # construction months
    horizon: int | None = None    # operating horizon years (None: reference project default)
    tenor: int | None = None      # Senior tenor years
    day_count: str | None = None  # "ACT_360" | "ACT_365"
    ppa: float | None = None      # PPA term years (0.0 = merchant only)

    @property
    def label(self) -> str:
        parts = [self.kind, self.cod.isoformat(), f"cm{self.months}"]
        for name in ("horizon", "tenor", "day_count", "ppa"):
            if getattr(self, name) is not None:
                parts.append(f"{name}={getattr(self, name)}")
        return "/".join(parts)


def financial_close_for(cod: date, months: int) -> date:
    """A financial close whose COD (close + months, month-end clamped) is exactly ``cod``."""
    base = cod - relativedelta(months=months)
    for delta in range(0, 4):
        fc = base + relativedelta(days=delta)
        if fc + relativedelta(months=months) == cod:
            return fc
    raise ValueError(f"no financial close gives COD {cod} after {months} months")


def project(case: Case, frequency: str, policy=None):
    """The reference project of ``case.kind``; only the calendar frequency (and optional policy) differs between S and Q."""
    pi = _base_build(case.kind, frequency, fc=financial_close_for(case.cod, case.months), months=case.months)
    assert pi.info.cod_date == case.cod, (pi.info.cod_date, case.cod)
    if frequency == "Q" and policy is not None:
        pi = dataclasses.replace(pi, info=dataclasses.replace(pi.info, operating_calendar_policy=policy))
    if case.horizon:
        pi = dataclasses.replace(pi, info=dataclasses.replace(pi.info, horizon_years=case.horizon))
    if case.tenor:
        pi = dataclasses.replace(pi, financing=dataclasses.replace(pi.financing, senior_tenor_years=case.tenor))
    if case.day_count:
        cfg = pi.financing.senior_debt_interest_config
        pi = dataclasses.replace(pi, financing=dataclasses.replace(
            pi.financing, senior_debt_interest_config=dataclasses.replace(cfg, day_count=DayCount[case.day_count])))
    if case.ppa is not None:
        pi = dataclasses.replace(pi, revenue=dataclasses.replace(pi.revenue, ppa_term_years=case.ppa))
    return pi


_CACHE: dict = {}


def run(case: Case, frequency: str, policy=None):
    key = (case, frequency, getattr(policy, "version", None))
    if key not in _CACHE:
        pi = project(case, frequency, policy)
        _CACHE[key] = (pi, canonical_run(pi))
    return _CACHE[key]


def six_month_rows(info, ppa_years: float):
    """Independent rows of the RELEASED six-month axis: stub to the next Jun 30 / Dec 31, +1 day on a first-of-month COD (D-02)."""
    cod = info.financial_close + relativedelta(months=info.construction_months)
    ppa_end = cod + relativedelta(years=int(ppa_years))
    rows, start = [], cod
    for k, end in enumerate(oracle.six_month_ends(cod, 2 * info.horizon_years)):
        days = (end - start).days + (1 if k == 0 and cod.day == 1 else 0)
        denom = 366 if oracle.pycal.isleap(end.year) else 365
        rows.append(oracle.Row(start, end, days, D(days) / D(denom), k // 2 + 1, start < ppa_end))
        start = end
    return tuple(rows)


def per_year(values, rows):
    out: dict = defaultdict(lambda: D(0))
    for value, row in zip(values, rows):
        out[row.year] += D(repr(float(value))) if not isinstance(value, Decimal) else value
    return dict(out)


def engine_year_totals(result, attribute: str):
    model = result.g2c_result.financing_result.project_model_result
    out: dict = defaultdict(lambda: D(0))
    for p in model.periods:
        if p.is_operation:
            out[p.year_index] += D(repr(float(getattr(p, attribute))))
    return dict(out)


def summary(case: Case, frequency: str, policy=None) -> dict:
    pi, result = run(case, frequency, policy)
    g = result.g2c_result
    fr = g.financing_result
    model = fr.project_model_result
    ops = [p for p in model.periods if p.is_operation]
    debt = model.senior_debt
    dscr = [x for x in debt.base_dscr if x is not None]
    return {
        "operating_rows": len(ops), "operating_start": ops[0].period_start, "operating_end": ops[-1].period_end,
        "operating_days": sum((p.period_end - p.period_start).days for p in ops),
        "model_years": len({p.year_index for p in ops}),
        "production_mwh": sum(p.production_mwh for p in ops), "revenue_keur": sum(p.revenue_keur for p in ops),
        "opex_keur": sum(p.opex_keur for p in ops), "book_depreciation_keur": sum(p.book_depreciation_keur for p in ops),
        "total_project_uses_keur": fr.project_uses.total_project_uses_keur,
        "senior_commitment_keur": fr.final_senior_commitment_keur,
        "senior_interest_keur": sum(debt.senior_interest_keur), "senior_principal_keur": sum(debt.senior_principal_keur),
        "senior_final_service_date": model.periods[debt.period_indices[-1]].period_end,
        "senior_service_rows": len(debt.period_indices),
        "min_dscr": min(dscr) if dscr else None, "avg_dscr": (sum(dscr) / len(dscr)) if dscr else None,
        "cash_tax_keur": sum(model.tax_and_cfads.corporate_tax_cash_keur),
        "sponsor_xirr": g.total_sponsor_xirr,
    }


def explained_totals(case: Case) -> dict:
    """Date-derived expectations for both frequencies, per model year: (production, revenue, opex) of the six-month and the 3/3 axis."""
    pi_s, _ = run(case, "S")
    pi_q, _ = run(case, "Q", quarterly_candidate_policy_v2())
    ppa = int(pi_s.revenue.ppa_term_years)
    rows_s = six_month_rows(pi_s.info, ppa)
    rows_q = oracle.operating_rows(pi_q.info, ppa)
    return {"S": (rows_s, oracle.operating(pi_s, rows_s, "P50")), "Q": (rows_q, oracle.operating(pi_q, rows_q, "P50"))}


V1, V2 = quarterly_candidate_policy_v1(), quarterly_candidate_policy_v2()


def _fmt(value) -> str:
    if isinstance(value, float):
        return f"{value:,.4f}"
    return str(value)


def report(cases: list[Case]) -> str:
    """Markdown reconciliation table: relative differences of 3/3 (v2, and the historical v1) against the released 6/6 project."""
    lines = ["| Case | Rows 6/6 | Rows v1 | Rows v2 | End 6/6 | End v1 | End v2 | Revenue v1 % | Revenue v2 % | Prod/OPEX/Dep v2 % | Senior size v2 % | Sponsor XIRR 6/6 | Sponsor XIRR v2 |",
             "|---|---:|---:|---:|---|---|---|---:|---:|---:|---:|---:|---:|"]
    for case in cases:
        s, a, b = summary(case, "S"), summary(case, "Q", V1), summary(case, "Q", V2)

        def pct(x, y):
            return 0.0 if x == 0 else (y - x) / x * 100.0
        flat = max(abs(pct(s[k], b[k])) for k in ("production_mwh", "opex_keur", "book_depreciation_keur"))
        lines.append(f"| {case.label} | {s['operating_rows']} | {a['operating_rows']} | {b['operating_rows']} | {s['operating_end']} | {a['operating_end']} | "
                     f"{b['operating_end']} | {pct(s['revenue_keur'], a['revenue_keur']):+.3f} | {pct(s['revenue_keur'], b['revenue_keur']):+.4f} | "
                     f"{flat:.6f} | {pct(s['senior_commitment_keur'], b['senior_commitment_keur']):+.3f} | {s['sponsor_xirr']:.4f} | {b['sponsor_xirr']:.4f} |")
    return "\n".join(lines)


if __name__ == "__main__":                                   # python tests/rc7c_frequency_reconciliation.py > table.md
    from test_rc7c_frequency_reconciliation import CASES
    sys.stdout.write(report(list(CASES)) + "\n")
