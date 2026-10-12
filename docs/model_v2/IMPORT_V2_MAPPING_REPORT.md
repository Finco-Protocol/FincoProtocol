# AI Import V2 — intelligent financial input mapping and review

Base: `main` 1152dd2. Branch `feat/model-ai-import-v2-mapping`. Application layer only: no `financial_engine/`, `finco_core/`, workflow, Radar/crypto or deployment change.
"AI" here is a deterministic, explainable ranking. No model, network call, key or provider is used; no workbook content leaves the process.

## 1. Reuse / gap matrix (from the code on main)
| Capability | Where | Status |
| --- | --- | --- |
| Authenticated CSV/XLSX intake, bounded parser, zip/active-content/formula guards | `model_import/intake.py` | DONE — reused unchanged |
| Exact field-id / exact-label mapping, unit + percent normalisation, provenance (sheet, cell) | `intake.py` | DONE — reused; extended |
| Signed preview / approved tickets, owner+project binding, 15-min TTL | `model_import/review.py` | DONE — reused; provenance fields added |
| Atomic canonical batch Apply, composite + scenario CAS, protected reference | `WorkbookUpdateService.apply_batch_draft_update` (C0) | DONE — the only writer, untouched |
| Cost lines atomic writer (#250), Revenue V2 contract writer (#258), F3/F3.5 instruments | own services | DONE — NOT written by Import (see §4) |
| Fuzzy / terminology / unit-dimension / context ranking, alternatives, duplicate detection | — | MISSING → `model_import/mapping.py` |
| European number formats, kW/GW and EUR/kWh conversions, units written in a label | — | MISSING → added (ambiguity rejected) |
| Category filter, confidence sort, attention queue, safe bulk select, per-row explanation | — | MISSING → `import_review.html` |
| Assumption Register as a provenance store | `assumption_register.py` | PARTIAL — a read projection with no write API, so it is not used as a store |

## 2. What is new
- **Mapping candidates** (`mapping.py`): token overlap over registry labels with a financial-terminology table, sheet/section context, CAPEX-vs-OPEX intent (wording, "/yr" units, sheet), unit-dimension compatibility (an incompatible unit is never a candidate), technology applicability from the registry (never from wording). Output per cell: target, kind, category, a confidence **category** (exact / exact label / high / medium / low — no invented probability), the explanation, and alternatives. Ties and duplicate targets are flagged, not resolved.
- **Never ready by inference**: only an exact field id is `ready`; every ranked suggestion is `needs_review` and unchecked.
- **Structured targets** (B/C/D) are recognised and shown read-only with `UNSUPPORTED_FOR_APPLY` and the editor that owns them. Cascade fields (e.g. installed capacity) are recognised but reported as not batch-applyable, with the precise backend reason.
- **Numbers**: `1.234,56`, `1,234.56`, `1 234,5`, `12,5`, `0,062` are read; `1,234`, `18.000`, `12.500` (thousands or decimal?) are rejected as ambiguous because a wrong guess is a 1000× error.
- **Units**: EUR→kEUR, kW/GW→MW, EUR/kWh↔EUR/MWh, %/fraction (existing strict rules), units explicitly written in a label (`Installed capacity (MW)`). A missing unit is never guessed.
- **CSV delimiter**: chosen by presence on most lines (`;` / TAB before `,`) so decimal commas do not break parsing.
- **Review UI** (same page): category and status filters, "Unmapped / ambiguous queue", sort, **Select validated** (only independently validated, non-duplicate, non-ambiguous rows), alternatives, explanation, original → normalised value, duplicate warning, final change-set review with previous values and normalisation decisions.
- **Provenance** (signed tickets and the result page): sheet/cell/label/raw value, source unit, normalisation decision, selected target, previous value, approved value, mapping method + explanation, approval event and time, and the new composite identity of the transaction. Nothing from the workbook is stored by the app.

## 3. Synthetic mapping benchmark (generic labels, `tests/test_model_import_v2_mapping.py::BENCHMARK`)
- scalar cases=21 correct_suggestion=21 wrong_suggestion=0 not_suggested=0
- non-scalar/unsupported cases=10 correctly_classified=10
A wrong confident scalar suggestion is a test failure (precision of confident suggestions = 100% on this set; recall asserted ≥ 90%). This is a regression guard on a small synthetic set, not a claim of general accuracy.

## 4. Structured targets: why they are read-only here
Writing B/C/D from Import would need ONE all-or-nothing transaction covering scalar rows, cost-line rows (row versions, `update_cost_lines_batch`), Revenue contract JSON, and F3 instruments, under the same composite CAS and scenario identity. The existing writers each own their transaction (`BEGIN EXCLUSIVE`); composing them is shared transactional authority. **Required contract before enabling:** a single `_exclusive_tx` entry point accepting heterogeneous staged writes with per-domain validators, the signed ticket carrying row versions, and independent review. Until then these rows stay `UNSUPPORTED_FOR_APPLY` and the C0 whitelist is unchanged.

## 5. Optional assistant (design only, not implemented)
An opt-in assistant would be a separate, explicitly configured provider with an approved data-transfer policy, off by default, no embedded keys. Its output could only enter through `mapping.validate_candidate` and the same unit/registry/applicability checks, then the same user approval. No provider code exists in this PR.

## 6. Security and safety (tests)
`test_model_import_v2_review_security.py` (route level, 15): unapproved suggestions never persist; forged / structured / cascade / inapplicable / unknown targets rejected before any write; read-only rows cannot be approved unmapped; mixed accept/reject exact; one invalid row rejects the whole set; stale composite rejects everything; tampered, replayed and foreign tickets refused; formulas and oversized files rejected. Existing C0, intake, browser and F3-integration suites (52) pass unchanged.

## 7. Browser acceptance (real Chromium, `test_model_import_v2_browser.py`)
Solar, Wind, Data Center, EV Charging: multi-sheet XLSX with European formats; categories, filters, attention queue, sort, bulk select; read-only rows unchecked; a user-modified mapping; a rejected row; confirm; Apply with exact canonical values (EUR→kEUR, kWh→MWh, %); state STALE with no Run and Run History unchanged; manual Run → CURRENT; earlier Run History entries unchanged. Mobile 390 px has no page overflow.

## 8. Not covered / limitations
- Layout support is unchanged: label / value / unit rows (plus one-cell block headers). Wide period tables are not interpreted.
- Interaction with the #264 cost UX was not exercised: that branch is open and was not touched; Import never writes cost lines.
- Ranking vocabulary is a curated table; unfamiliar terminology falls to the unmapped queue and the user maps it manually.
