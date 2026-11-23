"""WF-10A: the trust registry is internally consistent, evidence-backed and in scope."""
from __future__ import annotations

import importlib.util
import subprocess
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

# ── WF-05 (PR #245) exact-content integration exception ─────────────────────────────────────
# The Inputs grid added real CSRF validation to its validate/save routes, so the Trust CSRF
# statement had to change in the same PR. This is NOT a general mixed-scope allowance: it holds
# only while (1) the Trust-side change is EXACTLY the three approved text replacements below (and
# nothing else under the Trust scope except this guard file itself), (2) the actual token-validation
# call sites match the approved set including the grid router, and (3) every other changed path is
# one of the enumerated WF-05 files. Anything else falls back to the strict Trust-only policy.
WF05_REPLACEMENTS = {
    "app/trust_readiness/registry.py": (
        '"CSRF tokens protect the login form, the model-import steps and one crypto action. Other "',
        '"CSRF tokens protect the login form, the model-import steps, the Inputs grid validate and save routes and one crypto action. Other "',
    ),
    "docs/readiness/03_known_limitations_and_support_matrix.md": (
        "CSRF tokens protect the login form, the model-import steps and one crypto action. Other",
        "CSRF tokens protect the login form, the model-import steps, the Inputs grid validate and save routes and one crypto action. Other",
    ),
    "tests/test_trust_readiness_controls.py": (
        '''    # Login, the model-import steps and one crypto action. Nothing else validates a token.
    assert users == {"main_web.py", "app/v2/import_router.py", "app/crypto_ui.py"}''',
        '''    # Login, the model-import steps, the Inputs grid validate/save routes and one crypto action.
    # Nothing else validates a token.
    assert users == {"main_web.py", "app/v2/import_router.py", "app/v2/grid_router.py", "app/crypto_ui.py"}''',
    ),
}
WF05_GUARD_FILE = "tests/test_trust_readiness_registry.py"      # this guard (reviewed, not content-pinned)
WF05_CSRF_CALL_SITES = frozenset({
    "main_web.py", "app/v2/import_router.py", "app/v2/grid_router.py", "app/crypto_ui.py",
})
# Enumerated reviewed scope (exact files, no namespace). The four app/v2 files are the only
# entries that match FORBIDDEN_PREFIXES; engine, core, workbook, persistence and auth are never listed.
_NEVER_EXCEPTED = ("financial_engine/", "finco_core/", "finco_radar/", "app/auth.py", "app/persistence/",
                   "app/workbook/", "app/demo_cleanup.py", "app/radar")


def _in_trust_scope(path: str) -> bool:
    return path.startswith(("app/trust_readiness/", "app/templates/trust/", "docs/readiness/",
                            "tests/test_trust_readiness_", "tools/render_readiness_docs.py")) \
        or path == "static/trust_readiness.css"


def _csrf_call_sites() -> set[str]:
    import re
    sites = set()
    for path in list(ROOT.joinpath("app").rglob("*.py")) + [ROOT / "main_web.py"]:
        rel = path.relative_to(ROOT).as_posix()
        if rel.startswith("app/trust_readiness/"):
            continue
        if re.search(r"(?<!def )validate_csrf_token\(", path.read_text(encoding="utf-8", errors="ignore")):
            sites.add(rel)
    return sites


def _read_current(path):
    return (ROOT / path).read_text(encoding="utf-8")


# Approved PR #246 copy correction, after authorized normal main synchronization.
# This is an exact snapshot check, not permission to edit the protected namespaces.
CSRF_REVIEWED_HEAD = "f187c1785366d6d40d2e60c141b22ff113878d06"
CSRF_SYNC_HEAD = "2999dbccebcc00b38d98ce1e269459d5d63239bc"
CSRF_TRUST_BASE = "8af800a516d5298dc90ce0f9cd60dc9e3b198ca6"
CSRF_EXACT_BLOBS = {
    "app/trust_readiness/registry.py": "a246863f7c8b206828da06a0a9003dd96acc69c9",
    "tests/test_trust_readiness_controls.py": "37c4d84822d7743080547f1c1714c0dac4892ae5",
    "docs/readiness/03_known_limitations_and_support_matrix.md": "aed5313cc1b6cf2f9b0ba0a4ca2f57e8597d08e8",
    "docs/readiness/07_authentication_and_tenant_audit.md": "bceff61869a03e799652b576c281e0670bee1848",
    "docs/model_v2/REVENUE_V2_MULTISTREAM_AUTHORITY_REPORT.md": "0d2b33b789fbb780274d23c12885cbb9dc4850e1",
}
CSRF_GUARD_PATH = "tests/test_trust_readiness_registry.py"


def _csrf_exact_content_authorized(changed, blobs, since_sync, checkpoint_valid):
    if not checkpoint_valid or blobs != CSRF_EXACT_BLOBS:
        return False
    permitted = set(CSRF_EXACT_BLOBS) | {CSRF_GUARD_PATH}
    trust_changed = {p for p in changed if p.startswith(ALLOWED_PREFIXES)}
    expected_trust = {p for p in permitted if p.startswith(ALLOWED_PREFIXES)}
    return trust_changed == expected_trust and set(since_sync) <= permitted


def _git(*args):
    return subprocess.run(
        ["git", *args], cwd=ROOT, capture_output=True, text=True,
        encoding="utf-8", check=True,
    ).stdout.strip()


def test_csrf_exact_content_accepts_only_the_reviewed_snapshot():
    changed = list(CSRF_EXACT_BLOBS) + [CSRF_GUARD_PATH]
    assert _csrf_exact_content_authorized(changed, dict(CSRF_EXACT_BLOBS), changed, True)


@pytest.mark.parametrize("path", CSRF_EXACT_BLOBS)
def test_csrf_exact_content_rejects_any_pinned_file_modification(path):
    blobs = dict(CSRF_EXACT_BLOBS)
    blobs[path] = "0" * 40
    changed = list(CSRF_EXACT_BLOBS) + [CSRF_GUARD_PATH]
    assert not _csrf_exact_content_authorized(changed, blobs, changed, True)


