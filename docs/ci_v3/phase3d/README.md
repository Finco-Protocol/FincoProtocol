# Phase 3D-A — technical readiness, admission closed

This change implements technical corrections after merged Phase 3C (#342). It does not deploy a workflow, publish an image, activate a root, approve isolation/nonpass/daemon policy or authorize a hosted experiment. Mandatory sequential workflow files and financial/Radar application code are unchanged.

## Implemented boundaries

- `ci_v3_pytest_config` supplies explicit pytest-asyncio and AnyIO plugins to discovery, standalone probes and workers. Backend parametrization belongs to the installed AnyIO plugin; original parameter IDs are never rewritten. The adapter verifies actual plugin registration. Missing plugins fail before execution.
- The planner schedules indivisible reviewed colocation groups before assigning whole modules. Source/blob/fixture review remains enforced by `validate_isolation`; no real group is approved here. Three-worker hosted planning still rejects empty workers and overlaps.
- `ci_v3_runtime_weights` accepts sealed duration measurements only when source, inventory and environment match. Every other module receives an explicitly identified deterministic node-count estimate. Scheduling weights never count as isolation evidence.
- The already opt-in `ci_pytest_inventory` observer retains every setup/call/teardown report and semantic collection skip reason. Its existing selection, outcome fields and commands are preserved. No workflow topology, assertion, tolerance or test behavior is changed.
- `ci_v3_phase_compare` compares exact original IDs, phase presence/outcomes/xfail reasons, collection skips, native JUnit, and externally supplied process cleanup evidence. It requires independent byte pins, preserves a lack of service authentication and never grants admission. Progress-duration logs cannot supply missing phases. The proposal lists absent/unproven comparison as a blocker.
- Standalone probes now use tracked Git archives and credential-free private history rather than copying ignored host databases into fresh runs. Bootstrap script and shared plugin bytes are bound in attempt metadata.
- Explicit `--local-image-id sha256:...` review is local-only, verifies the Docker config identity and uses `--pull=never`. No registry digest is invented. Hosted roots continue to require an immutable registry reference; local collection uses run ID 0 and is never hosted authentication.

## Local reproduction

Use the existing isolated checkout; do not create a Git worktree. Freeze and commit implementation before recording source-bound evidence. Install repository dependencies with their constraints. Retain Python, complete resolved distributions, native threads and runtime tool manifests; local compatibility is not environment equivalence approval.

```
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 NUMEXPR_NUM_THREADS=1 \
python -m pytest -q -p pytest_asyncio.plugin -p anyio.pytest_plugin tests/test_ci_v3_*.py tests/test_ci_acceptance.py

python -m tools.ci_v3_prepare --project . --output /tmp/NEW-PREP --local-image-id sha256:REVIEWED_LOCAL_CONFIG_ID
python -m tools.ci_v3_runtime_weights --inventory /tmp/NEW-PREP/inventory.json \
  --environment-digest EXACT_ENVIRONMENT_DIGEST --measurements EXACT_SEALED_MEASUREMENTS --output /tmp/NEW-WEIGHTS.json
```

The no-network container's own loopback and thread wakeups must remain functional. A host execution sandbox that blocks local socket operations is not a comparable pytest runtime. Do not adjust timing assertions to accommodate it.

For standalone module evidence use `ci_v3_probe_run --help`, the final source HEAD/tree, the exact bootstrap hash, an external new output directory and an explicit module list. Inspect every result/JUnit, not just the lane-helper exit code. A measured target probe is not approval and failed P0A remains failed.

For comparison use `ci_v3_phase_compare --inputs INPUTS.json --output NEW-PROOF.json`. INPUTS is an independently retained list for control then three workers, each containing report/junit/process `{path, sha256}` records. Control comes from the original inventory observer, workers from original adapter reports. Process inputs must establish exact source, normal completion and verified cleanup; old control artifacts lacking phases or cleanup remain blocked. Service run/job/artifact authentication and environment approval remain separate prerequisites.

The smallest additional recording method, if an ordinary exact-head control lacks sufficient cleanup evidence, is a separately authorized full sequential advisory container on the same source/image with `worker=control`, all modules owned, original adapter/native JUnit and the original host receipt. The comparator accepts that report/receipt directly. No additional mandatory run, workflow deployment or hosted execution is authorized here.

## Separate lifecycle workstream

See `LIFECYCLE_PROPOSAL.md`. The three characterization tests execute owned/fake resources and document current gaps; they do not certify shutdown safety or approve thread names. No product lifecycle correction is included in this infrastructure PR.

## Remaining independent decisions

The exact 43 historical nonpass records, any changed final-source records, every module/shared fixture/colocation decision, both daemon survivor decisions, environment differences, target-runner P0A calibration, image publication, workflow/governance deployment, protected admission environment/root and run-specific hosted pair/budget all remain unapproved. `admission_ready=false` remains mandatory.

The performance objective is >=2x comparable end-to-end candidate-path speedup. Offline schedules and local timings are predictions only. Mandatory-CI acceleration requires Phase 4; one pair is one observation, not repeatability.
