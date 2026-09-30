"""Model Trust Pack V1 — read-only composition of existing canonical evidence.

This module owns NO calculations and NO truth authorities.  It composes the
existing canonical read services into one user-facing evidence surface:

  - Last Run identity          → app.api.v1_1.institutional.get_run_identity
  - Core KPIs                  → app.api.v1_1.institutional.get_kpis
  - Reference Regression Check → app.api.v1_1.institutional.get_institutional_validation
    (H-4A: re-runs canonical reference models against pinned expected values;
    regression protection — NOT independent validation of a user's Last Run)
  - FINCO VERIFY               → app.api.v1_1.institutional.get_verify_state
  - Institutional export       → app.api.v1_1.institutional.get_export_metadata
  - Methodology / conventions  → app.model_methodology_registry (existing text)
  - Signed Run Certificate     → app.services.run_certificate_service (separate authority)

Fail-closed: every section carries an explicit state (AVAILABLE / UNAVAILABLE).
UNAVAILABLE is a first-class, intentionally-styled outcome — never an error and
never a fake green check.  The model is never executed from Trust Pack
rendering, and nothing here mutates state.

Authority separation: the Signed Run Certificate is a SEPARATE authority from
FINCO VERIFY.  Certificate availability NEVER implies VERIFIED status and NEVER
increases PRODUCTION_VERIFIED_ASSET_COUNT.
"""
from __future__ import annotations

from typing import Any

from app.api.v1_1 import institutional as _v11
from app.api.v1_1.institutional import (
    STATE_AVAILABLE,
    STATE_UNAVAILABLE,
)
from app.verified.contracts import STATUS_DISPLAY
from app.services.run_certificate_service import (
    CertificateBuildUnavailable,
    SigningKeyUnavailable,
    issue_run_certificate,
)
from app.persistence.workspace_repository import get_workspace_state as _get_workspace_state

# Core KPI rows in institutional display order.  (key in v1.1 kpis payload,
# human label, formatter kind)
_CORE_KPI_ROWS: tuple[tuple[str, str, str], ...] = (
    ("project_irr", "Project IRR", "pct"),
    # H-3: total sponsor return (equity + shareholder loan) is the sponsor headline;
    # ``equity_irr`` keeps its machine key and meaning but is labelled as what it is.
    ("total_sponsor_xirr", "Total Sponsor XIRR (equity + SHL)", "pct"),
    ("equity_irr", "Share-capital IRR (equity only)", "pct"),
    ("senior_debt_keur", "Senior Debt", "keur"),
    ("min_dscr", "Min DSCR", "x"),
)

# Methodology rows surfaced verbatim from the existing machine-readable
# registry (label + period timing + sign convention).  No text is invented.
_METHODOLOGY_KEYS: tuple[str, ...] = (
    "production",
    "revenue",
    "revenue_data_center",
    "revenue_ev_charging",
    "ebitda",
    "cfads",
    "dscr",
    "senior_interest",
    "project_irr",
    "equity_irr",
    "total_sponsor_xirr",
    "total_capex",
    "initial_senior_debt",
    "xirr_year_fraction",
)

_METHODOLOGY_PAGE_URL = "/model/methodology"


def _fmt_pct(value: Any) -> str | None:
    try:
        return f"{float(value) * 100:.2f}%"
    except (TypeError, ValueError):
        return None


def _fmt_keur(value: Any) -> str | None:
    try:
        return f"{float(value):,.1f} kEUR"
    except (TypeError, ValueError):
        return None


def _fmt_x(value: Any) -> str | None:
    try:
        return f"{float(value):.3f}x"
    except (TypeError, ValueError):
        return None


_FORMATTERS = {"pct": _fmt_pct, "keur": _fmt_keur, "x": _fmt_x}


def _fmt_datetime(value: Any) -> str | None:
    """ISO timestamp → seconds-precision display text (no fractional tail)."""
    if not value or not isinstance(value, str):
        return None
    return value[:19].replace("T", " ")


def _short_hash(value: Any) -> str | None:
    if not value or not isinstance(value, str):
        return None
    return value[:12] + "…" if len(value) > 12 else value


