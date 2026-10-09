"""Request-local typed financing bridge; existing kernels own all economics."""
from __future__ import annotations

from dataclasses import replace
import json
from math import isfinite

FIELD_ID = "debt.bankability.configuration"
SNAPSHOT_KEY = "bankability_config_json"
KEYS = {"version", "sizing_mode", "lender_case", "targets", "target_scalar", "rates_pct", "day_count", "fees", "reserve"}


def number(value, name, minimum=0, maximum=100):
    try:
        finite = isinstance(value, (int, float)) and isfinite(value)
    except OverflowError:
        finite = False
    if isinstance(value, bool) or not finite:
        raise ValueError(f"{name} must be a finite number.")
    if not minimum <= value <= maximum:
        raise ValueError(f"{name} must be between {minimum} and {maximum}.")
    return float(value)


def parse_config(raw):
    if not raw:
        return {}
    if not isinstance(raw, str) or len(raw) > 16000:
        raise ValueError("Bankability configuration must be bounded JSON text.")
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"Duplicate bankability key: {key}.")
            result[key] = value
        return result
    try:
        config = json.loads(raw, object_pairs_hook=unique)
    except (TypeError, json.JSONDecodeError) as exc:
        raise ValueError("Bankability configuration is not valid JSON.") from exc
    if not isinstance(config, dict) or set(config) - KEYS or type(config.get("version")) is not int or config["version"] != 1:
        raise ValueError("Unsupported bankability configuration/version/keys.")
    for key, choices in (
        ("sizing_mode", ("flat_dscr_sculpted", "gearing_cap")),
        ("lender_case", ("P_50", "P90-10y")),
        ("day_count", ("act_360", "act_365")),
    ):
        if config.get(key) is not None and config[key] not in choices:
            raise ValueError(f"Unsupported {key}.")
    for key, low, high in (("targets", 1, 3), ("rates_pct", 0, 20)):
        values = config.get(key)
        if values is not None:
            if not isinstance(values, list) or len(values) > 120:
                raise ValueError(f"{key} must be a bounded complete period vector.")
            for value in values:
                number(value, key, low, high)
    if config.get("target_scalar") is not None:
        number(config["target_scalar"], "Scalar target DSCR", 1, 3)
        if config.get("targets") != []:
            raise ValueError("An explicit scalar target requires the scalar fallback selection.")
    fees = config.get("fees")
    if fees is not None:
        if not isinstance(fees, dict) or set(fees) != {"commitment_pct", "structuring_pct", "arrangement_pct"}:
            raise ValueError("Fees require exactly commitment, structuring and arrangement percentages.")
        for key, value in fees.items():
            number(value, key, 0, 10)
    reserve = config.get("reserve")
    if reserve is not None:
        if not isinstance(reserve, dict) or set(reserve) != {"mode", "months", "requirement_keur", "commitment_keur", "fee_pct"}:
            raise ValueError("Invalid reserve configuration keys.")
        if reserve["mode"] not in ("none", "automatic_peak", "cash_fixed", "dsrf"):
            raise ValueError("Unsupported reserve policy.")
        months = reserve["months"]
        if type(months) is not int or not 0 <= months <= 12:
            raise ValueError("Reserve coverage must be whole months from 0 to 12.")
        for key in ("requirement_keur", "commitment_keur"):
            number(reserve[key], key, 0, 1000000)
        number(reserve["fee_pct"], "Reserve commitment fee", 0, 10)
        mode = reserve["mode"]
        if mode == "automatic_peak":
            if months == 0 or any(reserve[k] != 0 for k in ("requirement_keur", "commitment_keur", "fee_pct")):
                raise ValueError("Automatic peak requires positive months and no manual reserve/facility amounts.")
        elif months != 0:
            raise ValueError("Only automatic peak coverage uses the months input in this editor.")
        if mode == "none" and any(reserve[k] != 0 for k in ("requirement_keur", "commitment_keur", "fee_pct")):
            raise ValueError("NONE cannot carry a positive reserve or facility.")
        if mode == "cash_fixed" and (reserve["commitment_keur"] or reserve["fee_pct"]):
            raise ValueError("Cash DSRA cannot carry DSRF facility inputs.")
        if mode == "dsrf" and reserve["commitment_keur"] < reserve["requirement_keur"]:
            raise ValueError("DSRF commitment must cover the reserve requirement.")
    return config


