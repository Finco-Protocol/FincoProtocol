"""D-029 durable reservation primitives; not yet wired into the Run route.

Authorization, Run CSRF and protected-reference checks belong to the caller.
This module never executes the engine, promotes Last Run, or inserts history.
``finalize_cursor`` must join the existing canonical financial transaction.
There is deliberately no cleanup/reuse operation for successful intent keys.
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
import hashlib
import json
import re
import sqlite3
from typing import Any, Mapping
import uuid

from app.persistence.db import get_connection

CONTRACT = "finco-run-intent-v1"


class RunIntentError(Exception):
    """Typed refusal; never evidence of a committed financial result."""

    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def validate_key(value: str) -> str:
    if not isinstance(value, str) or len(value) != 36:
        raise RunIntentError("RUN_INTENT_INVALID")
    try:
        parsed = uuid.UUID(value)
    except ValueError:
        raise RunIntentError("RUN_INTENT_INVALID") from None
    if parsed.version != 4 or parsed.variant != uuid.RFC_4122 or str(parsed) != value:
        raise RunIntentError("RUN_INTENT_INVALID")
    return value


def canonical_digest(value: Mapping[str, Any]) -> str:
    """Stable JSON authority; rejects non-finite numbers and unsupported types."""
    encoded = json.dumps(dict(value), sort_keys=True, separators=(",", ":"),
                         ensure_ascii=True, allow_nan=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class SubmittedIntent:
    actor_id: str
    project_id: str
    run_intent_id: str
    workbook_version: str
    content_hash: str

    def __post_init__(self):
        validate_key(self.run_intent_id)
        for value in (self.actor_id, self.project_id, self.workbook_version, self.content_hash):
            if not isinstance(value, str) or not value or len(value) > 256:
                raise RunIntentError("RUN_INTENT_BINDING_INVALID")

    @property
    def binding(self) -> str:
        # This ORIGINAL submitted authority is available before today's CAS.
        # Do not recompute the frozen effective fingerprint from today's draft
        # when reconciling an already-committed intent after an edit/newer Run.
        return canonical_digest({"contract": CONTRACT, "actor": self.actor_id,
                                 "project": self.project_id,
                                 "workbook_version": self.workbook_version,
                                 "content_hash": self.content_hash})


def frozen_fingerprint(intent: SubmittedIntent, *, scenario_id: str | None,
                       effective_input_identity: Mapping[str, Any],
                       line_override_identity: Mapping[str, Any],
                       execution_contract: str) -> str:
    """Called only after released initial CAS/materialization; no engine call.

    The integration must supply the SAME effective authority used by the
    canonical Run. This helper does not invent a second materialization path.
    """
    if not execution_contract or not effective_input_identity:
        raise RunIntentError("RUN_INTENT_FINGERPRINT_INVALID")
    return canonical_digest({"contract": CONTRACT, "submitted": intent.binding,
                             "scenario_id": scenario_id,
                             "effective_input": dict(effective_input_identity),
                             "lines_and_overrides": dict(line_override_identity),
                             "execution_contract": execution_contract})


@dataclass(frozen=True)
class Reservation:
    reservation_id: str
    state: str
    generation: int
    owner_nonce: str
    fingerprint: str
    lease_until_ms: int
    history_id: str | None
    error_code: str | None


_SCHEMA = """
CREATE TABLE IF NOT EXISTS model_run_intents (
 reservation_id TEXT PRIMARY KEY,
 actor_id TEXT NOT NULL,
 project_id TEXT NOT NULL,
 run_intent_id TEXT NOT NULL,
 submitted_binding TEXT NOT NULL,
 request_fingerprint TEXT NOT NULL,
 workbook_version TEXT NOT NULL,
 content_hash TEXT NOT NULL,
 state TEXT NOT NULL CHECK (state IN ('RESERVED','RUNNING','FAILED','COMMITTED')),
 generation INTEGER NOT NULL CHECK (generation >= 1),
 owner_nonce TEXT NOT NULL,
 lease_until_ms INTEGER NOT NULL,
 created_at_ms INTEGER NOT NULL,
 updated_at_ms INTEGER NOT NULL,
 history_id TEXT UNIQUE,
 error_code TEXT,
 UNIQUE (actor_id, project_id, run_intent_id),
 CHECK ((state = 'COMMITTED' AND history_id IS NOT NULL AND error_code IS NULL)
     OR (state <> 'COMMITTED' AND history_id IS NULL)),
 CHECK ((state = 'FAILED' AND error_code IS NOT NULL)
     OR (state <> 'FAILED' AND error_code IS NULL))
);
CREATE TRIGGER IF NOT EXISTS model_run_intents_identity_immutable
BEFORE UPDATE ON model_run_intents
WHEN NEW.reservation_id IS NOT OLD.reservation_id
 OR NEW.actor_id IS NOT OLD.actor_id OR NEW.project_id IS NOT OLD.project_id
 OR NEW.run_intent_id IS NOT OLD.run_intent_id
 OR NEW.submitted_binding IS NOT OLD.submitted_binding
 OR NEW.request_fingerprint IS NOT OLD.request_fingerprint
 OR NEW.workbook_version IS NOT OLD.workbook_version
 OR NEW.content_hash IS NOT OLD.content_hash
 OR NEW.created_at_ms IS NOT OLD.created_at_ms
 OR OLD.state IN ('COMMITTED','FAILED')
 OR NEW.generation < OLD.generation
 OR NEW.generation > OLD.generation + 1
 OR (NEW.generation = OLD.generation AND NEW.owner_nonce IS NOT OLD.owner_nonce)
 OR (NEW.generation > OLD.generation AND
     (NEW.state <> 'RESERVED' OR NEW.owner_nonce = OLD.owner_nonce))
