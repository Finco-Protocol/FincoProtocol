# revenue_reference_core (R01-A) — dormant, pure, synthetic

Isolated two-tier PPA numeric candidate. **Not imported by any engine, route, UI or Run.** Decimal only, no I/O, no global state.

* `compute_ppa_tiers(PpaTierInput) -> tuple[PeriodResult, ...]`
* The semantics of the two caps are **not reference-verified**. `cap_semantics` has no default and must be one of
  `CUMULATIVE_LIFETIME_CEILING`, `ANNUAL_CEILING`, `CUMULATIVE_LIFETIME_INCREMENTAL`, `ANNUAL_INCREMENTAL`; anything else raises `ContractError`.
* Every mode is exploratory: results are tagged `SEMANTICS_UNVERIFIED` / `SYNTHETIC_ORACLE_ONLY` and are never a parity claim.
* Units: generation `MWh|GWh`, caps one common unit `MWh|GWh`, prices `EUR/MWh`, outputs `MWh`, `EUR`, `kEUR` (= EUR/1000, exact). EUR is rounded half-even to 6 dp per component per period.
* Window: consecutive calendar years; energy outside `[ppa_start_year, ppa_end_year]` is merchant and never consumes a cap; merchant price must be given for every year and is never indexed here.
* Indexation: `factor = (1-f) + f*(1+r)^(year-base_year)` applied to both PPA prices only; `base_year <= ppa_start_year`.
* Tests: `tests/r01a_ppa_core/` (hand values + independent Fraction brute-force oracle + fail-closed negatives + isolation check).
