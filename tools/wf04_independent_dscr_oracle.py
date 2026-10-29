"""WF-04 independent DSCR / EoD / covenant oracle.  Python standard library ONLY (decimal, math).

It re-derives the three credit conclusions of one committed Run from the sealed Senior-debt period evidence and the two contractual DSCR terms
as saved text.  Nothing is imported from the FINCO code base: no engine function, tolerance constant, formatter or verdict is reused.  The
decision is taken on the exact value of each stored IEEE-754 double (``Decimal(float)`` is exact), never on a rounded display value, with a
strict ``<`` and no tolerance.  A period is tested only when its scheduled Senior debt service exceeds 1e-6 kEUR.
"""
from decimal import Decimal, getcontext
import math

getcontext().prec = 60
SERVICE_EPS = Decimal("1e-6")
FLOOR, CEILING = Decimal("0.01"), Decimal("10")


def _term(text):
    """('NOT_CONFIGURED'|'INVALID'|'CONFIGURED', float|None) from the saved text of one term."""
    if text is None or str(text).strip() == "":
        return "NOT_CONFIGURED", None
    try:
        value = float(str(text).strip())
    except ValueError:
        return "INVALID", None
    if not math.isfinite(value) or not (FLOOR <= Decimal(value) <= CEILING):
        return "INVALID", None
    return "CONFIGURED", value


def periods_under_test(evidence):
    out = []
    for row in evidence["senior_debt"]["periods"]:
        service = row.get("debt_service")
        if isinstance(service, (int, float)) and not isinstance(service, bool) and Decimal(service) > SERVICE_EPS:
            out.append(row)
    return out


def _threshold(rows, term_text, name):
    state, value = _term(term_text)
    if state != "CONFIGURED":
        return {"status": state}
    if not rows:
        return {"status": "NOT_APPLICABLE"}
    usable = [r for r in rows if isinstance(r.get("reported_dscr"), (int, float)) and math.isfinite(r["reported_dscr"])]
    breaching = [r["period_index"] for r in usable if Decimal(r["reported_dscr"]) < Decimal(value)]
    if breaching:
        return {"status": name[0], "periods": breaching}
    if len(usable) != len(rows):
        return {"status": "UNAVAILABLE"}
    return {"status": name[1]}


def verdicts(evidence, eod_text, contractual_text):
    rows = periods_under_test(evidence)
    usable = [r for r in rows if isinstance(r.get("reported_dscr"), (int, float)) and math.isfinite(r["reported_dscr"])]
    low = min(usable, key=lambda r: Decimal(r["reported_dscr"])) if usable else None
    deficits = [r["period_index"] for r in usable if Decimal(r["reported_dscr"]) < Decimal(1)]
    if not rows:
        coverage = {"status": "NOT_APPLICABLE"}
    elif deficits:
        coverage = {"status": "DEFICIENCY", "periods": deficits}
    elif len(usable) != len(rows):
        coverage = {"status": "UNAVAILABLE"}
    else:
        coverage = {"status": "NO_DEFICIENCY_FOUND"}
    # recomputation cross-check: the stored ratio is base CFADS / scheduled debt service
    deviation = max((abs(Decimal(r["reported_dscr"]) - Decimal(r["base_cfads"]) / Decimal(r["debt_service"])) for r in usable
                     if r.get("base_cfads") is not None), default=Decimal(0))
    return {
        "tested_periods": len(rows),
        "achieved_min": None if low is None else low["reported_dscr"],
        "achieved_min_period": None if low is None else low["period_index"],
        "recompute_max_deviation": float(deviation),
        "eod": _threshold(rows, eod_text, ("TRIGGERED", "NOT_TRIGGERED_UNDER_THIS_FLOOR")),
        "covenant": _threshold(rows, contractual_text, ("BREACHED", "COMPLIANT")),
        "coverage": coverage,
    }
