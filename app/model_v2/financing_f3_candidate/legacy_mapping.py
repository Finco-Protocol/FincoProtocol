"""Read-only mapping of today's single-Senior ``FinancingParams`` into the candidate shape.

Proves the migration seam without touching economics: the mapping only READS fields, never writes
to ``ProjectInputs``, never runs the engine and never persists.

Accuracy rules (Correction A):

* **No invented dates.**  The canonical Senior maturity is the last of ``senior_tenor_years x
  periods_per_year`` *operating* periods (``senior_debt/project_adapter.py``), i.e. an output of the
  model period axis anchored at the first operating period (COD), never ``financial_close + n years``.
  The candidate therefore records ``PERIOD_AXIS_DERIVED`` with the tenor and **no date**.
* **Only proven semantics.**  The clean SHL supports exactly BULLET and CASH_SWEEP
  (``adapters/project_inputs.py``).  Any other or unset ``clean_shl_repayment_method`` fails closed.
* **Strict funding mode.**  The canonical G2A stack requires an explicit ``SponsorFundingMode``
  (``G2A_SPONSOR_FUNDING_MODE_EXPLICIT_INPUT_REQUIRED``); ``None`` or any non-enum value fails closed.
* **Senior repayment** follows the typed ``debt_sizing_mode`` (and ``gearing_cap_repayment_method`` for
  GEARING_CAP); the legacy ``amortization_type`` string is not an authority.  Unset/unknown fails closed.

A missing explicit amount is never read as "zero Senior": the Senior commitment is recorded as
CANONICAL_SIZING_DERIVED.
"""
from __future__ import annotations

from finco_core.inputs import DebtSizingMode, GearingCapRepaymentMethod, SHLRepaymentMethod, SponsorFundingMode

from .contracts import (
    CapitalProvider,
    CommitmentAuthority,
    FinancingCollection,
    FinancingError,
    FinancingInstrument,
    InstrumentType,
    InterestTerms,
    MaturityAuthority,
    Provenance,
    RateMode,
    RepaymentMode,
    RepaymentTerms,
)

LEGACY_SPONSOR_PROVIDER_ID = "legacy-sponsor"
UNRESOLVED = "F3_LEGACY_MAPPING_UNRESOLVED"

_SHL_REPAYMENT = {
    SHLRepaymentMethod.BULLET: RepaymentMode.BULLET,
    SHLRepaymentMethod.CASH_SWEEP: RepaymentMode.CASH_SWEEP,
}


def _senior_repayment_mode(fin) -> RepaymentMode:
    mode = getattr(fin, "debt_sizing_mode", None)
    if mode in (DebtSizingMode.FLAT_DSCR_SCULPTED, DebtSizingMode.MINIMUM_DSCR_SCULPTED):
        return RepaymentMode.DSCR_SCULPTED
    if mode is DebtSizingMode.FROZEN_EXCEL_SCHEDULE:
        return RepaymentMode.EXPLICIT_SCHEDULE
    if mode is DebtSizingMode.GEARING_CAP:
        method = getattr(fin, "gearing_cap_repayment_method", None)
        if method is GearingCapRepaymentMethod.LEVEL_PRINCIPAL:
            return RepaymentMode.LEVEL_PRINCIPAL
        if method is GearingCapRepaymentMethod.DSCR_SCULPTED:
            return RepaymentMode.DSCR_SCULPTED
    raise FinancingError(UNRESOLVED, f"Senior repayment: debt_sizing_mode={mode!r} is unset or unmapped")


def map_legacy_financing(project_inputs) -> FinancingCollection:
    fin = project_inputs.financing
    funding_mode = getattr(fin, "sponsor_funding_mode", None)
    if not isinstance(funding_mode, SponsorFundingMode):
        raise FinancingError(UNRESOLVED, f"sponsor_funding_mode={funding_mode!r} is not an explicit SponsorFundingMode")

    senior_tenor = getattr(fin, "senior_tenor_years", None)
    instruments = [FinancingInstrument(
        instrument_id="legacy-senior", instrument_type=InstrumentType.SENIOR_TERM_LOAN,
        name="Senior Debt (legacy single facility)", commitment_keur=None,
        commitment_authority=CommitmentAuthority.CANONICAL_SIZING_DERIVED, seniority_rank=1,
        interest=InterestTerms(mode=RateMode.PERIOD_SCHEDULE),
        repayment=RepaymentTerms(
            mode=_senior_repayment_mode(fin),
            maturity_authority=MaturityAuthority.PERIOD_AXIS_DERIVED, tenor_years=senior_tenor),
        provenance=Provenance.LEGACY_FINANCING_PARAMS,
    )]
    if float(fin.share_capital_keur) > 0.0:
        instruments.append(FinancingInstrument(
            instrument_id="legacy-share-capital", instrument_type=InstrumentType.COMMON_EQUITY,
            name="Share Capital", commitment_keur=float(fin.share_capital_keur),
            funding_source_ref=LEGACY_SPONSOR_PROVIDER_ID, seniority_rank=2,
            provenance=Provenance.LEGACY_FINANCING_PARAMS))
    if float(fin.share_premium_keur) > 0.0:
        instruments.append(FinancingInstrument(
            instrument_id="legacy-share-premium", instrument_type=InstrumentType.SHARE_PREMIUM,
            name="Share Premium", commitment_keur=float(fin.share_premium_keur),
            funding_source_ref=LEGACY_SPONSOR_PROVIDER_ID, seniority_rank=2,
            provenance=Provenance.LEGACY_FINANCING_PARAMS))

    if funding_mode is SponsorFundingMode.EQUITY_ONLY:
        instruments.append(FinancingInstrument(
            instrument_id="legacy-additional-equity", instrument_type=InstrumentType.ADDITIONAL_EQUITY,
            name="Additional Equity (residual)", commitment_keur=None,
            commitment_authority=CommitmentAuthority.RESIDUAL_DERIVED,
            funding_source_ref=LEGACY_SPONSOR_PROVIDER_ID, seniority_rank=3,
            provenance=Provenance.LEGACY_FINANCING_PARAMS))
    else:  # SHARE_CAPITAL_THEN_SHL — residual is shareholder-loan cash
        method = getattr(fin, "clean_shl_repayment_method", None)
        if method not in _SHL_REPAYMENT:
            raise FinancingError(
                UNRESOLVED,
                f"clean_shl_repayment_method={method!r}: only BULLET and CASH_SWEEP are proven clean-SHL semantics")
        instruments.append(FinancingInstrument(
            instrument_id="legacy-shl", instrument_type=InstrumentType.SHAREHOLDER_LOAN,
            name="Shareholder Loan (residual)", commitment_keur=None,
            commitment_authority=CommitmentAuthority.RESIDUAL_DERIVED,
            funding_source_ref=LEGACY_SPONSOR_PROVIDER_ID, seniority_rank=3,
            interest=InterestTerms(mode=RateMode.FIXED, fixed_rate=float(fin.shl_rate)),
            repayment=RepaymentTerms(
                mode=_SHL_REPAYMENT[method],
                maturity_authority=MaturityAuthority.PERIOD_AXIS_DERIVED,
                maturity_period_index=getattr(fin, "shl_maturity_period_index", None)),
            provenance=Provenance.LEGACY_FINANCING_PARAMS))
    return FinancingCollection(
        instruments=tuple(instruments),
        providers=(CapitalProvider(LEGACY_SPONSOR_PROVIDER_ID, "Sponsor (legacy)", 1.0),))
