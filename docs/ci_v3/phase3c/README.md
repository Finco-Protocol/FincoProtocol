# CI V3 Phase 3C: resolve remaining isolation blockers

> **Evidence status after merging PR #332 (V9-P2a OD-R, main `2112d7c0`).** Sections 1 to 11 below describe the study executed at
> commit `cd46e45d` / tree `dbeacff5` (manifest digest `fdc9b6c717df07fb`). That evidence is now **historical**: it remains independently verifiable
> against its exact executed source and its files are unchanged, but it does **not** describe the synchronized tree, which also contains financial, application and governance changes.
> What is newly verified for the synchronized tree, and what is only historical, is in section 12.

Dormant infrastructure only. Nothing here activates a workflow, publishes an image, starts a hosted shadow run, approves a module,
a nonpass record, an environment difference or a daemon thread, or changes the mandatory sequential Public Safety workflow.
Starting point: main `c3a2f5b6` (Phase 3A and 3B merged). All execution evidence is in `evidence/`; its manifest is
`evidence/manifest.json` (digest `fdc9b6c717df07fb`) and is checked by `python -m tools.ci_v3_evidence verify`.

## 1. Executed source and every permitted carry-forward difference

| Item | Value |
|---|---|
| Executed source commit / tree | `cd46e45d5885173e8a71df9ebed5767688705001` / `dbeacff54004680ddb8e2829aa69bc84b50c9129` |
| Image (never pushed) | `sha256:0e447614cf691313002c6203ffb74ba65526e5defe86097cb978d8891862251a`, Python 3.12.15, base `python@sha256:6a0e06f5...` |
| Full 495-module run | tree `dfc5b547d83ea39c2c142cc4354a7a7bea739a23` (main + container passwd fix), three concurrent containers at 1.33 CPU, 4028 s wall |
| Re-executed on the executed tree | all 19 `tests/test_ci_v3_*` modules, 15-attempt stability set, CPU sweeps, calibration, golden-flow reproduction, the 20-module container validation and 5 negative controls |

Evidence executed on `dfc5b547` is accepted for a module on the executed tree only if (a) that module's blob SHA-256 is unchanged
(an attempt with a missing, malformed, stale or mismatched `module_sha256` never counts) and (b) every path that differs between the two trees is a CI V3 internal
addition, a listed CI V3 tool/test modification or documentation (`tools/ci_v3_evidence.py: carry_forward_changes`). Because CI V3 tools changed,
every `tests/test_ci_v3_*` module must additionally have an attempt on the executed tree, and for those modules older-tree attempts do not count.
The 15 permitted differences between `dfc5b547` and the executed tree are:

`tests/test_ci_v3_classify.py, tests/test_ci_v3_environment.py, tests/test_ci_v3_evidence.py, tests/test_ci_v3_nonpass.py, tests/test_ci_v3_proposal.py, tests/test_ci_v3_thread_policy.py, tools/ci_v3_classify.py, tools/ci_v3_container_validate.py, tools/ci_v3_environment.py, tools/ci_v3_evidence.py, tools/ci_v3_hosted_controller.py, tools/ci_v3_isolation.py, tools/ci_v3_nonpass.py, tools/ci_v3_proposal.py, tools/ci_v3_real_child.py`

The published PR head differs from the executed commit only under `docs/ci_v3/phase3c/` and `docs/ci_v3/phase3b/README.md`
(the verifier rejects any other difference). Pre-3C evidence in `docs/ci_v3/phase3b/evidence/` is historical and is not reused as current.

## 2. Linux isolation result (current main behaviour)

Collection in the image: 17,259 nodes in 497 modules, 68 whole modules skipped at collection
(playwright absent, identical module set to the sequential control). Classification (`evidence/classification/`):

- nonpass-approval-required: 14
- stable-pass: 481
- standalone-failure: 1
- target-concurrency-stability-validated: 1

Unresolved modules that still block admission: **15** (14 need the exact nonpass policy approved, `tests/test_p0a_model_execution.py` is hardware dependent).
No module is marked reviewed.

### Previous unresolved set reassessed (21 rows: the 20 from Phase 3B plus the load-sensitive module)

