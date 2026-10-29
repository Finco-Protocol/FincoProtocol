# WF-04 — Two contractual DSCR inputs: field lineage, Run binding and historical behaviour

Basis `main` `b76ac65c99e7fc9b486a557ae3c5ba9a711f50b3`. Authority: Financial Owner V3 decision (2026-10-29) and the Owner low-DSCR Run policy; the bounded
implementation grant of the unified WF-04 prompt §0A. **Source-derived facts (S)** are separated from **design choices (D)** and **unresolved (U)**.
Everything here is synthetic-input evidence; no workbook, customer or third-party material is used.

## 1. Is there an existing field for either input? (S)

| Question | Finding | Evidence |
|---|---|---|
| Is `min_dscr_covenant` a persisted, editable, contractual input? | **No.** It exists only as a field of the evidence dataclass `ProjectTerms` (`app/model_quality/evidence.py`). `terms_from_project_inputs()` never fills it; no registry field, no snapshot key, no writer, no editor, no Run record carries it. Only unit tests construct it by hand. | `git grep min_dscr_covenant` — consumers are `model_quality/{evaluators,registry,evidence}.py`, `v2/diagnostics_v2_projection.py`, `v2/insight_quality_projection.py`, `tools/numerical_validation/credit.py` and tests |
| Is there an already-owned persisted EoD floor? | **No.** `bankability_config.KEYS` carries `target_scalar` / `targets` (Senior **sizing** targets), lender case, rates, fees, reserve; nothing named or behaving as a default/EoD floor. `FinancingParams` has `target_dscr`, `lockup_dscr`, `min_llcr`, `target_min_dscr`, `flat_dscr_target` — all sizing or lock-up/LLCR controls. | `app/workbook/bankability_config.py`, `finco_core/inputs/_models.py` |
| Could the Senior sizing target, the lock-up threshold or `min_llcr` serve as either input? | **No** (V3: never repurposed). `target_dscr` sizes debt on the lender case; `lockup_dscr` restricts distributions; `min_llcr` is a loan-life ratio. | V3 §1; `financing/project.py` |
| Would adding the two values to `FinancingParams` be appropriate? | **No.** That is a protected core input type whose hash is part of engine identity. The two terms feed no calculation, so they are registered as workbook inputs only. | `finco_core/inputs/_models.py` is not touched |

Decision (D): create **exactly two** new registry inputs; reuse no existing field; add **no** third field (no default, no EoD ordering, no grace/cure).

## 2. Field table (the Owner's required lineage)

