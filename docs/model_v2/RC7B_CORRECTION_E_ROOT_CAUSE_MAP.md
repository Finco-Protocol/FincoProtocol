# RC-7B Correction E - root-cause map of the 75 remaining governance failures

Disposition: **QUARTERLY RC-7B BLOCKED - FINANCIAL OWNER / GOVERNANCE AUTHORITY REQUIRED.** No pin, helper, exemption, guard or financial
blob was changed by this document. Source of truth: `RC7B_CORRECTION_C_GOVERNANCE_FAILURES.csv` (77 original nodes, each with its original
assertion, checkpoint, guard blob, pins, purpose, successor process and required approval; 2 are resolved by the Correction D CSRF successor,
75 are `BLOCKED_INDEPENDENT_FINANCIAL_AND_GOVERNANCE_APPROVAL`).

## One root cause, not 75 defects

All 75 failures follow from a single fact: the branch changes exactly twelve protected paths, and every guard below correctly
refuses a protected diff that is not an independently reviewed, pinned slice.

| # | Protected path | Pinned by | Why a guard fires |
|---|---|---|---|
| 1 | `financial_engine/orchestrator.py` | WF07 / M7 RC-3 candidate (11-blob set) | exact-content pin differs from candidate |
| 2 | `financial_engine/adapters/project_inputs.py` | WF07 / M7 RC-3 candidate | same |
| 3 | `financial_engine/financing/project.py` | F3.2.4, F3.5-A, WF04, Developer Economics | exact-content pins differ |
| 4 | `financial_engine/financing/generic_product_policy.py` | F3.2.4, F3.5-A, Developer Economics | same |
| 5 | `financial_engine/senior_debt/project_adapter.py` | F3.2.4, F3.5-A | same |
| 6 | `finco_core/inputs/_models.py` | F3.2.4, F3.5-A, Developer Economics | same |
| 7 | `finco_core/inputs/serialization.py` | F3.2.4, F3.5-A, WF07, Developer Economics | same |
| 8 | `financial_engine/adapters/tax_inputs.py` | no blob pin | namespace zero-diff guards only |
| 9 | `financial_engine/financing/quarterly_scope.py` (new) | no blob pin | namespace zero-diff guards only |
| 10 | `financial_engine/inputs.py` | no blob pin | namespace zero-diff guards only |
| 11 | `finco_core/engine/calendar_policy.py` (new) | no blob pin | namespace zero-diff guards only |
| 12 | `finco_core/engine/period_engine.py` | no blob pin | namespace zero-diff guards only |

## The 75 by guard family (counts from the CSV)

| Family | Failures | Contract | Historical vs current |
|---|---:|---|---|
| Stream-local "no financial change" guards (radar, crypto, RWA, tokenized, yield, stock-token, market bridge, multi-source, product-truth) | 30 | each stream asserts its own PR changed no `financial_engine/` or `finco_core/` path | current HEAD diff against main; the stream is not the owner of these paths |
| Other stream-local and integration scope guards (cost templates, XLSX/P1, run certificate, goal seek, DC, EV, M3, CI acceptance, parallel-stream diff) | 20 | same, or the complete reviewed-slice test `test_frozen_financial_namespaces_unmodified` | current HEAD |
| M7 / PPA-01 / RC-3 / WF07 exact-content and candidate recognition | 15 | the eleven M7 and three PPA-01 candidate blobs must be exactly the reviewed content at HEAD | current exact-content authority; historical proofs are separate and already pass at their checkpoints |
| F3 / F3.5 / WF04 pinned blobs and finance-integrity allow-list | 12 | released pins and the Finance Integrity contract | current released authority |

Normalised classes in the CSV: 52 `LIVE_INTEGRATION_SCOPE_GUARD`, 25 `CURRENT_EXACT_CONTENT_OR_CANDIDATE_AUTHORITY` (including the two CSRF
nodes now resolved). **No failure is a numerical or equation defect**: the 6/6 four-vertical regression is bit-identical to main (maximum
difference 0, `RC7B_SEMIANNUAL_REGRESSION.json`) and the quarterly oracles pass.

## What is and is not correctable without authority

- Historical-checkpoint assertions that compared a moving HEAD with an immutable source: one was found and re-anchored
  (`test_rc7_quarterly_research_isolation`, Correction B). None of the remaining 75 compares against a fixed historical SHA; the RC-3
  inventory and RC-7A coexistence tests bind the *current* HEAD blobs to the pinned candidate, so they stay blocking by design
  (Correction D keeps the positive historical proof separate and does not move the current assertion).
- Approval-neutral recognition (exact-blob successor contract, `RC7B_QUARTERLY_PRODUCTION_SUCCESSOR_CONTRACT.md`) already exists and grants
  nothing; it cannot clear guards whose own diff logic is independent of it, and editing those guards is out of bounds.
- To turn the 75 green legitimately, ALL of the following must happen in this order: (1) the Financial Owner records D-01..D-12 (see the decision
  package); (2) an independent reviewer accepts the exact content of the twelve blobs; (3) a governance owner authorizes a bounded integration
  successor over the twelve paths. Without those, repeating the full suite only rediscovers the same 75.
