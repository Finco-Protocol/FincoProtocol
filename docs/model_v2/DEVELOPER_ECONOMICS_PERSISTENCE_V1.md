# Developer Economics — Persistence Bridge & Canonical Workbook Integration V1 (RC-2 / M4)

Flow: **Configure → Save → STALE → canonical Run → committed Developer evidence → CURRENT → scenario / history.**
No new developer financial formula exists in this change. Every figure is produced by the existing
`financial_engine.developer_economics` calculator inside the one canonical Run.

## Capability matrix

| Capability | State | Authority |
|---|---|---|
| Typed input `DevelopmentEconomicsInput` | EXISTING / FROZEN | `finco_core/inputs/development.py` |
| Developer ledger, XIRR/MOIC, project uses | EXISTING / FROZEN | `financial_engine/developer_economics/` |
| Strict versioned codec for the stored value | NEW (no math) | `app/workbook/developer_economics_config.py` |
| Atomic Save / Reset command | NEW (existing lock + CAS protocol) | `app/workbook/developer_economics_service.py` |
| Workbook field + scenario override key | NEW (additive) | `developer.economics.configuration` → `developer_economics_json` |
| Snapshot → `ProjectInputs.development_economics` | NEW (adapter tail) | `app/input_adapter.py` |
| Selected-scenario resolution at Run | NEW | `app/v2/router.py::v2_workbook_run` |
| Run-bound evidence | NEW (pass-through) | `app/model_v2/developer_evidence.py`, `app/api/project_runner.py` |
| Editor, committed view, history | NEW (display only) | `/v2/developer-decision` |

## Persistence and concurrency

* One versioned canonical JSON document under the snapshot key `developer_economics_json`. Base saves write the
  Working Copy snapshot; a non-Base scenario saves exactly one override key. Missing override = inherit; **Reset to
  inherited** removes only that key. An explicit disabled document in a scenario overrides an enabled Base.
* `BEGIN EXCLUSIVE`; owner + project + archived check; Protected Reference denial; active scenario must equal the
  rendered one; composite workbook identity must equal the rendered one (the identity already hashes the scalar
  snapshot and every scenario override, so a Save rotates it); the candidate is materialised as the exact Run inputs
  and validated by the calculator's own rules before commit; any failure rolls everything back.
* The route additionally requires an authenticated owner and the signed canonical CSRF token.
* Validation is strict and fail-closed: exact keys, finite numbers, canonical ISO dates, strictly increasing unique
  spend dates, reimbursement ≤ eligible spend, ABANDONED carries no receipts, spend on/before the effective Financial
  Close. Percent fees are stored as 0..1 fractions; the form converts percentage points exactly once.

## Run and history

* Disabled/absent is the neutral `None` — payloads and KPIs are unchanged and no `developer_economics` key is written.
* Enabled: the Run materialises the SELECTED scenario's effective input, the calculator owns every result, and the
  Run commit stores `developer_economics` (exact typed input, dated vector, reimbursement, fee, MOIC/XIRR with typed
  statuses, fee basis) bound to `snapshot_id`, `composite_hash` and `scenario_id`, inside the existing atomic
  `runtime_summary` / Run History commit. A failed Run or failed final CAS persists nothing.
* Reads re-validate shape, finiteness and binding; anything else is shown as UNAVAILABLE. A historical Run is read by
  its immutable `history_id` and is never reconstructed from the Working Copy.

## Known fail-closed limitation (existing engine rule, unchanged)

The multi-senior (F3) and Junior financing paths reject any non-`None` `development_economics`
(`F3_NON_CONSTRUCTION_USES_INTEGRATION_NOT_RELEASED`, `F35_DEVELOPER_USES_NOT_RELEASED`). Running such a project with
Developer Economics enabled stops at the Run with the engine's typed error; nothing is committed.

## Governance

* No change to `financial_engine/`, `finco_core/`, `domain/`, goldens or tolerances.
* Trust: the CSRF inventory gains `app/v2/developer_decision_router.py`; the Trust registry sentence and generated
  docs name the Developer Economics configuration Save; the Trust guard adds a post-merge RC-1 checkpoint successor
  with explicit exact-blob entries (no namespace waiver).
* Overlap notes for M2/M3: shared files touched are `app/v2/router.py` (Run bridge block + evidence binding),
  `app/input_adapter.py` (adapter tail), `app/workbook/registry.py` (new `developer` sheet),
  `app/persistence/_helpers.py` (one allowlisted key), `app/api/project_runner.py` (one conditional payload key).
