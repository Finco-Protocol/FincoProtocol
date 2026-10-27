# FIN-V2-R1 — Reserve Coverage: Integration Handoff

Branch `feat/fin-v2-r1-reserve-coverage` (built on `main` 1f25903, PR #390 merged). Target: FIN-V2 Integration RC
(#390 merged, #391, #392, this PR, #388). **Not merged, not deployed.**

## 0. Preflight and open item

| Item | Status at coding time |
|---|---|
| main HEAD / merge-base | `1f25903e7ed0bb8142f4e9f40d7eade58a746bf5` / same |
| #390 | MERGED (Senior debt evidence) |
| #388, #391, #392 | OPEN drafts (heads `6aaaaa5`, `0bf3ba2`, `511390e`) |
| `FINCO_MODEL_RESERVE_POLICY_OWNER_DELTA_2026-10-27.zip` | **NOT AVAILABLE in the session** (not in the repo or on disk). The binding Owner policy could not be read. Implementation follows the assigned prompt text only. **Owner must confirm the items in §7 against the zip before activation.** |

## 1. R0 — what the defect actually was (measured, not assumed)

`automatic_peak` was persisted as `dsra_support_mode=NONE, dsra_target_policy=None, dsra_months=N, requirement=0`.
That exact signature is what the **H-1 generic financing policy** (`generic_product_policy._is_untouched`) recognises as
"derive an automatic PEAK_FORWARD Cash DSRA and fund it by fixed point". So under the default Run policy the reserve *was*
realised (solar 12 months: initial DSRA 4 773.63 kEUR, Senior 29 134.06). But the same inputs also read as "no reserve"
(NONE) and, because `None` means FIXED_AMOUNT in the adapter, nothing in the inputs distinguished the three: under a
disabled/other financing policy the selection silently carried **0 funding** (probe: 12-month selection, policy disabled
-> DSRA 0.0). The reference projects themselves are already "automatic, 6 months" through the same path.

Fix (no economics changed; reference Runs bit-identical):

* `financial_engine/dsra/reserve_authority.py` — explicit `ReservePolicyKind` {NONE, FIXED_AMOUNT, FORWARD, PEAK_FORWARD},
  `ReservePolicyVersion` {STATIC_V0, SHORTCUT_V0, CALENDAR_V1}, `ReserveActivation` (incl. `GATED`), `classify_financing`,
  `selection_from_editor`, `assert_selection_realised`, typed `ReserveAuthorityError(code)`.
* `bankability_config.apply_config` now requests an explicit selection and **refuses** (typed, at Save and at Run) any
  selection whose resulting inputs would not carry the same kind / instrument / months. `parse_config` rejects gated modes
  (`automatic_forward`, `automatic_forward_calendar`, `automatic_peak_forward_calendar`) with
  `RESERVE_MODE_GATED` / `RESERVE_CALENDAR_V1_FUNDING_UNRESOLVED`, so they are never persisted.
* `build_view` additionally returns `reserve_selection` (effective classification, gated modes, gate reason).
* The persisted JSON (`bankability_config_json`) is unchanged in shape; historical projects parse and resolve exactly as before.
* Not done on purpose: raising inside `run_clean_production` when H-1 is disabled — the existing H-1 suite runs the
  reference with the policy disabled deliberately. The disabled case is reported by the evidence block instead
  (`recorded_cash_dsra_status = NO_CASH_DSRA_RECORDED`, never 0).

## 2. Versioned policy and semantics

`FORWARD_CALENDAR_COVERAGE_V1` (`financial_engine/dsra/forward_coverage.py`). Test date `T` = end of each operating period
plus the COD date (initial requirement). Window `(T, W]`, `W = T + m` calendar months, end-of-month preserving
(31-Dec+6m = 30-Jun; 30-Jun+6m = 31-Dec). Debt service is due on period end. Basis: the **final** Senior debt-service schedule.

| Convention | Rule | 9 months of semiannual service |
|---|---|---|
| `DUE_DATE_WINDOW` | payment covered in full iff its due date is in `(T, W]` | one payment (next due is at +12) |
| `PRORATED_PERIOD` | each period × share of its days inside the window | one full period + (92/184) of the next |

The convention is a **required argument; there is no default.** Prorating is a liquidity smoothing, not a claim that the
prorated cash is contractually due in the window. `FORWARD` = requirement on each date. `PEAK_FORWARD` = max over all test dates
(including COD), held while further debt service is due, 0 afterwards. Unavailable data is `None` + typed status
(`FUTURE_DEBT_SERVICE_MISSING`, `BEYOND_SCHEDULE_UNPROVEN_MATURITY`); `0.0` only with `NO_FURTHER_DEBT_SERVICE`
(zero Senior, early extinguishment, after final payment). Negative / non-finite / non-numeric inputs raise
`DSRA_COVERAGE_*`.

Historical contracts are untouched and now named: `STATIC_V0` (scalar) and `SHORTCUT_V0`
(`next_service × months × periods_per_year / 12`, `target.py` builder unchanged, pinned by a float.hex test).
For semiannual, 6 months the two agree exactly (tested); at 9 months they differ whenever future service differs.

## 3. Implemented vs gated

| Capability | State |
|---|---|
| Typed reserve authority, R0 guard, Save->Reload->Run | **Implemented, tested** |
| CALENDAR_V1 FORWARD / PEAK_FORWARD requirement (6/9/12, both conventions) | **Implemented, independently verified** |
| Read-only Reserve Coverage evidence | **Implemented** (`app/run_integrity/reserve_coverage_evidence.py`), on demand; not written into Run payloads |
| Engine execution of CALENDAR_V1 targets / automatic COD funding under V1 | **GATED — UNAVAILABLE** (§5) |
| DSRF draw/fees/interest/sweep, hybrid, Junior DSRA, SHL, XIRR/NPV, React | Out of scope, untouched |

Automatic Cash DSRA under CALENDAR_V1 is **not** claimed operational.

## 4. Source ownership and overlapping paths

New: `financial_engine/dsra/forward_coverage.py`, `financial_engine/dsra/reserve_authority.py`,
`app/run_integrity/reserve_coverage_evidence.py`, two test files, this doc.
Edited: `app/workbook/bankability_config.py` (+~25 lines), `financial_engine/dsra/target.py` (comment/constants only).
**Not touched:** `financial_engine/adapters/project_inputs.py`, `finco_core/inputs/_models.py` (#391), `app/api/project_runner.py`
(#391 also edits it), `app/run_integrity/senior_debt_evidence.py` (#390, only imported), any `frontend/` (#388).
Checked against #391 (73 files) and #392 (15 files): no shared path. `#392` shares the editor/Senior concerns only logically.

Merge contract for #391 when wiring V1 later: the adapter currently maps `dsra_target_policy` strings through
`DsraTargetPolicy`; add the V1 policy strings there and keep `classify_financing` as the single decoder.

## 5. Initial Cash DSRA funding — decision and blocker

Chain: reserve requirement -> Project Uses -> gearing capacity -> Senior sizing -> Senior DS -> requirement.
Existing contracts **do** resolve it consistently, but only for SHORTCUT_V0: `generic_product_policy.run_with_generic_financing_policy`
iterates `funding = peak(next-period DS) × m × 2/12` to a 1e-6 kEUR residual; funding is a Project Use in
`project_uses.reserve_account_funding_keur`, funded by the same construction sources (no CAPEX double count; the
COD handshake `resolver == ProjectUses == CashDsraInput == opening balance` holds). There is no single-pass
approximation and no hidden circularity there; I did not add one for V1.

**Blocker for V1 activation (needs a methodological decision, therefore not built):**
1. Owner ratifies the convention (`DUE_DATE_WINDOW` vs `PRORATED_PERIOD`) — currently unratified.
2. A versioned fixed-point that replaces the H-1 target function with the V1 peak (same loop, same tolerance, same
   Project Use) and a V1 policy string in the adapter / `CashDsraInput` (#391-owned files).
3. Orchestrator hook to build the V1 schedule from the final DS (today `build_dsra_required_balance_schedule` only knows V0).
4. Acceptance: opening balance == Sources & Uses DSRA use == V1 COD requirement (peak for PEAK_FORWARD); Senior unchanged
   except through that Project Use; waterfall conservation identities.
Evidence today shows the exact gap: for 6 months the DUE_DATE_WINDOW **peak equals the recorded H-1 funding to 1e-9**
(all four verticals, tested), and the COD-date requirement is far below the funded peak (e.g. solar 1 117 vs 1 934 kEUR),
i.e. PEAK_FORWARD (hold the peak from COD) and FORWARD (COD requirement) are different funding decisions.

## 6. Numerical oracles and baselines

Oracles (`tests/test_fin_v2_r1_reserve_coverage.py`) re-derive month arithmetic from `calendar.monthrange` and window
coverage from day-ordinal set intersection; hand values for 6/9/12 months; irregular quarterly/odd boundaries; stub first
period (COD 1-Mar); final payment; early extinguishment; missing period; zero Senior; negative/NaN/inf/bool/str; invalid months.
Four-vertical Run tests recompute every requirement row from the Run's raw Senior DS and period dates.

Existing reference identities (float.hex, no policy selected; pinned in the test):

| Vertical | initial DSRA | Senior | Total uses | Σ Senior DS |
|---|---|---|---|---|
| Solar | `0x1.e3619de423a32p+10` | `0x1.a59d53a2ff90ep+14` | `0x1.19138d17550b4p+15` | `0x1.1bb100f21f480p+15` |
| Wind | `0x1.78858e2bfe403p+11` | `0x1.1d3250e010c3bp+15` | `0x1.7c431680165a4p+15` | `0x1.730af03d2676fp+15` |
| Data Center | `0x1.5a8e14c04b205p+12` | `0x1.c855ec7065648p+15` | `0x1.96a44b9bf5b39p+17` | `0x1.3120ea853867fp+16` |
| EV Charging | `0x1.7ac2d235989bcp+9` | `0x1.94d5a429cc875p+12` | `0x1.37694333d8681p+13` | `0x1.0133ca50bd657p+13` |

## 7. React / integration agent (after #388 merges)

* Reserve control: read `view.reserve_selection.effective` (`kind`, `version`, `activation`, `coverage_months`) instead of the
  boolean `automatic_reserve`; show `gated_modes` / `gate_reason` as disabled options with the typed reason; surface
  `ReserveAuthorityError.code` from Save.
* Reserve Coverage panel: call `build_from_clean_run(run, coverage_months=m)`; render both conventions side by side
  (`conventions.due_date_window` / `.prorated_period`), `peak_reserve_requirement_keur`, per-row `required_reserve_keur`,
  `recorded_cash_dsra_balance_keur`, `reserve_shortfall_keur`, `excess_coverage_keur`, contractual maturity vs actual payoff.
  `null` means unavailable — never render as 0. Committed Runs: `project_reserve_coverage_evidence` -> `NOT_RECORDED`.
* To record it in Run payloads (like #390's block) add a one-line call in `project_runner` after #391 merges; deliberately
  not done here because it would change payload identity.

Owner confirmations needed against the (unreadable) policy zip: months set {6,9,12} (editor still accepts 0-12 for V0),
convention choice, whether PEAK_FORWARD holds from COD, treatment of the COD-date requirement as the opening funding.

## 8. Future R2 / R3 compatibility

`ReserveSelection.instrument` already separates `NONE | CASH_DSRA | DSRF`; DSRF is classified but unchanged. A hybrid
DSRA/DSRF split can add a `split` field to `ReserveSelection` and a new `ReservePolicyKind` without altering V0/V1.
`ReservePolicyVersion` is the extension point for V2+. The V1 requirement function is instrument-agnostic (it returns the
reserve amount to be supported), so DSRF commitment sufficiency (R2) can consume the same schedule.
