"""Convert ProjectInputsSchema (DTO) into domain ProjectInputs.

Architecture:
  JSON/YAML/API request
       ↓
  ProjectInputsSchema (validation only — no business logic)
       ↓
  input_adapter.build_projectinputs()
       ↓
  existing domain ProjectInputs  (frozen dataclass)
       ↓
  run_demo_project(project_inputs_override=...)

This is a pure adapter — it applies only the overrides specified in the schema,
leaving all other factory defaults intact.
"""
from __future__ import annotations

from calendar import monthrange
from dataclasses import replace as dc_replace
from datetime import date
from typing import TYPE_CHECKING, Optional

from app.input_schema import ProjectInputsSchema

if TYPE_CHECKING:
    from domain.inputs import ProjectInputs


class SnapshotInputError(ValueError):
    """Raised when a saved user-project snapshot cannot build runtime inputs."""


# Map of domain field paths → (getter, setter) for clean replacement
# Each setter takes (parent_obj, value) → new parent_obj with value applied


def _set_technical_capacity(proj: "ProjectInputs", value: float) -> "ProjectInputs":
    return dc_replace(proj, technical=dc_replace(proj.technical, capacity_mw=value))


def _set_technical_p50_hours(proj: "ProjectInputs", value: float) -> "ProjectInputs":
    return dc_replace(proj, technical=dc_replace(proj.technical, operating_hours_p50=value))


def _set_technical_degradation(proj: "ProjectInputs", value: float) -> "ProjectInputs":
    return dc_replace(proj, technical=dc_replace(proj.technical, pv_degradation=value))


def _set_revenue_tariff(proj: "ProjectInputs", value: float) -> "ProjectInputs":
    return dc_replace(proj, revenue=dc_replace(proj.revenue, ppa_base_tariff=value))


def _set_opex_inflation(proj: "ProjectInputs", value: float) -> "ProjectInputs":
    """Set annual_inflation on all existing OPEX line items."""
    new_items = tuple(
        dc_replace(item, annual_inflation=value) for item in proj.opex
    )
    return dc_replace(proj, opex=new_items)


def _set_financing_gearing(proj: "ProjectInputs", value: float) -> "ProjectInputs":
    # schema passes gearing as 0-100, domain uses 0.0-1.0
    return dc_replace(proj, financing=dc_replace(proj.financing, gearing_ratio=value / 100.0))


def _set_financing_senior_debt(proj: "ProjectInputs", value: float) -> "ProjectInputs":
    return dc_replace(proj, financing=dc_replace(proj.financing, senior_debt_amount_keur=value))


def senior_rate_authority(proj: "ProjectInputs") -> tuple[str, Optional[float], int]:
    """R8/N02 — classify the typed Senior pricing authority of a project.

    Returns ``(mode, uniform_ratio, n_periods)``:
      - ``"FLAT"``       — the explicit all-in schedule is uniform, so one
        scalar faithfully represents every applicable debt period;
      - ``"CALIBRATED"`` — the schedule carries a source-calibrated non-uniform
        vector that a single scalar cannot faithfully represent.
    """
    rs = proj.financing.senior_debt_interest_config.rate_schedule
    rates = list(getattr(rs, "explicit_all_in_rates", None) or [])
    if rates and len(set(round(r, 12) for r in rates)) == 1:
        return ("FLAT", rates[0], len(rates))
    return ("CALIBRATED", None, len(rates))


def senior_dscr_authority(proj: "ProjectInputs") -> tuple[str, Optional[float], int]:
    """R8/N02 — classify the typed Senior DSCR-target authority.

      - ``"FLAT_SCALAR"``   — no explicit schedule; ``financing.target_dscr``
        is the period authority consumed by the clean solve;
      - ``"FLAT_SCHEDULE"`` — an explicit schedule exists and is uniform, so a
        scalar faithfully represents every target period;
      - ``"CALIBRATED"``    — a source-calibrated non-uniform schedule
        (e.g. 1.15/1.35) that a single scalar cannot represent.
    """
    sculpt = proj.financing.senior_sculpting_config
    sched = list(getattr(sculpt, "target_dscr_schedule", None) or [])
    if not sched:
        return ("FLAT_SCALAR", proj.financing.target_dscr, 0)
    if len(set(round(t, 12) for t in sched)) == 1:
        return ("FLAT_SCHEDULE", sched[0], len(sched))
    return ("CALIBRATED", None, len(sched))


_SENIOR_LOCKED_RATE_REASON = (
    "Explicit calibrated period schedule controls this assumption — "
    "the all-in rate is not a single editable scalar for this project."
)
_SENIOR_LOCKED_DSCR_REASON = (
    "Explicit calibrated period schedule controls this assumption — "
    "the target DSCR is not a single editable scalar for this project."
)


def assert_debt_scalar_edit_allowed(pis, field_id: str) -> None:
    """R8/N02 (Correction A) — fail closed BEFORE persisting a Senior scalar
    edit that the typed authority cannot honour.

    Raises ValueError with the honest reason when the authority is a
    calibrated schedule OR cannot be resolved (chained from the underlying
    materialisation failure for diagnosis).  Never substitutes a factory."""
    if field_id not in ("debt.senior.interest_rate_pct",
                        "debt.senior.target_dscr"):
        return
    from app.workbook.service import WorkbookService

    try:
        pi = WorkbookService.to_projectinputs(pis)
    except Exception as exc:
        raise ValueError(
            "Senior authority unavailable — assumption cannot be edited "
            "safely.") from exc
    if field_id == "debt.senior.interest_rate_pct":
        mode, _, _ = senior_rate_authority(pi)
        if mode == "CALIBRATED":
            raise ValueError(_SENIOR_LOCKED_RATE_REASON)
    else:
        mode, _, _ = senior_dscr_authority(pi)
        if mode == "CALIBRATED":
            raise ValueError(_SENIOR_LOCKED_DSCR_REASON)


def _set_financing_interest_rate(proj: "ProjectInputs", value: float) -> "ProjectInputs":
    """R8/N02 — apply a Workbook all-in-rate edit (human %, 9.0 == 9%) to the
    typed authority the clean Senior engine consumes.

    Unit contract: UI/snapshot store percent; this setter converts to a ratio
    EXACTLY ONCE and writes it into every entry of the explicit all-in period
    vector.  ``financing.margin_bps`` is kept consistent as auxiliary state.
    A source-calibrated non-uniform schedule is never overwritten by a
    scalar — the caller must have gated the edit via
    ``assert_debt_scalar_edit_allowed``; the check is repeated here so no
    code path can silently write a decorative value.
    """
    fin = proj.financing
    rate_cfg = fin.senior_debt_interest_config
    schedule = list(getattr(
        rate_cfg.rate_schedule, "explicit_all_in_rates", None) or [])
    mode, _, _ = senior_rate_authority(proj)
    if mode == "CALIBRATED":
        # R8/N02: passive materialisation of a calibrated working copy must
        # NEVER break and must never let the scalar overwrite the typed
        # schedule — the calibrated vector wins and the auxiliary scalar is
        # ignored (the Save gate rejects calibrated edits before persistence;
        # the Debt sheet projects the schedule as the authority).
        return proj
    all_in = value / 100.0  # single % -> ratio conversion boundary
    new_schedule = tuple(all_in for _ in schedule)
    new_rate_cfg = dc_replace(
        rate_cfg,
        rate_schedule=dc_replace(rate_cfg.rate_schedule,
                                 explicit_all_in_rates=new_schedule),
    )
    base_rate = fin.base_rate
    margin_bps = max(0, int(round((all_in - base_rate) * 10_000)))
    return dc_replace(
        proj,
        financing=dc_replace(proj.financing,
                             margin_bps=margin_bps,
                             senior_debt_interest_config=new_rate_cfg),
    )


