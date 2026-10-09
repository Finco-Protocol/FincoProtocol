# Model V2 — Workflow E: Developer Economics & Investment Decision Workspace

Baseline: `main` at `bf9b71ee6e2c8b952dd0d9da7f995fa9c80bd3bf`. Branch `feat/model-v2-developer-decision-economics`.
One Draft PR, developed in parallel with PR #226 (not touched, not depended on). **Do not merge.**

## Capability inventory

| Capability | Classification | Evidence |
|---|---|---|
| Typed `DevelopmentEconomicsInput`, fee modes, dated spend, reimbursement ≤ eligible, abandoned rules | IMPLEMENTED (V1, frozen) | `finco_core/inputs/development.py` |
| Developer calculator, MOIC/XIRR with typed unavailable statuses, dated vector | IMPLEMENTED (V1, frozen) | `financial_engine/developer_economics/` |
| Project-use / S&U / book-basis integration, assumption register, trace, analytics | IMPLEMENTED (V1, frozen) | contract doc `DEVELOPER_ECONOMICS_CONTRACT.md` |
| Read-only Developer workspace (sections A–F), DISABLED / ACTIVE / INVALID states | **IMPLEMENTED (this PR)** | `developer_economics_projection.py`, `/v2/developer-decision` |
| Editable Developer inputs (spend schedule, reimbursement, fee) | **PERSISTENCE BRIDGE MISSING** | see "Missing bridge" |
| Developer metrics from the persisted Last Run | **PERSISTENCE BRIDGE MISSING** | the Run never receives `development_economics`, so nothing is persisted |
| Stage / Perspective display (workspace + compare) | IMPLEMENTED (this PR) | non-economic, never inferred |
| Stage / Perspective editing | UI MISSING | stored on the project record; no authorised edit route exists today. Editing must go through a project-record contract, not through this PR |
| Expected NPV (probability-weighted) | **FINANCIAL AUTHORITY MISSING** | 8 conditions, none met — shown unavailable with the exact gaps |
| Project NPV | FINANCIAL AUTHORITY MISSING | `runtime_summary.project_npv_keur` is not persisted; displayed only if a Last Run ever carries it |
| Development margin | FINANCIAL AUTHORITY MISSING | no approved definition; no competing MOIC created |
| Compare: stage, perspective, freshness, Last Run identity, Project NPV availability, developer-returns availability, stable sort | IMPLEMENTED (this PR) | `decision_support_projection.py`, `compare_projects.html` |
| Buy/sell recommendation | DEFERRED by design | never produced |

## What ships

* `app/v2/developer_economics_projection.py` — presentation of the canonical calculator output. No second calculator; the
  figures are `compute_developer_economics` / `resolve_developer_project_uses` applied to the effective typed `ProjectInputs`.
* `app/v2/developer_decision_projection.py` — Project NPV (persisted only), Expected NPV conditions, margin, stage/perspective.
* `app/v2/developer_decision_router.py` + `main_web.py` (two-line registration) — `GET /v2/developer-decision?project=CODE`,
  owner-isolated via `resolve_accessible_project`, freshness via `resolve_runtime_freshness`, no engine, no write.
* `app/templates/v2/developer_decision.html`, `static/css/model_developer_decision.css`.
* Compare Projects: stage/perspective rows, Last Run identity, CURRENT/STALE/NOT RUN (UNKNOWN when it cannot be determined),
  Project NPV and Developer returns availability rows, and a stable sort that always places unavailable last and handles
  negative/zero values (previously an ascending sort ranked unavailable first).

## Missing bridge for editable Developer inputs (exact)

A guarded editable path needs all of the following, none of which can be added from presentation files:

1. **Snapshot/input schema** — `app/workbook/input_set.py` `ProjectInputSet` and `to_projectinputs()` do not carry
   `development_economics`; the adapter always yields `None`. (Shared `ProjectInputs` schema/frozen contract.)
2. **Persistence** — a typed authority field (the `replay_metadata` contingency pattern in `workspace_repository.py`) with CAS,
   owner/protected-reference checks and scenario isolation.
3. **Identity** — `workbook_identity.py` must include the authority in the composite hash so a save turns the Last Run STALE
   and the run-bound identity (`last_runtime_identity_json`) records it for export parity.
4. **Run** — `app/v2/router.py` `v2_workbook_run` must pass it into the clean production run, and `runtime_summary` /
   Run History / exports must persist the developer ledger so the Last Run can show Developer MOIC/XIRR.
5. **Disabled ≡ reference** — disabled must keep payloads byte-identical; Project Perspective = Developer must not auto-enable.

Those are shared/central persistence contracts outside this PR's ownership, so the editable feature was **not** built, and no
browser-only calculator, ad-hoc JSON or disconnected form was added.

## Expected NPV proposal (not implemented)

A typed `OutcomeScenarioSet` (id, label, probability, owner, approval) in `finco_core`; one canonical persisted NPV per scenario
Run under a single approved valuation authority (discount rate + valuation date); bound to Run History; export parity;
`Expected NPV = Σ pᵢ × NPVᵢ` over CURRENT Runs only. Project NPV and Expected NPV keep separate labels and authorities.

## Isolation

Zero diff in `financial_engine/**`, `finco_core/**`, `domain/analytics/**`, Radar, Yield, Crypto, Protocol. One additive hunk in
`app/v2/router.py` (compare route payload + stable sort call) — the only touch of a file PR #226 also edits; different hunk.
