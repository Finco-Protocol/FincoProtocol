# Final CI V3 integration — dormant until exact admission

Baseline: #345 merged as `dd1af63ecaf655ef3a88a308f255f7b8a5acd18f`; executed head `e77e16ef3d05a243611d40e6e3905997a81c4ede` has the identical tree. All seven exact-head checks passed. Its local isolation checkpoint covered 507 modules / 17,493 original nodes with zero nonzero modules; 68 collection-skipped modules and 43 runtime nonpass records remain separate. This is historical input after the application/controller changes in this PR; unchanged test blobs do not establish unchanged imported behavior.

## Reviewable implementation

The application commit owns the demo cleanup service, preserves its 300-second defer and TTL cadence, interrupts idle waits, drains admitted operations and bounds joins/lock waits. Warmer ownership is an exact object token. Failed deadlines retain ownership, block replacement and fail shutdown. A joinable owned cleanup task bounds SQLite/guard waiting without closing resources beneath live work. Startup ownership rejection rolls back the application's demo service; shutdown attempts both services before reporting errors. The snapshot publication fence checks the live lease holder and expiry under the same `BEGIN IMMEDIATE` transaction as the canonical batch write. Payloads, eligibility, freshness, financial calculations and Model Executor semantics are unchanged. Financial/Application/Security review is required for this application commit; the fence changes publication authority on expired/foreign leases and must not be inferred approved from tests.

The CI commit retains the separate 0.6-second calibration threshold and rejects ANY slow retained sample. Calibration subprocesses and descendants are bounded and cleaned; hosted control/workers calibrate inside their actual immutable runtime before full execution. Missing project, samples, source/run context or calibration receipt blocks admission. Local calibration is not hosted calibration.

The existing group-aware integer-duration LPT partitioner, container supervisor and exact original-node verifier are reused. No test selection is removed. Full phase comparison retains setup/call/teardown outcome, declared skip/xfail reason and xfail marker, plus native JUnit outcome/message equality. Original traceback text remains retained separately; expected-failure policy reasons use pytest's declared `wasxfail`, not nondeterministic traceback object addresses.

Runtime observations include Python/transitive distribution RECORD and native-library hashes, OS/libc/runtime tools, native-thread settings, complete final plugin registrations and host CPU/kernel/affinity/cgroup evidence. Software identity is admitted independently of incidental host CPU addresses; full host observations remain review inputs. Semantic plugin profiles normalize process object IDs and conftest root paths while retaining every registration, implementation/hash and duplicate. No ambient plugin silently disappears.

`ci_v3_pair_acceptance` authenticates the exact control and three workers, their immutable service archives and independently retained receipt anchors. It invokes the original coverage/nonpass verifier and exact phase/native comparator. It independently authenticates the actual mandatory Public Safety workflow/source/control/proof archives and six-role browser proof. An unrelated green workflow cannot be a performance baseline. Exact per-record Financial and CI decisions must match every current-source runtime nonpass status/reason before execution and acceptance. Name-only daemon survivor permissions are rejected.

## Exact spending and measurement contract

A protected root is a prerequisite, not an approval produced by these tools. It binds source, controller/all tool hashes, actual run/attempt, workflow bytes, immutable published image, reviewed inventory/policy/colocation/environment and every required decision. Both pair run IDs must be allocated and independently authorized while execution remains held. No root or workflow is activated by this PR.

The inactive candidate now has two mutually exclusive modes:

- Shadow allocation: admission 10 + plan 25 + workers 3×100 + aggregate 15 = **350** runner-minutes.
- Additional same-image advisory control: admission 10 + full control 220 = **230** runner-minutes.
- Fixed pair reservations total 580, leaving 10 within an explicitly approved **590** cap for independent verification allocation. These are maxima, not predicted usage or spending authority. Lower budgets cannot authorize the unchanged fixed timeout profile.

