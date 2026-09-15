"""G2C contracts — typed covenant-gated shareholder waterfall results.

Source authority: validated reference evidence (versioned reference evidence), input_source_ref
  senior_lockup_dscr = 1.10 → generic distribution_lockup_dscr parameter.

R-row mapping (CF sheet, from excel source extraction):
  R84  free_cash_flow_for_junior_keur  → signed_post_senior (pre-DSRA; see note)
  R109 free_cash_flow_for_distribution → covenant-gated FCF, gate output
  R112 free_cash_flow_for_shl_keur     → inherits R109 (CF112 = H109)
  R116 free_cash_flow_for_dividends    → legal_equity_distribution_keur

Waterfall ordering (policy-defined):
  1. signed_post_senior (R84)
  2. PR-3 CASH_DSRA roll-forward → reserve_adjusted_cash (PR-4)
  3. Distribution Account roll-forward (CF108/CF109/CF110 — CAUSAL)
  4. SHL service from fcf_for_distribution (R112 = R109)
  5. legal_equity_distribution = remainder (R116)

REFERENCE_POLICY_EVIDENCE:
  cashflow_source_ref = =SUM(G94,G95,G106)+F110
  cashflow_source_ref = =IF(AND(OR(G$138<$B$109,G$4=0,G108<0,G91<G86,G105<G100),G$4<=$B$11),0,G108)
  cashflow_source_ref = G108-G109
  $B$11 = Senior Debt Maturity years = 14
  $B$109 = distribution_lockup_dscr = 1.10

PR-4 CHANGE: DA inflow now sourced from PR-3 cash_after_dsra_keur (reserve-adjusted)
rather than signed_post_senior directly. For NONE/DSRF modes, cash_after_dsra ==
signed_post_senior (neutral pass-through), so no financial change for those modes.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import Enum

from financial_engine.project_returns.contracts import DecisionCompleteReturnSummary
from financial_engine.valuation.contracts import DecisionCompleteValuationSummary

from financial_engine.financing.contracts import ProjectFinancingResult
from financial_engine.sponsor_returns.contracts import ReturnMetricStatus


class ReserveSupportGateStatus(Enum):
    """Per-period reserve support gate evaluation result.

    NONE mode  → NOT_APPLICABLE (requirement = 0, no block)
    CASH_DSRA  → PASS / PASS_NEUTRAL_SOURCE_PROVEN / FAIL_REQUIREMENT_NOT_MET
    DSRF mode  → DSRF_AVAILABLE_SUPPORT_ONLY_NO_DRAW_ENGINE
    CONSTRUCTION → CONSTRUCTION (pre-COD, gate not applicable)

    Senior CASH_DSRA is causally wired through CF109 component D. J-DSRA and
    DSRF draw support remain outside the implemented reserve boundary.
    """
    NOT_APPLICABLE = "not_applicable"
    PASS = "pass"
    PASS_NEUTRAL_SOURCE_PROVEN = "pass_neutral_source_proven"
    DSRF_AVAILABLE_SUPPORT_ONLY_NO_DRAW_ENGINE = "dsrf_available_support_only_no_draw_engine"
    FAIL_REQUIREMENT_NOT_MET = "fail_requirement_not_met"
    CONSTRUCTION = "construction"


class DistributionGateStatus(Enum):
    """Per-period distribution gate evaluation result.

    Source: validated reference evidence input_source_ref → generic lockup_dscr threshold.

    LOCKED_DSCR_BELOW_LOCKUP: gate triggered because comp_A (DSCR < lockup) was True.
    LOCKED_COVENANT_GATE: gate triggered by a non-DSCR component (C=DA<0, D=DSRA<target,
      E=J-DSRA<target) — DSCR was not the primary trigger.
    """
    OPEN = "open"
    LOCKED_DSCR_BELOW_LOCKUP = "locked_dscr_below_lockup"
    LOCKED_COVENANT_GATE = "locked_covenant_gate"
    DSCR_UNAVAILABLE_GATE_OPEN = "dscr_unavailable_gate_open"
    CONSTRUCTION = "construction"


@dataclass(frozen=True)
class CovenantGatedWaterfallPeriod:
    """Per-period covenant-gated waterfall result.

    Extends G2B SponsorCashFlowPeriod with the DA-based DSCR covenant gate.
    """
    period_index: int
    cashflow_date: date
    is_construction: bool

    # Gate inputs
    base_dscr: float | None
    distribution_lockup_dscr: float
    distribution_gate_status: DistributionGateStatus

    # Reserve support audit. Initial funded cash is distinct from the operating target.
    debt_service_reserve_requirement_keur: float    # legacy alias of period required balance
    initial_funded_dsra_keur: float                 # Project Uses / COD funded cash
    reserve_support_gate_status: ReserveSupportGateStatus

    # Cash waterfall (operating) — policy-defined ordering
    signed_post_senior_keur: float          # R84: pre-gate junior FCF
    dsrf_commitment_fee_keur: float         # DSRF fee deducted before gate (0 for CASH_DSRA/NONE)
    # PR-4: reserve-adjusted cash inserted between signed_post_senior and DA inflow
    reserve_adjusted_cash_keur: float       # PR-3 cash_after_dsra; == signed_post_senior for NONE/DSRF
    dsra_top_up_keur: float                 # PR-3 top_up this period (0 for NONE/DSRF)
    dsra_draw_keur: float                   # PR-3 draw_to_cover_shortfall this period (0 for NONE/DSRF)
    dsra_release_keur: float                # canonical PR-3 excess release this period
    fcf_for_distribution_keur: float        # R109: gate output (= DA release)
    covenant_locked_keur: float             # DA closing (accumulated locked cash per period)

    # Causal SHL balance roll-forward (from compute_shl_waterfall_period)
    shl_opening_balance_keur: float         # opening SHL balance this period
    shl_gross_interest_keur: float          # gross accrued SHL interest (opening × rate × dcf)
    shl_cash_interest_receipt_keur: float   # cash interest paid from fcf_for_distribution
    shl_pik_keur: float                     # unpaid gross interest → PIK capitalised

    # Contractual vs actual principal (BULLET: contractual balloon may exceed cash)
    contractual_shl_principal_due_keur: float   # scheduler balloon or sweep amount due
    actual_shl_principal_paid_keur: float        # actual cash paid ≤ contractual_due
    unpaid_shl_principal_keur: float             # contractual - actual (0 unless BULLET shortfall)

    # Actual causal closing balance: opening + PIK - actual_paid (NOT contractual)
    actual_shl_closing_balance_keur: float

    # Legacy aliases kept for backward compat
    shl_principal_receipt_keur: float       # = actual_shl_principal_paid_keur
    shl_closing_balance_keur: float         # = actual_shl_closing_balance_keur

    # Distribution Account causal roll-forward (CF108/CF109/CF110)
    # REFERENCE_POLICY_EVIDENCE (versioned reference evidence):
    #   cashflow_source_ref = SUM(G94,G95,G106)+F110
    #   cashflow_source_ref = IF(AND(OR(G$138<$B$109,G$4=0,G108<0,G91<G86,G105<G100),G$4<=$B$11),0,G108)
    #   cashflow_source_ref = G108 - G109
    distribution_account_opening_keur: float       # F110: closing of prior period
    distribution_account_inflow_keur: float        # G94+G95+G106 (net of DSRF fee)
    distribution_account_available_keur: float     # CF108 = inflow + opening
    # CF109 gate components (5 explicit policy-defined booleans + outer AND condition):
    gate_component_dscr_below_lockup: bool         # A: G$138 < $B$109
    gate_component_construction: bool              # B: G$4 = 0 (always False for operating)
    gate_component_da_negative: bool               # C: G108 < 0
    gate_component_dsra_underfunded: bool          # D: G91 < G86
    gate_component_j_dsra_underfunded: bool        # E: G105 < G100 (False for no-J-DSRA)
    within_senior_maturity: bool                   # G$4 <= $B$11 (outer AND)
    distribution_account_release_keur: float       # CF109 = gate output
    distribution_account_closing_keur: float       # CF110 = available - release
    shl_cash_input_keur: float                      # max(0, CF109 release)

    # Senior DSRA causal roll-forward (CF86-CF92)
    # REFERENCE_POLICY_EVIDENCE: Synthetic reference target may be zero when no DSRA is required
    senior_dsra_target_keur: float                 # CF86: target reserve balance
    senior_dsra_opening_keur: float                # CF87/F92: prior closing
    senior_dsra_closing_keur: float                # CF92: ending balance

    @property
    def dsra_required_balance_keur(self) -> float:
        """Canonical per-period Senior cash-DSRA requirement."""
        return self.senior_dsra_target_keur

    @property
    def dsra_opening_balance_keur(self) -> float:
        """Canonical per-period Senior cash-DSRA opening balance."""
        return self.senior_dsra_opening_keur

    @property
    def dsra_closing_balance_keur(self) -> float:
        """Canonical per-period Senior cash-DSRA closing balance."""
        return self.senior_dsra_closing_keur

    # BULLET maturity status: True once BULLET balloon was underfunded at contractual maturity
    shl_bullet_unpaid_at_maturity: bool

    # Equity distribution: residual after SHL service from fcf_for_distribution (R116)
    legal_equity_distribution_keur: float

    # U2 Phase L: Pre-distribution accounting cap layer
    # Source: Generic Wind Reference CF106-CF135, Generic Solar Reference CF116-CF144
    fcf_for_dividends_keur: float          # = legal_equity_distribution_keur (post-SHL residual)
    accounting_dividend_capacity_keur: float  # MAX(0, opening_RE + net_income - legal_reserve_transfer)
    cash_dividend_capacity_keur: float     # opening_unrestricted_cash + fcf_for_dividends

    distributable_keur: float              # MAX(0, MIN(accounting_cap, cash_cap))
    gross_dividend_paid_keur: float        # = distributable (WHT-neutral for corporate cash)
    dividend_wht_rate: float               # 0.0 for Generic Wind Reference, 0.05 for Generic Solar Reference
    dividend_wht_keur: float               # gross_dividend * wht_rate
    net_dividend_received_keur: float      # gross_dividend * (1 - wht_rate)
    unrestricted_cash_opening_keur: float  # prior period's unrestricted_cash_closing
    change_in_unrestricted_cash_keur: float  # fcf_for_dividends - gross_dividend_paid
    unrestricted_cash_closing_keur: float  # opening + change

    cash_shortfall_keur: float

    # Sponsor contributions (construction periods)
    share_capital_contribution_keur: float
    share_premium_contribution_keur: float
    other_committed_equity_contribution_keur: float
    additional_equity_contribution_keur: float
    shl_cash_contribution_keur: float

    # Net cashflows for return metrics
    pure_equity_net_cashflow_keur: float
    total_sponsor_net_cashflow_keur: float

    # O.8: Legal reserve causal roll-forward (exposed for auditability)
    # Default 0.0: periods where distribution accounting is inactive carry no LR movement.
    opening_legal_reserve_keur: float = 0.0   # legal reserve at start of period
    legal_reserve_transfer_keur: float = 0.0  # transfer to legal reserve this period
    closing_legal_reserve_keur: float = 0.0   # legal reserve at end of period


@dataclass(frozen=True)
class CovenantGatedWaterfallResult:
    """Top-level G2C result — covenant-gated shareholder waterfall."""
    financing_result: ProjectFinancingResult
    distribution_lockup_dscr: float
    waterfall_periods: tuple[CovenantGatedWaterfallPeriod, ...]

    # Contribution totals
    total_share_capital_contributed_keur: float
    total_share_premium_contributed_keur: float
    total_other_committed_equity_contributed_keur: float
    total_additional_equity_contributed_keur: float
    total_legal_equity_contributed_keur: float
    total_shl_cash_contributed_keur: float
    total_sponsor_contributed_keur: float

    # Receipt totals
    total_shl_cash_interest_received_keur: float
    total_shl_principal_received_keur: float
    total_legal_equity_distributions_keur: float
    total_covenant_locked_keur: float       # sum of per-period da_closing (accumulated locked)
    total_sponsor_receipts_keur: float
    total_dsrf_commitment_fee_keur: float   # total DSRF fee (0 for CASH_DSRA/NONE)

    # Distribution Account totals (causal — CF108/109/110)
    total_distribution_account_locked_keur: float  # sum of da_closing across all periods
    distribution_account_status: str               # causal status string

    # U2 Phase L: dividend totals
    total_gross_dividend_paid_keur: float
    total_net_dividend_received_keur: float

    # BULLET SHL maturity status
    shl_bullet_unpaid_at_maturity: bool     # True if any period had underfunded BULLET

    # Return metrics
    pure_equity_xirr: float | None
    pure_equity_xirr_status: ReturnMetricStatus
    pure_equity_moic: float | None
    pure_equity_moic_status: ReturnMetricStatus
    total_sponsor_xirr: float | None
    total_sponsor_xirr_status: ReturnMetricStatus
    total_sponsor_moic: float | None
    total_sponsor_moic_status: ReturnMetricStatus

    # Gate summary
    periods_locked_by_dscr: int
    total_periods_with_senior_ds: int

    # Reserve support gate summary
    # Senior CASH_DSRA is causal; remaining reserve gaps are named in the status value.
    reserve_support_gate_status_summary: str

    # G2C_DEDUCTIBLE_SHL_COVENANT_FEEDBACK_NOT_YET_CLOSED when deductible SHL
    # interest + gate locks any period + PIK accumulates (feedback loop not closed).
    # None when Generic Solar Reference FULLY_NON_DEDUCTIBLE or no gate lock or no SHL.
    deductible_shl_covenant_feedback_status: str | None

    # Phase C1 canonical downstream return and terminal-state authority.
    return_summary: DecisionCompleteReturnSummary
    # Phase C2 downstream-only Project NPV and lender-coverage authority.
    valuation_summary: DecisionCompleteValuationSummary
