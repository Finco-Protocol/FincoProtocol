"""WaterfallRunner — orchestrator for clean waterfall invocation.

S2-2: Encapsulates all waterfall computation logic.
UI pages call WaterfallRunner.run(), not run_waterfall() directly.
This makes testing easier and keeps UI layer thin.

FINCO Model update: WaterfallRunner now calls the uncached calculation core.
Streamlit caching remains in app/cache.py only.
"""
from __future__ import annotations
from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING, Optional

from app.waterfall_core import run_waterfall_v3_core
from domain.inputs import EquityIRRMethod, DebtSizingMethod, DebtSizingMode, SHLRepaymentMethod
from domain.senior_rate_schedule import SeniorDebtInterestConfig, build_senior_period_rate_schedule
from domain.senior_sculpting import SeniorSculptingConfig

if TYPE_CHECKING:
    from app.depreciation_engine import DepreciationSchedule


@dataclass(frozen=True)
class WaterfallRunConfig:
    """Configuration for a waterfall run.

    All parameters needed to run the waterfall are encapsulated here.
    This makes it easy to pass configuration around and to cache results.
    """
    # Rate and tenor
    rate_per_period: float = 0.02825        # Semi-annual rate (5.65% / 2)
    tenor_periods: int = 28                 # 14 years × 2 periods

    # DSCR settings
    target_dscr: float = 1.15              # Target DSCR for sculpting
    lockup_dscr: float = 1.10              # Lockup threshold

    # Tax
    tax_rate: float = 0.10                 # Corporate tax rate

    # DSRA
    dsra_months: int = 6                   # DSRA reserve months

    # SHL (Subordinated Hybrid Loan)
    shl_amount_keur: float = 0.0
    shl_rate: float = 0.0
    shl_idc_keur: float = 0.0
    shl_repayment_method: SHLRepaymentMethod = SHLRepaymentMethod.BULLET
    shl_tenor_years: int = 0               # 0 = bullet at senior maturity
    shl_wht_rate: float = 0.0              # WHT on SHL interest

    # Generic Wind Reference-specific: cap SHL sweep cash at R99-equivalent (reference-compatible).
    # Prevents SHL principal from consuming cash that Excel would hold back.
    use_senior_sweep_cash_cap_for_shl: bool = False
    use_reference_covenant_input_engine: bool = False
    use_shl_fcf_waterfall_engine: bool = False
    use_tax_bridge_engine: bool = False
    use_shl_gross_accrued_for_pnl: bool = False
    use_reference_shl_repayment_alignment: bool = False
    reference_shl_principal_eligibility_start_period: int | None = None
    # Phase 8.1: canonical SHL engine wiring — replaces legacy SHL output fields only.
    # When True, canonical ShlEngine output is used for SHL-specific fields at runtime.
    # REF-WIND-B and REF-SOLAR-A only.
    use_shl_canonical_engine: bool = False
    # Phase 8: canonical DepreciationEngine wiring — replaces legacy depreciation fields.
    # When True, canonical DepreciationEngine computes per-asset-class book and tax
    # depreciation; waterfall uses canonical outputs for depreciation_keur and
    # tax_depreciation_audit_keur at runtime.
    use_depreciation_canonical_engine: bool = False
    # Phase 8: canonical SeniorDebtSizing wiring — computes debt service capacity
    # from explicit sizing_cfads and per-period dscr_schedule.
    # When True, canonical SeniorDebtSizingEngine result is attached as
    # _canonical_senior_debt_sizing audit attribute.
    # R99/R102: BLOCKED — sizing wiring does not touch distribution gates.
    use_senior_debt_sizing_engine: bool = False
    # Phase 23A: explicit reference senior debt service schedule runtime wiring.
    # When True AND use_senior_debt_sizing_engine=True:
    #   - Senior debt service per period is taken from the frozen schedule
    #     (model_source_ref / debt_source_ref canonical capacity) instead of waterfall-computed DS.
    #   - DSCR becomes a backward-computed output: CFADS / frozen_senior_service.
    # Default False preserves existing runtime behavior.
    # Only Generic Wind Reference and Generic Solar Reference should enable this, after frozen data validation.
    use_frozen_excel_senior_debt_schedule: bool = False
    # Generic Wind Reference reference-compatible CIT cash tax start period (0-based operating index).
    # When set, R67 diagnostic and corporate_tax_cash are suppressed for
    # operating_index < value. Generic Wind Reference Excel: value=25 (first non-zero R67 at P25).
    generic_wind_reference_cit_cash_tax_start_operating_index: int | None = None
    # Phase 9: DistributionAccount dual-run validation (audit-only).
    # When True, attaches _dualrun_validation to the result for comparison
    # between WaterfallEngine.distribution_keur and DA.equity_distribution_paid_keur.
    # R99/R102: BLOCKED in this branch.
    use_dualrun_validation: bool = False
    shl_fcf_waterfall_cash_schedule_keur: tuple[float, ...] = ()
    shl_fcf_waterfall_minimum_cash_retained_keur: float = 0.0

    # Returns
    discount_rate_project: float = 0.0641
    discount_rate_equity: float = 0.0965

    # Debt overrides
    fixed_debt_keur: Optional[float] = None   # Override sculpted debt
    fixed_ds_keur: Optional[float] = None     # Fixed DS per period (fixed debt service)

    # Rate schedule
    rate_schedule: Optional[list[float]] = None  # Per-period Euribor curve
    use_senior_rate_schedule_engine: bool = False
    senior_debt_interest_config: SeniorDebtInterestConfig = field(default_factory=SeniorDebtInterestConfig)
    use_senior_sculpting_basis_engine: bool = False
    senior_sculpting_config: SeniorSculptingConfig = field(default_factory=SeniorSculptingConfig)

    # Equity IRR method
    equity_irr_method: EquityIRRMethod = EquityIRRMethod.EQUITY_ONLY
    share_capital_keur: float = 0.0          # Only for "combined" method
    sculpt_capex_keur: float = 0.0            # CAPEX for equity base

    # Debt sizing
    debt_sizing_method: DebtSizingMethod = DebtSizingMethod.DSCR_SCULPT
    debt_sizing_mode: Optional[DebtSizingMode] = None

    # Per-period DSCR targets (dual-DSCR sculpting)
    dscr_schedule: Optional[list[float]] = None

    # Advanced OPEX line items (None = use legacy OpexItem path)
    advanced_opex_line_items: Optional[tuple] = None

    # Advanced CAPEX line items — total computed from CapexLineItems tuple
    advanced_capex_line_items: Optional[tuple] = None

    # Advanced CAPEX depreciation schedule — from app.depreciation_engine
    # When provided, uses per-asset-class depreciable lives instead of legacy
    # CapexItem path. Must be a DepreciationSchedule object.
    advanced_capex_depreciation_schedule: "DepreciationSchedule | None" = None

    def cache_key(self) -> str:
        """Generate cache key from config parameters."""
        return (
            f"wf_{self.rate_per_period:.6f}_{self.tenor_periods}_"
            f"{self.target_dscr:.3f}_{self.shl_amount_keur:.0f}_"
            f"r99_{int(self.use_reference_covenant_input_engine)}_"
            f"sr_{int(self.use_senior_rate_schedule_engine)}_"
            f"ss_{int(self.use_senior_sculpting_basis_engine)}_"
            f"sfw_{int(self.use_shl_fcf_waterfall_engine)}_"
            f"taxb_{int(self.use_tax_bridge_engine)}_"
            f"shlg_{int(self.use_shl_gross_accrued_for_pnl)}_"
            f"shla_{int(self.use_reference_shl_repayment_alignment)}_"
            f"shlp_{self.reference_shl_principal_eligibility_start_period or 0}_"
            f"canon_{int(self.use_shl_canonical_engine)}_"
            f"depcanon_{int(self.use_depreciation_canonical_engine)}_"
            f"sds_{int(self.use_senior_debt_sizing_engine)}"
            f"frozensds_{int(self.use_frozen_excel_senior_debt_schedule)}"
        )

    @classmethod
    def from_inputs(cls, inputs: "ProjectInputs", engine: "PeriodEngine") -> "WaterfallRunConfig":
        """Build a config derived from project inputs and period engine.

        Maps financing, tax, SHL, and equity params from ProjectInputs into
        a WaterfallRunConfig so the UI need not hardcode defaults.
        """
        # Count operating periods
        periods = list(engine.periods())
        op_periods = [p for p in periods if p.is_operation]
        tenor_periods = inputs.financing.senior_tenor_years * 2
        if tenor_periods == 0:
            tenor_periods = len(op_periods) if op_periods else len(periods)

        # Determine all-in rate per period
        fin = inputs.financing
        if hasattr(fin, "all_in_rate") and fin.all_in_rate:
            rate_per_period = fin.all_in_rate / 2
        elif hasattr(fin, "base_rate") and hasattr(fin, "margin_bps"):
            rate_per_period = (fin.base_rate + fin.margin_bps / 10000.0) / 2
        else:
            rate_per_period = cls.rate_per_period  # use default

        use_senior_rate_schedule_engine = getattr(inputs.info, "use_senior_rate_schedule_engine", False)
        senior_debt_interest_config = getattr(
            fin,
            "senior_debt_interest_config",
            SeniorDebtInterestConfig(),
        )
        rate_schedule = None
        if use_senior_rate_schedule_engine:
            if not senior_debt_interest_config.enabled:
                raise ValueError(
                    "use_senior_rate_schedule_engine=True requires enabled "
                    "senior_debt_interest_config"
                )
            rate_schedule = build_senior_period_rate_schedule(
                senior_debt_interest_config,
                op_periods,
                tenor_periods,
            )
        use_senior_sculpting_basis_engine = getattr(
            inputs.info,
            "use_senior_sculpting_basis_engine",
            False,
        )
        senior_sculpting_config = getattr(
            fin,
            "senior_sculpting_config",
            SeniorSculptingConfig(),
        )
        if use_senior_sculpting_basis_engine and not senior_sculpting_config.enabled:
            raise ValueError(
                "use_senior_sculpting_basis_engine=True requires enabled "
                "senior_sculpting_config"
            )

        # Map SHL repayment method — FinancingParams may use str or enum
        shl_repayment = fin.shl_repayment_method
        if isinstance(shl_repayment, str):
            from domain.inputs import SHLRepaymentMethod
            shl_repayment = SHLRepaymentMethod(shl_repayment)
        use_shl_fcf_waterfall_engine = getattr(inputs.info, "use_shl_fcf_waterfall_engine", False)
        shl_fcf_cash_schedule = tuple(getattr(fin, "shl_fcf_waterfall_cash_schedule_keur", ()))
        if shl_repayment is SHLRepaymentMethod.FCF_WATERFALL:
            if not use_shl_fcf_waterfall_engine:
                raise ValueError(
                    "shl_repayment_method='fcf_waterfall' requires "
                    "use_shl_fcf_waterfall_engine=True"
                )
            if getattr(inputs.info, "code", "") != "REF-WIND-B":
                raise ValueError("SHL fcf_waterfall is currently supported only for REF-WIND-B")
            if not shl_fcf_cash_schedule:
                raise ValueError(
                    "SHL fcf_waterfall requires explicit reference-policy "
                    "shl_fcf_waterfall_cash_schedule_keur"
                )

        use_tax_bridge_engine = getattr(inputs.info, "use_tax_bridge_engine", False)
        # Stack AB: duplicate identity guard removed — waterfall_core enforces same guard at line 115.
        generic_wind_reference_cit_cash_tax_start_operating_index = getattr(
            inputs.tax, "cit_cash_tax_start_operating_index", None
        ) if use_tax_bridge_engine else None
        use_shl_gross_accrued_for_pnl = getattr(
            inputs.info,
            "use_shl_gross_accrued_for_pnl",
            False,
        )
        # Stack AB: duplicate identity guard removed — waterfall_core enforces same guard at line 117.
        use_reference_shl_repayment_alignment = getattr(
            fin,
            "use_reference_shl_repayment_alignment",
            False,
        )
        # Stack AB: duplicate identity guard removed — waterfall_core enforces same guard at line 119.

        use_shl_canonical_engine = getattr(
            inputs.info,
            "use_shl_canonical_engine",
            False,
        )
        if use_shl_canonical_engine and getattr(inputs.info, "code", "") not in ("REF-WIND-B", "REF-SOLAR-A"):
            raise ValueError(
                "Canonical SHL engine is currently supported only for "
                "REF-WIND-B and REF-SOLAR-A"
            )

        use_depreciation_canonical_engine = getattr(
            inputs.info,
            "use_depreciation_canonical_engine",
            False,
        )

        # Map equity_irr_method — FinancingParams stores as str, config expects enum
        from domain.inputs import EquityIRRMethod
        eq_irr = fin.equity_irr_method
        if isinstance(eq_irr, str):
            eq_irr = EquityIRRMethod(eq_irr)

        # Map debt_sizing_method — FinancingParams stores as str, config expects enum
        from domain.inputs import DebtSizingMethod
        ds_method = fin.debt_sizing_method
        if isinstance(ds_method, str):
            ds_method = DebtSizingMethod(ds_method)

        return cls(
            rate_per_period=rate_per_period,
            tenor_periods=tenor_periods,
            target_dscr=fin.target_dscr,
            lockup_dscr=fin.lockup_dscr,
            tax_rate=inputs.tax.corporate_rate,
            dsra_months=fin.dsra_months,
            shl_amount_keur=fin.shl_amount_keur,
            shl_rate=fin.shl_rate,
            shl_idc_keur=fin.shl_idc_keur,
            shl_repayment_method=shl_repayment,
            shl_tenor_years=fin.shl_tenor_years,
            equity_irr_method=eq_irr,
            share_capital_keur=fin.share_capital_keur,
            sculpt_capex_keur=inputs.capex.sculpt_capex_keur,
            debt_sizing_method=ds_method,
            debt_sizing_mode=fin.debt_sizing_mode,
            fixed_debt_keur=fin.fixed_debt_keur,
            dscr_schedule=fin.dscr_schedule,
            rate_schedule=rate_schedule,
            use_senior_rate_schedule_engine=use_senior_rate_schedule_engine,
            senior_debt_interest_config=senior_debt_interest_config,
            use_senior_sculpting_basis_engine=use_senior_sculpting_basis_engine,
            senior_sculpting_config=senior_sculpting_config,
            use_senior_sweep_cash_cap_for_shl=getattr(fin, "use_senior_sweep_cash_cap_for_shl", False),
            use_reference_covenant_input_engine=getattr(fin, "use_reference_covenant_input_engine", False),
            use_shl_fcf_waterfall_engine=use_shl_fcf_waterfall_engine,
            use_tax_bridge_engine=use_tax_bridge_engine,
            use_shl_gross_accrued_for_pnl=use_shl_gross_accrued_for_pnl,
            use_reference_shl_repayment_alignment=use_reference_shl_repayment_alignment,
            reference_shl_principal_eligibility_start_period=getattr(
                fin,
                "reference_shl_principal_eligibility_start_period",
                None,
            ),
            use_depreciation_canonical_engine=use_depreciation_canonical_engine,
            use_senior_debt_sizing_engine=getattr(
                inputs.info, "use_senior_debt_sizing_engine", False
            ),
            use_frozen_excel_senior_debt_schedule=getattr(
                fin, "use_frozen_excel_senior_debt_schedule", False
            ),
            generic_wind_reference_cit_cash_tax_start_operating_index=generic_wind_reference_cit_cash_tax_start_operating_index,
            shl_fcf_waterfall_cash_schedule_keur=shl_fcf_cash_schedule,
            shl_fcf_waterfall_minimum_cash_retained_keur=getattr(
                fin,
                "shl_fcf_waterfall_minimum_cash_retained_keur",
                0.0,
            ),
        )


