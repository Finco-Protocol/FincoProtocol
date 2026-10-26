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

Implemented: isolated reservation, lookup/reconciliation, schema audit, fencing and cursor finalization helpers.
Proven: the executed persistence-only and released-baseline checks listed in `evidence/D029_LOCAL_TEST_RESULTS.json`.
Proposed policy: `D029_OWNER_DECISION_REGISTER.md`; no production rollout is enabled.
Deferred integration: canonical HTTP Run, financial commit hook, startup migration and real clients, after FIN-VAL #383 merges.
Owner decisions: retention, expiration/retry and compatibility semantics remain open.
Residual risk: the currently released Run route still permits duplicate commits; isolated tests do not prove end-to-end idempotency.
