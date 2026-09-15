# FINCO Protocol Verification Layer

## Purpose

FINCO Protocol verification is a read-only layer above FINCO Model and FINCO Radar. It validates evidence that those surfaces have already produced and creates deterministic content addresses for that evidence.

It is **not** a second financial engine, a second Radar engine, or an on-chain execution layer.

The current implementation is entirely off-chain. No blockchain anchoring, smart contract, token contract, wallet signing, custody, or autonomous execution is required or implied.

The design goal is simple:

> **Model off-chain. Verify on-chain.**

The current code implements the **verify** side as chain-agnostic deterministic evidence. A future anchoring layer can publish only the resulting digest while full evidence and calculations remain off-chain.

## Architecture

The verification package is `finco_protocol.verification`.

It contains four separate authorities:

1. **Evidence envelope** — canonicalizes supported evidence and produces a SHA-256 content address.
2. **Model verifier** — reconciles identities across serialized FINCO Model production output.
3. **Radar R3 verifier** — independently checks identities exposed by R3 evidence without rerouting quotes or redefining R0/R1/R2/R3 economics.
4. **Public validation corpus** — builds deterministic synthetic cases across Model and Radar and wraps their verified claims in evidence envelopes.

The package is deliberately above both product surfaces. It consumes output; it does not mutate either engine.

## Evidence envelope

Schema: `finco.evidence-envelope.v1`

Canonicalization identifier: `FINCO_SORTED_JSON_V1`

Each envelope records:

- product surface;
- evidence type;
- explicit authority references;
- canonicalization version;
- full normalized payload;
- SHA-256 payload digest;
- `sha256:<digest>` content address.

The canonicalization is a FINCO project-defined encoding. It is **not** represented as RFC 8785 or another external canonical-JSON standard.

Decimal values are serialized as strings to preserve financial precision. Non-finite numeric values and timezone-naive datetimes are rejected rather than normalized silently.

The content address proves only that a given envelope payload hashes to the declared digest. It does not by itself prove source authenticity, legal validity, completeness, or blockchain publication.

## FINCO Model verification

Schema: `finco.model-validation.v1`

The Model verifier consumes the serialized result from `app.api.project_runner.run_project` and checks already-computed public surfaces. Current invariants include:

- no runtime warning/error messages for the public reference run;
- `CLEAN_PRODUCTION_READY` / `clean_g2c` authority with exactly one financial calculation;
- required KPIs are finite;
- total EBITDA reconciles to total revenue less total OPEX;
- minimum DSCR is positive;
- serialized senior debt service reconciles to principal plus interest in every period;
- debt-schedule total senior service reconciles to the KPI total;
- tax-schedule total reconciles to the KPI total;
- distribution-schedule total reconciles to the KPI total;
- representative DSCR reconciles to CFADS divided by senior debt service;
- P&L, balance sheet and PF cash-waterfall statement surfaces are present;
- serialized balance-sheet balance checks remain within the public verification tolerance.

These checks reconcile output surfaces. They do not independently calculate a second project valuation.

## FINCO Radar R3 verification

Schema: `finco.radar-r3-validation.v1`

The R3 verifier consumes `LiquiditySnapshot.to_evidence_dict()` output and checks the published evidence contract. Current invariants include:

- `LIQUIDITY_OK` status and canonical asset identity;
- exact four-slot BUY/SELL × $100/$1,000 quote matrix;
- notional ordering;
- BUY and SELL directional GAP-delta identities;
- executable cross-side spread formula at both notionals;
- executable spread-delta identity;
- canonical route evidence for all four quote slots;
- four provider-cost evidence rows;
- quote-pair timing coherence against the caller-supplied R3 policy;
- complete R0/R1/R2/R3 lineage evidence;
- preserved R3 boundaries (`R4_NOT_YET_APPLIED`, `R5_NOT_YET_APPLIED`, `R6_NOT_YET_APPLIED`);
- no composite score, classification, recommendation or trading-signal field.

R3 remains the authority for liquidity measurement. The verification layer only reconciles the evidence R3 publishes.

## Public validation corpus

Schema: `finco.public-validation-corpus.v1`

The current corpus contains exactly three deterministic synthetic cases:

- `model-solar-base`;
- `model-wind-base`;
- `radar-r3-synthetic-liquidity`.

The Model cases use the repository's generic synthetic reference factories. The Radar case uses a synthetic local-chain-style deployment, fictional token/settlement identities, fixed timestamps, fixed reference prices and fixed router quote amounts.

The corpus contains no client project, workbook, wallet, company, person, historical calibration dataset, or jurisdiction-specific source data.

Each case receives its own evidence envelope. The complete corpus also receives a SHA-256 digest over its schema, sanitization declaration and ordered case list.

## Reproduce locally

Install the constrained application environment:

```bash
pip install -r requirements.txt -c constraints.txt
python -m pip check
```

Run the focused verification tests:

```bash
pytest -q tests/test_protocol_verification.py
```

Build the corpus:

```bash
python tools/build_public_validation_corpus.py \
  --output artifacts/finco-public-validation-corpus.json
```

The command prints the corpus SHA-256 digest.

To reproduce the CI determinism check:

```bash
python tools/build_public_validation_corpus.py --output artifacts/corpus-a.json
python tools/build_public_validation_corpus.py --output artifacts/corpus-b.json
cmp artifacts/corpus-a.json artifacts/corpus-b.json
```

A byte difference fails the gate.

## CI evidence

`.github/workflows/protocol_verification.yml` runs on pull requests, `main`, manual dispatch and a weekly schedule. It:

- installs the constrained dependency set;
- runs `pip check`;
- compiles the verification package;
- runs focused verification tests;
- builds the public corpus twice;
- requires byte-identical output;
- runs the repository public-safety scan;
- uploads the generated corpus as retention-limited GitHub Actions evidence.

The corpus's internal SHA-256 is a digest of FINCO canonical content. GitHub's uploaded artifact ZIP has a separate platform-generated digest. These values serve different purposes and must not be conflated.

## Security and trust boundaries

A green verification gate means the configured deterministic invariants passed for the tested revision and the generated corpus reproduced byte-for-byte in that environment.

It does **not** mean:

- the software is vulnerability-free;
- every possible financial identity has been independently validated;
- external market data is true merely because it hashes deterministically;
- the evidence has been notarized or anchored on-chain;
- a token, staking mechanism or token-gated service exists;
- cryptographic signatures establish an external party's identity;
- legal, tax, investment or credit conclusions are certified.

Those are separate authorities and, where relevant, future workstreams.
