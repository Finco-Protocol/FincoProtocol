"""Concept B NON-MODEL integration V1 — provenance, boundary and routing guards.

The owner-approved Concept B frontend handoff
(``FINCO_CONCEPT_B_NON_MODEL_INTEGRATION.zip``, SHA-256
``549a3ac34733c09fbd3d05e80b0c5efa70f9b52aeaa0fac8eca78b6df841df63``) is
integrated into the host React application under ``frontend/src/nonmodel/``.
These tests pin the integration contract:

* provenance — the presentation sources that required no adaptation stay
  byte-identical to the handoff manifest (SHA-256 pinned);
* dependency surface — no runtime dependency is added (the handoff's
  ``lucide-react`` import is replaced by a local inline-SVG icon set whose
  rendering contract matches lucide-react 0.544.0);
* data boundary — the tree never fetches, invents or names a backend endpoint;
  all evidence stays labelled synthetic fixture data and the canonical Radar /
  Crypto / Roadmap server-rendered surfaces are untouched;
* routing — page-level routing goes through the canonical FastAPI route table
  (``GET /v2/non-model``), the mount is selected by ``data-surface``, the
  Model surface stays the default and unchanged, and the footer maps Verify /
  API / Docs / Methodology / Yield / $FINCO only to their verified canonical
  host destinations.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

REPO = Path(__file__).resolve().parent.parent
NONMODEL = REPO / "frontend" / "src" / "nonmodel"

#: Handoff manifest values (FILE_MANIFEST.txt, CODE_SOURCE entries).
HANDOFF_ZIP_SHA256 = "549a3ac34733c09fbd3d05e80b0c5efa70f9b52aeaa0fac8eca78b6df841df63"
BYTE_IDENTICAL_SOURCES = {
    "_shared/fixtures.ts": "362566c3eefaff99c62707e1d43fdf91c78e27972811ebb5aff24ad15cdcfb2a",
    "_shared/non-model-logic.ts": "aaa0e51000416cf8094afc41c1d3b47bc0a2a3238b1c9d853918b6875115e3f6",
    "concept-b.css": "65e83b6efd7d00a4274c272b5486cb945091791cb770e62326d7bc24d0ba5e47",
}

#: Canonical host destinations the footer may link to (verified on the base
#: branch: app/protocol_ui/router.py, app/protocol/router.py, finco_yield/web.py).
CANONICAL_HOST_DESTINATIONS = (
    "/verify",
    "/api",
    "/docs",
    "/model/methodology",
    "/yield",
    "/protocol/finco",
)

#: Harvest-guard markers (tests/test_model_react_source_harvest_v1.py) that must
#: never leak into the NON-MODEL tree either.
DEMO_MARKERS = (
    "demoProjectFixtures",
    "demoWorkingCopies",
    "demoSession",
    "demoAdapter",
    "TRANSFER_DEMO_STATEMENT",
    "SYNTHETIC_REFERENCE_PROJECTS",
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _nonmodel_sources() -> list[Path]:
    return [p for p in sorted(NONMODEL.rglob("*")) if p.is_file() and p.suffix in {".ts", ".tsx", ".css", ".mjs"}]


# ───────────────────────────── provenance ─────────────────────────────

def test_handoff_provenance_recorded() -> None:
    readme = (NONMODEL / "README.md").read_text(encoding="utf-8")
    assert HANDOFF_ZIP_SHA256 in readme, "handoff ZIP SHA-256 must stay recorded"


def test_unadapted_sources_are_byte_identical_to_the_handoff() -> None:
    for rel, expected in BYTE_IDENTICAL_SOURCES.items():
        assert _sha256(NONMODEL / rel) == expected, (
            f"{rel} must stay byte-identical to the handoff manifest"
        )


def test_icons_are_inlined_not_imported() -> None:
    component = (NONMODEL / "FincoNonModelExperience.tsx").read_text(encoding="utf-8")
    assert 'from "lucide-react"' not in component, (
        "the host pins the production dependency surface to react + react-dom; "
        "icons must come from the local inline-SVG set"
    )
    assert 'from "./icons"' in component
    manifest = json.loads((REPO / "frontend" / "package.json").read_text(encoding="utf-8"))
    assert manifest["dependencies"] == {"react": "18.3.1", "react-dom": "18.3.1"}, (
        "the Concept B integration must not add runtime dependencies"
    )


def test_no_harvest_marker_leaks_into_the_nonmodel_tree() -> None:
    for path in _nonmodel_sources():
        blob = path.read_bytes()
        for marker in DEMO_MARKERS:
            assert marker.encode() not in blob, f"{path.name} must not contain {marker!r}"


# ───────────────────────────── data boundary ─────────────────────────────

def test_nonmodel_tree_never_calls_a_backend() -> None:
    forbidden = ("fetch(", "XMLHttpRequest", "WebSocket", "EventSource(", "axios")
    for path in _nonmodel_sources():
        text = path.read_text(encoding="utf-8")
        for needle in forbidden:
            assert needle not in text, f"{path.name} must not contain {needle!r}"


def test_adapter_records_canonical_wiring_as_not_connected() -> None:
    adapter = (NONMODEL / "adapter.ts").read_text(encoding="utf-8")
    assert 'ACTIVE_NONMODEL_SOURCE: NonModelSourceKind = "local-fixtures"' in adapter
    assert adapter.count("NOT_CONNECTED") >= 5, "every placeholder surface must be explicit"


# ───────────────────────────── footer destinations ─────────────────────────────

def test_footer_links_only_verified_canonical_host_destinations() -> None:
    component = (NONMODEL / "FincoNonModelExperience.tsx").read_text(encoding="utf-8")
    for destination in CANONICAL_HOST_DESTINATIONS:
        assert f'href: "{destination}"' in component, f"{destination} must be mapped"
    assert "finco-visual-concept" not in component, (
        "the Replit-only concept gallery has no host route and must not be linked"
    )
    # In-surface navigation stays hash-based; host destinations must never be
    # presented as in-surface hash routes.
    for label in ("Verify", "API", "Docs", "Methodology", "Yield", "$FINCO"):
        assert f'href="#/{label.lower()}"' not in component


# ───────────────────────────── host routing ─────────────────────────────

def test_app_surface_switch_keeps_model_default() -> None:
    app_tsx = (REPO / "frontend" / "src" / "App.tsx").read_text(encoding="utf-8")
    assert 'host.dataset.surface === "non-model"' in app_tsx
    assert "return <ModelApp host={host} />" in app_tsx, "Model surface must stay the default"
    assert "export default function App" in app_tsx


def test_host_template_contract() -> None:
    template = (REPO / "app" / "templates" / "v2" / "nonmodel_host.html").read_text(encoding="utf-8")
    assert 'data-surface="non-model"' in template
    assert 'id="finco-react-root"' in template
    assert 'src="/static/react/finco-react.js' in template, "same-origin bundle only"
    assert "/static/" + "/".join([".."]) not in template
    assert "transfer" not in template.lower(), "dev-only harness must stay out of the host page"
    assert "__FINCO_TRANSFER_APP__" not in template


def test_router_is_composed_into_the_v2_route_table() -> None:
    source = (REPO / "app" / "v2" / "router.py").read_text(encoding="utf-8")
    assert "from app.v2.nonmodel_router import router as nonmodel_router" in source
    assert "router.include_router(nonmodel_router)" in source


@pytest.fixture()
def client() -> TestClient:
    from app.v2.nonmodel_router import router as nonmodel_router

    # Mounted with the same "/v2" prefix main_web.py uses for the v2 route table.
    app = FastAPI()
    app.include_router(nonmodel_router, prefix="/v2")
    with TestClient(app) as test_client:
        yield test_client


def test_nonmodel_page_is_public_and_serves_the_mount(client: TestClient) -> None:
    response = client.get("/v2/non-model")
    assert response.status_code == 200, response.text[:400]
    assert response.headers["cache-control"] == "no-store"
    body = response.text
    assert 'data-surface="non-model"' in body
    assert "/static/react/finco-react.js" in body
    assert "conceptb-v1" in body
    # No session/CSRF material is involved on this public surface.
    assert "csrf" not in body.lower()


def test_nonmodel_router_declares_only_the_page_route(client: TestClient) -> None:
    from app.v2 import nonmodel_router

    paths = sorted({route.path for route in nonmodel_router.router.routes})
    assert paths == ["/non-model"], paths
    assert client.get("/v2/non-model/unknown").status_code == 404
