"""WF-10A: no unsupported security claims and no confidential data on the trust surfaces."""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.trust_readiness import claims
from app.trust_readiness.router import PAGES

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="module")
def client():
    import main_web

    return TestClient(main_web.app)


def _trust_files() -> list[Path]:
    files = sorted((ROOT / "app" / "templates" / "trust").glob("*.html"))
    files += sorted((ROOT / "docs" / "readiness").glob("*.md"))
    files += [ROOT / "static" / "trust_readiness.css"]
    assert files
    return files


def _rendered(client) -> dict[str, str]:
    out = {p.path: client.get(p.path).text for p in PAGES}
    out["/trust/registry.json"] = client.get("/trust/registry.json").text
    return out


# ── The scanner itself ──────────────────────────────────────────────────────

@pytest.mark.parametrize("text", [
    "FINCO is SOC 2 compliant.",
    "We hold ISO 27001 certification.",
    "Built to the FAST Standard.",
    "IFC aligned and lender-approved.",
    "An institutional-grade platform.",
    "Fully audited and unhackable.",
    "Passed a penetration test.",
    "GDPR ready.",
])
def test_scanner_rejects_unsupported_claims(text):
    assert claims.scan_text(text), text


@pytest.mark.parametrize("text", [
    "FINCO does not claim SOC 2 attestation.",
    "No ISO 27001 certification is held.",
    "Compliance with FAST requires a review that has not been performed.",
    "There is no independent penetration test.",
    "A signature is not an audit opinion.",
])
def test_scanner_accepts_negated_statements(text):
    assert claims.scan_text(text) == [], text


def test_scanner_ignores_markup():
    assert claims.scan_text('<a href="/x" title="SOC 2">Security</a> overview') == []


# ── Unsupported claims ──────────────────────────────────────────────────────

def test_trust_surfaces_make_no_unsupported_claims(client):
    problems = []
    for f in _trust_files():
        problems += [f"{f.name}: [{v.label}] {v.sentence}" for v in claims.scan_text(f.read_text(encoding="utf-8"), f.name)]
    for path, body in _rendered(client).items():
        problems += [f"{path}: [{v.label}] {v.sentence}" for v in claims.scan_text(body, path)]
    assert not problems, "\n".join(problems)


def test_not_claimed_list_is_rendered_on_the_overview(client):
    body = client.get("/trust").text
    for label in ("SOC 2", "ISO/IEC 27001", "FAST Standard", "IFC Performance Standards"):
        assert label in body
    assert re.search(r"does not claim SOC 2", body)


def test_known_pre_existing_claims_are_exactly_the_documented_ones():
    """Repository-wide, the only unsupported-claim phrase is the one recorded as a known gap."""
    found = set()
    paths = [ROOT / "README.md", ROOT / "SECURITY.md"]
    paths += (ROOT / "docs").rglob("*.md")
    paths += (ROOT / "app" / "templates").rglob("*.html")
    for f in paths:
        rel = f.relative_to(ROOT).as_posix()
        if rel.startswith(("docs/readiness/", "app/templates/trust/")) or not f.is_file():
            continue
        for v in claims.scan_text(f.read_text(encoding="utf-8", errors="ignore"), rel):
            if v.label in claims.REPO_WIDE_LABELS:
                found.add((rel, v.label))
    assert found == set(claims.PRE_EXISTING_BASELINE), (
        f"new unsupported claim(s): {sorted(found - claims.PRE_EXISTING_BASELINE)}; "
        f"fixed (update the baseline and the gap record): {sorted(claims.PRE_EXISTING_BASELINE - found)}")


# ── Confidential data ───────────────────────────────────────────────────────

_SECRET_SHAPES = {
    "bcrypt hash": re.compile(r"\$2[aby]\$\d{2}\$[./A-Za-z0-9]{20,}"),
    "private key": re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    "cloud or API key": re.compile(r"\b(?:AKIA[0-9A-Z]{16}|ghp_[A-Za-z0-9]{20,}|sk-[A-Za-z0-9]{20,}|xox[bp]-[A-Za-z0-9-]{10,})"),
    "email address": re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b"),
    "IPv4 address": re.compile(r"\b(?!127\.|0\.)(?:\d{1,3}\.){3}\d{1,3}\b"),
    "host path": re.compile(r"(?:/home/|/root/|/Users/|[A-Z]:\\\\Users)"),
    "signed session token": re.compile(r"\b[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{6,}\.[A-Za-z0-9_-]{20,}\b"),
    "long hex secret": re.compile(r"\b[0-9a-f]{40,}\b"),
}


def test_no_confidential_data_in_published_examples(client):
    from app import auth

    literals = {"the default operator password": auth._DEFAULT_ADMIN_PASSWORD}
    for name in ("SECRET_KEY", "CSRF_SECRET"):
        value = getattr(auth, name, None)
        if value:
            literals[name] = value
    texts = {f.name: f.read_text(encoding="utf-8") for f in _trust_files()}
    texts.update(_rendered(client))

    leaks = []
    for source, text in texts.items():
        for label, secret in literals.items():
            if secret and secret in text:
                leaks.append(f"{source}: contains {label}")  # never print the value itself
        for label, rx in _SECRET_SHAPES.items():
            if rx.search(text):
                leaks.append(f"{source}: contains a {label}")
    assert not leaks, "\n".join(leaks)


def test_registry_json_is_documentation_only(client):
    data = json.loads(client.get("/trust/registry.json").text)
    assert set(data) == {"reviewed_on", "scope", "statuses", "controls", "release_checklist",
                         "data_stores", "known_gaps", "not_claimed", "legal_documents"}


# ── Links ───────────────────────────────────────────────────────────────────

_HREF = re.compile(r"""(?:href|src)=["']([^"']+)["']""")
_ID = re.compile(r"""\sid=["']([^"']+)["']""")


def test_no_broken_public_links(client):
    broken = []
    for path, body in _rendered(client).items():
        if path.endswith(".json"):
            continue
        ids = set(_ID.findall(body))
        for link in _HREF.findall(body):
            if re.match(r"^(?:https?:)?//", link) or link.startswith(("mailto:", "tel:", "data:")):
                broken.append(f"{path}: external link {link}")
            elif link.startswith("#"):
                if link[1:] not in ids:
                    broken.append(f"{path}: missing anchor {link}")
            elif link.startswith("/"):
                url = link.split("#", 1)[0]
                status = client.get(url, follow_redirects=False).status_code
                if status != 200:
                    broken.append(f"{path}: {link} -> {status}")
            else:
                broken.append(f"{path}: relative link {link}")
    assert not broken, "\n".join(broken)


def test_generated_documents_have_no_broken_relative_links():
    broken = []
    for f in (ROOT / "docs" / "readiness").glob("*.md"):
        for target in re.findall(r"\]\(([^)]+)\)", f.read_text(encoding="utf-8")):
            if "://" in target or target.startswith("#"):
                broken.append(f"{f.name}: {target}")
            elif not (f.parent / target.split("#")[0]).is_file():
                broken.append(f"{f.name}: {target}")
    assert not broken, "\n".join(broken)


def test_every_page_links_to_every_other_page(client):
    for p in PAGES:
        body = client.get(p.path).text
        for q in PAGES:
            assert f'href="{q.path}"' in body, f"{p.path} does not link to {q.path}"
