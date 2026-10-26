"""D-029 reconciliation classification, release-closed pending owner decisions.

No endpoint imports this yet. Security checks must precede these functions.
No financial execution, input materialization or persistence writer lives here.
"""
from dataclasses import dataclass

from app.persistence.run_history_repository import get_run_history_entry
from app.persistence.run_intent_repository import SubmittedIntent, lookup


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


@dataclass(frozen=True)
class IntentOutcome:
    kind: str
    history_id: str | None = None
    error_code: str | None = None


def reconcile(intent: SubmittedIntent) -> IntentOutcome:
    """Historical truth independent of today's draft hash/Last Run.

    Does not grant access: caller must enforce current session/project access,
    protected-reference and Run-CSRF policies before lookup. The history query
    repeats immutable actor/project scope, never asks for latest history.
    """
    row = lookup(intent)
    if row is None:
        return IntentOutcome("NEW")
    if row.state == "COMMITTED":
        entry = get_run_history_entry(intent.actor_id, intent.project_id, row.history_id)
        if entry is None:
            # Retention/history loss cannot reopen a successfully-used key.
            return IntentOutcome("HISTORY_UNAVAILABLE", error_code="RUN_INTENT_HISTORY_UNAVAILABLE")
        return IntentOutcome("REPLAYED", history_id=entry.history_id)
    if row.state == "FAILED":
        return IntentOutcome("FAILED", error_code=row.error_code)
    return IntentOutcome("IN_PROGRESS")
