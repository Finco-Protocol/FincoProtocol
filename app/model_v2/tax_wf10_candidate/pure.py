"""WF-10 tax candidate — deterministic pure evaluation helpers.

RELEASE-CLOSED: every public function calls ``require_release()`` and the
package is never imported by production. All helpers are deterministic,
side-effect free, and consume EXPLICITLY SUPPLIED evidence. Money is kEUR;
outputs are exact ``Decimal`` quantised to 6 decimal places (house
candidate convention); no rounding rule is invented beyond that.

None of these helpers calls the released engines; they consume
canonical-shaped, independently supplied evidence so a future release
integration (see ``WF10_TAX_CANDIDATE_DESIGN.md``) can wire them beside
the production CIT stack without re-deriving it.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import Mapping, Optional, Sequence, Tuple

from app.model_v2.tax_wf10_candidate.contracts import (
    ACTIVATION_ENABLED,
    DepreciationAsset,
    InterestLimitationInputs,
    TaxEntityBook,
    TaxLossCarryforwardConfig,
    TaxRateSchedule,
    VatConfig,
    VatPeriodInput,
    WithholdingRule,
    require_release,
)

activation_enabled = lambda: ACTIVATION_ENABLED  # noqa: E731

_QUANTUM = Decimal("0.000001")


def _fail(code: str, message: str) -> ValueError:
    return ValueError(f"{code}: {message}")


def _q(value: Decimal) -> Decimal:
    return Decimal(value).quantize(_QUANTUM, rounding=ROUND_HALF_UP)


def _dec(value, label: str) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, (int, float)) \
            or not math.isfinite(float(value)):
        raise _fail("TAX_WF10_VALUE", f"{label} must be a finite number")
    return Decimal(str(float(value)))


# ── A. CIT: reconciliation, dated rates, loss schedule ───────────────────────


@dataclass(frozen=True)
class TaxableIncomeReconciliation:
    """Explicit taxable-income reconciliation for one tax year (kEUR).

    Identity (exact, asserted): ``taxable_before_losses == ebitda +
    financing_income − tax_depreciation + non_deductible_addbacks −
    deductible_interest``. ``taxable_after_losses`` floors at zero: a
    negative result generates a new loss vintage (``loss_generated``) and
    NEVER a negative tax."""

    tax_year: int
    ebitda_keur: Decimal
    financing_income_keur: Decimal
    tax_depreciation_keur: Decimal
    non_deductible_addbacks_keur: Decimal
    deductible_interest_keur: Decimal
    loss_used_keur: Decimal
    taxable_before_losses_keur: Decimal
    taxable_after_losses_keur: Decimal
    loss_generated_keur: Decimal


def taxable_income_reconciliation(
    *,
    tax_year: int,
    ebitda_keur: float,
    financing_income_keur: float = 0.0,
    tax_depreciation_keur: float,
    non_deductible_addbacks_keur: float = 0.0,
    deductible_interest_keur: float,
    loss_used_keur: float = 0.0,
) -> TaxableIncomeReconciliation:
    """Deterministic taxable-income reconciliation with explicit lines.

    Every input is an explicitly supplied evidence amount (kEUR);
    ``non_deductible_addbacks_keur`` bundles fiscal reintegration and ATAD
    add-backs declared by the caller. The reconciliation identity is
    asserted exactly; the loss offset is bounded by the caller's
    utilisation schedule (``pure.tax_loss_schedule`` supplies
    ``loss_used_keur``)."""
    require_release()
    if not isinstance(tax_year, int) or isinstance(tax_year, bool) \
            or tax_year < 1:
        raise _fail("TAX_WF10_VALUE", "tax_year must be an integer >= 1")
    ebitda = _dec(ebitda_keur, "ebitda_keur")
    financing_income = _dec(financing_income_keur, "financing_income_keur")
    tax_dep = _dec(tax_depreciation_keur, "tax_depreciation_keur")
    addbacks = _dec(non_deductible_addbacks_keur,
                    "non_deductible_addbacks_keur")
    interest = _dec(deductible_interest_keur, "deductible_interest_keur")
    loss_used = _dec(loss_used_keur, "loss_used_keur")
    if loss_used < 0:
        raise _fail("TAX_WF10_VALUE", "loss_used_keur must be non-negative")
    before = ebitda + financing_income - tax_dep + addbacks - interest
    after = before - loss_used
    if after < 0:
        loss_generated = -after
        after = Decimal(0)
    else:
        loss_generated = Decimal(0)
    return TaxableIncomeReconciliation(
        tax_year=tax_year,
        ebitda_keur=_q(ebitda),
        financing_income_keur=_q(financing_income),
        tax_depreciation_keur=_q(tax_dep),
        non_deductible_addbacks_keur=_q(addbacks),
        deductible_interest_keur=_q(interest),
        loss_used_keur=_q(loss_used),
        taxable_before_losses_keur=_q(before),
        taxable_after_losses_keur=_q(after),
        loss_generated_keur=_q(loss_generated),
    )


def corporate_tax_for_tax_year(
    *,
    taxable_income_keur: Decimal,
    tax_rate_schedule: TaxRateSchedule,
    tax_year_start: date,
    tax_year_end: date,
) -> Optional[Decimal]:
    """CIT liability for one tax year at the evidence-supplied rate.

    The rate must be UNAMBIGUOUS for the whole tax year: the rates
    effective on the year's first and last date must be identical — a
    rate change inside a tax year fails closed
    (``TAX_WF10_TAX_YEAR_RATE_SPLIT``) rather than blending. A date not
    covered by a DATED_SERIES is UNAVAILABLE (``None``) — never a default
    rate. Negative taxable income yields zero tax (loss generation is
    the reconciliation's concern)."""
    require_release()
    schedule = tax_rate_schedule
    schedule.validate()
    start_rate = schedule.rate_on(tax_year_start)
    end_rate = schedule.rate_on(tax_year_end)
    if start_rate is None or end_rate is None:
        return None
    if start_rate != end_rate:
        raise _fail(
            "TAX_WF10_TAX_YEAR_RATE_SPLIT",
            f"the CIT rate changes inside tax year "
            f"[{tax_year_start} .. {tax_year_end}] "
            f"({start_rate} -> {end_rate}); the caller must align tax years "
            "to the rate schedule (no silent blending)")
    taxable = _dec(float(taxable_income_keur), "taxable_income_keur")
    if taxable < 0:
        taxable = Decimal(0)
    return _q(taxable * Decimal(str(start_rate)))


@dataclass(frozen=True)
class LossVintageRow:
    """One tax year's vintage-FIFO loss ledger row (kEUR, exact)."""

    tax_year: int
    opening_by_vintage: Tuple[Tuple[int, Decimal], ...]
    generated_keur: Decimal
    used_keur: Decimal
    expired_keur: Decimal
    closing_by_vintage: Tuple[Tuple[int, Decimal], ...]


@dataclass(frozen=True)
class LossLedgerResult:
    """Full loss ledger with the per-year identity
    ``opening + generated − used − expired == closing`` (asserted)."""

    rows: Tuple[LossVintageRow, ...]
    total_used_keur: Decimal
    total_expired_keur: Decimal
    closing_total_keur: Decimal


def tax_loss_schedule(
    *,
    taxable_income_after_limits_by_tax_year: Mapping[int, Decimal],
    config: TaxLossCarryforwardConfig,
    opening_vintages: Sequence = (),
    first_tax_year: int,
) -> LossLedgerResult:
    """Vintage-FIFO loss ledger with EXPLICITLY SUPPLIED expiration rules.

    ``config`` carries the caller's expiration window (``unlimited`` or an
    integer year count) and utilisation cap; nothing is defaulted. A
    vintage origin on/after ``first_tax_year`` fails closed (future-dated
    opening losses never enter the ledger). Vintages expire BEFORE use in
    the year after their last usable year; FIFO consumption honours the
    utilisation cap as a share of the year's positive taxable income.
    The per-year identity is asserted exactly."""
    require_release()
    config.validate()
    if not isinstance(first_tax_year, int) or isinstance(first_tax_year, bool) \
            or first_tax_year < 1:
        raise _fail("TAX_WF10_VALUE", "first_tax_year must be an integer >= 1")
    ledger: dict[int, Decimal] = {}
    for vintage in opening_vintages:
        vintage.validate()
        if vintage.origin_tax_year >= first_tax_year:
            raise _fail(
                "TAX_WF10_VALUE",
                f"opening loss vintage {vintage.origin_tax_year} is not in "
                "the past relative to first_tax_year "
                f"{first_tax_year} (future-dated opening losses are "
                "rejected)")
        ledger[vintage.origin_tax_year] = (
            ledger.get(vintage.origin_tax_year, Decimal(0))
            + _dec(vintage.amount_keur, "opening vintage amount"))
    years = sorted(taxable_income_after_limits_by_tax_year)
    if not years:
        raise _fail("TAX_WF10_VALUE",
                    "at least one tax year of taxable income is required")
    rows = []
    total_used = Decimal(0)
    total_expired = Decimal(0)
    for year in years:
        income = _dec(float(taxable_income_after_limits_by_tax_year[year]),
                      f"taxable income [{year}]")
        # expiry BEFORE use
        expired = Decimal(0)
        if not config.unlimited:
            for origin in sorted(ledger):
                if ledger[origin] <= 0:
                    continue
                if year > origin + config.carryforward_years:
                    expired += ledger[origin]
                    ledger[origin] = Decimal(0)
        # FIFO use, capped
        used = Decimal(0)
        if income > 0:
            capacity = income * Decimal(str(config.utilisation_cap_pct)) / Decimal(100)
            for origin in sorted(ledger):
                if used >= capacity:
                    break
                available = ledger.get(origin, Decimal(0))
                if available <= 0:
                    continue
                take = min(available, capacity - used)
                ledger[origin] = available - take
                used += take
        # new vintage from a loss year
        generated = Decimal(0)
        if income < 0:
            generated = -income
            ledger[year] = ledger.get(year, Decimal(0)) + generated
        closing = {origin: amount for origin, amount in ledger.items()
                   if amount > 0}
        rows.append(LossVintageRow(
            tax_year=year,
            opening_by_vintage=(),  # filled by the replay audit below
            generated_keur=_q(generated),
            used_keur=_q(used),
            expired_keur=_q(expired),
            closing_by_vintage=tuple(sorted(closing.items())),
        ))
        total_used += used
        total_expired += expired
    result = LossLedgerResult(
        rows=tuple(rows),
        total_used_keur=_q(total_used),
        total_expired_keur=_q(total_expired),
        closing_total_keur=_q(sum(v for v in ledger.values())),
    )
    # exact per-year identity audit: replay openings forward and record
    # each year's opening snapshot on its row
    replay: dict[int, Decimal] = {
        v.origin_tax_year: _dec(v.amount_keur, "opening amount")
        for v in opening_vintages}
    audited_rows = []
    for row in result.rows:
        opening_snapshot = tuple(sorted(
            ((origin, _q(amount)) for origin, amount in replay.items()
             if amount > 0)))
        opening_total = sum(replay.values())
        closing_total = sum(Decimal(str(v)) for _, v in row.closing_by_vintage)
        expected_closing = (Decimal(str(opening_total))
                            + row.generated_keur - row.used_keur
                            - row.expired_keur)
        if closing_total != expected_closing:
            raise _fail("TAX_WF10_VALUE",
                        f"loss ledger identity broken in tax year "
                        f"{row.tax_year}: opening {opening_total} + "
                        f"generated {row.generated_keur} - used "
                        f"{row.used_keur} - expired {row.expired_keur} != "
                        f"closing {closing_total}")
        audited_rows.append(LossVintageRow(
            tax_year=row.tax_year,
            opening_by_vintage=opening_snapshot,
            generated_keur=row.generated_keur,
            used_keur=row.used_keur,
            expired_keur=row.expired_keur,
            closing_by_vintage=row.closing_by_vintage,
        ))
        # roll the replay forward
        replay = {origin: Decimal(str(amount))
                  for origin, amount in row.closing_by_vintage}
    return LossLedgerResult(
        rows=tuple(audited_rows),
        total_used_keur=result.total_used_keur,
        total_expired_keur=result.total_expired_keur,
        closing_total_keur=result.closing_total_keur,
    )


# ── A. Interest limitation (ATAD-style) ──────────────────────────────────────


@dataclass(frozen=True)
class InterestLimitationOutcome:
    """ATAD-style interest limitation outputs (kEUR, exact).

    Identity: ``deductible + disallowed == net_interest``."""

    capacity_keur: Decimal
    deductible_interest_keur: Decimal
    disallowed_interest_keur: Decimal
    binding_rule: str


def interest_limitation(
    inputs: InterestLimitationInputs,
) -> InterestLimitationOutcome:
    """Deterministic interest limitation with explicit outputs.

    ``capacity = max(ebitda_limit_pct/100 × ebitda, de_minimis)`` when the
    limitation is enabled; an explicitly disabled limitation deducts
    everything. ``deductible = min(net_interest, capacity)``; the
    remainder is DISALLOWED (explicit output — the released production
    engine does not add it back to taxable income, and neither does this
    candidate). Disallowed-interest carryforward is typed UNSUPPORTED."""
    require_release()
    inputs.validate()
    interest = _dec(inputs.net_interest_keur, "net_interest_keur")
    if not inputs.enabled:
        return InterestLimitationOutcome(
            capacity_keur=_q(interest),
            deductible_interest_keur=_q(interest),
            disallowed_interest_keur=_q(Decimal(0)),
            binding_rule="DISABLED",
        )
    ebitda = _dec(inputs.ebitda_keur, "ebitda_keur")
    pct_component = ebitda * Decimal(str(inputs.ebitda_limit_pct)) / Decimal(100)
    de_minimis = _dec(inputs.de_minimis_keur, "de_minimis_keur")
    capacity = max(pct_component, de_minimis)
    deductible = min(interest, capacity)
    disallowed = interest - deductible
    binding = "DE_MINIMIS" if de_minimis >= pct_component else "EBITDA_PCT"
    return InterestLimitationOutcome(
        capacity_keur=_q(capacity),
        deductible_interest_keur=_q(deductible),
        disallowed_interest_keur=_q(disallowed),
        binding_rule=binding,
    )


# ── B. Financial vs tax depreciation ─────────────────────────────────────────


@dataclass(frozen=True)
class DepreciationPeriod:
    """One canonical operating period's geometry (released-axis shape)."""

    period_index: int
    start_date: date
    end_date: date
    day_fraction: float


@dataclass(frozen=True)
class DepreciationRow:
    """One period's book vs tax depreciation with temporary differences."""

    period_index: int
    book_keur: Decimal
    tax_keur: Decimal
    difference_keur: Decimal
    cumulative_difference_keur: Decimal


@dataclass(frozen=True)
class DepreciationSchedules:
    """Book vs tax straight-line schedules for one asset."""

    asset_id: str
    rows: Tuple[DepreciationRow, ...]
    total_book_keur: Decimal
    total_tax_keur: Decimal
    total_temporary_difference_keur: Decimal


def build_depreciation_schedules(
    asset: DepreciationAsset,
    *,
    cod_date: date,
    periods: Sequence[DepreciationPeriod],
) -> DepreciationSchedules:
    """Straight-line book and tax schedules with temporary differences.

    Annual amounts are ``basis / useful_life_years``; each canonical
    period receives ``annual × day_fraction`` (the released axis's own
    proration — stub COD periods included, leap denominators inherited).
    Periods before the in-service date contribute zero. Accumulated
    depreciation is capped at the gross basis (the final partial period
    absorbs the remainder). The per-period temporary difference is
    ``tax − book``; the cumulative difference is tracked explicitly.
    Deferred tax (DTA/DTL) is deliberately NOT computed (declared
    non-capability of the released stack; owner decision D-05)."""
    require_release()
    asset.validate(cod_date=cod_date)
    if not periods:
        raise _fail("TAX_WF10_VALUE", "at least one period is required")
    basis = _dec(asset.gross_basis_keur, "gross_basis_keur")
    book_annual = basis / Decimal(asset.book_useful_life_years)
    tax_annual = basis / Decimal(asset.tax_useful_life_years)
    book_acc = Decimal(0)
    tax_acc = Decimal(0)
    cum_diff = Decimal(0)
    rows = []
    for period in periods:
        if period.day_fraction < 0:
            raise _fail("TAX_WF10_VALUE", "day_fraction must be non-negative")
        if period.end_date < asset.in_service_date:
            row = DepreciationRow(period_index=period.period_index,
                                  book_keur=_q(Decimal(0)),
                                  tax_keur=_q(Decimal(0)),
                                  difference_keur=_q(Decimal(0)),
                                  cumulative_difference_keur=_q(cum_diff))
            rows.append(row)
            continue
        book = min(book_annual * Decimal(str(period.day_fraction)),
                   basis - book_acc)
        tax = min(tax_annual * Decimal(str(period.day_fraction)),
                  basis - tax_acc)
        if book < 0:
            book = Decimal(0)
        if tax < 0:
            tax = Decimal(0)
        book_acc += book
        tax_acc += tax
        diff = tax - book
        cum_diff += diff
        rows.append(DepreciationRow(
            period_index=period.period_index,
            book_keur=_q(book), tax_keur=_q(tax),
            difference_keur=_q(diff), cumulative_difference_keur=_q(cum_diff),
        ))
    return DepreciationSchedules(
        asset_id=asset.asset_id,
        rows=tuple(rows),
        total_book_keur=_q(book_acc),
        total_tax_keur=_q(tax_acc),
        total_temporary_difference_keur=_q(tax_acc - book_acc),
    )


# ── C. VAT ───────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class VatPosition:
    """One period's VAT position with SEPARATE cash and P&L ledgers.

    ``net_vat_cash_keur`` is the funding-impact ledger (positive = VAT
    payable to the authority, negative = refundable); ``pnl_expense_keur``
    is the non-recoverable VAT expensed through the P&L (EXPENSE policy
    only); ``capitalised_keur`` is the non-recoverable VAT added to the
    asset basis (CAPITALISE policy only). The two are mutually exclusive
    by policy and never mixed."""

    phase: str
    output_vat_keur: Decimal
    input_vat_keur: Decimal
    recoverable_input_vat_keur: Decimal
    nonrecoverable_input_vat_keur: Decimal
    net_vat_cash_keur: Decimal
    pnl_expense_keur: Decimal
    capitalised_keur: Decimal


def compute_vat_position(
    config: VatConfig, period_input: VatPeriodInput,
) -> VatPosition:
    """Deterministic VAT position with explicit recovery evidence.

    Recoverable input VAT = input VAT × phase recovery percentage
    (explicit evidence — a missing/absent percentage is unconstructible:
    the config requires both). Non-recoverable VAT follows the EXPLICIT
    policy (CAPITALISE vs EXPENSE); the default-free policy field makes
    "no recovery assumption" unrepresentable rather than silent. Cash
    impact = output VAT − recoverable input VAT (refund when negative)."""
    require_release()
    config.validate()
    period_input.validate()
    rate = Decimal(str(config.rate))
    output_vat = _dec(period_input.output_net_keur,
                      "output_net_keur") * rate
    input_vat = _dec(period_input.input_net_keur, "input_net_keur") * rate
    recovery_pct = (config.recovery_pct_construction
                    if period_input.phase == "CONSTRUCTION"
                    else config.recovery_pct_operating)
    recoverable = (input_vat * Decimal(str(recovery_pct))
                   / Decimal(100))
    nonrecoverable = input_vat - recoverable
    net_cash = output_vat - recoverable
    if config.nonrecoverable_treatment == "CAPITALISE":
        pnl_expense = Decimal(0)
        capitalised = nonrecoverable
    else:
        pnl_expense = nonrecoverable
        capitalised = Decimal(0)
    return VatPosition(
        phase=period_input.phase,
        output_vat_keur=_q(output_vat),
        input_vat_keur=_q(input_vat),
        recoverable_input_vat_keur=_q(recoverable),
        nonrecoverable_input_vat_keur=_q(nonrecoverable),
        net_vat_cash_keur=_q(net_cash),
        pnl_expense_keur=_q(pnl_expense),
        capitalised_keur=_q(capitalised),
    )


# ── D. Withholding tax ───────────────────────────────────────────────────────


@dataclass(frozen=True)
class WithholdingApplication:
    """One explicitly identified gross flow to which a rule is applied.

    ``flow_id`` must be unique across a ledger: applying the same flow
    twice is double withholding and fails closed."""

    flow_id: str
    rule: WithholdingRule
    gross_keur: float
    period_index: int = 0

    def validate(self) -> None:
        if not isinstance(self.flow_id, str) or not self.flow_id.strip() \
                or len(self.flow_id) > 200:
            raise _fail("TAX_WF10_SCHEMA",
                        "withholding flow_id must be a non-empty string of "
                        "at most 200 characters")
        self.rule.validate()
        _dec(self.gross_keur, "withholding gross_keur")
        if self.gross_keur < 0:
            raise _fail("TAX_WF10_VALUE",
                        "withholding gross_keur must be non-negative")
        if not isinstance(self.period_index, int) \
                or isinstance(self.period_index, bool) or self.period_index < 0:
            raise _fail("TAX_WF10_VALUE",
                        "withholding period_index must be an integer >= 0")


@dataclass(frozen=True)
class WithholdingOutcome:
    """Gross/net conservation: ``gross == withheld + net`` (exact)."""

    flow_id: str
    flow_type: str
    paying_entity_id: str
    recipient_entity_id: str
    gross_keur: Decimal
    withheld_keur: Decimal
    net_keur: Decimal
    period_index: int


def apply_withholding(application: WithholdingApplication) -> WithholdingOutcome:
    """Deterministic withholding with exact gross/net conservation.

    The rate arrives with the rule (no default, no treaty logic); entity
    and recipient jurisdictions ride the rule as opaque labels."""
    require_release()
    application.validate()
    gross = _dec(application.gross_keur, "withholding gross_keur")
    withheld = gross * Decimal(str(application.rule.rate))
    net = gross - withheld
    return WithholdingOutcome(
        flow_id=application.flow_id,
        flow_type=application.rule.flow_type,
        paying_entity_id=application.rule.paying_entity_id,
        recipient_entity_id=application.rule.recipient_entity_id,
        gross_keur=_q(gross),
        withheld_keur=_q(withheld),
        net_keur=_q(net),
        period_index=application.period_index,
    )


def withholding_ledger(
    applications: Sequence[WithholdingApplication],
) -> Tuple[WithholdingOutcome, ...]:
    """Apply a withholding ledger with double-withholding prevention.

    The same ``flow_id`` may appear at most once — a repeated flow id is
    double withholding (or double-counting the same cash) and fails
    closed with ``TAX_WF10_DOUBLE_WITHHOLDING``. Empty gross flows are a
    legitimate ZERO; duplicates are the only rejection."""
    require_release()
    seen = set()
    outcomes = []
    for application in applications:
        application.validate()
        if application.flow_id in seen:
            raise _fail(
                "TAX_WF10_DOUBLE_WITHHOLDING",
                f"withholding flow {application.flow_id!r} appears more "
                "than once; double withholding / double-counting is "
                "rejected (exact evidence required)")
        seen.add(application.flow_id)
        outcomes.append(apply_withholding(application))
    return tuple(outcomes)


# ── E. Multi-entity attribution (zero leakage) ───────────────────────────────


@dataclass(frozen=True)
class IntercompanyInterestAttribution:
    """Payer/payee attribution of one intercompany interest flow.

    Exact identity (asserted): ``payer_deduction_keur ==
    payee_taxable_income_keur == gross_keur`` — no leakage. The payer's
    deduction remains SUBJECT to the payer's interest limitation (apply
    ``pure.interest_limitation`` on the payer's totals separately); the
    payee includes the gross interest in its taxable income. Withholding
    is a separate, explicitly ruled ledger (``pure.withholding_ledger``).
    SHL principal flows are never taxable income (mirroring the released
    HoldCo authority)."""

    flow_id: str
    period_index: int
    payer_entity_id: str
    payee_entity_id: str
    payer_deduction_keur: Decimal
    payee_taxable_income_keur: Decimal


def attribute_intercompany_interest(
    flow,
    *,
    book: TaxEntityBook,
) -> IntercompanyInterestAttribution:
    """Attribute one INTEREST flow between two entities of the book.

    Fail closed unless both entities exist in the book and the flow is an
    INTEREST flow; the attribution identity is exact (zero leakage)."""
    require_release()
    book.validate()
    flow.validate()
    if flow.flow_type != "INTEREST":
        raise _fail("TAX_WF10_UNSUPPORTED",
                    f"flow type {flow.flow_type!r} is not an interest flow")
    payer = book.entity(flow.payer_entity_id)
    payee = book.entity(flow.payee_entity_id)
    if payer is None or payee is None:
        raise _fail("TAX_WF10_IDENTITY",
                    "intercompany flow references an entity outside the book")
    gross = _dec(flow.gross_keur, "intercompany gross_keur")
    return IntercompanyInterestAttribution(
        flow_id=flow.flow_id,
        period_index=flow.period_index,
        payer_entity_id=flow.payer_entity_id,
        payee_entity_id=flow.payee_entity_id,
        payer_deduction_keur=_q(gross),
        payee_taxable_income_keur=_q(gross),
    )
