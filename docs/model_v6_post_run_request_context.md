# Model V6: Coherent Post-Run Request Context

## Entry And Scope

Base: `92615601eb702edd37285c1119737950ac054f27`, including merged PRs #218 and #219.
Branch: `perf/model-post-run-request-context`.

This is an application-layer read/presentation optimization. There are zero
changes to `financial_engine/`, `finco_core/`, persistence implementation,
schema, model execution, financial equations, templates or deployment.
No native solver, cross-request cache, extra dependency or global production
monkeypatch is introduced. The original non-context builder remains available.

Changed files:

- `app/v2/post_run_context.py`
- `app/v2/post_run_ui.py`
- `app/v2/router.py`
- `app/ui/trust_pack.py`
- `app/api/v1_1/institutional.py`
- `tests/test_post_run_request_context.py`
- `tools/bench_post_run_context.py`
- `docs/model_v6_post_run_request_context.md`

## Contract And Authority

`PostRunRequestContext.capture` reads an authorized project, workspace, active
scenario, scenario listing and canonical transactional composite identity in
one read transaction. The owner/project predicate is the existing canonical
`get_project` predicate. A supplied RuntimeResult is reused only when its full
identity, timestamp, provenance, summary and schedules match persisted evidence;
otherwise the canonical persisted-result adapter reloads it.

The context has a factory-only capture marker, explicit owner/project/Run/scenario
bindings and frozen fields. Records are detached immutable snapshots; nested
JSON dictionaries/lists retain existing serialization compatibility but reject
mutation. Draft inputs, composite inputs, runtime and projection evidence are
deep-copied/frozen, not merely placed inside a frozen outer dataclass.

This is server-internal request-local evidence, not an authorization grant or a
client parameter. Each capture repeats scoped authorization. Every consumer
checks scope/binding. Independent API calls retain their original authorized
read paths. The five institutional evidence consumers reuse the same snapshot
but retain their original KPI formatting, Verify registry/composer, export
metadata and integrity-check authorities. Verify is not inferred from freshness.

The context reuses draft/composite input projection, freshness, runtime result,
runtime projection, scenario identity and five institutional workspace reads.
The Senior Debt sponsor presentation reuses the same result/freshness too.
Run History continues to read real append-only history; no history is invented.

## Concurrent Requests And Scenario Restoration

Canonical Run execution, final CAS and atomic commit are unchanged. Context
capture happens after commit and the real persisted RuntimeResult reload.
A final authorized read verifies a token covering project/workspace/scenario
records and canonical composite identity. A concurrent mutation invalidates
the response; assembly retries once from fresh authorized evidence without
executing the engine. A second mutation returns HTTP 409 and reload guidance;
the successful committed Run is neither overwritten nor reported as uncommitted.
This protects coherence at the validation read, not against edits after a
response has already been sent.

PR #219 remains the freshness/restoration authority. A legacy Base Run with
`last_runtime_scenario_id=None` is CURRENT only under the original positively
proved `pre_scenario_base_equivalence` rule. Base -> Scenario -> Base and
Scenario restoration preserve the original immutable Run identity/timestamp.
No project-level result is pinned independently of scenario identity.

All 13 OOB targets remain: Run/export controls, status banner, toolbar, Overview,
Senior Debt, Tax, Financial Statements, Returns, Scenarios, workspace header,
Smart Panel and Run History. Deterministic full HTML and Trust evidence are
exactly equal to the original builder for CURRENT, STALE and NOT_RUN.

## Local Functional Evidence

Initial-head combined focused ring: **305 passed**, 130 warnings, 202.73 seconds.
Pytest exited normally with exit code 0. This comprises 24 new context cases
and 281 existing focused cases, not a full local suite.

