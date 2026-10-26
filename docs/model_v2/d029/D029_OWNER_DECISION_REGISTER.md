# D-029 owner decision register

Engineering authorization does not decide retention/API or financial policy. Feature remains release-closed.
`RunIntentPolicy` groups the candidate semantics; it is not yet a deployable feature switch.

| Decision | Candidate/recommendation | Current implemented isolation | Owner disposition |
|---|---|---|---|
| Optional vs required keys | Optional migration, explicitly non-idempotent no-key | No route changed | PENDING |
| Retention | Assess 24h replay payload retention separately from durable key tombstone | No automatic deletion | PENDING; 24h NOT approved |
| Cleanup/expiration | Never silently reuse a successfully committed key | Delete trigger refuses key deletion | PENDING retention integration |
| Replay after retention | Exact history or truthful HISTORY_UNAVAILABLE; never recalculate committed intent | Helper implements refusal | PENDING policy |
| Different keys overlap | Preserve released admission/CAS semantics; deliberate new Run allowed | Independent ledger scope | PENDING project concurrency policy |
| In-progress behavior | Immediate typed IN_PROGRESS; no background polling/new daemon | Helper returns IN_PROGRESS, zero wait | PENDING transport UX |
| Failures/retry | Same failed key terminal; deliberate retry uses new key | Immutable FAILED + typed code | PENDING, including saturation UX |
| Expired active attempt | Explicit fenced recovery after current CAS; recomputation possible | Primitive only; not routed | PENDING lease/recovery values |

No numerical result or protected-reference permission depends on these candidate decisions. Missing decisions
must not be treated as consent. A future tombstone/payload-retention migration must preserve at-most-one commit
across its entire supported scope and coordinate existing demo/project deletion; no cleanup feature is shipped.

## Status boundary

Implemented: isolated reservation, lookup/reconciliation, schema audit, fencing and cursor finalization helpers.
Proven: the executed persistence-only and released-baseline checks listed in `evidence/D029_LOCAL_TEST_RESULTS.json`.
Proposed policy: `D029_OWNER_DECISION_REGISTER.md`; no production rollout is enabled.
Deferred integration: canonical HTTP Run, financial commit hook, startup migration and real clients, after FIN-VAL #383 merges.
Owner decisions: retention, expiration/retry and compatibility semantics remain open.
Residual risk: the currently released Run route still permits duplicate commits; isolated tests do not prove end-to-end idempotency.
