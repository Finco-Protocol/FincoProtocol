# FINCO ON-07 Executable Local Baseline (post-#399) — VERDICT: **PARTIAL**

`BASELINE_READY_FOR_POST400_LIVE_ACCEPTANCE` is **not** claimed. The harness is executable and reproducible, and 3 of 4 fixtures produced real engine Runs, but: WND-02 is refused by the engine (recorded, not coerced); the Run route does not bind the fixture CAPEX/OPEX totals (see Finding 1); several template metrics are not exposed by the Run payload; the ON-05 oracle was not supplied; contractual-DSCR/covenant status is not part of the Run payload. Exact blockers are in section 5.

## 1. Preflight (re-verified 2026-10-30 via GitHub)
- main `db504f6408cb456c617c9342a1ffa202ee455283`, tree `9b96717bae39a4dbb496879c7e6c028e675492d3` (includes merged #399 WF-04 and #401). Package was authored at `8a74fcb5`; everything below was re-derived on `db504f6`.
- #400: **open, Draft**, head `21d3ad8fcbe66973e045fe33f60284976c82237b`, base `8a74fcb5`, `mergeable_state: dirty`. Not merged, not asserted deployed, **untouched**.
- Isolation: throwaway venv + per-process temp SQLite DB (`FINCO_DB_PATH`), in-process engine calls, no network, no HTTP app, no auth, no credentials; no repo file edited, no PR/CI. Package input: `ON07_FIXTURE_REVIEW_PACKAGE.zip` sha256 `8b17aae6…b7b1` (per-file hashes in FIXTURE_PROVENANCE.md). The ON-05 oracle was **not** provided.

## 2. What was executed
`harness/run_on07_workbook.py` emulates the canonical workbook route: reference-seeded Working Copy (`create_reference_seeded_project`, the same authority both UIs use) -> overlay the fixture CSV's **EXPLICIT** cells onto the draft snapshot (registry-validated where a registry field exists) -> `ProjectInputSet.from_snapshot` -> `to_projectinputs` -> (variant A only) CAPEX/OPEX sub-line folds -> `run_project`. These are steps 7-11 of `POST /v2/workbook/run`; steps 1-6 (auth/CSRF/CAS), the atomic commit, history persistence and the process executor are **not** exercised. ENGINE_DEFAULT and EXCLUDED rows are never injected.

**Variant B: SNAPSHOT_TOTALS (fixture CAPEX/OPEX totals bound; NOT the Run route)**

| Fixture | Status | CAPEX kEUR | Senior kEUR | Actual gearing | Min DSCR (sealed evid.) | Avg DSCR | Equity IRR (share-cap) | Total Sponsor XIRR | Project IRR | Lock-up periods | Evidence digest |
|---|---|---|---|---|---|---|---|---|---|---|---|
| SOL-01 | RUN_OK | 45,600.0 | 32,338.3 | 66.51% | 1.282391 | 1.400477 | 23.24% | 9.9113% | 7.4137% | 0 | `d98c9eebcb8c1dbc` |
| SOL-02 | RUN_OK | 57,600.0 | 39,805.0 | 64.21% | 1.314062 | 1.459501 | 15.30% | 7.9115% | 6.4644% | 0 | `87ec3fbd9ba8bc0e` |
| WND-01 | RUN_OK | 62,400.0 | 49,706.2 | 72.00% | 1.344132 | 1.477300 | 72.97% | 14.0118% | 9.7882% | 0 | `80ee80171da1d4aa` |
| WND-02 | **REFUSED_OR_ERROR** | - | - | - | - | - | - | - | - | - | `PR8_CLEAN_ENGINE_FAIL_CLOSED: ValueError: SHL_MATURITY_NOT_ON_PERIOD_GRID_FAILS_CLOSED: maturit` |

**Variant A: RUN_ROUTE (steps 7-11; seeded sub-lines override CAPEX/OPEX)**

| Fixture | Status | CAPEX kEUR | Senior kEUR | Actual gearing | Min DSCR (sealed evid.) | Avg DSCR | Equity IRR (share-cap) | Total Sponsor XIRR | Project IRR | Lock-up periods | Evidence digest |
|---|---|---|---|---|---|---|---|---|---|---|---|
| SOL-01 | RUN_OK | 30,937.5 | 23,611.8 | 70.00% | 1.331532 | 1.504998 | 64.02% | 17.1269% | 12.7384% | 0 | `c7ea0cbe00cbf96b` |
| SOL-02 | RUN_OK | 41,250.0 | 39,094.6 | 85.00% | 1.356812 | 1.440577 | 98.80% | 20.7528% | 10.6882% | 0 | `5a5eb43e1ee059d3` |
| WND-01 | RUN_OK | 43,000.0 | 35,012.1 | 72.00% | 1.392796 | 1.471357 | 97.61% | 20.6830% | 14.9442% | 0 | `e52552c2a419bb56` |
| WND-02 | **REFUSED_OR_ERROR** | - | - | - | - | - | - | - | - | - | `PR8_CLEAN_ENGINE_FAIL_CLOSED: ValueError: SHL_MATURITY_NOT_ON_PERIOD_GRID_FAILS_CLOSED: maturit` |

Equity IRR here is the *share-capital* IRR on a 500 kEUR share-capital stub with an SHL-funded remainder, so it is not a comparable headline; **Total Sponsor XIRR** is the meaningful return. Both are reported as the engine returns them.

Repeatability: the three RUN_OK fixtures were executed in 3 fresh disposable DBs (variant B); `kpis`, `debt_schedule`, `sources_uses` and the evidence digests were identical every time. The Run-history `composite_hash`, `engine_version` and `history_id` do not exist locally (no persisted Run).

## 3. Headline findings
1. **CAPEX/OPEX totals do not bind on the Run route (NEW, not in ON-07 assumptions).** The snapshot cells `total_capex_keur`/`opex_y1_keur` do reach `to_projectinputs` (45,600 / 760 for SOL-01), but the Run's CAPEX/OPEX sub-line folds (`apply_user_sub_lines_replacing_base`/`apply_user_sub_lines_to_opex`, `app/v2/router.py` steps 9-10) replace them with the seeded, capacity-scaled DB lines (30,937.5 / 356.25). So a project with only the grid-cell totals set runs on **different economics** than the fixture. Entering the fixture totals needs the cost-lines editor, and the effective CAPEX/OPEX must be read back from the Run. Variant A shows what the route does today; variant B shows the totals-bound economics but is **not** the Run route and is not a proxy for a cost-line-edited project (line composition/spending profile would differ). Neither variant is parity evidence.
2. **WND-02 is refused fail-closed:** `SHL_MATURITY_NOT_ON_PERIOD_GRID_FAILS_CLOSED: maturity_period_index=57`, in both variants. Diagnostic (altered runs, never reported as the fixture): single-field changes to tenor, gearing, COD, construction months, capacity, P50 and PPA share do not remove it; horizon 30 changes it to `SHL_MATURITY_RESIDUAL_FAILS_CLOSED` (closing SHL 62,787 kEUR at index 57). Root cause is the interaction of the wind reference's SHL maturity index with the period grid; not diagnosed beyond that. The WND-02 stress case (88% gearing, short tenor) therefore has **no engine numbers**; per the brief this is recorded, not coerced.
3. **Gearing is a cap.** With true fixture CAPEX (variant B), SOL-01 ends at 66.5% (input 70%) and SOL-02 at 64.2% (input 85%): DSCR sizing binds first. WND-01 reaches 72.0%.
4. Fixture value read-back: 88 of 88 variant-B EXPLICIT read-backs and 80 of 88 variant-A read-backs MATCH the intended values (see ON07_FIXTURE_BINDING_AUDIT.csv); the 8 variant-A mismatches are exactly CAPEX and OPEX for all 4 fixtures (WND-02's inputs were materialised before its refusal). ENGINE_DEFAULT p99/degradation/CIT/LCF read back as stated.
5. U-07/U-08/U-09: **CONFIRMED** on main `db504f6` (v1 API only; see U07_U08_FINDINGS.md). The fixture route avoids them by using the workbook path, where P90 is supplied explicitly and read back as 1350/1305/2970.

## 4. Accounting identities (full precision, template tolerances)
ACCOUNTING_IDENTITIES.csv: for every RUN_OK fixture/variant — Sources=Uses, interest+principal=debt service, opening-principal=closing, closing_t=opening_t+1, final balance 0, DSCR=base CFADS/debt service, min DSCR profile = KPI, sponsor net flows = receipts - contributions — all PASS. One is labelled `PASS_AT_6DP_QUANTUM_EDGE` (SOL-02 variant A: recomputed difference 1.0000003e-6 from 6-dp component quantisation; engine-reported difference 0.0). IDENT-04 (cash conservation) and the construction-draw check are `NOT_EVALUATED` (no machine-readable identity / schedule exposed). The ON-05 precedent reconciliation is `NOT_EXECUTED` (oracle not provided).

## 5. Outstanding blockers
- ON-05 `ON05_FINANCIAL_ORACLE.md` not provided -> no independent reconciliation.
- WND-02 refusal (engine/input interaction) needs an owner/engine decision before it can yield numbers.
- CAPEX/OPEX binding method must be decided (cost-lines entry + read-back) before browser fixtures are entered.
- ON07_LOCAL_BASELINE.csv: per-period production/revenue/CFADS/debt rows are filled; EBITDA-02, OPEX-02, CAPEX-02, TAX-03, PLCR-01, DEBT-01 draws, RES-02, STATE-01 etc. are `NOT_EXTRACTED_BY_HARNESS_OR_NOT_EXPOSED`; NPV/LLCR/PLCR KPIs are `None` in the payload and recorded as such. `tables.*` were not used (their row labels are ambiguous in the payload).
- Contractual DSCR/covenant status is a Run-bound v2 projection, not in `run_project`; no live Run exists. The fixtures contain no contractual terms, so for the fixtures the correct status is NOT_CONFIGURED (WF04_COVENANT_EVALUATION.json).
- Package says 36 UX checks; the checklist has 39 A-F + 5 negative rows.
- Live parity: #400 merge+deploy at an exact SHA (ON07_RUNBOOK.md section 0 still lists #399 as unmerged: stale), owner-provided accounts, finmodels.io BLOCKED (not touched). No credentials/tokens anywhere in this ZIP.

## 6. Files / commands
`harness/` run_on07_workbook.py (main runner), analyze_captures.py, build_fixture_binding_audit.py, binding_probe.py (v1 probes), diagnose_refusal.py, on07_common.py. `captures_wb_route/`, `captures_wb_snapshot_totals/` raw JSON. Deliverables: ON07_LOCAL_BASELINE.csv (368 rows, comparator tolerance preserved, obs_react/obs_legacy/obs_competitor/discrepancy_class EMPTY), ON07_FIXTURE_BINDING_AUDIT.csv, ON07_V1_API_BINDING_PROBE.csv, ACCOUNTING_IDENTITIES.csv, WF04_COVENANT_EVALUATION.json, ON07_GAP_REGISTER_UPDATED.md, POST400_LIVE_PARITY_RUNBOOK.md, U07_U08_FINDINGS.md, WF04_VERIFICATION.md, ON05_RECONCILIATION.md, IMPLEMENTATION_GAP_SHORTLIST.md, FIXTURE_PROVENANCE.md.
```
python3 -m venv v && v/bin/pip install -r requirements.txt -c constraints.txt     # in a checkout pinned to main db504f6
P=<unzipped ON07 package>; R=<checkout>
v/bin/python -I harness/run_on07_workbook.py --repo $R --fixtures $P/ON07_PROJECT_FIXTURES.csv --out captures_wb_route
v/bin/python -I harness/run_on07_workbook.py --repo $R --fixtures $P/ON07_PROJECT_FIXTURES.csv --out captures_wb_snapshot_totals --no-subline-fold
v/bin/python -I harness/analyze_captures.py --repo $R --template $P/ON07_OUTPUT_COMPARISON_TEMPLATE.csv --captures captures_wb_route captures_wb_snapshot_totals --out .
v/bin/python -I harness/build_fixture_binding_audit.py --fixtures $P/ON07_PROJECT_FIXTURES.csv --captures captures_wb_route captures_wb_snapshot_totals --out ON07_FIXTURE_BINDING_AUDIT.csv
v/bin/python -I harness/binding_probe.py --repo $R --out ON07_V1_API_BINDING_PROBE.csv
```