@pytest.mark.parametrize("path", (
    "app/trust_readiness/projection.py", "app/trust_readiness/new_policy.py",
    "app/templates/trust/readiness.html", "static/trust_readiness.css",
    "docs/readiness/01_security_and_data_handling.md", "tools/render_readiness_docs.py",
    "tests/test_trust_readiness_claims.py", "tests/test_trust_readiness_new.py",
))
def test_csrf_exact_content_rejects_broader_trust_changes(path):
    changed = list(CSRF_EXACT_BLOBS) + [CSRF_GUARD_PATH, path]
    assert not _csrf_exact_content_authorized(changed, dict(CSRF_EXACT_BLOBS), changed, True)


@pytest.mark.parametrize("path", (
    "financial_engine/revenue_multistream.py", "financial_engine/new_solver.py",
    "finco_core/inputs/revenue_multistream.py", "domain/revenue/multistream_runtime.py",
    "app/workbook/update_service.py", "app/persistence/scenarios_repository.py",
    "app/v2/router.py", "app/auth.py", "app/services/export_service.py",
    "tests/model_v2_governance.py", "tests/test_wf07_revenue_governance.py",
))
def test_csrf_exact_content_rejects_any_new_engine_writer_or_pin_change(path):
    changed = list(CSRF_EXACT_BLOBS) + [CSRF_GUARD_PATH]
    assert not _csrf_exact_content_authorized(
        changed + [path], dict(CSRF_EXACT_BLOBS), changed + [path], True,
    )


def test_csrf_exact_content_rejects_missing_pin_or_invalid_checkpoint():
    changed = list(CSRF_EXACT_BLOBS) + [CSRF_GUARD_PATH]
    blobs = dict(CSRF_EXACT_BLOBS)
    blobs.pop("app/trust_readiness/registry.py")
    assert not _csrf_exact_content_authorized(changed, blobs, changed, True)
    assert not _csrf_exact_content_authorized(changed, dict(CSRF_EXACT_BLOBS), changed, False)


# Terminal demo disposal is a separate upstream correction, never a CI-only
# exception. Historical CSRF/WF-05 pins and the global forbidden list stay intact.
DEMO_RETENTION_BASE = "5dbfd2a2fb1c6c777b7eb26d93a7090820acce23"
DEMO_RETENTION_BLOBS = {
    "app/demo_cleanup.py": "a6a33fe83c6814e167a7cf90cb8f757c5e17741e",
    "tools/demo_reset.py": "e9f6427ed62007ce17232f530118961e730c395e",
    "docs/model_v2/RUN_HISTORY_V1_CONTRACT.md": "0f5aaccbd5629f013ad61118ad17afe13086430f",
    "tests/test_p6_correction_c.py": "9a0942517885794c93fd246097b26f388c17ef8e",
    "tests/test_p6_correction_d.py": "268ac1945e3f14d2f9c582a440d3f426ce283106",
    "tests/test_demo_history_retention.py": "c56232944fb1c06cf037252be570413c15b92e29",
    "app/trust_readiness/registry.py": "4a53ea61846feaa52fad3e3f19acad0a00d78753",
    "tests/test_trust_readiness_controls.py": "df8e246e454c04a212154d56dac5682bc3e23c68",
    "docs/readiness/03_known_limitations_and_support_matrix.md": "8aa7bfa170bff658d1bae30fd4365578be699990",
    "docs/readiness/06_retention_and_deletion.md": "d99982ed61a9b43310dcd5d7492e789464a1f28f",
}
DEMO_RETENTION_PATHS = frozenset(DEMO_RETENTION_BLOBS) | {
    CSRF_GUARD_PATH, "docs/model_v2/DEMO_HISTORY_RETENTION_CORRECTION_REPORT.md",
}


def _demo_retention_registry(original):
    replacements = (
        (
            '"Demo data: removed after the demo TTL when inactive, with one exception (known gap). "',
            '"Disposable demo sessions: removed atomically after the demo TTL when inactive, "\n'
            '        "including run-history activity, or by an explicitly authorized operator reset. "',
        ),
        (
            '"Append-only by design. NOT covered by the demo clean-up (known gap).",\n'
            '        "None in the product. A database foreign key to the project blocks project deletion while "\n'
            '        "history rows exist.", False,',
            '"Append-only while a session exists. Permanent, admin, reference and protected history "\n'
            '        "is never deleted by demo clean-up. Only complete terminal disposal of an inactive "\n'
            '        "expired demo session or an explicitly authorized operator demo reset removes its history.",\n'
            '        "No individual history deletion in the product. Verified demo-owned history and its "\n'
            '        "projects are removed in one transaction with foreign keys enabled and full rollback "\n'
            '        "on failure. Fresh history prevents TTL expiry.", False,',
        ),
        (
            '''    KnownGap(
        "gap.demo_cleanup_skips_run_history", "Expired demo data with run history is not deleted",
        GapSeverity.MEDIUM,
        "The demo clean-up deletes expired demo sessions after the TTL, but it does not delete "
        "run-history rows. Those rows reference the project through a foreign key, so deleting the "
        "project fails, the failure is only logged, and the whole demo session is kept. Demo "
        "projects that have been run therefore outlive the documented 24 hour demo TTL.",
        "Delete the user's run-history rows before their projects in the clean-up, with a "
        "regression test. This needs its own change because it alters retention behaviour.",
        (
            _code("app/demo_cleanup.py", "_TABLES_WITH_USER_ID"),
            _test(_CTRL, "test_known_gap_run_history_survives_demo_ttl_cleanup"),
        ),
    ),
''',
            "",
        ),
    )
    for old, new in replacements:
        assert original.count(old) == 1
        original = original.replace(old, new, 1)
    return original


def _demo_retention_exact_content_authorized(changed, blobs, checkpoint_valid):
    return (
        checkpoint_valid
        and set(changed) == DEMO_RETENTION_PATHS
        and blobs == DEMO_RETENTION_BLOBS
    )


@pytest.mark.parametrize("path", DEMO_RETENTION_BLOBS)
def test_demo_retention_exception_rejects_modified_content(path):
    blobs = dict(DEMO_RETENTION_BLOBS)
    blobs[path] = "0" * 40
    assert not _demo_retention_exact_content_authorized(DEMO_RETENTION_PATHS, blobs, True)


@pytest.mark.parametrize("path", sorted(DEMO_RETENTION_PATHS))
def test_demo_retention_exception_rejects_incomplete_scope(path):
    assert not _demo_retention_exact_content_authorized(
        DEMO_RETENTION_PATHS - {path}, dict(DEMO_RETENTION_BLOBS), True,
    )


