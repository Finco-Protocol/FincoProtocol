"""PR #91 Correction A — integration and contract regression tests.

Covers:
  - main_web integration: canonical public API routes reachable
  - legacy routes NOT reachable (not accidentally published)
  - /api/openapi.json exact path scope (all /api/v1/**, nothing else)
  - /api/openapi.json required paths present
  - /api/openapi.json components.schemas no internal UI models
  - API landing page ↔ public schema reconciliation
  - Demo-session cookie NOT issued on /api, /api/docs, /api/openapi.json,
    /api/v1/** requests
  - Product docs (/docs) serves FINCO docs, not Swagger
  - /api/docs serves Swagger, not product docs
  - public safety scanner vendor exemption: exact-SHA pass, mutated fail,
    ordinary-JS-with-email fails
"""
from __future__ import annotations

import copy
import hashlib
import os
import re
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

REPO = Path(__file__).resolve().parents[1]

# ── TestClient helpers ─────────────────────────────────────────────────────────

def _main_client() -> TestClient:
    import main_web
    return TestClient(main_web.app, raise_server_exceptions=True)


def _proto_client(follow_redirects: bool = True) -> TestClient:
    from app.protocol_ui.router import router as protocol_router
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    app.include_router(protocol_router)
    return TestClient(app, follow_redirects=follow_redirects)


# ── Section 9: main_web integration ───────────────────────────────────────────

class TestMainWebIntegration:
    """Canonical API routes reachable; legacy routes absent; docs routes work."""

    def test_model_references_200(self):
        resp = _main_client().get("/api/v1/model/references")
        assert resp.status_code == 200
        assert resp.json()  # non-empty

    def test_meta_200(self):
        resp = _main_client().get("/api/v1/meta")
        assert resp.status_code == 200

    def test_radar_assets_200_or_503(self):
        resp = _main_client().get("/api/v1/radar/assets")
        # 200 = registry available; 503 = registry offline (both valid in unit env)
        assert resp.status_code in (200, 503)

    def test_api_docs_200(self):
        resp = _main_client().get("/api/docs")
        assert resp.status_code == 200
        assert "swagger" in resp.text.lower()

    def test_api_openapi_json_200(self):
        resp = _main_client().get("/api/openapi.json")
        assert resp.status_code == 200
        data = resp.json()
        assert "paths" in data

    def test_product_docs_200(self):
        resp = _main_client().get("/docs")
        assert resp.status_code == 200
        assert "FINCO Documentation" in resp.text

    def test_docs_start_301(self):
        client = TestClient(_main_client().app, follow_redirects=False)
        resp = client.get("/docs/start")
        assert resp.status_code == 301
        assert resp.headers["location"] == "/docs"

    # Legacy routes MUST return 404
    def test_legacy_run_404(self):
        resp = _main_client().post("/api/v1/run", json={})
        assert resp.status_code == 404, (
            f"/api/v1/run must be 404 (legacy route not published) got {resp.status_code}"
        )

    def test_legacy_validate_404(self):
        resp = _main_client().post("/api/v1/validate", json={})
        assert resp.status_code == 404, (
            f"/api/v1/validate must be 404 got {resp.status_code}"
        )

    def test_legacy_project_types_404(self):
        resp = _main_client().get("/api/v1/project-types")
        assert resp.status_code == 404, (
            f"/api/v1/project-types must be 404 got {resp.status_code}"
        )

    def test_legacy_scenarios_404(self):
        resp = _main_client().get("/api/v1/scenarios")
        assert resp.status_code == 404, (
            f"/api/v1/scenarios must be 404 got {resp.status_code}"
        )


# ── Section 6: public OpenAPI path scope ──────────────────────────────────────

