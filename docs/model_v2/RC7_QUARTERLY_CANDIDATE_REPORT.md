# RC-7 Quarterly Operating and Senior Debt Candidate

## Disposition and scope

**Unreleased, incomplete project-finance candidate. NOT a production Run.**
Base: `05183b2a96c74fd4b3976903c593a61402cab7b3`.
Branch: `feat/model-rc7-quarterly-operating-debt-v1`.
Draft PR: https://github.com/Finco-Protocol/FincoProtocol/pull/313
A1 commit: `0214e60e106e77adc58a415bf5b7c0b472cf188a`.

No financial policy decision D-01..D-12 is closed by this work. See
[decision register](RC7_QUARTERLY_DECISION_REGISTER.md). A recommendation, an
executable research calculation and independently accepted financial content are
three different things. `ACTIVATION_ENABLED=False`. No release-map changes.

## Implemented versus blocked

| Consumer | Actual implementation / boundary | Status |
|---|---|---|
| Typed policies | Explicit versioned 3/3 tuple, strict enum/date/EDATE validation, complete serialization; unknown, partial and mixed frequencies refused | Executable candidate |
| Date/axis | Existing PeriodMeta and CanonicalAxisContract; actual COD retained, positive initial stub, exact ordered quarter boundaries, declared fixed 4N horizon and annual counter | Executable candidate, proposal convention |
| Production | Existing finco_core generation leaf, P50 Base/P90 Bank separation; degradation once per four operating rows | Executed Solar/Wind synthetic cases |
| Revenue | Existing generation revenue leaf; merchant annual curve, legacy fixed/model-year indexed PPA with boundary-aligned expiry; explicit certificate scalar remains unchanged | Bounded candidate |
| Other revenue | Revenue V2/V3, dated PPA policies and intraperiod expiry are refused, not relabelled as quarter-ready | BLOCKED for revenue-owner handoff |
| OPEX | Existing flat annual projection and period-fraction allocation; annual escalation retains four-row model-year authority | Executed candidate |
| Advanced OPEX | Hierarchical/maintenance/seasonal settlement not silently activated | BLOCKED for OPEX-owner handoff |
| Depreciation | Existing book/tax schedules and useful lives, mapped using candidate year/fraction; no depreciation formula edit | Executed candidate |
| Tax/LCF | Existing calendar-year fragment ledger, FIFO loss and final cash-tax recomputation; explicit four-period TaxPolicy and existing last-covered-day payment convention, lag zero | Executed ordinary-tax candidate |
| Other tax | ATAD, thin-cap, source-model pairing, exogenous old period vectors and other timing policies refused | BLOCKED pending dedicated proof/policy |
| Senior | Existing run_senior_debt_model, solve_senior_debt, interest, sculpting, and Bank/Base recomputations; no second solver | Executed candidate |
| Debt policies | DSCR, GEARING_CAP, COMBINED_MINIMUM; ACT/360 and ACT/365; explicit contractual end date; complete/absent quarterly rate and target vectors | Bounded candidate |
| Maturity/cash | Off-grid maturity and balloons refused; existing G2A Bank service-budget precision reused; negative unfinanced Base cash refused | Fail-closed candidate |
| Reserves | Existing NONE pass-through only; no active reserve facility admitted | CASH_DSRA/DSRF policy BLOCKED |
| Construction | No changes to monthly CAPEX, allocation, construction periods, fees, IDC or draws; candidate has an explicit FC-to-COD reporting column only | Full dated funding/reporting bridge NOT VERIFIED |
| Project statements | No constructed balance sheet or guessed funding. Existing statement engine remains unchanged | Full quarterly Sources/Uses and BS integration BLOCKED |
| Distributions/returns | No policy guessed and no sponsor receipts manufactured | Waterfall, Project/Sponsor IRR integration BLOCKED |
| Product admission | No route, selector, Save, scenario writer, immutable Run ledger or export changes. Ordinary ProjectInputs quarterly adaptation now refuses rather than silently dropping frequency | RELEASE-CLOSED |
| Other facilities/verticals | No SHL, multi-Senior, Junior, BESS, Acquisition, Data Center or EV quarterly activation | Refused/not admitted; legacy 6/6 preserved |

