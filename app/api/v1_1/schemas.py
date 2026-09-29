"""FINCO API v1.1 — Institutional Read-Only Surface schemas.

All responses follow the standard v1.1 envelope:
  {
    "api_version": "v1.1",
    "schema_version": "institutional-v1.1.0",
    "state": "<AVAILABLE | UNAVAILABLE>",
    "data": {...},
    "evidence": {...}   # optional
  }

Availability semantics (Correction A):
  AVAILABLE   — committed run exists; data is from canonical Last Run.
  UNAVAILABLE — no committed run, no project, or auth error.

STALE is NOT a valid state for Last Run endpoints.
Working Copy divergence is exposed explicitly via working_copy_changed_since_run.

MISSING != ZERO: Optional[float] None values stay None (never coerced to 0.0).
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from pydantic import BaseModel, ConfigDict

API_VERSION = "v1.1"
SCHEMA_VERSION = "institutional-v1.1.0"


# ── Error envelope ─────────────────────────────────────────────────────────────

class ApiErrorEnvelope(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    api_version: str = API_VERSION
    schema_version: str = SCHEMA_VERSION
    error: str
    detail: str
    project_id: Optional[str] = None


# ── Standard envelope ──────────────────────────────────────────────────────────

class InstitutionalEnvelope(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    api_version: str = API_VERSION
    schema_version: str = SCHEMA_VERSION
    state: str
    project_id: Optional[str] = None
    data: Optional[Dict[str, Any]] = None
    evidence: Optional[Dict[str, Any]] = None


class ProjectListEnvelope(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    api_version: str = API_VERSION
    schema_version: str = SCHEMA_VERSION
    state: str
    data: Optional[Dict[str, Any]] = None


# ── KPI helpers ────────────────────────────────────────────────────────────────

def _kpi_field(value: Any, unit: str = "") -> Dict[str, Any]:
    if value is None:
        return {"value": None, "state": "UNAVAILABLE", "unit": unit}
    return {"value": value, "state": "AVAILABLE", "unit": unit}


def kpis_out(ws: Any, result_adapter: Any) -> Dict[str, Any]:
    """Build KPI dict from persisted workspace + result adapter.

    Reads persisted fields only — no engine call.
    MISSING != ZERO: None values preserved as UNAVAILABLE.
    Correction A: includes working_copy_changed_since_run.
    """
    def _safe(attr: str) -> Any:
        return getattr(result_adapter, attr, None)

    draft = ws.draft_snapshot or {}
    last_run = ws.last_runtime_snapshot or {}
    wc_changed = draft != last_run

    return {
        "project_irr": _kpi_field(_safe("project_irr"), "pct"),
        # H-3: ``equity_irr`` keeps its meaning (pure share-capital return, equity_only);
        # ``share_capital_irr`` is the explicit name for the same value. Total sponsor
        # return (equity + shareholder loan) is served from the persisted
        # ``total_sponsor_xirr`` key; older Last Runs persisted it as ``sponsor_irr``.
        "equity_irr": _kpi_field(_safe("equity_irr"), "pct"),
        "share_capital_irr": _kpi_field(_safe("share_capital_irr"), "pct"),
        "total_sponsor_xirr": _kpi_field(
            _safe("total_sponsor_xirr") if _safe("total_sponsor_xirr") is not None
            else _safe("sponsor_irr"), "pct"),
        "senior_debt_keur": _kpi_field(_safe("senior_debt_keur"), "kEUR"),
        "min_dscr": _kpi_field(_safe("min_dscr"), "x"),
        "avg_dscr": _kpi_field(_safe("actual_avg_dscr"), "x"),
        "equity_npv": _kpi_field(_safe("equity_npv"), "kEUR"),
        "total_revenue_keur": _kpi_field(_safe("total_revenue_keur"), "kEUR"),
        "total_ebitda_keur": _kpi_field(_safe("total_ebitda_keur"), "kEUR"),
        "working_copy_changed_since_run": wc_changed,
    }


def run_identity_out(ws: Any) -> Dict[str, Any]:
    """Serialise run identity from persisted workspace state.

    Correction A: includes working_copy_changed_since_run.
    """
    identity = getattr(ws, "last_runtime_identity", None) or {}
    draft = ws.draft_snapshot or {}
    last_run = ws.last_runtime_snapshot or {}
    wc_changed = draft != last_run
    return {
        "snapshot_id": ws.last_runtime_snapshot_id,
        "composite_hash": ws.last_runtime_composite_hash,
        "run_at": ws.last_runtime_at.isoformat() if ws.last_runtime_at else None,
        "scenario_id": ws.last_runtime_scenario_id,
        "run_origin": ws.last_runtime_origin,
        "engine_version": identity.get("engine_version") if isinstance(identity, dict) else None,
        "git_sha": identity.get("git_sha") if isinstance(identity, dict) else None,
        "git_branch": identity.get("git_branch") if isinstance(identity, dict) else None,
        "working_copy_changed_since_run": wc_changed,
    }


def export_metadata_out(ws: Any, project_record: Any) -> Dict[str, Any]:
    """Build XLSX export contract metadata — does not produce the file."""
    pid = getattr(project_record, "project_id", "unknown")
    pname = (getattr(project_record, "project_name", "") or "project").replace(" ", "_")
    snap_id = ws.last_runtime_snapshot_id or "no_run"
    draft = ws.draft_snapshot or {}
    last_run = ws.last_runtime_snapshot or {}
    wc_changed = draft != last_run
    return {
        "download_path": f"/api/v1.1/projects/{pid}/export",
        "suggested_filename": f"FINCO_Institutional_{pname}_{snap_id}.xlsx",
        "export_authority": "CANONICAL_LAST_RUN",
        "working_copy_changed_since_run": wc_changed,
        "note": (
            "Download triggers zero-engine XLSX generation from persisted Last Run. "
            "No model re-run occurs at download time."
        ),
    }


def validation_out(vr: Any) -> Dict[str, Any]:
    """Serialise ValidationResult to API evidence dict (for /validation endpoint)."""
    return {
        "authority": "MODEL_VALIDATION",
        "validation_state": vr.validation_state,
        "passed": vr.passed,
        "framework_passed": vr.framework_passed,
        "product_reconciled": vr.product_reconciled,
        "pass_count": vr.pass_count,
        "fail_count": vr.fail_count,
        "gaps": [
            {
                "name": getattr(g, "name", ""),
                "gap_type": g.gap_type,
                "category": getattr(g, "category", ""),
                "detail": getattr(g, "description", getattr(g, "detail", "")),
            }
            for g in (vr.gaps or [])
        ],
    }


def verify_out(verified_asset: Dict[str, Any]) -> Dict[str, Any]:
    """Serialise verified asset record to API evidence dict (for /verify endpoint)."""
    return {
        "authority": "FINCO_VERIFY",
        "asset_id": verified_asset.get("asset_id"),
        "status": verified_asset.get("status"),
        "schema": verified_asset.get("schema", "FINCO_VERIFIED_ASSET_V1"),
        "verification": verified_asset.get("verification"),
        "model": verified_asset.get("model"),
    }
