"""F3.9 identity catalogue: independent Decimal checks over one evidence bundle.

Every identity recomputes a persisted quantity from OTHER persisted quantities of the same immutable Run, using only
Decimal arithmetic and the existing independent oracles.  It never reads a production module, never runs the model, and
never repairs, fits or substitutes a value.  Evidence that is absent is UNAVAILABLE; evidence whose periods, units or
definitions cannot be proven to line up is NOT_COMPARABLE.  Neither is ever reported as agreement.
"""
from __future__ import annotations

import re
from collections.abc import Mapping
from datetime import date
from decimal import Decimal
from typing import Any, Callable

from . import oracles
from .periodic import (BASIS_2DP, BASIS_FULL, KIND_CALCULATION, KIND_INPUT, Reconciler, TolerancePolicy)

# ── Approved tolerances ────────────────────────────────────────────────────────────────────────────────────────
# The numbers below MUST equal the constants the product already approved; a test asserts that, so a silent change
# of either side fails the build.  They are never adjusted per identity, vertical or Run.
KEUR_FULL = "KEUR_FULL_PRECISION"
KEUR_2DP = "KEUR_PERSISTED_2DP"
RATIO = "RATIO"
XIRR = "XIRR"
MWH_DISPLAY = "MWH_DISPLAY_ROUNDING"


def default_policies() -> list[TolerancePolicy]:
    return [
        TolerancePolicy(KEUR_FULL, Decimal("1e-6"), Decimal(0),
                        "app/run_integrity/contracts.py TOL_KEUR; app/v2/financing_sources_uses_projection.py "
                        "FINANCE_TOLERANCE_KEUR (existing G2A allocation audit)",
                        "kEUR identities over evidence recorded at full precision at commit time"),
        TolerancePolicy(KEUR_2DP, Decimal("1e-6"), Decimal(0),
                        "same approved kEUR tolerance, PLUS a separate half-quantum representation allowance per "
                        "value the product persists rounded to 2 decimals (F3.8: statements are persisted at 2dp)",
                        "the financial tolerance is unchanged; the allowance only bounds serialisation rounding"),
        TolerancePolicy(RATIO, Decimal("1e-7"), Decimal(0),
                        "app/run_integrity/checks.py check_dscr_identity: TOL_RATIO (1e-9) x 100",
                        "ratios (DSCR, day fractions) recorded at full precision"),
        TolerancePolicy(MWH_DISPLAY, Decimal("0.5"), Decimal(0),
                        "representation bound: generation is persisted only as display text rounded to whole MWh",
                        "half of one displayed unit; not a financial tolerance, used only for the allocation check"),
        TolerancePolicy(XIRR, Decimal("1e-9"), Decimal(0),
                        "app/run_integrity/contracts.py TOL_XIRR",
                        "internal rates of return recomputed independently from the committed flows"),
    ]


_RATIO_IDS = ("ret.", "summary.project_irr", "summary.equity_irr", "summary.sponsor_irr", "summary.total_sponsor_xirr",
              "summary.min_dscr", "summary.avg_dscr", "sponsor.project_xirr", "ev.senior.day_fraction", "ev.senior.dscr")
_STREAM_UNITS = {"quantity": "MWh", "price": "EUR/MWh", "capture": "ratio"}


def expected_unit(sid: str) -> str:
    """Unit a series/scalar MUST carry (declared convention); everything else is kEUR."""
    if sid in ("rev.generation_display", "rv2.unallocated"):
        return "MWh"
    if sid.startswith("rv2.stream."):
        return _STREAM_UNITS.get(sid.rsplit(".", 1)[-1], "kEUR")
    if sid.endswith((".day_fraction", ".annual_rate")):
        return "ratio"
    if any(sid == r or (r.endswith(".") and sid.startswith(r)) for r in _RATIO_IDS):
        return "ratio"
    return "kEUR"


class View:
    """Typed, read-only access to a bundle.  Missing is ``None``; nothing is defaulted.

    A series or scalar whose recorded unit differs from the declared convention is WITHHELD (read as absent) and
    listed in ``unit_errors``: values in different units are never compared or converted.
    """

    def __init__(self, bundle: Mapping[str, Any]):
        self.b = bundle
        self.unit_errors: dict[str, tuple[str, str]] = {}
        for group in ("series", "scalars"):
            for sid, item in bundle[group].items():
                want = expected_unit(sid)
                if item.get("unit") != want:
                    self.unit_errors[sid] = (str(item.get("unit")), want)

    def axis(self, name: str, phase: str | None = None) -> list[dict[str, Any]]:
        rows = self.b["axes"].get(name) or []
        return [r for r in rows if phase is None or r["phase"] == phase]

    def series(self, sid: str) -> dict[str, Decimal | None] | None:
        s = self.b["series"].get(sid)
        if s is None or sid in self.unit_errors:
            return None
        return {k: (None if v is None else Decimal(v)) for k, v in s["values"].items()}

    def scalar(self, sid: str) -> Decimal | None:
        s = self.b["scalars"].get(sid)
        return None if s is None or sid in self.unit_errors or s["value"] is None else Decimal(s["value"])

    def fact(self, key: str) -> Any:
        return self.b["facts"].get(key)

    def has(self, sid: str) -> bool:
        return sid in self.b["series"]


def _all(*values: Decimal | None) -> bool:
    return all(v is not None for v in values)


def _nonzero_terms(*values: Decimal | None) -> int:
    return sum(1 for v in values if v is not None and v != 0)


def build_reconciler(bundle: Mapping[str, Any]) -> Reconciler:
    """Run every identity over ``bundle`` and return the populated Reconciler."""
    rec = Reconciler(default_policies(), identity=dict(bundle["identity"]))
    v = View(bundle)
    for fn in (_axes, _assumptions, _revenue, _contract_revenue, _ebitda, _funding, _senior, _facilities, _statements, _tax, _cash,
               _returns):
        fn(rec, v)
    return rec


# ── axes ───────────────────────────────────────────────────────────────────────────────────────────────────────
def _axes(rec: Reconciler, v: View) -> None:
    rec.register("AXIS-INTEGRITY", "assumptions", KIND_INPUT, "Period axes are unique, dated and consistent across payloads",
                 BASIS_FULL, KEUR_FULL)
    errors = v.b["axis_errors"]
    if not v.axis("statements"):
        rec.unavailable("AXIS-INTEGRITY", None, "STATEMENT_AXIS_MISSING")
    for i, e in enumerate(errors):
        # An axis conflict is evidence that two payloads do not describe the same periods.
        rec.not_comparable("AXIS-INTEGRITY", f"{e['axis']}#{i}", e["reason"])
    if v.axis("statements") and not errors:
        rec.check("AXIS-INTEGRITY", "statements", Decimal(0), Decimal(0))
    rec.register("UNIT-CONSISTENCY", "assumptions", KIND_INPUT, "Every series carries its declared unit (kEUR, MWh, ratio)",
                 BASIS_FULL, KEUR_FULL)
    for sid, (got, want) in sorted(v.unit_errors.items()):
        rec.not_comparable("UNIT-CONSISTENCY", sid, f"UNIT_MISMATCH_{got}_EXPECTED_{want}")
    if not v.unit_errors:
        rec.check("UNIT-CONSISTENCY", "all", Decimal(0), Decimal(0))


# ── assumptions (recorded inputs) ───────────────────────────────────────────────────────────────────────────────
def _basis(day_count: Any) -> Decimal | None:
    return {"ACT_360": Decimal(360), "ACT_365": Decimal(365)}.get(day_count if isinstance(day_count, str) else "")


