# Model V2 Implementation Guardrails

Status: active for the `epic/model-saas-v2` program.
Baseline: `main` at `2f963a77bbad7bda23ca5bac5d6efbe9a11d2b0b`.

This document states the ownership and safety rules every Model V2 workflow
must follow. It is a guardrail document, not a feature specification.

## 1. Branch and delivery policy

- All Model V2 work happens on the isolated long-lived branch
  `epic/model-saas-v2`, created from canonical `main`.
- Feature PRs target the epic branch. Only the coordinator merges
  `main -> epic`. The shared epic branch is never rebased.
- The epic branch merges back to `main` only after the full Model V2
  acceptance gate passes.
- The foundation flag `FINCO_MODEL_V2_ENABLED` is **disabled by default**
  (`app/model_v2/flags.py`). No V2 UI, API surface, or runtime financial path
  switch may activate from the flag until a reviewed workflow introduces one.

## 2. Financial authority invariants

- There is ONE deterministic calculation authority. The canonical path is:
  typed ProjectInputs → technology/production → revenue/OPEX/tax →
  construction financing → senior debt sizing → project & shareholder
  waterfall → sponsor returns → financial statements → analytics → committed
  Last Run → API / XLSX / Trust Pack.
- No UI-side, exporter-side, or report-side financial arithmetic. Every
  numeric result traces to the engine.
- Working Copy edits never mutate committed Last Run evidence.
- Missing authority surfaces as typed unavailable, never as zero.
- Unsupported technologies fail closed (Storage remains gated as today).
- Scenario logic mutates typed inputs before the single canonical run.

## 3. Namespace ownership

| Namespace | Owns | Must not contain |
|---|---|---|
| `finco_core/**` | typed stable contracts, generic time/XIRR utilities, canonical input structures | app UX state, presentation metadata |
| `financial_engine/**` | financial mathematics: revenue aggregation, tax, debt, reserves, statements, returns, valuation | persistence, UI, product metadata |
| `domain/**` | reusable contract-level mathematics (PPA, merchant, CfD, FiT, capacity) | app adapters, persistence |
| `app/**` | template resolution, adapters, persistence, scenarios, API, UI, compare, assumption register, trace orchestration, exports | second financial calculators |

New financial mathematics enters `financial_engine/**` or `domain/**` only
when a proven economic capability does not already exist.

## 4. Stage and Perspective are non-economic

Project Stage (`screening`, `development`, `ready_to_build`, `financing`,
`construction`, `operating`, `exited`) and Model Perspective (`developer`,
`ipp`) are **product metadata** owned by `app/model_v2/project_metadata.py`
and persisted as nullable columns on the project record
(`projects.project_stage`, `projects.model_perspective`).

They must never:

- alter ProjectInputs financial assumptions or any engine formula;
- create hidden stage-dependent financial defaults;
- enter any engine input fingerprint, content hash, or run identity;
- be inferred or silently assigned for existing projects (NULL = not set;
  no sentinel value exists in the canonical vocabularies).

Stage/Perspective affect presentation, defaults, workflows and filtering —
nothing that lands in a financial result.

## 5. Central integration choke points

The following shared surfaces change only through coordinator-owned changes
with an explicit integration-diff specification:

- `finco_core/inputs/_models.py`, `domain/inputs.py`
- `app/input_schema.py`, `app/input_adapter.py`, `app/workbook/input_set.py`
- `financial_engine/adapters/project_inputs.py`
- `app/project_factories.py`
- `app/persistence/records.py`, `app/persistence/projects_repository.py`,
  `app/persistence/workspace_repository.py`
- `app/model_methodology_registry.py`
- central API routers and `app/export/institutional_workbook.py`

Feature workstreams build stable domain contracts first, then hand the
coordinator an explicit diff specification for these surfaces. Contracts
before adapters.

## 6. Migration and compatibility rules

- Existing projects open without silent economic mutation.
- Persistence changes are additive and nullable; old rows stay readable and
  unset metadata is never guessed.
- A migration changes representation only — it must not change economics.
- Protected Generic Solar / Generic Wind reference economics are frozen:
  zero intended numerical change unless a reviewed PR explicitly changes a
  contract. Every foundation-level change is proven against the captured
  before/after reference metric baseline.

## 6b. Active epic scope (temporary governance authority)

`docs/model_v2/ACTIVE_EPIC_SCOPE.json` declares the explicit Model V2 epic
scope: program, base SHA, the exact engine files the epic is authorized to
change, the exact reviewed support files, and the strictly frozen namespaces
(`finco_core/`, `domain/revenue/`, `domain/analytics/`, Radar/Yield/Crypto
authorities, `app/model_validation/`, `app/verified/`). It replaces the false
blanket "authorities are always zero-diff vs main" assumption for the duration
of the epic only.

Lifecycle rules:

- The marker exists ONLY while `epic/model-saas-v2` is under development.
- Authority never comes from a branch name and never from wildcards; every
  future file needs an explicit, committed scope update
  (`tests/test_model_v2_governance.py::test_g_future_files_require_explicit_scope_authorization`).
- Frozen namespaces can never be approved — rejected by scope validation and
  hard-denied in `tests/model_v2_governance.py`.
- **The marker must be deleted (or set `status=RETIRED`) before the final
  epic-to-main release merge.** This is enforced by
  `test_active_epic_scope_must_not_reach_main`
  (acceptance marker `MODEL_V2_EPIC_SCOPE_MARKER_RETIREMENT_GATE`), which
  fails on any main-tip checkout carrying an ACTIVE marker.

## 7. Implementation neutrality

All artifacts describe requirements as native FINCO product requirements.
Branch names, commits, code comments, tests, fixtures, docs, UI copy, API
descriptions and issue titles must not reference external products, research
provenance, or benchmark sources.