| Module | Phase 3B | Now | |
|---|---|---|---|
| `test_api_v1_radar.py` | nonpass-approval-required | nonpass-approval-required | open |
| `test_ci_v3_hosted_isolation.py` | nonpass-approval-required | nonpass-approval-required | open |
| `test_ci_v3_real_adapter.py` | load-sensitive-pass | target-concurrency-stability-validated | **resolved** |
| `test_crypto_p0_product_reality_reset.py` | nonpass-approval-required | stable-pass | **resolved** |
| `test_f08_opex_mobile_ux.py` | nonpass-approval-required | nonpass-approval-required | open |
| `test_golden_flow_correction_b.py` | standalone-failure | stable-pass | **resolved** |
| `test_model_credit_decision_v4_render.py` | nonpass-approval-required | nonpass-approval-required | open |
| `test_model_rc6_opex_profiles_ui.py` | nonpass-approval-required | nonpass-approval-required | open |
| `test_model_trust_pack_ux.py` | nonpass-approval-required | nonpass-approval-required | open |
| `test_model_v2_governance.py` | nonpass-approval-required | nonpass-approval-required | open |
| `test_multi_source_evidence_v2_correction_a.py` | nonpass-approval-required | stable-pass | **resolved** |
| `test_p0a_model_execution.py` | standalone-failure | standalone-failure | open |
| `test_p5_browser_acceptance.py` | nonpass-approval-required | nonpass-approval-required | open |
| `test_quarterly_acceptance_statements.py` | nonpass-approval-required | nonpass-approval-required | open |
| `test_rc7_institutional_reporting_v2.py` | nonpass-approval-required | nonpass-approval-required | open |
| `test_rc7_revenue_ppa_v3_economics.py` | nonpass-approval-required | nonpass-approval-required | open |
| `test_rc7b_gate_r_authorization.py` | nonpass-approval-required | stable-pass | **resolved** |
| `test_rc7c_frequency_reconciliation.py` | nonpass-approval-required | nonpass-approval-required | open |
| `test_trust_readiness_registry.py` | nonpass-approval-required | nonpass-approval-required | open |
| `test_u2_2_returns_surface.py` | nonpass-approval-required | nonpass-approval-required | open |
| `test_ux_c_strict_numbers.py` | nonpass-approval-required | stable-pass | **resolved** |

- `crypto_p0_product_reality_reset`, `multi_source_evidence_v2_correction_a`, `ux_c_strict_numbers` (31 skips): the image lacked `node`, which the hosted runner has. Fixed in the image; they now run and pass.
- `rc7b_gate_r_authorization`: `ssh-keygen` was added, then the test failed because the container user had no passwd entry (`No user exists for uid 1001`). Fixed by a read-only passwd mount; 150/150 pass.
- `golden_flow_correction_b`: see section 4.
- `ci_v3_real_adapter`: see section 5.

## 3. Nonpass proposal against the authoritative sequential control

Control: Public Safety run 39662990636 (head `968b89bb`, tree `c7fc4282` = main), `results.xml` sha256 `0127f47e5f3c2566`, 17,279 cases, 0 failures, 111 skipped = 68 collection + 43 runtime.
`evidence/nonpass-policy-proposal.json` (digest `6bbfd8a53fce7782`, `approved: false`):

- 43 exact node IDs with status and full reason, **identical to the control**; 0 changed, 0 environment-driven coverage losses, 0 unknown to the control, 0 control records not reproduced.
- Collection skips: same 68 modules; the control JUnit records only "collection skipped", so reasons come from the shadow adapter.
- Extra nodes versus the control (48) are the tests added after the control's tree (CI V3 tools and guards).
- Modules affected: `test_api_v1_radar.py`, `test_ci_v3_hosted_isolation.py`, `test_f08_opex_mobile_ux.py`, `test_model_credit_decision_v4_render.py`, `test_model_rc6_opex_profiles_ui.py`, `test_model_trust_pack_ux.py`, `test_model_v2_governance.py`, `test_p5_browser_acceptance.py`, `test_quarterly_acceptance_statements.py`, `test_rc7_institutional_reporting_v2.py`, `test_rc7_revenue_ppa_v3_economics.py`, `test_rc7c_frequency_reconciliation.py`, `test_trust_readiness_registry.py`, `test_u2_2_returns_surface.py`.
- A failure can never become a skip: only skip/xfail elements of completed runs are read, and any change of status, reason or identity is rejected.

