# F3.5-A Senior + Junior candidate acceptance

## Disposition and provenance

Independently accepted financial content; inert production capability pending activation.
Owner-approved scope: 37 exact candidate paths, including the separately approved
`financial_engine/financing/project_uses.py`, `financial_engine/book_basis.py`,
and the follow-up governance tests `tests/test_financing_f3_canonical_legacy.py`,
`tests/test_model_v2_released_engine_authorities.py`, and
`tests/test_developer_economics_v1.py`.
Baseline and independently rechecked live main:
`76b7215baf9dfe02d83382d6c33d01559eba9641`.
Branch: `feat/model-f3-5-advanced-debt`. The owner relayed explicit independent
acceptance of all 15 protected Git blobs in the reviewed candidate manifest.
`F3_5_A_JUNIOR_AUTHORITIES` adds those exact paths and SHA values only; every
historical authority map is retained unchanged. No production activation,
self-approval, merge or deployment is authorized. Final HEAD, Draft PR URL,
local test counts and exact-head CI evidence are recorded in the PR handoff.

The 14 accepted preflight tests are prior evidence, not implementation acceptance.
The two preflight amendment paths are sufficient; no tax, orchestrator, Senior
solver, construction allocator or depreciation engine changes were required.

## Implemented financial boundary

| Capability | Candidate authority | Limit |
| --- | --- | --- |
| Instruments | F3 collection, one Senior rank 1 and one Junior rank 2 | Explicit positive commitments, no providers or extra facilities |
| Construction | Dated draws through existing F3 contractual primitives | Fully drawn in construction; period overfunding rejected |
| Interest | Fixed cash interest, explicit ACT/360 or ACT/365 | No PIK, floating rate or invented default day count |
| Junior IDC | Validated dated cash ledger, distinct funded financial-cost asset | Explicit life and tax treatment; no reclassification as Senior IDC |
| Repayment | Existing level-principal/grace or bullet primitives | Exact operating maturity boundary; no automatic refinancing |
| Cash priority | Senior service, then contractual Junior service, then DA/sponsor | Missing payment cash fails before immutable Run commit |
| Gearing | Existing Senior capacity and separate explicit total-debt cap | Commitments are contractual, not a mixed bank-sizing solve |
| Tax | Junior interest in existing `other_interest_keur` authority | Ordinary existing policy only; ATAD/thin-cap activation rejected |
| IDC tax basis | Explicit exclusion or source-owned book-based policy at 100% | No universal deductibility assumption or alternative tax calculator |
| Statements | Separate Junior P&L expense, actual BS liability and PF cash service | Senior rows keep Senior-only meaning |
| Returns | Existing project and sponsor authorities consume reconciled cash | Project cash flows/IRR independent of Junior rate and life |
| Persistence | Existing versioned F3 snapshot, authorized CAS and scope identity | No schema, sidecar, migration or F3.6 editor |
| Export | Persisted Last Run identity, collection and policy digest binding | No export-time Run or mutable Working Copy substitution |

Unsupported: active SHL, reserves/DSRA/DSRF, VAT facility, mezzanine, Junior fees,
PIK, additional debt facilities, annual-period activation, typed interest
limitations, developer Uses and bank-sized mixed financing. These fail closed.

Application activation remains `ACTIVATION_ENABLED=False`. Candidate integration
tests enable it only inside isolated test fixtures. The existing sheet presents
this activation as unavailable, not as a working economic editor. Independent
production-activation approval remains a prerequisite to enabling the app path.

## Authority integration map

`JuniorProjectInputs` binds collection + Junior policy in serialization and input
hash. Each unchanged F3 instrument is passed independently to the existing debt
schedule primitives with its own explicit day-count. Only the actual Senior
instrument enters the Senior contract/kernel.

