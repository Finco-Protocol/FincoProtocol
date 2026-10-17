# WF-11 — Advanced OPEX Profiles V1 / Authority Report

## Existing canonical authorities

- finco_core/opex/projections.py: opex_item_amount_at_year implements persistent step changes, annual inflation; opex_schedule_annual and opex_schedule_period dispatch existing legacy and hierarchical period logic.
- finco_core/inputs/_models.py: OpexItem owns Y1 kEUR, annual_inflation, step_changes and percentage_of_opex. No approved typed arbitrary maintenance event schema.
- app/persistence/opex_sub_lines.py: owns Y1 amount and inflation for user sub-lines, not event/seasonality schedules.
- app/v2/opex_commands.py and opex_router.py: current authorized Save workflow, protected Reference, row version, owner and composite CAS. Unchanged.
- app/ui/opex_view_model.py: per-line year_values and inflation; existing Working Copy evidence. WF-11 reuses rather than recalculates or treats it as committed Run.
- app/ui/opex_sheet_projection.py: B.01–B.13 codes, parent grouping, mixed escalation and derived contingency.
- sheet_opex.html: existing cost editor, contingency and annual projections remain intact. New advanced panel is additive.

## Authority matrix

| Behavior | Financial authority | WF-11 treatment |
|---|---|---|
| Recurring / indexed annual OPEX | Existing canonical engine | Display effective ViewModel line values |
| Persistent step changes | Existing OpexItem | Display resulting annual line values; precise step provenance still needs source-specific attribution |
| Hierarchical OPEX / percentage-of-OPEX | Existing canonical engine | Do not edit derived contingent or electricity amounts independently |
| One-off / repeated major maintenance | NONE APPROVED | Typed candidate only; no persistence or Run |
| Semiannual seasonal distribution | NONE APPROVED | Illustrative full-year weight split only; does NOT claim exact canonical period/stub allocation |
| Quarterly seasonal distribution | Workstream A pending | Candidate validator only; not operationally activated |

## Candidate behavior

MaintenanceCandidate has owner identity, event ID, operating year, explicit amount in kEUR, recurrence class, proposed accounting class, and provenance. Negative/non-finite, unknown/derived owner, duplicate event identity, duplicate owner-year occurrence, invalid recurrence and out-of-horizon values fail closed. No candidate changes OpexItem step_changes, Working Copy, baseline annual amount or Run.

Browser candidates exist in transient in-page memory only; navigation/refresh discards them. No browser storage, DB schema, server-side Save or hidden activation mechanism. They have no asserted P&L, CFADS, tax, debt sculpting, return or committed historical effect. Even a proposed OPEX_EXPENSE classification requires explicit institutional approval. Capital replacement is never silently treated as operating expense.

Seasonal preview allocates full-year displayed line amounts into illustrative H1/H2 weights with exact total conservation in Decimal unit tests. Actual six-month period dates, day_fraction, COD and final stub periods, leap-year behavior and quarterly engine rules are **NOT VERIFIED** here. The existing canonical period engine is unchanged.

## Successor financial authority required before activation

1. Accounting approval and controls for overlap with baseline OPEX and CAPEX.
2. Approved schema, owner, persistence/readback and scenario/composite CAS.
3. Approved canonical period frequency, COD, leap year and first/last stub semantics.
4. Deterministic Run consumption and reconciled P&L/CFADS/tax/debt outputs.
5. No historical Run mutation and independently verified numerical parity, without widened goldens/tolerances.
6. Independent review and explicit approval before any canonical activation.

## Test evidence / limitations

Standalone Python unit ring: 19 tests passed (candidate validation, recurrence, finite values, annual-total conservation). Isolated Jinja and real Chromium mobile smoke: 2 tests passed, covering display, manual candidate entry, duplicate prevention, 40/60 allocation, invalid weights and no page-level overflow. JavaScript syntax verified. Full authenticated app/browser integration and existing golden suite require exact-head GitHub CI.

No local full checkout available; neither app-backed CAS tests nor actual canonical P&L/CFADS/tax effects are claimed to have been executed by this workstream.