def operating_axis(pi):
    from finco_core.engine.period_engine import PeriodEngine, PeriodFrequency
    from finco_core.inputs import PeriodFrequency as InputFrequency
    if pi.info.period_frequency != InputFrequency.SEMESTRIAL:
        raise ValueError("Bankability editor supports the clean SEMESTRIAL contract only.")
    info = pi.info
    engine = PeriodEngine(financial_close=info.financial_close,
        construction_months=info.construction_months, horizon_years=info.horizon_years,
        ppa_years=pi.revenue.ppa_term_years, frequency=PeriodFrequency.SEMESTRIAL,
        cod_date=info.cod_date, period_axis_convention=getattr(info.period_axis_convention, "value", info.period_axis_convention))
    periods = [p for p in engine.periods() if p.is_operation]
    count = pi.financing.senior_tenor_years * 2
    if count < 1 or len(periods) < count:
        raise ValueError("Senior tenor exceeds the actual operating period axis.")
    return periods[:count]


def fees_editable(pi):
    fin = pi.financing
    return fin.construction_financing is None and not fin.construction_period_uses_keur and not any(
        getattr(pi.capex, name, 0) for name in ("idc_keur", "commitment_fees_keur", "bank_fees_keur",
            "other_financial_keur", "vat_costs_keur", "vat_facility_idc_keur", "vat_facility_commitment_fee_keur"))


def workspace_fees_editable(pi, ws):
    """Read the same authorized CAPEX/scenario fold that Run consumes."""
    from app.persistence.scenarios_repository import get_scenario
    from app.services.capex_sub_lines_integration import apply_user_sub_lines_replacing_base
    overrides = None
    if ws.active_scenario_id:
        scenario = get_scenario(ws.active_scenario_id, ws.user_id)
        if scenario is None or scenario.archived or scenario.project_id != ws.project_id:
            raise ValueError("Active scenario fee authority is unavailable.")
        overrides = scenario.overrides
    capex = apply_user_sub_lines_replacing_base(pi.capex, project_id=ws.project_id, scenario_overrides=overrides)
    return fees_editable(replace(pi, capex=capex))


def assert_materialized_fee_authority(pi, raw):
    if parse_config(raw).get("fees") is not None and not fees_editable(pi):
        raise ValueError("Materialized CAPEX or explicit construction pricing owns fees. Remove the bankability fee override before Run.")


