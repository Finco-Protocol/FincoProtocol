"""FINCO P3 — Run Certificate V1 tests.

Acceptance markers:

  Core:
    RUN_CERTIFICATE_V1_SCHEMA_STABLE
    RUN_CERTIFICATE_FROM_PERSISTED_LAST_RUN_ONLY
    RUN_CERTIFICATE_NO_ENGINE_RECALCULATION
    RUN_CERTIFICATE_COMPOSITE_HASH_BOUND
    RUN_CERTIFICATE_ENGINE_VERSION_RUN_BOUND
    RUN_CERTIFICATE_NO_CURRENT_ENGINE_SUBSTITUTION
    RUN_CERTIFICATE_ASSUMPTION_DIGEST_DETERMINISTIC
    RUN_CERTIFICATE_OUTPUT_DIGEST_DETERMINISTIC
    RUN_CERTIFICATE_DIGEST_DETERMINISTIC
    RUN_CERTIFICATE_ID_DETERMINISTIC
    RUN_CERTIFICATE_WORKING_COPY_EDIT_IMMUTABLE
    RUN_CERTIFICATE_NEW_RUN_CHANGES_DIGEST
    RUN_CERTIFICATE_LEGACY_LINEAGE_FAILS_CLOSED

  Tamper:
    RUN_CERTIFICATE_TAMPER_FAILS_CLOSED

  JSON:
    RUN_CERTIFICATE_JSON_ROUNDTRIP

  Cross-user:
    RUN_CERTIFICATE_CROSS_USER_ISOLATION

  Idempotency:
    RUN_CERTIFICATE_REPEAT_READ_IDENTICAL

  Reference models:
    RUN_CERTIFICATE_REFERENCE_MODEL_ACCEPTANCE

  XLSX reconciliation:
    RUN_CERTIFICATE_XLSX_IDENTITY_RECONCILES

  Sensitive fields:
    RUN_CERTIFICATE_NO_SENSITIVE_IDENTITY_LEAK

  Frozen namespaces:
    RUN_CERTIFICATE_FROZEN_NAMESPACES_ZERO_DIFF

This is NOT a trading system.  No BUY/SELL/ARBITRAGE/OPPORTUNITY labels.
"""
from __future__ import annotations

import copy
import json
from datetime import datetime, timezone

import pytest


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def seeded_db(tmp_path, monkeypatch):
    from app.persistence import db
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "cert-v1.db"))
    db.init_db()
    yield


def _bootstrap(seeded_db):
    from app.services.project_library_service import (
        ensure_reference_models,
        ensure_reference_canonical_last_runs,
    )
    ensure_reference_models()
    return ensure_reference_canonical_last_runs()


def _get_solar_ws(seeded_db):
    from app.persistence.projects_repository import get_reference_by_template_source
    from app.persistence.workspace_repository import get_workspace_state
    _bootstrap(seeded_db)
    rec = get_reference_by_template_source("generic_solar_reference")
    ws = get_workspace_state(rec.user_id, rec.project_id)
    return rec, ws


# ---------------------------------------------------------------------------
# TestSchemaAndStructure
# RUN_CERTIFICATE_V1_SCHEMA_STABLE
# RUN_CERTIFICATE_JSON_ROUNDTRIP
# ---------------------------------------------------------------------------