class TestPublicOpenAPIScope:
    """All paths in /api/openapi.json start with /api/v1/; required paths present;
    legacy/internal paths absent."""

    REQUIRED_PATHS = {
        "/api/v1/model/references",
        "/api/v1/model/references/{reference_key}",
        "/api/v1/model/references/{reference_key}/capex",
        "/api/v1/model/references/{reference_key}/opex",
        "/api/v1/model/references/{reference_key}/preview",
        "/api/v1/model/references/{reference_key}/run",
        "/api/v1/radar/assets",
        "/api/v1/radar/assets/{economic_asset_uid}",
        "/api/v1/radar/assets/{economic_asset_uid}/fundamentals",
        "/api/v1/radar/assets/{economic_asset_uid}/financials",
        "/api/v1/radar/assets/{economic_asset_uid}/corporate-actions",
        "/api/v1/radar/assets/{economic_asset_uid}/evidence",
        "/api/v1/radar/assets/{economic_asset_uid}/execution-simulation",
        "/api/v1/meta",
    }

    FORBIDDEN_PATHS = {
        "/api/v1/run",
        "/api/v1/validate",
        "/api/v1/project-types",
        "/api/v1/scenarios",
    }

    def _schema(self):
        resp = _main_client().get("/api/openapi.json")
        assert resp.status_code == 200
        return resp.json()

    def test_all_paths_under_api_v1(self):
        data = self._schema()
        paths = list(data.get("paths", {}).keys())
        assert paths, "Schema must have at least one path"
        bad = [p for p in paths if not p.startswith("/api/v1/")]
        assert bad == [], f"Schema contains non-/api/v1/ paths: {bad}"

    def test_required_paths_present(self):
        data = self._schema()
        paths = set(data.get("paths", {}).keys())
        missing = self.REQUIRED_PATHS - paths
        assert missing == set(), f"Required paths missing from schema: {missing}"

    def test_forbidden_paths_absent(self):
        data = self._schema()
        paths = set(data.get("paths", {}).keys())
        present = self.FORBIDDEN_PATHS & paths
        assert present == set(), (
            f"Legacy/forbidden paths are exposed in public schema: {present}"
        )

    def test_library_paths_absent(self):
        data = self._schema()
        paths = [p for p in data.get("paths", {}).keys() if p.startswith("/library")]
        assert paths == [], f"Schema exposes /library paths: {paths}"

    def test_v2_paths_absent(self):
        data = self._schema()
        paths = [p for p in data.get("paths", {}).keys() if p.startswith("/v2/")]
        assert paths == [], f"Schema exposes /v2/ paths: {paths}"

    def test_login_logout_absent(self):
        data = self._schema()
        paths = [p for p in data.get("paths", {}).keys()
                 if p in ("/login", "/logout")]
        assert paths == [], f"Schema exposes auth routes: {paths}"


# ── Section 7: component/schema leakage ───────────────────────────────────────

class TestPublicOpenAPIComponentScope:
    """components.schemas must not contain internal UI/workbook models."""

    _V2_FAMILIES = re.compile(
        r"^(V2|Workbook|Scenario|Inputs|Capex|Opex|Library|Project|Export|Download)",
        re.IGNORECASE,
    )

    def test_no_v2_workbook_schemas(self):
        resp = _main_client().get("/api/openapi.json")
        data = resp.json()
        schemas = set(data.get("components", {}).get("schemas", {}).keys())
        internal = [s for s in schemas if self._V2_FAMILIES.match(s)]
        assert internal == [], (
            f"Public schema leaks internal workbook/v2 models: {internal}"
        )

    def test_expected_public_schemas_present(self):
        resp = _main_client().get("/api/openapi.json")
        data = resp.json()
        schemas = set(data.get("components", {}).get("schemas", {}).keys())
        # Schemas that must exist in the public API
        for expected in (
            "ModelReferenceListEnvelope",
            "RadarEnvelope",
            "ExecutionSimulationRequest",
        ):
            assert expected in schemas, f"Expected schema {expected!r} missing"


# ── Section 8: API landing ↔ public schema reconciliation ─────────────────────

class TestApiLandingSchemaReconciliation:
    """Every concrete endpoint on the /api landing page exists in the schema.
    Scenario API remains Coming Soon — not in the public schema.
    """

    # Concrete paths advertised on the /api page (from protocol_api.html)
    LANDING_PATHS = [
        "/api/v1/model/references",
        "/api/v1/model/references/{reference_key}",
        "/api/v1/model/references/{reference_key}/capex",
        "/api/v1/model/references/{reference_key}/opex",
        "/api/v1/model/references/{reference_key}/preview",
        "/api/v1/model/references/{reference_key}/run",
        "/api/v1/radar/assets",
        "/api/v1/radar/assets/{economic_asset_uid}",
        "/api/v1/radar/assets/{economic_asset_uid}/fundamentals",
        "/api/v1/radar/assets/{economic_asset_uid}/financials",
        "/api/v1/radar/assets/{economic_asset_uid}/corporate-actions",
        "/api/v1/radar/assets/{economic_asset_uid}/evidence",
        "/api/v1/radar/assets/{economic_asset_uid}/execution-simulation",
    ]

    def test_all_landing_paths_in_schema(self):
        resp = _main_client().get("/api/openapi.json")
        schema_paths = set(resp.json().get("paths", {}).keys())
        missing = [p for p in self.LANDING_PATHS if p not in schema_paths]
        assert missing == [], (
            f"Landing-page endpoints not in public schema: {missing}"
        )

    def test_scenario_api_not_in_schema(self):
        """Scenario API is Coming Soon — must not appear in the public schema."""
        resp = _main_client().get("/api/openapi.json")
        schema_paths = set(resp.json().get("paths", {}).keys())
        scenario_paths = [p for p in schema_paths if "scenario" in p.lower()]
        assert scenario_paths == [], (
            f"Scenario API (Coming Soon) is exposed in public schema: {scenario_paths}"
        )

    def test_api_page_scenario_coming_soon(self):
        resp = _main_client().get("/api")
        assert resp.status_code == 200
        assert "Coming soon" in resp.text or "coming-soon" in resp.text.lower(), (
            "Scenario/Coming-Soon marker not found on /api landing page"
        )