## 4. Golden-flow test (existing test modified, disclosed)

`tests/test_golden_flow_correction_b.py` was modified: it now requests an isolated fixture `reference_runs_seeded` that points persistence at a private database and seeds the reference runs before the Run counter exists.
Cause: app startup seeds four reference runs into the shared database (`ensure_reference_canonical_last_runs`) unless an earlier module already did; on a fresh copy the test counted 5 Runs instead of 1.
`tests/test_golden_flow_correction_b_guard.py` pins the AST of the rest of the module (Python-version independent digest) so every assertion, golden expectation and the `calls == 1` counter are provably unchanged.
Reproduction (`evidence/validation/golden-flow-repro.json`, procedure `docs/ci_v3/phase3b/evidence/golden-flow-repro/run.sh`): original fails 3/3 on fresh copies (`5 == 1`), also after eight other application-starting modules;
corrected passes 3/3 fresh, once repeated, and in a 266-test ring in both orders, and leaves **no** file in the shared database directory. The Public Safety control passed this test at the earlier PR head.

## 5. Load-sensitive module (`test_ci_v3_real_adapter.py`)

Not shared state, so no co-location or serialization is needed; it is a CPU-budget constraint. At 1.0 CPU it failed in 2 of 8 attempts across four sweeps (one failing sweep is preserved as historical evidence) and once in the original 4-way run; at >= 1.33 CPU it passed in every attempt (6 consecutive at three-way concurrency, 2/2 at 2 CPU).
Classified `target-concurrency-stability-validated` with the failure and the constraint recorded; `reviewed` stays false. A hosted worker has its own runner, so the constraint is conservative there.

## 6. `test_p0a_model_execution.py` (still blocking)

Fails 5/5 at the target concurrency and 8/8 over all attempts on the validation VM, passes on the hosted control. Cause established by experiment (not by raising timeouts):
the first task of the process pool spends the VM's cold start (worker spawn plus imports) of 1.012 s (ceiling 0.6 s derived from the test's fixed sleeps), while the test assumes it is below about 0.7 s.
With the single change that the pool is warmed outside the test's timeouts and every assertion unchanged, all 37 tests pass 3/3, including both capacity-release assertions. It is not a model-execution regression;
it is hardware dependent (median 2.4x slower than the hosted runner over the 140 modules compared, measured under four-way load). `tools/ci_v3_calibrate.py` measures the ceiling; it must be run in the approved image on the target runner class before admission.

## 7. A new blocker found: application daemon threads fail the Phase 3A leak gate

`demo-cleanup` (`main_web.py`) and `finco-r-live-snapshot-warmer` (`app/radar_rwa/r_live_warming.py`) are daemon threads started by application startup and still alive after `TestClient` exits.
The Phase 3A bootstrap counts any live non-main thread as a leak, so in the 20-module validation the worker with application tests passed all 715 tests but was rejected as abnormal.
Without a change every worker that boots the application would be rejected, so a full three-worker run could not be accepted.
Mechanism added (default closed, nothing approved): an optional `isolation.allowed_daemon_threads` object in the owner-approved isolation policy; each entry is an exact thread name with a `reason` and an `approval_reference`.
Only a **daemon** thread with an exact approved name is tolerated, the list is read from the approved bundle (never from the worker), and every observed thread is recorded. With the two names and a fixture approval the 20-module validation passes; without it the gate rejects
(`evidence/validation/negative-daemon-thread-leak.json`). Whether to approve these names is an owner decision (item below).

## 8. Environment and image reproducibility (`evidence/environment-equivalence.json`, `evidence/image/`)

