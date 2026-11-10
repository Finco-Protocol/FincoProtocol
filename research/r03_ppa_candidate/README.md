# R03 PPA candidate — ISOLATED, NOT ACTIVE

Typed two-tier PPA ledger candidate (annual period axis, Decimal, fail-closed).
Adapted from R01A (`feat/r01a-ppa-tiered-independent-core` @ `4cace462`) and extended
with: per-tier independent indexation, explicit cap-application hypothesis (Q4),
merchant UNSOLD mode, CfD settlement overlay (no extra physical sale), FLH cap units
with mandatory denominator metadata, per-period provenance.

**NOT active.  NOT imported by any product code.  NOT reference-verified.**
Q1-Q6 are open owner decisions; every emitted result carries
`approved_for_finco=False` / `SEMANTICS_UNVERIFIED` / `SYNTHETIC_ORACLE_ONLY`.

Schema surface (minimum per R03 contract §4.1):

- `CAP_MODE` = `YEARLY_ABSOLUTE | LIFE_ABSOLUTE | YEARLY_INCREMENTAL | LIFE_INCREMENTAL`
- `CAP_APPLICATION` = `AFTER_SHARE | BEFORE_SHARE` (Q4 hypotheses, explicit, no default)
- `TierPrice.mode` = `FIXED | INDEXED` (per-tier independent; dated curve deferred)
- `MerchantSpec.mode` = `MERCHANT_PRICE | UNSOLD`; missing price for a covered year is
  `EVIDENCE_MISSING` (never zero-fill)
- `Quantity.unit` = `MWh | GWh | FLH` (FLH requires `denominator_mw` metadata; bare
  2250-style numbers without units are refused)
- `CfdOverlay` = settlement-only `(strike - reference) x contracted MWh`
- Per-period `provenance` map with `approved_for_finco=False`

Product code must never import this package in this task.  Tests live in
`tests/r03_ppa_core/` with an independent `fractions.Fraction` oracle.