def _set_financing_tenor(proj: "ProjectInputs", value: int) -> "ProjectInputs":
    # Update the tenor year count AND resize the explicit-all-in rate schedule to match.
    # The generic project factories create a rate vector sized for the factory's default
    # tenor (e.g. 15y × 2 = 30 entries for SEMESTRIAL).  When the user changes tenor via
    # the workbook form the engine validation requires len(explicit_all_in_rates) >= tenor_periods.
    # We resize here — in the UI adapter — so that no financial vector mismatch reaches the engine.
    # Resizing strategy: extend by repeating the last rate; trim if shortening.
    financing = proj.financing
    new_financing = dc_replace(financing, senior_tenor_years=value)

    try:
        from finco_core.inputs.senior_rate_schedule import SeniorRateMode
        cfg = financing.senior_debt_interest_config
        if (cfg is not None and cfg.enabled and
                cfg.rate_schedule.mode == SeniorRateMode.EXPLICIT_ALL_IN_SCHEDULE):
            # Determine periods_per_year from project info (SEMESTRIAL = 2).
            freq_value = getattr(proj.info.period_frequency, "value", 2)
            periods_per_year = int(freq_value) if isinstance(freq_value, int) else 2
            target_len = value * periods_per_year
            current_rates = cfg.rate_schedule.explicit_all_in_rates
            if len(current_rates) != target_len:
                if len(current_rates) == 0:
                    resized = ()
                elif target_len <= len(current_rates):
                    resized = current_rates[:target_len]
                else:
                    last = current_rates[-1]
                    resized = current_rates + (last,) * (target_len - len(current_rates))
                new_schedule = dc_replace(cfg.rate_schedule, explicit_all_in_rates=resized)
                new_cfg = dc_replace(cfg, rate_schedule=new_schedule)
                new_financing = dc_replace(new_financing, senior_debt_interest_config=new_cfg)
    except Exception:
        pass  # If introspection fails, fall through with only the tenor year change.

    return dc_replace(proj, financing=new_financing)


def _set_financing_target_dscr(proj: "ProjectInputs", value: float) -> "ProjectInputs":
    """R8/N02 — apply a Workbook target-DSCR edit under the typed authority:
    no schedule -> the scalar is the period authority (unchanged behaviour);
    a uniform explicit schedule is faithfully rewritten flat; a calibrated
    non-uniform schedule is never silently replaced (fail closed)."""
    fin = proj.financing
    sculpt = fin.senior_sculpting_config
    sched = list(getattr(sculpt, "target_dscr_schedule", None) or [])
    mode, _, _ = senior_dscr_authority(proj)
    if mode == "CALIBRATED":
        # R8/N02: passive materialisation never breaks and never lets the
        # scalar overwrite the calibrated schedule (Save gate rejects the
        # edit; the Debt sheet projects the schedule as the authority).
        return proj
    if mode == "FLAT_SCHEDULE":
        new_sculpt = dc_replace(
            sculpt, target_dscr_schedule=tuple(float(value) for _ in sched))
        return dc_replace(
            proj,
            financing=dc_replace(proj.financing,
                                 target_dscr=float(value),
                                 senior_sculpting_config=new_sculpt))
    return dc_replace(proj, financing=dc_replace(proj.financing, target_dscr=value))


def _set_tax_corporate_rate(proj: "ProjectInputs", value: float) -> "ProjectInputs":
    """Apply a Workbook CIT-rate edit (human %, e.g. 18.0 == 18%) to the
    single effective rate authority for the project's typed tax mode
    (R4/F06 dual-mode contract).

    - Project WITHOUT a selected country_tax_policy_id: the generic
      project-level authority stays ``TaxParams.corporate_rate`` (ratio);
      ``corporate_rate_override`` is never fabricated.
    - Project WITH a selected country_tax_policy_id: the explicit Workbook
      edit maps to the typed ``TaxParams.corporate_rate_override`` (ratio).
      The selected policy remains the jurisdiction/default authority and the
      legacy ``corporate_rate`` keeps its policy-default value, so the clean
      country-tax adapter never sees a fabricated second authority
      (COUNTRY_TAX_LEGACY_FIELD_CONFLICT stays reserved for genuinely
      contradictory historical states).

    The % → ratio conversion happens exactly once, here — no layer duplicates it.
    """
    tax = proj.tax
    if getattr(tax, "country_tax_policy_id", None) is not None:
        return dc_replace(
            proj, tax=dc_replace(tax, corporate_rate_override=value / 100.0))
    return dc_replace(proj, tax=dc_replace(tax, corporate_rate=value / 100.0))


def _set_tax_loss_carryforward_years(proj: "ProjectInputs", value: int) -> "ProjectInputs":
    return dc_replace(proj, tax=dc_replace(proj.tax, loss_carryforward_years=int(value)))


def _set_revenue_ppa_term(proj: "ProjectInputs", value: int) -> "ProjectInputs":
    """Set the PPA term in years on the revenue block."""
    return dc_replace(
        proj,
        revenue=dc_replace(
            proj.revenue,
            ppa_term_years=int(value),
        ),
    )


def _set_revenue_ppa_index(proj: "ProjectInputs", value: float) -> "ProjectInputs":
    """UI stores human-readable % (e.g. 2.0); engine expects fraction (0.02)."""
    return dc_replace(proj, revenue=dc_replace(proj.revenue, ppa_index=value / 100.0))


def _set_revenue_ppa_production_share(proj: "ProjectInputs", value: float) -> "ProjectInputs":
    """UI stores human-readable % (e.g. 50.0); engine expects fraction (0.50)."""
    return dc_replace(proj, revenue=dc_replace(proj.revenue, ppa_production_share=value / 100.0))


def _set_revenue_ppa_indexation_policy(proj: "ProjectInputs", value: str) -> "ProjectInputs":
    return dc_replace(proj, revenue=dc_replace(proj.revenue, ppa_indexation_start_policy=value))


def _set_revenue_ppa_indexation_start_date(proj: "ProjectInputs", value: str) -> "ProjectInputs":
    """Parse ISO-8601 date string (YYYY-MM-DD) and set ppa_indexation_start_date."""
    from datetime import date as _date
    if not value or str(value).strip() == "":
        return dc_replace(proj, revenue=dc_replace(proj.revenue, ppa_indexation_start_date=None))
    try:
        parsed = _date.fromisoformat(str(value).strip())
    except ValueError as exc:
        raise ValueError(f"rev_ppa_indexation_start_date must be YYYY-MM-DD, got {value!r}") from exc
    return dc_replace(proj, revenue=dc_replace(proj.revenue, ppa_indexation_start_date=parsed))


def _set_revenue_merchant_balancing_pct(proj: "ProjectInputs", value: float) -> "ProjectInputs":
    """Set balancing_cost_pv (% of merchant revenue as fraction 0–1)."""
    return dc_replace(proj, revenue=dc_replace(proj.revenue, balancing_cost_pv=value / 100.0))


def _set_revenue_balancing_eur_per_mwh(proj: "ProjectInputs", value: float) -> "ProjectInputs":
    return dc_replace(proj, revenue=dc_replace(proj.revenue, balancing_cost_eur_per_mwh=value))


