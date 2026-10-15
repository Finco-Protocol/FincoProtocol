"""WF-A Addendum A: independent expectation identities for Add Debt, Add Equity / Investor Agreement and PPA effects.

These identities answer a different question from F3.9: not "is the persisted Run internally consistent?" but "did the
change the user DECLARED reach the committed Run, and does every figure the product recorded equal an independent
Decimal recomputation from that declared change?".  The declared change is a typed input (a saved F3 proposal, a revenue
contract book, an investor agreement).  It is recorded and hashed with the evidence, never inferred from outputs.

Read-only and additive: no production import, no model run, no repair, no fitted residual, and absent evidence stays
UNAVAILABLE.  Three families:

* ``FT-*`` facility terms: dated draws, IDC, upfront / commitment fees, operating interest, level / bullet repayment
  profile with grace, maturity.  The independent schedule is built from the declared terms only.
* ``RC-*`` revenue contracts: contract price timeline (fixed, operating-year indexed, explicit period curve), volume
  allocation (share, residual merchant), contract window / expiry and no double-counted energy.
* ``IV-*`` investor allocation: per-investor distributions equal ownership x approved net equity receipts, the sum equals
  the approved distributable total, paid-in equals the declared contributions, MOIC / DPI and an independent dated XIRR.
"""
from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from datetime import date, timedelta
from decimal import Decimal, localcontext
from typing import Any

from .credit import _plain
from .evidence import dec
from .identities import KEUR_FULL, RATIO, XIRR, View, build_reconciler
from .periodic import BASIS_FULL, KIND_CALCULATION, KIND_INPUT
from .reconcile import ReconciliationInputError, canonical_bytes

SCHEMA = "FINCO_IMPACT_EVIDENCE_V1"
DAY_COUNT_BASIS = {"ACT_360": Decimal(360), "ACT_365": Decimal(365)}
PRICE_POLICY = RATIO          # EUR/MWh prices are recorded at full precision; the approved ratio tolerance bounds them


def _iso(value: Any) -> date | None:
    try:
        return date.fromisoformat(value) if isinstance(value, str) else None
    except ValueError:
        return None


def impact_evidence_from_entry(entry: Any, bundle: Mapping[str, Any], *, facilities: Sequence[Mapping[str, Any]] | None = None,
                               contracts: Mapping[str, Any] | None = None,
                               agreement: Mapping[str, Any] | None = None) -> dict:
    """Read-only evidence of what the Run recorded for the DECLARED facilities / contracts / agreement.

    ``facilities`` is the saved F3 proposal's instruments (``collection.to_dict()['instruments']``), ``contracts`` the
    revenue contract book payload, ``agreement`` the investor agreement document.  They are declared inputs: hashed,
    recorded as such, and never treated as Run output.
    """
    summary = _plain(getattr(entry, "runtime_summary", None) or {})
    fe = summary.get("financing_evidence") if isinstance(summary.get("financing_evidence"), Mapping) else {}
    construction = (fe.get("construction_funding") or {}).get("periods") if isinstance(fe.get("construction_funding"), Mapping) else None
    schedules = fe.get("facility_schedules") if isinstance(fe.get("facility_schedules"), list) else None
    investors = summary.get("investor_waterfall_v1") if isinstance(summary.get("investor_waterfall_v1"), Mapping) else None
    sponsor = _plain(getattr(entry, "sponsor_schedule", None) or {})
    body = {
        "schema": SCHEMA,
        "identity": {k: bundle["identity"][k] for k in ("run_key", "composite_hash", "snapshot_id", "project_key")},
        "declared": {"source": "DECLARED_BY_CALLER_NOT_A_RUN_OUTPUT", "facilities": _plain(facilities) if facilities is not None else None,
                     "contracts": _plain(contracts) if contracts is not None else None,
                     "agreement": _plain(agreement) if agreement is not None else None},
        "recorded": {
            "construction_periods": [{"start": p.get("period_start"), "end_exclusive": p.get("period_end")}
                                     for p in (construction or []) if isinstance(p, Mapping)] if construction else None,
            "facilities": {s["instrument_id"]: {k: [dec(x) for x in s.get(k) or []] for k in (
                "construction_draws_keur", "construction_idc_keur", "construction_commitment_fees_keur", "upfront_fees_keur")}
                | {"commitment": dec(s.get("commitment_keur"))}
                for s in (schedules or []) if isinstance(s, Mapping) and isinstance(s.get("instrument_id"), str)} if schedules else None,
            "investors": investors,
            "sponsor_summary": {k: dec(v) for k, v in (sponsor.get("summary") or {}).items() if isinstance(v, (int, float))}
            if isinstance(sponsor.get("summary"), Mapping) else None,
        },
    }
    body["sha256"] = hashlib.sha256(canonical_bytes({k: v for k, v in body.items() if k != "sha256"})).hexdigest()
    return body