Dated construction draws produce Senior costs and a separate Junior cash-IDC
ledger. Canonical Project Uses independently recomputes Junior IDC from draws,
rejects tampered evidence and counts it exactly once. Equity funding is the
existing reconciled residual authority, not a balancing adjustment. Both debt
draw vectors enter the existing construction funding schedule.

Generic economic book basis and typed downstream book basis both carry the
Junior asset with explicit life. TaxPolicy alone determines whether that basis
is included for tax depreciation. Existing annual straight-line/day-fraction
logic is unchanged, including first/final partial periods; no catch-up plug.

Junior operating interest enters `PeriodInterestInput.other_interest_keur`
before the existing explicit Senior/tax/CFADS calculation. Actual contractual
service is compared with final Base CFADS for each period. G2C then records
Senior-only cash and post-Junior cash separately; Junior service is deducted
before distribution-account inflow. P&L and BS receive distinct typed Junior
rows. Construction rows never borrow operating Junior values merely because
period indices coincide.

Immutable Run evidence records the Junior ledger and IDC. The new integrity
check reads actual post-Junior waterfall cash rather than reconstructing that
cash from the same ledger. Last Run exports check immutable scope/hash/snapshot
binding plus both collection and policy digests, and reuse recorded statements.

## Numerical evidence

The local independent oracle covers 16 canonical runs: four verticals, two
day-counts, and both explicit IDC tax treatments. It uses Decimal dated interest,
draw-to-COD IDC, straight-line book/tax basis, ordinary tax reconciliation, cash
conservation and independently discounted sponsor cash flows.

| Maximum absolute residual | kEUR |
| --- | ---: |
| Junior IDC against Decimal | 1.1368683772161603e-13 |
| Junior operating interest | 5.684341886080802e-14 |
| Book/tax depreciation | 9.094947017729282e-13 |
| Taxable income / tax | 1.8189894035458565e-12 |
| Senior-to-Junior cash conservation | 9.094947017729282e-13 |
| Sources minus Uses | 2.9103830456733704e-11 |
| Balance Sheet | 6.571099220309407e-11 |
| Sponsor discounted NPV at published XIRR | 2.251735028912554e-10 |

All 16 runs: Integrity PASS; terminal Junior balance zero. Existing tolerances
and goldens are unchanged. Oracle tax arithmetic independently recomputes the
ordinary formula and CIT using recorded LCF utilisation; this is not an
independent implementation of the entire tax-loss vintage engine.

Example Solar ACT/360, explicit IDC exclusion: hard CAPEX 33,000 kEUR; Senior
1,980; Junior 1,320; Senior IDC 93.28; Junior cash IDC 62.11333333333333;
total Uses 33,175.193333333336; additional equity 29,375.193333333336.
Project XIRR 0.11767978038866954; Pure Equity/Total Sponsor XIRR
0.11418492122270787. No active SHL means those sponsor returns coincide.

## Inactive exact parity

Complete canonical result serialization, not selected KPIs, was SHA-256 compared
before/after edits at the same baseline. All six digests are identical:

| Case | Before = after SHA-256 |
| --- | --- |
| Solar | a24ac63a228a63e9ddecf6c2f7bbe094d4633f56edc0cdb9c6c5f1af92e0f481 |
| Wind | b8f2dee7eaa64272f209a9e554e64bfb06d3f702d7d08151060ac0e93c696333 |
| Data Center | bfbdd3d64bfccb36242fe5a78172e24d9f9dcb03e98c375629b729a738217bed |
| EV | 45b428a84725864fb39e6d15f37c2a0b79c85ac5081b2e8c0192e3e704e4f545 |
| Two-Senior Solar | 5f101488ed30e6364b75274a921b96bcbb71f1377aa185271919ebbdb9a2b42d |
| Two-Senior Wind | 06af88ed77a019844e4a218e9a180b905560c4ffba0768e3645ff9e5dbc02265 |

## Lifecycle and negative acceptance

