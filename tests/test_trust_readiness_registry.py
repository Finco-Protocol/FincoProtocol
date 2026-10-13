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
WF05_APPLICATION_PATHS = frozenset({
    ".github/workflows/protocol_ui_browser.yml",
    "app/templates/v2/partials/_hybrid_nav.html",
    "app/templates/v2/partials/sheet_capex.html",
    "app/templates/v2/partials/sheet_input_grid.html",
    "app/templates/v2/partials/sheet_opex.html",
    "app/templates/v2/workbook.html",
    "app/v2/grid_router.py",
    "app/v2/input_grid_projection.py",
    "app/v2/router.py",
    "app/v2/workspace_shell_projection.py",
    "docs/model_v2/WF05_HYBRID_INPUTS_GRID.md",
    "main_web.py",
    "static/css/inputs_grid_v1.css",
    "static/js/inputs_grid_v1.js",
    "tests/test_model_hybrid_inputs_grid_browser.py",
    "tests/test_model_hybrid_inputs_grid_f3_negative.py",
    "tests/test_model_hybrid_inputs_grid_routes.py",
})
_NEVER_EXCEPTED = ("financial_engine/", "finco_core/", "finco_radar/", "app/auth.py", "app/persistence/",
                   "app/workbook/", "app/demo_cleanup.py", "app/radar")


def _in_trust_scope(path: str) -> bool:
    return path.startswith(("app/trust_readiness/", "app/templates/trust/", "docs/readiness/",
                            "tests/test_trust_readiness_", "tools/render_readiness_docs.py")) \
        or path == "static/trust_readiness.css"


def wf05_exception_violations(changed, read_base, read_current, csrf_call_sites) -> list[str]:
    """Reasons the WF-05 exception does NOT hold ([] ⇒ it holds). Pure: callers inject the content."""
    problems: list[str] = []
    trust = {p for p in changed if _in_trust_scope(p)}
    expected_trust = set(WF05_REPLACEMENTS) | {WF05_GUARD_FILE}
    if trust != expected_trust:
        problems.append(f"Trust-side change is not exactly the approved set: extra={sorted(trust - expected_trust)} "
                        f"missing={sorted(expected_trust - trust)}")
    for path, (old, new) in WF05_REPLACEMENTS.items():
        base = read_base(path)
        if base is None or base.count(old) != 1:
            problems.append(f"{path}: approved original text not found exactly once in the base")
            continue
        if read_current(path) != base.replace(old, new, 1):
            problems.append(f"{path}: content is not exactly the base plus the approved CSRF replacement")
    if frozenset(csrf_call_sites) != WF05_CSRF_CALL_SITES:
        problems.append(f"token-validation call sites differ from the approved set: {sorted(csrf_call_sites)}")
    other = [p for p in changed if not _in_trust_scope(p)]
    stray = [p for p in other if p not in WF05_APPLICATION_PATHS]
    if stray:
        problems.append(f"changed files outside the enumerated WF-05 scope: {stray}")
    never = [p for p in changed if p.startswith(_NEVER_EXCEPTED)]
    if never:
        problems.append(f"engine / core / workbook / persistence / auth files changed: {never}")
    return problems


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


def _git_base_reader():
    import subprocess
    base = subprocess.run(["git", "merge-base", "origin/main", "HEAD"], capture_output=True, text=True,
                          cwd=str(ROOT), check=True).stdout.strip()

    def read_base(path):
        r = subprocess.run(["git", "show", f"{base}:{path}"], capture_output=True, text=True, cwd=str(ROOT))
        return r.stdout if r.returncode == 0 else None
    return read_base


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


