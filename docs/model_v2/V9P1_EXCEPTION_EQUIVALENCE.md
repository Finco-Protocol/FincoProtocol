# V9-P1 exception and lifecycle acceptance

Baseline: `5996453b8d5bbfaa48bc06922fc6963cf94d2f84`.
This is execution-test evidence, not independent financial release approval.

The final local focused run completed normally: **140 passed, zero failures,
zero skipped**, Python 3.12.10 on Windows. The breakdown was 43 speculative
execution cases, eight financial/application cases, 15 successor-proposal cases,
42 existing Senior maturity cases and 32 existing WF-04 precision cases.

## Decision ordering

| Injected condition | Required and tested result |
|---|---|
| Capacity and funded calls both fail | Native capacity error is first; funded failure has no authority. |
| Funded and strict calls both fail | Native funded error is first. |
| Required strict call fails | Native strict error is raised at the unchanged service-budget trigger. |
| Unused speculative strict call fails | Its failure cannot reject the Run. |
| Funded-input construction fails before capacity is consumed | Retain the first actual exception and cause; raise only after capacity succeeds. |
| Capacity also fails before a deferred input error | Capacity error wins. |
| Required strict-input construction fails | Preserve the first exception, without rebuilding or changing its text. |
| Unused strict-input construction fails | Ignore it unless the original strict trigger requires that input. |
| Financial error in helper | Replay the original solver in the owning process; compare native type, text and cause chain. |
| Helper process crashes or task times out | Terminate/join only helpers, replay required canonical work in order. |
| Parent is cancelled while waiting | Abort helpers and propagate cancellation; do not start a replacement financial calculation. |

Named regression nodes are in `tests/test_v9p1_speculative.py`, including
`test_capacity_then_funded_then_strict_exception_precedence`,
`test_deferred_input_exception_preserves_the_first_exact_native_error`,
`test_deferred_strict_input_error_is_not_reconstructed`, and
`test_worker_failure_or_timeout_replays_native_result_or_full_cause`.

## Operational refusal and isolation

Tests exercise requested widths 0/1/2/3; invalid worker/timeout settings;
daemonic owners; denied process creation; current and parent Linux CPU quotas;
unreadable active quotas; changed or missing worker-source evidence; contended
owner locks; independent empty per-task engine scopes; and native serial replay.
An invalid timeout must not catch and repeat an actual financial exception.

The real existing application spawn worker is exercised, not replaced with a
mock. Normal executor shutdown must leave no stragglers. Abrupt owner death is
also tested: the helper parent-sentinel watcher must exit without relying on
interpreter finalizers. No application executor or deployment file was changed.

The financial tests compare complete financial and Run Integrity fingerprints
for the four legacy verticals and two isolated quarterly compositions at all
four widths. They deliberately permit helper primitives on a small test host;
separate tests enforce the unmodified production CPU admission rule. This is
not permission to activate quarterly production admission.

## Limits of this evidence

Local results are Windows results. Existing Linux GitHub Actions must execute
the same tests on the final published HEAD. A hosted runner is not proof of
the deployed systemd/resource configuration. No production compatibility,
Financial Owner decision, historical-pin successor acceptance, merge or
deployment approval is inferred from these tests.