`evaluate_quarterly_candidate(QuarterlyDebtStudy(...))` returns a distinctly
labelled research result. `require_complete_project_run()` always raises with the
missing consumer list. Intermediate Phase 2A/2B/2C provenance also carries
`QUARTERLY_CANDIDATE_NOT_RELEASED`; existing released provenance is unchanged.

## Shared authority and exact semantic edits

Only two EXISTING financial files change:

- `financial_engine/orchestrator.py`: typed research calendar dispatch, quarterly
  proxy frequency, candidate validator selection and distinct provenance; existing
  production formulas, bank sizing, tax loops and solver are reused unchanged.
- `financial_engine/adapters/project_inputs.py`: refuse any non-SEMESTRIAL
  production adaptation. This intentionally closes WF-23's documented silent
  frequency-loss gap. Its old test now proves refusal, not that dangerous behavior
  persists. The existing CalendarInput serialization for released Runs is unchanged.

No edits in finco_core, domain, construction code, revenue-owner files, app,
workflows, financial release maps, goldens or numerical tolerance definitions.

## Independent numerical evidence

The initial A1 + WF-23 ring passed **84 tests**, normal pytest exit 0.
The first A1/A2 ring passed **59 tests**. The final expanded candidate ring passed
**75 tests**, normal process exit 0, in 4.09 seconds. It adds real February29 COD,
one-day initial stubs, early dated maturity with continued operations, PPA/annual
OPEX steps, unknown-frequency refusal and proof of no app candidate imports.

The wider ring completed **384 passed, 1 failed, 0 skipped**, process exit 1,
in 557.48 seconds. Its sole failure is the unchanged scope assertion
`test_model_v2_revenue_runtime_parity.py::TestNoFrozenDiff::test_zero_frozen_and_unauthorized_changes`.
This is an unreviewed protected-content rejection, NOT a numerical assertion.
It is retained, not excluded, skipped or weakened. This ring includes the earlier
59 candidate cases, WF-23/four-vertical checks, F3 legacy and multi-Senior, Project
Timeline, statements/trace, WF-04 numerical precision, maturity integrity and
synthetic Revenue numerical validation. Counts overlap; do not add them as unique
tests. The final historical governance ring recorded **118 passed, 1 failed**,
normal process exit 1, in 109.88 seconds. Its sole failure is the unchanged
`test_finance_integrity_governance.py::test_this_branch_stays_within_the_governance_contract`,
which rejects all five unapproved candidate financial paths. Historical pin and
negative-behavior tests in that ring remain intact and pass.

The unchanged public safety scanner passes all **11 delivery files**. All eight
changed Python files compile, staged diff hygiene passes, and every candidate
manifest blob matches the staged Git object. The final four-vertical capture was
repeated after candidate hardening and still exactly equals the pinned base.

Sixteen Decimal cases independently calculate period production, net revenue,
OPEX, depreciation, backward-present-value debt size and forward opening balance,
interest, principal, service and closing liability. Cross product: Solar/Wind,
December31/April17 COD, ACT/360/ACT/365, scalar/stepped DSCR. The oracle does NOT call
the solver or its schedule-building helpers. Decimal precision: 50.

| Metric | Maximum actual absolute residual |
|---|---:|
| Production MWh | 4.931506849315069e-13 |
| Revenue kEUR | 4.219178082191781e-14 |
| OPEX / depreciation kEUR | 2.465753424657534e-15 |
| Debt size kEUR | 7.436140340893606e-13 |
| Opening / closing debt kEUR | 9.741827264034144e-13 |
| Interest kEUR | 1.691147951702197e-14 |
| Principal kEUR | 9.648597307045395e-13 |
| Debt service kEUR | 9.775342465753425e-13 |

