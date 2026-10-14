# M7 exact-content successor proposal (Correction A)

Status: **PROPOSAL ONLY. FINANCIAL RELEASE NOT APPROVED. ACTIVATION FALSE.**

RC-2 historical checkpoint: `6fc77de98bc0562fb51efdbf96e1803a29b5b148`.
M7 financial candidate: `94d73ee7d7e33bf715e93bb021e8e63cb1ecdb0b`.
Candidate tree: `e27ab265b2518a069bddc566f51b6513fcb7e255`.

Owner follow-up authorizes proposal and negative tests only. No existing
financial registry, frozen-namespace guard, Trust inventory, release flag,
financial source, workflow, golden or tolerance is modified by this correction.
The original 44-file candidate remains byte-exact. The three correction files
are this document and the new proposal helper/test module.

## Proposed financial boundary

The eleven exact blobs remain listed in
`M7_BESS_FINANCIAL_CANDIDATE_MANIFEST.json`, with `release_approved:false`.
The independent proposal validator repeats those exact values rather than
accepting whichever bytes happen to be on HEAD. It does not register them as
released authorities. Review must separately decide acceptance of this content.

Gross merchant sales are Revenue. Charging purchases, auxiliary purchases,
grid import/export charges and DC-throughput variable maintenance are OPEX,
in addition to existing fixed OPEX. Signed EBITDA uses the existing canonical
authority. Canonical tax, CFADS, financing, statements and sponsor returns
remain downstream; no second calculator, revenue backfill or BS plug exists.
Initial CAPEX uses the existing CAPEX authority. Paid augmentation/replacement
financial accounting and nonzero stored-energy financial basis remain rejected.

Native Integrity evidence includes actual additional equity and identifies the
existing robust G2B XIRR authority. Missing/altered components fail closed;
check IDs and numerical tolerances remain unchanged. Inactive Solar/Wind/DC/EV
operating results are compared exactly with source at the RC-2 checkpoint.
That is operating parity, not a claim of complete reference-model acceptance.

## Proposed CSRF successor

Only these additional modules are proposed, not inserted into the Trust inventory:

| Exact path | Candidate Git blob | Protected handlers |
| --- | --- | --- |
| app/v2/bess_candidate_router.py | 7c643d2546f21a2cc8a5c48a253a06dd0af63a9b | validate_candidate |
| app/v2/bess_workspace_router.py | f1f81c9b36dae254dd2589f226ceb39f12f6f8a9 | working_copy, save |

Existing signed `app.auth` token validation is retained. It is not claimed to
be session-bound. Authentication, resolved ownership, protected Reference,
composite CAS and immutable history remain canonical. Candidate review does
not persist; native Save uses the existing transactional contract writer.
Missing, forged, expired, wrong-owner, protected and stale-CAS tests remain.

## Proposal-only validation

`tests/m7_bess_successor_proposal.py` observes both immutable Git checkpoints,
all original candidate blobs, exact current scope, financial source manifest,
historical financial registry, historical/current CSRF inventories and literal
closed activation flags. Missing Git/source evidence fails closed.

Negative tests cover all eleven changed/missing/falsely claimed blobs, both
CSRF routers, removed validation, extra call sites, missing historic call sites,
altered calculation/Run writer paths, additional financial files, altered
historical registries, missing evidence, invalid ancestry and flag mutations.
No production or released-governance module imports this proposal.

## Original exact-head CI evidence

Public Safety run `38526066117`, full-control job `115726582944`:

- Source safety SUCCESS.
- Supervisor budget 4200 s exceeded; process exit **124**, `normal_exit:false`.
- At timeout: 9280/11126 completed. Final progress artifact: 9221 passed,
  34 failed, 26 skipped (9281 recorded outcomes; not a completed pytest summary).
- Active test at timeout: RC-2 combined Revenue/Developer Solar lifecycle,
  in call for 15 s. This is budget exhaustion, not proof that that test stalled.
- No final JUnit or normal pytest/supervisor completion exists.
- Control evidence uploaded: artifact `11879671080`.
- Mandatory Evidence job `115751915612` failed because control failed; its
  aggregate-proof upload also had no files. It is not accepted evidence.
- All eight other exact-head workflows completed SUCCESS.

Failures recorded before timeout include frozen-namespace guards, historical
M3 financial denial, EV depreciation, XLSX/institutional wrapper assertions.
Trust/RC-2/WF07 failures also reproduce locally; later tests were not all
reached by the timed-out CI. Nothing here converts these failures into PASS.

Five additional completed CI failures reproduce locally: four XLSX/institutional
wrapper tests fail on frozen-namespace denial. The EV depreciation test passes
through its EV assertions and then fails in its legacy **Storage** comparison
loop, because the candidate adapter deliberately rejects `bess_enabled` without
a native contract (`BESS_NATIVE_CONTRACT_REQUIRED`). This is an explicit legacy
Storage compatibility decision, not an EV depreciation formula discrepancy.
No financial correction is authorized in this proposal-only follow-up.