def _assumptions(rec: Reconciler, v: View) -> None:
    rec.register("ASM-DAYFRACTION", "assumptions", KIND_INPUT,
                 "Recorded Senior day fraction = actual days since the previous dated row / day-count basis",
                 BASIS_FULL, RATIO)
    frac = v.series("ev.senior.day_fraction")
    axis = v.axis("statements")
    if frac is None:
        rec.unavailable("ASM-DAYFRACTION", None, "SENIOR_DAY_FRACTION_NOT_RECORDED")
        return
    basis = _basis(v.fact("day_count"))
    if basis is None:
        rec.unavailable("ASM-DAYFRACTION", None, "DAY_COUNT_CONVENTION_NOT_RECORDED")
        return
    previous: dict[str, str] = {axis[i]["key"]: axis[i - 1]["key"] for i in range(1, len(axis))}
    for key, recorded in frac.items():
        before = previous.get(key)
        if recorded is None:
            rec.unavailable("ASM-DAYFRACTION", key, "DAY_FRACTION_MISSING")
        elif before is None:
            rec.not_comparable("ASM-DAYFRACTION", key, "NO_PREVIOUS_DATED_ROW")
        else:
            days = (date.fromisoformat(key) - date.fromisoformat(before)).days
            rec.check("ASM-DAYFRACTION", key, recorded, Decimal(days) / basis)


# ── revenue ────────────────────────────────────────────────────────────────────────────────────────────────────
def _label_matches(label: str, key: str) -> bool:
    m = re.match(r"^Y(\d{4})-H([12])$", label)
    d = date.fromisoformat(key)
    return bool(m) and int(m.group(1)) == d.year and int(m.group(2)) == (1 if d.month <= 6 else 2)


def _revenue(rec: Reconciler, v: View) -> None:
    rec.register("REV-TOTAL", "revenue", KIND_CALCULATION, "Reported total revenue = sum of its own revenue periods",
                 BASIS_FULL, KEUR_FULL)
    rec.register("REV-STATEMENT", "revenue", KIND_CALCULATION,
                 "Statement revenue (2dp) = revenue period at the same dated operating row", BASIS_2DP, KEUR_2DP)
    rec.register("REV-STATEMENT-TOTAL", "revenue", KIND_CALCULATION,
                 "Reported total revenue = sum of persisted statement revenue", BASIS_2DP, KEUR_2DP)
    periods = v.series("rev.period_revenue")
    total = v.scalar("summary.total_revenue_keur")
    if periods is None or total is None or any(x is None for x in periods.values()) or not periods:
        rec.unavailable("REV-TOTAL", None, "REVENUE_PERIODS_OR_TOTAL_MISSING")
    else:
        o = oracles.sum_of_periods(list(periods.values()), total, tolerance=Decimal(0))
        rec.check("REV-TOTAL", "total", Decimal(o.observed), Decimal(o.expected))
    pnl = v.series("stmt.pnl.revenues")
    operating = v.axis("statements", "operation")
    if periods is None or pnl is None or not operating:
        rec.unavailable("REV-STATEMENT", None, "REVENUE_PERIODS_OR_STATEMENT_MISSING")
    else:
        labels = v.axis("revenue")
        if len(labels) != len(operating):
            rec.not_comparable("REV-STATEMENT", None, "REVENUE_PERIOD_COUNT_DIFFERS_FROM_OPERATING_ROWS")
        else:
            for label, row in zip(labels, operating):
                key = row["key"]
                if not _label_matches(label["key"], key):
                    rec.not_comparable("REV-STATEMENT", key, "REVENUE_LABEL_DISAGREES_WITH_ROW_DATE")
                elif periods.get(label["key"]) is None or pnl.get(key) is None:
                    rec.unavailable("REV-STATEMENT", key, "VALUE_MISSING")
                else:
                    rec.check("REV-STATEMENT", key, pnl[key], periods[label["key"]], rounded_terms=1)
    if pnl is None or total is None or any(x is None for x in pnl.values()):
        rec.unavailable("REV-STATEMENT-TOTAL", None, "STATEMENT_REVENUE_OR_TOTAL_MISSING")
    else:
        o = oracles.sum_of_periods(list(pnl.values()), total, tolerance=Decimal(0))
        rec.check("REV-STATEMENT-TOTAL", "total", Decimal(o.expected), Decimal(o.observed),
                  rounded_terms=_nonzero_terms(*pnl.values()))


# ── Revenue V2 explicit contracts ───────────────────────────────────────────────────────────────────────────────
def _contract_revenue(rec: Reconciler, v: View) -> None:
    for key, title, basis, pol in (
            ("RV2-ENERGY-REVENUE", "Stream revenue = quantity x price x capture / 1,000 (physical streams)",
             BASIS_FULL, KEUR_FULL),
            ("RV2-CFD-SETTLEMENT", "Signed CfD settlement = quantity x (strike - reference price) / 1,000",
             BASIS_FULL, KEUR_FULL),
            ("RV2-NET-REVENUE", "Net revenue = sum of stream revenue - balancing + certificate revenue",
             BASIS_FULL, KEUR_FULL),
            ("RV2-NET-VS-REVENUE-PERIOD", "Contract net revenue = revenue period at the same dated operating row",
             BASIS_FULL, KEUR_FULL),
            ("RV2-GENERATION-ALLOCATION", "Physical stream quantities + unallocated generation = generation "
                                          "(display rounding)", "PERSISTED_2DP", MWH_DISPLAY)):
        rec.register(key, "revenue", KIND_CALCULATION, title, BASIS_FULL if key != "RV2-GENERATION-ALLOCATION"
                     else BASIS_FULL, pol)
    streams: dict[str, str] = v.fact("rv2.streams") or {}
    net = v.series("rv2.net_revenue")
    if not streams or net is None:
        for key in ("RV2-ENERGY-REVENUE", "RV2-CFD-SETTLEMENT", "RV2-NET-REVENUE", "RV2-NET-VS-REVENUE-PERIOD",
                    "RV2-GENERATION-ALLOCATION"):
            rec.unavailable(key, None, "NO_EXPLICIT_REVENUE_CONTRACTS_IN_THIS_RUN")
        return
    phys = [sid for sid, kind in streams.items() if kind != "cfd"]
    cfds = [sid for sid, kind in streams.items() if kind == "cfd"]
    merchants = [sid for sid, kind in streams.items() if kind == "merchant"]

    def stream(sid: str, name: str, key: str) -> Decimal | None:
        series = v.series(f"rv2.stream.{sid}.{name}")
        return None if series is None else series.get(key)

    keys = sorted(net, key=lambda k: [r["key"] for r in v.axis("statements")].index(k)
                  if k in [r["key"] for r in v.axis("statements")] else 10 ** 9)
    labels = v.axis("revenue")
    operating = [r["key"] for r in v.axis("statements", "operation")]
    label_of = ({row: lab["key"] for lab, row in zip(labels, operating)} if len(labels) == len(operating) else {})
    revenue_periods, generation = v.series("rev.period_revenue"), v.series("rev.generation_display")
    for key in keys:
        for sid in phys:
            q, p, r, c = (stream(sid, n, key) for n in ("quantity", "price", "revenue", "capture"))
            if not _all(q, p, r):
                rec.unavailable("RV2-ENERGY-REVENUE", f"{sid}@{key}", "STREAM_VALUE_MISSING")
            elif streams[sid] != "merchant" and c not in (None, Decimal(1)):
                rec.not_comparable("RV2-ENERGY-REVENUE", f"{sid}@{key}", "CAPTURE_SEMANTICS_NOT_PROVEN_FOR_THIS_STREAM")
            else:
                res = oracles.energy_revenue([(q, p * (c if c is not None else Decimal(1)))], r, tolerance=Decimal(0))
                rec.check("RV2-ENERGY-REVENUE", f"{sid}@{key}", Decimal(res.observed), Decimal(res.expected))
        for sid in cfds:
            q, strike, settlement = (stream(sid, n, key) for n in ("quantity", "price", "settlement"))
            if len(merchants) != 1:
                rec.not_comparable("RV2-CFD-SETTLEMENT", f"{sid}@{key}", "CFD_REFERENCE_STREAM_NOT_IDENTIFIED")
                continue
            ref, ref_capture = stream(merchants[0], "price", key), stream(merchants[0], "capture", key)
            if not _all(q, strike, settlement, ref):
                rec.unavailable("RV2-CFD-SETTLEMENT", f"{sid}@{key}", "STREAM_VALUE_MISSING")
            elif ref_capture not in (None, Decimal(1)):
                rec.not_comparable("RV2-CFD-SETTLEMENT", f"{sid}@{key}", "REFERENCE_CAPTURE_SEMANTICS_NOT_PROVEN")
            else:
                res = oracles.cfd_settlement(q, strike, ref, settlement, tolerance=Decimal(0))
                rec.check("RV2-CFD-SETTLEMENT", f"{sid}@{key}", Decimal(res.observed), Decimal(res.expected))
        parts = [stream(sid, "revenue", key) for sid in streams]
        bal, cert, n = (v.series("rv2." + x).get(key) if v.series("rv2." + x) else None
                        for x in ("balancing", "certificate", "net_revenue"))
        if not parts or any(p is None for p in parts) or not _all(bal, cert, n):
            rec.unavailable("RV2-NET-REVENUE", key, "STREAM_OR_ADJUSTMENT_MISSING")
        else:
            rec.check("RV2-NET-REVENUE", key, n, sum(parts, Decimal(0)) - bal + cert)
        label = label_of.get(key)
        if revenue_periods is None or label is None:
            rec.not_comparable("RV2-NET-VS-REVENUE-PERIOD", key, "REVENUE_PERIOD_AXIS_NOT_PROVEN")
        elif not _label_matches(label, key):
            rec.not_comparable("RV2-NET-VS-REVENUE-PERIOD", key, "REVENUE_LABEL_DISAGREES_WITH_ROW_DATE")
        elif revenue_periods.get(label) is None or n is None:
            rec.unavailable("RV2-NET-VS-REVENUE-PERIOD", key, "VALUE_MISSING")
        else:
            rec.check("RV2-NET-VS-REVENUE-PERIOD", key, n, revenue_periods[label])
        unalloc = v.series("rv2.unallocated").get(key) if v.series("rv2.unallocated") else None
        qs = [stream(sid, "quantity", key) for sid in phys]
        gen = generation.get(label) if generation is not None and label else None
        if unalloc is None or gen is None or any(q is None for q in qs):
            rec.unavailable("RV2-GENERATION-ALLOCATION", key, "GENERATION_OR_QUANTITY_NOT_PERSISTED")
        else:
            rec.check("RV2-GENERATION-ALLOCATION", key, sum(qs, Decimal(0)) + unalloc, gen)