def verify_impact_binding(bundle: Mapping[str, Any], evidence: Mapping[str, Any]) -> list[str]:
    problems = [] if evidence.get("schema") == SCHEMA else ["IMPACT_SCHEMA_MISMATCH"]
    for key in ("run_key", "composite_hash", "snapshot_id", "project_key"):
        if (evidence.get("identity") or {}).get(key) != bundle["identity"].get(key):
            problems.append(f"IDENTITY_MISMATCH_{key}")
    if hashlib.sha256(canonical_bytes({k: v for k, v in evidence.items() if k != "sha256"})).hexdigest() != evidence.get("sha256"):
        problems.append("IMPACT_EVIDENCE_HASH_MISMATCH")
    return problems


# ───────────────────────────────────────────── facility terms ─────────────────────────────────────────────
FACILITY_IDENTITIES = (
    ("FT-DRAWS", "capex_funding", KIND_INPUT, "Recorded dated construction draws = the declared drawdowns mapped to construction periods"),
    ("FT-IDC", "capex_funding", KIND_CALCULATION, "Construction IDC = independent accrual of each dated draw to period end (rate, day count)"),
    ("FT-COMMITMENT-FEE", "capex_funding", KIND_CALCULATION, "Commitment fee = rate x undrawn integral (independent)"),
    ("FT-UPFRONT", "capex_funding", KIND_CALCULATION, "Upfront fee = declared rate x commitment, in the first construction period only"),
    ("FT-INTEREST", "debt", KIND_CALCULATION, "Operating interest = opening x DECLARED rate x recorded day fraction"),
    ("FT-REPAYMENT", "debt", KIND_CALCULATION, "Principal profile = independent level / bullet schedule from declared grace and maturity"),
    ("FT-MATURITY", "debt", KIND_CALCULATION, "The facility is scheduled to, and settles at, the declared maturity date"),
)


def _facility_declared(declared: Sequence[Mapping[str, Any]]) -> dict[str, dict[str, Any]]:
    out = {}
    for ins in declared:
        fid = ins.get("instrument_id")
        if not isinstance(fid, str):
            continue
        fees = {f.get("kind"): Decimal(str(f.get("rate"))) for f in ins.get("fees") or [] if isinstance(f, Mapping)}
        out[fid] = {
            "commitment": Decimal(str(ins["commitment_keur"])), "rate": Decimal(str((ins.get("interest") or {}).get("fixed_rate"))),
            "mode": (ins.get("repayment") or {}).get("mode"), "grace": int((ins.get("repayment") or {}).get("grace_months") or 0),
            "maturity": _iso((ins.get("repayment") or {}).get("maturity_date")),
            "draws": [(_iso(d.get("draw_date")), Decimal(str(d.get("amount_keur")))) for d in ins.get("drawdowns") or []],
            "upfront": fees.get("UPFRONT", Decimal(0)), "commitment_fee": fees.get("COMMITMENT", Decimal(0)),
            "interest_mode": (ins.get("interest") or {}).get("mode"),
        }
    return out


def _months(a: date, b: date) -> int:
    return (b.year - a.year) * 12 + (b.month - a.month)


def _add_months(d: date, months: int) -> date:
    y, m = divmod(d.month - 1 + months, 12)
    year, month = d.year + y, m + 1
    day = min(d.day, [31, 29 if year % 4 == 0 and (year % 100 or year % 400 == 0) else 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31][month - 1])
    return date(year, month, day)


