# Financing F3 — Typed Contract Specification (proposal, versioned)

**Schema version: `f3-candidate-0.1`.** Nothing here is live. The executable prototype is
`app/model_v2/financing_f3_candidate/` (non-authoritative). The eventual canonical home is a reviewed
`finco_core/inputs/financing_instruments.py` (F3.1), never an unrelated UI/workbook model.

## 1. Separation of concerns

| Layer | Fields | May change numbers? |
|---|---|---|
| **Identity** | `instrument_id` (stable, immutable, unique), `name` | No |
| **Classification** | `instrument_type`, `classification_label` ("Club Deal", "DFI Loan"), `provenance` | **No** — a label never alters a calculation |
| **Economics** | commitment, drawdowns, interest, repayment, grace, fees, seniority, sweep, reserve support, covenants, `enabled` | Only when a canonical authority consumes the field |

A loan-specific field is *effective* only if an engine reads it; otherwise it is *documentary* and UI-disabled.

## 2. Collection

`FinancingCollection { schema_version, instruments[], providers[] }`

* **Absent collection = legacy path.** Present-but-empty is invalid for activation (cannot mean "no Senior").
* **Ordering:** canonical order is `(seniority_rank asc, instrument_id asc)`; insertion order is never significant.
  Equal rank = pari passu.
* **Stable IDs:** opaque, user-immutable, unique within a project, `[a-z0-9-]{1,64}`; migrated legacy IDs are fixed
  (`legacy-senior`, `legacy-share-capital`, `legacy-share-premium`, `legacy-shl`, `legacy-additional-equity`).
* **Deterministic identity:** SHA-256 of canonical JSON (sorted keys, compact separators, ISO dates, enum values).
  It identifies a *proposal*; it is **not** a Run fingerprint. When activated it enters the composite workbook
  identity only if the collection is present, so projects without it keep today's hashes.

## 3. Debt instrument

| Dimension | Type | Validation |
|---|---|---|
| `instrument_id`, `name` | str | non-empty; id unique |
| `instrument_type` | enum | DEBT family: SENIOR_TERM_LOAN, CONSTRUCTION_FACILITY, JUNIOR_DEBT, MEZZANINE_DEBT, SHAREHOLDER_LOAN, BOND |
| `currency` | str | must equal model currency (EUR); FX out of scope |
| `commitment_keur` + `commitment_authority` | float? + enum | EXPLICIT ⇒ finite, ≥ 0, required; `CANONICAL_SIZING_DERIVED` / `RESIDUAL_DERIVED` ⇒ amount **must be absent** (it is an output) |
| `drawdowns[]` | (date, amount) | real dates (not datetimes), strictly increasing, Σ ≤ commitment; empty = engine-derived draws |
| `interest` | mode FIXED / PERIOD_SCHEDULE / FLOATING_BASE_PLUS_MARGIN; fraction rate; PIK flag | rates are **fractions** (0.05 = 5%); percent-style values rejected; FIXED needs rate; FLOATING needs margin |
| `repayment` | mode BULLET / LEVEL_PRINCIPAL / DSCR_SCULPTED / EXPLICIT_SCHEDULE / CASH_SWEEP / NONE; grace months; maturity | non-NONE ⇒ maturity required; grace ≥ 0 int |
| `seniority_rank` | int ≥ 1 | 1 = most senior |
| `fees[]` | kind UPFRONT / COMMITMENT / AGENCY; rate fraction; basis | rate in [0,1]; **basis is documentary until an authority consumes it** |
| `covenants` (future) | per-facility target DSCR, lock-up, min LLCR | never share one denominator across facilities |
| `reserve_support` (future) | DSRA / DSRF reference | per facility or aggregate-senior, explicit |
| `cash_sweep` (future) | % / priority | requires waterfall integration (F3.5) |
| `enabled` | bool | disabled ⇒ zero economic effect, retained for audit |
| `funding_source_ref` | provider id? | must exist; SHL requires one |
| `provenance` | USER_INPUT / LEGACY_FINANCING_PARAMS / PRESET | audit only |

Cross-instrument rules: duplicate IDs rejected; unknown provider refs rejected; Σ(drawdowns) per instrument ≤
commitment; total funded sources must reconcile to uses by the **existing** S&U authority (not recomputed here).

## 4. Equity and capital providers

`CapitalProvider { provider_id, name, ownership_share }` — shares are fractions summing ≤ 100%.
Equity instruments (COMMON_EQUITY, SHARE_PREMIUM, ADDITIONAL_EQUITY) carry commitment, contribution dates
(drawdown entries), funding priority (seniority rank within funding order), and `funding_source_ref`.

* **Return entitlement / distribution priority / preferred return / redemption:** *not representable in F3.*
  `PREFERRED_EQUITY` is **rejected** by the prototype (`F3_PREFERRED_EQUITY_DEFERRED`) so it cannot be added as a
  decorative field. These require the F4 investor-level waterfall and a per-provider cash-flow ledger.
* **SHL principal/interest per provider:** supported only as a debt-facility instrument funded by a provider; the
  per-provider SHL ledger is F3.5.
* No individual investor IRR/MOIC is produced without that ledger.

## 5. Validation catalogue (stable error codes)

`F3_DUPLICATE_INSTRUMENT_ID`, `F3_DUPLICATE_PROVIDER_ID`, `F3_NON_FINITE_VALUE`, `F3_NEGATIVE_VALUE`,
`F3_INVALID_DATE`, `F3_DRAWDOWN_ORDER`, `F3_DRAWDOWN_EXCEEDS_COMMITMENT`, `F3_MISSING_TERM`,
`F3_INVALID_TYPE`, `F3_INVALID_TYPE_COMBINATION`, `F3_CURRENCY_MISMATCH`, `F3_INVALID_SENIORITY`,
`F3_INVALID_GRACE`, `F3_RATE_NOT_A_FRACTION`, `F3_DERIVED_COMMITMENT_HAS_AMOUNT`, `F3_UNKNOWN_FUNDING_SOURCE`,
`F3_OWNERSHIP_ABOVE_100`, `F3_PREFERRED_EQUITY_DEFERRED`.

## 6. Serialization, compatibility, migration

* `to_dict/from_dict` with `schema_version`; unknown future versions fail closed; unknown keys rejected.
* Additive only: `ProjectInputs` gains an **optional** `financing_instruments: FinancingCollection | None = None`
  in F3.1/F3.2, default `None`, excluded from `project_inputs_to_dict` when `None` (byte-identical payloads) —
  the same discipline as `development_economics`.
* **Legacy mapping** (prototype `legacy_mapping.py`, read-only): one Senior (`CANONICAL_SIZING_DERIVED`), explicit
  Share Capital / Share Premium, and the residual instrument (`SHL` or `ADDITIONAL_EQUITY` by
  `sponsor_funding_mode`). Missing collection never maps to "zero Senior". Mapping is proven to reproduce current
  results bit-for-bit **before** activation (`F3_FINANCIAL_EQUIVALENCE_TEST_PLAN.md`).
* **No silent migration.** Existing projects are never rewritten; opting in is an explicit user action that records
  the mapping and its equivalence evidence.
* Historical Runs keep their run-bound identity; they are never re-interpreted.

## 7. Proposed persistence (F3.2)

Typed project-level authority stored like the contingency authority (`projects.replay_metadata_json` precedent): owner
auth, protected-reference rejection, compare-and-swap, scenario isolation, composite-identity inclusion **only when
present**, run-bound identity recorded for export parity. Concrete schema is decided at F3.2 review; no persistence is
added now.