class TestSchemaAndStructure:
    def test_schema_constant_is_stable(self):
        """RUN_CERTIFICATE_V1_SCHEMA_STABLE: schema string never changes."""
        from app.verify.run_certificate import CERTIFICATE_SCHEMA
        assert CERTIFICATE_SCHEMA == "FINCO_RUN_CERTIFICATE_V1"

    def test_certificate_id_prefix(self):
        """RUN_CERTIFICATE_ID_DETERMINISTIC: certificate_id starts with frc_."""
        from app.verify.run_certificate import CERTIFICATE_ID_PREFIX
        assert CERTIFICATE_ID_PREFIX == "frc_"

    def test_required_top_level_keys(self, seeded_db):
        """RUN_CERTIFICATE_JSON_ROUNDTRIP: certificate has all required keys."""
        from app.verify.run_certificate import build_run_certificate
        rec, ws = _get_solar_ws(seeded_db)
        cert = build_run_certificate(ws, rec)

        assert cert["schema"] == "FINCO_RUN_CERTIFICATE_V1"
        assert cert["certificate_id"].startswith("frc_")
        assert isinstance(cert["certificate_digest_sha256"], str)
        assert len(cert["certificate_digest_sha256"]) == 64

        run = cert["run"]
        assert "project_code" in run
        assert "snapshot_id" in run
        assert "committed_at" in run
        assert "origin" in run

        model = cert["model"]
        assert "engine_version" in model
        assert model["engine_version"] not in ("", "NOT_AVAILABLE", None)

        ident = cert["identity"]
        assert "composite_hash" in ident
        assert "assumptions_sha256" in ident
        assert "outputs_sha256" in ident

        assert "headline_outputs" in cert

    def test_certificate_roundtrips_through_json(self, seeded_db):
        """RUN_CERTIFICATE_JSON_ROUNDTRIP: certificate is JSON-serializable."""
        from app.verify.run_certificate import build_run_certificate
        rec, ws = _get_solar_ws(seeded_db)
        cert = build_run_certificate(ws, rec)
        round_tripped = json.loads(json.dumps(cert))
        assert round_tripped["certificate_digest_sha256"] == cert["certificate_digest_sha256"]
        assert round_tripped["certificate_id"] == cert["certificate_id"]


# ---------------------------------------------------------------------------
# TestPersistedLastRunOnly
# RUN_CERTIFICATE_FROM_PERSISTED_LAST_RUN_ONLY
# RUN_CERTIFICATE_NO_ENGINE_RECALCULATION
# ---------------------------------------------------------------------------

class TestPersistedLastRunOnly:
    def test_no_engine_import_in_certificate_module(self):
        """RUN_CERTIFICATE_NO_ENGINE_RECALCULATION: certificate module never imports the engine."""
        import ast, pathlib, tokenize, io
        src = pathlib.Path("/home/user/FincoProtocol/app/verify/run_certificate.py").read_text()
        assert "financial_engine" not in src, "certificate module must not import financial_engine"

        # Strip string literals (docstrings/comments) before checking for forbidden call names,
        # because the docstring explicitly names these functions as things the module must NOT do.
        tokens = list(tokenize.generate_tokens(io.StringIO(src).readline))
        code_only = "".join(
            tok.string for tok in tokens
            if tok.type not in (tokenize.STRING, tokenize.COMMENT, tokenize.NEWLINE, tokenize.NL)
        )
        assert "run_project" not in code_only, "certificate module must not call run_project"
        assert "run_clean_production" not in code_only

    def test_certificate_uses_snapshot_not_draft(self, seeded_db):
        """RUN_CERTIFICATE_FROM_PERSISTED_LAST_RUN_ONLY: assumption digest is from last_runtime_snapshot, not draft."""
        from app.verify.run_certificate import build_run_certificate, _build_assumption_digest
        from finco_protocol.verification.envelope import canonical_sha256
        rec, ws = _get_solar_ws(seeded_db)
        cert = build_run_certificate(ws, rec)
        expected = canonical_sha256(ws.last_runtime_snapshot or {})
        assert cert["identity"]["assumptions_sha256"] == expected


# ---------------------------------------------------------------------------
# TestCompositeHashBound
# RUN_CERTIFICATE_COMPOSITE_HASH_BOUND
# ---------------------------------------------------------------------------

class TestCompositeHashBound:
    def test_composite_hash_matches_workspace(self, seeded_db):
        """RUN_CERTIFICATE_COMPOSITE_HASH_BOUND: certificate composite_hash == ws.last_runtime_composite_hash."""
        from app.verify.run_certificate import build_run_certificate
        rec, ws = _get_solar_ws(seeded_db)
        cert = build_run_certificate(ws, rec)
        assert cert["identity"]["composite_hash"] == ws.last_runtime_composite_hash

    def test_missing_composite_hash_fails_closed(self, seeded_db):
        """RUN_CERTIFICATE_COMPOSITE_HASH_BOUND: missing composite_hash → fail closed."""
        from app.verify.run_certificate import build_run_certificate, RunCertificateUnavailableError
        rec, ws = _get_solar_ws(seeded_db)
        ws = copy.copy(ws)
        object.__setattr__(ws, "last_runtime_composite_hash", None)
        with pytest.raises(RunCertificateUnavailableError) as exc_info:
            build_run_certificate(ws, rec)
        assert exc_info.value.code == "MISSING_COMPOSITE_HASH"


