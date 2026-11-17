# Negative evidence and limits

61 candidate tests PASS, including 8/10/12 positive schedules, actual phase/native/ownership errors, wrong run/attempt/SHA/tree, runtime/archive binding drift, producer/ZIP identity, expired/missing/duplicate artifacts, forged/truncated/duplicate/DTD XML, missing/duplicate phases/nodes, worker crash/timeout/cleanup/source failure, calibration failure, environment/plugins, unexpected deselection, and coherent native+phase new skip/xfail. Synthetic positive controls prevent a trivial always-reject verifier from passing.

The real source experiment separately verifies clean accepted-main WF03 True, a byte mutation False, immutable HEAD True while the worktree is mutated, restoration True, unknown ref False; scope is empty between calls. A clean central gate is PASS, whereas a one-comment workflow tamper is FAIL (44/47 non-exact, 24 mutation violations). The source was restored in finally.

NOT PROVEN: full historical T01-E/D-029/State C/V5-3 closure under a new registered successor; file-mode, symlink, deleted-source, altered-commit/manifest attacks against an integrated controller; safe archive extraction/input binding; runtime equivalence under real hosted workload; release downgrade compatibility. No new historical pins were approved or altered. These missing checks block activation even though the isolated candidate tests pass.

Commands:

    python -m pytest -q docs/ci_v4/p0_40min/candidate/test_full_coverage.py
    python -m pytest -q tests/test_ci_v3_partition_plan.py tests/test_ci_v3_calibration_contract_v2.py
    python docs/ci_v4/p0_40min/candidate/benchmark_scope.py --repo <disposable-clean-base> --output <outside-repo.json>

A benchmark timeout is the external bounded experiment budget, not a skipped/xfail/deselected CI test. It never changes a required check's timeout or outcome.
