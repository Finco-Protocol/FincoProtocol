# F04 / U01 / U02 / F05 — Inputs workspace redesign

## Measured problem (real Chromium, disposable Working Copies)

Audit: ~11,889 px (1440) and ~15,199 px (390) for Inputs. Reproduced: a full-page screenshot of the Solar Inputs page at 1440 was
**11,889 px**. Causes read from the source and screenshots:

1. `CanonicalInputGrid` rendered **one table per category** — 17 CAPEX categories each with its own "Field / Value / Unit /
   Status" header and a one-row body, repeated through OPEX, Revenue, Tax…; columns drifted between tables.
2. The CAPEX/OPEX line editor and the "Add or retire lines" manager both listed all ~32 lines in full-height rows.
3. A paragraph said the CAPEX/OPEX writer was "out of this PR's scope" while a working editor sat below (F04).
4. Engineering help text ("composite CAS … 409", "inputs_section form … PARTIAL path", "(R8/N02)") (U02).
5. Label + unit duplicated (`IT Capacity (MW) (MW)`) (F05).

## Redesign (existing components and CSS tokens only; no new framework)

| Change | Where |
|---|---|
| One table per grid **section**, one header, consistent column widths; a group row only when a category has several rows or a different name | `CanonicalInputGrid.tsx`, `rx-mvp-correction.css` |
| Each section is a native `<details>`: sections containing editable fields start open; purely derived sections start collapsed with a count summary ("18 derived"); `Expand all sections` / `Show editable sections only`; a read-only (protected) grid starts fully expanded | same |
| Every row carries a state badge — **Editable**, **Derived** (follows line items or the model), **Not editable here** — plus its original authority text | same |
| Compact row padding; at ≤640 px rows stack (label, value+unit, status) instead of scrolling sideways | CSS |
| CAPEX/OPEX line tables are labelled, keyboard-reachable scroll regions with sticky headers (all controls stay in the DOM and tab order) | `ux040506Views.tsx`, `CostLineManager.tsx` |
| Sticky in-page navigation: **Project setup · Assumptions · CAPEX · OPEX · Revenue & PPA · Financing →** (CAPEX/OPEX switch the line editor; Financing opens its own section; keyboard focus moves to the target) | `InputsGuide.tsx`, `WorkspaceView.tsx` |
| "What each Save writes" guide + a one-line **Saves:** statement inside every editor (Project setup, Assumptions, CAPEX/OPEX, Financing, Scenario overrides; the PPA editor keeps its explicit "Save contracts") | `InputsGuide.tsx`, editors |
| Plain-language hints; the raw registry text moves to a "Technical note" disclosure | `plainCopy.ts`, `SheetFieldsEditor.tsx` |
| Unit rendered once, from metadata (`splitLabelUnit`) in `Field`, override rows, grid aria-labels | `fieldLabel.ts`, `workflowShared.tsx` |

Preserved: all editable fields, keyboard navigation, read-only authority labels, error feedback, the draft/dirty/leave-guard
registry, CSRF/CAS handling (no request shape changed), focus behaviour, separate Save writers (no global writer, no autosave).

## Result (same measurement method before/after: all editors loaded)

| Page height | Before | After |
|---|---|---|
| Solar 1440 px | 11,907 px | 4,920 px (−59%) |
| Solar 390 px | 15,292 px | 8,601 px (−44%) |
| Data Center 390 px | 16,054 px | 6,592 px (−59%) |

(Full matrix for 320/390/768/1440 × four verticals in `REACT_BROWSER_ACCEPTANCE.md`.) No essential field is hidden: the
acceptance compares the canonical API's editable cell list to the rendered `[data-grid-cell]` set (exact equality), and project-setup bound fields to inputs.

## F04 — the Save-scope truth

Obsolete text removed: "…writer is out of this PR's scope" (router `cost_line_boundary.note`, now: *CAPEX and OPEX are built from
line items. They are edited and saved in the CAPEX and OPEX line-item editors, not in this grid…*). `capex_opex_editable: false`
keeps its meaning (the scalar grid cannot edit them) and its existing test.

## U02 — plain language, what was and was not changed

Changed: Inputs/Financing/Project setup helper text, Run History note, CAPEX/OPEX notes, PPA note, metric "Canonical source:
RuntimeResult…" lines (now a finance meaning + a "Technical source of each figure" disclosure), sponsor/distribution
"Source: CovenantGatedWaterfallResult…" (now behind "Technical source"), scenario notes, footer.
Example: interest rate hint now reads *"…the interest rate is controlled by the detailed financing schedule."* The interest-rate
**value representation was not touched** (Overnight A / F01).

Deliberately **kept**: typed outcome messages that must say `UNKNOWN`, "may have committed", "retry/duplicate" (they carry safety
semantics asserted by existing tests), and implementation provenance inside disclosures. Stale/conflict messages from the server
are shown as the server sends them.

## Limits

* The Project-setup "Technical Parameters" block still repeats a few fields that the grid also lists (read-only there).
* Mobile Inputs remains long (8.6k px at 390 for Solar) because every editable field and the 32-line editor stay available.
