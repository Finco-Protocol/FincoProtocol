# Correction B — CI V3 worker root-cause register

Original run: [40478422312](https://github.com/Finco-Protocol/FincoProtocol/actions/runs/40478422312), source `45bd6849cb4a8b93a105e3d7d313823c5bd50545`, tree `935c0c8b88d06af145b0bd1d9d7b55e8243dee9b`. Its synthetic merge `4c2bdd8ecf3c9ccdc92b9fce4532cc53648a4088` has the identical source tree, verified by the plan artifact. All five `public-ci-v3-worker-N` artifacts were downloaded and inspected, including native JUnit, adapter original-node selection, process result, cleanup/finalization and exact-source bindings.

| Worker | Selected original nodes | Failed nodes | First failure | Classification |
|---|---:|---:|---|---|
| 0 | 3660 | 3 | `test_api_v1_1_institutional::test_corr_a_export_endpoint_authenticated_with_committed_run` | Authored percent fixture missing its explicit unit |
| 1 | 3861 | 3 | `test_model_workspace_productivity_v1::TestTypedFieldClassification::test_authority_gate_rejection_is_not_a_value_classification` | Authority mock/presentation fixture missing its explicit unit |
| 2 | 3842 | 3 | `test_p1_3_institutional_validation::test_p1_3_same_canonical_run_reconciliation` | Authored percent fixture missing its explicit unit |
| 3 | 5343 | 61 | `test_m3_two_driver_sensitivity::test_interest_rate_and_gearing_use_canonical_field_inputs_and_commute` | Oracle still multiplied the new already-percent seed by 100; remaining failures were unit fixtures/shared reporting helper |
| 4 | 3511 | 38 | `test_rc_reporting_v3::test_last_run_package_has_the_v3_front_section_right_after_the_guide[solar]` | Shared `rc7_helpers` authored factory-percent fixture missing its explicit unit |

All 108 original failed nodes were PASSED in the authenticated main source-reference artifact at `cf7056de4078ca66afcf52265a9bacafe35586f7`, tree `ba03a27692ca7bf47fb0170fd4fd5822f34ae4aa`. A fresh local replay of each worker's first failed node also passed on that unmodified main (5/5) and on corrected source `d53400a634bbaed8013c545dfa74b35991b9f436` (5/5). See [main replay](evidence/worker-clean-main.xml) and [corrected replay](evidence/worker-corrected-head.xml).

Every worker exited OS=1 / pytest=1. None timed out, was cancelled, terminated by signal, leaked a child/thread or failed cleanup. Every descendant-cleanup report verified zero surviving processes; source bytes were unchanged. The outer `worker failure or cleanup failure` message was a dependent controller error, not proof of cleanup failure. Raw selections, full assertions/tracebacks for every failed node, process/cleanup records and merge/source binding are retained in the original artifacts and the final downloadable forensic review package.

Database evidence limitation: original artifacts retain fixture paths and tracebacks, not SQLite database files. No claim is made of inspecting deleted original database bytes. Local reproductions use disposable fixture databases, and the fixture-integrity tests constrain the exact source transformations against authenticated main. No production database was accessed.

Repairs preserve all financial assertions, tolerances and historical golden files. Percent declarations identify values already explicitly produced as `factory.all_in_rate * 100`; the M3 oracle alone removes the obsolete multiplication. Source/fixture integrity and security mutation negatives remain mandatory. CI V3 collection, worker implementation, timeout and skip policy are unchanged. No retry was used to hide a failure.

A further governance error at `d53400a6`, financial run [40484810948](https://github.com/Finco-Protocol/FincoProtocol/actions/runs/40484810948), was separate: 139 focused cases passed, but the positive successor guard rejected the two-line unit-only Returns fixture adaptation as an unregistered blob. The original Returns pin remains intact; its exact new blob is now admitted additively in `FINVAL_F01_COMPLETE_SUCCESSORS`. Full local rerun: **140/140 financial/browser/lifecycle/governance cases passed, zero skips**, plus **209/209 governance/security mutation-negative cases passed**. This restores the positive guard and proves the negatives do not pass vacuously because of an unrelated pin violation. [Financial JUnit](evidence/financial-combined-final.xml), [governance JUnit](evidence/governance-final-reconciled.xml).

Separate genuine persistence defects discovered during acceptance—the optional supplied-hash mismatch and direct snapshot-converter unit bypass—are documented with red/green proof in [Correction A](FINVAL_F01_CORRECTION_A.md). They were not the original worker causes. Numerical engines, native source/manifests, D-029, CSRF, CAS, protected references and RC-M UI remain unchanged.

Final exact-head CI is required before Ready; no merge, deploy, migration, release activation or self-approval is authorized.
