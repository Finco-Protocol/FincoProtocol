"""CI V5 evaluator, schema V2 - SHADOW (never a required check in this PR; V4 stays authoritative).

What it proves, from Git OBJECTS only (never the working tree), is an INTEGRITY statement:

    guarded(HEAD) == guarded(BASE TIP) (+) declared changes            (base-relative delta, schema V2)

where ``guarded`` is ALL_TRACKED: every tracked path (add / modify / delete / rename = delete+add / mode / symlink / gitlink), minus the explicit exempt
list (the delta file itself and literal V4-bound manifests, which are reported, never invisible). Integrity is NOT authorization: the verdict carries
both, separately, and this tool never turns "integrity pass" into "approved to merge" (``authorization`` is ``NOT_EVALUATED`` here).

Trust model
  * The EPOCH is a milestone CHECKPOINT (owner-approved, ``docs/ci_v5/epoch.json``). It is trusted only when read from the trusted BASE. It anchors
    history (its pinned commit must be accepted history of the base and its snapshot must be a truthful ALL_TRACKED inventory of that commit); it is
    NOT required to equal the base inventory on every PR (that was the V1 ``EPOCH_STALE_AT_BASE`` dead end).
  * The BASE must be the current tip of the trusted protected ref (``trusted_ref_tip``), and the head must contain it (merge-tree identity). A
    caller-chosen merge-base or fork is ``UNKNOWN``, never authoritative.
  * The semantic registry and the class map come from trusted CODE (``POLICY`` below, read from the trusted base with this file), not from the epoch.
  * ``GIT_NO_REPLACE_OBJECTS=1``, a scrubbed environment, argv-only Git, 40-hex refs only, nothing evaluated by a shell, nothing cached across calls.
  * An integrity PASS needs: trusted tool source + trusted epoch + verified base tip + no failure + no unknown. Everything else is FAIL or UNKNOWN.

Stdlib only.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import time
import unicodedata
from fnmatch import fnmatchcase

EPOCH_SCHEMA_V1 = "FINCO_CI_V5_EPOCH_V1"                 # legacy narrow-guard document: readable, never a FULL guard
EPOCH_SCHEMA = "FINCO_CI_V5_EPOCH_V2"
DELTA_SCHEMA = "FINCO_CI_V5_DELTA_V2"
VERDICT_SCHEMA = "FINCO_CI_V5_VERDICT_V2"
TRUSTED_EPOCH_PATH = "docs/ci_v5/epoch.json"           # trust anchor: read from the trusted BASE only
CANDIDATE_EPOCH_PATH = "docs/ci_v5/epoch.candidate.json"
DELTA_PATH = "docs/ci_v5/delta.json"
MAX_DELTA = 5000
MODES = ("100644", "100755")                            # 120000 (symlink) and 160000 (gitlink) are never reviewable
OPS = ("add", "modify", "delete")
SHA40 = re.compile(r"[0-9a-f]{40}")
SHA256 = re.compile(r"[0-9a-f]{64}")
SAFE_PATH = re.compile(r"[A-Za-z0-9_@+.\-]+(?:/[A-Za-z0-9_@+.\-]+)*")
EPOCH_KEYS_V1 = {"schema", "epoch_id", "base_commit", "base_tree", "guard_prefixes", "entries", "entries_sha256", "atlas"}
EPOCH_KEYS = {"schema", "epoch_id", "base_commit", "base_tree", "guard", "policy_version", "full_run", "entries", "entries_sha256", "atlas"}
DELTA_KEYS = {"schema", "base_sha", "base_tree", "result_inventory_sha256", "changes"}
CHANGE_KEYS = {"op", "path", "blob", "mode", "class"}
# Files whose presence in an IGNORED or untracked position can execute or be served: never acceptable anywhere in the worktree.
DANGEROUS_SUFFIXES = (".py", ".pyc", ".pyo", ".pyd", ".so", ".pth", ".html", ".htm", ".js", ".mjs", ".cjs", ".css", ".wasm", ".sh", ".yml", ".yaml")
DANGEROUS_NAMES = ("conftest.py", "sitecustomize.py", "usercustomize.py", "pytest.ini", "setup.cfg", "tox.ini", ".env", "pyvenv.cfg")
TRUSTED_TOOL_SOURCES = ("TRUSTED_BASE",)


class POLICY:
    """CI V5 trusted POLICY (class map S/P/X/D + SEMANTIC registry): trusted CODE inside the evaluator, read from the trusted BASE together with it; never from
    the PR head and never from the epoch document (editing an epoch ``atlas`` cannot add, remove or relabel a semantic path).

    Classes (strictest first). A class changes the REVIEW a path needs; it never changes whether a path is evaluated (ALL_TRACKED is evaluated):
      S  semantic / V4-owned - V5 proves bytes only; any add/modify/delete is never better than ``UNKNOWN`` (deferred to the independent V4 checks).
      P  protected runtime or CI-adjacent source: declared + owner approval.
      X  executable or served material outside P: declared + owner approval.
      D  prose and evidence: declared (generated); lighter review is the owner's choice.
    A path that matches no rule is ``S`` / ``UNCLASSIFIED`` (new root files, new top-level folders): strictest by default, no prefix shortcut. An EMPTY or
    unreadable registry is ``UNKNOWN`` for every path (``registry_ok`` is False); it is never read as "no semantic paths".

    The delta file is always exempt from the guard (it would have to contain its own hash). ``V4_BOUND_EXEMPT`` lists literal V4 exact-source manifests that PIN
    the delta bytes and therefore cannot be listed inside it (a hash cycle): exempt from the DELTA but never invisible - a change to one is reported and forces
    ``UNKNOWN`` (the exact V4 pin of those bytes is the judge). A new entry needs a reviewed edit of this trusted code.
    """

    POLICY_VERSION = "FINCO_CI_V5_POLICY_2"
    CLASSES = ("S", "P", "X", "D")                      # strictest first
    V4_BOUND_EXEMPT = ("docs/ci_v5/hardening_2b/SOURCE_SUCCESSOR.json", "docs/ci_v5/gate_3/SOURCE_SUCCESSOR.json")
    # --- V5-3 gate policy (trusted CODE; changing any of it is a reviewed edit, never data a PR can carry) ---------------------------------------------
    GATE_CHECK_NAME = "V5 gate (trusted base)"          # the job name of the pull_request_target gate: the string the owner adds to the required checks
    # The six established V4 checks that must stay required and, for DEFERRED_TO_V4_VERIFIED, must be green at the EXACT head (names = check-run names).
    V4_REQUIRED_CHECKS = ("CI V4 gate", "mandatory-browser-evidence", "rate-contract-native-and-browser", "authoritative-history", "dependency-audit",
                          "compile-and-safety")
    # Independent approvers (GitHub logins) whose APPROVED review at the exact head counts. EMPTY until the owner names a distinct identity in a reviewed
    # edit: with no approver configured authorization is ``AUTHORIZATION_BLOCKED``, never a default-allow and never the PR author.
    APPROVERS = ()
    # Owner-signed approval (option B): (principal, "ssh-ed25519 AAAA...") public keys. The owner signs the approval commit with a key the agent never holds.
    ALLOWED_SIGNERS = ()
    REVIEW_ASSOCIATIONS = ("OWNER", "MEMBER", "COLLABORATOR")
    # The V4 mutation-security inventory (``tests.model_mutation_security_successor.BLOBS``) as of the accepted baseline; ``tests/test_ci_v5_foundation.py``
    # asserts this tuple still covers the CURRENT V4 inventory (drift = test failure), so a V4 addition can never silently fall out of the registry.
    SEMANTIC_LITERALS = (
        'app/library/router.py',
        'app/templates/v2/partials/_financing_bankability.html',
        'app/templates/v2/partials/_v2_export_controls.html',
        'app/templates/v2/partials/field_editor.html',
        'app/templates/v2/partials/sheet_capex.html',
        'app/templates/v2/partials/sheet_inputs.html',
        'app/templates/v2/partials/sheet_opex.html',
        'app/templates/v2/partials/sheet_project_setup.html',
        'app/templates/v2/partials/sheet_revenue.html',
        'app/templates/v2/partials/sheet_scenarios.html',
        'app/templates/v2/partials/sheet_senior_debt.html',
        'app/templates/v2/partials/sheet_tax.html',
        'app/templates/v2/partials/sheet_trust.html',
        'app/v2/capex_router.py',
        'app/v2/grid_router.py',
        'app/v2/opex_router.py',
        'app/v2/post_run_ui.py',
        'app/v2/react_poc_router.py',
        'app/v2/react_workspace_router.py',
        'app/v2/router.py',
        'app/workbook/financing_csrf.py',
        'app/workbook/mutation_csrf.py',
        'frontend/src/app/FinancialResults.tsx',
        'frontend/src/app/WorkspaceView.tsx',
        'frontend/src/app/types.ts',
        'frontend/src/app/workflow/ModelExportView.tsx',
        'frontend/src/app/workflow/ScenarioKpiComparison.tsx',
        'frontend/src/app/workflow/ScenarioWorkspace.tsx',
        'frontend/src/app/workflow/workflowApi.ts',
        'frontend/src/app/workflow/workflowShared.tsx',
        'frontend/src/styles/rc-react-mvp.css',
        'static/js/cost_staging.js',
        'static/react/finco-react.css',
        'static/react/finco-react.js',
        'tests/insights_browser_fixture.py',
        'tests/model_mutation_cookie_policy_acceptance.py',
        'tests/model_mutation_csrf.py',
        'tests/model_react_mvp_acceptance.py',
        'tests/model_react_wf2_browser_acceptance.py',
        'tests/run_clone_csrf.py',
        'tests/test_capex_numbering_contingency.py',
        'tests/test_correction_a_required_gates.py',
        'tests/test_cost_batch_save_v1.py',
        'tests/test_cost_workspace_consistency_v1.py',
        'tests/test_cost_workspace_parity_v1.py',
        'tests/test_data_center_correction_a.py',
        'tests/test_developer_economics_persistence_v1.py',
        'tests/test_ev_charging_acceptance.py',
        'tests/test_ev_charging_efficiency_authority.py',
        'tests/test_ev_charging_range_parity.py',
        'tests/test_f0_senior_maturity_integrity.py',
        'tests/test_financing_f35b_csrf.py',
        'tests/test_financing_f38_trace.py',
        'tests/test_financing_f3_junior_workspace.py',
        'tests/test_gf_f05_scenario_freshness.py',
        'tests/test_golden_flow_correction_b.py',
        'tests/test_investor_f4_workspace.py',
        'tests/test_model_credit_decision_v3_real_runs.py',
        'tests/test_model_credit_decision_v3_scenarios.py',
        'tests/test_model_decision_workspace_v2.py',
        'tests/test_model_diagnostics_v2_real_runs.py',
        'tests/test_model_financing_bankability.py',
        'tests/test_model_financing_f2.py',
        'tests/test_model_financing_f3_workspace.py',
        'tests/test_model_hybrid_inputs_grid_f3_negative.py',
        'tests/test_model_hybrid_inputs_grid_routes.py',
        'tests/test_model_import_excel_migration_journey.py',
        'tests/test_model_import_excel_migration_security.py',
        'tests/test_model_insight_q3_route.py',
        'tests/test_model_insight_q3_scenario_identity.py',
        'tests/test_model_mutation_request_security_v1.py',
        'tests/test_model_outputs_workspace.py',
        'tests/test_model_q4_whatif.py',
        'tests/test_model_react_correction_b_v1.py',
        'tests/test_model_react_insights_v1.py',
        'tests/test_model_react_outcome_integrity_v1.py',
        'tests/test_model_react_poc_v1.py',
        'tests/test_model_react_rc_ux_b_v1.py',
        'tests/test_model_react_ux02_workspace_v1.py',
        'tests/test_model_react_ux07_v1.py',
        'tests/test_model_react_wf2_financial_authority_v1.py',
        'tests/test_model_react_wf2_projections_v1.py',
        'tests/test_model_v7_diagnostics_routes.py',
        'tests/test_model_workspace_consolidation_browser.py',
        'tests/test_portfolio_monitoring_real_runs.py',
        'tests/test_post_run_request_context.py',
        'tests/test_ppa01_contractual_workspace.py',
        'tests/test_ppa01_rounding_workspace.py',
        'tests/test_ppa01_save_scenario_run_chain.py',
        'tests/test_pr161_contingency_identity.py',
        'tests/test_rc2_integration_acceptance.py',
        'tests/test_rc5_s7_effective_input_evidence.py',
        'tests/test_rc5_scenario_effective_input_safety.py',
        'tests/test_rc7b_quarterly_production_acceptance.py',
        'tests/test_rc7b_quarterly_run_workspace.py',
        'tests/test_react_mvp_rc_sec.py',
        'tests/test_revenue_v2_advanced_route.py',
        'tests/test_revenue_v3_workspace.py',
        'tests/test_sc34_project_identity.py',
        'tests/test_sc34_run_failure_explanation.py',
        'tests/test_sc34_run_status_dimensions.py',
        'tests/test_sc34_statements_drilldown.py',
        'tests/test_scenario_tariff_authority_v2.py',
        'tests/test_staging_acceptance_a.py',
        'tests/test_u2_1_v2_export.py',
        'tests/test_u2_2_returns_surface.py',
        'tests/test_v2_scenario_overrides.py',
        'tests/test_v9p2a_odr_run_commit_safety.py',
        'tests/test_wf05_wf07_integration.py',
        'tests/test_wf07_revenue_workspace.py',
        'tests/test_workflow_c_statements_analytics_trace.py',
        'tests/wfa_support.py',
    )
    SEMANTIC_PATTERNS = (
        ".github/*",                                      # workflows, CODEOWNERS, dependabot: V5 cannot judge CI semantics
        "pytest.ini", "tests/conftest.py", "*conftest.py", "tests/browser/*",
        "tests/*_scope.py", "tests/fin_v2_cohorts.py", "tests/*successor*", "tests/*_scope_*",
        "tests/*mutation*", "tests/*csrf*", "tests/*f01*", "tests/*finval*", "tests/*tenan*", "tests/*permission*", "tests/*_cas*", "tests/*save*",
        "tests/*browser*", "tests/*acceptance*", "tests/*native*", "tests/*cohort*", "tests/*governance*", "tests/*bootstrap*",
        "docs/ci_v4/*", "docs/*SOURCE_SUCCESSOR*.json", "docs/*EXACT_SOURCE*.json", "docs/ci_v5/bootstrap/*", "docs/ci_v5/hardening_2b/*", "docs/ci_v5/gate_3/*",
        "tools/ci_*", "tools/*gate*", "tools/*scan*", "tools/governance*",
        "app/*router*", "app/*routes*", "app/*route.py", "app/*csrf*", "app/*auth*", "app/*session*", "app/*tenan*", "app/*permission*",
        "app/*mutation*", "app/*save*", "app/*middleware*", "app/*security*",
        "frontend/src/*workflow*", "static/js/*save*",
    )
    PROTECTED_PATTERNS = (
        "app/*", "financial_engine/*", "finco_core/*", "domain/*", "main_web.py", "main_api.py", "main_mcp.py", "_warm.py",
        "requirements*.txt", "constraints.txt", "pyproject.toml", ".gitignore", ".gitattributes", ".env.example", "tools/*",
        "finco_radar/*", "finco_yield/*", "finco_protocol/*", "finco_app/*", "tax_reference_registry/*",
    )
    EXECUTABLE_PATTERNS = ("tests/*", "static/*", "deploy/*", "frontend/*", "scripts/*", "utils/*", "research/*", "examples/*", "OPUS_V1_REVIEW/*")
    PROSE_PATTERNS = ("*.md", "docs/*", "LICENSE", "LICENSE.*")

    @staticmethod
    def _matches(path, patterns):
        return any(fnmatchcase(path, pat) for pat in patterns)

    @staticmethod
    def registry_ok():
        """False when the semantic registry is empty or malformed: every path is then ``S`` (UNKNOWN), never 'no semantic paths'."""
        lit, pat = POLICY.SEMANTIC_LITERALS, POLICY.SEMANTIC_PATTERNS
        return (isinstance(lit, tuple) and len(lit) >= 100 and len(set(lit)) == len(lit)
                and isinstance(pat, tuple) and len(pat) > 0 and all(isinstance(s, str) and s for s in pat))

    @staticmethod
    def classify(path):
        """(class, reason). First match wins in the order S, P, X, D; no match is ``S`` / ``UNCLASSIFIED``."""
        if not POLICY.registry_ok():
            return "S", "SEMANTIC_REGISTRY_UNAVAILABLE"
        if path in POLICY.SEMANTIC_LITERALS:
            return "S", "V4_MUTATION_INVENTORY"
        if POLICY._matches(path, POLICY.SEMANTIC_PATTERNS):
            return "S", "SEMANTIC_PATTERN"
        if POLICY._matches(path, POLICY.PROSE_PATTERNS) and not path.startswith(("app/", "financial_engine/", "finco_core/", "domain/")):
            return "D", "PROSE"
        if POLICY._matches(path, POLICY.PROTECTED_PATTERNS):
            return "P", "PROTECTED"
        if POLICY._matches(path, POLICY.EXECUTABLE_PATTERNS):
            return "X", "EXECUTABLE_OR_SERVED"
        return "S", "UNCLASSIFIED"

    @staticmethod
    def is_exempt(path):
        return path == DELTA_PATH or path in POLICY.V4_BOUND_EXEMPT

    @staticmethod
    def touches_existing_test(op, path):
        """Modifying or deleting an EXISTING file under ``tests/`` is a potential neutering / retirement (replaced body, removed assertion, skip marker, deleted
        module): V5 proves bytes only, so it is never better than UNKNOWN. ADDING a new test module is not (B5 reports new skip/xfail markers separately)."""
        return op in ("modify", "delete") and path.startswith("tests/")


class GitError(RuntimeError):
    pass


def sanitized_env():
    """A scrubbed environment: no inherited ``GIT_*`` (GIT_DIR, GIT_WORK_TREE, GIT_INDEX_FILE, GIT_OBJECT_DIRECTORY, GIT_ALTERNATE_OBJECT_DIRECTORIES,
    GIT_NAMESPACE, GIT_CONFIG_*, GIT_EXEC_PATH ...), no user/system config, replace refs disabled. Only PATH/locale/temp survive."""
    env = {k: v for k, v in os.environ.items() if k in ("PATH", "LANG", "LC_ALL", "SYSTEMROOT", "TMPDIR", "TEMP", "TMP")}
    env.update(GIT_NO_REPLACE_OBJECTS="1", GIT_TERMINAL_PROMPT="0", GIT_OPTIONAL_LOCKS="0", GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull,
               GIT_ATTR_NOSYSTEM="1", GIT_CONFIG_COUNT="0", GIT_PAGER="cat", GIT_ASKPASS="true")
    return env


class Git:
    """Argv-only Git runner that counts its child processes (reported, never hidden). Replace objects are disabled twice (flag + variable)."""

    def __init__(self, root):
        self.root = str(root)
        self.children = 0

    def run(self, *args, input=None):
        self.children += 1
        p = subprocess.run(["git", "--no-replace-objects", "-c", "core.quotepath=false", "-c", "core.fsmonitor=false", "-c", "core.untrackedCache=false", *args],
                           cwd=self.root, input=input, capture_output=True, env=sanitized_env(), timeout=300)
        if p.returncode != 0:
            raise GitError("git %s failed (%d)" % (args[0], p.returncode))
        return p.stdout


def canonical(obj):
    """The ONLY accepted serialisation: no reordered, extra or hidden byte survives a load."""
    return (json.dumps(obj, indent=1, sort_keys=True) + "\n").encode()


def sha256_hex(raw):
    return hashlib.sha256(raw).hexdigest()


def blob_id(raw):
    return hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()


def entries_digest(entries):
    return hashlib.sha256("".join(e + "\n" for e in entries).encode()).hexdigest()


def entry_str(path, blob, mode):
    return "%s %s\t%s" % (mode, blob, path)


def parse_entry(text):
    meta, sep, path = text.partition("\t")
    parts = meta.split(" ")
    if not sep or len(parts) != 2 or parts[0] not in MODES or not SHA40.fullmatch(parts[1]) or not _path_ok(path):
        raise ValueError("bad entry")
    return path, parts[1], parts[0]


def _path_ok(path):
    return (isinstance(path, str) and SAFE_PATH.fullmatch(path) is not None and not any(s in (".", "..") for s in path.split("/"))
            and unicodedata.normalize("NFC", path) == path)


def is_exempt(path):
    """Delta-exempt paths (the delta itself + literal V4-bound manifests). Without a readable policy only the delta itself is exempt."""
    return path == DELTA_PATH or (POLICY is not None and POLICY.is_exempt(path))


def is_guarded(path):
    """ALL_TRACKED: every tracked path except the delta/V4-bound exempt files and the trust anchor (handled as a promotion transition)."""
    return path != TRUSTED_EPOCH_PATH and not is_exempt(path)


def classify(path):
    return POLICY.classify(path) if POLICY is not None else ("S", "SEMANTIC_REGISTRY_UNAVAILABLE")


def read_inventory(git, sha):
    """{path: (mode, blob-or-commit oid)} of a whole commit tree, ONE batched ``ls-tree`` (no per-file process)."""
    inventory = {}
    for rec in git.run("ls-tree", "-r", "-z", "--full-tree", sha).split(b"\0"):
        if rec:
            meta, _, name = rec.partition(b"\t")
            mode, _kind, oid = meta.decode().split()
            inventory[name.decode("utf-8", "surrogateescape")] = (mode, oid)
    return inventory


def guarded_inventory(inv):
    return {p: v for p, v in inv.items() if is_guarded(p)}


def inventory_digest(inv):
    """Digest of the guarded inventory (``mode blob<TAB>path`` lines, sorted by path). The delta file and the trust anchor are not part of it."""
    return entries_digest(sorted("%s %s\t%s" % (m, o, p) for p, (m, o) in inv.items()))


def unsafe_paths(inv):
    """Every evaluated path must be ASCII-safe, NFC and free of case-fold collisions (also between DIRECTORY components, e.g. ``App/`` vs ``app/``)."""
    bad, spellings = [], {}
    for p in inv:
        if not _path_ok(p):
            bad.append(("UNSAFE_PATH", p))
        parts = p.split("/")
        for i in range(1, len(parts) + 1):
            prefix = "/".join(parts[:i])
            seen = spellings.setdefault(prefix.casefold(), prefix)
            if seen != prefix:
                bad.append(("CASEFOLD_COLLISION", "%s vs %s" % (prefix, seen)))
    return bad


# ------------------------------------------------------------------------------------------------------------- epoch / delta documents
def make_epoch(git, commit, epoch_id="", atlas=(), full_run=None):
    """CANDIDATE epoch V2 of ``commit``: the ALL_TRACKED inventory (minus exempt files and the anchor). Pure function of Git objects."""
    inv = read_inventory(git, commit)
    tree = git.run("rev-parse", commit + "^{tree}").decode().strip()
    entries = sorted(entry_str(p, inv[p][1], inv[p][0]) for p in inv if is_guarded(p))
    for e in entries:
        parse_entry(e)                                          # a symlink / gitlink / unsafe path must stop generation, not be recorded
    return {"schema": EPOCH_SCHEMA, "epoch_id": epoch_id, "base_commit": commit, "base_tree": tree,
            "guard": {"mode": "ALL_TRACKED", "exempt": sorted({DELTA_PATH, *(POLICY.V4_BOUND_EXEMPT if POLICY else ())})},
            "policy_version": POLICY.POLICY_VERSION if POLICY else "UNAVAILABLE", "full_run": full_run or {"status": "UNVERIFIED"},
            "entries": entries, "entries_sha256": entries_digest(entries), "atlas": list(atlas)}


def make_delta(base_inv, head_inv, base_sha, base_tree):
    """The finite base-relative delta that turns ``guarded(base)`` into ``guarded(head)`` (a generator for REVIEW; the verifier never trusts it)."""
    base, now = guarded_inventory(base_inv), guarded_inventory(head_inv)
    changes = []
    for p in sorted(set(base) | set(now)):
        if p not in now:
            changes.append({"op": "delete", "path": p, "blob": None, "mode": None, "class": classify(p)[0]})
        elif p not in base:
            changes.append({"op": "add", "path": p, "blob": now[p][1], "mode": now[p][0], "class": classify(p)[0]})
        elif base[p] != now[p]:
            changes.append({"op": "modify", "path": p, "blob": now[p][1], "mode": now[p][0], "class": classify(p)[0]})
    return {"schema": DELTA_SCHEMA, "base_sha": base_sha, "base_tree": base_tree, "result_inventory_sha256": inventory_digest(now), "changes": changes}


def load_epoch(raw):
    """(epoch, problems). Rejects non-canonical bytes, unknown schema, wrong keys, bad/duplicate/unsorted entries and a forged digest.
    A V1 document loads with ``legacy=True`` (``LEGACY_NARROW_GUARD``): it can never be reported as an approved FULL guard."""
    problems = []
    try:
        d = json.loads(raw)
    except (ValueError, UnicodeDecodeError):
        return None, [("EPOCH_MALFORMED", "not JSON")]
    if not isinstance(d, dict) or d.get("schema") not in (EPOCH_SCHEMA, EPOCH_SCHEMA_V1):
        return None, [("EPOCH_UNKNOWN_SCHEMA", str(d.get("schema")) if isinstance(d, dict) else "not an object")]
    if raw != canonical(d):
        return None, [("EPOCH_NONCANONICAL", "bytes differ from the canonical serialisation")]
    legacy = d["schema"] == EPOCH_SCHEMA_V1
    if set(d) != (EPOCH_KEYS_V1 if legacy else EPOCH_KEYS) or not isinstance(d["entries"], list) or not isinstance(d["atlas"], list):
        return None, [("EPOCH_MALFORMED", "unexpected key set or types")]
    if not (isinstance(d["base_commit"], str) and SHA40.fullmatch(d["base_commit"]) and isinstance(d["base_tree"], str) and SHA40.fullmatch(d["base_tree"])):
        return None, [("EPOCH_MALFORMED", "base_commit/base_tree must be 40-hex")]
    if not legacy:
        g = d["guard"]
        if not (isinstance(g, dict) and set(g) == {"mode", "exempt"} and g["mode"] == "ALL_TRACKED" and isinstance(g["exempt"], list) and all(isinstance(x, str) for x in g["exempt"])):
            return None, [("EPOCH_MALFORMED", "guard must be {mode: ALL_TRACKED, exempt: [...]}")]
        if not isinstance(d["policy_version"], str) or not isinstance(d["full_run"], dict):
            return None, [("EPOCH_MALFORMED", "policy_version / full_run types")]
    elif not isinstance(d["guard_prefixes"], list):
        return None, [("EPOCH_MALFORMED", "guard_prefixes type")]
    seen = set()
    for e in d["entries"]:
        try:
            path, _b, _m = parse_entry(e)
        except (ValueError, AttributeError, TypeError):
            problems.append(("EPOCH_BAD_ENTRY", str(e)[:80]))
            continue
        if path in seen:
            problems.append(("EPOCH_DUPLICATE_PATH", path))
        seen.add(path)
    if d["entries"] != sorted(d["entries"]) and not problems:
        problems.append(("EPOCH_MALFORMED", "entries are not sorted"))
    if not problems and d["entries_sha256"] != entries_digest(d["entries"]):
        problems.append(("EPOCH_DIGEST_MISMATCH", "entries_sha256 does not match the entries"))
    if problems:
        return None, problems
    d = dict(d)
    d["legacy"] = legacy
    return d, []


def epoch_map(epoch):
    return {p: (m, b) for p, b, m in map(parse_entry, epoch["entries"])}


def load_delta(raw, base_inv, base_sha, base_tree):
    """(changes {path: change}, problems, binding). ``changes`` is only returned when the whole delta is acceptable; ``binding`` is the document's own
    claimed (base_sha, base_tree, result digest) so the caller can compare it with the observed head."""
    try:
        d = json.loads(raw)
    except (ValueError, UnicodeDecodeError):
        return None, [("DELTA_MALFORMED", "not JSON")], None
    if not isinstance(d, dict) or d.get("schema") != DELTA_SCHEMA:
        return None, [("DELTA_UNKNOWN_SCHEMA", str(d.get("schema")) if isinstance(d, dict) else "not an object")], None
    if raw != canonical(d):
        return None, [("DELTA_NONCANONICAL", "bytes differ from the canonical serialisation")], None
    if set(d) != DELTA_KEYS or not isinstance(d["changes"], list):
        return None, [("DELTA_MALFORMED", "unexpected key set or types")], None
    if not (isinstance(d["base_sha"], str) and SHA40.fullmatch(d["base_sha"]) and isinstance(d["base_tree"], str) and SHA40.fullmatch(d["base_tree"])
            and isinstance(d["result_inventory_sha256"], str) and SHA256.fullmatch(d["result_inventory_sha256"])):
        return None, [("DELTA_MALFORMED", "base_sha/base_tree must be 40-hex and result_inventory_sha256 64-hex")], None
    binding = (d["base_sha"], d["base_tree"], d["result_inventory_sha256"])
    problems = []
    if d["base_sha"] != base_sha:
        problems.append(("DELTA_BASE_MISMATCH", "delta is bound to base %s, evaluated base is %s (stale or replayed delta)" % (d["base_sha"][:12], base_sha[:12])))
    if d["base_tree"] != base_tree:
        problems.append(("DELTA_BASE_TREE_MISMATCH", "delta is bound to a different base tree"))
    if len(d["changes"]) > MAX_DELTA:
        return None, problems + [("DELTA_TOO_LARGE", "%d changes > %d: split the change" % (len(d["changes"]), MAX_DELTA))], binding
    base = guarded_inventory(base_inv)
    out, folded = {}, {}
    base_fold = {q.casefold() for q in base}
    for c in d["changes"]:
        if not isinstance(c, dict) or set(c) != CHANGE_KEYS:
            problems.append(("DELTA_MALFORMED", "change keys"))
            continue
        p, op = c["path"], c["op"]
        if not _path_ok(p):
            problems.append(("DELTA_BAD_PATH", str(p)[:80]))
            continue
        if p in out or p.casefold() in folded:
            problems.append(("DELTA_DUPLICATE_PATH", p))
            continue
        folded[p.casefold()] = p
        if not is_guarded(p):
            problems.append(("DELTA_EXEMPT_PATH", p + ": a delta cannot declare the delta, the trust anchor or a V4-bound exempt file"))
        elif op not in OPS:
            problems.append(("DELTA_BAD_OP", "%s: %s" % (p, op)))
        elif op == "delete" and (c["blob"] is not None or c["mode"] is not None):
            problems.append(("DELTA_MALFORMED", p + ": delete carries a blob/mode"))
        elif op != "delete" and not (isinstance(c["blob"], str) and SHA40.fullmatch(c["blob"])):
            problems.append(("DELTA_MALFORMED", p + ": blob must be 40-hex"))
        elif op != "delete" and c["mode"] not in MODES:
            problems.append(("DELTA_BAD_MODE", "%s: %s" % (p, c["mode"])))
        elif op == "add" and p in base:
            problems.append(("DELTA_BAD_OP", p + ": add of a path that exists at the base"))
        elif op in ("modify", "delete") and p not in base:
            problems.append(("DELTA_BAD_OP", p + ": " + op + " of a path that is not at the base"))
        elif op == "modify" and base[p] == (c["mode"], c["blob"]):
            problems.append(("DELTA_NOOP", p + ": modify equals the base entry (same-value change)"))
        elif op == "add" and p.casefold() in base_fold:
            problems.append(("DELTA_PATH_COLLISION", p + ": case-insensitive collision with a base path"))
        elif POLICY is not None and POLICY.registry_ok() and c["class"] != classify(p)[0]:
            problems.append(("DELTA_CLASS_MISMATCH", "%s: declared %s, trusted policy says %s" % (p, c["class"], classify(p)[0])))
        out[p] = c
    allp = set(out) | set(base)
    for p in out:                                               # a file may not collide with a directory of another path
        if out[p]["op"] == "add" and any(q.startswith(p + "/") for q in allp):
            problems.append(("DELTA_PATH_COLLISION", p))
    return (None if problems else out), problems, binding


# --------------------------------------------------------------------------------------------------------------------------- worktree
def _worktree(git, head_sha, head_inv, failures, notes):
    """Attest that the checked-out tree IS the evaluated head, for EVERY tracked path and everywhere else too. Never trusts index flags or ``git status``
    alone: tracked bytes are re-hashed from disk. Ignored/untracked importable or served material anywhere is a failure."""
    if git.run("rev-parse", "HEAD").decode().strip() != head_sha:
        failures.append(("WORKTREE_HEAD_MISMATCH", "the checked-out HEAD is not the evaluated SHA"))
    # 1. porcelain: dirty tracked + untracked anywhere (not only guarded paths: ALL_TRACKED)
    for rec in git.run("status", "--porcelain=v1", "-z", "--untracked-files=all", "--no-renames").split(b"\0"):
        if len(rec) > 3:
            xy, path = rec[:2].decode(), rec[3:].decode("utf-8", "surrogateescape")
            failures.append(("UNTRACKED_PATH" if xy == "??" else "DIRTY_PATH", path))
    # 2. index flags that blind ``git status`` (skip-worktree 'S', assume-unchanged lower-case)
    for rec in git.run("ls-files", "-v", "-z").split(b"\0"):
        if rec and rec[:1] != b"H":
            failures.append(("INDEX_FLAG_HIDES_PATH", rec[2:].decode("utf-8", "surrogateescape") + " (tag %s)" % rec[:1].decode()))
    # 3. ignored files: importable / served ones are failures anywhere (app/data/*.py, __pycache__/*.pyc, root conftest, sitecustomize ...)
    ignored = [r.decode("utf-8", "surrogateescape") for r in git.run("ls-files", "-z", "--others", "--ignored", "--exclude-standard").split(b"\0") if r]
    other = 0
    for path in ignored:
        base = path.rsplit("/", 1)[-1].lower()
        if path.lower().endswith(DANGEROUS_SUFFIXES) or base in DANGEROUS_NAMES or "__pycache__/" in path or path.startswith("__pycache__/"):
            failures.append(("IGNORED_IMPORTABLE_FILE", path))
        else:
            other += 1
    notes["ignored_files_not_importable"] = other
    # 4. tracked content re-hashed from disk against the evaluated head (independent of the index flags): one ``hash-object`` batch
    paths = sorted(p for p, (m, _o) in head_inv.items() if m in MODES)
    on_disk = []
    for p in paths:
        full = os.path.join(git.root, *p.split("/"))
        if os.path.islink(full) or not os.path.isfile(full):
            failures.append(("WORKTREE_PATH_MISSING_OR_NOT_REGULAR", p))
        else:
            on_disk.append(p)
            if bool(os.stat(full).st_mode & 0o111) != (head_inv[p][0] == "100755"):
                failures.append(("WORKTREE_MODE_MISMATCH", p))
    if on_disk:
        out = git.run("hash-object", "--stdin-paths", input=("\n".join(on_disk) + "\n").encode()).decode().split()
        if len(out) != len(on_disk):
            failures.append(("WORKTREE_HASH_ERROR", "hash-object returned %d of %d" % (len(out), len(on_disk))))
        else:
            for p, h in zip(on_disk, out):
                if h != head_inv[p][1]:
                    failures.append(("WORKTREE_CONTENT_MISMATCH", p))


# --------------------------------------------------------------------------------------------------------------------------- verification
def _tidy(items):
    return [{"code": c, "detail": d} for c, d in items]


def epoch_full_provenance(epoch):
    """(ok, reason). An epoch is only a TRUSTED checkpoint when its FULL witness is an attested PASS bound to the very commit it snapshots (run id + sha). A
    blocked / failed / unknown FULL is recorded honestly and is NEVER read as a pass: the epoch then stays non-authoritative (``EPOCH_FULL_PROVENANCE_NOT_GREEN``)."""
    fr = epoch.get("full_run") if isinstance(epoch, dict) else None
    if not isinstance(fr, dict):
        return False, "no FULL witness"
    if fr.get("status") != "PASS":
        return False, "FULL status is %s" % fr.get("status")
    if not (isinstance(fr.get("run_id"), str) and fr["run_id"] and fr.get("sha") == epoch.get("base_commit")):
        return False, "FULL witness is not bound to run id + the epoch's own commit"
    return True, "FULL PASS attested for run %s" % fr["run_id"]


def _epoch_truth(git, epoch, base_sha, base_inv, failures, unknowns):
    """The epoch must be a truthful ALL_TRACKED snapshot of the commit it names, and that commit must be accepted history of the trusted base."""
    etypes = git.run("cat-file", "--batch-check=%(objectname) %(objecttype)", input=("%s\n%s^{tree}\n" % (epoch["base_commit"], epoch["base_commit"])).encode()).decode().splitlines()
    if [ln.split(" ")[-1] for ln in etypes] != ["commit", "tree"]:
        unknowns.append(("EPOCH_COMMIT_UNAVAILABLE", "the epoch's pinned commit is not present in this repository"))
        return
    if etypes[1].split(" ")[0] != epoch["base_tree"]:
        failures.append(("EPOCH_TREE_NOT_OWNED", "the pinned SHA does not own the declared tree"))
        return
    if not epoch.get("legacy"):
        einv = base_inv if epoch["base_commit"] == base_sha else read_inventory(git, epoch["base_commit"])
        snap = {p: v for p, v in einv.items() if is_guarded(p)}
        emap = epoch_map(epoch)
        if snap != emap:
            failures.append(("EPOCH_SNAPSHOT_MISMATCH", "epoch entries differ from the pinned commit's ALL_TRACKED inventory (%d paths)" % len(
                {p for p in set(snap) | set(emap) if snap.get(p) != emap.get(p)})))
        if POLICY is not None and sorted(epoch["guard"]["exempt"]) != sorted({DELTA_PATH, *POLICY.V4_BOUND_EXEMPT}):
            failures.append(("EPOCH_GUARD_DEFINITION_MISMATCH", "the epoch's exempt list differs from the trusted policy's"))
        if POLICY is not None and epoch["policy_version"] != POLICY.POLICY_VERSION:
            unknowns.append(("EPOCH_POLICY_VERSION", "epoch was approved under policy %s, trusted code is %s" % (epoch["policy_version"], POLICY.POLICY_VERSION)))
    try:
        git.run("merge-base", "--is-ancestor", epoch["base_commit"], base_sha)
    except GitError:
        failures.append(("EPOCH_NOT_ACCEPTED_HISTORY", "the epoch's pinned commit is not an ancestor of the trusted base"))


def verify(root, head_sha, base_sha, *, trusted_ref_tip=None, tool_source="UNTRUSTED_TOOL_SOURCE", epoch_bytes=None, delta_bytes=None,
           expect_head_tree=None, check_worktree=False):
    """The V5 verdict. ``trusted_ref_tip`` = the current tip of the allow-listed protected ref (the caller fetched it); the base MUST equal it.
    ``tool_source`` = where this evaluator's code came from (``TRUSTED_BASE`` only when it was archived from the trusted base commit).
    ``epoch_bytes`` given explicitly => ``EXPLICIT_UNTRUSTED`` (tests / tooling); otherwise the epoch is discovered: trusted BASE
    ``docs/ci_v5/epoch.json`` (TRUSTED_BASE), else the PR-head candidate (CANDIDATE_UNTRUSTED), else NO_EPOCH."""
    wall0, cpu0 = time.monotonic(), time.process_time()
    git = Git(root)
    failures, unknowns, notes = [], [], {}
    rec = {"schema": VERDICT_SCHEMA, "integrity": "UNKNOWN", "authorization": "NOT_EVALUATED", "enforcement": "SHADOW", "transition": "NONE",
           "source_head_sha": head_sha, "source_tree": None, "base_sha": base_sha, "base_tree": None, "epoch_sha": None, "epoch_digest": None,
           "delta_digest": None, "result_inventory_sha256": None, "full_guard_count": 0, "semantic_gaps": [],
           "trust": {"tool_source": tool_source, "epoch_state": "NO_EPOCH", "base_state": "UNVERIFIED", "guard_mode": "ALL_TRACKED", "authoritative": False},
           "epoch": None, "delta_changes": 0, "classes": {}}

    def finish():
        rec["integrity"] = "INTEGRITY_FAIL" if failures else ("UNKNOWN" if unknowns else "INTEGRITY_PASS")
        t = rec["trust"]
        t["authoritative"] = rec["integrity"] in ("INTEGRITY_PASS", "INTEGRITY_FAIL") and t["tool_source"] in TRUSTED_TOOL_SOURCES and t["epoch_state"] == "TRUSTED_BASE" \
            and t["base_state"] == "VERIFIED_TIP" and t["guard_mode"] == "ALL_TRACKED"
        rec["effective"] = rec["integrity"] if t["authoritative"] else "NON_AUTHORITATIVE_" + rec["integrity"]
        rec["failures"], rec["unknowns"], rec["notes"] = _tidy(failures), _tidy(unknowns), notes
        rec["metrics"] = {"wall_s": round(time.monotonic() - wall0, 3), "cpu_s": round(time.process_time() - cpu0, 3), "git_children": git.children, "memo_or_cache": "none"}
        return rec

    if not (isinstance(head_sha, str) and SHA40.fullmatch(head_sha) and isinstance(base_sha, str) and SHA40.fullmatch(base_sha)):
        failures.append(("BAD_REF", "head and base must be full 40-hex commit SHAs (symbolic refs are rejected)"))
        return finish()
    if trusted_ref_tip is not None and not (isinstance(trusted_ref_tip, str) and SHA40.fullmatch(trusted_ref_tip)):
        failures.append(("BAD_REF", "the trusted ref tip must be a full 40-hex commit SHA"))
        return finish()
    if tool_source not in TRUSTED_TOOL_SOURCES:
        unknowns.append(("UNTRUSTED_TOOL_SOURCE", "the evaluator was not read from the trusted base (%s): a pass is impossible, a failure still counts" % tool_source))
    try:
        # object-database identity: replace refs / grafts / shallow history would redirect or truncate what a SHA means
        if git.run("for-each-ref", "--format=%(refname)", "refs/replace").strip():
            failures.append(("REPLACE_REFS_PRESENT", "refs/replace entries exist in the evaluating repository (ignored, but never a clean run)"))
        gitdir = git.run("rev-parse", "--absolute-git-dir").decode().strip()
        if os.path.exists(os.path.join(gitdir, "info", "grafts")):
            failures.append(("GRAFTS_PRESENT", "info/grafts exists in the evaluating repository"))
        if git.run("rev-parse", "--is-shallow-repository").decode().strip() != "false":
            unknowns.append(("SHALLOW_REPOSITORY", "ancestry cannot be proven in a shallow clone (use fetch-depth: 0)"))

        names = [head_sha, head_sha + "^{tree}", base_sha, base_sha + "^{tree}"]
        out = git.run("cat-file", "--batch-check=%(objectname) %(objecttype)", input=("\n".join(names) + "\n").encode()).decode().splitlines()
        types = [ln.split(" ")[1] if ln.count(" ") == 1 else "missing" for ln in out]
        if types != ["commit", "tree", "commit", "tree"]:
            unknowns.append(("OBJECT_UNAVAILABLE", "head/base are not both present commits in this repository"))
            return finish()
        rec["source_tree"], rec["base_tree"] = out[1].split(" ")[0], out[3].split(" ")[0]
        if expect_head_tree is not None and expect_head_tree != rec["source_tree"]:
            failures.append(("HEAD_TREE_MISMATCH", "expected %s, found %s" % (expect_head_tree, rec["source_tree"])))

        # the base must be the CURRENT TIP of the trusted protected ref and the head must contain it (merge-tree identity), never a caller-chosen merge-base
        if trusted_ref_tip is None:
            unknowns.append(("TRUSTED_REF_TIP_NOT_PROVIDED", "no trusted ref tip supplied: the base cannot be proven to be the protected branch tip"))
        elif trusted_ref_tip != base_sha:
            unknowns.append(("BASE_NOT_TRUSTED_REF_TIP", "evaluated base %s is not the trusted ref tip %s" % (base_sha[:12], trusted_ref_tip[:12])))
        else:
            rec["trust"]["base_state"] = "VERIFIED_TIP"
        try:
            git.run("merge-base", "--is-ancestor", base_sha, head_sha)
            notes["merge_identity"] = "HEAD_CONTAINS_BASE_TIP"
        except GitError:
            unknowns.append(("HEAD_NOT_UP_TO_DATE", "the head does not contain the trusted base tip (stale fork / other base): not evaluated, merge or rebase the base first"))
            rec["trust"]["base_state"] = "HEAD_DOES_NOT_CONTAIN_BASE"
            return finish()
        head_inv, base_inv = read_inventory(git, head_sha), read_inventory(git, base_sha)
        head_g, base_g = guarded_inventory(head_inv), guarded_inventory(base_inv)
        rec["full_guard_count"] = len(head_g)
        rec["result_inventory_sha256"] = inventory_digest(head_g)
        failures.extend(unsafe_paths(head_inv))

        # ---------------------------------------------------------------- the trust anchor (epoch) and the promotion transition
        raw_epoch, source = epoch_bytes, "explicit"
        if raw_epoch is not None:
            rec["trust"]["epoch_state"] = "EXPLICIT_UNTRUSTED"
        elif TRUSTED_EPOCH_PATH in base_inv and base_inv[TRUSTED_EPOCH_PATH][0] in MODES:
            raw_epoch, rec["trust"]["epoch_state"], source = git.run("cat-file", "blob", base_inv[TRUSTED_EPOCH_PATH][1]), "TRUSTED_BASE", "base:" + TRUSTED_EPOCH_PATH
        elif CANDIDATE_EPOCH_PATH in head_inv and head_inv[CANDIDATE_EPOCH_PATH][0] in MODES:
            raw_epoch, rec["trust"]["epoch_state"], source = git.run("cat-file", "blob", head_inv[CANDIDATE_EPOCH_PATH][1]), "CANDIDATE_UNTRUSTED", "head:" + CANDIDATE_EPOCH_PATH
        promotion = head_inv.get(TRUSTED_EPOCH_PATH) != base_inv.get(TRUSTED_EPOCH_PATH)
        if promotion:
            rec["transition"] = "PROMOTION_REQUIRES_OWNER"
            unknowns.append(("PROMOTION_REQUIRES_OWNER", TRUSTED_EPOCH_PATH + " differs between the trusted base and the PR head: an epoch promotion (or rollback) can never "
                             "authorise itself; it needs the owner's independent approval and takes effect only for the NEXT pull request"))
            _promotion_checks(git, head_inv, base_inv, base_sha, failures)
        if rec["trust"]["epoch_state"] != "TRUSTED_BASE":
            unknowns.append(("NO_TRUSTED_EPOCH", "epoch state %s: no trusted epoch is anchored at the base, so integrity is computed base-relative but can never be a "
                             "trusted pass; V4 stays authoritative" % rec["trust"]["epoch_state"]))
        if raw_epoch is None:
            epoch = None
        else:
            epoch, problems = load_epoch(raw_epoch)
            if epoch is None:
                failures.extend(problems)
            else:
                rec["epoch"] = {"source": source, "id": epoch["epoch_id"], "commit": epoch["base_commit"], "tree": epoch["base_tree"], "entries": len(epoch["entries"]),
                                "entries_sha256": epoch["entries_sha256"], "schema": EPOCH_SCHEMA_V1 if epoch["legacy"] else EPOCH_SCHEMA}
                rec["epoch_sha"], rec["epoch_digest"] = epoch["base_commit"], sha256_hex(raw_epoch)
                if epoch["legacy"]:
                    rec["trust"]["guard_mode"] = "LEGACY_NARROW_GUARD"
                    unknowns.append(("LEGACY_NARROW_GUARD", "epoch schema V1 guards a narrow prefix list: it is never an approved FULL guard"))
                _epoch_truth(git, epoch, base_sha, base_inv, failures, unknowns)
                if not epoch["legacy"]:
                    full_ok, full_why = epoch_full_provenance(epoch)
                    rec["epoch"]["full_witness"] = "FULL_WITNESS_ATTESTED_GREEN" if full_ok else (epoch["full_run"] or {}).get("status", "UNKNOWN")
                    if not full_ok:
                        unknowns.append(("EPOCH_FULL_PROVENANCE_NOT_GREEN", "%s: the epoch is a checkpoint without a green FULL witness and is never authoritative" % full_why))
                if not epoch["legacy"] and epoch_map(epoch) != base_g:
                    drift = {p for p in set(base_g) | set(epoch_map(epoch)) if base_g.get(p) != epoch_map(epoch).get(p)}
                    notes["epoch_drift_paths"] = len(drift)               # informational only: the epoch is a checkpoint, not the base inventory

        # ---------------------------------------------------------------- the base-relative delta
        if delta_bytes is None and DELTA_PATH in head_inv and head_inv.get(DELTA_PATH) == base_inv.get(DELTA_PATH):
            notes["delta_inherited_from_base"] = True       # the delta file at the head IS the one already merged: it declares nothing for THIS pull request
        elif delta_bytes is None and DELTA_PATH in head_inv:
            if head_inv[DELTA_PATH][0] not in MODES:
                failures.append(("NON_REGULAR_MODE", "%s: mode %s (the delta must be a regular file)" % (DELTA_PATH, head_inv[DELTA_PATH][0])))
            else:
                delta_bytes = git.run("cat-file", "blob", head_inv[DELTA_PATH][1])
        changes = {}
        if delta_bytes is not None:
            rec["delta_digest"] = sha256_hex(delta_bytes)
            changes, problems, binding = load_delta(delta_bytes, base_inv, base_sha, rec["base_tree"])
            if changes is None:
                failures.extend(problems)
                changes = {}
            if binding is not None and binding[2] != rec["result_inventory_sha256"]:
                failures.append(("DELTA_RESULT_MISMATCH", "result_inventory_sha256 does not match the guarded inventory of the evaluated head"))
        rec["delta_changes"] = len(changes)

        expected = dict(base_g)
        for p, c in changes.items():
            if c["op"] == "delete":
                expected.pop(p, None)
            else:
                expected[p] = (c["mode"], c["blob"])
        for p, (mode, oid) in sorted(head_g.items()):
            if mode not in MODES:
                failures.append(("NON_REGULAR_MODE", "%s: mode %s (symlink/gitlink are never reviewable)" % (p, mode)))
            elif p not in expected:
                failures.append(("UNDECLARED_ADD" if p not in changes else "DELTA_NOT_REALISED", p))
            elif expected[p] != (mode, oid):
                kind = "UNDECLARED_MODE_CHANGE" if expected[p][1] == oid else ("UNDECLARED_CHANGE" if p not in changes else "DELTA_BLOB_MISMATCH")
                failures.append((kind, "%s: expected %s %s, found %s %s" % (p, expected[p][0], expected[p][1][:12], mode, oid[:12])))
        for p in sorted(set(expected) - set(head_g)):
            failures.append(("UNDECLARED_DELETE_OR_RENAME" if p not in changes else "DELTA_NOT_REALISED", p))

        # ---------------------------------------------------------------- classes and the semantic registry (trusted code)
        observed = {p: ("delete" if p not in head_g else ("add" if p not in base_g else "modify")) for p in set(head_g) | set(base_g) if head_g.get(p) != base_g.get(p)}
        counts = {}
        semantic = []
        for p, op in sorted(observed.items()):
            cls, why = classify(p)
            counts[cls] = counts.get(cls, 0) + 1
            if cls == "S":
                semantic.append("%s (%s)" % (p, why))
            elif POLICY is not None and POLICY.touches_existing_test(op, p):
                semantic.append("%s (TEST_MODIFIED_OR_RETIRED)" % p)
        exempt_changed = sorted(p for p in set(head_inv) | set(base_inv) if is_exempt(p) and p != DELTA_PATH and head_inv.get(p) != base_inv.get(p))
        if exempt_changed:
            semantic.extend("%s (V4_BOUND_EXEMPT)" % p for p in exempt_changed)
        rec["classes"], rec["semantic_gaps"] = counts, semantic
        if POLICY is None or not POLICY.registry_ok():
            unknowns.append(("SEMANTIC_REGISTRY_UNAVAILABLE", "the trusted semantic registry is missing or empty: every change is UNKNOWN, never 'none'"))
        if semantic:                      # V4 judges these by AST / chain / test semantics V5 does not evaluate: never a V5 INTEGRITY_PASS
            unknowns.append(("SEMANTIC_INVARIANT_NOT_EVALUATED", "%d changed path(s) are semantic or V4-owned: %s" % (len(semantic), ", ".join(semantic[:5]))))
        if check_worktree:
            _worktree(git, head_sha, head_inv, failures, notes)
        return finish()
    except (GitError, OSError, ValueError, subprocess.TimeoutExpired) as exc:       # fail closed: an evaluator error is never a PASS
        failures.append(("EVALUATOR_ERROR", "%s: %s" % (type(exc).__name__, exc)))
        return finish()


def _promotion_checks(git, head_inv, base_inv, base_sha, failures):
    """The promotion transition must be narrow: the new anchor is a valid V2 epoch of exactly the accepted base, and NOTHING else guarded changes."""
    other = {p for p in set(head_inv) | set(base_inv) if is_guarded(p) and head_inv.get(p) != base_inv.get(p)}
    if other:
        failures.append(("PROMOTION_NOT_ISOLATED", "a promotion PR may change only the trust anchor and the delta; %d other path(s) differ: %s" % (len(other), ", ".join(sorted(other)[:5]))))
    if TRUSTED_EPOCH_PATH not in head_inv:
        return                                                  # an intentional ROLLBACK removes the anchor: still requires the owner (reported above)
    if head_inv[TRUSTED_EPOCH_PATH][0] not in MODES:
        failures.append(("NON_REGULAR_MODE", TRUSTED_EPOCH_PATH))
        return
    new, problems = load_epoch(git.run("cat-file", "blob", head_inv[TRUSTED_EPOCH_PATH][1]))
    if new is None:
        failures.extend(problems)
        return
    if new["legacy"]:
        failures.append(("PROMOTION_LEGACY_EPOCH", "a promoted anchor must be a V2 ALL_TRACKED epoch"))
    if new["base_commit"] != base_sha:
        failures.append(("PROMOTION_EPOCH_NOT_BASE", "the promoted epoch must snapshot exactly the accepted base commit"))
    else:
        snap = {p: v for p, v in base_inv.items() if is_guarded(p)}
        if not new["legacy"] and snap != epoch_map(new):
            failures.append(("PROMOTION_SNAPSHOT_MISMATCH", "the promoted epoch is not a truthful ALL_TRACKED snapshot of the accepted base"))


def main(argv=None):
    ap = argparse.ArgumentParser(description="CI V5 evaluator V2 (shadow; exit 0 INTEGRITY_PASS, 1 INTEGRITY_FAIL, 2 UNKNOWN).")
    ap.add_argument("--repo", default=".")
    ap.add_argument("--head-sha", required=True)
    ap.add_argument("--base-sha", required=True)
    ap.add_argument("--trusted-ref-tip", help="current tip of the protected ref (40-hex); the base must equal it")
    ap.add_argument("--tool-source", choices=("TRUSTED_BASE", "UNTRUSTED_TOOL_SOURCE"), default="UNTRUSTED_TOOL_SOURCE")
    ap.add_argument("--epoch-file")
    ap.add_argument("--delta-file")
    ap.add_argument("--expect-head-tree")
    ap.add_argument("--check-worktree", action="store_true")
    ap.add_argument("--output")
    a = ap.parse_args(argv)
    read = lambda f: open(f, "rb").read() if f else None
    rec = verify(a.repo, a.head_sha, a.base_sha, trusted_ref_tip=a.trusted_ref_tip, tool_source=a.tool_source, epoch_bytes=read(a.epoch_file),
                 delta_bytes=read(a.delta_file), expect_head_tree=a.expect_head_tree, check_worktree=a.check_worktree)
    text = json.dumps(rec, indent=2, sort_keys=True) + "\n"
    if a.output:
        os.makedirs(os.path.dirname(os.path.abspath(a.output)), exist_ok=True)
        with open(a.output, "w") as fh:
            fh.write(text)
    print("CI V5 %s (authorization=%s enforcement=%s transition=%s tool_source=%s): %d failures, %d unknowns" % (
        rec["integrity"], rec["authorization"], rec["enforcement"], rec["transition"], rec["trust"]["tool_source"], len(rec["failures"]), len(rec["unknowns"])))
    return {"INTEGRITY_PASS": 0, "INTEGRITY_FAIL": 1}.get(rec["integrity"], 2)


if __name__ == "__main__":
    sys.exit(main())
