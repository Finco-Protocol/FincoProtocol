"""Model Trust Pack UX V1 — canonical-evidence workbook surface acceptance.

Covers the mandatory trust-pack UX gates:

  TRUST_PACK_CANONICAL_LAST_RUN_ONLY
  TRUST_PACK_DIRTY_WC_DISCLOSED
  TRUST_PACK_NO_EXPORT_RERUN
  TRUST_PACK_VALIDATION_LABEL_EXPLICIT
  TRUST_PACK_VERIFY_LABEL_EXPLICIT
  TRUST_PACK_VALIDATION_NEVER_IMPLIES_VERIFIED
  TRUST_PACK_UNAVAILABLE_FAILS_CLOSED
  TRUST_PACK_RUN_IDENTITY_VISIBLE
  TRUST_PACK_KPIS_MATCH_API_AUTHORITY
  TRUST_PACK_NO_NEW_FINANCIAL_MATH
  TRUST_PACK_BROWSER_ACCEPTANCE

Verticals: Solar, Wind, Data Center, EV Charging (where applicable).
The Trust Pack composes existing canonical read services only — no new
calculations, no new truth authorities, no engine execution at render time.
"""
from __future__ import annotations

from tests.run_clone_csrf import post_valid_csrf

import math
import re
from unittest import mock

import pytest


@pytest.fixture
def seeded_db(tmp_path, monkeypatch):
    from app.persistence import db

    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "trust-pack-ux.db"))
    db.init_db()
    yield


VERTICALS = [
    ("generic_solar_reference", 64.0),
    ("generic_wind_reference", 48.0),
    ("generic_data_center_reference", 20.0),
    ("generic_ev_charging_reference", 30.0),
]


def _make_client_and_copy(user_id: str, template_source: str, capacity_mw: float):
    from app.auth import COOKIE_NAME, create_session_token
    from app.services.reference_seed_service import create_reference_seeded_project
    from fastapi.testclient import TestClient
    import main_web

    record = create_reference_seeded_project(
        user_id=user_id,
        template_source=template_source,
        requested_name=f"Trust Pack {template_source}",
        capacity_mw=capacity_mw,
    )
    cookies = {COOKIE_NAME: create_session_token(user_id=user_id, username="admin")}
    client = TestClient(main_web.app, raise_server_exceptions=True)
    return client, cookies, record


def _run_via_workbook(client, cookies, record) -> None:
    boot = client.get(
        f"/v2/model-react/workspace?project={record.project_code}",
        cookies=cookies,
        headers={"X-Finco-React-Request": "1"},
    )
    assert boot.status_code == 200, boot.text[:300]
    wb = boot.json()["workbook"]
    run = post_valid_csrf(
        client,
        "/v2/workbook/run",
        data={
            "project": record.project_code,
            "content_hash": wb["composite_hash"],
            "workbook_version": wb["version"],
        },
        cookies=cookies,
        headers={"Accept": "application/json", "X-Finco-React-Request": "1"},
    )
    assert run.status_code == 200, run.text[:300]
    after = client.get(
        f"/v2/model-react/workspace?project={record.project_code}",
        cookies=cookies,
        headers={"X-Finco-React-Request": "1"},
    )
    assert after.status_code == 200
    assert after.json()["freshness"]["state"] == "CURRENT"


def _get_react_trust(client, cookies, project_code: str) -> dict:
    resp = client.get(
        f"/v2/model-react/trust?project={project_code}",
        cookies=cookies,
        headers={"X-Finco-React-Request": "1"},
    )
    assert resp.status_code == 200, resp.text[:300]
    data = resp.json()
    assert data["ok"] is True
    return data