# ── operating expenses and EBITDA ───────────────────────────────────────────────────────────────────────────────
def _ebitda(rec: Reconciler, v: View) -> None:
    for key, title in (
            ("EBITDA-PERIOD", "EBITDA = revenue - operating expenses (persisted cash waterfall, 2dp)"),
            ("EBITDA-REVENUE-LINK", "Revenue in the P&L = revenue in the cash waterfall (2dp)"),
            ("EBIT-PERIOD", "EBIT = revenue - operating expenses - depreciation (persisted P&L, 2dp)")):
        rec.register(key, "opex_ebitda", KIND_CALCULATION, title, BASIS_2DP, KEUR_2DP)
    for key, title in (("EBITDA-TOTAL", "Reported total EBITDA = sum of waterfall EBITDA"),
                       ("OPEX-TOTAL", "Reported total operating expenses = sum of waterfall operating expenses")):
        rec.register(key, "opex_ebitda", KIND_CALCULATION, title, BASIS_2DP, KEUR_2DP)
    rec.register("EBITDA-SUMMARY", "opex_ebitda", KIND_CALCULATION,
                 "Reported total EBITDA = reported total revenue - reported total operating expenses",
                 BASIS_FULL, KEUR_FULL)
    revenue, opex, ebitda = (v.series("stmt.pf." + n) for n in ("revenue_cash", "opex_cash", "ebitda_cash"))
    if None in (revenue, opex, ebitda):
        rec.unavailable("EBITDA-PERIOD", None, "CASH_WATERFALL_MISSING")
    else:
        for key in ebitda:
            r, o, e = revenue.get(key), opex.get(key), ebitda[key]
            if not _all(r, o, e):
                rec.unavailable("EBITDA-PERIOD", key, "VALUE_MISSING")
                continue
            res = oracles.ebitda(r, o, e, tolerance=Decimal(0))
            rec.check("EBITDA-PERIOD", key, Decimal(res.observed), Decimal(res.expected),
                      rounded_terms=_nonzero_terms(r, o, e))
    pnl_rev, pnl_opex, pnl_dep, pnl_ebit = (v.series("stmt.pnl." + n) for n in
                                           ("revenues", "operating_expenses", "depreciation", "ebit"))
    if None in (pnl_rev, revenue):
        rec.unavailable("EBITDA-REVENUE-LINK", None, "REVENUE_SERIES_MISSING")
    else:
        for key, value in pnl_rev.items():
            other = revenue.get(key)
            if value is None or other is None:
                rec.unavailable("EBITDA-REVENUE-LINK", key, "VALUE_MISSING")
            else:
                rec.check("EBITDA-REVENUE-LINK", key, value, other, rounded_terms=_nonzero_terms(value, other))
    if None in (pnl_rev, pnl_opex, pnl_dep, pnl_ebit):
        rec.unavailable("EBIT-PERIOD", None, "PNL_MISSING")
    else:
        for key, e in pnl_ebit.items():
            r, o, d = pnl_rev.get(key), pnl_opex.get(key), pnl_dep.get(key)
            if not _all(r, o, d, e):
                rec.unavailable("EBIT-PERIOD", key, "VALUE_MISSING")
                continue
            res = oracles.ebit(r, o, d, e, tolerance=Decimal(0))
            rec.check("EBIT-PERIOD", key, Decimal(res.observed), Decimal(res.expected),
                      rounded_terms=_nonzero_terms(r, o, d, e))
    for ident, series, scalar in (("EBITDA-TOTAL", ebitda, "summary.total_ebitda_keur"),
                                  ("OPEX-TOTAL", opex, "summary.total_opex_keur")):
        total = v.scalar(scalar)
        if series is None or total is None or any(x is None for x in series.values()):
            rec.unavailable(ident, None, "SERIES_OR_TOTAL_MISSING")
        else:
            res = oracles.sum_of_periods(list(series.values()), total, tolerance=Decimal(0))
            rec.check(ident, "total", Decimal(res.expected), Decimal(res.observed),
                      rounded_terms=_nonzero_terms(*series.values()))
    r, o, e = (v.scalar("summary." + n) for n in ("total_revenue_keur", "total_opex_keur", "total_ebitda_keur"))
    if not _all(r, o, e):
        rec.unavailable("EBITDA-SUMMARY", None, "SUMMARY_TOTALS_MISSING")
    else:
        res = oracles.ebitda(r, o, e, tolerance=Decimal(0))
        rec.check("EBITDA-SUMMARY", "total", Decimal(res.observed), Decimal(res.expected))


# ── Sources & Uses and funding ──────────────────────────────────────────────────────────────────────────────────
_USES = ("base_project_capex_keur", "capitalized_idc_keur", "commitment_fee_keur", "structuring_fee_keur",
         "other_financing_costs_keur", "initial_dsra_funding_keur", "other_uses_keur",
         "development_cost_reimbursement_keur", "developer_fee_keur")
_SOURCES = ("senior_debt_keur", "junior_or_other_keur", "share_capital_and_other_equity_keur",
            "shareholder_loan_cash_keur")


