# WF-04 — Independent oracle and true before/after parity

Basis: **before** = clean `main` `b76ac65c99e7fc9b486a557ae3c5ba9a711f50b3`; **after** = this branch. Same machine, same Python 3.13 environment, canonical Python engine in thread mode
(`FINCO_MODEL_EXECUTION_MODE=thread`). Synthetic inputs only (the shipped reference templates and the seeded Wind working copy). The native V10/V11 arms were **not run**
(`runtime_compilation_authorized: false`).

## 1 — What was compared and the result

| # | Comparison | Method | Result |
|---|---|---|---|
| P1 | Engine output at identical effective inputs, 11 named cases (default Wind 25 MW; Wind 25 MW `GEARING_CAP` at 0.50 / 0.55 / 0.575 / 0.58 / 0.65 / 0.75; the four shipped reference templates) | one script, run once per source tree, writing one JSON line per case (Integrity overall + every check status, Senior debt, minimum base and bank DSCR, shortfall count, minimum balances, **evidence digest**, financing fingerprint) | **byte-identical files** (`cmp` exit 0, 11/11 lines) |
| P2 | Persisted Run blobs of **committed** Runs through the real app (4 technologies at default + the weak-coverage Wind project: seeded Wind at 85 % gearing under `GEARING_CAP`) | commit one Run per project in each tree, dump `financial_statements`, `debt_schedule`, `tax_schedule`, `distribution_schedule`, `sponsor_schedule`, `integrity_evidence` | **all 30 blobs raw-identical** (not merely normalised) — including the sealed Integrity-evidence digest |
| P3 | The identity wrapper of the same Runs | key-by-key diff after removing per-project random ids (project / snapshot / sub-line UUIDs and their sort order) | the **only** differences: (a) `last_runtime_identity.dscr_contract_terms` is **added**; (b) `composite_hash` differs and (c) the two derived values that embed it (`acquisition_source_candidate_v1.binding.composite_hash` + its digest, `financing_evidence.run_binding.composite_hash`) — all explained below |
| P4 | A Run committed on **main**, opened under this branch (upgrade path) | commit a Run in a `main` database, copy the database, read it with this tree | Last Run stays **`CURRENT`**; the page open adds no snapshot key; the old Run reads `NOT_RECORDED` → EoD/covenant `UNAVAILABLE`, coverage still computed from its sealed evidence |
| P5 | Existing Integrity checks on the adversarial evidence set (control, DSCR < 1 with unfunded cash and a negative distribution account, DSCR-evidence missing, no Senior periods, interest +5 kEUR, negative stored balance −50 kEUR, terminal balance not repaid, sources ≠ uses) | the phase-1 replay script run against this tree | verdicts **identical** to the ones recorded on `main` for all 9 cases (e.g. the negative distribution account still gives `FAIL` with `NO_UNFUNDED_CASH_DEFICIT: NEGATIVE_CASH_WITHOUT_FUNDING_SOURCE`) |
| P6 | Terms feed no calculation | same project run with and without both terms configured | `runtime_summary`, statements, debt, tax, distribution, sponsor schedules and the Integrity digest equal (`test_wf04_run_bound_terms::test_configured_terms_change_no_financial_result`) |

### Explanation of the identity difference (P3)

The composite workbook hash is computed over the draft snapshot, the CAPEX/OPEX rows and the scenario, with the project's own random row identifiers; it therefore differs between any two
projects and was never comparable across trees. What matters is **upgrade behaviour** (P4): an existing project's snapshot contains neither new key, no code path adds an empty key on page
open, and the composite hash of an unchanged draft is unchanged, so no existing Last Run turns `STALE` by deploying this change. The hash changes **only** when a user saves one of the two
inputs — which is the intended input-identity semantics (a Last Run recorded before the edit becomes `STALE`).

No financial number, period vector, schedule, statement or Integrity digest changed. No signature input was changed: the signed-certificate modules are not in the diff, and old Runs, old
snapshots and old signatures stay valid because the new identity key is additive and absent from them.

## 2 — Reference numbers (identical before and after)

