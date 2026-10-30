# ON-07 Unverified Assumptions - REVISED COPY (Correction A, main db504f6, 2026-10-30)
Labels: CONFIRMED / CHANGED_SINCE_ON07 / NOT_REPRODUCED / NOT_TESTED. The ORIGINAL text follows unchanged below the table; rows here supersede it.
| ID | Status | Evidence (executed unless noted) |
|---|---|---|
| U-01..U-04 competitor | unchanged (BLOCKED) | no access attempted |
| U-05 contractual DSCR/covenant | **CHANGED_SINCE_ON07**: #399 merged; inputs exist; fixtures carry none (NOT_CONFIGURED) | WF04 evaluator on sealed evidence |
| U-06 #400 unmerged | CONFIRMED (Draft, head 25f2cda2 at 08:38Z) | GitHub |
| U-07 v1 API `revenue.degradation_pct` dropped | **CONFIRMED - scope: v1 API only** (`/api/v1/run`, `build_projectinputs`). NOT_TESTED for React/Legacy grid: the workbook registry has no degradation field at all, so the statement "dropped" does not apply there (no entry point) | prior bundle probes |
| U-08 v1 `opex.inflation_pct` dropped | **CONFIRMED - v1 API only.** On the user route OPEX inflation is a per-line value (`inflation_pct` on cost lines, seeded 2.0) and IS consumed (`opex_items_after_fold[].infl`) | prior probes; ledger |
| U-09 P90/P99 derived from P50 | **CONFIRMED and EXTENDED to the user route** (`p90_probe.json`): P90=0.9xP50, P99=0.8xP50 always; the seeded P90 1400 is ignored; no registry field exists. Fixture P90 values equal 0.9xP50 in all four fixtures (so they "match" but are not independently entered). Supplied P90 / remaining P99 policy: recorded in the ledger as MATCH_DERIVED_NOT_SETTABLE | `p90_probe.json` |
| U-10 currency display-only | CONFIRMED (binding PARTIAL; not entered) | registry |
| U-11 seasonality | PARTIALLY_REPRODUCED (candidate OPEX module mentions it; no production input) | grep |
| U-12 working-capital/dividend | CONFIRMED | grep |
| U-13 CAPEX composition from total | **CHANGED/CORRECTED**: totals are derived from lines; the Run's category fold replaces snapshot totals. Fixture CAPEX/OPEX are expressible only as cost lines (allocation rule OD-2) | `TRUE_ROUTE_INPUT_LEDGER.csv`, prior route-vs-totals finding |
| U-14 examples unused | unchanged | |
| NEW U-15 reference-seeded SHL indices not re-derived | **CONFIRMED** | `WND02_SHL_MATURITY_FORENSICS.md` |
| NEW U-16 WND-02 SHL repayability | **CONFIRMED** (economic infeasibility; boundaries recorded) | levers |
| NEW U-17 gearing is a ceiling | **CONFIRMED**: executed 66.37% / 64.07% / 72.00% / 50.07% vs ceilings 70 / 85 / 72 / 88 | runs table |
| NEW U-18 NPV/LLCR/PLCR NOT_CONFIGURED | **CONFIRMED** (valuation policy and coverage CFADS case absent) | exposure register |
---
## ORIGINAL TEXT (superseded where marked above)
# ON-07 — Unverified Assumptions & Blockers Register

**Repo baseline:** `Finco-Protocol/FincoProtocol` `main` @ `8a74fcb5cd57e470cf83a458bd165ea14ad394fb`
(2026-10-30). Everything below is explicitly NOT verified, NOT runnable, or a fixture-author choice —
listed so nothing silently hardens into a "fact". No numeric engine outputs, competitor capabilities,
credentials, or test results appear anywhere in the ON07 package.

## 1. Competitor (finmodels.io) — total blocker

| ID | Item | Status | Consequence |
|---|---|---|---|
| U-01 | Every finmodels.io field mapping | **UNVERIFIED** — the repository contains ZERO finmodels.io comparison material; all 5 in-repo mentions are explicit unavailability disclaimers (`app/model_quality/registry.py:6`; `docs/model_v2/MODEL_QUALITY_Q1_REPORT.md:72,106`; `docs/model_v2_financing_bankability_workflow_b.md:14`; `docs/model_v2/financing_f3/F3_ARCHITECTURE_BLUEPRINT.md:11`) | All `ON07_FIELD_MAPPING.csv` competitor columns default to `UNVERIFIED` with empty field names; FINCO-vs-competitor comparisons are `NOT_RUN` |
| U-02 | Competitor tolerance conventions | UNVERIFIED | `ON07_OUTPUT_COMPARISON_TEMPLATE.csv` competitor tolerance cells intentionally unset |
| U-03 | Competitor support for PPA share / merchant curves / indexation policies / DSCR-sculpted sizing / SHL constructs / ATAD tax mechanics / semestrial axis | UNVERIFIED | Any unsupported FINCO feature must surface as `MISSING_FEATURE`, never be silently dropped on the competitor side |
| U-04 | Authorized competitor access | NOT SUPPLIED | `ON07_RUNBOOK.md` §2 cannot start; no authentication is attempted by this package |

## 2. PR-coupled items (verified unmerged; not assumed)

