# T01-D — FINAL REPORT (tax reference registry foundation + governed integration)

**Branch:** `feat/t01d-tax-reference-registry-foundation` · **Foundation commit:** `52a5793ce0a9fed04745efe904353a5fc662a52e` (tree `66e86ec23d04bc4ec19965d71202cde5e0e8aec1`, parent = main `d295922b…` at preflight) · **Governed integration:** merge of main `4e22f330…` (#430) + this cohort (manifest `docs/tax_reference_registry/SOURCE_SUCCESSOR.json`).

## Scope

New, self-contained, offline, reference-only namespace: `tax_reference_registry/**` + `tests/tax_reference_registry/**`. No production imports (repo-scan test inside the package suite); no `financial_engine/`, `finco_core/`, `app/`, `.github/` path touched; #430 paths untouched.

## Delivered capabilities

1. Typed versioned records (`LawStatus`/`VerificationStatus`/`TaxCategory`/`RateScheduleMode`/`AssetClass`); canonical mapping from the T01-B/T01-C 35-column harvest vocabulary; **`IN_FORCE` never implies verified**; only `PRIMARY_CONFIRMED` counts as verified.
2. Deterministic 35-column CSV importer with per-row rejection reasons (duplicate ids, overlapping windows, text rates never defaulted, unparsed units/currencies, false verified statuses, missing provenance, private-marker scan, format errors).
3. `NO_IMPLICIT_FX` currency policy: cross-currency comparisons raise without an explicitly pinned FX table.
4. Registry: compare (added/removed/changed/expired + verification changes; no overwrites, no deduced updates), explain (citations + evidence status, never a computed rate), export-candidates (`NON_ACTIVATABLE_REFERENCE_ONLY`, whitelist-only).
5. `activate_country` / `get_effective_run_profile` fail CLOSED unconditionally; all 34 country profiles CANDIDATE_NOT_ACTIVE; no automatic country fallback.
6. Offline CLI: `python -m tax_reference_registry validate|compare|explain|export-candidates` (stdlib-only, deterministic sorted JSON).

## Reconciliation (private corpus, run offline by the operator)

34 countries / 634 rows read = 593 valid + 41 rejected per-row (7 VALUE_UNPARSED text rates, 34 FALSE_VERIFIED_STATUS). Baseline preservation: compare 19-baseline → 34-combined = added 232 / changed 0 / removed 0 / verification changes 0. The full private corpus is NOT committed; reconciliation requires the operator's private path.

## No-activation statement

No country activation, no FX defaults, no engine hook, no run-profile selection exists in this phase. The next integration contract (this directory) lists the owner decisions (OD-FX-1, OD-ACT-1/2, OD-DATA-1) that must close first.
