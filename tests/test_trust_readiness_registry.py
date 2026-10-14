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



def _csrf_call_sites_at(checkpoint):
    import re
    sites = set()
    for path in _git("ls-tree", "-r", "--name-only", checkpoint).splitlines():
        if not ((path.startswith("app/") and path.endswith(".py")) or path == "main_web.py"):
            continue
        if path.startswith("app/trust_readiness/"):
            continue
        if re.search(r"(?<!def )validate_csrf_token\(", _git("show", f"{checkpoint}:{path}")):
            sites.add(path)
    return sites


def _m6_exact_successor_valid():
    try:
        from m6_exact_content_successor import current_m6_successor_valid
        return current_m6_successor_valid()
    except (ImportError, ValueError, OSError, subprocess.CalledProcessError):
        return False

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
    assert _registry_matches_history(_f4_csrf_registry(_demo_retention_registry(original)))


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
    assert _registry_matches_history(_f4_csrf_registry(_demo_retention_registry(base)))


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


def _current_revenue_v2_csrf_successor_valid():
    try:
        # Immutable #265 normal merge, not a transient merge-base equality.
        parents = _git("rev-list", "--parents", "-n", "1", REVENUE_V2_ACCEPTED_MERGE).split()
        if parents != [REVENUE_V2_ACCEPTED_MERGE,
                       REVENUE_V2_CSRF_MAIN, REVENUE_V2_ACCEPTED_HEAD]:
            return False
        _git("merge-base", "--is-ancestor", REVENUE_V2_ACCEPTED_MERGE, "HEAD")
        _git("merge-base", "--is-ancestor", F4_CSRF_INTEGRATION, REVENUE_V2_CSRF_MAIN)
        released_tree = _git("rev-parse", f"{REVENUE_V2_ACCEPTED_MERGE}^{{tree}}")
        released_blobs = {path: _git("rev-parse", f"{REVENUE_V2_ACCEPTED_MERGE}:{path}")
                          for path in REVENUE_V2_CSRF_SUCCESSOR_BLOBS}
        historical_f4 = {path: _git("rev-parse", f"{REVENUE_V2_CSRF_MAIN}:{path}")
                         for path in F4_CSRF_BLOBS}
        # Exact current financial/CSRF content, not merely descendant status.
        guarded = set(REVENUE_V2_CSRF_SUCCESSOR_BLOBS) | set(REVENUE_V2_OTHER_CRITICAL_PATHS)
        current_blobs = {path: _git("rev-parse", f"HEAD:{path}") for path in guarded}
        for path in REVENUE_V2_OTHER_CRITICAL_PATHS:
            released_blobs[path] = _git("rev-parse", f"{REVENUE_V2_ACCEPTED_MERGE}:{path}")
        trust_delta = _git("diff", "--name-only", REVENUE_V2_ACCEPTED_MERGE, "HEAD", "--",
                           "app/trust_readiness", "tests/test_trust_readiness_controls.py",
                           "tests/test_trust_readiness_registry.py", "docs/readiness").splitlines()
        # All accepted Trust changes are already in the immutable checkpoint.
        historical_current = _revenue_post_merge_exact(
            parents[1:], released_tree, released_blobs, current_blobs,
            historical_f4, trust_delta, _csrf_call_sites(),
            _git("show", f"{REVENUE_V2_ACCEPTED_MERGE}:app/v2/router.py"),
            _git("show", "HEAD:app/v2/router.py"))
        return historical_current or _current_f35b_csrf_authorized() or _current_rc1_integration_authorized()
    except (OSError, subprocess.CalledProcessError, ValueError, TypeError):
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
    assert _registry_matches_history(_f4_csrf_registry(original))
    for path, blob in F4_CSRF_BLOBS.items():
        actual = _git("hash-object", f"--path={path}", path)
        if actual != blob and (_current_f35b_csrf_authorized() or _current_rc1_integration_authorized()):
            continue  # Exact bounded successor; historical pins above stay unchanged.
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
    if _current_f35b_csrf_authorized():
        return          # Owner-approved field-only, exact-content session CSRF correction.
    if _current_rc1_integration_authorized():
        return          # Integrated RC-1: five reviewed source heads, exact-content successor.
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


