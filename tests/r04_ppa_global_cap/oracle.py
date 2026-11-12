"""Independent spec-derived oracle for R04: brute-force DAY-BY-DAY exact accounting.

Deliberately shares NO code with ``research.r04_ppa_global_cap``: it enumerates every calendar day, derives the per-day availability from
the authoritative segment energy (uniform over the segment's days) and the per-day contract energy from the contract volume (absolute:
annual MWh / days of the contract anniversary year the day falls in; percent: fraction of that day's availability), then aggregates by
calendar year and checks the ceiling day by day.
"""
from __future__ import annotations

from datetime import date, timedelta
from fractions import Fraction


def _add_years(d, k):
    try:
        return d.replace(year=d.year + k)
    except ValueError:
        return date(d.year + k, 2, 28)


def day_energy(segments, day):
    for start, end, mwh in segments:
        if start <= day < end:
            return Fraction(mwh) / (end - start).days
    return None


def contract_day_energy(contract, day, avail):
    start, end, basis, value = contract
    if not (start <= day < end):
        return Fraction(0)
    if basis == "PERCENT":
        return Fraction(value) * avail
    k = 0
    while _add_years(start, k + 1) <= day:
        k += 1
    return Fraction(value) / (_add_years(start, k + 1) - _add_years(start, k)).days


def run(segments, contracts):
    """segments: [(start, end, mwh)], contracts: [(start, end, 'MWH'|'PERCENT', value)] -> (per-year dict, breaches list)."""
    lo = min(c[0] for c in contracts)
    hi = max(c[1] for c in contracts)
    years, breaches = {}, []
    day = lo
    while day < hi:
        if not any(c[0] <= day < c[1] for c in contracts):      # a day with no active contract is outside the allocation report
            day += timedelta(days=1)
            continue
        avail = day_energy(segments, day)
        if avail is None:
            raise LookupError(day)
        per = {i: contract_day_energy(c, day, avail) for i, c in enumerate(contracts)}
        total = sum(per.values(), Fraction(0))
        row = years.setdefault(day.year, {"available": Fraction(0), "committed": Fraction(0), "per": {}})
        row["available"] += avail
        row["committed"] += total
        for i, v in per.items():
            row["per"][i] = row["per"].get(i, Fraction(0)) + v
        if total > avail:
            breaches.append((day, total - avail))
        day += timedelta(days=1)
    return years, breaches
