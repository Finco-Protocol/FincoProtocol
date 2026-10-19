# RC-7B Matched 3/3 — Successor Governance Contract (recognition only, NOT approval)

Status: **INTEGRATED_RELEASE_CLOSED_CANDIDATE — FINANCIAL_OWNER_APPROVAL_REQUIRED — NO MERGE.**
Machine-checked by `tests/rc7b_quarterly_candidate_authority.py` (RC-3 C2 PPA-01 precedent).

| Item | Value |
|---|---|
| Original authority / predecessor | main `5be8c4b149712dd39b38b54c6fabcf3fcf47ef0d` (PR #313 merge; PR #319 ancestor) |
| Reviewed RC-7B source head | `4b086b83e207249c807cc0521a14f78812ac8be3` |
| Activation flag | `app/workbook/quarterly_frequency_config.ACTIVATION_ENABLED = False` (literal, AST-checked) |
| Acceptance record | `docs/model_v2/RC7B_QUARTERLY_FINANCIAL_ACCEPTANCE.json` — **does not exist** |
| Research reference | `tools/quarterly_research/` byte-identical to predecessor (validation only) |

## Candidate changed-file inventory (protected namespaces; not financial approval)

| Path | Predecessor blob | Candidate blob |
|---|---|---|
| `financial_engine/adapters/project_inputs.py` | `14bd759a` | `d97ae939` |
| `financial_engine/adapters/tax_inputs.py` | `0150eb1c` | `9e271f69` |
| `financial_engine/financing/generic_product_policy.py` | `2894334e` | `59a2c1f8` |
| `financial_engine/financing/project.py` | `30536cec` | `2e18a6e7` |
| `financial_engine/financing/quarterly_scope.py` | new | `0bcf6605` |
| `financial_engine/inputs.py` | `8ba4cd3e` | `6fb5913a` |
| `financial_engine/orchestrator.py` | `be7ac31c` | `07aa1e18` |
| `financial_engine/senior_debt/project_adapter.py` | `a73611a1` | `b2302be9` |
| `finco_core/engine/calendar_policy.py` | new | `91f55f9b` |
| `finco_core/engine/period_engine.py` | `7a44c10b` | `465c172d` |
| `finco_core/inputs/_models.py` | `b896d3c0` | `a48139b9` |
| `finco_core/inputs/serialization.py` | `31f70570` | `7e678450` |

Full 40-character blobs are the literals in the module.

## Separate states (never one boolean)

`research_isolated` = True · `candidate_content_matches_exactly` = True · `candidate_is_financially_approved` = **False** ·
`candidate_is_product_admitted` = **False** · `candidate_is_released` = **False**.

## Independent financial evidence

* `tests/rc7b_quarterly_oracle.py` — 60-digit Decimal reference from inputs; `tests/test_rc7b_quarterly_funding_statements.py` (42).
* `tests/test_rc7b_quarterly_axis_production.py` — independent Fraction/calendar geometry (228).
* `tests/test_rc7b_quarterly_production_acceptance.py` — real committed app Runs, Solar and Wind (5).
* `docs/model_v2/RC7B_SEMIANNUAL_REGRESSION.json` — four verticals, 6/6 bit-identical to the predecessor (max difference 0).

## Wiring (recognition proposal only)

Correction A removed the unapproved RC-7B recognition clauses from
`tests/finance_integrity_governance.py`. Neither `unapproved_engine_changes`
nor `strictly_frozen_changes` currently exempts this candidate. The separate
`tests/rc7b_quarterly_candidate_authority.py` can recognize exact bytes, but
recognition is not financial approval and does not authorize frozen paths.
`rc3_authority_states.authority_state` reports `INTEGRATED_RELEASE_CLOSED_CANDIDATE`;
that state does not satisfy the independent financial acceptance requirement.
`tests/model_v2_governance.py`, every historical pin map, the M7 and PPA-01
literals and `approved_frozen_path` remain unchanged. Negative controls:
`tests/test_rc7b_quarterly_candidate_authority.py`.

## Open governance work (keeps the PR red and Draft)

Historical provenance assertions and current released-authority requirements
must be distinguished individually. A historical claim may be tested at its
immutable checkpoint only when its original scope and ancestry prove that is
the claim being made. Current HEAD pins and live integration scope guards
remain blocking; they cannot all be converted to historical assertions.
The #313 isolation assertion was reconciled in Correction B. The remaining
financial and scope successor decisions require independent review and owner
authorization; none is self-approved here.

## Correction C: financial structure is preserved

Matched 3/3 requires an already eligible Working Copy: EQUITY_ONLY, zero SHL
and no reserve funding/support. The legacy `excluded_structure` JSON key is
retained for decoding, not authority to discard anything. Selecting frequency
changes only calendar inputs. Even an exactly recorded nonzero SHL or DSRA
is refused before calculation. Invalid saved selections remain visible and
renderable, while Run refuses without changing inputs or historical evidence.
Monthly funding parity compares the original eligible 6/6 Run with its 3/3 Run,
not a six-month comparator reconstructed from altered quarterly inputs.

## Correction D: separate CSRF inventory successor proposal

`tests/rc7b_quarterly_csrf_successor.py` recognizes only
`app/v2/quarterly_calendar_router.py` at Git blob
`7e3ea127918bfe9d9988a807a25f65b44bd4731c`, sourced from immutable
`8048a74e7f568a40fbcaecf185621350c8251a85`. Full-module AST identity,
source ancestry and literal closed activation are required as separate checks.
The existing CSRF inventory includes this one router only while that exact
contract holds. Changed bytes, auth/CSRF/owner/CAS/financing guards, routes,
extra writes, missing provenance or opened activation invalidate recognition.

This is an independently reviewable security inventory proposal, not a
financial successor, financial approval, product admission or release. No live
finance-integrity exemptions or historical pin-map changes are introduced.

The RC-7A M7/PPA compatibility test retains its blocking current-byte checks.
A separate positive test proves the original content at immutable research
checkpoints and their ancestry. Historical proof does not approve new HEAD
content. The 77 original failure nodes are preserved in the updated register;
two security inventory mismatches have a scoped correction, while 75 financial
and integration authority failures still require independent approval.