def _current_csrf_correction_authorized(changed):
    try:
        _git("merge-base", "--is-ancestor", CSRF_SYNC_HEAD, "HEAD")
        unchanged_financial_authority = not _git(
            "diff", "--name-only", CSRF_REVIEWED_HEAD, CSRF_SYNC_HEAD, "--",
            "financial_engine", "finco_core", "domain",
            "tests/model_v2_governance.py", "tests/test_wf07_revenue_governance.py",
        )
        blobs = {
            path: _git("hash-object", f"--path={path}", path)
            for path in CSRF_EXACT_BLOBS
        }
        since_sync = _git("diff", "--name-only", CSRF_SYNC_HEAD).splitlines()
        return _csrf_exact_content_authorized(
            changed, blobs, since_sync, unchanged_financial_authority,
        )
    except (OSError, subprocess.CalledProcessError):
        return False


def test_csrf_registry_correction_is_only_the_two_approved_sentences():
    original = _git("show", f"{CSRF_TRUST_BASE}:app/trust_readiness/registry.py")
    replacements = (
        (
            "Tokens also protect the model-import steps and one crypto action.",
            "Tokens also protect the model-import steps, the Inputs grid validate and save routes, Revenue V2 contract writes and one crypto action.",
        ),
        (
            "CSRF tokens protect the login form, the model-import steps, the Inputs grid validate and save routes and one crypto action.",
            "CSRF tokens protect the login form, the model-import steps, the Inputs grid validate and save routes, Revenue V2 contract writes and one crypto action.",
        ),
    )
    for old, new in replacements:
        assert original.count(old) == 1
        original = original.replace(old, new, 1)
    # Preserve the historical CSRF proof; the only subsequent registry change
    # authorized here is the separately reviewed terminal-demo retention policy.
    assert _git("show", f"{DEMO_RETENTION_BASE}:app/trust_readiness/registry.py") == original
    assert _read_current("app/trust_readiness/registry.py").strip() == _f4_csrf_registry(_demo_retention_registry(original))


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


def test_csrf_exact_content_git_failure_is_not_an_authorization(monkeypatch):
    def unavailable(*args):
        raise subprocess.CalledProcessError(1, ["git", *args])

    monkeypatch.setattr(__import__(__name__, fromlist=["_git"]), "_git", unavailable)
    assert not _current_csrf_correction_authorized(list(CSRF_EXACT_BLOBS))


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


def _current_demo_retention_authorized(changed):
    try:
        base = _git("merge-base", "origin/main", "HEAD")
        blobs = {
            path: _git("hash-object", f"--path={path}", path)
            for path in DEMO_RETENTION_BLOBS
        }
        return _demo_retention_exact_content_authorized(changed, blobs, base == DEMO_RETENTION_BASE)
    except (OSError, subprocess.CalledProcessError):
        return False


def test_demo_retention_exception_accepts_only_exact_approved_content():
    assert _demo_retention_exact_content_authorized(DEMO_RETENTION_PATHS, dict(DEMO_RETENTION_BLOBS), True)
    base = _git("show", f"{DEMO_RETENTION_BASE}:app/trust_readiness/registry.py")
    assert _read_current("app/trust_readiness/registry.py").strip() == _f4_csrf_registry(_demo_retention_registry(base))


@pytest.mark.parametrize("path", DEMO_RETENTION_BLOBS)
def test_demo_retention_exception_rejects_modified_content(path):
    blobs = dict(DEMO_RETENTION_BLOBS)
    blobs[path] = "0" * 40
    assert not _demo_retention_exact_content_authorized(DEMO_RETENTION_PATHS, blobs, True)


@pytest.mark.parametrize("path", (
    "financial_engine/orchestrator.py", "finco_core/inputs/_models.py", "domain/tax.py",
    "app/persistence/run_history_repository.py", "app/auth.py", "app/workbook/update_service.py",
    "app/v2/router.py", ".github/workflows/public_safety.yml", "tests/model_v2_governance.py",
    "app/trust_readiness/projection.py", "app/templates/trust/retention.html",
    "docs/readiness/07_authentication_and_tenant_audit.md", "tools/render_readiness_docs.py",
))
def test_demo_retention_exception_rejects_any_broader_change(path):
    assert not _demo_retention_exact_content_authorized(
        DEMO_RETENTION_PATHS | {path}, dict(DEMO_RETENTION_BLOBS), True,
    )