# ─────────────────────────────────────────────────────────────────────────────
# Canonical Last Run only + run identity + KPI authority (per vertical)
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("template_source,capacity_mw", VERTICALS)
class TestTrustPackCanonicalLastRun:
    def test_trust_pack_canonical_last_run_only(
        self, seeded_db, template_source, capacity_mw
    ):
        user_id = f"tp-user-{template_source}"
        client, cookies, record = _make_client_and_copy(user_id, template_source, capacity_mw)
        _run_via_workbook(client, cookies, record)

        from app.persistence.workspace_repository import get_workspace_state
        from app.ui.trust_pack import build_trust_pack

        ws = get_workspace_state(user_id, record.project_id)

        trust = _get_react_trust(client, cookies, record.project_code)
        assert trust["run_state"] == "CURRENT"
        assert trust["identity"]["snapshot_id"] == (ws.last_runtime_snapshot_id or "")
        tp = build_trust_pack(
            user_id, record.project_id,
            project_code=record.project_code, any_run_committed=True,
        )
        assert tp["last_run"]["snapshot_id"] == (ws.last_runtime_snapshot_id or "")
        assert tp["last_run"]["composite_hash_short"]
        assert tp["kpis"]["state"] == "AVAILABLE"

    def test_trust_pack_run_identity_visible(
        self, seeded_db, template_source, capacity_mw
    ):
        user_id = f"tp-id-{template_source}"
        client, cookies, record = _make_client_and_copy(user_id, template_source, capacity_mw)
        _run_via_workbook(client, cookies, record)

        from app.persistence.workspace_repository import get_workspace_state
        from app.ui.trust_pack import build_trust_pack

        ws = get_workspace_state(user_id, record.project_id)
        trust = _get_react_trust(client, cookies, record.project_code)

        full_hash = ws.last_runtime_composite_hash or ""
        short = full_hash[:12]
        assert short and short in (trust["identity"].get("composite_hash") or "")
        tp = build_trust_pack(
            user_id, record.project_id,
            project_code=record.project_code, any_run_committed=True,
        )
        assert tp["last_run"]["composite_hash_short"].startswith(short)
        assert tp["last_run"]["run_at_display"]

    def test_trust_pack_kpis_match_api_authority(
        self, seeded_db, template_source, capacity_mw
    ):
        user_id = f"tp-kpi-{template_source}"
        client, cookies, record = _make_client_and_copy(user_id, template_source, capacity_mw)
        _run_via_workbook(client, cookies, record)

        from fastapi.testclient import TestClient
        import main_api

        api = TestClient(main_api.app, raise_server_exceptions=True)
        resp = api.get(f"/api/v1.1/projects/{record.project_id}/kpis", cookies=cookies)
        assert resp.status_code == 200, resp.text[:300]
        api_kpis = resp.json()["data"]

        from app.ui.trust_pack import build_trust_pack

        tp = build_trust_pack(
            user_id, record.project_id,
            project_code=record.project_code, any_run_committed=True,
        )
        for row in tp["kpis"]["rows"]:
            api_field = api_kpis[row["key"]]
            assert row["state"] == api_field["state"], row["key"]
            assert row["value"] == api_field["value"], row["key"]
            assert row["unit"] == api_field["unit"], row["key"]
        # Formatting is presentation-only: the authority value is unchanged.
        irr_row = next(r for r in tp["kpis"]["rows"] if r["key"] == "project_irr")
        if irr_row["state"] == "AVAILABLE":
            assert math.isclose(
                float(irr_row["value"]), float(api_kpis["project_irr"]["value"])
            )
            assert irr_row["display"].endswith("%")


# ─────────────────────────────────────────────────────────────────────────────
# Dirty working copy disclosure
# ─────────────────────────────────────────────────────────────────────────────

class TestTrustPackDirtyWorkingCopy:
    def test_trust_pack_dirty_wc_disclosed(self, seeded_db):
        user_id = "tp-dirty-user"
        client, cookies, record = _make_client_and_copy(
            user_id, "generic_data_center_reference", 20.0
        )
        _run_via_workbook(client, cookies, record)

        from app.persistence.workspace_repository import (
            get_workspace_state,
            save_workspace_state,
        )

        # A real WC edit writes through the draft snapshot; mutating the draft
        # (as any post-run input edit does) is the disclosed condition.
        ws = get_workspace_state(user_id, record.project_id)
        draft = dict(ws.draft_snapshot)
        draft["dc_pue"] = "1.45"
        save_workspace_state(
            user_id=ws.user_id,
            project_id=ws.project_id,
            project_code=ws.project_code,
            draft_snapshot=draft,
            saved_snapshot=ws.saved_snapshot,
            dirty=True,
            governance_state=ws.governance_state,
            replay_metadata=ws.replay_metadata,
        )

        from app.ui.trust_pack import build_trust_pack

        trust = _get_react_trust(client, cookies, record.project_code)
        assert trust["run_state"] == "STALE"
        assert trust["identity"]["snapshot_id"] == ws.last_runtime_snapshot_id
        tp = build_trust_pack(
            user_id, record.project_id,
            project_code=record.project_code, any_run_committed=True,
        )
        assert tp["export"]["working_copy_changed_since_run"] is True
        assert tp["last_run"]["snapshot_id"] == ws.last_runtime_snapshot_id


