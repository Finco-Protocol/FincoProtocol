"""FINCO Run Certificate V1 — deterministic integrity record for a committed Last Run.

Principle: NUMBER → LINEAGE → RUN CERTIFICATE

This module is a READ operation over already-persisted, already-committed Last Run
data. It never calls run_project(), run_clean_production(), or any financial-engine
calculation entry point.

Authority reuse:
  canonical_sha256 / canonical_json_bytes  — finco_protocol.verification.envelope
  WorkspaceStateRecord                     — app.persistence.records
  engine_version                           — ws.last_runtime_identity["engine_version"]
  composite_hash                           — ws.last_runtime_composite_hash

Fail-closed on:
  - no committed run
  - missing last_runtime_identity (legacy run — no persisted engine_version)
  - engine_version == "NOT_AVAILABLE" (stored at commit time; signals import failure)
  - missing composite_hash
  - missing last_runtime_at

Markers:
  RUN_CERTIFICATE_FROM_PERSISTED_LAST_RUN_ONLY
  RUN_CERTIFICATE_NO_ENGINE_RECALCULATION
  RUN_CERTIFICATE_COMPOSITE_HASH_BOUND
  RUN_CERTIFICATE_ENGINE_VERSION_RUN_BOUND
  RUN_CERTIFICATE_NO_CURRENT_ENGINE_SUBSTITUTION
  RUN_CERTIFICATE_LEGACY_LINEAGE_FAILS_CLOSED
  RUN_CERTIFICATE_ASSUMPTION_DIGEST_DETERMINISTIC
  RUN_CERTIFICATE_WORKING_COPY_EDIT_IMMUTABLE
  RUN_CERTIFICATE_OUTPUT_DIGEST_DETERMINISTIC
  RUN_CERTIFICATE_OUTPUTS_FROM_PERSISTED_LAST_RUN
  RUN_CERTIFICATE_DIGEST_DETERMINISTIC
  RUN_CERTIFICATE_ID_DETERMINISTIC
  RUN_CERTIFICATE_NEW_RUN_CHANGES_DIGEST
  RUN_CERTIFICATE_V1_SCHEMA_STABLE
  RUN_CERTIFICATE_NO_SENSITIVE_IDENTITY_LEAK
"""
from __future__ import annotations

from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from app.persistence.records import WorkspaceStateRecord

CERTIFICATE_SCHEMA = "FINCO_RUN_CERTIFICATE_V1"
CERTIFICATE_ID_PREFIX = "frc_"
CERTIFICATE_ID_DIGEST_CHARS = 16

# Headline keys consumed from last_runtime_summary (raw numeric values).
_HEADLINE_KEYS = (
    "project_irr",
    "equity_irr",
    "sponsor_irr",
    "min_dscr",
    "senior_debt_keur",
    "total_capex_keur",
)


class RunCertificateUnavailableError(Exception):
    """Raised when a certificate cannot be produced for this workspace state."""

    def __init__(self, reason: str, code: str) -> None:
        super().__init__(reason)
        self.reason = reason
        self.code = code


def _canonical_sha256(value: Any) -> str:
    """Thin wrapper — delegates to finco_protocol canonical authority."""
    from finco_protocol.verification.envelope import canonical_sha256
    return canonical_sha256(value)


def _build_assumption_digest(ws: "WorkspaceStateRecord") -> str:
    """SHA-256 over the persisted last-run snapshot (frozen at commit time).

    Does NOT touch the current working-copy draft.

    RUN_CERTIFICATE_ASSUMPTION_DIGEST_DETERMINISTIC
    RUN_CERTIFICATE_WORKING_COPY_EDIT_IMMUTABLE
    """
    return _canonical_sha256(ws.last_runtime_snapshot or {})


def _build_output_digest(ws: "WorkspaceStateRecord") -> str:
    """SHA-256 over the full persisted last-run output artifact set.

    Missing optional schedules are represented as explicit empty dicts
    so the digest is deterministic regardless of whether the caller stores
    None or {} for an absent schedule.

    RUN_CERTIFICATE_OUTPUT_DIGEST_DETERMINISTIC
    RUN_CERTIFICATE_OUTPUTS_FROM_PERSISTED_LAST_RUN
    """
    payload = {
        "runtime_summary": ws.last_runtime_summary or {},
        "financial_statements": ws.last_financial_statements or {},
        "debt_schedule": ws.last_debt_schedule or {},
        "tax_schedule": ws.last_tax_schedule or {},
        "distribution_schedule": ws.last_distribution_schedule or {},
        "sponsor_schedule": ws.last_sponsor_schedule or {},
    }
    return _canonical_sha256(payload)


def _build_headline_outputs(summary: dict[str, Any]) -> dict[str, Any]:
    """Extract headline metrics from the persisted runtime summary.

    Returns None for any metric that is absent or None in the summary.
    Does not convert absence to zero.
    """
    return {k: summary.get(k) for k in _HEADLINE_KEYS}


