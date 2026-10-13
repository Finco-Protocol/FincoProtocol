# WF-06 — Professional Statements + Debt Workspace V1

Read-only output workspace over the **persisted Last Run**. Route: `GET /v2/workbook/outputs?project=…`
(lazy tab *Statements & Debt* under Outputs; nothing is fetched until the tab is opened).

## Authority
* Source: `RuntimeResult.financial_statements` (P&L, balance sheet, PF cash waterfall), `debt_schedule`,
  `distribution_schedule`, `sponsor_schedule`, `runtime_summary.financing_evidence` (F3 facility schedules), and the
  canonical Run Integrity report. One coherent `PostRunRequestContext` snapshot per request.
* Never runs the engine, recomputes a statement line, creates/modifies an input, or writes. A value the Run did not
  persist is rendered "—" / "not available" (and announced to screen readers) — never as zero. A row unavailable in
  every period is also disclosed in words.
* Freshness is the canonical `RuntimeFreshness`: CURRENT / STALE / NOT_RUN. STALE names the prior Run (timestamp,
  snapshot, scenario). Run Integrity is a separate badge: CURRENT can coexist with Integrity FAIL.
* Reconciliation indicator (RECONCILED / BREAK / UNVERIFIED) compares persisted numbers only: the Run's balance-check
  row (±1 kEUR) and, for F3 Runs, Σ facility debt service against the PF waterfall's Senior service (0.01 kEUR).

## Sections
P&L · Balance Sheet · Cash Flow (PF waterfall — not an indirect-method CFS) · CFADS (`fcf_banks_keur`, DSCR/DSRA from
the debt schedule only where persisted dates match) · Debt schedules (F3: Senior A/B separately with commitment,
construction draws/IDC/upfront and commitment fees, operating opening/interest/principal/service/closing, maturity
date and unpaid obligation after the final scheduled period; legacy Runs: one aggregate Senior schedule, per-facility
terms/fees/opening balance labelled not exposed) · Sponsor distributions & Returns (existing returns projection).

## Toolbar (formatting only)
kEUR/EUR (×1000 of the raw `data-raw`), 0–3 decimals, show/hide Year 0 (period index 0), sticky line-item labels,
per-period columns, Run identity/timestamp, status badges. Preferences live in `localStorage` (optional).

## Verification
`tests/test_model_outputs_workspace.py` (numeric reconciliation to Run evidence, XLSX parity, accessibility contract,
read-only/no-engine, STALE/NOT_RUN/Integrity-FAIL) and `tests/model_outputs_workspace_acceptance.py` (Chromium,
real server; screenshots are CI artifacts, never committed).
