# RC-M — integrated React migration parity: executive README

**Branch:** `claude/new-session-6o4z8l` · **Base:** `main` `cf7056de4078ca66afcf52265a9bacafe35586f7` (PR #386 and #387 merged) · **Status:** Draft, for independent review.
No merge, deployment, activation of a release-closed feature, or self-approval was performed.

**Release posture (Correction B):** the React workspace is behind `FINCO_MODEL_REACT_V1` (default OFF) and nothing here authorizes production use. **New Project is not
production-ready**: cross-worker duplicates are fenced by an adapter-level ledger, but exactly-once creation at the canonical writer is prepared, tested and held until FIN-VAL
F01 (#389) merges (`atomic_create/README.md`, `08_…` item 3). Interest-rate unit behaviour belongs to F01 and is not reimplemented. The deployed bundle is cache-busted by a
content hash (`REACT_ASSET_VERSION`), not by hand.

## What this delivers

Four React capabilities that the Legacy→React audit named as P1 gaps, each a thin, authenticated adapter over an **existing canonical
authority** plus a compact React UI. No financial formula, solver, default or writer was added or changed.

| Gap | React capability | Canonical authority reused | Writes |
|---|---|---|---|
| GAP-R1 | **+ New Project** 4-step wizard (Library CTA and global navigation) | `create_reference_seeded_project` (the service Legacy `/projects/create` uses for the Solar/Wind/Data Center/EV references) | one CSRF-bound create; exactly one working copy |
| GAP-R2 | **Analysis › Sensitivity**: one-driver 5-point table and 3×3 / 5×5 matrix | `sensitivity_matrix` service + `run_matrix_points` (original `run_project` in the bounded executor) | none — ephemeral, not a Run |
| GAP-R3 | **Analysis › Goal Seek**: PREVIEW solve, explicit *Apply to Working Copy* | `goal_seek.solve_tariff_for_metric`; `WorkbookUpdateService.apply_draft_update` (composite-hash CAS) | Apply only; CSRF-bound; Last Run becomes STALE, never run |
| GAP-R5 | **Financing studio**: Debt terms (existing editor, opens first), overview, **typed Bankability editor**, Senior facilities (read-only), Sources & uses, Investors | Legacy Debt-sheet context (`_build_debt_ctx`), `bankability_config`, `build_sources_uses_projection` | the canonical per-field writer `/v2/workbook/update` (no new endpoint) |
| GAP-R6 | **Investors & sponsor**: typed common-equity holders and paid-in capital, Run-bound evidence, read-only SHL facts | F4 `save_agreement`, `validate_evidence`, `build_sponsor_view` | the canonical F4 route (CAS + version CAS) |

## Architectural choices

* **Adapters live in their own new modules** (`app/v2/react_new_project.py`, `react_analysis.py`, `react_goal_seek.py`,
  `react_financing.py`, `react_investors.py`), mounted by one additive include block in the already-pinned `react_workspace_router.py`.
  Behaviour is therefore reviewable as new files, not as edits to protected sources.
* **Read adapters are GET and write nothing.** The two that spend executor capacity (sensitivity, goal-seek solve) require the
  `X-Finco-React-Request: 1` header (not sendable cross-site without a CORS preflight). The only new mutation routes are
  `new-project/create` and `goal-seek/apply`; both validate the signed, resource-bound CSRF token **before** any writer.
* **The browser calculates nothing.** The only arithmetic is presentational (percent↔fraction of an *input* exactly as the Legacy
  editors do, a delta of two server-supplied numbers, a total of what the user typed). A governance test greps the new React sources
  and adapters for engine/solver/IRR/NPV code.
* **Serializer parity is proven, not assumed:** Chromium tests drive the Legacy form and the React form with identical values and assert
  byte-identical documents for the bankability configuration and the F4 agreement.
* **Fail closed on ambiguity.** An unknown Create / Save / Apply outcome is never retried; the UI locks the control, says "Result unknown",
  and reconciles by request identity (Create) or a fresh authorized read.

## Before / after

Before: React could open and run working copies but could not create a project, analyse sensitivity, solve a tariff, edit
bankability terms or define investors — each sent the user back to the classic workbook. After: each is a React workflow with the same
server authority, explicit PREVIEW / NOT A RUN / STALE labelling, and the unchanged Save ≠ Run separation.

## Evidence map

`06_BROWSER_ACCEPTANCE_AND_ACCESSIBILITY.md` (real Chromium, mandatory role) · `07_TEST_REPORT.md` (every suite, counts, mutation checks) ·
`08_OPEN_OWNER_AUTHORIZATIONS.md` (governance successors, atomic-create plan, findings) · `09_EXACT_HEAD_EVIDENCE_AND_FINAL_REVIEW.md` (exact-head CI and verdict).
No statement here claims that all audited gaps are closed, a coverage percentage, or complete Legacy parity.

## Not delivered (see `02_PARITY_GAP_REGISTER.csv` and `08_OPEN_OWNER_AUTHORIZATIONS.md`)

Two-Senior facility **editing** (shown read-only and marked NOT RELEASED), what-if, scenario KPI compare breadth, Run History
browsing, Revenue/CAPEX studios, Import, Trust triggers, Library filters/compare — **NOT-STARTED** here. F01 (interest-rate contract) is
not merged, so no rate default or rate-dependent parity claim is made.
