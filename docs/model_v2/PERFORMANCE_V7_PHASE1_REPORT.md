# Performance V7: Phase 0 and Phase 1

## Provenance and scope

- Base/live main verified during development: `97de3833449d91f3febc450c7e163287b63e208d`.
- Branch: `perf/model-v7-diagnostics-lazy-render`. Candidate SHA is the commit containing this report; publication metadata records the exact HEAD.
- Local evidence only: Windows, Python 3.12.10, Chromium 151.0.7922.34, authenticated synthetic 40 MW Solar/Wind projects, isolated disposable SQLite. No staging access or deployment.
- Five samples per vertical per operation, identical benchmark and edits on detached base and candidate. Sequential before/after fixtures, not interleaved statistical trials. Candidate enables timing observation; base lacks it.
- Private audit inputs, databases, logs, JUnit and screenshots remain outside Git. The adjacent measurement JSON contains sanitized synthetic timings/byte counts only, not source models, credentials or financial authority.
- No changes to financial_engine, finco_core, domain, financial evaluators, persistence, Run/CAS, release flags, pins, workflows, goldens or tolerances.

## Implementation

1. `app/services/model_performance.py` adds opt-in ASGI Server-Timing and duration-only structured logs. `FINCO_MODEL_PERF_ENABLED=1` is required; default is OFF. ContextVar state is per request and reset on exceptions. Labels are fixed; no SQL, paths, inputs, owners, tokens, project names or financial values enter the timing logger.
2. Ordinary workbook GET retains the original Quality evaluation and an equivalent Model Health summary, but does not call the full period/DX Diagnostics projection or serialize its payload. `?sheet=diagnostics` explicitly requests the full view. Hash/deep-link navigation loads it on demand.
3. Existing `/v2/workbook/diagnostics` remains the read authority: authentication, accessible-project resolution, request-context binding, final coherence validation and no-store remain intact. No engine execution is introduced.
4. Hidden panels receive/invalidate a small placeholder after mutations. Visible panels fetch the latest coherent view. Page-local single-flight state avoids repeat navigation GETs until invalidated. Failed reads show UNAVAILABLE and an explicit retry; NOT_RUN stays NOT_RUN.
5. Each read has its own temporary HTMX request source. An old held request cannot serialize/block a newer Run's read. Generation, project/hash, original target and pending-write guards reject obsolete responses before any OOB processing. Detached-source listeners remain effective. Late completion cannot change a newer view's busy state or focus.
6. `diagnostics_client_v1` removes duplicated groups/top-issues, the server-rendered waterfall/inventory and only EXACTLY inherited per-period check/Run/source metadata. Unexpected identity differences are retained, not overwritten. All 30 Quality checks, nine DX checks, values, residuals, severity, heatmap and root-cause evidence remain unchanged. Bankability/history/reserve-binding metadata stays for existing acceptance consumers. HTML-safe JSON encoding is retained.
7. The grid emits two Diagnostics-only lifecycle notifications around its existing Save promise. Its writer, CAS, financial semantics and other refresh fan-out are unchanged. No optional Investor or broad navigation redesign was included.

## Before/after: wall-clock milliseconds

Median (observed min-max), five samples each. Save rows below are authenticated browser fetch HTTP measurements, NOT whole perceived editing workflows; returned mutation HTML is not inserted by the benchmark. Separate real browser acceptance exercises actual swaps and fan-out.

| Operation | Solar base | Solar candidate | Wind base | Wind candidate |
|---|---:|---:|---:|---:|
| Fresh-context workbook open | 1904 (1774-1950) | 1542 (1305-1848) | 1739 (1317-2047) | 1504 (1329-1664) |
| Repeated workbook open | 1722 (1552-1830) | 1476 (1103-1728) | 1814 (1421-2120) | 1299 (1188-1515) |
| Scalar Save HTTP | 183 (131-183) | 138 (122-185) | 189 (162-221) | 126 (124-150) |
| Diagnostics GET | 932 (637-1022) | 657 (583-997) | 823 (643-967) | 738 (594-970) |
| Statements GET | 385 (292-402) | 394 (296-539) | 412 (185-574) | 320 (301-576) |
| CAPEX line Save HTTP | 1143 (1127-1278) | 665 (636-1186) | 1108 (667-1480) | 724 (630-855) |
| Committed Run HTTP | 5050 (3312-6241) | 5285 (4408-5894) | 3031 (2505-4469) | 3860 (2359-4972) |
| First Diagnostics navigation | 504 (439-595) | 1702 (1204-1818) | 463 (344-580) | 1454 (1271-1470) |