def _kpi_section(state: str, kpis: dict[str, Any], identity: dict[str, Any]) -> dict[str, Any]:
    """Build the Core KPIs section from the v1.1 KPI authority."""
    rows: list[dict[str, Any]] = []
    for key, label, kind in _CORE_KPI_ROWS:
        field = kpis.get(key) or {}
        raw = field.get("value")
        state_f = field.get("state", STATE_UNAVAILABLE)
        rows.append({
            "key": key,
            "label": label,
            "value": raw,
            "display": _FORMATTERS[kind](raw) if state_f == STATE_AVAILABLE else None,
            "state": state_f,
            "unit": field.get("unit", ""),
        })
    return {
        "state": state,
        "rows": rows,
        "authority": "API v1.1 /projects/{id}/kpis — persisted canonical Last Run only",
        "lineage": {
            "snapshot_id": identity.get("snapshot_id"),
            "run_at_display": _fmt_datetime(identity.get("run_at")),
            "composite_hash_short": _short_hash(identity.get("composite_hash")),
        },
    }


def _validation_section(state: str, evidence: dict[str, Any]) -> dict[str, Any]:
    gaps = evidence.get("gaps") or []
    return {
        "state": state,
        "validation_state": evidence.get("validation_state"),
        "passed": evidence.get("passed"),
        "framework_passed": evidence.get("framework_passed"),
        "product_reconciled": evidence.get("product_reconciled"),
        "pass_count": evidence.get("pass_count"),
        "fail_count": evidence.get("fail_count"),
        "gaps": gaps[:5],
        "gap_count": len(gaps),
        "authority": "REFERENCE REGRESSION CHECK — P1.3 pinned-reference reconciliation (app.model_validation)",
    }


def _verify_section(state: str, evidence: dict[str, Any]) -> dict[str, Any]:
    status = evidence.get("status")
    # STATUS_DISPLAY maps status → {"label", "description", "css_class"}; keys
    # may be enum members, so look up by value string as well.
    display = None
    if status:
        display = STATUS_DISPLAY.get(status)
        if display is None:
            for _k, _v in STATUS_DISPLAY.items():
                if getattr(_k, "value", str(_k)) == str(status):
                    display = _v
                    break
    return {
        "state": state,
        "status": status,
        "label": display["label"] if display else None,
        "description": display["description"] if display else None,
        "css_class": display["css_class"] if display else None,
        "asset_id": evidence.get("asset_id"),
        "authority": str(evidence.get("authority") or "FINCO_VERIFY"),
        "verify_url": (
            f"/verify/run/"  # per-project link appended by the caller
        ),
    }


def _export_section(state: str, metadata: dict[str, Any]) -> dict[str, Any]:
    return {
        "state": state,
        "suggested_filename": metadata.get("suggested_filename"),
        "export_authority": metadata.get("export_authority"),
        "export_generated_at": metadata.get("export_generated_at"),
        "working_copy_changed_since_run": metadata.get("working_copy_changed_since_run"),
        "note": metadata.get("note"),
    }


def _methodology_section(vertical_hint: str | None = None) -> dict[str, Any]:
    """Surface existing methodology text from the machine-readable registry."""
    from app.model_methodology_registry import METRIC_REGISTRY

    by_key = {e.key: e for e in METRIC_REGISTRY}
    rows: list[dict[str, Any]] = []
    for key in _METHODOLOGY_KEYS:
        entry = by_key.get(key)
        if entry is None:
            continue
        rows.append({
            "key": entry.key,
            "label": entry.label,
            "period_timing": entry.period_timing,
            "sign_convention": entry.sign_convention,
            "notes": entry.notes,
        })
    return {
        "state": STATE_AVAILABLE,
        "rows": rows,
        "page_url": _METHODOLOGY_PAGE_URL,
        "authority": "app.model_methodology_registry (existing product conventions)",
    }


_CERTIFICATE_AUTHORITY = (
    "FINCO Signed Run Certificate V1 — app.services.run_certificate_service"
)


