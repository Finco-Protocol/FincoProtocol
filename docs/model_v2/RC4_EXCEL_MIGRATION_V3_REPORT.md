# RC-4 / Workstream C — Excel model migration V3

Base: `origin/main` 4483b30904a30cd3f5406506283202e2ebeaf427. Additive: no financial engine, no new writer, no database/schema change, no macro or formula execution. All fixtures are original and synthetic.

## 1. Preflight inventory (from main)
| Capability | Where | Status |
| --- | --- | --- |
| Bounded CSV/XLSX intake, zip/active-content guards, unit + number validation | `model_import/intake.py` | DONE — reused; `_check_xlsx_zip` gained an opt-in `inspect` mode, strict path unchanged |
| Exact/fuzzy ranking, structured-owner recognition | `model_import/mapping.py` | DONE — reused unchanged |
| Signed preview/approved tickets, owner+project binding | `model_import/review.py` | DONE — extended additively (`migration` payload, scenario confirmation, applied-evidence ticket) |
| Atomic scalar Apply with composite + scenario CAS, protected reference | `WorkbookUpdateService.apply_batch_draft_update` (C0) | DONE — the only writer, untouched |
| Scenario create/select, Run, Run History | existing routes | DONE — reused |
| P0-B3 numerical reconciliation | `tools/numerical_validation/reconcile.py` | DONE — delegated to |
| Macro/formula/scenario inspection, migration plan, portfolio manifest, migration reconciliation view | — | MISSING → added |

## 2. What is new
- `model_import/workbook_inspect.py` — non-executing inspection of `.xlsx/.xlsm`: sheets (incl. hidden/veryHidden), defined names (kind-classified), calc flags (iterative), literals vs formula text vs stored result, formula references/functions/active-or-dynamic flags, external-link *descriptors*, macro indicators, VBA module **names** from the OLE directory (no decompression, no source, malformed containers reported not raised). `defusedxml` for all XML; the zip-bomb, entry-count, size, ratio, path and timeout guards are the existing ones.
- `migration_scenarios.py` — scenario evidence (column blocks, sheet-per-scenario, name-only, selector cells/names + the formulas that read them, macro-bearing switch). Resolution: `STATIC_OBSERVABLE`, `PARTIALLY_OBSERVABLE`, `SCENARIO_LOGIC_UNRESOLVED`. Every scenario is `LABEL_ONLY_UNVERIFIED`; a name alone is never semantics, and a scenario-named sheet never degrades to case-independent inputs.
- `migration_plan.py` — classification into `DIRECT_INPUT_MAPPING`, `STRUCTURED_INPUT_REQUIRES_OWNER_EDITOR`, `FORMULA_OR_MACRO_DEPENDENCY`, `OUTPUT_FOR_RECONCILIATION_ONLY`, `UNSUPPORTED_OR_AMBIGUOUS`; per item: source sheet/cell, value, unit, canonical field, mapping explanation, scenario membership, target project+scenario, supported writer, required human decision, unsupported dependency. Scalar mapping/unit rules are the existing engine (`intake.proposals_from_tables`, refactored out of `extract_proposals`). Apply **slices** (one per observable scenario, plus case-independent inputs) are re-run through that engine, so duplicates and applicability are re-validated. Macro-aware assessment answers the seven required questions as a dependency assessment, not a VBA interpreter.
- `migration_reconcile.py` — see §5. `migration_portfolio.py` — see §6.
- Routes (same router, same prefix): `POST /workbook/import/assess`, `/review-slice`, `/reconcile`, `/manifest`; template `import_migration.html`; the existing review/confirm/apply template shows the scenario banner, the required scenario confirmation, "CHANGED — NOT RUN" and the compare form.

## 3. Journey (supported scalar data)
upload → assess (read-only) → plan → open one scenario slice (signed ticket, no re-upload) → review in the existing UI (units resolved per row) → **mandatory** confirmation that the source case is the intended target scenario → existing signed confirm → existing C0 Apply into the **active** scenario → "CHANGED — NOT RUN" → user starts a normal Run → reconcile against the committed Run. Target Working Copy/scenario is chosen with the existing scenario workflow (create/select); the ticket is bound to that scenario id and composite hash, so switching scenario makes every earlier ticket stale. Each slice is a separate transaction: **there is no cross-scenario atomicity** and none is claimed. Structured/formula/output/unresolved rows have no checkbox, no ticket row that Apply accepts, and are rejected server-side if forged.