@pytest.mark.parametrize("path", sorted(DEMO_RETENTION_PATHS))
def test_demo_retention_exception_rejects_incomplete_scope(path):
    assert not _demo_retention_exact_content_authorized(
        DEMO_RETENTION_PATHS - {path}, dict(DEMO_RETENTION_BLOBS), True,
    )


def test_demo_retention_exception_rejects_invalid_base_missing_pin_and_git_failure(monkeypatch):
    assert not _demo_retention_exact_content_authorized(DEMO_RETENTION_PATHS, dict(DEMO_RETENTION_BLOBS), False)
    assert not _demo_retention_exact_content_authorized(DEMO_RETENTION_PATHS, {}, True)

    def unavailable(*args):
        raise subprocess.CalledProcessError(1, ["git", *args])

    monkeypatch.setattr(__import__(__name__, fromlist=["_git"]), "_git", unavailable)
    assert not _current_demo_retention_authorized(DEMO_RETENTION_PATHS)


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


def _current_f4_csrf_authorized(changed):
    try:
        _git("merge-base", "--is-ancestor", F4_CSRF_INTEGRATION, "HEAD")
        _git("merge-base", "--is-ancestor", F4_CSRF_MAIN, F4_CSRF_APPROVED_MAIN)
        checkpoint_valid = (
            _git("merge-base", "origin/main", "HEAD") == F4_CSRF_APPROVED_MAIN
            and _git("merge-base", F4_CSRF_MAIN, F4_CSRF_REVIEWED_HEAD) == F4_CSRF_MAIN
            and _git("rev-list", "--parents", "-n", "1", F4_CSRF_CORRECTION_A).split()
                == [F4_CSRF_CORRECTION_A, F4_CSRF_REVIEWED_HEAD]
            and all(_git("rev-parse", f"{F4_CSRF_MAIN}:{p}") == DEMO_RETENTION_BLOBS[p]
                    and _git("rev-parse", f"{F4_CSRF_CORRECTION_A}:{p}") == blob
                    for p, blob in F4_CSRF_BLOBS.items())
        )
        parents = _git("rev-list", "--parents", "-n", "1", F4_CSRF_INTEGRATION).split()[1:]
        tree = _git("rev-parse", f"{F4_CSRF_INTEGRATION}^{{tree}}")
        since_integration = _git("diff", "--name-only", F4_CSRF_INTEGRATION).splitlines()
        integration_valid = _f4_integration_exact_content_authorized(
            parents, tree, since_integration, checkpoint_valid,
        )
        blobs = {p: _git("hash-object", f"--path={p}", p) for p in F4_CSRF_BLOBS}
        correction_a = _git("diff", "--name-only", F4_CSRF_REVIEWED_HEAD, F4_CSRF_CORRECTION_A).splitlines()
        return _f4_csrf_exact_content_authorized(
            changed, blobs, correction_a, integration_valid, _csrf_call_sites(),
        )
    except (OSError, subprocess.CalledProcessError):
        return False


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


def _current_revenue_v2_csrf_successor_valid():
    try:
        if _git("merge-base", "origin/main", "HEAD") != REVENUE_V2_CSRF_MAIN:
            return False
        if _git("rev-parse", REVENUE_V2_CSRF_MAIN) != REVENUE_V2_CSRF_MAIN:
            return False
        # Main must still hold the released F4 Trust snapshot.
        if any(_git("rev-parse", f"{REVENUE_V2_CSRF_MAIN}:{path}") != sha
               for path, sha in F4_CSRF_BLOBS.items()):
            return False
        changed = _git("diff", "--name-only", REVENUE_V2_CSRF_MAIN, "HEAD").splitlines()
        trust_changed = [p for p in changed if _in_trust_scope(p)]
        actual = {
            path: _git("hash-object", f"--path={path}", path)
            for path in REVENUE_V2_CSRF_SUCCESSOR_BLOBS
        }
        return _revenue_v2_csrf_successor_exact(
            trust_changed, actual, True, _csrf_call_sites())
    except (OSError, subprocess.CalledProcessError):
        return False