# PR #267: keep publication, Correction A and inherited main integration distinct.
# The guard itself is independently reviewed, as in WF-05; payloads are blob-pinned.
F4_CSRF_MAIN = "b47aa732f567e380cbe4c8e20b6c1a7dc0db9fbf"
F4_CSRF_REVIEWED_HEAD = "a47b89e678ec05d01edcc01b703bc9fdef9887f4"
F4_CSRF_CORRECTION_A = "b87fe25a35da2272fea92093a474ad69bcbdc50b"
F4_CSRF_APPROVED_MAIN = "153d7044958bb94d01ff07325c09c6b354aa32fa"
F4_CSRF_INTEGRATION = "cc3252ae38f6e25df67f96e7d32559f9c818cfb4"
F4_CSRF_INTEGRATION_TREE = "38f87e277e16512ff10bc00844c05e5ff842bd99"
F4_CSRF_BLOBS = {
    "app/trust_readiness/registry.py": "ea39361e3f48ffe2588e5f451afd405e19a1651f",
    "docs/readiness/03_known_limitations_and_support_matrix.md": "94a4c85b45e2d35389ef612cfb8ec064dc1352ae",
    "tests/test_trust_readiness_controls.py": "2b197f7dc99c31a8055e4a617537dc56b13b3a6f",
}
F4_CSRF_PATHS = frozenset(F4_CSRF_BLOBS) | {CSRF_GUARD_PATH}
F4_CSRF_CALL_SITES = frozenset({
    "main_web.py", "app/v2/import_router.py", "app/v2/grid_router.py",
    "app/crypto_ui.py", "app/v2/router.py", "app/v2/investor_f4_router.py",
})
F4_CSRF_OLD = (
    "CSRF tokens protect the login form, the model-import steps, the Inputs grid validate and save routes, "
    "Revenue V2 contract writes and one crypto action."
)
F4_CSRF_NEW = (
    "CSRF tokens protect the login form, the model-import steps, the Inputs grid validate and save routes, "
    "Revenue V2 contract writes, Investor agreement Save and one crypto action."
)


def _f4_csrf_registry(original):
    assert original.count(F4_CSRF_OLD) == 1
    return original.replace(F4_CSRF_OLD, F4_CSRF_NEW, 1)


def _f4_csrf_exact_content_authorized(changed, blobs, since_review, checkpoint_valid, call_sites):
    return (
        checkpoint_valid
        and blobs == F4_CSRF_BLOBS
        and {p for p in changed if _in_trust_scope(p)} == F4_CSRF_PATHS
        and set(since_review) == F4_CSRF_PATHS
        and frozenset(call_sites) == F4_CSRF_CALL_SITES
    )


def _f4_integration_exact_content_authorized(parents, tree, since_integration, checkpoint_valid):
    return (
        checkpoint_valid
        and tuple(parents) == (F4_CSRF_CORRECTION_A, F4_CSRF_APPROVED_MAIN)
        and tree == F4_CSRF_INTEGRATION_TREE
        and set(since_integration) <= {CSRF_GUARD_PATH}
    )


# Revenue V2 + F4 additive CSRF inventory after the exact #267 main.
# These are supplementary, one-content-only candidate pins; the earlier
# F4_CSRF_BLOBS and all historical CSRF constants above remain UNCHANGED.
REVENUE_V2_CSRF_MAIN = "03320e2bad88c3e811942240064965f5726763f8"
REVENUE_V2_CSRF_SUCCESSOR_BLOBS = {
    "tests/test_trust_readiness_controls.py": "c96a865110c70054ff6563476c107d5539e67cdc",
    "app/v2/router.py": "a2cd37c7df8e8dac881ba44d9f28df3bf25b913e",
    "domain/revenue/multistream_runtime.py": "48465ce2a298fa1383a7eabcb921eb9fbe4610cb",
    "tests/model_v2_governance.py": "929677427c346aa08578a2b0e657fe63e25b2907",
}
REVENUE_V2_CSRF_TRUST_DELTA = frozenset({
    "tests/test_trust_readiness_controls.py", "tests/test_trust_readiness_registry.py",
})


def _revenue_v2_csrf_successor_exact(changed, blobs, main_valid, call_sites):
    return (
        main_valid
        and blobs == REVENUE_V2_CSRF_SUCCESSOR_BLOBS
        and set(changed) == REVENUE_V2_CSRF_TRUST_DELTA
        and frozenset(call_sites) == F4_CSRF_CALL_SITES
    )


# Immutable normal-merge release identity. Keep the original pre-merge
# REVENUE_V2_CSRF_MAIN and all F4/WF07 release constants unchanged.
REVENUE_V2_ACCEPTED_MERGE = "6315f1d2ed9798ba77628357090013d3ebbf59a7"
REVENUE_V2_ACCEPTED_HEAD = "7354516cfd92c713ae452e36c2b81fed8b52e746"
REVENUE_V2_ACCEPTED_TREE = "727ac064b146239cc1fcdbe62f78e513f9abc63c"
# Only the two independently reviewed Revenue V2 POST handlers are compared
# within the shared router. Everything else financial/security-sensitive below
# is checked as exact released Git content; there is no whole-directory waiver.
REVENUE_V2_PROTECTED_ROUTER_FUNCTIONS = frozenset({
    "v2_revenue_contracts", "v2_revenue_commercial_stress",
    "_get_current_user", "_build_pis_with_composite_identity",
})
REVENUE_V2_OTHER_CRITICAL_PATHS = frozenset({
    "app/auth.py", "app/v2/investor_f4_router.py",
    "app/ui/protected_reference_service.py",
    "app/persistence/projects_repository.py",
    "app/workbook/revenue_contracts_service.py",
    "app/workbook/revenue_multistream.py",
    "app/workbook/revenue_commercial_stress.py",
})


def _revenue_critical_functions(source: str):
    """Return exact text including route decorators. Fail closed on duplicates.

    This is intentionally *not* an AST-only normalized hash: even a one-byte
    change inside a protected handler is unauthorized. Outside additions are
    accepted only insofar as independent PR scope/governance also allows them.
    """
    import ast
    tree = ast.parse(source)
    lines = source.splitlines(keepends=True)
    selected = {}
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in REVENUE_V2_PROTECTED_ROUTER_FUNCTIONS:
            if node.name in selected:
                raise ValueError("duplicate protected Revenue route")
            start = min([node.lineno] + [d.lineno for d in node.decorator_list])
            selected[node.name] = "".join(lines[start - 1:node.end_lineno])
    if set(selected) != REVENUE_V2_PROTECTED_ROUTER_FUNCTIONS:
        raise ValueError("missing protected Revenue route")
    return selected


