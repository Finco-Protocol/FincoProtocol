"""WF-10A: the trust registry is internally consistent, evidence-backed and in scope."""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from app.trust_readiness import registry as R
from app.trust_readiness.contracts import EvidenceKind, ReadinessStatus as S

ROOT = Path(__file__).resolve().parent.parent
IMPLEMENTATION = {EvidenceKind.CODE, EvidenceKind.CI}
VERIFICATION = {EvidenceKind.TEST, EvidenceKind.CI}


def _everything():
    return list(R.all_items()) + list(R.DATA_STORES) + list(R.KNOWN_GAPS)


def test_keys_are_unique_and_prefixed():
    keys = [o.key for o in _everything()] + [d.key for d in R.LEGAL_DOCUMENTS]
    assert len(keys) == len(set(keys))
    assert all("." in k for k in keys)


def test_every_citation_resolves_in_the_repository():
    problems = []
    for obj in _everything():
        for e in obj.evidence:
            f = ROOT / e.path
            if not f.is_file():
                problems.append(f"{obj.key}: missing {e.path}")
            elif e.anchor not in f.read_text(encoding="utf-8", errors="ignore"):
                problems.append(f"{obj.key}: anchor not found in {e.path}: {e.anchor!r}")
    assert not problems, "\n".join(problems)


def test_verified_means_code_and_an_automated_check():
    for obj in _everything():
        if getattr(obj, "status", None) is not S.IMPLEMENTED_VERIFIED:
            continue
        kinds = {e.kind for e in obj.evidence}
        assert kinds & IMPLEMENTATION, f"{obj.key}: no implementation evidence"
        assert kinds & VERIFICATION, f"{obj.key}: no automated verification"


def test_evidence_kinds_match_the_file_cited():
    for obj in _everything():
        for e in obj.evidence:
            if e.kind is EvidenceKind.CODE:
                assert e.path.endswith((".py", ".html", ".conf", ".yml", ".yaml", ".json")), \
                    f"{obj.key}: {e.path} is not code"
            if e.kind is EvidenceKind.TEST:
                assert e.path.startswith("tests/"), f"{obj.key}: {e.path}"


def test_all_four_statuses_are_used_and_kept_apart():
    used = {i.status for i in R.all_items()}
    assert used == set(S)


def test_every_known_gap_is_pinned_by_a_test():
    for gap in R.KNOWN_GAPS:
        tests = [e for e in gap.evidence if e.kind is EvidenceKind.TEST]
        assert tests, f"{gap.key} is not pinned by a test"


def test_every_data_store_states_its_retention_and_deletion():
    for d in R.DATA_STORES:
        assert d.retention_rule.strip() and d.deletion_path.strip(), d.key
    assert all(d.tables for d in R.DATA_STORES if d.store == "SQLite database")


def test_legal_documents_are_never_published():
    assert {d.key for d in R.LEGAL_DOCUMENTS} >= {"legal.terms", "legal.privacy", "legal.dpa"}
    assert all(d.publication_state == "NOT_PUBLISHED" for d in R.LEGAL_DOCUMENTS)
    import main_web

    paths = {getattr(r, "path", "") for r in main_web.app.routes}
    assert not paths & {"/terms", "/privacy", "/dpa", "/legal/terms", "/legal/privacy", "/legal/dpa"}
    names = {p.name.lower() for p in (ROOT / "app" / "templates").rglob("*.html")}
    assert not {n for n in names if n.startswith(("terms", "privacy", "dpa", "cookie"))}


def test_certifications_are_listed_only_as_not_claimed():
    labels = {n.label for n in R.NOT_CLAIMED}
    assert {"SOC 2", "ISO/IEC 27001", "FAST Standard", "IFC Performance Standards"} <= labels
    assert all(" not " in f" {n.statement} " or "None" in n.statement for n in R.NOT_CLAIMED)


def test_generated_documents_are_up_to_date():
    spec = importlib.util.spec_from_file_location("render_readiness_docs", ROOT / "tools" / "render_readiness_docs.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    out = ROOT / "docs" / "readiness"
    expected = mod.build()
    for name, text in expected.items():
        assert (out / name).read_text(encoding="utf-8") == text, (
            f"docs/readiness/{name} is stale: run python tools/render_readiness_docs.py")
    assert {p.name for p in out.glob("*.md")} == set(expected)


def test_all_eight_deliverables_have_a_page_and_a_document():
    from app.trust_readiness.router import PAGES

    assert {"security", "data", "retention", "support", "evidence", "access", "readiness"} <= {p.slug for p in PAGES}
    docs = sorted(p.name for p in (ROOT / "docs" / "readiness").glob("0*.md"))
    assert len(docs) == 8


def test_support_matrix_follows_the_capability_registry():
    from app.product_capability import PRODUCT_CAPABILITIES
    from app.trust_readiness import projection as P

    expected = [c.public_name for c in PRODUCT_CAPABILITIES if c.product_area == "model"]
    assert [r["name"] for r in P.support_matrix()] == expected
    live = {r["name"] for r in P.support_matrix() if r["status"] == "LIVE"}
    assert live and not live & {u["name"] for u in P.unavailable_features()}


def test_integrity_check_list_follows_the_implementation():
    from app.run_integrity.checks import CHECKS
    from app.trust_readiness import projection as P

    assert len(P.integrity_checks()) == len(CHECKS) >= 9


ALLOWED_PREFIXES = (
    "app/trust_readiness/", "app/templates/trust/", "static/trust_readiness.css",
    "docs/readiness/", "tools/render_readiness_docs.py", "tests/test_trust_readiness_",
)
FORBIDDEN_PREFIXES = (
    "financial_engine/", "finco_core/", "finco_radar/", "app/auth.py", "app/persistence/",
    "app/workbook/", "app/demo_cleanup.py", "app/radar", "app/v2/",
)


def test_scope_guard_this_work_touches_no_engine_input_writer_or_radar_code():
    try:
        from finance_integrity_governance import changed_paths_vs_main

        changed = changed_paths_vs_main()
    except Exception as exc:  # no git history or no origin/main in this checkout
        pytest.skip(f"cannot compute the diff against main: {exc}")
    if not any(p.startswith("app/trust_readiness/") for p in changed):
        pytest.skip("trust pack not part of this diff")
    bad = [p for p in changed if p.startswith(FORBIDDEN_PREFIXES)]
    assert not bad, f"out-of-scope files changed: {bad}"
    stray = [p for p in changed if p != "main_web.py" and not p.startswith(ALLOWED_PREFIXES)]
    assert not stray, f"files outside the trust pack changed: {stray}"
