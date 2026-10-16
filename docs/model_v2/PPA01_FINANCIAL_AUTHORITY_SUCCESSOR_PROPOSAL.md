# PPA-01 exact-content successor proposal

Status: **PENDING independent financial/governance acceptance. NOT a release approval.**

## Contractual-date scope addendum (supersedes the one-path proposal below)

The owner authorized candidate-only SIGNATURE/COD/PPA_START/CUSTOM timing and
PERIOD_BOUNDARY_ONLY reviews, then explicitly authorized the minimal canonical
COD bridge in `finco_core/revenue/generation.py`. Project Timeline remains the
only project-date authority. No financial blob or release pin was approved.

Current exact protected candidates:

| Path | Main blob | New candidate blob |
|---|---|---|
| domain/revenue/multistream_runtime.py | 83beda4eb296b02baf2ebd6659fec243ab196206 | 4c53ed15491e3f4a3faddde0e142681ed0a13ae2 |
| finco_core/revenue/generation.py | 35670dc7b5ab4ce01177f9df817a4776c10569ab | 8e23a949e72acc6422a6c7cd46f034b31f81fdfb |

Source parent is `1c257cb909d79af3a9afaa3a55c7e6da534231ec`; the exact committed
candidate HEAD/tree and current CI belong to the PR handoff (a document cannot
contain its own containing Git commit hash). No additional protected financial
paths change. The prior `e5e26082...` candidate is NOT the final financial scope
and must not be authorized as its substitute.

Read `PPA01_CONTRACTUAL_INDEXATION_METHODOLOGY.md` before reviewing the diff:
explicit contractual dates, annual anniversaries, pre-COD reviews, dated index
references/publication dates and held-base versus explicit index-ratio behavior
are distinct from the legacy model-year series. Missing required data and
within-operating-period reviews refuse Save/Run. No automatic date shift or
within-period financial weighting is introduced.

Evidence is in `PPA01_CONTRACTUAL_INDEXATION_CANDIDATE_REPORT.md`. Independent
review must cover BOTH exact blobs, the methodology and limitations, not just
the old five WF07 assertions. Any new successor must preserve all historical
WF07/V2/V3/F3.5 pins and M7 candidate boundaries; no successor is implemented
or self-authorized here. M7 and Revenue V3 release gates remain unchanged.

## Previous model-year-only proposal (historical candidate context)

Repository: Finco-Protocol/FincoProtocol. Existing Draft PR: #293.
Reviewed starting HEAD: `dcd7d21368d669fbc8ef054f20bf4c92f556e60e`.
Base: `540e1f4bb54d53ad6d2c1628074b94fdb0c9eb06`.

## Exact candidate

Only proposed protected financial path: `domain/revenue/multistream_runtime.py`.

| Content | Git blob |
|---|---|
| Historical WF07 | `94e1559472d0f3051fb7faccf3b67ce44337188f` |
| Historical Revenue V2 advanced | `48465ce2a298fa1383a7eabcb921eb9fbe4610cb` |
| Current main / Revenue V3 successor | `83beda4eb296b02baf2ebd6659fec243ab196206` |
| Starting PR PPA-01 candidate | `1cfdad8863041ba47e04f4f57b96e6c7ff7fcaaa` |
| Correction A candidate for independent acceptance | `e5e26082d670baa7adc91da4848959ab032ce2ad` |

Any further byte change requires renewed exact-content review. This table records candidate provenance; it does not authorize the blob. No historical map/pin is rewritten by this proposal.

## Financial scope requiring a decision

An opt-in version-2 PPA can carry explicit positive CPI/PPI levels, with each observation labelled OBSERVED or FORECAST. Annual-rate indexation and explicit nominal price curves are mutually exclusive with levels. Existing dated windows, settlement, volume allocation, residual Merchant and signed CfD remain authoritative and unchanged.

Pricing: `price[y] = base_price * level[y] / level[first_observation]`. The first observation is the explicit base and must be at or before the first active priced operating year. Continuous supplied observations must cover every active year. A late-starting PPA may retain an earlier base or explicitly start its base at its first priced year. Neither the base price nor missing observations are inferred.

The key is canonical `PeriodMeta.year_index`, not calendar year or contract anniversary. On the existing semiannual axis, each two operating periods advance this key; a partial first operating period remains in year 1. Existing annual-rate contracts already use that axis. Independent acceptance must explicitly approve using it for supplied CPI/PPI levels, including non-calendar COD and delayed PPA commencement.

Correction A makes public `plan_at(date, year_index)` fail closed when an active indexed PPA lacks a positive integer year. Parser-only `validate_structure_at(date)` validates activity/allocation/overlays and returns no priced plan. Canonical evaluation supplies the actual period year. There is no interpolation, extrapolation or fallback annual rate.

Effective period prices remain in the existing committed evidence; the supplied series and observation labels remain in committed configuration. No evidence schema, tax, debt, working-capital, generation or return formula changes. Floor/cap remain existing PPA price-authority behavior, not new JSON/editor controls. Revenue V3 activation remains closed; none of its other protected files or activation flags are changed.

## Evidence and governance blockers

Before correction, public pricing without year returned 60.0 while correct year 3 pricing returned 63.6 in a controlled synthetic case. Missing context now raises rather than returning an unindexed price.

Twenty exact pre-PPA-01 comparisons execute full canonical revenue schedules against immutable main content: Solar/Wind, normal/partial COD, fixed PPA, annual indexing, scheduled PPA, scheduled Merchant and two-way CfD. All compare with exact equality, not adjusted tolerances or regenerated goldens. Existing Decimal level, volume, floor/cap and period-axis tests are retained.

The unchanged `tests/test_wf07_revenue_governance.py` reproduces five current failures:

- `test_exact_seven_content_pins_only`.
- `test_advanced_revenue_successor_is_one_exact_blob_without_rewriting_wf07_history`.
- `test_revenue_successor_rejects_extra_byte_and_unlisted_domain_path` (its initial acceptance assertion).
- `test_revenue_v3_candidate_is_exactly_three_blobs_and_does_not_rewrite_history`.
- `test_revenue_v3_candidate_rejects_any_further_byte_and_other_paths[domain/revenue/multistream_runtime.py]` (its initial acceptance assertion).

These failures are not green evidence. Financial candidate correctness is distinct from authorization.

## Proposed additive release procedure, not applied

After explicit independent acceptance of the exact candidate and year convention, a separately reviewed additive one-path successor map in `tests/model_v2_governance.py` could recognize only this blob. Preserve all existing WF07, advanced V2, V3 and other historical map values. Historical assertions must continue to evaluate their original accepted checkpoints; current-HEAD assertions may recognize only the independently approved successor for this exact path.

Associated narrow tests in `tests/test_wf07_revenue_governance.py` must retain all existing negatives and add rejection of a changed candidate byte, an unrelated domain path, missing Git history/ref and any attempted broader authorization. Do not use wildcard namespaces, arbitrary HEAD-derived hashes or CI exclusions. No change to an authority map is permitted by this proposal itself.

Without that decision, the PR remains **BLOCKED - PPA-01 FINANCIAL AUTHORITY APPROVAL REQUIRED**, OPEN/DRAFT, unmerged and undeployed. PR #289 remains separate and open. The RC coordinator, not this branch, owns eventual workstream integration and integrated exact-head acceptance.
