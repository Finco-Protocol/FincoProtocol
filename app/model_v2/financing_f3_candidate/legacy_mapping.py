"""Read-only mapping of today's single-Senior ``FinancingParams`` into the candidate shape.

Proves the migration seam without touching economics: the mapping only READS fields, never writes
to ``ProjectInputs``, never runs the engine and never persists.  Senior commitment is recorded as
CANONICAL_SIZING_DERIVED (an output of the existing sizing), so a missing explicit amount is never
read as "zero Senior".
"""
from __future__ import annotations

from .contracts import (
    CapitalProvider,
    CommitmentAuthority,
    FinancingCollection,
    FinancingInstrument,
    InstrumentType,
    InterestTerms,
    Provenance,
    RateMode,
    RepaymentMode,
    RepaymentTerms,
)

LEGACY_SPONSOR_PROVIDER_ID = "legacy-sponsor"


def _senior_repayment_mode(fin) -> RepaymentMode:
    method = str(getattr(fin, "amortization_type", "") or "").lower()
    return {"sculpted": RepaymentMode.DSCR_SCULPTED, "level": RepaymentMode.LEVEL_PRINCIPAL}.get(
        method, RepaymentMode.EXPLICIT_SCHEDULE)


def map_legacy_financing(project_inputs) -> FinancingCollection:
    fin = project_inputs.financing
    close = project_inputs.info.financial_close
    maturity = close.replace(year=close.year + int(fin.senior_tenor_years))
    instruments = [FinancingInstrument(
        instrument_id="legacy-senior", instrument_type=InstrumentType.SENIOR_TERM_LOAN,
        name="Senior Debt (legacy single facility)", commitment_keur=None,
        commitment_authority=CommitmentAuthority.CANONICAL_SIZING_DERIVED, seniority_rank=1,
        interest=InterestTerms(mode=RateMode.PERIOD_SCHEDULE),
        repayment=RepaymentTerms(mode=_senior_repayment_mode(fin), maturity_date=maturity),
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
    equity_only = str(getattr(getattr(fin, "sponsor_funding_mode", None), "value",
                              getattr(fin, "sponsor_funding_mode", None)) or "") == "equity_only"
    if equity_only:
        instruments.append(FinancingInstrument(
            instrument_id="legacy-additional-equity", instrument_type=InstrumentType.ADDITIONAL_EQUITY,
            name="Additional Equity (residual)", commitment_keur=None,
            commitment_authority=CommitmentAuthority.RESIDUAL_DERIVED,
            funding_source_ref=LEGACY_SPONSOR_PROVIDER_ID, seniority_rank=3,
            provenance=Provenance.LEGACY_FINANCING_PARAMS))
    else:
        instruments.append(FinancingInstrument(
            instrument_id="legacy-shl", instrument_type=InstrumentType.SHAREHOLDER_LOAN,
            name="Shareholder Loan (residual)", commitment_keur=None,
            commitment_authority=CommitmentAuthority.RESIDUAL_DERIVED,
            funding_source_ref=LEGACY_SPONSOR_PROVIDER_ID, seniority_rank=3,
            interest=InterestTerms(mode=RateMode.FIXED, fixed_rate=float(fin.shl_rate)),
            repayment=RepaymentTerms(mode=RepaymentMode.BULLET, maturity_date=maturity),
            provenance=Provenance.LEGACY_FINANCING_PARAMS))
    return FinancingCollection(
        instruments=tuple(instruments),
        providers=(CapitalProvider(LEGACY_SPONSOR_PROVIDER_ID, "Sponsor (legacy)", 1.0),))
