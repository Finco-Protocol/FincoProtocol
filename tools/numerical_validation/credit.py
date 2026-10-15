"""WF-A institutional credit validation over ONE committed Run (read-only, Decimal, additive to F3.9).

What this module is
-------------------
An independent *checker* of the credit quantities a committed Run already persisted.  It recomputes them from OTHER
persisted quantities of the same immutable Run and compares.  It never runs the model, never imports a production
financial module, never changes a formula, and never turns absent evidence into a number.

Two kinds of result are kept strictly apart, because they answer different questions:

* **Numerical identities** (``CR-*``, registered on the F3.9 ``Reconciler``).  FAIL means the persisted evidence is
  internally inconsistent: a potential numerical defect that needs FINANCIAL AUTHORITY REVIEW.
* **Credit assessment** (``assess_credit``).  Constraint headroom/breach against the thresholds the Run's own approved
  definitions use.  A breach is a *credit finding about the case*, never a validation failure and never a bankability
  opinion.  Nothing in here is a signed bankability statement.

Definitions used (product definitions, not invented here)
---------------------------------------------------------
* DSCR (reported)  = base CFADS / Senior debt service, defined only for periods with debt service > 1e-6 kEUR
  (``check_dscr_identity`` / F3.9 ``DEBT-DSCR``); minimum and average are over exactly those periods
  (arithmetic mean of the period ratios).
* Sizing DSCR      = bank CFADS / Senior debt service, which the sizing target constrains (``target_dscr`` x availability).
* Gearing          = Senior debt / total project uses (``TOTAL_PROJECT_USES`` basis), compared with the recorded cap.
* Lock-up          = the shareholder-waterfall gate closes a period when DSCR < the lock-up threshold (strictly less
  than), Senior debt service is non-zero and the period is inside Senior maturity.  The gate has further
  non-DSCR components, so ``locked`` does not imply ``DSCR < lock-up``; only the implication ``DSCR < lock-up =>
  locked`` is checkable, and a lock without a DSCR trigger is reported NOT_COMPARABLE, never PASS or FAIL.
* LLCR / PLCR      = NOT persisted and NOT defined by the product Run (``min_llcr`` is null; there is no persisted
  discount basis).  They are reported UNAVAILABLE, never derived.

Declared inputs
---------------
Covenant thresholds and the sizing mode are *inputs*, not Run outputs.  They are supplied explicitly by the caller
(``declared``), recorded and hashed in the credit evidence, and never inferred.  A missing declaration makes the
dependent identity UNAVAILABLE.
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
from collections.abc import Mapping, Sequence
from decimal import Decimal
from typing import Any

from .evidence import dec
from .identities import KEUR_2DP, KEUR_FULL, RATIO, View, build_reconciler
from .periodic import BASIS_2DP, BASIS_FULL, KIND_CALCULATION
from .reconcile import ReconciliationInputError, canonical_bytes

SCHEMA = "FINCO_CREDIT_EVIDENCE_V1"
ASSESSMENT_SCHEMA = "FINCO_CREDIT_ASSESSMENT_V1"

#: debt service at or below this is "no debt service" (same boundary F3.9 ``DEBT-DSCR`` uses).
DEBT_SERVICE_FLOOR = Decimal("1e-6")
#: canonical Senior solver precision (``DEFAULT_TERMINAL_TOLERANCE_KEUR`` in the Model Quality evidence contract).
TERMINAL_TOLERANCE_KEUR = Decimal("1e-4")
RATIO_TOLERANCE = Decimal("1e-7")
HALF_QUANTUM = Decimal("0.005")

SIZING_MODES = ("FLAT_DSCR_SCULPTED", "GEARING_CAP", "COMBINED_MINIMUM")

UNSUPPORTED_CREDIT = (
    ("llcr", "LLCR is not persisted (min_llcr is null) and the product records no discount basis; it is never derived."),
    ("plcr", "PLCR is not defined by the persisted Run; it is never derived or substituted by another ratio."),
    ("event_of_default", "No Event-of-Default mechanic exists in the engine; the lender-case RAG thresholds are "
                         "presentation classes, not contractual events."),
    ("cash_sweep", "No cash-sweep amount is persisted (cash_sweep_keur is null in every distribution period)."),
    ("fixed_debt_resolve", "The product has no re-run that keeps a previously sized debt fixed; fixed-debt stress is "
                           "expressed only through GEARING_CAP sizing, which sizes on cost and not on CFADS."),
    ("independent_binding_constraint_capacity", "Neither the DSCR capacity nor the gearing capacity is persisted "
                                                "separately; the binding label is checked for coherence only."),
)


def _plain(value: Any) -> Any:
    """Plain JSON-compatible copy of a (possibly frozen / mapping-proxy) payload."""
    if isinstance(value, Mapping):
        return {str(k): _plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(v) for v in value]
    return value


def _flag(value: Any) -> bool | None:
    return value if isinstance(value, bool) else None


def credit_evidence_from_entry(entry: Any, bundle: Mapping[str, Any], *, declared: Mapping[str, Any] | None = None) -> dict:
    """Read-only credit evidence for the Run ``entry`` that produced ``bundle``.

    ``entry`` is duck-typed (a Run History record): only ``runtime_summary``, ``integrity_evidence`` and
    ``distribution_schedule`` are read.  ``declared`` carries the explicitly declared covenant thresholds and sizing
    mode; anything else is rejected so a threshold can never be smuggled in under another name.
    """
    declared = dict(declared or {})
    unknown = set(declared) - {"lockup_dscr", "min_dscr_covenant", "sizing_mode"}
    if unknown:
        raise ReconciliationInputError(f"unsupported declared credit input(s): {sorted(unknown)}")
    mode = declared.get("sizing_mode")
    if mode is not None and mode not in SIZING_MODES:
        raise ReconciliationInputError(f"unsupported declared sizing_mode {mode!r}")
    summary = _plain(getattr(entry, "runtime_summary", None) or {})
    integrity = _plain(getattr(entry, "integrity_evidence", None) or {})
    distribution = _plain(getattr(entry, "distribution_schedule", None) or {})
    senior = integrity.get("senior_debt") if isinstance(integrity.get("senior_debt"), Mapping) else {}
    diag = senior.get("diagnostics") if isinstance(senior.get("diagnostics"), Mapping) else {}
    rows = distribution.get("periods") if isinstance(distribution.get("periods"), list) else None
    periods: list[dict[str, Any]] = []
    for row in rows or []:
        if isinstance(row, Mapping) and isinstance(row.get("date"), str):
            periods.append({"date": row["date"], "is_operation": _flag(row.get("is_operation")),
                            "lockup_active": _flag(row.get("lockup_active")),
                            "distribution": dec(row.get("distribution_keur")),
                            "cash_sweep": dec(row.get("cash_sweep_keur"))})
    body = {
        "schema": SCHEMA,
        "identity": {k: bundle["identity"][k] for k in ("run_key", "composite_hash", "snapshot_id", "project_key")},
        "declared": {"source": "DECLARED_BY_CALLER_NOT_A_RUN_OUTPUT",
                     "lockup_dscr": dec(declared.get("lockup_dscr")),
                     "min_dscr_covenant": dec(declared.get("min_dscr_covenant")),
                     "sizing_mode": mode},
        "summary": {name: dec(summary.get(name)) for name in (
            "actual_gearing_pct", "gearing_cap_pct", "senior_debt_keur", "total_project_uses_keur", "min_dscr",
            "avg_dscr", "min_llcr", "target_dscr")},
        "periods_in_lockup": summary.get("periods_in_lockup") if isinstance(summary.get("periods_in_lockup"), int)
        and not isinstance(summary.get("periods_in_lockup"), bool) else None,
        "diagnostics": {"binding_constraint": diag.get("binding_constraint") if isinstance(diag.get("binding_constraint"), str) else None,
                        "final_debt_size_keur": dec(diag.get("final_debt_size_keur")),
                        "converged": _flag(diag.get("converged")), "is_authoritative": _flag(diag.get("is_authoritative")),
                        "termination_reason": diag.get("termination_reason") if isinstance(diag.get("termination_reason"), str) else None},
        "distribution_periods": periods if rows is not None else None,
        "unsupported": [{"capability": c, "reason": r} for c, r in UNSUPPORTED_CREDIT],
    }
    body["sha256"] = hashlib.sha256(canonical_bytes({k: v for k, v in body.items() if k != "sha256"})).hexdigest()
    return body


def verify_credit_binding(bundle: Mapping[str, Any], credit: Mapping[str, Any]) -> list[str]:
    """Reasons the credit evidence is not provably the same Run as the bundle (empty when bound)."""
    problems = []
    if credit.get("schema") != SCHEMA:
        problems.append("CREDIT_SCHEMA_MISMATCH")
    for key in ("run_key", "composite_hash", "snapshot_id", "project_key"):
        if (credit.get("identity") or {}).get(key) != bundle["identity"].get(key):
            problems.append(f"IDENTITY_MISMATCH_{key}")
    body = {k: v for k, v in credit.items() if k != "sha256"}
    if hashlib.sha256(canonical_bytes(body)).hexdigest() != credit.get("sha256"):
        problems.append("CREDIT_EVIDENCE_HASH_MISMATCH")
    return problems


def _dscr_rows(v: View) -> tuple[list[str], dict[str, Decimal | None], dict[str, Decimal | None]]:
    """Statement-axis keys with debt service above the floor, the recomputed DSCR and the recomputed sizing DSCR."""
    service = v.series("ev.senior.debt_service")
    base = v.series("ev.senior.base_cfads")
    bank = v.series("ev.senior.bank_cfads")
    keys: list[str] = []
    dscr: dict[str, Decimal | None] = {}
    sizing: dict[str, Decimal | None] = {}
    if service is None:
        return keys, dscr, sizing
    for row in v.axis("statements"):
        key = row["key"]
        d = service.get(key)
        if d is None or d <= DEBT_SERVICE_FLOOR:
            continue
        keys.append(key)
        b, k = (base or {}).get(key), (bank or {}).get(key)
        dscr[key] = None if b is None else b / d
        sizing[key] = None if k is None else k / d
    return keys, dscr, sizing


def register(rec: Any, v: View, credit: Mapping[str, Any]) -> None:
    """Register and evaluate every ``CR-*`` identity on ``rec`` (a F3.9 Reconciler)."""
    spec = (
        ("CR-GEARING-DEF", "debt", "Recorded gearing = Senior debt / total project uses (full-precision Sources & Uses)", BASIS_FULL, RATIO),
        ("CR-SIZED-DEBT", "debt", "Solver final debt size = Senior debt recorded in Sources & Uses", BASIS_FULL, KEUR_FULL),
        ("CR-BINDING", "debt", "Persisted binding-constraint label is coherent with recorded gearing and cap", BASIS_FULL, RATIO),
        ("CR-DSCR-MIN", "debt", "Reported minimum DSCR = minimum of recomputed period DSCR (debt service > 0)", BASIS_FULL, RATIO),
        ("CR-DSCR-AVG", "debt", "Reported average DSCR = arithmetic mean of recomputed period DSCR (debt service > 0)", BASIS_FULL, RATIO),
        ("CR-DSCR-NODS", "debt", "No DSCR is reported for a period without debt service (never a fabricated ratio)", BASIS_FULL, RATIO),
        ("CR-LOCKUP-FLAG", "cfads_waterfall", "DSCR below the declared lock-up threshold => the distribution gate is closed", BASIS_FULL, RATIO),
        ("CR-LOCKUP-DIST", "cfads_waterfall", "A closed gate distributes nothing (persisted at 2dp)", BASIS_2DP, KEUR_2DP),
        ("CR-LOCKUP-COUNT", "cfads_waterfall", "Reported periods in lock-up = number of closed-gate periods", BASIS_FULL, RATIO),
    )
    for key, stage, title, basis, policy in spec:
        rec.register(key, stage, KIND_CALCULATION, title, basis, policy)
    s = credit["summary"]
    bound = verify_credit_binding(v.b, credit)
    if bound:
        for key, *_ in spec:
            rec.not_comparable(key, None, "CREDIT_EVIDENCE_NOT_BOUND_TO_RUN:" + "+".join(bound))
        return
    D = lambda name: None if s.get(name) is None else Decimal(s[name])  # noqa: E731
    gearing, cap = D("actual_gearing_pct"), D("gearing_cap_pct")
    senior, uses = v.scalar("su.senior_debt_keur"), v.scalar("su.total_uses_keur")

    # gearing definition
    if gearing is None or senior is None or uses is None:
        rec.unavailable("CR-GEARING-DEF", None, "GEARING_OR_SOURCES_USES_NOT_RECORDED")
    elif uses == 0:
        rec.not_comparable("CR-GEARING-DEF", None, "ZERO_TOTAL_USES")
    else:
        rec.check("CR-GEARING-DEF", "total", gearing, senior / uses)

    # sized debt
    diag = credit["diagnostics"]
    final = None if diag["final_debt_size_keur"] is None else Decimal(diag["final_debt_size_keur"])
    if final is None or senior is None:
        rec.unavailable("CR-SIZED-DEBT", None, "FINAL_DEBT_SIZE_OR_SOURCES_USES_NOT_RECORDED")
    elif v.fact("facility_authority") is not None or v.fact("financing_authority") is not None:
        rec.not_comparable("CR-SIZED-DEBT", None, "MULTI_FACILITY_FINANCING_SIZE_NOT_ATTRIBUTABLE_TO_ONE_SOLVE")
    elif diag["is_authoritative"] is not True or diag["converged"] is not True:
        rec.not_comparable("CR-SIZED-DEBT", None, f"SOLVER_NOT_AUTHORITATIVE_{diag['termination_reason']}")
    else:
        rec.check("CR-SIZED-DEBT", "total", final, senior)

    # binding label coherence
    label = diag["binding_constraint"]
    if label is None or gearing is None or cap is None:
        rec.unavailable("CR-BINDING", None, "BINDING_LABEL_OR_GEARING_NOT_RECORDED")
    elif label == "GEARING":
        rec.check("CR-BINDING", "gearing_at_cap", cap - gearing, Decimal(0))
    elif label == "DSCR":
        if gearing < cap - RATIO_TOLERANCE:
            rec.check("CR-BINDING", "gearing_not_binding", Decimal(0), Decimal(0))
        else:
            rec.not_comparable("CR-BINDING", None, "DSCR_LABEL_WITH_GEARING_AT_CAP_TIE")
    else:
        rec.unavailable("CR-BINDING", None, f"BINDING_LABEL_NOT_RECOGNISED_{label}")

    keys, dscr, _sizing = _dscr_rows(v)
    reported = v.series("ev.senior.reported_dscr")
    values = [x for x in dscr.values() if x is not None]
    minimum, average = D("min_dscr"), D("avg_dscr")
    if not keys or not values or len(values) != len(keys):
        for key in ("CR-DSCR-MIN", "CR-DSCR-AVG"):
            rec.unavailable(key, None, "NO_PERIOD_WITH_DEBT_SERVICE_AND_CFADS")
    else:
        for key, reported_value, expected in (("CR-DSCR-MIN", minimum, min(values)),
                                              ("CR-DSCR-AVG", average, sum(values) / Decimal(len(values)))):
            if reported_value is None:
                rec.unavailable(key, None, "SUMMARY_DSCR_NOT_RECORDED")
            else:
                rec.check(key, "summary", reported_value, expected)
    service = v.series("ev.senior.debt_service")
    for row in v.axis("statements"):
        key = row["key"]
        d = (service or {}).get(key)
        if d is None or d > DEBT_SERVICE_FLOOR:
            continue
        got = (reported or {}).get(key)
        rec.check("CR-DSCR-NODS", key, Decimal(0) if got is None else Decimal(1), Decimal(0))

    # lock-up (needs a declared threshold and the persisted gate flags)
    lockup = None if credit["declared"]["lockup_dscr"] is None else Decimal(credit["declared"]["lockup_dscr"])
    dist = credit["distribution_periods"]
    flags = {} if dist is None else {p["date"]: p for p in dist}
    if lockup is None:
        for key in ("CR-LOCKUP-FLAG",):
            rec.unavailable(key, None, "LOCKUP_DSCR_NOT_DECLARED")
    elif dist is None:
        rec.unavailable("CR-LOCKUP-FLAG", None, "DISTRIBUTION_SCHEDULE_NOT_PERSISTED")
    else:
        for key in keys:
            ratio = dscr.get(key)
            row = flags.get(key)
            if ratio is None:
                rec.unavailable("CR-LOCKUP-FLAG", key, "DSCR_NOT_RECOMPUTABLE")
            elif row is None or row["lockup_active"] is None:
                rec.unavailable("CR-LOCKUP-FLAG", key, "GATE_FLAG_NOT_PERSISTED_FOR_PERIOD")
            elif ratio < lockup:                       # strictly below: the engine's predicate
                rec.check("CR-LOCKUP-FLAG", key, Decimal(int(row["lockup_active"])), Decimal(1))
            elif row["lockup_active"]:                 # locked without a DSCR trigger
                rec.not_comparable("CR-LOCKUP-FLAG", key, "LOCKED_WITHOUT_DSCR_TRIGGER_NON_DSCR_GATE_COMPONENT_NOT_PROVABLE")
            else:
                rec.check("CR-LOCKUP-FLAG", key, Decimal(0), Decimal(0))
    if dist is None:
        rec.unavailable("CR-LOCKUP-DIST", None, "DISTRIBUTION_SCHEDULE_NOT_PERSISTED")
    else:
        for p in dist:
            if p["lockup_active"] is True:
                if p["distribution"] is None:
                    rec.unavailable("CR-LOCKUP-DIST", p["date"], "DISTRIBUTION_NOT_PERSISTED")
                else:
                    rec.check("CR-LOCKUP-DIST", p["date"], Decimal(p["distribution"]), Decimal(0), rounded_terms=1)
        if not any(p["lockup_active"] is True for p in dist):
            rec.check("CR-LOCKUP-DIST", "no_closed_gate", Decimal(0), Decimal(0))
    count = credit["periods_in_lockup"]
    if dist is None or count is None:
        rec.unavailable("CR-LOCKUP-COUNT", None, "LOCKUP_COUNT_OR_FLAGS_NOT_PERSISTED")
    else:
        rec.check("CR-LOCKUP-COUNT", "summary", Decimal(count), Decimal(sum(1 for p in dist if p["lockup_active"] is True)))


def reconcile_credit(bundle: Mapping[str, Any], credit: Mapping[str, Any]) -> dict[str, Any]:
    """F3.9 identities + CR-* identities in one deterministic result, with the credit assessment attached."""
    rec = build_reconciler(bundle)
    register(rec, View(bundle), credit)
    result = rec.finalise()
    result["credit_assessment"] = assess_credit(bundle, credit)
    return result


# ───────────────────────────── credit assessment (findings, never validation failures) ─────────────────────────────
def _s(value: Decimal | None) -> str | None:
    return None if value is None else format(value, "f")


def assess_credit(bundle: Mapping[str, Any], credit: Mapping[str, Any]) -> dict[str, Any]:
    v = View(bundle)
    s = credit["summary"]
    declared = credit["declared"]
    D = lambda name: None if s.get(name) is None else Decimal(s[name])  # noqa: E731
    gearing, cap = D("actual_gearing_pct"), D("gearing_cap_pct")
    keys, dscr, sizing = _dscr_rows(v)
    target = v.series("ev.senior.target_dscr")
    availability = v.series("ev.senior.availability")
    items: list[dict[str, Any]] = []

    def add(item: str, status: str, **detail: Any) -> None:
        items.append({"item": item, "status": status, **{k: detail[k] for k in sorted(detail)}})

    # gearing
    if gearing is None or cap is None:
        add("GEARING_CAP", "UNAVAILABLE", reason="GEARING_OR_CAP_NOT_RECORDED")
    else:
        headroom = cap - gearing
        status = "BREACH" if headroom < -RATIO_TOLERANCE else ("AT_CAP" if headroom <= RATIO_TOLERANCE else "BELOW_CAP")
        add("GEARING_CAP", status, cap=_s(cap), gearing=_s(gearing), headroom=_s(headroom))

    # sizing DSCR floor (a product guarantee only for DSCR-based sizing)
    mode = declared["sizing_mode"]
    floors = []
    for key in keys:
        t, a, sz = (target or {}).get(key), (availability or {}).get(key), sizing.get(key)
        if None in (t, sz):
            continue
        floors.append((key, sz - t / (a if a else Decimal(1))))
    if not floors:
        add("SIZING_DSCR_FLOOR", "UNAVAILABLE", reason="TARGET_OR_BANK_CFADS_NOT_RECORDED")
    else:
        worst = min(floors, key=lambda x: x[1])
        met = worst[1] >= -RATIO_TOLERANCE
        if mode == "GEARING_CAP":
            add("SIZING_DSCR_FLOOR", "NOT_A_GUARANTEE" if not met else "MET", sizing_mode=mode, worst_headroom=_s(worst[1]),
                worst_period=worst[0], note="GEARING_CAP sizes on cost, not on CFADS: a DSCR below target is a case finding")
        else:
            add("SIZING_DSCR_FLOOR", "MET" if met else "BREACH", sizing_mode=mode, worst_headroom=_s(worst[1]), worst_period=worst[0])

    values = {k: x for k, x in dscr.items() if x is not None}
    if not values:
        for name in ("MIN_DSCR_COVENANT", "LOCKUP_DSCR", "CFADS_COVER"):
            add(name, "UNAVAILABLE", reason="NO_PERIOD_WITH_DEBT_SERVICE_AND_CFADS")
    else:
        low_key = min(values, key=lambda k: values[k])
        low = values[low_key]
        for name, threshold, verb in (("MIN_DSCR_COVENANT", declared["min_dscr_covenant"], "BREACH"),
                                      ("LOCKUP_DSCR", declared["lockup_dscr"], "TRIGGERED")):
            if threshold is None:
                add(name, "UNAVAILABLE", reason="THRESHOLD_NOT_DECLARED")
            else:
                t = Decimal(threshold)
                below = [k for k, x in values.items() if x < t]        # strictly below, like the engine
                add(name, verb if below else "HEADROOM", threshold=_s(t), minimum_dscr=_s(low), minimum_period=low_key,
                    periods_below=len(below), first_below=min(below) if below else None, headroom=_s(low - t))
        short = [k for k, x in values.items() if x < 1]
        add("CFADS_COVER", "DEBT_SERVICE_NOT_COVERED" if short else "COVERED", periods_below_one=len(short),
            first_below_one=min(short) if short else None)
    nonpositive = []
    base = v.series("ev.senior.base_cfads")
    service = v.series("ev.senior.debt_service")
    for key in keys:
        if base and base.get(key) is not None and base[key] <= 0:
            nonpositive.append(key)
    add("NONPOSITIVE_CFADS_WITH_DEBT_SERVICE", "PRESENT" if nonpositive else "NONE", periods=len(nonpositive),
        first=min(nonpositive) if nonpositive else None)

    # terminal liability
    closing = v.series("ev.senior.closing")
    if closing is None or service is None or not keys:
        add("SENIOR_TERMINAL_BALANCE", "UNAVAILABLE", reason="SENIOR_SCHEDULE_NOT_RECORDED")
    else:
        final = closing.get(keys[-1])
        if final is None:
            add("SENIOR_TERMINAL_BALANCE", "UNAVAILABLE", reason="CLOSING_BALANCE_MISSING")
        else:
            add("SENIOR_TERMINAL_BALANCE", "SETTLED" if final <= TERMINAL_TOLERANCE_KEUR else "OUTSTANDING_AT_FINAL_PERIOD",
                balance=_s(final), final_period=keys[-1], tolerance=_s(TERMINAL_TOLERANCE_KEUR))
    for capability in ("llcr", "plcr"):
        reason = "LLCR_NOT_PERSISTED_NO_DISCOUNT_BASIS" if capability == "llcr" else "PLCR_NOT_DEFINED_BY_PERSISTED_RUN"
        add(capability.upper(), "UNAVAILABLE", reason=reason, note="never derived or substituted by another ratio")
    add("EVENT_OF_DEFAULT", "UNAVAILABLE", reason="NO_EVENT_OF_DEFAULT_MECHANIC_IN_ENGINE")
    sweep = [p for p in (credit["distribution_periods"] or []) if p["cash_sweep"] is not None]
    add("CASH_SWEEP", "UNAVAILABLE" if not sweep else "PERSISTED", reason="NO_CASH_SWEEP_AMOUNT_PERSISTED" if not sweep else "",
        periods_with_sweep=len(sweep))
    return {"schema": ASSESSMENT_SCHEMA, "identity": credit["identity"], "credit_evidence_sha256": credit["sha256"],
            "declared": credit["declared"], "items": items,
            "disclaimer": "Credit assessment of recorded Run evidence only. It is not a bankability opinion, lender approval "
                          "or Signed Run, and a numerical identity PASS does not establish bankability."}


def assessment_reports(result: Mapping[str, Any]) -> dict[str, bytes]:
    """Deterministic JSON / CSV / Markdown of the credit assessment (no raw payloads)."""
    a = result["credit_assessment"]
    js = canonical_bytes(a)
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow(["item", "status", "detail"])
    for item in a["items"]:
        writer.writerow([item["item"], item["status"], json.dumps({k: v for k, v in item.items() if k not in ("item", "status")},
                                                                  sort_keys=True)])
    lines = [f"# Credit assessment — run `{a['identity']['run_key']}`", "", a["disclaimer"], "",
             "| Item | Status | Detail |", "|---|---|---|"]
    for item in a["items"]:
        detail = ", ".join(f"{k}={v}" for k, v in item.items() if k not in ("item", "status") and v not in (None, ""))
        lines.append(f"| {item['item']} | {item['status']} | {detail} |")
    return {"credit_assessment.json": js, "credit_assessment.csv": out.getvalue().encode(),
            "credit_assessment.md": ("\n".join(lines) + "\n").encode()}


__all__ = ["SCHEMA", "ASSESSMENT_SCHEMA", "UNSUPPORTED_CREDIT", "credit_evidence_from_entry", "verify_credit_binding",
           "register", "reconcile_credit", "assess_credit", "assessment_reports"]
