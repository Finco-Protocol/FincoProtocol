"""FINCO 37 Batch 4 — Slice B (C1F-A-2 / A16): durable minimal append-only import receipt repository.

Stores ONLY privacy-preserving transaction metadata and hash lineage inside the same
``BEGIN EXCLUSIVE`` transaction as the canonical ``WorkbookUpdateService.apply_batch_draft_update``:
- opaque versioned receipt ID (``imp_v1_<32hex>``)
- owner / actor / project / scenario scope
- SHA-256 of original uploaded bytes & source format (``csv`` / ``xlsx``)
- approval event ID, event label, approved_at & committed_at UTC timestamps
- workbook version, before & committed after composite hashes
- allowlisted canonical field IDs (approved & changed) and counts
- canonical approval binding digest & unique replay key

NEVER persists workbook bytes, filenames, paths, client names, sheet/cell contents or addresses,
free-text labels/correction notes, source/approved values, raw tickets, tokens, formulas, or secrets.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import re
import sqlite3
from typing import Any, Sequence
import uuid

from app.persistence.db import get_connection
from app.workbook.registry import WORKBOOK

CONTRACT_VERSION = "finco-import-receipt-v1"
_HEX64_RE = re.compile(r"^[0-9a-f]{64}$")
_ALLOWED_FORMATS = frozenset({"csv", "xlsx", "unknown"})


class ImportReceiptError(ValueError):
    """Typed refusal for durable import receipt validation, replay, or persistence failure."""

    def __init__(self, code: str, message: str = ""):
        self.code = code
        super().__init__(f"{code}: {message}" if message else code)


@dataclass(frozen=True)
class ImportReceiptRecord:
    receipt_id: str
    contract_version: str
    owner_id: str
    actor_id: str
    project_id: str
    scenario_id: str
    replay_key: str
    source_sha256: str
    source_format: str
    approval_event_id: str
    approval_event: str
    approved_at: str
    committed_at: str
    workbook_version: str
    before_composite_hash: str
    after_composite_hash: str
    approved_field_ids: tuple[str, ...]
    changed_field_ids: tuple[str, ...]
    approved_count: int
    changed_count: int
    approval_digest: str

    def to_safe_dict(self) -> dict[str, Any]:
        """Return strictly privacy-preserving metadata safe for authenticated owner responses."""
        return {
            "receipt_id": self.receipt_id,
            "contract_version": self.contract_version,
            "status": "COMMITTED",
            "project_id": self.project_id,
            "scenario_id": self.scenario_id or None,
            "source_sha256": self.source_sha256,
            "source_format": self.source_format,
            "approval_event_id": self.approval_event_id,
            "approval_event": self.approval_event,
            "approved_at": self.approved_at,
            "committed_at": self.committed_at,
            "workbook_version": self.workbook_version,
            "before_composite_hash": self.before_composite_hash,
            "after_composite_hash": self.after_composite_hash,
            "approved_field_ids": list(self.approved_field_ids),
            "changed_field_ids": list(self.changed_field_ids),
            "approved_count": self.approved_count,
            "changed_count": self.changed_count,
            "approval_digest": self.approval_digest,
        }


_SCHEMA = """
CREATE TABLE IF NOT EXISTS model_import_receipts (
 receipt_id TEXT PRIMARY KEY,
 contract_version TEXT NOT NULL,
 owner_id TEXT NOT NULL,
 actor_id TEXT NOT NULL,
 project_id TEXT NOT NULL,
 scenario_id TEXT NOT NULL DEFAULT '',
 replay_key TEXT NOT NULL,
 source_sha256 TEXT NOT NULL,
 source_format TEXT NOT NULL CHECK (source_format IN ('csv', 'xlsx', 'unknown')),
 approval_event_id TEXT NOT NULL,
 approval_event TEXT NOT NULL,
 approved_at TEXT NOT NULL,
 committed_at TEXT NOT NULL,
 workbook_version TEXT NOT NULL,
 before_composite_hash TEXT NOT NULL,
 after_composite_hash TEXT NOT NULL,
 approved_field_ids_json TEXT NOT NULL,
 changed_field_ids_json TEXT NOT NULL,
 approved_count INTEGER NOT NULL CHECK (approved_count >= 1 AND approved_count <= 50),
 changed_count INTEGER NOT NULL CHECK (changed_count >= 0 AND changed_count <= approved_count),
 approval_digest TEXT NOT NULL,
 UNIQUE (owner_id, project_id, replay_key)
);
CREATE INDEX IF NOT EXISTS idx_model_import_receipts_owner_project
 ON model_import_receipts (owner_id, project_id, committed_at DESC);
