# FINCO Public Verification

FINCO Protocol treats reproducibility and evidence as part of the product architecture. This document describes what the public repository verifies, how to reproduce the main checks, and what those checks do **not** prove.

## Verification principles

1. **Deterministic before interpretive.** Financial outputs should be produced by deterministic code paths before any narrative or AI interpretation is applied.
2. **Evidence before assertion.** Claims that can be tested should be backed by tests, workflow results, or runtime evidence artifacts.
3. **Synthetic public references.** Public validation uses synthetic references and sanitized fixtures rather than client or historical proprietary datasets.
4. **Fail closed.** Public-safety and authority checks should reject ambiguous or unsupported states rather than silently inventing a fallback.
5. **Scope is explicit.** FINCO Model, FINCO Radar, and future protocol/on-chain functionality are separate product surfaces with separate authority boundaries.

## Canonical public CI gate

The repository workflow `.github/workflows/public_safety_and_smoke.yml` runs on pull requests and pushes to `main`.

Its public gate covers:

| Gate | Purpose |
| --- | --- |
| `python tools/public_safety_scan.py` | rejects material that violates the repository's public-safety/sanitization rules |
| `python -m compileall -q .` | verifies Python source compilation |
| `python -m pip check` | checks installed dependency consistency |
| `pytest -q` | executes the public synthetic/reference and regression suite |

The workflow also publishes machine-readable JUnit test output as a GitHub Actions artifact so a specific CI run has a durable test-evidence record.

## Component evidence workflows

FINCO Radar uses additional component-specific workflows alongside the repository-wide gate. At the time of this document, public workflows include:

- `radar_r0_live_quote.yml` — runtime quote evidence and size-aware execution economics;
- `radar_r1_asset_registry.yml` — Radar R1 asset-registry gates;
- `radar_r2_gap.yml` — Radar R2 directional execution/reference gap gates and evidence.

Component workflows are intentionally narrower than the repository-wide regression gate. Their job is to prove a component-specific authority or runtime property, not to replace the full suite.

## Reproduce the repository-wide checks locally

From a clean checkout:

```bash
python -m venv .venv
source .venv/bin/activate       # Windows: .venv\Scripts\activate
python -m pip install --upgrade pip
pip install -r requirements.txt
python -m pip check
python tools/public_safety_scan.py
python -m compileall -q .
pytest -q
```

A successful local run is useful evidence, but the canonical public record for a reviewed change is the GitHub Actions result attached to that commit or pull request.

## What the public model tests cover

The public repository contains synthetic/reference tests and regression tests around the exposed FINCO Model and platform surfaces. Depending on the current revision, coverage includes areas such as:

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

A passing Radar workflow proves the assertions encoded by that workflow at that commit. It does not imply custody, wallet signing, autonomous execution, or investment performance.

## Evidence boundaries

Public CI and regression tests provide evidence of software behavior. They do **not**, by themselves, establish that:

- a financial model has been independently audited by an external accounting, tax, engineering, rating, or credit institution;
- synthetic reference assumptions match a specific real jurisdiction, project, borrower, or investment;
- historical or future market returns are accurate or guaranteed;
- the public application is production-hardened for every deployment environment;
- future token, smart-contract, or on-chain functionality is already deployed or externally audited.

Those claims require separate evidence and must be stated separately if and when they become true.

## Repository provenance and sanitization

The public repository is derived from a private development lineage through a sanitization process. Public verification therefore focuses on reproducible behavior available from this repository and does not depend on inaccessible client workbooks, project databases, calibration files, or private historical artifacts.

See `MIGRATION_CONTROL.md` for the repository migration/sanitization boundary.

## Review discipline

For material changes to financial authority, market-data authority, evidence semantics, or public-safety controls, the expected review sequence is:

1. implement on a dedicated branch;
2. run the relevant focused tests;
3. run the repository-wide public gate;
4. obtain independent review of the changed authority/semantics;
5. merge only after the evidence and review findings are resolved.

This document describes the intended verification discipline. Repository branch rules should enforce as much of that discipline as the hosting configuration permits.
