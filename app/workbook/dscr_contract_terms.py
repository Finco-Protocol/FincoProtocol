"""WF-04 — the two contractual DSCR inputs, their immutable per-Run capture and their strict evaluation.

Financial Owner decision (2026-10-29, V3): exactly TWO user-configurable contractual DSCR values exist for this feature.

* ``Minimum DSCR``     — the project-specific Event-of-Default floor.  ``actual < floor`` in an applicable test period is a
                          model-evaluated ``EVENT_OF_DEFAULT: TRIGGERED``; ``actual == floor`` is NOT a trigger.
* ``Contractual DSCR`` — the contractual covenant requirement, evaluated separately.

The *achieved* minimum DSCR is a measured OUTPUT, never an input.  The Senior sizing target, the sculpting target vector and the
lock-up threshold are independent existing controls and are never reused as either value.

This module is PURE (no persistence, no engine).  It never calculates a financial number: it captures two typed inputs and compares
already-persisted, sealed per-period DSCR ratios against them.  Every comparison is on raw IEEE-754 doubles with NO tolerance; display
rounding is presentation only (see :func:`format_ratio`).  A model-evaluated EoD condition is not a legally declared default, not proof
of a missed payment and not proof that a project is unprofitable.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping, Optional, Sequence

SCHEMA = "FINCO_DSCR_CONTRACT_TERMS_V1"
IDENTITY_KEY = "dscr_contract_terms"          # key inside the Run's immutable ``last_runtime_identity``

EOD_FIELD_ID = "debt.contract.min_dscr_eod"
EOD_SNAPSHOT_KEY = "dscr_min_eod_x"
COVENANT_FIELD_ID = "debt.contract.contractual_dscr"
COVENANT_SNAPSHOT_KEY = "dscr_contractual_x"

MIN_VALUE_X = 0.01        # a DSCR requirement is a positive multiple; 0 is never "no floor" (blank is NOT_CONFIGURED)
MAX_VALUE_X = 10.0

#: A period carries scheduled Senior debt service when it exceeds this amount.  This is the SAME applicability convention as the
#: Run-Integrity DSCR identity check (``app.run_integrity.contracts.TOL_KEUR``; a test pins the equality).  It decides WHICH periods are
#: tested; it is never a tolerance on a ratio comparison.
DEBT_SERVICE_DUE_KEUR = 1e-6

CONFIGURED = "CONFIGURED"
NOT_CONFIGURED = "NOT_CONFIGURED"
INVALID = "INVALID"

# Evaluation statuses (strings are part of the API contract; the UI renders them verbatim).
EOD_TRIGGERED = "TRIGGERED"
EOD_NOT_TRIGGERED = "NOT_TRIGGERED_UNDER_THIS_FLOOR"
COV_BREACHED = "BREACHED"
COV_COMPLIANT = "COMPLIANT"
UNAVAILABLE = "UNAVAILABLE"
NOT_APPLICABLE = "NOT_APPLICABLE"
COVERAGE_DEFICIENCY = "DEFICIENCY"
COVERAGE_NO_DEFICIENCY = "NO_DEFICIENCY_FOUND"

#: The documented test convention.  It is a FINCO model convention, disclosed with every verdict.  Whether a facility agreement tests
#: on another frequency (for example a rolling annual ratio) is the single unresolved methodology question of this feature; it is
#: deliberately not guessed and no third input field exists to configure it.
TEST_BASIS: Mapping[str, str] = {
    "ratio": "BASE_CASE_CFADS_OVER_SCHEDULED_SENIOR_DEBT_SERVICE",
    "source": "integrity_evidence.senior_debt.periods[].reported_dscr (digest-sealed, full precision)",
    "test_periods": "every period of this Run with scheduled Senior debt service above 1e-6 kEUR, on the Run's own calendar",
    "eod_predicate": "actual < Minimum DSCR (strict, raw doubles, no tolerance)",
    "covenant_predicate": "actual < Contractual DSCR is a breach; actual >= Contractual DSCR is compliant (raw doubles, no tolerance)",
    "authority": "FINCO_MODEL_CONVENTION_NOT_A_LEGAL_TEST",
}

MESSAGE_COVENANT = ("Minimum DSCR is below the contractual requirement. Debt service may still be covered, but the covenant is not met.")
MESSAGE_COVERAGE = ("Minimum DSCR is below 1.00x. CFADS does not cover scheduled debt service in the identified periods. "
                    "Review available reserves and the debt repayment schedule.")
MESSAGE_EOD_NOTE = ("A model-evaluated threshold condition on the entered credit terms. It is not a legally declared default, "
                    "not proof of a missed payment and not proof that the project is unprofitable.")


# ── typed terms ──────────────────────────────────────────────────────────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class Term:
    field_id: str
    status: str                      # CONFIGURED | NOT_CONFIGURED | INVALID
    value: Optional[float] = None    # raw double parsed from ``raw``; None unless CONFIGURED
    raw: Optional[str] = None        # the exact text the user saved


@dataclass(frozen=True)
class RunTerms:
    """The two contractual DSCR terms exactly as they were when one specific Run was committed."""
    recorded: bool
    reason: str = ""
    eod: Term = field(default_factory=lambda: Term(EOD_FIELD_ID, NOT_CONFIGURED))
    contractual: Term = field(default_factory=lambda: Term(COVENANT_FIELD_ID, NOT_CONFIGURED))


def _term_from_text(field_id: str, raw: Any, label: str) -> dict[str, Any]:
    text = "" if raw is None else str(raw).strip()
    if not text:
        return {"field_id": field_id, "status": NOT_CONFIGURED, "value": None, "raw": None, "unit": "x"}
    try:
        value = float(text)
    except (TypeError, ValueError):
        return {"field_id": field_id, "status": INVALID, "value": None, "raw": text, "unit": "x",
                "reason": f"{label} is not a number."}
    if not math.isfinite(value) or value < MIN_VALUE_X or value > MAX_VALUE_X:
        return {"field_id": field_id, "status": INVALID, "value": None, "raw": text, "unit": "x",
                "reason": f"{label} must be a finite multiple between {MIN_VALUE_X} and {MAX_VALUE_X}."}
    return {"field_id": field_id, "status": CONFIGURED, "value": value, "raw": text, "unit": "x"}


def capture(draft_snapshot: Mapping[str, Any]) -> dict[str, Any]:
    """The immutable per-Run record, taken from the draft that is being committed.  Never raises: a corrupt value is recorded as
    ``INVALID`` (and evaluated as UNAVAILABLE) so that a credit term can never make a mathematically valid Run fail to commit."""
    snap = draft_snapshot if isinstance(draft_snapshot, Mapping) else {}
    return {
        "schema": SCHEMA,
        "captured_from": "WORKING_COPY_DRAFT_AT_RUN_COMMIT",
        "eod_minimum_dscr": _term_from_text(EOD_FIELD_ID, snap.get(EOD_SNAPSHOT_KEY), "Minimum DSCR (EoD threshold)"),
        "contractual_dscr": _term_from_text(COVENANT_FIELD_ID, snap.get(COVENANT_SNAPSHOT_KEY), "Contractual DSCR (covenant)"),
        "test_basis": dict(TEST_BASIS),
    }


def _read_term(block: Any, field_id: str) -> Optional[Term]:
    if not isinstance(block, Mapping) or block.get("field_id") != field_id:
        return None
    status = block.get("status")
    if status == NOT_CONFIGURED:
        return Term(field_id, NOT_CONFIGURED)
    raw = block.get("raw")
    if status == INVALID:
        return Term(field_id, INVALID, None, raw if isinstance(raw, str) else None)
    value = block.get("value")
    if status == CONFIGURED and isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and value > 0:
        return Term(field_id, CONFIGURED, float(value), raw if isinstance(raw, str) else None)
    return None


def read_run_terms(identity: Optional[Mapping[str, Any]]) -> RunTerms:
    """Decode the terms of ONE committed Run from its own immutable identity.  Never reads the Working Copy.

    A Run committed before this contract existed has no record: ``recorded=False`` (verdicts UNAVAILABLE/NOT_RECORDED).  A malformed
    record is UNREADABLE, never a default and never a pass."""
    if not isinstance(identity, Mapping) or IDENTITY_KEY not in identity:
        return RunTerms(False, "NOT_RECORDED: this Run was committed before the two contractual DSCR terms were recorded with a Run.")
    block = identity.get(IDENTITY_KEY)
    if not isinstance(block, Mapping) or block.get("schema") != SCHEMA:
        return RunTerms(False, "UNREADABLE: the recorded contractual DSCR terms of this Run could not be decoded.")
    eod = _read_term(block.get("eod_minimum_dscr"), EOD_FIELD_ID)
    cov = _read_term(block.get("contractual_dscr"), COVENANT_FIELD_ID)
    if eod is None or cov is None:
        return RunTerms(False, "UNREADABLE: the recorded contractual DSCR terms of this Run could not be decoded.")
    return RunTerms(True, "", eod, cov)


# ── display (presentation only — never used by a predicate) ────────────────────────────────────────────────────────────────────────
def format_ratio(value: Optional[float], refs: Iterable[float] = (1.0,), *, min_digits: int = 2, max_digits: int = 12) -> str:
    """A ratio as ``1.05x`` text with enough digits that it can never read EQUAL to a reference unless it IS equal, nor on the wrong
    side of it.  The verdict never uses this string; it exists so that 0.9951 is not shown as a safe-looking 1.00x."""
    if value is None or isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        return "—"
    v = float(value)
    references = [float(r) for r in refs if isinstance(r, (int, float)) and not isinstance(r, bool) and math.isfinite(r)]
    for digits in range(min_digits, max_digits + 1):
        shown = round(v, digits)
        # Acceptable only if, at this precision, the displayed value equals a reference's displayed value exactly when the raw values are
        # equal, and (otherwise) sits on the same side of it as the raw value does.
        if all((shown == round(r, digits)) == (v == r) and (v == r or (shown < round(r, digits)) == (v < r)) for r in references):
            return f"{v:.{digits}f}x"
    return f"{v!r}x"          # within rounding noise of a reference yet not equal: the shortest exact text, never a trailing-zero look-alike


def _signed(value: float, suffix: str, min_digits: int, max_digits: int) -> str:
    """Signed decimal text with at least two significant digits, so a small difference is neither shown as zero nor exaggerated."""
    if value == 0.0:
        return f"{0.0:+.{min_digits}f}{suffix}"
    digits = max(min_digits, min(max_digits, 1 - math.floor(math.log10(abs(value)))))
    return f"{value:+.{digits}f}{suffix}"


def format_delta_x(delta: Optional[float], *, min_digits: int = 2, max_digits: int = 12) -> str:
    """A signed ratio difference such as ``+0.15x`` or ``-0.0075x``; a non-zero difference is never displayed as ``+0.00x``."""
    if delta is None or isinstance(delta, bool) or not isinstance(delta, (int, float)) or not math.isfinite(delta):
        return "—"
    return _signed(float(delta), "x", min_digits, max_digits)


def format_relative_pct(pct: Optional[float], *, min_digits: int = 2, max_digits: int = 12) -> str:
    """A signed relative difference in percent; a non-zero value is never displayed as ``+0.00%``."""
    if pct is None or isinstance(pct, bool) or not isinstance(pct, (int, float)) or not math.isfinite(pct):
        return "—"
    return _signed(float(pct), "%", min_digits, max_digits)


def headroom(actual: Optional[float], required: Optional[float]) -> Optional[dict[str, Any]]:
    """Absolute (``x``) and relative (%) headroom of two persisted numbers; ``None`` unless both exist and ``required`` is positive."""
    if actual is None or required is None or not math.isfinite(actual) or not math.isfinite(required) or required <= 0:
        return None
    return {"absolute_x": actual - required, "relative_pct": (actual / required - 1.0) * 100.0}


# ── evaluation over persisted per-period evidence ───────────────────────────────────────────────────────────────────────────────────
def _finite(x: Any) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)


def test_rows(evidence_periods: Sequence[Mapping[str, Any]], dates: Mapping[int, str]) -> list[dict[str, Any]]:
    """Per-period facts read from the Run's sealed Senior-debt evidence.  Nothing is calculated except two presentation ratios that the
    evidence's own DSCR identity check already guarantees (bank DSCR) and the arithmetic shortfall (service minus CFADS)."""
    rows: list[dict[str, Any]] = []
    for p in evidence_periods:
        if not isinstance(p, Mapping):
            continue
        idx = p.get("period_index")
        if isinstance(idx, bool) or not isinstance(idx, int):
            continue
        service = p.get("debt_service")
        due = _finite(service) and float(service) > DEBT_SERVICE_DUE_KEUR
        dscr = p.get("reported_dscr")
        base = p.get("base_cfads")
        bank = p.get("bank_cfads")
        rows.append({
            "period_index": idx, "date": dates.get(idx),
            "applicable": bool(due),
            "debt_service_keur": float(service) if _finite(service) else None,
            "principal_keur": float(p["principal"]) if _finite(p.get("principal")) else None,
            "interest_keur": float(p["interest"]) if _finite(p.get("interest")) else None,
            "base_cfads_keur": float(base) if _finite(base) else None,
            "bank_cfads_keur": float(bank) if _finite(bank) else None,
            "dscr": float(dscr) if (due and _finite(dscr)) else None,
            "bank_dscr": (float(bank) / float(service)) if (due and _finite(bank)) else None,
            "sizing_target_dscr": float(p["target_dscr"]) if _finite(p.get("target_dscr")) else None,
            "shortfall_keur": (float(service) - float(base)) if (due and _finite(base)) else None,
        })
    rows.sort(key=lambda r: r["period_index"])
    return rows


