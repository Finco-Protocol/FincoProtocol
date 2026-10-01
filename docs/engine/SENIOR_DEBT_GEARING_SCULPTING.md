# Senior debt — sizing policy, repayment policy, and optional full-tenor sculpting (M-6)

Scope: `financial_engine/senior_debt/**` (engine policy and tests only). Not exposed in any UI, API, MCP,
Radar, Yield, Verify or Bridge surface in this change.

## Sizing policy is not repayment policy

| Sizing mode | Debt size | Repayment |
|---|---|---|
| `DSCR_SCULPTED` | DSCR capacity (backward induction on CFADS) | DSCR-sculpted |
| `GEARING_CAP` | `eligible_project_cost × maximum_gearing` | **`LEVEL_PRINCIPAL` (default)** or, by explicit opt-in, **`DSCR_SCULPTED`** |
| `COMBINED_MINIMUM` | `min(DSCR capacity, gearing cap)` | DSCR-sculpted (never level principal, even when gearing binds) |
| `EXPLICIT_SCHEDULE` | `opening_debt_balance_keur` | the explicit principal schedule |

`COMBINED_MINIMUM` and `GEARING_CAP + DSCR_SCULPTED` are **different things**: the first resizes debt to the
smaller of two capacities; the second never resizes, it only changes how a gearing-sized balance is repaid.

## Current default (unchanged)

`GEARING_CAP` sizing → `LEVEL_PRINCIPAL` repayment. `SeniorDebtPolicy.gearing_cap_repayment_method` defaults to
`GearingCapRepaymentMethod.LEVEL_PRINCIPAL`; every existing policy and every reference vertical keeps its
current result. The solver paths for the other three modes are untouched (`_forward_roll` gains a
`debt_service_scale` argument that defaults to `1.0`, and `1.0 × x == x` exactly, so their outputs are
bit-identical; `tests/m6_baseline_pre_change.json` pins values captured from the pre-change solver).

## Optional policy: `GEARING_CAP` + `DSCR_SCULPTED`

`gearing_cap_repayment_method = GearingCapRepaymentMethod.DSCR_SCULPTED`, valid only with
`sizing_mode = GEARING_CAP` (any other combination is `INVALID_INPUT`; a raw string is rejected).

- **Debt size is fixed** at `eligible_project_cost × maximum_gearing`. It is never reduced to DSCR capacity.
- **Full tenor.** The canonical DSCR roll pays *all* the debt service the DSCR allows, which would retire a
  balance smaller than DSCR capacity early. To spread it over the whole repayment window every period uses the
  same factor `k` on its DSCR- and availability-constrained debt-service budget
  `scaled_budget[p] = max(0, CFADS[p]/DSCR[p]) · availability[p] · k`, with `k` the smallest value in `(0, 1]`
  that repays the balance exactly at maturity (fixed-length bisection; deterministic).
  Where that scaled budget is fully consumed, realised DSCR equals
  `target_dscr[p] / (availability_fraction[p] · k)`; with full availability this reduces to `target_dscr / k`.
  A period clipped by the remaining balance (typically the final period) may realise a higher DSCR.
- Reused canonical primitives: per-period DSCR targets, debt-service availability, rolling-balance interest,
  day count, repayment start and maturity, the tax ↔ CFADS fixed point and the finalisation handshake
  (`_finalise_authoritative`, given the same full-tenor roll).
- **Handshake:** the interest returned in the schedule is exactly the interest handed to the last tax/CFADS call.
- **Fails closed.** If CFADS cannot repay the balance inside `CFADS / target_dscr` the result is
  `DSCR_SCULPTING_INFEASIBLE` (existing typed reason), `is_authoritative = False`. The solver does not resize the
  debt, capitalise interest, extend maturity, lower the DSCR target, invent CFADS or add sponsor funding.
  A period whose interest alone exceeds its allowed debt service is infeasible even when a balloon is permitted.
- **`permit_terminal_balloon`** keeps its existing meaning: when `True`, a residual balance at maturity is a
  disclosed balloon (visible in the closing balance) and is authoritative, exactly as for the other sculpted
  modes; when `False`, a residual balance is infeasible.

## Latent feasibility protection — scope decision

The new mode is fully guarded. For the **default** `GEARING_CAP` (level principal) and `EXPLICIT_SCHEDULE`:

- *Maturity feasibility* is already enforced: level principal repays by construction; explicit schedules must lie
  inside the repayment window, be non-negative and not exceed the opening balance, and an under-repaid schedule is
  `TERMINAL_BALANCE_NOT_ALLOWED` unless a balloon is permitted.
- *Cash-service feasibility* (debt service ≤ CFADS) is **not** checked today: neither mode sizes to a DSCR, so a
  schedule with DSCR < 1 is still reported `CONVERGED`. Neither mode is reachable from the product adapter
  (`project_adapter.py` maps only `DSCR_SCULPTED` and `COMBINED_MINIMUM`). Adding the guard would change the
  authority class of such historical results and needs a typed reason of its own, so it is **deferred** to a
  separate reviewed change. `test_characterisation_default_gearing_does_not_check_cash_service_today` records the
  current behaviour so a later change is deliberate.

## Provenance

`compute_senior_debt_fingerprint` includes `gearing_cap_repayment_method` only when it is not the default, so every
existing fingerprint is unchanged and an opted-in policy fingerprints differently.