def _funding(rec: Reconciler, v: View) -> None:
    for key, title in (("SU-USES-SUM", "Uses components sum to total uses"),
                       ("SU-SOURCES-SUM", "Sources components sum to total sources"),
                       ("SU-BALANCE", "Total sources = total uses"),
                       ("SU-PERIOD", "Sources = uses in every construction period"),
                       ("SU-AUDIT-USES", "Audit total uses = construction-period uses + Financial Close use outside them"),
                       ("SU-AUDIT-SOURCES",
                        "Audit total sources = construction-period sources + Financial Close source outside them"),
                       ("SU-AUDIT-USES-CONSTRUCTION", "Audit total uses = construction-period uses "
                                                      "(when no Financial Close term outside them is recorded)"),
                       ("SU-AUDIT-SOURCES-CONSTRUCTION", "Audit total sources = construction-period sources "
                                                         "(when no Financial Close term outside them is recorded)"),
                       ("CAPEX-LINK", "Reported total CAPEX = base project CAPEX in Sources & Uses"),
                       ("FUND-IDC", "Senior facility construction IDC = capitalised IDC in Sources & Uses"),
                       ("FUND-JUNIOR-IDC", "Junior facility construction IDC = Junior cash IDC record"),
                       ("FUND-COMMITMENT-FEES", "Facility commitment fees = commitment fees in Sources & Uses"),
                       ("FUND-UPFRONT-FEES", "Facility upfront fees = structuring fees in Sources & Uses"),
                       ("FUND-COMMITMENT", "Facility commitments = Senior (+ Junior) in Sources & Uses"),
                       ("FUND-FUNDED-OPENING", "Facility construction draws = first operating opening")):
        rec.register(key, "capex_funding", KIND_CALCULATION, title, BASIS_FULL, KEUR_FULL)
    scalars = {k: v.scalar("su." + k) for k in _USES + _SOURCES + ("total_uses_keur", "total_sources_keur")}
    if any(scalars[k] is None for k in _USES + ("total_uses_keur",)):
        rec.unavailable("SU-USES-SUM", None, "USES_EVIDENCE_MISSING_NOT_DEFAULTED_TO_ZERO")
    else:
        res = oracles.sum_of_periods([scalars[k] for k in _USES], scalars["total_uses_keur"], tolerance=Decimal(0))
        rec.check("SU-USES-SUM", "total", Decimal(res.observed), Decimal(res.expected))
    if any(scalars[k] is None for k in _SOURCES + ("total_sources_keur",)):
        rec.unavailable("SU-SOURCES-SUM", None, "SOURCES_EVIDENCE_MISSING")
    else:
        res = oracles.sum_of_periods([scalars[k] for k in _SOURCES], scalars["total_sources_keur"],
                                     tolerance=Decimal(0))
        rec.check("SU-SOURCES-SUM", "total", Decimal(res.observed), Decimal(res.expected))
    if scalars["total_sources_keur"] is None or scalars["total_uses_keur"] is None:
        rec.unavailable("SU-BALANCE", None, "TOTALS_MISSING")
    else:
        res = oracles.sources_uses(scalars["total_sources_keur"], scalars["total_uses_keur"], tolerance=Decimal(0))
        rec.check("SU-BALANCE", "total", Decimal(res.observed), Decimal(res.expected))
    uses, sources = v.series("su.construction.uses"), v.series("su.construction.sources")
    if uses is None or sources is None:
        rec.unavailable("SU-PERIOD", None, "CONSTRUCTION_PERIODS_MISSING")
    else:
        for key in sorted(set(uses) | set(sources)):
            u, s = uses.get(key), sources.get(key)
            if not _all(u, s):
                rec.unavailable("SU-PERIOD", key, "VALUE_MISSING")
            else:
                res = oracles.sources_uses(s, u, tolerance=Decimal(0))
                rec.check("SU-PERIOD", key, Decimal(res.observed), Decimal(res.expected))
        # The audit total spans the construction periods AND any use / source booked at Financial Close outside them
        # (e.g. the initial DSRA funding).  A recorded term is added; a term the Run records as null is NOT treated as
        # zero: the construction-only identity is evaluated instead, which holds only if that term really is nil.
        for ident, fallback, series, scalar, extra in (
                ("SU-AUDIT-USES", "SU-AUDIT-USES-CONSTRUCTION", uses, "su.audit.uses", "su.nonconstruction.uses"),
                ("SU-AUDIT-SOURCES", "SU-AUDIT-SOURCES-CONSTRUCTION", sources, "su.audit.sources",
                 "su.nonconstruction.sources")):
            total, outside = v.scalar(scalar), v.scalar(extra)
            if total is None or any(x is None for x in series.values()):
                rec.unavailable(ident, None, "AUDIT_TOTAL_OR_PERIOD_MISSING")
                rec.unavailable(fallback, None, "AUDIT_TOTAL_OR_PERIOD_MISSING")
            elif outside is None:
                rec.unavailable(ident, None, "NO_FINANCIAL_CLOSE_TERM_RECORDED")
                res = oracles.sum_of_periods(list(series.values()), total, tolerance=Decimal(0))
                rec.check(fallback, "total", Decimal(res.observed), Decimal(res.expected))
            else:
                res = oracles.sum_of_periods(list(series.values()) + [outside], total, tolerance=Decimal(0))
                rec.check(ident, "total", Decimal(res.observed), Decimal(res.expected))
                rec.unavailable(fallback, None, "FINANCIAL_CLOSE_TERM_IS_RECORDED_SEE_FULL_IDENTITY")
    capex, base = v.scalar("summary.total_capex_keur"), scalars["base_project_capex_keur"]
    if capex is None or base is None:
        rec.unavailable("CAPEX-LINK", None, "CAPEX_TOTAL_OR_BASE_MISSING")
    else:
        rec.check("CAPEX-LINK", "total", capex, base)
    facilities = [f for f in (v.fact("facilities") or []) if v.scalar(f"fac.{f}.commitment") is not None]
    commitments = [v.scalar(f"fac.{f}.commitment") for f in facilities]
    senior, junior = scalars["senior_debt_keur"], scalars["junior_or_other_keur"]
    if not facilities:
        for key in ("FUND-COMMITMENT", "FUND-FUNDED-OPENING", "FUND-IDC", "FUND-JUNIOR-IDC", "FUND-COMMITMENT-FEES",
                    "FUND-UPFRONT-FEES"):
            rec.unavailable(key, None, "NO_FACILITY_SCHEDULES_IN_THIS_CONFIGURATION")
    else:
        # Senior IDC is capitalised in Sources & Uses; a Junior facility's cash IDC has its own record (F3.8).
        senior_only = [f for f in facilities if f != "junior_facility"]
        for ident, name, target, members in (
                ("FUND-IDC", "construction_idc_total", "capitalized_idc_keur", senior_only),
                ("FUND-COMMITMENT-FEES", "commitment_fees_total", "commitment_fee_keur", facilities),
                ("FUND-UPFRONT-FEES", "upfront_fees_total", "structuring_fee_keur", facilities)):
            parts = [v.scalar(f"fac.{f}.{name}") for f in members]
            if scalars[target] is None or not parts or any(p is None for p in parts):
                rec.unavailable(ident, None, "FACILITY_CONSTRUCTION_VECTOR_OR_USE_MISSING")
            else:
                res = oracles.sum_of_periods(parts, scalars[target], tolerance=Decimal(0))
                rec.check(ident, "total", Decimal(res.observed), Decimal(res.expected))
        junior_idc, recorded = v.scalar("fac.junior_facility.construction_idc_total"), v.scalar("junior.cash_idc_total")
        if "junior_facility" not in facilities:
            rec.unavailable("FUND-JUNIOR-IDC", None, "NO_JUNIOR_FACILITY_IN_THIS_CONFIGURATION")
        elif junior_idc is None or recorded is None:
            rec.unavailable("FUND-JUNIOR-IDC", None, "JUNIOR_IDC_RECORD_MISSING")
        else:
            rec.check("FUND-JUNIOR-IDC", "total", junior_idc, recorded)
        if senior is None or junior is None:
            rec.unavailable("FUND-COMMITMENT", None, "SOURCES_EVIDENCE_MISSING")
        else:
            res = oracles.sum_of_periods(commitments, senior + junior, tolerance=Decimal(0))
            rec.check("FUND-COMMITMENT", "total", Decimal(res.observed), Decimal(res.expected))
        for f in facilities:
            draws, opening = v.scalar(f"fac.{f}.construction_draws_total"), v.series(f"fac.{f}.opening")
            first = None if not opening else next(iter(sorted(opening)), None)
            if draws is None or first is None or opening[first] is None:
                rec.unavailable("FUND-FUNDED-OPENING", f, "DRAWS_OR_OPENING_MISSING")
            else:
                rec.check("FUND-FUNDED-OPENING", f, opening[first], draws)