# ─────────────────────────────────────────────────────────────────────────────
# No export / no rerun from Trust Pack rendering
# ─────────────────────────────────────────────────────────────────────────────

class TestTrustPackNoSideEffects:
    def test_trust_pack_no_export_rerun(self, seeded_db):
        from app.api import project_runner
        from app.persistence.db import get_cursor
        from app.persistence.workspace_repository import get_workspace_state
        from app.ui.trust_pack import build_trust_pack

        client, cookies, record = _make_client_and_copy(
            "tp-side-user", "generic_solar_reference", 64.0
        )
        _run_via_workbook(client, cookies, record)

        ws_before = get_workspace_state("tp-side-user", record.project_id)
        snapshot_before = ws_before.last_runtime_snapshot_id

        calls: list[tuple] = []

        def _no_run(*args, **kwargs):  # the engine must never be invoked
            calls.append((args, kwargs))
            raise AssertionError("Trust Pack rendering must not run the model")

        with mock.patch.object(project_runner, "run_project", side_effect=_no_run):
            trust = _get_react_trust(client, cookies, record.project_code)
            tp = build_trust_pack(
                "tp-side-user", record.project_id,
                project_code=record.project_code, any_run_committed=True,
            )
        assert calls == []
        assert trust["run_state"] == "CURRENT"
        assert tp["kpis"]["state"] == "AVAILABLE"

        ws_after = get_workspace_state("tp-side-user", record.project_id)
        assert ws_after.last_runtime_snapshot_id == snapshot_before

        with get_cursor() as cur:
            cur.execute(
                "SELECT COUNT(*) n FROM scenario_exports WHERE project_id=?",
                (record.project_id,),
            )
            assert cur.fetchone()["n"] == 0


# ─────────────────────────────────────────────────────────────────────────────
# Labels, separation, fail-closed
# ─────────────────────────────────────────────────────────────────────────────

