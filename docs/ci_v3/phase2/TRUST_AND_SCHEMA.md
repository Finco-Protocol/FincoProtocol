# Phase 2 trust and compatibility contract

The Phase 1 inventory, policy, partition and independent V1 verifier are unchanged. Phase 2 adds schema-2 envelopes and a separate observed-execution verifier; its compatibility bridge supplies V1 evidence to the original verifier. The Phase 1 local simulated controls remain valid and non-authoritative. A schema-1 simulation is never accepted as a schema-2 OS observation.

## Independent inputs and claims

The trusted local controller obtains source HEAD/tree from a clean Git project before importing its tests. It compares tracked physical bytes with canonical Git bytes. Inventory/policy/weights come from explicit caller input, not worker-selected IDs. A separate real discovery subprocess must reproduce that complete universe before any worker starts. A changed/new test fails closed; no domain is omitted and all demo nodes are F.

The parent constructs repository, source, run ID, attempt, partition and policy digests, evaluator identity and expected dependency environment. Its invocation fixes the interpreter and bootstrap by absolute path with Python isolated mode. Subject code cannot shadow a different `tools` package at bootstrap. Expected environment is computed in the parent; each child independently reports resolved distribution names/versions, Python/executable/platform/architecture and relevant native thread settings. Package-version identity is not proof of wheel-byte identity; a future hosted controller needs reviewed lock/wheel/image provenance too.

The adapter reports actual complete collection, skips/errors, selected/deselected IDs and setup/call/teardown reports. It never assigns PASS to a merely collected test. Exact JSON-escaped node/reason properties are added to pytest's native JUnit. A controller-side normalization copy adds missing collection-skip identity/reason/type metadata without changing counts or outcomes. Native JUnit is retained unchanged. Missing/duplicate phases, missing calls, failed teardown, unauthorized deselection or unowned execution reject independently of JUnit totals.

The parent, outside pytest, uses the OS process result and a finite deadline. Printed success markers are ignored. A true pytest return record, interpreter finalization record and observed OS exit must agree; zero OS exit alone is insufficient. Windows uses an anonymous kill-on-close Job Object established before a release handshake permits subject imports. POSIX uses a new process session/group. Timeout or cancellation cleanup kills the owned process tree. No arbitrary unrelated process is targeted. Return-time active child/thread snapshots and explicit database teardown are retained.

## Artifact authentication demonstration

The parent hashes original adapter, native/V3 JUnit, request, process/return/finalization and execution artifacts after the child exits. It writes a separate schema-2 observation receipt. The verifier requires the receipt's SHA-256 **from a separately retained trusted controller channel**, alongside independently retained trust inputs and producer/evaluator file hashes.

It does not read `receipt-pin.json` as authority. That file is labeled a convenience copy only. Mutating worker evidence, recomputing its seal/JUnit checksum, or replacing both the receipt and its accompanying pin cannot match the independently retained anchor. The tests actually perform these attacks and require rejection. The observer's OS result also cannot be replaced by a worker's claimed green marker.

This is a precise local trust boundary, not a cryptographic signature service or a sandbox against arbitrary code running as the same OS user. A malicious subject with sufficient filesystem/process privileges could attack the parent or its trusted input store. Prototype temp directories provide independent fixture namespaces, not hostile-code security isolation. A future hosted design must protect trusted bootstrap/approval inputs, use separate disposable runners and least privilege, and obtain job/attempt/artifact digests independently from the Actions service. Worker-supplied claims and self-reported checksums are not sufficient for that hosted binding. No hosted authority, owner approval or authenticity is manufactured here.

## Sources and evidence modes

The tested source in each demonstration is its own tiny Git-backed pytest project, not the FINCO main tree. FINCO main/Phase 1/Phase 2 producer identities are recorded separately. The parent fingerprints the actual trusted tool files. Schema-2 receipts use recorded mode and `real-local-OS-observed`; historical Phase 1 replay remains simulated. Every proof, including a successful actual execution, contains `authoritative_acceptance:false`.

The local harness refuses the FINCO root and projects carrying FINCO's engine/mandatory workflow, requires an explicit synthetic marker, caps the expected universe at 200 nodes and limits each child to 120 seconds. Only three separate subprocesses are started after discovery, with whole-module ownership and isolated temp/database paths. The hosted controller and budget/transport binding are a separate exact-content activation proposal, not an undocumented override to these local safeguards.

## Measurements and limits

Evidence records observed worker startup, pytest import, adapter import, actual session-start-to-collection-finish duration, phase durations, controller V3 JUnit construction, aggregation and shutdown. Startup/shutdown are local process observations; these tiny tests do not predict FINCO performance. Adapter initialization and distribution enumeration are distinct from collection. Native JUnit generation remains inside pytest's session finish and is not separately profiled; the explicitly timed V3 normalization is reported separately.

Session fixtures, opaque parametrization, mutable module globals, actual SQLite ownership and teardown are exercised. Shared database contamination, unexpected ordering/protocol repetition, collection-only execution, non-daemon shutdown hangs and an owned grandchild timeout are adversarial cases. No native numerical workload is executed; installed numerical packages and native-thread environment are evidence of configuration only. Full FINCO fixture independence, numerical thread contention, hosted startup and real 34–45-minute scaling remain unproven.
