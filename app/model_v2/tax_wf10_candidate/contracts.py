"""WF-10 — Advanced Tax & Jurisdiction Contracts candidate: typed contracts.

RELEASE-CLOSED CANDIDATE. This package is not released financial authority,
is never imported by any production path, and adds no product surface.
Every public calculation entry point is gated behind
:data:`ACTIVATION_ENABLED` (a module-level literal ``False``). Only
isolated acceptance fixtures may enable the gate in memory; no environment
variable, customer payload or product surface can enable it.

Design rules (mission §3):

- Evidence-supplied only. Every rate, percentage, threshold and convention
  used by the candidate is EXPLICITLY SUPPLIED by the caller. A
  jurisdiction identifier is an OPAQUE label: it NEVER silently selects a
  rate, a treaty, an exemption or a recovery rule. A date or entity with
  no supplied evidence yields a typed UNAVAILABLE, never a default.
- No invented law. Tax rates, national exemptions, treaties, depreciation
  schedules and VAT recovery rules are not fabricated here. Unsupported
  methods/arrangements (declining-balance depreciation, interest-limitation
  carryforward, deferred tax, consolidation) fail closed with
  ``TAX_WF10_UNSUPPORTED`` and are recorded as Financial Owner decisions
  (``docs/model_v2/WF10_TAX_OWNER_DECISIONS.md``).
- Deterministic money: all amounts are kEUR (the engine's canonical unit);
  exact ``Decimal`` arithmetic with 6-decimal-place output quantisation;
  percentages are 0..100, rates are 0..1; both are strict-typed (bool and
  non-finite rejected).
- Relationship to released authorities: the production CIT engine
  (``financial_engine/tax/**`` — flat corporate rate, calendar-year
  fragments, vintage FIFO loss ledger, annual ATAD), the audit-only
  Phase 6A/6B/6C engines (``finco_core/tax/**``) and the canonical
  depreciation engine (``finco_core/depreciation/**``) are REUSED as the
  released capabilities; nothing here replaces or re-derives them. The
  candidate adds the explicitly evidence-supplied contracts the released
  stack does not have: dated rate schedules, explicit LCF
  expiration/utilisation conventions, ATAD-style inputs/outputs with
  disallowed-interest outputs, tax-vs-book temporary-difference ledgers,
  a VAT recovery/position engine, evidence-supplied withholding with
  gross/net conservation and double-withholding prevention, and
  separate-entity (SPV/HoldCo) ledgers with zero leakage.
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass
from datetime import date
from typing import Optional, Tuple

#: Release-closure flag (house convention). Candidate content is not
#: released authority. Only isolated acceptance fixtures enable this gate;
#: no environment variable or customer payload can enable it.
ACTIVATION_ENABLED = False


def require_release() -> None:
    if not ACTIVATION_ENABLED:
        raise ValueError(
            "TAX_WF10_RELEASE_CLOSED: independent financial release "
            "approval required")


# ── Strict primitives ────────────────────────────────────────────────────────


def _fail(code: str, message: str) -> ValueError:
    return ValueError(f"{code}: {message}")


def _num(value, label: str, *, minimum: Optional[float] = None,
         maximum: Optional[float] = None, exclusive_min: bool = False) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) \
            or not math.isfinite(float(value)):
        raise _fail("TAX_WF10_VALUE", f"{label} must be a finite number, got "
                                      f"{value!r}")
    v = float(value)
    if minimum is not None:
        if exclusive_min and v <= minimum:
            raise _fail("TAX_WF10_VALUE",
                        f"{label} must be strictly above {minimum}")
        if not exclusive_min and v < minimum:
            raise _fail("TAX_WF10_VALUE", f"{label} must be at least {minimum}")
    if maximum is not None and v > maximum:
        raise _fail("TAX_WF10_VALUE", f"{label} must be at most {maximum}")
    return v


def _pct(value, label: str) -> float:
    """Percentage 0..100 (never a fraction)."""
    if isinstance(value, bool) or not isinstance(value, (int, float)) \
            or not math.isfinite(float(value)):
        raise _fail("TAX_WF10_VALUE", f"{label} must be a finite number")
    v = float(value)
    if not 0.0 <= v <= 100.0:
        raise _fail("TAX_WF10_VALUE",
                    f"{label} is a percentage and must be within [0, 100], "
                    f"got {v!r}")
    return v


def _rate(value, label: str) -> float:
    """Fractional rate 0..1 (never a percentage)."""
    return _num(value, label, minimum=0.0, maximum=1.0)


def _date(value, label: str) -> date:
    if not isinstance(value, date):
        raise _fail("TAX_WF10_SCHEMA", f"{label} must be a datetime.date")
    return value


def _choice(value, label: str, allowed) -> str:
    if not isinstance(value, str) or value not in allowed:
        raise _fail("TAX_WF10_UNSUPPORTED",
                    f"{label} {value!r} is not supported (supported: "
                    f"{sorted(allowed)})")
    return value


def _identity(value, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise _fail("TAX_WF10_SCHEMA", f"{label} is required and must be a "
                                       "non-empty string")
    if len(value) > 200:
        raise _fail("TAX_WF10_IDENTITY",
                    f"{label} must be at most 200 characters")
    return value


# ── A. Entities, jurisdiction (opaque) and dated CIT rates ───────────────────

TAX_ENTITY_KINDS = ("SPV", "HOLDCO")


@dataclass(frozen=True)
class TaxEntityIdentity:
    """Explicit tax-entity identity.

    ``jurisdiction_code`` is an OPAQUE label (canonical 2-character code)
    carried for attribution and reporting only. It NEVER selects a rate,
    a treaty, a recovery rule or any other treatment: every economic
    parameter arrives through its own explicitly supplied contract."""

    entity_id: str
    jurisdiction_code: str
    entity_kind: str

    def validate(self) -> None:
        _identity(self.entity_id, "entity_id")
        code = self.jurisdiction_code
        if not isinstance(code, str) or len(code) != 2 \
                or not code.isalpha() or not code.isupper():
            raise _fail("TAX_WF10_SCHEMA",
                        "jurisdiction_code must be a canonical 2-character "
                        "uppercase code (an opaque label; it never selects "
                        "rates or treatments)")
        _choice(self.entity_kind, "entity_kind", TAX_ENTITY_KINDS)


RATE_SCHEDULE_MODES = ("FLAT", "DATED_SERIES")


@dataclass(frozen=True)
class TaxRateWindow:
    """One dated CIT rate window: ``[effective_from, next window's from)``."""

    effective_from: date
    rate: float

    def validate(self) -> None:
        _date(self.effective_from, "rate window effective_from")
        _rate(self.rate, "rate window rate")


@dataclass(frozen=True)
class TaxRateSchedule:
    """Evidence-supplied corporate income tax rate schedule.

    FLAT: one explicit rate for every date. DATED_SERIES: windows sorted
    by ``effective_from``; a date before the first window is UNAVAILABLE
    (never a default rate); two windows sharing an effective_from fail
    closed. The schedule covers DATES — mapping periods to tax years and
    detecting a rate change INSIDE one tax year is the caller's
    responsibility and fails closed in
    ``pure.corporate_tax_for_tax_year``."""

    mode: str
    flat_rate: Optional[float] = None
    windows: Tuple[TaxRateWindow, ...] = ()

    def validate(self) -> None:
        _choice(self.mode, "tax_rate_schedule.mode", RATE_SCHEDULE_MODES)
        if self.mode == "FLAT":
            if self.flat_rate is None:
                raise _fail("TAX_WF10_SCHEMA", "FLAT mode requires flat_rate")
            _rate(self.flat_rate, "tax_rate_schedule.flat_rate")
            if self.windows:
                raise _fail("TAX_WF10_SCHEMA",
                            "FLAT mode must not carry windows")
        else:
            if not self.windows:
                raise _fail("TAX_WF10_SCHEMA",
                            "DATED_SERIES requires at least one window")
            if self.flat_rate is not None:
                raise _fail("TAX_WF10_SCHEMA",
                            "DATED_SERIES must not carry flat_rate")
            ordered = sorted(self.windows, key=lambda w: w.effective_from)
            for window in ordered:
                window.validate()
            for earlier, later in zip(ordered, ordered[1:]):
                if later.effective_from == earlier.effective_from:
                    raise _fail("TAX_WF10_OVERLAP",
                                f"two rate windows share effective_from "
                                f"{earlier.effective_from}")

    def rate_on(self, when: date) -> Optional[float]:
        """The CIT rate effective on an exact date, or None when a
        DATED_SERIES does not cover the date (typed UNAVAILABLE)."""
        self.validate()
        if self.mode == "FLAT":
            return self.flat_rate
        applicable: Optional[TaxRateWindow] = None
        for window in self.windows:
            if window.effective_from <= when:
                applicable = window
        return None if applicable is None else applicable.rate


# ── A. Tax-loss carryforward conventions ─────────────────────────────────────


@dataclass(frozen=True)
class TaxLossCarryforwardConfig:
    """Explicitly supplied loss utilisation and expiration rules.

    Exactly one of ``unlimited`` or ``carryforward_years`` must be
    supplied (never both, never neither). ``utilisation_cap_pct`` is the
    share of the period's positive taxable income that losses may offset
    (0..100, explicit — the production engine's implicit 100% is NOT
    assumed here)."""

    utilisation_cap_pct: float
    carryforward_years: Optional[int] = None
    unlimited: bool = False

    def validate(self) -> None:
        _pct(self.utilisation_cap_pct,
             "loss carryforward utilisation_cap_pct")
        if self.unlimited:
            if self.carryforward_years is not None:
                raise _fail("TAX_WF10_SCHEMA",
                            "carryforward_years must be omitted when "
                            "unlimited is supplied")
        else:
            if not isinstance(self.carryforward_years, int) \
                    or isinstance(self.carryforward_years, bool) \
                    or self.carryforward_years < 1:
                raise _fail("TAX_WF10_SCHEMA",
                            "carryforward_years must be an integer >= 1 "
                            "unless unlimited is explicitly supplied")


@dataclass(frozen=True)
class OpeningLossVintage:
    """An explicitly supplied opening tax-loss vintage."""

    origin_tax_year: int
    amount_keur: float

    def validate(self) -> None:
        if not isinstance(self.origin_tax_year, int) \
                or isinstance(self.origin_tax_year, bool) \
                or self.origin_tax_year < 1:
            raise _fail("TAX_WF10_VALUE",
                        "origin_tax_year must be an integer >= 1")
        _num(self.amount_keur, "opening loss amount_keur", minimum=0.0)


# ── A. Interest limitation (ATAD-style) inputs ───────────────────────────────

INTEREST_LIMITATION_COMBINATIONS = ("MAX",)


@dataclass(frozen=True)
class InterestLimitationInputs:
    """Explicitly supplied interest-limitation (ATAD-style) inputs.

    ``capacity = max(ebitda_limit_pct/100 × ebitda, de_minimis_keur)``
    computed on the caller's declared tax-year EBITDA and net interest.
    Both parameters are explicit evidence; neither has a default.
    Disallowed-interest CARRYFORWARD is typed UNSUPPORTED (the released
    production engine raises the same way) — V1 computes per-tax-year
    outputs only. EBITDA <= 0: the percentage term is non-positive, so
    the capacity is the de-minimis threshold alone (the all-limited
    alternative is Financial Owner decision D-04)."""

    ebitda_keur: float
    net_interest_keur: float
    ebitda_limit_pct: float
    de_minimis_keur: float
    enabled: bool = True

    def validate(self) -> None:
        _num(self.ebitda_keur, "interest limitation ebitda_keur")
        _num(self.net_interest_keur, "interest limitation net_interest_keur",
             minimum=0.0)
        _pct(self.ebitda_limit_pct, "interest limitation ebitda_limit_pct")
        _num(self.de_minimis_keur, "interest limitation de_minimis_keur",
             minimum=0.0)
        if not isinstance(self.enabled, bool):
            raise _fail("TAX_WF10_VALUE", "enabled must be a boolean")


# ── B. Depreciation ──────────────────────────────────────────────────────────

DEPRECIATION_METHODS = ("STRAIGHT_LINE",)


@dataclass(frozen=True)
class DepreciationAsset:
    """One asset's explicit financial vs tax depreciation terms.

    Straight-line is the ONLY method in V1: any other method fails closed
    (inventing accelerated depreciation is prohibited; a supported method
    requires evidence plus an approved convention). ``in_service_date``
    must be on or after the project COD — construction-period tax
    depreciation is Financial Owner decision D-06 and fails closed here."""

    asset_id: str
    category: str
    gross_basis_keur: float
    book_useful_life_years: int
    tax_useful_life_years: int
    in_service_date: date
    method: str = "STRAIGHT_LINE"

    def validate(self, *, cod_date: Optional[date] = None) -> None:
        _identity(self.asset_id, "asset_id")
        _identity(self.category, "category")
        _num(self.gross_basis_keur, "depreciation gross_basis_keur",
             minimum=0.0, exclusive_min=True)
        for label, years in (("book_useful_life_years",
                              self.book_useful_life_years),
                             ("tax_useful_life_years",
                              self.tax_useful_life_years)):
            if not isinstance(years, int) or isinstance(years, bool) \
                    or years < 1:
                raise _fail("TAX_WF10_VALUE",
                            f"{label} must be an integer >= 1")
        _date(self.in_service_date, "in_service_date")
        if self.method != "STRAIGHT_LINE":
            raise _fail(
                "TAX_WF10_UNSUPPORTED",
                f"depreciation method {self.method!r} is not supported in "
                "V1: only STRAIGHT_LINE is implemented; any other method "
                "requires supplied evidence and an approved convention "
                "(no invented accelerated depreciation)")
        if cod_date is not None and self.in_service_date < cod_date:
            raise _fail(
                "TAX_WF10_UNSUPPORTED",
                f"asset {self.asset_id!r} is in service "
                f"{self.in_service_date} before COD {cod_date}: "
                "construction-period tax depreciation is Financial Owner "
                "decision D-06 and is unsupported in V1")


# ── C. VAT ───────────────────────────────────────────────────────────────────

VAT_PHASES = ("CONSTRUCTION", "OPERATING")
NONRECOVERABLE_TREATMENTS = ("CAPITALISE", "EXPENSE")


@dataclass(frozen=True)
class VatConfig:
    """Explicitly supplied VAT parameters.

    Recovery percentages for BOTH phases are required evidence — there is
    no assumed recoverability and no default (mission: "explicit handling
    of missing recovery assumptions"). ``nonrecoverable_treatment``
    (CAPITALISE vs EXPENSE) is an explicit Financial Owner policy field;
    it has no default."""

    rate: float
    recovery_pct_construction: float
    recovery_pct_operating: float
    nonrecoverable_treatment: str

    def validate(self) -> None:
        _rate(self.rate, "vat rate")
        _pct(self.recovery_pct_construction,
             "vat recovery_pct_construction")
        _pct(self.recovery_pct_operating, "vat recovery_pct_operating")
        _choice(self.nonrecoverable_treatment,
                "vat nonrecoverable_treatment", NONRECOVERABLE_TREATMENTS)


@dataclass(frozen=True)
class VatPeriodInput:
    """One period's declared net (VAT-exclusive) amounts and phase."""

    phase: str
    output_net_keur: float
    input_net_keur: float

    def validate(self) -> None:
        _choice(self.phase, "vat period phase", VAT_PHASES)
        _num(self.output_net_keur, "vat output_net_keur", minimum=0.0)
        _num(self.input_net_keur, "vat input_net_keur", minimum=0.0)


# ── D. Withholding tax ───────────────────────────────────────────────────────

WHT_FLOW_TYPES = ("DIVIDEND", "SHL_INTEREST", "SENIOR_INTEREST",
                  "JUNIOR_INTEREST")


@dataclass(frozen=True)
class WithholdingRule:
    """An evidence-supplied withholding rule for one flow type.

    ``rate`` has NO default: it arrives with the rule or the rule is not
    constructible. ``legal_basis_ref`` is REQUIRED for every flow type
    (evidence traceability); there is NO default treaty relief, beneficial-
    ownership or exemption assumption anywhere. Senior/junior interest
    additionally refuse an empty basis with a dedicated code (mission:
    only where a supported legal basis is supplied). Entity and recipient
    jurisdictions are carried as opaque labels."""

    flow_type: str
    rate: float
    paying_entity_id: str
    recipient_entity_id: str
    legal_basis_ref: str

    def validate(self) -> None:
        _choice(self.flow_type, "withholding flow_type", WHT_FLOW_TYPES)
        _rate(self.rate, "withholding rate")
        _identity(self.paying_entity_id, "withholding paying_entity_id")
        _identity(self.recipient_entity_id, "withholding recipient_entity_id")
        _identity(self.legal_basis_ref, "withholding legal_basis_ref")
        if self.flow_type in ("SENIOR_INTEREST", "JUNIOR_INTEREST") \
                and len(self.legal_basis_ref.strip()) < 3:
            raise _fail(
                "TAX_WF10_UNSUPPORTED",
                f"{self.flow_type} withholding requires a supported legal "
                "basis reference (senior/junior interest withholding is "
                "only modelled where the legal basis is supplied)")


# ── E. Multiple tax entities and intercompany flows ──────────────────────────

INTERCOMPANY_FLOW_TYPES = ("INTEREST", "DIVIDEND", "PRINCIPAL", "SERVICE")


@dataclass(frozen=True)
class IntercompanyFlow:
    """One explicitly supplied intercompany flow (no consolidation)."""

    flow_id: str
    payer_entity_id: str
    payee_entity_id: str
    flow_type: str
    period_index: int
    gross_keur: float

    def validate(self) -> None:
        _identity(self.flow_id, "intercompany flow_id")
        _identity(self.payer_entity_id, "intercompany payer_entity_id")
        _identity(self.payee_entity_id, "intercompany payee_entity_id")
        if self.payer_entity_id == self.payee_entity_id:
            raise _fail("TAX_WF10_VALUE",
                        "intercompany flow payer and payee must differ")
        _choice(self.flow_type, "intercompany flow_type",
                INTERCOMPANY_FLOW_TYPES)
        if not isinstance(self.period_index, int) \
                or isinstance(self.period_index, bool) or self.period_index < 0:
            raise _fail("TAX_WF10_VALUE",
                        "intercompany period_index must be an integer >= 0")
        _num(self.gross_keur, "intercompany gross_keur", minimum=0.0)


@dataclass(frozen=True)
class TaxEntityBook:
    """One tax entity's explicitly supplied book (no consolidation).

    Every component is optional evidence; a component that is absent is
    simply not modelled for that entity (typed absence — never a default
    treatment)."""

    identity: TaxEntityIdentity
    rate_schedule: Optional[TaxRateSchedule] = None
    loss_config: Optional[TaxLossCarryforwardConfig] = None
    opening_loss_vintages: Tuple[OpeningLossVintage, ...] = ()
    interest_limitation: Optional[InterestLimitationInputs] = None
    vat_config: Optional[VatConfig] = None

    def validate(self) -> None:
        self.identity.validate()
        if self.rate_schedule is not None:
            self.rate_schedule.validate()
        if self.loss_config is not None:
            self.loss_config.validate()
            for vintage in self.opening_loss_vintages:
                vintage.validate()
        elif self.opening_loss_vintages:
            raise _fail("TAX_WF10_SCHEMA",
                        "opening loss vintages require a loss carryforward "
                        "configuration")
        if self.interest_limitation is not None:
            self.interest_limitation.validate()
        if self.vat_config is not None:
            self.vat_config.validate()


@dataclass(frozen=True)
class TaxCandidateBook:
    """The composed multi-entity candidate book.

    Validation guarantees: unique entity ids; withholding rules and
    intercompany flows reference KNOWN entities; no payer==payee flow;
    unique flow ids (double-withholding / double-counting prevention).
    There is NO consolidation: each entity keeps its own ledger."""

    entities: Tuple[TaxEntityBook, ...]
    withholding_rules: Tuple[WithholdingRule, ...] = ()
    intercompany_flows: Tuple[IntercompanyFlow, ...] = ()

    def validate(self) -> None:
        if not self.entities:
            raise _fail("TAX_WF10_SCHEMA",
                        "the candidate book requires at least one entity")
        seen = set()
        for entity in self.entities:
            entity.validate()
            if entity.identity.entity_id in seen:
                raise _fail("TAX_WF10_IDENTITY",
                            f"duplicate tax entity "
                            f"{entity.identity.entity_id!r}")
            seen.add(entity.identity.entity_id)
        rule_ids = set()
        for rule in self.withholding_rules:
            rule.validate()
            for ref in (rule.paying_entity_id, rule.recipient_entity_id):
                if ref not in seen:
                    raise _fail("TAX_WF10_IDENTITY",
                                f"withholding rule references unknown entity "
                                f"{ref!r}")
            rule_key = (rule.flow_type, rule.paying_entity_id,
                        rule.recipient_entity_id)
            if rule_key in rule_ids:
                raise _fail("TAX_WF10_IDENTITY",
                            f"duplicate withholding rule for {rule_key}")
            rule_ids.add(rule_key)
        flow_ids = set()
        for flow in self.intercompany_flows:
            flow.validate()
            for ref in (flow.payer_entity_id, flow.payee_entity_id):
                if ref not in seen:
                    raise _fail("TAX_WF10_IDENTITY",
                                f"intercompany flow references unknown entity "
                                f"{ref!r}")
            if flow.flow_id in flow_ids:
                raise _fail("TAX_WF10_IDENTITY",
                            f"duplicate intercompany flow_id {flow.flow_id!r}")
            flow_ids.add(flow.flow_id)

    def entity(self, entity_id: str) -> Optional["TaxEntityBook"]:
        for entity in self.entities:
            if entity.identity.entity_id == entity_id:
                return entity
        return None


# ── Deterministic serialization ──────────────────────────────────────────────


def canonical_json(payload) -> str:
    """Sorted-key, ASCII, NaN-refusing canonical JSON (house convention)."""
    require_release()
    return json.dumps(payload, sort_keys=True, ensure_ascii=True,
                      allow_nan=False, separators=(",", ":"))