Local revalidation: 197 financial/physical/lifecycle/Integrity tests PASS;
4 actual Chromium tests PASS, desktop light and narrow dark; source safety PASS.
Final proposal/negative/historical-checkpoint/EV/parity ring: **81 PASS**, rc=0,
normal process completion, 31.68 s. This includes the eight existing M7 boundary
cases; totals from overlapping rings must not be added as unique tests.
The separate frozen-governance diagnostic ring remains 6 failed, 110 passed,
10 existing skips. The RC-2/M3/Trust diagnostic ring remains 11 failed,
166 passed, 1 existing skip and 1 fixture error. Those diagnostics precede
this proposal and are deliberately not weakened.

## All 34 observed failures: independent local reproduction

Exact same node selection from the original progress artifact: **34 failed**,
pytest rc=1, normal local return, 49.94 s. No test was removed or relaxed.

G = frozen/financial scope or exact-authority rejection. These assertions reject
the actual candidate changes; they are not evidence of a numerical discrepancy.
Some are historical stream zero-diff rules, while shared Finance Integrity and
CI exact-content rules are current authorization barriers. Neither kind is
waived without independently accepted successor content.

S = legacy Storage input rejection inside the EV comparison test. This is a
real compatibility change versus RC-2, intentionally present in the candidate;
it is not environmental and must not be disguised as a governance-only failure.

| Exact observed node ID | Cause |
| --- | --- |
| `tests/test_ci_acceptance.py::test_frozen_financial_namespaces_unmodified` | G: protected diff is not released F3.5 content |
| `tests/test_crypto_p0_product_reality_reset.py::test_frozen_namespaces_zero_diff[financial_engine]` | G |
| `tests/test_crypto_p0_product_reality_reset.py::test_frozen_namespaces_zero_diff[finco_core]` | G |
| `tests/test_crypto_roadmap_q4_q1.py::test_frozen_authority_namespaces_unchanged_from_canonical_base` | G |
| `tests/test_data_center_a3_1.py::test_DC_A3_ZERO_DIFF_FINANCIAL_ENGINE` | G |
| `tests/test_data_center_a3_1.py::test_DC_A3_ZERO_DIFF_FINCO_CORE` | G |
| `tests/test_ev_charging_reference.py::test_ev_charging_equipment_depreciates_over_10_years` | S: adapter line 128, not EV useful-life assertion |
| `tests/test_finance_integrity_governance.py::test_approved_engine_paths_are_allowed` | G: adapter/orchestrator no longer match released blobs |
| `tests/test_finance_integrity_governance.py::test_this_branch_stays_within_the_governance_contract` | G: unapproved adapter, orchestrator, new bess.py |
| `tests/test_finance_integrity_governance.py::test_stream_guard_exemption_covers_only_allow_listed_engine_files` | G: exact released authority mismatch |
| `tests/test_m3_two_driver_sensitivity.py::test_no_engine_or_financial_authority_files_are_touched` | G: M3 only recognizes historical RC-2 V3 content |
| `tests/test_model_market_bridge.py::TestFrozenAuthorities::test_zero_diff_vs_main[financial_engine]` | G |
| `tests/test_model_market_bridge.py::TestFrozenAuthorities::test_zero_diff_vs_main[finco_core]` | G |
| `tests/test_model_v2_assumption_trace_references.py::test_no_frozen_namespace_touched` | G: shared Finance Integrity denial |
| `tests/test_model_v2_cost_templates.py::test_revenue_and_engine_files_untouched` | G |
| `tests/test_model_v2_cost_templates_cd.py::test_cd_revenue_and_engine_files_untouched` | G |
| `tests/test_model_v2_revenue_runtime_parity.py::TestNoFrozenDiff::test_zero_frozen_and_unauthorized_changes` | G: shared Finance Integrity denial |
| `tests/test_multi_source_evidence_v2.py::test_frozen_namespaces_have_zero_diff[financial_engine]` | G |
| `tests/test_multi_source_evidence_v2.py::test_frozen_namespaces_have_zero_diff[finco_core]` | G |
| `tests/test_opus_c1_product_truth.py::TestBehaviorUnchanged::test_frozen_namespaces_zero_diff_against_main[financial_engine]` | G: new bess.py outside historical allowance |
| `tests/test_opus_c1_product_truth.py::TestBehaviorUnchanged::test_frozen_namespaces_zero_diff_against_main[finco_core]` | G |
| `tests/test_p0a_model_execution.py::test_frozen_engine_and_core_are_untouched_by_this_stream` | G |
| `tests/test_p1_2_xlsx_export_reconciliation.py::test_xlsx_frozen_namespace_no_financial_engine_changes` | G |
| `tests/test_p1_2_xlsx_export_reconciliation.py::test_finco_pr98_correction_a_true_xlsx_reconciliation_complete` | G: wrapper exits at namespace assertion |
| `tests/test_p1_2_xlsx_export_reconciliation.py::test_finco_pr98_correction_b_persisted_xlsx_authority_complete` | G: wrapper exits at namespace assertion |
| `tests/test_p1_2_xlsx_export_reconciliation.py::test_finco_pr98_correction_c_final_xlsx_lineage_complete` | G: wrapper exits at namespace assertion |
| `tests/test_p1_3_institutional_validation.py::test_p1_3_frozen_namespace` | G |
| `tests/test_p1_3_institutional_validation.py::test_finco_p1_3_institutional_validation_pack_complete` | G: wrapper exits at namespace assertion |
| `tests/test_p3_run_certificate_v1.py::TestFrozenNamespaces::test_financial_engine_not_modified` | G |
| `tests/test_parallel_stream_frozen_diff.py::test_ce_real_repo_guards_green_against_current_main` | G: new frozen core input |
| `tests/test_public_product_truth_sync.py::TestFrozenAuthoritiesZeroDiff::test_financial_engine_zero_diff` | G |
| `tests/test_public_product_truth_sync.py::TestFrozenAuthoritiesZeroDiff::test_finco_core_zero_diff` | G |
| `tests/test_radar_crypto_surface_coherence.py::test_authorities_have_zero_diff[financial_engine]` | G: adapter/orchestrator exact authorization absent |
| `tests/test_radar_r3_deepstate_composition.py::test_no_frozen_namespace_delta_on_branch` | G: new core input |

