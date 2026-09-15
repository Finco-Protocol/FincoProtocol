# FINCO Protocol

[![Public Safety and Model Smoke](https://github.com/Finco-Protocol/FincoProtocol/actions/workflows/public_safety_and_smoke.yml/badge.svg?branch=main)](https://github.com/Finco-Protocol/FincoProtocol/actions/workflows/public_safety_and_smoke.yml)

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

Radar is architecturally separate from the classic project-finance engine. Its roadmap and active development cover execution-aware gap analysis, size-aware liquidity, reference-state semantics, deterministic signals, asset identity, and evidence-backed market observations.

### FINCO Protocol layer — roadmap

The protocol layer is intended to connect FINCO Model and FINCO Radar with verification, provenance, access utility, and later on-chain functions.

A future FINCO token is planned as an access and utility layer rather than a substitute for deterministic financial calculations. Planned utility may include holding-based access to selected FINCO Model and FINCO Radar tiers, premium feature unlocks, higher usage limits, verification services, and future protocol-level functionality.

Potential premium surfaces include advanced scenario and portfolio analysis, expanded modelling limits, institutional exports, advanced Radar analytics, API/data access, and model or valuation verification. Exact token economics, access thresholds, network deployment, and smart-contract design are not final and should not be inferred from the current codebase.

## Verification and CI

FINCO is structured to expose repeatable verification procedures and per-run evidence rather than relying on repository claims alone.

The main release CI gate currently performs:
- configured public-release safety scanning for defined identifiers/patterns/artifact types,
- Python compilation checks,
- dependency consistency checks,
- synthetic reference and regression tests.

The safety scan is an automated control, not a general-purpose confidentiality or provenance guarantee. Controlled public release still requires human review.

Radar components also use dedicated evidence-oriented workflows for component-specific runtime and deterministic gates.

See [docs/VERIFICATION.md](docs/VERIFICATION.md) for the verification model, local reproduction commands, evidence boundaries, CI provenance, and known limitations.

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

The current application surface is **FINCO Model**. FINCO Radar is under active development. The protocol/token layer described above is roadmap functionality and is not represented as a live token deployment in this repository.

## Safety boundaries

- deterministic engine outputs are not investment, tax, legal, or credit advice;
- synthetic reference markets are illustrative and are not jurisdictional tax templates;
- FINCO Model does not require wallet signing, custody, swaps, approvals, or private keys;
- Radar and future protocol functionality remain architecturally separate from the classic financial engine;
- planned token utility does not imply that a token contract, token sale, staking system, or token-gated production service is currently live.

## Long-term direction

**Model off-chain. Verify on-chain.**

The research roadmap includes financial digital twins, cross-market price truth, execution-aware simulation, machine-readable due diligence, self-auditing models, autonomous finance agents, and cryptographic model / valuation proofs.

## Status

Sanitized corporate codebase under active development and prepared for controlled public release. Synthetic reference validation and CI are active. Public deployment, session isolation, load testing, and the final public-readiness review remain in progress. Protocol/token utility remains roadmap functionality until separately specified and implemented.
