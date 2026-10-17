# Performance V7 Phase 2

## Provenance and Boundaries

- PR: #303, `perf/model-v7-diagnostics-lazy-render`; Draft, no merge or deployment.
- Main/base: `97de3833449d91f3febc450c7e163287b63e208d`.
- Measured Phase 1 control: `fb7b4514090a190b7fc97fdb592b3126e82dfcb1`.
- Addendum A fix: `9d305233cb6105aa33796d4a8a9951c6f5c0a7ba`.
- Pending-state browser assertion alignment: `c12fdf9eebe9e4d0b530f7c35504d80f8b04eccd`.
- The Phase 2 commit containing this report identifies the candidate source. Final exact-head CI is recorded in the PR, not inferred from older green runs.
- No main integration, financial calculation, writer, schema, worker, golden, activation or financial governance changes.

## Addendum A

The unchanged `test_consecutive_atomic_save_run_stale_current_with_csp_enabled` was independently reproduced on the Phase 1 control: timeout at the existing STALE assertion, pytest exit 1. The loader was replacing server-proven STALE with UNAVAILABLE merely because detailed checks needed loading.

Financial freshness and loading state are now independent. Invalidation marks details pending without inventing financial state. Successful grid Save uses the server's `run_state`; failed Save preserves prior freshness. The small placeholder retains Last Run identity and the HISTORICAL label. Health retains its server-rendered summary. Genuine failed detail reads still show UNAVAILABLE and allow retry; NOT_RUN is distinct.

The correction-only snapshot passed 18 focused tests, including the unchanged failing browser test, Solar/Wind, rejected CSRF Save, hidden zero-GET behavior, keyboard/CSP, delayed responses and immutable persisted evidence. A subsequent exact CI failure identified our Phase 1 delayed-read helper's incompatible UNAVAILABLE expectation; it now positively requires STALE plus pending, preserving every later new-Run/old-response assertion. Its isolated browser rerun passed. The original failing test function remains byte-for-byte identical.

Correction-head CI: Browser run `39037897393` SUCCESS, Governance `39037897352` SUCCESS, Security `39037897348` SUCCESS, Compile `39037897401` SUCCESS, Q4 `39037897382` SUCCESS. Public Safety `39037897403` was still running at this checkpoint; these are not final Phase 2 acceptance claims.

## Selective Save Refresh

The Inputs Grid's existing JSON Save, CSRF, scenario binding, validation and atomic CAS writer are unchanged. After success, one coherent authorized grid read refreshes the shared Run/Export controls, Overview, scenario list, Trust/Integrity and Health. It reuses the existing typed request context and performs a final current-snapshot validation before releasing HTML. Missing/obsolete content hashes and concurrent mutations fail closed.

The old five-sheet fan-out and hidden History/Outputs/Investor post-Save reads are deferred to visibility. Existing financial-integrity follow-up reads are preserved, not bypassed. No financial dependency graph is invented: all managed projections are conservatively invalidated. A pending hidden editor cannot submit old forms; a new read verifies project, composite hash, client generation, target identity and server response hash. Drafts entered while a read is pending are retained and that read is rejected. Explicit retry is required before replacing such a draft.

Existing cost-row writers can replace just a row rather than an entire sheet. A successful same-generation own-view response restores that editor's readiness without replacing remaining drafts or moving keyboard focus. Other projections stay invalidated. The existing explicit cross-sheet cost-batch acknowledgement path is retained; this is not a claim that every possible legacy writer has zero hidden refreshes.

A separately reproduced race showed a background grid snapshot starting during Run and later restoring pre-Run NOT_RUN presentation. Background reads are now refused while canonical writes are active. A successful Save's final callback also checks its captured generation before publishing state after HTMX settles. No Run/CAS implementation was changed.

