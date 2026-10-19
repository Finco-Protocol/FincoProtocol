# V8-B1 solver successor proposal and approval request

Scope: exactly one path, `financial_engine/senior_debt/solver.py`, predecessor blob `6cf4a6cd9f149f271d4b61a60bb6b0aa70e4c9e0` (main
`5be8c4b1`), candidate blob `a3939cee010b799479d5f489c5a5ddfa60f0405a`. Recognition-only helper: `tests/v8b1_solver_candidate.py` with
`APPROVED = False`; no guard consumes it; any further byte or any other path loses recognition
(`tests/test_v8b1_solver_candidate_recognition.py`).

## The change (precise)

Two statements, in `_solve_dscr` and `_solve_gearing_sculpted`: `_compute_max_abs_diff(...)` is evaluated only when
`converged or iteration == max_iter` instead of on every iteration. `_schedules_converged`, the iteration path, the tax callbacks, rolls,
finalisations, tolerances, seeds, termination reasons and status semantics are untouched.

## Why it is diagnostic-only (proof)

1. The metric is a pure function and is only ever assigned to `max_abs_diff`.
2. `max_abs_diff` is read only to build `SolverDiagnostics` on a returning path: converged, `FINALISATION_NOT_CONVERGED`,
   `DSCR_SCULPTING_INFEASIBLE`, or `MAX_ITERATIONS_REACHED`. The last reports the value of the last iteration, which is why the last
   iteration is also computed. Earlier values are overwritten unread. No branch depends on it.
3. Evidence: 38 scenarios bit-identical to the unmodified solver (digests include `maximum_absolute_difference_keur`); a mutation to
   "computed only on convergence" fails the equivalence and max-iteration tests; real Solar and Wind Run digests identical in 9 paired cold
   samples; 828 solver, perf, financing, tax and integrity tests passed. Measured effect: metric calls 1692 to 220 (Solar), 2028 to 284
   (Wind); Run time Solar -4.7 % (median of 9), Wind -0.2 % which is noise and is not claimed as an improvement.
4. O1 (finalisation reuse) is proven not bit-identical and is excluded. No V8-B2 element (warm start, seeds) is present.

## Classification of the 11 failures on `dde4e699`/`a64d5c1f`

All 11 are triggered solely by the protected diff of that one path. The same 84 tests pass on unmodified main.

| Test | Class | Original contract |
|---|---|---|
| `test_ci_acceptance::test_frozen_financial_namespaces_unmodified` | current HEAD authorization | any protected diff must be the complete independently reviewed slice |
| `test_m3_two_driver_sensitivity::test_no_engine_or_financial_authority_files_are_touched` | stream-local no-financial-change | M3 stream changed no financial path (diff vs `origin/main` at the anchored head) |
| `test_radar_r4_tokenized_monitor_v2::test_no_frozen_financial_venue_or_collector_authority_changed` | stream-local no-financial-change | Radar R4 stream changed no financial path |
| `test_m7_rc3_candidate_successor` x3 | exact-content candidate successor | the integrated content is exactly the eleven reviewed M7 blobs; unlisted protected changes are rejected |
| `test_ppa01_candidate_authority` x4 | exact-content candidate recognition and current-HEAD anchor | exact PPA-01 candidate; M7 coexistence; the anchored head has no protected delta |
| `test_rc7_quarterly_research_isolation::test_protected_production_tree_...` | **immutable historical checkpoint** | PR #313 changed no production path |

Only the last is a mis-anchored historical assertion (moving HEAD vs the #313 base). It was re-anchored to `78e4c0ed..5be8c4b1` with the
same hunk as PR #320 (identical text, so the two PRs merge cleanly), which keeps the historical proof valid. The other 10 constrain the
current released HEAD and must stay effective; none was changed, no path was exempted, no historical pin was re-pinned.

## Approval request (not granted; nothing here authorizes anything)

To green the remaining 10 legitimately an independent party must:

1. Financial reviewer: confirm that candidate blob `a3939cee…` differs from `6cf4a6cd…` only by the two statements above and that the
   evidence in section "Why it is diagnostic-only" is sufficient to treat it as semantic-preserving. Record name, role and date.
2. Governance owner: authorize a bounded integration successor for exactly this path and blob (and the stream-local guards that diff against
   `origin/main`), by the repository's reviewed-successor process. No blanket exemption for `financial_engine/**` or for this directory.

Until both are recorded this PR stays Draft and the V8 performance integration (V8-A + V8-B1) is not performed.