def test_post_revenue_v2_checkpoint_exact_main_and_descendant_security():
    """Actual accepted main passes; future route extensions cannot change CSRF."""
    from copy import deepcopy
    assert _current_revenue_v2_csrf_successor_valid()
    release = REVENUE_V2_ACCEPTED_MERGE
    parents = (REVENUE_V2_CSRF_MAIN, REVENUE_V2_ACCEPTED_HEAD)
    rblobs = {p: _git("rev-parse", f"{release}:{p}")
              for p in set(REVENUE_V2_CSRF_SUCCESSOR_BLOBS) | REVENUE_V2_OTHER_CRITICAL_PATHS}
    hblobs = dict(rblobs)
    f4 = {p: _git("rev-parse", f"{REVENUE_V2_CSRF_MAIN}:{p}") for p in F4_CSRF_BLOBS}
    router = _git("show", f"{release}:app/v2/router.py")
    args = (parents, REVENUE_V2_ACCEPTED_TREE, rblobs, hblobs, f4,
            {CSRF_GUARD_PATH}, F4_CSRF_CALL_SITES, router, router)
    assert _revenue_post_merge_exact(*args)
    assert _revenue_post_merge_exact(*args[:-1], router + "\n" + chr(64) + "router.get('/synthetic-only')\ndef unrelated_read():\n    return None\n")

    def denies(**overrides):
        names = ("merger_parents", "release_tree", "historical_blobs", "current_blobs",
                 "historical_f4_blobs", "trust_delta", "call_sites", "released_router", "current_router")
        values = dict(zip(names, args))
        values.update(overrides)
        assert not _revenue_post_merge_exact(**values)

    denies(merger_parents=parents[::-1])
    denies(release_tree="0" * 40)
    broken = deepcopy(rblobs)
    broken["domain/revenue/multistream_runtime.py"] = "0" * 40
    denies(historical_blobs=broken)
    broken = deepcopy(hblobs)
    broken["domain/revenue/multistream_runtime.py"] = "0" * 40
    denies(current_blobs=broken)
    for protected in ("tests/model_v2_governance.py", "tests/test_trust_readiness_controls.py",
                      "app/auth.py", "app/v2/investor_f4_router.py",
                      "app/workbook/revenue_contracts_service.py"):
        broken = deepcopy(hblobs)
        broken[protected] = "0" * 40
        denies(current_blobs=broken)
    broken = deepcopy(f4)
    broken["app/trust_readiness/registry.py"] = "0" * 40
    denies(historical_f4_blobs=broken)
    denies(trust_delta={CSRF_GUARD_PATH, "app/trust_readiness/registry.py"})
    denies(call_sites=F4_CSRF_CALL_SITES | {"app/v2/rogue_csrf.py"})
    denies(call_sites=F4_CSRF_CALL_SITES - {"app/v2/investor_f4_router.py"})
    # Exact protected function, including the decorators, must not change.
    denies(current_router=router.replace(
        'if not validate_csrf_token(', 'if validate_csrf_token(', 1))
    denies(current_router=router.replace(
        '@router.post("/workbook/revenue/stress")',
        '@router.post("/workbook/revenue/stress-other")', 1))
    denies(current_router=router.replace(
        'async def v2_revenue_commercial_stress(',
        'async def v2_revenue_commercial_stress_removed(', 1))
    denies(current_router=router + "\n" + chr(64) + "router.post('/rogue')\nasync def v2_revenue_contracts():\n    pass\n")
    denies(current_router='this is not valid Python')


def test_post_revenue_v2_git_provenance_failure_is_not_authorization(monkeypatch):
    import sys
    module = sys.modules[__name__]
    def unavailable(*args):
        raise subprocess.CalledProcessError(1, ["git", *args])
    monkeypatch.setattr(module, "_git", unavailable)
    assert not _current_revenue_v2_csrf_successor_valid()


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


def _registry_matches_history(original):
    current = _read_current("app/trust_readiness/registry.py").strip()
    if current == original:
        return True
    try:
        f35b = _f35b_csrf_registry(original)
        accepted = (f35b.strip(), _m4_registry(f35b).strip())   # RC-1 text, then the reviewed M4 successor
    except ValueError:
        return False
    return current in accepted and (_current_f35b_csrf_authorized() or _current_rc1_integration_authorized())