def _point(r: Mapping[str, Any]) -> dict[str, Any]:
    return {"period_index": r["period_index"], "date": r["date"], "dscr": r["dscr"], "base_cfads_keur": r["base_cfads_keur"],
            "debt_service_keur": r["debt_service_keur"], "principal_keur": r["principal_keur"], "interest_keur": r["interest_keur"],
            "shortfall_keur": r["shortfall_keur"]}


def _threshold_verdict(rows: Sequence[Mapping[str, Any]], term: Term, *, recorded: bool, reason: str, breach: str, ok: str) -> dict[str, Any]:
    base: dict[str, Any] = {"threshold_x": term.value, "threshold_raw": term.raw, "breaching_periods": [], "worst": None, "headroom": None}
    if not recorded:
        return {**base, "status": UNAVAILABLE, "reason": reason}
    if term.status == NOT_CONFIGURED:
        return {**base, "status": NOT_CONFIGURED, "reason": "No value is configured for this term in this Run. No default is assumed."}
    if term.status != CONFIGURED or term.value is None:
        return {**base, "status": UNAVAILABLE, "reason": "The saved value for this term is not a valid multiple."}
    applicable = [r for r in rows if r["applicable"]]
    if not applicable:
        return {**base, "status": NOT_APPLICABLE, "reason": "This Run has no period with scheduled Senior debt service."}
    usable = [r for r in applicable if r["dscr"] is not None]
    if not usable:
        return {**base, "status": UNAVAILABLE, "reason": "The Run persisted no DSCR for any period with scheduled debt service."}
    worst = min(usable, key=lambda r: r["dscr"])
    breaches = [r for r in usable if r["dscr"] < term.value]          # strict, raw doubles
    out = {**base, "worst": _point(worst), "headroom": headroom(worst["dscr"], term.value),
           "breaching_periods": [{**_point(r), "gap_x": term.value - r["dscr"]} for r in breaches]}
    if breaches:
        return {**out, "status": breach, "reason": ""}
    if len(usable) != len(applicable):
        return {**out, "status": UNAVAILABLE, "reason": "DSCR is missing for some periods with scheduled debt service, so compliance cannot be established."}
    return {**out, "status": ok, "reason": ""}


