# PR #400 CI V3 artifact attempt-integrity repair: test evidence

## Gate 1 (local, Python 3.12 venv, full Git history, no Docker credentials, run as root)

Incident-replay tests (`tests/test_ci_v3_production.py`, SYNTHETIC service with real ZIP round trips; each negative asserted on its
specific rejection message):

| Case | Test | Rejection / result |
|---|---|---|
| A | `test_case_a_incident_replay_stale_attempt_1_plan_never_wins` | The toolkit "highest ID" rule on the legacy name reproduces the incident (12999360429 wins). The attempt-scoped name resolves uniquely to the complete attempt-2 plan. `authenticate_current` records only attempt-2 IDs. The stale plan handed to a worker fails with `incomplete plan artifact: missing plan.json` before Docker |
| B | `test_case_b_ambiguous_current_attempt_plan_is_rejected_whatever_the_order[valid-first / malformed-first]` | `missing/duplicate service artifact: public-ci-v3-plan-attempt-2` in both orders |
| C | `test_case_c_baseline_only_plan_starts_no_expensive_work` | All 8 worker indexes: `missing plan.json`; an unsealed plan: `missing attempt-seal.json`; Docker/`observe_container` never called |
| D | `test_case_d_…[runtime-from-other-attempt / plan-from-other-attempt / runtime-missing]` | `runtime transfer bytes…`, `plan artifact belongs to another run/attempt/source…`, `missing current-attempt runtime archive`, all before Docker |
| E | `test_case_e_two_attempt_end_to_end_contract_authenticates_and_verifies_current_attempt` | seal → upload → download → `preflight` → `authenticate_current` → `verify_data`: attempt 2, 3 workers, 6 original nodes, cleanup verified, with attempt-1 artifacts present at higher IDs |
| F | `test_case_f_…` × 12 | rerun-failed (reused attempt-1 plan): `unexpected/missing worker artifact identity`; cancelled plan: `artifact producer not successful`; duplicated worker / missing runtime: `missing/duplicate service artifact`; missing/stale worker: `unexpected/missing worker artifact identity`; wrong head / wrong run: `service artifact run/source binding`; forged archive: `service archive digest`; payload mutated after seal: `plan artifact contents differ from the sealed attempt payload`; wrong tree: `plan inventory/source drift`; wrong image: `attempt seal does not bind this plan` |
| workflow | `test_workflow_publishes_only_complete_current_attempt_artifacts_and_consumes_by_attempt`, `test_worker_attempt_guard_runs_before_any_download[4]`, `test_aggregate_requires_the_plan_of_this_attempt[3]`, `test_accepted_reference_selects_only_its_final_attempt[3]` | pass |

Suite results on the repaired tree are listed in `GATE1_RESULTS` below. Pre-existing environment-only failures, identical on the
untouched head `2ed3653b`: `tests/test_ci_v3_hosted_isolation.py::test_container_never_inherits_actions_credentials`,
`tests/test_ci_v3_probe_tools.py::{test_passwd_file_gives_the_numeric_host_user_an_entry_without_secrets,
test_local_image_review_cannot_become_registry_or_hosted_authority}`. Each raises `test containers require a non-root host
identity` because this sandbox runs as root. GitHub runners run as a non-root user.

GATE1_RESULTS
- CI V3 + acceptance + RC-3/RC-5 + M3 + WF-03/WS-2/D-029 governance suites: see the commit message of the pushed commit
  (exact counts) and the PR #400 thread.

## Gate 2 (GitHub exact head)

Recorded on PR #400, not in this file. Committing the results here would change the tested head.
