"""financial_engine.ppa_indexation — PPA tariff escalation policy.

Pure computation — no I/O, no project identity, no financial model state.

Three escalation policies:

FIRST_FULL_CALENDAR_YEAR_AS_BASE
    The first full calendar year following COD is index year zero.
    Escalation begins on 1 January of the year AFTER that base year.
    Example: COD = 29-Jun-2030 → base year = 2031 → first escalation 1-Jan-2032.

AFTER_FIRST_FULL_OPERATING_YEAR
    The first escalation occurs exactly one year after COD / operation start.
    Date-driven: each subsequent escalation on the COD anniversary.
    Example: COD = 29-Jun-2030 → first escalation 29-Jun-2031.

CONTRACT_ANNIVERSARY
    Escalation follows the anniversary of an explicit PPA / indexation start date.
    ppa_indexation_start_date is REQUIRED — callers must supply an explicit date.
    Example: COD = 29-Jun-2030, PPA start = 01-Oct-2030 → first escalation 01-Oct-2031.

Period-crossing convention
    The count of escalation events that have occurred is evaluated at the period END DATE.
    For FIRST_FULL_CALENDAR_YEAR_AS_BASE, indexation boundaries are 1 January, which coincide
    with semiannual period boundaries (June-30 / Dec-31 series) — no intra-period split required.
    For AFTER_FIRST_FULL_OPERATING_YEAR and CONTRACT_ANNIVERSARY, the indexation date is
    arbitrary and may fall inside a semiannual period. This module evaluates escalation at
    period_end and does NOT split the period. Callers requiring intra-period weighted revenue
    must implement that split themselves.
"""
from __future__ import annotations

from datetime import date
from enum import Enum


class PpaIndexationStartPolicy(str, Enum):
    """When PPA tariff escalation begins relative to COD / contract start."""
    FIRST_FULL_CALENDAR_YEAR_AS_BASE = "FIRST_FULL_CALENDAR_YEAR_AS_BASE"
    AFTER_FIRST_FULL_OPERATING_YEAR = "AFTER_FIRST_FULL_OPERATING_YEAR"
    CONTRACT_ANNIVERSARY = "CONTRACT_ANNIVERSARY"


def _base_year_for_first_full_cy(cod: date) -> int:
    """Return the first calendar year that is fully within the operating period.

    If COD falls on 1 January, that year is already a full year.
    Otherwise, the first full CY is cod.year + 1.
    """
    if cod.month == 1 and cod.day == 1:
        return cod.year
    return cod.year + 1


def count_ppa_escalation_events(
    policy: PpaIndexationStartPolicy,
    cod: date,
    period_end: date,
    ppa_indexation_start_date: date | None = None,
) -> int:
    """Return the number of PPA tariff escalation events that have occurred by period_end.

    Always returns a non-negative integer.  Zero means the base tariff applies.

    Args:
        policy: Which escalation timing convention to apply.
        cod: Contractual Operation Date (financial_close + construction_months).
        period_end: End date of the period being priced.
        ppa_indexation_start_date: Required when policy is CONTRACT_ANNIVERSARY.
            Raises ValueError if None and policy is CONTRACT_ANNIVERSARY.
    """
    from dateutil.relativedelta import relativedelta

    if policy == PpaIndexationStartPolicy.FIRST_FULL_CALENDAR_YEAR_AS_BASE:
        base_year = _base_year_for_first_full_cy(cod)
        # Escalation count = how many full calendar years after base_year have ended
        # by period_end.  Evaluated at end-of-period year.
        return max(0, period_end.year - base_year)

    elif policy == PpaIndexationStartPolicy.AFTER_FIRST_FULL_OPERATING_YEAR:
        # Count anniversary crossings: k such that cod + k years <= period_end, for k >= 1.
        k = 0
        while (cod + relativedelta(years=k + 1)) <= period_end:
            k += 1
        return k

    elif policy == PpaIndexationStartPolicy.CONTRACT_ANNIVERSARY:
        if ppa_indexation_start_date is None:
            raise ValueError(
                "ppa_indexation_start_date is required when policy is CONTRACT_ANNIVERSARY. "
                "Provide an explicit PPA / indexation start date."
            )
        ref = ppa_indexation_start_date
        k = 0
        while (ref + relativedelta(years=k + 1)) <= period_end:
            k += 1
        return k

    else:
        raise ValueError(f"Unknown PpaIndexationStartPolicy: {policy!r}")