def register_facilities(rec: Any, v: View, impact: Mapping[str, Any]) -> None:
    for key, stage, kind, title in FACILITY_IDENTITIES:
        rec.register(key, stage, kind, title, BASIS_FULL, KEUR_FULL if key != "FT-INTEREST" else KEUR_FULL)
    problems = verify_impact_binding(v.b, impact)
    declared = impact["declared"]["facilities"]
    if problems:
        for key, *_ in FACILITY_IDENTITIES:
            rec.not_comparable(key, None, "IMPACT_EVIDENCE_NOT_BOUND_TO_RUN:" + "+".join(problems))
        return
    if declared is None:
        for key, *_ in FACILITY_IDENTITIES:
            rec.unavailable(key, None, "NO_FACILITY_TERMS_DECLARED")
        return
    recorded = impact["recorded"]["facilities"]
    periods = impact["recorded"]["construction_periods"]
    basis = DAY_COUNT_BASIS.get(v.fact("day_count") if isinstance(v.fact("day_count"), str) else "")
    terms = _facility_declared(declared)
    if recorded is None or periods is None or basis is None:
        for key in ("FT-DRAWS", "FT-IDC", "FT-COMMITMENT-FEE", "FT-UPFRONT"):
            rec.unavailable(key, None, "CONSTRUCTION_EVIDENCE_OR_DAY_COUNT_NOT_RECORDED")
    else:
        bounds = [(_iso(p["start"]), _iso(p["end_exclusive"])) for p in periods]
        if any(None in b for b in bounds):
            for key in ("FT-DRAWS", "FT-IDC", "FT-COMMITMENT-FEE", "FT-UPFRONT"):
                rec.not_comparable(key, None, "CONSTRUCTION_PERIOD_BOUNDS_NOT_ISO_DATES")
        else:
            for fid, t in sorted(terms.items()):
                got = recorded.get(fid)
                if got is None or t["interest_mode"] != "FIXED":
                    for key in ("FT-DRAWS", "FT-IDC", "FT-COMMITMENT-FEE", "FT-UPFRONT"):
                        rec.unavailable(key, fid, "FACILITY_NOT_RECORDED_OR_RATE_MODE_NOT_FIXED")
                    continue
                _construction_checks(rec, fid, t, got, bounds, basis)
    _operating_checks(rec, v, terms)


def _construction_checks(rec: Any, fid: str, t: Mapping[str, Any], got: Mapping[str, Any],
                         bounds: list[tuple[date, date]], basis: Decimal) -> None:
    opening = Decimal(0)
    for k, (start, end_excl) in enumerate(bounds):
        tag = f"{fid}#{k + 1}"
        entries = [(d, a) for d, a in t["draws"] if d is not None and start <= d < end_excl]
        dcf = Decimal((end_excl - start).days) / basis
        drawn = sum((a for _d, a in entries), Decimal(0))
        accrued = opening * t["rate"] * dcf + sum((a * t["rate"] * Decimal((end_excl - d).days) / basis for d, a in entries), Decimal(0))
        undrawn = (t["commitment"] - opening) * dcf - sum((a * Decimal((end_excl - d).days) / basis for d, a in entries), Decimal(0))
        upfront = t["upfront"] * t["commitment"] if k == 0 else Decimal(0)
        for key, vector, expected in (("FT-DRAWS", "construction_draws_keur", drawn), ("FT-IDC", "construction_idc_keur", accrued),
                                      ("FT-COMMITMENT-FEE", "construction_commitment_fees_keur", t["commitment_fee"] * undrawn),
                                      ("FT-UPFRONT", "upfront_fees_keur", upfront)):
            values = got.get(vector) or []
            value = None if k >= len(values) or values[k] is None else Decimal(values[k])
            if value is None:
                rec.unavailable(key, tag, "RECORDED_CONSTRUCTION_VALUE_MISSING")
            else:
                rec.check(key, tag, value, expected)
        opening += drawn
    mapped = sum((a for d, a in t["draws"] if d is not None and any(s <= d < e for s, e in bounds)), Decimal(0))
    declared_total = sum((a for _d, a in t["draws"]), Decimal(0))
    if mapped != declared_total:
        rec.not_comparable("FT-DRAWS", f"{fid}#outside", "DECLARED_DRAW_OUTSIDE_RECORDED_CONSTRUCTION_PERIODS")


