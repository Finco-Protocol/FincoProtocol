"""Quarterly (3/3) institutional acceptance: scenario matrix, a calendar oracle that uses dates only, and run helpers.

TEST-ONLY. Nothing here is a production engine, enables the candidate, or edits a pin, golden or tolerance.

Oracle layering (every expected value comes from one of these, never from the engine under test):

* ``calendar_oracle`` below: pure ``datetime.date`` arithmetic (quarter-end search, half-year boundary index, half-open day counts). It does not
  import the engine, ``finco_core`` or ``tests/rc7b_quarterly_oracle.py``; a test cross-checks the two oracles against each other.
* ``tests/rc7b_quarterly_oracle.py`` (Decimal, 60 digits): revenue / OPEX / depreciation / calendar-year tax / Senior sizing from the inputs.
* identities derived from the engine's own outputs only where the identity is an arithmetic definition (interest = opening * rate * actual days / basis,
  closing = opening - principal, service = interest + principal, CFADS / target >= service), so a defect cannot hide by being self-consistent.

This is synthetic institutional acceptance. It is not Excel parity and does not claim to be.
"""
from __future__ import annotations

import calendar as pycal
import dataclasses
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Callable, Optional

import rc7b_quarterly_oracle as oracle
import rc7c_frequency_reconciliation as recon
from finco_core.engine.calendar_policy import quarterly_candidate_policy_v2
from test_rc7b_quarterly_funding_statements import canonical_run

D = Decimal
V2 = quarterly_candidate_policy_v2()

# Tolerances are the existing approved constants (see RC-7B funding/statements module); none is widened here.
OPERATING_TOL = Decimal("1e-9")   # non-iterated float arithmetic vs 60-digit Decimal
SOLVER_TOL = Decimal("1e-4")      # clean Senior policy convergence_tolerance_keur (tax-interest fixed point)
IDENTITY_TOL = Decimal("1e-6")    # funding / statements identities (G2A_SERVICE_BUDGET_ACCEPTANCE_TOLERANCE_KEUR, statements _TOLERANCE_KEUR)


# ── calendar oracle (dates only) ──────────────────────────────────────────────

@dataclass(frozen=True)
class Quarter:
    start: date
    end: date
    days: int
    year_basis: int          # 365 / 366, the length of the calendar year in which the row ends
    model_year: int
    period_in_year: int

    @property
    def fraction(self) -> Decimal:
        return D(self.days) / D(self.year_basis)


def _last_day(year: int, month: int) -> date:
    return date(year, month, pycal.monthrange(year, month)[1])


def next_quarter_end(d: date) -> date:
    """First 31 Mar / 30 Jun / 30 Sep / 31 Dec strictly after ``d`` (half-open rows: a COD on a quarter end starts the NEXT quarter)."""
    year = d.year
    while True:
        for month in (3, 6, 9, 12):
            end = _last_day(year, month)
            if end > d:
                return end
        year += 1


def half_year_boundaries(cod: date, count: int) -> list[date]:
    """End dates of the first ``count`` six-month rows of the matched six-month project (stub to the next 30 Jun / 31 Dec)."""
    first = _last_day(cod.year, 6)
    if cod >= first:
        first = _last_day(cod.year, 12)
    if cod >= first:
        first = _last_day(cod.year + 1, 6)
    out, year, june = [], first.year, first.month == 6
    for _ in range(count):
        out.append(_last_day(year, 6 if june else 12))
        if not june:
            year += 1
        june = not june
    return out


def calendar_oracle(cod: date, horizon_years: int) -> tuple[Quarter, ...]:
    """The date-authoritative operating axis: same economic end date and model years as the equivalent six-month project, rows on quarter ends."""
    halves = half_year_boundaries(cod, 2 * horizon_years)
    rows, start = [], cod
    while start < halves[-1]:
        end = next_quarter_end(start)
        parent = next(k for k, boundary in enumerate(halves) if end <= boundary)
        year = parent // 2 + 1
        position = sum(1 for r in rows if r.model_year == year) + 1
        rows.append(Quarter(start, end, (end - start).days, 366 if pycal.isleap(end.year) else 365, year, position))
        start = end
    return tuple(rows)


def senior_maturity_oracle(cod: date, tenor_years: int) -> date:
    return half_year_boundaries(cod, 2 * tenor_years)[-1]


# ── scenarios ─────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Scenario:
    """A reproducible acceptance fixture. ``mutate`` is applied to the project of BOTH frequencies so the only difference is the frequency."""
    id: str
    case: recon.Case
    group: str
    why: str
    mutate: Optional[Callable] = field(default=None, compare=False)


def _opex_stepped(pi):
    first, *rest = pi.opex
    stepped = dataclasses.replace(first, step_changes=((6, first.y1_amount_keur * 1.5), (11, first.y1_amount_keur * 2.0)))
    return dataclasses.replace(pi, opex=(stepped, *rest))


