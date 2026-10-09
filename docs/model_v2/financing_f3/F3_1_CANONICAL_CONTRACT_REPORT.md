# F3.1 Canonical Financing Contract Delivery

## Provenance and scope

Baseline: `e84ffa65fa785af826642178854aafb4e0d5691c` on `main`.
Live verification confirmed PRs #229, #230, #231, #232 and #233 merged,
with no competing F3.1 PR at entry. Work uses an isolated
`feat/model-f3-multi-instrument-contract` worktree. Q1/Q2 are untouched.
Exact feature HEAD, Draft PR URL and exact-head CI conclusions are recorded
in the PR delivery body; no self-referential commit SHA is embedded here.

Only two new canonical modules, two new test files and this report are added.
There is no production import, ProjectInputs field, persistence, UI, worker,
Run hash integration, engine change, golden refresh or financial calculation.
The existing Senior maturity fail-closed authority from #233 is untouched.

## Implemented contract

`finco_core.inputs.financing_instruments` promotes the accepted F3 candidate
into immutable, recursively typed proposal records: collection, instrument,
provider, drawdown, interest, repayment and fee terms. InstrumentType is the
debt/equity/other discriminator; no second solver or economic class hierarchy
is introduced. Funding-source references, commitment authority, seniority,
provenance and classification remain explicit validated fields.

| Vocabulary | Contract disposition |
| --- | --- |
| Senior, Construction, Junior, Mezzanine, SHL, Bond | Typed debt proposals; interest and repayment terms required |
| Common Equity, Share Premium, Additional Equity | Typed equity proposals; no redemption or interest economics |
| Preferred Equity | Rejected with `F3_PREFERRED_EQUITY_DEFERRED`; F4 owns economics |
| Grant, Deferred Payment, Developer Reimbursement | Existing candidate labels retained; no executable economic semantics |
| EXPLICIT commitment | Required finite nonnegative amount; draw cap validated |
| CANONICAL_SIZING_DERIVED / RESIDUAL_DERIVED | Amount must be None; no inferred debt/residual or explicit draw profile |
| Disabled instrument | Fully validated, serialized and digest-bearing; not discarded |

`active()` means enabled proposals, not a runtime activation grant.
Rate schedules, floating curves, fee settlement and explicit repayments are
not generated or executed by these labels. F3.3 must supply real authority.

### Validation and wire identity

Schema version is `f3-1.0`, distinct from the app-layer candidate schema.
Collection and module APIs provide `to_dict`, `from_dict`, `canonical_json`
and SHA-256 `content_digest`. All nested objects are frozen with immutable
tuples. Returned dictionaries are detached. Ordering is seniority/ID for
instruments and provider ID for providers. Dates use ISO YYYY-MM-DD; JSON
uses sorted keys, compact separators and finite full-precision values.

Every serialized field must be present; unknown keys/version are rejected.
Wire enum/date decoding is explicit. Strings never become numbers or bools.
All documented F3 error codes are covered by rejected cases, including the
legacy unresolved-authority error. Non-finite/negative values, duplicate IDs,
invalid providers, fractions above one, invalid integer margins/grace,
draw chronology/caps and repayment/maturity conflicts fail closed.
Bounds are exact contract validation, not changes to engine tolerances.
The candidate ID check is tightened to reject trailing newline suffixes.

## Read-only legacy mapping

`financing_instruments_legacy.map_legacy_financing` returns a collection.
`map_legacy_financing_with_authority` returns a frozen source-audit envelope
with actual DebtSizingMode, SponsorFundingMode and Senior maturity date.

Senior retains CANONICAL_SIZING_DERIVED with amount None; neither
`fixed_debt_keur` nor the legacy amortization label supplies new authority.
FLAT/MINIMUM sizing maps to DSCR_SCULPTED, FROZEN to EXPLICIT_SCHEDULE,
and GEARING uses its typed repayment setting. Representation does not claim
these modes are all executable through the current clean runtime.

The existing pure PeriodEngine calendar supplies the actual SEMESTRIAL
operating axis and contractual maturity index. The resolved date is audit
output only; period-derived RepaymentTerms do not carry an invented date.
No Financial Close + tenor shortcut is used. Unsupported frequencies,
invalid FC/COD, missing calendar authority and out-of-axis terms fail closed.