def apply_config(pi, raw, *, project_type=None):
    config = parse_config(raw)
    if not config:
        return pi
    from finco_core.inputs import DebtSizingMode, DebtServiceReserveSupportMode, GearingBasisMode, GearingCapRepaymentMethod, YieldScenario
    from finco_core.inputs.senior_rate_schedule import SeniorRateMode, SeniorDayCountConvention
    fin = pi.financing
    if fin.debt_sizing_mode not in (DebtSizingMode.FLAT_DSCR_SCULPTED, DebtSizingMode.GEARING_CAP):
        raise ValueError("Frozen/minimum-DSCR authority cannot be promoted by this editor.")
    axis = operating_axis(pi)
    if config.get("sizing_mode") is not None:
        fin = replace(fin, debt_sizing_mode=DebtSizingMode(config["sizing_mode"]),
            gearing_basis_mode=GearingBasisMode.TOTAL_PROJECT_USES,
            gearing_cap_repayment_method=GearingCapRepaymentMethod.LEVEL_PRINCIPAL)
    if config.get("lender_case") is not None:
        if project_type not in ("Solar", "Wind"):
            raise ValueError("Production yield lender cases are supported for Solar and Wind only.")
        fin = replace(fin, debt_sizing_case=replace(fin.debt_sizing_case,
            production_yield_scenario=YieldScenario(config["lender_case"])))
    targets = config.get("targets")
    if targets is not None:
        if targets and len(targets) != len(axis):
            raise ValueError(f"Target DSCR must cover exactly {len(axis)} actual debt periods, or be empty for the scalar fallback.")
        if targets and fin.debt_sizing_mode != DebtSizingMode.FLAT_DSCR_SCULPTED:
            raise ValueError("Period DSCR editing requires FLAT_DSCR_SCULPTED; gearing-level-principal does not sculpt to this vector.")
        fin = replace(fin, senior_sculpting_config=replace(fin.senior_sculpting_config,
            target_dscr_schedule=tuple(targets)))
    if config.get("target_scalar") is not None:
        fin = replace(fin, target_dscr=config["target_scalar"])
    rates = config.get("rates_pct")
    cfg = fin.senior_debt_interest_config
    if rates is not None:
        if len(rates) != len(axis):
            raise ValueError(f"Rates must cover exactly {len(axis)} actual debt periods.")
        cfg = replace(cfg, enabled=True, rate_schedule=replace(cfg.rate_schedule,
            mode=SeniorRateMode.EXPLICIT_ALL_IN_SCHEDULE,
            explicit_all_in_rates=tuple(x / 100 for x in rates)))
    if config.get("day_count") is not None:
        cfg = replace(cfg, day_count=SeniorDayCountConvention(config["day_count"]))
    if cfg.rate_schedule.mode != SeniorRateMode.EXPLICIT_ALL_IN_SCHEDULE or cfg.day_count not in (
        SeniorDayCountConvention.ACT_360, SeniorDayCountConvention.ACT_365):
        raise ValueError("Clean Senior requires explicit all-in rates and ACT/360 or ACT/365.")
    fin = replace(fin, senior_debt_interest_config=cfg)
    fees = config.get("fees")
    if fees is not None:
        if not fees_editable(pi):
            raise ValueError("Explicit construction pricing or manual financing CAPEX owns fees; this editor cannot override it.")
        fin = replace(fin, commitment_fee=fees["commitment_pct"] / 100,
            structuring_fee=fees["structuring_pct"] / 100, arrangement_fee=fees["arrangement_pct"] / 100)
    reserve = config.get("reserve")
    if reserve is not None:
        if pi.capex.reserve_accounts_keur:
            raise ValueError("Legacy CAPEX reserve authority is present; no competing reserve editor is permitted.")
        mode = reserve["mode"]
        if mode == "automatic_peak" and pi.financing.dsra_support_mode != DebtServiceReserveSupportMode.NONE:
            raise ValueError("Automatic peak requires the existing generic auto-reserve authority.")
        support = {"none": DebtServiceReserveSupportMode.NONE, "automatic_peak": DebtServiceReserveSupportMode.NONE,
            "cash_fixed": DebtServiceReserveSupportMode.CASH_DSRA, "dsrf": DebtServiceReserveSupportMode.DSRF}[mode]
        fin = replace(fin, dsra_support_mode=support, dsra_months=reserve["months"],
            dsra_target_policy=None if mode == "automatic_peak" else "fixed_amount",
            debt_service_reserve_requirement_keur=reserve["requirement_keur"],
            dsrf_commitment_keur=reserve["commitment_keur"], dsrf_commitment_fee_rate_pa=reserve["fee_pct"] / 100,
            dsrf_fee_expires_at_senior_maturity=True)
    result = replace(pi, financing=fin)
    # Validate the existing financial boundary without solving or materializing new costs.
    from financial_engine.financing.reserve_policy import resolve_cash_dsra_requirement_keur
    resolve_cash_dsra_requirement_keur(result)
    return result


def build_view(pi, raw, *, project_type=None):
    if pi is None:
        return {"available": False, "reason": "Typed financing authority unavailable."}
    try:
        axis = operating_axis(pi)
        config = parse_config(raw)
        apply_config(pi, '{"version":1}', project_type=project_type)
        from finco_core.inputs import DebtSizingMode
        if pi.financing.debt_sizing_mode not in (DebtSizingMode.FLAT_DSCR_SCULPTED, DebtSizingMode.GEARING_CAP):
            raise ValueError("Frozen/reference and minimum-DSCR modes are not editable through the clean sizing contract.")
    except ValueError as exc:
        return {"available": False, "reason": str(exc)}
    except (AttributeError, TypeError):
        return {"available": False, "reason": "Complete typed financing authority unavailable."}
    fin = pi.financing
    rates = fin.senior_debt_interest_config.rate_schedule.explicit_all_in_rates
    targets = fin.senior_sculpting_config.target_dscr_schedule
    return {"available": True, "config": config, "lender": fin.debt_sizing_case.production_yield_scenario.value,
        "renewable": project_type in ("Solar", "Wind"), "mode": fin.debt_sizing_mode.value,
        "day_count": fin.senior_debt_interest_config.day_count.value, "fees_editable": fees_editable(pi),
        "reserve_editable": not pi.capex.reserve_accounts_keur,
        "automatic_reserve": fin.dsra_support_mode.value == "NONE",
        "fees": {"commitment_pct": fin.commitment_fee * 100, "structuring_pct": fin.structuring_fee * 100,
            "arrangement_pct": fin.arrangement_fee * 100},
        "periods": [{"number": i + 1, "index": p.index, "start": p.start_date.isoformat(), "end": p.end_date.isoformat(),
            "target": targets[i] if i < len(targets) else fin.target_dscr,
            "rate_pct": rates[i] * 100 if i < len(rates) else None} for i, p in enumerate(axis)],
        "scalar_target": fin.target_dscr}