| Case | Committed | Integrity overall | Senior debt (kEUR) | Min base DSCR | Min bank DSCR |
|---|---|---|---|---|---|
| Wind 25 MW, shipped FLAT default | yes | PASS | 28,399.34 | 1.29838 | 1.2000 |
| Wind 25 MW, `GEARING_CAP` 0.50 | **refused** (`SHL_MATURITY_RESIDUAL_FAILS_CLOSED`, residual 10,594.21 kEUR) | – | – | – | – |
| `GEARING_CAP` 0.55 | **refused** (residual 1,896.90 kEUR) | – | – | – | – |
| `GEARING_CAP` 0.575 | **refused** (residual 242.67 kEUR) | – | – | – | – |
| `GEARING_CAP` 0.58 | yes | FAIL | 26,894.66 | 1.00074 | 0.88385 |
| `GEARING_CAP` 0.65 | yes | FAIL | 30,432.11 | 0.88442 | 0.78111 |
| `GEARING_CAP` 0.75 | yes | FAIL | 35,606.00 | 0.75590 | 0.66761 |
| Reference solar / wind / data-centre / EV (shipped FLAT) | yes | PASS | 26,983.33 / 36,505.16 / 58,410.96 / 6,477.35 | 1.2486 / 1.2800 / 1.3000 / 1.3000 | 1.2000 / 1.2000 / 1.3000 / 1.3000 |

The low-gearing refusal band (0.50–0.575) is **unchanged**: same refusal code, same residuals. Nothing was suppressed, resized or re-run in a shadow mode (D-C, POC-IV remains NO-GO).
The `FAIL` Integrity results at `GEARING_CAP` ≥ 0.58 are the existing, untouched checks (DSCR-sculpting feasibility, unfunded cash) — they are displayed next to, and never merged with,
the new Credit-axis observations.

## 3 — The independent oracle (`tools/wf04_independent_dscr_oracle.py`)

Python standard library only (`decimal`, `math`; `test_the_oracle_is_standard_library_only` enforces it). It imports nothing from FINCO: no engine function, tolerance, formatter or
verdict is reused. It re-derives, from the **sealed Senior-debt period evidence** and the two saved term texts:

* which periods are under test (scheduled service > 1e-6 kEUR),
* the achieved minimum DSCR and its period,
* EoD condition, covenant, coverage (< 1.00x) with the exact breaching periods,
* a recomputation cross-check (stored ratio = base CFADS ÷ scheduled debt service, max deviation < 1e-9).

All comparisons use the **exact value of the stored double** (`Decimal(float)` is exact) with strict `<` and no tolerance. The product and the oracle were compared on **real committed
Runs** (`tests/test_wf04_independent_oracle.py`):

| Threshold set (EoD, Contractual) on the weak-coverage Run (raw minimum 0.9925114505766469) | Product = Oracle |
|---|---|
| none configured | `NOT_CONFIGURED` / `NOT_CONFIGURED`; coverage `DEFICIENCY` |
| 1.05 / 1.2 | `TRIGGERED` / `BREACHED`, same breaching periods |
| exactly the measured minimum (full-precision text) | `NOT_TRIGGERED_UNDER_THIS_FLOOR` (equality is no trigger) |
| one ulp **above** the measured minimum | `TRIGGERED` (raw value fractionally below; 2-decimal display would read equal) |
| one ulp below | `NOT_TRIGGERED_UNDER_THIS_FLOOR` |
| 0.5 / 0.9 | not triggered / compliant for the EoD floor; coverage still `DEFICIENCY` |
| 9.5 / 10 (upper bound) | `TRIGGERED` / `BREACHED` |
| four technologies at 1.35 / 1.45 | statuses and breaching-period lists equal for solar, wind, data centre, EV charging |

## 4 — Raw versus display

* Decisions use the persisted raw double. Display uses `format_ratio`, which prints the fewest digits at which the displayed value is distinguishable from every reference it is shown next to
  (1.00x, the term, the sizing target): `0.9951` prints `0.9951x`, never `1.00x`; a value one ulp from a threshold prints enough digits to differ from it; an exactly equal value prints equal.
* Presentation precision (0 → 2 → 0 decimals) lives only in the browser. The server payload is a pure function of the sealed Run: three consecutive reads are byte-identical and the Run's
  Integrity digest and identity do not move (`test_the_projection_is_a_pure_function_of_the_sealed_run…`).
* The Debt Metrics CSV export carries the raw persisted values, not the display strings.

## 5 — Evidence a Run does not carry (stays `UNAVAILABLE`, listed on screen and in the payload)

| Conclusion | Missing evidence |
|---|---|
| Reserve draw covering a shortfall | DSRA draw per period; required DSRA amount per period; standby reserve facility (DSRF) commitment and drawings |
| Unpaid scheduled Senior debt service | debt service actually paid per period (payment ledger); cash applied to debt service after reserves, per period |
| Per-period LLCR / PLCR | only the aggregate minimum is persisted |
| Lock-up threshold value | only the per-period lock-up flag is persisted |
| Legal testing convention of a facility agreement | not supplied; no input exists to configure it (model convention is disclosed with every verdict) |

## 6 — Not run

Native V10/V11 arms; the 183-case catalogue; end-to-end combined Save All + Debt Metrics browser acceptance (requires #397 merged); signed-certificate regeneration; production or staging data.
