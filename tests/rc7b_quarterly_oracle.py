"""RC-7B independent high-precision reference for the matched 3/3 Solar/Wind candidate.

TEST-ONLY numerical validation reference. It is NOT a production engine, has no
runtime consumer and must never be imported by application or engine code.

Independence contract
---------------------
* Expected quarterly values are computed here from typed project INPUTS with
  ``decimal.Decimal`` arithmetic (60 significant digits) and calendar code.
* Nothing is read from the quarterly candidate's outputs.
* Construction/Uses quantities (hard-CAPEX timing, Total Project Uses) are taken
  from the RELEASED six-month run of the same project. The tests separately prove
  those construction results are identical under both frequencies, so they are
  frequency-independent authority, not candidate output.
* Formulas reproduce the released economic definitions (generation, legacy PPA
  tariff, merchant curve, balancing, flat OPEX, straight-line model-year
  depreciation, calendar-year tax with [start, end) fragments and FIFO losses,
  CFADS = EBITDA - cash tax, ACT/360 or ACT/365 Senior interest, DSCR-sculpted
  forward roll and backward capacity) as written in their reviewed docstrings.
"""
from __future__ import annotations

import calendar as pycal
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal, getcontext, localcontext

from dateutil.relativedelta import relativedelta

getcontext().prec = 60
D = Decimal
ZERO = D(0)
ONE = D(1)


def dec(x) -> Decimal:
    return D(repr(float(x))) if not isinstance(x, Decimal) else x


# ── calendar ─────────────────────────────────────────────────────────────────

def quarter_end_after(d: date) -> date:
    candidates = [date(d.year, m, pycal.monthrange(d.year, m)[1]) for m in (3, 6, 9, 12)]
    candidates.append(date(d.year + 1, 3, 31))
    return min(c for c in candidates if c > d)


@dataclass(frozen=True)
class Row:
    start: date
    end: date
    days: int
    fraction: Decimal
    year: int
    ppa_active: bool


