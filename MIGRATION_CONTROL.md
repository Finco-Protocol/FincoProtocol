# FINCO Protocol — Corporate Migration Control

Status: PRIVATE MIGRATION WORKSPACE

## Authority

The corporate repository is a clean-room destination. Historical Git objects, branches, pull-request metadata, private project datasets, client identifiers, workbook names, emails, local paths, screenshots, exports, logs, and production database contents must never be imported into this repository.

The migration source is a frozen legacy code snapshot. Only files that pass sanitization and provenance review may enter this repository.

## Required gates

1. Freeze legacy source at an exact commit SHA.
2. Export source without `.git` history.
3. Remove all saved projects, scenarios, runs, exports, generated artifacts, caches, screenshots, local databases, and binary working files.
4. Remove or generalize all project-, company-, person-, country-, workbook-, account-, path-, and environment-specific identifiers.
5. Replace legacy reference models with fully synthetic Generic Solar, Generic Wind, and Generic Storage reference models.
6. Use generic market identifiers rather than source-country identities in synthetic reference data.
7. Run secret, identifier, path, binary, provenance, and forbidden-term scans before import.
8. Run financial-engine regression and application tests after sanitization.
9. Import only the sanitized working tree into corporate Git history.
10. Keep the corporate repository private until the public-readiness gate passes.

## Corporate repository branch policy

The migration begins with `main` only. Historical development branches are not imported. New branches are created only for active corporate work.

## Product positioning

FINCO Protocol is financial intelligence infrastructure. Financial modelling is one protocol capability, not the identity of the whole product.

Initial product surfaces:
- FINCO Model — deterministic financial modelling and scenario intelligence.
- FINCO Radar — reference-aware intelligence for tokenized markets.

## Acceptance token

`FINCO_CORPORATE_MIGRATION_R0_READY`