def _set_revenue_co2_enabled(proj: "ProjectInputs", value: bool) -> "ProjectInputs":
    return dc_replace(proj, revenue=dc_replace(proj.revenue, co2_enabled=bool(value)))


def _set_revenue_co2_price_eur_mwh(proj: "ProjectInputs", value: float) -> "ProjectInputs":
    """Set canonical co2_certificate_price_eur_per_mwh (EUR/MWh applied to generation)."""
    return dc_replace(proj, revenue=dc_replace(proj.revenue, co2_certificate_price_eur_per_mwh=value))


def validate_merchant_curve_json(curve_json: str) -> list:
    """Validate and parse a merchant price curve JSON string.

    Expected format: [{"year": 2042, "price_eur_mwh": 75.12}, ...]
    Returns sorted list of dicts on success; raises ValueError with a descriptive
    message on any validation failure.
    """
    import json as _json
    import math as _math

    try:
        items = _json.loads(curve_json)
    except (_json.JSONDecodeError, TypeError) as exc:
        raise ValueError(f"Invalid JSON: {exc}") from exc

    if not isinstance(items, list):
        raise ValueError("Merchant curve must be a JSON array")
    if not items:
        raise ValueError("Merchant curve must not be empty")

    parsed = []
    for i, item in enumerate(items):
        if not isinstance(item, dict):
            raise ValueError(f"Item {i} is not an object")
        if "year" not in item:
            raise ValueError(f"Item {i} missing 'year'")
        if "price_eur_mwh" not in item:
            raise ValueError(f"Item {i} missing 'price_eur_mwh'")
        raw_year = item["year"]
        if isinstance(raw_year, bool):
            raise ValueError(f"Item {i} 'year' must be an integer, got {raw_year!r}")
        if isinstance(raw_year, float):
            if raw_year != int(raw_year):
                raise ValueError(
                    f"Item {i} 'year' must be a whole-number calendar year, "
                    f"got {raw_year!r} (fractional years are not supported)"
                )
            year = int(raw_year)
        elif isinstance(raw_year, int):
            year = raw_year
        elif isinstance(raw_year, str):
            stripped = raw_year.strip()
            try:
                as_float = float(stripped)
            except (TypeError, ValueError):
                raise ValueError(f"Item {i} 'year' must be an integer, got {raw_year!r}")
            if as_float != int(as_float):
                raise ValueError(
                    f"Item {i} 'year' must be a whole-number calendar year, "
                    f"got {raw_year!r} (fractional years are not supported)"
                )
            year = int(as_float)
        else:
            raise ValueError(f"Item {i} 'year' must be an integer, got {raw_year!r}")
        try:
            price = float(item["price_eur_mwh"])
        except (TypeError, ValueError):
            raise ValueError(f"Item {i} 'price_eur_mwh' must be numeric, got {item['price_eur_mwh']!r}")
        if _math.isnan(price) or _math.isinf(price):
            raise ValueError(f"Item {i} 'price_eur_mwh' must be finite, got {price}")
        if price < 0:
            raise ValueError(f"Item {i} 'price_eur_mwh' must be non-negative, got {price}")
        parsed.append({"year": year, "price_eur_mwh": price})

    sorted_items = sorted(parsed, key=lambda x: x["year"])

    # Duplicate year check
    years = [x["year"] for x in sorted_items]
    if len(years) != len(set(years)):
        raise ValueError("Merchant curve contains duplicate years")

    # Contiguous year check — gaps would corrupt the calendar-year tuple index
    for j in range(1, len(years)):
        if years[j] != years[j - 1] + 1:
            raise ValueError(
                f"Merchant curve years must be contiguous; gap between {years[j-1]} and {years[j]}"
            )

    return sorted_items


def _set_revenue_merchant_price_curve_json(proj: "ProjectInputs", curve_json: str) -> "ProjectInputs":
    """Parse JSON merchant price curve and wire into market_prices_by_calendar_year_eur_mwh.

    Expected format: [{"year": 2042, "price_eur_mwh": 75.12}, ...]
    Raises ValueError for malformed input; caller should catch and surface to user.
    """
    sorted_items = validate_merchant_curve_json(curve_json)
    start_year = sorted_items[0]["year"]
    prices = tuple(x["price_eur_mwh"] for x in sorted_items)
    return dc_replace(
        proj,
        revenue=dc_replace(
            proj.revenue,
            market_price_calendar_start_year=start_year,
            market_prices_by_calendar_year_eur_mwh=prices,
        ),
    )


def _zero_financial_capex_subfields(proj: "ProjectInputs") -> "ProjectInputs":
    """Zero out the financial cost sub-fields on the
    capex structure.

    Phase S1 contract: user-supplied ``total_capex_keur``
    MUST map 1:1 into runtime CAPEX for both the form
    path and the snapshot path. The Generic factory
    defaults populate these financial sub-fields
    (idc, bank_fees, etc.) with non-zero values that
    come from generic financial cost-of-debt
    modelling, NOT from the user's CAPEX input.

    The cleanest way to preserve the user's CAPEX
    intent is to zero these sub-fields. The runtime
    sculpt does not depend on them (it uses
    total_capex - epc_contract_other for sizing).
    """
    return dc_replace(
        proj,
        capex=dc_replace(
            proj.capex,
            idc_keur=0.0,
            commitment_fees_keur=0.0,
            bank_fees_keur=0.0,
            other_financial_keur=0.0,
            vat_costs_keur=0.0,
            reserve_accounts_keur=0.0,
        ),
    )


# R1: snapshot_key → CapexStructure CapexItem field name (14 editable scalars).
# Keys match registry binding_label="bound" fields in sections C and D.
# "contingencies" is formula-derived and excluded.
_SCALAR_CAPEX_MAP: dict[str, str] = {
    "capex_epc_contract_keur":        "epc_contract",
    "capex_production_units_keur":    "production_units",
    "capex_epc_other_keur":           "epc_other",
    "capex_grid_connection_keur":     "grid_connection",
    "capex_ops_prep_keur":            "ops_prep",
    "capex_insurances_keur":          "insurances",
    "capex_lease_tax_keur":           "lease_tax",
    "capex_construction_mgmt_a_keur": "construction_mgmt_a",
    "capex_commissioning_keur":       "commissioning",
    "capex_taxes_keur":               "taxes",
    "capex_project_acquisition_keur": "project_acquisition",
    "capex_project_rights_keur":      "project_rights",
    "capex_audit_legal_keur":         "audit_legal",
    "capex_construction_mgmt_b_keur": "construction_mgmt_b",
}


def _apply_scalar_capex(
    proj: "ProjectInputs",
    scalars: dict[str, float],
) -> "ProjectInputs":
    """Apply individual scalar CAPEX amounts from ``scalars`` (field_name → kEUR)
    onto ``proj.capex``, returning a new ProjectInputs.  Only keys present in
    ``scalars`` are overwritten; absent keys keep their current value.

    ``scalars`` is keyed by CapexStructure field name (e.g. "epc_contract"),
    NOT the snapshot key.  Values must already be floats.
    """
    new_capex = proj.capex
    for field_name, amount_keur in scalars.items():
        current_item = getattr(new_capex, field_name)
        new_item = dc_replace(current_item, amount_keur=float(amount_keur))
        new_capex = dc_replace(new_capex, **{field_name: new_item})
    return dc_replace(proj, capex=new_capex)