# ── Senior debt (full-precision Run Integrity evidence) ─────────────────────────────────────────────────────────
def _consecutive(v: View, keys: list[str]) -> dict[str, str | None]:
    """previous key on the statement axis, or None when the axis has a gap (never guessed)."""
    axis = [r["key"] for r in v.axis("statements")]
    position = {k: i for i, k in enumerate(axis)}
    prev: dict[str, str | None] = {}
    ordered = sorted(keys, key=lambda k: position.get(k, 10 ** 9))
    for earlier, later in zip(ordered, ordered[1:]):
        prev[later] = earlier if position.get(later, -2) == position.get(earlier, -5) + 1 else None
    return prev


def _senior(rec: Reconciler, v: View) -> None:
    spec = (("DEBT-ROLLFORWARD", "Closing = opening + draws (none in operation) - principal", BASIS_FULL, KEUR_FULL),
            ("DEBT-CHAIN", "Opening = previous closing", BASIS_FULL, KEUR_FULL),
            ("DEBT-SERVICE", "Debt service = interest + principal", BASIS_FULL, KEUR_FULL),
            ("DEBT-INTEREST", "Interest = opening x recorded rate x recorded day fraction", BASIS_FULL, KEUR_FULL),
            ("DEBT-NONNEGATIVE", "Closing balance is never negative", BASIS_FULL, KEUR_FULL),
            ("DEBT-FIRST-OPENING", "First opening = reported Senior debt", BASIS_FULL, KEUR_FULL),
            ("DEBT-PRINCIPAL-TOTAL", "Sum of principal + terminal closing = first opening", BASIS_FULL, KEUR_FULL),
            ("DEBT-DSCR", "Reported DSCR = base CFADS / debt service", BASIS_FULL, RATIO),
            ("DEBT-TOTAL-SERVICE", "Reported total Senior service = sum of scheduled debt service", BASIS_FULL, KEUR_FULL))
    for key, title, basis, pol in spec:
        rec.register(key, "debt", KIND_CALCULATION, title, basis, pol)
    for key, field, title in (("DEBT-STATEMENT-SERVICE", "senior_ds", "debt service"),
                              ("DEBT-STATEMENT-INTEREST", "senior_interest", "interest"),
                              ("DEBT-STATEMENT-PRINCIPAL", "senior_principal", "principal"),
                              ("DEBT-STATEMENT-BALANCE", "senior_balance", "closing balance")):
        rec.register(key, "debt", KIND_CALCULATION, f"Persisted debt schedule {title} (2dp) = recorded Senior evidence",
                     BASIS_2DP, KEUR_2DP)
    s = {n: v.series("ev.senior." + n) for n in ("opening", "interest", "principal", "closing", "debt_service",
                                                  "annual_rate", "day_fraction", "base_cfads", "reported_dscr")}
    if s["opening"] is None:
        for key, *_ in spec:
            rec.unavailable(key, None, "SENIOR_EVIDENCE_NOT_RECORDED")
        for key in ("DEBT-STATEMENT-SERVICE", "DEBT-STATEMENT-INTEREST", "DEBT-STATEMENT-PRINCIPAL",
                    "DEBT-STATEMENT-BALANCE"):
            rec.unavailable(key, None, "SENIOR_EVIDENCE_NOT_RECORDED")
        return
    keys = sorted(s["opening"], key=lambda k: [r["key"] for r in v.axis("statements")].index(k)
                  if k in [r["key"] for r in v.axis("statements")] else 10 ** 9)
    prev = _consecutive(v, keys)
    for key in keys:
        o, i, p, c, d = (s[n].get(key) if s[n] else None for n in ("opening", "interest", "principal", "closing",
                                                                    "debt_service"))
        if _all(o, p, c):
            res = oracles.debt_rollforward(o, 0, p, c, tolerance=Decimal(0))
            rec.check("DEBT-ROLLFORWARD", key, Decimal(res.observed), Decimal(res.expected))
        else:
            rec.unavailable("DEBT-ROLLFORWARD", key, "VALUE_MISSING")
        if c is None:
            rec.unavailable("DEBT-NONNEGATIVE", key, "VALUE_MISSING")
        else:
            rec.check("DEBT-NONNEGATIVE", key, min(c, Decimal(0)), Decimal(0))
        if _all(i, p, d):
            res = oracles.debt_service(i, p, d, tolerance=Decimal(0))
            rec.check("DEBT-SERVICE", key, Decimal(res.observed), Decimal(res.expected))
        else:
            rec.unavailable("DEBT-SERVICE", key, "VALUE_MISSING")
        rate, frac = (s[n].get(key) if s[n] else None for n in ("annual_rate", "day_fraction"))
        if _all(o, i, rate, frac):
            res = oracles.check("interest", i, o * rate * frac, tolerance=Decimal(0))
            rec.check("DEBT-INTEREST", key, Decimal(res.observed), Decimal(res.expected))
        else:
            rec.unavailable("DEBT-INTEREST", key, "RATE_OR_DAY_FRACTION_NOT_RECORDED")
        earlier = prev.get(key)
        if key == keys[0]:
            pass
        elif earlier is None:
            rec.not_comparable("DEBT-CHAIN", key, "PERIOD_GAP_ON_STATEMENT_AXIS")
        elif _all(o, s["closing"].get(earlier)):
            rec.check("DEBT-CHAIN", key, o, s["closing"][earlier])
        else:
            rec.unavailable("DEBT-CHAIN", key, "VALUE_MISSING")
        cfads, dscr = (s[n].get(key) if s[n] else None for n in ("base_cfads", "reported_dscr"))
        if d is not None and d > Decimal("1e-6"):
            if _all(cfads, dscr):
                res = oracles.dscr(cfads, d, dscr, tolerance=Decimal(0))
                rec.check("DEBT-DSCR", key, Decimal(res.observed), Decimal(res.expected))
            else:
                rec.unavailable("DEBT-DSCR", key, "CFADS_OR_DSCR_NOT_RECORDED")
    first = keys[0]
    commitment = v.scalar("summary.senior_debt_keur")
    config_authority = v.fact("financing_authority")
    if commitment is None or s["opening"].get(first) is None:
        rec.unavailable("DEBT-FIRST-OPENING", None, "SENIOR_DEBT_TOTAL_MISSING")
    elif config_authority == "F3_SINGLE_SENIOR_JUNIOR_EXPLICIT_V1":
        # With a controlled Junior the Senior facility alone is evidenced; the reported total spans both facilities.
        rec.not_comparable("DEBT-FIRST-OPENING", None, "REPORTED_SENIOR_TOTAL_SPANS_SENIOR_AND_JUNIOR")
    else:
        rec.check("DEBT-FIRST-OPENING", "total", s["opening"][first], commitment)
    last = keys[-1]
    if any(s[n] is None or any(x is None for x in s[n].values()) for n in ("principal", "closing")) \
            or s["opening"].get(first) is None:
        rec.unavailable("DEBT-PRINCIPAL-TOTAL", None, "VALUE_MISSING")
    else:
        res = oracles.sum_of_periods(list(s["principal"].values()) + [s["closing"][last]], s["opening"][first],
                                     tolerance=Decimal(0))
        rec.check("DEBT-PRINCIPAL-TOTAL", "total", Decimal(res.expected), Decimal(res.observed))
    total_ds = v.scalar("summary.total_senior_ds_keur")
    if config_authority == "F3_SINGLE_SENIOR_JUNIOR_EXPLICIT_V1":
        rec.not_comparable("DEBT-TOTAL-SERVICE", None, "REPORTED_SERVICE_SPANS_SENIOR_AND_JUNIOR")
    elif total_ds is None or s["debt_service"] is None or any(x is None for x in s["debt_service"].values()):
        rec.unavailable("DEBT-TOTAL-SERVICE", None, "VALUE_MISSING")
    else:
        res = oracles.sum_of_periods(list(s["debt_service"].values()), total_ds, tolerance=Decimal(0))
        rec.check("DEBT-TOTAL-SERVICE", "total", Decimal(res.observed), Decimal(res.expected))
    sched = {"DEBT-STATEMENT-SERVICE": ("debt.senior_ds", "debt_service"),
             "DEBT-STATEMENT-INTEREST": ("debt.senior_interest", "interest"),
             "DEBT-STATEMENT-PRINCIPAL": ("debt.senior_principal", "principal"),
             "DEBT-STATEMENT-BALANCE": ("debt.senior_balance", "closing")}
    for ident, (stmt_id, ev_name) in sched.items():
        stmt = v.series(stmt_id)
        if stmt is None:
            rec.unavailable(ident, None, "DEBT_SCHEDULE_NOT_PERSISTED")
            continue
        for key in keys:
            a, b = stmt.get(key), s[ev_name].get(key) if s[ev_name] else None
            if key not in stmt:
                rec.not_comparable(ident, key, "PERIOD_NOT_ON_PERSISTED_SCHEDULE")
            elif not _all(a, b):
                rec.unavailable(ident, key, "VALUE_MISSING")
            else:
                rec.check(ident, key, a, b, rounded_terms=_nonzero_terms(a))


