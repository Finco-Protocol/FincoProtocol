# FIN-V2-3 backend integration contract

Save through the existing Workbook single or batch Save authority. Field ID:
`debt.valuation.configuration`; snapshot key: `financial_core_config_json`.
Registry sheet: `project_setup`. Existing ownership, protected-reference, CSRF,
scenario and composite-hash CAS checks apply. Save never creates a Run.

The bounded JSON object has exactly these top-level keys:

```json
{
  "schema_version": "FIN_V2_3_POLICY_V1",
  "rate_unit": "human_percent_v1",
  "shl_timing_basis": "ABSOLUTE_INDEX",
  "project": null,
  "coverage": null,
  "sponsor": null
}
```

Null sections/rates remain unconfigured. No numerical rate default is supplied.
Every configured section requires `discount_rate_pct`, `authority_label`
(`FINANCIAL_OWNER:<explicit policy source>`) and `discount_convention`.
Research-only authorities and unknown/duplicate keys are refused. Human rate
0.056 means 0.056%, converted once to ratio 0.00056; 0.56%, 5.60% and 9.00%
remain distinct. Typed serialization stores ratios and never reapplies that
conversion. Rates must be finite and -100% < rate <= 1000%, matching existing C2.

Project fields: `valuation_date_policy` (`FIRST_PROJECT_CASHFLOW_DATE` or
`EXPLICIT_DATE`), `explicit_valuation_date` (ISO date or null). Sponsor fields use
`FINANCIAL_CLOSE` or `EXPLICIT_DATE`; Sponsor currently supports `ACT_365_FIXED`
only and refuses other conventions explicitly.

Coverage fields: `cfads_case` (`BASE` or `BANK`), `calculation_date_policy`
(`FIRST_SENIOR_PERIOD_OPENING`), `llcr_cashflow_basis`, `plcr_cashflow_basis`
(`RAW_SELECTED_CFADS` supported for the new loan-life metrics),
`denominator_basis` (`SENIOR_OPENING_BALANCE`), and `rolling_loan_life`
(`ACTUAL_REPAYMENT` or `CONTRACTUAL_MATURITY`). A missing eligibility authority
is not fabricated for `SENIOR_ELIGIBLE_CFADS`.

Periodic Project/coverage policies additionally require
`periodic_rate_conversion: AS_QUOTED_PER_MODEL_PERIOD`, positive integer
`periods_per_year`, and `first_cashflow_timing: END_OF_FIRST_PERIOD`. The quoted
rate is per model period; it is not divided by periods_per_year.

New committed Run evidence lives at
`runtime_summary.financing_evidence.financial_core_v1`. It inherits the existing
financing `run_binding` (snapshot, composite hash, scenario) in the same atomic
transaction as the summary and immutable history. It contains policy/version,
C2 audit rows, loan-life observation rows, sponsor NPV/status, full-precision
statement input components, project flows and disclosures. Existing database
JSON columns suffice. Historical absence returns `NOT_PERSISTED`.

New sponsor rows use `SPONSOR_PERIOD_EVIDENCE_V1`, `axis_kind`, dates, equity/SHL
cash contributions, receipts, PIK and net cash flows. Loan-recognition rows are
separately dated in `loan_balance_periods`. Never join sponsor construction and
operating rows on their repeated numeric period labels.

Additive metric keys: `llcr_contractual_maturity`, `llcr_actual_repayment`,
`llcr_at_first_senior_opening`, `min_rolling_llcr`, `plcr`, `sponsor_npv_keur`.
Project NPV retains `project_npv_keur`. Absence has a typed reason, never a zero.
The original `min_llcr` remains unchanged.

Goal Seek service adds `min_dscr` (multiple), `project_npv` (kEUR), `sponsor_npv`
(kEUR); `total_sponsor_irr` remains the canonical Total Sponsor XIRR target
(ratio internally). Legacy form input interprets return targets as percent and
DSCR/NPV targets in their declared unit. `GoalSeekResult.target_unit` makes the
unit explicit. RC-M should use `financial_goal_seek.available_targets(inputs,
project_type, canonical_kpis)` against the matching current authoritative input
state, not stale Run values. Missing policies/metrics are not offered. There is
no DC/EV scalar tariff solver. Preview remains persistence-free. Apply uses the
existing authorized Goal Seek Save/CAS flow and never auto-runs.

New financial target results are canonically rerun with exact float identity and
a narrow neighboring bracket. Non-monotonic values, unavailable candidates or
an unresolved financing regime switch return typed refusal. Evaluation budget
includes the three final checks. RC-M must render units/statuses and explicit
policy controls; no React source/bundle is modified by this workstream.
