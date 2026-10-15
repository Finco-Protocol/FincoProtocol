"""WF-A bounded credit stress matrix and its directional expectations.

Expectations are derived from the product's sizing mechanics, stated per sizing mode, and never from "every ratio moves
with the shock":

* ``resized`` (``flat_dscr_sculpted`` + P50 lender case): debt is re-sized to CFADS capacity, so a CFADS shock moves the
  debt quantum and equity funding, while the sizing DSCR stays at the target.  Debt direction is NOT asserted for shocks
  that act through gearing x uses (CAPEX, rate via interest during construction).
* ``fixed`` (``gearing_cap``): debt is sized on cost, not on CFADS, so revenue and OPEX shocks leave debt and debt service
  unchanged and move coverage; this is the only product route that keeps a sized debt fixed under a CFADS shock.
* ``lender`` (P90-10y lender case): changes the sizing case only; the operating (P50) case is unchanged.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Any

from tests import wfa_cases as C
from tools.numerical_validation import credit_matrix as M

ZERO = Decimal(0)
# EBITDA / debt identities are full precision; the half-quantum is the persisted-2dp bound for rounded totals.
TOL = Decimal("1e-6")


def _cases(lab, kind: str, full: bool) -> dict[str, C.Case]:
    k = kind
    out: dict[str, C.Case] = {}

    def add(label, sizing, delta, setup=None):
        out[label] = C.build_case(lab, k, f"{k}-{label}", sizing, delta, setup)

    has_lender = k in ("solar", "wind")           # the lender case (P50/P90) exists only for the resource technologies
    LC = C.lender if has_lender else (lambda _name: (lambda record, bank: {}))
    add("R0", "dscr", "baseline, DSCR-sized" + (", P50 lender case" if has_lender else ""), LC("P_50"))
    if has_lender:                                 # generation hours exist only for the resource technologies
        add("R-hours-30", "dscr", "P50 generation hours -30%", C.combine(LC("P_50"), C.hours(.7)))
    add("F0", "fixed", "baseline, GEARING_CAP (debt sized on cost)")
    if has_lender:
        add("F-hours-30", "fixed", "P50 generation hours -30%", C.hours(.7))
    else:                                          # CAPEX / OPEX contingency are the released stress routes for these verticals
        add("R-capex+10", "dscr", "CAPEX contingency +10%", C.capex(10))
        add("R-opex+50", "dscr", "OPEX contingency +50%", C.opex(50))
        add("F-opex+50", "fixed", "OPEX contingency +50%", C.opex(50))
    if has_lender:
        add("L-P90", "dscr", "P90-10y lender case vs P50", LC("P90-10y"))
    if not full:
        return out
    add("R-tariff-30", "dscr", "contracted price -30%", C.combine(LC("P_50"), C.tariff(.7)))
    if has_lender:
        add("R-capex+10", "dscr", "CAPEX contingency +10%", C.combine(LC("P_50"), C.capex(10)))
        add("R-opex+50", "dscr", "OPEX contingency +50%", C.combine(LC("P_50"), C.opex(50)))
    add("R-rate-5.5", "dscr", "explicit all-in rate 5.50% (control for the explicit schedule route)",
        C.combine(LC("P_50"), C.rate(5.5)))
    add("R-rate-6.5", "dscr", "all-in rate +100 bp", C.combine(LC("P_50"), C.rate(6.5)))
    add("R-combined", "dscr", "combined downside: hours -20%, price -20%, CAPEX +5%, OPEX +20%, rate +100 bp",
        C.combine(LC("P_50"), C.hours(.8), C.tariff(.8), C.capex(5), C.opex(20), C.rate(6.5)))
    add("R-tenor-10", "dscr", "short Senior tenor (10 years)", C.combine(LC("P_50"), C.tenor(10)))
    add("R-tenor-18", "dscr", "long Senior tenor (18 years)", C.combine(LC("P_50"), C.tenor(18)))
    add("F-tariff-30", "fixed", "contracted price -30%", C.tariff(.7))
    add("F-capex+10", "fixed", "CAPEX contingency +10%", C.capex(10))
    add("F-opex+50", "fixed", "OPEX contingency +50%", C.opex(50))
    add("F-rate-5.5", "fixed", "explicit all-in rate 5.50% (control)", C.rate(5.5))
    add("F-rate-6.5", "fixed", "all-in rate +100 bp", C.rate(6.5))
    add("F-combined", "fixed", "combined downside: hours -20%, price -20%, CAPEX +5%, OPEX +20%, rate +100 bp",
        C.combine(C.hours(.8), C.tariff(.8), C.capex(5), C.opex(20), C.rate(6.5)))
    add("L-P90-price-10", "dscr", "P90 lender case with price -10%", C.combine(LC("P90-10y"), C.tariff(.9)))
    add("L-P90-rate-6.5", "dscr", "P90 lender case with rate +100 bp", C.combine(LC("P90-10y"), C.rate(6.5)))
    add("L-downside", "dscr", "combined lender downside: P90, price -10%, CAPEX +5%, rate +100 bp",
        C.combine(LC("P90-10y"), C.tariff(.9), C.capex(5), C.rate(6.5)))
    # near-boundary debt capacity: the tenor-10 DSCR capacity sits at gearing ~0.674; cap just below / just above it
    add("B-below", "combined", "tenor 10, gearing cap 67.0% (just BELOW DSCR capacity)", C.combine(C.tenor(10), C.gearing(67.0)))
    add("B-above", "combined", "tenor 10, gearing cap 67.5% (just ABOVE DSCR capacity)", C.combine(C.tenor(10), C.gearing(67.5)))
    # low / near-zero CFADS: expected to fail closed
    add("Z-price-85", "dscr", "contracted price -85% (near-zero CFADS)", C.combine(LC("P_50"), C.tariff(.15)))
    add("Z-price-98", "dscr", "contracted price -98% (CFADS below debt service)", C.combine(LC("P_50"), C.tariff(.02)))
    return out


def _m(case: C.Case, name: str) -> Decimal | None:
    return case.metrics.get(name) if case.committed else None


def directionals(cases: dict[str, C.Case], kind: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []

    def d(name, expectation, a, b, metric, relation, basis, tol=TOL):
        if a not in cases or b not in cases:
            return
        rows.append(M.directional(f"{kind}: {name}", expectation, a, _m(cases[a], metric), b, _m(cases[b], metric),
                                  relation, tolerance=tol, basis=basis))

    fixed_hold = "GEARING_CAP sizes on cost, not CFADS: a revenue shock cannot change the sized debt"
    for shock in ("hours-30", "tariff-30", "opex+50"):
        b = f"F-{shock}"
        d(f"fixed debt unchanged under {shock}", "debt quantum unchanged", "F0", b, "senior_debt", "unchanged", fixed_hold)
        d(f"fixed debt service unchanged under {shock}", "total Senior service unchanged", "F0", b, "total_service", "unchanged", fixed_hold)
        d(f"fixed minimum DSCR under {shock}", "minimum DSCR falls", "F0", b, "min_dscr", "decreases", "same debt service on lower CFADS")
        d(f"fixed lock-up periods under {shock}", "lock-up periods do not fall", "F0", b, "lockup_periods", "not_below", "lower DSCR cannot reduce lock-up")
        d(f"fixed EBITDA under {shock}", "EBITDA falls", "F0", b, "total_ebitda", "decreases", "shock acts on revenue / OPEX")
    d("fixed capex+10 raises debt", "debt quantum rises (gearing x uses)", "F0", "F-capex+10", "senior_debt", "increases", "gearing cap on larger uses")
    d("fixed capex+10 raises equity funding", "equity funding rises", "F0", "F-capex+10", "equity_funding", "increases", "uses rise")
    d("fixed capex+10 lowers coverage", "minimum DSCR falls", "F0", "F-capex+10", "min_dscr", "decreases", "more debt on the same CFADS")
    d("fixed rate control", "explicit 5.50% schedule equals the default 5.50% case", "F0", "F-rate-5.5", "senior_debt", "unchanged", "route control")
    d("fixed rate+100bp raises interest", "total interest rises", "F-rate-5.5", "F-rate-6.5", "total_interest", "increases", "higher rate on the same debt")
    d("fixed rate+100bp raises service", "total Senior service rises", "F-rate-5.5", "F-rate-6.5", "total_service", "increases", "higher rate on the same debt")
    d("fixed rate+100bp lowers coverage", "minimum DSCR falls", "F-rate-5.5", "F-rate-6.5", "min_dscr", "decreases", "higher service on the same CFADS")
    d("fixed combined downside lowers coverage", "minimum DSCR falls", "F0", "F-combined", "min_dscr", "decreases", "combined shocks")

    for shock in ("hours-30",):
        b = f"R-{shock}"
        d(f"resized debt shrinks under {shock}", "re-sized debt quantum falls", "R0", b, "senior_debt", "decreases", "debt capacity = PV(CFADS / target)")
        d(f"resized EBITDA under {shock}", "EBITDA falls", "R0", b, "total_ebitda", "decreases", "shock acts on revenue")
    conditional_debt(rows, kind, cases, "resized price-30", "R0", "R-tariff-30")
    conditional_debt(rows, kind, cases, "resized hours-30", "R0", "R-hours-30")
    conditional_debt(rows, kind, cases, "resized combined downside", "R0", "R-combined")
    explained_uses(rows, kind, cases, "R0", ("R-hours-30", "R-tariff-30", "R-combined", "R-rate-6.5", "R-opex+50", "L-P90"))
    d("resized capex+10 raises uses and equity", "equity funding rises", "R0", "R-capex+10", "equity_funding", "increases", "uses rise")
    d("resized opex+50 lowers EBITDA", "EBITDA falls", "R0", "R-opex+50", "total_ebitda", "decreases", "OPEX shock")
    d("resized rate control", "explicit 5.50% schedule equals the default case", "R0", "R-rate-5.5", "senior_debt", "unchanged", "route control")
    d("resized rate+100bp raises interest", "total interest rises", "R-rate-5.5", "R-rate-6.5", "total_interest", "increases", "higher rate")
    d("resized combined downside lowers EBITDA", "EBITDA falls", "R0", "R-combined", "total_ebitda", "decreases", "combined shocks")
    d("resized tenor 10 vs 18 debt capacity", "a longer tenor does not reduce debt capacity", "R-tenor-10", "R-tenor-18", "senior_debt", "not_below", "more CFADS periods")
    for label in ("R0", "R-hours-30", "R-tariff-30", "R-capex+10", "R-opex+50", "R-rate-6.5", "R-combined", "R-tenor-10", "R-tenor-18"):
        if label in cases and cases[label].committed:
            rows.append(M.directional(f"{kind}: {label} sizing DSCR holds the target",
                                      "minimum sizing DSCR is not below the sizing target (constraint satisfied)",
                                      "target", sizing_target_decimal(cases[label]), label, _m(cases[label], "min_sizing_dscr"),
                                      "not_below", tolerance=Decimal("1e-7"), basis="DSCR-sized debt is constrained by target x availability"))
    d("P90 lender case does not enlarge debt", "P90 debt quantum is not above P50", "R0", "L-P90", "senior_debt", "not_above", "lower sizing CFADS")
    d("lender case leaves the operating case unchanged", "EBITDA identical under P50 and P90 lender cases", "R0", "L-P90", "total_ebitda", "unchanged", "lender case changes sizing only")
    d("P90 keeps base coverage at or above P50", "base minimum DSCR not below P50 case", "R0", "L-P90", "min_dscr", "not_below", "P50 operating cash on smaller debt")
    d("P90 + price-10 lowers EBITDA", "EBITDA falls", "L-P90", "L-P90-price-10", "total_ebitda", "decreases", "price shock")
    conditional_debt(rows, kind, cases, "P90 + price-10", "L-P90", "L-P90-price-10")
    explained_uses(rows, kind, cases, "L-P90", ("L-P90-price-10", "L-P90-rate-6.5", "L-downside"))
    d("P90 + rate+100bp raises interest", "total interest rises", "L-P90", "L-P90-rate-6.5", "total_interest", "increases", "higher rate")
    d("lender combined downside lowers EBITDA", "EBITDA falls", "L-P90", "L-downside", "total_ebitda", "decreases", "price shock")
    return rows


def conditional_debt(rows, kind, cases, name, a, b):
    """Debt direction is asserted ONLY where the modified case is DSCR-bound.  Where the gearing cap binds, debt is
    gearing x uses and uses move with financing items (initial DSRA, IDC, fees), so a falling CFADS can raise debt: that is
    a documented product mechanic, reported NOT_ASSERTED with its proof (see explained_uses), never a false monotonicity."""
    if a not in cases or b not in cases or not (cases[a].committed and cases[b].committed):
        return
    binding = cases[b].credit["diagnostics"]["binding_constraint"]
    if binding == "DSCR":
        rows.append(M.directional(f"{kind}: {name}: debt falls when DSCR capacity binds", "re-sized debt quantum falls",
                                  a, _m(cases[a], "senior_debt"), b, _m(cases[b], "senior_debt"), "decreases",
                                  tolerance=TOL, basis="debt capacity = PV(CFADS / target) when DSCR binds"))
    else:
        rows.append({"check": f"{kind}: {name}: debt direction", "expectation": "not asserted: the gearing cap binds",
                     "basis": "debt = gearing x total uses; uses move with initial DSRA, IDC and fees", "from_case": a, "to_case": b,
                     "relation": "not_asserted", "tolerance": "", "from_value": _fmt(_m(cases[a], "senior_debt")),
                     "to_value": _fmt(_m(cases[b], "senior_debt")), "signed_difference": _fmt(_diff(cases[a], cases[b], "senior_debt")),
                     "result": "NOT_ASSERTED", "action": ""})


def explained_uses(rows, kind, cases, a, bs):
    """The change in total uses is fully explained by the change in financing items (base CAPEX unchanged)."""
    for b in bs:
        if a not in cases or b not in cases or not (cases[a].committed and cases[b].committed):
            continue
        ca, cb = cases[a], cases[b]
        need = ("total_uses", "base_capex", "idc", "financing_fees", "initial_dsra")
        if any(ca.metrics.get(n) is None or cb.metrics.get(n) is None for n in need):
            rows.append(M.directional(f"{kind}: {b}: uses change explained by financing items", "", a, None, b, None, "unchanged"))
            continue
        d = {n: cb.metrics[n] - ca.metrics[n] for n in need}
        unexplained = d["total_uses"] - d["idc"] - d["financing_fees"] - d["initial_dsra"] - d["base_capex"]
        row = M.directional(f"{kind}: {b}: uses change explained by financing items (+CAPEX)",
                            "change in total uses = change in (CAPEX + IDC + fees + initial DSRA); nothing unexplained",
                            a, Decimal(0), b, unexplained, "unchanged", tolerance=Decimal("1e-6"),
                            basis="Sources & Uses decomposition from full-precision evidence")
        row["components"] = {k: _fmt(v) for k, v in sorted(d.items())}
        rows.append(row)


def _fmt(v):
    return None if v is None else format(v, "f")


def _diff(ca, cb, name):
    x, y = ca.metrics.get(name), cb.metrics.get(name)
    return None if x is None or y is None else y - x


def sizing_target_decimal(case: C.Case) -> Decimal | None:
    return C.sizing_target(case)


def boundary_rows(cases: dict[str, C.Case]) -> list[dict[str, Any]]:
    """Binding-constraint flips either side of the DSCR capacity (CR-BINDING must follow the evidence)."""
    rows = []
    for label in ("B-below", "B-above"):
        c = cases.get(label)
        if c and c.committed:
            diag = c.credit["diagnostics"]["binding_constraint"]
            rows.append({"case": label, "binding": diag, "gearing": c.metrics["gearing"],
                         "cr_binding": next(r["verdict"] for r in c.result["by_identity"] if r["identity"] == "CR-BINDING")})
    return rows


def assemble(cases: dict[str, C.Case], kind: str):
    committed = [c for c in cases.values() if c.committed]
    case_rows = [{"case": c.label, "run_key": c.result["identity"]["run_key"],
                  "rows": M.metric_rows(c.label, c.result, delta=c.delta, configuration=c.configuration),
                  "assessment": c.result["credit_assessment"]["items"]} for c in committed]
    none = [{"case": c.label, "assumption_delta": c.delta, "reason": c.reason} for c in cases.values() if not c.committed]
    return M.build(case_rows, directionals(cases, kind), none)