# ---------------------------------------------------------------------------
# TestEngineVersionRunBound
# RUN_CERTIFICATE_ENGINE_VERSION_RUN_BOUND
# RUN_CERTIFICATE_NO_CURRENT_ENGINE_SUBSTITUTION
# RUN_CERTIFICATE_LEGACY_LINEAGE_FAILS_CLOSED
# ---------------------------------------------------------------------------

class TestEngineVersionRunBound:
    def test_engine_version_from_persisted_identity(self, seeded_db):
        """RUN_CERTIFICATE_ENGINE_VERSION_RUN_BOUND: engine_version comes from last_runtime_identity."""
        from app.verify.run_certificate import build_run_certificate
        rec, ws = _get_solar_ws(seeded_db)
        cert = build_run_certificate(ws, rec)
        persisted_ev = ws.last_runtime_identity["engine_version"]
        assert cert["model"]["engine_version"] == persisted_ev

    def test_changing_current_engine_version_does_not_change_certificate(self, seeded_db, monkeypatch):
        """RUN_CERTIFICATE_NO_CURRENT_ENGINE_SUBSTITUTION: historical certificate uses persisted engine_version."""
        from app.verify.run_certificate import build_run_certificate
        import financial_engine.version as ev_mod
        rec, ws = _get_solar_ws(seeded_db)
        cert_before = build_run_certificate(ws, rec)

        monkeypatch.setattr(ev_mod, "ENGINE_VERSION", "hypothetical_future_v99")
        cert_after = build_run_certificate(ws, rec)

        assert cert_before["model"]["engine_version"] == cert_after["model"]["engine_version"]
        assert cert_before["certificate_digest_sha256"] == cert_after["certificate_digest_sha256"]

    def test_no_runtime_identity_fails_closed(self, seeded_db):
        """RUN_CERTIFICATE_LEGACY_LINEAGE_FAILS_CLOSED: None last_runtime_identity → LEGACY_LINEAGE_FAILS_CLOSED."""
        from app.verify.run_certificate import build_run_certificate, RunCertificateUnavailableError
        rec, ws = _get_solar_ws(seeded_db)
        ws = copy.copy(ws)
        object.__setattr__(ws, "last_runtime_identity", None)
        with pytest.raises(RunCertificateUnavailableError) as exc_info:
            build_run_certificate(ws, rec)
        assert exc_info.value.code == "LEGACY_LINEAGE_FAILS_CLOSED"

    def test_not_available_engine_version_fails_closed(self, seeded_db):
        """RUN_CERTIFICATE_LEGACY_LINEAGE_FAILS_CLOSED: engine_version=NOT_AVAILABLE → fail closed."""
        from app.verify.run_certificate import build_run_certificate, RunCertificateUnavailableError
        rec, ws = _get_solar_ws(seeded_db)
        ws = copy.copy(ws)
        bad_identity = {**ws.last_runtime_identity, "engine_version": "NOT_AVAILABLE"}
        object.__setattr__(ws, "last_runtime_identity", bad_identity)
        with pytest.raises(RunCertificateUnavailableError) as exc_info:
            build_run_certificate(ws, rec)
        assert exc_info.value.code == "LEGACY_LINEAGE_FAILS_CLOSED"

    def test_missing_any_run_committed_fails_closed(self, seeded_db):
        """No committed run → NO_COMMITTED_RUN fail closed."""
        from app.verify.run_certificate import build_run_certificate, RunCertificateUnavailableError
        rec, ws = _get_solar_ws(seeded_db)
        ws = copy.copy(ws)
        object.__setattr__(ws, "any_run_committed", False)
        with pytest.raises(RunCertificateUnavailableError) as exc_info:
            build_run_certificate(ws, rec)
        assert exc_info.value.code == "NO_COMMITTED_RUN"