def _revenue_post_merge_exact(merger_parents, release_tree, historical_blobs,
                              current_blobs, historical_f4_blobs, trust_delta,
                              call_sites, released_router, current_router):
    """Pure fail-closed verifier; mutation tests can exercise all controls."""
    expected_parents = (REVENUE_V2_CSRF_MAIN, REVENUE_V2_ACCEPTED_HEAD)
    if tuple(merger_parents) != expected_parents or release_tree != REVENUE_V2_ACCEPTED_TREE:
        return False
    expected_paths = set(REVENUE_V2_CSRF_SUCCESSOR_BLOBS) | set(REVENUE_V2_OTHER_CRITICAL_PATHS)
    if set(historical_blobs) != expected_paths or any(
            historical_blobs.get(path) != blob
            for path, blob in REVENUE_V2_CSRF_SUCCESSOR_BLOBS.items()):
        return False
    if historical_f4_blobs != F4_CSRF_BLOBS:
        return False
    # The guard file itself is the narrowly reviewed correction; all other
    # Trust, financial, release-pin and writer paths retain release content.
    if set(trust_delta) - {CSRF_GUARD_PATH}:
        return False
    if frozenset(call_sites) != F4_CSRF_CALL_SITES:
        return False
    expected_current = {
        k: v for k, v in REVENUE_V2_CSRF_SUCCESSOR_BLOBS.items()
        if k != "app/v2/router.py"
    }
    if any(current_blobs.get(k) != v for k, v in expected_current.items()):
        return False
    if any(k not in current_blobs for k in REVENUE_V2_OTHER_CRITICAL_PATHS):
        return False
    if any(current_blobs[k] != historical_blobs[k]
           for k in REVENUE_V2_OTHER_CRITICAL_PATHS):
        return False
    try:
        return _revenue_critical_functions(released_router) == _revenue_critical_functions(current_router)
    except (SyntaxError, ValueError, TypeError):
        return False


def test_f4_csrf_exception_accepts_only_the_exact_approved_correction():
    assert _f4_csrf_exact_content_authorized(
        F4_CSRF_PATHS, dict(F4_CSRF_BLOBS), F4_CSRF_PATHS, True, F4_CSRF_CALL_SITES,
    )


@pytest.mark.parametrize("path", sorted(F4_CSRF_BLOBS))
def test_f4_csrf_exception_rejects_altered_or_missing_blobs(path):
    for replacement in ("0" * 40, None):
        blobs = dict(F4_CSRF_BLOBS)
        if replacement is None:
            del blobs[path]
        else:
            blobs[path] = replacement
        assert not _f4_csrf_exact_content_authorized(
            F4_CSRF_PATHS, blobs, F4_CSRF_PATHS, True, F4_CSRF_CALL_SITES,
        )


@pytest.mark.parametrize("path", sorted(F4_CSRF_PATHS))
def test_f4_csrf_exception_rejects_incomplete_scope(path):
    incomplete = F4_CSRF_PATHS - {path}
    for changed, since_review in ((incomplete, F4_CSRF_PATHS), (F4_CSRF_PATHS, incomplete)):
        assert not _f4_csrf_exact_content_authorized(
            changed, dict(F4_CSRF_BLOBS), since_review, True, F4_CSRF_CALL_SITES,
        )


def test_f4_csrf_exception_rejects_invalid_checkpoint_and_validator_inventory():
    assert not _f4_csrf_exact_content_authorized(
        F4_CSRF_PATHS, dict(F4_CSRF_BLOBS), F4_CSRF_PATHS, False, F4_CSRF_CALL_SITES,
    )
    for sites in (F4_CSRF_CALL_SITES - {"app/v2/investor_f4_router.py"},
                  F4_CSRF_CALL_SITES | {"app/v2/unreviewed.py"}):
        assert not _f4_csrf_exact_content_authorized(
            F4_CSRF_PATHS, dict(F4_CSRF_BLOBS), F4_CSRF_PATHS, True, sites,
        )


def test_f4_integration_accepts_only_the_exact_normal_merge_and_guard_correction():
    parents = (F4_CSRF_CORRECTION_A, F4_CSRF_APPROVED_MAIN)
    assert _f4_integration_exact_content_authorized(parents, F4_CSRF_INTEGRATION_TREE, {CSRF_GUARD_PATH}, True)
    for actual_parents in (parents[::-1], parents[:1], parents + (F4_CSRF_MAIN,)):
        assert not _f4_integration_exact_content_authorized(
            actual_parents, F4_CSRF_INTEGRATION_TREE, {CSRF_GUARD_PATH}, True,
        )
    assert not _f4_integration_exact_content_authorized(parents, "0" * 40, {CSRF_GUARD_PATH}, True)
    assert not _f4_integration_exact_content_authorized(parents, F4_CSRF_INTEGRATION_TREE, {CSRF_GUARD_PATH}, False)


# ── fail-closed proofs of the exception (pure; no git) ──────────────────────────────────────


# PR #270 bounded successor. Historical WF05/Revenue/F4/demo pins above are
# immutable. These candidate pins constrain the complete F3.5-B diff, not a
# financial namespace or a router-wide security exemption.
F35B_CSRF_BASE = "cff1a7b19a72429636ec20325aadf5364365b12d"
F35B_CSRF_OLD = "Investor agreement Save and one crypto action. Other "
F35B_CSRF_NEW = "Investor agreement Save, session-bound Capital Stack instrument Save and one crypto action. Other "
F35B_CSRF_BLOBS = {
    "tests/model_outputs_workspace_acceptance.py": "07b04003b8a35f2750b9227531c60499b2b65121",
    "app/v2/capital_stack_projection.py": "a42e0258904fd3a9c4aa2b931d63f8007581069f",
    "app/templates/v2/partials/_financing_multisenior.html": "6197f19411ab9051859e334c3c681c0262f71fa2",
    "app/v2/router.py": "82f836ed397e46d8384288a0bd967381af96ea04",
    "app/workbook/financing_csrf.py": "4e30083fbd64b3157b3057d87ac73f95e039ae33",
    "app/trust_readiness/registry.py": "dfdd0f668ee78e510ed38f17f6b343be63c8a61d",
    "docs/readiness/03_known_limitations_and_support_matrix.md": "d8407e9a318d32f56d2b015e472a5a583a9a5b5b",
    "docs/model_v2/financing_f3/F3_5_B_RELEASE_READINESS_REPORT.md": "625373ef0e93941e37492ce0b38012b02c81adaf",
    "tests/test_model_financing_f2.py": "0adc439820a36629aa3e0d9aa00c8fae0fc7a9ae",
    "tests/test_trust_readiness_controls.py": "b55f2bc00dd2cefe6a69f9ef9202b4066c0b2415",
    "tests/test_financing_f35b_release_closed.py": "9a4253d27f0c4ef7cbbcd075837a2a33c8da1875",
    "tests/test_financing_f35b_numerical.py": "c7b06472a94d858fc8186aece380384121e6e132",
    "tests/test_financing_f35b_browser.py": "eb8f502436879cd7caf787077462f6bc6674eb9b",
    "tests/test_financing_f35b_csrf.py": "73894bd976f973c3be2ab32ad284073c87ad5de7",
}