```text
tests/test_post_run_request_context.py
tests/test_staging_acceptance_a.py
tests/test_model_v2_run_binding.py
tests/test_model_v2_run_history.py
tests/test_model_v2_ux_smart_panel.py
tests/test_model_trust_pack.py
tests/test_api_v1_1_institutional.py
tests/test_f05_shared_session_contract.py
tests/test_u2_1_v2_export.py
tests/test_f07_export_lineage.py
tests/test_f07b_canonical_export_authority.py
tests/test_p1_1_institutional_trust_pack.py
```

New coverage includes real authenticated Runs on Solar/Wind/Data Center/EV,
CURRENT/STALE/NOT_RUN, deep immutability, cross-owner/project refusal, wrong Run
reconciliation, invalid persisted authority, independent concurrent requests,
threaded edit/select during render, repeated-mutation fail-closed behavior,
legacy Base equivalence and all 13 OOB targets. Existing focused tests cover
shared sessions, Run binding/history, staging scenario restoration, Trust and
export lineage. Executor teardown uses existing safe lifecycle authority.

The first unprivileged legacy-ring attempt hit Windows temporary-directory
PermissionErrors. An authorized rerun with explicit isolated basetemp passed;
no assertions or legacy tests were changed to hide those environment errors.

## Fresh Baseline And Paired Performance

Measured 8 October 2026 on Windows 11, Python 3.12.10, AMD Ryzen 5 7535U.
Before production edits, current-main authenticated Solar/Wind baseline measured
same-snapshot builder medians 395.104/450.547 ms and post-engine medians
561/576 ms. Historical research timings were not used as acceptance evidence.

The initial-head paired run uses the unchanged non-context builder as arm A and the
production coherent entry as arm B, including capture, freezing and final
validation in its timer. Signed authenticated sessions, isolated SQLite,
real process workers and reference-seeded projects are used. Five alternating
ABBA/BAAB builder blocks provide ten samples per arm/project. Three edited
route pairs alternate AB/BA order; first-use Runs are excluded. Worker policy
cache is cleared by isolated benchmark instrumentation, never production code.
No tests or safety scan were running concurrently with the final benchmark.

| Project | Builder A ms | Builder B ms | Saving ms | Post-engine A ms | Post-engine B ms | Reduction |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Solar 64 MW | 402.216 | 198.932 | 203.284 | 671 | 360 | 46.35% |
| Wind 48 MW | 453.822 | 241.319 | 212.502 | 624 | 483 | 22.60% |
| Data Center 16 MW | 440.258 | 195.526 | 244.732 | 608 | 343 | 43.59% |
| EV Charging 1 MW | 420.838 | 237.000 | 183.838 | 639 | 453 | 29.11% |

Both Solar and Wind pass both materiality alternatives. Other technologies
show no measured application regression. There were 28 successful real Run
requests, 24 paired route HTML comparisons and 80 same-snapshot HTML comparisons.
Every deterministic comparison was byte-identical. The benchmark process exited
normally after existing executor shutdown.

Raw same-snapshot builder samples, milliseconds:

```text
Solar A: 428.170,402.781,428.777,381.678,830.562,390.923,401.650,400.186,394.476,404.729
Solar B: 229.536,233.119,231.786,178.412,199.133,184.080,193.245,200.482,198.730,197.779
Wind A: 449.647,437.500,675.123,440.761,486.083,466.981,457.997,438.913,468.244,439.865
Wind B: 233.228,236.295,427.692,241.167,262.381,253.846,241.471,368.718,238.789,235.704
DC A: 619.199,434.231,433.021,542.517,454.715,372.752,403.833,395.248,1039.957,446.285
DC B: 219.964,207.331,272.628,184.393,195.629,195.163,170.766,174.508,219.077,195.423
EV A: 400.612,372.805,405.909,436.055,362.121,446.223,435.901,435.767,382.482,500.621
EV B: 175.402,186.090,241.067,286.823,219.135,232.933,267.714,633.959,280.201,212.796
```

