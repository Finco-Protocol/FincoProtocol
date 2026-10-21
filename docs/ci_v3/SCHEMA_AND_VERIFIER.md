# Version 1 data and verifier contract

## Canonical encoding and authority

Every sealed artifact uses UTF-8 JSON, sorted object keys, ASCII-escaped string encoding, compact separators and one final LF. Its SHA-256 `digest` covers the canonical object with the digest field omitted. Duplicate JSON keys, non-finite numbers, malformed/truncated JSON, wrong schema and mismatching digests are rejected. Manifest node arrays are sorted and unique. Original node strings, including opaque parameter IDs and embedded delimiters, are never shortened or reformatted.

All inventories, policies and plans are labeled `authority:offline-prototype`. There is no approved-content pin, activation flag or historical exemption added. Digests provide identity/integrity; they do not prove independent owner approval or cryptographic producer authenticity.

## Inventory plus plan is the execution manifest

The canonical inventory defines the full universe independently of worker count. The sealed partition plan assigns each complete source module to an actual worker. Together they form the versioned execution manifest; no second node-owner copy can drift from the module assignment. `resolved-node-assignments.csv` materializes every original node ID with explicit 2-, 3- and 4-worker owners for review.

| Inventory field | Meaning |
|---|---|
| `source.head`, `source.tree` | Exact historical source identity; never relabeled as the prototype HEAD |
| `nodes[].nodeid` | Full original pytest node ID |
| `nodes[].module`, `fixture_unit` | Original module path; the module is the indivisible fixture unit |
| `nodes[].execution_owner` | Required reference `plan.module_workers`; resolves to `worker-0`, `worker-1`, etc. |
| `nodes[].domain`, `confidence` | Model/Radar/Shared/Cross-domain/Governance candidate or F/unresolved |
| `mandatory` | Always true, including every F/governance node |
| `obligations` | Full regression plus known domain obligations; F explicitly retains unresolved financial/security/governance scope |
| `dependency_evidence` | Reference to per-module evidence with the original audit dependency and fixture artifact hashes |
| `optional_overlap_ownership` | Required reference `policy.module_overlaps`; empty in historical candidate policies |
| `collection_skips` | Separate complete records with original node and reason; not fabricated uncollected node IDs |
| `baseline` | Historical run/source, outcomes, original artifact digests, timings and process metadata |

Whole-module overlaps may be declared explicitly by a separately supplied policy. Every node in that module then appears once per authorized owner. Duplicates in a worker or overlap not authorized by the exact policy/plan are rejected. The initial plans declare no overlap.

Weights record exact source, original run, timing artifact digest, measured setup/call/teardown phases and integer milliseconds per module. Missing, foreign, negative, fractional or non-finite weights fail; there is no implicit default. A setup-skipped node has no call report, so its absent call duration is zero rather than a missing execution.

## New nodes and fresh collection

The current complete collection is a mandatory independent verifier input, with exact source, nodes, collection skips, completeness and errors. Every worker must also report that full collection. The verifier compares multisets against the inventory, so unknown, removed, duplicated or substituted nodes fail closed. The policy sets `new_nodes:fail-closed` and `selective_execution:false`.

The historical demonstration replays the archived historical collection, explicitly labeled simulation. It is not a claim that the prototype's newly added tests belong to the old source tree. Future execution must collect its actual candidate tree and reconcile the newly added prototype tests before acceptance. A manifest cannot discover a genuinely new test from stale evidence alone; the future trusted producer must guarantee fresh complete discovery. This prerequisite is disclosed, not replaced by a hash of an old list.

All workers in this prototype report the 68 full-collection skips. Their separate JUnit also contains those 68 skip records. That intentional replication describes repeated collection and does not create duplicate test execution: the execution-node multiset still contains exactly 15,440 nodes without overlaps.

## Trusted expected context

The caller supplies a trust input outside worker artifacts: inventory/plan/policy digests; repository; PR or main identity; workflow; workflow run ID; attempt; worker set from plan; exact head/tree; environment digest; evaluator `ci-v3-offline/1`; mode simulated/recorded; and a main-head or byte-identical synthetic merge-tree proof. Every worker context must exactly match. Mixed runs, attempts, repositories, evaluator versions, source trees or environments cannot be combined.

No worker's claimed aggregate success or proposed policy is consulted as independent authority. A future trusted executor must pin these expected values from approved content and actual GitHub event/commit information. Phase 1 does not authenticate GitHub signatures, owner approvals, a producer binary, process observation, real resolved packages or branch protection. An adversary with control of both the trust input and all evidence can fabricate a consistent offline bundle; the CLI is deliberately not a merge gate.

## Worker evidence and JUnit

Each worker supplies a sealed execution manifest and `results.xml` only. The manifest binds context, worker, full collection, exact execution records, job success, completion, JUnit checksum and process evidence. Every return code is an integer zero; normal exit is true; timeout false. Required pytest-start, pytest-return, child-exit and elapsed markers must be present and chronologically consistent. Missing/failed/cancelled/timeout workers reject.

JUnit is parsed separately. The V3 format requires exactly one `ci_v3_identity` property per testcase containing JSON `["node", FULL_NODE_ID]` or `["collection-skip", CANONICAL_SKIP_RECORD]`. A JSON-escaped `ci_v3_reason` property preserves an approved skipped/xfail reason without XML attribute normalization. A future adapter is needed to produce these properties from actual pytest; the current inventory plugin and JUnit producer are unchanged. Existing historical JUnit is independently reconciled by its unambiguous classname/name locators by the audit importer, not silently accepted as V3 identity evidence.

DTD/entities, invalid/truncated XML, failure/error elements, unexpected structure, missing identity, duplicate cases, bad suite counts, JUnit/outcome disagreement, unknown skips and wrong checksums reject. A passing worker cannot hide a failing test behind a zero JUnit summary. Xpass always rejects. Existing skipped/xfail nodes require the exact explicitly supplied policy record; an unexpected skip, an omitted skip or even an unexpected change from a known skip to pass rejects for reconciliation.

The independent verifier does not import the planner algorithm. It checks the approved plan's structural coverage and per-worker ownership, then compares actual worker execution multisets against expected multiplicity. A duplicate cannot compensate for a missing node. The positive proof binds each execution/JUnit digest and the complete collection digest. It always states `authoritative_acceptance:false`, including recorded-data mode.

## Local controls

Independent hand-authored fixtures specify the small expected schedule and worker node lists. Mutations are resealed so negative tests exercise semantic validation rather than only a checksum failure. Coverage includes deletion, duplication, equal-count substitution, foreign/truncated IDs, F omission, wrong ownership, collection errors/skips, test failure/skip/xfail/xpass, source/tree/digest/lineage/environment drift, missing workers, timeout, failed/missing/ill-ordered process markers, corrupt/foreign JUnit, hidden worker failure, stale successful output and new tests. A parameter ID exceeding 125,000 characters survives JSON/JUnit round trips. A legal whole-module overlap is tested positively.
