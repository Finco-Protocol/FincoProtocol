# F0-P0 Correction A: Senior maturity publication protection

## Provenance and review gate

- Actual starting main: `943a38658fe1571eafd36f31dde14ed69bb388e1`.
- PR #230 and PR #232 were independently confirmed merged before work.
- Parallel PR #231 was OPEN/DRAFT at `3a3c6f14ef5bb2903e61abb741c340f806aea228`.
- Isolated branch: `fix/model-f0-senior-maturity-integrity`.
- Final feature HEAD, Draft PR URL and exact-head CI run IDs are recorded in
  the PR description after commit; this document does not claim its own hash.
- Disposition at submission: **NO MERGE** pending independent financial review
  and all five exact-head CI workflows. No deployment is authorized.

## Independently reproduced P0

The original F0-B immutable Solar/Wind inputs were executed on the actual
starting main **before production edits**, not inferred from the prior report.
Both use GEARING_CAP, 95% gearing, eight-year tenor and DSCR_SCULPTED repayment.
The same unchanged input snapshots were then executed with this correction.

| Evidence, kEUR unless stated | Solar before | Wind before |
| --- | ---: | ---: |
| Opening Senior | 34464.50532587937 | 46947.5962694057 |
| Actual cumulative principal | 13552.271280653085 | 23302.7025918088 |
| Unpaid at contractual maturity | 20912.234045226287 | 23644.893677596927 |
| Contractual maturity period | 18 | 19 |
| First post-maturity BS Senior | 0.0 | 0.0 |
| Terminal classification | OUTSTANDING_AT_MATURITY | OUTSTANDING_AT_MATURITY |
| Equity / Sponsor return status | OK / OK | OK / OK |
| Run Integrity | FAIL | FAIL |
| After correction | Typed rejection, same actual unpaid amount | Typed rejection, same actual unpaid amount |

The before/after input bundle SHA-256 is
`3b04a139b23f91150f2e376386dd277e989d124a4312a97b5e8a13fe2eeba199`.
This digest identifies evidence, not a new model input or financial golden.

## Root cause and authority chain

Canonical ProjectInputs -> generic financing policy -> Senior sizing and
repayment -> canonical G2C -> Senior terminal evidence -> application production
authority -> financial statements -> presentation -> V2 atomic Run commitment
-> Last Run / history / export.

The Senior adapter intentionally permits a solver balloon. That does not
authorize a maturity payment, refinancing, settlement or write-off. The canonical
Senior closing vector and `return_summary.terminal.senior` correctly preserve
unpaid principal. However, `financial_engine/financial_statements/assembly.py`
uses zero Senior outside its active axis, assuming a settled facility.
The G2C return metrics also have no complete material Senior-balloon settlement
authority. Consequently publishing their otherwise completed result is unsafe.

The earliest shared application boundary is immediately after policy-wrapped
G2C returns, before `assemble_decision_complete_financial_statements` and before
any successful `CleanProductionRun` can leave the production authority.

## Correction

`_require_settled_senior_maturity` in
`app/services/production_financial_authority.py` checks:

1. The existing typed Senior adapter's contractual repayment/maturity policy.
2. Complete, ordered, non-duplicate Senior period indices matching the canonical
   Senior axis and the operating periods selected by that policy.
3. Complete finite, nonnegative opening, principal, closing, interest and
   debt-service vectors; existing `1e-6` kEUR Integrity checks for commitment,
   opening/closing roll-forward, principal bounds and service components.
4. Actual maturity closing balance and the copied terminal/horizon evidence.
5. Contractual maturity index/date and a recognized terminal classification.
6. Genuine zero/microscopic-funded evidence for NOT_APPLICABLE under the
   existing canonical `1e-7` threshold; missing evidence is not zero.
7. Materiality under the adapter's existing absolute precision contract.

