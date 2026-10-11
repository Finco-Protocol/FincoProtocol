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


def test_scope_guard_this_work_touches_no_engine_input_writer_or_radar_code():
    try:
        from finance_integrity_governance import changed_paths_vs_main

        changed = changed_paths_vs_main()
        read_base = _git_base_reader()
    except Exception as exc:  # no git history or no origin/main in this checkout
        pytest.skip(f"cannot compute the diff against main: {exc}")
    if not any(p.startswith("app/trust_readiness/") for p in changed):
        pytest.skip("trust pack not part of this diff")
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