First Diagnostics navigation is intentionally more expensive: the old page had already paid its computation/download cost. Previously loaded navigation does not re-fetch without invalidation. This is a tradeoff, not an acceleration claim.

### Payload, DOM and network

Median bytes/elements/requests; raw sample ranges, TTFB, DOMContentLoaded and responseEnd are in `PERFORMANCE_V7_LOCAL_MEASUREMENTS.json`.

| Metric | Solar base -> candidate | Wind base -> candidate |
|---|---:|---:|
| Initial uncompressed HTML | 4,790,947 -> 1,583,863 (-66.9%) | 5,131,561 -> 1,646,997 (-67.9%) |
| Initial DOM elements | 23,593 -> 16,106 (-31.7%) | 24,814 -> 16,748 (-32.5%) |
| Initial resource requests | 53 -> 55 | 53 -> 55 |
| Initial TTFB, ms | 1497 -> 986 | 1295 -> 938 |
| Diagnostics fragment bytes | 3,407,502 -> 1,743,838 | 3,688,746 -> 1,870,944 |
| First sampled Diagnostics JSON bytes | 2,524,312 -> 894,273 | 2,743,026 -> 962,056 |
| CAPEX Save response bytes | 3,823,679 -> 582,512 | 4,120,955 -> 597,707 |
| Run response bytes | 3,984,805 -> 758,047 | 4,299,855 -> 795,715 |
| Hidden Diagnostics GETs after real grid Save | 1 -> 0 | 1 -> 0 |

Encoded body size equalled decoded body size in this local server: no HTTP content compression was observed. These are actual browser byte counts, not gzip estimates. Initial request count is NOT reduced: one new loader asset and timing-dependent existing lazy requests account for the observed 54-55 range. Other Save fragment requests are deliberately retained.

The >=50% initial uncompressed reduction target passes independently of compression. Warm repeat medians are below 1.5 s, but fresh-context medians (1.542/1.504 s) and some warm samples miss it. This is NOT a universal <=1.5 s acceptance result.

### Observable stages and limits

Candidate median stage milliseconds:

| Stage | Solar | Wind |
|---|---:|---:|
| Initial server span | 983 | 933 |
| Initial workspace/project reads | 51 | 50 |
| Initial input construction/identity helper | 21 | 29 |
| Initial Insight projection (inclusive) | 114 | 96 |
| Initial workbook template render | 107 | 109 |
| Diagnostics GET full projection | 163 | 203 |
| Diagnostics GET JSON serialization | 21 | 29 |
| Diagnostics GET template render | 191 | 163 |
| Diagnostics GET snapshot capture | 86 | 77 |
| Diagnostics GET final coherence check | 38 | 38 |
| Run worker roundtrip | 4589 | 3197 |
| Run model-completed -> persistence-completed | 51 | 68 |
| Run persistence-completed -> response-generated | 456 | 520 |

Stages are inclusive/nested and NOT additive. `response_assembly` observes the Smart Panel/Health/Diagnostics helper, not all thirteen OOB templates. Other workbook rendering is included in server/post-engine spans; do not interpret the tiny placeholder render as the total render cost. The commit-boundary interval contains existing post-engine preparation as well as persistence; transaction internals are not separately measured.

Base's existing Run stage logs report median worker-boundary 3703/1797 ms and post-persistence response generation 1062/1077 ms. Candidate post-persistence work shrinks, while observed complete Run medians rise 4.7%/27.3%. The higher worker-boundary samples remain unattributed, with overlapping total ranges. Pure engine CPU, admission/IPC components, SQL breakdown and network transport overhead are NOT isolated. No overall Run acceleration or native-engine justification is claimed.

## Correctness and local acceptance

- Existing route/display/Insight ring: **33 passed**, normal process exit 0.
- Diagnostics V1/V2 and real Runs, scenario identity, Integrity, request context, Q4 and Compare ring: **235 passed**, normal exit 0.
- Final instrumentation/lazy route tests: **10 passed**, normal exit 0. Explicit mocks assert full Diagnostics is never called on ordinary GET or Save. Four-vertical full findings and Model Health HTML match exactly; compact period evidence reconstructs field-for-field.
- New Chromium suite: **5 passed**, normal exit 0. Solar/Wind, 1440/1366/390 px, light/dark, hidden/visible Save, single-flight, keyboard drill-down, deep-link reload, Back/Forward, delayed stale response, 503/retry/focus and NOT_RUN.
- Existing Diagnostics Chromium suite: **13 passed**, 17 unrelated deselected, zero skips, normal exit 0. Includes four verticals, failed period evidence, mobile, advanced checks/actions and committed Run comparison. Existing delayed-read test retains its assertions and explicitly opens the now-lazy panel before holding a read.
- Baseline and candidate benchmark: **2 passed each**, normal exit 0, five samples for all eight actions per vertical.
- Independent unchanged-base browser controls: **3 layout cases and 2 hidden-Save cases passed**. The latter directly observed one eager Diagnostics GET per hidden Solar/Wind Save, compared with zero in V7.
- Public repository source safety: PASS. Python compilation, JS syntax and diff hygiene: PASS.
- No full local Public suite or staging acceptance claimed. Exact-head GitHub/integration CI remains a separate release gate.

