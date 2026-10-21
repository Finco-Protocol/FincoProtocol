# V9-P1 local acceptance and performance decision

**Disposition: NO GO for production enablement.** Bit-identical execution is
demonstrated locally; cold/small-Run latency, resource costs and unproven
profitable admission prevent an accepted production optimization.

Immutable baseline: `5996453b8d5bbfaa48bc06922fc6963cf94d2f84`. The candidate is the commit carrying this
document; pre-publication measurements bind the exact protected blobs below.
One Draft PR preserves the candidate and reproduction evidence, not release approval.

## Scope and exact content

| Protected path | Proposed Git blob |
|---|---|
| `financial_engine/financing/project.py` | `5d3e42863abddf0a75a05e6d7688aa76a6d41c50` |
| `financial_engine/financing/speculative.py` | `9d85dad49bd1014fa7d864fab6bd29649d214cd7` |

No other financial/core/domain/application source is changed. Existing Run
worker, persistence, authorization, CAS, historical evidence, CI, numerical
tolerances, goldens and historical governance maps remain unchanged.
No #327/#324/#322 financial code or branch is incorporated. Quarterly admission
and the joint solver remain closed. `FINCO_G2A_WORKERS` defaults to zero.

## Local numerical and failure acceptance

- **140 passed, zero failed, zero skipped**, normal process exit zero.
- New tests: 43 execution/lifecycle, eight financial/application and 15 proposal cases.
- Existing tests: 42 Senior maturity and 32 WF-04 numerical precision cases.
- **252 exact comparisons:** all 63 inventory cases at widths 0/1/2/3.
- Every width retained 44 feasible outcomes and all 19 original refusals.
- Original input fingerprints and complete result/Integrity fingerprints match immutable main.
- Matrix rejections compare type, text and reason. Injected tests separately compare native cause chains.
- The supplied Opus 58-name inventory is fully covered as a subset. Its five omitted
  policy/isolated-quarterly cases are also exercised through their existing correct entry points.
- Four legacy verticals and isolated quarterly compositions are included, without activating quarterly admission.
- Crash, timeout, cancellation, source mismatch, CPU refusal, daemon/spawn refusal,
  per-task isolation, canonical exception order and helper cleanup are tested.

See `V9P1_EXCEPTION_EQUIVALENCE.md` for the explicit failure matrix. Exploratory
failed/aborted development runs are not counted as final acceptance.

## Measurement method

Five alternating isolated A/B pairs per workload, OMP/OPENBLAS threads one.
The baseline is a separate unchanged main checkout. Application measurements use
the actual spawn-based `ModelExecutor` and actual `run_project`, including dispatch,
all complete returned objects, serialization, helper startup/source validation and draining.
Existing outer-worker prewarm is measured separately in raw evidence, not added to
per-Run latency. No helper prewarm is injected. First-helper-cold and same-owner-helper-warm
Runs remain separate. Calculation caches are cleared; this is not HTTP/DB/UI timing.
Every paired input and complete financial return fingerprint matched; no forced shutdown stragglers.

Benchmark settings are explicit: one web process, one or two admitted Run workers,
three requested helpers per owner on a 12-logical-CPU Windows host. These are not
claimed as observed production defaults. Production admission still accounts for
configured web/model concurrency and CPU/affinity/cgroup limits.

p95 below is nearest rank from only five samples: the sample maximum, not a
reliable production-tail estimate. All raw sample arrays are committed in the evidence JSON.

## Actual application Run worker

Negative change means faster. Seconds; first Run includes cold helper initialization.

| Case | Cold main median / p95 | Cold parallel median / p95 | Cold change | Warm main median / p95 | Warm parallel median / p95 | Warm change |
|---|---|---|---|---|---|---|
| S50 | 2.240 / 2.354 | 4.620 / 4.860 | +106.2% | 1.789 / 1.809 | 1.526 / 1.623 | -14.7% |
| S16 | 16.941 / 17.130 | 13.021 / 13.120 | -23.1% | 16.891 / 17.218 | 10.219 / 10.324 | -39.5% |
| W25 | 5.883 / 6.025 | 7.131 / 7.215 | +21.2% | 5.722 / 6.031 | 4.388 / 4.680 | -23.3% |
| DC | 1.040 / 1.057 | 2.873 / 3.049 | +176.3% | 0.756 / 0.768 | 0.680 / 0.700 | -10.0% |
| EV | 1.450 / 1.829 | 3.220 / 3.394 | +122.1% | 1.129 / 1.140 | 1.038 / 1.083 | -8.1% |
| concurrent-S16-W25 | 17.714 / 18.057 | 14.805 / 15.157 | -16.4% | 17.154 / 17.836 | 10.803 / 10.979 | -37.0% |

