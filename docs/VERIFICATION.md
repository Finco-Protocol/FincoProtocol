# FINCO Public Verification

FINCO Protocol treats repeatable verification procedures and per-run evidence as part of the product architecture. This document describes what the sanitized public-release surface verifies, how to repeat the main checks, and what those checks do **not** prove.

> **Repository status at this revision:** private/staged for controlled public release. “Public” in this document refers to the sanitized public-release surface and verification contract, not current repository visibility.

## Verification principles

1. **Deterministic before interpretive.** Financial outputs should be produced by deterministic code paths before any narrative or AI interpretation is applied.
2. **Evidence before assertion.** Claims that can be tested should be backed by tests, workflow results, or runtime evidence artifacts.
3. **Synthetic public references.** Public validation uses synthetic references and sanitized fixtures rather than client or historical proprietary datasets.
4. **Fail closed.** Public-safety and authority checks should reject ambiguous or unsupported states rather than silently inventing a fallback.
5. **Scope is explicit.** FINCO Model, FINCO Radar, and future protocol/on-chain functionality are separate product surfaces with separate authority boundaries.

## Canonical public-release CI gate

The repository workflow `.github/workflows/public_safety_and_smoke.yml` runs on pull requests and pushes to `main`.

Its gate covers:

| Gate | Purpose |
| --- | --- |
| `python tools/public_safety_scan.py` | rejects configured forbidden identifiers, email-like identifiers, selected secret patterns, local-user paths, and forbidden binary/data artifact types |
| `python -m compileall -q .` | verifies Python source compilation |
| `python -m pip check` | checks installed dependency consistency |
| `pytest -q` | executes the synthetic/reference and regression suite |

The workflow publishes machine-readable JUnit test output as a retained GitHub Actions artifact, subject to GitHub Actions artifact-retention settings.

For `pull_request` workflows, GitHub's default checkout may execute a synthetic PR merge ref rather than the raw PR head commit. Evidence for a reviewed change should therefore identify the PR head SHA and the actual checked-out/tested SHA when that distinction matters.

## Component evidence workflows

FINCO Radar uses additional component-specific workflows alongside the repository-wide gate. At the time of this document, public-release workflows include:

- `radar_r0_live_quote.yml` — runtime quote evidence and size-aware execution economics;
- `radar_r1_asset_registry.yml` — Radar R1 asset-registry gates;
- `radar_r2_gap.yml` — Radar R2 directional execution/reference gap gates and evidence.

Component workflows are intentionally narrower than the repository-wide regression gate. Their job is to prove a component-specific authority or runtime property, not to replace the full suite.

## Repeat the repository-wide checks locally

From a clean checkout:

```bash
python -m venv .venv
source .venv/bin/activate       # Windows: .venv\Scripts\activate
python -m pip install --upgrade pip
pip install -r requirements.txt -c constraints.txt
python -m pip check
python tools/public_safety_scan.py
python -m compileall -q .
pytest -q
```

These commands repeat the verification procedure; they do not guarantee a bit-for-bit identical environment. `constraints.txt` pins the core dependency set used by CI, but runner images, Python patch versions, transitive dependencies not covered by the constraints file, package-index state, and external services can still change unless separately pinned or captured.

A successful local run is useful evidence, but the canonical reviewed-change record is the GitHub Actions result and associated evidence for the commit/PR state that actually executed.

## What the public model tests cover

The sanitized public-release surface contains synthetic/reference tests and regression tests around the exposed FINCO Model and platform surfaces. Depending on the current revision, coverage includes areas such as:

- public engine smoke execution;
- synthetic solar, wind, and storage reference models;
- application/UI smoke behavior;
- public deployment/demo isolation controls;
- deterministic financial and state-authority regression paths that have been sanitized for public use.

The authoritative list is the `tests/` directory at the commit being evaluated. Test counts are deliberately not hard-coded into this document because the suite grows over time.

## What Radar evidence proves

Radar evidence is designed around observable and typed market-state authority. Component-specific workflows may verify properties such as:

- amount-specific executable quote retrieval;
- size-aware economics;
- asset identity and reference-state rules;
- directional execution/reference gap semantics;
- deterministic evidence serialization.

A passing Radar workflow proves the assertions encoded by that workflow at that tested revision. It does not imply custody, wallet signing, autonomous execution, or investment performance.

## Evidence boundaries

CI and regression tests provide evidence of software behavior. They do **not**, by themselves, establish that:

- a financial model has been independently audited by an external accounting, tax, engineering, rating, or credit institution;
- synthetic reference assumptions match a specific real jurisdiction, project, borrower, or investment;
- historical or future market returns are accurate or guaranteed;
- the application is production-hardened for every deployment environment;
- future token, smart-contract, or on-chain functionality is already deployed or externally audited.

A passing public-safety scan is one automated control and does not prove the absence of all confidential, proprietary, personal, or otherwise unsuitable material. Controlled public release still requires human provenance/sanitization review in addition to the automated scanner.

Those claims require separate evidence and must be stated separately if and when they become true.

## Repository provenance and sanitization

The sanitized public-release codebase is derived from a private development lineage through a controlled migration process. Verification therefore focuses on repeatable behavior available from this repository and does not depend on inaccessible client workbooks, project databases, calibration files, or private historical artifacts.

See `MIGRATION_CONTROL.md` for the repository migration/sanitization boundary.

## Review discipline

For material changes to financial authority, market-data authority, evidence semantics, or public-safety controls, the expected review sequence is:

1. implement on a dedicated branch;
2. run the relevant focused tests;
3. run the repository-wide public-release gate;
4. obtain independent review of the changed authority/semantics;
5. merge only after the evidence and review findings are resolved.

This document describes the intended verification discipline. Repository branch rules should enforce as much of that discipline as the hosting configuration permits.