def _f35b_csrf_registry(original):
    if original.count(F35B_CSRF_OLD) != 1:
        raise ValueError("missing exact Capital Stack CSRF source sentence")
    return original.replace(F35B_CSRF_OLD, F35B_CSRF_NEW, 1)


# ── D-029 (PR #384): bounded additive Trust successor ─────────────────────────────────────────
# The ONLY newly admitted registry difference is the reviewed `data.run_intents` data-store entry
# (the Run-intent ledger table), inserted at one exact position. It is verified from the exact merged
# main baseline text, never by accepting "whatever the current file says"; every earlier historical
# layer above (WF-05, Revenue V2, F4, demo retention, F3.5-B, RC-1, M4) is untouched and still
# applies to the text this transformation starts from.
D029_TRUST_MAIN = "36edeeb5d9a14749fdfafcd3b60a0d384cac73ba"
D029_TRUST_MAIN_REGISTRY_BLOB = "32a6bcb86516ff4d1ee8b1dc90191fdb57c5dc2d"
D029_TRUST_REGISTRY_BLOB = "99ff83825e6bef013be9411235d2d77345f78b02"
D029_RUN_INTENTS_ANCHOR = '    DataStoreEntry(\n        "data.backups", "Database backups",'
D029_RUN_INTENTS_ENTRY = '''    DataStoreEntry(
        "data.run_intents", "Run idempotency intents (D-029)", "SQLite database",
        "actor_id (workspace owner), project_id",
        "One row per client Run intent: a UUID, one-way digests of the submitted binding and the "
        "frozen effective inputs, the intent state and, once committed, the history_id it is "
        "bound to. No financial results, no credentials and no tokens.", False,
        "Not automatically deleted: a database trigger refuses DELETE. Retention is an open "
        "owner decision; until it is approved rows are kept so a committed intent can always be "
        "reconciled to its exact history row.",
        "No deletion path exists. Rows are small and are removed only by an approved, "
        "explicitly authorized retention procedure.", False,
        S.REQUIRES_OPERATIONAL_CONTROLS,
        (_code("app/persistence/run_intent_repository.py", "CREATE TABLE IF NOT EXISTS model_run_intents"),),
        "Intent rows of a deleted or disposed project are retained until the retention "
        "decision is made; they carry identifiers and digests only.",
        tables=("model_run_intents",),
    ),
'''


def _d029_registry(original: str) -> str:
    if original.count(D029_RUN_INTENTS_ANCHOR) != 1 or "data.run_intents" in original:
        raise ValueError("D-029 insertion point missing, duplicated or already applied")
    return original.replace(D029_RUN_INTENTS_ANCHOR, D029_RUN_INTENTS_ENTRY + D029_RUN_INTENTS_ANCHOR, 1)


# ── WS-2 Trust successor (Save All request ledger) ──────────────────────────────────────────────
# Additive and chained exactly like D-029: ONE reviewed DataStoreEntry for the new `save_all_requests` table,
# inserted at the same exact position (after the D-029 entry, before "data.backups").  Every historical layer
# above stays untouched; the transformation starts from the D-029 text.
WS2_TRUST_REGISTRY_BLOB = "c616833bdce263b60b4bccec217cad1fb4e8d7d8"
WS2_SAVE_ALL_ANCHOR = D029_RUN_INTENTS_ANCHOR
WS2_SAVE_ALL_ENTRY = '    DataStoreEntry(\n        "data.save_all_requests", "Save All request ledger (WS-2)", "SQLite database",\n        "user_id, project_id",\n        "One row per Save All request: the client request id, a one-way SHA-256 digest of the canonical request "\n        "body and the stored outcome (the resulting content hash and the per-section counts). No credentials, "\n        "no tokens and no financial results; the submitted values are not copied here.", False,\n        "Not automatically deleted: rows are small and let an interrupted Save All be repeated safely (the same "\n        "request id with an identical body returns the stored outcome; a different body under the same id is "\n        "refused). Retention is an open owner decision; until it is approved rows are kept.",\n        "No deletion path exists. Rows carry identifiers and digests only and are removed only by an approved, "\n        "explicitly authorized retention procedure.", False,\n        S.REQUIRES_OPERATIONAL_CONTROLS,\n        (_code("app/persistence/db.py", "CREATE TABLE IF NOT EXISTS save_all_requests"),),\n        "Ledger rows of a deleted or disposed project are retained until the retention decision is made; "\n        "they carry identifiers and digests only.",\n        tables=("save_all_requests",),\n    ),\n'


def _ws2_registry(original: str) -> str:
    if original.count(WS2_SAVE_ALL_ANCHOR) != 1 or "data.save_all_requests" in original:
        raise ValueError("WS-2 insertion point missing, duplicated or already applied")
    return original.replace(WS2_SAVE_ALL_ANCHOR, WS2_SAVE_ALL_ENTRY + WS2_SAVE_ALL_ANCHOR, 1)


def _registry_with_d029(base_registry: str):
    """The reviewed registry texts for a historical base: unchanged, or plus the one D-029 entry."""
    return (base_registry.strip(), _d029_registry(base_registry).strip())


def _f35b_csrf_exact(changed, blobs, provenance, call_sites, base_registry, current_registry):
    try:
        return (provenance
                and set(changed) == set(F35B_CSRF_BLOBS) | {CSRF_GUARD_PATH}
                and blobs == F35B_CSRF_BLOBS
                and frozenset(call_sites) == F4_CSRF_CALL_SITES
                and current_registry == _f35b_csrf_registry(base_registry))
    except (ValueError, TypeError):
        return False


