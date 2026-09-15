"""domain/shl/engine — Canonical SHL Engine."""
from typing import Tuple

from finco_core.shl.inputs import ShlEngineInputs, ShlPeriodInput
from finco_core.shl.result import ShlEngineResult, ShlPeriodResult, ShlAuditRow


class ShlEngine:
    """Canonical SHL engine.

    Computes period-by-period SHL interest, PIK, principal, and closing balance
    given post-senior cash availability.

    Does NOT compute:
        - R99/R102 distribution gates
        - Tax (only exposes interest outputs)
        - Senior debt
        - Sponsor IRR

    Waterfall order per period:
        1. opening_balance + drawdown
        2. gross_accrued = (opening + drawdown) × rate × day_frac
        3. available_for_shl = post_senior_cash (minus reserve if enabled)
        4. cash_interest = min(gross_accrued, available_for_shl)
        5. available -= cash_interest
        6. pik = max(gross_accrued - cash_interest, 0) if pik_allowed else 0
        7. principal = min(available, opening + drawdown + pik)  [capped at balance]
        8. closing = opening + drawdown + pik - principal
        9. cash_consumed = cash_interest + principal
        10. cash_after_shl = post_senior_cash - cash_consumed
        11. cash_for_dist = max(cash_after_shl, 0)
    """

    @staticmethod
    def compute(inputs: ShlEngineInputs) -> ShlEngineResult:
        """Compute SHL engine result given period inputs."""
        period_results: list[ShlPeriodResult] = []
        audit_rows: list[ShlAuditRow] = []

        # Accumulate totals
        totals = dict(
            gross=0.0,
            cash_int=0.0,
            pik=0.0,
            principal=0.0,
            cash_consumed=0.0,
        )

        pik_count = 0
        sweep_100_count = 0

        for t, p in enumerate(inputs.period_inputs):
            prev_closing = (
                period_results[t - 1].closing_balance_keur
                if t > 0
                else sum(inputs.tranche_opening_balances_keur)
            )

            # Balance at start of period
            balance = prev_closing + p.drawdown_keur

            # Gross accrued interest
            gross = balance * p.interest_rate * p.day_count_fraction

            # Cash available for SHL (after optional reserve)
            if p.maintain_minimum_cash_reserve and p.minimum_cash_reserve_keur > 0:
                available = max(0.0, p.post_senior_cash_available_keur - p.minimum_cash_reserve_keur)
                reserve_applied = True
            else:
                available = p.post_senior_cash_available_keur
                reserve_applied = False

            # [R102 CONTRACT] Add explicit R102 sweep from DistributionAccount.
            # When provided: increases cash available for SHL service.
            # Applied before interest: cash interest first, then PIK, then principal.
            # When None: use internal R102 logic (unchanged — no external sweep).
            # Tolerance: 0.01 kEUR for validation/comparison purposes.
            r102_candidate = p.distribution_account_r102_sweep_candidate_keur
            r102_sweep_applied = 0.0
            if r102_candidate is not None and r102_candidate >= 0.0:
                r102_sweep_applied = r102_candidate
                # Add candidate to available SHL service pool
                available += r102_sweep_applied

            # Cash interest paid
            cash_int = min(gross, available)
            available_after_int = available - cash_int

            # PIK capitalized
            if p.pik_allowed:
                pik = max(0.0, gross - cash_int)
            else:
                pik = 0.0

            # Principal repaid: remaining cash capped at outstanding balance
            # Outstanding balance = opening + drawdown + pik
            outstanding = balance + pik
            principal = min(available_after_int, outstanding)
            available_after_principal = available_after_int - principal

            # Closing balance
            closing = balance + pik - principal

            # Cash accounting
            cash_consumed = cash_int + principal
            cash_after_shl = p.post_senior_cash_available_keur - cash_consumed
            cash_for_dist = max(cash_after_shl, 0.0)

            # Flags
            pik_triggered = pik > 0.01
            sweep_100 = (
                abs(p.post_senior_cash_available_keur - cash_consumed) < 0.01
                if p.post_senior_cash_available_keur > 0.01
                else False
            )

            if pik_triggered:
                pik_count += 1
            if sweep_100:
                sweep_100_count += 1

            # Tranche breakdown (single tranche for Generic Wind Reference, placeholder)
            tranche_count = len(inputs.tranche_rates) if inputs.tranche_rates else 1
            tranche_openings = (balance,) * tranche_count
            tranche_gross = (gross,) * tranche_count
            tranche_cash_int = (cash_int,) * tranche_count
            tranche_pik = (pik,) * tranche_count
            tranche_principal = (principal,) * tranche_count
            tranche_closing = (closing,) * tranche_count

            period_result = ShlPeriodResult(
                period_index=p.period_index,
                opening_balance_keur=balance,
                drawdown_keur=p.drawdown_keur,
                gross_accrued_interest_keur=gross,
                cash_interest_paid_keur=cash_int,
                pik_capitalized_keur=pik,
                principal_repaid_keur=principal,
                closing_balance_keur=closing,
                cash_consumed_by_shl_keur=cash_consumed,
                cash_after_shl_keur=cash_after_shl,
                cash_for_distribution_keur=cash_for_dist,
                pik_triggered=pik_triggered,
                cash_sweep_100_pct=sweep_100,
                reserve_applied=reserve_applied,
                distribution_account_r102_sweep_candidate_keur=r102_candidate,
                r102_sweep_applied_keur=r102_sweep_applied,
                tranche_opening_balances_keur=tranche_openings,
                tranche_gross_accrued_keur=tranche_gross,
                tranche_cash_int_paid_keur=tranche_cash_int,
                tranche_pik_keur=tranche_pik,
                tranche_principal_keur=tranche_principal,
                tranche_closing_balances_keur=tranche_closing,
            )
            period_results.append(period_result)

            # Accumulate totals
            totals["gross"] += gross
            totals["cash_int"] += cash_int
            totals["pik"] += pik
            totals["principal"] += principal
            totals["cash_consumed"] += cash_consumed

            # Audit row
            classification = (
                "SHL_Active"
                if p.post_senior_cash_available_keur > 0.01 and balance > 0.01
                else ("SHL_Inactive" if balance > 0.01 else "N/A")
            )

            warnings: list[str] = []
            if pik > 0.01 and cash_int > gross:
                warnings.append("cash_int > gross_accrued")
            if closing < -0.01:
                warnings.append("negative_closing_balance")
            if principal > balance + pik + 0.01:
                warnings.append("principal_exceeds_outstanding")

            audit_rows.append(
                ShlAuditRow(
                    period_index=p.period_index,
                    excel_col=_period_to_excel_col(p.period_index),
                    operating_period_index=int(p.period_index - 2) if p.period_index > 1 else 0,
                    shl_opening_keur=balance,
                    drawdown_keur=p.drawdown_keur,
                    shl_closing_keur=closing,
                    gross_accrued_keur=gross,
                    cash_int_paid_keur=cash_int,
                    pik_capitalized_keur=pik,
                    post_senior_cash_keur=p.post_senior_cash_available_keur,
                    cash_consumed_keur=cash_consumed,
                    cash_after_shl_keur=cash_after_shl,
                    cash_for_distribution_keur=cash_for_dist,
                    pik_triggered=pik_triggered,
                    cash_sweep_100_pct=sweep_100,
                    reserve_applied=reserve_applied,
                    distribution_account_r102_sweep_candidate_keur=r102_candidate,
                    r102_sweep_applied_keur=r102_sweep_applied,
                    classification=classification,
                    warnings=tuple(warnings),
                )
            )

        # Compute final closing balance
        final_closing = period_results[-1].closing_balance_keur if period_results else 0.0

        # Total SHL debt service incl WHT (for Generic Wind Reference: WHT=0 so = cash_int + principal)
        total_shl_ds = totals["cash_int"] + totals["principal"]

        return ShlEngineResult(
            project_name=inputs.project_name,
            period_count=inputs.period_count,
            period_results=tuple(period_results),
            total_gross_accrued_interest_keur=totals["gross"],
            total_cash_interest_paid_keur=totals["cash_int"],
            total_pik_capitalized_keur=totals["pik"],
            total_principal_repaid_keur=totals["principal"],
            total_shl_debt_service_incl_wht_keur=total_shl_ds,
            total_cash_consumed_keur=totals["cash_consumed"],
            final_closing_balance_keur=final_closing,
            pik_period_count=pik_count,
            cash_sweep_100_pct_period_count=sweep_100_count,
            audit_table=tuple(audit_rows),
        )


def _period_to_excel_col(period_index: int) -> str:
    """Convert 1-based period index to Excel column letter."""
    # Period 1 = col G, Period 2 = col H, etc.
    # G=7, H=8, ...
    col_num = period_index + 6
    result = ""
    while col_num > 0:
        col_num, remainder = divmod(col_num - 1, 26)
        result = chr(65 + remainder) + result
    return result