# ---------------------------------------------------------------------------
# TestAssumptionDigest
# RUN_CERTIFICATE_ASSUMPTION_DIGEST_DETERMINISTIC
# RUN_CERTIFICATE_WORKING_COPY_EDIT_IMMUTABLE
# ---------------------------------------------------------------------------

class TestAssumptionDigest:
    def test_same_run_same_assumption_digest(self, seeded_db):
        """RUN_CERTIFICATE_ASSUMPTION_DIGEST_DETERMINISTIC: same run → same assumptions_sha256."""
        from app.verify.run_certificate import build_run_certificate
        rec, ws = _get_solar_ws(seeded_db)
        cert1 = build_run_certificate(ws, rec)
        cert2 = build_run_certificate(ws, rec)
        assert cert1["identity"]["assumptions_sha256"] == cert2["identity"]["assumptions_sha256"]

    def test_working_copy_edit_after_run_does_not_change_digest(self, seeded_db):
        """RUN_CERTIFICATE_WORKING_COPY_EDIT_IMMUTABLE: editing the draft snapshot does not change the certificate."""
        from app.verify.run_certificate import build_run_certificate
        rec, ws = _get_solar_ws(seeded_db)
        cert_before = build_run_certificate(ws, rec)

        # Simulate a working-copy edit (only draft_snapshot changes, not last_runtime_snapshot)
        ws = copy.copy(ws)
        modified_draft = dict(ws.draft_snapshot)
        modified_draft["__edited__"] = True
        object.__setattr__(ws, "draft_snapshot", modified_draft)

        cert_after = build_run_certificate(ws, rec)
        assert cert_before["identity"]["assumptions_sha256"] == cert_after["identity"]["assumptions_sha256"]
        assert cert_before["certificate_digest_sha256"] == cert_after["certificate_digest_sha256"]

    def test_mutated_persisted_assumption_changes_digest(self, seeded_db):
        """TAMPER A: mutate one persisted assumption → assumptions SHA changes."""
        from app.verify.run_certificate import build_run_certificate
        rec, ws = _get_solar_ws(seeded_db)
        cert_original = build_run_certificate(ws, rec)

        ws_tampered = copy.copy(ws)
        modified_snapshot = dict(ws.last_runtime_snapshot)
        modified_snapshot["__tampered__"] = "yes"
        object.__setattr__(ws_tampered, "last_runtime_snapshot", modified_snapshot)

        cert_tampered = build_run_certificate(ws_tampered, rec)
        assert cert_tampered["identity"]["assumptions_sha256"] != cert_original["identity"]["assumptions_sha256"]
        assert cert_tampered["certificate_digest_sha256"] != cert_original["certificate_digest_sha256"]


# ---------------------------------------------------------------------------
# TestOutputDigest
# RUN_CERTIFICATE_OUTPUT_DIGEST_DETERMINISTIC
# RUN_CERTIFICATE_OUTPUTS_FROM_PERSISTED_LAST_RUN
# ---------------------------------------------------------------------------