After a complete successful canonical Run has actually replaced Health with CURRENT evidence, its already-rendered shared state need not be rebuilt by the following grid-marker read. That read can request the primary grid only, with the same authorization, snapshot and final-coherence gates. Any mutation invalidates this presentation-readiness marker; failed/incomplete Run responses do not establish it. A grid Save still requests the complete shared refresh.

## Lazy Statements and Outputs

Ordinary workbook GET and modern Run responses carry a small Financial Statements placeholder with the existing authoritative runtime bar, not the hidden full tables. Explicit `sheet=fs` and coherent presentation GETs still render through the existing statement helper. Financial values, totals, period axes and tree hierarchy are unchanged.

Outputs uses its existing authorized committed-Run route. A response hash and client generation prevent obsolete responses from swapping into a newer model. Loading errors remove usable-looking old tables and offer retry. Navigation/back-forward, actual CSP, keyboard navigation, narrow/dark views and all original financial cell assertions remain covered.

Default server response contracts for clients not opting into lazy views are retained. A read-only Reference remains read-only through the new refresh path. No engine execution or immutable history mutation occurs on these reads.

## Measurements

Five paired synthetic samples per vertical, Python 3.12.10, Windows, Chromium 151.0.7922.34, production process workers. Raw samples, discarded pre-optimization results and summaries are in `PERFORMANCE_V7_PHASE2_MEASUREMENTS.json`. The control and candidate were run sequentially, not randomized/interleaved; these are local measurements, not staging or Linux acceptance.

| Median | Solar control | Solar candidate | Wind control | Wind candidate |
|---|---:|---:|---:|---:|
| Complete Save UI, ms | 1748.5 | 1548.4 | 1913.5 | 1631.2 |
| Save promise/finished feedback, ms | 348.6 | 784.7 | 382.6 | 796.0 |
| Save POST, ms | 186.4 | 165.9 | 176.1 | 174.9 |
| Save requests, including POST | 8 | 3 | 8 | 3 |
| Save decoded bytes | 618049 | 401528 | 628022 | 407026 |
| Save OOB fragments | 11 | 17 | 11 | 17 |
| Save long-task total, ms | 308 | 349 | 474 | 320 |
| Save longest task, ms | 100 | 216 | 122 | 186 |
| Response application span, ms | 99.6 | 198.4 | 120.1 | 171.1 |
| Initial HTML bytes | 1584270 | 1362089 | 1648260 | 1405376 |
| Initial DOM elements | 16109 | 13126 | 16766 | 13503 |
| Hidden FS HTML bytes | 225644 | 620 | 246635 | 620 |
| Hidden FS descendants | 2989 | 6 | 3269 | 6 |
| Run HTTP, ms | 2957.6 | 2865.6 | 3373.4 | 3318.5 |
| Complete Run UI, ms | 4451.1 | 4482.5 | 4859.7 | 4917.0 |
| Run response bytes | 758343 | 536183 | 796381 | 553518 |
| Worker roundtrip, ms | 2266.2 | 2269.9 | 2674.1 | 2715.3 |
| Run prepare, ms | 91.3 | 96.6 | 92.9 | 91.7 |
| Canonical commit, ms | 80.1 | 85.7 | 80.9 | 37.9 |
| Post-engine application, ms | 502.0 | 327.9 | 361.2 | 321.5 |
| Response assembly, ms | 162.1 | 97.5 | 118.2 | 96.4 |

Complete Save improves by 200.0 ms (11.4%) for Solar and 282.3 ms (14.8%) for Wind. The complete metric includes all required reads, the same 500-ms quiet interval and two animation frames; it is not the fast JSON Save alone. Three requests are the unchanged Save, one coherent shared/grid read and the preserved Integrity read. Hidden Diagnostics and hidden legacy sheets are not fetched in this measured journey.

Trade-offs are explicit: finished Save feedback waits longer for coherent shared UI, and the consolidated response has more OOB targets and a longer individual main-thread task. Total long-task time improves for Wind but not Solar. A shorter first acknowledgement and further pure DOM initializer scoping are future candidates, not claimed completed here. Cumulative swap spans overlap and must not be summed.