def _operating_checks(rec: Any, v: View, terms: Mapping[str, Mapping[str, Any]]) -> None:
    axis = v.axis("statements")
    day_fraction = v.series("ev.senior.day_fraction")
    ordered = [r["key"] for r in axis]
    phase = {r["key"]: r["phase"] for r in axis}
    ops = [k for k in ordered if phase[k] == "operation"]
    construction_keys = [k for k in ordered if phase[k] == "construction"]
    for fid, t in sorted(terms.items()):
        f = {n: v.series(f"fac.{fid}.{n}") for n in ("opening", "interest", "principal", "closing")}
        if any(x is None for x in f.values()) or not f["opening"]:
            for key in ("FT-INTEREST", "FT-REPAYMENT", "FT-MATURITY"):
                rec.unavailable(key, fid, "FACILITY_VECTORS_NOT_RECORDED")
            continue
        keys = [k for k in ordered if k in f["opening"]]
        for key in keys:
            o, i = f["opening"].get(key), f["interest"].get(key)
            frac = None if day_fraction is None else day_fraction.get(key)
            if None in (o, i, frac) or t["interest_mode"] != "FIXED":
                rec.unavailable("FT-INTEREST", f"{fid}@{key}", "OPENING_INTEREST_OR_DAY_FRACTION_NOT_RECORDED")
            else:
                rec.check("FT-INTEREST", f"{fid}@{key}", i, o * t["rate"] * frac)
        # period starts (engine convention): the first operating period starts on the last construction cash date and every
        # later one on the previous period's end date (end-exclusive boundaries)
        if not construction_keys or not ops or t["maturity"] is None:
            rec.not_comparable("FT-REPAYMENT", fid, "OPERATING_PERIOD_STARTS_OR_MATURITY_NOT_PROVABLE")
            rec.not_comparable("FT-MATURITY", fid, "OPERATING_PERIOD_STARTS_OR_MATURITY_NOT_PROVABLE")
            continue
        first_start = _iso(construction_keys[-1])
        starts = {}
        for n, key in enumerate(ops):
            starts[key] = first_start if n == 0 else _iso(ops[n - 1])
        maturity_key = t["maturity"].isoformat()
        if maturity_key not in starts:
            rec.not_comparable("FT-MATURITY", fid, "DECLARED_MATURITY_IS_NOT_AN_OPERATING_PERIOD_END")
            rec.not_comparable("FT-REPAYMENT", fid, "DECLARED_MATURITY_IS_NOT_AN_OPERATING_PERIOD_END")
            continue
        scheduled = [k for k in ops if k <= maturity_key]
        grace_end = _add_months(starts[ops[0]], t["grace"])
        eligible = [k for k in scheduled if starts[k] >= grace_end]
        if not eligible:
            rec.not_comparable("FT-REPAYMENT", fid, "NO_PERIOD_AFTER_GRACE")
            continue
        commitment = t["commitment"]
        for key in scheduled:
            actual = f["principal"].get(key)
            if t["mode"] == "LEVEL_PRINCIPAL":
                expected = commitment / Decimal(len(eligible)) if key in eligible else Decimal(0)
            elif t["mode"] == "BULLET":
                expected = commitment if key == maturity_key else Decimal(0)
            else:
                rec.not_comparable("FT-REPAYMENT", f"{fid}@{key}", f"REPAYMENT_MODE_{t['mode']}_HAS_NO_INDEPENDENT_PROFILE")
                continue
            if actual is None:
                rec.unavailable("FT-REPAYMENT", f"{fid}@{key}", "PRINCIPAL_NOT_RECORDED")
            else:
                rec.check("FT-REPAYMENT", f"{fid}@{key}", actual, expected)
        last_recorded = keys[-1] if keys else None
        rec.check("FT-MATURITY", f"{fid}:last_scheduled_period", Decimal(0 if last_recorded == maturity_key else 1), Decimal(0))
        closing = f["closing"].get(maturity_key)
        if closing is None:
            rec.unavailable("FT-MATURITY", f"{fid}:closing", "CLOSING_AT_MATURITY_NOT_RECORDED")
        else:
            rec.check("FT-MATURITY", f"{fid}:closing", closing, Decimal(0))


# ───────────────────────────────────────────── revenue contracts ─────────────────────────────────────────────
CONTRACT_IDENTITIES = (
    ("RC-PRICE", "revenue", KIND_CALCULATION, "Stream price = declared base price x (1 + index)^(operating year - 1), or the declared period curve"),
    ("RC-ALLOCATION", "revenue", KIND_CALCULATION, "Contract volume = declared share x physical generation while the contract is active"),
    ("RC-RESIDUAL", "revenue", KIND_CALCULATION, "Residual merchant volume = generation - contracted volumes (nothing double-counted)"),
    ("RC-WINDOW", "revenue", KIND_CALCULATION, "A contract carries no volume outside its declared window (expiry hands the volume to merchant)"),
)


