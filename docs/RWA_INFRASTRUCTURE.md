# FINCO RWA Infrastructure Modelling

## Thesis

**Most RWA platforms start with the token. FINCO starts with the asset.**

Tokenization can change how ownership, access, settlement, or market participation is represented. It does not remove the need to understand the economics of the underlying real-world asset.

For infrastructure, that means modelling questions such as:

- What does the asset physically produce or provide?
- What drives utilization, volume, occupancy, production, or availability?
- How is revenue priced and indexed?
- What CAPEX is required and when?
- What does it cost to operate and maintain the asset?
- How is construction and long-term debt structured?
- What taxes and depreciation rules affect cash generation?
- How much cash must remain in reserves?
- What cash is ultimately distributable?
- What IRR, NPV, DSCR, and other return / credit metrics follow from those assumptions?
- Can the resulting model evidence be reproduced and reconciled?

FINCO is building a deterministic analytical layer for answering those questions.

The objective is not to move a full infrastructure model onto a blockchain. The intended architecture is:

> **Model off-chain. Verify on-chain.**

Financial calculations remain off-chain. Compact evidence and selected outputs may later be anchored or referenced cryptographically through separately specified Protocol functionality.

## Current first vertical: renewable infrastructure

The initial RWA infrastructure module focuses on:

- **Solar**
- **Wind**

Renewables provide a strong starting vertical because their economics combine physical production, contracted or merchant pricing, long-duration infrastructure, CAPEX, debt, taxation, reserves, and equity distributions in a structure that can be modelled deterministically.

The current codebase should therefore be read as **renewable infrastructure first**, not as a claim that every infrastructure module below is already implemented.

## What the current engine can model

FINCO's common engine already contains financial primitives that are relevant far beyond one infrastructure category.

### 1. Physical and operating assumptions

For renewable assets, these currently include the assumptions needed to translate installed infrastructure into operating production and revenue inputs.

Future asset modules can replace renewable-specific operating drivers with vertical-specific drivers while retaining the downstream financial engine.

Examples:

- traffic volume for a toll road,
- occupancy and rent for a building,
- occupancy / ADR / RevPAR for a hotel,
- water output and contracted tariff for a desalination plant,
- contracted capacity and utilization for a data center.

### 2. Revenue modelling

The engine can represent structured revenue assumptions, including contractual pricing and indexation logic.

The general RWA pattern is:

`operating driver -> volume / production -> price / tariff -> revenue`

The operating driver differs by asset vertical, but the downstream cash-flow architecture can remain common.

### 3. CAPEX and construction

FINCO models capital expenditure and construction-related financing assumptions.

This is fundamental for infrastructure RWAs because value cannot be separated from:

- initial build cost,
- timing of spend,
- financing during construction,
- commissioning / operating transition,
- future expansion or major refurbishment needs.

### 4. Operating expenditure

The engine supports operating-cost assumptions and their effect on EBITDA and cash generation.

Future vertical modules can introduce asset-specific operating-cost structures without replacing the core cash-flow and reporting logic.

### 5. Debt financing

FINCO includes infrastructure-style debt logic such as:

- senior debt sizing,
- amortization,
- interest,
- debt service,
- DSCR,
- financing schedules,
- construction / operating period separation.

This matters for RWA analysis because the economics of the asset and the economics of the security or token can diverge materially depending on leverage.

### 6. Sponsor and shareholder funding

The engine can model shareholder loans and sponsor funding structures alongside senior financing.

That enables separation of:

- project-level economics,
- debt economics,
- sponsor cash flows,
- equity returns.

### 7. Tax and depreciation

FINCO includes tax, tax-loss carryforward, tax depreciation, and book-depreciation logic.

These are essential for infrastructure assets because accounting profit, taxable profit, and distributable cash are not the same quantity.

### 8. Reserves and cash waterfalls

Infrastructure assets frequently operate under contractual or financing restrictions on cash.

FINCO can represent reserves and cash-waterfall logic so that investor distributions are calculated after the relevant operating, financing, tax, and reserve requirements rather than from headline revenue alone.

### 9. Financial statements

The engine produces structured financial-statement surfaces, including P&L, balance-sheet, and cash-flow / waterfall outputs.

This supports reconciliation between valuation outputs and the underlying accounting / financing structure.

### 10. Investor returns and credit metrics

Current outputs include metrics such as:

- project IRR,
- equity / sponsor returns,
- NPV,
- DSCR and related debt-service metrics,
- distributable cash,
- debt balances and debt service.

These are useful primitives for analyzing both traditional infrastructure ownership and future tokenized representations of infrastructure cash flows.