CREATE TRIGGER IF NOT EXISTS model_import_receipts_append_only
BEFORE UPDATE ON model_import_receipts
BEGIN SELECT RAISE(ABORT, 'IMPORT_RECEIPT_IMMUTABLE'); END;
"""


def ensure_schema(connection: sqlite3.Connection) -> None:
    """Idempotent additive migration for fresh and existing databases."""
    if connection.in_transaction:
        raise ImportReceiptError("IMPORT_RECEIPT_MIGRATION_IN_TRANSACTION")
    try:
        connection.executescript("BEGIN IMMEDIATE;\n" + _SCHEMA)
        connection.commit()
    except BaseException:
        connection.rollback()
        raise


def _require_hex64(name: str, value: Any, *, code: str) -> str:
    if not isinstance(value, str) or not _HEX64_RE.match(value):
        raise ImportReceiptError(code, f"{name} must be a 64-char lowercase hex SHA-256 digest")
    return value


def _validate_allowlisted_field_ids(field_ids: Sequence[str], *, label: str) -> tuple[str, ...]:
    cleaned: list[str] = []
    seen: set[str] = set()
    for raw in field_ids:
        if not isinstance(raw, str) or not raw:
            raise ImportReceiptError("IMPORT_RECEIPT_FIELD_INVALID", label)
        try:
            WORKBOOK.field(raw)
        except KeyError:
            raise ImportReceiptError("IMPORT_RECEIPT_FIELD_INVALID", raw) from None
        if raw not in seen:
            seen.add(raw)
            cleaned.append(raw)
    return tuple(sorted(cleaned))


def compute_replay_key(
    *,
    owner_id: str,
    project_id: str,
    scenario_id: str,
    approval_event_id: str,
    source_sha256: str,
    before_composite_hash: str,
    approved_field_ids: Sequence[str],
) -> str:
    payload = {
        "contract": CONTRACT_VERSION,
        "owner_id": owner_id,
        "project_id": project_id,
        "scenario_id": scenario_id,
        "approval_event_id": approval_event_id,
        "source_sha256": source_sha256,
        "before_composite_hash": before_composite_hash,
        "approved_field_ids": sorted(approved_field_ids),
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    ).hexdigest()


def insert_receipt_in_tx(
    cur: sqlite3.Cursor,
    *,
    owner_id: str,
    actor_id: str,
    project_id: str,
    scenario_id: str | None,
    source_sha256: str,
    source_format: str,
    approval_event_id: str,
    approval_event: str,
    approved_at: str,
    workbook_version: str,
    before_composite_hash: str,
    after_composite_hash: str,
    approved_field_ids: Sequence[str],
    changed_field_ids: Sequence[str],
) -> ImportReceiptRecord:
    """Insert an append-only import receipt inside the caller's active DB transaction."""
    if not owner_id or not actor_id or not project_id:
        raise ImportReceiptError("IMPORT_RECEIPT_SCOPE_INVALID")
    if not approval_event_id or not isinstance(approval_event_id, str) or len(approval_event_id) > 128:
        raise ImportReceiptError("IMPORT_RECEIPT_APPROVAL_EVENT_INVALID")
    if not approval_event or not approved_at or not workbook_version:
        raise ImportReceiptError("IMPORT_RECEIPT_METADATA_INVALID")

    src_sha = _require_hex64("source_sha256", source_sha256, code="IMPORT_SOURCE_DIGEST_INVALID")
    before_h = _require_hex64("before_composite_hash", before_composite_hash, code="IMPORT_RECEIPT_HASH_INVALID")
    after_h = _require_hex64("after_composite_hash", after_composite_hash, code="IMPORT_RECEIPT_HASH_INVALID")

    fmt = str(source_format or "").strip().lower()
    if fmt not in _ALLOWED_FORMATS:
        raise ImportReceiptError("IMPORT_RECEIPT_FORMAT_INVALID", fmt)

    approved_ids = _validate_allowlisted_field_ids(approved_field_ids, label="approved_field_ids")
    changed_ids = _validate_allowlisted_field_ids(changed_field_ids, label="changed_field_ids")
    if not (1 <= len(approved_ids) <= 50):
        raise ImportReceiptError("IMPORT_RECEIPT_FIELD_COUNT_INVALID")
    if not set(changed_ids).issubset(set(approved_ids)):
        raise ImportReceiptError("IMPORT_RECEIPT_CHANGED_SUBSET_INVALID")

    norm_scenario = str(scenario_id or "")
    committed_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    receipt_id = f"imp_v1_{uuid.uuid4().hex}"
    replay_key = compute_replay_key(
        owner_id=owner_id,
        project_id=project_id,
        scenario_id=norm_scenario,
        approval_event_id=approval_event_id,
        source_sha256=src_sha,
        before_composite_hash=before_h,
        approved_field_ids=approved_ids,
    )
    approval_digest = hashlib.sha256(
        json.dumps(
            {
                "contract": CONTRACT_VERSION,
                "replay_key": replay_key,
                "after_composite_hash": after_h,
                "workbook_version": workbook_version,
                "changed_field_ids": list(changed_ids),
            },
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        ).encode("utf-8")
    ).hexdigest()

    try:
        cur.execute(
            """
            INSERT INTO model_import_receipts (
                receipt_id, contract_version, owner_id, actor_id, project_id, scenario_id,
                replay_key, source_sha256, source_format, approval_event_id, approval_event,
                approved_at, committed_at, workbook_version, before_composite_hash,
                after_composite_hash, approved_field_ids_json, changed_field_ids_json,
                approved_count, changed_count, approval_digest
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                receipt_id,
                CONTRACT_VERSION,
                owner_id,
                actor_id,
                project_id,
                norm_scenario,
                replay_key,
                src_sha,
                fmt,
                approval_event_id,
                approval_event,
                approved_at,
                committed_at,
                workbook_version,
                before_h,
                after_h,
                json.dumps(list(approved_ids), separators=(",", ":")),
                json.dumps(list(changed_ids), separators=(",", ":")),
                len(approved_ids),
                len(changed_ids),
                approval_digest,
            ),
        )
    except sqlite3.IntegrityError as exc:
        if "UNIQUE" in str(exc).upper():
            raise ImportReceiptError("IMPORT_RECEIPT_REPLAY_CONFLICT") from exc
        raise ImportReceiptError("IMPORT_RECEIPT_PERSISTENCE_FAILED", str(exc)) from exc

    return ImportReceiptRecord(
        receipt_id=receipt_id,
        contract_version=CONTRACT_VERSION,
        owner_id=owner_id,
        actor_id=actor_id,
        project_id=project_id,
        scenario_id=norm_scenario,
        replay_key=replay_key,
        source_sha256=src_sha,
        source_format=fmt,
        approval_event_id=approval_event_id,
        approval_event=approval_event,
        approved_at=approved_at,
        committed_at=committed_at,
        workbook_version=workbook_version,
        before_composite_hash=before_h,
        after_composite_hash=after_h,
        approved_field_ids=approved_ids,
        changed_field_ids=changed_ids,
        approved_count=len(approved_ids),
        changed_count=len(changed_ids),
        approval_digest=approval_digest,
    )


def _row_to_record(row: sqlite3.Row) -> ImportReceiptRecord:
    return ImportReceiptRecord(
        receipt_id=row["receipt_id"],
        contract_version=row["contract_version"],
        owner_id=row["owner_id"],
        actor_id=row["actor_id"],
        project_id=row["project_id"],
        scenario_id=row["scenario_id"],
        replay_key=row["replay_key"],
        source_sha256=row["source_sha256"],
        source_format=row["source_format"],
        approval_event_id=row["approval_event_id"],
        approval_event=row["approval_event"],
        approved_at=row["approved_at"],
        committed_at=row["committed_at"],
        workbook_version=row["workbook_version"],
        before_composite_hash=row["before_composite_hash"],
        after_composite_hash=row["after_composite_hash"],
        approved_field_ids=tuple(json.loads(row["approved_field_ids_json"])),
        changed_field_ids=tuple(json.loads(row["changed_field_ids_json"])),
        approved_count=int(row["approved_count"]),
        changed_count=int(row["changed_count"]),
        approval_digest=row["approval_digest"],
    )


def list_receipts_for_project(owner_id: str, project_id: str, *, limit: int = 50) -> list[ImportReceiptRecord]:
    """Return owner-scoped durable import receipts for one project, newest first."""
    bounded = max(1, min(int(limit), 200))
    conn = get_connection()
    try:
        rows = conn.execute(
            """
            SELECT * FROM model_import_receipts
            WHERE owner_id = ? AND project_id = ?
            ORDER BY committed_at DESC, rowid DESC
            LIMIT ?
            """,
            (owner_id, project_id, bounded),
        ).fetchall()
        return [_row_to_record(r) for r in rows]
    finally:
        conn.close()


def get_receipt(owner_id: str, project_id: str, receipt_id: str) -> ImportReceiptRecord | None:
    """Return one owner-scoped durable import receipt, or None if absent/foreign."""
    conn = get_connection()
    try:
        row = conn.execute(
            """
            SELECT * FROM model_import_receipts
            WHERE owner_id = ? AND project_id = ? AND receipt_id = ?
            """,
            (owner_id, project_id, receipt_id),
        ).fetchone()
        return _row_to_record(row) if row is not None else None
    finally:
        conn.close()
