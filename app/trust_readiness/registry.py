"""The FINCO Model trust and release-readiness registry (WF-10A).

Single source of truth for the public Trust pages, the generated documents under
``docs/readiness/`` and the supporting tests. Nothing here is aspirational by accident:

* a statement is ``IMPLEMENTED_VERIFIED`` only if it cites code and an automated check
  (the registry tests resolve every citation against the repository);
* what is not built is ``PROPOSED``; what needs counsel is ``REQUIRES_LEGAL_APPROVAL``;
  what depends on hosting or process is ``REQUIRES_OPERATIONAL_CONTROLS``;
* every verified deviation from what a reader would reasonably expect is a ``KnownGap``
  that a test pins, so fixing it forces this file to change.

Scope: the FINCO Model product (modelling, persistence, run evidence). Radar, Yield and
token/wallet features have their own data and controls and are NOT assessed here.

No external certification is held or claimed. Legal documents are not published.
"""
from __future__ import annotations

from app.trust_readiness.contracts import (
    DataStoreEntry,
    EvidenceKind,
    EvidenceRef,
    GapSeverity,
    KnownGap,
    LegalDocument,
    NotClaimed,
    ReadinessItem,
    ReadinessStatus as S,
)

REVIEWED_ON = "2026-10-10"
SCOPE_STATEMENT = (
    "This pack covers the FINCO Model product: modelling, persistence, authentication, "
    "run evidence and release readiness. Radar, Yield and token or wallet features have "
    "their own data and controls and are not assessed here."
)


def _code(path: str, anchor: str) -> EvidenceRef:
    return EvidenceRef(EvidenceKind.CODE, path, anchor)


def _test(path: str, anchor: str) -> EvidenceRef:
    return EvidenceRef(EvidenceKind.TEST, path, anchor)


def _ci(path: str, anchor: str) -> EvidenceRef:
    return EvidenceRef(EvidenceKind.CI, path, anchor)


def _doc(path: str, anchor: str) -> EvidenceRef:
    return EvidenceRef(EvidenceKind.DOC, path, anchor)


_CTRL = "tests/test_trust_readiness_controls.py"

# ---------------------------------------------------------------------------
# Controls (security, access, tenant isolation, run evidence, operations)
# ---------------------------------------------------------------------------

AREA_LABELS = {
    "access_control": "Authentication and sessions",
    "tenant_isolation": "Tenant isolation",
    "security_controls": "Security controls",
    "run_evidence": "Run evidence and integrity",
    "operations": "Operations and hosting",
}