class TestTrustPackLabelsAndFailClosed:
    def test_trust_pack_validation_label_explicit(self, seeded_db):
        from app.ui.trust_pack import build_trust_pack

        client, cookies, record = _make_client_and_copy(
            "tp-label-user", "generic_solar_reference", 64.0
        )
        trust = _get_react_trust(client, cookies, record.project_code)
        assert trust["validation"]["authority"] == "REFERENCE_REGRESSION_CHECK"
        tp = build_trust_pack(
            "tp-label-user", record.project_id,
            project_code=record.project_code, any_run_committed=False,
        )
        assert "REFERENCE REGRESSION CHECK" in tp["validation"]["authority"]

    def test_trust_pack_verify_label_explicit(self, seeded_db):
        from app.ui.trust_pack import build_trust_pack

        client, cookies, record = _make_client_and_copy(
            "tp-verify-user", "generic_solar_reference", 64.0
        )
        tp = build_trust_pack(
            "tp-verify-user", record.project_id,
            project_code=record.project_code, any_run_committed=False,
        )
        assert "FINCO_VERIFY" in tp["verify"]["authority"]

    def test_trust_pack_validation_never_implies_verified(self, seeded_db):
        client, cookies, record = _make_client_and_copy(
            "tp-sep-user", "generic_solar_reference", 64.0
        )
        _run_via_workbook(client, cookies, record)
        trust = _get_react_trust(client, cookies, record.project_code)
        assert trust["validation"]["state"] == "DEFERRED"
        assert trust["validation"]["not_verify"] is True
        # Validation is an explicit on-demand load (render never executes the model)
        frag = client.get(
            f"/v2/model-react/trust/validation?project={record.project_code}",
            cookies=cookies,
            headers={"X-Finco-React-Request": "1"},
        )
        assert frag.status_code == 200, frag.text[:300]
        assert "REFERENCE REGRESSION CHECK" in frag.json()["validation"]["authority"]

    def test_trust_pack_unavailable_fails_closed(self, seeded_db):
        from app.ui.trust_pack import build_trust_pack

        client, cookies, record = _make_client_and_copy(
            "tp-closed-user", "generic_solar_reference", 64.0
        )
        trust = _get_react_trust(client, cookies, record.project_code)
        assert trust["run_state"] == "NOT_RUN"
        assert trust["validation"]["state"] == "UNAVAILABLE"
        assert trust["certificate"]["state"] == "UNAVAILABLE"
        tp = build_trust_pack(
            "tp-closed-user", record.project_id,
            project_code=record.project_code, any_run_committed=False,
        )
        assert tp["overall_state"] == "UNAVAILABLE"
        assert tp["kpis"]["state"] == "UNAVAILABLE"
        assert tp["verify"]["state"] == "UNAVAILABLE"

    def test_trust_pack_builder_fails_closed_without_workspace(self, seeded_db):
        from app.ui.trust_pack import build_trust_pack

        tp = build_trust_pack(
            "tp-ghost-user", "nonexistent-project-id",
            project_code="nonexistent", any_run_committed=False,
        )
        assert tp["overall_state"] == "UNAVAILABLE"
        assert tp["kpis"]["state"] == "UNAVAILABLE"
        assert tp["last_run"]["state"] == "UNAVAILABLE"
        assert tp["verify"]["state"] == "UNAVAILABLE"
        assert tp["export"]["state"] == "UNAVAILABLE"

    def test_trust_pack_global_failure_no_actionable_deferred_state(self, seeded_db):
        """TRUST_PACK_GLOBAL_FAILURE_NO_ACTIONABLE_DEFERRED_STATE

        When overall state is UNAVAILABLE (no committed Last Run),
        MODEL VALIDATION must not remain DEFERRED with an actionable
        load URL — it must be UNAVAILABLE too.
        """
        from app.ui.trust_pack import build_trust_pack

        tp = build_trust_pack(
            "tp-ghost3-user", "nonexistent-project-id",
            project_code="nonexistent", any_run_committed=False,
        )
        assert tp["overall_state"] == "UNAVAILABLE"
        # Validation must not be DEFERRED when no Last Run exists.
        assert tp["validation"]["state"] != "DEFERRED", (
            "MODEL VALIDATION must not be DEFERRED with an actionable load URL "
            "when the overall Trust Pack state is UNAVAILABLE"
        )
        assert tp["validation"]["state"] == "UNAVAILABLE"
        # No actionable load URL should be present.
        assert tp["validation"].get("load_url") is None


# ─────────────────────────────────────────────────────────────────────────────
# Verify presentation — canonical va-status--* CSS classes
# ─────────────────────────────────────────────────────────────────────────────

