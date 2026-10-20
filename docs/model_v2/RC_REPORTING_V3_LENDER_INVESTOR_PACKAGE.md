# Institutional Reporting V3 — lender & investor evidence package

Base: `origin/main` `5996453b8d5bbfaa48bc06922fc6963cf94d2f84`. Branch `feat/model-rc-reporting-v3`.
Scope: read-only presentation over committed Runs. No change to any financial engine, solver, Run writer, persistence schema, financial policy,
tolerance or golden.

## What V3 adds beyond V2

V2 (PR #316 / RC-7A) already provides `RunEvidence` (frozen persisted evidence), the V2 sheets (Periods, Sources & Uses, Construction funding, Debt/DSCR,
Reserves, Tax, Run Integrity, Disclosures), the statements/returns sheets of the self-contained historical package and
`build_historical_run_workbook_export` (service). V3 reuses all of it unchanged and adds:

| Addition | Where |
|---|---|
| `Report_Contents` — hyperlinked contents grouped A Overview, B Capital & funding, C Debt/reserves/tax, D Statements, E Evidence | `app/export/institutional_reporting_v3.py` |
| `Executive_Overview` — project/Run identity, state, period basis, Run Integrity, returns (IRR, XIRR, MOIC, NPV), capital, operating totals | same |
| `Lender_Overview` — senior sizing evidence, repayment profile, drawdowns by construction period (real dates), coverage, DSRA, financial maturity and terminal/settlement status | same |
| `Evidence_Limits` — every reported metric with exactly one evidence class, and what the report does not claim | same |
| Print/navigation polish — header/footer with Run id, state and digest, landscape fit-to-width, tab colours, "<< Contents" links | same |
| **Historical Run export route** `GET /v2/workbook/run-history/export?project=&history_id=` and a download link in the Run detail | `app/v2/router.py`, `run_history_detail.html` |

Wiring: the Last Run workbook (`institutional_workbook.py`) appends the V3 sheets after the V2 sheets over the **same** frozen evidence;
`build_historical_run_workbook_export` now builds `build_run_evidence_workbook_v3`. `write_reporting_v2_sheets` gained an optional
`sheet_names` argument so the Report_Guide announces the V3 sheets.

## Evidence classes (A4)

| Class | Meaning |
|---|---|
| `PERSISTED` | stored by the committed Run and written unchanged |
| `PRESENTATION_ARITHMETIC` | a sum, maximum or ratio of persisted values computed only to present them; the persisted figure is shown beside it |
| `NOT_AVAILABLE` | not persisted for this Run: shown as `n/a`, never zero, never rebuilt |
| `OBSERVATIONAL_CHECK` | comparison of persisted values with a stated tolerance; changes no figure |
| `CONTRACTUAL_ASSESSMENT_NOT_AVAILABLE` | needs contractual terms (covenants, thresholds, default events) not held with the Run |

The register is generated from the same rows the sheets write, so it cannot drift from what is shown. Covenant compliance is `NOT DECLARED`; no
investment recommendation is expressed.

## Historical export behaviour (A2)

* Selection by the real committed `history_id`; the project is resolved through `resolve_accessible_project` for the authenticated user, and the
  service re-checks owner, project and ids (unknown or foreign id -> 404, missing -> 400, malformed stored row -> 422; hostile ids never reflected;
  unauthenticated -> redirect to `/login`).
* The package is built only from that Run History row: no Working Copy, no newer Last Run, no engine. Equal evidence gives byte-identical output.
* Fields unavailable in historical snapshots are disclosed: Run History persists results and identity, not the input snapshot, so input-assumption
  sheets are not produced and nothing is back-filled.
* A newer Run or a Working Copy edit changes only the disclosed Run state (CURRENT -> HISTORICAL); every number and the evidence digest stay identical.

## Guarantees

* No import of `financial_engine`, `finco_core`, `domain`, the Run writer or persistence from the V3 module (AST-checked).
* Persisted Run records and fingerprints are untouched by reporting (hash-checked in tests).
* Period labels use persisted dates; a 6-month Run is never labelled quarterly (the V2 period-basis authority is reused).

## Tests

`tests/test_rc_reporting_v3.py` (real committed Solar, Wind, EV and Data Center Runs) plus the unchanged V2 acceptance suite
(`test_rc7_institutional_reporting_v2.py`, `test_rc7a_cross_stream_acceptance.py`) and the Credit Decision V4 regressions.