CONTROLS: tuple[ReadinessItem, ...] = (
    # ---- authentication and sessions -------------------------------------------------
    ReadinessItem(
        "access.secure_mode_fail_closed", "access_control",
        "Secure deployment mode fails closed",
        S.IMPLEMENTED_VERIFIED,
        "In pilot mode, and in any unrecognised app mode, startup refuses to run with a missing "
        "or placeholder signing secret, a placeholder CSRF secret, a weak or repository-default "
        "operator password, or cookies that are not marked Secure.",
        (
            _code("app/auth.py", "Refusing to start with a fallback signing secret"),
            _test("tests/test_f04_signing_secret_fail_closed.py", "test_pilot_missing_secret_fails_closed"),
            _test("tests/test_p0c_secure_runtime.py", "test_pilot_rejects_placeholder_csrf_secret"),
        ),
        "Development and internal modes deliberately start with warnings; they are not for "
        "deployments that hold real data.",
    ),
    ReadinessItem(
        "access.password_hashing", "access_control",
        "Operator password hashing",
        S.IMPLEMENTED_VERIFIED,
        "The operator password is checked with bcrypt (cost factor 12). A pre-computed bcrypt "
        "hash can be supplied through the environment instead of a plain password.",
        (
            _code("app/auth.py", "bcrypt.hashpw(password.encode(), bcrypt.gensalt(rounds=12))"),
            _test(_CTRL, "test_operator_password_is_bcrypt_hashed"),
        ),
    ),
    ReadinessItem(
        "access.session_cookies", "access_control",
        "Signed session cookies",
        S.IMPLEMENTED_VERIFIED,
        "Sessions are signed tokens held in HttpOnly cookies, marked Secure and SameSite=Lax by "
        "default, with expiry enforced on the server (24 hours by default).",
        (
            _code("app/auth.py", '"httponly": True'),
            _test(_CTRL, "test_session_cookie_flags_are_hardened"),
            _test("tests/test_f05_shared_session_contract.py", "test_resolver_expired_admin_token_fails_closed"),
        ),
        "Tokens are stateless. There is no server-side session store, so a single session cannot "
        "be revoked before it expires; rotating the signing secret ends all sessions.",
    ),
    ReadinessItem(
        "access.login_rate_limit", "access_control",
        "Login rate limiting",
        S.IMPLEMENTED_VERIFIED,
        "After 5 failed logins from one address, further attempts are refused for 300 seconds.",
        (
            _code("app/auth.py", "MAX_LOGIN_FAILURES = 5"),
            _test(_CTRL, "test_login_rate_limit_locks_out_after_repeated_failures"),
        ),
        "The counter lives in process memory. It is per address, not shared between workers, and "
        "resets on restart.",
    ),
    ReadinessItem(
        "access.csrf_login", "access_control",
        "CSRF token on the login form",
        S.IMPLEMENTED_VERIFIED,
        "The login form carries a signed, time-limited token that is validated on submission.",
        (
            _code("app/auth.py", "def validate_csrf_token"),
            _test(_CTRL, "test_login_requires_valid_csrf_token"),
        ),
        "Tokens also protect the model-import steps and one crypto action. Other state-changing "
        "requests rely on the SameSite cookie attribute (see known gap).",
    ),
    ReadinessItem(
        "access.operator_demo_boundary", "access_control",
        "Operator and demo identities are not interchangeable",
        S.IMPLEMENTED_VERIFIED,
        "Operator and anonymous demo sessions use different cookies and signing salts, and a token "
        "of one kind is rejected as the other.",
        (
            _code("app/auth.py", 'salt="finco-demo-session"'),
            _test("tests/test_p6_demo_isolation.py", "test_admin_token_not_accepted_as_demo"),
            _test("tests/test_p6_demo_isolation.py", "test_demo_token_not_accepted_as_admin"),
        ),
    ),
    ReadinessItem(
        "access.demo_operation_limits", "access_control",
        "Per-session limits on demo operations",
        S.IMPLEMENTED_VERIFIED,
        "Anonymous demo sessions are rate limited on expensive operations such as exports and "
        "scenario creation. The operator session is not limited.",
        (
            _code("app/auth.py", "def check_demo_rate_limit"),
            _test("tests/test_p6_demo_isolation.py", "test_demo_rate_limit_enforced"),
            _test("tests/test_p6_demo_isolation.py", "test_demo_rate_limit_not_applied_to_admin"),
        ),
        "Counters are in process memory, as for login limiting.",
    ),
    ReadinessItem(
        "access.multi_user_identity", "access_control",
        "Multi-user identity, roles, SSO and MFA",
        S.PROPOSED,
        "The product has one operator account configured through the deployment environment, plus "
        "anonymous demo identities. There is no user directory, no roles, no single sign-on, no "
        "multi-factor authentication, no password reset and no per-user audit trail. These are "
        "proposed, not built.",
        (_code("app/auth.py", 'ADMIN_USERNAME = os.getenv("FINCO_ADMIN_USER", "admin")'),),
    ),
    ReadinessItem(
        "access.edge_controls", "access_control",
        "Network-edge protections",
        S.REQUIRES_OPERATIONAL_CONTROLS,
        "TLS termination, IP allow-listing, shared rate limiting, request-size limits and "
        "restricting operational endpoints are deployment controls. The repository ships example "
        "nginx and systemd configuration, which enforces HTTPS, TLS 1.2 or later and a 10 MB body "
        "limit but includes no rate limiting. The repository cannot prove how a live deployment "
        "is configured.",
        (_doc("deploy/nginx/app.conf", "ssl_protocols       TLSv1.2 TLSv1.3;"),),
    ),
    # ---- tenant isolation ---------------------------------------------------------------
    ReadinessItem(
        "tenant.user_keyed_storage", "tenant_isolation",
        "Every user data table is tenant keyed",
        S.IMPLEMENTED_VERIFIED,
        "Each table that holds user data carries a user_id column, or is reached only through a "
        "project that does. A test fails if a new table is added without being classified here.",
        (
            _code("app/persistence/db.py", "CREATE TABLE IF NOT EXISTS projects"),
            _test(_CTRL, "test_every_persisted_table_is_tenant_keyed_and_classified"),
        ),
        "All tenants share one SQLite database file. Isolation is enforced by application queries, "
        "not by separate databases or database-level row security.",
    ),
    ReadinessItem(
        "tenant.project_resolution", "tenant_isolation",
        "Project lookup never crosses tenants",
        S.IMPLEMENTED_VERIFIED,
        "A project code resolves to the caller's own project or to a protected canonical "
        "reference, never to another user's project.",
        (
            _code("app/persistence/projects_repository.py", "Never returns another normal user's project"),
            _test(_CTRL, "test_project_resolution_never_crosses_tenants"),
            _test("tests/test_p6_demo_isolation.py", "test_idor_demo_vs_admin_isolation"),
            _test("tests/test_p6_correction_a.py", "test_idor_workspace_state_session_b_cannot_read_session_a"),
        ),
    ),
    ReadinessItem(
        "tenant.demo_isolation", "tenant_isolation",
        "Demo sessions are isolated from each other",
        S.IMPLEMENTED_VERIFIED,
        "Each anonymous visitor gets a cryptographically random demo identity, and demo data is "
        "scoped to it.",
        (
            _code("app/auth.py", "secrets.token_urlsafe(24)"),
            _test("tests/test_p6_demo_isolation.py", "test_demo_user_id_is_unique"),
            _test("tests/test_p6_demo_isolation.py", "test_demo_session_data_isolation"),
        ),
    ),
    # ---- security controls ----------------------------------------------------------------
    ReadinessItem(
        "security.response_headers", "security_controls",
        "Security response headers",
        S.IMPLEMENTED_VERIFIED,
        "Every response carries X-Frame-Options DENY, X-Content-Type-Options nosniff, a "
        "same-origin Referrer-Policy, a restrictive Permissions-Policy and a Content-Security-Policy "
        "that forbids framing. HTML is not cached. HSTS is sent when secure cookies are enabled.",
        (
            _code("app/middleware/security_headers.py", "frame-ancestors 'none'"),
            _test(_CTRL, "test_security_headers_are_present_on_every_response"),
        ),
        "The Content-Security-Policy still allows inline scripts and styles. Removing that is "
        "tracked as a known gap.",
    ),
    ReadinessItem(
        "security.request_logging_minimal", "security_controls",
        "Request logs carry no cookies or bodies",
        S.IMPLEMENTED_VERIFIED,
        "Request logs record method, path, status code and a request id. They do not record "
        "cookies, headers, request bodies or client addresses.",
        (
            _code("app/middleware/request_logging.py", "without sensitive data"),
            _test(_CTRL, "test_request_log_contains_no_cookie_or_body"),
        ),
        "A path can contain a project code, so log lines can identify a project.",
    ),
    ReadinessItem(
        "security.same_origin_resources", "security_controls",
        "No third-party scripts, styles or fonts",
        S.IMPLEMENTED_VERIFIED,
        "Served templates load scripts, styles and fonts from the product's own origin only, and "
        "the Content-Security-Policy restricts resources to the same origin.",
        (
            _code("app/middleware/security_headers.py", "default-src 'self'"),
            _test(_CTRL, "test_templates_load_no_external_resources"),
        ),
    ),
    ReadinessItem(
        "security.import_not_persisted", "security_controls",
        "Model imports are processed in memory",
        S.IMPLEMENTED_VERIFIED,
        "The model import path does not write uploaded files to disk.",
        (
            _code("app/model_import/intake.py", "No file persistence"),
            _test(_CTRL, "test_model_import_never_writes_uploads_to_disk"),
        ),
        "Imported values that the user then saves are stored like any other project data.",
    ),
    ReadinessItem(
        "security.bounded_model_execution", "security_controls",
        "Bounded model execution",
        S.IMPLEMENTED_VERIFIED,
        "Model runs execute in a bounded pool of worker processes with a typed busy response when "
        "capacity is full, so a burst of runs cannot exhaust the host or block other requests.",
        (
            _code("app/runtime/model_execution.py", "One bounded admission boundary"),
            _test("tests/test_p0a_model_execution.py", "test_above_capacity_fails_fast_typed_busy_with_no_queue"),
        ),
        "The bound is per process, not host-wide.",
    ),
    ReadinessItem(
        "security.ci_gates", "security_controls",
        "Repository safety scan and dependency audit in CI",
        S.IMPLEMENTED_VERIFIED,
        "Every pull request runs a public-repository safety scan, a compile check, the full test "
        "suite and a pinned dependency vulnerability audit.",
        (
            _ci(".github/workflows/public_safety_and_smoke.yml", "python tools/public_safety_scan.py"),
            _ci(".github/workflows/dependency_security_audit.yml", "pip-audit"),
        ),
        "Automated scans are controls, not guarantees that no secret, vulnerability or confidential "
        "item is present.",
    ),
    ReadinessItem(
        "security.encryption_at_rest", "security_controls",
        "Encryption at rest",
        S.REQUIRES_OPERATIONAL_CONTROLS,
        "The application does not encrypt the database, backups or exports itself. Encryption at "
        "rest, file permissions and key custody are host or volume controls that must be provided "
        "and evidenced by the deployment.",
    ),
    ReadinessItem(
        "security.vulnerability_reporting", "security_controls",
        "Private vulnerability reporting route",
        S.REQUIRES_OPERATIONAL_CONTROLS,
        "A private reporting channel has to be enabled and verified by the maintainers. The "
        "security policy states that it must not be read as advertising a route that is not yet "
        "configured.",
        (_doc("SECURITY.md", "must enable a canonical private vulnerability-reporting route"),),
    ),
    ReadinessItem(
        "security.independent_assessment", "security_controls",
        "Independent security assessment",
        S.PROPOSED,
        "No independent penetration test or security audit report is held. Commissioning one, "
        "and publishing only its verified outcome, is proposed before institutional use.",
    ),
    ReadinessItem(
        "security.incident_response", "security_controls",
        "Incident response and breach notification",
        S.REQUIRES_OPERATIONAL_CONTROLS,
        "An incident response plan, on-call ownership and customer notification procedure are "
        "operational controls that do not exist in the repository. Legal notification duties "
        "also need counsel's input.",
    ),
    # ---- run evidence --------------------------------------------------------------------------
    ReadinessItem(
        "evidence.run_integrity_checks", "run_evidence",
        "Run Integrity Checks",
        S.IMPLEMENTED_VERIFIED,
        "Nine automated checks test the internal consistency of a committed Last Run, for example "
        "that Sources equal Uses, the balance sheet balances, debt rolls forward and the reported "
        "DSCR equals CFADS over debt service. A failed or missing check is shown as such, never "
        "as a pass.",
        (
            _code("app/run_integrity/checks.py", "def run_integrity_checks"),
            _test("tests/test_h4b_run_integrity_checks.py", "test_real_runs_pass_every_check"),
            _test("tests/test_h4b_run_integrity_checks.py", "test_missing_or_foreign_evidence_is_incomplete_never_pass"),
        ),
        "Internal consistency only. It does not validate assumptions, market data or the asset.",
    ),
    ReadinessItem(
        "evidence.tamper_detection", "run_evidence",
        "Tamper detection on committed evidence",
        S.IMPLEMENTED_VERIFIED,
        "Committed run evidence carries a digest; altering it after commit is detected and fails "
        "the digest check.",
        (
            _code("app/run_integrity/checks.py", "def check_evidence_digest"),
            _test("tests/test_h4b_run_integrity_checks.py", "test_tampering_after_commit_is_detected_by_the_digest"),
        ),
        "A digest detects change; it does not prove who made it.",
    ),
    ReadinessItem(
        "evidence.signed_run_certificate", "run_evidence",
        "Signed Run Certificate",
        S.IMPLEMENTED_VERIFIED,
        "A committed Last Run can be signed with Ed25519. Issuance never re-runs the model, never "
        "signs a Working Copy, and fails closed if the run identity is incomplete or no signing key "
        "is configured.",
        (
            _code("app/services/run_certificate_service.py", "Ed25519"),
            _doc("docs/SIGNED_RUN_CERTIFICATE_V1.md", "never runs the model and never"),
            _test("tests/test_signed_run_certificate.py", "test_signed_run_incomplete_identity_fails_closed"),
            _test("tests/test_signed_run_certificate.py", "test_signed_run_no_engine_rerun"),
        ),
        "A signature proves a record came from a key holder and has not changed. It is not an "
        "audit opinion, not FINCO Verify and not evidence of economic truth.",
    ),
    ReadinessItem(
        "evidence.public_verification", "run_evidence",
        "Public certificate verification",
        S.IMPLEMENTED_VERIFIED,
        "Anyone can verify a certificate without logging in, through a public endpoint or an "
        "offline command-line verifier that share one verification core. The bundled trust "
        "registry ships with no trusted key.",
        (
            _code("app/protocol/signing_keys_registry.json", '"keys"'),
            _test("tests/test_m2_signed_run_public_trust.py", "test_bundled_manifest_ships_no_default_trust_key"),
        ),
        "Until a production issuer key is committed through a reviewed change, every certificate "
        "verifies as UNKNOWN_KEY_ID.",
    ),
    ReadinessItem(
        "evidence.signing_key_provisioning", "run_evidence",
        "Production signing key custody",
        S.REQUIRES_OPERATIONAL_CONTROLS,
        "The signing seed has to be generated and held in managed key storage by the deployment, "
        "its public key committed through review, and rotation exercised. None of that can be "
        "proven from the repository.",
        (_doc("docs/SIGNED_RUN_CERTIFICATE_V1.md", "Rotation runbook"),),
    ),
    ReadinessItem(
        "evidence.reference_regression", "run_evidence",
        "Reference Regression Check",
        S.IMPLEMENTED_VERIFIED,
        "Canonical synthetic reference models are re-run against pinned expected outputs and "
        "tolerances to detect regressions in the engine.",
        (
            _code("app/api/v1_1/institutional.py", "get_institutional_validation"),
            _doc("docs/review/PRODUCT_TRUTH_RELEASE_MATRIX.md", "Reference Regression Check (P1.3)"),
            _test("tests/test_p1_3_institutional_validation.py", "def test_p1_3_tolerance_policy_complete"),
        ),
        "Regression protection only. It never validates a user's own Last Run.",
    ),
    # ---- operations ------------------------------------------------------------------------------
    ReadinessItem(
        "ops.sqlite_backups", "operations",
        "Database backups",
        S.IMPLEMENTED_VERIFIED,
        "Backups of the SQLite database can be created with a checksum, validated and restored. "
        "Automatic backups are enabled by default every 24 hours and the 10 newest are kept.",
        (
            _code("app/persistence/backup_restore.py", "_AUTO_BACKUP_MAX_FILES"),
            _test(_CTRL, "test_sqlite_backup_roundtrip_and_prune"),
        ),
        "Backups are unencrypted copies of the whole database. Manual and pre-restore safety "
        "backups are never pruned automatically, and a backup can still hold data that was "
        "deleted from the live database.",
    ),
    ReadinessItem(
        "ops.log_retention", "operations",
        "Log retention",
        S.REQUIRES_OPERATIONAL_CONTROLS,
        "The application writes logs to standard output. How long they are kept, and who can read "
        "them, is decided by the host. An example logrotate file keeps 7 to 14 days.",
        (_doc("deploy/logrotate/finco-web", "rotate 14"),),
    ),
    ReadinessItem(
        "ops.hosting_and_residency", "operations",
        "Hosting location and data residency",
        S.REQUIRES_OPERATIONAL_CONTROLS,
        "The repository does not fix where a deployment runs. Region, provider and any "
        "contractual residency commitment are operational and legal decisions.",
    ),
    ReadinessItem(
        "ops.subprocessors", "operations",
        "Sub-processors",
        S.REQUIRES_LEGAL_APPROVAL,
        "Any hosting, backup or monitoring provider that handles customer data has to be listed "
        "and contractually approved. No such list is published.",
    ),
)