def _apply_capex_total(proj: "ProjectInputs", target: float) -> "ProjectInputs":
    """Scale the epc_contract to hit a user-supplied
    ``target`` total capex, preserving all other
    capex line items at their defaults.

    If the target is below the sum of the other
    capex line items, the epc_contract is clamped
    to 0.0 (the runtime then sees the factory
    other capex items as the effective CAPEX).
    """
    other_keur = sum(
        getattr(proj.capex, f.name).amount_keur
        for f in proj.capex.__dataclass_fields__.values()
        if f.name not in ("idc_keur", "commitment_fees_keur", "bank_fees_keur",
                          "other_financial_keur", "vat_costs_keur", "reserve_accounts_keur",
                          "vat_facility_idc_keur", "vat_facility_commitment_fee_keur",
                          "epc_contract")
        and hasattr(getattr(proj.capex, f.name), "amount_keur")
        and getattr(proj.capex, f.name).amount_keur > 0
    )
    epc_target = max(target - other_keur, 0.0)
    new_epc = dc_replace(proj.capex.epc_contract, amount_keur=epc_target)
    return dc_replace(proj, capex=dc_replace(proj.capex, epc_contract=new_epc))


def _resolve_user_inputs(
    *,
    project_type: str,
    project_name: str = None,
    project_code: str = None,
    country_iso: str = None,
    capacity_mw: float = None,
    cod_date: date = None,
    construction_months: int = None,
    horizon_years: int = None,
    tariff_eur_mwh: float = None,
    ppa_term_years: int = None,
    rev_ppa_index: float = None,
    rev_ppa_production_share: float = None,
    rev_ppa_indexation_start_policy: str = None,
    rev_ppa_indexation_start_date: str = None,
    rev_merchant_balancing_pct: float = None,
    rev_balancing_cost_eur_per_mwh: float = None,
    rev_co2_enabled: bool = None,
    rev_co2_price_eur_mwh: float = None,
    rev_merchant_price_curve_json: str = None,
    p50_hours: float = None,
    operating_hours_p90_10y: float = None,
    operating_hours_p99_1y: float = None,
    opex_y1_keur: float = None,
    total_capex_keur: float = None,
    # R1 — individual scalar CAPEX inputs (14 fields, section C + D).
    # When any key is present, scalars take authority over total_capex_keur.
    capex_epc_contract_keur: float = None,
    capex_production_units_keur: float = None,
    capex_epc_other_keur: float = None,
    capex_grid_connection_keur: float = None,
    capex_ops_prep_keur: float = None,
    capex_insurances_keur: float = None,
    capex_lease_tax_keur: float = None,
    capex_construction_mgmt_a_keur: float = None,
    capex_commissioning_keur: float = None,
    capex_taxes_keur: float = None,
    capex_project_acquisition_keur: float = None,
    capex_project_rights_keur: float = None,
    capex_audit_legal_keur: float = None,
    capex_construction_mgmt_b_keur: float = None,
    gearing_pct: float = None,
    interest_rate_pct: float = None,
    tenor_years: int = None,
    target_dscr: float = None,
    tax_corporate_rate_pct: float = None,
    tax_loss_carryforward_years: int = None,
    base_inputs: "ProjectInputs" = None,
) -> "ProjectInputs":
    """Phase S1: shared resolver. Both the form path and the
    snapshot path route through this function. Identical
    input values produce identical ProjectInputs
    regardless of which entry point was used.

    All parameters are optional. ``None`` means "use
    the factory default for the project type".

    The resolver:
    1. Starts from the Generic factory default (DSCR_SCULPT),
       or from ``base_inputs`` when provided (Stack R: project-
       specific seeded path for Generic Wind Reference / Generic Solar Reference templates).
    2. Applies identity / info overrides.
    3. Applies technical overrides.
    4. Applies revenue overrides.
    5. Zeros the financial capex sub-fields and scales
       the epc_contract to hit a user-supplied total.
       When ``base_inputs`` is provided, zeroing is skipped
       unless the caller also supplies ``total_capex_keur``,
       preserving the factory's calibrated IDC / bank-fee
       structure.
    6. Applies opex as a single user-supplied Y1 line (only
       when ``opex_y1_keur`` is not None).
    7. Applies financing overrides via the same
       _set_financing_* helpers used by the form path.
    """
    from app.project_factories import (
        create_default_solar_project,
        create_default_wind_project,
    )
    from domain.inputs import OpexItem, TechnicalParams

    if base_inputs is not None:
        proj: "ProjectInputs" = base_inputs
    else:
        factory_map = {
            "Solar": create_default_solar_project,
            "Wind": create_default_wind_project,
        }
        proj: "ProjectInputs" = factory_map[project_type]()

    # ── Identity / Info ──────────────────────────────────────
    if country_iso is not None or construction_months is not None or cod_date is not None or horizon_years is not None:
        new_country = country_iso if country_iso is not None else proj.info.country_iso
        new_construction_months = int(construction_months) if construction_months is not None else proj.info.construction_months
        new_cod_date = cod_date if cod_date is not None else proj.info.cod_date
        new_horizon_years = int(horizon_years) if horizon_years is not None else proj.info.horizon_years
        if cod_date is not None and construction_months is not None:
            new_financial_close = _subtract_months(cod_date, int(construction_months))
        else:
            new_financial_close = proj.info.financial_close
        new_name = project_name if project_name is not None else proj.info.name
        # Preserve pre-S1 code logic: prefer project_code
        # (often stored as `active_project` on snapshots)
        # over project_name; fall back to project_name,
        # then to factory default code.
        code_source = project_code or project_name or proj.info.code
        new_code = (
            code_source.strip().upper()
            .replace(" ", "_")
        )
        proj = dc_replace(
            proj,
            info=dc_replace(
                proj.info,
                name=new_name,
                code=new_code,
                country_iso=_country_iso(new_country) if country_iso is not None else proj.info.country_iso,
                financial_close=new_financial_close,
                construction_months=new_construction_months,
                cod_date=new_cod_date,
                horizon_years=new_horizon_years,
                period_frequency=proj.info.period_frequency,
            ),
        )

    # ── Technical ────────────────────────────────────────────
    if capacity_mw is not None or p50_hours is not None or operating_hours_p90_10y is not None or operating_hours_p99_1y is not None:
        new_cap = capacity_mw if capacity_mw is not None else proj.technical.capacity_mw
        new_p50 = p50_hours if p50_hours is not None else proj.technical.operating_hours_p50
        new_p90_10y = operating_hours_p90_10y if operating_hours_p90_10y is not None else (new_p50 * 0.9)
        new_p99_1y = operating_hours_p99_1y if operating_hours_p99_1y is not None else (new_p50 * 0.8)
        proj = dc_replace(
            proj,
            technical=TechnicalParams(
                capacity_mw=new_cap,
                yield_scenario=proj.technical.yield_scenario,
                operating_hours_p50=new_p50,
                operating_hours_p90_10y=new_p90_10y,
                operating_hours_p99_1y=new_p99_1y,
                pv_degradation=proj.technical.pv_degradation,
                plant_availability=proj.technical.plant_availability,
                grid_availability=proj.technical.grid_availability,
                bess_enabled=proj.technical.bess_enabled,
                bess=proj.technical.bess,
            ),
        )

    # ── Revenue ──────────────────────────────────────────────
    if tariff_eur_mwh is not None:
        proj = _set_revenue_tariff(proj, tariff_eur_mwh)
    if ppa_term_years is not None:
        proj = _set_revenue_ppa_term(proj, ppa_term_years)
    # Canonical V2 revenue fields (C2B2) — applied after legacy fields so canonical wins.
    if rev_ppa_index is not None:
        proj = _set_revenue_ppa_index(proj, rev_ppa_index)
    if rev_ppa_production_share is not None:
        proj = _set_revenue_ppa_production_share(proj, rev_ppa_production_share)
    if rev_ppa_indexation_start_policy is not None:
        proj = _set_revenue_ppa_indexation_policy(proj, rev_ppa_indexation_start_policy)
    if rev_ppa_indexation_start_date is not None:
        proj = _set_revenue_ppa_indexation_start_date(proj, rev_ppa_indexation_start_date)
    # Cross-field: CONTRACT_ANNIVERSARY requires a date at runtime.
    # Only enforce when policy was explicitly set (not inherited from factory).
    if rev_ppa_indexation_start_policy is not None:
        from app.revenue_input_validation import validate_revenue_ppa_cross_field
        validate_revenue_ppa_cross_field(
            ppa_indexation_start_policy=proj.revenue.ppa_indexation_start_policy,
            ppa_indexation_start_date=proj.revenue.ppa_indexation_start_date,
        )
    if rev_merchant_balancing_pct is not None:
        proj = _set_revenue_merchant_balancing_pct(proj, rev_merchant_balancing_pct)
    if rev_balancing_cost_eur_per_mwh is not None:
        proj = _set_revenue_balancing_eur_per_mwh(proj, rev_balancing_cost_eur_per_mwh)
    if rev_co2_enabled is not None:
        proj = _set_revenue_co2_enabled(proj, rev_co2_enabled)
    if rev_co2_price_eur_mwh is not None:
        proj = _set_revenue_co2_price_eur_mwh(proj, rev_co2_price_eur_mwh)
    if rev_merchant_price_curve_json is not None:
        proj = _set_revenue_merchant_price_curve_json(proj, rev_merchant_price_curve_json)

    # ── CAPEX (shared resolver) ──────────────────────────────
    # R1: collect scalar inputs supplied by the caller (14 individual fields).
    # When ANY scalar is present, they take authority — each named line is set
    # directly, giving the user per-component control.  total_capex_keur is used
    # only as a legacy fallback when NO scalar is supplied (backwards compat for
    # snapshots that only store the aggregate).
    _scalar_capex: dict[str, float] = {}
    for _snap_key, _field_name in _SCALAR_CAPEX_MAP.items():
        _local_val = locals().get(_snap_key)
        if _local_val is not None:
            _scalar_capex[_field_name] = float(_local_val)

    # When using a seeded base (Generic Wind Reference / Generic Solar Reference factory), only zero
    # financial sub-fields if the caller explicitly supplies a new
    # total_capex_keur, preserving calibrated IDC / bank-fee values.
    # V4-1: additionally skip restructuring when the supplied total
    # matches the factory total within 0.01 kEUR — preserves the
    # calibrated IDC / bank-fee sub-line breakdown and eliminates
    # UI vs factory CAPEX composition drift.
    if _scalar_capex:
        # R1 scalar authority order (Correction C):
        #
        # Establish the pre-edit effective CAPEX baseline, then apply scalars.
        # Do NOT re-force any aggregate after scalar edits — epc_contract must
        # epc_contract must not be re-forced after scalar edits.
        #
        # Two sub-cases for the baseline:
        #
        # A. Factory project (base_inputs is None):
        #    If total_capex_keur is present → _apply_capex_total sets epc to
        #    reproduce the effective CAPEX the user saw before the scalar edit.
        #
        # B. Seeded project (base_inputs is not None):
        #    The seeded factory is the default baseline.  But if a persisted
        #    total_capex_keur differs materially from the factory total, the
        #    project's pre-R1 effective CAPEX was already re-normalised to that
        #    legacy total (zero financial sub-fields + _apply_capex_total).
        #    We must reconstruct that SAME effective baseline before applying the
        #    scalar so untouched lines are not silently reverted to the pristine
        #    seeded factory values (Correction C: backward-compat migration).
        #
        # The financing-reset comparison is always vs the pre-edit effective
        # total (total_capex_keur when it diverged from factory, else factory).
        _pre_edit_total_for_reset: Optional[float] = None

        if total_capex_keur is not None:
            if base_inputs is None:
                # Case A: factory project — normalise from factory.
                proj = _apply_capex_total(proj, total_capex_keur)
                _pre_edit_total_for_reset = float(total_capex_keur)
            else:
                # Case B: seeded project — reconstruct pre-R1 effective state
                # only when the legacy total diverges from the seeded factory.
                _base_factory_total = getattr(base_inputs.capex, "total_capex", None)
                _legacy_matches_factory = (
                    _base_factory_total is not None
                    and abs(float(total_capex_keur) - float(_base_factory_total)) < 0.01
                )
                if not _legacy_matches_factory:
                    # The working copy's legacy aggregate diverged from the
                    # calibrated factory.  Reproduce the exact pre-edit
                    # effective state (zero financial sub-fields so IDC/fees
                    # from the factory do not inflate the total, then scale
                    # epc_contract to hit total_capex_keur).
                    proj = _zero_financial_capex_subfields(proj)
                    proj = _apply_capex_total(proj, total_capex_keur)
                    _pre_edit_total_for_reset = float(total_capex_keur)
                    # If the frozen schedule was still True, reset it now
                    # (same semantics as the no-scalar seeded divergence path).
                    if getattr(proj.financing, "use_frozen_excel_senior_debt_schedule", False):
                        proj = dc_replace(
                            proj,
                            financing=dc_replace(
                                proj.financing,
                                use_frozen_excel_senior_debt_schedule=False,
                                fixed_debt_keur=0.0,
                                shl_amount_keur=0.0,
                                shl_idc_keur=0.0,
                            ),
                        )

        # Apply scalar edits on top of the effective baseline.
        proj = _apply_scalar_capex(proj, _scalar_capex)

        # For seeded projects, determine whether the scalar edit represents a
        # material CAPEX change vs the pre-edit effective total.  A material
        # change disables the frozen debt schedule so the engine can re-size.
        if base_inputs is not None:
            _new_capex_total = getattr(proj.capex, "total_capex", None)
            # Compare against pre-edit effective total (legacy-normalised when
            # applicable, factory total otherwise).
            _compare_total = (
                _pre_edit_total_for_reset
                if _pre_edit_total_for_reset is not None
                else getattr(base_inputs.capex, "total_capex", None)
            )
            _scalar_capex_changed_materially = (
                _new_capex_total is not None
                and _compare_total is not None
                and abs(float(_new_capex_total) - float(_compare_total)) >= 0.01
            )
            if _scalar_capex_changed_materially and getattr(
                proj.financing, "use_frozen_excel_senior_debt_schedule", False
            ):
                proj = dc_replace(
                    proj,
                    financing=dc_replace(
                        proj.financing,
                        use_frozen_excel_senior_debt_schedule=False,
                        fixed_debt_keur=0.0,
                        shl_amount_keur=0.0,
                        shl_idc_keur=0.0,
                    ),
                )
    elif base_inputs is not None:
        if total_capex_keur is not None:
            _base_capex_total = getattr(base_inputs.capex, "total_capex", None)
            _capex_matches_base = (
                _base_capex_total is not None
                and abs(float(total_capex_keur) - float(_base_capex_total)) < 0.01
            )
            if not _capex_matches_base:
                proj = _zero_financial_capex_subfields(proj)
                proj = _apply_capex_total(proj, total_capex_keur)
                # Frozen debt schedule and SHL were calibrated for the
                # original capex; disable frozen schedule and zero SHL
                # when the user supplies a different capex total, so the
                # engine can size debt from gearing/DSCR inputs instead.
                if getattr(proj.financing, "use_frozen_excel_senior_debt_schedule", False):
                    proj = dc_replace(
                        proj,
                        financing=dc_replace(
                            proj.financing,
                            use_frozen_excel_senior_debt_schedule=False,
                            fixed_debt_keur=0.0,
                            shl_amount_keur=0.0,
                            shl_idc_keur=0.0,
                        ),
                    )
    else:
        proj = _zero_financial_capex_subfields(proj)
        if total_capex_keur is not None:
            proj = _apply_capex_total(proj, total_capex_keur)

    # ── OPEX (single user-supplied Y1 line) ──────────────────
    # V4-1: when a seeded base is provided, skip the single-item
    # replacement when the supplied Y1 total matches the factory
    # sum within 0.01 kEUR. This preserves the factory's calibrated
    # per-item inflation schedule and eliminates UI vs factory drift.
    if opex_y1_keur is not None:
        _skip_opex_replace = False
        if base_inputs is not None:
            _base_opex_y1 = sum(
                getattr(item, "y1_amount_keur", 0.0) for item in base_inputs.opex
            )
            _skip_opex_replace = abs(float(opex_y1_keur) - _base_opex_y1) < 0.01
        if not _skip_opex_replace:
            proj = dc_replace(
                proj,
                opex=(
                    OpexItem(
                        name="User provided year 1 operating expense",
                        y1_amount_keur=float(opex_y1_keur),
                        annual_inflation=0.02,
                    ),
                ),
            )

    # ── Tax ──────────────────────────────────────────────────
    # Registry stores CIT rate as % (0–100); absent key means inherit factory/template default.
    if tax_corporate_rate_pct is not None:
        proj = _set_tax_corporate_rate(proj, tax_corporate_rate_pct)
    if tax_loss_carryforward_years is not None:
        proj = _set_tax_loss_carryforward_years(proj, tax_loss_carryforward_years)

    # ── Financing (DSCR sculpt semantics) ────────────────────
    if gearing_pct is not None:
        proj = _set_financing_gearing(proj, gearing_pct)
    if interest_rate_pct is not None:
        # V4-1: when using a seeded base, skip the interest-rate override if
        # the supplied value matches the factory all-in rate within 0.1 bps.
        # _set_financing_interest_rate expects a percentage (5.75 for 5.75%)
        # but the form path sends a decimal (0.0575) — this dual-format check
        # handles both without altering the existing percentage contract.
        _skip_rate = False
        if base_inputs is not None:
            _base_all_in = (
                base_inputs.financing.base_rate
                + base_inputs.financing.margin_bps / 10_000
            )
            _v = float(interest_rate_pct)
            # Accept either percentage (5.75) or decimal (0.0575) form
            _skip_rate = (
                abs(_v - _base_all_in) < 0.00001
                or abs(_v / 100.0 - _base_all_in) < 0.00001
            )
        if not _skip_rate:
            proj = _set_financing_interest_rate(proj, interest_rate_pct)
    if tenor_years is not None:
        proj = _set_financing_tenor(proj, tenor_years)
    if target_dscr is not None:
        proj = _set_financing_target_dscr(proj, target_dscr)

    # Generic SHL policy: recompute CASH_SWEEP indices from FINAL effective
    # ProjectInputs AFTER all user overrides. Only for generic Solar/Wind;
    # named projects (base_inputs is not None) keep their own SHL policy.
    if base_inputs is None and project_type in {"Solar", "Wind"}:
        from app.generic_shl_policy import resolve_generic_shl_policy
        proj = resolve_generic_shl_policy(proj)

    return proj