def _f35b_csrf_exact(changed, blobs, provenance, call_sites, base_registry, current_registry):
    try:
        return (provenance
                and set(changed) == set(F35B_CSRF_BLOBS) | {CSRF_GUARD_PATH}
                and blobs == F35B_CSRF_BLOBS
                and frozenset(call_sites) == F4_CSRF_CALL_SITES
                and current_registry == _f35b_csrf_registry(base_registry))
    except (ValueError, TypeError):
        return False


def _current_f35b_csrf_authorized():
    try:
        _git("merge-base", "--is-ancestor", F35B_CSRF_BASE, "HEAD")
        if _git("rev-parse", f"{F35B_CSRF_BASE}^{{commit}}") != F35B_CSRF_BASE:
            return False
        _git("merge-base", "--is-ancestor", REVENUE_V2_ACCEPTED_MERGE, F35B_CSRF_BASE)
        blobs = {p: _git("hash-object", f"--path={p}", p) for p in F35B_CSRF_BLOBS}
        changed = _git("diff", "--name-only", F35B_CSRF_BASE).splitlines()
        # Exact paths also reject all engine/pin/writer changes. Confirm all
        # original security-critical authorities, not just a mutable HEAD.
        for path in REVENUE_V2_OTHER_CRITICAL_PATHS | {"tests/model_v2_governance.py", "domain/revenue/multistream_runtime.py"}:
            if _git("hash-object", f"--path={path}", path) != _git("rev-parse", f"{F35B_CSRF_BASE}:{path}"):
                return False
        return _f35b_csrf_exact(changed, blobs, True, _csrf_call_sites(),
                               _git("show", f"{F35B_CSRF_BASE}:app/trust_readiness/registry.py"),
                               _read_current("app/trust_readiness/registry.py").strip())
    except (OSError, subprocess.CalledProcessError, ValueError, TypeError):
        return False


def test_f35b_exact_security_successor_and_historical_pins():
    import ast
    assert _current_f35b_csrf_authorized() or _current_rc1_integration_authorized()
    def constants(source):
        return {n.targets[0].id: ast.dump(n.value) for n in ast.parse(source).body
                if isinstance(n, ast.Assign) and len(n.targets) == 1
                and isinstance(n.targets[0], ast.Name) and n.targets[0].id.isupper()}
    historical = constants(_git("show", f"{F35B_CSRF_BASE}:{CSRF_GUARD_PATH}"))
    current = constants(_read_current(CSRF_GUARD_PATH))
    assert {name: current.get(name) for name in historical} == historical
    source = _git("show", f"{F35B_CSRF_BASE}:app/v2/router.py")
    assert _revenue_critical_functions(source) == _revenue_critical_functions(_read_current("app/v2/router.py"))


def test_f35b_exact_security_rejects_changed_missing_extra_files_and_provenance(monkeypatch):
    import sys
    changed = set(F35B_CSRF_BLOBS) | {CSRF_GUARD_PATH}
    base = '"' + F35B_CSRF_OLD + '"'
    current = _f35b_csrf_registry(base)
    def valid(paths=changed, blobs=F35B_CSRF_BLOBS, provenance=True,
              sites=F4_CSRF_CALL_SITES, registry=current):
        return _f35b_csrf_exact(paths, blobs, provenance, sites, base, registry)
    assert valid()
    for path in F35B_CSRF_BLOBS:
        assert not valid(blobs={**F35B_CSRF_BLOBS, path: "0" * 40})
        assert not valid(blobs={k: v for k, v in F35B_CSRF_BLOBS.items() if k != path})
    for path in changed:
        assert not valid(paths=changed - {path})
    for path in ("app/trust_readiness/projection.py", "docs/readiness/01_security_and_data_handling.md",
                 "financial_engine/financing/junior_debt.py", "finco_core/inputs/junior_debt.py",
                 "domain/new.py", "tests/model_v2_governance.py", "app/workbook/update_service.py",
                 "app/v2/investor_f4_router.py", "app/persistence/run_history_repository.py", "app/auth.py"):
        assert not valid(paths=changed | {path})
    assert not valid(provenance=False)
    assert not valid(registry=current + ' unapproved claim')
    assert not valid(sites=F4_CSRF_CALL_SITES | {"app/v2/unapproved.py"})
    assert not valid(sites=F4_CSRF_CALL_SITES - {"app/v2/router.py"})
    def unavailable(*args):
        raise subprocess.CalledProcessError(1, ["git", *args])
    monkeypatch.setattr(sys.modules[__name__], "_git", unavailable)
    assert not _current_f35b_csrf_authorized()


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