def _opex_percentage(pi):
    pct = dataclasses.replace(pi.opex[0], name="Asset-management fee (pct of base OPEX)", y1_amount_keur=0.0, annual_inflation=0.0, percentage_of_opex=0.05)
    return dataclasses.replace(pi, opex=(*pi.opex, pct))


def _ppa_half_share(pi):
    return dataclasses.replace(pi, revenue=dataclasses.replace(pi.revenue, ppa_production_share=0.6, ppa_index=0.03))


def _rates_36(pi):
    """The six-month schedule needs two entries per tenor year; give both frequencies the same flat 5.5% with enough entries."""
    cfg = pi.financing.senior_debt_interest_config
    schedule = dataclasses.replace(cfg.rate_schedule, explicit_all_in_rates=(0.055,) * 48)
    return dataclasses.replace(pi, financing=dataclasses.replace(pi.financing, senior_debt_interest_config=dataclasses.replace(cfg, rate_schedule=schedule)))


def _target(value):
    def apply(pi):
        return dataclasses.replace(pi, financing=dataclasses.replace(pi.financing, target_dscr=value))
    return apply


S = Scenario
SCENARIOS: tuple[Scenario, ...] = (
    # quarter-end / half-year-end CODs: contractual PPA supported
    S("solar-q1end", recon.Case("solar", date(2031, 3, 31)), "quarter-boundary", "COD on 31 Mar: first row is a full quarter (Mar31-Jun30)"),
    S("solar-q3end", recon.Case("solar", date(2031, 9, 30)), "quarter-boundary", "COD on 30 Sep (second quarter of a half-year: the v1 defect shape)"),
    S("solar-h1end", recon.Case("solar", date(2031, 6, 30)), "quarter-boundary", "COD on 30 Jun: stub is exactly one quarter, half-year aligned"),
    S("solar-yearend", recon.Case("solar", date(2031, 12, 31)), "year-crossing", "COD on 31 Dec: first row crosses into a new year, PPA expiry on a boundary"),
    S("wind-q1end", recon.Case("wind", date(2031, 3, 31)), "quarter-boundary", "Wind, 12-year PPA expiring on a quarter boundary"),
    S("wind-q3end", recon.Case("wind", date(2031, 9, 30)), "quarter-boundary", "Wind, COD in the second quarter of a half-year"),
    S("wind-yearend", recon.Case("wind", date(2031, 12, 31)), "year-crossing", "Wind, COD on 31 Dec"),
    # mid-period CODs: merchant-only (a PPA expiring inside a quarter is refused, see negative controls)
    S("solar-mid-q2", recon.Case("solar", date(2031, 4, 17), ppa=0.0), "mid-period-cod", "COD 17 Apr: 74-day stub row, three rows in model year 1"),
    S("solar-firstday", recon.Case("solar", date(2031, 7, 1), ppa=0.0), "mid-period-cod", "COD 1 Jul: first row has 91 days, first-of-month COD (D-02 shape)"),
    S("solar-jan1", recon.Case("solar", date(2032, 1, 1), ppa=0.0), "year-crossing", "COD 1 Jan of a leap year"),
    S("solar-aug", recon.Case("solar", date(2031, 8, 15), ppa=0.0), "mid-period-cod", "COD 15 Aug: 46-day stub inside a half-year"),
    S("solar-nov-leap", recon.Case("solar", date(2027, 11, 10), ppa=0.0), "leap-year", "COD Nov 2027: horizon contains 2028, 2032, 2036, 2040, 2044, 2048, 2052"),
    S("wind-mid-q2", recon.Case("wind", date(2031, 4, 1), ppa=0.0), "mid-period-cod", "Wind, COD 1 Apr"),
    S("wind-nov-leap", recon.Case("wind", date(2027, 11, 10), ppa=0.0), "leap-year", "Wind, COD Nov 2027"),
    # leap-day COD needs 13 construction months to be reachable from a financial close
    S("solar-feb29", recon.Case("solar", date(2032, 2, 29), months=13, ppa=0.0), "leap-year", "COD 29 Feb 2032 after 13 construction months"),
    # construction length / tenor / horizon / day count
    S("solar-cm18", recon.Case("solar", date(2031, 9, 30), months=18), "construction", "18-month construction, COD on a quarter end"),
    S("solar-cm24", recon.Case("solar", date(2032, 3, 31), months=24), "construction", "24-month construction, COD on a quarter end"),
    S("solar-tenor10", recon.Case("solar", date(2031, 12, 31), tenor=10), "financing", "10-year Senior tenor"),
    S("solar-tenor18-h30", recon.Case("solar", date(2031, 6, 30), tenor=18, horizon=30), "financing", "18-year tenor on a 30-year horizon", mutate=_rates_36),
    S("solar-act365", recon.Case("solar", date(2031, 12, 31), day_count="ACT_365"), "financing", "Interest accrued ACT/365 instead of ACT/360"),
    S("solar-h20", recon.Case("solar", date(2031, 12, 31), horizon=20, tenor=12), "financing", "20-year horizon, 12-year tenor"),
    # DSCR-capacity-bound sculpting (the default fixtures are gearing-bound, which leaves the sculpting capacity non-binding)
    S("solar-dscr-bound", recon.Case("solar", date(2031, 12, 31), tenor=10), "sculpting", "Target DSCR 1.5, 10-year tenor: capacity binds, debt is sized by the sculpting",
      mutate=_target(1.5)),
    S("solar-dscr-mid", recon.Case("solar", date(2031, 8, 15), tenor=15, ppa=0.0), "sculpting", "Target DSCR 2.0, 15-year tenor, 46-day stub, merchant only", mutate=_target(2.0)),
    S("wind-dscr-bound", recon.Case("wind", date(2031, 9, 30), tenor=10), "sculpting", "Wind, target DSCR 1.5, 10-year tenor, COD in the second quarter of a half-year",
      mutate=_target(1.5)),
    S("solar-dscr-act365", recon.Case("solar", date(2031, 6, 30), tenor=10, day_count="ACT_365"), "sculpting", "Target DSCR 1.5, 10-year tenor, ACT/365 interest", mutate=_target(1.5)),
    S("solar-dscr-high", recon.Case("solar", date(2031, 3, 31), tenor=15), "sculpting", "Target DSCR 2.5, 15-year tenor (small, strongly sculpted debt)", mutate=_target(2.5)),
    # revenue and OPEX shapes
    S("solar-opex-step", recon.Case("solar", date(2031, 9, 30), ppa=0.0), "operating", "Stepped OPEX (steps in model years 6 and 11) with a stub first row",
      mutate=_opex_stepped),
    S("solar-opex-pct", recon.Case("solar", date(2031, 6, 30)), "operating", "OPEX item expressed as a percentage of base OPEX", mutate=_opex_percentage),
    S("wind-ppa-share", recon.Case("wind", date(2031, 12, 31)), "operating", "PPA covers 60% of production with 3% indexation; remainder merchant", mutate=_ppa_half_share),
)

