# V9-P1 - speculative execution of the unchanged G2A trajectory

## Authority and scope

Baseline: `5996453b8d5bbfaa48bc06922fc6963cf94d2f84` (merged RC-7C).
This candidate does not import, merge or cherry-pick #327, #324 or #322.
Only `financial_engine/financing/project.py` and the new
`financial_engine/financing/speculative.py` change protected source.
The copied acceptance/compare tools are unprotected test tooling, not joint-solver activation.

No financial policy decision is implemented: the original zero seed, complete
DSRA/IDC/SHL trajectory, all intermediate refusals, final handshakes and numerical
tolerances remain authoritative. OD-R and OD-1 are explicitly outside this PR.
In particular, the research's proposed final-state-only SHL maturity treatment is
NOT adopted, including for cases alleged to be falsely rejected by the baseline.

## Execution and decision order

For each original SHL candidate, the original funded input construction is
extracted into a local builder with unchanged arguments and typed replacements.
The capacity, funded and optional strict model calls still invoke the original
`run_senior_debt_model`. Serialization provides independent immutable snapshots;
no financial object is shared mutably with a helper.

Capacity verdict and its unavailable-result check are consumed first. A
speculative funded-input construction failure retains its original exception and
cause chain until its original position, after the capacity verdict. Funded results are consumed
next. The strict result is consumed ONLY under the original service-budget
trigger, with the original accuracy settings, final budget check and diagnostics.
Strict speculation starts only after that session has actually needed strict once,
and only when three helper slots are configured. It never changes that trigger.

Unused work is cancelled where possible or drained before the next iteration and
before the owning execution scope closes. It cannot raise a financial refusal.
On a worker exception, source mismatch, crash, timeout or process-start failure,
the required original call executes in-process at its original decision position.
Worker exceptions are not unpickled as financial exceptions. Native replay is
outside transport exception handlers, preserving native type, text and cause chain.

## Runtime boundaries

- `FINCO_G2A_WORKERS=0` is the default and retains serial execution.
- Allowed requested helper counts: 0, 1, 2, 3. Invalid settings are serial.
- `FINCO_G2A_TASK_TIMEOUT_SECONDS` defaults to 30, bounded to (0, 180].
- Every pool uses `multiprocessing.get_context("spawn")`, never fork.
- Daemonic owners, denied process creation and unknown CPU availability fall back
  to serial. CPU availability accounts for affinity and Linux cgroup v1/v2 quotas,
  including the current cgroup's ancestors.
- Requested helpers are conservatively capped at
  `floor(effective_cpus / (web_workers * model_concurrency)) - 1`, never above 3.
  This reserves a parent CPU and does not pretend to implement global admission.
- The existing application admission/executor/timeout/persistence code is untouched.
- A nonblocking per-process ownership lock prevents two requests sharing a helper
  batch. A competing request uses serial execution, not another request's context.

The pool is process-local infrastructure, not a result cache. A fresh
`engine_run_scope` encloses every helper task and its memo is discarded afterward.
No input, output, tenant or project identity is retained in global helper state.
Only operational counters, PIDs, source identity and process peaks remain.

## Source identity and lifecycle

Each owner and newly spawned helper independently fingerprints all Python sources
under `financial_engine`, `finco_core`, `domain` and `app`, requirement files,
Python/platform identity, dependency versions and numeric thread configuration.
Required source evidence must exist. Every task/result binds the expected identity;
a mismatch cannot supply a financial result.

As with the application's existing imported Run graph, source must be immutable
for the process lifetime. Source replacement requires restarting Run workers;
this is not a hot-reload protocol or a financial-content approval mechanism.

Helpers are reused within one owning process to avoid paying spawn/import costs
on every iterate. Orderly owner exit closes them through a multiprocessing finalizer
before automatic child joins. A standard parent-sentinel watcher also exits helpers
when the owning worker dies without finalizers. No deployment hooks are changed.
Timeout/crash cleanup terminates only the helper pool, joins it and preserves serial
execution. Python 3.12's process cleanup uses the same private `_processes` inspection
pattern already used by the application's test/runtime cleanup; other Python
versions require explicit compatibility testing.

## Performance truthfulness

The application's existing prewarm imports the canonical Run graph, not this
helper pool. The first enabled Run therefore pays helper initialization. Cold
and warm measurements must remain separate, and all source handshake, dispatch,
serialization, transfer, draining and required replay costs must be counted.

The Opus reproduction used fork, not production spawn; its measured percentages
are research observations, not acceptance results for this implementation.
Local Windows results and Linux CI results must be reported independently.
CPU, per-process memory, simultaneous Runs and small Data Center/EV workloads
must be assessed alongside isolated speed, not omitted to make a chart favorable.
Explicit opt-in is not evidence of profitability. Default serial is retained;
if automatic safe/profitable selection or end-user benefit is not proven, the
candidate must remain NO GO rather than being presented as a shipped optimization.

## Governance and release

`V9P1_CANDIDATE_MANIFEST.json` is an exact-content SUCCESSOR PROPOSAL ONLY.
It is not a release map, Financial Owner decision or independent acceptance.
The proposal roots in the immutable RC-7C main and changes only two exact paths;
all remaining RC-7C content and historical authorities are preserved.
Negative proposal tests reject changed/missing blobs, unrelated financial/core/
domain/writer changes, invalid ancestry, changed guards and quarterly activation.

No historical map or effective frozen-namespace guard is changed. Consequently
an unapproved protected diff may correctly fail Public Safety. This must be
reported, not disguised as a financial arithmetic failure or bypassed. A new
effective successor state requires independent exact-content review; its scope
must preserve RC-7C ancestry and historical mutation controls, never rewrite pins.

Quarterly product admission remains OFF. No Revenue V3, BESS, Junior or joint
solver activation is introduced. No schema, worker application, CI, golden,
tax, debt, waterfall, statement or return formula is changed outside the two paths.

## Acceptance evidence

The V9 matrix tool compares all 63 original cases at 0/1/2/3 helpers with immutable
baseline output and input fingerprints. The supplied 58-name Opus inventory is
a subset; the five additional cases include policy overrides and isolated 3/3
composition. Isolated quarterly tests do not enable production admission.

Platform-independent pytest exercises real spawned helpers, failure replay,
timeouts, cause/precedence, immutable task isolation, prohibited resources,
existing nested application workers and abrupt parent death on Windows and Linux.
Financial CI tests explicitly isolate widths on small CI hosts; production CPU
admission is independently tested and is not overridden in application code.
`tools/v9p1_worker_benchmark.py` measures the actual application Run worker and
complete returned objects, not an HTTP route, database commit or UI render.

Actual deployed Linux resource limits, systemd lifecycle and production load are
not observed by a hosted CI runner. They remain deployment acceptance requirements;
no SSH, staging mutation or deployment is authorized by this workstream.
