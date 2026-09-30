"""FINCO API v1.1 — Institutional service layer (Correction A).

Read-only glue over existing canonical authorities:
  - app.auth.resolve_request_session       (signed session — no X-User-Id trust)
  - WorkspaceStateRecord / ProjectRecord   (persistence)
  - app.product_capability.PRODUCT_CAPABILITIES (supported-today authority)
  - app.model_validation.runner            (/validation endpoint only)
  - app.verified                           (/verify endpoint only)
  - app.radar_rwa.r_live_service           (/radar/r-live/{uid} — read-only)
  - app.services.v2_export_service         (/export — canonical Last Run XLSX)

Contract guarantees (Correction A):
  - Signed session only — spoofed X-User-Id has zero authority.
  - AVAILABLE = committed run exists. UNAVAILABLE = no committed run.
  - STALE is NOT a valid state. WC divergence exposed via working_copy_changed_since_run.
  - /validation != /verify (separate authorities).
  - /validation is a Reference Regression Check (pinned reference-model KPIs),
    not independent validation of a user's Last Run (H-4A).
  - Verify fails closed when no source-proven binding exists.
  - R-LIVE GET performs zero history writes.
  - No raw exception text in API responses.
  - financial_engine/** = ZERO DIFF; finco_core/** = ZERO DIFF.
  - PRODUCTION_VERIFIED_ASSET_COUNT must not increase.
"""
from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any, Optional, Tuple


STATE_AVAILABLE = "AVAILABLE"
STATE_UNAVAILABLE = "UNAVAILABLE"


# ── Internal helpers ───────────────────────────────────────────────────────────

def _load_workspace(user_id: str, project_id: str) -> Tuple[Any, Any]:
    """Return (project_record, workspace_state) — both may be None."""
    from app.persistence.projects_repository import get_project
    from app.persistence.workspace_repository import get_workspace_state

    pr = get_project(project_id, user_id)
    ws = get_workspace_state(user_id, project_id) if pr else None
    return pr, ws


def _availability_state(ws: Any) -> str:
    """Correction A: AVAILABLE iff committed run exists; UNAVAILABLE otherwise.

    Working Copy divergence does NOT change this to STALE — it is a separate
    data field (working_copy_changed_since_run) exposed on each response.
    """
    if ws is None or not ws.any_run_committed:
        return STATE_UNAVAILABLE
    return STATE_AVAILABLE


def _runtime_result_adapter(ws: Any) -> Optional[Any]:
    """Return _RuntimeResultAdapter wrapping persisted RuntimeResult, or None."""
    if ws is None:
        return None
    try:
        from app.workbook.runtime_result import RuntimeResult
        from app.services.v2_export_service import _RuntimeResultAdapter
        rr = RuntimeResult.from_workspace_state(ws)
        if rr is None:
            return None
        return _RuntimeResultAdapter(rr.runtime_summary, rr.debt_schedule)
    except Exception:
        return None


def _canonical_runtime_project_code(project_type: str, template_source: str) -> str:
    """Map project_type/template_source to the canonical runtime project code.

    The export service uses this key to locate the right project configuration.
    template_source takes priority; project_type is the fallback.
    """
    ts = (template_source or "").strip().lower()
    if ts:
        return ts
    pt = (project_type or "").strip().lower()
    if pt == "solar":
        return "generic_solar"
    if pt in ("data center", "data_center", "datacenter"):
        return "generic_data_center_reference"
    if pt in ("ev charging", "ev_charging"):
        return "generic_ev_charging_reference"
    return "generic_wind"


# ── Public service functions ───────────────────────────────────────────────────

def get_supported_today() -> dict:
    """Return canonical supported-today capabilities from PRODUCT_CAPABILITIES."""
    from app.product_capability import PRODUCT_CAPABILITIES, as_api_dict
    capabilities = [as_api_dict(cap) for cap in PRODUCT_CAPABILITIES]
    return {
        "capabilities": capabilities,
        "count": len(capabilities),
    }


def get_projects_for_user(user_id: str) -> dict:
    """Return project list for user."""
    from app.persistence.projects_repository import list_projects

    projects = list_projects(user_id)
    items = []
    for pr in projects:
        items.append({
            "project_id": pr.project_id,
            "project_name": pr.project_name,
            "project_code": pr.project_code,
            "project_type": pr.project_type,
            "project_origin": pr.project_origin,
            "template_source": getattr(pr, "template_source", None),
        })
    return {
        "projects": items,
        "count": len(items),
    }


