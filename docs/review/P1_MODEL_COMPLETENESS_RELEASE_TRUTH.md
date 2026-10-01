# P1 Institutional Model Completeness & Release Truth — Dossier

Master stream: PR #155 (`feat/p1-model-completeness-release-truth`).
Initial live main: `cf65370f6fb46fc8a3facae5b9f34077b36651b8` (post-#151/#152).

## 1–3. Baseline, final main, changed files

Recorded at finalization (see PR merge block). Primary changed files:
`app/services/sensitivity_service.py`, `app/export/institutional_workbook.py`,
`app/export/clean_statements_adapter.py` (new), `app/v2/router.py` (DC
sensitivity endpoint pre-existing), `app/templates/protocol_docs.html`,
`app/templates/protocol/finco.html`, `app/templates/v2/partials/sheet_revenue.html`
(no change this stream), `app/output_tables.py`, `app/excel_export.py`,
`docs/trust/FINCO_WORKED_SOLAR_RECONCILIATION.md`,
`docs/review/P1_INSTITUTIONAL_TRUST_PACK.md`, tests
(`test_p1_dc_sensitivity_semantics.py`, `test_p1_xlsx_statement_binding.py`,
`test_p1_release_truth.py`).

## 4–7. DC sensitivity authority map

Capability registry: `_VERTICAL_SENSITIVITY_DRIVERS` in
`app/services/sensitivity_service.py` — one driver key → one exact canonical
input path in `_apply_shock`.

Supported DC drivers (each maps to an exact existing input):

| Driver | Canonical input path |
|---|---|
| dc_service_price | revenue.market_prices_curve + revenue.ppa_base_tariff (DC runtime adapter carries service price on both) |
| dc_occupancy | revenue.market_prices_curve (occupancy rides the curve in the DC runtime adapter) |
| dc_pue | opex "Power Expenses" y1 + step schedule (linear in PUE per canonical identity) |
| dc_electricity_price | opex "Power Expenses" y1 + step schedule (linear in price) |
| capex / opex | CapexStructure / OpexItem tuples |
| interest_rate / tax_rate | financing.base_rate / tax.corporate_rate |

Forbidden DC drivers (renewable-only): `ppa_price`, `merchant_price`, `yield`.
`assert_driver_supported` raises `UnsupportedSensitivityDriverError` before
any model execution; `run_sensitivity(vertical=...)` enforces this on the full
shock list.

Solar/Wind/EV driver sets unchanged (renewable set retained, including EV
availability/yield). Bounded evaluation: base + len(shocks) runs; no fanout;
MODEL_EXECUTION_BUSY semantics preserved (bounded infrastructure from #152).

Base outputs: Data Center canonical identities unchanged (stabilized core
capacity revenue 35,700 kEUR asserted); Solar/Wind/EV reference behavior
asserted unchanged per driver.

## 8–10. XLSX statement binding

- `app/export/clean_statements_adapter.py` — identity-preserving serialization
  view over the clean runtime's own `financial_statements_result` (same ONE
  G2C calculation). Verbatim field mapping only; banned-token test proves no
  arithmetic/balancing tokens.
- `_build_export_bundle` binds the adapter output for the clean path; the
  legacy assembly path remains only for blocked/legacy projects.
- Same-run identity rows (bound run id + snapshot id) stamped on Tax / P&L /
  PF Cash Flow / Balance Sheet sheets.
- Balance reconciliation = runtime's own `balance_check_keur` (max residual
  < 1e-6 asserted). Same-run provenance BY CONSTRUCTION (the bundle serializes the clean
  execution object itself); independent source-package provenance digest
  NOT_AVAILABLE in V1 (no self-stamped identity claim).
- Legacy aggregates the clean runtime does not publish (total assets,
  total liabilities+equity, net fixed assets, net dividends) → None → typed
  NOT_AVAILABLE rows (missing != 0).
