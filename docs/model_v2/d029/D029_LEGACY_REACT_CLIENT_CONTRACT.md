# D-029 Legacy and React client contract

Inspected actual callers: React `workflow/WorkflowBar.tsx` -> `api.ts::runModel`; Legacy `_v2_run_controls.html`
and header controls forwarding to its real form; `static/js/workbook_v2.js::_tryFireQueuedRun` collects its
hidden fields then uses htmx.ajax after Saves settle. inputs_grid_v1 also guards the canonical form.
No alternate engine route is proposed. Current React uses synchronous useRef single-flight and an unresolved
outcome lock; its success reconciliation counts history rows, which is insufficient for exact intent replay.

Deferred React: generate crypto.randomUUID per explicit action, persist key WITH ORIGINAL version/hash/request
binding across unknown response/reload, retain synchronous flight guard, and reconcile the exact returned
history ID. Never clear an unknown key just because a newer Last Run exists. Success may be historical REPLAYED.
The old history-count growth heuristic must not reject a valid same-ID replay or misidentify a concurrent Run.

Deferred Legacy: cryptographically generated initial form key (server-rendered or real browser crypto), retained
across unknown response and OOB refreshes caused by Save; new key only after definitive completion/new action.
Queued htmx.ajax must include that SAME form key; a re-render must not accidentally create a fresh unknown intent.
Reconcile unknown key after reload using original binding; use actual server-issued Run CSRF each time.
Add real browser lost-response/reload/replay-after-edit/newer-Run coverage for both clients.

Missing-key external callers retain existing non-idempotent behavior during optional migration; current foundation
changes NO caller and provides NO HTTP guarantee. Do not activate a required-key policy without owner approval.

## Status boundary

Implemented: isolated reservation, lookup/reconciliation, schema audit, fencing and cursor finalization helpers.
Proven: the executed persistence-only and released-baseline checks listed in `evidence/D029_LOCAL_TEST_RESULTS.json`.
Proposed policy: `D029_OWNER_DECISION_REGISTER.md`; no production rollout is enabled.
Deferred integration: canonical HTTP Run, financial commit hook, startup migration and real clients, after FIN-VAL #383 merges.
Owner decisions: retention, expiration/retry and compatibility semantics remain open.
Residual risk: the currently released Run route still permits duplicate commits; isolated tests do not prove end-to-end idempotency.
