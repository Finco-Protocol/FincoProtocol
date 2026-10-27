# PR #389 — Correction A: native CI and financial persistence final acceptance

Financial Owner authorization: **FINCO — PR #389 / CORRECTION A**, supplied in this session on 2026-10-27, §0–8. This supplements the original F01 authorization; it does not authorize merge/deploy/migration/activation or self-approval.

## Fresh GitHub preflight and RC-M boundary

Main remains `cf7056de4078ca66afcf52265a9bacafe35586f7`, tree `ba03a27692ca7bf47fb0170fd4fd5822f34ae4aa`. PR #389 at correction preflight is draft `45bd6849cb4a8b93a105e3d7d313823c5bd50545`, tree `935c0c8b88d06af145b0bd1d9d7b55e8243dee9b`, merge-base main, ahead 7 / behind 0. Reviews and review threads: zero. See raw preflight JSON in evidence. Final publication SHA/tree and exact-head hosted conclusions are authoritative in the PR and final review package.

PR #388 is separately OPEN/DRAFT at `634fdf609e1309ed0959f9b21502fefd68f43f43`, branch `claude/new-session-6o4z8l`. Its wizard/analysis/financing/investor implementations remain untouched. Shared files are the three additive governance tests/contracts: `model_mutation_security_successor.py`, `test_model_mutation_security_successor.py`, `test_model_react_overnight_b_governance.py`. Their eventual integration needs additive union and renewed exact-head verification. No merge or modification of #388 was performed. The machine-readable RC-M contract stays at its required path; RC-M must synchronize with accepted/merged F01 main, then jointly verify defaults, bankability percent display, clone provenance, schedule authority, Save/Reload and Run parity.

## Native environment defect and smallest recovery

Run `40478422151` failed before financial execution: the unchanged image's declared user `1000:1000` could not write `/subject/financial_engine/native_v10/_fk_v10.so` in the differently owned GitHub checkout. The fixtures reproducibly install temporary native artefacts beside the package. No numerical mismatch was observed in that failed setup.

The focused workflow now uses `docker run --user "$(id -u):$(id -g)"`, matching the non-root checkout owner. It attests user and native-directory ownership before execution. No root test execution, source-directory chmod, exception suppression, compiler/manifests/kernel change or test reduction is used. The approved Dockerfile remains unchanged. Local non-root identity/toolchain evidence is [native-nonroot-environment.json](evidence/native-nonroot-environment.json). Final-source local native execution: **20 passed, zero skips** ([JUnit](evidence/native-final-correction-a.xml)); 16 edited-rate cases plus 4 untouched controls, unchanged from the existing 20-case inventory. Financial/full/integrity/final-check digests match exactly across canonical Python, V10 and V10+V11 for the same typed inputs, including identical legitimate refusal outcomes.

The workflow explicitly gates all 20 native cases against skips/failures/errors, and requires the four actual browser cases with no skipped financial acceptance. Existing CI V3, all its workers, required browser roles, toolchain and provenance policies are unchanged.

## Demonstrated persistence defect and correction

At the correction preflight source, `save_workspace_state` restored a missing verified unit/lineage under `BEGIN IMMEDIATE` but retained a caller-supplied `v2_draft_content_hash` computed without that metadata. The saved JSON and supplied hash could disagree. The new regression failed with **DID NOT RAISE** before the fix: [red JUnit](evidence/hash-baseline-red.xml).

After reconciliation, `_rate_coherent_draft_hash` validates the optional **plain ProjectInputSet hash**, as documented by that legacy writer's existing parameter. A mismatch raises typed `RateContractHashError`, code `RATE_UNIT_CONTENT_HASH_MISMATCH`, before UPDATE; the transaction rolls back every column. INSERT validates before writing too. A correct hash of the final preserved snapshot is accepted; no supplied hint means the existing raw-JSON fallback hash is recomputed from the final snapshot. The modern single/batch writers retain their cursor-bound **composite** hash/CAS authority; no CAS token is reinterpreted as this legacy plain hash.

The direct `_snapshot_to_dict` caller in the legacy seeded adapter previously bypassed `build_projectinputs_from_snapshot`'s unit guard. A second red regression proved it accepted an unversioned snapshot. The converter now requires the same explicit unit whenever a rate is present. It performs no percentage conversion; the one conversion stays in `_set_financing_interest_rate`. Existing ambiguous legacy rates cannot be changed or relabeled by a full snapshot Save. Safe read-only recovery/history remains available.

## Invariant proof

| Required invariant | Proof |
|---|---|
| Stored draft + unit + hash describe the same state | Read actual SQLite JSON/hash, reconstitute PIS and compare exactly; correct final hash survives missing incoming metadata |
| Supplied hash cannot stay incorrect after reconciliation | Four stale/forged-hint negatives, UPDATE full-row rollback and INSERT absence; typed hash-mismatch code |
| Single/batch Save retain the unit | Existing four-vertical × four-rate lifecycle, both writers; metadata stays in the same JSON transaction |
| Concurrent Save/Clone cannot forge lineage | Real concurrent batch Save and two distinct clones; unique identity, exact source lineage, protected project/workspace rows unchanged |
| Ambiguous history is not migrated | Unknown old rate cannot change or gain a label; unchanged unknown value remains unknown; committed history read/detail stays byte-identical |
| Invalid provenance has no partial write | Wrong marker/lineage and hash refusal assert every stored workspace column unchanged; interrupted single/batch tests roll back |
| Run History and D-029 remain protected | Keyed/keyless HTTP Runs, old-row byte identity after Save/re-Run, D-029 idempotency/CSRF/ownership/CAS regression |

Local Correction A finance/persistence/D-029/request-security selection: **198 passed**. Final boundary/reference/fixture-integrity selection: **72 passed**. Final real Chromium plus all 16 HTTP Run outcomes: **20 passed**. Overlapping selections are not summed as unique cases. The new safe-history test separately checks a real committed Run after current-draft ambiguity.

## First-head CI failures and fixture preservation

All required first-head browser roles, Compile/Safety, source-safety, Governance Full History, Dependency Security, Q4, AI Import and Crypto checks passed. Public Safety workers exposed 108 old test-node failures due to authored fixtures missing the new unit declaration or an oracle still multiplying an already-percent seed by 100. The 25 directly affected caller nodes passed on targeted rerun; the shared reporting helper correction restored 141 local reporting/integrity checks. Original source assertions, numerical tolerances and golden files are preserved and independently constrained by the fixture-integrity tests.

One local optional LibreOffice test exposed the execution environment's binary path: `shutil.which` found the installed shim, but that unchanged test replaces child PATH with `/usr/bin:/bin`, excluding the shim. Its original assertions passed when a local environment-only plugin resolved the same actual installed binary to an absolute path (1 passed, no skip). The plugin changes no test argument beyond binary resolution, no environment/result/assertion, and is included as evidence. No tracked test or CI selection was disabled.

Disposition remains **CORRECTION REQUIRED — SAME PR** until final exact-head hosted CI is complete and green. Independent financial merge review is still required. No merge, deploy, historical migration or release activation occurred.