class TestTrustPackVerifyPresentation:
    def test_trust_pack_verified_style_only_for_verified(self, seeded_db):
        """TRUST_PACK_VERIFIED_STYLE_ONLY_FOR_VERIFIED

        When FINCO VERIFY status is VERIFIED, build_trust_pack returns
        css_class 'va-status--verified'.  No other status may produce
        that class.
        """
        from app.api.v1_1 import institutional as _v11
        from app.ui.trust_pack import build_trust_pack
        from app.verified.contracts import VerifiedAssetStatus

        client, cookies, record = _make_client_and_copy(
            "tp-vss-user", "generic_solar_reference", 64.0
        )
        _run_via_workbook(client, cookies, record)

        with mock.patch.object(
            _v11,
            "get_verify_state",
            return_value=(
                "AVAILABLE",
                {"status": VerifiedAssetStatus.VERIFIED, "asset_id": "test-asset"},
            ),
        ):
            tp = build_trust_pack(
                "tp-vss-user",
                record.project_id,
                project_code=record.project_code,
                any_run_committed=True,
            )

        assert tp["verify"]["state"] == "AVAILABLE"
        assert tp["verify"]["css_class"] == "va-status--verified"

    def test_trust_pack_model_only_not_green(self, seeded_db):
        """TRUST_PACK_MODEL_ONLY_NOT_GREEN

        MODEL_ONLY verify status must produce 'va-status--model-only',
        never 'va-status--verified' (green).
        """
        from app.api.v1_1 import institutional as _v11
        from app.ui.trust_pack import build_trust_pack
        from app.verified.contracts import VerifiedAssetStatus

        client, cookies, record = _make_client_and_copy(
            "tp-mon-user", "generic_solar_reference", 64.0
        )
        _run_via_workbook(client, cookies, record)

        with mock.patch.object(
            _v11,
            "get_verify_state",
            return_value=(
                "AVAILABLE",
                {"status": VerifiedAssetStatus.MODEL_ONLY, "asset_id": None},
            ),
        ):
            tp = build_trust_pack(
                "tp-mon-user",
                record.project_id,
                project_code=record.project_code,
                any_run_committed=True,
            )

        assert tp["verify"]["state"] == "AVAILABLE"
        assert tp["verify"]["css_class"] == "va-status--model-only"
        assert tp["verify"]["css_class"] != "va-status--verified"

    def test_trust_pack_unavailable_not_green(self, seeded_db):
        """TRUST_PACK_UNAVAILABLE_NOT_GREEN

        When verify state is UNAVAILABLE, the rendered page must not
        show the green va-status--verified chip.
        """
        from app.ui.trust_pack import build_trust_pack

        client, cookies, record = _make_client_and_copy(
            "tp-ung-user", "generic_solar_reference", 64.0
        )
        # No run committed → verify is UNAVAILABLE.
        trust = _get_react_trust(client, cookies, record.project_code)
        assert trust["run_state"] == "NOT_RUN"
        tp = build_trust_pack(
            "tp-ung-user", record.project_id,
            project_code=record.project_code, any_run_committed=False,
        )
        assert tp["verify"]["state"] == "UNAVAILABLE"
        assert tp["verify"]["css_class"] != "va-status--verified"

    def test_trust_pack_partial_not_fully_verified(self, seeded_db):
        """TRUST_PACK_PARTIAL_NOT_FULLY_VERIFIED

        VERIFIED_MARKET_PARTIAL must produce va-status--partial (amber),
        never va-status--verified (green).
        """
        from app.api.v1_1 import institutional as _v11
        from app.ui.trust_pack import build_trust_pack
        from app.verified.contracts import VerifiedAssetStatus

        client, cookies, record = _make_client_and_copy(
            "tp-partial-user", "generic_solar_reference", 64.0
        )
        _run_via_workbook(client, cookies, record)

        with mock.patch.object(
            _v11,
            "get_verify_state",
            return_value=(
                "AVAILABLE",
                {"status": VerifiedAssetStatus.VERIFIED_MARKET_PARTIAL, "asset_id": "test-asset"},
            ),
        ):
            tp = build_trust_pack(
                "tp-partial-user",
                record.project_id,
                project_code=record.project_code,
                any_run_committed=True,
            )

        assert tp["verify"]["state"] == "AVAILABLE"
        assert tp["verify"]["css_class"] == "va-status--partial"
        assert tp["verify"]["css_class"] != "va-status--verified"


# ─────────────────────────────────────────────────────────────────────────────
# Signed Run Certificate — separate authority from FINCO VERIFY (Correction A2)
# ─────────────────────────────────────────────────────────────────────────────

