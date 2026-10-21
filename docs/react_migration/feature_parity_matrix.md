# FINCO Model — React migration feature-parity framework (initial matrix)

States per row (each must be earned separately — **a screen being visually
complete never counts as production functionality**):

- **D** — Designed in Replit (design exists; no code in this repo).
- **R** — React component integrated in this repo.
- **B** — Real canonical backend connected (existing authorities only).
- **P** — Functional parity tested against the legacy acceptance reference.
- **F** — Financial/output authority verified (values provably from persisted
  canonical evidence; no browser calculation).
- **S** — Staging accepted (requires the UX-00 staging baseline, currently PENDING).

| Legacy workflow | Canonical authority | React component | Integration state | Test evidence |
|---|---|---|---|---|
| App shell / Model navigation | `/v2/workbook` shell, hybrid nav groups | `App.tsx` shell (PoC scope, no primary nav replacement) | R (PoC slice) | `tests/test_model_react_poc_v1.py`; browser acceptance shell checks |
| Tax input editing (CIT rate) | `tax.assumptions.cit_rate_pct` registry field; `POST /v2/workbook/grid/save`; `resolve_runtime_freshness` | `CitRateField.tsx` | R+B+P+F (PoC slice) | save/invalid/stale/no-auto-run tests; browser save + STALE banner |
| Profit & Loss statement | `PostRunRequestContext` + `statement_presentation` over persisted RuntimeResult | `PnlStatement.tsx` | R+B+P+F (PoC slice) | persisted-parity + unavailable≠zero tests; browser statement render |
| Project setup inputs | grid save (scalar C0 writer) | — | D (Replit) | — |
| Revenue / PPA inputs | `revenue.*` registry fields + revenue contracts/stress routes | — | D (Replit) | — |
| CAPEX line editing | row-versioned CAPEX repository + `cost-lines/save` atomic writer | — | D (Replit) | legacy regression: `test_cost_batch_save_v1.py`, `test_cost_batch_save_browser_v1.py` |
| OPEX line editing | row-versioned OPEX repository + `cost-lines/save` atomic writer | — | D (Replit) | legacy regression: cost-batch suites |
| Financing (senior debt, F1–F4) | financing editors, F3 candidate authority, financing trace | — | D (Replit) | legacy suites unchanged |
| Scenarios & overrides | scenario authority + override authority | — | D (Replit) | — |
| Run execution | `POST /v2/workbook/run` (server-only) | none — deferred (thin outcome adapter required) | B (authority documented) | no-auto-run pinned by tests |
| Statements & Debt workspace | outputs projection, balance/cash/returns tables | P&L only (PoC) | R+B for P&L; D for the rest | P&L parity tests |
| Run history & drill-downs | run history repository + historical statements | — | D (Replit) | — |
| Diagnostics & quality | diagnostics projections | — | D (Replit) | — |
| Trust / integrity surfaces | trust readiness + run integrity evidence | status badges only (PoC slice) | R+B (badges); D for full Trust | status-dimension independence tests |
| Import (Excel migration) | import workflow C gate | — | D (Replit) | — |
| Exports (XLSX) | export services | — | D (Replit) | — |
| Protected references / Library | reference seed service, read-only gate | read-only field state (PoC) | R+B (PoC slice) | protected-reference read-only tests |