def evaluate(terms: RunTerms, rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """The three independent credit conclusions of one committed Run.  Coverage (< 1.00x) does not depend on either configured term."""
    applicable = [r for r in rows if r["applicable"]]
    usable = [r for r in applicable if r["dscr"] is not None]
    achieved: dict[str, Any]
    if not usable:
        achieved = {"available": False, "reason": ("This Run has no period with scheduled Senior debt service." if not applicable
                                                  else "The Run persisted no DSCR for any period with scheduled debt service."),
                    "min": None, "period": None}
    else:
        low = min(usable, key=lambda r: r["dscr"])
        achieved = {"available": True, "reason": "", "min": low["dscr"], "period": _point(low),
                    "tested_periods": len(usable), "applicable_periods": len(applicable)}
    bank_usable = [r for r in applicable if r["bank_dscr"] is not None]
    bank_low = min(bank_usable, key=lambda r: r["bank_dscr"]) if bank_usable else None

    deficits = [r for r in usable if r["dscr"] < 1.0]
    if not applicable:
        coverage = {"status": NOT_APPLICABLE, "reason": "This Run has no period with scheduled Senior debt service.", "periods": []}
    elif not usable:
        coverage = {"status": UNAVAILABLE, "reason": "The Run persisted no DSCR for any period with scheduled debt service.", "periods": []}
    elif deficits:
        coverage = {"status": COVERAGE_DEFICIENCY, "reason": "", "message": MESSAGE_COVERAGE, "periods": [_point(r) for r in deficits],
                    "total_shortfall_keur": math.fsum(r["shortfall_keur"] for r in deficits if r["shortfall_keur"] is not None)}
    elif len(usable) != len(applicable):
        coverage = {"status": UNAVAILABLE, "reason": "DSCR is missing for some periods with scheduled debt service.", "periods": []}
    else:
        coverage = {"status": COVERAGE_NO_DEFICIENCY, "reason": "", "periods": []}

    eod = _threshold_verdict(rows, terms.eod, recorded=terms.recorded, reason=terms.reason, breach=EOD_TRIGGERED, ok=EOD_NOT_TRIGGERED)
    cov = _threshold_verdict(rows, terms.contractual, recorded=terms.recorded, reason=terms.reason, breach=COV_BREACHED, ok=COV_COMPLIANT)
    if cov["status"] == COV_BREACHED:
        cov["message"] = MESSAGE_COVENANT
    if eod["status"] == EOD_TRIGGERED:
        eod["note"] = MESSAGE_EOD_NOTE
    return {
        "schema": SCHEMA, "basis": dict(TEST_BASIS), "terms_recorded": terms.recorded, "terms_reason": terms.reason,
        "achieved_min_dscr": achieved,
        "bank_case_min_dscr": ({"available": True, "min": bank_low["bank_dscr"], "period": {**_point(bank_low), "bank_dscr": bank_low["bank_dscr"]}}
                               if bank_low is not None else {"available": False, "min": None, "period": None}),
        "coverage": coverage, "eod": eod, "covenant": cov,
    }