# ---------------------------------------------------------------------------
# Release-readiness checklist
# ---------------------------------------------------------------------------

RELEASE_CHECKLIST: tuple[ReadinessItem, ...] = (
    ReadinessItem(
        "release.ci_exact_head", "release", "All required CI gates green on the exact head",
        S.IMPLEMENTED_VERIFIED,
        "Pull requests run the safety scan, compile check, full test suite, dependency audit and "
        "the frozen-namespace governance guards.",
        (_ci(".github/workflows/pr_compile_and_safety.yml", "compileall"),),
    ),
    ReadinessItem(
        "release.synthetic_only_repository", "release", "Public repository contains synthetic data only",
        S.IMPLEMENTED_VERIFIED,
        "Client data, project-specific workbooks, production databases, credentials and keys must "
        "not be committed, and the safety scan checks for them.",
        (
            _doc("docs/PUBLIC_DATA_POLICY.md", "generic, synthetic, or explicitly public data"),
            _ci(".github/workflows/public_safety_and_smoke.yml", "python tools/public_safety_scan.py"),
        ),
    ),
    ReadinessItem(
        "release.no_unverified_certifications", "release", "No unverified certification or compliance claims",
        S.IMPLEMENTED_VERIFIED,
        "A test scans the trust pages, the generated documents and the registry for certification "
        "and compliance claims and fails on any that are not explicitly negated.",
        (
            _code("app/trust_readiness/claims.py", "def scan_text"),
            _test("tests/test_trust_readiness_claims.py", "test_trust_surfaces_make_no_unsupported_claims"),
        ),
    ),
    ReadinessItem(
        "release.terms_of_service", "release", "Terms of Service",
        S.REQUIRES_LEGAL_APPROVAL,
        "Not published. Requires counsel's approval and the owner's explicit authorisation.",
    ),
    ReadinessItem(
        "release.privacy_notice", "release", "Privacy Notice",
        S.REQUIRES_LEGAL_APPROVAL,
        "Not published. Requires counsel's approval and the owner's explicit authorisation. It "
        "must reflect the cookies and retention behaviour documented in this pack.",
    ),
    ReadinessItem(
        "release.data_processing_agreement", "release", "Data Processing Agreement",
        S.REQUIRES_LEGAL_APPROVAL,
        "Not published. Requires counsel's approval and the owner's explicit authorisation.",
    ),
    ReadinessItem(
        "release.cookie_notice", "release", "Cookie notice",
        S.REQUIRES_LEGAL_APPROVAL,
        "The product sets a signed session cookie and an anonymous demo cookie. Whether and how "
        "they are disclosed or consented to is a legal decision.",
    ),
    ReadinessItem(
        "release.erasure_procedure", "release", "Data deletion and erasure procedure",
        S.REQUIRES_OPERATIONAL_CONTROLS,
        "No product route deletes a project, run or run history. Until one exists, deleting a "
        "customer's data is a manual database operation that needs a documented, tested procedure "
        "and a legal basis (see known gaps).",
    ),
    ReadinessItem(
        "release.backup_restore_drill", "release", "Backup and restore drill",
        S.REQUIRES_OPERATIONAL_CONTROLS,
        "A restore from backup into a clean environment has to be exercised and recorded.",
    ),
    ReadinessItem(
        "release.monitoring_and_support", "release", "Monitoring, alerting, support and service levels",
        S.REQUIRES_OPERATIONAL_CONTROLS,
        "Uptime monitoring, alert routing, a support channel and any service-level commitment are "
        "operational and contractual matters not present in the repository.",
    ),
    ReadinessItem(
        "release.security_assessment", "release", "Independent security assessment",
        S.PROPOSED,
        "Proposed before institutional use of real client data.",
    ),
    ReadinessItem(
        "release.certification_roadmap", "release", "Certification roadmap (proposed, not started)",
        S.PROPOSED,
        "No certification programme has been started and none is held. Whether to pursue one is "
        "a proposal that has not been decided.",
    ),
)

