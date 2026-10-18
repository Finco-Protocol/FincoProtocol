# RC-7 / Workstream C - Advanced Revenue & PPA V3

Base: `origin/main` `05183b2a96c74fd4b3976903c593a61402cab7b3`. Branch `feat/model-rc7-advanced-revenue-ppa-v3`.
No release approval is claimed here. Protected revenue authorities (`domain/revenue/multistream_runtime.py`, `domain/revenue/advanced_products.py`,
`finco_core/revenue/generation.py`) are **byte-identical to main**: the review found no defect in them that this stage needs to fix, so no new
governance successor pin is created and none of the exact-blob guards is touched.

## 1. Financial contract authority matrix (reuse / extend / unsupported)

| Capability | Status | Authority / evidence |
| --- | --- | --- |
| Several simultaneous PPAs, per-contract price, share and dated window | REUSE (released V2) | `parse_config` / `MultiStreamRevenue`; `test_rc7_revenue_ppa_v3_economics::test_overlapping_and_sequential_contracts_*` |
| Exact contract end / start boundary (end exclusive, canonical period boundary, no pro-rating) | REUSE | mid-period dates rejected `REVENUE_V2_AXIS`; boundary test above |
| Fixed, annual-indexed, scheduled (`price_curve`) prices | REUSE | `test_fixed_indexed_and_scheduled_prices_reconcile_independently` |
| Calendar / contract-anniversary indexation, dated index series, rounding (PPA-01) | REUSE (release-closed PPA-01 candidate already on main) | PPA-01 reports; not re-opened |
| Merchant residual + capture rate | REUSE | residual = 1 - allocated physical shares |
| Signed two-way CfD overlay (financial only) | REUSE | `test_signed_cfd_settlement_*`: both signs, no physical MWh consumed |
| Explicit zero price vs missing price | REUSE | zero valid, missing `price_eur_mwh` rejected |
| Negative / NaN / Inf / mistyped numerics, duplicate contract id, over-allocated shares | REUSE | rejected at parse and by the Save route (422, nothing persisted) |
| P50 vs P90 production basis, lender sizing on P90 | REUSE | `technical.yield_scenario`; `test_lender_case_sizes_debt_on_p90_*`; bank case refuses silent contract-price replacement (`REVENUE_V2_BANK_PRICE_OVERRIDE_UNSUPPORTED`) |
| Tariff sensitivity under explicit contracts | REUSE (RC-5A) | refused, never a silent zero delta |
| Physical-energy ledger (production vs contracted vs merchant vs unallocated vs CfD overlay vs non-energy) | **EXTEND (this PR)** | new pure module `app/workbook/revenue_energy_ledger.py`, persisted in Last Run as `revenue_energy_ledger` |
| Capacity / Ancillary / REC contracts | CANDIDATE (release-closed, `ACTIVATION_ENABLED=False`) | typed units, eligibility, ownership and REC/legacy collision already enforced; guard kept |
| Lagged settlement, FX, dispatch/utilisation, penalties, activation energy, price interpolation, invented indices | UNSUPPORTED | fail closed; no methodology exists |

## 2. What this PR adds

* `app/workbook/revenue_energy_ledger.py`: read-only projection over the per-period contract evidence the Run already commits. It performs
  **no** price, volume or settlement arithmetic. Physical classes (contracted, merchant, unallocated) are additive; CfD overlay volume is
  reported separately and never added to the physical total; non-energy products keep their own units.
* The Run summary now carries `revenue_energy_ledger` (only for Runs with explicit contracts; legacy Runs and their history are untouched).
* A finding made visible rather than hidden: the released allocation accepts shares that do not cover 100% of production (for example one PPA at
  30% and no merchant stream). The energy earns nothing and the engine records `unallocated_generation_mwh`; the ledger now classifies it as
  `UNALLOCATED_ENERGY`. Rejecting such books would change released Revenue V2 behaviour and needs a financial decision (section 5).
* `tests/test_rc7_revenue_ppa_v3_economics.py` (independent Decimal oracles) and `tests/test_rc7_revenue_ppa_v3_workspace.py`
  (Save / Run / STALE / CURRENT / history / duplicate / deactivate on the existing editor route).

## 3. Independent numerical reconciliation

Expected values are computed in the tests from contract terms and the engine's own period axis; none are produced by the code under test.
Solar and Wind committed Runs: contracted + merchant + unallocated reconciles to production with residual < 1e-6 MWh; per-stream revenue to
1e-8 kEUR; an input price change of +20 EUR/MWh on a 60% share moves total revenue and EBITDA by exactly `sum(generation) x 0.6 x 20 / 1000`,
and changes tax, CFADS, senior debt size, Sponsor XIRR and Project XIRR.

## 4. Revenue V2 legacy equivalence

No protected revenue file, financial engine file, writer, or run-history code is modified. Runs without explicit contracts produce the same
summary keys as before. Existing suites (WF07 runtime/governance, Revenue V2 curves, Revenue V3 runtime) pass unchanged.

## 5. Financial-release gaps and required approvals

1. Policy for unallocated energy under explicit contracts: reject at Save, require an explicit merchant/curtailment stream, or keep as is.
   Any of the first two changes released Revenue V2 behaviour and needs financial approval plus an exact-blob successor for the protected files.
2. Capacity / Ancillary / REC remain release-closed; activation needs independent exact-content review of the three candidate blobs.
3. Cross-stream date policy (Agent A 3/3 financial mode) is not assumed. Interface needed from the RC coordinator: the contract windows are
   expressed as exact operating-period boundary dates of the released 6/6 axis; a 3/3 axis would require re-validation through
   `MultiStreamRevenue.validate_axis`, which already rejects contract dates that are not canonical period boundaries.