BEGIN SELECT RAISE(ABORT, 'RUN_INTENT_IMMUTABLE'); END;
CREATE TRIGGER IF NOT EXISTS model_run_intents_no_delete
BEFORE DELETE ON model_run_intents
BEGIN SELECT RAISE(ABORT, 'RUN_INTENT_RETENTION_NOT_APPROVED'); END;
"""


def install_schema(connection: sqlite3.Connection) -> None:
    """Additive, repeatable migration. Explicit until application wiring lands.

    executescript commits an existing transaction; refuse that situation rather
    than accidentally splitting a caller's financial transaction.
    """
    if connection.in_transaction:
        raise RunIntentError("RUN_INTENT_MIGRATION_IN_TRANSACTION")
    try:
        connection.executescript("BEGIN IMMEDIATE;\n" + _SCHEMA)
        verify_schema(connection)
        connection.commit()
    except BaseException:
        connection.rollback()
        raise


def _normalize_schema(sql: str) -> str:
    return re.sub(r"\s+", " ", sql.replace("IF NOT EXISTS ", "")).strip().rstrip(";")


def verify_schema(connection: sqlite3.Connection) -> None:
    """Fail closed if a unique constraint, state check or fence trigger is lost.

    IF NOT EXISTS alone would silently accept an incompatible preexisting
    table/trigger. Compare this small isolated schema, not financial schemas.
    """
    statements = re.split(r"(?=CREATE (?:TABLE|TRIGGER))", _SCHEMA)
    for statement in statements:
        if not statement.strip():
            continue
        name = re.search(r"CREATE (?:TABLE|TRIGGER) IF NOT EXISTS (\w+)", statement).group(1)
        row = connection.execute("SELECT sql FROM sqlite_master WHERE name=?", (name,)).fetchone()
        if row is None or _normalize_schema(row[0]) != _normalize_schema(statement):
            raise RunIntentError("RUN_INTENT_SCHEMA_INVALID")


def _now(connection) -> int:
    # Shared DB clock; generation, not wall time, is the fencing authority.
    return connection.execute(
        "SELECT CAST((julianday('now') - 2440587.5) * 86400000 AS INTEGER)"
    ).fetchone()[0]


def _decode(row) -> Reservation:
    return Reservation(row["reservation_id"], row["state"], row["generation"],
                       row["owner_nonce"], row["request_fingerprint"],
                       row["lease_until_ms"], row["history_id"], row["error_code"])


def _find(connection, intent: SubmittedIntent):
    row = connection.execute(
        "SELECT * FROM model_run_intents WHERE actor_id=? AND project_id=? AND run_intent_id=?",
        (intent.actor_id, intent.project_id, intent.run_intent_id),
    ).fetchone()
    if row is not None and row["submitted_binding"] != intent.binding:
        raise RunIntentError("RUN_INTENT_CONFLICT")
    return row


@contextmanager
def _write():
    conn = get_connection()
    try:
        conn.execute("BEGIN IMMEDIATE")
        verify_schema(conn)
        yield conn
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    finally:
        conn.close()


def lookup(intent: SubmittedIntent) -> Reservation | None:
    """Read original binding before current CAS; never replays today's Last Run."""
    conn = get_connection()
    try:
        verify_schema(conn)
        row = _find(conn, intent)
        return _decode(row) if row is not None else None
    finally:
        conn.close()


def reserve(intent: SubmittedIntent, fingerprint: str, *, lease_ms: int) -> tuple[Reservation, bool]:
    """One unique cross-process claim. Existing state is never overwritten.

    Return (reservation, acquired). Existing expired reservations still require
    explicit recover(), after the caller has applied the approved policy/CAS.
    """
    if not isinstance(lease_ms, int) or isinstance(lease_ms, bool) or not 1000 <= lease_ms <= 3_600_000:
        raise RunIntentError("RUN_INTENT_LEASE_INVALID")
    if not isinstance(fingerprint, str) or len(fingerprint) != 64 or any(c not in "0123456789abcdef" for c in fingerprint):
        raise RunIntentError("RUN_INTENT_FINGERPRINT_INVALID")
    with _write() as conn:
        now = _now(conn)
        cur = conn.execute(
            """INSERT INTO model_run_intents VALUES (?,?,?,?,?,?,?,?, 'RESERVED',1,?,?,?,?,NULL,NULL)
               ON CONFLICT(actor_id, project_id, run_intent_id) DO NOTHING""",
            (uuid.uuid4().hex, intent.actor_id, intent.project_id, intent.run_intent_id,
             intent.binding, fingerprint, intent.workbook_version, intent.content_hash,
             uuid.uuid4().hex, now + lease_ms, now, now),
        )
        row = _find(conn, intent)
        if row["request_fingerprint"] != fingerprint:
            raise RunIntentError("RUN_INTENT_CONFLICT")
        return _decode(row), cur.rowcount == 1


