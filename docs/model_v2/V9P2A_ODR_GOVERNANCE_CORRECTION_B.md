# PR #332 - OD-R Governance Correction B

## Disposition

**FINANCIAL OWNER APPROVAL REQUIRED - GOVERNANCE BLOCKED.**

This correction adds strict standalone candidate recognition and negative tests. It does not
approve financial content, change a current-authority guard, alter a historical pin, or activate
OD-R. All six protected candidate blobs, application behavior and Correction A are unchanged.
No merge, deployment, self-approval, tolerance change or financial golden update is authorized.

## Verified Git identities

- Pre-correction PR HEAD: `dddfff4ead725707bc53a37be1c5a87b8f596857`.
- Current main and merge-base: `96e5816478306e240a5872662eae449647921595`.
- Pre-correction relationship: 7 ahead / 0 behind; OPEN, Draft, technically MERGEABLE; no reviews.
- Financial predecessor: `5996453b8d5bbfaa48bc06922fc6963cf94d2f84` (RC-7C).
- Main #333 merge parents, in order: financial predecessor above and
  `78b2882859b65ee7569d5de5c925c66d4bb2bfee`.
- Main #333 introduces zero financial_engine/finco_core/domain diff from that predecessor.
- Correction A financial source: `84e17358ef739f422cda7bd546e5c2af23bf4506`.

The final correction commit cannot contain its own SHA. The PR description records the published
HEAD and fresh exact-head workflow identities after push. This report's reproduction checkpoint
remains the immutable pre-correction HEAD above.

Open Draft #324 (`1b56bc7ec124ee4cc26001f46ee58082b2e4b5b5`), #327
(`2f6f6626d0d981d8278ecde9785361ac0c3775a5`) and #328
(`e42d15ee60343b3153aa74a9821669a75e87790b`) overlap `financing/project.py`.
None is incorporated or treated as approval.

## Original exact-head CI

Public Safety run `39459946670`, job `118757288848`: **15,390 passed, 109 skipped,
25 failed**. Pytest rc=1, supervisor child exit=1. The process returned; it did not hang.
The uploaded process artifact reports `normal_exit:false`, so successful acceptance was not met.
Evidence upload succeeded. Mandatory aggregate job `118807051127` failed downstream.
No OD-R financial/numerical node is among the 25 failures.

| Workflow/job | Run | Job | Conclusion on dddfff4e |
|---|---|---|---|
| Public Safety source-safety | 39459946670 | 118757288882 | SUCCESS |
| Public Safety full tests | 39459946670 | 118757288848 | FAILURE |
| Mandatory evidence | 39459946670 | 118807051127 | FAILURE |
| Governance Full History | 39459946472 | 118756484378 | SUCCESS |
| Dependency Security Audit | 39459946529 | 118756485022 | SUCCESS |
| Compile/Safety | 39459946371 | 118756483332 | SUCCESS |
| Browser Acceptance | 39459946564 | 118756488554 | SUCCESS |
| Additional R5 authority | 39459946621 | 118757586741 | SUCCESS |
| Additional R6 terminal | 39459946257 | 118756482355 | SUCCESS |

Workflow-level Governance success does not override the stricter protected-content tests in Public
Safety. No rerun or CI bypass was used.

## All 25 failures: independent comparison

Local reproduction and the complete affected governance ring are recorded below. Each row names
the exact original node, rather than removing it from acceptance. Classification **B** means a
direct OD-R protected-content mismatch; **C** means a historical/current-state interpretation that
needs a separately authorized successor. B/C failures are approval blockers, not permission to
weaken assertions. No financial equation defect follows from these assertions alone.

Required actions:

- **R1:** independent financial review and Financial Owner exact-content decision for the six
  candidate blobs; keep this financial approval guard blocking until authorized.
- **R2:** separately review a bounded current-guard successor that preserves immutable historical
  checkpoints and every negative control. Standalone recognition here grants no path exemption.