def build_certificate_fragment(user_id: str, project_id: str) -> dict[str, Any]:
    """Build the on-demand Signed Run Certificate evidence fragment.

    Called ONLY from the explicit user-triggered load endpoint — NEVER during
    page rendering.  Signing never happens automatically on page load.

    AUTHORITY SEPARATION: certificate proves provenance/integrity only.
    It is NOT FINCO VERIFY and NEVER implies VERIFIED status.
    TRUST_PACK_RENDER_DOES_NOT_SIGN
    """
    ws = _get_workspace_state(user_id, project_id)
    if ws is None or not ws.any_run_committed:
        return {
            "state": STATE_UNAVAILABLE,
            "reason": "COMMITTED_LAST_RUN_REQUIRED",
            "not_verify": True,
            "authority": _CERTIFICATE_AUTHORITY,
        }
    try:
        cert = issue_run_certificate(ws)
        return {
            "state": STATE_AVAILABLE,
            "schema_version": cert.get("certificate_schema_version"),
            "issuer": cert.get("issuer"),
            "issued_at": _fmt_datetime(cert.get("issued_at")),
            "snapshot_id": cert.get("snapshot_id"),
            "composite_hash": cert.get("composite_hash"),
            "composite_hash_short": _short_hash(cert.get("composite_hash")),
            "workbook_version": cert.get("workbook_version"),
            "engine_version": cert.get("engine_version"),
            "active_scenario_id": cert.get("active_scenario_id"),
            "run_origin": cert.get("run_origin"),
            "key_id": cert.get("key_id"),
            "payload_digest": cert.get("payload_digest"),
            "signature_algorithm": cert.get("signature_algorithm"),
            "not_verify": True,
            "authority": _CERTIFICATE_AUTHORITY,
        }
    except SigningKeyUnavailable as _exc:
        return {
            "state": STATE_UNAVAILABLE,
            "reason": _exc.REASON,
            "not_verify": True,
            "authority": _CERTIFICATE_AUTHORITY,
        }
    except CertificateBuildUnavailable as _exc:
        return {
            "state": STATE_UNAVAILABLE,
            "reason": _exc.REASON,
            "not_verify": True,
            "authority": _CERTIFICATE_AUTHORITY,
        }
    except Exception:
        return {
            "state": STATE_UNAVAILABLE,
            "reason": "CERTIFICATE_UNAVAILABLE",
            "not_verify": True,
            "authority": _CERTIFICATE_AUTHORITY,
        }


def _integrity_section(state: str, evidence: dict[str, Any]) -> dict[str, Any]:
    """Run Integrity Checks section: typed per-check results, never a market or asset claim."""
    return {
        "state": state,
        "overall": evidence.get("overall"),
        "counts": evidence.get("counts") or {},
        "checks": list(evidence.get("checks") or []),
        "authority": "RUN_INTEGRITY_CHECKS",
        "scope": evidence.get("scope") or (
            "Internal consistency of the committed Last Run only; not FINCO Verify, not the "
            "Reference Regression Check, not a Signed Run."),
    }


def build_validation_fragment(user_id: str, project_id: str) -> dict[str, Any]:
    """Build the on-demand Reference Regression Check evidence fragment.

    Called ONLY from the explicit user-triggered load endpoint (never during
    page rendering): delegates to the v1.1 validation authority, which runs
    the P1.3 vertical reconciliation against the canonical reference.
    """
    val_state, validation = _v11.get_institutional_validation(user_id, project_id)
    if val_state != STATE_AVAILABLE:
        validation = {}
    return _validation_section(val_state, validation)


