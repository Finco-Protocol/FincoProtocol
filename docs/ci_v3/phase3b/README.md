# CI V3 Phase 3B — Linux inventory, isolation, image and hosted-pilot readiness

> **Superseded for current evidence by Phase 3C** (`docs/ci_v3/phase3c/README.md`). The figures and evidence below describe Phase 3B at the time and are historical; where they conflict with Phase 3C (for example the 20 unresolved modules, the `node`/`ssh-keygen` skips and the golden-flow state), Phase 3C is current.

Depends on PR #340 (Phase 3A, head `e6ee8cc9`). Nothing here activates a workflow, publishes an image, runs a hosted
shadow, or alters the mandatory sequential Public Safety workflow. All evidence is under `evidence/` and was produced
locally in Docker on Linux (4 vCPU Firecracker VM, shared by up to four containers); local timings are NOT hosted
measurements and support no performance claim.

## What was added
| File | Purpose |
|---|---|
| `Dockerfile`, `build_image.sh` | Reproducible Python 3.12 image from a digest-pinned base; optional build-only CA secret (never in a layer); resolved Python/system lists baked into `/opt/ci-v3`; no registry push. |
| `ci_v3_shadow.yml` | Exact deployable bytes for `.github/workflows/ci_v3_shadow.yml` (Phase 3A topology, header only changed). Kept outside active workflows. Guarded by `tests/test_ci_v3_phase3b_workflow.py`. |
| `tools/ci_v3_prepare.py --image` | Collect-only inside the immutable image as a private non-root, no-network container. |
| `tools/ci_v3_solo_probe.py` | Runs every module alone in a fresh private copy (empirical order/shared-state evidence). |
| `tools/ci_v3_classify.py` | Turns collection + solo evidence into an UNREVIEWED isolation and nonpass proposal; anything not clean stays `blocked`. |
| `tools/ci_v3_container_validate.py` | Drives the real Phase 3A plan/worker/aggregate stages with real containers on a derived subset; only GitHub service metadata is mocked. |

## Results (source of evidence: branch commit before the final doc commit; regenerate on the final tested tree before any admission)
* **Linux collection (in image):** 17,143 nodes, 487 collected modules, 0 executed phases, container removed, normal exit. 68 whole modules are skipped at collection (`playwright not installed`, the same condition the existing Public Safety job has; their coverage is the separate mandatory browser job). They are listed in `evidence/collection-skips.json`, not dropped.
* **Isolation inventory (487 collected modules, each run alone, fresh private copy, no network):** 466 pass, 1 passes only uncontended (`test_ci_v3_real_adapter`, timing under 4-way load), 18 pass with runtime skips needing an exact owner-approved nonpass policy (75 records, all matched to exact node IDs in `allowed-nonpass-proposal.json`), 2 fail alone. **Unresolved modules blocking admission: 20.** No module is marked reviewed; owner review is the only approval.
* **Genuine order dependence found:** `tests/test_golden_flow_correction_b.py::test_active_scenario_override_stays_stale_on_reopen_and_first_run_succeeds` asserts exactly one `run_project` call, but app startup (`ensure_reference_canonical_last_runs`) seeds four reference runs into the persistent `app/data/finco_runs.db` unless an earlier module already did. It fails on a fresh copy (5 != 1) and passes on a second invocation. It needs an owner decision: explicit seeding predecessor with enforced worker order, or a test-side fix. No test was edited.
* **Second unresolved failure:** `tests/test_p0a_model_execution.py` (timeout/disconnect capacity-release timing) fails reproducibly in the image on this VM although the hosted control passes; unresolved until measured on a hosted runner.
* **Dependency finding:** `constraints.txt` pins only direct dependencies; transitive versions float (see `evidence/resolved-python.txt`). Control and shadow can resolve different transitive versions unless owners bind a lock. The control also does not set the single-thread native variables the shadow image fixes.
* **Bounded real-container validation (NOT complete FINCO coverage):** 9 modules, 397 nodes, three real containers, allocation 132/136/129 nodes, native JUnit and process evidence preserved, 397 unique nodes independently verified, `coverage_valid=true`, `authoritative_acceptance=false`, `provenance_authenticated=false` (mock service). Earlier larger-subset attempts failed closed as designed: an unapproved-skip worker exited 0 but was not accepted as normal; a failing test worker was rejected; artefacts of my own subset construction (missing files/history) were fixed in the validator, not by weakening any gate.
* **Phase 3A Linux tests in the image:** 210 passed, 1 skipped (the non-Linux refusal negative).

## Control datum observed (hosted, single samples, different trees — not an experiment)
Public Safety `safety-and-smoke / tests`: PR #340 head 14:50:26→16:20:10 UTC (89.7 min); main `6fb8fc1` 14:08:42→15:22:08 UTC (73.4 min). No shadow time has been measured on hosted runners.

## Not yet possible (blockers)
1. Owners must resolve the 20 unresolved modules above, approve the exact nonpass policy, and mark isolation reviewed (Financial/Security/CI).
2. Publish the image through an authorized path to get a registry digest and re-record it (`evidence/image.json` has none).
3. Protected environment `ci-v3-shadow-admission`, root pin, controller pin and the exact-content governance successor for the new workflow file.
4. Run-specific experiment authorization and budget (350 shadow runner-minutes; ~590 for the pair). One pair, no retry.
5. Comparable control settings (native threads, dependency lock).