def get_last_run_summary(user_id: str, project_id: str) -> Tuple[str, dict]:
    """Return (state, data) for canonical Last Run summary.

    Correction A: state is AVAILABLE or UNAVAILABLE only.
    working_copy_changed_since_run exposed in run_identity sub-dict.
    """
    pr, ws = _load_workspace(user_id, project_id)
    if pr is None:
        return STATE_UNAVAILABLE, {}

    state = _availability_state(ws)
    if state == STATE_UNAVAILABLE:
        return STATE_UNAVAILABLE, {}

    from app.api.v1_1.schemas import run_identity_out
    identity = run_identity_out(ws)
    return state, {
        "project_id": project_id,
        "project_name": pr.project_name,
        "project_type": pr.project_type,
        "run_identity": identity,
        "any_run_committed": ws.any_run_committed,
    }


def get_run_identity(user_id: str, project_id: str) -> Tuple[str, dict]:
    """Return (state, data) for run identity / certificate metadata."""
    pr, ws = _load_workspace(user_id, project_id)
    if pr is None:
        return STATE_UNAVAILABLE, {}

    state = _availability_state(ws)
    if state == STATE_UNAVAILABLE:
        return STATE_UNAVAILABLE, {}

    from app.api.v1_1.schemas import run_identity_out
    return state, run_identity_out(ws)


def get_kpis(user_id: str, project_id: str) -> Tuple[str, dict]:
    """Return (state, kpis_dict) for core institutional KPIs.

    Reads persisted last_runtime_summary only — no engine call.
    """
    pr, ws = _load_workspace(user_id, project_id)
    if pr is None:
        return STATE_UNAVAILABLE, {}

    state = _availability_state(ws)
    if state == STATE_UNAVAILABLE:
        return STATE_UNAVAILABLE, {}

    adapter = _runtime_result_adapter(ws)
    if adapter is None:
        return STATE_UNAVAILABLE, {}

    from app.api.v1_1.schemas import kpis_out
    return state, kpis_out(ws, adapter)


def get_export_metadata(user_id: str, project_id: str) -> Tuple[str, dict]:
    """Return (state, metadata) for XLSX export contract metadata.

    Does NOT produce the file.
    """
    pr, ws = _load_workspace(user_id, project_id)
    if pr is None:
        return STATE_UNAVAILABLE, {}

    state = _availability_state(ws)
    if state == STATE_UNAVAILABLE:
        return STATE_UNAVAILABLE, {}

    if getattr(pr, "project_origin", "") != "user_created":
        return STATE_UNAVAILABLE, {
            "reason": "EXPORT_NOT_APPLICABLE",
            "detail": "Institutional export requires a user-created project with a committed run.",
        }

    from app.api.v1_1.schemas import export_metadata_out
    return state, export_metadata_out(ws, pr)


def get_export_bytes(user_id: str, project_id: str) -> Tuple[int, Any]:
    """Return (status_code, ExportResponse) for XLSX institutional export.

    Thin authenticated delegate to canonical Last Run XLSX export.
    Zero engine rerun. WC changes do not change exported Last Run.
    """
    pr, ws = _load_workspace(user_id, project_id)
    if pr is None:
        from app.services.export_service import ExportResponse
        return 404, ExportResponse(
            status_code=404,
            error_content="<html><body><h2>Not Found</h2><p>Project not found.</p></body></html>",
        )

    if not (ws and ws.any_run_committed):
        from app.services.export_service import ExportResponse
        return 400, ExportResponse(
            status_code=400,
            error_content="<html><body><h2>Export failed</h2><p>Last Run required.</p></body></html>",
        )

    runtime_project_code = _canonical_runtime_project_code(
        pr.project_type or "",
        getattr(pr, "template_source", "") or "",
    )

    from app.services.v2_export_service import build_canonical_last_run_institutional_workbook_export
    result = build_canonical_last_run_institutional_workbook_export(
        runtime_project_code,
        safe_project=runtime_project_code,
        project_record=pr,
        user_id=user_id,
    )
    return result.status_code, result


def get_institutional_validation(user_id: str, project_id: str) -> Tuple[str, dict]:
    """Return (state, evidence) from the P1.3 Reference Regression Check.

    /validation — delegates to app.model_validation.runner.
    H-4A terminology: this capability re-runs canonical reference-model KPIs
    against pinned expected values (regression protection for the reference
    library). It runs against the canonical reference, NOT the user's Last
    Run — it does not independently validate the user's model or establish
    accounting/debt/cash integrity of the Last Run. WC state is irrelevant.
    The machine authority key stays ``MODEL_VALIDATION`` for API stability.
    """
    pr, ws = _load_workspace(user_id, project_id)
    if pr is None:
        return STATE_UNAVAILABLE, {"reason": "PROJECT_NOT_FOUND"}

    project_type = (pr.project_type or "").strip()
    vertical_map = {
        "Solar": "solar",
        "Wind": "wind",
        "EV Charging": "ev_charging",
        "Data Center": "data_center",
    }
    vertical = vertical_map.get(project_type)
    if vertical is None:
        return STATE_UNAVAILABLE, {
            "reason": "VALIDATION_UNAVAILABLE",
            "detail": f"Vertical '{project_type}' not in institutional validation set.",
        }

    try:
        from app.model_validation.runner import run_vertical_validation
        vr = run_vertical_validation(vertical)
    except Exception:
        return STATE_UNAVAILABLE, {"reason": "VALIDATION_UNAVAILABLE"}

    from app.api.v1_1.schemas import validation_out
    return STATE_AVAILABLE, validation_out(vr)