def _schema_to_dict(schema: ProjectInputsSchema) -> dict:
    """Flatten a ProjectInputsSchema to a dict of optional
    input values, suitable for _resolve_user_inputs.

    None values mean "use factory default".

    Phase S1: the form path and the snapshot path route
    through this dict and the shared resolver. The form
    path can now pass every input field the snapshot
    path accepts (Phase S1 schema expansion).
    """
    from datetime import date as _date
    cod_date = None
    if schema.cod_date is not None:
        try:
            cod_date = _date.fromisoformat(schema.cod_date)
        except ValueError:
            cod_date = None
    return {
        "project_type": schema.project_type,
        "project_name": schema.project_name,
        "country_iso": schema.country_iso,
        "capacity_mw": schema.capacity_mw,
        "cod_date": cod_date,
        "construction_months": schema.construction_months,
        "horizon_years": schema.horizon_years,
        "tariff_eur_mwh": (
            schema.revenue.tariff_eur_mwh if schema.revenue else None
        ),
        "ppa_term_years": (
            schema.revenue.ppa_term_years if schema.revenue else None
        ),
        "p50_hours": (
            schema.revenue.p50_hours if schema.revenue else None
        ),
        "operating_hours_p90_10y": schema.operating_hours_p90_10y,
        "operating_hours_p99_1y": schema.operating_hours_p99_1y,
        "opex_y1_keur": (
            schema.opex.opex_y1_keur if schema.opex else None
        ),
        "total_capex_keur": (
            schema.capex.total_capex_keur if schema.capex else None
        ),
        "gearing_pct": (
            schema.debt.gearing_pct if schema.debt else None
        ),
        "interest_rate_pct": (
            schema.debt.interest_rate_pct if schema.debt else None
        ),
        "tenor_years": (
            schema.debt.tenor_years if schema.debt else None
        ),
        "target_dscr": (
            schema.debt.target_dscr if schema.debt else None
        ),
        "tax_corporate_rate_pct": (
            schema.tax.cit_rate_pct if schema.tax else None
        ),
        "tax_loss_carryforward_years": (
            schema.tax.loss_carryforward_years if schema.tax else None
        ),
    }