# ---------------------------------------------------------------------------
# Data inventory (also the retention and deletion inventory)
# ---------------------------------------------------------------------------

# Every persisted table must appear in exactly one entry's ``tables`` (tested).
DATA_STORES: tuple[DataStoreEntry, ...] = (
    DataStoreEntry(
        "data.operator_credential", "Operator credential", "Deployment environment variables",
        "not applicable", "Operator username and a bcrypt hash or plain password.", False,
        "Held by the deployment for as long as it is configured.",
        "Rotate or remove the environment variable.", False,
        S.REQUIRES_OPERATIONAL_CONTROLS,
        (_code("app/auth.py", "FINCO_ADMIN_PASSWORD_HASH"),),
        "Secret storage and rotation are deployment controls. Prefer the hash form.",
    ),
    DataStoreEntry(
        "data.session_cookie", "Operator session cookie", "Browser cookie",
        "user id in the token", "User id, username, login time and a signature. No personal data "
        "beyond the operator username.", False,
        "24 hours by default (FINCO_SESSION_HOURS), enforced on the server.",
        "Sign out clears the cookie. The token cannot be revoked on the server before it expires.", True,
        S.IMPLEMENTED_VERIFIED,
        (
            _code("app/auth.py", "def create_session_token"),
            _test("tests/test_f05_shared_session_contract.py", "test_resolver_expired_admin_token_fails_closed"),
        ),
    ),
    DataStoreEntry(
        "data.demo_cookie", "Anonymous demo cookie", "Browser cookie",
        "random demo id", "A random demo identity, login time and a signature. No personal data.",
        False,
        "24 hours by default (FINCO_DEMO_TTL_HOURS).",
        "Expires; clearing the browser cookie ends the session.", True,
        S.IMPLEMENTED_VERIFIED,
        (
            _code("app/auth.py", "def create_demo_session_token"),
            _test("tests/test_p6_demo_isolation.py", "test_demo_session_token_roundtrip"),
        ),
        "Most public pages issue this cookie to a first-time visitor automatically. The Trust "
        "pages do not.",
    ),
    DataStoreEntry(
        "data.projects", "Projects and cost lines", "SQLite database",
        "user_id (sub-lines through project_id)",
        "Project code and name, inputs and assumptions, governance state and the last run summary.",
        True,
        "Demo data: removed after the demo TTL when inactive, with one exception (known gap). "
        "Other data: kept until an operator removes it.",
        "No product route deletes a project. Archiving is a soft flag. Deletion is an operator "
        "database procedure.", False,
        S.REQUIRES_OPERATIONAL_CONTROLS,
        (_code("app/demo_cleanup.py", "_SUBLINE_TABLES"),),
        "User-entered names and notes can be confidential and are stored unencrypted by the "
        "application.",
        tables=("projects", "capex_sub_lines", "opex_sub_lines"),
    ),
    DataStoreEntry(
        "data.scenarios", "Scenarios and workspace state", "SQLite database",
        "user_id", "Scenario inputs, overrides and the working copy.", True,
        "As for projects.", "As for projects (scenarios can be archived, not deleted).", False,
        S.REQUIRES_OPERATIONAL_CONTROLS,
        (_code("app/demo_cleanup.py", '"workspace_states"'),),
        tables=("scenarios", "workspace_states"),
    ),
    DataStoreEntry(
        "data.runs", "Run records and exports", "SQLite database",
        "user_id", "Inputs and KPI snapshots per run, and export metadata (names, lineage). "
        "Generated workbook files, when written, live on the host file system.", True,
        "As for projects.", "A delete function exists in the repository but nothing in the "
        "product calls it.", False,
        S.REQUIRES_OPERATIONAL_CONTROLS,
        (_code("app/persistence/runs_repository.py", "def delete_run"),),
        tables=("runs", "scenario_exports"),
    ),
    DataStoreEntry(
        "data.run_history", "Run history (immutable)", "SQLite database",
        "user_id", "One immutable row per successful run: full financial statements, debt, tax, "
        "distribution and sponsor schedules, integrity evidence.", True,
        "Append-only by design. NOT covered by the demo clean-up (known gap).",
        "None in the product. A database foreign key to the project blocks project deletion while "
        "history rows exist.", False,
        S.REQUIRES_OPERATIONAL_CONTROLS,
        (_code("app/persistence/db.py", "CREATE TABLE IF NOT EXISTS model_run_history"),),
        "This is the most complete copy of a customer's modelled results.",
        tables=("model_run_history",),
    ),
    DataStoreEntry(
        "data.backups", "Database backups", "Files on the host (default under the data directory)",
        "whole database", "A full copy of every table above.", True,
        "Automatic backups: the newest 10 are kept. Manual and pre-restore safety backups are "
        "kept until removed.",
        "Delete the backup files. Data removed from the live database remains in older backups.",
        True,
        S.REQUIRES_OPERATIONAL_CONTROLS,
        (_code("app/persistence/backup_restore.py", "def prune_auto_backups"),),
        "Backups are not encrypted by the application.",
    ),
    DataStoreEntry(
        "data.logs", "Application and access logs", "Standard output, then host log storage",
        "none", "Method, path, status and request id. No cookies, bodies or client addresses.",
        False,
        "Decided by the host. An example logrotate file keeps 7 to 14 days.",
        "Host log management.", False,
        S.REQUIRES_OPERATIONAL_CONTROLS,
        (_code("app/middleware/request_logging.py", "without sensitive data"),),
        "The reverse proxy keeps its own access log with client addresses.",
    ),
    DataStoreEntry(
        "data.rate_limit_counters", "Rate-limit counters", "Process memory",
        "client address or demo id", "Failed-login counts and demo operation counts.", False,
        "Cleared on restart; demo counters are purged when stale.",
        "Restart the process.", True,
        S.IMPLEMENTED_VERIFIED,
        (
            _code("app/auth.py", "def purge_expired_demo_rate_entries"),
            _test(_CTRL, "test_rate_limit_counters_are_in_memory_and_stale_ones_are_purged"),
        ),
    ),
    DataStoreEntry(
        "data.model_import", "Imported model files", "Not stored",
        "not applicable", "Processed in memory to prefill a project; the upload is not written to "
        "disk.", True,
        "Not retained.", "Not applicable.", True,
        S.IMPLEMENTED_VERIFIED,
        (
            _code("app/model_import/intake.py", "No file persistence"),
            _test(_CTRL, "test_model_import_never_writes_uploads_to_disk"),
        ),
        "Values the user saves afterwards are stored as project data.",
    ),
)