## 4. Supported / unsupported matrix
| Workbook content | Result |
| --- | --- |
| Literal scalar with exact id / exact label / ranked label, convertible unit | DIRECT (review required; only exact id is `ready`) |
| Scenario columns with literal values (Base/Upside/Downside/P50/P90/numbered) | observable per scenario; separate slice and transaction each |
| Scenario via sheet-per-scenario | same |
| Switch cell + CHOOSE/INDEX/IF, macro-driven switch, scenario name only | `SCENARIO_LOGIC_UNRESOLVED`; never applyable; stored values reflect only the case selected at save time |
| Partially literal scenario | literal cells slice; formula cells listed as dependencies |
| CAPEX/OPEX line tables, revenue contracts/curves, financing instruments, cascade fields (capacity) | STRUCTURED, owner editor named, not written |
| Formula cells (incl. those with stored results) | FORMULA_OR_MACRO_DEPENDENCY; stored result shown as "not authoritative"; never a fixed assumption |
| IRR/NPV/DSCR/totals, output sheets (Results/Summary/…) | OUTPUT_FOR_RECONCILIATION_ONLY; output sheets never feed Apply |
| Ambiguous unit / `1,234` number / missing currency unit / percent scale | DIRECT but BLOCKED with required unit decision; never guessed |
| Wide period tables, matrices, text notes | not interpreted (counted per sheet and reported) |
| External links, DDE, WEBSERVICE/HYPERLINK, ActiveX, VBA | reported; never opened/executed; strict flat path still rejects them |
| Macro behaviour, iterative/circular calculation, INDIRECT/OFFSET | listed under "requires a separate approved feature" |

## 5. Numerical reconciliation
Delegated to P0-B3 `compare` (statuses PASS/FAIL/UNAVAILABLE/NOT_COMPARABLE, residual FINCO − source, declared tolerance, default 0). A comparison is attempted only if: (G1) the source output is a finite cached/literal number whose label maps to exactly one metric in an explicit table with an explicit unit rule; (G2) its formula precedents are fully observable and every numeric leaf was mapped **and applied** (a static hard-coded output has no dependency evidence, dynamic/external functions and truncated graphs block); (G3) the committed Run is the newest Run of the target scenario, freshness CURRENT, `composite_hash` equals the Working Copy; (G4) applied values are intact; (G5) the user attests scope, currency, period and conventions. Else NOT_COMPARABLE with reason codes. Run id must belong to the same project (forged/cross-project ids rejected). Horizon metrics use a single labelled whole-run pseudo-period, not a calendar alignment. Input-mapping completeness is a separate number and is labelled "not financial parity". Source outputs are only what the file itself stores (cached values); nothing is recomputed.

## 6. Portfolio manifest
Signed (itsdangerous, 6 h), user-carried, ≤ 12 workbooks, keyed by SHA-256. Holds identity hash, sheet used-ranges, scenario labels/resolution, class counts, mapping completeness, unsupported-feature codes, review status, apply eligibility, reconciliation status. **No** values, formulas or workbook bytes; no server table/file/worker/queue; grants no authority; never runs or overwrites anything. Statuses advance only from server-observed steps (assessed → review → applied → reconciled).