| Exact pytest node | Main | PR #332 | Class / root cause | Required action |
|---|---|---|---|---|
| `tests/test_ci_acceptance.py::test_frozen_financial_namespaces_unmodified` | PASS | FAIL | B: six OD-R paths are not the accepted F3.5 protected diff | R1 |
| `tests/test_developer_economics_v1.py::TestGovernanceTreatment::test_other_core_and_engine_paths_stay_frozen` | PASS | FAIL | B: waterfall 6ab84043 is not the accepted e3473e1a blob | R1 |
| `tests/test_finance_integrity_governance.py::test_approved_engine_paths_are_allowed` | PASS | FAIL | B/C: exact engine mismatches and no recognized quarterly supersession | R1 + R2 |
| `tests/test_finance_integrity_governance.py::test_this_branch_stays_within_the_governance_contract` | PASS | FAIL | B: unapproved OD-R engine delta | R1 |
| `tests/test_finance_integrity_governance.py::test_stream_guard_exemption_covers_only_allow_listed_engine_files` | PASS | FAIL | B/C: approved historic slice differs; quarterly fallback unavailable | R1 + R2 |
| `tests/test_financing_f3_governance.py::test_rc7b_candidate_path_never_acquires_f3_or_released_authority_but_is_recognised_only_as_the_exact_candidate` | PASS | FAIL | C: historical recognizer returns None, not RC7B/RC7C | R2 |
| `tests/test_financing_f3_junior_governance.py::test_only_fifteen_independently_accepted_blobs_are_released` | PASS | FAIL | B: generic_product_policy changed from its historical F3 authority | R1 |
| `tests/test_financing_f3_multisenior_governance.py::test_only_exact_seven_paths_at_their_pinned_content_are_authorized` | PASS | FAIL | C: unchanged RC7C models/serialization lose whole-candidate recognition | R2 |
| `tests/test_m7_bess_boundaries.py::test_exact_candidate_manifest_is_not_a_release_and_mutations_fail` | PASS | FAIL | B/C: changed orchestrator and inherited RC7C adapter are not the M7-only state | R1 + R2 |
| `tests/test_m7_rc3_candidate_successor.py::test_the_integrated_content_is_exactly_the_eleven_reviewed_blobs` | PASS | FAIL | B/C: old M7 HEAD fallback cannot describe OD-R atop RC7C | R1 + R2 |
| `tests/test_ppa01_candidate_authority.py::test_exact_candidate_is_recognised_but_neither_approved_nor_released` | PASS | FAIL | C: inherited quarterly paths are no longer recognized; PPA blobs unchanged | R2 |
| `tests/test_ppa01_candidate_authority.py::test_m7_eleven_blobs_are_unchanged_and_coexist_without_cross_approval` | PASS | FAIL | B/C: M7 coexistence fallback sees changed orchestrator/inherited adapter | R1 + R2 |
| `tests/test_rc3_integration_inventory.py::test_the_integrated_head_is_exactly_the_documented_union_of_the_five_sources` | PASS | FAIL | C: RC3 union must remain historical, not relabel the OD-R HEAD | R2 |
| `tests/test_rc3_integration_inventory.py::test_the_merged_main_state_binds_head_to_the_pinned_candidate` | PASS | FAIL | B/C: M7 adapter/orchestrator HEAD pins differ after later successors | R1 + R2 |
| `tests/test_rc3_post_merge_authority_states.py::test_the_three_states_are_distinct_and_activation_is_unreachable_for_m7` | PASS | FAIL | C: old current-state resolver reports UNAUTHORIZED | R2 |
| `tests/test_rc3_post_merge_authority_states.py::test_every_m7_blob_is_the_candidate_state_while_the_flags_are_closed` | PASS | FAIL | C: inherited RC7C adapter not recognized as a later state | R2 |
| `tests/test_rc7_quarterly_rc7a_compatibility.py::test_all_historical_m7_and_ppa_bytes_are_preserved_without_successors` | PASS | FAIL | C: old M7 fallback used when RC7C recognition is lost | R2 |
| `tests/test_rc7c_candidate_successor.py::test_real_repository_is_the_recognised_rc7c_candidate_and_nothing_more` | PASS | FAIL | C: OD-R tree is not identical to the historical RC7C candidate | R2 |
| `tests/test_rc7c_candidate_successor.py::test_four_blobs_are_the_pinned_rc7c_blobs_and_eight_are_the_merged_rc7b_blobs` | PASS | FAIL | B/C: OD-R gpp/project/orchestrator supersede that exact content | R1 + R2 |
| `tests/test_rc7c_candidate_successor.py::test_no_protected_file_changed_beyond_the_four_since_the_pr_320_merge_and_pr_326_base` | PASS | FAIL | B/C: six OD-R deltas include paths outside the RC7C four-path delta | R1 + R2 |
| `tests/test_rc7c_candidate_successor.py::test_11_the_rc7b_candidate_is_not_the_rc7c_candidate_and_stays_recognised_as_rc7b_only` | PASS | FAIL | C: clone seeded from OD-R HEAD fails historical candidate precondition | R2; retain mutation rejection |
| `tests/test_rc7c_candidate_successor.py::test_12_13_recognition_is_never_approval_admission_or_release` | PASS | FAIL | C: clone seeded from OD-R HEAD fails historical candidate precondition | R2; preserve closed flags |
| `tests/test_rc7c_candidate_successor.py::test_14_candidate_recognition_does_not_turn_the_changed_paths_into_released_authority` | PASS | FAIL | C: loss of whole-candidate state also removes inherited calendar scope recognition | R2; no new released authority |
| `tests/test_wf04_numeric_precision_governance.py::test_exact_wf04_paths_and_content_only` | PASS | FAIL | B: project.py OD-R blob is not an accepted WF04/F3 successor | R1 |
| `tests/test_wf07_revenue_governance.py::test_exact_seven_content_pins_only` | PASS | FAIL | C: unchanged RC7C serialization falls back to old F3 pin | R2 |