def build_trust_pack(
    user_id: str,
    project_id: str,
    *,
    project_code: str,
    any_run_committed: bool = False,
) -> dict[str, Any]:
    """Compose the Model Trust Pack from existing canonical read services.

    Pure read composition: no engine execution, no DB writes, no state
    mutation.  Every section fails closed to UNAVAILABLE independently.
    """
    # ── A. Last Run identity ────────────────────────────────────────────
    id_state, identity = _v11.get_run_identity(user_id, project_id)
    if id_state != STATE_AVAILABLE:
        identity = {}

    # ── B. Core KPIs (same canonical Last Run authority) ────────────────
    kpi_state, kpis = _v11.get_kpis(user_id, project_id)
    if kpi_state != STATE_AVAILABLE:
        kpis = {}

    # ── C. Reference Regression Check (H-4A terminology) ────────────────
    # Correction: vertical validation executes the reference production model
    # inside app.model_validation, so it must NEVER run during Trust Pack
    # rendering (render is side-effect-free).  The section renders as an
    # explicit on-demand load: the user clicks to fetch the evidence from the
    # same v1.1 authority (see /v2/workbook/trust/validation fragment).
    # Fail-closed: DEFERRED is only valid when there is a committed Last Run.
    # Without one, validation is UNAVAILABLE (no actionable load state).
    _can_defer_validation = id_state == STATE_AVAILABLE and any_run_committed
    validation: dict[str, Any] = {
        "state": "DEFERRED" if _can_defer_validation else STATE_UNAVAILABLE,
        "load_url": (
            f"/v2/workbook/trust/validation?project={project_code}"
            if _can_defer_validation
            else None
        ),
        "authority": "REFERENCE REGRESSION CHECK — P1.3 pinned-reference reconciliation (app.model_validation)",
    }

    # ── D. FINCO VERIFY (separate authority — never implied by validation) ──
    ver_state, verify = _v11.get_verify_state(user_id, project_id)
    verify_section = _verify_section(ver_state, verify if ver_state == STATE_AVAILABLE else {})
    verify_section["verify_url"] = f"/verify/run/{project_code}"

    # ── E. Institutional export metadata (action = existing V2 export) ──
    exp_state, export_meta = _v11.get_export_metadata(user_id, project_id)

    # ── Run Integrity Checks (H-4b): internal consistency of the committed Last Run.
    # Read-only recomputation over evidence recorded at commit; never runs the model.
    # Separate authority from the Reference Regression Check and FINCO VERIFY.
    integ_state, integrity = _v11.get_run_integrity_checks(user_id, project_id)
    integrity_section = _integrity_section(
        integ_state, integrity if integ_state == STATE_AVAILABLE else {})

    # ── G. Signed Run Certificate (separate authority, DEFERRED — never signed
    #        at render time, explicit user action required)
    _can_defer_certificate = id_state == STATE_AVAILABLE and any_run_committed
    certificate: dict[str, Any] = {
        "state": "DEFERRED" if _can_defer_certificate else STATE_UNAVAILABLE,
        "load_url": (
            f"/v2/workbook/trust/certificate?project={project_code}"
            if _can_defer_certificate
            else None
        ),
        "not_verify": True,
        "authority": _CERTIFICATE_AUTHORITY,
    }

    overall = (
        STATE_AVAILABLE
        if (id_state == STATE_AVAILABLE and any_run_committed)
        else STATE_UNAVAILABLE
    )

    return {
        "overall_state": overall,
        "last_run": {
            "state": id_state,
            "snapshot_id": identity.get("snapshot_id"),
            "composite_hash": identity.get("composite_hash"),
            "composite_hash_short": _short_hash(identity.get("composite_hash")),
            "run_at": identity.get("run_at"),
            "run_at_display": _fmt_datetime(identity.get("run_at")),
            "scenario_id": identity.get("scenario_id"),
            "run_origin": identity.get("run_origin"),
            "engine_version": identity.get("engine_version"),
            "git_sha": identity.get("git_sha"),
            "git_branch": identity.get("git_branch"),
            "working_copy_changed_since_run": identity.get(
                "working_copy_changed_since_run"
            ),
        },
        "kpis": _kpi_section(kpi_state, kpis, identity),
        "validation": _validation_section(validation["state"], validation),
        "verify": verify_section,
        "export": _export_section(exp_state, export_meta),
        "integrity": integrity_section,
        "methodology": _methodology_section(),
        "certificate": certificate,
    }


__all__ = ["build_trust_pack", "build_certificate_fragment", "build_validation_fragment"]