# ── Integrated RC-1 exact-content governance successor ──────────────────────────────────────
# RC-1 integrates five independently reviewed PRs (#271, #272, #268, #270, #237) by normal merge.
# Every historical constant above stays immutable. This successor is NOT "any descendant of the
# release candidate is allowed": it holds only while (1) the Git provenance is exactly the five
# reviewed source heads merged in order with two parents, (2) every changed path is either an exact
# reviewed blob, a rule-verified router function, a rule-scanned read-only module, or a path in a
# non-authority namespace, and (3) the protected router handlers still behave as approved. It never
# pins this guard file itself, and it grants no router-wide, financial or Radar namespace exemption.
RC1_BASE_MAIN = F35B_CSRF_BASE
RC1_SOURCE_HEADS = (          # merge order; each must be the second parent of a normal merge
    ("271", "5bf529fdef89f2f70265e2443f5274e1e3c8f9e2"),
    ("272", "f3c5aaaa8ef507593301e2ee1582465aea7ff4af"),
    ("268", "685fb8275a94c66c6607bb1b37fa38af0d5b586e"),
    ("270", "8fe1f05c1c5db252621b78c57fb52c5b2a3caf51"),
    ("237", "4b4e9302d01581b3c44a506af7f8500f3b58e27e"),
)
RC1_RADAR_BLOBS = {           # the three reviewed Radar blobs; no wildcard and no fourth path
    "app/radar_rwa/r_live_service.py": "6c0e291db48fd208ecd1dc59e39e16dc03df273e",
    "finco_radar/venues/intelligence.py": "d5673713d6fff4e14e039ffaea75482e67bc0008",
    "finco_radar/venues/robinhood_live.py": "85b6f951516f11e08c768a05e8c6e95e5c406a15",
}
RC1_EXACT_BLOBS = {
    # #270 security contract: everything except the shared router, which has its own rule below.
    **{path: blob for path, blob in F35B_CSRF_BLOBS.items() if path != "app/v2/router.py"},
    **RC1_RADAR_BLOBS,
    # #237 governance hooks that admit exactly the Radar blobs above.
    "tests/finance_integrity_governance.py": "962f9f2c16d8b70501d5d2406405bf1dccba512e",
    "tests/model_v2_governance.py": "13b7fb3b90a3b6a3b776fc660edc1a59cc5381cc",
    "tests/radar_authority_governance.py": "1398a217163c20aa18a443d23e3cd6b565602445",
    "tests/test_radar_authority_governance.py": "f40a1529c3a5d8d13a46c1a313816958db7ce02d",
    # #268 read-only period adapter over the canonical check (default behaviour unchanged).
    "app/run_integrity/checks.py": "dc5c25f0864e365e25b568d18f4a61fd43350d41",
    # #271 closed candidate (no activation, no writer).
    "app/model_v2/investor_f4_candidate/p2_contracts.py": "71e29a07efcd84e870753e30250a2c278b6e0f2b",
    "app/model_v2/investor_f4_candidate/p2_evaluator.py": "a20138abfbe87e2f04b234c69f35a132dc0084c3",
}
# Read-only presentation modules: any change is accepted only while they gain no writer, route,
# persistence or CSRF reference compared with main.
RC1_SCANNED_MODULES = frozenset({
    "app/v2/diagnostics_projection.py", "app/v2/insight_quality_projection.py",
    "app/v2/post_run_ui.py", "app/v2/workspace_destinations.py",
})
RC1_FORBIDDEN_REFERENCES = (
    r"validate_csrf_token", r"financing_csrf", r"@router\.", r"APIRouter", r"update_service",
    r"apply_(?:batch_)?draft_update", r"save_contracts", r"save_agreement", r"persistence",
    r"run_history_repository", r"v2_atomic_run_commit\(",
)
RC1_FREE_PREFIXES = ("tests/", "docs/model_v2/", "static/", "app/templates/", "tools/numerical_validation/")
RC1_FREE_FILES = frozenset({"tools/model_financing_f3_evidence.py"})
RC1_SENSITIVE_TEST_PATTERN = r"^tests/(?:[^/]*governance[^/]*|test_trust_readiness_[^/]*|test_financing_f35b_[^/]*)\.py$"
# Router: the ONLY functions that differ from main, as exact text (decorators included).
RC1_ROUTER_MODIFIED_SHA256 = {
    "_attach_insight": "5ebe92bd8b1f6928ad660bbdfd248c6c11af576d210cff27a2b9827287507fe4",
    "_base_sheet_ctx": "f0d11172ae0e3e53b3488dec4f355662cb69367fd5548d094997343f7975edd8",
    "v2_workbook": "1b624bbee79a12ce1e73fb03ad6b104dcd36842cad5e314f84af58a19151be13",
    "v2_workbook_update": "3a9cd70b61ee87877d2dab9c0c4f732bf4f85f17b15a3253b261904b079ce6de",
}
RC1_ROUTER_ADDED_SHA256 = {      # read-only Diagnostics route; GET only
    "v2_model_diagnostics": "ddc545d205bc5cfa95047f9bd6e45c508e1d8f8a4ccd08606c9c8b15a0e2c971",
}
RC1_ROUTER_CSRF_FUNCTIONS = frozenset({"v2_revenue_contracts", "v2_revenue_commercial_stress", "v2_workbook_update"})
RC1_CAPITAL_STACK_FIELD = "debt.financing.instruments"
RC1_STATE_CHANGING_VERBS = frozenset({"post", "put", "patch", "delete"})


def _router_function_texts(source: str):
    import ast
    tree = ast.parse(source)
    lines = source.splitlines(keepends=True)
    functions, others = {}, []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.name in functions:
                raise ValueError(f"duplicate router function {node.name}")
            start = min([node.lineno] + [d.lineno for d in node.decorator_list])
            functions[node.name] = ("".join(lines[start - 1:node.end_lineno]), node)
        else:
            others.append(ast.dump(node))
    return functions, others


def _decorator_verbs(node):
    import ast
    verbs = set()
    for decorator in node.decorator_list:
        target = decorator.func if isinstance(decorator, ast.Call) else decorator
        if isinstance(target, ast.Attribute):
            verbs.add(target.attr)
    return verbs


