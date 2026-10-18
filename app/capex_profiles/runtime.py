"""RC-7 - Run-time materialisation of the persisted monthly CAPEX profile document (pure over its inputs; no engine change).

Called on the SAME ``ProjectInputs`` a Run is about to execute, AFTER the user sub-lines are folded into the CapexStructure.  With no
profile document it returns the input object unchanged (identity), so every default output is untouched.  With a document it:

  1. derives the leaf rows exactly as the Run folds them (REPLACE semantics: a category with active sub-lines is owned by those
     sub-lines only - the category base is zeroed by the Run and therefore cannot carry a profile);
  2. fails closed when a stored profile no longer names a current leaf, or when the financing structure cannot be bound
     (Junior/Multi-Senior, an explicit typed construction input, manual financing costs, non-semester axis, ...);
  3. expands the construction input the generic policy would derive onto the month grid (``binding.bind``) and installs it as the
     typed ``construction_financing``.  The unchanged generic policy then sees an explicit construction authority and the canonical
     Stage B2 / allocator / IDC path computes uses, draws, commitment fees, capitalised IDC and total uses.
"""
from __future__ import annotations

import dataclasses
from dataclasses import dataclass
from typing import Any, Mapping, Optional

from app.capex_profiles import config
from app.capex_profiles.binding import BindingEvidence, BindingUnsupported, BoundConstruction, Leaf, bind
from app.capex_profiles.contract import ProfileError, ProfileSpec

# CapexStructure fields that are timing items in the construction authority (derived / financing rows are excluded by design).
DERIVED_FIELDS = frozenset({"contingencies", "idc", "bank_fees", "commitment_fees", "other_financial", "vat_costs", "reserve_accounts"})
BASE_PREFIX = "base:"


class CapexProfileBindingError(ValueError):
    """A stored profile cannot be bound to this Run; nothing was approximated and the Run must not proceed."""

    def __init__(self, code: str, detail: str = ""):
        self.code = code
        super().__init__(f"{code}: {detail}" if detail else code)


@dataclass(frozen=True)
class RuntimeBinding:
    inputs: Any
    evidence: Optional[BindingEvidence]
    leaves: tuple[Leaf, ...]
    bound: Optional[BoundConstruction]


def leaves_for(capex, project_id: str, scenario_overrides: Optional[Mapping[str, Any]] = None) -> tuple[Leaf, ...]:
    """Leaf rows exactly as the Run folds them.  ``capex`` is the FOLDED CapexStructure."""
    from app.persistence.capex_sub_lines import CAPEX_CATEGORY_TO_FIELD, resolve_effective_sub_line_amount
    from app.services.capex_sub_lines_integration import _extract_sub_line_overrides, _load_active_sub_lines

    subs = [s for s in (_load_active_sub_lines(project_id) if project_id else ()) if s.is_active]
    overrides = _extract_sub_line_overrides(scenario_overrides)
    by_field: dict[str, list] = {}
    for sub in subs:
        field = CAPEX_CATEGORY_TO_FIELD.get(sub.parent_category_code)
        if field:
            by_field.setdefault(field, []).append(sub)
    leaves: list[Leaf] = []
    for field in capex._CAPEX_ITEM_FIELDS:
        if field in DERIVED_FIELDS:
            continue
        category = float(getattr(capex, field).amount_keur)
        if field in by_field:
            raw = [(sub.business_code, float(resolve_effective_sub_line_amount(sub.amount_keur, overrides.get(sub.sub_line_id))))
                   for sub in sorted(by_field[field], key=lambda s: s.business_code)]
            total = sum(amount for _, amount in raw)
            if category > 0 and total <= 0:
                raise CapexProfileBindingError("CAPEX_BINDING_LEAF_AMOUNTS_UNAVAILABLE", field)
            # A leaf owns its SHARE of the category the Run actually executes, so category-level scaling (a CAPEX shock, a scenario
            # multiplier) re-times the scaled amount instead of invalidating the profile.
            scale = category / total if total > 0 else 0.0
            leaves.extend(Leaf(code, field, amount * scale) for code, amount in raw)
        else:
            leaves.append(Leaf(BASE_PREFIX + field, field, category))
    return tuple(leaves)


