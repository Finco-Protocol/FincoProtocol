# PR #394 staging corrections (F1–F10)

Base: `main` at the PR #394 merge commit. Scope: React presentation, the React read/projection routes, and the user-safe text of the
canonical Run outcome. No financial calculation, protected golden output, security guard or CI workflow is changed.

## Disposition

| # | Finding (staging acceptance) | Correction | Evidence |
|---|---|---|---|
| F1 | CAPEX/OPEX staged-line Save always returned HTTP 422: the client sent `amount_keur` (and `inflation_pct`) as JSON numbers, the canonical writer requires decimal strings | New `costLinePayload.ts` serialises the typed text (trimmed) as strings, validates plain-decimal form before sending, and omits a blank inflation (stored escalation kept). Server validation is untouched | `tests/test_pr394_staging_corrections_v1.py` (all four verticals, decimals, Save ≠ Run, numbers/invalid/stale/CSRF still refused); real-browser check on all four verticals |
| F2 | Bankability offered DSRF and forward-coverage reserve policies that are not released | `RELEASED_RESERVE_MODES = inherit, none, cash_fixed` is the only set that can be newly selected. A stored `dsrf` / `automatic_peak` configuration is shown read-only with the release limitation and is written back byte-for-byte when other settings are saved (never reset to NONE). The wording of the Senior facilities "not released" row is aligned | node-run tests on the real TypeScript; browser check of the gate, the preserved stored DSRF and the explicit Reset wording |
| F3 | Last Run XLSX export disabled with the false reason "No committed Run exists" after a CAPEX spending profile was saved | The export availability returns the real code and reason. When the Last Run export is closed for a monthly CAPEX profile, the screen offers the immutable historical export of that very Run (matched on its committed snapshot id). Working values are never exported as Run values | contract test (reason, fallback id equals the Last Run, XLSX bytes); browser download |
| F4 | A failed Run showed only "Run failed." | The typed JSON outcome carries a user-safe reason, an error code and the ledger reference (the same 8 characters are in the server log line). Implemented in `app/services/run_intent_service.py` only (`mark_failed` records the reason of the failure being handled; `payload` returns it once, to the request that owns it); `app/v2/router.py` is unchanged. Typed engine refusals reuse the route's reviewed wording; every other failure is generic. No traceback, SQL, path or exception text is returned; the cache is bounded and never crosses users, intents or replays | `tests/test_pr394_f4_run_failure_reason_v1.py` (leak probes, unknown failures, replay, cross-user, concurrency, bounded cache, D-029 payload shape and status unchanged) + the existing D-029 suites; browser check |
| F5 | After a lost Save response the editor could not tell whether the Save had committed; "Reload now" reloaded the whole page and discarded a draft that had not been saved | Reconciliation reads the canonical state without leaving the page and without re-sending. Same composite hash as before the Save: not committed, draft kept, retry allowed. Every attempted value equal: committed, draft cleared, nothing sent twice. Anything else: changed elsewhere, draft kept for review. A failed read keeps the editor locked. The CAPEX/OPEX batch has the same reconciliation by row version | node-run classifier tests; browser: committed, not committed (exactly one retry request), two-tab CAS conflict, batch committed and not committed |
| F6 | Scenario panel said only Tariff can differ, while What-if creates a scenario with another single change | Sentence now states that a What-if scenario carries its one reviewed change | browser |
| F7 | Unconfigured draft Senior facilities were rendered as 0 kEUR / 0.00 % | "Not configured" for placeholder facilities | node test, browser |
| F8 | Compare Projects showed no market and no MOIC | Market from the project's stored market code; Pure Equity / Sponsor MOIC read from the sponsor schedule summary the Run published (absent stays unavailable) | contract test, browser |
| F9 | The contract editor did not state its limits (R8, R20); R12 pack limits were silent | Plain limitation notes in the PPA editor and the credit decision panel | browser |
| F10 | Blank Agreement ID reached the server and returned the internal text "F4 requires explicit, nonblank identities" | Identity gaps are caught in business words before sending; the internal text is mapped if the server still returns it | node test, browser |

Retracted from the staging report: the missing unsaved-change guard on tab close was a measurement artefact; the guard exists and
fires (`beforeunload`) once the edit has been flushed.

## Not changed (separate, outside this correction)

* Signed Run certificates need a signing key and a trusted key registry (fail-closed by design).
* EV Sensitivity logs a 409 console line for its typed "not available" answer (cosmetic).
* "Set all targets…" uses a browser prompt.
* Registering a browser acceptance module for these corrections in the mandatory consolidation role changes a governed CI contract
  (`tests/test_rcux_governance.py` asserts the exact imports), so it needs exact-path governance and is not done here.

## Reserve boundary — Owner interpretation to confirm in review

The Financial Owner's decision was applied as: new selections limited to the existing fixed-amount cash reserve (`cash_fixed`), `none`
and "no override"; forward-looking coverage and DSRF/hybrid are gated. If `cash_fixed` is also to be closed, remove it from
`RELEASED_RESERVE_MODES` in `serializeBankability.ts` (one line, tests follow).

## Exact-source governance of this correction

Approved by the Financial Owner as an exact-path reconciliation (no wildcard, prefix or pattern admission). Root causes of the failures seen before
reconciliation (all governance failures were one cascade: the cohort registry reports "invalid" while any admitted path or pin is out of date):

1. two RC-UX cohort pins were stale (`app/v2/react_workspace_router.py`, `app/v2/react_compare_projects.py`);
2. two changed paths were owned by no cohort (`app/services/run_intent_service.py` and the new corrections test);
3. the pinned React sources and the bundle had new blobs.

Reconciliation, using the repository's own `refresh_pins.py` for 3 and 1, and a separate exact-blob cohort for 2:

* `RC_UX_SUCCESSORS` and the RC-UX manifest: only the blobs of the changed pinned paths moved (workspace router, `WorkspaceView.tsx`, `ModelExportView.tsx`,
  `ScenarioWorkspace.tsx`, the bundle; `react_compare_projects.py` in the manifest).
* New cohort `tests/fin_v2_pr394_corr_scope.py` (registered in `tests/fin_v2_cohorts.py`, manifest `docs/react_migration/pr394_corrections/SOURCE_SUCCESSOR.json`)
  owns exactly five paths by exact blob: `app/services/run_intent_service.py`, the cohort module and its negative-control test, and the two correction test modules.
* `tests/test_rcux_governance.py`: the three F3 router blocks appended to the reviewed wording list (rebuilt byte-for-byte from the #388 router), and one exact
  attribution of `run_intent_service.py` to the new cohort (only with exactly its pinned blob).
* Re-pinned inside the other cohort manifests only: `tests/model_mutation_security_successor.py` (fin_v2_3, d01) and `tests/fin_v2_cohorts.py` (r1).

No test was disabled, skipped or weakened; the negative controls (one byte, deletion, extra path, added or dropped manifest entry, non-ancestor base) cover the new cohort too.
