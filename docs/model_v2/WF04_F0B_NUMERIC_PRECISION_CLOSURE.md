# WF-04: F0-B numerical precision closure

## Provenance and scope

Live main verified before work: `1b257d2e226fd8a8900d022de62291ffe39d55aa`.
Branch: `fix/model-f0b-numeric-precision-v1`. Draft PR only; no deployment.

Diagnosis re-executed the original F0-B serialized inputs on that main,
including SOLAR-23/24/25/27, WIND-25 and the seeded 16 MW/P50/10-year case.
The existing 51-case F0-P0 acceptance bundle is validation-only, SHA-256
`3b04a139b23f91150f2e376386dd277e989d124a4312a97b5e8a13fe2eeba199`.
No fixture, financial golden, baseline, equation or input authority is refreshed.

## Root causes

### Minimum-size handshake

G2A previously compared the funded Senior result against the capacity of a
second, DSCR-only Senior/SHL/tax fixed point. COMBINED_MINIMUM re-finalises its
schedule, so its SHL cash/interest feedback and finite stopping error differ.
Equal outer SHL principal does not make those two full schedules identical.
In a gearing-bound case they are economically different feedback states, not
just duplicate rounded presentations. The separate DSCR-only capacity remains
an informational result; it must not be the funded solver's second constraint.

At the failing F0-B iteration:

| Case | Separate capacity (kEUR) | Funded capacity (kEUR) | Difference (kEUR) |
| --- | ---: | ---: | ---: |
| SOLAR-27 | 25074.78741066055 | 25074.787411513626 | 8.5307693e-7 |
| Seeded 16 MW | 6617.989864516111 | 6617.9898647462705 | 2.3015946e-7 |

The inner solver accepts absolute convergence at `1e-4` kEUR or relative
convergence at `1e-9`; G2A's minimum-size handshake remains `1e-7` kEUR.
These errors therefore deterministically denied Run without demonstrating an
incorrect lending minimum. They are not UI rounding differences.

Correction: the expected minimum is the funded solver's own audited DSCR
capacity versus the independently computed Project Uses gearing capacity.
The gearing handshake, minimum-size tolerance and missing/invalid-capacity
rejection remain intact. The separate informational DSCR-only output is
preserved, including for GEARING_CAP; no debt is resized from that mode.

Once the denial was removed, the formerly unpublished SOLAR-27 also exposed
`3.437935652073065e-5` kEUR debt-service excess over its final Bank CFADS budget.
The inner stopping criterion can return a schedule using the preceding CFADS,
while the authoritative tax response is slightly smaller. This is a premature
numeric stop, not new economics or an impossible economic constraint.

Only if that excess fails the EXISTING committed financial-evidence precision
(`1e-6` kEUR) does G2A repeat the SAME kernel with identical economic inputs,
absolute convergence no larger than its existing `1e-7` kEUR contract and
relative convergence `0`. A failed refinement is rejected, never published.
Period targets and debt-service availability use their existing typed axes.
Already-valid cases are not refined. In particular WIND-03 has an existing
`5.218039405008312e-7` excess, within unchanged evidence precision, and remains
bit-identical. This is not generic tolerance widening.

The attempted global finalisation tightening was rejected locally because it
changed an existing M6 output. There is ZERO final diff in the Senior solver,
tax engine, SHL kernel, rate policy or repayment equations.

### Balance-sheet residual

The statements assembly used zero Senior liability after the contractual
Senior axis ended, even when its authoritative last closing balance was not
zero. The balance-sheet residual was precisely the omitted liability.

| Frozen case | Actual terminal Senior (kEUR) | Original Integrity BS residual (kEUR) |
| --- | ---: | ---: |
| SOLAR-23 | 2.3221237597681466e-5 | 2.3220834918902256e-5 |
| SOLAR-24 | 1.3787690704702982e-5 | 1.3787794159725308e-5 |
| SOLAR-25 | 8.486792239636998e-6 | 8.486906153848395e-6 |
| WIND-25 | 9.149442576017464e-6 | 9.148119715973735e-6 |

The debt remainder is a finite solver stopping residual, not merely a display
rounding error. SOLAR-23's balance is millions of float ULPs at the debt scale.
Residual differences around `1e-10` kEUR are ordinary accounting accumulation.

Correction: after maturity, carry the ACTUAL last canonical Senior closing
balance as a liability. Before that axis, the existing zero/default behavior
is unchanged. No asset, retained earnings or cash is adjusted to balance it.
No additional interest, principal, refinancing or terminal repayment is created.

SOLAR-23 now has maximum assembled BS residual `4.150706445216201e-10` kEUR,
with EXACTLY the same debt, closing remainder and cash flows. Its terminal
status remains `OUTSTANDING_AT_MATURITY`, not artificially `REPAID`.
Passing accounting Integrity is not a settlement or bankability certification.
The existing return/maturity classification remains authoritative.

## Completed-run numerical evidence

The old denial amounts above are intermediate iterations, NOT final targets.
The existing construction/Senior/SHL fixed point now finishes naturally:

| Case | Final Senior (kEUR) | Terminal Senior | Integrity |
| --- | ---: | ---: | --- |
| SOLAR-27 | 25013.42973345471 | 0 | PASS |
| Seeded 16 MW | 6583.298480917883 | 0 | PASS |

No balancing plug, forced draw, forced repayment, target fitting, output replay
or project-identity dispatch is introduced.

Independent 50-digit Decimal recomputation in the focused tests sums actual
BS assets and each actual liability/equity component, without using the
engine's `balance_check`. It independently verifies the lending minimum too.
The seeded test creates its Working Copy through the existing reference-seed,
WorkbookService and CAPEX/OPEX folds, not an invented scaled financial output.

