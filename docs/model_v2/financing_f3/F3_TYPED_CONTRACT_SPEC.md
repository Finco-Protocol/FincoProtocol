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
| `instrument_id`, `name` | str | id matches `^[a-z0-9][a-z0-9-]{0,63}$` and is unique; name non-empty text |
| `instrument_type` | enum | DEBT family: SENIOR_TERM_LOAN, CONSTRUCTION_FACILITY, JUNIOR_DEBT, MEZZANINE_DEBT, SHAREHOLDER_LOAN, BOND |
| `currency` | str | must equal model currency (EUR); FX out of scope |
| `commitment_keur` + `commitment_authority` | float? + enum | EXPLICIT ⇒ finite, ≥ 0, required; `CANONICAL_SIZING_DERIVED` / `RESIDUAL_DERIVED` ⇒ amount **must be absent** (it is an output) |
| `drawdowns[]` | (date, amount) | real dates (not datetimes), strictly increasing, Σ ≤ commitment; empty = engine-derived draws |
| `interest` | mode FIXED / PERIOD_SCHEDULE / FLOATING_BASE_PLUS_MARGIN; fraction rate; `margin_bps`; strict-bool PIK flag | rates are **fractions** (0.05 = 5%); percent-style values rejected; FIXED needs `fixed_rate` and may not carry a margin; FLOATING needs an integer `margin_bps` in 0..10000 and may not carry a fixed rate; PERIOD_SCHEDULE carries neither |
| `repayment` | mode BULLET / LEVEL_PRINCIPAL / DSCR_SCULPTED / EXPLICIT_SCHEDULE / CASH_SWEEP / NONE; grace months; `maturity_authority` EXPLICIT_DATE or PERIOD_AXIS_DERIVED; `maturity_date`; informational `tenor_years` / `maturity_period_index` | EXPLICIT_DATE ⇒ a real `date` is required and tenor/index must be absent; PERIOD_AXIS_DERIVED ⇒ the maturity is an **output** of the canonical operating period axis and **must not carry a date**; grace ≥ 0 plain int |
| `seniority_rank` | int ≥ 1 | 1 = most senior |
| `fees[]` | kind UPFRONT / COMMITMENT / AGENCY (enum); rate fraction; basis ∈ {COMMITMENT, UNDRAWN, DRAWN} | rate in [0,1]; **basis is documentary until an authority consumes it** |
| `covenants` (future) | per-facility target DSCR, lock-up, min LLCR | never share one denominator across facilities |
| `reserve_support` (future) | DSRA / DSRF reference | per facility or aggregate-senior, explicit |
| `cash_sweep` (future) | % / priority | requires waterfall integration (F3.5) |
| `enabled` | strict `bool` (no 0/1/"yes") | disabled ⇒ zero economic effect (`FinancingCollection.active()` excludes it), but it is retained, still fully validated and still part of the proposal identity |
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
`F3_OWNERSHIP_ABOVE_100`, `F3_PREFERRED_EQUITY_DEFERRED`, `F3_INVALID_ID`, `F3_INVALID_ENUM`, `F3_INVALID_BOOL`,
`F3_INVALID_MARGIN`, `F3_INVALID_FEE_BASIS`, `F3_INVALID_TERM`, `F3_UNSUPPORTED_SCHEMA_VERSION`, `F3_LEGACY_MAPPING_UNRESOLVED`.
All enum-typed fields must be actual enum members (strings are rejected); containers must be typed tuples.

## 6. Serialization, compatibility, migration

* `to_dict/from_dict` with `schema_version`; unknown future versions fail closed; unknown keys rejected.
* Additive only: `ProjectInputs` gains an **optional** `financing_instruments: FinancingCollection | None = None`
  in F3.1/F3.2, default `None`, excluded from `project_inputs_to_dict` when `None` (byte-identical payloads) —
  the same discipline as `development_economics`.
* **Legacy mapping** (prototype `legacy_mapping.py`, read-only) — Correction A rules:
  * **Senior maturity is never `financial_close + n years`.** The canonical maturity is the last of
    `senior_tenor_years × periods_per_year` *operating* periods (`senior_debt/project_adapter.py`), anchored at the first
    operating period (COD) on the model period axis. The mapping records `PERIOD_AXIS_DERIVED` + `tenor_years` and **no
    date**. Financial Close and COD do not influence the mapped identity; leap-day closes cannot fail.
  * **Senior repayment** follows the typed `debt_sizing_mode` (and `gearing_cap_repayment_method` for GEARING_CAP); the
    legacy `amortization_type` string is not an authority. Unset/unknown ⇒ fail closed (`F3_LEGACY_MAPPING_UNRESOLVED`).
  * **Residual instrument by `SponsorFundingMode`** — must be an explicit enum member (the canonical G2A stack itself
    requires it). `None`/unknown/strings ⇒ fail closed. `SHARE_CAPITAL_THEN_SHL` ⇒ shareholder loan;
    `EQUITY_ONLY` ⇒ additional equity (no SHL).
  * **SHL repayment** maps only proven clean-SHL semantics: `BULLET` and `CASH_SWEEP` (the only modes the clean adapter
    accepts). `PIK`, `ACCRUED`, `PIK_THEN_SWEEP`, `PARTIAL_PAY_SWEEP`, `FCF_WATERFALL` or unset ⇒ fail closed. The four
    reference verticals all use `CASH_SWEEP`. SHL maturity is the canonical `shl_maturity_period_index` (a period-axis
    index), not a date.
  * Explicit Share Capital / Share Premium amounts are mapped as-is. Missing collection never maps to "zero Senior";
    the Senior commitment is `CANONICAL_SIZING_DERIVED`. Mapping is proven to reproduce current results bit-for-bit
    **before** activation (`F3_FINANCIAL_EQUIVALENCE_TEST_PLAN.md`).
* **No silent migration.** Existing projects are never rewritten; opting in is an explicit user action that records
  the mapping and its equivalence evidence.
* Historical Runs keep their run-bound identity; they are never re-interpreted.

## 7. Proposed persistence (F3.2)

Typed project-level authority stored like the contingency authority (`projects.replay_metadata_json` precedent): owner
auth, protected-reference rejection, compare-and-swap, scenario isolation, composite-identity inclusion **only when
present**, run-bound identity recorded for export parity. Concrete schema is decided at F3.2 review; no persistence is
added now.