The additional proposal comparison proves EV book and tax adapter inputs match
RC-2 exactly: Charging Equipment retains its 10-year override on both bases,
400 kEUR/year for years 1-10 and zero afterward. Solar/Wind/DC/EV depreciation
adapter results are bit-exact. RC-2 accepts legacy Storage depreciation inputs;
M7 rejects that configuration without a native contract. Storage compatibility
is explicitly left for owner/financial review; the original failing test stays.

## Runtime comparison and lifecycle inspection

Successful RC-2 main run `38511546434` at the exact base has process elapsed
4048.708816 s, pytest returned at 4045.314963 s, pytest rc=0, child exit=0,
normal_exit=true. Final JUnit has 11002 passed, 71 skipped, zero failures/errors.
It already used 96.4% of the fixed 4200 s budget, leaving
151.291184 s. Its environment SHA equals the failed M7 control's environment SHA;
this does not imply identical hosted runner load or performance.

The 9191 common completed node IDs total 3056.539 s at base and 4102.248 s in
M7, a 1045.709 s increase. The 90 M7-specific completed cases total 32.357 s.
Adding just those cases to base would be about 4081.066 s, below the budget;
their own measured time does not explain the observed timeout.

| Largest cumulative candidate module | Completed cases | Seconds |
| --- | ---: | ---: |
| test_cost_workspace_consistency_v1.py | 29 | 247.774 |
| test_m3_two_driver_sensitivity.py | 41 | 241.723 |
| test_f39_four_vertical_acceptance.py | 31 | 214.385 |
| test_model_financing_f2.py | 33 | 208.269 |
| test_cost_workspace_parity_v1.py | 40 | 203.329 |
| test_financing_f37_instrument_su.py | 58 | 194.183 |
| test_goal_seek_v1.py | 44 | 147.793 |
| test_developer_economics_persistence_v1.py | 62 | 130.335 |

Slowest individual observed cases include P6 safety scanning (110.780 s), Solar
F2 economics (92.322 s), runtime canonical parity (72.236 s), Wind F2 economics
(62.241 s) and decision-support cross-project (50.857 s). These are existing
cases. Several already slow before the M7 tests execute: e.g. Solar F2 is
77.137 -> 92.322 s, and cost-workspace DC OPEX is 7.194 -> 20.345 s.
This does not establish a causal M7-specific leak or justify a speculative fix.

The timeout snapshot has 57 native threads (46 sleeping, 10 futex waiting,
one running), plus multiprocessing resource tracker. The successful base log
also reports background demo-cleanup threads and then normal interpreter exit.
Thread presence alone does not identify a leak or stalled active test.

Native BESS evidence uses the existing run-scoped memo, not a global hourly-result
cache; only bounded period evidence is retained. Test fixtures use disposable
DBs, close TestClient, explicitly shutdown/join ModelExecutor and reset it.
The 197-case local financial/lifecycle/Integrity ring and actual browser tests
return normally. No demonstrated M7 teardown defect is corrected here.
Full-suite timing remains unresolved; timeouts, suite selection and evidence
requirements are unchanged. A single slower CI sample is not sufficient proof
of either infrastructure causality or a financial runtime regression.

## Decisions outstanding

1. Independent exact financial-content acceptance of the eleven candidate blobs.
2. Independent Trust/CSRF successor acceptance and bounded historical-checkpoint
   reconciliation; no broad scope exemption.
3. Separate authorization to wire accepted successors into frozen guards.
4. CI budget/performance diagnosis without hiding failures or relaxing tests.
5. Activation review remains separate. BESS, Revenue V3 and Junior stay FALSE.
6. Legacy Storage adapter compatibility requires an explicit financial decision;
   the original EV/Storage regression test is unchanged and remains RED.

PR remains OPEN/DRAFT/unmerged. No deployment or self-approval.
