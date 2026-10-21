# V9-P2a / OD-R — Correction F, Review Fix A: final evidence contract hardening

**Status: UNAPPROVED financial candidate, local only (`local/v9p2a-correction-e`).** Not pushed; no governance wiring or
repin; no owner approval claimed; canonical default unchanged; OD-R release-closed.

Preflight (live): main `82fb309cede335303e3632fc4dfb0e2ad7f9263b` (no financial-path change since `591ea192`; 12 commits ahead
of the candidate's base — recorded as Stage 2 drift, not synchronised); PR #332 head `32b9478f`; local chain
`32b9478f → db92728d → a32ad575 → 971aa4f1 → 7f6a2e6d → (this fix)`.

## 1. Confirmed issues and corrections (`financial_engine/shl/maturity_authority.py` only)

| Issue | Defect at `7f6a2e6d` (reproduced, real engine) | Correction |
|---|---|---|
| G2A role cardinality | two distinct evidence tokens with valid passes under one required role were both accepted | exactly one authoritative registration per required role; more → `ODR_FINAL_EVIDENCE_CONTRADICTORY: <role> registered N times`; token re-registration still `DUPLICATE`; provisional / superseded evidence still diagnostic |
| Waterfall schedule identity | float `==` (`+0.0 == -0.0`), dictionaries silently collapsed duplicate indices, `zip` truncated misaligned vectors, coverage limited to indices present on both sides, registration maturity trusted | registration rejects misaligned vectors, non-int / non-strictly-increasing (duplicate or reordered) indices and non-float values; rows stored as exact IEEE-754 binary64 bytes; returned **operating** rows (construction rows excluded by their `is_construction` flag) with a duplicated period are contradictory; match requires registration maturity = the returned state's contractual SHL maturity (`return_summary.terminal.shareholder_loan`), complete ordered coverage of every operating period up to it on both sides, and bit-exact closing / gross interest / principal |
| State identity completeness | `required_final_checks` returned no G2A role for a `ProjectFinancingResult` with positive SHL liability but no final SHL schedule (inferred inapplicability) | such a state is `ODR_UNSUPPORTED_FINANCING` (structurally inconsistent); digest scope unchanged (no counterexample showed a digest gap) |

Before / after (same final controls; `tests/test_v9p2a_odr_finalization_contract.py::test_rfa_*`):
at `7f6a2e6d` **7 failed** — every one `DID NOT RAISE` (accepted): duplicate final role, checked `-0.0`, reordered rows,
mismatched maturity, duplicate returned row, returned `-0.0`, liability without schedule; duplicate index, missing row and
truncated vector were already rejected (incidentally). After the fix **14 / 14 pass**, including the unchanged valid
schedule and the legitimate identical repeat.

Real-engine shape found while fixing: the returned waterfall legitimately contains construction row 4 and operating
period 4 (different numbering domains). Duplicate detection is therefore scoped to operating rows, never collapsed.

## 2. Numerical acceptance and tests

See the results section appended after the acceptance run.

## 3. Unchanged

Senior sizing / sculpting, SHL economics and the maturity predicate, IDC / construction funding, DSRA / DSRF, tax / CFADS /
waterfall economics, cash sweep, tolerances, canonical default, OD-R release-closed status, historical guards and accepted
hashes, the Correction B proposal module. Only `maturity_authority.py` and its contract tests changed in this fix.