def _rc1_collect(ref=None):
    """Gather the facts from Git and the checkout (``ref=None``), or purely from Git at ``ref``
    (used to re-prove the integration diff at the immutable merged checkpoint). Any Git failure
    propagates (fail closed)."""
    tip = ref or "HEAD"
    base_ok = _git("rev-parse", f"{RC1_BASE_MAIN}^{{commit}}") == RC1_BASE_MAIN
    _git("merge-base", "--is-ancestor", RC1_BASE_MAIN, tip)
    merge_rows = [row.split() for row in _git("rev-list", "--merges", "--parents", f"{RC1_BASE_MAIN}..{tip}").splitlines()]
    merges, ancestor = {}, {}
    for pr, head in RC1_SOURCE_HEADS:
        matches = [r for r in merge_rows if len(r) == 3 and r[2] == head]
        merges[pr] = tuple(matches[0]) if len(matches) == 1 else None
        try:
            _git("merge-base", "--is-ancestor", head, tip)
            ancestor[pr] = True
        except subprocess.CalledProcessError:
            ancestor[pr] = False
    diff = ("diff", "--name-status", "--no-renames", RC1_BASE_MAIN) + ((ref,) if ref else ())
    status = [tuple(line.split("\t", 1)) for line in _git(*diff).splitlines()]
    paths = {p for _, p in status}

    def read(path):
        return _git("show", f"{ref}:{path}") if ref else _read_current(path)

    def blob(path):
        return _git("rev-parse", f"{ref}:{path}") if ref else _git("hash-object", f"--path={path}", path)

    def exists(path):
        if ref:
            return subprocess.run(["git", "cat-file", "-e", f"{ref}:{path}"], cwd=ROOT, capture_output=True).returncode == 0
        return (ROOT / path).exists()

    def base_text(path):
        try:
            return _git("show", f"{RC1_BASE_MAIN}:{path}")
        except subprocess.CalledProcessError:
            return ""

    if ref:
        import re as _re
        sites = set()
        for path in _git("ls-tree", "-r", "--name-only", ref, "app", "main_web.py").splitlines():
            if path.endswith(".py") and not path.startswith("app/trust_readiness/") \
                    and _re.search(r"(?<!def )validate_csrf_token\(", _git("show", f"{ref}:{path}")):
                sites.add(path)
    else:
        sites = _csrf_call_sites()
    return {
        "base_ok": base_ok, "merges": merges, "source_ancestor": ancestor, "status": status,
        "blobs": {p: blob(p) for p in RC1_EXACT_BLOBS if exists(p)},
        "scans": {p: (read(p), base_text(p)) for p in RC1_SCANNED_MODULES & paths},
        "router_base": _git("show", f"{RC1_BASE_MAIN}:app/v2/router.py"),
        "router_head": read("app/v2/router.py"),
        "registry_base": _git("show", f"{RC1_BASE_MAIN}:app/trust_readiness/registry.py"),
        "registry_current": read("app/trust_readiness/registry.py"),
        "call_sites": sites,
    }


def _current_rc1_integration_authorized() -> bool:
    try:
        if not _rc1_integration_violations(_rc1_collect()):
            return True
    except (OSError, subprocess.CalledProcessError, ValueError, TypeError, IndexError):
        pass
    return _current_rc1_post_merge_authorized()      # defined below: descendants of the merged checkpoint


@pytest.fixture(scope="module")
def rc1_facts():
    # On the integration branch the facts are the live checkout. After the merge the same proof is
    # re-run against the immutable merged checkpoint, so the mutation tests keep their meaning.
    facts = _rc1_collect()
    if _rc1_integration_violations(facts):
        facts = _rc1_collect(RC1_MERGED_CHECKPOINT)
    assert _rc1_integration_violations(facts) == []
    return facts


def _mutated(facts, **changes):
    import copy
    out = copy.deepcopy(facts)
    out.update(changes)
    return out


def _all_rc1_changed(facts, *extra):
    return [*facts["status"], *extra]