## Financial acceptance

Solar/Wind reference precision, Data Center/EV legacy results, period targets,
availability, Senior sizing, M6 repayment, Sources & Uses, sponsor/IRR and
unpaid maturity checks are exercised by the focused ring and frozen corpus.

| Reference | Senior before = after (kEUR) | Project XIRR before = after |
| --- | ---: | ---: |
| Solar | 26983.331676476686 | 0.11767978038866954 |
| Wind | 36505.15795948399 | 0.13310997970744148 |
| Data Center | 58410.96179501392 | 0.023012141497371998 |
| EV | 6497.019462566068 | 0.18019413353035196 |

Original impossible high-gearing/short-tenor cases remain rejected with
`SENIOR_MATURITY_UNSETTLED_LIABILITY`, with unchanged actual unpaid balances:
Solar `20912.234045226287` and Wind `23644.893677596927` kEUR.
Neither a maturity extension nor an invented settlement is implemented.

The final focused financial ring completed normally: **242 passed** in
514.18 seconds. The paired 51-case corpus has **38 fully identical outputs,
12 balance-sheet/audit-only corrections and 1 newly completed SOLAR-27**.
There are zero unexplained differences. All four reference outputs and the
already-valid WIND-03 output are fully structurally identical, excluding only
capture timestamps, execution time and checkout provenance. None of the 12
previously completed cases changes debt, tax, cash flow, distributions or IRR.

Exact-head governance and GitHub CI results are recorded in the Draft PR
delivery. Raw generated captures are external evidence, not
committed financial fixtures. During local capture HEAD still points at base;
candidate provenance is the exact two Git blobs below, not the capture's
unchanged Git-HEAD label. Exact-head CI validates the committed candidate.

## Governance and boundaries

Only two financial-authority files change:

- `financial_engine/financing/project.py`:
  `4349b4bc396cba446a0b1c473f1a466eafb12bb5`
- `financial_engine/financial_statements/assembly.py`:
  `7b8607c719ef1d780490dfbee8107ce290508bff`

Existing historical governance pins remain intact. The new authorization is
exact-path AND exact-blob only, with negative tests for changed content and
unrelated engine/core paths. Two historical HEAD-content assertions recognize
only these exact WF-04 successor blobs. There are no wildcard exemptions.

ZERO diff: `finco_core/`, Senior solver, tax/SHL equations, schemas,
persistence, factories, UI, exports, execution workers, workflow definitions,
locks, financial goldens and baselines. Integrity checks and their `1e-6`
financial tolerance are unchanged. No full local suite is substituted for
the five mandatory exact-head GitHub CI workflows.

**Draft / independent financial review required. No merge or deployment.**

## Integration Correction A

Normal main synchronization uses merge commit
`78677ef36b904d3952b8b86c33a05ee8b32d0ee8`, with parents
`dffa81c2b3d96d6dd4e512a835322fa937934628` and current main
`c1531711fed736fdc83cb45a6fffacffd6536890`. The merge had no conflicts.
All Q3/F3/C0 changes are inherited unchanged; there is no WF-04 diff in their
application, persistence or workflow authorities against the integrated main.
Both financial-engine blobs above remain exactly unchanged.

The old exact-head Public Safety run `38064227281` returned normally with
9358 passed, 54 skipped and one failed historical performance assertion.
That assertion froze all 17 post-#212 result-tree digests, including a proved
financial precision defect in `loss_carryforward`. An isolated exact-base
execution reproduces the old committed digest, not just a guessed baseline.
Its final Bank service-budget excess is `2.7684582164511085e-6` kEUR, and its
unchanged Integrity check reports `DSCR_SCULPTING_FEASIBLE` FAIL.
Conditional refinement reduces the excess to `2.2737367544323206e-13` kEUR
and Integrity PASS. Debt quantum remains `26810.99980604639` kEUR.
Interest/service timing changes propagate through the existing tax, cash flow,
statements and returns equations; the 343 changed leaves are not falsely
described as a BS-only change or an unaffected calculation.

No digest or financial fixture is refreshed. The historical performance
contract now retains all 16 unaffected digests and fail-closed reasons, while
an additional full-tree differential compares BOTH retained kernels for ALL
17 scenarios under the SAME current financial authority. It selects the
existing authoritative roll via a test-scoped delegating wrapper, asserts
that it is actually exercised and forbids the numeric kernel in that path.
All outputs/failure reasons must be bit-identical, with zero numeric tolerance.
There is no new solver and no production monkeypatch.

A dedicated independent Decimal precision test reproduces the exact unchanged
old loss-case golden using a validation-only no-refinement counterfactual.
It requires the old Integrity failure, proves the service-budget violation,
then requires the corrected same-input Run to pass `1e-7` kEUR budget precision,
retain the exact debt quantum and pass unchanged Integrity. This is a causal
financial contract, not a replacement target digest or an allowed-drift list.

Integrated focused counts, the fresh 51-case comparison and new exact-head CI
run IDs are recorded in the PR delivery. The original 51-case corpus and the
additional 17-scenario performance matrix are separate acceptance evidence.

The integrated focused financial, governance, maturity, runtime equivalence,
F3 and C0 ring completed with **350 passed** in 608.39 seconds, normal process
exit 0. The separate Correction A checkpoint completed with **3 passed** in
199.67 seconds, exit 0. All nine changed Python files compile, diff hygiene and
changed-file safety checks pass. The re-executed 51-case corpus retains exactly
38 identical, 12 BS/audit-only and one newly completed output; all 51 integrated
financial outputs equal the prior WF-04 candidate. No unexplained changes.