def _csrf_call_functions(functions) -> set[str]:
    import ast
    return {name for name, (_, node) in functions.items()
            if any(isinstance(c, ast.Call) and isinstance(c.func, ast.Name) and c.func.id == "validate_csrf_token"
                   for c in ast.walk(node))}


def _capital_stack_gate_violations(node) -> list[str]:
    """Effective behaviour of the field-only Capital Stack CSRF gate in ``v2_workbook_update``."""
    import ast
    problems = []
    body = node.body
    gate_at = next((i for i, s in enumerate(body) if isinstance(s, ast.If)
                    and ast.unparse(s.test) == f"field_id == {RC1_CAPITAL_STACK_FIELD!r}"), None)
    if gate_at is None:
        return ["Capital Stack field gate is missing or no longer exactly the instrument field"]
    gate = body[gate_at]
    validator = [c for c in ast.walk(gate) if isinstance(c, ast.Call) and isinstance(c.func, ast.Name)
                 and c.func.id == "validate_csrf_token"]
    if len(validator) != 1 or ast.unparse(validator[0].args[0]) != \
            "extract_bound_token(request, project, form.get('csrf_token'))":
        problems.append("canonical timed validation must wrap the session+project bound token")
    rejects = [r for r in ast.walk(gate) if isinstance(r, ast.Return) and r.value is not None
               and "403" in ast.unparse(r.value)]
    if not rejects or not any(isinstance(s, ast.If) and isinstance(s.test, ast.UnaryOp) for s in gate.body):
        problems.append("an invalid token must be rejected with 403 inside the gate")
    def first_call(name):
        return next((i for i, s in enumerate(body) if any(
            isinstance(c, ast.Call) and getattr(c.func, "id", getattr(c.func, "attr", None)) == name
            for c in ast.walk(s))), None)
    for earlier in ("resolve_accessible_project", "is_protected_reference"):
        at = first_call(earlier)
        if at is None or at > gate_at:
            problems.append(f"{earlier} must run before the CSRF gate")
    persistence = first_call("get_workspace_state")
    if persistence is None or persistence < gate_at:
        problems.append("the CSRF gate must run before any workspace read or persistence")
    if "content_hash" not in ast.unparse(node):
        problems.append("composite CAS (content_hash) handling is missing")
    return problems


def _rc1_router_violations(base_source: str, head_source: str) -> list[str]:
    import hashlib
    try:
        base_fn, base_other = _router_function_texts(base_source)
        head_fn, head_other = _router_function_texts(head_source)
    except (SyntaxError, ValueError, TypeError) as exc:
        return [f"router is not analysable: {exc}"]
    problems = []
    if [n for n in base_fn if n not in head_fn]:
        problems.append("router functions were removed")
    if base_other != head_other:
        problems.append("router module-level statements differ from main")
    modified = {n for n in base_fn if n in head_fn and base_fn[n][0] != head_fn[n][0]}
    added = set(head_fn) - set(base_fn)
    if modified != set(RC1_ROUTER_MODIFIED_SHA256) or added != set(RC1_ROUTER_ADDED_SHA256):
        problems.append(f"router changed-function set is not the approved one: modified={sorted(modified)} added={sorted(added)}")
    for name, expected in {**RC1_ROUTER_MODIFIED_SHA256, **RC1_ROUTER_ADDED_SHA256}.items():
        if name in head_fn and hashlib.sha256(head_fn[name][0].encode()).hexdigest() != expected:
            problems.append(f"router function {name} is not the approved text")
    for name in added:
        if _decorator_verbs(head_fn[name][1]) & RC1_STATE_CHANGING_VERBS:
            problems.append(f"added router function {name} is a state-changing route")
    for name in modified & set(head_fn):
        if _decorator_verbs(head_fn[name][1]) != _decorator_verbs(base_fn[name][1]):
            problems.append(f"route methods of {name} changed")
    try:
        if _revenue_critical_functions(base_source) != _revenue_critical_functions(head_source):
            problems.append("protected Revenue V2 / owner functions differ from main")
    except (SyntaxError, ValueError, TypeError):
        problems.append("protected Revenue V2 functions are not verifiable")
    if _csrf_call_functions(head_fn) != RC1_ROUTER_CSRF_FUNCTIONS:
        problems.append("the set of router handlers that validate CSRF is not the approved one")
    if "v2_workbook_update" in head_fn:
        problems.extend(_capital_stack_gate_violations(head_fn["v2_workbook_update"][1]))
    else:
        problems.append("v2_workbook_update is missing")
    return problems


def _rc1_path_violations(status_rows, blobs, scans) -> list[str]:
    """Classify every path changed against main. ``status_rows`` are (status, path) pairs."""
    import re
    problems = []
    changed = {path for _, path in status_rows}
    for status, path in status_rows:
        if status not in ("A", "M"):
            problems.append(f"{path}: {status} is not permitted (no deletions, renames or type changes)")
            continue
        if path in RC1_EXACT_BLOBS:
            if blobs.get(path) != RC1_EXACT_BLOBS[path]:
                problems.append(f"{path}: not the exact reviewed blob")
        elif path == "app/v2/router.py" or path == CSRF_GUARD_PATH:
            continue
        elif path in RC1_SCANNED_MODULES:
            head, base = scans.get(path, (None, None))
            if head is None:
                problems.append(f"{path}: content unavailable")
                continue
            for pattern in RC1_FORBIDDEN_REFERENCES:
                if len(re.findall(pattern, head)) > len(re.findall(pattern, base or "")):
                    problems.append(f"{path}: gained a writer/route/CSRF reference ({pattern})")
        elif re.match(RC1_SENSITIVE_TEST_PATTERN, path):
            problems.append(f"{path}: governance/Trust/F3.5-B test changed outside the reviewed set")
        elif path.startswith(RC1_FREE_PREFIXES) or path in RC1_FREE_FILES:
            continue
        else:
            problems.append(f"{path}: not part of the reviewed integration")
    for path in sorted(set(RC1_EXACT_BLOBS) - changed):
        problems.append(f"{path}: reviewed change is missing")
    return problems


