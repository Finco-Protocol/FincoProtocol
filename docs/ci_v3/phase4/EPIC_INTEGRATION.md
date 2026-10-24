# React Epic five-worker integration

This integration normally merges main `f8b31a4d1d635dfa1f76735f3693fc3e9960f42e`
(PR #359) into Epic `4153d050b60175df4d2582ed9fd6574d16467704`.
Default allocation remains five whole-module, group-aware workers (range 2–12).
Main and Epic pushes and PRs retain the same stable required checks, independent
proof, native JUnit, original phases, process cleanup and immediate sequential
rollback. Deployment and feature flags are unchanged.

## Bootstrap is OPEN

The authenticated Epic reference is ordinary PR #356 Public Safety run
[40049477518, attempt 1](https://github.com/Finco-Protocol/FincoProtocol/actions/runs/40049477518).
Its actual source `8c2ca31094683ea5286924ad657caf1105f6e247` is an ancestor
of Epic with the identical tree `e8d95c4f1317960e446c2bec5a7ae24a2500c504`.
It contains 18,044 original IDs and preserves all 17,910 historical control IDs.
Source authentication succeeds, but policy admission does not: it has 45 runtime
nonpass records versus the frozen historical 43. These additional tests skipped
because the frontend toolchain was absent:

- `tests/test_model_react_source_harvest_v1.py::test_production_module_graph_excludes_demo_modules`
- `tests/test_model_react_source_rc5_v1.py::test_production_module_graph_excludes_forbidden_modules`

Both recorded `Skipped: frontend toolchain not installed in this environment`.
A successful legacy run does not authorize new skips. Route preflight now checks
historical outcomes and new-node PASS before selecting workers, so this reference
selects the retained sequential bootstrap instead of starting a doomed parallel
run. No new nonpass permission is introduced.

Sequential bootstrap explicitly installs the existing frontend lock without
lifecycle scripts. The private runtime image includes the same locked toolchain;
tests receive a source-checked link to immutable dependencies, with no network or
installation during tests. Missing or mismatched tools fail before collection.
The existing TypeScript module-graph assertions run unchanged. Compile CI also
correctly checks package.json relative to its frontend working directory.

A successful toolchain-complete exact-source integration checkpoint still needs
independent review and normal merge into Epic before it can become an accepted
Epic reference. A subsequent eligible Epic-targeted PR must demonstrate five real
workers, complete coverage and independent proof. No such proof is claimed here.
The push-before source contract remains unchanged; a push whose previous source
is still the old incompatible Epic reference may itself select sequential.

## Merge preservation

The sole textual conflict was in `tests/test_ci_v3_production.py`: preserve main's
source-aware checks plus Epic's original admitted parameter identities. The
SQLite readiness/fork/mutex implementation is main's approved implementation;
React functional sources and bundles remain Epic's bytes. PRs #357 and #358 are
not merged or modified. Their later rebases are not required by this integration;
normal base synchronization remains their independent review responsibility.