Actual authenticated Solar/Wind routes test CAS Save/reload, dirty/STALE state,
canonical Run, persisted Integrity PASS, immutable Last Run binding, XLSX Junior
rows, export without engine execution, changed Junior interest and distinct new
Run identity. Protected references, foreign owners/projects, stale CAS, foreign
scenario writes and policy/collection tampering are rejected.

An unfundable first-period Junior bullet raises
`F35_CONTRACTUAL_SERVICE_CASH_SHORTFALL`; the route shows the existing safe error
banner. Prior Last Run result, identity and snapshot remain unchanged.

Scenario-only activation does not become Base financing. Existing scenario
restore retains the original immutable summary. Because the F3 JSON snapshot
includes all financing scopes, editing a scope can make a restored Base Run
STALE; the existing resolver then refuses Last Run reconstruction if its input
snapshot is unavailable. This limitation is tested and preserved, not converted
to false CURRENT or fixed through unauthorized persistence changes.

Other negatives cover unfunded maturity, total-debt cap, unsupported tax/reserve
combinations, invalid policy, missing/inconsistent/NaN/recomputed-tampered IDC,
wrong useful life, and independently altered post-Junior cash. Valid grace and
bullet schedules are consumed by the actual canonical Run.

Junior grace must end exactly on an operating-period start; ambiguous bullet
grace is rejected. The first synthetic fixture inherited a 12-month grace from
the old two-Senior fixture although March COD does not align it to the semiannual
axis. The Junior-only fixture was corrected to explicit zero grace. A separate
canonical month-end-COD case independently tests a valid 12-month grace. The
existing two-Senior fixture and runtime remain unchanged. Cash shortfall errors
carry period, Base CFADS, Senior/Junior due, available cash and unpaid principal
diagnostics; no failed Run publishes a successful ledger or return.

## Changed-file inventory

Protected candidate paths (15):

- `finco_core/inputs/junior_debt.py` (new typed opt-in and funded IDC)
- `finco_core/inputs/_models.py` (opt-in composite input hash)
- `finco_core/inputs/serialization.py` (strict typed round-trip)
- `financial_engine/financing/junior_debt.py` (new bounded composition)
- `financial_engine/financing/project.py` (opt-in dispatch)
- `financial_engine/financing/generic_product_policy.py` (explicit policy boundary)
- `financial_engine/senior_debt/project_adapter.py` (Senior-only contract)
- `financial_engine/shareholder_waterfall/contracts.py` (typed Junior rows)
- `financial_engine/shareholder_waterfall/model.py` (Junior priority and cash)
- `financial_engine/financial_statements/contracts.py` (distinct Junior lines)
- `financial_engine/financial_statements/assembly.py` (P&L/BS/PF handoff)
- `financial_engine/project_returns/contracts.py` (Junior terminal evidence)
- `financial_engine/project_returns/model.py` (terminal liability boundary)
- `financial_engine/financing/project_uses.py` (verified IDC counted once)
- `financial_engine/book_basis.py` (distinct Junior asset)

Application paths (9):

- `app/workbook/junior_debt_config.py` (new, release-closed CAS bridge)
- `app/workbook/multisenior_config.py` (existing F3 scope dispatch)
- `app/api/project_runner.py` (immutable evidence serialization)
- `app/run_integrity/evidence.py` (actual recorded Junior vectors)
- `app/run_integrity/checks.py` (additional opt-in conservation check)
- `app/services/export_service.py` (historical authority binding)
- `app/export/clean_statements_adapter.py` (Junior BS projection)
- `app/export/institutional_workbook.py` (recorded Junior statement lines)
- `app/excel_export.py` (reuse canonical Junior statements)

Four new tests: `tests/test_financing_f3_junior_contract.py`,
`tests/test_financing_f3_junior_runtime.py`,
`tests/test_financing_f3_junior_workspace.py`,
`tests/test_financing_f3_junior_governance.py`.
The follow-up also changes `tests/test_financing_f3_canonical_legacy.py`, retaining
its original legacy mapping, nonactivation and serialization assertions. Exactly
three consumers are added to its existing exact-path import-ownership set:

- `app/workbook/junior_debt_config.py`: collection validation and strict CAS payload binding.
- `financial_engine/financing/junior_debt.py`: typed collection, instrument and repayment contracts.
- `finco_core/inputs/junior_debt.py`: typed commitments, maturity, rates, repayment and validation errors.

Five synthetic negatives run the original guard against unauthorized app, engine,
core and domain consumers, including an approved-path lookalike. No prefix or
namespace exemption is introduced. Total scope: 37 changed paths in the 37-path
envelope, with no added financial or application changes since independent review.
The reviewed 29-file snapshot is supplemented by exactly eight existing
governance/helper paths: the two shared helpers, F3 two-Senior governance,
WF-04 governance, WF-07 governance, canonical legacy import ownership, released
Model V2 engine authorities and Developer Economics governance.

The Junior governance test no longer requires
whole-file identity after a future independently approved release. Instead, six
historical authority maps must retain their exact baseline values, including
F3.1, F3.2-F3.4, WF-04 and WF-07. Historical and new path/blob cases separately
prove original-content acceptance, changed-content rejection, missing-ref
rejection and acceptance of the original historical ref. Five unrelated-path
negatives reject unauthorized and lookalike paths. Release-closed activation
remains asserted. Finance Integrity's existing broad stream ownership cannot
bypass the new content pin: each F3.5 path must match a reviewed release blob.
Legacy positive HEAD checks use F3.5 exact-pin precedence only where an accepted
successor exists. Developer Economics removes just the newly authorized
shareholder-waterfall path from its unconditional negative set and positively
requires the exact accepted SHA. All other tests in that file are unchanged;
the Junior negative ring rejects altered content at the same path. No blanket
namespace exemption or historical pin refresh is introduced.

## Independently accepted release pins

Provenance: `candidate-blob-manifest.json` supplied in the independently reviewed
2026-10-12 candidate package. All 15 hashes were independently reproduced from
the supplied source bytes and subsequently explicitly accepted for release
governance. These pins are not generated from arbitrary current HEAD content.

| Exact path | Accepted Git blob |
| --- | --- |
| financial_engine/book_basis.py | 1281cc05a5638714e78279968ee739d9af2cfc02 |
| financial_engine/financial_statements/assembly.py | 778610e8bb5c2a61b022f147a601cc0f02d66982 |
| financial_engine/financial_statements/contracts.py | f5a15655d58b1d4a5ac7c02f0cdde5bc2a069358 |
| financial_engine/financing/generic_product_policy.py | 2894334e7241c4ac9f8967d4ce4ca6ce77a32fa0 |
| financial_engine/financing/junior_debt.py | 2205cfbcca33889975c964a5748797c82af5792f |
| financial_engine/financing/project.py | 30536cec8779fdb6a490d82fd80bfce2c09e16fe |
| financial_engine/financing/project_uses.py | 489cbcc800158326a5b3764aef25514b6ad6ab48 |
| financial_engine/project_returns/contracts.py | 2a43b4e82db2fa6eee956970c5a5c6087245b36f |
| financial_engine/project_returns/model.py | 711bf15d954c5e20cce13fd6df1067e5d00182e2 |
| financial_engine/senior_debt/project_adapter.py | a73611a117f0c04ecc7bd7350eac64456520f265 |
| financial_engine/shareholder_waterfall/contracts.py | 19cff0f003a9fdf8921cae8e5c18e703d93e2408 |
| financial_engine/shareholder_waterfall/model.py | e3473e1a2064c8310e41b434da2b0aff9d5753b8 |
| finco_core/inputs/_models.py | b896d3c071ee22c1c82c48f23d4c169e058c7a7b |
| finco_core/inputs/junior_debt.py | ef63e3355f30541a69b503a3a2e2c02feaf1803f |
| finco_core/inputs/serialization.py | 31f70570376b2f5b50ece583c54c1d9811e90a3c |

