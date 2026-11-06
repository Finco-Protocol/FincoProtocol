# V9-B1 Correction A: intermediate capacity rejection authority

## Decision and provenance

Independent review of PR #324 at `e76619454212867c7be27f7d783dee849cbc0844`
requires correction, not release. The complete independent final review supplied
on 19 October confirms the same P0 failure-order gap addressed here.

Immutable comparison main: `5be8c4b149712dd39b38b54c6fabcf3fcf47ef0d`.
Protected path: `financial_engine/financing/project.py`.

| Content | Git blob |
| --- | --- |
| Released main | `30536cec8779fdb6a490d82fd80bfce2c09e16fe` |
| Superseded unsafe B1 | `61bd3e644b8e3159d1709c32b41aec12340c5e34` |
| Correction A candidate, NOT released | `5ef0d94c80af9e31ac389a571e9e2cfe762ed627` |

No safe eligibility predicate or cheaper equivalent check has been established.
Consequently **all cases take the original capacity-first algorithm**. Deferral
and exception-triggered retries have been removed. Optimized eligibility is zero;
the 49 research and seven extended cases all take the canonical path. The previous
B1 speedup claims are withdrawn; they describe unsafe historical code only.

The remaining helper extraction adds no numerical operation. A regression parses
the actual immutable main source and proves AST equality of the entire numerical
body, beginning at `uses`, with the extracted candidate body. Original dispatch,
construction recursion, thresholds, funded calculations and failure precedence
are preserved. This does not replace independent exact-content authorization.

## Failure inventory and safety argument

`V9B1_CORRECTION_A_RAISE_SITES.csv` records 534 explicit raise sites in 61 relevant
source modules. It is a conservative source superset, NOT a claim that every site
is dynamically reachable from every capacity call. Implicit Python exceptions
are additional possible failures. No unknown check is waived on that basis.

| Capacity path / gate | Intermediate dependence and treatment |
| --- | --- |
| Input adapter, construction validation | Some validation precedes the old deferral; not all was skipped. Preserve existing position and evidence. |
| `run_senior_debt_model` without SHL | Initial no-SHL state is distinct from later positive-SHL states. Tax, Base/Bank axis, Senior convergence, interest consistency and reserve checks cannot be presumed equivalent. |
| SHL-enabled orchestration | Principal affects maturity residual, cash interest, interest limitation, tax feedback, repayment and final financing consistency. Early refusal cannot be inferred from a successful final capacity. |
| Senior solver and GEARING_CAP | A gearing-bound funded result does not prove the independently executed DSCR capacity is valid. Keep the original capacity call, solver rejection and audited result checks. |
| Tax and final CFADS recomputation | Intermediate interest and limitation inputs differ. No alternate tax validation or proxy capacity is introduced. |
| DSRA and other downstream checks | Preserve the actual model invocation, validation and exception ordering; do not presume independence from intermediate debt service. |
| Missing capacity Senior evidence | Existing `G2A DSCR capacity result is unavailable` rejection remains before funded work. |
| Axis and static contract checks | Even if input-independent, deferring a failure could change which error wins. No error-order waiver is authorized. |
| Arithmetic and programming exceptions | Propagate unchanged; no broad catch, retry or success promotion. |
| Funded/stack checks | These are not substitutes for capacity gates. Where both fail, original capacity-first precedence remains authoritative. |
| M6 sizing evidence | Informational use of capacity does not make its fail-closed validation optional. |

All categories remain executable at their original iteration, rather than being
reimplemented as an incomplete error-name allowlist. AST equality protects gates
not covered by the finite synthetic error list as well.

## Deterministic counterexample

The controlled fixture uses actual Data Center financing inputs, with construction
disabled to isolate G2A. It injects an error only in the early DSCR capacity call
whose SHL is absent. Funded calculations and the final positive-SHL capacity are
real calculations. Three separate processes execute the actual source versions:

| Actual source | Result | Order |
| --- | --- | --- |
| Immutable main | REJECTED | initial capacity only |
| Unsafe reviewed B1 | FEASIBLE | funded, funded, final capacity |
| Correction A | REJECTED | initial capacity only |

Both rejections preserve the exact error:
`SHL_MATURITY_RESIDUAL_FAILS_CLOSED: synthetic early capacity residual=11.25`.
Unsafe B1 returns Senior `58410.96179501392` kEUR and SHL
`51589.03820498608` kEUR. This is an **injected control-flow proof, not a genuine
economic input counterexample**. No genuine B1 economic counterexample is claimed.
V9-A section 7.3 concerns a different seed experiment and is supporting context,
not direct evidence of a B1 input counterexample.

Regression controls also preserve the same exception object for Senior
non-convergence, SHL limitation, final-interest mismatch, axis/validation errors,
overflow, runtime/type errors and failed invariants. Each fails before funded work
with no retry. Missing Senior evidence remains a refusal.

## Validation and performance

Local focused regression: **289 passed, zero failures/skips**, 774.43 seconds,
pytest process exit **0**. This includes all 49 research cases (31 feasible,
18 rejected), seven extended cases, 15 capacity-order/control tests, WF-04
precision, M6, generic financing, Run Integrity, maturity, multi-Senior,
immutable history and export lineage. The fixed full-result fingerprints remain
unchanged: 595,064 output/error leaves across the 49+7 cases.

Supplemental boundary comparison executes immutable main and corrected source in
separate processes: **32/32 complete result/error records identical**, 31 feasible
and one rejected. DSCR targets are 1.4, 1.5, 1.6, 1.7, 1.8, 1.9, 2.0 and 2.2
on each of four Solar/Wind case bases, with explicit no-construction/no-DSRA
policy to isolate the inner G2A boundary.

Pre-commit governance run: 52 passed, three expected exact-content failures,
process exit 1. Those guards inspect committed HEAD and therefore still identify
the superseded `61bd...` blob at this stage. A post-commit run must identify the
corrected candidate without silently accepting it. These are release blockers,
not a fully green regression claim.

Public repository safety scan exits 0 with
`PUBLIC_REPOSITORY_SAFETY_SCAN_PASS`. The scanner also checks the new report and
raise-site inventory explicitly before publication. Python compilation and
`git diff --check` pass. Uncached paired measurements are
recorded in the companion evidence JSON after process completion.
No frozen output fingerprint, golden or tolerance is changed.
The benchmark uses five alternating AB/BA cold-process samples per arm, cleared
production-policy cache, and separate profiles excluded from timing summaries.
It is engine-only, not HTTP latency. With only five samples, nearest-rank p95 is
the largest observed sample, not a reliable production-tail estimate. Small timing
variation between identical canonical numerical bodies must not be presented as
retained B1 benefit.

| Case | Baseline median s | Corrected median s | Measured saving | Capacity calls / G2A iterations |
| --- | ---: | ---: | ---: | ---: |
| Solar 50 | 1.90 | 1.99 | -4.83% | 34 / 34 |
| Solar 16 | 16.58 | 16.77 | -1.18% | 166 / 166 |
| Wind DSCR 2.0 | 10.35 | 9.99 | 3.41% | 121 / 121 |

All paired digests and every comparable profiled kernel/solver/tax call count
match. There are no speculative retries. The new helper-entry counter is an
instrumentation-only distinction, not saved work. Raw samples, full-precision
medians, separate profiles and sanitized actual-source counterexample evidence
are in `V9B1_CORRECTION_A_EVIDENCE.json`.

## Remaining authority gates

OD-5 remains **PENDING**. The corrected protected blob is not a released successor.
The known F3/WF04 exact-content blockers must remain active until independently
authorized; no historical pins, governance maps or those tests are changed here.
PR #320 and quarterly behavior are untouched. No activation, merge or deployment
is authorized. A new independent financial and governance review is required.