def _refuse_structure(pi) -> None:
    from finco_core.inputs.junior_debt import JuniorProjectInputs
    from finco_core.inputs.multisenior import MultiSeniorProjectInputs
    if isinstance(pi, (JuniorProjectInputs, MultiSeniorProjectInputs)):
        raise CapexProfileBindingError("CAPEX_BINDING_FINANCING_STRUCTURE_UNSUPPORTED", "Junior / Multi-Senior projects own their construction timeline")
    if pi.financing.construction_financing is not None or pi.financing.construction_period_uses_keur:
        raise CapexProfileBindingError("CAPEX_BINDING_EXPLICIT_CONSTRUCTION_UNSUPPORTED", "the project already carries an explicit construction input")
    capex = pi.capex
    if any(getattr(capex, name, 0.0) for name in ("idc_keur", "commitment_fees_keur", "bank_fees_keur", "other_financial_keur", "vat_costs_keur",
                                                  "vat_facility_idc_keur", "vat_facility_commitment_fee_keur")):
        raise CapexProfileBindingError("CAPEX_BINDING_MANUAL_FINANCING_COSTS_UNSUPPORTED", "manual financing costs would be counted twice")


def bind_inputs(pi, raw, *, project_id: str, scenario_overrides: Optional[Mapping[str, Any]] = None) -> RuntimeBinding:
    try:
        specs = config.parse(raw)
    except ProfileError as exc:
        raise CapexProfileBindingError(exc.code, str(exc)) from exc
    if not specs:
        return RuntimeBinding(pi, None, (), None)
    _refuse_structure(pi)
    leaves = leaves_for(pi.capex, project_id, scenario_overrides)
    known = {leaf.item_key for leaf in leaves}
    unknown = sorted(s.item_key for s in specs if s.item_key not in known)
    if unknown:
        raise CapexProfileBindingError("CAPEX_PROFILE_LEAF_UNKNOWN", ", ".join(unknown))
    spec_by_key = {s.item_key: s for s in specs}
    leaves = tuple(dataclasses.replace(leaf, spec=spec_by_key.get(leaf.item_key)) for leaf in leaves)
    from financial_engine.financing.generic_product_policy import GenericFinancingPolicyError, derive_construction_financing
    try:
        construction = derive_construction_financing(pi)
        category_amounts = {item.code: float(getattr(pi.capex, item.code).amount_keur) for item in construction.capex_items}
        bound = bind(construction, construction_months=int(pi.info.construction_months), category_amounts_keur=category_amounts, leaves=leaves)
    except GenericFinancingPolicyError as exc:
        raise CapexProfileBindingError("CAPEX_BINDING_CONSTRUCTION_DERIVATION_UNSUPPORTED", str(exc)) from exc
    except BindingUnsupported as exc:
        raise CapexProfileBindingError(exc.code, str(exc)) from exc
    except ProfileError as exc:
        raise CapexProfileBindingError(exc.code, str(exc)) from exc
    financing = dataclasses.replace(pi.financing, construction_financing=bound.construction)
    return RuntimeBinding(dataclasses.replace(pi, financing=financing), bound.evidence, leaves, bound)


def apply_profiles(pi, raw, *, project_id: str, scenario_overrides: Optional[Mapping[str, Any]] = None):
    """The ``ProjectInputs`` to run.  Identity when ``raw`` carries no profile."""
    return bind_inputs(pi, raw, project_id=project_id, scenario_overrides=scenario_overrides).inputs


def apply_snapshot_profiles(pi, snapshot, *, project_id: str, scenario_overrides: Optional[Mapping[str, Any]] = None):
    """``apply_profiles`` reading the document from a snapshot mapping (``snapshot_origin`` / draft / Run snapshot)."""
    raw = (snapshot or {}).get(config.SNAPSHOT_KEY)
    if not raw:
        return pi
    return apply_profiles(pi, raw, project_id=project_id, scenario_overrides=scenario_overrides)


def refuse_unbound_surface(snapshot, surface: str) -> None:
    """Fail closed on a surface that cannot bind a monthly profile: a silent semester Run would contradict the Working Copy."""
    if (snapshot or {}).get(config.SNAPSHOT_KEY):
        from app.input_adapter import SnapshotInputError
        raise SnapshotInputError(
            f"CAPEX_PROFILE_UNBOUND_SURFACE: this Working Copy carries a monthly CAPEX construction profile that {surface} does not apply. "
            "Use the Workbook V2 Run, or remove the profile in the CAPEX planner.")


def guard_snapshot_builder(builder, surface: str):
    """``build_projectinputs_from_snapshot`` that refuses a snapshot carrying a profile it cannot bind."""
    def guarded(snapshot, *args, **kwargs):
        refuse_unbound_surface(snapshot, surface)
        return builder(snapshot, *args, **kwargs)
    guarded.__name__ = getattr(builder, "__name__", "build_projectinputs_from_snapshot")
    guarded.__wrapped__ = builder
    return guarded