| Item | Status | Control | Shadow image |
|---|---|---|---|
| python-version | equal | 3.12.15 | 3.12.15 |
| python-packages-direct-and-transitive | equal | 76 installed | 76 frozen |
| native-numerical-libraries | equal | numpy/scipy/pandas wheels (bundled BLAS) by version above | same wheels by version above |
| native-thread-variables | different | unset (workflow defines none) | OMP/MKL/OPENBLAS/NUMEXPR_NUM_THREADS=1 |
| operating-system | different | ubuntu-24.04 20261018.339.1 | Debian GNU/Linux 12 (bookworm) |
| libc | unproven | Ubuntu 24.04 glibc (not recorded in artifacts) | 2.36-9+deb12u14 |
| optional-tools-node-ssh | unproven | preinstalled on runner image (versions not recorded in artif | v18.20.4; OpenSSH_9.2p1 Debian-2+deb12u10, OpenSSL 3.0.22 25 |
| pytest-plugin-config | different | autoload on; -p tools.ci_pytest_inventory -p tools.ci_pytest | PYTEST_DISABLE_PLUGIN_AUTOLOAD=1; -p pytest_asyncio.plugin v |
| cpu-and-start-up-speed | unproven | hosted 4 vCPU runner (unmeasured here) | see calibration evidence |

All 76 resolved Python packages (direct and transitive) are identical to the control's install log; `constraints.txt` still pins only direct requirements, so transitive drift remains possible between builds.
The base image is digest pinned, the image has no network at run time, runs read-only as a numeric non-root user and holds no credentials (the build-only CA secret is never in a layer). A rebuild yields the same resolved lists but not the same bytes. No registry digest exists because nothing is published.
The mandatory workflow was not changed to force equivalence; the admission condition stays closed.

## 9. Real-container validation (not complete FINCO coverage, not a speedup claim)

20 modules, 2,698 nodes across financial engine, model run and integrity, governance, Radar, application/API and the highest-runtime modules,
three real containers via the Phase 3A plan/worker/aggregate stages (only GitHub service metadata mocked; `provenance_authenticated=false`): `coverage_valid=True`, 2,698 unique nodes independently verified, native JUnit and process evidence preserved.

| | worker-0 | worker-1 | worker-2 |
|---|---|---|---|
| nodes | 1268 | 715 | 715 |
| container wall (s) | 20.3 | 66.7 | 408.9 |
| startup + shutdown overhead (s) | 2.7 | 3.4 | 3.3 |
| peak memory (MiB) | 253.6 | 216.7 | 100.0 |

Local wall: collection 21.53 s, plan 17.14 s, workers 426.5 s (slowest worker), verification 0.69 s, total 465.86 s.
The imbalance comes from the node-count proxy weights on a small subset (one 291 s module); these are local-VM numbers, about 2.4x slower than hosted, and prove nothing about hosted speed.

Negative controls in real containers (all rejected, containers removed): failing test stays a failure; unapproved skip; unauthorized node (collected but not approved); required node missing; leaked daemon thread without approval; duplicated or removed JUnit testcase after the host receipt (rejected by the independently pinned artifact hash).

### Projection (unverified until a hosted run)

Hosted control timings (single sample, run 39662990636): sum of module test time 5,717 s; the current node-count planner assigns 1,910 / 1,903 / 1,904 s to the three workers (slowest 31.8 min, ideal 31.8 min).
Add collection/plan, image pull, container startup, artifact upload and verification, which are unmeasured on hosted runners. The control's own wall time has varied between 65 and 97 minutes across runs, so any comparison needs the single authorized pair and may be inconclusive.

## 10. Remaining blockers and owner decisions

Admission blockers: 15 unresolved modules, environment not proven equivalent, image not published, hosted-runner calibration absent or failing, daemon thread policy not approved, no owner has reviewed isolation, nonpass policy not approved.

1. **Financial+CI** (blocking): approve or reject the exact 43 runtime skip/xfail records (digest 6bbfd8a53fce7782); every record is identical to the sequential control
2. **CI** (blocking): resolve or explicitly accept each unresolved module: tests/test_api_v1_radar.py, tests/test_ci_v3_hosted_isolation.py, tests/test_f08_opex_mobile_ux.py, tests/test_model_credit_decision_v4_render.py, tests/test_model_rc6_opex_profiles_ui.py, tests/test_model_trust_pack_ux.py, tests/test_model_v2_governance.py, tests/test_p0a_model_execution.py, tests/test_p5_browser_acceptance.py, tests/test_quarterly_acceptance_statements.py, tests/test_rc7_institutional_reporting_v2.py, tests/test_rc7_revenue_ppa_v3_economics.py, tests/test_rc7c_frequency_reconciliation.py, tests/test_trust_readiness_registry.py, tests/test_u2_2_returns_surface.py
3. **Security+CI** (blocking): accept or remove each environment difference: native-thread-variables, operating-system, libc, optional-tools-node-ssh, pytest-plugin-config, cpu-and-start-up-speed
4. **CI** (blocking): run tools/ci_v3_calibrate.py inside the approved image on the target hosted runner class; tests/test_p0a_model_execution.py needs worker cold start <= 0.6 s
5. **Security+CI** (blocking): authorize publication of the execution image and record its registry digest
6. **Security+CI** (blocking): decide whether to approve these exact daemon threads left alive by application startup (demo-cleanup, finco-r-live-snapshot-warmer); without an approved isolation.allowed_daemon_threads entry (reason + approval_reference) every worker that boots the application is rejected by the leak gate
7. **Financial**: acknowledge the disclosed modification of tests/test_golden_flow_correction_b.py (isolated precondition fixture; assertions pinned by tests/test_golden_flow_correction_b_guard.py)

## 11. Is a single bounded three-worker hosted experiment technically ready?

Technically close but **not ready for authorization**: (1) the daemon-thread policy and the exact nonpass policy must be approved and written into the owner bundle (inventory, policy, isolation, weights, environment), (2) the image must be published and its digest pinned,
(3) calibration of `p0a` on the target runner class must pass, (4) the 15 unresolved modules must be resolved or explicitly accepted, (5) the protected environment, root pin, workflow content approval and the experiment budget (350 shadow / about 590 pair runner-minutes) are still absent.
The infrastructure side (collection, planning, containers, evidence verification, negative controls, proposal assembly) is exercised end to end locally.

## 12. Synchronization with main (PR #332) and evidence integrity

PR #332 changed 7 production source files (`financial_engine/financing/generic_product_policy.py`, `financial_engine/financing/project.py`, `financial_engine/orchestrator.py`,
`financial_engine/shareholder_waterfall/model.py`, `financial_engine/shl/production.py`, new `financial_engine/shl/maturity_authority.py`, `app/services/production_financial_authority.py`),
15 test modules (8 changed, 7 new) and governance documents. It was merged into this branch with a normal merge (parents `fccbad4c` and `2112d7c0`); the PR still changes only `docs/ci_v3/**`, `tools/ci_v3_*` and `tests/test_ci_v3_*`,
the seven protected production blobs are byte-identical to main and `.github/` is unchanged.

