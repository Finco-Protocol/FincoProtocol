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
_PAGE_HANDLED_PREFIXES = ("QUARTERLY_",)
BOOK_FIELD_ID = "revenue.multistream.contracts"
BOOK_SNAPSHOT_KEY = "rev_multistream_config_json"
# Typed refusals that originate in the stored revenue contract book (R04 cap/quantity/date rules, v2 contract grammar).  The book is a
# single document with ONE canonical writer (the revenue contracts route); a stored book that no longer validates is repairable there.
_BOOK_ERROR_PREFIXES = ("R04_", "REVENUE_V2", "REVENUE_V3", "REVENUE_STREAM", "DATE_AUTHORITY_")


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
            if message.split(":", 1)[0].startswith(_PAGE_HANDLED_PREFIXES):
                # A typed scope refusal (RC-7B 3/3 selection) is rendered in place by the existing pages and
                # refused by the Run; it is not an unreadable draft and must keep its own handling.
                break
            key = _leading_key(message, known) if isinstance(exc, SnapshotInputError) else None
            if (key is None and BOOK_SNAPSHOT_KEY not in seen and str(probe.get(BOOK_SNAPSHOT_KEY) or "").strip()
                    and message.startswith(_BOOK_ERROR_PREFIXES)):
                # The stored contract book itself is invalid (for example over the global P50 cap): offer the canonical book writer as the
                # repair path.  Nothing is clipped, reallocated or deleted; the replacement book is validated as a whole by the writer.
                seen.add(BOOK_SNAPSHOT_KEY)
                issues.append(RecoveryIssue(
                    snapshot_key=BOOK_SNAPSHOT_KEY, field_id=BOOK_FIELD_ID, label="Revenue contract book", unit="contract book (JSON)",
                    stored_value=str(snapshot.get(BOOK_SNAPSHOT_KEY) or ""), reason=message[:300], repairable=True))
                probe[BOOK_SNAPSHOT_KEY] = ""      # copy only: look for further independent problems
                continue
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
