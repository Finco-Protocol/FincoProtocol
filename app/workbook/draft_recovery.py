"""Working Copy recovery diagnosis (read-only).

A Working Copy can hold a persisted draft that the canonical adapter refuses to materialise (for
example a negative CAPEX amount saved before the registry bound existed).  Every full-page and
projection builder then fails.  This module only DIAGNOSES such a draft: it never writes, never
corrects, clamps, rounds or discards a value, and never runs the model.  The owner repairs a value
through the existing authenticated Save routes (operation-bound CSRF + composite CAS).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Optional

RECOVERY_CODE = "WORKING_COPY_RECOVERY_REQUIRED"
_MAX_ISSUES = 25


@dataclass(frozen=True)
class RecoveryIssue:
    snapshot_key: str
    field_id: Optional[str]          # None => not a registry-editable scalar (cannot be repaired from the recovery view)
    label: str
    unit: str
    stored_value: str
    reason: str
    repairable: bool


@dataclass(frozen=True)
class DraftRecovery:
    issues: tuple[RecoveryIssue, ...]
    complete: bool                   # False when more problems may exist than were listed

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": RECOVERY_CODE,
            "message": ("This Working Copy contains saved input values the model cannot read. "
                        "Nothing was changed. Replace the listed value(s) to continue."),
            "complete": self.complete,
            "issues": [
                {"snapshot_key": i.snapshot_key, "field_id": i.field_id, "label": i.label, "unit": i.unit,
                 "stored_value": i.stored_value, "reason": i.reason, "repairable": i.repairable}
                for i in self.issues
            ],
        }


def _registry_by_snapshot_key() -> dict[str, Any]:
    from app.workbook.registry import WORKBOOK
    out: dict[str, Any] = {}
    for spec in WORKBOOK.all_fields():
        if spec.snapshot_key and spec.snapshot_key not in out:
            out[spec.snapshot_key] = spec
    return out


def _leading_key(message: str, known: Mapping[str, Any]) -> Optional[str]:
    token = message.strip().split(" ", 1)[0].rstrip(":")
    return token if token in known else None


def diagnose_draft(snapshot: Mapping[str, Any]) -> Optional[DraftRecovery]:
    """Return ``None`` when the adapter materialises the draft, else the invalid stored value(s).

    Works on a COPY: each already-reported key is neutralised in the copy only, to discover further
    independent problems.  The persisted draft is never touched.
    """
    from app.input_adapter import SnapshotInputError, build_projectinputs_from_snapshot

    known = _registry_by_snapshot_key()
    probe = dict(snapshot or {})
    issues: list[RecoveryIssue] = []
    seen: set[str] = set()
    complete = True
    for _ in range(_MAX_ISSUES):
        try:
            build_projectinputs_from_snapshot(dict(probe))
            break
        except (SnapshotInputError, ArithmeticError, ValueError) as exc:
            message = str(exc) or type(exc).__name__
            key = _leading_key(message, known) if isinstance(exc, SnapshotInputError) else None
            if key is None or key in seen:
                issues.append(RecoveryIssue(
                    snapshot_key=key or "", field_id=None, label="Model input", unit="",
                    stored_value="", reason=message[:300], repairable=False))
                complete = False
                break
            seen.add(key)
            spec = known[key]
            stored = snapshot.get(key)
            editable = bool(getattr(spec, "editable", False)) and getattr(
                getattr(spec, "binding_status", None), "name", "") == "BOUND"
            issues.append(RecoveryIssue(
                snapshot_key=key, field_id=spec.field_id if editable else None, label=spec.label,
                unit=getattr(spec, "unit", None) or "", stored_value="" if stored is None else str(stored),
                reason=message[:300], repairable=editable))
            probe[key] = ""          # copy only: look for further independent problems
    else:
        complete = False
    if not issues:
        return None
    return DraftRecovery(issues=tuple(issues), complete=complete)
