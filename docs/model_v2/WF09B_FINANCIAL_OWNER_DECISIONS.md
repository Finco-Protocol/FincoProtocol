# WF-09B — Financial Owner Decision Packet

All decisions are **OPEN**. The candidate encodes none: each is supplied as explicit
evidence (receipt field) or results in UNAVAILABLE. Supplied convention text is a
receipt, not approval. No self-approval.

| ID | Decision | Candidate behaviour until decided |
|---|---|---|
| C-01 | Valuation date and discount-factor origin (rate source, WACC vs project rate, pre-/after-tax debt/equity interpretation) | factors are supplied per period; convention and rate source must be non-empty; nothing derived |
| C-02 | Period timing convention (beginning / end / mid / actual dates), stub and day-count handling, annual-vs-quarterly rate conversion | no conversion; one supplied factor per aligned period |
| C-03 | Real vs nominal cost / rate pairing and currency / FX date | receipt basis must match; non-EUR rejected; no inflation or FX applied |
| C-04 | Delivered-energy boundary for Solar/Wind (exported at POI vs metered production), treatment of curtailment, losses, auxiliary consumption, commissioning energy | one boundary per vertical; breakdown accepted only if it reconciles to supplied delivered energy; nothing reconstructed |
| C-05 | DEVEX / CAPEX / IDC boundary (what is capitalised, depreciation vs cash) | capitalised items are declared via `contains`; double counting rejected; depreciation never a cost |
| C-06 | Levered metric definition (interest / fee / IDC timing, treatment of principal and equity funding, whether the metric is an equity-required price) | principal, drawdown, equity and distributions are excluded memos only |
| C-07 | Tax: cash vs accounting tax, deductibility, refunds, terminal proceeds; any tax-on-required-price solve | only cash tax paid / refund (signed) is a cost; no endogenous solve |
| C-08 | BESS LCOS: charging tariffs, import / grid fees, auxiliary consumption, energy boundary (AC discharge), inventory and residual treatment | explicit paid charging required; net-spread-only and RTE haircuts rejected |
| C-09 | BESS augmentation / lifecycle replacement CAPEX posting and funding | any such line, or unknown status, ⇒ UNAVAILABLE |
| C-10 | Data Center and EV Charging economic denominators (MWh may not be the appropriate unit) | UNAVAILABLE (`WF09B_VERTICAL_DENOMINATOR_NOT_APPROVED`) |
| C-11 | Reconciliation tolerance and display rounding / published precision | 1e-30 internal tolerance only; no rounding or published figure |
| C-12 | Evidence attestation: who certifies Run freshness, evidence completeness and calculation authority | supplied flags; stale / incomplete ⇒ UNAVAILABLE |
