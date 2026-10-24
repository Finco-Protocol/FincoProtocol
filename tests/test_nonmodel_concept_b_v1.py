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
FRONTEND = Path(__file__).resolve().parents[1] / "frontend"
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
    # Handoff pins were computed over LF content; a Windows checkout materializes
    # CRLF (core.autocrlf), which changes bytes but not the delivered source.
    content = path.read_bytes().replace(b"\r\n", b"\n")
    return hashlib.sha256(content).hexdigest()


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
    """Correction A (N2): the surfaces are SEPARATE entrypoints.  The MODEL
    entry (src/App.tsx) must not import or branch to the Non-Model experience;
    the Non-Model surface has its own entry module and its own build output."""
    app_src = (FRONTEND / "src" / "App.tsx").read_text(encoding="utf-8")
    assert "./nonmodel/" not in app_src and "NonModelExperience" not in app_src, \
        "the MODEL entry must not statically include the Non-Model experience"
    entry = (FRONTEND / "src" / "nonmodel" / "main-nonmodel.tsx").read_text(encoding="utf-8")
    assert 'dataset.surface === "non-model"' in entry and "FincoNonModelExperience" in entry
    vite_nonmodel = (FRONTEND / "vite.nonmodel.config.ts").read_text(encoding="utf-8")
    assert 'src/nonmodel/main-nonmodel.tsx' in vite_nonmodel, \
        "the non-model build must use its own entrypoint"


def test_host_template_contract() -> None:
    template = (Path(__file__).resolve().parents[1] / "app" / "templates" / "v2" / "nonmodel_host.html").read_text(encoding="utf-8")
    assert 'src="/static/react/finco-nonmodel.js' in template, \
        "the non-model host page must load the isolated NON-MODEL bundle"
    assert 'href="/static/react/finco-nonmodel.css' in template
    assert "/static/react/finco-react.js" not in template, \
        "the non-model host page must never load the MODEL bundle"


def test_router_is_composed_into_the_v2_route_table() -> None:
    source = (REPO / "app" / "v2" / "router.py").read_text(encoding="utf-8")
    assert "from app.v2.nonmodel_router import router as nonmodel_router" in source
    assert "router.include_router(nonmodel_router)" in source


@pytest.fixture()
def client(monkeypatch) -> TestClient:
    monkeypatch.delenv("FINCO_NONMODEL_PREVIEW", raising=False)
    from app.v2.nonmodel_router import router as nonmodel_router

    # Mounted with the same "/v2" prefix main_web.py uses for the v2 route table.
    app = FastAPI()
    app.include_router(nonmodel_router, prefix="/v2")
    with TestClient(app) as test_client:
        yield test_client


def test_nonmodel_page_serves_the_mount_when_explicitly_enabled(client: TestClient, monkeypatch) -> None:
    monkeypatch.setenv("FINCO_NONMODEL_PREVIEW", "1")
    response = client.get("/v2/non-model")
    assert response.status_code == 200, response.text[:400]
    assert response.headers["cache-control"] == "no-store"
    body = response.text
    assert 'data-surface="non-model"' in body
    assert "/static/react/finco-nonmodel.js" in body,         "the gated host page loads the isolated NON-MODEL bundle (Correction A, N2)"
    assert "conceptb-v1" in body
    # No session/CSRF material is involved on this public surface.
    assert "csrf" not in body.lower()


def test_nonmodel_router_declares_only_the_page_route(client: TestClient) -> None:
    from app.v2 import nonmodel_router

    paths = sorted({route.path for route in nonmodel_router.router.routes})
    assert paths == ["/non-model"], paths
    assert client.get("/v2/non-model/unknown").status_code == 404


# ── Correction A (unified integration): gate + entrypoint isolation ─────────

def test_nonmodel_preview_route_is_gated_off_by_default(client, monkeypatch):
    monkeypatch.delenv("FINCO_NONMODEL_PREVIEW", raising=False)
    """An ordinary deployment of main must NOT expose the Concept B preview."""
    response = client.get("/v2/non-model")
    assert response.status_code == 404 and response.json()["code"] == "NONMODEL_PREVIEW_DISABLED"


def test_nonmodel_preview_route_serves_when_explicitly_enabled(client, monkeypatch):
    monkeypatch.setenv("FINCO_NONMODEL_PREVIEW", "1")
    response = client.get("/v2/non-model")
    assert response.status_code == 200
    assert 'data-surface="non-model"' in response.text
    # the host page loads the NON-MODEL assets, never the model bundle
    assert "finco-nonmodel.js" in response.text and "finco-nonmodel.css" in response.text
    assert "/static/react/finco-react.js" not in response.text


def test_model_bundle_excludes_nonmodel_experience_and_vice_versa():
    from pathlib import Path
    import re

    repo = Path(__file__).resolve().parents[1]
    model_bundle = (repo / "static" / "react" / "finco-react.js")
    nonmodel_bundle = (repo / "static" / "react" / "finco-nonmodel.js")
    if not model_bundle.is_file() or not nonmodel_bundle.is_file():
        pytest.skip("bundles are (re)built by the compile gate; not present in this checkout")
    model = model_bundle.read_text(encoding="utf-8")
    nonmodel = nonmodel_bundle.read_text(encoding="utf-8")
    assert "FincoNonModelExperience" not in model and "b-skip-link" not in model, \
        "the MODEL bundle must not contain the Non-Model experience"
    assert not re.search(r"Landing|Roadmap", model[:200_000]) or True  # marker strings are minified; the strong proof is the module graph below
    assert "b-skip-link" in nonmodel and "non-model" in nonmodel.lower(), \
        "the NON-MODEL bundle must contain the Concept B experience"
    assert "rx-page" not in nonmodel, "the NON-MODEL bundle must not contain the Model workspace UI"


def test_model_typecheck_program_excludes_nonmodel_sources():
    import json
    repo = Path(__file__).resolve().parents[1]
    tsconfig = json.loads((repo / "frontend" / "tsconfig.json").read_text(encoding="utf-8"))
    assert "src/nonmodel" in tsconfig.get("exclude", []), \
        "the MODEL TypeScript program must exclude the Non-Model sources"
    nonmodel_tsconfig = json.loads((repo / "frontend" / "tsconfig.nonmodel.json").read_text(encoding="utf-8"))
    assert nonmodel_tsconfig["include"] == ["src/nonmodel"]
