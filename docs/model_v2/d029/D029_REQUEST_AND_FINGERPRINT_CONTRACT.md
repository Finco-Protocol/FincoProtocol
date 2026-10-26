# D-029 request and fingerprint contract

The proposed field is `run_intent_id` on the existing `POST /v2/workbook/run`. It is NOT accepted by that
route yet. `SubmittedIntent` validates a canonical lowercase 36-character RFC UUIDv4 without coercing its bits.
This identifier is correlation, never authorization or a CSRF token. One explicit new Run needs a new key.

The immutable database scope is `(authenticated actor_id, immutable project_id, run_intent_id)`.
The early submitted-binding SHA256 covers contract `finco-run-intent-v1`, actor/project, ORIGINAL submitted
workbook version and composite hash. Canonical serialization is sorted-key compact JSON with non-finite
numbers refused; no HTTP time, lease time, session token or retry count participates.

The frozen request fingerprint adds scenario ID, effective input authority, CAPEX/OPEX/override identity and
execution contract. Callers must supply the ACTUAL canonical materialization, not a second reconstruction or
engine output. This module has not yet been connected to that materialization. Source verification must
establish all effective scenario/line layers are included before integration is accepted.

A changed submitted binding or changed frozen fingerprint in the same scope raises `RUN_INTENT_CONFLICT`.
Cross-user/project lookup is scoped and never returns another reservation. Normal access checks must still run first.
Existing committed replay checks the ORIGINAL submitted binding; it must not fingerprint today's edited inputs.
Re-executing under a new engine contract is a new intent; original committed evidence remains historical truth.

## Status boundary

Release state: **RELEASE CLOSED**. See the release-state matrix in `D029_EXECUTIVE_REVIEW.md`.
Implemented and tested on PR #384 head: the canonical `POST /v2/workbook/run` intent lifecycle, the single-transaction
commit, startup schema, the React and Legacy clients and the governance successor. Not owner-approved, not activated:
the owner policies in `D029_OWNER_DECISION_REGISTER.md` remain candidates, `RELEASE_POLICY.enabled` is false, nothing is
deployed or merged. A request without `run_intent_id` keeps the released, non-idempotent behaviour.
