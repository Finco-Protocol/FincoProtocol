# CI Architecture V3 — local Phase 1

Offline prototype only. The existing single sequential Public Safety gate remains authoritative. These tools have no workflow hooks, scheduler, application imports or GitHub writer. No production or accepted governance file is changed.

Read [the implementation report](PHASE1_REPORT.md), [data and trust contracts](SCHEMA_AND_VERIFIER.md), and [the Phase 2 proposal](PHASE2_PROPOSAL.md).

## Reproduce from the historical audit

From the repository root, with the extracted Audit V3 package and a new output directory:

```text
python -m tools.ci_v3_audit_prototype --audit AUDIT_DIR --output NEW_REPLAY_DIR
```

The builder verifies checksums, full node/JUnit/timing identities and collection skips before writing inventories, policies, integer-millisecond weights and 2/3/4-worker plans for each successful cohort. It preserves the failed run as diagnostics; it does not convert that run into successful acceptance. It fabricates explicitly SIMULATED three-worker evidence to exercise the verifier. No audited test runs.

Keep generated evidence outside the public repository. Original parameter IDs and skip reasons are preserved, including historical runner paths. The generated research policy is not an approved omission policy.

```text
python -m tools.ci_v3_partition_plan --inventory INVENTORY --policy POLICY --weights WEIGHTS --workers 3 --output PLAN
python -m tools.ci_v3_evidence_verify --inventory INVENTORY --policy POLICY --plan PLAN --collection COLLECTION --trust TRUST --evidence WORKERS_DIR --output PROOF
```

The verifier requires all inputs explicitly. Its exit 0 means offline coverage-contract validation only. Every successful output includes `authoritative_acceptance:false`. Failure exits 1 and overwrites the requested output with a rejection, preventing reuse of an earlier valid-looking proof. Worker evidence checksums and fresh collection digest are bound into a positive proof.

For focused local tests, use the two new `test_ci_v3_*.py` modules. This machine required controlled pytest plugin loading because an unrelated host Web3 plugin failed before collection. The saved implementation report records the exact validation configuration. No pytest plugin setting or dependency file was edited.

No push, PR, CI dispatch, rerun, shadow execution, merge or deployment is part of this phase. Publication requires subsequent user authorization because a PR would trigger expensive mandatory CI.