Raw Solar/Wind route stage samples, milliseconds. Composition is the interval
from workspace resolution to model entry; model await includes IPC. Post-engine
is the per-sample sum of persistence and response, not a sum of separate medians.

| Project/arm | Resolve | Composition | Model await | Persistence | Response | Total stage |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Solar A1 | 62 | 93 | 3391 | 77 | 483 | 4108 |
| Solar B1 | 157 | 281 | 3327 | 93 | 297 | 4157 |
| Solar B2 | 92 | 93 | 3594 | 30 | 328 | 4140 |
| Solar A2 | 77 | 109 | 3842 | 94 | 577 | 4702 |
| Solar A3 | 93 | 94 | 3796 | 78 | 655 | 4718 |
| Solar B3 | 93 | 108 | 3202 | 32 | 328 | 3766 |
| Wind A1 | 61 | 109 | 4358 | 94 | 530 | 5155 |
| Wind B1 | 94 | 93 | 4170 | 94 | 391 | 4844 |
| Wind B2 | 77 | 110 | 4093 | 92 | 327 | 4702 |
| Wind A2 | 141 | 108 | 3922 | 77 | 531 | 4781 |
| Wind A3 | 47 | 108 | 4093 | 108 | 516 | 4875 |
| Wind B3 | 94 | 108 | 3796 | 94 | 389 | 4483 |

Route medians A/B: Solar 4722.446/4143.679 ms; Wind 4898.891/4720.372 ms.
Worker wall medians A/B: Solar 3783.447/3329.475 ms; Wind 4095.874/4089.448 ms.
Worker variation is explicitly NOT attributed to context reuse. The acceptance
claim is paired builder/post-engine application savings, not a financial-engine
speedup. No wall-clock thresholds are added to normal CI.

Reproduce outside the repository artifact tree:

```powershell
python tools/bench_post_run_context.py --blocks 5 --pairs 3 --other-technologies --out ../v6-production-final-benchmark.json
```

Local raw evidence is `../v6-production-baseline.json`,
`../v6-production-final-benchmark.json` and matching logs. Final JSON includes
Python/platform provenance and SHA-256 fingerprints of all five application
sources, binding measurements to the uncommitted implementation bytes. Private
local paths, runtime databases and generated evidence are not committed.

## Safety And Linux Qualification

The unchanged full worktree public-safety scanner reported two environment/local
artifact findings: a CRLF vendor checkout invalidates its exact-byte exemption,
and a pre-existing untracked research document contains a local user path.
The canonical base vendor Git blob matches the approved SHA-256 exactly; the
worktree equals that blob after CRLF normalization, with zero vendor diff.
Neither the vendor asset nor scanner nor existing research file is modified or
included in this PR. The approved change set must pass safety independently.
All eight changed files passed the unchanged scanner's `scan_file` checks.
Changed Python files passed `py_compile`; staged diff hygiene and the frozen
namespace checks passed.

Windows timings are not a Linux deployment guarantee. Existing exact-head
Ubuntu GitHub CI is the full-suite and Linux semantic acceptance authority;
its result is recorded in the PR after push. No suitable local Linux benchmark
runner is assumed and no staging/production deployment is performed.

## Correction A: Preserve Non-Context Call Shapes

Exact-head Linux run `37760926111` completed normally and uploaded evidence,
but reported **1 failed, 8317 passed, 48 skipped** in 1052.42 seconds.
The sole failure was the existing H4b test
`test_last_run_committed_without_evidence_reads_as_incomplete_not_pass`.
It was independently reproduced locally before the fix: a legacy two-argument
workspace loader rejected the newly forwarded `context=None` keyword.

The correction keeps the original loader/adapter call shapes whenever there
is no context. An actual context still follows the scoped optimized path.
All five institutional consumers receive the same narrow compatibility fix;
there is no new authority, financial behavior or abstraction. The existing
H4b test and its INCOMPLETE-not-PASS assertions are unchanged. Five new cases
lock the old call shapes and identical evidence for all five consumers.

