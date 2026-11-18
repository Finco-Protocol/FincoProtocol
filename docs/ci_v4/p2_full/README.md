# P2 — parallel exact-inventory CI V4 FULL (Draft; owner review required)

**State: `PREPARED` — implementation + local evidence. A ≤ 40 min hosted FULL on an accepted `main` SHA is NOT claimed here.**
Any hosted measurement is recorded in the PR, not in this file (no self-attesting document).

## Why the old FULL never finished

`ci_v4_full.yml` called the unchanged CI V3 job; `tools/ci_v3_production.py:route_preflight` trusts only `push`/`pull_request`, so `schedule` /
`workflow_dispatch` routed **sequential**: one unsharded pytest, 19,200 s budget. Every FULL run (#9–#15) timed out. Run 44054710153 (`955952c1`):
2,658 / 26,035 nodes, `tests/test_ci_v3_reference_admission_successor.py` 14,561.8 s for 10 nodes (four nodes ≈ 3,630–3,660 s each). The same
module takes ≈ 270 s locally in a fresh process with full history (≈ 55 s per node, ≈ 9,200 `git` spawns per `d029_source_facts()` call):
the cost is the exact-source chain walk, amplified late in one long process. P2 does **not** widen the V3 `trusted` boolean.

## What P2 changes (and does not)

| Piece | Change |
|---|---|
| `.github/workflows/ci_v4_full.yml` | `plan` → (`recollect` ∥ `shards[k]` ∥ `f01`) → `record`. Same name, path, triggers (`schedule`, `workflow_dispatch`), permissions (`contents/actions: read`), release-gate artifact name `ci-v4-full-record`. No `pull_request` trigger. |
| `tools/ci_full_parallel.py` (new) | Controller + strict record (see module docstring). |
| `docs/ci_v4/p2_full/full_parallel_policy.json` (new) | Worker range 8–16 (adaptive), shard limit, node-split allowlist = **only** the three accepted isolation-proven modules of `docs/ci_v4/node_split_policy.json`, F01 counts, the reviewed skip baseline. |
| `docs/ci_v4/p2_full/full_node_weights.json` (new) | Balance input only (never an acceptance input). |
| `tests/test_ci_full_parallel.py` (new) | Plan coverage, adaptive workers, policy weakening, 28-case record attack matrix, transport attacks, workflow structure, old-record single-case weakness. |
| P0 cohort (`tests/ci_v4_p0_scope.py`) | The FULL workflow joins `REPLACED`/`CI_PATHS`; the existing literal P1 hooks in 7 cohorts + 7 historical tests + `tests/ci_v4_scope.py` admit **one more literal path** at the **exact P0 pin**. No new cohort, no prefix, no older pin rewritten. |

Unchanged: the V3 regression tools/workflows, `ci_v4_f01_job.yml`, `ci_v4_release_gate.yml` + `tools/ci_v4_release_gate.py`, `tools/ci_v4_nodes.py`,
`tools/ci_v4_activate.py`, `tools/ci_v4_full_record.py` (kept, no longer called), the PR workflow, every required check, every financial / product byte, V5.

## Fail-closed record (`FINCO_CI_V4_FULL_RECORD_V1` + `strict`)

`pass` only if: plan seal intact and bound to this sha/tree/run/attempt/policy; an **independent re-collection** (separate job) equals the planned
inventory; every artifact of this attempt present exactly once, downloaded through the API, zip SHA-256 == GitHub digest, no unsafe member; every shard
record sealed, bound, exit 0, not timed out, same execution plugin; every module's shard collection == inventory (count + ordered-id digest, enforced by the
accepted plugin **before** anything runs); executed == collected as a disjoint union; an independent recorder (bound once at configure; a test cannot switch
it off) has setup+teardown for every node; JUnit reconciles 1:1; collection-level skips reproduced; every skip ∈ `docs/ci_v4/full_skip_baseline.json`
(a skip is never a pass); F01: 4 browser verticals + 20 native, no skip; every job `success`. Anything else — including an API outage — is `fail`.

Found while building it (real run, not synthetic): `tests/test_ci_v4_nodes.py` deletes `FINCO_CI_V4_NODE_*` from `os.environ` in a fixture, so the
accepted plugin silently drops setup/call reports of those nodes. V4 only checks per-node evidence for split modules, so this never surfaced; P2's record
refused it (`incomplete`) until the independent recorder was added.

## Authority

A record is a claim. `ci_v4_release_gate.py` and the V5 gate (`verify_full_witness`) re-read the GitHub run: this repository, this workflow path,
`schedule`/`workflow_dispatch`, branch `main`, exact sha, `completed/success`. A dispatch on a PR branch is a benchmark (`ref` recorded), never a witness.
A V5 epoch may only be promoted **after** P2 is merged by the owner AND a FULL of that exact accepted `main` SHA is green.
