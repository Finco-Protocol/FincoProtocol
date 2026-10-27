# FIN-VAL — implementation and financial parity

## Implemented application scope

- `app/input_adapter.py`: explicit rate-unit check, strict scalar validation, exact canonical-unit identity fast path and exactly one percent conversion; unversioned saved scalar pricing fails closed.
- `app/persistence/projects_repository.py`: human-percent baseline rates and explicit provenance for runnable reference/default seeds; Storage pricing is unchanged.
- `app/services/project_library_service.py`: NEW canonical Solar/Wind/DC/EV Working Copies receive corrected rate and marker in their copied snapshot, without updating the reference.
- `app/v2/router.py`: interest display formats the declared human percentage, including sub-1% rates; unverified-rate fields are read-only. No unrelated percentage semantics are changed.
- `app/workbook/update_service.py`: individual and batch field application require and retain verified rate provenance; existing atomic CAS writers remain unchanged.

The metadata is already in the snapshot when a Save begins. Individual Save updates the rate while retaining metadata in that same transaction. Batch Save changes only approved financial keys; it cannot invent metadata for an ambiguous existing record. No second metadata persistence call, migration, formula change or financial tolerance change was introduced.

## A. Unchanged economic inputs

For each of Solar/Wind/DC/EV, reapplying the factory's actual flat rate as human percentage preserves the typed ProjectInputs exactly. The source factories, engine, solver, tax, sponsor formulas and all financial tolerances have zero diff. Existing H1/H2/H3/H4b/F3.9/reference and D-029 tests are included in the 313-pass regression evidence. Canonical native identity is separately subject to compiler availability; local GCC 14.2 does not match the approved GCC 13.3 build, so native-executing checks are explicitly skipped, not counted as passes.

## B. Intentionally changed inputs

The following disposable 20MW cases change economics. No bit-identical outcome is claimed. First-period and total interest below are kEUR; IRRs are decimal ratios. Full annual interest, debt service, CFADS, baseline and corrected returns are in `evidence/financial/*.json`.

| Case | Baseline human % | Saved human % | Typed ratio | First interest | Total interest | Equity XIRR | Sponsor XIRR |
|---|---:|---:|---:|---:|---:|---:|---:|
| data_center-rate-0.056 | 6 | 0.056 | 0.00056 | REFUSED | REFUSED | unavailable | unavailable |
| data_center-rate-0.56 | 6 | 0.56 | 0.0056 | 311.7640644 | 4312.196826 | 0.02592251988 | 0.02879559849 |
| data_center-rate-5.6 | 6 | 5.6 | 0.056 | 1762.045532 | 20609.70328 | -0.03555751564 | 0.02019448757 |
| data_center-rate-9.0 | 6 | 9 | 0.09 | REFUSED | REFUSED | unavailable | unavailable |
| ev_charging-rate-0.056 | 6 | 0.056 | 0.00056 | 7.179579169 | 51.17646281 | 0.6806322054 | 0.2030726791 |
| ev_charging-rate-0.56 | 6 | 0.56 | 0.0056 | 71.85203324 | 520.8043878 | 0.6767640544 | 0.2020661742 |
| ev_charging-rate-5.6 | 6 | 5.6 | 0.056 | 725.0263064 | 6404.301739 | 0.6212265039 | 0.1895917298 |
| ev_charging-rate-9.0 | 6 | 9 | 0.09 | 1023.027906 | 9241.168061 | 0.5791366238 | 0.1691478475 |
| solar-rate-0.056 | 5.5 | 0.056 | 0.00056 | 1.94264613 | 31.59140597 | 0.2864734792 | 0.1531511058 |
| solar-rate-0.56 | 5.5 | 0.56 | 0.0056 | 19.46286385 | 326.5678045 | 0.2848454418 | 0.1519444155 |
| solar-rate-5.6 | 5.5 | 5.6 | 0.056 | 200.5544934 | 5243.159824 | unavailable | unavailable |
| solar-rate-9.0 | 5.5 | 9 | 0.09 | 271.4382671 | 8173.979184 | 0.1599961905 | 0.0987672836 |
| wind-rate-0.056 | 5.5 | 0.056 | 0.00056 | 5.4799728 | 111.4005407 | 0.2488746632 | 0.1178689539 |
| wind-rate-0.56 | 5.5 | 0.56 | 0.0056 | 55.28877654 | 1175.842266 | 0.2437160094 | 0.1159918582 |
| wind-rate-5.6 | 5.5 | 5.6 | 0.056 | 459.7350697 | 13100.31498 | 0.1419378536 | 0.07959002537 |
| wind-rate-9.0 | 5.5 | 9 | 0.09 | REFUSED | REFUSED | unavailable | unavailable |