## Test status and review gate

Python 3.12.10 / Windows, plugin autoload disabled, isolated disposable SQLite.
TestClient requires local loopback outside the sandbox; no staging service or
staging database is used. Unknown `asyncio_mode` under disabled plugins is a
configuration warning, not a skipped financial test.

The initial reviewed checkpoint had 72 focused PASS and 442 broader PASS plus
one import-ownership failure. The follow-up owner amendment authorizes that
test path only; no financial content changed to resolve the failure.

Pre-release-map combined acceptance: **562 passed, 0 failed, 0 skipped**, pytest rc=0,
normal process return, 526.07 seconds. Of these, 92 are F3.5 candidate tests and
470 are existing targeted regressions, including five added import negatives.
The separate first governance/import check passed 88 tests; it overlaps the
combined ring and is not added again to the total.

Final release-governance acceptance on commit
`8a1cf33ae6cdaa24537ebd235b361164ea6aa655`: **683 passed, 0 failed, 10 existing
retired-marker skips**, pytest rc=0 and normal process return, 720.13 seconds.
F3.5 focused: **108 passed, zero skips**. Existing targeted regressions: 575
passed, with the ten unchanged conditional Model V2 scope tests skipped because
the epic marker is absent. Nine report "Model V2 epic scope marker absent
(retired or not started)"; the branch-scope test reports "scope marker absent".
No skips, xfails, tolerances or golden changes were introduced.

| Suite | Passed |
| --- | ---: |
| F3.5 Junior contracts | 17 |
| F3.5 Junior runtime / Decimal | 38 |
| F3.5 Junior workspace / CAS / immutable export | 7 |
| F3.5 Junior historical/release governance | 46 |
| F3.1 canonical contracts | 131 |
| F3 canonical legacy / import ownership | 58 |
| F3 historical governance | 10 |
| F3 two-Senior runtime | 32 |
| F3 two-Senior governance | 15 |
| F3 existing workspace | 39 |
| WF-04 numeric precision | 32 |
| WF-04 governance | 9 |
| WF-07 governance | 13 |
| Senior maturity integrity | 42 |
| Run integrity | 36 |
| Sponsor return semantics | 12 |
| Statements / debt trace | 36 |
| Revenue numerical validation | 5 |
| Full Developer Economics module | 95 |
| Model V2 governance | 2 (10 existing retired-marker skips) |
| Released Model V2 engine authorities | 8 |

The independent 16-case evidence was regenerated without changing its oracle;
all numerical values remain identical to the reviewed JSON. Inactive four-vertical
and two-Senior full-result fingerprints are rechecked separately, not refreshed.
Source scan, compilation and tracked/untracked diff hygiene are separate gates.
No scanner, tolerance, golden, skip or xfail change is made.

All 15 protected candidate blobs and all nine application blobs must continue
to match the reviewed manifest exactly. Original review artifacts are retained;
follow-up artifacts use distinct filenames and record the three test/report-only
changes. Governance release changes are separately listed above; all six
historical authority maps retain their original values.

The 683-pass result includes the complete Developer Economics module,
Model V2/F3/WF-04/WF-07 governance and financial regressions against actual
candidate HEAD. The final reporting commit changes this document only, not
tested Python content or accepted financial/application blobs. The Draft PR must
also obtain the five mandatory exact-head workflow results, full Public pytest
rc=0, normal supervisor exit and uploaded evidence. Pending or partial output
must never be reported as GitHub CI acceptance.

Disposition: **inert financial capability for independent final review only**.
Financial exact content is accepted; production activation, merge and deployment
remain unapproved. Normal main synchronization only if needed. No schema change,
financial modification, numerical relaxation or historical authority repinning.