Independent read-only SQLite comparison covers every numeric leaf in persisted summary, Senior schedules, tax, statements, distribution schedules, sponsor schedules and Integrity evidence after identical edits. It compares representations as well as numeric values (including signed zero); identity strings are not compared across distinct Runs.

| Fixture | Numeric leaves | Differences | Maximum residual | Before/after numerical SHA-256 |
|---|---:|---:|---:|---|
| Solar | 5831 | 0 | 0 | `41a403ce7a923e80506cdfd27db5bc7d8f604b9697d5e20d20b95bc220ba03ee` |
| Wind | 6324 | 0 | 0 | `08ffaa37b1870c069ee170186c24d0be01b1f38f77d00e4d3d090db76bf2905a` |

Separate tests prove same-workspace identity, timestamps, financial statements, Integrity and immutable history do not change on Diagnostics reads or Save presentation. Different genuine Runs retain their own identities. Authorization is tested for unauthenticated, other-owner and protected-reference reads; concurrent changes fail UNAVAILABLE rather than promoting stale evidence.

## Existing issue and parallel integration

An independent unchanged-base Chromium control reproduces desktop shell overflow: document width 1801 px at both 1440 and 1366 px, versus 390 px at the mobile viewport. V7 does not change CSS. New tests require no regression from that control and retain contained Diagnostics table scrolling/mobile width. This is an existing UX backlog item, not a V7 financial or navigation fix.

- #299 (initially `daa6f2bd425313c94378628536642bc50a8c56e4`, refreshed to `daebbe083eebe920c7931a70fe41b587c99b7682`) owns scenario/effective-input and scenario-scoped Trust/Integrity/freshness. Its later Run evidence/rename edits remain outside V7. V7 does not cherry-pick or overwrite those changes. Shared boundaries: initial Diagnostics choice in `v2_workbook`, optional argument in `_attach_insight`, Diagnostics render branch in `_build_smart_panel_oob`.
- #300 (`59f04df51bef89344ee8e5410320d7f59ddfbd42`) owns Compare/Sensitivity/Goal Seek; router changes are in separate functions.
- #301 (`9ff6104ee343accdce9f73c58120d332a1f6514a`) has no direct changed-file overlap.
- Owner confirmed these boundaries for RC-5 coordination. The coordinator owns conflict resolution and combined regression acceptance. Scenario Base/Upside/Downside CURRENT/STALE/Integrity tests from #299 and comparison/sensitivity tests from #300 MUST pass on the actual combined integration HEAD; standalone V7 results are not a substitute.
- A remote coordinator integration branch was observed at `07bffce47f7b374f2bd9bbe5997103d925eb736e`; V7 did not modify or merge it.

## Reproduction and Phase 2

Run `tests/perf_model_v7_diagnostics.py` explicitly (it is not auto-collected). Set `V7_BENCH_DIR` and `--basetemp` to disposable directories outside the checkout, use Python 3.12 and Chromium, `FINCO_MODEL_EXECUTION_MODE=process`, `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1`, `PYTHONUTF8=1`, and a transient test secret. Enable `FINCO_MODEL_PERF_ENABLED=1` only for candidate profiling. Never point this fixture at service databases. Preserve raw samples, not just medians.

Next bounded work:

1. Profile the remaining unattributed initial server work. About 1.6 MB/16k elements still render eagerly; Financial Statements remains approximately 1 MB as a standalone fragment. Consider lazy Statements/Outputs with the same authorized snapshot pattern.
2. Scope a Phase 2 Save-refresh contract: preserve canonical STALE immediately, update edited cells/identity, and refresh only relevant visible projections. Do not mix it with financial writer/CAS changes.
3. Investigate existing Investor/other fragment initialization requests separately; not changed here.
4. Investigate worker-boundary timing with dedicated CPU/admission/IPC evidence before proposing solver changes. React or native finance rewrites are not justified by this experiment.

Disposition: **PERFORMANCE_V7_PHASE1_READY_FOR_INDEPENDENT_REVIEW**, subject to exact-head CI and coordinator-owned combined RC-5 regression. No merge, deployment, release activation or self-approval.