Material unpaid principal raises
`CleanProductionRunUnavailable("SENIOR_MATURITY_UNSETTLED_LIABILITY", detail)`.
Detail contains actual maturity period, unpaid kEUR and absence of complete
canonical settlement/refinancing/accounting authority. Invalid evidence raises
`SENIOR_MATURITY_EVIDENCE_INVALID`. Unsupported typed repayment mapping also
fails closed. No project-type or identity exemption exists.

The guard runs on **cache hits as well as new computations**. It adds no second
solver, does not change `permit_terminal_balloon`, does not modify balances,
and cannot force repayment, add proceeds, forgive debt or shift it to SHL/equity.

## Numerical precision and remaining P1

The existing Senior adapter absolute convergence threshold is `1e-4` kEUR;
its relative threshold remains `1e-9`. This publication guard consumes the
existing absolute threshold, not a debt-size-scaled allowance. No global
tolerance is changed. Statements/Run Integrity remain stricter at `1e-6` kEUR;
the canonical return terminal classification remains unchanged at `1e-7`.
For NOT_APPLICABLE, the canonical terminal summary legitimately reports zero
even when actual fully repaid funding was microscopic. Real gearing `1e-12`
and `2e-13` cases preserve this behavior, including the latter's actual
`2.740035779081904e-24` kEUR closing residue. No material debt can use that path.
An independent adversarial review also proved that zeroing a real balloon's
closing/terminal copies must be rejected by the repayment identity checks;
a committed actual corrupt-cache test locks that boundary.

A real 90%-gearing, 1.3x-target Solar case still returns residual
`2.3221237597681466e-5` kEUR and **Integrity FAIL / BALANCE_SHEET_IMBALANCE**.
Before and after outputs are identical, including that failure. The guard does
not label this residual settled, normalize it to zero or turn FAIL into PASS.
Reconciling tiny residual accounting remains a separate P1 correction.

The previously reported 16 MW / P50 / 10-year G2A handshake discrepancy remains
untouched. The equivalent-main acceptance also retains the existing SOLAR-27
rejection: expected `25074.78741066055`, actual `25074.787411513626` kEUR.

## Real economic before/after acceptance

51 unchanged snapshots were run cold, before and after. Comparison covers
complete effective inputs, Senior vectors/diagnostics, Sources & Uses, full
financial statements, G2C/Sponsor outputs, audit evidence and Integrity.
Only execution timestamps, elapsed time, checkout provenance and traceback line
numbers are excluded; financial amounts and rejection details are not excluded.

- 48 previously executed, non-P0 cases: **zero differing financial fields**.
- One existing numerical rejection: identical status and error values.
- Two original P0 cases: now rejected before publication.
- The 48 include four reference technologies, 24 equivalent-main F2 typed cases,
  five Developer Uses cases and 15 additional Solar/Wind financing variations.
- Coverage includes P50/P90, scalar/period DSCR, gearing, tenor, interest,
  construction fees, NONE/CASH_DSRA/DSRF, automatic peak reserve and developer
  reimbursement/fee. Existing constraints and unsupported combinations remain
  operative; zero change is not falsely advertised as a new capacity response.

| Reference | Senior before = after, kEUR | Debt service before = after, kEUR | Project IRR before = after | Terminal | Integrity |
| --- | ---: | ---: | ---: | ---: | --- |
| Solar | 26983.331676476686 | 36312.50184724573 | 0.11767978038866954 | 0 | PASS |
| Wind | 36505.15795948399 | 47493.4692165394 | 0.13310997970744148 | 0 | PASS |
| Data Center | 58410.96179501392 | 78112.916095281 | 0.023012141497371998 | 0 | PASS |
| EV Charging | 6497.019462566068 | 7700.678712039187 | 0.18019413353035196 | 0 | PASS |

Evidence is kept outside the repository in `Finco-f0-p0-evidence-20261009/`:
`acceptance_inputs.json`, `before/`, `after_final/`, `comparison_final.json`, `compare.py`,
and process logs. No source workbook, generated binary or runtime DB is committed.
The executable committed regression cases independently recreate the original
P0 configuration using the canonical synthetic factories.