Share Capital, Share Premium and Other Committed Equity are represented
separately. EQUITY_ONLY has residual Additional Equity without SHL;
SHARE_CAPITAL_THEN_SHL has residual SHL with typed BULLET/CASH_SWEEP only.
Positive scalar Junior funding is refused because instrument-level terms
are absent. No Junior loan, missing maturity or derived amount is invented.
Mapping calls no solver or persistence API and never mutates ProjectInputs.

## Four-vertical economic non-mutation evidence

The test performs two cold canonical production runs per vertical, clearing
the test's existing policy cache between runs. It compares the entire
CleanProductionRun dataclass output exactly, without rounding or exclusions,
including financial statements, Senior schedules, Sources/Uses, financing
fees and sponsor cash flows. Input serialization/hash and Integrity evidence
are also exactly unchanged. Structured evidence is written only to pytest
temporary storage, not committed as a golden or supplied to runtime.

The following verified values are identical before/after mapping (kEUR;
returns are fractions). Capitalized financing is IDC plus applicable fees,
not an IDC-only label.

| Synthetic reference | Senior | Capitalized financing | Senior maturity index | Project XIRR | Sponsor XIRR | Integrity |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| Solar | 26983.331676476686 | 1044.250306724227 | 32 | 0.11767978038866954 | 0.16610200308722253 | PASS |
| Wind | 36505.15795948399 | 2661.3703410167163 | 33 | 0.13310997970744148 | 0.18711831062341863 | PASS |
| Data Center | 58410.96179501392 | 2655.710630817117 | 27 | 0.023012141497371998 | 0.020785385741656906 | PASS |
| EV Charging | 6477.352578925075 | 207.6357736503246 | 21 | 0.15085906329985793 | 0.18722152859264346 | PASS |

This proves non-mutation of the existing single-facility runtime, not
multi-facility runtime equivalence. F3.3 needs separate financial acceptance.

## Validation and governance

New contract tests cover all catalogue errors, strict wire shapes, round-trip,
precision, recursive immutability, ordering, hashing and disabled proposals.
Legacy tests cover four real cold runs, actual mode/maturity authority,
typed invalid/missing inputs, no calculation/persistence calls, and no
production import or ProjectInputs field. The focused ring additionally
includes F3 candidate/reference, F0 maturity/Uses, F1/F2, orchestration,
financing policy, DSCR feasibility, sponsor semantics, integrity governance
and Data Center/EV/developer economics regressions. Exact counts and CI
process-exit evidence are recorded in the PR body after completion.

The consolidated 17-suite local ring exited normally with 693 passed and
1 failed in 611.51 seconds. The sole failure is
`test_finance_integrity_governance.test_this_branch_stays_within_the_governance_contract`:
`strictly_frozen_changes()` rejects the two new explicitly authorized F3.1
core modules. Existing governance helper/test changes are outside the current
file scope. No guard is skipped or weakened; an exact-path/content-pinned
authorization needs separate approval before this gate can be green.
The standalone new F3.1 contract/legacy suite passed all 184 tests in
27.70 seconds and returned process exit code zero.

Existing tracked financial/app/domain/static/workflow files remain identical
to baseline. No golden, hash lock or fixture expectation is weakened. No
public-safety scanner or CI exception is introduced. Full-suite execution
and normal supervisor exit are required from exact-head GitHub CI.

The local Windows safety scan returned one pre-existing vendor email
finding in `static/vendor/swagger-ui/swagger-ui-bundle.js`: CRLF checkout
bytes hash to `94d5341abf945c05b5dc2a4ee599be6adee30503790b998540795e766d8aea02`.
A read-only LF normalization hashes exactly to the unchanged scanner
allowlist `fd76294e33356ab3fd111ddaeeb10d3f79de8ae1a4d34dbf777f5eef224648d9`.
Neither vendor bytes nor scanner policy is edited. Linux exact-head CI
remains the authoritative public-safety gate; this is not reported as a
green local scanner run.

## F3.2 decision and review recommendation

Before persistence/activation, explicitly bind the proposal to original
sizing, rate-schedule, fee and sponsor authorities. The legacy envelope
retains sizing/sponsor modes without adding speculative economic fields to
the accepted collection schema. Its resolved calendar date is audit output.
The proposal digest is not a complete active financing identity. F3.2 must
decide how those authorities are preserved/versioned, and how edits obtain
owner/CAS/identity protection, before any opt-in integration.

Recommendation: review this contract foundation independently; no merge
or runtime activation is performed by this delivery. Missing production
integration is intentional F3.2/F3.3 scope, not a working-looking control.
