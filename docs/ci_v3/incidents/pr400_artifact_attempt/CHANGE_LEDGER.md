# PR #400 CI V3 artifact attempt-integrity repair: change ledger

Predecessor: PR #400 HEAD `2ed3653b62720bb490c048ab58cac6410d279fd2` (tree `b3800b6c…`). Judged against the WF-03 parent
`db504f6408cb456c617c9342a1ffa202ee455283`. The authoritative pins live in
`docs/react_migration/wf03_project_lifecycle/SOURCE_SUCCESSOR.json` (`source_blobs`, ledger rows tagged
`"successor": "ci-artifact-attempt"`, `authorization.ci_artifact_attempt_successor`). Earlier ledger rows are retained unchanged as
immutable predecessor records.

| Path | Before blob (2ed3653b) | After blob | Change |
|---|---|---|---|
| `.github/workflows/ci_v3_required_job.yml` | `7a320b59…49ef` | `e96fe1ee…f440` | Per-attempt artifact names. Plan `seal` step. Authoritative uploads `if: success()`, failure output under `ci-v3-diagnostic-*`. Plan outputs `plan_attempt`, `plan/runtime_artifact_id`, `…_digest`. Worker `if` requires `needs.plan.result == 'success'`. First worker step refuses another attempt's plan. Worker downloads by immutable artifact ID. Aggregate downloads `public-ci-v3-*-attempt-N` and requires `plan_attempt == run_attempt`. **Unchanged:** the job set, `needs`, every `timeout-minutes` (sum 310), matrix/fail-fast, permissions, no `continue-on-error`, single Docker build |
| `tools/ci_v3_production.py` | `9ca394a1…f6d6` | `25d06ce0…e013` | `seal_attempt`, `check_seal_binding`, `preflight` (before Docker). Loaded image-ID check. `authenticate_current` selects only current-attempt names, binds the run/head, requires producer success, checks digest and byte equality, re-verifies the seal, records artifact IDs. `seal` stage and `--runtime` option. **Unchanged:** `verify_data`, `production_plan`, `make_plan`, D-029/WS-2/WF-03 outcome rules, reference policy |
| `tools/ci_v3_source_reference.py` | `7563bdde…08a39` | `5b19bb86…9cee` | The accepted reference reads the reference run's *final attempt* scoped names and extracts them under logical folders. Legacy unsuffixed runs follow the original rule. Uniqueness, digest, head and producer checks unchanged |
| `tests/test_ci_v3_production.py` | `5ade8163…8fba` | `80e81828…30ea` | The original node ids and their 18 attack parameters are kept. The service fixture now uses current-attempt names. Additive tests: cases A–F, workflow contract, worker/aggregate attempt guards, reference final-attempt selection |
| `tests/test_rc3_integration_inventory.py` | `5116f668…f50b` | `e20effae…167a` | Gate 1 genuine failure (13 nodes on the untouched head). Node ids kept. Historical CI-200M judged on the text derived from RC-5. The worktree must be an exact member of the CI-340M chain. No negative removed |
| `tests/wf03_lifecycle_scope.py` | `2e770089…a5fe` | `db591dd3…de4f` | +4 exact owned paths: `tools/ci_v3_source_reference.py` and the three incident documents. No new `.github/` path; `CI_TIMEOUT_WORKFLOWS` unchanged |
| `docs/react_migration/wsv2_editing/SOURCE_SUCCESSOR.json` | `ede43ffb…9517` | `9df7183d…53a3` | `source_blobs` for `tools/ci_v3_production.py` and `tests/test_ci_v3_production.py` follow the exact WF-03 pins. History untouched |
| `docs/react_migration/wf03_project_lifecycle/SOURCE_SUCCESSOR.json` | manifest (not self-pinned) | (seal) | New pins, ledger rows and authorization record |
| `docs/ci_v3/incidents/pr400_artifact_attempt/*.md` | new | pinned in manifest | Documentation only |

Not touched: `.github/workflows/public_safety_and_smoke.yml`, `.github/workflows/ci_public_job.yml` (RC-5/CI-340M chain, F01
oracle), `tests/test_m3_two_driver_sensitivity.py`, `tests/test_rc5_ci_successor_governance.py`, every financial/engine/app path, and
every protected expected value. No test is skipped, deselected, `-k`-filtered or marked `continue-on-error`. No timeout or budget
was changed.