# ── facilities (two Senior / controlled Senior + Junior) ───────────────────────────────────────────────────────
def _facilities(rec: Reconciler, v: View) -> None:
    for key, title in (("FAC-ROLLFORWARD", "Facility closing = opening - principal"),
                       ("FAC-CHAIN", "Facility opening = previous closing"),
                       ("FAC-SERVICE", "Facility debt service = interest + principal"),
                       ("FAC-NONNEGATIVE", "Facility closing balance is never negative"),
                       ("FAC-AGGREGATE-SENIOR", "Senior aggregate evidence = sum of the Senior facilities"),
                       ("FAC-JUNIOR-INTEREST", "Junior interest = opening x recorded rate x recorded day fraction"),
                       ("FAC-JUNIOR-INTEGRITY", "Junior facility schedule = Junior Run Integrity evidence"),
                       ("FAC-JUNIOR-CASH", "Cash after Junior = cash after Senior - Junior debt service")):
        rec.register(key, "debt", KIND_CALCULATION, title, BASIS_FULL, KEUR_FULL)
    facilities = list(v.fact("facilities") or [])
    if not facilities:
        for key in ("FAC-ROLLFORWARD", "FAC-CHAIN", "FAC-SERVICE", "FAC-NONNEGATIVE", "FAC-AGGREGATE-SENIOR",
                    "FAC-JUNIOR-INTEREST", "FAC-JUNIOR-INTEGRITY", "FAC-JUNIOR-CASH"):
            rec.unavailable(key, None, "NO_FACILITY_SCHEDULES_IN_THIS_CONFIGURATION")
        return
    axis = [r["key"] for r in v.axis("statements")]
    for f in facilities:
        f_series = {n: v.series(f"fac.{f}.{n}") for n in ("opening", "interest", "principal", "debt_service", "closing")}
        if any(x is None for x in f_series.values()):
            for key in ("FAC-ROLLFORWARD", "FAC-CHAIN", "FAC-SERVICE", "FAC-NONNEGATIVE"):
                rec.unavailable(key, f, "FACILITY_VECTOR_NOT_RECORDED")
            continue
        keys = sorted(f_series["opening"], key=lambda k: axis.index(k) if k in axis else 10 ** 9)
        prev = _consecutive(v, keys)
        for key in keys:
            tag = f"{f}@{key}"
            o, i, p, d, c = (f_series[n].get(key) for n in ("opening", "interest", "principal", "debt_service", "closing"))
            if _all(o, p, c):
                res = oracles.debt_rollforward(o, 0, p, c, tolerance=Decimal(0))
                rec.check("FAC-ROLLFORWARD", tag, Decimal(res.observed), Decimal(res.expected))
            else:
                rec.unavailable("FAC-ROLLFORWARD", tag, "VALUE_MISSING")
            if _all(i, p, d):
                res = oracles.debt_service(i, p, d, tolerance=Decimal(0))
                rec.check("FAC-SERVICE", tag, Decimal(res.observed), Decimal(res.expected))
            else:
                rec.unavailable("FAC-SERVICE", tag, "VALUE_MISSING")
            if c is None:
                rec.unavailable("FAC-NONNEGATIVE", tag, "VALUE_MISSING")
            else:
                rec.check("FAC-NONNEGATIVE", tag, min(c, Decimal(0)), Decimal(0))
            if key != keys[0]:
                earlier = prev.get(key)
                if earlier is None:
                    rec.not_comparable("FAC-CHAIN", tag, "PERIOD_GAP_ON_STATEMENT_AXIS")
                elif _all(o, f_series["closing"].get(earlier)):
                    rec.check("FAC-CHAIN", tag, o, f_series["closing"][earlier])
                else:
                    rec.unavailable("FAC-CHAIN", tag, "VALUE_MISSING")
    senior_ids = [f for f in facilities if f != "junior_facility"]
    agg = {n: v.series("ev.senior." + n) for n in ("opening", "interest", "principal", "closing", "debt_service")}
    members = [{n: v.series(f"fac.{f}.{n}") for n in agg} for f in senior_ids]
    if not senior_ids or any(x is None for x in agg.values()) or any(m[n] is None for m in members for n in agg):
        rec.unavailable("FAC-AGGREGATE-SENIOR", None, "SENIOR_AGGREGATE_OR_FACILITY_EVIDENCE_MISSING")
    else:
        for n in agg:
            for key, value in agg[n].items():
                parts = [m[n].get(key, Decimal(0)) if key in m[n] else None for m in members]
                # A facility that is not yet (or no longer) scheduled contributes nothing: the facility vector
                # simply has no row; that absence is explicit evidence of an inactive period, not a missing value.
                present = [p for p in parts if p is not None]
                if value is None or any(m[n].get(key) is None and key in m[n] for m in members):
                    rec.unavailable("FAC-AGGREGATE-SENIOR", f"{n}@{key}", "VALUE_MISSING")
                else:
                    rec.check("FAC-AGGREGATE-SENIOR", f"{n}@{key}", value, sum(present, Decimal(0)))
    junior = {n: v.series("ev.junior." + n) for n in ("opening", "interest", "principal", "closing", "debt_service",
                                                       "annual_rate", "day_fraction", "post_senior_cash",
                                                       "post_junior_cash")}
    jf = {n: v.series("fac.junior_facility." + n) for n in ("opening", "interest", "principal", "closing",
                                                              "debt_service")}
    if junior["opening"] is None or any(x is None for x in jf.values()):
        for key in ("FAC-JUNIOR-INTEREST", "FAC-JUNIOR-INTEGRITY", "FAC-JUNIOR-CASH"):
            rec.unavailable(key, None, "NO_JUNIOR_FACILITY_IN_THIS_CONFIGURATION")
        return
    for key, o in junior["opening"].items():
        i, rate, frac = (junior[n].get(key) for n in ("interest", "annual_rate", "day_fraction"))
        if _all(o, i, rate, frac):
            res = oracles.check("junior_interest", i, o * rate * frac, tolerance=Decimal(0))
            rec.check("FAC-JUNIOR-INTEREST", key, Decimal(res.observed), Decimal(res.expected))
        else:
            rec.unavailable("FAC-JUNIOR-INTEREST", key, "RATE_OR_DAY_FRACTION_NOT_RECORDED")
        for n in ("opening", "interest", "principal", "closing", "debt_service"):
            a, b = junior[n].get(key), jf[n].get(key)
            if _all(a, b):
                rec.check("FAC-JUNIOR-INTEGRITY", f"{n}@{key}", b, a)
            else:
                rec.unavailable("FAC-JUNIOR-INTEGRITY", f"{n}@{key}", "VALUE_MISSING")
        ps, pj, ds = (junior[n].get(key) for n in ("post_senior_cash", "post_junior_cash", "debt_service"))
        if _all(ps, pj, ds):
            res = oracles.cash_after_service(ps, ds, pj, tolerance=Decimal(0))
            rec.check("FAC-JUNIOR-CASH", key, Decimal(res.observed), Decimal(res.expected))
        else:
            rec.unavailable("FAC-JUNIOR-CASH", key, "JUNIOR_CASH_SEAM_NOT_RECORDED")