BY_ID = {s.id: s for s in SCENARIOS}
IDS = [s.id for s in SCENARIOS]
# Scenarios whose Senior is sized by the DSCR sculpting capacity (the others are bound by the gearing ratio); every test asserts the declaration is true.
DSCR_BOUND_IDS = [s.id for s in SCENARIOS if s.group == "sculpting" or s.id == "solar-tenor10"]
GEARING_BOUND_IDS = [i for i in IDS if i not in DSCR_BOUND_IDS]


def scenario(scenario_id: str) -> Scenario:
    return BY_ID[scenario_id]


def project(scn: Scenario, frequency: str):
    pi = recon.project(scn.case, frequency, V2 if frequency == "Q" else None)
    return scn.mutate(pi) if scn.mutate else pi


_RUNS: dict = {}


def run(scn: Scenario, frequency: str):
    """(project inputs, canonical run) for ``scn`` under 'S' (released six-month) or 'Q' (matched 3/3 candidate, rc7c-v2)."""
    key = (scn.id, frequency)
    if key not in _RUNS:
        pi = project(scn, frequency)
        _RUNS[key] = (pi, canonical_run(pi, source_id="quarterly_institutional_acceptance"))
    return _RUNS[key]


# ── result accessors ──────────────────────────────────────────────────────────

def model_of(result):
    return result.g2c_result.financing_result.project_model_result


def operating_periods(result):
    return [p for p in model_of(result).periods if p.is_operation]


def construction_periods(result):
    return [p for p in model_of(result).periods if p.is_construction]


def d(x) -> Decimal:
    return oracle.dec(x)


def per_year(values, years) -> dict:
    out: dict = {}
    for value, year in zip(values, years):
        out[int(year)] = out.get(int(year), D(0)) + d(value)
    return out


def senior_rows(result):
    """Senior service rows aligned to the model axis: (period, opening, interest, principal, service, closing, dscr)."""
    model = model_of(result)
    debt = model.senior_debt
    rows = []
    for k, index in enumerate(debt.period_indices):
        rows.append(dict(period=model.periods[index], opening=d(debt.senior_debt_opening_keur[k]), interest=d(debt.senior_interest_keur[k]),
                         principal=d(debt.senior_principal_keur[k]), service=d(debt.senior_debt_service_keur[k]),
                         closing=d(debt.senior_debt_closing_keur[k]), dscr=debt.base_dscr[k]))
    return rows


def senior_rate(pi) -> Decimal:
    return d(pi.financing.senior_debt_interest_config.rate_schedule.explicit_all_in_rates[0])


def day_count_basis(pi) -> int:
    return 360 if pi.financing.senior_debt_interest_config.day_count.name == "ACT_360" else 365
