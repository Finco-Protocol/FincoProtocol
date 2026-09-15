"""
financial_engine.provenance — Deterministic engine run provenance.

EngineProvenance is attached at result construction time and is immutable.
The input fingerprint is a deterministic hash of the clean OperatingModelInput —
same inputs always produce the same fingerprint; one material change produces
a different one. It contains no timestamps, object IDs, paths, or Git SHAs.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import date
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from financial_engine.inputs import OperatingModelInput


@dataclass(frozen=True)
class DerivationEvidence:
    """Records which source module/function produced a specific output."""
    output_path: str
    source_module: str
    source_function: str
    input_paths: tuple[str, ...]
    notes: tuple[str, ...]


@dataclass(frozen=True)
class EngineProvenance:
    """Immutable provenance record for one clean engine run."""
    engine_version: str
    run_path_id: str
    input_fingerprint: str
    derivation_evidence: tuple[DerivationEvidence, ...]


def _to_canonical(obj: Any) -> Any:
    """Recursively convert to a JSON-serializable canonical form."""
    if isinstance(obj, date):
        return obj.isoformat()
    if isinstance(obj, (bool, int, float, str, type(None))):
        return obj
    if isinstance(obj, (list, tuple)):
        return [_to_canonical(v) for v in obj]
    if isinstance(obj, dict):
        return {k: _to_canonical(v) for k in sorted(obj) for v in [obj[k]]}
    # dataclass fallback
    try:
        import dataclasses
        if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
            return _to_canonical(dataclasses.asdict(obj))
    except Exception:
        pass
    return str(obj)


def compute_input_fingerprint(inputs: "OperatingModelInput") -> str:
    """Compute a deterministic SHA-256 fingerprint of the clean input contract.

    Stable key ordering, no timestamps, no paths, no object IDs.
    Same OperatingModelInput always produces the same hex digest.
    """
    import dataclasses
    raw = _to_canonical(dataclasses.asdict(inputs))
    canonical = json.dumps(raw, sort_keys=True, ensure_ascii=False, allow_nan=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def compute_tax_cfads_fingerprint(inputs: "Any") -> str:
    """Compute a deterministic SHA-256 fingerprint of TaxCfadsModelInput.

    Covers the complete operating + tax input set. Any change to:
    - corporate tax rate, ATAD limit, ATAD threshold, LCF duration,
      cash-tax timing, cash-tax lag, opening vintage origins/amounts,
      any period interest component, any fiscal adjustment
    will produce a different fingerprint.
    """
    import dataclasses

    def _to_canonical_extended(obj: Any) -> Any:
        """Handle TaxPolicy enum fields and property-based fields."""
        from enum import Enum
        if isinstance(obj, Enum):
            return obj.value
        if isinstance(obj, date):
            return obj.isoformat()
        if isinstance(obj, (bool, int, float, str, type(None))):
            return obj
        if isinstance(obj, (list, tuple)):
            return [_to_canonical_extended(v) for v in obj]
        if isinstance(obj, dict):
            return {k: _to_canonical_extended(v) for k in sorted(obj) for v in [obj[k]]}
        try:
            if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
                d = dataclasses.asdict(obj)
                # Add computed properties that affect tax calculations
                if hasattr(obj, 'total_interest_keur'):
                    d['_total_interest_keur'] = obj.total_interest_keur
                return _to_canonical_extended(d)
        except Exception:
            pass
        return str(obj)

    raw = _to_canonical_extended(inputs)
    canonical = json.dumps(raw, sort_keys=True, ensure_ascii=False, allow_nan=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def compute_senior_debt_fingerprint(inputs: "Any") -> str:
    """Deterministic SHA-256 fingerprint for a Phase 2C SeniorDebtModelInput.

    Covers operating + tax + senior_debt_policy + senior_debt_inputs.
    initial_debt_guess_keur is intentionally EXCLUDED — the correct answer
    must be independent of the initial guess.

    Two runs differing only in target_dscr, annual_fixed_rate, maximum_gearing,
    maturity, opening_debt_balance_keur, or explicit_principal produce different
    fingerprints. Two identical runs produce the same fingerprint.

    Per-period formula (C3B3A provenance):
        resolved_target_dscr[p] = period_dscr_targets[p].target_dscr
                                   if p in period_dscr_targets else policy.target_dscr
        resolved_availability[p] = period_debt_service_availability[p].availability_fraction
                                    if p in period_debt_service_availability else 1.0
        allowed_debt_service[p]  = max(0, CFADS[p] / resolved_target_dscr[p])
                                    * resolved_availability[p]
        principal[p]             = min(
                                       opening_balance[p],
                                       max(0, allowed_debt_service[p] - interest[p])
                                   )
    """
    import dataclasses
    from enum import Enum

    def _to_c(obj):
        if isinstance(obj, Enum):
            return obj.value
        if isinstance(obj, date):
            return obj.isoformat()
        if isinstance(obj, (bool, int, float, str, type(None))):
            return obj
        if isinstance(obj, (list, tuple)):
            return [_to_c(v) for v in obj]
        if isinstance(obj, dict):
            return {k: _to_c(v) for k in sorted(obj) for v in [obj[k]]}
        try:
            if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
                return _to_c(dataclasses.asdict(obj))
        except Exception:
            pass
        return str(obj)

    from financial_engine.inputs import TaxCfadsModelInput
    phase2b_fp = compute_tax_cfads_fingerprint(
        TaxCfadsModelInput(operating=inputs.operating, tax=inputs.tax)
    )

    # Include debt_sizing_case in fingerprint (source_label excluded — audit-only).
    debt_case_payload = None
    dc = getattr(inputs, "debt_sizing_case", None)
    if dc is not None:
        debt_case_payload = {
            "production_yield_scenario": dc.production_yield_scenario.value,
            "merchant_price_calendar_start_year": dc.merchant_price_calendar_start_year,
            "merchant_prices_by_calendar_year_eur_mwh": list(dc.merchant_prices_by_calendar_year_eur_mwh),
            "market_prices_curve_eur_mwh": list(dc.market_prices_curve_eur_mwh),
            "tax_periodisation_mode_override": dc.tax_periodisation_mode_override,
        }

    shl_payload = None
    shl = getattr(inputs, "shareholder_loan", None)
    if shl is not None:
        convention = getattr(shl.day_count_convention, "value", shl.day_count_convention)
        shl_payload = {
            "initial_principal_keur": shl.initial_principal_keur,
            "annual_fixed_rate": shl.annual_fixed_rate,
            "day_count_convention": convention,
            "construction_day_count_fraction": shl.construction_day_count_fraction,
            "repayment_mode": getattr(shl.repayment_mode, "value", shl.repayment_mode),
            "repayment_start_period_index": shl.repayment_start_period_index,
            "maturity_period_index": shl.maturity_period_index,
            "convergence_tolerance_keur": shl.convergence_tolerance_keur,
            "convergence_relative_tolerance": shl.convergence_relative_tolerance,
            "maximum_iterations": shl.maximum_iterations,
        }

    policy = inputs.senior_debt_policy
    sd = inputs.senior_debt_inputs

    payload = {
        "phase2b_fingerprint": phase2b_fp,
        "debt_sizing_case": debt_case_payload,
        "shareholder_loan": shl_payload,
        "policy": {
            "policy_id": policy.policy_id,
            "policy_version": policy.policy_version,
            "sizing_mode": policy.sizing_mode.value,
            "target_dscr": policy.target_dscr,
            "maximum_gearing": policy.maximum_gearing,
            "annual_fixed_rate": policy.annual_fixed_rate,
            "periods_per_year": policy.periods_per_year,
            "day_count_convention": policy.day_count_convention.value,
            "repayment_start_period_index": policy.repayment_start_period_index,
            "maturity_period_index": policy.maturity_period_index,
            "convergence_tolerance_keur": policy.convergence_tolerance_keur,
            "convergence_relative_tolerance": policy.convergence_relative_tolerance,
            "maximum_iterations": policy.maximum_iterations,
            "permit_terminal_balloon": policy.permit_terminal_balloon,
            "damping_alpha": policy.damping_alpha,
        },
        "inputs": {
            "eligible_project_cost_keur": sd.eligible_project_cost_keur,
            "opening_debt_balance_keur": sd.opening_debt_balance_keur,
            "period_rates": [{"period_index": pr.period_index, "annual_rate": pr.annual_rate} for pr in sd.period_rates],
            "explicit_principal": [{"period_index": pp.period_index, "principal_keur": pp.principal_keur} for pp in (sd.explicit_principal_schedule or ())],
            "period_dscr_targets": [{"period_index": dt.period_index, "target_dscr": dt.target_dscr} for dt in sd.period_dscr_targets],
            "period_debt_service_availability": [{"period_index": av.period_index, "availability_fraction": av.availability_fraction} for av in sd.period_debt_service_availability],
        },
    }
    canonical = json.dumps(payload, sort_keys=True, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