### Historical evidence is preserved, not rewritten or widened
- `evidence/` (executed source `cd46e45d5885173e8a71df9ebed5767688705001`, tree `dbeacff54004680ddb8e2829aa69bc84b50c9129`) is untouched. `python -m tools.ci_v3_evidence verify --repo . --evidence docs/ci_v3/phase3c/evidence --historical`
  verifies it against that exact source (it must be an ancestor of HEAD; tool hashes are read from that commit, not from HEAD) and reports `applies_to_published_head: false`.
  The default (strict) mode refuses it, because the published tree differs from the executed one outside permitted evidence paths.
- Differences between the historical source and the synchronized tree, by class: application-source: 1, ci-v3-internal: 6, financial-source: 6, general-tests: 15, other-docs: 10, other-tools: 1. None of the product classes is permitted to inherit evidence: the allow-lists
  (`ALLOWED_FOLLOWUP`, carry-forward additions/modifications) were **not** widened and a guard test asserts they contain no financial, application, workflow or general-test path.
- A current manifest records each historical manifest it refers to with `applies_to_this_source` and the unreviewed change classes; the admission proposal carries the same `evidence_scope`.

### Newly verified for the synchronized tree (`evidence-sync-2112d7c0/`, executed source `f0a187930dfe0575ac1271bb46aef615849daf75`, tree `f32034a1063ebead03c4cbf316fb1673cda975a4`)
- Collection in the image: 17,438 nodes in 502 modules (historical 497 module records; 179 nodes added, 0 removed; 5 new and 10 changed test modules, listed in `inventory-diff-vs-historical.json`), 68 collection skips.
- Executed freshly on this source at three-way concurrency: **147 modules / 5,067 nodes** = every new or changed module, every module whose text references one of the 7 changed production modules (105, a heuristic and not a proof of dependency closure), all CI V3 self-tests, the earlier blockers and the tree-scanning guards; plus 5 repeats of `real_adapter`, `p0a` and a heavy module.
  Everything passed except `test_p0a_model_execution.py` (hardware dependent, unchanged finding). The 5 new V9-P2a modules and the 7 changed modules pass.
