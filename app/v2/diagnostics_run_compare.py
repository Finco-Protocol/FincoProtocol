"""Diagnostics Run Comparison (read-only): diagnostics of two genuine committed Runs, side by side.

No comparison repository, KPI engine or new route: it reads the EXISTING immutable Run History (owner / project scoped), evaluates
each committed Run with the SAME checks (the Quality evaluation is injected by the existing adapter, the ``DX-*`` checks are pure) and
compares check by check. Nothing is mutated and no historical evidence is rewritten.

Comparison rules (pinned by tests):
* both Runs must evaluate the check (PASS / FAIL / WARNING) under the same methodology, else ``NOT_COMPARABLE`` with the reason of each
  side. A check missing or UNAVAILABLE in an older Run is NEVER read as resolved;
* RESOLVED / NEW / PERSISTENT / UNCHANGED_PASS are assigned only between two evaluated sides; residual change is a plain difference of
  the two measured residuals;
* thresholds are not bound to a historical Run, so covenant-type checks that need Working Copy terms are NOT_COMPARABLE.
"""
from __future__ import annotations

from types import SimpleNamespace
from typing import Any, Callable, Mapping, Optional

from app.v2.diagnostics_dx_checks import Facts, evaluate_advanced_checks

EVALUATED = ("PASS", "FAIL", "WARNING")
MAX_CANDIDATES = 4


def _ws_view(entry: Any) -> SimpleNamespace:
    """The committed payloads of ONE history entry under the attribute names the checks read."""
    return SimpleNamespace(
        last_financial_statements=getattr(entry, "financial_statements", None) or {},
        last_integrity_evidence=getattr(entry, "integrity_evidence", None) or {},
        last_distribution_schedule=getattr(entry, "distribution_schedule", None) or {},
        last_tax_schedule=getattr(entry, "tax_schedule", None) or {},
        last_runtime_summary=getattr(entry, "runtime_summary", None) or {},
        last_sponsor_schedule=getattr(entry, "sponsor_schedule", None) or {},
        last_runtime_snapshot_id=getattr(entry, "runtime_snapshot_id", None))


def _digest_ok(evidence: Mapping) -> bool:
    from app.run_integrity.evidence import evidence_digest
    try:
        return bool(evidence) and evidence.get("digest") == evidence_digest(dict(evidence))
    except Exception:  # noqa: BLE001 - malformed evidence is simply not intact
        return False


def evaluate_entry(entry: Any, quality_for_entry: Optional[Callable[[Any], Any]]) -> dict[str, dict[str, Any]]:
    """{check_id: {status, residual, reason}} for the QM checks (injected evaluator) and the DX checks of one committed Run."""
    rows: dict[str, dict[str, Any]] = {}
    if quality_for_entry is not None:
        try:
            report = quality_for_entry(entry)
            for c in report.checks:
                rows[c.check_id] = {"status": c.status.value, "residual": c.measured_value, "reason": c.reason_code or None, "family": "QM"}
        except Exception:  # noqa: BLE001 - one malformed Run must not hide the others
            pass
    ws = _ws_view(entry)
    try:
        for c in evaluate_advanced_checks(Facts.from_workspace(ws, digest_ok=_digest_ok(ws.last_integrity_evidence), reserve_regime=None)):
            rows[c["check_id"]] = {"status": c["status"], "residual": c["measured_value"], "reason": c["reason_code"], "family": "DX"}
    except Exception:  # noqa: BLE001
        pass
    return rows


def classify(a: Optional[Mapping], b: Optional[Mapping]) -> tuple[str, Optional[float], str]:
    """(classification, change in residual, reason) for one check; A = older Run, B = newer Run."""
    if a is None or b is None:
        return "NOT_COMPARABLE", None, "CHECK_NOT_EVALUATED_IN_BOTH_RUNS"
    if a["status"] not in EVALUATED or b["status"] not in EVALUATED:
        sides = []
        if a["status"] not in EVALUATED:
            sides.append(f"RUN_A_{a['status']}" + (f"({a['reason']})" if a.get("reason") else ""))
        if b["status"] not in EVALUATED:
            sides.append(f"RUN_B_{b['status']}" + (f"({b['reason']})" if b.get("reason") else ""))
        return "NOT_COMPARABLE", None, "; ".join(sides)
    bad_a, bad_b = a["status"] in ("FAIL", "WARNING"), b["status"] in ("FAIL", "WARNING")
    delta = (b["residual"] - a["residual"]) if (isinstance(a.get("residual"), (int, float)) and isinstance(b.get("residual"), (int, float))) else None
    if bad_a and not bad_b:
        return "RESOLVED", delta, ""
    if bad_b and not bad_a:
        return "NEW", delta, ""
    if bad_a and bad_b:
        return "PERSISTENT", delta, ""
    return "UNCHANGED_PASS", delta, ""