@dataclass
class WaterfallRunner:
    """Orchestrator for waterfall computation.

    Usage:
        runner = WaterfallRunner(inputs, engine)
        config = WaterfallRunConfig(
            target_dscr=1.15,
            lockup_dscr=1.10,
            shl_amount_keur=29_135,
            shl_rate=0.03965,
            shl_repayment_method=SHLRepaymentMethod.PIK_THEN_SWEEP,
        )
        result = runner.run(config)
    """
    inputs: object  # ProjectInputs
    engine: object  # PeriodEngine

    def __post_init__(self):
        # Inputs validation
        if not hasattr(self.inputs, 'capex'):
            raise ValueError("inputs must have 'capex' attribute")

    def run(self, config: Optional[WaterfallRunConfig] = None) -> object:
        """Run waterfall with given configuration.

        Args:
            config: WaterfallRunConfig. If None, uses defaults.

        Returns:
            WaterfallResult from run_waterfall
        """
        if config is None:
            config = WaterfallRunConfig()

        # S4-1: Use sculpt_capex_keur from inputs.capex when config does not override it.
        sculpt_capex = (
            self.inputs.capex.sculpt_capex_keur
            if config.sculpt_capex_keur == 0.0
            else config.sculpt_capex_keur
        )

        # FINCO Model: call the uncached calculation core. app/cache.py is the only
        # module that should wrap this with Streamlit @st.cache_data.
        return run_waterfall_v3_core(
            inputs=self.inputs,
            engine=self.engine,
            rate_per_period=config.rate_per_period,
            tenor_periods=config.tenor_periods,
            target_dscr=config.target_dscr,
            lockup_dscr=config.lockup_dscr,
            tax_rate=config.tax_rate,
            dsra_months=config.dsra_months,
            shl_amount=config.shl_amount_keur,
            shl_rate=config.shl_rate,
            shl_idc_keur=config.shl_idc_keur,
            shl_repayment_method=config.shl_repayment_method.value,
            shl_tenor_years=config.shl_tenor_years,
            shl_wht_rate=config.shl_wht_rate,
            discount_rate_project=config.discount_rate_project,
            discount_rate_equity=config.discount_rate_equity,
            fixed_debt_keur=config.fixed_debt_keur,
            fixed_ds_keur=config.fixed_ds_keur,
            rate_schedule=config.rate_schedule,
            senior_sculpting_config=(
                config.senior_sculpting_config
                if config.use_senior_sculpting_basis_engine
                else None
            ),
            equity_irr_method=config.equity_irr_method.value,
            share_capital_keur=config.share_capital_keur,
            sculpt_capex_keur=sculpt_capex,
            debt_sizing_method=config.debt_sizing_method.value,
            dscr_schedule=config.dscr_schedule,
            advanced_opex_line_items=config.advanced_opex_line_items,
            advanced_capex_line_items=config.advanced_capex_line_items,
            advanced_capex_depreciation_schedule=config.advanced_capex_depreciation_schedule,
            use_senior_sweep_cash_cap_for_shl=config.use_senior_sweep_cash_cap_for_shl,
            use_reference_covenant_input_engine=config.use_reference_covenant_input_engine,
            use_shl_fcf_waterfall_engine=config.use_shl_fcf_waterfall_engine,
            use_tax_bridge_engine=config.use_tax_bridge_engine,
            use_shl_gross_accrued_for_pnl=config.use_shl_gross_accrued_for_pnl,
            use_reference_shl_repayment_alignment=config.use_reference_shl_repayment_alignment,
            reference_shl_principal_eligibility_start_period=(
                config.reference_shl_principal_eligibility_start_period
            ),
            use_shl_canonical_engine=config.use_shl_canonical_engine,
            use_depreciation_canonical_engine=config.use_depreciation_canonical_engine,
            use_senior_debt_sizing_engine=config.use_senior_debt_sizing_engine,
            use_frozen_excel_senior_debt_schedule=config.use_frozen_excel_senior_debt_schedule,
            generic_wind_reference_cit_cash_tax_start_operating_index=config.generic_wind_reference_cit_cash_tax_start_operating_index,
            use_dualrun_validation=config.use_dualrun_validation,
            shl_fcf_waterfall_cash_schedule_keur=config.shl_fcf_waterfall_cash_schedule_keur,
            shl_fcf_waterfall_minimum_cash_retained_keur=(
                config.shl_fcf_waterfall_minimum_cash_retained_keur
            ),
        )

    def run_with_defaults(self) -> object:
        """DEPRECATED: Use WaterfallRunConfig.from_inputs() + run(config) instead.

        This method uses hardcoded defaults rather than project-specific financing
        assumptions. It exists only for backward compatibility with legacy calls.
        """
        import warnings
        warnings.warn(
            "WaterfallRunner.run_with_defaults() is deprecated. "
            "Use WaterfallRunConfig.from_inputs(inputs, engine) + runner.run(config) instead.",
            DeprecationWarning,
            stacklevel=2,
        )
        return self.run(WaterfallRunConfig())

    def invalidate_cache(self) -> None:
        """Invalidate all Streamlit cached computations for this project.

        Imported lazily so this runner remains importable in headless contexts.
        """
        from app.cache import clear_all_caches

        clear_all_caches()


@dataclass
class ScenarioRunner:
    """Runner for multiple scenarios (sensitivity, Monte Carlo, etc.).

    Encapsulates the logic for running multiple waterfall configurations
    and collecting results.
    """
    inputs: object  # ProjectInputs
    engine: object  # PeriodEngine

    def run_sensitivity(
        self,
        base_config: WaterfallRunConfig,
        param_name: str,
        param_values: list[float],
    ) -> list[object]:
        """Run sensitivity analysis over parameter values.

        Args:
            base_config: Base configuration to modify
            param_name: Name of parameter to vary
            param_values: List of values to test

        Returns:
            List of WaterfallResult (one per value)
        """
        results = []
        for value in param_values:
            if not hasattr(base_config, param_name):
                raise ValueError(f"Unknown sensitivity parameter: {param_name}")

            config = replace(base_config, **{param_name: value})
            runner = WaterfallRunner(self.inputs, self.engine)
            result = runner.run(config)
            results.append(result)

        return results


__all__ = [
    "WaterfallRunConfig",
    "WaterfallRunner",
    "ScenarioRunner",
]
