# Current state and root cause

Exact main `955952c1bc16b21ce342121c5224a19d3e105aa7` / tree `7bb70e037bae0cdef62ac3f6115d420089ad0d7d`; preflight 2026-11-17T11:04:51.731266+00:00. #456 accepted head 5c6dcfdb6b506e9e52013076e8a6c83964942ca0; merge 2026-11-17T08:22:33Z. Svi otvoreni PR-ovi spremljeni lokalno; #450 i #448 su paralelni CI prijedlozi, nisu trenutni main niti osnova ove grane.

## Routing

`tools/ci_v3_production.py:route_preflight` trusts only push/pull_request. FULL schedule/workflow_dispatch therefore routes sequential. `ci_v3_required_job.yml` calls ci_public_job.yml, one unsharded pytest, budget 19.200 s, grace 240 s. Eight configured workers are unused by FULL. Accepted-source reference authentication in V3 is a distinct authorization boundary: adding events to trusted=true does not solve bootstrapping.

## Repeated evaluation

Deep exact-source chain evaluation invokes thousands of Git subprocesses outside fin_v2_cohorts.call_scope. Same-source local A/B: A did not finish in 60 s, >=3.000 calls; B True in 11.648 s, 1.588 calls. Concurrent local collection/other diagnostics mean these are measurements of this host, not hosted forecasts. Fresh process per A/B variant, same immutable main commit; subprocess group reaped after A timeout.

Per-test caching is unsafe as a generic change: test_fin_v2_3_scope tests mutate the protected reader BETWEEN valid() calls in the same test. The proposed boundary is ONE read-only outer call; never hold a verdict across such a mutation. The candidate deliberately refuses an already-active outer cache.

## Historical hosted evidence (different heads)

- 43828509961 at c8b7e8133ec126df42a56e6e0879b1c1a7087c5c: outcome_reconciliation 16.008,5 s; fin_truth_b1/source_successor 2.496,8 s; 2.242/25.406 completed, budget timeout. The prior chat retained the original CI_PROGRESS excerpts.
- 43942925714 at 54043549b8caf3ac6a53e2e155aae5bb5435dffa: reference_admission_successor 13.121,6 s; active fin_v2_3_scope node 2.706 s when budget expired; 5.229/25.977 completed. Not current-main results.
- #456 report, earlier PR run 43946034993: WF03 4.809,1 s /185 nodes; Trust registry 4.278,7 s /159; U1 2.315,8 s /100. These three are a historical lower-bound scenario, not latest-head JUnit profiling.

## F01 and full-run clock

Current run 44047601863 started 08:32:25Z. F01 success artifact 14314201324, digest metadata sha256:7316172ee4aa618cbbf27c9a4b8712b7816a4e89689c59d60b7c401266fae654, created 09:00:18Z. This parallel lane already uses about 28 min of workflow elapsed; exact job start/end are in live jobs JSON. Record/aggregate overhead must fit alongside it, not be excluded from the 40-min promise.

No artifact content digest is claimed verified from metadata alone. Previous ZIP downloads returned storage Forbidden; no signed download URL, credentials or private material is included here. Current live run has no regression/record artifact yet. Collection and full execution counts must remain distinct.

## Source closure blocker

The clean central gate passed 47/47. A harmless workflow comment invalidated 44/47 and 24 mutation checks; restored main is untouched. At least seven independent terminal-layer FROZEN checks pin the V4 controls. A functional parallel controller is insufficient: source admission must extend those exact chains and historical negative controls. No existing pin or baseline was rewritten to obtain acceptance.
