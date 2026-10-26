# D-029 reproduction and root cause

Source: current main at the executive-review SHA. Synthetic Solar Working Copies, disposable WAL databases,
real signed Run tokens and real canonical financial engine; released thread-mode executor for this local baseline.
The supplied archive used older main `80dbe67`; its observations are evidence, not a current source contract.

Portable reproduction (explicit disposable output directory):
`python tests/d029_baseline_probe.py --case sequential --output <disposable-evidence-directory>`.
Supported cases are shown by `--help`. A current single-Run smoke execution of this portable tool completed
successfully. The original 10-case baseline used the same lifecycle body adapted from the supplied probe;
additional wrong-CSRF/reference/failure checks and actual Chromium acceptance are separate evidence.

| Case | Engine entries | Successful history delta | HTTP statuses |
|---|---:|---:|---|
| single | 1 | 1 | [200] |
| sequential | 2 | 2 | [200, 200] |
| concurrent | 2 | 2 | [200, 200] |
| save-during-run | 1 | 0 | [200, 200] |
| stale-cas | 0 | 0 | [200, 200] |
| missing-csrf | 0 | 0 | [403] |
| cross-session | 0 | 0 | [403] |
| busy | 1 | 1 | [429, 200] |
| lost-response | 1 | 1 | [] |
| unknown-outcome | 1 | 0 | [200] |
| wrong-csrf | 0 | 0 | [403] |
| protected-reference | 0 | 0 | [200] |
| engine-failure | 1 | 0 | [200] |

`unknown-outcome` fault-injects the transport-facing executor timeout while allowing the actual calculation
to finish; it is not proof of a physical hard-deadline kill. `engine-failure` injects a thrown exception.
`lost-response` drops the HTTP response AFTER the actual canonical commit. Protected-reference and wrong-CSRF
checks compare digests of every persisted table before/after, with no changes. These baseline cases do NOT send a key.

Real Chromium rapid activation passed: one request/history row across repeated activations, including keyboard.
That React synchronous in-flight guard is local to the client; two independent HTTP requests still commit twice.

Root cause: Run has no durable request identity. Initial composite CAS checks current inputs, not prior Run intent.
An unchanged draft allows both engine executions and both final CAS checks to pass. `v2_atomic_run_commit`
appends a new history ID on every successful invocation. Admission limits capacity, not logical duplicates.
Freeze effective authority after canonical scenario/input/CAPEX/OPEX materialization, before engine admission.
Claim a new intent durably there. Reconcile already-known committed bindings BEFORE today's CAS instead.
Only the existing final financial transaction can bind the claim to a successful history ID.

## Status boundary

Release state: **RELEASE CLOSED**. See the release-state matrix in `D029_EXECUTIVE_REVIEW.md`.
Implemented and tested on PR #384 head: the canonical `POST /v2/workbook/run` intent lifecycle, the single-transaction
commit, startup schema, the React and Legacy clients and the governance successor. Not owner-approved, not activated:
the owner policies in `D029_OWNER_DECISION_REGISTER.md` remain candidates, `RELEASE_POLICY.enabled` is false, nothing is
deployed or merged. A request without `run_intent_id` keeps the released, non-idempotent behaviour.
