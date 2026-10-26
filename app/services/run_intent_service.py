"""D-029 Run intent lifecycle used by the canonical ``POST /v2/workbook/run`` route.

Authorization, the Run CSRF and protected-reference refusal belong to the caller and
precede every function here; an intent id is never authorization.  This module
performs no calculation, no input materialization and no financial persistence: the
committed finalization joins ``v2_atomic_run_commit``'s own transaction
(``run_intent_repository.finalize_cursor``).

Release state: the lifecycle is wired but only engaged when a caller submits a
``run_intent_id`` (optional migration; no key keeps the released non-idempotent
behavior).  Owner policy decisions remain open (see D029_OWNER_DECISION_REGISTER.md).
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from typing import Any, Mapping

from app.persistence.run_history_repository import get_run_history_entry
from app.persistence.run_intent_repository import (
    Reservation, RunIntentError, SubmittedIntent, fail as _fail, frozen_fingerprint,
    lookup, reserve, start as _start, validate_key,
)

# The model executor timeout is capped at 900 s; the lease must outlive the longest
# permitted calculation plus the final commit or a legitimate owner would be fenced.
LEASE_MS = (900 + 120) * 1000
EXECUTION_CONTRACT = "v2_workbook_run:finco-run-intent-v1"


@dataclass(frozen=True)
class RunIntentPolicy:
    # Enabling is intentionally not an environment variable / rollout shortcut.
    # Final policy approval and canonical integration acceptance are outstanding.
    enabled: bool = False
    missing_key_behavior: str = "RELEASED_NON_IDEMPOTENT"
    in_progress_wait_ms: int = 0
    failed_retry_behavior: str = "NEW_INTENT_REQUIRED"
    expired_retry_behavior: str = "EXPLICIT_FENCED_RECOVERY_ONLY"
    retention_behavior: str = "NO_AUTOMATIC_DELETION_OR_KEY_REUSE"


RELEASE_POLICY = RunIntentPolicy()

#: Typed outcomes a client may receive (``X-Finco-Run-Outcome`` / JSON ``outcome``).
OUTCOMES = ("COMMITTED", "REPLAYED", "IN_PROGRESS", "FAILED", "CONFLICT", "HISTORY_UNAVAILABLE",
            "INVALID", "EXPIRED", "REFUSED", "UNAVAILABLE")


@dataclass(frozen=True)
class Decision:
    """What the route does next.  ``kind == 'NEW'`` is the only non-terminal value."""
    kind: str
    intent: SubmittedIntent | None = None
    history_id: str | None = None
    snapshot_id: str | None = None
    error_code: str | None = None
    message: str = ""

    @property
    def terminal(self) -> bool:
        return self.kind != "NEW"


_MESSAGES = {
    "REPLAYED": "This Run was already committed; its original result is returned. Nothing was recalculated.",
    "IN_PROGRESS": "This Run is already in progress. No second calculation was started.",
    "FAILED": "This Run attempt failed and cannot be reused. Start a new Run to try again.",
    "CONFLICT": "This Run key was already used with different original inputs. Nothing was run.",
    "HISTORY_UNAVAILABLE": "This Run was committed but its history record is unavailable. It was not recalculated.",
    "INVALID": "The Run key is not valid. Nothing was run.",
    "EXPIRED": "A previous attempt with this Run key did not finish and requires approved recovery. Nothing was run.",
    "UNAVAILABLE": "Run reconciliation is unavailable. Nothing was run.",
}


def _decide_existing(row: Reservation, intent: SubmittedIntent) -> Decision:
    if row.state == "COMMITTED":
        entry = None
        try:
            entry = get_run_history_entry(intent.actor_id, intent.project_id, row.history_id)
        except Exception:  # noqa: BLE001 - malformed stored history fails closed, never recalculates
            entry = None
        if entry is None or not getattr(entry, "history_id", None) or not getattr(entry, "runtime_snapshot_id", None):
            return Decision("HISTORY_UNAVAILABLE", intent, error_code="RUN_INTENT_HISTORY_UNAVAILABLE",
                            message=_MESSAGES["HISTORY_UNAVAILABLE"])
        return Decision("REPLAYED", intent, history_id=entry.history_id, snapshot_id=entry.runtime_snapshot_id,
                        message=_MESSAGES["REPLAYED"])
    if row.state == "FAILED":
        return Decision("FAILED", intent, error_code=row.error_code, message=_MESSAGES["FAILED"])
    # RESERVED / RUNNING.  An expired lease needs the approved fenced recovery: fail closed.
    from app.persistence.run_intent_repository import _now  # shared DB clock
    from app.persistence.db import get_connection
    conn = get_connection()
    try:
        now = _now(conn)
    finally:
        conn.close()
    if row.lease_until_ms <= now:
        return Decision("EXPIRED", intent, error_code="RUN_INTENT_EXPIRED_ACTIVE", message=_MESSAGES["EXPIRED"])
    return Decision("IN_PROGRESS", intent, message=_MESSAGES["IN_PROGRESS"])


def decide(*, actor_id: str, project_id: str, run_intent_id: str, workbook_version: str, content_hash: str,
           protected_reference: bool, refused_message: str = "") -> Decision:
    """Classify a submitted key BEFORE today's CAS, using the ORIGINAL submitted binding.

    Order: key syntax -> protected-reference refusal -> ledger lookup.  A committed key
    never bypasses the protected-reference refusal (the caller already enforced access/CSRF).
    """
    try:
        validate_key(run_intent_id)
        intent = SubmittedIntent(actor_id, project_id, run_intent_id, workbook_version, content_hash)
    except RunIntentError:
        return Decision("INVALID", error_code="RUN_INTENT_INVALID", message=_MESSAGES["INVALID"])
    if protected_reference:
        return Decision("REFUSED", intent, error_code="PROTECTED_REFERENCE", message=refused_message)
    try:
        row = lookup(intent)
    except RunIntentError as exc:
        if exc.code == "RUN_INTENT_CONFLICT":
            return Decision("CONFLICT", intent, error_code=exc.code, message=_MESSAGES["CONFLICT"])
        return Decision("UNAVAILABLE", intent, error_code=exc.code, message=_MESSAGES["UNAVAILABLE"])
    if row is None:
        return Decision("NEW", intent)
    return _decide_existing(row, intent)


@dataclass(frozen=True)
class IntentOutcome:
    kind: str
    history_id: str | None = None
    error_code: str | None = None


def reconcile(intent: SubmittedIntent) -> IntentOutcome:
    """Pure ledger classification, independent of today's draft hash / Last Run.

    Grants no access: the route enforces session, project, protected-reference and
    Run-CSRF policy before it asks.  The history query repeats the immutable
    actor/project scope and never asks for "latest history".  Lease expiry is the
    route's concern (``decide``); this keeps the released ledger contract.
    """
    row = lookup(intent)
    if row is None:
        return IntentOutcome("NEW")
    if row.state == "COMMITTED":
        entry = get_run_history_entry(intent.actor_id, intent.project_id, row.history_id)
        if entry is None:
            return IntentOutcome("HISTORY_UNAVAILABLE", error_code="RUN_INTENT_HISTORY_UNAVAILABLE")
        return IntentOutcome("REPLAYED", history_id=entry.history_id)
    if row.state == "FAILED":
        return IntentOutcome("FAILED", error_code=row.error_code)
    return IntentOutcome("IN_PROGRESS")


def effective_identity(override: Any, *, composite_hash: str, scenario_id: str | None,
                       runtime_project_key: str, scenario_overrides: Mapping[str, Any] | None) -> dict[str, Any]:
    """Digest of the SAME effective inputs the canonical Run is about to execute (no second materialization)."""
    import dataclasses

    def _digest(value: Any) -> str:
        return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                         default=repr, allow_nan=True).encode("utf-8")).hexdigest()

    inputs = dataclasses.asdict(override) if dataclasses.is_dataclass(override) else override
    return {"effective_input": {"inputs_sha256": _digest(inputs), "composite_hash": composite_hash,
                                "runtime_project_key": runtime_project_key},
            "line_override": {"scenario_overrides_sha256": _digest(dict(scenario_overrides or {}))},
            "scenario_id": scenario_id}


def reserve_and_start(intent: SubmittedIntent, identity: Mapping[str, Any]) -> tuple[Decision, Reservation | None]:
    """Freeze the fingerprint, take the durable claim and mark it RUNNING.

    A concurrent winner (or any pre-existing state) is returned as a terminal decision;
    only the unique acquirer receives a reservation and may execute the engine.
    """
    try:
        fingerprint = frozen_fingerprint(
            intent, scenario_id=identity["scenario_id"], effective_input_identity=identity["effective_input"],
            line_override_identity=identity["line_override"], execution_contract=EXECUTION_CONTRACT)
        reservation, acquired = reserve(intent, fingerprint, lease_ms=LEASE_MS)
        if not acquired:
            return _decide_existing(reservation, intent), None
        return Decision("NEW", intent), _start(reservation)
    except RunIntentError as exc:
        if exc.code in ("RUN_INTENT_CONFLICT",):
            return Decision("CONFLICT", intent, error_code=exc.code, message=_MESSAGES["CONFLICT"]), None
        return Decision("UNAVAILABLE", intent, error_code=exc.code, message=_MESSAGES["UNAVAILABLE"]), None


def mark_failed(reservation: Reservation | None, code: str) -> None:
    """Terminal same-intent failure; never raises into the user response path."""
    if reservation is None:
        return
    try:
        _fail(reservation, code)
    except RunIntentError:
        # Ownership already lost or the intent is already terminal: leave the ledger untouched.
        pass


def committed_decision(intent: SubmittedIntent) -> Decision:
    """After the atomic commit, read back the exact immutable history id bound to the intent."""
    row = lookup(intent)
    if row is None or row.state != "COMMITTED":
        return Decision("UNAVAILABLE", intent, error_code="RUN_INTENT_NOT_FINALIZED", message=_MESSAGES["UNAVAILABLE"])
    entry = get_run_history_entry(intent.actor_id, intent.project_id, row.history_id)
    if entry is None:
        return Decision("HISTORY_UNAVAILABLE", intent, error_code="RUN_INTENT_HISTORY_UNAVAILABLE",
                        message=_MESSAGES["HISTORY_UNAVAILABLE"])
    return Decision("COMMITTED", intent, history_id=entry.history_id, snapshot_id=entry.runtime_snapshot_id)


#: HTTP status per typed outcome for JSON clients (the HTMX transport stays 200 + header).
STATUS = {"COMMITTED": 200, "REPLAYED": 200, "IN_PROGRESS": 409, "FAILED": 409, "CONFLICT": 409,
          "HISTORY_UNAVAILABLE": 409, "INVALID": 422, "EXPIRED": 409, "REFUSED": 409, "UNAVAILABLE": 503}


def payload(decision: Decision, outcome: str | None = None) -> dict[str, Any]:
    kind = outcome or decision.kind
    return {"ok": kind in ("COMMITTED", "REPLAYED"), "outcome": kind,
            "run_intent_id": decision.intent.run_intent_id if decision.intent else None,
            "history_id": decision.history_id, "runtime_snapshot_id": decision.snapshot_id,
            "error_code": decision.error_code, "message": decision.message}


def headers(decision: Decision, outcome: str | None = None) -> dict[str, str]:
    out = {"X-Finco-Run-Outcome": outcome or decision.kind, "Cache-Control": "no-store"}
    if decision.intent:
        out["X-Finco-Run-Intent"] = decision.intent.run_intent_id
    if decision.history_id:
        out["X-Finco-Run-History-Id"] = decision.history_id
    if decision.snapshot_id:
        out["X-Finco-Run-Snapshot-Id"] = decision.snapshot_id
    return out