# ── statements / accounting identities ──────────────────────────────────────────────────────────────────────────
_BS_BASE = ("gross_fixed_assets", "accumulated_depreciation", "unrestricted_cash", "dsra_balance",
            "distribution_account", "senior_debt", "shl", "share_capital", "share_premium", "legal_reserve",
            "retained_earnings", "net_cit_payable")


def _statements(rec: Reconciler, v: View) -> None:
    rec.register("BS-IDENTITY", "statements", KIND_CALCULATION, "Assets = liabilities + equity (components recomputed)",
                 BASIS_FULL, KEUR_FULL)
    rec.register("STM-SENIOR-INTEREST", "statements", KIND_CALCULATION,
                 "P&L Senior interest expense (2dp) = recorded Senior interest", BASIS_2DP, KEUR_2DP)
    rec.register("STM-DEPRECIATION", "statements", KIND_CALCULATION,
                 "P&L depreciation (2dp) = change in recorded accumulated depreciation", BASIS_2DP, KEUR_2DP)
    bs = {n: v.series("ev.bs." + n) for n in _BS_BASE + ("additional_equity", "junior_debt")}
    authority = v.fact("financing_authority")
    f3 = authority in ("F3_TWO_SENIOR_EXPLICIT_COMMITMENTS_V1", "F3_SINGLE_SENIOR_JUNIOR_EXPLICIT_V1")
    junior = authority == "F3_SINGLE_SENIOR_JUNIOR_EXPLICIT_V1"
    if bs["gross_fixed_assets"] is None:
        rec.unavailable("BS-IDENTITY", None, "BALANCE_SHEET_EVIDENCE_NOT_RECORDED")
    else:
        for key in bs["gross_fixed_assets"]:
            vals = {n: (bs[n].get(key) if bs[n] else None) for n in bs}
            need = list(_BS_BASE) + (["additional_equity"] if f3 else []) + (["junior_debt"] if junior else [])
            if not _all(*(vals[n] for n in need)):
                rec.unavailable("BS-IDENTITY", key, "BALANCE_SHEET_COMPONENTS_INCOMPLETE")
                continue
            assets = vals["gross_fixed_assets"] - vals["accumulated_depreciation"] + vals["unrestricted_cash"] + \
                vals["dsra_balance"] + vals["distribution_account"]
            liabilities = vals["senior_debt"] + vals["shl"] + vals["share_capital"] + vals["share_premium"] + \
                vals["legal_reserve"] + vals["retained_earnings"] + vals["net_cit_payable"]
            if f3:
                liabilities += vals["additional_equity"]
            if junior:
                liabilities += vals["junior_debt"]
            res = oracles.balance_sheet(assets, liabilities, 0, tolerance=Decimal(0))
            rec.check("BS-IDENTITY", key, Decimal(res.observed), Decimal(res.expected))
    interest, pnl_int = v.series("ev.senior.interest"), v.series("stmt.pnl.senior_interest_expense")
    if interest is None or pnl_int is None:
        rec.unavailable("STM-SENIOR-INTEREST", None, "INTEREST_EVIDENCE_OR_STATEMENT_MISSING")
    else:
        for key, value in interest.items():
            stmt = pnl_int.get(key)
            if value is None or stmt is None:
                rec.unavailable("STM-SENIOR-INTEREST", key, "VALUE_MISSING")
            else:
                rec.check("STM-SENIOR-INTEREST", key, stmt, value, rounded_terms=_nonzero_terms(stmt))
    acc, dep = bs["accumulated_depreciation"], v.series("stmt.pnl.depreciation")
    if acc is None or dep is None:
        rec.unavailable("STM-DEPRECIATION", None, "DEPRECIATION_EVIDENCE_OR_STATEMENT_MISSING")
    else:
        keys = [r["key"] for r in v.axis("statements") if r["key"] in acc]
        for earlier, later in zip(keys, keys[1:]):
            a0, a1, d = acc.get(earlier), acc.get(later), dep.get(later)
            if not _all(a0, a1, d):
                rec.unavailable("STM-DEPRECIATION", later, "VALUE_MISSING")
            else:
                rec.check("STM-DEPRECIATION", later, d, a1 - a0, rounded_terms=_nonzero_terms(d))


# ── tax ────────────────────────────────────────────────────────────────────────────────────────────────────────
def _tax(rec: Reconciler, v: View) -> None:
    rec.register("TAX-TOTAL", "tax", KIND_CALCULATION, "Reported total tax = sum of persisted cash tax", BASIS_2DP,
                 KEUR_2DP)
    rec.register("TAX-CASH-LINK", "tax", KIND_CALCULATION, "Tax schedule cash tax = cash waterfall cash tax (2dp)",
                 BASIS_2DP, KEUR_2DP)
    rec.register("TAX-LOSS-USE", "tax", KIND_CALCULATION,
                 "Taxable profit after losses = taxable income before losses - losses used", BASIS_2DP, KEUR_2DP)
    cash, total = v.series("tax.corporate_tax_cash"), v.scalar("summary.total_tax_keur")
    if cash is None or total is None or any(x is None for x in cash.values()):
        rec.unavailable("TAX-TOTAL", None, "TAX_PERIODS_OR_TOTAL_MISSING")
    else:
        res = oracles.sum_of_periods(list(cash.values()), total, tolerance=Decimal(0))
        rec.check("TAX-TOTAL", "total", Decimal(res.expected), Decimal(res.observed),
                  rounded_terms=_nonzero_terms(*cash.values()))
    pf = v.series("stmt.pf.cash_tax")
    if cash is None or pf is None:
        rec.unavailable("TAX-CASH-LINK", None, "TAX_OR_CASH_WATERFALL_MISSING")
    else:
        for key, value in cash.items():
            other = pf.get(key)
            if value is None or other is None:
                rec.unavailable("TAX-CASH-LINK", key, "VALUE_MISSING")
            else:
                rec.check("TAX-CASH-LINK", key, value, other, rounded_terms=_nonzero_terms(value, other))
    before, used, after = (v.series("tax_audit." + n) for n in ("taxable_income_before_losses", "tax_loss_used",
                                                                 "taxable_profit_after_losses"))
    if None in (before, used, after) or not any(x is not None for x in after.values()):
        rec.unavailable("TAX-LOSS-USE", None, "TAX_AUDIT_FIELDS_NOT_PERSISTED")
    else:
        for key, a in after.items():
            b, u = before.get(key), used.get(key)
            if not _all(a, b, u):
                rec.unavailable("TAX-LOSS-USE", key, "VALUE_MISSING")
            else:
                rec.check("TAX-LOSS-USE", key, a, b - u, rounded_terms=_nonzero_terms(a, b, u))


