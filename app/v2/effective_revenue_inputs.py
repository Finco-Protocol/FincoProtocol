"""SC-06: the revenue inputs the NEXT Run will actually use, with where each value comes from.

Presentation only. It reads the already-resolved ``ProjectInputs`` that a Run would be built from (the same ``pis.to_projectinputs()`` the model
uses), plus the persisted snapshot keys, so a value that comes from a saved legacy key or a project-template default is shown as such instead of
as an empty field. It performs no revenue arithmetic, never writes, and never invents an override: a number appears only when the engine
inputs carry it.
"""
from __future__ import annotations

from typing import Any, Mapping

_RUN_NOTE = "A change takes effect only after Save and a new Run; the Last Run keeps the values it was computed with."


def _num(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _row(key: str, label: str, value: float | None, unit: str, source: str, detail: str, editable: str) -> dict:
    return {"key": key, "label": label, "value": value, "unit": unit, "source": source, "detail": detail, "editable": editable, "run_note": _RUN_NOTE}


def build_effective_revenue_inputs(pis: Any, *, contracts_active: bool = False) -> tuple[dict, ...]:
    try:
        snapshot: Mapping[str, str] = pis.to_snapshot()
        revenue = pis.to_projectinputs().revenue
    except Exception:           # display helper: an unavailable resolution shows nothing rather than a guess
        return ()
    rows: list[dict] = []

    # --- contracted tariff -------------------------------------------------------------------------------------------------------------------
    if contracts_active:
        rows.append(_row("tariff", "PPA base tariff", None, "EUR/MWh", "Not used",
                         "Explicit revenue contracts are active, so each contract sets its own price.",
                         "Edit prices in the contract table."))
    else:
        tariff = _num(getattr(revenue, "ppa_base_tariff", None))
        if _num(snapshot.get("rev_ppa_base_tariff")) is not None:
            source, detail = "Saved input", "Saved on this Working Copy."
        elif _num(snapshot.get("tariff_eur_mwh")) is not None:
            source = "Saved legacy tariff key"
            detail = ("This Working Copy stores the tariff under an older key, so the PPA base tariff field above can look empty. "
                      "The model uses the saved value shown here.")
        else:
            source, detail = "Project template default", "No tariff has been saved; the project template supplies this value."
        rows.append(_row("tariff", "PPA base tariff", tariff, "EUR/MWh", source, detail,
                         "Editable in 1. Contracted Revenue (PPA base tariff)."))

    # --- balancing deduction (EUR/MWh on total generation) -----------------------------------------------------------------------------------
    schedule = getattr(revenue, "balancing_cost_schedule", None)
    explicit = _num(getattr(revenue, "balancing_cost_eur_per_mwh", 0.0)) or 0.0
    template = _num(getattr(revenue, "balancing_cost_wind_eur_mwh", 0.0)) or 0.0
    entered_balancing = _num(snapshot.get("rev_balancing_cost_eur_per_mwh"))
    meaning = "Deducted for every MWh generated: net revenue = gross revenue - balancing deduction."
    if schedule is not None:
        rows.append(_row("balancing", "Balancing deduction", None, "EUR/MWh", "Explicit schedule",
                         "A per-period schedule overrides the flat values. " + meaning, "Edit the schedule input."))
    elif explicit != 0.0:
        rows.append(_row("balancing", "Balancing deduction", explicit, "EUR/MWh", "Saved input",
                         "The Balancing Cost (EUR/MWh) field is set and replaces the template value. " + meaning,
                         "Editable in 2. Merchant Adjustments (Balancing Cost)."))
    elif template != 0.0:
        if entered_balancing == 0.0:
            detail = ("The saved Balancing Cost is explicitly 0 EUR/MWh. Under the existing model's zero-value fallback, "
                      f"the template deduction applies at {template:g} EUR/MWh. ")
        else:
            detail = "No Balancing Cost (EUR/MWh) has been saved, so the template deduction applies. "
        rows.append(_row("balancing", "Balancing deduction", template, "EUR/MWh", "Project template default (not an entered value)",
                         detail +
                         "Enter a non-zero value there to replace it; 0 does not switch the template value off. " + meaning,
                         "Editable in 2. Merchant Adjustments (Balancing Cost)."))
    else:
        detail = "The saved Balancing Cost is explicitly 0 EUR/MWh. " if entered_balancing == 0.0 else ""
        rows.append(_row("balancing", "Balancing deduction", 0.0, "EUR/MWh", "No deduction",
                         detail + "No flat per-MWh balancing deduction applies to this project.", "Editable in 2. Merchant Adjustments (Balancing Cost)."))

    merchant_fraction = _num(getattr(revenue, "balancing_cost_pv", 0.0)) or 0.0
    if merchant_fraction != 0.0:
        rows.append(_row("merchant_balancing", "Merchant balancing", round(merchant_fraction * 100, 6), "% of spot sales",
                         "Saved input", "Deducted from merchant (spot) electricity revenue only, not from contracted PPA revenue.",
                         "Editable in 2. Merchant Adjustments."))
    return tuple(rows)


def effective_pricing_fallbacks(pis: Any) -> dict:
    """Resolved values for the Revenue Pricing Basis summary when the matching input field is empty (display only; no field is written)."""
    try:
        revenue = pis.to_projectinputs().revenue
    except Exception:
        return {}
    out = {}
    tariff = _num(getattr(revenue, "ppa_base_tariff", None))
    term = _num(getattr(revenue, "ppa_term_years", None))
    index = _num(getattr(revenue, "ppa_index", None))
    if tariff is not None:
        out["tariff"] = tariff
    if term is not None:
        out["term"] = term
    if index is not None:
        out["escalation"] = round(index * 100, 6)
    return out
