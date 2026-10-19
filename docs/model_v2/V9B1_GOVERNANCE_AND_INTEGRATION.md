# V9-B1 Protected-Content Review Request

Candidate development only. No Financial Owner approval, release successor, merge or deployment is recorded by this document.

## Exact Scope

Base: `5be8c4b149712dd39b38b54c6fabcf3fcf47ef0d`.
Research: `79270c9513cbd0ed7c0432733903482bc6528b93`, one commit ahead of that base.
Branch: `feat/model-v9b1-g2a-capacity-deferral`.

| Protected path | Released baseline Git blob | Candidate Git blob |
| --- | --- | --- |
| `financial_engine/financing/project.py` | `30536cec8779fdb6a490d82fd80bfce2c09e16fe` | `61bd3e644b8e3159d1709c32b41aec12340c5e34` |

Only this protected production path changes. Core, domain, solver, tax, financial statements, Run commit, CAS, database, application routes, activation flags, workflows and governance authority maps do not change.

## Requested Decision: OD-5

Request independent financial/source review of the exact candidate blob above as a structural capacity-pass deferral, not a change in financial methodology. Development authorization is not approval of the blob. Acceptance must identify the exact source bytes, baseline, verified feasible/rejected matrix, numerical evidence, failure-order assessment and performance results.

`tests/model_v2_governance.py::released_engine_authority_matches` currently recognizes exact historical financial blobs, including the baseline `project.py` from F3.5-A. The new blob is not in those maps. Historical positive HEAD-lock tests will require an independently authorized successor; they must not be excluded, weakened or dynamically taught to accept arbitrary current HEAD.

No guard or historical pin was changed in this candidate. Publication and exact-head CI are blocked pending the required owner decision and separately scoped successor authorization. A local candidate commit is a review artifact, not released financial authority.

## Implementation and Failure Order

The existing entry point retains Junior/multi-Senior dispatch and construction-IDC dispatch. Its unchanged numerical inner body is moved into one private helper. The helper supports the original capacity-first order for a bounded re-decision and the candidate order (unchanged funded iterations, then one capacity pass using the accepted iteration's exact input).

The funded capacity-minimum handshake still uses its own audited DSCR capacity and independent gearing capacity. Service-budget refinement, tolerances, iteration seeds, reconciliation, terminal checks and returned financial fields remain unchanged. The accepted iteration's input must not be reconstructed from `derived_shl`, which can differ by a few bits within the convergence band.

Only the named `SHL_MATURITY_RESIDUAL_FAILS_CLOSED:` ValueError triggers re-decision. The canonical helper is called once with deferral disabled, without catching its result or exception. Unrelated ValueError, RuntimeError, TypeError and AssertionError propagate. No broad catch-all, source compilation, monkeypatch, global optimizer state or new financial kernel exists in production.

Independent review must assess intermediate-refusal preservation beyond the finite test matrix. Equality in 49 research cases is evidence, not a mathematical proof for every possible contract. In particular, a fallback entered only on candidate failure cannot by itself detect a skipped intermediate failure if an untested candidate were to return success. Such an outcome would be NO GO under the current OD-2 policy, not authorization to relax it. Additional boundary/property testing or a stronger eligibility proof is required before production release if the reviewer finds that risk unresolved.

## Live Integration Checkpoint

Observed before implementation:

| Work | Exact observed HEAD | State | Production overlap |
| --- | --- | --- | --- |
| PR #320 quarterly | `915ea5bcdac7d28a0c3c7d9c5277e6aebfe9ea9a` | OPEN/DRAFT | `financial_engine/financing/project.py` |
| PR #321 V8-A | `f4ff18cd66a784c7e7aedfbf13df94b26c7e1d60` | OPEN/DRAFT | None |
| PR #322 V8-B1 | `a00cf1f599c78163ec08c09edaca4b0bc0cd3ad6` | OPEN/DRAFT | None; separate `senior_debt/solver.py` optimization |

All three merge bases were the baseline above. PR #321's five workflows were SUCCESS. PR #322 Public Safety `39198330866` was FAILURE; its other six observed workflows were SUCCESS. PR #320 Public Safety `39209255036` was CANCELLED, with eight other workflows SUCCESS. These are preflight observations, not V9 acceptance or proof of the underlying failure cause. No run was rerun/cancelled by this workstream.

## Later Normal-Merge Procedure

1. Independently resolve/review each other PR. Do not merge their candidate financial code into this workstream as a shortcut.
2. Fetch the newly released main and normal-merge it into this feature branch, without rebase/cherry-pick/squash/force push.
3. Resolve `project.py` explicitly against both reviewed source blobs. Preserve quarterly admission and all approved structural/period rules; keep B1 confined to the existing SHL/Senior inner loop. Do not enable 3/3.
4. Re-establish immutable before/after baselines at that actual integration SHA. Repeat the entire feasible/rejected matrix, extended M6/four-vertical cases, terminal failures, full financial evidence and immutable history/export checks.
5. Test #322's final metric semantics and call counts jointly without attributing its solver savings to B1. Re-measure independently after #321 to avoid attributing database savings to B1.
6. Only after independently approved exact-content successor governance and source/safety/regression acceptance, publish one Draft PR and require complete exact-head CI. No green CI is claimed here.

No PR #320/#321/#322 branch was modified. Quarterly compatibility is source-level only in this candidate: no isolated quarterly execution or integration is claimed. Existing 6/6 behavior is tested; quarterly activation remains closed and frequency semantics are untouched.