def get_run_integrity_checks(user_id: str, project_id: str) -> Tuple[str, dict]:
    """Return (state, evidence) for Run Integrity Checks on the committed Last Run.

    /integrity — read-only. Checks the INTERNAL CONSISTENCY of the committed Last Run from
    the evidence recorded at commit. It never re-runs the model, never mutates the Working
    Copy or Last Run, never issues a Signed Run and never touches Verify or Radar. It is a
    separate authority from the Reference Regression Check (/validation).
    """
    pr, ws = _load_workspace(user_id, project_id)
    if pr is None:
        return STATE_UNAVAILABLE, {"reason": "PROJECT_NOT_FOUND"}
    if ws is None or not getattr(ws, "any_run_committed", False):
        return STATE_UNAVAILABLE, {"reason": "NO_COMMITTED_RUN"}
    try:
        from app.api.v1_1.schemas import integrity_out
        from app.run_integrity import run_integrity_checks

        report = run_integrity_checks(getattr(ws, "last_integrity_evidence", None))
        return STATE_AVAILABLE, integrity_out(report, ws)
    except Exception:
        return STATE_UNAVAILABLE, {"reason": "INTEGRITY_CHECKS_UNAVAILABLE"}


def get_verify_state(user_id: str, project_id: str) -> Tuple[str, dict]:
    """Return (state, evidence) from canonical Verify authority for this project.

    /verify — delegates to app.verified (asset_registry + composer).
    Fails closed when no source-proven binding exists in the registry.
    PRODUCTION_VERIFIED_ASSET_COUNT must not increase.
    """
    pr, ws = _load_workspace(user_id, project_id)
    if pr is None:
        return STATE_UNAVAILABLE, {"reason": "PROJECT_NOT_FOUND"}

    if ws is None or not ws.any_run_committed:
        return STATE_UNAVAILABLE, {"reason": "NO_COMMITTED_RUN"}

    template_source = (getattr(pr, "template_source", "") or "").strip()
    if not template_source:
        template_source = _canonical_runtime_project_code(pr.project_type or "", "")

    from app.verified.asset_registry import get_asset_definition
    asset_def = get_asset_definition(template_source)
    if asset_def is None:
        return STATE_UNAVAILABLE, {
            "reason": "VERIFY_BINDING_UNAVAILABLE",
            "detail": f"No source-proven Verify binding for template_source='{template_source}'.",
        }

    try:
        from app.verified.composer import build_verified_asset
        verified = build_verified_asset(asset_def, pr, ws)
    except Exception:
        return STATE_UNAVAILABLE, {"reason": "VERIFY_BINDING_UNAVAILABLE"}

    from app.api.v1_1.schemas import verify_out
    return STATE_AVAILABLE, verify_out(verified)


def _r_live_composite_state(
    onchain_state: Any,
    token_state: Any,
    underlying_state: Any,
    premium_state: Any,
) -> str:
    """Determine composite R-LIVE API state from all four current components.

    AVAILABLE only when ALL components are AVAILABLE.
    STALE if evidence is stale but otherwise bound; a stale on-chain reference
    also makes its downstream token/premium placeholders unavailable.
    UNAVAILABLE otherwise.

    This enforces the PR #126 fail-closed contract: a partial current read
    never surfaces as AVAILABLE.
    """
    from finco_radar.authority.contracts import AuthorityState

    components = [onchain_state, token_state, underlying_state, premium_state]
    if all(s is AuthorityState.AVAILABLE for s in components):
        return STATE_AVAILABLE
    # A STALE on-chain reference has no numeric IndependentTokenReference by
    # design. B1.0 consequently marks token/premium UNAVAILABLE; these are
    # downstream placeholders, not independent evidence that the pool is absent.
    if (onchain_state is AuthorityState.STALE
            and underlying_state not in (AuthorityState.UNAVAILABLE, AuthorityState.IDENTITY_UNAVAILABLE)):
        return "STALE"
    for s in components:
        if s is AuthorityState.UNAVAILABLE or s is AuthorityState.IDENTITY_UNAVAILABLE:
            return STATE_UNAVAILABLE
    return "STALE"


