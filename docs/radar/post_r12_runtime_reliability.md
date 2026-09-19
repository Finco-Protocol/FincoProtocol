# Post-R12 Runtime Reliability — Astra N01–N04 Closure

Runtime-reliability correction over the canonical P1 acquisition runtime
and the P2 Radar v1 UI.  Frozen R0–R12 authority is untouched; the P3
settlement branch (`radar/post-r12-p3-settlement-quote-context`, PR #35)
is preserved unmerged and NOT included here.

## N01 — service-wide provider-work bound (MAJOR)

Before: every acquisition created its own `ThreadPoolExecutor`, so
`max_concurrent_providers` bounded each acquisition pool separately, and
timed-out-but-still-running provider work accumulated across
acquisitions (`shutdown(wait=False)` cannot kill running threads).

Now: ONE executor is owned by `AcquisitionService` (created once, fixed
worker count = `max_concurrent_providers`) plus a bounded admission
semaphore of the same size.  A provider work item is submitted only
after a capacity slot is acquired (non-blocking); the slot is released
inside the worker when the provider callable actually returns/raises —
coordinator timeouts NEVER release capacity for still-running work.  The
executor queue therefore never grows beyond the admitted items.  When no
slot is available the provider fails closed immediately with the stable
typed result `TIMEOUT` / `PROVIDER_CAPACITY_EXHAUSTED` — no indefinite
blocking, no claim of cancelled threads.  Adapter-level I/O timeouts
remain required and unchanged.

`AcquisitionService.close()` provides idempotent lifecycle teardown of
the service-owned executor; already-running Python callables cannot be
force-killed and no correctness depends on `__del__`.

## N02 — worker-side completion time decides deadlines (MAJOR)

The provider worker now returns an internal `ProviderExecutionOutcome`
envelope capturing `dispatch_mono` and `completed_mono` — the completion
timestamp is recorded INSIDE the worker immediately when the callable
returns/raises.  The authoritative deadline decision
(`_deadline_outcome`) compares `completed_mono` against the immutable
limiting deadline `min(provider_deadline, total_deadline)`:

- completed after the limiting deadline → `TIMEOUT` even when the
  future is already done (`TOTAL_BUDGET_EXHAUSTED` when the total budget
  was limiting, else `PER_PROVIDER_TIMEOUT`);
- completed before the deadline → the genuine result is preserved even
  when the coordinator collects it late;
- still running at the decision point → typed timeout, capacity still
  held.

`elapsed_ms` semantics: completed providers report the actual
dispatch→completion interval; timed-out still-running providers report
the authoritative deadline-decision time.

## N03 — refresh offloaded from the ASGI event loop (MAJOR)

`POST /radar/refresh` now awaits
`run_in_threadpool(get_service().acquire, request)` (Starlette-native
threadpool; no request-local executor).  The ASGI integration test runs
a ~600 ms refresh and a lightweight heartbeat concurrently against the
REAL `main_web.app`: the heartbeat completes in well under half the
provider duration while the refresh performs exactly one acquisition and
binds exactly one snapshot_id.  This test fails against the previous
direct blocking implementation.

## N04 — mobile containment (MINOR)

Long unbroken identifiers (snapshot ids, fingerprints, digests,
lineage values) now wrap inside their panels: the Radar grid uses
`minmax(0, …)` columns and value cells carry `min-width: 0`,
`max-width: 100%`, `overflow-wrap: anywhere`.  The intentionally
scrollable evidence `<pre>` is unchanged.  A real headless-Chromium test
(`playwright`) proves at **390 px** — page shell, refreshed panels, open
Evidence Inspector — that
`document.documentElement.scrollWidth <= window.innerWidth` (+2 px
rounding), with a 1440 px desktop non-regression pass, against the real
`main_web.app` served by uvicorn.
