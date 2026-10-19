# RC-7C — Quarterly Financial Acceptance (Economic Horizon, Financial Policy, Run Readiness)

**Classification: RESEARCH CANDIDATE, RELEASE-CLOSED. This document is not an approval.** No Financial Owner decision, key, signature, registry entry,
independent review or GitHub approval is created or implied. `ACTIVATION_ENABLED = False` is unchanged (asserted by
`tests/test_rc7c_quarterly_run_acceptance.py::test_the_committed_activation_constant_stays_off`); the owner-only Gate R of PR #320 is **not**
generalised; no deploy, no product activation, no historical Run changed.

Base: live `main` `bf0167a036a6e30d3225b901aeda1b353681171a` (merge commit of PR #320). Companion documents:
`RC7C_FREQUENCY_RECONCILIATION.md` (numerical 6/6 vs 3/3 table and bit-identical proof), `RC7B_QUARTERLY_DECISION_MATRIX.md` and
`RC7B_FINANCIAL_OWNER_DECISION_PACKAGE.md` (inputs; D-03 row superseded by this document), `RC7C_SEMIANNUAL_REGRESSION.json`.

## 1. D-03 — what was wrong and what RC-7C changes

PR #320's independent review found ~1.07 % additional revenue when the reviewed Solar project is switched from 6/6 to 3/3. Root cause, reproduced
numerically and with an independent date oracle: the v1 candidate (`rc7b-quarterly-candidate-v1`) defines the horizon as `4 × N` operating rows and counts the
opening stub as one row, so when COD lies in the *second quarter of a half-year* the 3/3 project operates **exactly one extra quarter** (e.g. end
`2055-12-31` → `2056-03-31`, 100 rows vs the 6/6 project's 50 rows = 99 quarters). Frequency alone extended project life and invented revenue.

**RC-7C candidate policy v2 (`rc7c-quarterly-candidate-v2`) — date-authoritative.**

| Aspect | Rule (v2) |
|---|---|
| Economic end date | The end date of the **equivalent released six-month project** (`semiannual_row_ends(operating_start, 2N)[-1]`). A `date`, not a row count. Switching frequency preserves it. |
| Quarterly rows | Half-open quarters from COD (D-01 `KEEP_ACTUAL_COD`) up to the economic end date; only the opening stub may be shorter than a quarter. |
| Model year (D-04) | Each quarterly row inherits the model year of the six-month row that contains it. Degradation, indexation, depreciation and OPEX steps fall on the same dates as in 6/6; each model year spans exactly the same dates under both frequencies. |
| Senior maturity (D-10) | End date of six-month row `2 × tenor` — the same date under both frequencies; the final quarterly payment falls on it. No extension, no acceleration. |
| Terminal stub | The engine supports an explicit `economic_end_date` (date-authoritative policy only) strictly inside the final model year: the last row is a dated stub with exact `days / 365|366` fraction. A one-day terminal stub is refused (`PERIOD_AXIS_TERMINAL_STUB`); a date outside the final model year, a non-date, or use with 6/6 or v1 is refused. Not yet wired to a user input — see decision **D-03-b**. |
| Validation | `validate_canonical_period_axis(year_alignment="SEMIANNUAL_ALIGNED", expected_economic_end=…)` recomputes the clock from dates alone and rejects a wrong end date, row-count clock, wrong slot, or a v1 axis presented as v2. |
| Versioning | Policy version, ruleset (horizon/model-year/maturity) and cache key are explicit. v1 and v2 never mix (`QUARTERLY_POLICY_RULESET_MISMATCH`); v1 stays decodable and its axis is unchanged so historical candidate evidence remains valid. The workbook selection and committed-Run evidence carry the v2 version. |
| Released 6/6 | Untouched. The 6/6 axis, annualisation and every 6/6 input are bit-identical to `main` (see reconciliation doc). |

**Files changed in the financial/protected set** (each is a pinned RC-7B blob — see §6): `finco_core/engine/calendar_policy.py`,
`finco_core/engine/period_engine.py`, `financial_engine/orchestrator.py`, `financial_engine/senior_debt/project_adapter.py`.

### Horizon convention for new projects (not silently redefining existing ones)

* **Existing projects / 6/6 (legacy fixed-row convention):** horizon = `2N` six-month rows counted from the opening stub's row; the end date is the Jun 30 /
  Dec 31 that closes row `2N`. This is the released authority and is unchanged. It is *not* a contractual anniversary (example: COD 17 Apr 2028, N = 1 ends
  31 Dec 2028, 258 days after COD — the stub row counts as a row, so the horizon is not COD + N years when COD is mid-half-year).
* **3/3 candidate (v2):** preserves that date exactly. The two frequencies are therefore economically equivalent on the time axis.
* **New projects wanting a contractual-anniversary horizon (COD + N years):** supported *technically* by the explicit `economic_end_date` + terminal stub,
  limited to the final model year so annual input arrays keep their length. Adopting it as a convention for new projects (and for 6/6 as well) is a
  Financial Owner policy change and a separate released-engine change; it is **not** applied here (decision **D-03-b**).

## 2. Evidence summary

| Requirement | Evidence |
|---|---|
| 6/6 bit-identical (Solar/Wind/DC/EV) vs live main | `tools/rc7b_semiannual_regression.py --baseline origin/main` → exit 0, max difference 0 (`RC7C_SEMIANNUAL_REGRESSION.json`) |
| v2 rows, model years, maturity vs independent date oracle | `tests/test_rc7c_quarterly_date_authority.py` — start/end/days/model-year spans for 12 FCs × 8 construction durations × horizons 1…25; v1 = +1 quarter exactly when COD+1d is in the second quarter of a half-year |
| Terminal stub & explicit end date | same file: exact stub days and day fraction, 1-day stub refused, outside-final-year refused, policy/6-6 misuse refused, cache key distinct |
| Annualisation regression | released 6/6 axis byte-identical test; per-year identities (production/OPEX/depreciation equal; revenue equal except the PPA-expiry year) |
| Canonical Run, both frequencies, numerical reconciliation | `tests/test_rc7c_frequency_reconciliation.py` (30 cases: Solar/Wind, different CODs, leap years, initial/terminal stubs, construction 9…24 months, ACT/360 & ACT/365, tenors 8/10/12, horizons 15/20/25/30, PPA 0/7/12 y) |
| Real committed app Runs | `tests/test_rc7c_quarterly_run_acceptance.py` (Solar, Wind): same project run 6/6 then 3/3 → same operating start/end/days, same model-year spans, identical production/OPEX/depreciation, revenue equal except the PPA-expiry year, quarterly Senior service ending on the same maturity date, policy version v2 in committed evidence, the historical 6/6 Run byte-identical. Existing `test_rc7b_quarterly_production_acceptance.py` (Save/CAS, STALE/CURRENT, Run History, export label, refusals) passes unchanged with v2 as default |
| Unsupported scope still refused | `tests/test_rc7b_quarterly_*` suites: SHL, DSRA/DSRF, Junior/multi-Senior, BESS/DC/EV, VAT facility, multistream revenue, dated indexation, hierarchical OPEX, non-quarter-end PPA expiry, COD roll window, mixed 3/6 and 6/3 |

## 3. Consolidated Financial Owner decision matrix (D-01 … D-12 + new)

Recommendations are **not approvals**. "Evidence" cites tests/documents in this PR. "Consequence" is the economic effect if the owner accepts the
recommended choice. Status of every item: **OPEN** unless stated.

| ID | Recommended choice | Evidence | Economic consequence of the recommendation | Alternative / what the owner may instead require |
|---|---|---|---|---|
| **D-01** COD / opening stub | Accept `KEEP_ACTUAL_COD`: half-open quarters from actual COD; roll windows (COD < 7 days before a quarter end) stay **refused** | date-authority tests; refusal tests | A one-day first quarter is kept (1 day of production/interest). Economics identical to 6/6 except the COD-on-the-1st day (see D-02) | Add a roll rule (needs sourced convention) |
| **D-02** Day counts | Keep three separate conventions: production/operating fraction `days / end-year 365|366` (half-open), construction IDC inclusive ACT, Senior interest on its own ACT/360 or ACT/365; accept that a COD on the 1st does not get the released axis's `+1` day | reconciliation (first-of-month rows: ≈ 0.015 % of production/OPEX/depreciation); leap-year/short-stub cases; Senior day-count cases | −1 day of first-row production for a COD on the 1st | Re-introduce the `+1` rule on the 3/3 axis (would make 3/3 count one more day than the dates support) |
| **D-03** Horizon | Accept v2 date-authoritative policy (end date of the equivalent six-month project) as the 3/3 horizon | §1; reconciliation: horizon effect `+1.07 % → 0` revenue | 3/3 and 6/6 operate the same dates; no invented revenue (merchant-only cases exactly `+0.0000 %`) | Fixed-count v1 (not recommended; +1 quarter) |
| **D-03-b** Contractual-anniversary horizon for new projects | Defer; if adopted, apply to **both** frequencies as a released-engine change with explicit terminal stub; engine capability already tested | explicit-end-date tests | Horizon becomes COD + N years (differs from legacy fixed-row by up to a half-year) | Keep legacy fixed-row convention |
| **D-04** Annual clock | Each input follows its own time authority; model year = year of the containing six-month row (v2) | model-year span tests | Annual steps occur on the same dates as 6/6 | Calendar/anniversary clocks per input (separate change) |
| **D-05** PPA | Preserve PPA authority; expiry must lie on a quarter boundary or switch at the quarter boundary where it expires; no mid-quarter energy split; multistream/dated indexation stay refused | reconciliation: `+0.08 … +0.33 %` revenue only in the PPA-expiry year (cause identified); merchant-only `+0.0000 %` | Up to half a row of PPA-priced energy is priced at merchant earlier than in 6/6 | Sourced intra-quarter split (new contract feature) |
| **D-06** 3/6 mixed | **DEFERRED**, refused | refusal tests | none | — |
| **D-07** 6/3 mixed | **DEFERRED**, refused | refusal tests | none | — |
| **D-08** DSCR observation / distributions / Sponsor returns | Observe DSCR per quarter on the quarter's own service; distributions quarterly via the released waterfall; Sponsor returns stay disclosed as `PENDING_D08_DISTRIBUTION_ELIGIBILITY` until accepted | funding/statement suites; reconciliation (Sponsor XIRR ≈ +0.3 pp = timing only) | IRR higher by earlier cash receipts, not by value | Annual/semiannual lock-up observation |
| **D-09** Reserves | Keep DSRA/DSRF **refused** for 3/3 (no silent default) | `quarterly_scope` refusal tests | 3/3 projects cannot model a reserve | Dated reserve window + partial-period rule (new work) |
| **D-10** Maturity / repayment | Maturity = end date of six-month row `2×tenor` (same as 6/6); terminal Senior balance must be exactly zero; no balloon | maturity-date tests; closing balance < 1e-6 in committed Run | No extension/acceleration of Senior | Contractual off-grid maturity (needs its own date input) |
| **D-11** Tax | Keep the annual tax authority (calendar-year ledger, FIFO losses, annual limits) and pay cash tax once, in the last row of the tax year; ATAD/thin-cap refused | tax cases in reconciliation | Cash tax identical in timing to 6/6 (year-end), never 4 instalments | Quarterly instalments (needs tax-payment policy) |
| **D-12** Scope | Solar and Wind, one Senior, `EQUITY_ONLY`, no SHL/reserves/Junior/multi-Senior/VAT/BESS/DC/EV | `quarterly_scope` + refusal tests | Legacy four-vertical 6/6 unchanged | Extend only with reviewed evidence |
| **New** Activation | Keep admission **OFF**; first activation after D-03/D-03-b/D-08/D-09 decisions and a governance successor (§6) | `ACTIVATION_ENABLED` test | — | — |

## 4. Staging acceptance pack (read-only, no deploy, no activation)

1. Check out the PR head; confirm `app/workbook/quarterly_frequency_config.py: ACTIVATION_ENABLED = False` and that a 3/3 selection is refused for a general user.
2. In staging (admission closed) open an existing 6/6 Solar and Wind Run: confirm Run History, statements and XLSX export show half-year periods and **no** `operating_frequency` evidence.
3. Reproduce the reconciliation table locally against the staging reference inputs: `PYTHONPATH=.:tests python tests/rc7c_frequency_reconciliation.py`.
4. With the gate opened **only in a throw-away local environment** (monkeypatch as in `tests/test_rc7c_quarterly_run_acceptance.py`): run 6/6 then 3/3 on the same project and compare: operating start/end, model-year spans, production, OPEX, depreciation, revenue by year, Senior maturity date, closing balance 0, STALE→CURRENT after frequency change, historical Run byte-identical, XLSX frequency label `Quarterly`.
5. Compare staging Run history `runtime_summary.financing_evidence.operating_calendar_policy.version` = `rc7c-quarterly-candidate-v2` for new candidate Runs; `rc7b-quarterly-candidate-v1` Runs (if any exist) remain decodable and unchanged.

## 5. Activation-ready checklist (release stays CLOSED)

- [ ] Financial Owner records D-01…D-05, D-08…D-12 and D-03-b in the separate financial-acceptance record (not the Gate R record).
- [x] RC-7C release-closed candidate recognition (bytes only, §6) is in place — not an approval.
- [ ] Genuine Financial Owner authorization of the four RC-7C blobs, and independent review of those exact blobs (the PR #320 decision does not cover them).
- [ ] Staging acceptance (§4) executed by the Financial Owner delegate.
- [ ] Only then a separate PR flips `ACTIVATION_ENABLED` (not part of RC-7C).

## 6. Governance status (see `RC7C_GOVERNANCE_STATUS.md`, the canonical current-state document)

RC-7C changes four of the twelve RC-7B blobs. The PR #326 post-merge successor deliberately recognises only the original twelve and is **not** widened;
a separate, explicitly scoped RC-7C candidate successor (`tests/rc7c_candidate_successor.py`) recognises eight unchanged RC-7B blobs + the four pinned
RC-7C blobs, with the PR #320 merge ancestry, no other financial/core/domain change, the exact policy version and `ACTIVATION_ENABLED = False`.
Recognition is bytes-only and release-closed. **It is not approval:** the Financial Owner decision that accompanied the merge of PR #320 does not cover the
four RC-7C blobs, and none of D-01…D-12, D-03-b, Gate P, product admission or release is decided by it. The genuine outstanding authorization is the
Financial Owner's decision on the four RC-7C blobs and on the open D-codes above, with independent review of those exact blobs.
