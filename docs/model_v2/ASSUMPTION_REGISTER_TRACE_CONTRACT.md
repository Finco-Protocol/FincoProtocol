# Model V2 Assumption Register & Calculation Trace — Contract (Workflow 04)

Status: read-only foundation, exact-path authorized under
`docs/model_v2/ACTIVE_EPIC_SCOPE.json`. Branch: `feat/model-v2-assumption-register-trace`
→ `epic/model-saas-v2`. No engine, persistence, or Workflow 02 RevenuePlan
code is modified.

## What the Assumption Register is

`app/model_v2/assumption_register.py` builds a typed, deterministic,
byte-stable inventory of the **real input authorities** on a canonical
`ProjectInputs` object (plus optional RevenuePlan structure):

- one immutable `AssumptionEntry` per exposed authority, with a stable
  `assumption_id` (canonical path — never a display label), `section`,
  `label`, `value`, `unit`, typed provenance, optional snapshot-key and
  lineage references;
- explicit collectors per section (PROJECT, TECHNICAL, REVENUE, CAPEX, OPEX,
  FINANCING, TAX, VALUATION). No blind dataclass dump: capability flags
  (`info.use_*`), derived construction-layer values (`capex.idc_keur`,
  `capex.commitment_fees_keur`, `capex.bank_fees_keur`,
  `capex.reserve_accounts_keur`, `financing.shl_idc_keur`),
  `tax.construction_pl` and deprecated non-authorities
  (`target_min_dscr`, `flat_dscr_target`, `shl_cap_applies`) are excluded;
- **MISSING ≠ ZERO**: absent authorities are `ValuePresence.MISSING` with
  value `None`; explicit zeros stay `PRESENT` with value `0`;
- **NaN/Inf fail closed** — never serialized, rejected at construction;
- current coverage ≈250 entries on the Generic Solar/Wind references.

## What it is not

Not a second financial engine. The register computes nothing, infers
nothing, defaults nothing, and never mutates inputs. Provenance is never
guessed: unknown provenance is `UNKNOWN`.

## Working Copy vs Last Run

`RegisterContext` carries exactly one `AssumptionContextKind`:

- `WORKING_COPY` — current draft/saved state. Must not carry run identity.
- `RUN_BOUND` — assumptions bound to one committed run; requires a caller-
  supplied `RunIdentity` (snapshot id, composite hash, workbook + engine
  versions) mirroring the committed `workspace_states.last_runtime_*`
  family. Incomplete identity fails closed (`RUN_IDENTITY_INCOMPLETE`).

Registers never mix the two, never label current Working Copy assumptions
as historical Last Run inputs, and never overwrite run identity.

## Provenance rules

`AssumptionSourceKind` is grounded in repository vocabulary: `USER_INPUT` /
`FACTORY_DEFAULT` (F10, `app/v2/provenance.py`), `REFERENCE_SEED`
(reference-seed service vocabulary), `SCENARIO_OVERRIDE` (canonical
scenario-override state), `UNKNOWN` (unproved). Scenario overrides are
marked on entries only when the caller proves the id set
(`scenario_override_ids`); with proof, matching entries get
`override_proven=True` and `SCENARIO_OVERRIDE`; all others get
`override_proven=False`. Without proof, `override_proven` stays `None`
(unknown), never silently False.

## Stable identity strategy

`assumption_id`s are canonical, lowercase, dot-separated paths bound to
input semantics (`financing.target_dscr`, `capex.epc_contract.amount_keur`,
`revenue.plan.stream.<id>.stream_type`, indexed `opex.items[i].*`). They
are independent of display labels (relabeling a CAPEX line changes no id).
Entry order is sorted by id; the register fingerprint is sha256 over the
canonical JSON payload. The fingerprint is a content-integrity helper only —
it never replaces run, workbook or project identity, which are linked
(not replaced) via `RegisterContext.workbook_composite_hash` / `RunIdentity`.

## Serialization

`to_json()` is deterministic (sorted keys, ASCII, no NaN, explicit nulls)
with schema `finco.model-v2.assumption-register` v1. Deserialization is
fail-closed: wrong schema id/version, unknown enum values, unexpected
fields, non-finite JSON literals and fingerprint mismatches all raise
`ValueError`.

## The Calculation Trace

`app/model_v2/calculation_trace.py` records lineage for canonical outputs:
Project XIRR, Pure Equity XIRR, Total Sponsor XIRR, Project NPV, Senior
Debt amount, min DSCR, min LLCR, min PLCR, total revenue/OPEX/EBITDA/cash
tax. Values are verbatim pass-throughs of the canonical result (or of the
canonical read-only presentation adapter's aggregation). The trace never
recomputes any financial quantity.

### Completeness levels

`TraceCompleteness`: `COMPLETE` and `PARTIAL` are typed seams — this
workflow never emits them. Every traced output is `AUTHORITY_ONLY` (value
present, authority and methodology pinned) or `UNAVAILABLE` (canonical
authority statused the metric unavailable — recorded with its status
string, never as zero).

### No-shadow-engine rule

The trace may read canonical results/inputs, point at methodology
authority (`app/model_methodology_registry.py` keys and canonical
module::function identities) and record dependency references. It may not
compute IRR, DSCR, debt size, tax, revenue or depreciation. Where the
registry has no key (NPV, PLCR today), the producer function is pinned
directly and marked as such; adding registry keys is a coordinator-owned
change.

## Referenced assumptions

Trace entries reference register assumption ids via documented, per-output
prefix rules (driver sections, CAPEX amounts, OPEX Y1 amounts, named
financing/tax/valuation ids). Every referenced id must exist in the
supplied register or the builder raises `TRACE_REFERENCE_UNKNOWN_ASSUMPTION`.
Register for references should be built from the run's **effective** inputs.

## Intentionally unsupported lineage

Per-period waterfall/statement lineages, full formula-tree derivation, and
cost-template lineage (Workflow 03 is not an epic authority) are out of
scope. Future seam: when Workflow 03 merges, a cost-template collector can
join this register without contract changes.