class TestTrustPackSignedRunCertificate:
    def test_trust_pack_certificate_separate_from_verify(self, seeded_db):
        """TRUST_PACK_CERTIFICATE_SEPARATE_FROM_VERIFY

        The certificate section and the FINCO VERIFY section are distinct keys
        in the Trust Pack dict and distinct sections in the rendered page.
        Certificate state is independent of verify state.
        """
        from app.ui.trust_pack import build_trust_pack

        client, cookies, record = _make_client_and_copy(
            "tp-cert-sep-user", "generic_solar_reference", 64.0
        )
        _run_via_workbook(client, cookies, record)

        tp = build_trust_pack(
            "tp-cert-sep-user", record.project_id,
            project_code=record.project_code, any_run_committed=True,
        )
        # Both sections exist as independent keys.
        assert "certificate" in tp
        assert "verify" in tp
        # They are structurally separate authorities.
        assert tp["certificate"]["not_verify"] is True
        assert "not_verify" not in tp["verify"]
        # Certificate is DEFERRED (not signed at render time).
        assert tp["certificate"]["state"] == "DEFERRED"
        assert tp["certificate"]["load_url"] is not None

        trust = _get_react_trust(client, cookies, record.project_code)
        assert trust["certificate"]["not_verify"] is True
        assert trust["certificate"]["state"] == "DEFERRED"

    def test_trust_pack_signing_never_implies_verified(self, seeded_db):
        """TRUST_PACK_SIGNING_NEVER_IMPLIES_VERIFIED

        Even when build_certificate_fragment succeeds (mocked to return a cert),
        the Trust Pack verify section must never show va-status--verified.
        Certificate AVAILABLE does not imply VERIFIED.
        """
        from app.api.v1_1 import institutional as _v11
        from app.ui.trust_pack import build_certificate_fragment, build_trust_pack

        client, cookies, record = _make_client_and_copy(
            "tp-cert-noverify-user", "generic_solar_reference", 64.0
        )
        _run_via_workbook(client, cookies, record)

        with mock.patch.object(
            _v11,
            "get_verify_state",
            return_value=("AVAILABLE", {"status": "MODEL_ONLY", "asset_id": None}),
        ):
            tp = build_trust_pack(
                "tp-cert-noverify-user", record.project_id,
                project_code=record.project_code, any_run_committed=True,
            )

        # Trust Pack itself never signs — certificate is DEFERRED.
        assert tp["certificate"]["state"] == "DEFERRED"
        # Verify status is MODEL_ONLY — certificate cannot promote it.
        assert tp["verify"]["css_class"] != "va-status--verified"
        assert tp["verify"]["css_class"] == "va-status--model-only"

    def test_trust_pack_certificate_reuses_signed_run_authority(self, seeded_db):
        """TRUST_PACK_CERTIFICATE_REUSES_SIGNED_RUN_AUTHORITY

        build_certificate_fragment delegates to app.services.run_certificate_service.
        The authority string confirms this, and fail-closed behaviour (no signing
        key configured) returns UNAVAILABLE with the typed reason.
        """
        from app.ui.trust_pack import build_certificate_fragment

        client, cookies, record = _make_client_and_copy(
            "tp-cert-auth-user", "generic_solar_reference", 64.0
        )
        _run_via_workbook(client, cookies, record)

        frag = build_certificate_fragment("tp-cert-auth-user", record.project_id)
        # The authority string names the canonical Signed Run Certificate service.
        assert "run_certificate_service" in frag["authority"]
        # Fail-closed: without a signing key, cert is UNAVAILABLE (not an error).
        assert frag["state"] == "UNAVAILABLE"
        assert frag["reason"] == "SIGNING_KEY_UNAVAILABLE"

    def test_trust_pack_certificate_unavailable_fails_closed(self, seeded_db):
        """TRUST_PACK_CERTIFICATE_UNAVAILABLE_FAILS_CLOSED

        When no committed run exists, the certificate section is UNAVAILABLE
        (not DEFERRED, not an error state with raw exception text).
        The rendered page shows the intentional UNAVAILABLE chip.
        """
        from app.ui.trust_pack import build_trust_pack

        client, cookies, record = _make_client_and_copy(
            "tp-cert-fc-user", "generic_solar_reference", 64.0
        )
        # No run committed.
        tp = build_trust_pack(
            "tp-cert-fc-user", record.project_id,
            project_code=record.project_code, any_run_committed=False,
        )
        assert tp["certificate"]["state"] == "UNAVAILABLE"
        assert tp["certificate"]["load_url"] is None

        trust = _get_react_trust(client, cookies, record.project_code)
        assert trust["certificate"]["state"] == "UNAVAILABLE"
        assert trust["certificate"]["load_url"] is None

    def test_trust_pack_render_does_not_sign(self, seeded_db):
        """TRUST_PACK_RENDER_DOES_NOT_SIGN

        Reading Trust evidence (page load / JSON read) must NOT call issue_run_certificate.
        Signing only happens when the user explicitly requests the certificate.
        """
        from app.ui import trust_pack as tp_module

        client, cookies, record = _make_client_and_copy(
            "tp-cert-nosign-user", "generic_solar_reference", 64.0
        )
        _run_via_workbook(client, cookies, record)

        sign_calls: list = []

        def _no_sign(*args, **kwargs):
            sign_calls.append((args, kwargs))
            raise AssertionError("issue_run_certificate must not be called at render time")

        with mock.patch.object(tp_module, "issue_run_certificate", side_effect=_no_sign):
            trust = _get_react_trust(client, cookies, record.project_code)
        assert sign_calls == [], "issue_run_certificate was called during trust read"
        assert trust["certificate"]["state"] == "DEFERRED"


