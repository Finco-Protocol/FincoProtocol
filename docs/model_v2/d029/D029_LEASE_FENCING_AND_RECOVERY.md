# D-029 lease, fencing and recovery

`LEASE_MS` = 1,020,000 (900 s executor cap + 120 s margin). `reserve` is a single unique INSERT; only the acquirer receives a
reservation and may start the engine. Fencing is checked twice: at `start` and inside the commit transaction
(`require_owner_cursor`), comparing generation, owner nonce, fingerprint, RUNNING state and unexpired lease.

`recover()` (explicit expired-lease takeover, generation + 1) exists and is tested but is NOT routed: an expired RESERVED/
RUNNING intent answers typed `EXPIRED` and runs nothing. Test `test_stale_owner_is_fenced_and_commits_nothing` expires the
lease mid-run, takes over with a second owner, releases the first, and proves: no history row, Last Run unchanged, the new
owner's claim untouched. Automatic recovery needs an owner decision (see register).

## Status boundary

Release state: **RELEASE CLOSED**. See the release-state matrix in `D029_EXECUTIVE_REVIEW.md`.
Implemented and tested on PR #384 head: the canonical `POST /v2/workbook/run` intent lifecycle, the single-transaction
commit, startup schema, the React and Legacy clients and the governance successor. Not owner-approved, not activated:
the owner policies in `D029_OWNER_DECISION_REGISTER.md` remain candidates, `RELEASE_POLICY.enabled` is false, nothing is
deployed or merged. A request without `run_intent_id` keeps the released, non-idempotent behaviour.
