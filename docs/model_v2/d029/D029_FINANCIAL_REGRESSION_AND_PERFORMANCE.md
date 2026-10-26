# D-029 financial regression and performance

## Bit-identical parity (real engine, real HTTP route)

`tests/test_d029_run_idempotency_http.py::test_keyed_run_is_bit_identical_to_the_released_keyless_run[solar|wind|data_center|ev_charging]`
runs each technology once without a key (released path) and once with a key and compares runtime summary, financial statements,
debt, tax, distribution, sponsor schedules, integrity evidence, composite hash, engine and workbook version as canonical JSON.
The only values that differ are the per-run snapshot id and the one digest covering it (`acquisition_source_candidate_v1.binding.snapshot_id`,
`.digest`, `financing_evidence.run_binding.snapshot_id`); all four technologies pass. No formula, solver, tolerance, golden value or
native V11 code changed.

## Route latency, before (main `36edeeb`) vs after (PR head), in-process ASGI, thread executor, n = 6 per technology, median ms

Non-HTMX keyless request (no UI rendering), two interleaved rounds:

| Technology | main r1 / r2 | PR r1 / r2 | PR keyed (JSON) |
|---|---|---|---|
| Solar | 64.1 / 65.0 | 76.6 / 76.6 | 86.6 |
| Wind | 73.2 / 73.8 | 80.2 / 70.6 | 89.9 |
| Data Center | 66.0 / 59.5 | 67.4 / 66.0 | 93.9 |
| EV Charging | 85.7 / 65.6 | 64.7 / 67.3 | 92.8 |

HTMX keyless (full post-run UI render) was also measured: main 247-313 ms, PR 215-314 ms (differences are within run-to-run noise;
single-digit-percent shifts are not distinguishable at n = 6). Keyed requests add the ledger work: roughly +10-25 ms over the keyless
non-HTMX path (reservation, start, fence check, finalize inside the commit, read-back). Reconciling an existing intent (replay) runs no engine.
The earlier isolated ledger micro-benchmark (`evidence/D029_LEDGER_PERFORMANCE.json`) remains the per-operation reference.
Measurement scripts are scratch tooling (not committed); numbers are from a shared 4-core container, not a production host.

## Status boundary

Release state: **RELEASE CLOSED**. See the release-state matrix in `D029_EXECUTIVE_REVIEW.md`.
Implemented and tested on PR #384 head: the canonical `POST /v2/workbook/run` intent lifecycle, the single-transaction
commit, startup schema, the React and Legacy clients and the governance successor. Not owner-approved, not activated:
the owner policies in `D029_OWNER_DECISION_REGISTER.md` remain candidates, `RELEASE_POLICY.enabled` is false, nothing is
deployed or merged. A request without `run_intent_id` keeps the released, non-idempotent behaviour.
