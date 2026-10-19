# Performance V9: candidate acceptance and NO GO

## Disposition

**V9 NO GO - NUMERICAL OR PERFORMANCE SAFETY NOT PROVEN.**

This is an isolated, disabled numerical candidate, not a released acceleration.
No financial precision, skipped-state equivalence, release or activation approval
is asserted. No merge or deployment is requested. The fastest *proven authoritative*
path in these experiments remains the original canonical Run. Neither the old
B1 deferral nor BW is presented as a safe alternative.

## Reproducible authority

- Immutable main: `5996453b8d5bbfaa48bc06922fc6963cf94d2f84` (merged #325).
- Feature branch: `feat/model-v9-joint-solver-v1`.
- Research inspected: `79270c9513cbd0ed7c0432733903482bc6528b93`, read-only;
  no merge, cherry-pick or dynamic source compilation.
- Open #321, #322 and #324 were inspected. The current changes do not import
  their work; #324 overlaps `financing/project.py` but is not reused.
- Python 3.12.10, Windows 11 AMD64, 12 logical CPUs. Repeated benchmark processes
  use `OMP_NUM_THREADS=1` and `OPENBLAS_NUM_THREADS=1`, with NumPy prepared equally
  before the measured financial Run in all arms.

The exact proposed blobs and immutable predecessors are in
`V9_CANDIDATE_BLOB_MANIFEST.json`. Matrix and timing records include source-byte
SHA-256 fingerprints as well as Git provenance. Local pre-publication measurements
were executed with a dirty candidate tree based on the immutable commit; they
must not be falsely described as already published exact-head CI evidence.

## Implemented scope

The six-dimensional DSRA/construction-cost proposal is bounded, request-local
and safeguarded. It calls the existing kernels, strict Stage B2, Senior solver,
tax, SHL, waterfall and statement authorities. The public G2A function is
AST-identical to the baseline, including every intermediate capacity pass.

The three approval/activation constants are literal `False`. Normal application
dispatch never calls the lab entry. No UI, DB, worker, CAS, saved-input schema,
tax policy, Senior tolerance, quarterly activation or historical pin is changed.
One existing application assembly block is extracted into a shared helper;
there is no second statement or returns calculator.

Raw proposal mode is explicitly non-authoritative. Guarded mode **always**
re-decides through the original canonical Run, even after proposal success.
An injected refusal at an actual outer configuration skipped by the new
trajectory proves why a final-convergence-only check is insufficient. This is
an injected control-flow counterexample, not a claimed real economic defect.

## Financial acceptance

The main 60-case batch includes all 49 historical scenarios, four vertical
references, equity-only Solar, four extra DSCR boundaries and two isolated RC-7C
v2 projects. Three further equity-only zero/near-zero/reserve cases are recorded
separately, not substituted into the original matrix.

Complete typed output leaves are compared, including IEEE float bytes, financial
statements, returns, debt classifications, policy evidence, Integrity and error
type/code/text. No tolerance is used to turn a difference into a PASS.

The main batch results are:

| Path | Bit-identical feasible | Different feasible | Identical rejection |
| --- | ---: | ---: | ---: |
| Unchanged default | 42 | 0 | 18 |
| Raw joint proposal | 7 | 35 | 18 |
| Guarded canonical re-decision | 42 | 0 | 18 |

The separate three-case edge batch adds two bit-identical feasible outcomes and
one identical refusal for default/guarded execution. Both raw feasible proposals
differ (one only in evidence), with no observed financial classification change.
Thus the combined inventory is 63, not a claim of 63 successful Runs.

No financial classification flip was observed in this finite batch. That does
not prove equivalence for unsampled intermediate failures. The maximum observed
cash difference is `6.3059269450604915618896484375e-7` kEUR, in cumulative Wind
SHL cash interest. OD-1 is pending; this is not an approved precision band.

80-digit independent Decimal arithmetic recomputes Sources minus Uses, Balance
Sheet identities, principal roll-forwards and terminal margins from persisted
output leaves. Missing components remain unavailable, never invented zeroes.
The complete differences and rejection evidence are retained in the review
packet; compact results and fingerprints are in `V9_FINANCIAL_EVIDENCE.json`.

The raw BW test-only seed probe changed 335 Solar and 166 Wind leaves; it is
excluded. No production warm-start argument or cross-Run state is introduced.

## Performance acceptance

`V9_PERFORMANCE_EVIDENCE.json` contains each raw sample, median, nearest-rank p95,
per-arm fingerprints, memory peaks and independent profile counts. Five samples
make p95 the observed maximum, not a reliable production-tail estimate.

Baseline, proposal and guarded arms alternate order in separate processes.
The application policy cache is cleared before every Run. Imports, NumPy worker
preparation, output flattening and profiler time are excluded from medians.
These are uncached finance timings on equally prepared workers, **not** cold
process startup, route, workbook or end-user Run latency.

Profiles are separate from timed samples. Their L1-L5, Stage B2, tax/CFADS,
SHL/Senior, construction and final-verification counts include nested work.
Inclusive profiled durations must not be added or treated as uninstrumented
stage timings. Guarded timing includes both attempted joint work and required
canonical re-decision; raw proposal saving is not accepted production saving.

The measured safety cost prevents a production performance acceptance. Financial
Owner precision approval alone cannot solve skipped-state rejection coverage.
An independently justified cheaper equivalence proof is a separate prerequisite.

Actual median / observed p95 in seconds (five fresh-process samples per arm):

| Workload | Original | Raw, non-authoritative | Guarded canonical decision |
| --- | ---: | ---: | ---: |
| Solar 50 MW | 1.7317 / 1.9089 | 0.7985 / 1.0457 | 2.3380 / 2.3870 |
| Solar 16 MW, constrained | 14.7129 / 15.5527 | 4.8452 / 4.9973 | 19.8314 / 20.2100 |
| Wind 25 MW | 4.9893 / 5.0902 | 2.7193 / 2.8526 | 7.5071 / 7.8291 |
| Data Center | 0.8233 / 0.9642 | 0.5213 / 0.5610 | 1.2175 / 1.4478 |
| EV reference | 1.1774 / 1.2234 | 0.5890 / 0.6188 | 1.5924 / 1.9324 |
| Wind / 12-month DSRA, REJECTED | 1.9167 / 1.9873 | 3.4884 / 3.6914 | 3.5428 / 3.8639 |

The last row is time to an identical refusal, not time to a feasible result.
Raw proposal savings for the five successful workloads are 36.69-67.07%; guarded
decisions are 34.79-50.47% slower. The observed rejected-case overhead is 84.83%
in guarded mode. This is observed fallback cost, not a universal wall-clock bound.
No threshold was moved to make those results count as production acceptance.

For constrained Solar 16 MW the independent profile records:

| Evaluation count | Original | Raw proposal | Guarded |
| --- | ---: | ---: | ---: |
| L1 original DSRA policy iterations | 2 | not the original policy loop | 2 |
| L2 construction iterations | 14 | 5 | 19 |
| L3 G2A calls | 21 | 7 | 28 |
| L4 SHL/tax calls | 408 | 140 | 548 |
| L5 Senior solver calls | 2879 | 999 | 3878 |
| Tax/CFADS calls | 17175 | 5967 | 23142 |
| SHL/tax iterations | 2414 | 838 | 3252 |
| Strict final construction/G2A calls | 2 | 1 | 3 |

The raw path instead reports its explicit joint iteration count; absence of the
old L1 loop is not an assertion that no DSRA work occurred. Observed process
peak memory on that workload is 133.76 / 132.46 / 135.98 MB. Memory includes
imports and evidence serialization, not just solver allocations. Complete
per-workload counts and inclusive final-verification profile times are in JSON.

## Tests and existing boundaries

- Immutable-main financial governance: 115 passed, normal rc=0. An initial
  sandbox-only Git clone permission failure was rerun with authorized execution;
  no test or assertion was weakened.
- Focused financial/runtime/history/export/quarterly ring: 1781 passed, one
  existing conditional skip, zero failures, rc=0. That skip states that an
  unchanged semiannual/quarterly depreciation equality is inapplicable when
  financing costs change. The original test is untouched. A separate unskipped
  test proves each actual funded structure against its own existing Decimal
  book-basis oracle (one passed).
- New candidate, proposal negative-control and final post-commit governance
  counts are recorded in the handoff and JUnit evidence, not inferred from CI.
- Source safety and Python compilation are required again on final bytes.

Historical frozen-namespace tests have not been modified. They may reject this
unapproved financial candidate and its effect on the RC-7C recognition chain.
The new exact-content **proposal checker is not connected to those guards** and
is not a financial release map. Any resulting CI blockers must remain visible.

## Reproduction

Use an immutable detached checkout of the base, a separate candidate checkout,
Python 3.12, and disposable storage outside both checkouts. From the candidate:

```powershell
python tools/v9_joint_acceptance.py --repo BASE --out PRIVATE/baseline.json
python tools/v9_joint_acceptance.py --repo . --mode canonical --out PRIVATE/default.json
python tools/v9_joint_acceptance.py --repo . --mode proposal --out PRIVATE/proposal.json
python tools/v9_joint_acceptance.py --repo . --mode guarded --out PRIVATE/guarded.json
python tools/v9_joint_compare.py --baseline PRIVATE/baseline.json --candidate PRIVATE/default.json --out PRIVATE/default-diff.json --require-identical
python tools/v9_joint_compare.py --baseline PRIVATE/baseline.json --candidate PRIVATE/proposal.json --out PRIVATE/proposal-diff.json
python tools/v9_joint_compare.py --baseline PRIVATE/baseline.json --candidate PRIVATE/guarded.json --out PRIVATE/guarded-diff.json --require-identical
python tools/v9_joint_benchmark.py --baseline BASE --candidate . --out PRIVATE/bench --samples 5 --cases S50 S16 W25 DC reference-ev_charging W25-dsra12 --profiles --include-guarded --warm-numerics
python -m tools.v9_bw_probe --out PRIVATE/bw.json
```

The original delivered matrix contains a 60-case batch plus a separate three-case
edge batch. The current harness runs all 63 by default; comparisons must use the
same input inventory on both sides. Do not refresh a reference golden.

## Remaining decisions

1. OD-1: exact permitted representative differences and evidence semantics.
2. Equivalent coverage of original intermediate rejection sites without paying
   for a complete canonical re-decision. No bypass-eligible subset is proved.
3. Independent exact-content review of four financial and one application blobs.
4. A scoped, independently accepted successor before any frozen guard can change.
5. New successful safety-inclusive performance acceptance before release.

Quarterly D-01-D-12, Junior, BESS and Revenue V3 authorities are untouched.
No independent human review, release approval or green CI is fabricated.