## Atomicity and consumer coverage

The authenticated V2 test uses a synthetic typed equity-only gearing/sculpted
baseline, the real existing scalar Save contract and the real canonical engine.
It does not substitute a financial result. Actual sequence:

Valid Run -> record Last Run/history -> Save gearing 95% and tenor 8 -> STALE
-> Run rejection (actual unpaid `21973.744912075996` kEUR) -> unchanged workspace,
Last Run RuntimeResult, snapshot ID, original summary and single history entry.
Changed Working values remain saved. No new history, certificate, financial
schedule or partial CAS commitment is written.

The existing V2 safe error banner remains unchanged and does not display raw
engine details. The test verifies the actual typed exception caught by the
route. User-specific maturity guidance can be integrated by F2 after approval;
this PR does not edit F2's router surface.

| Consumer | Protection / evidence |
| --- | --- |
| V2 Workbook Run | Actual authenticated rejected Run before atomic commit |
| Canonical `run_project` API | Same common authority; material balance raises typed error |
| Stateless model HTTP API | Actual canonical worker execution returns 503, no KPI payload |
| Waterfall/UI/values-only recalculation | Common production seam raises before result/export construction |
| Sensitivity | Real candidate returns error and no KPI dictionary |
| Goal Seek / decision support | Real candidate evaluator returns unavailable (`None`), not a successful metric |
| Historical V2 export | POST returns old committed P&L/Balance Sheet/Cash Flow cells; zero engine calls |

Historical export timestamps truthfully change when a new artifact is serialized.
The old Run identity and all statement cells remain unchanged. The guard does
not rewrite, retroactively reclassify or delete historical records. Previously
committed defective historical records are not silently repaired by this PR.

## Local validation

All commands used `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1` (the local environment has
an unrelated globally installed web3 pytest-plugin conflict).

| Focused ring | Result |
| --- | --- |
| `test_f0_senior_maturity_integrity.py` | 42 passed |
| M6, H1/H2/H3/H4B, Developer Uses, Financing F1 | 170 passed |
| Existing bankability, U2.1/F07-B/F07 exports, Goal Seek | 169 passed |
| Total focused, one final invocation | 381 passed, no skips, normal exit code 0 in 259.41s |
| 51-case before/after capture | Both exited normally; zero unexplained financial drift |

The old M6 high-gearing/sculpted test exposed another actual unsupported balloon
of `17545.520955323154` kEUR at period 32. Its production assertion now requires
the typed rejection; all underlying sizing/repayment assertions are retained.
This is the approved P0 acceptance change, not a changed golden or solver fix.

Changed Python files compile, diff hygiene passes and the unchanged public
safety scanner reports PASS. On Windows, unchanged vendor files required local
line-ending normalization to match their existing trusted Git-blob hashes;
no vendor content, hash or scanner change is part of this PR. The five GitHub
workflows remain mandatory exact-head gates, recorded in the live PR description.
Independent read-only adversarial review found no remaining guard defect after
25 real/synthetic checks; this is not final financial approval or CI acceptance.

## Scope and F2 follow-up

Only the production authority, its focused tests, the M6 production acceptance
assertion and this report are changed. ZERO diff in financial_engine, finco_core,
domain, schemas/persistence, workflows, locks, financial goldens, F1/F3 surfaces
and Radar/Protocol/Yield. No equation or repayment policy changes.

PR #231 is not edited or merged. After independent review and a separately
authorized merge of this correction, synchronize F2 by normal merge, run the
combined F0/F1/F2/equivalent-main ring, preserve the separate numerical P1,
require fresh exact-head CI and obtain independent financial sign-off.

**NO MERGE / NO DEPLOYMENT.** This is publication protection, not a completed
balloon/refinancing/accounting engine or a blanket bankability approval.