# ---------------------------------------------------------------------------
# Known gaps: verified, pinned by tests
# ---------------------------------------------------------------------------

KNOWN_GAPS: tuple[KnownGap, ...] = (
    KnownGap(
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
    KnownGap(
        "gap.no_user_erasure_path", "No way to delete project data from the product",
        GapSeverity.HIGH,
        "No route deletes a project, scenario, run or run history; archiving is a soft flag and "
        "the repository's run-delete function is imported but never called. A customer's data can be removed "
        "only by an operator working directly on the database and its backups.",
        "Define the erasure requirement with counsel, then add an authenticated, tenant-scoped "
        "deletion path that also covers history and documents backup expiry. Until then, "
        "treat institutional use of real client data as not ready.",
        (
            _code("app/persistence/runs_repository.py", "def delete_run"),
            _test(_CTRL, "test_known_gap_no_product_route_deletes_user_data"),
        ),
    ),
    KnownGap(
        "gap.readyz_discloses_server_details", "The public readiness endpoint exposes server details",
        GapSeverity.LOW,
        "GET /readyz needs no login and returns the app mode and the configured database path, "
        "backup directory and backup settings (shown as placeholders only when unset).",
        "Return only a status to unauthenticated callers, or restrict the endpoint at the "
        "reverse proxy.",
        (
            _code("app/observability.py", '"db_path": db_path'),
            _test(_CTRL, "test_known_gap_readyz_discloses_server_paths"),
        ),
    ),
    KnownGap(
        "gap.csrf_login_only", "Most state-changing requests have no CSRF token",
        GapSeverity.MEDIUM,
        "CSRF tokens protect the login form, the model-import steps, the Inputs grid validate and save routes and one crypto action. Other "
        "state-changing requests rely on the session cookie being SameSite=Lax, and the SameSite "
        "value can be changed by an environment variable without validation.",
        "Add an Origin or token check to state-changing endpoints and validate the SameSite "
        "setting at startup.",
        (
            _code("main_web.py", "validate_csrf_token(csrf_token)"),
            _test(_CTRL, "test_known_gap_state_changing_posts_have_no_csrf_token"),
        ),
    ),
    KnownGap(
        "gap.csp_unsafe_inline", "Content-Security-Policy allows inline scripts and styles",
        GapSeverity.LOW,
        "The policy includes 'unsafe-inline' for scripts and styles because some pages still use "
        "inline initialisation scripts.",
        "Move inline scripts to external files and remove 'unsafe-inline'.",
        (
            _code("app/middleware/security_headers.py", "unsafe-inline"),
            _test(_CTRL, "test_security_headers_are_present_on_every_response"),
        ),
    ),
    KnownGap(
        "gap.public_pages_set_a_cookie", "Public pages issue an anonymous cookie on first visit",
        GapSeverity.LOW,
        "Visiting most public pages, including documentation, gives a first-time visitor a signed "
        "anonymous demo cookie. It holds no personal data, but whether it needs disclosure or "
        "consent is a legal question. The Trust pages are excluded from this behaviour.",
        "Decide with counsel whether public information pages should be excluded, then extend "
        "the skip list.",
        (
            _code("main_web.py", "_DEMO_PROVISION_SKIP_PREFIXES"),
            _test(_CTRL, "test_other_public_pages_still_provision_demo_session"),
        ),
    ),
    KnownGap(
        "gap.sessions_not_revocable", "Sessions cannot be revoked individually",
        GapSeverity.LOW,
        "Sessions are stateless signed tokens, so a stolen token stays valid until it expires "
        "(24 hours by default) unless the signing secret is rotated, which ends every session.",
        "Introduce a server-side session identifier with a revocation list if multi-user access "
        "is added.",
        (
            _code("app/auth.py", "Server-side session data (no DB, no Redis)"),
            _test(_CTRL, "test_known_gap_sessions_are_stateless_and_not_revocable"),
        ),
    ),
    KnownGap(
        "gap.pre_existing_grade_claim", "An existing guide uses an unsupported quality claim",
        GapSeverity.LOW,
        "The external pilot guide uses the unsupported phrase \"institutional-grade\" for an export, "
        "and nothing in the repository establishes that grade.",
        "Reword it in a separate documentation change. This pack does not edit that guide.",
        (
            _doc("docs/external_pilot_guide.md", "institutional-grade"),
            _test("tests/test_trust_readiness_claims.py", "test_known_pre_existing_claims_are_exactly_the_documented_ones"),
        ),
    ),
)

# ---------------------------------------------------------------------------
# What is NOT claimed
# ---------------------------------------------------------------------------

NOT_CLAIMED: tuple[NotClaimed, ...] = (
    NotClaimed("SOC 2", "FINCO does not claim SOC 2 attestation. No audit has been performed and no report is held."),
    NotClaimed("ISO/IEC 27001", "FINCO does not claim ISO/IEC 27001 certification. None is held."),
    NotClaimed("FAST Standard", "FINCO does not claim FAST Standard compliance. No review against it has been performed."),
    NotClaimed("IFC Performance Standards", "FINCO does not claim IFC compliance or alignment. No assessment has been performed."),
    NotClaimed("Penetration test", "FINCO does not claim an independent penetration test. None is held."),
    NotClaimed("Legal or regulatory compliance", "FINCO does not claim compliance with any privacy or data-protection regulation. That requires legal review."),
    NotClaimed("Audit or lender approval", "FINCO does not claim that any model output is audited, certified or approved by a lender. Run evidence is not an audit opinion."),
)

# ---------------------------------------------------------------------------
# Legal documents: never published as approved from here
# ---------------------------------------------------------------------------

LEGAL_DOCUMENTS: tuple[LegalDocument, ...] = (
    LegalDocument("legal.terms", "Terms of Service", "NOT_PUBLISHED",
                  "Counsel approval and explicit owner authorisation",
                  "No text is published. This pack provides facts for counsel, not terms."),
    LegalDocument("legal.privacy", "Privacy Notice", "NOT_PUBLISHED",
                  "Counsel approval and explicit owner authorisation",
                  "The Data handling and Retention pages record what the product does so the notice can be accurate."),
    LegalDocument("legal.dpa", "Data Processing Agreement", "NOT_PUBLISHED",
                  "Counsel approval and explicit owner authorisation",
                  "Depends on the sub-processor list and hosting decisions, which are open."),
    LegalDocument("legal.cookies", "Cookie notice", "NOT_PUBLISHED",
                  "Counsel approval and explicit owner authorisation",
                  "The cookies the product sets are listed on the Data handling page."),
)


def all_items() -> tuple[ReadinessItem, ...]:
    return CONTROLS + RELEASE_CHECKLIST
