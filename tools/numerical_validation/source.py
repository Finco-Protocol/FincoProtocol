"""F3.9 read-only source adapter: an immutable persisted Run -> an evidence bundle.

This is the ONLY module of the validation workflow that touches the application, and it only READS: it loads an
owner-scoped Run History entry (an append-only, immutable record) and hands its persisted payloads to the pure
bundle builder.  It never runs the model, never writes, and never imports ``financial_engine`` or ``finco_core``.
"""
from __future__ import annotations

import hashlib
from typing import Any

from .evidence import build_bundle
from .reconcile import canonical_bytes


def _configuration_sha256(entry: Any) -> str:
    """Deterministic digest of what configured this Run: its composite content hash, scenario and financing configuration.

    The composite hash is the product's own identity of inputs + scenario; the financing collection digest is added
    when the Run used an explicit financing collection, so two configurations with equal inputs still differ.
    """
    fe = (entry.runtime_summary or {}).get("financing_evidence") or {}
    material = {
        "composite_hash": entry.composite_hash,
        "scenario": entry.last_runtime_scenario_id,
        "financing_authority": (entry.integrity_evidence or {}).get("financing_authority") or fe.get("authority"),
        "collection_digest": fe.get("collection_digest"),
    }
    return hashlib.sha256(canonical_bytes(material)).hexdigest()


def _payloads(entry: Any) -> dict[str, Any]:
    return {
        "runtime_summary": entry.runtime_summary,
        "financial_statements": entry.financial_statements,
        "tax_schedule": entry.tax_schedule,
        "debt_schedule": entry.debt_schedule,
        "distribution_schedule": entry.distribution_schedule,
        "sponsor_schedule": entry.sponsor_schedule,
        "integrity_evidence": entry.integrity_evidence or None,
    }


def source_sha256(entry: Any) -> str:
    """Digest of the persisted payloads exactly as the bundle builder hashes them."""
    return hashlib.sha256(canonical_bytes({k: v for k, v in _payloads(entry).items() if v is not None})).hexdigest()


def verify_source_binding(bundle: dict[str, Any], entry: Any) -> list[str]:
    """Reasons a bundle is NOT bound to this immutable Run (empty = bound): identity fields and source digest."""
    ident, problems = bundle.get("identity", {}), []
    for key, want in (("run_key", entry.history_id), ("project_key", entry.project_code),
                      ("composite_hash", entry.composite_hash or ""), ("snapshot_id", entry.runtime_snapshot_id),
                      ("engine_version", entry.engine_version or "")):
        if ident.get(key) != want:
            problems.append(f"IDENTITY_MISMATCH_{key}")
    if ident.get("source_sha256") != source_sha256(entry):
        problems.append("SOURCE_HASH_MISMATCH")
    return problems


def bundle_from_history_entry(entry: Any) -> dict[str, Any]:
    """Bundle for one decoded ``RunHistoryEntry`` (already owner- and project-scoped by the repository)."""
    identity = {
        "project_key": entry.project_code,
        "project_id": entry.project_id,
        "scenario_key": entry.last_runtime_scenario_id or "BASE_CASE",
        "run_key": entry.history_id,
        "snapshot_id": entry.runtime_snapshot_id,
        "composite_hash": entry.composite_hash or "",
        "configuration_sha256": _configuration_sha256(entry),
        "engine_version": entry.engine_version or "",
        "workbook_version": entry.workbook_version,
        "calculated_at": entry.ran_at,
        "run_origin": entry.runtime_origin,
    }
    payloads = _payloads(entry)
    return build_bundle(payloads, identity)


def bundle_for_run(owner_id: str, project_id: str, history_id: str | None = None) -> dict[str, Any]:
    """Bundle for a named Run History entry, or the newest one.  Raises LookupError when none exists."""
    from app.persistence.run_history_repository import get_latest_history_entry, get_run_history_entry

    entry = (get_run_history_entry(owner_id, project_id, history_id) if history_id
             else get_latest_history_entry(owner_id, project_id))
    if entry is None:
        raise LookupError("no committed Run History entry for this owner and project")
    return bundle_from_history_entry(entry)