### Local execution evidence

- Windows, Python 3.12.10, separate detached worktree at current main. Disposable test storage and
  all logs/JUnit artifacts are outside Git. Local plugin autoload disabled to avoid an unrelated
  installed Web3/eth_typing plugin import conflict; test selection and repository dependencies unchanged.
- Exact original 25 on candidate dddfff4e: **25 failed**, rc=1, 105.99 s; node inventory matches CI.
- New proposal/negative suite: **21 passed**, rc=0, 238.47 s, normal process return, zero skips/xfails.
- Final clean main 25-node comparison: **25 passed**, rc=0, 245.59 s, normal process return.
  Every original failure passes on current main; no class A pre-existing or unexplained class D
  failure remains in this exact 25-node comparison.
- Full affected governance and negative-control ring: **309 passed / 25 failed**, rc=1,
  941.11 s, normal process return, zero errors/skips/xfails. JUnit failure node IDs match the
  original 25 exactly: no unexpected or missing failure. Negative controls were not weakened.
- Source safety on all four correction files, compilation of both Python files and diff hygiene:
  **PASS**. Full repository source safety remains a fresh exact-head CI gate.

An initial Windows-only baseline setup yielded 24 passed / 1 failed because the M7 test hashes
physical bytes with autocrlf disabled, while clean Windows checkout had CRLF. Independently
confirmed 11 M7 physical files, normalized only line endings to their exact existing LF Git blobs,
and verified zero tracked content diff. The isolated M7 baseline test then passed (rc=0, 24.68 s).
This is not a main financial regression, a pin change, or permission to waive the assertion.

## Immutable financial manifest

All candidate content below is **UNAPPROVED exact content**, unchanged by Correction B.
The first column's predecessor is identical at both main checkpoints 5996453b and 96e58164.

| Exact path | Predecessor Git blob | Candidate Git blob (before and after B) |
|---|---|---|
| `financial_engine/financing/generic_product_policy.py` | `59a2c1f868b4c12718a22919c3114f3af5af5120` | `293d896ac474f47ea74a93ac5ac5d7a587f1446b` |
| `financial_engine/financing/project.py` | `2e18a6e7c8ddfd85929d9b1906f91dd8858d0044` | `16ab1921b539ec3ed42d55554b1392ce781e6ce5` |
| `financial_engine/orchestrator.py` | `b6dc102ea18be4d40adc4a7ad08f187af17c5076` | `85c8008f2b4a656fd28eea1169689b19131576e4` |
| `financial_engine/shareholder_waterfall/model.py` | `e3473e1a2064c8310e41b434da2b0aff9d5753b8` | `6ab84043c0267832125a073a3a881e1e86ac0e3d` |
| `financial_engine/shl/maturity_authority.py` | absent | `8383eb2d735f310a09d9f080134a314efb276ba6` |
| `financial_engine/shl/production.py` | `744b384cfa1652588817e77b8f1c04f8a36fc75f` | `9bb852c235a988bff994c4327b3b63dd6d77ae20` |