def _snapshot_to_dict(snapshot: dict) -> dict:
    """Convert a saved user-project snapshot dict to the
    same shape as _schema_to_dict. Required fields are
    validated by build_projectinputs_from_snapshot before
    this function is called.

    C2B2: canonical rev_* keys win over legacy keys when both present.
    """
    # Canonical key wins over legacy when both present (C2B2).
    # Strict: non-empty invalid values raise SnapshotInputError; absent/empty → None (use legacy).
    _canonical_tariff = _snapshot_float_strict(snapshot, "rev_ppa_base_tariff", non_negative=True)
    _legacy_tariff = _snapshot_float(snapshot, "tariff_eur_mwh", non_negative=True)

    _canonical_ppa_term = _snapshot_float_strict(
        snapshot, "rev_ppa_term_years", min_value=1, max_value=50
    )
    _legacy_ppa_term = _snapshot_int(snapshot, "ppa_term_years", positive=True)

    return {
        "project_type": _snapshot_text(snapshot, "project_type").title(),
        "project_name": _snapshot_text(snapshot, "project_name"),
        # Optional project_code (often stored as
        # `active_project` on saved snapshots). When
        # present, the resolver prefers it as info.code
        # over project_name (matches pre-S1 behavior).
        "project_code": (
            snapshot.get("active_project")
            or snapshot.get("project_code")
        ),
        "country_iso": _snapshot_text(snapshot, "country_market"),
        "capacity_mw": _snapshot_float(snapshot, "capacity_mw", positive=True),
        "cod_date": _snapshot_date(snapshot, "cod_date"),
        "construction_months": _snapshot_int(
            snapshot, "construction_months", positive=True
        ),
        "horizon_years": _snapshot_int(
            snapshot, "horizon_years", positive=True
        ),
        # Canonical rev_ppa_base_tariff wins over legacy tariff_eur_mwh.
        "tariff_eur_mwh": _canonical_tariff if _canonical_tariff is not None else _legacy_tariff,
        # Canonical rev_ppa_term_years wins over legacy ppa_term_years.
        "ppa_term_years": int(_canonical_ppa_term) if _canonical_ppa_term is not None else _legacy_ppa_term,
        "p50_hours": _snapshot_float(
            snapshot, "p50_hours", positive=True
        ),
        "operating_hours_p90_10y": None,
        "operating_hours_p99_1y": None,
        "opex_y1_keur": _snapshot_float(
            snapshot, "opex_y1_keur", non_negative=True
        ),
        "total_capex_keur": _snapshot_float(
            snapshot, "total_capex_keur", positive=True
        ),
        # R1 — individual scalar CAPEX snapshot keys (14 fields).
        # Present values override total_capex_keur (scalar authority).
        # Absent / zero → None (legacy total fallback or factory default).
        **{
            snap_key: (
                _snapshot_float(snapshot, snap_key, non_negative=True)
                if str(snapshot.get(snap_key, "") or "").strip()
                else None
            )
            for snap_key in _SCALAR_CAPEX_MAP
        },
        # gearing_pct is optional: empty/absent means use the template default.
        "gearing_pct": (
            _snapshot_float(snapshot, "gearing_pct", non_negative=True)
            if str(snapshot.get("gearing_pct", "") or "").strip()
            else None
        ),
        # R8/N02 unit contract: the V2 pipeline persists interest_rate_pct as
        # PERCENT (9.00 == 9 %); _set_financing_interest_rate converts to a
        # ratio exactly once (the single conversion boundary).  The legacy
        # ×100 here double-converted V2 percent values into e.g. 900 % /
        # 89,700 bps margins (Astra N02).  No magnitude heuristic: the
        # registry bounds (0–20 %) and the typed schedule authority govern.
        "interest_rate_pct": _snapshot_float(
            snapshot, "interest_rate_pct", non_negative=True
        ),
        "tenor_years": _snapshot_int(
            snapshot, "tenor_years", positive=True
        ),
        "target_dscr": _snapshot_float(
            snapshot, "target_dscr", positive=True
        ),
        # Tax snapshot keys — optional; absent means inherit factory/template TaxParams.
        "tax_corporate_rate_pct": (
            _snapshot_float(snapshot, "tax_corporate_rate_pct", non_negative=True)
            if str(snapshot.get("tax_corporate_rate_pct", "") or "").strip()
            else None
        ),
        "tax_loss_carryforward_years": (
            _snapshot_int(snapshot, "tax_loss_carryforward_years")
            if str(snapshot.get("tax_loss_carryforward_years", "") or "").strip()
            else None
        ),
        # C2B2/C2B3 canonical revenue fields — optional; absent/empty → inherit factory.
        # Non-empty invalid values raise SnapshotInputError (strict helpers).
        "rev_ppa_index": _snapshot_float_strict(snapshot, "rev_ppa_index", non_negative=True, max_value=100.0),
        "rev_ppa_production_share": _snapshot_float_strict(snapshot, "rev_ppa_production_share", non_negative=True, max_value=100.0),
        "rev_ppa_indexation_start_policy": _snapshot_str_opt(snapshot, "rev_ppa_indexation_start_policy"),
        "rev_ppa_indexation_start_date": _snapshot_str_opt(snapshot, "rev_ppa_indexation_start_date"),
        "rev_merchant_balancing_pct": _snapshot_float_strict(snapshot, "rev_merchant_balancing_pct", non_negative=True, max_value=100.0),
        "rev_balancing_cost_eur_per_mwh": _snapshot_float_strict(snapshot, "rev_balancing_cost_eur_per_mwh", non_negative=True),
        "rev_co2_enabled": _snapshot_bool_strict(snapshot, "rev_co2_enabled"),
        "rev_co2_price_eur_mwh": _snapshot_float_strict(snapshot, "rev_co2_price_eur_mwh", non_negative=True),
        "rev_merchant_price_curve_json": _snapshot_str_opt(snapshot, "rev_merchant_price_curve_json"),
    }