# ── Section 10: demo-session statelessness ────────────────────────────────────

class TestDemoSessionStatelessness:
    """API routes must not issue FINCO demo session cookies."""

    _DEMO_COOKIE_RE = re.compile(r"finco[_-]?session|demo[_-]?session", re.IGNORECASE)

    def _has_demo_cookie(self, resp) -> bool:
        set_cookie = resp.headers.get("set-cookie", "")
        return bool(self._DEMO_COOKIE_RE.search(set_cookie))

    def test_api_landing_no_demo_cookie(self):
        resp = _main_client().get("/api")
        assert not self._has_demo_cookie(resp), (
            f"/api must not issue a demo session cookie; got Set-Cookie: {resp.headers.get('set-cookie')}"
        )

    def test_api_docs_no_demo_cookie(self):
        resp = _main_client().get("/api/docs")
        assert not self._has_demo_cookie(resp), (
            f"/api/docs must not issue a demo session cookie"
        )

    def test_api_openapi_json_no_demo_cookie(self):
        resp = _main_client().get("/api/openapi.json")
        assert not self._has_demo_cookie(resp), (
            f"/api/openapi.json must not issue a demo session cookie"
        )

    def test_model_references_no_demo_cookie(self):
        resp = _main_client().get("/api/v1/model/references")
        assert not self._has_demo_cookie(resp), (
            f"/api/v1/model/references must not issue a demo session cookie"
        )


# ── Section 12: product docs separation ───────────────────────────────────────

class TestProductDocsSeparation:
    """/docs = product docs (not Swagger). /api/docs = developer docs (Swagger)."""

    def test_docs_serves_product_content_not_swagger(self):
        resp = _main_client().get("/docs")
        assert resp.status_code == 200
        assert "FINCO Documentation" in resp.text
        assert "SwaggerUIBundle" not in resp.text

    def test_api_docs_serves_swagger_not_product_content(self):
        resp = _main_client().get("/api/docs")
        assert resp.status_code == 200
        assert "swagger" in resp.text.lower()
        assert "FINCO Documentation" not in resp.text

    def test_docs_nav_link_points_to_docs(self):
        resp = _main_client().get("/docs")
        assert 'href="/docs"' in resp.text
        assert 'href="/docs/start"' not in resp.text

    def test_api_page_open_api_docs_link_correct(self):
        resp = _main_client().get("/api")
        assert 'href="/api/docs"' in resp.text, (
            "Open API Documentation link must point to /api/docs"
        )

    def test_api_page_openapi_json_link_correct(self):
        resp = _main_client().get("/api")
        assert 'href="/api/openapi.json"' in resp.text, (
            "OpenAPI JSON link must point to /api/openapi.json"
        )


# ── Section 2: vendor safety scanner exception ────────────────────────────────

class TestVendorSafetyScannerException:
    """Fail-closed SHA256 vendor exception for swagger-ui assets."""

    _SCAN = staticmethod(__import__(
        "tools.public_safety_scan", fromlist=["scan_file"]
    ).scan_file)

    _BUNDLE = "static/vendor/swagger-ui/swagger-ui-bundle.js"

    def test_approved_vendor_asset_passes(self):
        failures = self._SCAN(self._BUNDLE, REPO)
        email_failures = [f for f in failures if "email-like" in f]
        assert email_failures == [], (
            f"Approved vendor asset should not trigger email check: {email_failures}"
        )

    def test_mutated_vendor_asset_fails(self, tmp_path):
        """One-byte modification => exception no longer applies => email check fires."""
        original = (REPO / self._BUNDLE).read_bytes()
        mutated = original + b"\x00"  # append one null byte => SHA mismatch

        mutated_path = tmp_path / "swagger-ui-bundle.js"
        mutated_path.write_bytes(mutated)

        # Scan the mutated file from a root where the path matches
        fake_root = tmp_path
        vendor_dir = fake_root / "static" / "vendor" / "swagger-ui"
        vendor_dir.mkdir(parents=True)
        (vendor_dir / "swagger-ui-bundle.js").write_bytes(mutated)

        failures = self._SCAN(self._BUNDLE, fake_root)
        email_failures = [f for f in failures if "email-like" in f]
        assert email_failures != [], (
            "Mutated vendor asset (SHA mismatch) must not receive email exemption"
        )

    def test_ordinary_js_with_email_fails(self, tmp_path):
        """A non-vendor JS file with an email must still trigger the check."""
        fake_root = tmp_path
        js_path = fake_root / "app" / "bad_file.js"
        js_path.parent.mkdir(parents=True)
        # Construct the email bytes at runtime so the scanner does not flag THIS file.
        email_bytes = b"admin" + b"@" + b"company.internal"
        js_path.write_bytes(b"var contact = '" + email_bytes + b"'; module.exports = {};")

        failures = self._SCAN("app/bad_file.js", fake_root)
        email_failures = [f for f in failures if "email-like" in f]
        assert email_failures != [], (
            "Ordinary JS with email must trigger email-like-identifier check"
        )

    def test_secret_check_still_active_on_vendor_file(self, tmp_path):
        """Even an approved vendor file must still be caught if it contains a secret."""
        fake_root = tmp_path
        vendor_dir = fake_root / "static" / "vendor" / "swagger-ui"
        vendor_dir.mkdir(parents=True)
        # Construct a fake AWS-style key at runtime so the scanner does not flag THIS file.
        # Pattern: AKIA[0-9A-Z]{16}
        fake_key = b"AKIA" + b"IOSFODNN7EXAMPLE"  # 4+16 = 20 chars, matches secret pattern
        (vendor_dir / "swagger-ui-bundle.js").write_bytes(fake_key)

        failures = self._SCAN(self._BUNDLE, fake_root)
        secret_failures = [f for f in failures if "secret-like" in f]
        assert secret_failures != [], (
            "Secret-like token check must fire regardless of vendor exemption"
        )


