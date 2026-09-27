"""FINCO Reference Certificate V1 — deterministic certificate from a live Solar reference run.

Unlike RunCertificateV1 (which requires a committed workspace state), this module
builds a certificate directly from run_project() output. Used exclusively by the
public reference verify endpoint.

No user data, no workspace state, no private project data.

Markers:
  REF_CERT_NO_WORKSPACE_STATE
  REF_CERT_SOLAR_REFERENCE_ONLY
  REF_CERT_DETERMINISTIC_GIVEN_SAME_ENGINE
  REF_CERT_ASSUMPTIONS_FROM_FACTORY
"""
from __future__ import annotations

from typing import Any

REFERENCE_CERTIFICATE_SCHEMA = "FINCO_REFERENCE_CERTIFICATE_V1"
REFERENCE_CERTIFICATE_ID_PREFIX = "frc_"
REFERENCE_CERTIFICATE_ASSET_ID = "solar-reference-a"

_HEADLINE_KEYS = (
    "project_irr",
    "equity_irr",
    "sponsor_irr",
    "min_dscr",
    "senior_debt_keur",
    "total_capex_keur",
)


class ReferenceCertificateUnavailableError(Exception):
    """Raised when the reference certificate cannot be built."""

    def __init__(self, reason: str, code: str) -> None:
        super().__init__(reason)
        self.reason = reason
        self.code = code


def build_solar_reference_package() -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    """Run the Solar reference model and return (certificate, assumptions, outputs).

    All three are plain dicts suitable for canonical serialization and SHA-256 hashing.
    Runs synchronously — call via run_in_threadpool in async routes.

    Raises ReferenceCertificateUnavailableError on any failure.

    REF_CERT_NO_WORKSPACE_STATE
    REF_CERT_SOLAR_REFERENCE_ONLY
    """
    from app.project_factories import create_generic_solar_reference
    from app.api.project_runner import run_project
    from finco_core.inputs.serialization import project_inputs_to_dict
    from finco_protocol.verification.envelope import canonical_sha256
    from financial_engine.version import ENGINE_VERSION

    try:
        project_inputs = create_generic_solar_reference()
    except Exception as exc:
        raise ReferenceCertificateUnavailableError(
            f"Failed to create Solar reference inputs: {exc}",
            code="FACTORY_FAILURE",
        ) from exc

    try:
        payload = run_project("Generic Solar Reference", "Base",
                              project_inputs_override=project_inputs)
    except Exception as exc:
        raise ReferenceCertificateUnavailableError(
            f"Solar reference model run failed: {exc}",
            code="RUN_FAILURE",
        ) from exc

    # Assumptions: canonical serialisation of the factory project inputs.
    # REF_CERT_ASSUMPTIONS_FROM_FACTORY
    try:
        assumptions = project_inputs_to_dict(project_inputs)
    except Exception as exc:
        raise ReferenceCertificateUnavailableError(
            f"Failed to serialise Solar reference inputs: {exc}",
            code="SERIALISATION_FAILURE",
        ) from exc

    # Outputs: same fields as RunCertificateV1 output digest payload.
    outputs: dict[str, Any] = {
        "runtime_summary": payload.get("kpis") or {},
        "financial_statements": payload.get("financial_statements") or {},
        "debt_schedule": payload.get("debt_schedule") or {},
        "tax_schedule": payload.get("tax_schedule") or {},
        "distribution_schedule": payload.get("distribution_schedule") or {},
        "sponsor_schedule": payload.get("sponsor_schedule") or {},
    }

    assumptions_sha256 = canonical_sha256(assumptions)
    outputs_sha256 = canonical_sha256(outputs)

    kpis = payload.get("kpis") or {}
    headline_outputs = {k: kpis.get(k) for k in _HEADLINE_KEYS}

    cert_payload: dict[str, Any] = {
        "schema": REFERENCE_CERTIFICATE_SCHEMA,
        "asset_id": REFERENCE_CERTIFICATE_ASSET_ID,
        "run": {
            "project_code": project_inputs.info.code,
            "project_name": project_inputs.info.name,
            "scenario": "Base",
        },
        "model": {
            "engine_version": ENGINE_VERSION,
        },
        "identity": {
            "assumptions_sha256": assumptions_sha256,
            "outputs_sha256": outputs_sha256,
        },
        "headline_outputs": headline_outputs,
    }

    certificate_digest_sha256 = canonical_sha256(cert_payload)
    certificate_id = REFERENCE_CERTIFICATE_ID_PREFIX + certificate_digest_sha256[:16]

    cert_payload["certificate_id"] = certificate_id
    cert_payload["certificate_digest_sha256"] = certificate_digest_sha256

    return cert_payload, assumptions, outputs


def verify_reference_certificate_digest(certificate: dict[str, Any]) -> bool:
    """Verify that certificate_digest_sha256 matches the certificate payload.

    Returns True if intact, False if tampered.
    """
    from finco_protocol.verification.envelope import canonical_sha256

    digest = certificate.get("certificate_digest_sha256")
    if not digest:
        return False
    payload_without_digest = {
        k: v for k, v in certificate.items()
        if k not in ("certificate_id", "certificate_digest_sha256")
    }
    expected = canonical_sha256(payload_without_digest)
    return expected == digest
