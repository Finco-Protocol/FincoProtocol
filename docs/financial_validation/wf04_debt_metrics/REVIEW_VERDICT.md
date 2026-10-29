# WF-04 — review verdict (short)

**Status: DRAFT PR, not merge-ready.** Merge, deployment and release remain with the Financial Owner / independent reviewer. Exact-head CI is recorded on the PR (this file cannot contain its own head).

## Correction A (this push)
CI-A: the Public Safety collection-skip failure (exact delta: the standalone WF-04 browser module) is fixed by running the browser acceptance inside the existing mandatory Chromium role (274 → 287 nodes, all 287 pass locally); a real regression the role caught (the Financing tab list) is fixed with an exact, reviewed expectation update. UX-A: Period Status Matrix replaces the OPEN/LOCKED tiles. LABEL-A: `Minimum DSCR`. See `CORRECTION_A_CI_AND_PERIOD_MATRIX.md`.

## Implemented (this PR)
* Two persisted, user-editable contractual DSCR multiples — `Minimum DSCR (EoD threshold)` and `Contractual DSCR (covenant)` — through the existing authorised writers (per-field and batch; CSRF + content-hash CAS unchanged). No third field, no default, no ordering rule.
* Each committed Run records the terms saved when it was committed, inside its immutable identity (same atomic transaction, fail-closed). Older Runs read `NOT_RECORDED` → `UNAVAILABLE`; nothing is backfilled or read from the Working Copy; existing Last Runs stay `CURRENT` after deployment.
* Strict raw-double evaluation (`actual < threshold`, equality is no trigger) of the EoD condition, the covenant and the independent coverage (< 1.00x) conclusion, verified against a stdlib-only oracle on real Runs, 4 technologies, with the evidence digest verified before any verdict is drawn.
* Run / Integrity / Credit are separate axes; Integrity logic is untouched; no payment-default, cure/grace, profitability or bankability wording is produced.
* Adaptive ratio display (0.9951 never reads 1.00x; one-ulp breaches print exactly).
* React **Debt Metrics** workspace (covenant monitor, KPI row, DSCR/LLCR profile with gaps, distribution & reserves, Excel-like period schedule with raw CSV export), linked from Overview, Financing, Results and Credit.
* Exact-source governance: closed cohort `tests/wf04_scope.py` + manifest, named predecessor re-pins with preserved history, negative controls, and the reviewed protected-test updates in `OWNER_PROTECTED_PATH_EXECUTION_LEDGER.md`.
* Zero numerical change: 11/11 engine cases byte-identical, 30/30 persisted financial blobs raw-identical before vs after.

## Proposed / deferred (not implemented, not approved)
* Facility-agreement testing convention (frequency, rolling-year ratios, calculation dates) — the one classification that cannot be asserted as a legal test; disclosed as a model convention.
* Persisting DSRA draw / required DSRA / DSRF drawings / a payment ledger (would let reserve-covered shortfalls and unpaid service become evidenced instead of `UNAVAILABLE`); per-period LLCR/PLCR series; lock-up threshold value.
* Certificate vN+1 / integrity attestation (Owner gate O4); any change to sizing, `GEARING_CAP`, SHL, reserves, cash sweep, maturity, native engines.

## Real blockers / conditional gates
1. **#397 (Save All)** is unmerged: the combined Save All + Debt Metrics browser acceptance, the ≥50-input body and the request-id/idempotency cases are **NOT RUN**. When #397 merges the bundle must be rebuilt once from the merged sources and `tests/fin_v2_cohorts.py` / the shared manifests reconciled (both PRs touch them).
2. Pre-existing failures that also fail on clean `main` (listed in the acceptance matrix §C) are not fixed here.
3. Independent finance/security/UX review and exact-head CI are required before merge.