The existing normal mandatory control (240 timeout allocation) and browser/governance/dependency/compile (75) must be explicitly classified as pre-existing CI expenditure or separately authorized. An advisory control does not replace or erase the real mandatory sequential baseline. Their actual job-rounded usage is reported separately; none is silently free. Post-run verification rejects allocation overruns but does not authorize retries. Prospective roots validate the allocation before a worker can start.

Performance is measured from workflow creation to independent proof. The mandatory baseline ends at its authenticated `mandatory-evidence` job completion; shadow ends after independent comparison at a fresh GitHub server UTC observation. Queue, approval holds, image pulls, planning, execution, uploads, downloads and proof latency are included. A timing mismatch, missing comparable source/environment evidence or clock skew blocks comparison. Technical validity and performance success are separate: less than **2×** is not performance success. One pair does not establish repeatability or mandatory CI acceleration.

The #345 local singleton duration model predicted 43.892/43.891/43.892 execution minutes, plus 3.95–9.5 critical-path overhead. It projected only 1.22–1.36× / 1.50–1.67× / 1.82–2.03× against hypothetical 65/80/97-minute controls. These are historical local estimates, not hosted measurements. Regenerate final-source measurements and recompute all reviewed indivisible colocation groups before admission. No longest module/group may be split or disabled to manufacture speedup.

## Dormant Phase 4 implementation and rollback

`docs/ci_v3/phase4/ci_v3_required_job.candidate.yml` and `public_safety_and_smoke.candidate.yml` are exact deployment candidates, OUTSIDE active workflows. `activation.closed.json` remains disabled with rollback true. The current mandatory sequential workflow, browser workflow and governance checks remain active and unchanged.

After accepted hosted evidence and explicit Financial/Security/CI protected-source/activation review, deployment can copy the two reviewed candidates to `.github/workflows/ci_v3_required_job.yml` and `.github/workflows/public_safety_and_smoke.yml`. This is an authorization/deployment change, not another planned CI V3 implementation PR. Do not deploy different bytes under the existing approval. Review all three mandatory reusable/workflow hashes, exact controller/source, job-name prefix, protected environment rules and stable check contexts.

The selected source-specific root must match the accepted control root/artifact anchors, accepted pair, current approved policy/environment/isolation and semantic plugin profile. A stale/missing/rejected activation routes to the original sequential execution BEFORE any parallel work. Operator rollback also selects sequential before work. Once parallel work is selected, failure remains a mandatory failure; there is no automatic second full suite or spending retry. Both aggregation and the independent required gate compare this run's actual three workers with the authenticated accepted full control. The stable `safety-and-smoke / tests`, `source-safety` and `mandatory-evidence` contexts are preserved. The separate six-role browser acceptance remains mandatory.

The dormant parallel production candidate reserves **375** runner-minutes including routing, wrappers, source safety and independent proof, plus explicitly separate ancillary allocation. This is distinct from the advisory 350/590 pilot ceilings and is NOT authorized. Source/run-specific activation intentionally defaults subsequent unapproved sources to sequential; no financial policy is silently carried forward.

## Concrete gates still external

1. Exact-source Financial + CI decisions for all current nonpass records and reviewed fixture/import/colocation classifications.
2. Financial/Application/Security review of the application lifecycle/fencing commit; CI acceptance of raw cleanup evidence.
3. Published immutable image digest and independently approved environment/plugin/host comparability, including mandatory baseline differences.
4. Exact target-runner maximum-sample calibration; a failed 0.6-second gate aborts before full execution.
5. Protected-root/workflow governance, exact run/attempt authorization and complete runner-minute allocation. No retry is implied.
6. Separately authorized single hosted pair, original control/worker/native/phase/process/browser provenance, accepted >=2× end-to-end result and independent owner review.
7. Explicit production activation/deployment authority. Code merge is not activation.

Until those gates are recorded, retain the original sequential workflow. No hosted performance result, owner approval or production completion is claimed.
