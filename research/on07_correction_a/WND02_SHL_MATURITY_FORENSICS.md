# WND-02 SHL maturity forensics (main db504f6; true route; disposable DBs; nothing in the repo changed)

## Verdict
Two **independent, layered** causes. Neither is a "one-field-at-a-time" artefact; the first masks the second.

| Layer | Finding | Class |
|---|---|---|
| L1 | On a **reference-seeded** project the SHL maturity/eligibility indices are fixed at creation from the reference's own timeline and are **not re-derived** when `construction_months`, `horizon_years` or `senior_tenor_years` are edited. Wind reference = 20 months / 27 y => maturity index 57. WND-02 (18 m / 25 y) has period grid 0..52, so index 57 is off-grid => `SHL_MATURITY_NOT_ON_PERIOD_GRID_FAILS_CLOSED`. | **B/C: valid inputs transformed inconsistently by the route** (a reproducible route/contract defect, not an input error). The engine's fail-closed guard works as designed. |
| L2 | With the indices correct (re-derived in memory) WND-02 is still refused: `SHL_MATURITY_RESIDUAL_FAILS_CLOSED`, 62,453 kEUR of SHL left at maturity (index 52). Debt is DSCR-sized (1.35x, 12 y), the 88% ceiling is far from binding, so the sponsor remainder is SHL at 8% that compounds and CFADS cannot retire it. | **A: the fixture, as specified, violates a documented engine precondition** (SHL must be repayable by maturity; engine is fail-closed). Economics are too weak (EBITDA/CAPEX ~9% vs WND-01 ~14%). |

## Exact invariant
`shl_maturity_period_index` must lie on the engine period grid, and the closing SHL balance at maturity must be ~0 (`financial_engine/shl/production.py:~481` and the residual check). The generic policy `app/generic_shl_policy.py::resolve_generic_shl_policy` recomputes `maturity = ceil(construction_months/6) + 2*horizon_years - 1` and `elig_start = ceil(construction_months/6) + 2*senior_tenor_years` from the FINAL inputs, but is applied only when there is **no** base template (`app/input_adapter.py`, `if base_inputs is None and project_type in {"Solar","Wind"}`). Reference-seeded projects carry the reference's stored values (`app/project_factories.py` `_wind_shl_maturity`, `_solar_shl_maturity`).

## Intermediate indices (true-route materialised inputs, `shl_e1.json`)
| Fixture | construction / horizon / tenor | grid last | stored SHL maturity | policy formula | on grid | stored elig start vs formula |
|---|---|---|---|---|---|---|
| SOL-01 | 14 / 25 / 15 | 52 | 52 | 52 | yes | equal |
| SOL-02 | 18 / 25 / 18 | 52 | 52 | 52 | yes | **differs** (tenor edited, stored elig not re-derived) |
| WND-01 | 20 / 27 / 16 | 57 | 57 | 57 | yes | **differs** (same) |
| WND-02 | 18 / 25 / 12 | **52** | **57** | **52** | **NO** | differs |
SOL-02 and WND-01 run only because their stored maturity coincidentally lies on the grid; their eligibility start is nevertheless stale (documented, not corrected here).

## Minimal reproducible (`wnd_minimal_repro.py`, no fixture inputs)
Fresh reference-seeded Wind project (reference defaults 20 m / 27 y / tenor 15, stored maturity 57), **one Save-All cell** `horizon_years`, materialise as the Run route does, run (`min_wind.json`):
| horizon | grid last | stored maturity | as materialised | maturity re-derived (DIAGNOSTIC) |
|---|---|---|---|---|
| 23-26 | 49-55 | 57 | **REFUSED** `SHL_MATURITY_NOT_ON_PERIOD_GRID_FAILS_CLOSED` | RUN_OK |
| 27 | 57 | 57 | RUN_OK | RUN_OK |
| 28-30 | 59-63 | 57 | RUN_OK **(with a stale maturity: SHL matures mid-life)** | RUN_OK |
Solar reference (14 m / 25 y, stored 52): identical pattern (`min_solar.json`): horizon 21-24 refused, 25-28 run. So the defect is generic to reference-seeded Solar/Wind, and **lengthening the horizon silently runs with a wrong SHL maturity** (no fail-closed signal). That silent direction is the more important owner issue.

## Why one-at-a-time probing misled (previous report)
Changing tenor, gearing, COD, construction or capacity on WND-02 never changes the stored maturity 57 relative to a grid ending at 52, so every probe hit L1 and L2 stayed hidden. Only after the grid is made consistent does L2 appear.

## L2 levers (route-consistent timeline 20 m / 27 y; `wnd02_levers.json`, DIAGNOSTIC)
- Unaltered: `SHL_MATURITY_RESIDUAL_FAILS_CLOSED` (62,130 kEUR).
- CAPEX bisection (all else as WND-02): RUN_OK at <= 38,375 kEUR, refused at >= 38,406 kEUR (boundary ~38.4 MEUR, -26%).
- PPA tariff bisection: RUN_OK at >= 114.19, refused at <= 113.22 EUR/MWh (boundary ~114, +97%).

## WND-02-R (clearly labelled replacement; original WND-02 stays as the mandatory fail-closed negative fixture)
Changed inputs only: `construction_months` 18->20, `horizon_years` 25->27 (route-consistent timeline; financial close derives to 2029-11-01), `total_capex_keur` 52,000->36,000 (-30.8%, ~6% margin below the 38.4 MEUR boundary). Everything else is the original WND-02 (88% ceiling, 12 y tenor, DSCR 1.35x, 55% PPA 58 EUR/MWh 7 y, merchant curve, 4% merchant balancing, OPEX 1,150).
Result (3 fresh DBs identical, digest `bf5ed81eabfdfa27`): RUN_OK, executed gearing **50.07%** (ceiling 88%), senior 19,537 kEUR, min DSCR 1.478935, Total Sponsor XIRR 8.6222%, lock-up periods 0, Run Integrity PASS.
**Limitation:** the stress objective ("high leverage into the >85% band") is **not preserved** in executed terms: DSCR sizing binds (capacity 19.5 MEUR vs gearing capacity 34.3 MEUR). Preserving executed leverage would require economics the engine's DSCR sizing does not support at this tariff/yield; that is an owner decision (OD-3), not something to engineer here. WND-02-R is a regression fixture for the sculpted/merchant/short-tenor path, not the original stress case.

## Not done / owner-gated
No engine, financial-policy or product change. Whether the route should (a) re-derive SHL indices from edited timeline inputs, (b) refuse any horizon/construction/tenor edit that desynchronises them, or (c) keep reference calibration, is a policy decision (OD-1). Evidence files: `shl_e1.json`, `min_wind.json`, `min_solar.json`, `wnd02_levers.json`, `wnd02_rederived.json`; scripts in `harness/`.
