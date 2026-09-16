# FINCO Protocol

[![Public Safety and Model Smoke](https://github.com/Finco-Protocol/FincoProtocol/actions/workflows/public_safety_and_smoke.yml/badge.svg?branch=main)](https://github.com/Finco-Protocol/FincoProtocol/actions/workflows/public_safety_and_smoke.yml)
[![Dependency Security Audit](https://github.com/Finco-Protocol/FincoProtocol/actions/workflows/dependency_security_audit.yml/badge.svg?branch=main)](https://github.com/Finco-Protocol/FincoProtocol/actions/workflows/dependency_security_audit.yml)
[![Protocol Verification Corpus](https://github.com/Finco-Protocol/FincoProtocol/actions/workflows/protocol_verification.yml/badge.svg?branch=main)](https://github.com/Finco-Protocol/FincoProtocol/actions/workflows/protocol_verification.yml)

**Financial Intelligence Infrastructure**

FINCO Protocol is financial-intelligence infrastructure for modelling, monitoring, comparing, and eventually verifying traditional, real-world, and tokenized assets.

> **AI explains. FINCO calculates.**

FINCO Protocol combines deterministic financial engines, typed evidence, reproducible calculations, and explicit state authority into a broader financial intelligence infrastructure spanning modelling, market intelligence, verification, and future on-chain functionality.

## Product surfaces

### FINCO Model — SaaS financial modelling

FINCO Model is the current SaaS application surface for deterministic financial modelling, scenario analysis, and decision support across infrastructure and real assets.

Current capabilities include:
- revenue and operating assumptions,
- CAPEX and construction financing,
- senior debt sizing and DSCR,
- shareholder loans and sponsor returns,
- tax and loss carryforward,
- cash waterfall and reserves,
- project / equity / sponsor returns,
- scenario workflows,
- financial statements and controlled exports.

### FINCO Radar — crypto and tokenized-asset intelligence

FINCO Radar is the crypto and tokenized-asset intelligence surface of FINCO Protocol.

Radar is architecturally separate from the classic project-finance engine. Active development now includes canonical asset identity, live execution quotes, execution-aware GAP analysis, and FINCO LIQUIDITY with size-aware route, spread, cost, timing, and lineage evidence. Later Radar stages cover reference-state semantics, deterministic signals, and terminal surfaces.

### FINCO Protocol layer — verification now, on-chain later

The first protocol-layer capability is implemented off-chain: deterministic, content-addressed evidence envelopes and cross-surface verification for synthetic FINCO Model and FINCO Radar R3 outputs.

The verification layer validates already-produced evidence rather than replacing either calculation engine. A sanitized public corpus currently covers generic Solar, generic Wind, and a synthetic R3 liquidity observation. Each case receives a SHA-256 content address, and CI independently rebuilds the complete corpus twice and requires byte-identical output.

No blockchain anchoring or smart-contract deployment is claimed by the current verification implementation. The intended architecture remains **Model off-chain. Verify on-chain.** A future anchoring layer can publish compact evidence digests while full calculations and evidence remain off-chain.

A future FINCO token is planned as an access and utility layer rather than a substitute for deterministic financial calculations. Planned utility may include holding-based access to selected FINCO Model and FINCO Radar tiers, premium feature unlocks, higher usage limits, verification services, and future protocol-level functionality.

Potential premium surfaces include advanced scenario and portfolio analysis, expanded modelling limits, institutional exports, advanced Radar analytics, API/data access, and model or valuation verification. Exact token economics, access thresholds, network deployment, and smart-contract design are not final and should not be inferred from the current codebase.

## Verification and CI

FINCO is structured to expose repeatable verification procedures and per-run evidence rather than relying on repository claims alone.

The main release CI gates currently perform:
- configured public-release safety scanning for defined identifiers/patterns/artifact types,
- Python compilation checks,
- dependency consistency checks,
- synthetic reference and regression tests,
- resolved-environment dependency vulnerability auditing with retained evidence,
- deterministic cross-surface Protocol verification with a content-addressed synthetic corpus.

The Protocol verification gate runs focused Model/Radar invariant checks, builds the public validation corpus twice, requires byte-identical JSON, runs the public-safety scan, and uploads the resulting corpus as retention-limited evidence. The corpus content digest and GitHub artifact ZIP digest are separate evidence values and are not represented as blockchain anchoring.

The safety scan, dependency audit, and verification corpus are automated controls, not general-purpose confidentiality, provenance, external-data-truth, or vulnerability-free guarantees. Controlled public release still requires human review.

Radar components also use dedicated evidence-oriented workflows for component-specific runtime and deterministic gates.

See [docs/PROTOCOL_VERIFICATION.md](docs/PROTOCOL_VERIFICATION.md) for the content-addressed verification layer and public corpus. See [docs/VERIFICATION.md](docs/VERIFICATION.md) for the wider verification model, local reproduction commands, evidence boundaries, CI provenance, and known limitations. See [docs/GOVERNANCE.md](docs/GOVERNANCE.md) for repository governance, dependency-security automation, target `main` protection, and pre-public-release controls.

## Public reference models

This repository contains only synthetic reference data:

| Reference | Market | Purpose |
| --- | --- | --- |
| Generic Solar Reference | Generic Market A (`XA`) | deterministic renewable-model demonstration |
| Generic Wind Reference | Generic Market B (`XB`) | deterministic renewable-model demonstration |
| Generic Storage Reference | Generic Market C (`XC`) | storage / BESS reference capability |

`XA`, `XB`, and `XC` are user-assigned market identifiers used only for synthetic examples. They do not represent real jurisdictions.

No client project, company, workbook, saved project, production database, project-specific spreadsheet, or historical calibration artifact is part of the corporate repository.

## Repository provenance

The corporate repository is a clean-room sanitized codebase derived from a private development lineage and prepared for controlled public release. Historical branches, commits, client datasets, calibration evidence, screenshots, exports, working databases, and source materials are intentionally not imported.

The migration policy is fail-closed: source enters this repository only after sanitization and public-safety checks.

## Quick start

```bash
python -m venv .venv
source .venv/bin/activate       # Windows: .venv\Scripts\activate
pip install -r requirements.txt -c constraints.txt
uvicorn main_web:app --reload
```

Build the deterministic public verification corpus with:

```bash
python tools/build_public_validation_corpus.py \
  --output artifacts/finco-public-validation-corpus.json
```

FINCO Model is the current application surface. FINCO Radar is under active staged development, and the verification layer is implemented off-chain. Token utility and blockchain anchoring remain roadmap functionality until separately specified and implemented.

## Safety boundaries

- deterministic engine outputs are not investment, tax, legal, or credit advice;
- synthetic reference markets are illustrative and are not jurisdictional tax templates;
- FINCO Model does not require wallet signing, custody, swaps, approvals, or private keys;
- Radar and protocol verification remain architecturally separate from the classic financial engine;
- a deterministic evidence digest is not proof that external market data is true and is not an on-chain notarization by itself;
- planned token utility does not imply that a token contract, token sale, staking system, or token-gated production service is currently live.

## Long-term direction

**Model off-chain. Verify on-chain.**

The research roadmap includes financial digital twins, cross-market price truth, execution-aware simulation, machine-readable due diligence, self-auditing models, autonomous finance agents, and cryptographic model / valuation proofs.

## Status

Sanitized corporate codebase under active development and prepared for controlled public release. Synthetic reference validation, dependency security, Radar R0-R3 evidence gates, and deterministic off-chain Protocol verification are active. Public deployment, session isolation, load testing, and the final public-readiness review remain in progress. Token utility and blockchain anchoring remain roadmap functionality until separately specified and implemented.