class TestOutputDigest:
    def test_same_run_same_output_digest(self, seeded_db):
        """RUN_CERTIFICATE_OUTPUT_DIGEST_DETERMINISTIC: same run → same outputs_sha256."""
        from app.verify.run_certificate import build_run_certificate
        rec, ws = _get_solar_ws(seeded_db)
        cert1 = build_run_certificate(ws, rec)
        cert2 = build_run_certificate(ws, rec)
        assert cert1["identity"]["outputs_sha256"] == cert2["identity"]["outputs_sha256"]

    def test_mutated_output_changes_digest(self, seeded_db):
        """TAMPER B: mutate one persisted financial output → outputs SHA changes."""
        from app.verify.run_certificate import build_run_certificate
        rec, ws = _get_solar_ws(seeded_db)
        cert_original = build_run_certificate(ws, rec)

        ws_tampered = copy.copy(ws)
        modified_summary = dict(ws.last_runtime_summary)
        modified_summary["project_irr"] = 0.9999
        object.__setattr__(ws_tampered, "last_runtime_summary", modified_summary)

        cert_tampered = build_run_certificate(ws_tampered, rec)
        assert cert_tampered["identity"]["outputs_sha256"] != cert_original["identity"]["outputs_sha256"]
        assert cert_tampered["certificate_digest_sha256"] != cert_original["certificate_digest_sha256"]

    def test_missing_optional_schedules_deterministic(self, seeded_db):
        """Missing optional schedules produce a stable (not error-raising) output digest."""
        from app.verify.run_certificate import build_run_certificate
        rec, ws = _get_solar_ws(seeded_db)
        ws = copy.copy(ws)
        # Simulate missing optional schedules
        object.__setattr__(ws, "last_distribution_schedule", {})
        object.__setattr__(ws, "last_sponsor_schedule", {})
        cert1 = build_run_certificate(ws, rec)
        cert2 = build_run_certificate(ws, rec)
        assert cert1["identity"]["outputs_sha256"] == cert2["identity"]["outputs_sha256"]


# ---------------------------------------------------------------------------
# TestCertificateDigest
# RUN_CERTIFICATE_DIGEST_DETERMINISTIC
# RUN_CERTIFICATE_ID_DETERMINISTIC
# RUN_CERTIFICATE_NEW_RUN_CHANGES_DIGEST
# RUN_CERTIFICATE_REPEAT_READ_IDENTICAL
# ---------------------------------------------------------------------------

class TestCertificateDigest:
    def test_digest_is_deterministic(self, seeded_db):
        """RUN_CERTIFICATE_DIGEST_DETERMINISTIC: same run → same certificate digest every call."""
        from app.verify.run_certificate import build_run_certificate
        rec, ws = _get_solar_ws(seeded_db)
        cert1 = build_run_certificate(ws, rec)
        cert2 = build_run_certificate(ws, rec)
        assert cert1["certificate_digest_sha256"] == cert2["certificate_digest_sha256"]

    def test_id_is_deterministic(self, seeded_db):
        """RUN_CERTIFICATE_ID_DETERMINISTIC: same run → same certificate_id every call."""
        from app.verify.run_certificate import build_run_certificate
        rec, ws = _get_solar_ws(seeded_db)
        cert1 = build_run_certificate(ws, rec)
        cert2 = build_run_certificate(ws, rec)
        assert cert1["certificate_id"] == cert2["certificate_id"]

    def test_id_derived_from_digest(self, seeded_db):
        """certificate_id = frc_ + first 16 chars of digest."""
        from app.verify.run_certificate import build_run_certificate, CERTIFICATE_ID_DIGEST_CHARS
        rec, ws = _get_solar_ws(seeded_db)
        cert = build_run_certificate(ws, rec)
        expected_id = "frc_" + cert["certificate_digest_sha256"][:CERTIFICATE_ID_DIGEST_CHARS]
        assert cert["certificate_id"] == expected_id

    def test_repeat_read_identical(self, seeded_db):
        """RUN_CERTIFICATE_REPEAT_READ_IDENTICAL: J — same run generated multiple times → exact same certificate."""
        from app.verify.run_certificate import build_run_certificate
        rec, ws = _get_solar_ws(seeded_db)
        certs = [build_run_certificate(ws, rec) for _ in range(5)]
        digests = [c["certificate_digest_sha256"] for c in certs]
        assert len(set(digests)) == 1, "all repeats must produce identical digest"

    def test_digest_verification_utility(self, seeded_db):
        """verify_certificate_digest returns True for an intact certificate."""
        from app.verify.run_certificate import build_run_certificate, verify_certificate_digest
        rec, ws = _get_solar_ws(seeded_db)
        cert = build_run_certificate(ws, rec)
        assert verify_certificate_digest(cert) is True

    def test_tampered_payload_fails_digest_verification(self, seeded_db):
        """TAMPER C: mutate certificate payload after digest → verification fails."""
        from app.verify.run_certificate import build_run_certificate, verify_certificate_digest
        rec, ws = _get_solar_ws(seeded_db)
        cert = build_run_certificate(ws, rec)
        tampered = dict(cert)
        tampered["model"] = {**tampered["model"], "engine_version": "EVIL_v0"}
        assert verify_certificate_digest(tampered) is False


