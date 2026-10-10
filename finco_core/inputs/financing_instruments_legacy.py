"""Read-only F3 proposal projection; no solver, persistence or runtime activation.

Calendar authority is reused to identify maturity, never FC + Senior tenor.
The source financing modes live in a separate immutable audit envelope; they
are not guessed from an instrument label or from a legacy debt amount.
"""
from dataclasses import dataclass
from datetime import date

from ._models import (
    DebtSizingMode, GearingCapRepaymentMethod, PeriodAxisConvention, PeriodFrequency, ProjectInputs,
    SHLRepaymentMethod, SponsorFundingMode,
)
from .financing_instruments import (
    CapitalProvider, CommitmentAuthority, FinancingCollection, FinancingError,
    FinancingInstrument, InstrumentType, InterestTerms, MaturityAuthority,
    Provenance, RateMode, RepaymentMode, RepaymentTerms, _finite,
)

UNRESOLVED = "F3_LEGACY_MAPPING_UNRESOLVED"
LEGACY_SPONSOR_PROVIDER_ID = "legacy-sponsor"


@dataclass(frozen=True)
class LegacyFinancingMapping:
    collection: FinancingCollection
    senior_sizing_mode: DebtSizingMode
    sponsor_funding_mode: SponsorFundingMode
    senior_contractual_maturity_date: date

    def __post_init__(self):
        if (
            not isinstance(self.collection, FinancingCollection)
            or not isinstance(self.senior_sizing_mode, DebtSizingMode)
            or not isinstance(self.sponsor_funding_mode, SponsorFundingMode)
            or type(self.senior_contractual_maturity_date) is not date
        ):
            raise FinancingError(UNRESOLVED, "invalid legacy source-authority envelope")


def _senior_repayment_mode(fin) -> RepaymentMode:
    mode = fin.debt_sizing_mode
    if not isinstance(mode, DebtSizingMode):
        raise FinancingError(UNRESOLVED, "Senior sizing needs an explicit typed mode")
    if mode in (DebtSizingMode.FLAT_DSCR_SCULPTED, DebtSizingMode.MINIMUM_DSCR_SCULPTED):
        return RepaymentMode.DSCR_SCULPTED
    if mode is DebtSizingMode.FROZEN_EXCEL_SCHEDULE:
        return RepaymentMode.EXPLICIT_SCHEDULE
    if mode is DebtSizingMode.GEARING_CAP:
        if fin.gearing_cap_repayment_method is GearingCapRepaymentMethod.LEVEL_PRINCIPAL:
            return RepaymentMode.LEVEL_PRINCIPAL
        if fin.gearing_cap_repayment_method is GearingCapRepaymentMethod.DSCR_SCULPTED:
            return RepaymentMode.DSCR_SCULPTED
    raise FinancingError(UNRESOLVED, "Senior repayment method has no proven mapping")