# ── CFADS and cash waterfall ────────────────────────────────────────────────────────────────────────────────────
def _cash(rec: Reconciler, v: View) -> None:
    rec.register("CF-AFTER-SENIOR", "cfads_waterfall", KIND_CALCULATION,
                 "Cash after Senior = base CFADS - Senior debt service", BASIS_FULL, KEUR_FULL)
    rec.register("CF-STATEMENT-SERVICE", "cfads_waterfall", KIND_CALCULATION,
                 "Cash waterfall Senior service (2dp) = recorded debt service", BASIS_2DP, KEUR_2DP)
    rec.register("CF-STATEMENT-CFADS", "cfads_waterfall", KIND_CALCULATION,
                 "Cash waterfall FCF to banks (2dp) = recorded base CFADS", BASIS_2DP, KEUR_2DP)
    rec.register("CF-DISTRIBUTION-TOTAL", "cfads_waterfall", KIND_CALCULATION,
                 "Reported total distributions = sum of sponsor equity distributions", BASIS_FULL, KEUR_FULL)
    cfads, ds, after = (v.series(s) for s in ("ev.senior.base_cfads", "ev.senior.debt_service", "ev.cash.after_senior"))
    if None in (cfads, ds, after):
        rec.unavailable("CF-AFTER-SENIOR", None, "CASH_SEAM_EVIDENCE_NOT_RECORDED")
    else:
        for key, c in cfads.items():
            s_, a = ds.get(key), after.get(key)
            if not _all(c, s_, a):
                rec.unavailable("CF-AFTER-SENIOR", key, "VALUE_MISSING")
            else:
                res = oracles.cash_after_service(c, s_, a, tolerance=Decimal(0))
                rec.check("CF-AFTER-SENIOR", key, Decimal(res.observed), Decimal(res.expected))
    for ident, stmt_id, ev_series in (("CF-STATEMENT-SERVICE", "stmt.pf.senior_total_ds", ds),
                                      ("CF-STATEMENT-CFADS", "stmt.pf.fcf_banks", cfads)):
        stmt = v.series(stmt_id)
        if stmt is None or ev_series is None:
            rec.unavailable(ident, None, "STATEMENT_OR_EVIDENCE_MISSING")
            continue
        for key, value in ev_series.items():
            other = stmt.get(key)
            if key not in stmt:
                rec.not_comparable(ident, key, "PERIOD_NOT_ON_PERSISTED_STATEMENT")
            elif value is None or other is None:
                rec.unavailable(ident, key, "VALUE_MISSING")
            else:
                rec.check(ident, key, other, value, rounded_terms=_nonzero_terms(other))
    dist = v.series("ev.sponsor.legal_equity_distribution")
    total = v.scalar("summary.total_distributions_keur")
    if dist is None or total is None or any(x is None for x in dist.values()):
        rec.unavailable("CF-DISTRIBUTION-TOTAL", None, "DISTRIBUTIONS_OR_TOTAL_MISSING")
    else:
        res = oracles.sum_of_periods(list(dist.values()), total, tolerance=Decimal(0))
        rec.check("CF-DISTRIBUTION-TOTAL", "total", Decimal(res.observed), Decimal(res.expected))


# ── returns ────────────────────────────────────────────────────────────────────────────────────────────────────
def _returns(rec: Reconciler, v: View) -> None:
    rec.register("RET-FLOW-PURE", "returns", KIND_CALCULATION,
                 "Pure equity flow = distributions - equity contributions", BASIS_FULL, KEUR_FULL)
    rec.register("RET-FLOW-TOTAL", "returns", KIND_CALCULATION,
                 "Total sponsor flow = pure equity flow - SHL contributions + SHL interest + SHL principal",
                 BASIS_FULL, KEUR_FULL)
    rec.register("RET-XIRR-PURE", "returns", KIND_CALCULATION,
                 "Reported pure-equity XIRR = independent Decimal XIRR of the committed flows", BASIS_FULL, XIRR)
    rec.register("RET-XIRR-TOTAL", "returns", KIND_CALCULATION,
                 "Reported total-sponsor XIRR = independent Decimal XIRR of the committed flows", BASIS_FULL, XIRR)
    rec.register("RET-LINK", "returns", KIND_CALCULATION,
                 "Return metrics published twice in the Run agree", BASIS_FULL, XIRR)
    rec.register("RET-NPV", "returns", KIND_CALCULATION,
                 "Discounted cash flow identity (needs a persisted discount basis)", BASIS_FULL, KEUR_FULL)
    parts = {n: v.series("ev.sponsor." + n) for n in ("share_capital", "share_premium", "other_committed_equity",
                                                      "additional_equity", "shl_contribution", "shl_cash_interest",
                                                      "shl_principal", "legal_equity_distribution", "pure_equity_net",
                                                      "total_sponsor_net")}
    if any(x is None for x in parts.values()):
        for key in ("RET-FLOW-PURE", "RET-FLOW-TOTAL", "RET-XIRR-PURE", "RET-XIRR-TOTAL"):
            rec.unavailable(key, None, "SPONSOR_EVIDENCE_NOT_RECORDED")
    else:
        axis = v.axis("sponsor")
        dates = [r["key"] for r in axis]
        for key in dates:
            g = {n: parts[n].get(key) for n in parts}
            if not _all(*g.values()):
                rec.unavailable("RET-FLOW-PURE", key, "VALUE_MISSING")
                rec.unavailable("RET-FLOW-TOTAL", key, "VALUE_MISSING")
                continue
            contributions = g["share_capital"] + g["share_premium"] + g["other_committed_equity"] + g["additional_equity"]
            pure = g["legal_equity_distribution"] - contributions
            total = pure - g["shl_contribution"] + g["shl_cash_interest"] + g["shl_principal"]
            rec.check("RET-FLOW-PURE", key, g["pure_equity_net"], pure)
            rec.check("RET-FLOW-TOTAL", key, g["total_sponsor_net"], total)
        chronological = dates == sorted(dates)
        for ident, flow, metric in (("RET-XIRR-PURE", "pure_equity_net", "ret.pure_equity_xirr"),
                                    ("RET-XIRR-TOTAL", "total_sponsor_net", "ret.total_sponsor_xirr")):
            reported, status = v.scalar(metric), v.fact(metric + "_status")
            if not chronological:
                rec.not_comparable(ident, None, "SPONSOR_DATES_NOT_CHRONOLOGICAL")
            elif status != "OK" or reported is None:
                rec.unavailable(ident, None, f"RETURN_NOT_PUBLISHED_STATUS_{status}")
            elif any(parts[flow].get(k) is None for k in dates):
                rec.unavailable(ident, None, "FLOW_MISSING")
            else:
                recomputed = oracles.xirr([parts[flow][k] for k in dates], dates)
                if recomputed is None:
                    rec.unavailable(ident, None, "NO_INTERNAL_RATE_OF_RETURN_EXISTS")
                else:
                    rec.check(ident, None, reported, recomputed)
    links = (("project_irr_vs_xirr", "summary.project_irr", "sponsor.project_xirr"),
             ("equity_irr_vs_pure_equity_xirr", "summary.equity_irr", "ret.pure_equity_xirr"),
             ("total_sponsor_xirr_twice", "summary.total_sponsor_xirr", "ret.total_sponsor_xirr"))
    for name, left, right in links:
        a, b = v.scalar(left), v.scalar(right)
        if a is None or b is None:
            rec.unavailable("RET-LINK", name, "METRIC_NOT_PUBLISHED")
        else:
            rec.check("RET-LINK", name, a, b)
    npv = [v.scalar("summary.project_npv_keur"), v.scalar("summary.equity_npv_keur")]
    if all(x is None for x in npv):
        rec.unavailable("RET-NPV", None, "NPV_NOT_PUBLISHED_BY_THE_PERSISTED_RUN")
    else:
        rec.not_comparable("RET-NPV", None, "DISCOUNT_BASIS_NOT_PERSISTED")


def reconcile_bundle(bundle: Mapping[str, Any]) -> dict[str, Any]:
    """The reusable workflow: bundle in, deterministic reconciliation result out."""
    return build_reconciler(bundle).finalise()