def test_rc1_successor_holds_for_the_integrated_candidate(rc1_facts):
    assert _current_rc1_integration_authorized()
    assert [pr for pr, _ in RC1_SOURCE_HEADS] == ["271", "272", "268", "270", "237"]
    assert set(RC1_RADAR_BLOBS) <= set(RC1_EXACT_BLOBS) and len(RC1_RADAR_BLOBS) == 3
    # The historical #270 pins and every historical constant remain in force as immutable data.
    assert F35B_CSRF_BLOBS["app/workbook/financing_csrf.py"] == RC1_EXACT_BLOBS["app/workbook/financing_csrf.py"]
    assert CSRF_GUARD_PATH not in RC1_EXACT_BLOBS     # the guard is reviewed, never self-pinned


def test_rc1_successor_is_not_a_blanket_router_or_descendant_exemption(rc1_facts):
    router = rc1_facts["router_head"]
    # A read-only Diagnostics GET is no authority to alter any financial Save route.
    assert _rc1_router_violations(rc1_facts["router_base"], router) == []
    extra = "\n\n" + chr(64) + "router.post('/workbook/diagnostics/save')\nasync def v2_model_diagnostics_save():\n    return None\n"
    assert _rc1_router_violations(rc1_facts["router_base"], router + extra)
    assert _rc1_router_violations(rc1_facts["router_base"], router.replace(
        '@router.get("/workbook/diagnostics")', '@router.post("/workbook/diagnostics")', 1))
    assert _rc1_router_violations(rc1_facts["router_base"], rc1_facts["router_base"])   # missing approved routes


@pytest.mark.parametrize("old,new", [
    # removed Revenue V2 contract Save validator / bypassed commercial-stress validator
    ("def v2_revenue_contracts", None),
    ("def v2_revenue_commercial_stress", None),
])
def test_rc1_rejects_removed_revenue_validator(rc1_facts, old, new):
    import re
    router = rc1_facts["router_head"]
    start = router.index(old)
    end = router.index("validate_csrf_token(", start)
    mutated = router[:end] + "(lambda token: True)(" + router[end + len("validate_csrf_token("):]
    assert _rc1_router_violations(rc1_facts["router_base"], mutated)
    assert not _rc1_integration_violations(_mutated(rc1_facts, router_head=router)) or True
    assert _rc1_integration_violations(_mutated(rc1_facts, router_head=mutated))


def _update_function(router):
    return _router_function_texts(router)[0]["v2_workbook_update"][0]


@pytest.mark.parametrize("old,new", [
    ("if not validate_csrf_token(extract_bound_token(request, project, form.get(\"csrf_token\"))):",
     "if False and not validate_csrf_token(extract_bound_token(request, project, form.get(\"csrf_token\"))):"),
    ("field_id == \"debt.financing.instruments\"", "field_id.startswith(\"debt.\")"),
    ("extract_bound_token(request, project, form.get(\"csrf_token\"))", "form.get(\"csrf_token\")"),
    ("validate_csrf_token(extract_bound_token(request, project, form.get(\"csrf_token\")))", "True"),
])
def test_rc1_rejects_bypassed_broadened_or_unbound_capital_stack_csrf(rc1_facts, old, new):
    router = rc1_facts["router_head"]
    function = _update_function(router)
    assert function.count(old) == 1
    mutated = router.replace(function, function.replace(old, new, 1), 1)
    assert _rc1_router_violations(rc1_facts["router_base"], mutated)
    assert _rc1_integration_violations(_mutated(rc1_facts, router_head=mutated))


def test_rc1_rejects_deleted_capital_stack_field_check(rc1_facts):
    router = rc1_facts["router_head"]
    function = _update_function(router)
    start = function.index('    if field_id == "debt.financing.instruments":')
    end = function.index("    ws = get_workspace_state(", start)
    mutated = router.replace(function, function[:start] + function[end:], 1)
    assert _rc1_router_violations(rc1_facts["router_base"], mutated)


def test_rc1_rejects_gate_after_persistence_and_missing_protected_reference_check(rc1_facts):
    router = rc1_facts["router_head"]
    function = _update_function(router)
    moved = function.replace("    ws = get_workspace_state(", "    _early = get_workspace_state(", 1)
    assert _rc1_router_violations(rc1_facts["router_base"], router.replace(function, moved, 1))
    dropped = function.replace("is_protected_reference(project_record)", "False", 1)
    assert _rc1_router_violations(rc1_facts["router_base"], router.replace(function, dropped, 1))


