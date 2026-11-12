# R04 global PPA technical ceiling — ISOLATED, NOT ACTIVE, NOT WIRED

Pure, exact (`fractions.Fraction`) validator of simultaneous PPA delivery windows against the authoritative technical production of ONE
selected case (P50 / P90-10y / ...). Owner-approved policy only: the sum of committed PPA energy over all overlapping contracts must not exceed
available generation in any time interval; excess is a typed refusal (`GLOBAL_PPA_CAP_EXCEEDED`) with year/date range, case, available,
existing, requested, excess and maximum-additional GWh.

- Contracts use their TRUE `[start, end)` date range; calendar years are only an exact aggregation.
- Volume is either `ABSOLUTE_ANNUAL_MWH` (MWh or GWh per year, prorated by days inside each contract anniversary year) or
  `PERCENT_OF_AVAILABLE`; the two are never interchanged and the legacy `volume_share` key is refused.
- Merchant / UNSOLD is only the uncontracted residual: no price, never zero-filled (`price_status=EVIDENCE_REQUIRED`).
- Availability is an INPUT with provenance (`source_id`, project, scenario, case, version, basis); this module never derives P50, never
  hardcodes a capacity and never imports product code.
- Prices, indexation and CfD settlement are NOT computed here.

`STATUS` is `active=False, approved_for_finco=False, wired_into_save_or_run=False`. Integration into the canonical contract writer and the
Run effective-input path is **blocked** (see the R04 report): the stored contract schema has no absolute-volume or true-date representation
and the released axis rejects partial-period contracts.