| | **Minimum DSCR (EoD threshold)** | **Contractual DSCR (covenant)** |
|---|---|---|
| UI label | `Minimum DSCR (EoD threshold)` | `Contractual DSCR (covenant)` |
| Canonical field id | `debt.contract.min_dscr_eod` | `debt.contract.contractual_dscr` |
| Snapshot key | `dscr_min_eod_x` | `dscr_contractual_x` |
| Type / unit / bounds | FLOAT, multiple `x`, finite, `0.01 ≤ v ≤ 10`; blank = `NOT_CONFIGURED` (never 0); display step 4 decimals, **saved text exactly as the writer coerces it** | same |
| Registry location | `app/workbook/registry.py` → debt sheet, new section `contract` ("Contractual DSCR terms"); `kind=INPUT`, `source_of_truth=INPUT_SET`, `binding=BOUND`, `engine_path="credit_terms.*"` (no engine consumption) | same |
| Schema / version | registry `WORKBOOK.version` **unchanged** (`2.3.0`, as for the previous registry additions); Run record schema `FINCO_DSCR_CONTRACT_TERMS_V1` | same |
| Writer | the existing authorised field writer `POST /v2/workbook/update` (`WorkbookUpdateService.validate_field_update` → `v2_atomic_draft_update`) and the existing batch writer `POST /v2/workbook/grid/save` (`v2_apply_batch_draft_update`). **No new route, writer, CSRF purpose or CAS.** | same |
| CSRF / CAS / ownership | unchanged: per-operation CSRF, content-hash CAS, workbook-version check, owner and protected-reference gates (tests: forged CSRF → 403, stale CAS → 409, other user sees nothing) | same |
| Save ≠ Run | a Save writes the draft and leaves the Last Run `STALE`; it commits no history entry (test) | same |
| Save All (PR #397) | #397's `save_all` routes scalar cells through the existing batch body (`v2_apply_batch_draft_update_in_tx`), which validates any registry `INPUT` field generically. The two fields therefore **need no integration code**; a combined Save All is atomic for them exactly as for other cells. Proven today on `main` against `/v2/workbook/grid/save` (atomic, whole-batch rollback on one invalid cell). End-to-end combined-UI acceptance is **NOT RUN** until #397 merges. | same |
| Scenario authority | `ScenarioPolicy.NOT_ALLOWED`: project-level contractual terms, not scenario overrides | same |
| CURRENT / STALE | part of the input identity (`ProjectInputSet` content hash and composite hash): editing either value makes the Last Run `STALE` | same |
| Run materialisation | inside the exclusive Run-commit transaction (`workspace_repository.v2_atomic_run_commit`), the draft that is being committed is captured into **that Run's immutable `last_runtime_identity["dscr_contract_terms"]`** (same atomic transaction as the Last Run and the history row; fail-closed). Corrupt text is recorded as `INVALID`, never raised, so a credit term can never fail a valid Run. | same |
| Historical behaviour | each history entry is judged only by **its own** record. A Run committed before this contract has no record → `NOT_RECORDED` (UNAVAILABLE), never today's Working Copy, no backfill, no migration. Old Runs and signatures stay valid. | same |
| Period basis | the sealed Senior-debt evidence rows of the Run (`integrity_evidence.senior_debt.periods[].reported_dscr`, base-case CFADS ÷ scheduled Senior debt service, full precision, digest-verified before use); test periods = every period of that Run with scheduled service > 1e-6 kEUR, on the Run's own calendar | same |
| Predicate | `actual < threshold` on raw IEEE-754 doubles, **no tolerance**, no display rounding. Equality does not trigger. | covenant breach `actual < threshold`; compliant otherwise |
| Provenance | Run history id / snapshot id / composite hash + the recorded term text; `test_basis` disclosed with every verdict | same |
| Governance owner | exact-source cohort `tests/wf04_scope.py` (this PR) | same |

## 3. Outputs, not inputs (S)

* **Achieved Minimum DSCR** = measured minimum of the applicable per-period base-case DSCR of that Run (`runtime_summary.min_dscr` is the same value; test-pinned). Read-only everywhere; never an editable field.
* **Bank-case DSCR** (lender case) is shown separately and never decides either verdict.
* Senior **sizing target**, sculpting targets and **lock-up** keep their existing authority; the lock-up threshold value is not persisted with a Run (only the per-period flag), so it is shown as an observation.

## 4. What was deliberately not done (S / U)

* **U — test frequency convention.** The Run's own calendar (every period with scheduled service) is a FINCO model convention, disclosed in `test_basis.authority = FINCO_MODEL_CONVENTION_NOT_A_LEGAL_TEST`. Whether a facility agreement tests another basis (for example a rolling annual ratio) is the **one unresolved methodology question**; no third input field exists to configure it and nothing is guessed.
* No cure, grace, waiver, acceleration, payment-default or profitability statement is produced from DSCR. Reserve **draw** and **unpaid scheduled service** are `UNAVAILABLE` (not persisted by a Run); the payload (`reserves.unavailable_conclusions`) and the screen list the exact missing evidence.
* `QM-COV-001`/`QM-COV-004` keep their legacy `ProjectTerms` semantics (so no ordering between the two new values is imposed); when a Run records a Contractual DSCR the contradicting "not supplied" `QM-COV-001` row is superseded by the Run-bound `CD-COV-DSCR` finding.