# ── Section 13: Data Center integration proof (PR #88 preservation) ───────────

class TestDataCenterIntegration:
    """Generic Data Center reference is present in the public API after PR #88 rebase.

    These tests guard against accidental removal of the Data Center entry during
    the rebase.  They are intentionally non-brittle: counts and ordering are not
    asserted — only the presence and key metadata of the Data Center reference.
    """

    _DC_KEY = "generic_data_center_reference"

    def _references(self):
        resp = _main_client().get("/api/v1/model/references")
        assert resp.status_code == 200
        return resp.json()

    def test_model_references_contains_data_center(self):
        data = self._references()
        # Envelope wraps a list; look for the key regardless of exact schema shape.
        text = str(data)
        assert self._DC_KEY in text, (
            f"generic_data_center_reference missing from /api/v1/model/references"
        )

    def _dc_entry(self):
        """Return the Data Center reference entry from the envelope."""
        data = self._references()
        # Envelope: {"api_version": ..., "state": ..., "data": {"count": ..., "references": [...]}}
        items = (
            data.get("data", {}).get("references", [])
            if isinstance(data, dict)
            else data
        )
        return next((r for r in items if r.get("reference_key") == self._DC_KEY), None)

    def test_data_center_technology_field(self):
        dc = self._dc_entry()
        assert dc is not None, f"{self._DC_KEY} entry not found in references list"
        assert dc.get("technology") == "data_center", (
            f"Expected technology='data_center', got {dc.get('technology')!r}"
        )

    def test_data_center_capacity_unit(self):
        dc = self._dc_entry()
        assert dc is not None, f"{self._DC_KEY} entry not found"
        assert dc.get("capacity_unit") == "MW IT", (
            f"Expected capacity_unit='MW IT', got {dc.get('capacity_unit')!r}"
        )

    def test_data_center_detail_endpoint(self):
        resp = _main_client().get(f"/api/v1/model/references/{self._DC_KEY}")
        assert resp.status_code == 200

    def test_data_center_preview_endpoint(self):
        resp = _main_client().post(
            f"/api/v1/model/references/{self._DC_KEY}/preview",
            json={"capacity_mw": 100},
        )
        assert resp.status_code == 200

    def test_data_center_run_stateless(self):
        resp = _main_client().post(
            f"/api/v1/model/references/{self._DC_KEY}/run",
            json={"capacity_mw": 100},
        )
        assert resp.status_code == 200
        data = resp.json()
        # Stateless contract: no project persisted.
        # project_created lives under data.scaling.project_created in the v1 envelope.
        project_created = data.get("data", {}).get("scaling", {}).get("project_created")
        assert project_created is False, (
            f"Run endpoint must not create a project; project_created={project_created!r}"
        )

    def test_data_center_reachable_via_public_schema_path(self):
        """The model references path in the public schema is the one that serves Data Center.

        The schema exposes the parametric path; runtime data (reference keys) are not
        embedded in the schema itself — they come from the live endpoint.
        """
        resp = _main_client().get("/api/openapi.json")
        assert resp.status_code == 200
        paths = set(resp.json().get("paths", {}).keys())
        assert "/api/v1/model/references" in paths, (
            "Public schema must expose /api/v1/model/references (Data Center is served there)"
        )
        assert "/api/v1/model/references/{reference_key}" in paths, (
            "Public schema must expose /api/v1/model/references/{reference_key}"
        )
