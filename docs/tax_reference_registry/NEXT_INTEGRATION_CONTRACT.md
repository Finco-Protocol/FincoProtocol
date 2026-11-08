# NEXT_INTEGRATION_CONTRACT — tax reference registry (after this governed integration)

Audience: the next integration agent + the owner.

## 1. Precondition

#430 (Financing read layer) is merged (main `4e22f330…`). This cohort composes on top of it; the composite cohort registry (`tests/fin_v2_cohorts.py`) now admits exactly the registry paths via `tests/tax_reference_registry_scope.py` (closed set, no wildcard). Any later change to a registry byte requires a new successor slice of this cohort's manifest.

## 2. Minimal next PR (still dormant)

1. Optional read-only app-layer surface calling `registry.explain()` for internal review UIs (no rates to users, no country-selection coupling).
2. Dataset ingestion stays PRIVATE (operator env `TAX_REF_PRIVATE_DATASET`); never committed.

Explicitly NOT permitted: activation flags, FX tables, rate resolution, engine imports, schema migrations, UI country-tax controls.

## 3. Owner decisions blocking any activation path

| # | Decision | Recommendation |
|---|---|---|
| OD-FX-1 | Native-currency comparison vs pinned dated FX table | Keep native comparison; any conversion must be pinned, dated and cited |
| OD-ACT-1 | First jurisdiction to graduate | HR first (parity-reference), PL second (first Wave-A with primary-confirmed headline rates) |
| OD-ACT-2 | Project opt-in mechanics | Explicit per-project opt-in; exact-content owner decision record + tests-side content pin; no country-selection coupling; no silent fallback |
| OD-DATA-1 | The 41 harvest rows rejected by the loader (34 FALSE_VERIFIED_STATUS, 7 VALUE_UNPARSED) | Re-harvest with recorded primary citations / structured rate representation; data confidence is a release blocker for country activation, not for the dormant library |

## 4. Opt-in path (after OD-ACT-1/2)

1. `FINANCIAL_OWNER_TAX_PROFILE_<ISO>_DECISION.md` + exact JSON record + tests-side content pin.
2. Versioned, dated profile blob derived from VALID rows only.
3. Engine wiring in its own governed successor slice (`financial_engine/policies/tax.py`, `financial_engine/tax/engine.py` are protected files).
4. Float-identity clean-Run acceptance: every unflagged project and historical Run bit-identical; profile applies only to opted-in projects.
5. Only then does `activate_country` un-block; until then it raises.

## 5. Invariants

- `IN_FORCE` never implies verified.
- No implicit FX; no default currency.
- `compare` shows changed=[] for the 19-baseline rows unless a dated re-harvest is owner-reviewed.
- All 34 profiles CANDIDATE_NOT_ACTIVE until OD-ACT-1/2 close.