These are measured residuals, not replacement tolerances. Existing thresholds are
not widened. Full-year production, revenue, OPEX and depreciation conservation is
proved for aligned complete years. Odd-COD first model years are prorated under
the explicit proposal; fixed 4N rows are NOT claimed to be N elapsed years.

The calendar tax oracle independently splits every dated amount at January1,
recomputes taxable income, opening loss utilisation, annual CIT and payment
placement from the existing last-covered-day contract. A first test assumption
that payment belonged to the final tiny carry fragment was rejected: existing
TaxPolicy instead pays in the latest period whose last covered day is in that
year, with a documented maximum-allocation fallback when no such period exists.
No tax rule was altered to satisfy the oracle.

## Exact legacy before/after comparison

Two independent Python processes evaluated unchanged base and candidate against
the same four generic frozen reference inputs. All unrounded dataclass result
fields and input identities compare EXACTLY. No expected financial values were
updated. Maximum numerical change: **0**.

| Six-month reference | Whole-result SHA256, identical before/after |
|---|---|
| Solar | `a24ac63a228a63e9ddecf6c2f7bbe094d4633f56edc0cdb9c6c5f1af92e0f481` |
| Wind | `b8f2dee7eaa64272f209a9e554e64bfb06d3f702d7d08151060ac0e93c696333` |
| Data Center | `bfbdd3d64bfccb36242fe5a78172e24d9f9dcb03e98c375629b729a738217bed` |
| EV Charging | `45b428a84725864fb39e6d15f37c2a0b79c85ac5081b2e8c0192e3e704e4f545` |

Private full structures/logs remain outside Git in `rc7-private`. The hashes above
are measurement evidence, NOT new golden tests or released-authority pins.

## Financial and product handoffs required

1. Finance owner: decide D-01..D-04 and D-10 for this bounded 3/3 candidate. The
   current fixed-count horizon does not implement an anniversary terminal stub.
2. Revenue owner: consume the typed dated PeriodMeta axis plus actual project COD;
   validate contract expiry/review against those exact endpoints. No replay or
   automatic price-date movement. No edits to their files in this workstream.
3. CAPEX/construction owner: prove complete monthly funding/IDC dates map into
   quarterly model reporting once, without changing cashflow dates or funding.
4. OPEX owner: prove supported annual/seasonal/one-off budgets and settlement dates
   on this axis. Flat annual accrual alone is not maintenance cash-timing proof.
5. Reserve/credit owner: approve D-08/D-09; no inheritance of the next-payment
   multiplier as an exact dated forward window, no assumed dividend eligibility.
6. Reuse the existing downstream statements and return authorities only after
   those policies and date joins are proved. Do not add a parallel project engine.
7. Independently review exact candidate financial blobs. Only a separately
   accepted exact-content successor can close the historical freeze guards.

Live parallel-source review: #314 (`54c40fd...`, Credit V4) and #315
(`bf23b5b...`, Revenue/PPA V3) were inspected. Their changed paths do not overlap
this branch. Neither branch was merged or cherry-picked. Their source contents
are not treated as quarterly financial approval; no coordinator acknowledgement
or cross-workstream financial acceptance is invented.

## Governance and CI

Existing exact financial authority maps are untouched. Local governance currently
rejects this candidate's unreviewed protected contents; it must remain fail-closed.
No independently approved quarterly financial successor exists. A green historical
Git-history workflow alone is NOT content-release approval.

The exact five protected Git blobs are enumerated in
[the candidate review manifest](RC7_QUARTERLY_CANDIDATE_BLOB_MANIFEST.json).
That JSON is NOT a governance authorization source and is not consumed by any
runtime or scope guard. All other historical financial/core paths remain unchanged.

CI is run on the staged Draft PR. Final exact-head conclusions, including any
expected financial-scope rejection and pending full Public Safety execution, must
be reported as observed rather than promoted to PASS.

**NO FINANCIAL RELEASE / NO MAIN MERGE / NO DEPLOY / NO SELF-APPROVAL.**