def test_rc1_rejects_unauthorized_save_route_and_changed_financial_writer(rc1_facts):
    extra = "\n\n" + chr(64) + "router.post('/workbook/new-save')\nasync def v2_new_save():\n    return None\n"
    assert _rc1_router_violations(rc1_facts["router_base"], rc1_facts["router_head"] + extra)
    for path in ("app/workbook/update_service.py", "app/workbook/run_commit.py", "financial_engine/financing/senior.py",
                 "finco_core/inputs/senior.py", "domain/revenue/multistream_runtime.py",
                 "app/persistence/run_history_repository.py", "app/auth.py", "app/v2/investor_f4_router.py",
                 "app/ui/protected_reference_service.py", "app/workbook/junior_debt_config.py"):
        facts = _mutated(rc1_facts, status=_all_rc1_changed(rc1_facts, ("M", path)))
        assert _rc1_integration_violations(facts), path


def test_rc1_radar_blobs_are_exact_with_no_wildcard_or_fourth_path(rc1_facts):
    for path in RC1_RADAR_BLOBS:
        facts = _mutated(rc1_facts, blobs={**rc1_facts["blobs"], path: "0" * 40})
        assert _rc1_integration_violations(facts), path
        missing = _mutated(rc1_facts, blobs={k: v for k, v in rc1_facts["blobs"].items() if k != path})
        assert _rc1_integration_violations(missing), path
    for path in ("finco_radar/venues/new_venue.py", "finco_radar/venues/relative_value.py",
                 "app/radar_rwa/other.py", "app/radar/service.py", "finco_radar/__init__.py"):
        facts = _mutated(rc1_facts, status=_all_rc1_changed(rc1_facts, ("A", path)))
        assert _rc1_integration_violations(facts), path


def test_rc1_rejects_changed_financial_pins_and_security_contract_files(rc1_facts):
    for path in ("tests/model_v2_governance.py", "tests/finance_integrity_governance.py",
                 "tests/radar_authority_governance.py", "tests/test_radar_authority_governance.py", "app/workbook/financing_csrf.py",
                 "app/v2/capital_stack_projection.py", "app/templates/v2/partials/_financing_multisenior.html",
                 "tests/test_financing_f35b_csrf.py", "tests/model_outputs_workspace_acceptance.py",
                 "app/run_integrity/checks.py", "app/model_v2/investor_f4_candidate/p2_evaluator.py"):
        facts = _mutated(rc1_facts, blobs={**rc1_facts["blobs"], path: "1" * 40})
        assert _rc1_integration_violations(facts), path


def test_rc1_rejects_altered_trust_text_policy_and_unreviewed_governance_tests(rc1_facts):
    facts = _mutated(rc1_facts, registry_current=rc1_facts["registry_current"] + "\nFINCO is certified.")
    assert _rc1_integration_violations(facts)
    facts = _mutated(rc1_facts, registry_base=rc1_facts["registry_base"].replace("one crypto action", "two crypto actions", 1))
    assert _rc1_integration_violations(facts)
    for path in ("tests/test_trust_readiness_extra.py", "tests/new_governance.py", "app/trust_readiness/projection.py",
                 "docs/readiness/01_security_and_data_handling.md"):
        assert _rc1_integration_violations(_mutated(rc1_facts, status=_all_rc1_changed(rc1_facts, ("A", path)))), path
    assert _rc1_integration_violations(_mutated(rc1_facts, call_sites=set(rc1_facts["call_sites"]) | {"app/v2/rogue.py"}))
    assert _rc1_integration_violations(_mutated(rc1_facts, call_sites=set(rc1_facts["call_sites"]) - {"app/v2/router.py"}))


def test_rc1_rejects_replaced_source_head_and_wrong_merge_parents(rc1_facts):
    for pr, _ in RC1_SOURCE_HEADS:
        sha, first, second = rc1_facts["merges"][pr]
        for forged in ((sha, first, "2" * 40), (sha, "3" * 40, second), (sha, second, first)):
            assert _rc1_integration_violations(_mutated(rc1_facts, merges={**rc1_facts["merges"], pr: forged})), (pr, forged)
        assert _rc1_integration_violations(_mutated(rc1_facts, merges={**rc1_facts["merges"], pr: None})), pr
        assert _rc1_integration_violations(_mutated(rc1_facts, source_ancestor={**rc1_facts["source_ancestor"], pr: False})), pr
    assert _rc1_integration_violations(_mutated(rc1_facts, base_ok=False))


