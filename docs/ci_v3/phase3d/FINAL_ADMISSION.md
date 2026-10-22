# Final technical closure — admission stays closed

Merged starting point: main `c398bc600955a59a7bd8665c9cc39e37a290e922`, whose
tree equals #344 final HEAD `b7542e36ae13582f00f663c20fdeb0789ffb3e67`.
All seven required #344 exact-head checks succeeded. No financial/application
source, dependencies or mandatory workflow is changed by this correction.

## P0A correction and regression protection

Independent reproduction found the original final stats checkpoint occurred
before actual workload completion in seven observed failures. Cold worker entry
took 0.729–0.866 seconds; the original request-relative waits left about 0.7
seconds around the unchanged 1.5-second workload. The original finish callback
released capacity after actual completion. Same-executor re-admission succeeded.
Sequential Docker failures and mixed four-CPU results exclude a claim that merely
adding CPU reliably fixes the test. These are bounded local observations.

The test now uses a spawn-safe owned Pipe acknowledgement immediately before
calling the SAME `spin(1.5)` helper. Missing/invalid readiness is failed bounded
setup, not a skip. The existing 0.4-second cancellation, CancelledError, active=1
while calculating, 1.8-second follow-up, active=0 and same-executor re-admission
assertions are preserved. No post-checkpoint wait turns failure into success.
Both premature release and never releasing capacity are exercised as deliberate
subprocess defects; the real original assertions must reject each one. Parameter
IDs for readiness negatives are fixed, including the current-parent-PID case.

The 0.6-second actual-target-runner calibration remains a separate, unapproved
pilot requirement. This test correction neither changes that threshold nor
authorizes a hosted calibration. No production release-on-cancellation behavior
is introduced; that would violate the capacity bound.

## Application lifecycle boundary

`LIFECYCLE_PROPOSAL.md` is a separate focused product correction proposal, not
implemented here. Existing characterizations pass while documenting unsafe
ownership: repeated demo startup creates unowned threads; warmer stop returns
before in-flight work and lease cleanup complete. A real owned-thread/SQLite
experiment confirms the lease remains held until work exits and a manual join
finishes. It uses mocked acquisition, not live RPC or financial mutation.

Financial/Application/Security/CI review is required before changing application
startup/shutdown. Retain ownership, use cooperative stop/interruptible waits,
bound acquisition, join and verify heartbeat/loop completion before closing
resources, and fail incomplete shutdown. Test repeated lifespans, in-flight stop,
residual writes and timeout negatives. No thread is permitted solely by name.
The test-only executor shutdown helper can terminate stragglers and must not be
copied unchanged into production financial execution.

## Concrete remaining admission inputs

The task evidence ZIP carries the final-source inventory, original-node/JUnit
accounting, unapproved 43-record owner table, source-gap matrix, duration weights,
partition recommendation, original local receipts and exact GitHub snapshots.
Historical positive evidence is not promoted across the changed test/helper tree.
Collection-skipped modules remain separate from executed original IDs.

Passing standalone modules does not establish complete worker phase equivalence,
approved fixture/group isolation, background-thread cleanup or service provenance.
The independently pinned full control and each of three workers must supply
original setup/call/teardown outcomes, exact nonpass/collection skip reasons,
native JUnit, normal exit and actual cleanup. Bind mandatory browser evidence
separately. If ordinary control artifacts lack independent cleanup, the smallest
additional recorder is one separately authorized full advisory sequential
container on the exact approved source/image with `worker=control`; original
adapter, native JUnit and host receipt are already supported. No such run is
authorized here.

Duration measurements are source/inventory/environment-bound. Final allocation
keeps every module and original ID; unapproved groups cannot enter the hosted
planner. Singleton simulations are explicitly provisional until group review.
Pull/startup, source preparation, execution, upload, independent verification and
cleanup are all counted. Local schedule estimates are not hosted speedup claims.

## Exact run authorization and rollback boundary

Before any pilot, independent Financial/Security/CI decisions must bind source
HEAD/tree, controller HEAD/tree/file hashes, exact workflow bytes and governance
successor, published image registry digest, complete environment, inventory,
nonpass/isolation/group policies, protected root/environment, GitHub control and
shadow run IDs/attempts, artifact provenance, one pair, three workers and budgets.
Existing proposed ceilings stay 350 shadow / 590 enumerated pair runner-minutes;
they are ceilings, not estimates or automatic spending permission. Calibration,
browser and ancillary jobs must be explicitly enumerated before authorization.

Stop on drift, unexpected IDs/skips/xfails/xpasses/deselections, phase/outcome
mismatch, failed P0A/calibration, cleanup/provenance failure or budget exhaustion.
Cancel siblings, preserve artifacts and original failures, and do not retry
automatically. Keep mandatory sequential Public Safety and governance unchanged.

Only after an independently accepted comparable pair with >=2x measured
workflow-start-to-verified-proof candidate-path speedup may owners consider
Phase 4. A smaller improvement is technical feasibility only; one pair is not
repeatability. Minimal Phase 4 scope is a separately reviewed mandatory job
implementation change preserving required contexts, full coverage, provenance,
merge-tree guard, browser and financial/governance checks. Keep the former full
sequential workflow deployable as rollback until retirement is separately
approved. A failed activation rolls back through a normal reviewed change;
there is no force push or silent fallback that conceals failed evidence.

No image publication, workflow deployment, active root, hosted pair, mandatory
parallel activation, owner approval or merge is performed by this PR.
`admission_ready=false` remains mandatory.