All 16 cases verify correct saved/displayed/typed units. Thirteen produce complete numerical schedules. Three intentionally different input combinations are rejected by unchanged financial authority:

- Data Center 0.056%: `G2A_FIXED_SOURCES_EXCEED_TOTAL_PROJECT_USES`, excess 3169.529490977 kEUR. Lower interest changes debt sizing/uses; the configured fixed funding no longer reconciles.
- Wind 9%: `SHL_MATURITY_RESIDUAL_FAILS_CLOSED`, residual 9032.890315327104 kEUR at maturity period 57.
- Data Center 9%: same SHL refusal, residual 9807.288823047207 kEUR at maturity period 43.

No output was fabricated for rejected cases, no solver/tolerance was relaxed, and no historical Run was promoted from those direct diagnostic failures. Some feasible cases legitimately return unavailable IRR; this is recorded as unavailable, not zero.

## Independent numerical evidence

The new regression independently reconstructs every operating-period senior interest as Decimal(opening debt) × Decimal(human rate)/100 × actual days/360 or /365, using raw typed period dates and explicit convention. It checks debt service = interest + principal and aggregates annual interest with end-exclusive dates. Assertions use the existing financial precision scale (1e-8 kEUR for independent arithmetic), not relaxed engine convergence tolerances. Snapshot/API equality alone is not the oracle.

New real HTTP acceptance covers keyless and D-029 keyed Runs in all four verticals. After a committed Run, an atomic batch rate Save leaves the original history row byte-identical; the next deliberate Run appends a distinct row. Individual and batch Save/reload cover all four required rates. Existing browser acceptance verifies the V2 legacy form and React canonical route workflow, including D-029 response loss and original binding.

## Regression and governance

Security tests retain reference refusals, operation/session-bound CSRF, cross-project ownership, stale composite hash and scenario guards. New tests cover legitimate sub-1% rates, repeated Save/materialization, ambiguous/forged units, unit-field mutation refusal, concurrent CAS winner, calibrated vector preservation and bankability ownership.

The SEC-02 successor adds exactly one new router blob; every original 112-pin map, FIN-VAL B2/C1 layer and D-029 layer remains unchanged and individually admitted. Existing structural negative tests still detect missing/reordered CSRF, reference, Run reservation and commit gates. One non-golden EV fixture gains explicit provenance for its already-declared 6% rate; no assertion or expected financial number is removed or changed.

## Limits

The newer canonical Working Copy path is corrected. Older unversioned records and `main_web.py` producers remain a rollout blocker requiring an exact-path/record owner disposition. The Financial Owner clarified that work should continue isolated and PR handling be revisited later; no new PR, push, hosted CI, merge or deployment is claimed. Local source/tree evidence and all final test outcomes are in `FINVAL_FINAL_CI_AND_REVIEW.md` and the evidence manifest.

## Final consolidated execution and actual Chromium rate proof

The final 40-module local batch passed **1,115 tests, zero failures**, in the time recorded in local-acceptance.xml on committed code subject `4050c51d4b5337c93fffe6338a4092819850357b` / tree `90c54c9d88ed2d82914c297793d1662993db1be2`. The worktree was clean at execution start. Earlier failures are retained only as reproduction/development evidence; the final batch includes the corrected fixtures and all 45 rate-contract tests plus 24 numerical/history tests.

Independent Chromium Save/reload proof also covers every vertical: fresh Solar/Wind editable 5.5 and DC/EV 6; enter 0.056, Save, reload, displayed API 0.056%, typed ratio 0.00056, history remains empty. Eight actual screenshots and per-vertical observations are in `evidence/browser-rate-proof/`. This closes the original browser-to-typed reproduction chain without React component changes.

## Historical reference bootstrap preservation

A final source review identified that the pre-existing reference reconciler would otherwise write a changed scalar seed representation into existing protected workspaces. The authorized project-library path now retains existing reference rate/provenance fields exactly while constructing the current canonical comparison snapshot. New copies still receive the correct new unit contract. A historical-producer fixture creates old-format references before the correction is exercised; re-bootstrap and four new clones leave all pre-existing reference project/workspace/scenario rows unchanged. This guard and related reference acceptance passed 96 tests; it is also included in the final consolidated batch. No source reference or existing history is automatically repaired.
