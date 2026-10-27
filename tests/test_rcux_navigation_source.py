"""RC-UX Addendum A — React-only navigation: classifier negative controls and source inspection (no browser needed).

The browser walk (``tests/model_react_rcux_navigation_acceptance.py``) proves what is RENDERED; this proves the rule itself rejects what it must
(explicit staging URLs AND same-host classic routes) and that no navigation sink in the React sources points at a classic route.
"""
import re
from pathlib import Path

import pytest

from tests.model_react_rcux_navigation_acceptance import DOWNLOAD_PATHS, REACT_PREFIX, TARGETS_JS, violation

ROOT = Path(__file__).resolve().parents[1]
PAGE = "https://app.example.test/v2/model-react/PRJ-1#trust"


@pytest.mark.parametrize("target", [
    "https://staging.finco.one/v2/workbook?project=P", "//staging.finco.one/library", "/v2/workbook/trust/certificate?project=P",
    "/v2/workbook/trust/validation?project=P", "/v2/workbook?project=P", "/v2/workbook/run-history/statements?project=P&history_id=h",
    "/v2/workbook/run-history/detail?project=P&history_id=h", "/library", "/library/clone/abc", "/projects/new", "/projects", "/login",
    "/v2/capex/spending-profiles", "/v2/import", "/credit-decision", "/verify/abc", "https://example.org/", "javascript:alert(1)",
    "data:text/html,x", "/v2/model-reactor/x", "/v2/", "/",
])
def test_the_classifier_rejects_staging_and_every_same_host_classic_route(target):
    assert violation(target, page_url=PAGE), target


@pytest.mark.parametrize("target", [
    "", "#inputs", "#", "/v2/model-react/", "/v2/model-react", "/v2/model-react/PRJ-1", "/v2/model-react/PRJ-1?analysis=runs#analysis",
    "https://app.example.test/v2/model-react/PRJ-1#results", "PRJ-2", "mailto:support@example.test",
    "/v2/workbook/export?project=P", "/v2/workbook/run-history/export?project=P&history_id=h",
])
def test_the_classifier_accepts_react_destinations_hash_links_and_the_two_export_downloads(target):
    assert violation(target, page_url=PAGE) is None, target


def test_the_walker_collects_every_kind_of_navigation_target():
    for needle in ("a[href]", "area[href]", "form[action]", "formaction", "iframe[src]", "[data-href]", "meta[http-equiv]"):
        assert needle in TARGETS_JS


def test_only_the_two_export_endpoints_are_download_exceptions():
    assert DOWNLOAD_PATHS == ("/v2/workbook/export", "/v2/workbook/run-history/export") and REACT_PREFIX == "/v2/model-react"


FORBIDDEN_TARGET = re.compile(r"(staging\.finco|/v2/workbook(?!/(run-history/)?export)|/library|/projects\b|/login|/v2/(?!model-react)|/credit-decision|/verify/)")
SINK = re.compile(r"(href\s*=|location\.(href|assign|replace)|window\.open|\baction\s*=|formAction|\.navigate\(|<Link\b|to=)")
#: Request paths (fetch / canonical writers) are not navigation: they are the existing JSON/form writers the React app calls.
API_LINE = re.compile(r"(fetch\(|classifyFormPostOutcome|expectedPath|getJson|postForm|postJson|method:|\* |//|/\*)")


def _sources():
    for path in sorted((ROOT / "frontend/src").rglob("*.ts*")):
        rel = path.relative_to(ROOT).as_posix()
        if "/nonmodel/" in rel or "/__tests__/" in rel or rel.endswith(".d.ts"):
            continue
        yield rel, path.read_text(encoding="utf-8")


def test_no_navigation_sink_in_the_react_sources_points_at_a_classic_route_or_staging():
    hits = []
    for rel, text in _sources():
        for number, line in enumerate(text.splitlines(), 1):
            if SINK.search(line) and FORBIDDEN_TARGET.search(line) and not API_LINE.search(line.split("href", 1)[0] if "href" in line else line):
                hits.append(f"{rel}:{number}: {line.strip()[:160]}")
        assert "staging.finco" not in text, rel
    assert hits == [], hits


def test_no_react_source_builds_a_navigation_target_from_the_classic_workbook_routes():
    """Programmatic navigation (route helpers, generated URLs): the only module that names a classic path as a URL to LOAD is the download helper."""
    offenders = []
    for rel, text in _sources():
        for number, line in enumerate(text.splitlines(), 1):
            if re.search(r"(location\.(assign|replace|href)|window\.open|\.href\s*=)", line) and "/v2/workbook" in line:
                offenders.append(f"{rel}:{number}")
    assert offenders == [], offenders


def test_the_trust_view_has_no_classic_link_and_requests_evidence_only_on_a_click():
    view = (ROOT / "frontend/src/app/ux040506Views.tsx").read_text(encoding="utf-8")
    assert "load_url" in view and "href={data.validation.load_url}" not in view and "href={data.certificate.load_url}" not in view
    evidence = (ROOT / "frontend/src/app/trust/TrustEvidence.tsx").read_text(encoding="utf-8")
    assert "href=" not in evidence and "data-trust-load" in evidence and "useEffect" not in evidence       # nothing is requested while rendering
    api = (ROOT / "frontend/src/app/trust/api.ts").read_text(encoding="utf-8")
    assert "/v2/model-react/trust/" in api and "/v2/workbook" not in api


def test_evidence_links_accept_react_destinations_only():
    text = (ROOT / "frontend/src/app/insights/presentation.ts").read_text(encoding="utf-8")
    assert "startsWith('/v2/model-react/')" in text and "startsWith('/v2/')" not in text