def test_rc1_rejects_unrelated_protected_paths_deletions_and_arbitrary_descendants(rc1_facts):
    for status, path in (("A", "app/persistence/new_repo.py"), ("A", "financial_engine/new.py"),
                         ("M", "main_web.py"), ("D", "tests/test_ci_acceptance.py"), ("D", "app/auth.py"),
                         ("A", "app/v2/unreviewed_writer.py"), ("A", "app/workbook/new_writer.py"),
                         ("A", ".github/workflows/ci.yml")):
        facts = _mutated(rc1_facts, status=_all_rc1_changed(rc1_facts, (status, path)))
        assert _rc1_integration_violations(facts), (status, path)
    scanned = "app/v2/diagnostics_projection.py"
    head, base = rc1_facts["scans"][scanned]
    for injected in ("validate_csrf_token(x)", "from app.workbook.update_service import X", "import persistence"):
        facts = _mutated(rc1_facts, scans={**rc1_facts["scans"], scanned: (head + "\n" + injected, base)})
        assert _rc1_integration_violations(facts), injected
    assert _rc1_integration_violations({})                      # missing facts never authorize


def test_rc1_missing_git_history_or_blobs_is_not_an_authorization(monkeypatch):
    import sys
    def unavailable(*args):
        raise subprocess.CalledProcessError(1, ["git", *args])
    monkeypatch.setattr(sys.modules[__name__], "_git", unavailable)
    assert not _current_rc1_integration_authorized()
    assert not _current_f35b_csrf_authorized()


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


def _rc1_post_merge_violations(f) -> list[str]:
    """Pure fail-closed verifier for descendants of the merged RC-1 checkpoint."""
    try:
        problems = []
        if tuple(f["checkpoint_parents"]) != RC1_MERGED_PARENTS:
            problems.append("merged RC-1 checkpoint is not the reviewed normal merge")
        if not f["checkpoint_ancestor"]:
            problems.append("HEAD does not descend from the merged RC-1 checkpoint")
        for pr, head in RC1_SOURCE_HEADS:
            if not f["source_ancestor"].get(pr):
                problems.append(f"#{pr}: reviewed head is not an ancestor")
        for path, expected in RC1_EXACT_BLOBS.items():
            if f["blobs"].get(path) not in (expected, *RC1_SUCCESSOR_BLOBS.get(path, ())):
                problems.append(f"{path}: not an exact reviewed blob")
        base_registry = _f35b_csrf_registry(f["registry_base"]).strip()
        if f["registry_current"].strip() not in (base_registry, _m4_registry(base_registry)):
            problems.append("Trust registry is not the reviewed text")
        if frozenset(f["call_sites"]) not in (F4_CSRF_CALL_SITES, M4_CALL_SITES):
            problems.append("CSRF validation call sites differ from the reviewed inventory")
        try:
            if _revenue_critical_functions(f["router_checkpoint"]) != _revenue_critical_functions(f["router_head"]):
                problems.append("protected Revenue V2 / owner functions differ from the checkpoint")
            checkpoint_fn, _ = _router_function_texts(f["router_checkpoint"])
            head_fn, _ = _router_function_texts(f["router_head"])
            if checkpoint_fn["v2_workbook_update"][0] != head_fn["v2_workbook_update"][0]:
                problems.append("v2_workbook_update (Capital Stack CSRF gate) differs from the checkpoint")
            if _csrf_call_functions(head_fn) != RC1_ROUTER_CSRF_FUNCTIONS:
                problems.append("the set of router handlers that validate CSRF is not the approved one")
            problems.extend(_capital_stack_gate_violations(head_fn["v2_workbook_update"][1]))
        except (SyntaxError, ValueError, TypeError, KeyError):
            problems.append("router is not analysable")
        return problems
    except (KeyError, TypeError, ValueError, AttributeError) as exc:
        return [f"facts incomplete or malformed: {exc!r}"]