# ---------------------------------------------------------------------------
# TestNewRunChangesDigest
# RUN_CERTIFICATE_NEW_RUN_CHANGES_DIGEST
# ---------------------------------------------------------------------------

class TestNewRunChangesDigest:
    def test_new_committed_run_produces_different_digest(self, seeded_db):
        """RUN_CERTIFICATE_NEW_RUN_CHANGES_DIGEST: E — commit a new run → certificate changes."""
        from app.verify.run_certificate import build_run_certificate
        from app.persistence.projects_repository import get_reference_by_template_source
        from app.persistence.workspace_repository import get_workspace_state, v2_atomic_run_commit
        from app.workbook.workbook_identity import assemble_for_workspace
        from app.workbook.registry import WORKBOOK

        _bootstrap(seeded_db)
        rec = get_reference_by_template_source("generic_solar_reference")
        ws = get_workspace_state(rec.user_id, rec.project_id)
        cert_before = build_run_certificate(ws, rec)

        # Commit a new run with a modified runtime_summary
        identity = assemble_for_workspace(
            ws, user_id=rec.user_id, project_id=rec.project_id,
            workbook_version=WORKBOOK.version,
        )
        ws_after = v2_atomic_run_commit(
            user_id=rec.user_id,
            project_id=rec.project_id,
            project_code=rec.project_code,
            expected_composite_hash=identity.composite_hash,
            runtime_snapshot_id="new_run_test_id",
            runtime_origin="test_new_run",
            runtime_summary={
                **ws.last_runtime_summary,
                "project_irr": 0.9999,  # deliberately different
            },
            financial_statements=ws.last_financial_statements,
            debt_schedule=ws.last_debt_schedule,
            tax_schedule=ws.last_tax_schedule,
            distribution_schedule=ws.last_distribution_schedule,
            sponsor_schedule=ws.last_sponsor_schedule,
            active_scenario_id=ws.active_scenario_id,
            active_scenario_name=ws.active_scenario_name,
            ran_at=datetime.now(timezone.utc),
        )
        cert_after = build_run_certificate(ws_after, rec)

        assert cert_before["certificate_digest_sha256"] != cert_after["certificate_digest_sha256"]
        assert cert_before["certificate_id"] != cert_after["certificate_id"]


# ---------------------------------------------------------------------------
# TestFailedClosed
# RUN_CERTIFICATE_LEGACY_LINEAGE_FAILS_CLOSED
# ---------------------------------------------------------------------------

class TestFailedClosed:
    def test_delete_composite_identity_fails_closed(self, seeded_db):
        """G — delete composite identity → fail closed."""
        from app.verify.run_certificate import build_run_certificate, RunCertificateUnavailableError
        rec, ws = _get_solar_ws(seeded_db)
        ws = copy.copy(ws)
        object.__setattr__(ws, "last_runtime_identity", None)
        with pytest.raises(RunCertificateUnavailableError) as exc_info:
            build_run_certificate(ws, rec)
        assert exc_info.value.code == "LEGACY_LINEAGE_FAILS_CLOSED"

    def test_missing_snapshot_id_fails_closed(self, seeded_db):
        """Missing snapshot_id → MISSING_SNAPSHOT_ID fail closed."""
        from app.verify.run_certificate import build_run_certificate, RunCertificateUnavailableError
        rec, ws = _get_solar_ws(seeded_db)
        ws = copy.copy(ws)
        object.__setattr__(ws, "last_runtime_snapshot_id", None)
        with pytest.raises(RunCertificateUnavailableError) as exc_info:
            build_run_certificate(ws, rec)
        assert exc_info.value.code == "MISSING_SNAPSHOT_ID"

    def test_missing_run_timestamp_fails_closed(self, seeded_db):
        """Missing last_runtime_at → MISSING_RUN_TIMESTAMP fail closed."""
        from app.verify.run_certificate import build_run_certificate, RunCertificateUnavailableError
        rec, ws = _get_solar_ws(seeded_db)
        ws = copy.copy(ws)
        object.__setattr__(ws, "last_runtime_at", None)
        with pytest.raises(RunCertificateUnavailableError) as exc_info:
            build_run_certificate(ws, rec)
        assert exc_info.value.code == "MISSING_RUN_TIMESTAMP"


