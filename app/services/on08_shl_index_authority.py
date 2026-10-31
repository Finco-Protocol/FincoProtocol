"""ON-08 OD-1(A): geometry authority for the two generic-SHL period indices on a qualifying Working Copy.

A Solar/Wind Working Copy seeded from the canonical factory reference carries the REFERENCE's
``shl_maturity_period_index`` / ``shl_principal_eligibility_start_period`` (computed for the reference
construction/horizon/tenor).  Editing construction months, horizon or senior tenor moves the real period grid
but not these two stored indices, so a Run is either refused (``SHL_MATURITY_NOT_ON_PERIOD_GRID_FAILS_CLOSED``)
or, worse, committed against a silently wrong SHL maturity/eligibility.

This module re-derives exactly those two indices from the FINAL effective inputs, and only for a project whose
persisted lineage and SHL terms prove it is an unmodified factory-generic SHL.  It deliberately does NOT call
``resolve_generic_shl_policy`` (that also forces CASH_SWEEP): the repayment method and every other input are preserved.

Pure and I/O-free: the caller resolves the persisted facts (project row, canonical reference row, factory reference
inputs, actual grid end) and passes them in.  Nothing here reads form fields or the editable workspace snapshot.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, replace as _replace
from typing import Any, Callable

REFERENCE_OWNER = "__reference__"
_TECH_TO_TEMPLATE = {"Solar": "generic_solar_reference", "Wind": "generic_wind_reference"}
# Exact, case-sensitive frequency labels.  Anything else (incl. Quarterly) is NOT defaulted to semestrial.
_PERIODS_PER_YEAR = {"Annual": 1, "Semestrial": 2}
# SHL terms that must equal the factory reference for the SHL to count as "factory generic" (indices are checked separately).
_SHL_TERM_FIELDS = ("clean_shl_repayment_method", "shl_rate", "shl_day_count_convention", "shl_construction_day_count_fraction")

NOT_ELIGIBLE, UNCHANGED, CORRECTED = "NOT_ELIGIBLE", "UNCHANGED", "CORRECTED"


class On08ShlIndexRefusal(ValueError):
    """A typed, fail-closed refusal raised BEFORE fingerprinting, reservation, calculation or commit."""

    def __init__(self, code: str, message: str):
        super().__init__(f"{code}: {message}")
        self.code = code


@dataclass(frozen=True)
class ShlIndexOutcome:
    status: str                      # NOT_ELIGIBLE | UNCHANGED | CORRECTED
    reason: str = ""
    before: tuple | None = None      # (maturity, eligibility) as stored
    after: tuple | None = None       # (maturity, eligibility) as used


def _integral(value: Any, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or float(value) != int(value):
        raise On08ShlIndexRefusal("ON08_SHL_NON_INTEGRAL_TERM", f"{name}={value!r} is not a finite whole number")
    return int(value)


def geometry_indices(*, construction_months: Any, horizon_years: Any, senior_tenor_years: Any, period_frequency: str) -> tuple[int, int]:
    """(maturity, eligibility) per the approved OD-1(A) contract, from effective values and the real period geometry."""
    ppy = _PERIODS_PER_YEAR.get(period_frequency)
    if ppy is None:
        raise On08ShlIndexRefusal("ON08_SHL_UNSUPPORTED_FREQUENCY", f"period frequency {period_frequency!r} is not Annual or Semestrial")
    months_per_period = 12 // ppy
    cm = _integral(construction_months, "construction_months")
    hy = _integral(horizon_years, "horizon_years")
    st = _integral(senior_tenor_years, "senior_tenor_years")
    construction_periods = (cm + months_per_period - 1) // months_per_period
    return construction_periods + hy * ppy - 1, construction_periods + st * ppy


def _value(x: Any) -> Any:
    return getattr(x, "value", x)


def _lineage_proven(project_record: Any, *, actor_user_id: str, owner_user_id: str, runtime_project_key: str,
                    canonical_reference: Any) -> str:
    """'' when the persisted project is an eligible factory-generic Working Copy, else the reason it is not."""
    g = lambda name: getattr(project_record, name, None)
    template = _TECH_TO_TEMPLATE.get(runtime_project_key)
    if template is None:
        return "technology not Solar/Wind"
    if not actor_user_id or g("user_id") != actor_user_id or owner_user_id != actor_user_id:
        return "actor is not the owner"
    if g("project_role") != "working_copy" or g("project_origin") != "user_created":
        return "not a user-created working copy"
    if g("is_protected") or g("archived") or g("is_readonly"):
        return "protected, archived or readonly"
    if (g("project_type") or "").strip().lower() != runtime_project_key.lower() or g("template_source") != template:
        return "persisted technology/template disagree"
    if not g("source_project_id") or canonical_reference is None:
        return "no canonical source lineage"
    ref = canonical_reference
    if (getattr(ref, "user_id", None) != REFERENCE_OWNER or getattr(ref, "project_role", None) != "reference"
            or not getattr(ref, "is_protected", False) or getattr(ref, "archived", True)
            or getattr(ref, "template_source", None) != template
            or getattr(ref, "project_id", None) != g("source_project_id")):
        return "source is not the current canonical factory reference"
    return ""


def apply_generic_shl_index_authority(
    override: Any, *, project_record: Any, actor_user_id: str, owner_user_id: str, runtime_project_key: str,
    canonical_reference: Any, factory_reference_inputs: Any, grid_last_provider: "Callable[[Any], int] | None",
) -> tuple[Any, ShlIndexOutcome]:
    """Return (inputs, outcome).  Only the two index fields may differ from ``override``; the object is returned
    unchanged (same identity) when the project is not eligible or the stored indices already equal the geometry."""
    why = _lineage_proven(project_record, actor_user_id=actor_user_id, owner_user_id=owner_user_id,
                          runtime_project_key=runtime_project_key, canonical_reference=canonical_reference)
    if why:
        return override, ShlIndexOutcome(NOT_ELIGIBLE, why)
    fin, ref_fin = override.financing, factory_reference_inputs.financing
    if any(_value(getattr(fin, f, None)) != _value(getattr(ref_fin, f, None)) for f in _SHL_TERM_FIELDS):
        return override, ShlIndexOutcome(NOT_ELIGIBLE, "SHL terms differ from the factory generic SHL")
    stored = (fin.shl_maturity_period_index, fin.shl_principal_eligibility_start_period)
    ref_ind = (ref_fin.shl_maturity_period_index, ref_fin.shl_principal_eligibility_start_period)
    ref_info = factory_reference_inputs.info
    ref_expected = geometry_indices(
        construction_months=ref_info.construction_months, horizon_years=ref_info.horizon_years,
        senior_tenor_years=ref_fin.senior_tenor_years, period_frequency=_value(ref_info.period_frequency))
    if ref_ind != ref_expected:
        return override, ShlIndexOutcome(NOT_ELIGIBLE, "factory reference indices are not geometry-derived")
    if stored != ref_ind:
        # A custom or historical index is unreviewed lineage: never overwritten.
        return override, ShlIndexOutcome(NOT_ELIGIBLE, "stored SHL indices differ from the factory reference (custom/unreviewed)")

    info = override.info
    maturity, eligibility = geometry_indices(
        construction_months=info.construction_months, horizon_years=info.horizon_years,
        senior_tenor_years=fin.senior_tenor_years, period_frequency=_value(info.period_frequency))
    if maturity < eligibility:
        # Horizon not longer than the senior tenor: nothing is rewritten and nothing is refused here, so the existing downstream refusal and its
        # precise explanation (run_failure_explanation: "horizon is not longer than the senior debt tenor") apply exactly as before.
        return override, ShlIndexOutcome(NOT_ELIGIBLE, "unserviceable geometry: existing downstream refusal applies")
    try:
        grid_last_index = grid_last_provider(override) if grid_last_provider is not None else None
    except On08ShlIndexRefusal:
        raise
    except Exception as exc:  # the real grid cannot be built: fail closed, never guess
        raise On08ShlIndexRefusal("ON08_SHL_INDEX_OFF_GRID", f"the period grid could not be established ({type(exc).__name__})") from exc
    if grid_last_index is None or maturity > grid_last_index or eligibility > grid_last_index:
        raise On08ShlIndexRefusal(
            "ON08_SHL_INDEX_OFF_GRID", f"derived SHL indices ({maturity}, {eligibility}) do not fit the period grid ending at {grid_last_index}")
    if (maturity, eligibility) == stored:
        return override, ShlIndexOutcome(UNCHANGED, "stored indices already equal the geometry", stored, stored)
    new_fin = _replace(fin, shl_maturity_period_index=maturity, shl_principal_eligibility_start_period=eligibility)
    return _replace(override, financing=new_fin), ShlIndexOutcome(CORRECTED, "re-derived from effective geometry", stored, (maturity, eligibility))


def effective_grid_last_index(override: Any) -> int:
    """Last index of the REAL period grid the engine will build for these inputs (no second authority)."""
    from financial_engine.adapters.project_inputs import from_project_inputs
    from financial_engine.orchestrator import _build_period_engine
    periods = list(_build_period_engine(from_project_inputs(override)).periods())
    if not periods:
        raise On08ShlIndexRefusal("ON08_SHL_INDEX_OFF_GRID", "empty period grid")
    return periods[-1].index