## 7. Security and test results
Local, this branch: new suites 120+ tests (inspect 28, reconcile 48, security 22, journey 2, benchmark 6, Chromium 3) plus existing Import V1/V2 (mapping, intake, provenance, review security, atomic C0, F3 integration, counters, trust controls: 231 incl. new unit suites) and existing Chromium import suites — **50 passed** in the browser/route group, all existing suites unchanged in intent.
Covered: normal XLSX; XLSM without execution; hidden/veryHidden sheets; named ranges (cell/range/constant/formula/external); formula-only cells; cached vs formula; external links (strict path still rejects); zip bomb, traversal, entry-count, size, malformed zip, XML entity/DTD; truncated/looping/garbage VBA containers; ambiguous numbers/units; duplicate targets; untrusted labels (bidi/control stripped, bounded); selector cells, selector-only, macro-bearing selector, partial observability, name-only scenarios; cross-project and cross-owner tickets, tampered/replayed tickets, wrong ticket kind; cross-scenario CAS on review, confirm and apply; concurrent edit; atomic rejection (one bad row, unit-less currency, duplicate target — nothing written); forged structured/cascade/formula targets; skipped scenario confirmation; protected reference; no Run and no write from assess/review/reconcile; module source guard (no file/network/subprocess/eval, no engine or writer call).

## 8. Synthetic benchmark (`test_model_import_excel_migration_benchmark.py`, run with `-s`)
- Plan level: workbooks=13 (scenario columns xlsx/xlsm, selector + columns, selector-only, macro selector, hidden/external/named, formula-only inputs, P50/P90 sheets, period tables, 4 vertical European-format models), classified_items=119 (direct 54, structured 26, unsupported 22, formula 7, output 10), declared label checks=51, mismatches=0, safety violations=0 (no formula promoted, no output/structured/unresolved row applyable).
- Applied (solar, wind, data centre, EV charging): 5 canonical values exact after EUR→kEUR, European decimals and % normalisation; changed-not-run; manual Run; reconciliation with every precedent applied and attested gives a **real, large residual** (source toy Total CAPEX 1245.5005 kEUR vs FINCO 8250 / 14333.33 / 160000 / 28800 kEUR → status FAIL), which shows scope attestation does not create parity. Leaving one precedent unapplied gives NOT_COMPARABLE. Parity claimed: 0.
This is a regression guard on a small synthetic set, not a claim about arbitrary institutional workbooks.

## 9. Limitations
- Layouts: label/value/unit rows and one scenario column block per sheet. Several stacked blocks, wide time-series and matrices are not read.
- Block/sheet scenario *names* come from a fixed vocabulary; other names fall to unresolved.
- Dependency tracing is bounded (depth 12, 5000 cells, range ≤ 2000 cells) and static; named-range indirection is token-based.
- An applied scalar is not proven to drive the compared FINCO metric (e.g. total CAPEX also reflects the cost-line tables); attestation carries that burden and the residual is shown.
- A user can still manually re-map a row to another valid scalar field in review (existing V2 behaviour, recorded as `FIELD_REMAPPED`/user-reviewed).
- Manifest and applied-evidence tickets expire (6 h); nothing is persisted, so reconciliation after expiry means re-assess/re-apply.

## 10. Integrator notes (shared files touched)
`main_web.py`: one-line extension of the upload size gate to `/v2/workbook/import/assess`. `app/v2/import_router.py`, `import_review.html`, `intake.py`, `review.py`: additive. `tools/ci_browser_job.py` SELECTIONS were **not** changed (a test pins them); new browser file `tests/test_model_import_excel_migration_browser.py` should be added to the `import` selection by the integrator together with the pin test. No Workstream A governance or Workstream B credit files touched. The branch was developed on the session-designated `claude/upbeat-bell-4u1zgs`, not the suggested `feat/model-rc4-excel-migration-v3`.

## 11. Next requirements for fully automated migration
1. A single heterogeneous transaction (scalar + cost lines + revenue contracts + financing instruments, per-domain validators, row versions in the ticket) so structured data can be applied atomically.
2. An approved workbook-formula translation policy (or a deterministic recalculation oracle) for scenario selectors and derived inputs; macro-driven switches need the scenario results exported as plain values by the owner.
3. Period-table interpretation with calendar/indexation/currency conventions and an approved convention registry (replaces the user attestation).
4. Per-scenario transactional authority (multi-scenario import) and an approved retention policy if workbooks/manifests must persist.
5. A tested metric/dependency map from applied inputs to FINCO outputs so "applied" implies "drives".
6. Approved handling of circular/iterative calculation and external-data dependencies.