def test_revenue_v2_csrf_successor_exact_content_and_negatives():
    assert _current_revenue_v2_csrf_successor_valid()
    exact = dict(REVENUE_V2_CSRF_SUCCESSOR_BLOBS)
    permitted = set(REVENUE_V2_CSRF_TRUST_DELTA)
    assert _revenue_v2_csrf_successor_exact(permitted, exact, True, F4_CSRF_CALL_SITES)
    for path in exact:
        forged = dict(exact)
        forged[path] = "0" * 40
        assert not _revenue_v2_csrf_successor_exact(permitted, forged, True, F4_CSRF_CALL_SITES)
    assert not _revenue_v2_csrf_successor_exact(permitted, exact, False, F4_CSRF_CALL_SITES)
    assert not _revenue_v2_csrf_successor_exact(
        permitted | {"app/trust_readiness/registry.py"}, exact, True, F4_CSRF_CALL_SITES)
    assert not _revenue_v2_csrf_successor_exact(
        permitted, exact, True, F4_CSRF_CALL_SITES | {"app/v2/unknown_router.py"})


def test_f4_csrf_correction_preserves_historical_content_and_authorities():
    import ast

    original = _git("show", f"{F4_CSRF_MAIN}:app/trust_readiness/registry.py")
    assert _read_current("app/trust_readiness/registry.py").strip() == _f4_csrf_registry(original)
    for path, blob in F4_CSRF_BLOBS.items():
        actual = _git("hash-object", f"--path={path}", path)
        if path == "tests/test_trust_readiness_controls.py" and actual != blob:
            # The reviewed Revenue stress CSRF validator changes only the
            # additive inventory, never the historical F4 register or pin.
            assert _current_revenue_v2_csrf_successor_valid()
        else:
            assert actual == blob

    def constants(source):
        return {node.targets[0].id: ast.dump(node.value)
                for node in ast.parse(source).body
                if isinstance(node, ast.Assign) and len(node.targets) == 1
                and isinstance(node.targets[0], ast.Name) and node.targets[0].id.isupper()}

    historical = constants(_git("show", f"{F4_CSRF_MAIN}:{CSRF_GUARD_PATH}"))
    current = constants(_read_current(CSRF_GUARD_PATH))
    assert {name: current.get(name) for name in historical} == historical
    correction_a = constants(_git("show", f"{F4_CSRF_CORRECTION_A}:{CSRF_GUARD_PATH}"))
    assert {name: current.get(name) for name in correction_a} == correction_a


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