| ID | Item | Status |
|---|---|---|
| U-05 | Contractual DSCR inputs + Run-bound Minimum DSCR/covenant evaluation | PR #399 OPEN (head `71e3958127…`). WND-02 covenant rows are `NOT_RUN` on `main`; the only covenant-adjacent behaviour on `main` is the distribution lockup at engine-default `lockup_dscr=1.10` (not user-editable) |
| U-06 | Guarded Archive/Restore, explicit setup drafts | PR #400 OPEN (head `21d3ad8f…`). Archive columns in the gap checklist are record-only; no Archive behaviour is assumed |

## 3. Engine defaults inside the fixtures (recorded, never harmonized)

These are left at engine/factory values by design and MUST NOT be read as harmonized parity inputs:
solar degradation 0.004/yr and wind 0.0 (`finco_core/inputs/_models.py:533` + factories); plant/grid
availability 0.99/0.99 (`_models.py:538-539`); P99 fallback p50×0.8 (`app/input_adapter.py:760`);
OPEX single-line inflation hardcoded 2.0% (`app/input_adapter.py:973`); lockup DSCR 1.10 and min LLCR
1.15 (`_models.py:922-923`); DSRA 6 months FIXED_AMOUNT, support mode NONE (`_models.py:927-950`);
share capital 500 kEUR with G2A-derived SHL; CIT 25%, LCF 5y, ATAD 0.30/3,000 kEUR
(`app/project_factories.py:168-170`); factory CAPEX line composition and spending profiles under a
supplied total; the 30-point factory merchant curve (present but pricing no volume in the 100%-PPA
fixtures).

## 4. Silent-drop / hidden-default findings verified on `main` (input-mismatch class)

| ID | Finding | Evidence |
|---|---|---|
| U-07 | v1 API `revenue.degradation_pct` is accepted, validated, used in `examples/custom_solar.json` — and silently dropped (never mapped; setter never called) | `app/input_schema.py:26`; `app/api/router.py:62-64`; `app/input_adapter.py:118-119` (defined, zero callers); `app/input_adapter.py` `_schema_to_dict` (no mapping) |
| U-08 | v1 API `opex.inflation_pct` accepted — silently dropped; single-line path hardcodes 2.0% | `app/input_schema.py:38`; `app/input_adapter.py:973` |
| U-09 | v1 capacity/P50 override silently re-derives P90=p50×0.9, P99=p50×0.8 unless explicitly supplied | `app/input_adapter.py:759-760` |
| U-10 | `currency` input is a display label only (binding PARTIAL); engine is EUR-internal | `app/workbook/registry.py:151-158` |
| U-11 | No seasonality input exists anywhere in the engine | repo-wide search: only a DSRA comment mentions seasonal behaviour |
| U-12 | No working-capital or dividend-policy inputs exist | grep `working_capital|dividend_policy|payout` over inputs: zero matches |
| U-13 | CAPEX composition is engine-derived when only a total is supplied (EPC line rescaled) | resolver step 5 (`app/input_adapter.py`) |
| U-14 | `examples/custom_*.json` are unused v1-API payload samples, not parity fixtures | no repo references; agent-verified git history (initial sanitized import only) |

## 5. Fixture-author choices (arbitrary by design; not engine facts)

All `intended_value` cells in `ON07_PROJECT_FIXTURES.csv` with `source_class=EXPLICIT` are fixture
design values chosen for economic distinctness inside verified validation ranges: capacities 40–80 MW,
P50 1,450–3,300 h/yr, tariffs 55–64 EUR/MWh, merchant curves 52.00/45.00 EUR/MWh at 2%/yr (rounded to
2dp per year — the rounding is a fixture-author choice), CAPEX 45,600–62,400 kEUR, OPEX 760–1,300
kEUR/yr, gearing 70–88%, rates 5.25–6.75%, tenors 12–18 y, target DSCR 1.25–1.35. They imply no
performance claim and no expected result values. WND-01's "stronger seasonal generation" is expressed
as P50=3,300 h/yr because seasonality is not supported (U-11).

## 6. Method-level caveats

- Exact tolerance constants (1e-6 kEUR / 1e-7 ratio / 1e-9 XIRR / 0.5 MWh / 0.01 pp goal-seek) were
  transcribed from `tools/numerical_validation/identities.py:29-52`, which itself cites FINCO internal
  authorities; whether the same ladder applies to a future competitor comparison is UNVERIFIED (U-02).
- The React-vs-Legacy acceptance baseline `docs/react_migration/ux00_legacy_baseline_manifest.md`
  (legacy HEAD `b28a0572`, 2026-10-21) predates merged PR #397; the runbook requires re-confirming the
  operative baseline at execution time.
- `ON07_REACT_LEGACY_GAP_CHECKLIST.md` expected-behaviour cells describe verified `main` source
  behaviour; they are expectations to test, not observations.
- Legacy UI label strings for some workbook fields may differ cosmetically between surfaces; the
  registry labels cited in the mapping are the canonical ones — any mismatch found during execution is
  a gap-register row, not a fixture error.

## 7. Confidentiality

No user credentials, session tokens, CSRF tokens, or account identifiers are stored in this package.
All fixture identities are synthetic (`ON07-*`, countries XA/XB, sponsor names avoided). Test accounts
for the later acceptance are created by the owner out-of-band and never recorded in ON07 artifacts.