def _map_legacy_financing(project_inputs: ProjectInputs) -> LegacyFinancingMapping:
    """Represent source inputs, not a new financing result or execution permission.

    MINIMUM/FROZEN modes can be represented without claiming they are executable
    through today's clean path. Scalar Junior funding lacks terms and is refused.
    """
    if not isinstance(project_inputs, ProjectInputs):
        raise FinancingError(UNRESOLVED, "expected canonical ProjectInputs")
    fin = project_inputs.financing
    funding_mode = fin.sponsor_funding_mode
    if not isinstance(funding_mode, SponsorFundingMode):
        raise FinancingError(UNRESOLVED, "residual funding needs explicit SponsorFundingMode")
    repayment = _senior_repayment_mode(fin)
    tenor = fin.senior_tenor_years
    if type(tenor) is not int or tenor <= 0:
        raise FinancingError(UNRESOLVED, "Senior tenor must be a positive plain integer")
    info = project_inputs.info
    if type(info.financial_close) is not date or type(info.cod_date) is not date:
        raise FinancingError(UNRESOLVED, "calendar authority needs real FC/COD dates")
    if info.period_frequency is not PeriodFrequency.SEMESTRIAL:
        raise FinancingError(UNRESOLVED, "canonical Senior maturity supports SEMESTRIAL axis only")
    if not isinstance(info.period_axis_convention, PeriodAxisConvention):
        raise FinancingError(UNRESOLVED, "calendar axis convention needs its typed authority")
    # Calendar metadata only: no production, debt, tax or cash calculation.
    from finco_core.engine.period_engine import PeriodEngine
    try:
        calendar = PeriodEngine(
            financial_close=info.financial_close, construction_months=info.construction_months,
            horizon_years=info.horizon_years, ppa_years=project_inputs.revenue.ppa_term_years,
            frequency=info.period_frequency, cod_date=info.cod_date,
            period_axis_convention=info.period_axis_convention.value,
        )
    except (TypeError, ValueError, OverflowError, AttributeError) as exc:
        raise FinancingError(UNRESOLVED, f"canonical calendar authority: {exc}") from exc
    operating = calendar.operation_periods()
    if len(operating) < tenor * 2:
        raise FinancingError(UNRESOLVED, "Senior tenor exceeds canonical operating axis")
    maturity = operating[tenor * 2 - 1]
    instruments = [FinancingInstrument(
        instrument_id="legacy-senior", instrument_type=InstrumentType.SENIOR_TERM_LOAN,
        name="Senior Debt (legacy single facility)", commitment_keur=None,
        commitment_authority=CommitmentAuthority.CANONICAL_SIZING_DERIVED,
        interest=InterestTerms(RateMode.PERIOD_SCHEDULE),
        repayment=RepaymentTerms(repayment, maturity_authority=MaturityAuthority.PERIOD_AXIS_DERIVED,
                                 tenor_years=tenor, maturity_period_index=maturity.index),
        provenance=Provenance.LEGACY_FINANCING_PARAMS,
    )]
    if _finite("junior funding", fin.junior_or_other_project_funding_keur) > 0:
        raise FinancingError(UNRESOLVED, "scalar Junior funding has no instrument-level terms")
    for field, instrument_id, kind, name in (
        ("share_capital_keur", "legacy-share-capital", InstrumentType.COMMON_EQUITY, "Share Capital"),
        ("share_premium_keur", "legacy-share-premium", InstrumentType.SHARE_PREMIUM, "Share Premium"),
        ("other_equity_funding_before_shl_keur", "legacy-other-committed-equity",
         InstrumentType.ADDITIONAL_EQUITY, "Other Committed Equity"),
    ):
        amount = _finite(field, getattr(fin, field))
        if amount > 0:
            instruments.append(FinancingInstrument(
                instrument_id=instrument_id, instrument_type=kind, name=name, commitment_keur=amount,
                funding_source_ref=LEGACY_SPONSOR_PROVIDER_ID, seniority_rank=2,
                provenance=Provenance.LEGACY_FINANCING_PARAMS,
            ))
    if funding_mode is SponsorFundingMode.EQUITY_ONLY:
        instruments.append(FinancingInstrument(
            instrument_id="legacy-additional-equity", instrument_type=InstrumentType.ADDITIONAL_EQUITY,
            name="Additional Equity (residual)", commitment_keur=None,
            commitment_authority=CommitmentAuthority.RESIDUAL_DERIVED,
            funding_source_ref=LEGACY_SPONSOR_PROVIDER_ID, seniority_rank=3,
            provenance=Provenance.LEGACY_FINANCING_PARAMS,
        ))
    else:
        method = fin.clean_shl_repayment_method
        shl_modes = {SHLRepaymentMethod.BULLET: RepaymentMode.BULLET,
                     SHLRepaymentMethod.CASH_SWEEP: RepaymentMode.CASH_SWEEP}
        if not isinstance(method, SHLRepaymentMethod) or method not in shl_modes:
            raise FinancingError(UNRESOLVED, "only typed SHL BULLET/CASH_SWEEP are proven")
        index = fin.shl_maturity_period_index
        if type(index) is not int or index not in {p.index for p in operating}:
            raise FinancingError(UNRESOLVED, "SHL maturity is missing or outside canonical operating axis")
        instruments.append(FinancingInstrument(
            instrument_id="legacy-shl", instrument_type=InstrumentType.SHAREHOLDER_LOAN,
            name="Shareholder Loan (residual)", commitment_keur=None,
            commitment_authority=CommitmentAuthority.RESIDUAL_DERIVED,
            funding_source_ref=LEGACY_SPONSOR_PROVIDER_ID, seniority_rank=3,
            interest=InterestTerms(RateMode.FIXED, fixed_rate=fin.shl_rate),
            repayment=RepaymentTerms(shl_modes[method], maturity_authority=MaturityAuthority.PERIOD_AXIS_DERIVED,
                                     maturity_period_index=index),
            provenance=Provenance.LEGACY_FINANCING_PARAMS,
        ))
    return LegacyFinancingMapping(
        FinancingCollection(tuple(instruments),
                            (CapitalProvider(LEGACY_SPONSOR_PROVIDER_ID, "Sponsor (legacy)", 1.0),)),
        fin.debt_sizing_mode, funding_mode, maturity.end_date,
    )


def map_legacy_financing_with_authority(project_inputs: ProjectInputs) -> LegacyFinancingMapping:
    try:
        return _map_legacy_financing(project_inputs)
    except FinancingError:
        raise
    except (AttributeError, TypeError, ValueError, OverflowError) as exc:
        raise FinancingError(UNRESOLVED, f"invalid/missing legacy authority: {exc}") from exc


def map_legacy_financing(project_inputs: ProjectInputs) -> FinancingCollection:
    return map_legacy_financing_with_authority(project_inputs).collection
