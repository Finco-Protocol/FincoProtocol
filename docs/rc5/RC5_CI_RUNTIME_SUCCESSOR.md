# RC-5 CI runtime successor (PR #302, Correction A)

Owner-approved CI limits only. This is not a financial approval and changes no product, financial-engine, golden, tolerance or
scanner behavior.

## Measured root cause

| Evidence | Value |
|---|---|
| `main` `97de3833` FULL UNSHARDED step | `06:35:48` to `07:54:47` = 4739 s of the 4800 s budget (61 s headroom) |
| PR #299 (`daa6f2bd`), 12,325 tests | stopped by the supervisor at 11,997 tests, 4,750 s of recorded test time (exit 124) |
| PR #300 (`5b906fab`), 12,306 tests | stopped at 11,815 tests (exit 124) |
| PR #302 (`07bffce4`), 12,395 tests, run `39029623599` | stopped at 12,071 tests, 324 remaining (exit 124); the active test was running normally |

No assertion failure was identified before any timeout; `mandatory-evidence` failed only because the full-test control job failed.
The suite grows with every merged workstream while `main` was already at the budget, so the failure is cumulative runtime, not a
financial regression. The largest single test, `tests/test_p6_correction_a.py::test_safety_scanner_does_not_flag_gitignored_db`
(about 150 s), is the frozen public safety scanner and is deliberately not optimized here.

## Change (exactly three values of `.github/workflows/ci_public_job.yml`)

| Value | RC-3 | RC-5 |
|---|---|---|
| `timeout-minutes` | 100 | 130 |
| `FINCO_CI_PYTEST_BUDGET_S` | `4800` | `6000` |
| `FINCO_CI_EXIT_GRACE_S` | `180` | `240` |

`FINCO_CI_STALL_S` stays `300`. Fit: `6000 + 240 + 900 s overhead = 7140 s <= 7800 s` (660 s slack). Blob
`0fa7e2bec303bb94053fe7799186e666dd1e06a9`.

## Governance successor

`tests/test_rc3_integration_inventory.py` pins the workflow (`POST_MERGE_PROTECTED`). The successor follows the RC-3 procedure: the
owning test now accepts the workflow after the pinned integration commit only when it is byte-identical to the accepted RC-3
workflow except for these three values (`rc5_workflow_successor_violations`), and only when its blob is the pinned RC-5 blob. Any
other byte, a different limit, a narrowed selection, softened evidence or a missing fit is rejected (see the parametrized negative
tests). The RC-3 successor tests are unchanged.

## Preserved

FULL UNSHARDED pytest, identical inventory, no deselection or new skips, normal process exit, complete JUnit, exact HEAD/tree
provenance, synthetic merge-tree equivalence, mandatory single-gate evidence. A genuine timeout still ends the supervisor with a
non-zero exit (exit 124); the job timeout still strictly contains budget, grace and overhead.