def build_projectinputs(schema: ProjectInputsSchema) -> "ProjectInputs":
    """Build a domain ProjectInputs from a ProjectInputsSchema.

    Phase S1: this is a clean thin wrapper around the
    shared _resolve_user_inputs resolver. The schema
    is first flattened to a dict of optional values
    via _schema_to_dict, then the resolver applies
    them to the factory default. Both
    build_projectinputs(schema) and
    build_projectinputs_from_snapshot(snapshot) route
    through this resolver, so identical Generic user
    inputs produce exactly equal ProjectInputs and
    exactly equal KPIs.
    """
    return _resolve_user_inputs(**_schema_to_dict(schema))


def build_projectinputs_seeded(
    schema: ProjectInputsSchema,
    base_inputs: "ProjectInputs",
) -> "ProjectInputs":
    """Stack R: build ProjectInputs using a project-specific factory base.

    Identical to build_projectinputs except it starts from
    ``base_inputs`` (e.g. create_generic_wind_reference() or
    create_generic_solar_reference()) rather than the generic Wind/Solar
    factory.  Only the scalar fields present in the schema are
    applied on top; all calibrated configuration on base_inputs
    (SHL mechanics, equity_irr_method, merchant curve, tax params,
    frozen DS schedule, etc.) is preserved unless the user
    explicitly overrides it via the schema.
    """
    return _resolve_user_inputs(base_inputs=base_inputs, **_schema_to_dict(schema))


REQUIRED_USER_PROJECT_SNAPSHOT_FIELDS = (
    "project_name",
    "project_type",
    "country_market",
    "capacity_mw",
    "cod_date",
    "construction_months",
    "horizon_years",
    "tariff_eur_mwh",
    "ppa_term_years",
    "p50_hours",
    "opex_y1_keur",
    "total_capex_keur",
    "gearing_pct",
    "interest_rate_pct",
    "tenor_years",
    "target_dscr",
)


def _snapshot_float_opt(snapshot: dict, key: str, *, non_negative: bool = False) -> "float | None":
    """Read an optional float from a snapshot — returns None when absent or non-numeric."""
    raw = snapshot.get(key)
    if raw is None or str(raw).strip() == "":
        return None
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None
    if non_negative and value < 0:
        return None
    return value


def _snapshot_float_strict(
    snapshot: dict,
    key: str,
    *,
    non_negative: bool = False,
    min_value: float | None = None,
    max_value: float | None = None,
) -> "float | None":
    """Read an optional float from a snapshot — strict version.

    Unlike _snapshot_float_opt, raises SnapshotInputError when a non-empty value
    is present but cannot be parsed or violates range constraints.
    Returns None only when the key is absent or empty.
    """
    raw = snapshot.get(key)
    if raw is None or str(raw).strip() == "":
        return None
    try:
        value = float(raw)
    except (TypeError, ValueError) as exc:
        raise SnapshotInputError(f"{key}: invalid numeric value {raw!r}") from exc
    if non_negative and value < 0:
        raise SnapshotInputError(f"{key}: value must be non-negative, got {value}")
    if min_value is not None and value < min_value:
        raise SnapshotInputError(f"{key}: value must be ≥ {min_value}, got {value}")
    if max_value is not None and value > max_value:
        raise SnapshotInputError(f"{key}: value must be ≤ {max_value}, got {value}")
    return value