def _r_live_freshness(evidence: Any) -> dict:
    """Presentation-only ages from canonical on-chain evidence timestamps."""
    fields = evidence if isinstance(evidence, dict) else dict(evidence or {})

    def parsed(name: str) -> datetime | None:
        raw = fields.get(name)
        if not isinstance(raw, str):
            return None
        try:
            value = datetime.fromisoformat(raw)
        except ValueError:
            return None
        return value.astimezone(timezone.utc) if value.tzinfo and value.utcoffset() is not None else None

    retrieved = parsed("retrievedAt")

    def age(name: str) -> int | None:
        source = parsed(name)
        if source is None or retrieved is None:
            return None
        seconds = (retrieved - source).total_seconds()
        return int(seconds) if seconds >= 0 else None

    return {
        "market_activity_age_seconds": age("lastPoolActivityAt"),
        "quote_feed_age_seconds": age("quoteUpdatedAt"),
        "block_age_seconds": age("blockTimestamp"),
        "last_pool_activity_at": fields.get("lastPoolActivityAt"),
        "quote_updated_at": fields.get("quoteUpdatedAt"),
        "block_timestamp": fields.get("blockTimestamp"),
        "effective_evidence_at": fields.get("effectiveObservedAt"),
        "retrieved_at": fields.get("retrievedAt"),
    }


def get_r_live(uid: str) -> Tuple[str, dict]:
    """Return (state, data) for R-LIVE exact AssetKey reference.

    /radar/r-live/{uid} — delegates to app.radar_rwa.r_live_service.
    GET performs zero history writes (persist_history=False).
    Validates the exact reviewed canonical AssetKey — no ticker/fuzzy identity.

    State parity (Correction B):
      AVAILABLE — all four current components (onchain, token, underlying, premium) are AVAILABLE.
      STALE     — any component is STALE; none is UNAVAILABLE.
      UNAVAILABLE — any component is UNAVAILABLE/IDENTITY_UNAVAILABLE, or no RPC, or invalid UID.

    When state != AVAILABLE, current price/value fields are suppressed to None.
    """
    from finco_radar.authority.r_live_policy import AAPL_KEY, APPROVED_BY_CANONICAL_ID
    policy = APPROVED_BY_CANONICAL_ID.get(uid)
    if policy is None:
        return STATE_UNAVAILABLE, {"reason": "ASSET_UID_INVALID"}

    rpc_url = os.getenv("ROBINHOOD_RPC_URL")
    if not rpc_url:
        return STATE_UNAVAILABLE, {"reason": "RPC_NOT_CONFIGURED"}

    try:
        from app.radar_rwa.r_live_service import collect_aapl_r_live, collect_r_live
        if policy.asset_key == AAPL_KEY:
            result = collect_aapl_r_live(rpc_url=rpc_url, persist_history=False)
        else:
            result = collect_r_live(canonical_asset_id=uid, rpc_url=rpc_url, persist_history=False)
    except Exception:
        return STATE_UNAVAILABLE, {"reason": "RADAR_AUTHORITY_UNAVAILABLE"}

    from finco_radar.authority.contracts import AuthorityState
    authority = result.authority
    onchain = result.onchain
    token = authority.token
    underlying = authority.underlying
    premium = authority.premium

    state = _r_live_composite_state(
        onchain.state, token.state, underlying.state, premium.state,
    )
    is_current = (state == STATE_AVAILABLE)

    data = {
        "exact_asset_key": {
            "canonical_id": policy.asset_key.canonical_id,
            "chain_id": policy.asset_key.chain_id,
            "contract_address": policy.asset_key.contract_address,
        },
        "economic_asset_uid": authority.economic_asset_uid or policy.economic_asset_uid,
        "token_reference": {
            "state": token.state.value,
            "price_usd_per_token": str(token.price_usd_per_token) if (is_current and token.price_usd_per_token is not None) else None,
            "source": token.source,
            "observed_at": token.observed_at.isoformat() if token.observed_at else None,
            "reason": token.reason,
        },
        "robinhood_basis": {
            "state": underlying.state.value,
            "price_usd_per_token": str(underlying.price_usd_per_token) if (is_current and underlying.price_usd_per_token is not None) else None,
            "source": underlying.source,
            "observed_at": underlying.observed_at.isoformat() if underlying.observed_at else None,
            "reason": underlying.reason,
        },
        "b1_0_premium": {
            "state": premium.state.value,
            "value_bps": str(premium.value_bps) if (is_current and premium.value_bps is not None) else None,
            "formula": premium.formula,
            "reason": premium.reason,
        },
        "observed_at": onchain.observed_at.isoformat() if onchain.observed_at else None,
        "freshness": _r_live_freshness(onchain.evidence),
    }
    return state, data