Run end-to-end does not improve in these samples (about +31/+57 ms); no overall Run speedup is claimed. Worker roundtrip contains admission/dispatch/serialization/calculation/return and is not a pure engine timer. Admission is nonblocking in the existing executor, but its duration and internal engine time are not separately measured here. Stages overlap; response assembly is part of post-engine time. First startup Run and spawn/prewarm are excluded. No worker or solver architecture was changed.

Read-only independent comparison of seven persisted output structures after the same five edits and Runs finds 5843 Solar and 6344 Wind numeric leaves, zero differences even in numeric representation, maximum residual 0. Numeric SHA-256s match on both sides:

- Solar: `ce01e08e458eccd158cfcdb0cdcc6856ba1f984dbf41d827d8eeae877ba24fcb`.
- Wind: `38e95d5a1103558ab2fde47e281e3c6fba55906d166be4a3e720e32f90cf1b5c`.

The compared structures are runtime summary, debt, tax, financial statements, distributions, sponsor schedule and Integrity evidence. Legitimately distinct Run timestamps/identifiers are not numerical performance targets. Browser tests independently verify that Save preserves prior committed evidence and new Run gets a new identity.

Reproduction uses the ordinary local test secret and Chromium configuration, plus:

```powershell
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD = '1'
$env:FINCO_MODEL_EXECUTION_MODE = 'process'
$env:FINCO_MODEL_PERF_ENABLED = '1'
$env:V7P2_BENCH_DIR = '<disposable evidence directory outside the checkout>'
python -m pytest -q -s -p no:cacheprovider tests/perf_model_v7_refresh.py --basetemp='<separate disposable database directory>'
```

Use the same harness and fixtures against the pinned control checkout and candidate, without other local test load. The harness is opt-in, not part of ordinary pytest discovery. The 500-ms quiescence interval is deliberately included in both reported UI timings, rather than silently subtracted from one side.

The first complete paired experiment deliberately did not pass performance acceptance: requests fell from 8 to 3, but Solar median Save quiescence increased from 1748 to 1851 ms and Wind from 1913 to 1933 ms. These measurements are retained, not presented as a speedup. Private V8 sampling identified repeated Workbook chart reconstruction during the OOB event sequence. The existing chart renderers now reuse an SVG only for the same DOM node and identical chart-type/period/target strings. Changed inputs or a replacement node render normally. This is node-local display initialization, not server-side financial caching. Non-Workbook chart dispatch and all plotting formulas are unchanged.

Earlier incomplete experiments are excluded: a dramatic Wind production reduction caused a legitimate canonical financing rejection; another launcher inherited pytest thread mode rather than production processes; 150-ms network quiescence could miss the existing 350-ms deferred refresh. The final protocol explicitly uses process workers, Overview entry and 500-ms quiet plus two animation frames, with identical fixtures and no other local test load. The 60-second network deadline and financial tolerances are not widened.

## Local Validation

- Initial broad non-browser ring: 362 passed, seven failed eager-render/trigger expectations. The two complete affected modules were subsequently rerun: 80 passed. Their financial value assertions were not relaxed; full statement comparisons now explicitly open the full statement view.
- Full tracked-source safety scan passed. Final changed/new files are rescanned before publication.
- Python compilation, JavaScript syntax checks and diff hygiene pass at the recorded checkpoint.
- Existing 30-test consolidation browser role: all passed, including the unchanged original failure, four-vertical statements, dark/mobile views, Back/Forward and both delayed-response checks.
- Extended 41-case run: 40 passed; its new pending-editor fixture initially tried to edit a collapsed cost group. Opening the real group corrected the fixture; the full draft-preservation assertion then passed.
- Grid/history rerun: 23 passed, one old test acted before new lazy readiness. That helper now positively waits for a loaded editor; the unchanged STALE, marker, Integrity and persisted-value assertions passed on rerun.
- Final optimized ring: 20 passed, covering all V7 routes/performance, read-only References, complete findings parity, chart node reuse/replacement, original CSP Save/Run, four consecutive CAPEX and OPEX immediate Saves, post-Run markers and pending-editor protection. All processes exited normally with rc=0, no skips or xfails in these explicit browser runs.
- Final control and candidate benchmark processes: 2 passed each, rc=0 and normal executor cleanup; full local pytest was not run.