Application `app/services/production_financial_authority.py` remains
`89083cd41a4de029ae3c57ee0a4f4a871c7863bd` (predecessor
`173991ca8107169672bbf977fe2fad91af520e9c`). No application writer, engine, core, domain,
UI, workflow, dependency, tolerance, golden or activation file changes in this correction.

## Chained proposal, not release authorization

The chain is historical RC7B -> RC7C at immutable 5996453b -> financially identical integrated
main 96e58164 -> exact Correction A six-blob source 84e17358 -> published candidate dddfff4e ->
metadata/test-only Correction B. The proposal verifies ancestry, exact #333 merge parents,
before/after blobs, the exact six protected paths, exact application/evidence content, unchanged
historical guards and an explicit total changed-file inventory. Invalid/missing refs fail closed.

Original RC7C recognition is evaluated at its immutable checkpoints, not falsely against OD-R HEAD.
Historical M7, PPA, F3, WF04 and WF07 authority maps and their validators are not edited. Nine
historical helpers are checked unchanged against both predecessor checkpoints.

`candidate_recognized()` is confined to the standalone proposal. It grants no path permission.
Existing `quarterly_candidate_recognition.scope_exempt` couples recognition to protected-path
exemptions; wiring OD-R there would widen effective financial permissions. This correction does
not make that unauthorized change merely to pass tests. Current-authority failures remain blocking.

States: policy approved in principle = true; exact candidate recognized = true when all evidence
matches; protected content approved, independent financial review, wired current guards, product
activation and financial release = **false**. No environment variable or forged approval JSON can
grant approval. Original canonical product policy remains the default; M7/Revenue V3/Junior closed
flags remain unchanged.

Negative controls exercise actual Git objects in disposable clones: one-byte changes in each of six
blobs; unrelated engine/core/domain/app/guard edits; missing candidate file; stale manifest; missing
Git, invalid ref, shallow missing predecessor, exact bytes without ancestry; altered evidence/app;
opened Junior flag plus forged approval. None edits the actual financial checkout or grants release.

## Preserved financial evidence

The 112-case JSON is unchanged at blob `707fb20a873a1f142cdde4735cfe0ab308cd123e` and identifies
Correction A 84e17358: 62 previously feasible cases with full-output/Integrity bit identity, 17 newly
feasible, 27 final economic rejections, 4 structural rejections, 2 numerical rejections. Three-seed
verdict differences = zero; seed probes do not claim bit identity across different seeds. The
interest-limitation/bullet supplementary evidence and combined-failure precedence remain recorded.

Preserved tool/test blobs:

- `tools/v9p2a_odr_acceptance.py`: `4b03d1fa9cd17d24efc53fe1dc8bd603b58e4a25`.
- `tests/test_v9p2a_odr_final_state_authority.py`: `0612c3aa429c6bbecb80f500b2fa3ff4861653da`.
- `tests/test_v9p2a_odr_run_commit_safety.py`: `d7d265f2819fe69ee4189011739349eaded0dd12`.

The previous numerical evidence was inspected and bound to identical financial blobs; the 112
financial runs were **not rerun** for this metadata/governance-only correction, as requested.
This is preservation evidence, not a claim of a new independent financial approval.

## Correction B changed-file inventory

1. `tests/v9p2a_odr_candidate_proposal.py`: strict unapproved predecessor/successor recognition.
2. `tests/test_v9p2a_odr_candidate_proposal.py`: positive historical/candidate checks and mutation tests.
3. `docs/model_v2/V9P2A_ODR_FINAL_STATE_SHL_AUTHORITY.md`: factual current-main/report pointer only.
4. `docs/model_v2/V9P2A_ODR_GOVERNANCE_CORRECTION_B.md`: this failure classification and handoff.

## Required independent decisions

1. Independent financial review and explicit Financial Owner exact-content acceptance of all six
   candidate blobs above, including Correction A exception precedence and changed admission semantics.
2. Independent governance review of the standalone chain and a specifically bounded successor for
   current-guard consumption, preserving all historical pins and unauthorized-content rejection.
3. A distinct future activation/release decision. Neither policy approval nor technical candidate
   recognition authorizes production selection, deployment or merge.

Until these decisions and required exact-head CI are satisfied, PR #332 stays OPEN / DRAFT and
**FINANCIAL OWNER APPROVAL REQUIRED - GOVERNANCE BLOCKED**.