- Nonpass: 43 records observed on the fresh runs, all identical to the sequential control for this exact tree (run 39678405601, tree `c3355eb8`, 17,433 cases, 0 failures, 111 skipped = 68 collection + 43 runtime). 0 changed, 0 coverage losses. Still a proposal.
- Container validation on the synchronized source: 24 modules / 2,872 nodes (including three new V9-P2a modules), three workers 1268/803/801 nodes, `coverage_valid=true`, 2,872 nodes verified, JUnit tamper rejected. Not complete coverage; the subset is derived from published commit `f0a18793`.
- Container-level negative controls (failing test, unapproved skip, unauthorized node, missing node, unapproved daemon thread) were run on the historical source; the code they exercise is unchanged since (only `ci_v3_evidence`, `ci_v3_classify` and `ci_v3_proposal` changed), so they remain **historically supported, not re-run**.
  The evidence-integrity negative controls for this correction are unit tests (`tests/test_ci_v3_evidence.py`, `test_ci_v3_classify.py`, `test_ci_v3_proposal.py`).

### Classification for the synchronized tree
- historical-only-needs-current-execution: 354
- nonpass-approval-required: 14
- stable-pass: 132
- standalone-failure: 1
- target-concurrency-stability-validated: 1

`historical-only-needs-current-execution` means the module has evidence only on an earlier source. An unchanged test file hash is explicitly **not** treated as equivalence while production source changed, so those modules stay blocked until they are executed on the current source.
The earlier full 495-module study was not repeated (about 67 minutes locally); full-source equivalence for the synchronized tree is a future admission prerequisite, not a claim made here.

### Admission remains closed (`admission_ready: false`)
- 369 unresolved modules
- environment not proven equivalent
- image not published
- hosted-runner calibration absent or failing
- 354 modules have only earlier-source (historical) evidence
- earlier execution evidence does not apply to the current source
- daemon thread policy not approved
- no owner has reviewed isolation
- nonpass policy not approved

Unchanged separate prerequisites: the 15 isolation blockers from the historical study (14 modules need the exact nonpass policy approved, `p0a` needs hosted calibration), the exact nonpass approval, the daemon-thread owner decision, the environment differences (the hosted runner image also differs between controls: `20261018.339.1` earlier, `20261012.601` for the #332 control), image publication and hosted calibration.
CI V3 is inactive: no workflow is added or changed and no hosted shadow run, image publication or merge happened.

## Reproduce

```
python -m tools.ci_v3_prepare --project . --output OUT/prep --image finco-ci-v3@sha256:<image id>
python -m tools.ci_v3_probe_run ...            # full target-concurrency run; see tools/ci_v3_probe_run.py --help
python -m tools.ci_v3_classify --prepared OUT/prep --attempt RUN... --image-id <id> --tree <baseline tree> <executed tree> --output OUT/cls
python -m tools.ci_v3_nonpass --observed OUT/cls/allowed-nonpass-proposal.json --control-xml results.xml --inventory OUT/prep/inventory.json --collection OUT/prep/collection.json --control-ref <run> --output OUT/nonpass.json
python -m tools.ci_v3_environment ...; python -m tools.ci_v3_proposal ...; python -m tools.ci_v3_evidence build|verify ...
```
