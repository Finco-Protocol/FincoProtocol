# Closed admission and additive governance successor

Current active governance and workflow files are untouched. The old Phase 2 successor JSON remains historical and unapproved; it binds the earlier inert topology bytes, not this executable Phase 3A candidate. A new proposal inventory binds this candidate separately. No old accepted constant is repinned.

The independent root is JSON schema 3, kind `ci-v3-hosted-admission`. `enabled` is false in the shipped root. Setting a local boolean, supplying workflow inputs or replacing a nearby checksum does not grant authority: the hosted consumer requires the protected environment's independently retained SHA-256, controller revision and service workflow identity as well.

Required root fields when owners authorize a future exact-content experiment:

| Field | Binding |
|---|---|
| `repository` | Exact owner/repository |
| `run_id`, `run_attempt` | Exact independently authorized queued run/attempt; never a reusable permission for another run or retry |
| `source.head`, `source.tree` | Exact immutable tested source |
| `pr_number`, `merge_proof` | Current PR head/base/synthetic merge with identical tree, or independently observed main |
| `workflow_path` | Only `.github/workflows/ci_v3_shadow.yml` |
| `workflow_head`, `workflow_sha256` | Exact separately deployed workflow revision and bytes |
| `controller_head`, `controller_tree`, `controller_files_sha256` | Immutable trusted checkout and all Python tool bytes |
| `image` | Public immutable registry reference ending in an approved SHA-256 digest |
| `bundle.repository`, `bundle.revision`, `bundle.files` | Immutable independently reviewed Git content for inventory, policy, weights, isolation and environment; each path has exact SHA-256 |
| `review_reference`, `owner_decisions` | Actual independent Financial, Security and CI decision references; no decision is provided here |
| `workers`, `experiment_pairs` | Exactly 3 and 1 |

The protected `ci-v3-shadow-admission` environment must restrict deployment refs and require independent reviewers. Its `CI_V3_CONTROLLER_SHA`, `CI_V3_ROOT_SHA256` and `CI_V3_ROOT_B64` variables are operator-controlled configuration, never PR/test output. For the future authorized experiment, first queue admission behind that protected environment; owners independently obtain the queued run/attempt identity, issue the exact root/pin for that instance and only then release the environment review. A reused root for another run or retry is rejected. Validate the organization's environment-variable/review provisioning before deployment; absence of those owner inputs remains closed. The admission job checks the complete root before releasing source/controller pins to downstream jobs through service job outputs. Owners must approve both deployment and experiment separately. The execution image must include the identical resolved Python/dependency/native environment expected by the approved environment JSON; immutable image contents bind installed wheels/system libraries beyond version labels alone.

Isolation policy uses profile `docker-no-network-private-workspace-v1`, exact source, `fixture_tree_reviewed`, a review reference, and every collected module. Each decision needs an exact module SHA-256, reviewed flag, rationale and either `runner-private` or `co-locate` with a named group. External network or host resource requirements and unresolved/blocked modules stop admission. No unsupported module is omitted. Colocation can create a sequential bottleneck; a plan leaving an empty worker is rejected instead of being labeled a successful three-worker design. Shared fixture/helper/order review is required against the whole pinned source tree.

The narrow future successor can add only the exact approved standalone shadow workflow and a new shadow admission guard/negative controls. If an existing required fast-policy integration is chosen, that exact extra file/content requires separate approval. Existing Public workflow job topology, unsharded verifier, CI200/RC3/RC5 source/tree protections and protected financial identities stay intact. Existing guards mainly constrain the Public workflow and historical source unions; limited mechanical coverage of arbitrary new workflows is not authorization. Preserve their original negative controls.

CI Owner approves the executable workflow/bootstrap/image, complete inventory, budgets, cancellation and one-pair experiment. Security Owner approves protected root/service outputs, runner/container assumptions and artifact access. Financial Owner reviews complete F obligations and isolation scope without approving numerical changes or product release. PR #332, OD-R authority and its financial candidate remain separate.

Read-only branch-protection preflight returned HTTP 404 `Branch not protected` for main. Therefore distinguish the unchanged mandatory sequential protocol/context from server-side branch protection; this implementation does not claim to have installed or altered enforcement settings. Any owner decision to configure protection is separate.