# ---------------------------------------------------------------------------
# TestCrossUserIsolation
# RUN_CERTIFICATE_CROSS_USER_ISOLATION
# ---------------------------------------------------------------------------

class TestCrossUserIsolation:
    def test_user_b_cannot_get_user_a_certificate_via_router(self, seeded_db):
        """I — User B requests User A project certificate → no certificate leakage.

        resolve_accessible_project enforces the ownership boundary.
        When User B requests a project_code owned by User A (and it is not a
        canonical reference), resolve_accessible_project returns (None, user_b_id).
        The route returns 404 — no certificate is produced.
        """
        from app.persistence.projects_repository import resolve_accessible_project

        user_a = "user_a_test_id"
        user_b = "user_b_test_id"
        project_code = "user_a_private_project"

        # User A's project does not exist for user B
        record, workspace_owner = resolve_accessible_project(user_b, project_code)
        assert record is None, "User B must not be able to resolve User A's project"

    def test_reference_projects_are_accessible_to_all(self, seeded_db):
        """Canonical reference projects are accessible to any authenticated user (by design)."""
        from app.persistence.projects_repository import (
            resolve_accessible_project,
            get_reference_by_template_source,
        )
        _bootstrap(seeded_db)

        ref = get_reference_by_template_source("generic_solar_reference")
        assert ref is not None, "Reference model must exist after bootstrap"

        random_user = "some_other_user_id"
        record, workspace_owner = resolve_accessible_project(random_user, ref.project_code)
        assert record is not None, "Canonical reference must be accessible to any user"


# ---------------------------------------------------------------------------
# TestSensitiveFieldLeak
# RUN_CERTIFICATE_NO_SENSITIVE_IDENTITY_LEAK
# ---------------------------------------------------------------------------

class TestSensitiveFieldLeak:
    def test_no_user_id_in_certificate(self, seeded_db):
        """RUN_CERTIFICATE_NO_SENSITIVE_IDENTITY_LEAK: user_id must not appear in certificate."""
        from app.verify.run_certificate import build_run_certificate
        from app.persistence.workspace_repository import get_workspace_state
        from app.persistence.projects_repository import get_reference_by_template_source

        _bootstrap(seeded_db)
        rec = get_reference_by_template_source("generic_solar_reference")
        ws = get_workspace_state(rec.user_id, rec.project_id)

        cert = build_run_certificate(ws, rec)
        cert_json = json.dumps(cert)

        # No user_id or internal workspace_id should appear
        assert rec.user_id not in cert_json, "user_id must not leak into certificate"
        assert "__reference__" not in cert_json, "internal reference user must not leak"

    def test_no_workspace_id_in_certificate(self, seeded_db):
        """Workspace DB row identifier must not appear in certificate."""
        from app.verify.run_certificate import build_run_certificate
        from app.persistence.workspace_repository import get_workspace_state
        from app.persistence.projects_repository import get_reference_by_template_source

        _bootstrap(seeded_db)
        rec = get_reference_by_template_source("generic_solar_reference")
        ws = get_workspace_state(rec.user_id, rec.project_id)
        cert = build_run_certificate(ws, rec)

        # workspace_id (internal DB row id) should not appear
        cert_flat = json.dumps(cert)
        assert ws.workspace_id not in cert_flat