def require_owner_cursor(cursor, reservation: Reservation, *, running: bool = True) -> Reservation:
    """Fence inside the caller's existing financial transaction BEFORE writes."""
    if not cursor.connection.in_transaction:
        raise RunIntentError("RUN_INTENT_TRANSACTION_REQUIRED")
    verify_schema(cursor.connection)
    row = cursor.execute("SELECT * FROM model_run_intents WHERE reservation_id=?",
                         (reservation.reservation_id,)).fetchone()
    if (row is None or row["generation"] != reservation.generation
            or row["owner_nonce"] != reservation.owner_nonce
            or row["request_fingerprint"] != reservation.fingerprint
            or row["state"] not in (("RUNNING",) if running else ("RESERVED", "RUNNING"))
            or row["lease_until_ms"] <= _now(cursor.connection)):
        raise RunIntentError("RUN_INTENT_OWNERSHIP_LOST")
    return _decode(row)


def start(reservation: Reservation) -> Reservation:
    with _write() as conn:
        current = require_owner_cursor(conn.cursor(), reservation, running=False)
        if current.state != "RESERVED":
            raise RunIntentError("RUN_INTENT_ALREADY_RUNNING")
        conn.execute("UPDATE model_run_intents SET state='RUNNING', updated_at_ms=? WHERE reservation_id=?",
                     (_now(conn), reservation.reservation_id))
        return _decode(conn.execute("SELECT * FROM model_run_intents WHERE reservation_id=?",
                                    (reservation.reservation_id,)).fetchone())


def recover(intent: SubmittedIntent, fingerprint: str, *, lease_ms: int) -> Reservation:
    """Explicit expired-lease takeover. Does NOT guarantee one engine execution.

    No automatic recovery is wired/enabled. Caller must check approved recovery
    policy and current CAS first. The old owner can never finalize generation+1.
    """
    if not isinstance(lease_ms, int) or isinstance(lease_ms, bool) or not 1000 <= lease_ms <= 3_600_000:
        raise RunIntentError("RUN_INTENT_LEASE_INVALID")
    with _write() as conn:
        row = _find(conn, intent)
        if row is None or row["request_fingerprint"] != fingerprint:
            raise RunIntentError("RUN_INTENT_CONFLICT")
        now = _now(conn)
        if row["state"] not in ("RESERVED", "RUNNING") or row["lease_until_ms"] > now:
            raise RunIntentError("RUN_INTENT_NOT_RECOVERABLE")
        if row["generation"] >= 2**63 - 1:
            raise RunIntentError("RUN_INTENT_GENERATION_EXHAUSTED")
        conn.execute("""UPDATE model_run_intents SET state='RESERVED', generation=generation+1,
                        owner_nonce=?, lease_until_ms=?, updated_at_ms=? WHERE reservation_id=?""",
                     (uuid.uuid4().hex, now + lease_ms, now, row["reservation_id"]))
        return _decode(_find(conn, intent))


def fail(reservation: Reservation, error_code: str) -> None:
    """Terminal same-intent failure. A deliberate new Run uses a NEW key."""
    if error_code not in {"ADMISSION_REFUSED", "ENGINE_FAILED", "ENGINE_TIMEOUT",
                          "FINANCIAL_REFUSED", "FINAL_CAS_CONFLICT", "CANCELLED"}:
        raise RunIntentError("RUN_INTENT_ERROR_INVALID")
    with _write() as conn:
        require_owner_cursor(conn.cursor(), reservation, running=False)
        conn.execute("UPDATE model_run_intents SET state='FAILED', error_code=?, updated_at_ms=? WHERE reservation_id=?",
                     (error_code, _now(conn), reservation.reservation_id))


def finalize_cursor(cursor, reservation: Reservation, history_id: str) -> None:
    """Bind canonical history AFTER its append, BEFORE the caller's COMMIT.

    Does not commit/rollback the caller's transaction. Any refusal must propagate
    and roll back Last Run/history together. No independent financial writer.
    """
    require_owner_cursor(cursor, reservation)
    row = cursor.execute("""SELECT i.actor_id, i.project_id, i.workbook_version, i.content_hash,
                                  h.user_id, h.project_id, h.workbook_version, h.composite_hash
                           FROM model_run_intents i JOIN model_run_history h ON h.history_id=?
                           WHERE i.reservation_id=?""",
                         (history_id, reservation.reservation_id)).fetchone()
    if row is None or tuple(row[:4]) != tuple(row[4:]):
        raise RunIntentError("RUN_INTENT_HISTORY_MISMATCH")
    cursor.execute("UPDATE model_run_intents SET state='COMMITTED', history_id=?, updated_at_ms=? WHERE reservation_id=?",
                   (history_id, _now(cursor.connection), reservation.reservation_id))
