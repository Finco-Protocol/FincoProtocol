# Exact-head evidence and final review (Correction D)

Blobs are git SHA-1; hosted evidence is read from the named runs/artifacts. This file records the **last fully observed hosted head**. Later commits on the branch are evidence/documentation commits (the exact new head and its run IDs are in the PR description and
supersede the "CI on the last observed head" section only for that head).

## Identity

| Item | Value |
|---|---|
| `main` | `128bf0c2b79af56985326543132cc806ff7f001c`, tree `459d67a89c8c204f03d364dbba2242c168dea5bf` (FIN-VAL F01 #389 merged) |
| Last fully observed hosted head | `9ac495c83a64b326d6074d2ea2150f112778a5f7`, tree `42a4e2e080772cffd3969ac7b9021235fea0f819`; merge base = `main`; 0 behind, 19 ahead |
| React bundle | `static/react/finco-react.js` `37852f40afdcb3c141005a5cd2694ea4e435ead8`, `.css` `4c119cdff91c2bcb2cb751ac9668acce7a66607c`; a clean `npm run build` reproduces both byte for byte; `REACT_ASSET_VERSION=rc-sec-mutation-v1-2e74b6f81a87` |
| Pinned-governance successor blobs | `react_new_project.py` `5abdb46a4704277a895d256a434f7a6f510206c1`, `react_goal_seek.py` `4cf820e8…`; layer defined in `tests/model_mutation_security_successor.py::RC_M_SUCCESSORS` (6 paths) and `tests/rcm_adapter_csrf_successor.py` |

## CI on the last observed head (`9ac495c8`)

| Workflow | Run | Result |
|---|---|---|
| PR Compile and Safety Gate | 40522710040 | success |
| Governance Full History | 40522709761 | success |
| Dependency Security Audit | 40522709611 | success |
| FIN-VAL F01 Financial Acceptance | 40522709602 | success |
| Protocol UI Browser Acceptance (mandatory `consolidation` role) | 40522709601 | success |
| Public Safety and Model Smoke | 40522709690 | **failure**: `source-safety`, `route`, `plan` success; workers 0, 2, 4 success; **workers 1 and 3 failure**; `aggregate`, `tests`, `mandatory-evidence` failure (consequence) |

### Five workers (artifacts `public-ci-v3-worker-N`, run 40522709690)

| Worker | Exit type | Calibration max (s) | pytest | Original nodes |
|---|---|---|---|---|
| 0 | normal, pytest exit 0 | 0.324 | ran, no leaks | 5190 |
| 1 | **calibration refusal, `os_exit_code` 124** | **0.802** | never started | 4665 |
| 2 | normal, pytest exit 0 | 0.320 | ran, no leaks | 3211 |
| 3 | **calibration refusal, `os_exit_code` 124** | **0.704** | never started | 3778 |
| 4 | normal, pytest exit 0 | 0.260 | ran, no leaks | 3690 |

Workers 1 and 3 refused on the 0.600 s cold-start readiness gate (maximum of three samples) before any test ran; they are not pytest failures, not timeouts, not leaks. Analysis, 60-worker hosted baseline, local `main`-vs-branch
measurements and the honest limitation: `PR388_CALIBRATION_EVIDENCE.md`. Root causes: `PR388_CORRECTION_D_ROOT_CAUSE.md`. The earlier worker-0 failure (SQLite migration order, `248d9112`) is **closed** by exact-head evidence: worker-0 passed on `9ac495c8`.

## Acceptance evidence (local unless stated)

* **SQLite migration / exactly-once create:** schema suites 35 passed; atomic + multi-process (three real uvicorn processes) + wizard + F01 + rate matrix + governance sequence 367 passed, 0 failed; negative controls proven (old index order fails six tests).
* **Browser (hosted, mandatory consolidation role, run 40522709601):** green, 165 nodes (106 original + 59 RC-M), no collection skip added (the plan job's authenticated reconciliation passed: collection-skip inventory identical to `main`, 66).
* **Financial / F01:** hosted F01 acceptance green; local rate matrix 22 tests — four verticals × 0.056 / 0.56 / 5.60 / 9.00 % reach the engine as 0.00056 / 0.0056 / 0.056 / 0.09; previews write no Run, history or Working Copy change; ambiguous historical copies stay fail-closed; no financial source, golden fixture, kernel or `human_percent_v1` code changed by RC-M.
* **Security:** both React write endpoints validate the signed resource-bound token before any writer; Goal Seek Apply token bound to the exact candidate; Sensitivity read-only and bounded; reference models protected; Two-Senior / Storage release-closed.
* **Local gates:** public safety scan `PUBLIC_REPOSITORY_SAFETY_SCAN_PASS`; `compileall` clean; bundle reproducible; protected-path audit against `main`: only the four atomic-create persistence/service files (two admitted through `ATOMIC_CREATE_SUCCESSORS`) and the D-029 reviewed-set record changed; nothing under `financial_engine/`, `finco_core/`, `app/input_adapter.py`, `app/runtime/`, `app/v2/router.py`, `main_web.py`, `.github/` or the golden fixtures.
* **Broad local regression:** 5,876 passed, 15 skipped, 4 failed — the same four fail on unmodified `main` (three CI V3 tests need a non-root host user; one navigation assertion). See `07`.

## Unresolved findings / limitations (none hidden)

1. Hosted cold-start readiness refusals (RC-2) block the `aggregate` and `tests` jobs on the last observed head; not attributable to this PR on the evidence, but the gate is not met until a wave in which all five workers meet it. A recurring refusal is a CI performance-contract question for the CI owner.
2. Legacy unkeyed `/projects/create` is not keyed; the keyed seeded create is still several SQLite writes (detectable and fenced, not one transaction); the demo budget is a read-then-create check; the Two-Senior facility editor is release-closed in React.
3. Legacy Goal Seek / Sensitivity routes without a resource-bound token (pre-existing, `08` item 6) — separate change.
4. The two audit archives were never available: **no claim of full Legacy parity**, completeness percentage or production authorization is made.
5. Everything stays behind `FINCO_MODEL_REACT_V1` (default OFF); nothing is deployed or activated. No self-approval, merge or deployment.

## Final verdict for the last fully observed head

**CORRECTION REQUIRED — SAME PR #388** (exact remaining cause: the hosted CI V3 cold-start calibration refusal on workers 1 and 3; every other mandatory check on `9ac495c8` is green). The verdict for the newest pushed head is stated in the PR description.