def _rc1_integration_violations(f) -> list[str]:
    """Pure, fail-closed verifier over injected facts. [] means the successor holds."""
    try:
        problems = []
        if not f["base_ok"]:
            problems.append("immutable main baseline is not an ancestor of HEAD")
        previous = RC1_BASE_MAIN
        for pr, head in RC1_SOURCE_HEADS:
            merge = f["merges"].get(pr)
            if not f["source_ancestor"].get(pr) or merge is None:
                problems.append(f"#{pr}: reviewed head is not merged")
                continue
            sha, first, second = merge
            if second != head:
                problems.append(f"#{pr}: second parent is not the reviewed head")
            if first != previous:
                problems.append(f"#{pr}: first parent breaks the normal-merge chain")
            previous = sha
        problems += _rc1_path_violations(f["status"], f["blobs"], f["scans"])
        problems += _rc1_router_violations(f["router_base"], f["router_head"])
        if f["registry_current"].strip() != _f35b_csrf_registry(f["registry_base"]).strip():
            problems.append("Trust registry is not main plus the one approved Capital Stack CSRF sentence")
        if frozenset(f["call_sites"]) != F4_CSRF_CALL_SITES:
            problems.append("CSRF validation call sites differ from the approved set")
        return problems
    except (KeyError, TypeError, ValueError, AttributeError) as exc:
        return [f"facts incomplete or malformed: {exc!r}"]


def _mutated(facts, **changes):
    import copy
    out = copy.deepcopy(facts)
    out.update(changes)
    return out


def _all_rc1_changed(facts, *extra):
    return [*facts["status"], *extra]


def _update_function(router):
    return _router_function_texts(router)[0]["v2_workbook_update"][0]


# ── Post-merge RC-1 checkpoint (main already contains the integrated release) ───────────────
# The pre-merge successor above authorizes the integration DIFF against the old main. Once the
# release is on main, later PRs are checked against the immutable merged checkpoint instead:
# provenance of the merge, exact reviewed blobs of every security/Radar/financial authority, the
# protected router handlers (Revenue V2, Capital Stack CSRF gate) and the CSRF call-site inventory.
# Each later PR that legitimately extends an exact-blob file or the CSRF inventory adds its own
# explicit, reviewed successor entry below; there is no namespace waiver and no "descendant" rule.
RC1_MERGED_CHECKPOINT = "5058c6b4935168241d6923676cb32955cb903185"
RC1_MERGED_PARENTS = (RC1_BASE_MAIN, "097ca1829131ded67278917bad06696eda5b91aa")
# RC-2 / M4: the Developer Economics configuration Save is a new, CSRF-protected command.
M4_CSRF_NEW = ("Investor agreement Save, session-bound Capital Stack instrument Save, Developer Economics "
               "configuration Save and one crypto action. Other ")
M4_CALL_SITES = F4_CSRF_CALL_SITES | {"app/v2/developer_decision_router.py"}
RC1_SUCCESSOR_BLOBS = {         # path -> additional reviewed blobs accepted after the RC-1 blob
    # RC-2: adds ONLY the reviewer-conditional, release-closed Revenue V3 candidate map (three exact blobs).
    "tests/model_v2_governance.py": ("bf197d35c79a99656821eb77c441a719415ee0a4",),
    "app/trust_readiness/registry.py": ("32a6bcb86516ff4d1ee8b1dc90191fdb57c5dc2d",),
    "docs/readiness/03_known_limitations_and_support_matrix.md": ("4930d20a749706e40e234751f5a9c5226bb42e60",),
    "tests/test_trust_readiness_controls.py": ("9bf549373574398a56e1e7cb4264ff57c580e34c",),
}


def _m4_registry(f35b_registry: str) -> str:
    if f35b_registry.count(F35B_CSRF_NEW) != 1:
        raise ValueError("missing exact Capital Stack CSRF sentence")
    return f35b_registry.replace(F35B_CSRF_NEW, M4_CSRF_NEW, 1)


# ── D-029 Trust successor: proof and negatives ───────────────────────────────────────────────


def test_d029_trust_entry_makes_only_accurate_retention_claims():
    entry = D029_RUN_INTENTS_ENTRY
    assert "data.run_intents" in entry and "model_run_intents" in entry
    assert "Not automatically deleted" in entry and "trigger refuses DELETE" in entry
    for misleading in ("automatically deleted after", "24 hour", "24h", "purged", "expire", "TTL", "certified", "encrypted"):
        assert misleading not in entry, misleading
    assert "No financial results, no credentials and no tokens" in entry
    from app.trust_readiness import registry as live
    item = next(d for d in live.DATA_STORES if d.key == "data.run_intents")
    assert "open owner decision" in item.retention_rule and "trigger refuses DELETE" in item.retention_rule
    assert item.automatic_deletion is False and item.may_contain_user_text is False
    assert item.tables == ("model_run_intents",)
    assert any(e.path == "app/persistence/run_intent_repository.py" for e in item.evidence)


def test_d029_trust_successor_does_not_weaken_historical_layers():
    base = _git("show", f"{D029_TRUST_MAIN}:app/trust_readiness/registry.py")
    d029 = _d029_registry(base)
    for sentence in (F4_CSRF_NEW, F35B_CSRF_NEW, M4_CSRF_NEW):
        assert d029.count(sentence) == 1 or sentence not in base
    # historical constants and snapshots stay the exact originals
    assert len(DEMO_RETENTION_BLOBS) >= 10 and F4_CSRF_BLOBS["app/trust_readiness/registry.py"] == "ea39361e3f48ffe2588e5f451afd405e19a1651f"
    assert CSRF_EXACT_BLOBS["app/trust_readiness/registry.py"] == "a246863f7c8b206828da06a0a9003dd96acc69c9"
    assert DEMO_RETENTION_BLOBS["app/trust_readiness/registry.py"] == "4a53ea61846feaa52fad3e3f19acad0a00d78753"


def _mutated_current_registry(monkeypatch, mutate):
    text = mutate(_read_current("app/trust_readiness/registry.py"))
    assert text != _read_current("app/trust_readiness/registry.py")
    real = _read_current
    monkeypatch.setattr(__import__(__name__, fromlist=["_read_current"]), "_read_current",
                        lambda path: text if path == "app/trust_readiness/registry.py" else real(path))
    return text


def test_d029_successor_refuses_a_second_application_or_a_missing_anchor():
    base = _git("show", f"{D029_TRUST_MAIN}:app/trust_readiness/registry.py")
    with pytest.raises(ValueError):
        _d029_registry(_d029_registry(base))
    with pytest.raises(ValueError):
        _d029_registry(base.replace(D029_RUN_INTENTS_ANCHOR, "", 1))