Corrected focused ring: **346 passed**, 138 warnings, 212.86 seconds, normal
exit code 0. This comprises the original 305 cases, five new compatibility
cases and the 36-case H4b suite. Changed Python compile checks and frozen
namespace checks pass. No full local suite was run.

The same paired benchmark was repeated on the corrected application bytes,
again with five builder blocks, three edited route pairs and no simultaneous
tests. All 28 real Runs, 24 route HTML and 80 builder HTML comparisons passed;
the process exited normally. Current acceptance medians are:

| Project | Builder A ms | Builder B ms | Saving ms | Post-engine A ms | Post-engine B ms | Reduction |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Solar | 344.919 | 200.772 | 144.147 | 437 | 264 | 39.59% |
| Wind | 340.324 | 166.295 | 174.029 | 452 | 294 | 34.96% |
| Data Center | 329.883 | 148.389 | 181.494 | 452 | 296 | 34.51% |
| EV Charging | 352.451 | 198.516 | 153.935 | 499 | 296 | 40.68% |

Solar clears the >=20% post-engine alternative, not the separate >=150 ms
builder alternative. Wind clears both. No engine speedup is claimed.
Route medians A/B: Solar 3255.485/3101.745 ms; Wind 3799.920/3653.408 ms.
Worker medians A/B: Solar 2674.896/2628.383 ms; Wind 3197.872/3194.305 ms.

Current raw same-snapshot builder samples, milliseconds:

```text
Solar A: 420.761,439.631,396.152,346.337,332.117,719.321,331.312,336.551,343.501,335.205
Solar B: 226.187,215.349,174.910,196.283,187.510,205.260,219.972,237.124,154.580,158.934
Wind A: 371.223,349.937,331.034,370.543,339.569,336.226,351.913,337.999,334.088,341.079
Wind B: 171.064,167.488,255.724,157.704,163.879,177.030,170.025,163.891,162.722,165.103
DC A: 328.426,319.055,348.835,361.949,313.834,311.595,314.471,353.973,808.825,331.341
DC B: 161.680,144.238,147.971,142.054,145.050,143.766,149.025,149.970,162.952,148.808
EV A: 324.600,312.445,326.234,317.231,352.569,365.520,391.263,779.603,498.708,352.334
EV B: 175.626,140.827,215.854,159.359,204.325,182.993,192.707,215.987,247.056,235.384
```

Corrected raw route stages, milliseconds:

| Project/arm | Resolve | Composition | Model await | Persistence | Response | Total stage |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Solar A1 | 47 | 77 | 2922 | 46 | 391 | 3484 |
| Solar B1 | 125 | 94 | 2609 | 45 | 219 | 3094 |
| Solar B2 | 61 | 94 | 2968 | 31 | 218 | 3375 |
| Solar A2 | 63 | 61 | 2672 | 30 | 407 | 3234 |
| Solar A3 | 47 | 77 | 2688 | 30 | 422 | 3266 |
| Solar B3 | 77 | 78 | 2625 | 46 | 233 | 3061 |
| Wind A1 | 30 | 94 | 4233 | 30 | 422 | 4811 |
| Wind B1 | 219 | 93 | 3202 | 31 | 250 | 3797 |
| Wind B2 | 46 | 78 | 3234 | 61 | 233 | 3655 |
| Wind A2 | 62 | 92 | 3125 | 63 | 436 | 3780 |
| Wind A3 | 61 | 77 | 3204 | 31 | 421 | 3796 |
| Wind B3 | 63 | 61 | 3188 | 61 | 234 | 3609 |

Raw corrected evidence is `../v6-correction-a-benchmark.json` and its log.
Capture, identity verification, freezing, final coherence validation and
rendering remain inside the paired candidate timer. A new exact-head CI run
must pass before review of this correction; the failed initial head is not
merge-approved merely because most tests passed.
