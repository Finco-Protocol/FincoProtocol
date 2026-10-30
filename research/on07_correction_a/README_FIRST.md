> **Status update (later on 2026-10-30):** PR heads below are snapshots (#400 has since moved to `e66b7346...`). Merge status of PR #403 is governed by `SOURCE_GOVERNANCE_DECISION.md` (`BLOCKED_SOURCE_GOVERNANCE`: any added path fails the closed-world exact-source guards). Inputs/re-run: `INPUTS_AND_PROVENANCE.md`.

# FINCO ON-07 Correction A - true-route fixture materialisation + WND-02 SHL forensics
## VERDICT: **PARTIAL** (`BASELINE_READY_FOR_POST400_LIVE_ACCEPTANCE` is NOT claimed)
Why: (1) the original WND-02 does not run and its runnable replacement WND-02-R is **not yet owner-accepted** and does not preserve the high-executed-leverage stress; (2) no `COMMITTED_RUN` and no `LIVE_UI_PARITY` evidence exists; (3) NPV/LLCR/PLCR are NOT_CONFIGURED; (4) P90/P99 are derived, not enterable; (5) the cost-line allocation rule (OD-2) is mine, not the fixture author's. What IS established: SOL-01, SOL-02, WND-01 materialise as intended on the user-created route (every compared input MATCH), run, satisfy the independent identities and the ON-05 oracle, and reproduce across 3 fresh databases.

## 1. Preflight (GitHub, 2026-10-30, last read ~08:40Z)
| Ref | Value |
|---|---|
| main | `db504f6408cb456c617c9342a1ffa202ee455283` (unchanged all session; `git ls-remote` re-checked at the end) |
| #400 | OPEN **Draft**, head **`25f2cda20b0366dbeb5f6c00b10944ca97400446`**, base db504f6, `mergeable_state: unstable`, 56 files. It moved four times today (`21d3ad8f` -> `731bde2f` -> `0a30c052` -> `25f2cda2`); the handover's `731bde2f` is stale. Not touched. |
| #402 | OPEN Draft, head `9e776252086a28e8bd295c155903cc07b221784b`, BLOCKED_EXACT_SCOPE (FIN-TRUTH-A). Not touched, not assumed present. |
Isolation: throwaway venv, one temp SQLite DB per process (`FINCO_DB_PATH`), no network, no HTTP app, no repo file edited, no PR/CI/staging/production/competitor access, no credentials. ON-05 pack and ON-07 package were read as data; the ON-05 oracle (stdlib only) was read before import.

## 2. Evidence classes - never mixed
| Class | Meaning | Present? |
|---|---|---|
| `SYNTHETIC_VARIANT_B` | prior study: totals injected in memory | yes, diagnostic control only (`captures/synthetic_variant_b_prior`) |
| `USER_CREATED_CORE_RUN` | real `create_reference_seeded_project` + real atomic `save_all` (cells one at a time, cost lines in one batch) + Run-route steps 7-10 + `run_project` | **yes (this study)** |
| `COMMITTED_RUN` | persisted Run: history_id, composite_hash, engine_version | **no** (HTTP/auth/CSRF/run-intent/executor/`v2_atomic_run_commit` bypassed) |
| `LIVE_UI_PARITY` | browser observation on deployed staging | **no** |

## 3. Results (USER_CREATED_CORE_RUN; input ceiling and executed gearing kept separate)
| Fixture | Input gearing ceiling | Executed gearing | CAPEX kEUR | Senior kEUR | Min DSCR | Avg DSCR | Equity IRR (share-cap) | Total Sponsor XIRR | Project IRR | Lock-up | Digest (3 DBs identical) |
|---|---|---|---|---|---|---|---|---|---|---|---|
| SOL-01 | 70% | 66.37% | 45,600.0 | 32,292.2 | 1.301523 | 1.402244 | 22.93% | 9.8737% | 7.4121% | 0 | `4e33b963bffa9940` |
| SOL-02 | 85% | 64.07% | 57,600.0 | 39,761.0 | 1.302824 | 1.458355 | 14.77% | 7.8443% | 6.4642% | 0 | `f14a48df1a590611` |
| WND-01 | 72% | 72.00% (gearing binds) | 62,400.0 | 49,785.5 | 1.245257 | 1.504828 | 76.97% | 14.0936% | 9.8081% | 0 | `9b8b1dcd5275a4dd` |
| WND-02 (original) | 88% | - | - | - | - | - | - | - | - | - | **REFUSED** `SHL_MATURITY_NOT_ON_PERIOD_GRID_FAILS_CLOSED` (idx 57), 3 DBs same |
| WND-02-R (replacement) | 88% | 50.07% | 36,000.0 | 19,537.0 | 1.478935 | 1.555892 | 20.74% | 8.6222% | 7.4173% | 0 | `bf5ed81eabfdfa27` |
Min DSCR is the sealed per-period evidence minimum. WND-01 min DSCR 1.2453 is below its 1.30 target because the gearing cap binds (level-principal; consistent with ON-05's ON05-006 narrative, not independently proven here). The repo's `run_integrity_checks` returns **PASS** for all four runs (`probes/integrity_verdicts.json`) - low DSCR is a credit observation, not an identity failure. Equity IRR is on a 500 kEUR share-capital stub; Total Sponsor XIRR is the meaningful return. **Variant B (prior) numbers differ** (e.g. SOL-01 min DSCR 1.282391 vs 1.301523): totals-in-memory is not the user route (line composition/spending profiles differ) - do not use Variant B as a baseline.

## 4. Findings (corrections to the prior report marked *)
1. **CAPEX/OPEX are expressible only as cost lines** (`capex_opex_editable=False`; Run folds replace snapshot totals). `COST_LINE_ALLOCATION_LEDGER.csv` records every line for every fixture (rule `PROPORTIONAL_RESCALE_OF_SEEDED_LINES`, Decimal residual on the largest line; OD-2). After Save All + fold, effective CAPEX and OPEX Y1 equal the intended totals exactly for all four fixtures (ledger class `MATCH_ALLOCATED_LINES`).
2. **P90/P99 are not enterable.** No registry field exists; effective P90/P99 = 0.9/0.8 x P50 even for the untouched seeded project (seeded 1400 ignored; `probes/p90_probe.json`). The four fixtures' "EXPLICIT" P90 equals 0.9 x P50, so they match without being independently entered (`MATCH_DERIVED_NOT_SETTABLE`).
3. **WND-02 = two layers** (details `WND02_SHL_MATURITY_FORENSICS.md`): L1 reference-seeded projects keep the reference's SHL maturity/eligibility indices (Wind 57) when construction/horizon/tenor are edited -> off-grid refusal for horizons <= 26; horizons >= 28 run with a **stale maturity silently**. Minimal repro: one Save-All cell on a fresh Wind project. L2 with indices re-derived the fixture is still refused (`SHL_MATURITY_RESIDUAL_FAILS_CLOSED`, 62,453 kEUR): economics cannot retire the SHL. Boundaries: CAPEX <= ~38.4 MEUR or PPA tariff >= ~114 EUR/MWh. *The prior one-field-at-a-time probing could not see L2.*
4. *Prior "6-decimal rounding edge" explained: the payload `sources_uses` is 6-dp quantised; full-precision `financing_evidence.sources_uses` differs by <= ~1e-11 kEUR (engine-reported 0.0). Identity now uses full precision.
5. *Prior "construction-draw schedule not exposed" was wrong: `financing_evidence.construction_funding.periods` exists. Periodic uses + non-construction FC uses = audit total (exact); periodic senior draws + non-construction FC senior draw = senior commitment (exact; 30,455.96 + 1,836.22 = 32,292.18 for SOL-01).
6. **ON-05 reconciliation (definitions demonstrably identical, applied to the engine's own sealed fields; 7 runs x 9 checks, all PASS):** `identity_report` (roll-forward, chain, first opening, interest = opening x rate x day-fraction, service, DSCR, non-negativity) within the ON-05 tolerances; `sculpted_roll` reproduces engine principal/closing from the engine's bank CFADS, target and availability with **max deviation 9.6e-7 kEUR (just inside the 1e-6 ladder)**; the independent `xirr` equals Total Sponsor XIRR with max deviation 3.2e-16. Not independent of the engine's inputs: it checks arithmetic and the sculpting law, not input truth.
7. One residual recorded, not bent: SOL-02 final senior closing 3.1e-6 kEUR > 1e-6 ladder (`RESIDUAL_ABOVE_1E-6_RECORDED`); repo integrity requires ~zero terminal balance only when `permit_terminal_balloon` is false (it is true here).
8. 78 previously unextracted baseline rows split (`OUTPUT_EXPOSURE_REGISTER.csv`): ENGINE_AVAILABLE_BUT_HARNESS_MISSING (EBITDA-02, OPEX-02, CAPEX-02, DEBT-01, RES-02, STATE-01, WARN-01, WARN-02, IDENT-02/03, PROV-02) - 10 now extracted, PROV-02 still not run; NOT_EXPOSED_BY_PAYLOAD (TAX-03 loss ledger null; IDENT-04 no defined identity); NOT_CONFIGURED (NPV-01/02, LLCR-01: no valuation policy / coverage CFADS case); NOT_COMPUTED (PLCR-01); PERSISTED_RUN_AVAILABLE (DSCR-04 covenant verdict, PROV-01 engine fingerprint/composite hash - only for a committed Run). Nothing made up.
9. Checklist: A5 B7 C10 D6 E5 F6 = 39, G = 5, total 44; the "36" is unexplained (OD-5). U-07/U-08 are scoped to the **v1 API** only.

## 5. Files
`TRUE_ROUTE_INPUT_LEDGER.csv`, `COST_LINE_ALLOCATION_LEDGER.csv`, `FIXTURE_RUNS_AND_IDENTITIES.csv`, `ON07_LOCAL_BASELINE_TRUE_ROUTE.csv` (obs_react/obs_legacy/obs_competitor/discrepancy_class EMPTY), `OUTPUT_EXPOSURE_REGISTER.csv`, `REPRODUCIBILITY_3_FRESH_DBS.csv`, `ORIGINAL_VS_REVISED_FIXTURE_DIFF.csv`, `WND02_SHL_MATURITY_FORENSICS.md`, `OWNER_DECISION_REGISTER.md`, `isolated_revised_copies/` (runbook, fixtures, mapping, comparison template, unverified assumptions, checklist audit), `probes/`, `captures/`, `harness/`.
## 6. Commands (inside a checkout pinned to main db504f6; venv from requirements.txt + constraints.txt)
```
R=<checkout>; P=<unzipped ON07 package>; O=<unzipped ON05 pack>/ON05/harness/oracle.py
python -I harness/true_route.py --repo $R --fixtures $P/ON07_PROJECT_FIXTURES.csv --out tr1            # repeat to tr2, tr3
python -I harness/true_route.py --repo $R --fixtures $P/ON07_PROJECT_FIXTURES.csv --out wr1 --fixture WND-02 --override construction_months=20 --override horizon_years=27 --override total_capex_keur=36000 --tag WND-02-R
python -I harness/analyze_ca.py --repo $R --template $P/ON07_OUTPUT_COMPARISON_TEMPLATE.csv --oracle $O --group "USER_CREATED_CORE_RUN|TR|SOL-01|tr1,tr2,tr3" ... --out out
python -I harness/shl_forensics.py|wnd_minimal_repro.py|wnd02_levers.py|wnd02_rederived_diag.py|p90_probe.py|integrity_verdicts.py   (see script docstrings)
```
## 7. Remaining blockers / minimum owner decisions
OD-1 SHL index policy (owner-gated; recommended re-derive), OD-2 cost-line allocation, OD-3 WND-02 disposition (adopt WND-02-R?), OD-4 P90/P99 contract, OD-5 checklist count, OD-6 #400 merge+staging SHA+accounts, OD-7 valuation policy for NPV/LLCR. finmodels.io stays BLOCKED (untouched). The original negative authentication/CAS/history checks remain required for live acceptance and were **not** exercised.
