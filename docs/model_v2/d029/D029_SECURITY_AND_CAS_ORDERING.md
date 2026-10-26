# D-029 security and CAS ordering (as implemented)

Order in `v2_workbook_run` (structurally enforced by `d029_run_order_violations` in the SEC-02 successor module, with
negative mutations proving each reorder is detected without byte pins):

1. authenticate; 2. resolve accessible project and workspace owner (404 for inaccessible, non-disclosing);
3. purpose-bound `workbook-run-v1` CSRF, contradictory dual tokens rejected (403) - **before any ledger access**;
4. `run_intent_id` syntax; 5. `decide(...)`: protected reference => REFUSED without touching the ledger; otherwise lookup by
the ORIGINAL submitted binding (workspace owner, project, workbook_version, content_hash) => REPLAYED / IN_PROGRESS /
FAILED / EXPIRED / HISTORY_UNAVAILABLE / CONFLICT, or NEW;
6. only NEW continues: workspace, version, CAS, scenario, effective-input materialization, frozen fingerprint, durable
reservation (unique acquirer only), bounded executor; 7. `v2_atomic_run_commit` re-checks CAS and the fence inside BEGIN
EXCLUSIVE, appends exactly one history row, `finalize_cursor`, COMMIT. No second history writer, no post-commit finalizer.

Deviation to confirm: the spec lists the protected-reference refusal before CSRF; the released handler (RC-SEC pinned) runs
CSRF first and has exactly one protected gate. Both orders never read the ledger for a protected project; the released one
reveals nothing to an unauthenticated-CSRF caller. Left as released.

Committed replay never restores Last Run, clears dirty, refreshes certificates or returns a newer result. Tests: cross-session
token, cross-actor, cross-project, protected reference, foreign `history_id`, malformed history, invalid UUID, schema corruption.

## Status boundary

Release state: **RELEASE CLOSED**. See the release-state matrix in `D029_EXECUTIVE_REVIEW.md`.
Implemented and tested on PR #384 head: the canonical `POST /v2/workbook/run` intent lifecycle, the single-transaction
commit, startup schema, the React and Legacy clients and the governance successor. Not owner-approved, not activated:
the owner policies in `D029_OWNER_DECISION_REGISTER.md` remain candidates, `RELEASE_POLICY.enabled` is false, nothing is
deployed or merged. A request without `run_intent_id` keeps the released, non-idempotent behaviour.