The new V7-specific browser modules were executed explicitly locally. A green standard six-role Browser workflow alone is not represented as proof that those additional modules were selected by CI.

## Exact Phase 2 Inventory

The Phase 2 follow-up changes exactly these 24 files; the earlier Addendum A correction commits are separate:

```text
app/templates/v2/partials/_financial_statements_placeholder.html
app/templates/v2/partials/sheet_outputs.html
app/templates/v2/workbook.html
app/v2/grid_router.py
app/v2/post_run_ui.py
app/v2/presentation_views.py
app/v2/router.py
docs/model_v2/PERFORMANCE_V7_PHASE2_MEASUREMENTS.json
docs/model_v2/PERFORMANCE_V7_PHASE2_REPORT.md
static/interaction/overview-charts.js
static/js/fx_ui.js
static/js/inputs_grid_v1.js
static/js/model_outputs_workspace.js
static/js/model_view_refresh.js
static/js/workbook_v2.js
tests/perf_model_v7_refresh.py
tests/test_model_hybrid_inputs_grid_browser.py
tests/test_model_outputs_workspace.py
tests/test_model_v7_chart_browser.py
tests/test_model_v7_pending_editor_browser.py
tests/test_model_v7_presentation_views.py
tests/test_model_v7_refresh_browser.py
tests/test_model_workspace_consolidation_browser.py
tests/test_workflow_c_statements_analytics_trace.py
```

The Addendum A commits change `static/js/model_diagnostics_loader.js`, the Diagnostics placeholder and Health templates, `tests/test_model_v7_diagnostics_browser.py`, and the existing delayed-Diagnostics helper. They do not change the original failing atomic Save test.

## Protected Trees

Base and candidate committed trees are identical:

| Namespace | Git tree SHA |
|---|---|
| financial_engine | `9f1e2f5f227b20720407bc74662df9a7fee13c3c` |
| finco_core | `b089fe11ba8cea4dd63b124b5719db0f8006c094` |
| domain | `852c47ce3b14d0ca763cbd0ab1d0c6dcd5bdf5cb` |

There is no working-tree diff in these namespaces, workflow definitions, persistence writers, runtime freshness or composite identity authority. Release-closed features remain closed.

## Integration and Remaining Gates

PR #302 is deliberately not merged into this branch. Last inspected coordinator head: `1c8a864b8cf9510fc8148ab132588b4962720b96`. Shared changes are presentation selection in `v2_workbook`, response headers in the existing Outputs GET, lazy FS rendering and optional same-snapshot reuse in `build_post_save_ui_state`. The accepted scenario/Trust bodies, Run Compare, Sensitivity, execution, CAS and history persistence are not rewritten. The coordinator must independently verify the combined scenario/Trust and V7 behavior.

The original Public Safety run `39030581276` did not complete: supervisor budget 4800 seconds, active pytest at 11767/12300 nodes, exit 124; mandatory evidence failed downstream. This is not a passing full suite or proof of a pytest assertion failure. No timeout, test selection, evidence requirement or workflow was changed to conceal it.

Worker admission/roundtrip, engine execution and persistence are measured only. First-opening deferred panels still incurs a read/render cost; no claim of faster first-open follows from smaller initial HTML. Further worker architecture, broader projection rewrites, global CI optimization and the combined RC-5 integration remain outside this PR's authorization.

Independent review and final exact-head CI remain required. No self-approval, merge or deployment.
