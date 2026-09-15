# FINCO Protocol

**Financial Intelligence Infrastructure**

FINCO Protocol is a financial-intelligence platform for modelling, monitoring, comparing, and eventually verifying real-world and tokenized assets.

> **AI explains. FINCO calculates.**

The protocol is built around deterministic financial engines, typed evidence, reproducible calculations, and explicit model-state authority. Financial modelling is one capability of the protocol — not the identity of the whole product.

## Product surfaces

### FINCO Model

Deterministic financial modelling and scenario intelligence for infrastructure and real assets.

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

### FINCO Radar

Reference-aware market intelligence for tokenized assets.

Radar is architecturally separate from the classic project-finance engine. Its roadmap includes execution-aware gap analysis, size-aware liquidity, reference-state semantics, deterministic signals, and evidence-backed market observations.

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

The corporate repository is a clean-room public codebase derived from a private development lineage. Historical branches, commits, client datasets, calibration evidence, screenshots, exports, working databases, and source materials are intentionally not imported.

The migration policy is fail-closed: source enters this repository only after sanitization and public-safety checks.

## Quick start

```bash
python -m venv .venv
source .venv/bin/activate       # Windows: .venv\Scripts\activate
pip install -r requirements.txt
uvicorn main_web:app --reload
```

The current application surface is the **FINCO Model** module within FINCO Protocol.

## Safety boundaries

- deterministic engine outputs are not investment, tax, legal, or credit advice;
- synthetic reference markets are illustrative and are not jurisdictional tax templates;
- no wallet signing, custody, swaps, approvals, or private keys are required by the modelling module;
- token-market functionality belongs to the separate Radar product surface.

## Long-term direction

**Model off-chain. Verify on-chain.**

The research roadmap includes financial digital twins, cross-market price truth, execution-aware simulation, machine-readable due diligence, self-auditing models, autonomous finance agents, and cryptographic model / valuation proofs.

## Status

Sanitized corporate migration candidate. Public deployment, session isolation, load testing, and the final public-readiness review remain pending.
