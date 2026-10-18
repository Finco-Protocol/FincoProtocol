"""Presentation helpers shared by the institutional reporting writers (RC-7 / E2, E4).

Pure formatting/classification.  No financial arithmetic beyond counting and
summing already-persisted flow values for a display total.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from typing import Any, Iterable, Sequence

from app.export.run_evidence import NOT_AVAILABLE, number

FLOW = "Flow"
STOCK = "Stock"
RATIO = "Ratio"

NA_CELL = "n/a"  # not persisted for this period; deliberately distinct from a numeric 0

# Explicit zero stays visible as 0.0 (the legacy K_EUR format renders zero as "-",
# which reads like a blank).
KEUR_FORMAT = '#,##0.0;[Red](#,##0.0);0.0'
KEUR_FULL_FORMAT = '#,##0.000000;[Red](#,##0.000000);0.000000'
MULTIPLE_FORMAT = '0.0000"x"'
PCT_FORMAT = "0.0000%"
DATE_FORMAT = "yyyy-mm-dd"

# whole-word matching: "Corporate" must not read as "rate", "reintegration" not as "ratio"
_STOCK_RE = re.compile(r"\b(balance|opening|closing|cumulative|accumulated|retained|liabilities|check|"
                       r"reserve|fixed assets|total assets)\b")
_RATIO_RE = re.compile(r"\b(dscr|llcr|ratio|rate|irr|xirr|gearing)\b")


def classify_metric(label: str, default: str | None = None) -> str:
    """Stock (point-in-time balance), Flow (per-period amount) or Ratio, from the line label.

    Balances must never be summed across periods; ratios are never summed either.
    """
    text = (label or "").strip().lower()
    if default is not None:  # statement-level knowledge (e.g. every balance-sheet line is a stock)
        return default
    if text == "cash":  # unrestricted cash balance on the balance sheet
        return STOCK
    if _RATIO_RE.search(text):
        return RATIO
    if _STOCK_RE.search(text):
        return STOCK
    return FLOW


def parse_date(value: Any) -> date | None:
    if isinstance(value, date):
        return value
    if isinstance(value, str) and len(value) >= 10:
        try:
            return date.fromisoformat(value[:10])
        except ValueError:
            return None
    return None


def months_between(earlier: date, later: date) -> int:
    return (later.year - earlier.year) * 12 + (later.month - earlier.month)


# ── period basis (E4) ───────────────────────────────────────────────────────

_DECLARED_LABELS = {1: "Monthly", 3: "Quarterly", 6: "Half-year (semi-annual)", 12: "Annual"}
_NAMED_MONTHS = {"monthly": 1, "quarterly": 3, "semiannual": 6, "semi-annual": 6,
                 "semiannually": 6, "half-yearly": 6, "halfyear": 6, "annual": 12, "yearly": 12}


@dataclass(frozen=True)
class PeriodBasis:
    declared_months: int | None      # only from explicitly persisted metadata
    declared_source: str             # where the declaration was read, or ""
    observed_months: tuple[int, ...]  # distinct spacings between consecutive persisted period ends
    label: str
    disclosure: str
    warning: str = ""


def _declared(sources: Iterable[tuple[str, Any]]) -> tuple[int | None, str]:
    """Read explicit frequency metadata if (and only if) it was persisted.

    Accepts ``period_months`` (int) or ``frequency`` / ``period_frequency`` / ``period_view``
    (name).  Absent metadata yields (None, "") -- a frequency is never assumed.
    """
    for where, container in sources:
        if not isinstance(container, dict):
            continue
        months = container.get("period_months")
        if isinstance(months, int) and not isinstance(months, bool) and months > 0:
            return months, f"{where}.period_months"
        for key in ("frequency", "period_frequency", "period_view"):
            raw = container.get(key)
            if isinstance(raw, str):
                norm = raw.strip().lower().replace("_", "").replace(" ", "")
                if norm in _NAMED_MONTHS:
                    return _NAMED_MONTHS[norm], f"{where}.{key}"
    return None, ""


def period_basis(dates: Sequence[date | None], metadata_sources: Iterable[tuple[str, Any]] = (),
                 operating: Sequence[bool] | None = None) -> PeriodBasis:
    """Describe the period axis from persisted dates plus any explicit frequency metadata.

    A label is only ever derived from a persisted declaration or from the observed spacing of
    persisted dates, so 6-month data is reported as 6-month data and can never be relabelled
    quarterly.  Future frequency metadata (``period_months`` / ``frequency``) is read when present.
    """
    declared, where = _declared(metadata_sources)
    real = [d for d in dates if d is not None]
    spacings = sorted({months_between(a, b) for a, b in zip(real, real[1:])})
    observed = tuple(spacings)
    if declared is not None:
        label = _DECLARED_LABELS.get(declared, f"{declared}-month periods")
        disc = f"Declared by persisted metadata ({where}): {label}."
        warning = ""
        if observed and set(observed) != {declared}:
            warning = (f"FREQUENCY_METADATA_MISMATCH: declared {declared}-month periods but persisted "
                       f"period ends are spaced {', '.join(map(str, observed))} month(s) apart. "
                       "Period dates are shown as persisted.")
        return PeriodBasis(declared, where, observed, label, disc, warning)
    if operating is not None and len(operating) == len(dates):
        op_dates = [d for d, o in zip(dates, operating) if o and d is not None]
        op_sp = sorted({months_between(a, b) for a, b in zip(op_dates, op_dates[1:])})
        if len(op_sp) == 1 and len(observed) > 1:
            m = op_sp[0]
            return PeriodBasis(None, "", observed, f"{m}-month spacing in operation (observed); "
                               "construction / stub periods vary",
                               f"No frequency metadata persisted; operating period ends are {m} months apart "
                               f"(construction and stub periods are spaced {', '.join(map(str, observed))} months). "
                               "The label describes observed spacing only.")
    if len(observed) == 1:
        m = observed[0]
        return PeriodBasis(None, "", observed, f"{m}-month spacing (observed)",
                           f"No frequency metadata persisted; consecutive persisted period ends are {m} "
                           "months apart. The label describes the observed spacing only.")
    if not observed:
        return PeriodBasis(None, "", observed, "Not determinable",
                           "Fewer than two dated periods persisted and no frequency metadata.")
    return PeriodBasis(None, "", observed, "Irregular spacing",
                       "No frequency metadata persisted; period-end spacing varies "
                       f"({', '.join(map(str, observed))} months). Dates are shown as persisted.")


def period_label(index: Any, end: date | None) -> str:
    """Neutral period label: ordinal + persisted end date (never a Q/H/Y name)."""
    idx = f"P{index}" if index is not None else "P?"
    return f"{idx} | {end.isoformat()}" if end is not None else f"{idx} | date n/a"


# ── totals ──────────────────────────────────────────────────────────────────

def display_total(values: Sequence[Any], kind: str) -> tuple[Any, str]:
    """(cell value, coverage note) for a table's Total column.

    Flows: sum of the PERSISTED values; missing periods are never counted as zero, and
    coverage is returned so a partial total is visible.  Stocks and ratios are not summed.
    """
    if kind == STOCK:
        return "n/a (balance)", ""
    if kind == RATIO:
        return "n/a (ratio)", ""
    nums = [number(v) for v in values]
    present = [n for n in nums if n is not None]
    if not present:
        return NOT_AVAILABLE, f"0 of {len(values)} periods persisted"
    note = "" if len(present) == len(values) else f"{len(present)} of {len(values)} periods persisted"
    return sum(present), note