- Deterministic output: two builds of the same reference produce identical
  P&L and balance-check series.
- Status: **XLSX_STATEMENT_VALUE_TRACE = PASS**;
  **XLSX_STATEMENT_RUN_BINDING = BY_CONSTRUCTION**;
  **XLSX_CROSS_RUN_SOURCE_PROVENANCE = NOT_AVAILABLE** (typed
  NOT_AVAILABLE rows remain only for unpublished quantities).

## 11. Terminology corrections (H-3 residual)

- `app/services/sensitivity_service.py` KPI_DEFS: "Equity IRR" →
  "Equity IRR (share capital only)" with an explicit H-3 comment.
- `app/output_tables.py` labels + `app/excel_export.py` KPI row: same truthful
  label. v2 KPI catalog already used "Pure Equity IRR" / "Total Sponsor IRR".
- Machine field names (`equity_irr`, `sponsor_irr`) unchanged — API
  compatibility preserved.

## 12. Token / metering truth

`/protocol/finco` now states `PRODUCTION_TOKEN_METERING = NOT_SHIPPED` — the
B2.3 usage ledger exists; no proven scarce production resource is metered and
enforced today. README already carries the same distinction.

## 13. Early repayment truth

Documented in `/docs` Status → Known limitations (debt repayment semantics):
mandatory cash sweep SUPPORTED; terminal balloon PARTIAL (policy flag, no
standalone balloon structure); voluntary early repayment / refinancing /
prepayment penalty / debt acceleration NOT_SUPPORTED. Engine source scan:
no voluntary-prepayment module exists. Generic debt-schedule functionality
does not imply these structures.

## 14. Supported Today matrix

See `docs/review/PRODUCT_TRUTH_RELEASE_MATRIX.md` (kept current by the
Product Truth stream) plus this dossier's deltas: DC vertical-specific
sensitivity semantics; XLSX statement value trace PASS; early-repayment
limitations. PR #153 (Radar instant snapshot) remains OPEN/DRAFT — **not**
described as shipped anywhere.

## 15. Known Limitations

- Voluntary early repayment / refinancing / prepayment penalty / debt
  acceleration: NOT_SUPPORTED (documented).
- Balance-sheet legacy aggregate totals: typed NOT_AVAILABLE on the clean
  path (runtime publishes components + balance check, not totals).
- XLSX adapter exposes clean-runtime fields verbatim; unpublished legacy
  fields are None.

## 16. Frozen-namespace proof

Contract-tested ZERO diff vs origin/main: `financial_engine/`,
`finco_core/`, `finco_radar/`, `app/model_validation/`, `app/verified/`
(see each test module's TestFrozenAuthorities).

## 17. Tests

- `tests/test_p1_dc_sensitivity_semantics.py` (17) — capability registry,
  forbidden drivers, fail-closed-before-execution (spy), exact shock→input
  mappings, bounded evaluation, Solar/Wind/EV unchanged.
- `tests/test_p1_xlsx_statement_binding.py` (10) — adapter binding, verbatim
  fields, typed NOT_AVAILABLE, runtime balance reconciliation, same-run
  identity, no-arithmetic/no-plug source scans, determinism.
- `tests/test_p1_release_truth.py` (13) — JEV/Yield default OFF, Verify
  count truth, metering wording, Signed Run ≠ Verify, Reference Regression
  naming, early-repayment Known Limitation, #153-not-shipped guard.

## 18. Exact-head CI

Recorded on the final candidate (see PR checks).

## 19. Deferred items

- Engine performance (own profiled stream).
- All-equity/zero-debt redesign; new debt structures; prepayment economics.
- Production Model↔Market → Verify activation.
- Multitenancy/RBAC; production token metering; JEV intelligence expansion;
  Yield execution expansion.
- PR #153 Radar snapshot UX: Product Truth update lands in a later pass once
  #153 merges (Section F of the master stream is WAITING, not guessed).