# ─────────────────────────────────────────────────────────────────────────────
# No new financial math
# ─────────────────────────────────────────────────────────────────────────────

class TestTrustPackNoNewFinancialMath:
    def test_trust_pack_no_new_financial_math(self):
        import inspect

        import app.ui.trust_pack as tp_module

        source = inspect.getsource(tp_module)
        banned = (
            "numpy_financial", "irr(", "xirr(", "npv(",
            "financial_engine", "finco_core",
            "run_project", "run_clean_production", "senior_debt_model",
        )
        for token in banned:
            assert token not in source, token
        # The only value transformation is presentation formatting.
        assert "_fmt_" in source
        # All data comes from the v1.1 read services + methodology registry.
        assert "from app.api.v1_1" in source
        assert "model_methodology_registry" in source


# ─────────────────────────────────────────────────────────────────────────────
# Browser acceptance
# ─────────────────────────────────────────────────────────────────────────────

class TestTrustPackBrowserAcceptance:
    def test_trust_pack_browser_acceptance(self, seeded_db):
        pytest.importorskip("playwright")
        pytest.importorskip("uvicorn")
        from playwright.sync_api import sync_playwright

        import socket
        import threading
        import time
        import uvicorn

        import main_web

        def _free_port() -> int:
            with socket.socket() as sock:
                sock.bind(("127.0.0.1", 0))
                return sock.getsockname()[1]

        port = _free_port()
        server = uvicorn.Server(
            uvicorn.Config(main_web.app, host="127.0.0.1", port=port, log_level="error")
        )
        thread = threading.Thread(target=server.run, daemon=True)
        thread.start()
        deadline = time.time() + 300  # Opus H-1: startup seeds reference runs (~18 s each)
        while not server.started and time.time() < deadline:
            time.sleep(0.05)
        assert server.started, "Trust Pack browser fixture server did not start"
        try:
            from app.auth import COOKIE_NAME, create_session_token

            user_id = "tp-browser-user"
            client, cookies, record = _make_client_and_copy(
                user_id, "generic_data_center_reference", 20.0
            )
            _run_via_workbook(client, cookies, record)

            with sync_playwright() as pw:
                import os as _os

                _launch_kwargs: dict = {"args": ["--no-sandbox", "--disable-setuid-sandbox"]}
                exec_path = _os.getenv("FINCO_TEST_CHROMIUM_PATH") or (
                    "/opt/pw-browsers/chromium" if _os.path.exists("/opt/pw-browsers/chromium") else ""
                )
                if exec_path:
                    _launch_kwargs["executable_path"] = exec_path
                browser = pw.chromium.launch(**_launch_kwargs)
                page = browser.new_page(viewport={"width": 1280, "height": 1000})
                page.context.add_cookies([{
                    "name": COOKIE_NAME,
                    "value": create_session_token(user_id=user_id, username="admin"),
                    "domain": "127.0.0.1",
                    "path": "/",
                }])
                page.goto(
                    f"http://127.0.0.1:{port}/v2/model-react/{record.project_code}#trust",
                    wait_until="load",
                )
                section = page.locator('section[aria-label="Trust and integrity evidence"]')
                section.wait_for(state="visible", timeout=20000)
                section.locator('[data-trust-panel="validation"]').wait_for(state="visible")
                section.locator('[data-trust-panel="certificate"]').wait_for(state="visible")

                body = section.inner_text()
                assert "Reference regression evidence" in body
                assert "Run certificate" in body
                assert "FINCO Verify" in body
                assert "none of these sections imply FINCO Verify" in body

                overflow = page.evaluate(
                    "document.documentElement.scrollWidth - document.documentElement.clientWidth"
                )
                assert overflow <= 1, f"horizontal overflow {overflow}px — desktop"

                # Narrow/mobile viewport check.
                page.set_viewport_size({"width": 390, "height": 844})
                overflow_narrow = page.evaluate(
                    "document.documentElement.scrollWidth - document.documentElement.clientWidth"
                )
                assert overflow_narrow <= 1, f"horizontal overflow {overflow_narrow}px — narrow"

                browser.close()
        finally:
            server.should_exit = True
            thread.join(10)
