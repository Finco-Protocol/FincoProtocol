"""Run Integrity Checks (Opus H-4b): internal consistency of a committed Last Run."""
from app.run_integrity.checks import run_integrity_checks
from app.run_integrity.contracts import (
    AUTHORITY,
    CheckStatus,
    IntegrityCheck,
    OverallStatus,
    RunIntegrityReport,
)
from app.run_integrity.evidence import build_run_integrity_evidence, evidence_digest

__all__ = [
    "AUTHORITY", "CheckStatus", "IntegrityCheck", "OverallStatus", "RunIntegrityReport",
    "build_run_integrity_evidence", "evidence_digest", "run_integrity_checks",
]