def validate_no_intraperiod_escalation(
    policy: PpaIndexationStartPolicy,
    cod: date,
    period_start: date,
    period_end: date,
    ppa_indexation_start_date: date | None = None,
) -> None:
    """Raise ValueError if a PPA escalation anniversary falls strictly inside a period.

    FIRST_FULL_CALENDAR_YEAR_AS_BASE is year-based (not date-anchored) and never
    produces an intraperiod split — always passes without checking.

    AFTER_FIRST_FULL_OPERATING_YEAR and CONTRACT_ANNIVERSARY are date-anchored;
    the anniversary may fall at any day.  If an anniversary date falls at or after
    period_start and at or before period_end (i.e. strictly inside or at period_end),
    the tariff escalation event is ambiguous without an intra-period split.

    anniversary == period_start is safe: the whole period runs at the new tariff.
    anniversary == period_end is NOT safe: count_ppa_escalation_events() treats the
    event as having occurred by period_end, meaning the next period also sees the
    escalated tariff — but the split day is the last day of this period, which is
    equivalent to the first day of the next period. Until explicit splitting is
    implemented this boundary is rejected.
    anniversary > period_end: not yet escalated; safe.

    Raises:
        ValueError: if period_start < anniversary <= period_end.
    """
    from dateutil.relativedelta import relativedelta

    if policy == PpaIndexationStartPolicy.FIRST_FULL_CALENDAR_YEAR_AS_BASE:
        return  # year-based evaluation; never intraperiod

    if policy == PpaIndexationStartPolicy.AFTER_FIRST_FULL_OPERATING_YEAR:
        ref = cod
    elif policy == PpaIndexationStartPolicy.CONTRACT_ANNIVERSARY:
        if ppa_indexation_start_date is None:
            raise ValueError(
                "ppa_indexation_start_date is required when policy is CONTRACT_ANNIVERSARY. "
                "Provide an explicit PPA / indexation start date."
            )
        ref = ppa_indexation_start_date
    else:
        raise ValueError(f"Unknown PpaIndexationStartPolicy: {policy!r}")

    k = 1
    while True:
        anniversary = ref + relativedelta(years=k)
        if anniversary > period_end:
            break
        if period_start < anniversary <= period_end:
            raise ValueError(
                f"Selected PPA indexation policy {policy.value!r} requires intra-period tariff "
                f"splitting, which is not yet supported. Anniversary date {anniversary} falls "
                f"inside or at the end of period {period_start}–{period_end} "
                f"(supported boundary: anniversary == period_start only). "
                f"Use FIRST_FULL_CALENDAR_YEAR_AS_BASE for calendar-boundary-aligned escalation, "
                f"or choose an explicit contract anniversary date that equals period_start."
            )
        k += 1


def compute_ppa_tariff(
    base_tariff: float,
    ppa_index: float,
    policy: PpaIndexationStartPolicy,
    cod: date,
    period_end: date,
    ppa_indexation_start_date: date | None = None,
) -> float:
    """Return the PPA tariff (EUR/MWh) for a period ending at period_end.

    tariff = base_tariff * (1 + ppa_index) ** n_escalations

    Args:
        base_tariff: Y1 / base tariff in EUR/MWh.
        ppa_index: Annual escalation rate (e.g. 0.02 for 2%).
        policy: Escalation timing convention.
        cod: Contractual Operation Date.
        period_end: End date of the period being priced.
        ppa_indexation_start_date: Required for CONTRACT_ANNIVERSARY; raises ValueError if None.
    """
    n = count_ppa_escalation_events(policy, cod, period_end, ppa_indexation_start_date)
    return base_tariff * (1.0 + ppa_index) ** n