### 11. Scenarios and sensitivities

Infrastructure RWA value is assumption-sensitive.

FINCO supports scenario workflows so that users can test changes in operating, pricing, financing, tax, and other assumptions rather than relying on a single static valuation.

### 12. Evidence and verification

FINCO Protocol adds a separate verification layer above already-produced Model and Radar evidence.

It is designed to make calculations more reproducible and auditable without creating a second financial engine.

Current verification remains off-chain. A deterministic digest is evidence of the serialized payload, not proof that an external data source is true and not a claim that the evidence has already been notarized on-chain.

## The modular RWA architecture

FINCO's intended infrastructure architecture can be viewed in two layers.

### Common deterministic financial layer

Reusable across multiple infrastructure categories:

- CAPEX,
- OPEX,
- financing,
- debt service,
- tax,
- depreciation,
- reserves,
- financial statements,
- cash waterfalls,
- distributions,
- valuation and return metrics,
- scenarios,
- reporting,
- evidence and verification.

### Asset-specific operating module

Different for each vertical:

- physical production,
- capacity,
- utilization,
- occupancy,
- traffic,
- contracted volume,
- tariffs,
- concession terms,
- maintenance patterns,
- refurbishment / lifecycle CAPEX,
- vertical-specific operating constraints.

This separation is what allows a renewable-first engine to expand into broader RWA infrastructure without rebuilding the entire financial architecture for each new asset class.

## Planned infrastructure verticals

### Renewable energy — current first module

**Solar and wind** are the first production verticals.

Core drivers include capacity, production, availability, pricing, operating costs, financing, tax, reserves, and distributions.

### Transport infrastructure — planned

Examples:

- toll roads,
- highways,
- concession assets.

Potential vertical drivers include:

- traffic volume,
- vehicle mix,
- toll rates,
- tariff indexation,
- concession life,
- maintenance CAPEX,
- operating costs.

### Real estate — planned

Examples:

- commercial buildings,
- residential buildings,
- mixed-use assets.

Potential vertical drivers include:

- leasable area,
- occupancy,
- rent,
- lease escalation,
- operating expenses,
- development CAPEX,
- refurbishment,
- refinancing.

### Hospitality — planned

Examples:

- hotels,
- resort assets,
- other operating hospitality real estate.

Potential vertical drivers include:

- occupancy,
- ADR,
- RevPAR,
- room inventory,
- food / beverage and ancillary revenue,
- operating margins,
- refurbishment CAPEX.

### Water infrastructure — planned

Examples:

- desalination plants,
- water-treatment plants,
- wastewater infrastructure.

Potential vertical drivers include:

- water production,
- contracted capacity,
- water tariff,
- energy consumption,
- plant availability,
- operating costs,
- long-term infrastructure debt.

### Digital infrastructure — planned

Examples:

- data centers,
- capacity infrastructure,
- related digital facilities.

Potential vertical drivers include:

- installed capacity,
- contracted capacity,
- utilization,
- power usage,
- power cost,
- pricing,
- expansion CAPEX.

### Additional future candidates

Potential longer-term verticals include:

- energy storage,
- regulated and contracted utilities,
- ports and terminals,
- logistics infrastructure,
- telecom towers and networks,
- district heating and cooling,
- industrial and process facilities.

These are roadmap candidates and should not be interpreted as currently implemented asset-specific modules.

## RWA positioning

FINCO is not designed around the assumption that an RWA becomes analytically complete when a token is created.

A credible infrastructure RWA still needs an underlying model of:

1. the asset,
2. its cash generation,
3. its liabilities and financing,
4. its taxes and reserves,
5. the cash available to capital providers,
6. the valuation and return assumptions,
7. the evidence supporting those outputs.

FINCO Model addresses the underlying asset economics.

FINCO Radar addresses crypto / tokenized-asset market behavior and execution conditions.

FINCO Protocol addresses deterministic evidence and future verification / anchoring infrastructure.

Together, the long-term objective is an analytical stack that connects **real asset economics** with **tokenized-market intelligence** without pretending that the token and the asset are the same thing.

## Current boundary

Current implementation should be described conservatively:

- renewable infrastructure modelling is the first Model vertical;
- Solar and Wind are the initial supported asset modules;
- future infrastructure verticals remain roadmap targets;
- Protocol verification is currently off-chain;
- no live blockchain anchoring is claimed;
- no token contract, staking system, custody system, or tokenized infrastructure issuance platform is claimed by this document;
- deterministic financial outputs are not investment, tax, legal, or credit advice.