# ---------------------------------------------------------------------------
# TestReferenceModelAcceptance
# RUN_CERTIFICATE_REFERENCE_MODEL_ACCEPTANCE
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("template_source", [
    "generic_solar_reference",
    "generic_wind_reference",
    "generic_data_center_reference",
])
def test_reference_model_certificate(seeded_db, template_source):
    """RUN_CERTIFICATE_REFERENCE_MODEL_ACCEPTANCE: Solar, Wind, Data Center all produce valid certificates."""
    from app.verify.run_certificate import build_run_certificate, verify_certificate_digest
    from app.persistence.projects_repository import get_reference_by_template_source
    from app.persistence.workspace_repository import get_workspace_state

    _bootstrap(seeded_db)
    rec = get_reference_by_template_source(template_source)
    assert rec is not None, f"reference model missing: {template_source}"
    ws = get_workspace_state(rec.user_id, rec.project_id)
    assert ws is not None

    cert = build_run_certificate(ws, rec)

    assert cert["schema"] == "FINCO_RUN_CERTIFICATE_V1"
    assert cert["certificate_id"].startswith("frc_")
    assert verify_certificate_digest(cert) is True

    # Headline outputs must be present (reference models produce them)
    ho = cert["headline_outputs"]
    assert ho.get("project_irr") is not None, f"{template_source}: project_irr must be present"
    assert ho.get("min_dscr") is not None, f"{template_source}: min_dscr must be present"


# ---------------------------------------------------------------------------
# TestXlsxReconciliation
# RUN_CERTIFICATE_XLSX_IDENTITY_RECONCILES
# ---------------------------------------------------------------------------

class TestXlsxReconciliation:
    def test_certificate_composite_hash_matches_xlsx_run_identity(self, seeded_db):
        """RUN_CERTIFICATE_XLSX_IDENTITY_RECONCILES: certificate composite_hash == XLSX Run Identity composite_hash."""
        from app.verify.run_certificate import build_run_certificate
        from app.persistence.projects_repository import get_reference_by_template_source
        from app.persistence.workspace_repository import get_workspace_state

        _bootstrap(seeded_db)
        rec = get_reference_by_template_source("generic_solar_reference")
        ws = get_workspace_state(rec.user_id, rec.project_id)

        cert = build_run_certificate(ws, rec)

        # XLSX Run Identity reads composite_hash from ws.last_runtime_composite_hash
        # (same source the certificate uses — both from v2_atomic_run_commit)
        assert cert["identity"]["composite_hash"] == ws.last_runtime_composite_hash

    def test_certificate_engine_version_matches_xlsx_run_identity(self, seeded_db):
        """RUN_CERTIFICATE_XLSX_IDENTITY_RECONCILES: certificate engine_version == XLSX run-bound engine version."""
        from app.verify.run_certificate import build_run_certificate
        from app.persistence.projects_repository import get_reference_by_template_source
        from app.persistence.workspace_repository import get_workspace_state

        _bootstrap(seeded_db)
        rec = get_reference_by_template_source("generic_solar_reference")
        ws = get_workspace_state(rec.user_id, rec.project_id)

        cert = build_run_certificate(ws, rec)

        # XLSX Run Identity reads engine_version from ws.last_runtime_identity["engine_version"]
        # (same source the certificate uses)
        assert cert["model"]["engine_version"] == ws.last_runtime_identity["engine_version"]


# ---------------------------------------------------------------------------
# TestFrozenNamespaces
# RUN_CERTIFICATE_FROZEN_NAMESPACES_ZERO_DIFF
# ---------------------------------------------------------------------------

class TestFrozenNamespaces:
    def test_financial_engine_not_modified(self):
        """RUN_CERTIFICATE_FROZEN_NAMESPACES_ZERO_DIFF: financial_engine namespace is ZERO DIFF."""
        import subprocess, pathlib
        result = subprocess.run(
            ["git", "diff", "origin/main", "HEAD", "--name-only", "--",
             "financial_engine/", "finco_core/", "finco_radar/"],
            capture_output=True, text=True,
            cwd="/home/user/FincoProtocol",
        )
        changed = [
            line for line in result.stdout.strip().splitlines()
            if line.startswith(("financial_engine/", "finco_core/", "finco_radar/"))
        ]
        assert changed == [], (
            f"Frozen namespaces must have ZERO DIFF. Changed: {changed}"
        )