def _identity(entry: Any) -> dict[str, Any]:
    return {"history_id": entry.history_id, "ran_at": entry.ran_at, "snapshot_id": entry.runtime_snapshot_id,
            "composite_hash": entry.composite_hash, "scenario_id": entry.last_runtime_scenario_id,
            "scenario_name": entry.active_scenario_name, "engine_version": entry.engine_version}


def qualifications(entry_a: Any, entry_b: Any) -> list[dict[str, str]]:
    """What limits the comparability of two committed Runs. Never changes a classification: it states the limit beside it."""
    out: list[dict[str, str]] = []
    ea, eb = getattr(entry_a, "engine_version", None), getattr(entry_b, "engine_version", None)
    if not ea or not eb:
        out.append({"code": "ENGINE_VERSION_UNKNOWN", "message": "The engine version is not recorded for "
                    + " and ".join(n for n, v in (("Run A", ea), ("Run B", eb)) if not v)
                    + ": the two Runs cannot be shown to have been produced by the same engine."})
    elif ea != eb:
        out.append({"code": "ENGINE_VERSION_DIFFERS", "message": f"Run A was produced by engine {ea} and Run B by engine {eb}: differences may "
                    "come from the engine, not only from inputs."})
    sa, sb = getattr(entry_a, "last_runtime_scenario_id", None), getattr(entry_b, "last_runtime_scenario_id", None)
    if sa != sb:
        out.append({"code": "DIFFERENT_SCENARIO_CONTEXT", "message": "The two Runs belong to different scenario contexts: the comparison is "
                    "between scenarios, not between two Runs of the same inputs."})
    return out


def build_run_comparison(ws: Any, *, quality_for_entry: Optional[Callable[[Any], Any]] = None, limit: int = MAX_CANDIDATES) -> dict[str, Any]:
    """Each of the previous committed Runs of this project against the Last Run, from the immutable Run History."""
    try:
        from app.persistence.run_history_repository import get_run_history          # read-only
        entries = get_run_history(ws.user_id, ws.project_id, limit=limit + 6)
    except Exception:  # noqa: BLE001
        return {"available": False, "reason": "RUN_HISTORY_UNAVAILABLE"}
    last_id = getattr(ws, "last_runtime_snapshot_id", None)
    newest = next((e for e in entries if e.runtime_snapshot_id == last_id), None)
    if newest is None:
        return {"available": False, "reason": "LAST_RUN_NOT_IN_RUN_HISTORY"}
    older = [e for e in entries if e.history_id != newest.history_id and (e.ran_at, e.history_id) < (newest.ran_at, newest.history_id)][:limit]
    if not older:
        return {"available": False, "reason": "NEED_AT_LEAST_TWO_COMMITTED_RUNS", "last_run": _identity(newest)}
    new_rows = evaluate_entry(newest, quality_for_entry)
    candidates = []
    for entry in older:
        old_rows = evaluate_entry(entry, quality_for_entry)
        rows = []
        for check_id in sorted(set(new_rows) | set(old_rows)):
            a, b = old_rows.get(check_id), new_rows.get(check_id)
            kind, delta, reason = classify(a, b)
            rows.append({"check_id": check_id, "family": (b or a or {}).get("family"), "classification": kind, "reason": reason,
                         "run_a": None if a is None else {"status": a["status"], "residual": a["residual"]},
                         "run_b": None if b is None else {"status": b["status"], "residual": b["residual"]},
                         "residual_change": delta})
        counts: dict[str, int] = {}
        for r in rows:
            counts[r["classification"]] = counts.get(r["classification"], 0) + 1
        quals = qualifications(entry, newest)
        for r in rows:
            r["qualified"] = bool(quals) and r["classification"] != "NOT_COMPARABLE"
        candidates.append({"run_a": _identity(entry), "counts": counts, "rows": rows, "qualifications": quals})
    return {"available": True, "run_b": _identity(newest), "candidates": candidates,
            "rules": "Run A is an earlier committed Run, Run B the Last Run. A check that is missing or UNAVAILABLE on either side is NOT_COMPARABLE, never "
                     "'resolved'. Historical evidence is never mutated; thresholds are not bound to historical Runs."}


__all__ = ["build_run_comparison", "classify", "evaluate_entry", "qualifications"]
