# FINCO Model — F0-P1 Integrity Correction A

**Date:** 2026-10-09  
**Repository:** `Finco-Protocol/FincoProtocol`  
**Verified branch base:** `ba96bb8229692f8efed7f1f6222a9eea01d8ccb9` (`main` at branch creation)  
**Feature branch:** `fix/model-f0-developer-uses-integrity`  
**Disposition:** Draft only; independent exact-head review and full CI required. **NO MERGE / NO DEPLOY.**

## Root cause and pre-fix reproduction

`financial_engine/financing/project_uses.py` adds developer reimbursement and
developer fee to Total Project Uses. `build_sources_and_uses` itemises both
as independent component fields. However, the existing
`app/run_integrity/checks.py::check_sources_equal_uses` omitted those fields
from its subtotal of Uses.

Given base uses `B`, reimbursement `R`, and fee `F`, the canonical
Total Uses was `B + R + F` while the Integrity reconstruction used `B`.
With a correctly balanced stack this generated `SOURCES_USES_MISMATCH`
where `R + F > 1e-6 kEUR`, despite no actual funding imbalance.

No financing formula, source allocation, model output, or
`build_sources_and_uses` implementation is changed by this PR.

## Minimum correction

- Include `development_cost_reimbursement_keur` and `developer_fee_keur`
  **exactly once** in `_USE_KEYS`; leave `other_uses_keur` unchanged.
- Validate both published developer fields as explicit finite, non-boolean,
  nonnegative numeric kEUR values.
- Missing either value returns `UNAVAILABLE` with
  `DEVELOPER_USES_EVIDENCE_MISSING`; malformed/non-finite/negative values
  return `UNAVAILABLE` with `DEVELOPER_USES_EVIDENCE_INVALID`.
- Preserve normal genuine-funding failure `SOURCES_USES_MISMATCH` and the
  independent per-construction-period Sources/Uses residual check.
- Preserve existing `1e-6 kEUR` tolerance; never infer a missing amount
  from current Working Copy, display state or a fabricated zero.

## Historical evidence contract

`RUN_INTEGRITY_EVIDENCE_V1` is **unchanged**. The existing evidence writer
already persisted both developer-use fields from the canonical
`build_sources_and_uses` dataclass; this change introduces no new data field
to current persisted evidence and therefore requires no migration or
schema version bump.

For an older V1 payload missing one or both fields, a matching SHA-256
digest only proves that those specific old bytes are intact. It does not
prove Developer Economics was inactive. The old evidence remains immutable:
`EVIDENCE_DIGEST` may PASS, but `SOURCES_EQUAL_USES` is deliberately
`UNAVAILABLE`, making the overall result `INCOMPLETE` in the
absence of other failures. No old Run History record is re-hashed,
rewritten, backfilled or recalculated. A literal zero recorded in both
fields is distinguished from missing data and is checked normally.

## Regression coverage

The new `tests/test_f0_developer_uses_integrity.py` uses
`run_clean_production` and the existing public synthetic Solar/Wind
factories, reads `build_run_integrity_evidence` through a JSON round-trip
and compares the output directly with the canonical Sources & Uses
builder. The complete matrix covers:

1. Solar baseline — developer uses both zero.
2. Wind baseline — developer uses both zero.
3. Solar — positive reimbursement only.
4. Wind — positive developer fee only.
5. Solar — both developer fields positive.
6. Positive component with unchanged recorded total => mismatch FAIL.
7. Corrupted recorded Sources or Uses total => mismatch FAIL.
8. Missing developer component => UNAVAILABLE, never assumed zero.
9. Null, string, boolean, negative, NaN and infinity developer fields
   => UNAVAILABLE, never PASS.
10. Simulated historical V1 evidence with missing fields preserves its
    own committed digest and produces an INCOMPLETE verdict.
11. Corrupted construction-period funding residual => mismatch FAIL.
12. Calling Integrity is read-only: no engine re-execution, input hash,
    canonical financing result or recorded evidence mutation.

Each positive real-run variant also independently proves the **old**
component-sum residual algebra against the actual canonical result.
No mocked KPI snapshots or reference-baseline edits are used.

### Execution caveat

At the time of authoring, GitHub repository cloning and local pytest
execution from this environment are not possible because direct
`github.com` DNS resolution fails. Test code has been committed for
CI and independent local execution; **test PASS is not claimed from
source inspection alone**. All canonical economic parity and five
exact-head GitHub workflows must be verified before merge approval.

Recommended command for an independently provisioned clean checkout:

```bash
python -m pytest -q tests/test_f0_developer_uses_integrity.py tests/test_h4b_run_integrity_checks.py tests/test_developer_economics_v1.py
```

Continue with applicable Sources & Uses, construction, Solar/Wind
reference and V2 Run History regression suites; verify the pytest process
exits normally and public-safety checks pass.

## Frozen scope

Only:

- `app/run_integrity/checks.py`
- `tests/test_f0_developer_uses_integrity.py`
- `docs/model_v2/FINANCING_F0_P1_INTEGRITY_CORRECTION.md`

Expected ZERO DIFF under `financial_engine/**`, `finco_core/**`,
`domain/**`, `app/v2/**`, `app/workbook/**`,
`app/api/project_runner.py`, `app/input_adapter.py`,
`app/templates/**`, `main_web.py` and all parallel F1/F2 code.
No migrations, infrastructure, crypto, fees, tax, SHL, IRR, DSRA,
interest-rate, maturity or debt-sizing changes.

## Parallel branch status at branch creation

- PR #229 (F3 foundation): merged.
- PR #230 (F1 Sources & Uses): open/draft, separate source ownership.
- PR #231 (F2 Bankability): open/draft, separate source ownership.

Neither parallel branch is modified. Independent review must reconfirm
their current heads, the exact PR merge-base/divergence, five final
exact-head CI workflow conclusions, full normal pytest exit, and
zero-diff scope before recommending a normal merge.

**Final gate: NO MERGE until independent verification confirms the
financial cases, historical compatibility and all exact-head CI checks.**