The concurrent row is the completion time of both distinct S16/W25 user tasks,
not one task or the sum of their times. This is two-user evidence, not a whole-host load test.

## Application resource cost

CPU is summed OS process CPU, including startup, execution and transfer, excluding
post-measurement evidence hashing. Memory is the sum of individual process lifetime
peaks: a conservative upper bound, **not simultaneous peak RSS**. Process count includes caller.

| Case | Cold CPU main / parallel (s) | Warm CPU main / parallel (s) | Warm CPU change | Peak-sum main / parallel (MiB) | Max processes main / parallel |
|---|---|---|---|---|---|
| S50 | 2.125 / 6.516 | 1.766 / 3.125 | +77.0% | 258.6 / 329.0 | 2 / 5 |
| S16 | 16.703 / 28.469 | 16.703 / 25.422 | +52.2% | 262.8 / 334.5 | 2 / 5 |
| W25 | 5.703 / 14.156 | 5.641 / 11.094 | +96.7% | 288.0 / 335.4 | 2 / 5 |
| DC | 0.984 / 3.594 | 0.750 / 1.219 | +62.5% | 214.5 / 284.6 | 2 / 4 |
| EV | 1.391 / 4.109 | 1.109 / 1.781 | +60.6% | 231.6 / 285.9 | 2 / 4 |
| concurrent-S16-W25 | 23.766 / 45.891 | 23.062 / 39.141 | +69.7% | 481.8 / 577.5 | 3 / 9 |

## Direct financial authority, cold process and helpers

These are complete canonical financial/Integrity comparisons, not application round trips.

| Case | Verdict | Main median / p95 (s) | Parallel median / p95 (s) | Wall change | CPU main / parallel median (s) |
|---|---|---|---|---|---|
| S50 | FEASIBLE | 2.042 / 2.188 | 4.407 / 4.663 | +115.8% | 1.953 / 6.578 |
| S16 | FEASIBLE | 16.659 / 17.212 | 12.873 / 13.053 | -22.7% | 16.406 / 28.344 |
| W25 | FEASIBLE | 5.706 / 5.916 | 7.044 / 7.953 | +23.4% | 5.641 / 14.344 |
| DC | FEASIBLE | 0.989 / 1.047 | 2.748 / 2.876 | +177.8% | 0.938 / 3.734 |
| reference-ev_charging | FEASIBLE | 1.358 / 1.398 | 3.088 / 3.254 | +127.5% | 1.281 / 4.219 |
| W25-dsra12 | REJECTED | 2.200 / 2.207 | 3.892 / 3.947 | +76.9% | 2.109 / 6.328 |

## Gate decision and smallest next alternative

The bit-identity and local failure/lifecycle gates pass. Production performance
acceptance does not: cold/small Runs materially regress, CPU/memory costs rise,
and whole-host non-regression and automatic profitable selection are unproven.
A safe CPU fallback is not a profitability policy. Explicit opt-in does not cure
those failed gates. Keep the candidate disabled; do not advertise a shipped speedup.

Smallest next experiment: compare two versus three helpers with this unchanged
harness, then evaluate a measured serial-eligibility boundary and worker-startup
prewarm. Any application initializer hook needs a separately bounded scope amendment.
Retain a hard CPU/headroom budget and repeat cold/small/concurrent acceptance.
Do not switch to a trajectory-changing solver, relax tolerances, or adopt OD-R/OD-1.

## Governance and Linux status

The two-blob manifest is a **proposal only**. No independently accepted financial
content or released successor is fabricated. Historical maps and negative guards
remain unchanged, so effective frozen guards may correctly reject this candidate.
A chained exact-content successor must retain immutable RC-7C ancestry and all
other protected blobs, and requires independent review before release wiring.

Linux exact-head CI is pending publication at the time this document is committed.
Final run/job IDs, full pytest exit/supervisor/artifacts and explicit Linux V9-P1
results belong in the Draft PR and private handoff, not an invented green claim here.
Existing workflow definitions and required checks are unchanged.
Actual deployed Linux cgroups, service lifecycle and production concurrency remain
unverified: no SSH, staging access, deployment or activation was performed.

No self-approval, merge or deployment is authorized by this report.