@pytest.mark.parametrize("path", (
    "app/trust_readiness/projection.py", "app/templates/trust/readiness.html",
    "docs/readiness/07_authentication_and_tenant_audit.md", "tools/render_readiness_docs.py",
    "tests/test_trust_readiness_claims.py", "static/trust_readiness.css",
    "financial_engine/orchestrator.py", "finco_core/inputs/_models.py", "domain/tax.py",
    "tests/model_v2_governance.py", "tests/test_wf07_revenue_governance.py",
    "app/workbook/update_service.py", "app/persistence/run_history_repository.py",
    "app/v2/investor_f4_router.py", "app/v2/router.py", "app/auth.py",
    "app/services/export_service.py", ".github/workflows/public_safety_and_smoke.yml",
    "tests/test_investor_f4_workspace.py", "unrelated.py",
))
def test_f4_csrf_exception_rejects_any_additional_change(path):
    broader = F4_CSRF_PATHS | {path}
    assert not _f4_csrf_exact_content_authorized(
        broader, dict(F4_CSRF_BLOBS), broader, True, F4_CSRF_CALL_SITES,
    )
    assert not _f4_integration_exact_content_authorized(
        (F4_CSRF_CORRECTION_A, F4_CSRF_APPROVED_MAIN), F4_CSRF_INTEGRATION_TREE,
        {CSRF_GUARD_PATH, path}, True,
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


def test_f4_csrf_exception_git_failure_is_not_authorization(monkeypatch):
    def unavailable(*args):
        raise subprocess.CalledProcessError(1, ["git", *args])

    monkeypatch.setattr(__import__(__name__, fromlist=["_git"]), "_git", unavailable)
    assert not _current_f4_csrf_authorized(F4_CSRF_PATHS)


def test_f4_integration_accepts_only_the_exact_normal_merge_and_guard_correction():
    parents = (F4_CSRF_CORRECTION_A, F4_CSRF_APPROVED_MAIN)
    assert _f4_integration_exact_content_authorized(parents, F4_CSRF_INTEGRATION_TREE, {CSRF_GUARD_PATH}, True)
    for actual_parents in (parents[::-1], parents[:1], parents + (F4_CSRF_MAIN,)):
        assert not _f4_integration_exact_content_authorized(
            actual_parents, F4_CSRF_INTEGRATION_TREE, {CSRF_GUARD_PATH}, True,
        )
    assert not _f4_integration_exact_content_authorized(parents, "0" * 40, {CSRF_GUARD_PATH}, True)
    assert not _f4_integration_exact_content_authorized(parents, F4_CSRF_INTEGRATION_TREE, {CSRF_GUARD_PATH}, False)


@pytest.mark.parametrize("command, output", (
    (("merge-base", "origin/main", "HEAD"), "0" * 40),
    (("merge-base", F4_CSRF_MAIN, F4_CSRF_REVIEWED_HEAD), "0" * 40),
    (("rev-list", "--parents", "-n", "1", F4_CSRF_CORRECTION_A),
     f"{F4_CSRF_CORRECTION_A} {F4_CSRF_MAIN}"),
    (("rev-list", "--parents", "-n", "1", F4_CSRF_INTEGRATION),
     f"{F4_CSRF_INTEGRATION} {F4_CSRF_APPROVED_MAIN} {F4_CSRF_CORRECTION_A}"),
    (("rev-parse", f"{F4_CSRF_INTEGRATION}^{{tree}}"), "0" * 40),
    (("merge-base", "--is-ancestor", F4_CSRF_INTEGRATION, "HEAD"), None),
    (("merge-base", "--is-ancestor", F4_CSRF_MAIN, F4_CSRF_APPROVED_MAIN), None),
))
def test_f4_integration_rejects_invalid_main_correction_or_checkpoint_provenance(monkeypatch, command, output):
    original_git = _git

    def invalid(*args):
        if args == command:
            if output is None:
                raise subprocess.CalledProcessError(1, ["git", *args])
            return output
        return original_git(*args)

    monkeypatch.setattr(__import__(__name__, fromlist=["_git"]), "_git", invalid)
    assert not _current_f4_csrf_authorized(F4_CSRF_PATHS)


def test_scope_guard_this_work_touches_no_engine_input_writer_or_radar_code():
    try:
        from finance_integrity_governance import changed_paths_vs_main

        changed = changed_paths_vs_main()
        read_base = _git_base_reader()
    except Exception as exc:  # no git history or no origin/main in this checkout
        if F4_CSRF_NEW in _read_current("app/trust_readiness/registry.py"):
            pytest.fail(f"F4 CSRF correction requires valid Git provenance: {exc}")
        pytest.skip(f"cannot compute the diff against main: {exc}")
    if not any(p.startswith("app/trust_readiness/") for p in changed):
        pytest.skip("trust pack not part of this diff")
    if _current_f4_csrf_authorized(changed):
        return          # Reviewed F4 + exact Correction A + pinned normal main integration.
    if _current_csrf_correction_authorized(changed):
        return          # PR #246 exact-blob CSRF correction (see CSRF_EXACT_BLOBS)
    if _current_demo_retention_authorized(changed):
        return          # Separate bounded demo-retention correction, exact content only.
    if not wf05_exception_violations(changed, read_base, _read_current, _csrf_call_sites()):
        return          # the exact, evidence-backed WF-05 integration (see WF05_REPLACEMENTS)
    bad = [p for p in changed if p.startswith(FORBIDDEN_PREFIXES)]
    assert not bad, f"out-of-scope files changed: {bad}"
    stray = [p for p in changed if p != "main_web.py" and not p.startswith(ALLOWED_PREFIXES)]
    assert not stray, f"files outside the trust pack changed: {stray}"


# ── fail-closed proofs of the exception (pure; no git) ──────────────────────────────────────

def _scenario(**override):
    changed = sorted(set(WF05_REPLACEMENTS) | {WF05_GUARD_FILE} | WF05_APPLICATION_PATHS)
    base = {p: f"before {old} after" for p, (old, _new) in WF05_REPLACEMENTS.items()}
    cur = {p: f"before {new} after" for p, (_old, new) in WF05_REPLACEMENTS.items()}
    args = {"changed": changed, "base": base, "cur": cur, "sites": set(WF05_CSRF_CALL_SITES)}
    args.update(override)
    return args


def _violations(a):
    return wf05_exception_violations(a["changed"], a["base"].get, a["cur"].get, a["sites"])


def test_wf05_exception_holds_for_the_exact_approved_integration():
    assert _violations(_scenario()) == []


def test_wf05_exception_fails_when_trust_text_is_altered_or_extended():
    a = _scenario()
    path = "app/trust_readiness/registry.py"
    a["cur"][path] = a["cur"][path] + " plus an extra unapproved claim"
    assert any("not exactly the base plus the approved" in p for p in _violations(a))
    a = _scenario()
    a["cur"]["docs/readiness/03_known_limitations_and_support_matrix.md"] = "unrelated rewrite"
    assert _violations(a)


def test_wf05_exception_fails_on_any_additional_trust_file_or_unrelated_code():
    a = _scenario()
    a["changed"] = a["changed"] + ["app/trust_readiness/projection.py"]
    assert any("not exactly the approved set" in p for p in _violations(a))
    a = _scenario()
    a["changed"] = a["changed"] + ["app/v2/some_other_router.py"]
    assert any("outside the enumerated WF-05 scope" in p for p in _violations(a))
    for forbidden in ("financial_engine/orchestrator.py", "finco_core/inputs/_models.py",
                      "app/workbook/update_service.py", "app/persistence/workspace_repository.py"):
        a = _scenario()
        a["changed"] = a["changed"] + [forbidden]
        assert _violations(a), forbidden


def test_wf05_exception_fails_when_csrf_protection_is_removed_or_text_replacement_missing():
    a = _scenario()
    a["sites"] = set(WF05_CSRF_CALL_SITES) - {"app/v2/grid_router.py"}
    assert any("call sites differ" in p for p in _violations(a))
    a = _scenario()
    a["sites"] = set(WF05_CSRF_CALL_SITES) | {"app/v2/another.py"}
    assert _violations(a)
    a = _scenario()
    a["base"]["app/trust_readiness/registry.py"] = "base without the approved original text"
    assert any("not found exactly once" in p for p in _violations(a))


def test_wf05_exception_is_not_a_blanket_allowance_for_other_mixed_scope_changes():
    a = _scenario()
    a["changed"] = [p for p in a["changed"] if p != "docs/readiness/03_known_limitations_and_support_matrix.md"]
    assert any("missing" in p for p in _violations(a))
    # a Trust-only change with a different registry edit and no WF-05 files is not covered either
    a = _scenario(changed=["app/trust_readiness/registry.py", "docs/readiness/03_known_limitations_and_support_matrix.md"])
    assert _violations(a)


def test_wf05_allow_list_contains_no_engine_core_workbook_persistence_or_auth_paths():
    assert not [p for p in WF05_APPLICATION_PATHS if p.startswith(_NEVER_EXCEPTED)]
    app_v2 = {p for p in WF05_APPLICATION_PATHS if p.startswith("app/v2/")}
    assert app_v2 == {"app/v2/grid_router.py", "app/v2/input_grid_projection.py", "app/v2/router.py",
                      "app/v2/workspace_shell_projection.py"}