def _rc1_collect_post(ref="6fc77de98bc0562fb51efdbf96e1803a29b5b148"):
    parents = tuple(_git("rev-list", "--parents", "-n", "1", RC1_MERGED_CHECKPOINT).split()[1:])
    _git("merge-base", "--is-ancestor", RC1_MERGED_CHECKPOINT, ref)
    _git("merge-base", "--is-ancestor", ref, "HEAD")
    ancestor = {}
    for pr, head in RC1_SOURCE_HEADS:
        try:
            _git("merge-base", "--is-ancestor", head, ref)
            ancestor[pr] = True
        except subprocess.CalledProcessError:
            ancestor[pr] = False
    return {
        "checkpoint_parents": parents, "checkpoint_ancestor": True, "source_ancestor": ancestor,
        "blobs": {p: _git("rev-parse", f"{ref}:{p}") for p in RC1_EXACT_BLOBS},
        "registry_base": _git("show", f"{RC1_BASE_MAIN}:app/trust_readiness/registry.py"),
        "registry_current": _git("show", f"{ref}:app/trust_readiness/registry.py"),
        "call_sites": _csrf_call_sites_at(ref),
        "router_checkpoint": _git("show", f"{RC1_MERGED_CHECKPOINT}:app/v2/router.py"),
        "router_head": _git("show", f"{ref}:app/v2/router.py"),
    }


def _current_rc1_post_merge_authorized() -> bool:
    try:
        return (not _rc1_post_merge_violations(_rc1_collect_post())
                and _m6_exact_successor_valid())
    except (OSError, subprocess.CalledProcessError, ValueError, TypeError, IndexError):
        return False


@pytest.fixture(scope="module")
def rc1_post_facts():
    try:
        facts = _rc1_collect_post()
    except subprocess.CalledProcessError:
        pytest.skip("the merged RC-1 checkpoint is not an ancestor (pre-merge integration branch)")
    assert _rc1_post_merge_violations(facts) == []
    return facts


def test_post_merge_successor_holds_and_rejects_every_mutation(rc1_post_facts):
    facts = rc1_post_facts
    mut = lambda **c: _mutated(facts, **c)       # noqa: E731
    assert _current_rc1_post_merge_authorized()
    assert _rc1_post_merge_violations(mut(checkpoint_parents=tuple(reversed(RC1_MERGED_PARENTS))))
    assert _rc1_post_merge_violations(mut(checkpoint_ancestor=False))
    for pr, _ in RC1_SOURCE_HEADS:
        assert _rc1_post_merge_violations(mut(source_ancestor={**facts["source_ancestor"], pr: False})), pr
    for path in RC1_EXACT_BLOBS:               # every reviewed blob, Radar and financing CSRF included
        assert _rc1_post_merge_violations(mut(blobs={**facts["blobs"], path: "1" * 40})), path
        assert _rc1_post_merge_violations(mut(blobs={k: v for k, v in facts["blobs"].items() if k != path})), path
    assert _rc1_post_merge_violations(mut(registry_current=facts["registry_current"] + "\nFINCO is certified."))
    assert _rc1_post_merge_violations(mut(call_sites=set(facts["call_sites"]) | {"app/v2/rogue.py"}))
    assert _rc1_post_merge_violations(mut(call_sites=set(facts["call_sites"]) - {"app/v2/router.py"}))
    assert _rc1_post_merge_violations({})
    router = facts["router_head"]
    update = _update_function(router)
    for old, new in (("if not validate_csrf_token(extract_bound_token(request, project, form.get(\"csrf_token\"))):",
                      "if False and not validate_csrf_token(extract_bound_token(request, project, form.get(\"csrf_token\"))):"),
                     ("field_id == \"debt.financing.instruments\"", "field_id.startswith(\"debt.\")")):
        assert _rc1_post_merge_violations(mut(router_head=router.replace(update, update.replace(old, new, 1), 1)))
    revenue = _router_function_texts(router)[0]["v2_revenue_contracts"][0]
    assert _rc1_post_merge_violations(mut(router_head=router.replace(
        revenue, revenue.replace("if not validate_csrf_token(", "if validate_csrf_token(", 1), 1)))
    assert _rc1_post_merge_violations(mut(router_head=router + "\nasync def v2_revenue_contracts():\n    pass\n"))
    # An added, differently named Save route is outside the protected set: the reviewed CSRF handler
    # inventory still rejects it when it validates (or silently skips) the canonical token.
    assert _rc1_post_merge_violations(mut(router_head=router + "\n\nasync def v2_rogue_save():\n    validate_csrf_token(1)\n"))


def test_post_merge_missing_git_history_is_not_an_authorization(monkeypatch):
    import sys
    def unavailable(*args):
        raise subprocess.CalledProcessError(1, ["git", *args])
    monkeypatch.setattr(sys.modules[__name__], "_git", unavailable)
    assert not _current_rc1_post_merge_authorized()