def _snapshot_bool_strict(snapshot: dict, key: str) -> "bool | None":
    """Read an optional bool from a snapshot — strict version.

    Raises SnapshotInputError when a non-empty value is present but cannot be
    interpreted as a boolean.  Returns None only when the key is absent or empty.
    """
    raw = snapshot.get(key)
    if raw is None or str(raw).strip() == "":
        return None
    if isinstance(raw, bool):
        return raw
    s = str(raw).strip().lower()
    if s in ("true", "1", "yes"):
        return True
    if s in ("false", "0", "no"):
        return False
    raise SnapshotInputError(f"{key}: invalid boolean value {raw!r}; expected true/false")


def _snapshot_bool_opt(snapshot: dict, key: str) -> "bool | None":
    """Read an optional bool from a snapshot — returns None when absent."""
    raw = snapshot.get(key)
    if raw is None or str(raw).strip() == "":
        return None
    if isinstance(raw, bool):
        return raw
    return str(raw).strip().lower() in ("true", "1", "yes")


def _snapshot_str_opt(snapshot: dict, key: str) -> "str | None":
    """Read an optional string from a snapshot — returns None when absent or empty."""
    raw = snapshot.get(key)
    if raw is None or str(raw).strip() == "":
        return None
    return str(raw).strip()


def _snapshot_text(snapshot: dict, key: str) -> str:
    value = snapshot.get(key)
    if value is None or str(value).strip() == "":
        raise SnapshotInputError(f"{key} is required for user-created project runtime")
    return str(value).strip()


def _snapshot_float(
    snapshot: dict,
    key: str,
    *,
    positive: bool = False,
    non_negative: bool = False,
) -> float:
    raw = _snapshot_text(snapshot, key)
    try:
        value = float(raw)
    except (TypeError, ValueError) as exc:
        raise SnapshotInputError(f"{key} must be numeric for user-created project runtime") from exc
    if positive and value <= 0:
        raise SnapshotInputError(f"{key} must be greater than zero for user-created project runtime")
    if non_negative and value < 0:
        raise SnapshotInputError(f"{key} must be zero or greater for user-created project runtime")
    return value


def _snapshot_int(snapshot: dict, key: str, *, positive: bool = False) -> int:
    value = _snapshot_float(snapshot, key, positive=positive)
    if int(value) != value:
        raise SnapshotInputError(f"{key} must be a whole number for user-created project runtime")
    return int(value)


def _snapshot_date(snapshot: dict, key: str) -> date:
    raw = _snapshot_text(snapshot, key)
    try:
        return date.fromisoformat(raw)
    except ValueError as exc:
        raise SnapshotInputError(f"{key} must be an ISO date for user-created project runtime") from exc


def _subtract_months(value: date, months: int) -> date:
    month_index = value.month - months
    year = value.year + (month_index - 1) // 12
    month = (month_index - 1) % 12 + 1
    day = min(value.day, monthrange(year, month)[1])
    return date(year, month, day)


def _country_iso(value: str) -> str:
    normalized = value.strip()
    if normalized.lower() in {"generic_market_a", "hr", "hrv", "generic_market_a"}:
        return "XA"
    return normalized.upper()[:2] or "XA"


def build_projectinputs_from_snapshot(snapshot: dict) -> "ProjectInputs":
    """Build runtime inputs for a user-created project from saved assumptions.

    Phase S1: this is a clean thin wrapper around the
    shared _resolve_user_inputs resolver (same as
    build_projectinputs). The snapshot is first
    validated for required fields, then flattened via
    _snapshot_to_dict, then the resolver applies the
    values to the Generic factory default.

    Both build_projectinputs(schema) and
    build_projectinputs_from_snapshot(snapshot) route
    through _resolve_user_inputs, so identical Generic
    user inputs produce exactly equal ProjectInputs
    and exactly equal KPIs.
    """
    # Validate required fields (preserve SnapshotInputError
    # behavior).  gearing_pct is excluded from the "must be non-empty"
    # check because the engine handles None gearing gracefully (DSCR-
    # sculpted debt sizing).  An empty-string gearing is treated as
    # "not overriding the template default" rather than an error.
    _OPTIONAL_EMPTY = frozenset({"gearing_pct"})
    missing = [
        key for key in REQUIRED_USER_PROJECT_SNAPSHOT_FIELDS
        if key not in _OPTIONAL_EMPTY
        and (snapshot.get(key) is None or str(snapshot.get(key)).strip() == "")
    ]
    if missing:
        raise SnapshotInputError(
            "Missing required user-created project runtime fields: "
            + ", ".join(missing)
        )

    # Validate gearing_pct range only when it is present (it is optional;
    # empty string means "use template default", not an error).
    _gearing_str = str(snapshot.get("gearing_pct", "") or "").strip()
    if _gearing_str:
        gearing_raw = _snapshot_float(snapshot, "gearing_pct", non_negative=True)
        if gearing_raw > 100:
            raise SnapshotInputError(
                "gearing_pct must be between 0 and 100 for user-created project runtime"
            )

    # Validate project_type is Solar or Wind (preserved
    # behavior).
    project_type = _snapshot_text(snapshot, "project_type").title()
    if project_type not in {"Solar", "Wind"}:
        raise SnapshotInputError(
            "project_type must be Solar or Wind for user-created project runtime"
        )

    # V4-1: use the project-specific factory base for Generic Wind Reference / Generic Solar Reference
    # snapshots so that saved-state runs preserve calibrated configuration
    # (SHL mechanics, merchant curve, tax params, etc.) — same as the
    # template-seeded fresh-run path (Stack R). Generic templates fall
    # through to the generic Wind/Solar factory (base_inputs=None).
    _template_source = str(snapshot.get("template_source") or "").lower()
    if _template_source == "generic_wind_reference":
        from app.project_factories import create_generic_wind_reference as _tf
        _base = _tf()
    elif _template_source == "generic_solar_reference":
        from app.project_factories import create_generic_solar_reference as _of
        _base = _of()
    else:
        _base = None

    # Delegate to the shared resolver. _snapshot_to_dict
    # applies the snapshot field validation (positive,
    # non_negative, ISO date, whole-number int) for the
    # remaining fields.
    result = _resolve_user_inputs(base_inputs=_base, **_snapshot_to_dict(snapshot))

    # Per-line OPEX fold: apply B.01–B.12 scalar overrides from the snapshot onto
    # the calibrated base item tuple, preserving step_changes, annual_inflation, etc.
    # Precedence: Generic Wind Reference/Generic Solar Reference → use _base.opex (project-specific calibrated items).
    #             generic → recreate the factory to get the correct name set, then fold.
    # B.13 (Contingencies, derived) and B.09 (Fees, no scalar) are always skipped.
    from app.v2.opex_assembly import has_per_line_overrides, build_effective_draft_opex
    if has_per_line_overrides(snapshot):
        if _base is not None:
            _base_opex = _base.opex
        else:
            # Generic project: recreate the appropriate factory to get named OpexItems.
            # This is the only place a generic factory is recreated for OPEX base resolution.
            if project_type == "Solar":
                from app.project_factories import create_default_solar_project as _gsf
                _base_opex = _gsf().opex
            else:
                from app.project_factories import create_default_wind_project as _gwf
                _base_opex = _gwf().opex
        _effective_opex = build_effective_draft_opex(_base_opex, snapshot)
        if _effective_opex is not _base_opex:
            import dataclasses as _dc
            result = _dc.replace(result, opex=_effective_opex)

    return result