def operating_rows(info, ppa_years: int) -> tuple[Row, ...]:
    cod = info.financial_close + relativedelta(months=info.construction_months)
    assert cod == info.cod_date
    ppa_end = cod + relativedelta(years=ppa_years)
    rows, start = [], cod
    for k in range(4 * info.horizon_years):
        end = quarter_end_after(start)
        days = (end - start).days
        denom = 366 if pycal.isleap(end.year) else 365
        rows.append(Row(start, end, days, D(days) / D(denom), k // 4 + 1, start < ppa_end))
        start = end
    return tuple(rows)


# ── operating economics (released definitions) ───────────────────────────────

def _hours(tech, yield_case: str) -> Decimal:
    return dec(tech.operating_hours_p90_10y if yield_case == "P90" else tech.operating_hours_p50)


def operating(pi, rows, yield_case: str = "P50"):
    tech, rev = pi.technical, pi.revenue
    hours = _hours(tech, yield_case)
    availability = dec(tech.plant_availability) * dec(tech.grid_availability)
    out = []
    for r in rows:
        degradation = (ONE - dec(tech.pv_degradation)) ** (r.year - 1)
        mwh = dec(tech.capacity_mw) * hours * r.fraction * availability * degradation
        tariff = dec(rev.ppa_base_tariff) * (ONE + dec(rev.ppa_index)) ** (r.year - 1)
        curve = rev.market_prices_curve
        if r.year - 1 < len(curve):
            market = dec(curve[r.year - 1])
        else:
            market = dec(curve[-1]) * (ONE + dec(rev.market_inflation)) ** (r.year - len(curve))
        share = min(max(dec(rev.ppa_production_share), ZERO), ONE)
        ppa_mwh = mwh * share if r.ppa_active else ZERO
        merchant_mwh = mwh - ppa_mwh
        ppa_rev = ppa_mwh * tariff / 1000
        merchant_rev = merchant_mwh * market / 1000
        bal_rate = dec(rev.balancing_cost_eur_per_mwh) if rev.balancing_cost_eur_per_mwh else dec(rev.balancing_cost_wind_eur_mwh)
        balancing = merchant_rev * dec(rev.balancing_cost_pv) + mwh * bal_rate / 1000
        if rev.co2_enabled:
            co2_price = dec(rev.co2_certificate_price_eur_per_mwh) if rev.co2_certificate_price_eur_per_mwh else dec(rev.co2_price_eur)
        else:
            co2_price = ZERO
        revenue = ppa_rev + merchant_rev - balancing + mwh * co2_price / 1000
        opex = annual_opex(pi.opex, r.year) * r.fraction
        out.append(dict(mwh=mwh, revenue=revenue, opex=opex, ebitda=revenue - opex))
    return out


def annual_opex(items, year: int) -> Decimal:
    fixed, pct = {}, []
    for item in items:
        if item.percentage_of_opex > 0:
            pct.append(item)
            continue
        steps = sorted((y, a) for y, a in item.step_changes if y <= year)
        if steps:
            step_year, amount = steps[-1]
            value = dec(amount) * (ONE + dec(item.annual_inflation)) ** (year - step_year)
        else:
            value = dec(item.y1_amount_keur) * (ONE + dec(item.annual_inflation)) ** (year - 1)
        fixed[item.name] = max(ZERO, value)
    base = sum(fixed.values(), ZERO)
    for item in pct:
        fixed[item.name] = dec(item.percentage_of_opex) * base
    return sum(fixed.values(), ZERO)


def depreciation(dep_items, financial_cost_life: int, horizon: int, rows):
    from finco_core.inputs import ASSET_CLASS_USEFUL_LIFE, AssetClass
    annual = {y: ZERO for y in range(1, horizon + 1)}
    for item in dep_items:
        cls = AssetClass(item.asset_class_code)
        if cls is AssetClass.FINANCIAL_COSTS and item.useful_life_override is None:
            life = financial_cost_life
        else:
            life = item.useful_life_override or ASSET_CLASS_USEFUL_LIFE[cls]
        per_year = dec(item.amount_keur) / D(life)
        for y in range(1, min(life, horizon) + 1):
            annual[y] += per_year
    return [annual.get(r.year, ZERO) * r.fraction for r in rows]


# ── released calendar-year tax ledger ([start, end) fragments, FIFO losses) ──

def tax(rows, ebitda, tax_dep, interest, *, rate, lcf_years):
    """Return (cash tax per row, accrual per calendar year) under TAX_YEAR_LAST_PERIOD, lag 0."""
    by_year: dict[int, Decimal] = {}
    payment_row: dict[int, int] = {}
    for k, r in enumerate(rows):
        amount = ebitda[k] - tax_dep[k] - interest[k]
        total = (r.end - r.start).days
        cursor = r.start
        while cursor < r.end:
            year_end = date(cursor.year + 1, 1, 1)
            frag_end = min(r.end, year_end)
            by_year[cursor.year] = by_year.get(cursor.year, ZERO) + amount * D((frag_end - cursor).days) / D(total)
            cursor = frag_end
        payment_row[(r.end - timedelta(days=1)).year] = k
    cash = [ZERO] * len(rows)
    pool: list[list] = []  # [origin, last_usable, amount]
    accrual = {}
    for year in sorted(by_year):
        pool = [v for v in pool if v[1] >= year]
        taxable = by_year[year]
        if taxable <= 0:
            if taxable < 0:
                pool.append([year, year + lcf_years, -taxable])
            liability = ZERO
        else:
            remaining = taxable
            for v in pool:
                used = min(v[2], remaining)
                v[2] -= used
                remaining -= used
            pool = [v for v in pool if v[2] > 0]
            liability = dec(rate) * remaining
        accrual[year] = liability
        if year in payment_row:
            cash[payment_row[year]] += liability
    return cash, accrual


# ── Senior debt (released solver definitions) ────────────────────────────────

def accrual_fraction(start: date, end: date, day_count: str) -> Decimal:
    return D((end - start).days) / D(360 if day_count == "ACT_360" else 365)


def backward_capacity(cfads, fracs, rate, target):
    closing = ZERO
    for c, f in zip(reversed(cfads), reversed(fracs)):
        ds = max(ZERO, c / target)
        rf = rate * f
        if rf > D("1e-15"):
            closing = min(closing, ds / rf)
        closing = max(ZERO, (closing + ds) / (ONE + rf))
    return closing


def forward_roll(debt, cfads, fracs, rate, target):
    rows, balance = [], debt
    for c, f in zip(cfads, fracs):
        interest = balance * rate * f
        allowed = max(ZERO, c / target)
        principal = min(max(ZERO, allowed - interest), balance)
        closing = max(ZERO, balance - principal)
        rows.append(dict(opening=balance, interest=interest, principal=principal,
                         service=interest + principal, closing=closing))
        balance = closing
    return rows


@dataclass(frozen=True)
class SeniorOracle:
    debt: Decimal
    dscr_capacity: Decimal
    gearing_capacity: Decimal
    rows: tuple
    bank_cfads: tuple
    base_cfads: tuple
    base_cash_tax: tuple
    base_ebitda: tuple
    tax_dep: tuple


def senior(pi, *, total_project_uses_keur, dep_items, financial_cost_life):
    """DSCR capacity / gearing minimum with tax-interest fixed points, solved in Decimal."""
    info, fin, taxp = pi.info, pi.financing, pi.tax
    rows = operating_rows(info, int(pi.revenue.ppa_term_years))
    tenor_rows = fin.senior_tenor_years * 4
    rate = dec(fin.senior_debt_interest_config.rate_schedule.explicit_all_in_rates[0])
    day_count = fin.senior_debt_interest_config.day_count.name
    fracs = [accrual_fraction(r.start, r.end, day_count) for r in rows[:tenor_rows]]
    target = dec(fin.target_dscr)
    base = operating(pi, rows, "P50")
    bank = operating(pi, rows, "P90")
    tax_dep = depreciation(dep_items, financial_cost_life, info.horizon_years, rows)
    n = len(rows)

    def cfads_with(op, interest_debt_rows):
        interest = [r["interest"] for r in interest_debt_rows] + [ZERO] * (n - len(interest_debt_rows))
        ebitda = [o["ebitda"] for o in op]
        cash, _ = tax(rows, ebitda, tax_dep, interest, rate=taxp.corporate_rate, lcf_years=taxp.loss_carryforward_years)
        return [e - c for e, c in zip(ebitda, cash)], cash

    def fixed_point(debt_fn):
        debt = ZERO
        debt_rows = forward_roll(ZERO, [ZERO] * tenor_rows, fracs, rate, target)
        for _ in range(500):
            bank_cfads, _ = cfads_with(bank, debt_rows)
            new_debt = debt_fn(bank_cfads[:tenor_rows])
            new_rows = forward_roll(new_debt, bank_cfads[:tenor_rows], fracs, rate, target)
            delta = max([abs(new_debt - debt)] + [abs(a["interest"] - b["interest"]) for a, b in zip(new_rows, debt_rows)])
            debt, debt_rows = new_debt, new_rows
            if delta < D("1e-30"):
                return debt, debt_rows, bank_cfads
        raise AssertionError("oracle fixed point did not converge")

    capacity, _, _ = fixed_point(lambda cf: backward_capacity(cf, fracs, rate, target))
    gearing = dec(total_project_uses_keur) * dec(fin.gearing_ratio)
    final = min(capacity, gearing)
    _, debt_rows, bank_cfads = fixed_point(lambda cf: final)
    base_cfads, base_cash = cfads_with(base, debt_rows)
    return SeniorOracle(final, capacity, gearing, tuple(debt_rows), tuple(bank_cfads),
                        tuple(base_cfads), tuple(base_cash), tuple(o["ebitda"] for o in base), tuple(tax_dep))


# ── returns ──────────────────────────────────────────────────────────────────

def xirr(dates, flows) -> Decimal:
    """ACT/365 XIRR by bisection on NPV(r) in Decimal; requires one sign change."""
    t0 = dates[0]
    years = [D((d - t0).days) / D(365) for d in dates]

    def npv(r):
        with localcontext() as ctx:
            ctx.prec = 60
            return sum((f / (ONE + r) ** y for f, y in zip(flows, years)), ZERO)

    lo, hi = D("-0.99"), D("10")
    f_lo, f_hi = npv(lo), npv(hi)
    assert f_lo * f_hi < 0, "XIRR bracket"
    for _ in range(300):
        mid = (lo + hi) / 2
        f_mid = npv(mid)
        if f_lo * f_mid <= 0:
            hi, f_hi = mid, f_mid
        else:
            lo, f_lo = mid, f_mid
    return (lo + hi) / 2


def unlevered_project_flows(pi, *, hard_capex_rows, dep_items, financial_cost_life):
    rows = operating_rows(pi.info, int(pi.revenue.ppa_term_years))
    base = operating(pi, rows, "P50")
    tax_dep = depreciation(dep_items, financial_cost_life, pi.info.horizon_years, rows)
    ebitda = [o["ebitda"] for o in base]
    cash, _ = tax(rows, ebitda, tax_dep, [ZERO] * len(rows),
                  rate=pi.tax.corporate_rate, lcf_years=pi.tax.loss_carryforward_years)
    by_date: dict[date, Decimal] = {}
    for d, amount in hard_capex_rows:
        by_date[d] = by_date.get(d, ZERO) - dec(amount)
    for r, e, c in zip(rows, ebitda, cash):
        by_date[r.end] = by_date.get(r.end, ZERO) + e - c
    dates = sorted(by_date)
    return dates, [by_date[d] for d in dates]