def build_run_certificate(
    ws: "WorkspaceStateRecord",
    project_record: Any,
) -> dict[str, Any]:
    """Build a deterministic Run Certificate from a committed Last Run.

    Returns a certificate dict on success.
    Raises RunCertificateUnavailableError on any fail-closed condition.

    The project_record must belong to the same user/workspace as ws.
    Do NOT expose user_id, session data, or internal DB row identifiers
    in the returned certificate.

    RUN_CERTIFICATE_FROM_PERSISTED_LAST_RUN_ONLY
    RUN_CERTIFICATE_NO_ENGINE_RECALCULATION
    RUN_CERTIFICATE_NO_SENSITIVE_IDENTITY_LEAK
    """
    # Fail closed: no committed run
    if not ws.any_run_committed:
        raise RunCertificateUnavailableError(
            "No committed run exists for this project. "
            "Run the model at least once before requesting a certificate.",
            code="NO_COMMITTED_RUN",
        )

    # Fail closed: legacy run — no persisted identity (pre-Correction B)
    # This also enforces RUN_CERTIFICATE_ENGINE_VERSION_RUN_BOUND and
    # RUN_CERTIFICATE_NO_CURRENT_ENGINE_SUBSTITUTION.
    ri = getattr(ws, "last_runtime_identity", None)
    if ri is None:
        raise RunCertificateUnavailableError(
            "This run predates run-bound identity persistence. "
            "Re-run the model to establish a certifiable Last Run.",
            code="LEGACY_LINEAGE_FAILS_CLOSED",
        )

    # Fail closed: engine_version not available at commit time
    # RUN_CERTIFICATE_LEGACY_LINEAGE_FAILS_CLOSED
    engine_version = ri.get("engine_version")
    if not engine_version or engine_version == "NOT_AVAILABLE":
        raise RunCertificateUnavailableError(
            "Engine version was not persisted with this run. "
            "Re-run the model to establish a certifiable Last Run.",
            code="LEGACY_LINEAGE_FAILS_CLOSED",
        )

    # Fail closed: missing required lineage fields
    if not ws.last_runtime_composite_hash:
        raise RunCertificateUnavailableError(
            "Run composite hash is missing.",
            code="MISSING_COMPOSITE_HASH",
        )
    if not ws.last_runtime_snapshot_id:
        raise RunCertificateUnavailableError(
            "Run snapshot ID is missing.",
            code="MISSING_SNAPSHOT_ID",
        )
    if ws.last_runtime_at is None:
        raise RunCertificateUnavailableError(
            "Run timestamp is missing.",
            code="MISSING_RUN_TIMESTAMP",
        )

    # Build deterministic digests from persisted data only.
    assumptions_sha256 = _build_assumption_digest(ws)
    outputs_sha256 = _build_output_digest(ws)

    # Build the certificate payload (without the final digest + id).
    # Use the committed run timestamp as the temporal authority —
    # never use "generated now" timestamps so the same run always
    # produces the same certificate.
    cert_payload: dict[str, Any] = {
        "schema": CERTIFICATE_SCHEMA,
        "run": {
            "project_code": project_record.project_code,
            "project_name": getattr(project_record, "project_name", None),
            "snapshot_id": ws.last_runtime_snapshot_id,
            "scenario_id": ws.last_runtime_scenario_id,
            "scenario_name": ri.get("scenario_name"),
            "origin": ws.last_runtime_origin,
            "committed_at": ws.last_runtime_at.isoformat(),
        },
        "model": {
            # Always from the persisted run — never current-time ENGINE_VERSION.
            # RUN_CERTIFICATE_ENGINE_VERSION_RUN_BOUND
            # RUN_CERTIFICATE_NO_CURRENT_ENGINE_SUBSTITUTION
            "engine_version": engine_version,
        },
        "identity": {
            # RUN_CERTIFICATE_COMPOSITE_HASH_BOUND
            "composite_hash": ws.last_runtime_composite_hash,
            "assumptions_sha256": assumptions_sha256,
            "outputs_sha256": outputs_sha256,
        },
        "headline_outputs": _build_headline_outputs(ws.last_runtime_summary or {}),
    }

    # Compute the final certificate digest over the payload above.
    # Same Last Run → same payload → same digest → same certificate_id.
    # RUN_CERTIFICATE_DIGEST_DETERMINISTIC
    # RUN_CERTIFICATE_ID_DETERMINISTIC
    certificate_digest_sha256 = _canonical_sha256(cert_payload)
    certificate_id = CERTIFICATE_ID_PREFIX + certificate_digest_sha256[:CERTIFICATE_ID_DIGEST_CHARS]

    cert_payload["certificate_id"] = certificate_id
    cert_payload["certificate_digest_sha256"] = certificate_digest_sha256

    return cert_payload


def verify_certificate_digest(certificate: dict[str, Any]) -> bool:
    """Verify that the certificate_digest_sha256 matches the payload.

    Returns True if intact, False if tampered.
    Used by tests (section C: mutate certificate payload after digest → fails).
    """
    digest = certificate.get("certificate_digest_sha256")
    if not digest:
        return False
    payload_without_digest = {
        k: v for k, v in certificate.items()
        if k not in ("certificate_id", "certificate_digest_sha256")
    }
    expected = _canonical_sha256(payload_without_digest)
    return expected == digest