def register_contracts(rec: Any, v: View, impact: Mapping[str, Any]) -> None:
    for key, stage, kind, title in CONTRACT_IDENTITIES:
        rec.register(key, stage, kind, title, BASIS_FULL, PRICE_POLICY)
    problems = verify_impact_binding(v.b, impact)
    contracts = impact["declared"]["contracts"]
    if problems:
        for key, *_ in CONTRACT_IDENTITIES:
            rec.not_comparable(key, None, "IMPACT_EVIDENCE_NOT_BOUND_TO_RUN:" + "+".join(problems))
        return
    if contracts is None:
        for key, *_ in CONTRACT_IDENTITIES:
            rec.unavailable(key, None, "NO_CONTRACT_BOOK_DECLARED")
        return
    streams = {s["id"]: s for s in contracts.get("streams") or [] if isinstance(s, Mapping) and isinstance(s.get("id"), str)}
    types = v.fact("rv2.streams")
    if not types:
        for key, *_ in CONTRACT_IDENTITIES:
            rec.unavailable(key, None, "REVENUE_CONTRACT_EVIDENCE_NOT_RECORDED")
        return
    ordered = [r["key"] for r in v.axis("statements")]
    phase = {r["key"]: r["phase"] for r in v.axis("statements")}
    ops = [k for k in ordered if phase[k] == "operation"]
    construction_keys = [k for k in ordered if phase[k] == "construction"]
    if not ops or not construction_keys:
        for key, *_ in CONTRACT_IDENTITIES:
            rec.not_comparable(key, None, "OPERATING_PERIOD_STARTS_NOT_PROVABLE")
        return
    first_start = _iso(construction_keys[-1])
    start_of = {k: (first_start if n == 0 else _iso(ops[n - 1])) for n, k in enumerate(ops)}
    gaps = {_months(_iso(a), _iso(b)) for a, b in zip(ops, ops[1:])}
    if len(gaps) != 1 or 12 % next(iter(gaps)) != 0:
        for key, *_ in CONTRACT_IDENTITIES:
            rec.not_comparable(key, None, "OPERATING_PERIODS_NOT_UNIFORM_SUB_YEAR_STEPS")
        return
    per_year = 12 // next(iter(gaps))
    # The product's operating year groups ``per_year`` consecutive operating periods starting at the first one (a stub
    # first period therefore counts as a full bucket); this is the recorded definition, not an assumption of anniversary.
    op_year = {k: n // per_year + 1 for n, k in enumerate(ops)}
    series = {sid: {n: v.series(f"rv2.stream.{sid}.{n}") for n in ("quantity", "price")} for sid in types}
    physical = [sid for sid, t in types.items() if t != "cfd"]
    for key in ops:
        total = Decimal(0)
        missing = False
        for sid in physical:
            q = (series[sid]["quantity"] or {}).get(key)
            if q is None:
                missing = True
            else:
                total += q
        for sid, t in sorted(types.items()):
            spec = streams.get(sid)
            if spec is None:
                rec.not_comparable("RC-PRICE", f"{sid}@{key}", "STREAM_NOT_IN_DECLARED_CONTRACT_BOOK")
                continue
            q, p = (series[sid]["quantity"] or {}).get(key), (series[sid]["price"] or {}).get(key)
            start, end = _iso(spec.get("start_date")), _iso(spec.get("end_date"))
            active = start is not None and end is not None and start <= start_of[key] < end
            # price
            if q is not None and q != 0 and p is not None:
                if "price_curve" in spec:
                    points = {pt["period_start"]: Decimal(str(pt["price_eur_mwh"])) for pt in spec["price_curve"]}
                    expected = points.get(start_of[key].isoformat())
                    if expected is None:
                        rec.not_comparable("RC-PRICE", f"{sid}@{key}", "CURVE_POINT_NOT_ON_PROVABLE_PERIOD_START")
                    else:
                        rec.check("RC-PRICE", f"{sid}@{key}", p, expected)
                elif t != "cfd":
                    base, idx = Decimal(str(spec["price_eur_mwh"])), Decimal(str(spec.get("indexation_rate") or 0))
                    rec.check("RC-PRICE", f"{sid}@{key}", p, base * (Decimal(1) + idx) ** (op_year[key] - 1))
            # window
            if q is not None:
                if not active:
                    rec.check("RC-WINDOW", f"{sid}@{key}", q, Decimal(0))
                else:
                    rec.check("RC-WINDOW", f"{sid}@{key}", Decimal(0), Decimal(0))
            # allocation of contracted shares
            share = spec.get("volume_share")
            if t != "cfd" and share is not None and active and q is not None and not missing and total != 0:
                rec.check("RC-ALLOCATION", f"{sid}@{key}", q / total, Decimal(str(share)))
        # residual merchant
        merchants = [sid for sid in physical if types[sid] == "merchant" and streams.get(sid, {}).get("volume_share") is None]
        if merchants and not missing and total != 0:
            contracted = sum((Decimal(str(streams[sid]["volume_share"])) for sid in physical
                              if streams.get(sid, {}).get("volume_share") is not None and types[sid] != "merchant"
                              and _contract_active(streams[sid], start_of[key], key)), Decimal(0))
            for sid in merchants:
                q = (series[sid]["quantity"] or {}).get(key)
                if q is not None:
                    rec.check("RC-RESIDUAL", f"{sid}@{key}", q / total, Decimal(1) - contracted)


def _contract_active(spec: Mapping[str, Any], start: date, key: str) -> bool:
    a, b = _iso(spec.get("start_date")), _iso(spec.get("end_date"))
    return a is not None and b is not None and a <= start < b


# ───────────────────────────────────────────── investor allocation ─────────────────────────────────────────────
INVESTOR_IDENTITIES = (
    ("IV-OWNERSHIP", "returns", KIND_CALCULATION, "Investor distribution = declared ownership x approved net equity receipt (per dated event)"),
    ("IV-AGGREGATE", "returns", KIND_CALCULATION, "Sum of investor distributions = approved distributable total (never more, never less)"),
    ("IV-PAIDIN", "returns", KIND_INPUT, "Investor paid-in = declared dated contributions; their sum = the actual legal equity funding"),
    ("IV-MULTIPLE", "returns", KIND_CALCULATION, "Realised MOIC = DPI = distributions / paid-in"),
    ("IV-XIRR", "returns", KIND_CALCULATION, "Investor XIRR = independent dated ACT/365 bisection over the recorded cash events"),
)


def decimal_xirr(events: Sequence[tuple[date, Decimal]]) -> Decimal | None:
    """Independent dated XIRR (ACT/365 from the first flow, bisection); None unless the flows change sign."""
    if not events or not (any(a < 0 for _d, a in events) and any(a > 0 for _d, a in events)):
        return None
    with localcontext() as ctx:
        ctx.prec = 50
        t0 = events[0][0]
        years = [Decimal((d - t0).days) / Decimal(365) for d, _a in events]

        def npv(rate: Decimal) -> Decimal:
            return sum((a / ((1 + rate) ** t) for (_d, a), t in zip(events, years)), Decimal(0))
        lo, hi = Decimal("-0.999"), Decimal(100)
        if not (npv(lo) > 0 > npv(hi)):
            return None
        for _ in range(250):
            mid = (lo + hi) / 2
            lo, hi = (mid, hi) if npv(mid) > 0 else (lo, mid)
        return (lo + hi) / 2


def register_investors(rec: Any, v: View, impact: Mapping[str, Any]) -> None:
    for key, stage, kind, title in INVESTOR_IDENTITIES:
        rec.register(key, stage, kind, title, BASIS_FULL, KEUR_FULL if key not in ("IV-MULTIPLE", "IV-XIRR") else (RATIO if key == "IV-MULTIPLE" else XIRR))
    problems = verify_impact_binding(v.b, impact)
    agreement = impact["declared"]["agreement"]
    evidence = impact["recorded"]["investors"]
    if problems:
        for key, *_ in INVESTOR_IDENTITIES:
            rec.not_comparable(key, None, "IMPACT_EVIDENCE_NOT_BOUND_TO_RUN:" + "+".join(problems))
        return
    if agreement is None or evidence is None:
        for key, *_ in INVESTOR_IDENTITIES:
            rec.unavailable(key, None, "NO_INVESTOR_AGREEMENT_DECLARED_OR_NO_INVESTOR_EVIDENCE_IN_RUN")
        return
    declared = {i["investor_id"]: i for i in agreement.get("investors") or []}
    paid_declared: dict[str, Decimal] = {}
    for c in agreement.get("contributions") or []:
        paid_declared[c["investor_id"]] = paid_declared.get(c["investor_id"], Decimal(0)) + Decimal(str(c["amount_keur"]))
    sponsor = impact["recorded"]["sponsor_summary"] or {}
    approved = None if sponsor.get("total_legal_equity_distributions_keur") is None else Decimal(sponsor["total_legal_equity_distributions_keur"])
    funded = None if sponsor.get("total_legal_equity_contributed_keur") is None else Decimal(sponsor["total_legal_equity_contributed_keur"])
    investors = {i["investor_id"]: i for i in evidence.get("investors") or []}
    raw_receipts = evidence.get("canonical_receipts")
    rows = raw_receipts.get("periods") if isinstance(raw_receipts, Mapping) else raw_receipts
    receipts = {p["date"]: Decimal(str(p["net_equity_receipt_keur"])) for p in rows or []
                if isinstance(p, Mapping) and p.get("net_equity_receipt_keur") is not None}
    if set(investors) != set(declared):
        rec.not_comparable("IV-OWNERSHIP", None, "RECORDED_INVESTORS_DIFFER_FROM_DECLARED_AGREEMENT")
        return
    for iid, inv in sorted(investors.items()):
        share = Decimal(str(declared[iid]["ownership_fraction"]))
        for event in inv["cash_events"]:
            receipt = receipts.get(event["date"])
            if receipt is None:
                rec.unavailable("IV-OWNERSHIP", f"{iid}@{event['date']}", "CANONICAL_RECEIPT_NOT_RECORDED_FOR_DATE")
            else:
                rec.check("IV-OWNERSHIP", f"{iid}@{event['date']}", Decimal(str(event["residual_distribution_keur"])), share * receipt)
        paid = Decimal(str(inv["total_paid_in_keur"]))
        rec.check("IV-PAIDIN", iid, paid, paid_declared.get(iid, Decimal(0)))
        dist = Decimal(str(inv["cumulative_distributions_keur"]))
        if paid > 0 and inv.get("realized_moic") is not None:
            rec.check("IV-MULTIPLE", f"{iid}:moic", Decimal(str(inv["realized_moic"])), dist / paid)
            rec.check("IV-MULTIPLE", f"{iid}:dpi", Decimal(str(inv["dpi"])), dist / paid)
        else:
            rec.unavailable("IV-MULTIPLE", iid, "NO_PAID_IN_OR_MULTIPLE_NOT_RECORDED")
        events = [(_iso(e["date"]), Decimal(str(e["net_cashflow_keur"]))) for e in inv["cash_events"]]
        independent = decimal_xirr(events) if all(d is not None for d, _a in events) else None
        if inv.get("xirr") is None or independent is None:
            rec.unavailable("IV-XIRR", iid, "XIRR_NOT_RECORDED_OR_FLOWS_DO_NOT_CHANGE_SIGN")
        else:
            rec.check("IV-XIRR", iid, Decimal(str(inv["xirr"])), independent)
    if approved is None:
        rec.unavailable("IV-AGGREGATE", None, "APPROVED_DISTRIBUTABLE_TOTAL_NOT_RECORDED")
    else:
        rec.check("IV-AGGREGATE", "total_distributions", sum((Decimal(str(i["cumulative_distributions_keur"])) for i in investors.values()),
                                                           Decimal(0)), approved)
    if funded is None:
        rec.unavailable("IV-PAIDIN", "total_funding", "ACTUAL_LEGAL_EQUITY_FUNDING_NOT_RECORDED")
    else:
        rec.check("IV-PAIDIN", "total_funding", sum((Decimal(str(i["total_paid_in_keur"])) for i in investors.values()), Decimal(0)), funded)


def reconcile_impact(bundle: Mapping[str, Any], impact: Mapping[str, Any], *, credit: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """F3.9 (+ optional credit) identities plus whichever impact families the declared evidence supports."""
    from . import credit as credit_module
    rec = build_reconciler(bundle)
    v = View(bundle)
    if credit is not None:
        credit_module.register(rec, v, credit)
    register_facilities(rec, v, impact)
    register_contracts(rec, v, impact)
    register_investors(rec, v, impact)
    result = rec.finalise()
    if credit is not None:
        result["credit_assessment"] = credit_module.assess_credit(bundle, credit)
    return result


__all__ = ["SCHEMA", "impact_evidence_from_entry", "verify_impact_binding", "register_facilities", "register_contracts",
           "register_investors", "reconcile_impact", "decimal_xirr"]
