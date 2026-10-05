"""Client Cost Template extraction — pure capture of project cost truth.

`CostProjectState` is the pure, engine-free capture of a project's current
cost authorities (parent CAPEX fields with their accounting metadata, OPEX
items with per-line inflation and steps, active CAPEX/OPEX sub-lines with
their persistent identities, and the typed contingency lineage).
`extract_client_cost_template` turns that state into a CLIENT CostTemplate.

Client semantics (Correction-level rules from the Workflow 03 contract):

- EXACT SNAPSHOT by default: amounts, inflation, steps, schedules and
  metadata are preserved verbatim; scaling is NEVER inferred from
  amount / capacity.
- Only rows/items explicitly classified PER_MW become scalable (a future
  explicit user action); the extractor never marks them so on its own.
- User-added persistent identities (C.NN.U### / B.NN.U###) are carried as
  `child_code` verbatim — never renumbered or collapsed into labels.
- Only cost economics are captured: no revenue, financing, debt, DSRA, SHL,
  tax rates, returns, statements or Last Run outputs.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

from app.services.cost_template.contracts import (
    CapexTemplateItem,
    CostDriver,
    CostTemplate,
    ItemClassification,
    OpexTemplateItem,
    ScalingBasis,
    TemplateKind,
    TemplateSource,
)


@dataclass(frozen=True)
class CapexFieldState:
    """Parent-level CAPEX field state (a CapexItem on its C.NN field).

    Applicability addendum (A7): a non-decomposed parent assumption may
    carry project applicability directly; stored economics are never zeroed
    by applicability.
    """

    field_name: str
    parent_code: str
    label: str
    amount_keur: float
    y0_share: float = 0.0
    spending_profile: tuple[float, ...] = ()
    asset_class: Optional[str] = None
    useful_life_override: Optional[int] = None
    is_depreciable: bool = True
    is_active: bool = True


@dataclass(frozen=True)
class OpexItemState:
    """Parent-level OPEX item state (A7: may carry applicability)."""

    name: str
    parent_code: str
    y1_amount_keur: float
    annual_inflation: float = 0.0
    step_changes: tuple[tuple[int, float], ...] = ()
    percentage_of_opex: float = 0.0
    is_active: bool = True


@dataclass(frozen=True)
class CapexSubLineState:
    """CAPEX sub-line (child row) with its persistent identity.

    Applicability addendum (A5/A10): ``is_active`` is the project-owned
    applicability of the row (existing persistence authority); inactive rows
    are preserved with their economics, never dropped or zeroed.
    """

    parent_category_code: str
    business_code: str            # C.NN.NN (reference detail) or C.NN.U###
    label: str
    amount_keur: float
    schedule_json: str = "{}"
    scalar_metadata: dict[str, Any] = field(default_factory=dict)
    source: str = "user"
    is_active: bool = True


@dataclass(frozen=True)
class OpexSubLineState:
    """Active OPEX sub-line (child row) with its persistent identity."""

    parent_group_code: str
    business_code: str            # B.NN.NN or B.NN.U###
    label: str
    amount_keur: float            # Y1
    inflation_pct: float = 0.0    # percent (existing persistence unit)
    source: str = "user"
    # Applicability addendum (A5/A10): project-owned ON/OFF, preserved
    # through extraction; inactive rows retain their economics.
    is_active: bool = True
    # Correction B (defect 5): replacement provenance — the exact canonical
    # OpexItem name this detail row replaces (seeded/detail B.NN.NN rows);
    # user B.NN.U### rows are ADDITIVE and leave both unset.
    canonical_parent_key: Optional[str] = None
    reference_seed: bool = False
    # Correction C (defect 3): the original persisted runtime row source
    # ("reference_seed" | "user_override" | "user") so client-extracted
    # decomposition rows stay runtime-compatible replacements.
    persisted_source: Optional[str] = None


@dataclass(frozen=True)
class ContingencyState:
    """Typed contingency authority state (percentage + basis + lineage).

    Correction A (defect 5): percent values use the canonical FINCO
    contingency-authority unit — PERCENT POINTS (6.0 means 6%), strict
    0..100 — exactly as `contingency_authority.validate_pct` stores them.
    """

    capex_pct: Optional[float] = None    # percent points, authority unit
    opex_pct: Optional[float] = None     # percent points, authority unit
    # Applicability addendum (A9): an authority may be INACTIVE (config
    # retained, not applied) - distinct from an explicit 0.0% authority.
    capex_active: bool = True
    opex_active: bool = True
    lineage: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class CostProjectState:
    """Pure capture of a project's cost truth across its authorities."""

    capacity_mw: float
    project_ref: str
    capex_fields: tuple[CapexFieldState, ...] = ()
    opex_items: tuple[OpexItemState, ...] = ()
    capex_sub_lines: tuple[CapexSubLineState, ...] = ()
    opex_sub_lines: tuple[OpexSubLineState, ...] = ()
    contingency: Optional[ContingencyState] = None

    def validate(self) -> None:
        # Correction A (defect 7): NaN / +Inf / -Inf must fail closed.
        import math as _math

        # Correction D (defect 6): applicability is strict boolean state.
        for state_row in list(self.capex_fields) + list(self.opex_items):
            value = getattr(state_row, "is_active", None)
            if value is not None and type(value) is not bool:
                raise ValueError(
                    f"COST_STATE_APPLICABILITY_INVALID: "
                    f"{type(state_row).__name__}.is_active must be a strict "
                    f"boolean, got {value!r}"
                )
        for state_row in list(self.capex_sub_lines) + list(self.opex_sub_lines):
            value = getattr(state_row, "is_active", None)
            if value is not None and type(value) is not bool:
                raise ValueError(
                    f"COST_STATE_APPLICABILITY_INVALID: "
                    f"{type(state_row).__name__}.is_active must be a strict "
                    f"boolean, got {value!r}"
                )
        if self.contingency is not None:
            for flag in ("capex_active", "opex_active"):
                value = getattr(self.contingency, flag)
                if type(value) is not bool:
                    raise ValueError(
                        f"COST_STATE_APPLICABILITY_INVALID: ContingencyState."
                        f"{flag} must be a strict boolean, got {value!r}"
                    )

        if isinstance(self.capacity_mw, bool) \
                or not isinstance(self.capacity_mw, (int, float)) \
                or not _math.isfinite(float(self.capacity_mw)) \
                or float(self.capacity_mw) <= 0:
            raise ValueError(
                f"COST_STATE_CAPACITY_INVALID: capacity_mw must be a finite "
                f"number strictly greater than zero, got {self.capacity_mw!r}"
            )


def extract_client_cost_template(
    state: CostProjectState,
    *,
    template_id: str,
    version: int = 1,
    name: str = "",
) -> CostTemplate:
    """Extract a CLIENT CostTemplate from a project's cost state.

    Deterministic: identical state → identical template. Every active row is
    captured verbatim under EXACT_SNAPSHOT scaling; percentage contingency
    semantics stay percentages; financing/reserve scalars are out of scope
    (runtime-derived authorities, never part of a client cost template).
    """
    state.validate()

    capex_items: list[CapexTemplateItem] = []
    sub_parents = {s.parent_category_code for s in state.capex_sub_lines}
    for f in state.capex_fields:
        if f.parent_code in {"C.17", "C.18"}:
            # Runtime-derived financing/reserve authorities: metadata only.
            capex_items.append(CapexTemplateItem(
                item_id=f"capex.{f.field_name}",
                parent_code=f.parent_code,
                label=f.label,
                driver=CostDriver.DERIVED_RUNTIME,
                classification=ItemClassification.DERIVED_RUNTIME,
                source=TemplateSource.CLIENT_EXTRACT,
                source_ref=state.project_ref,
            ))
            continue
        if f.parent_code == "C.13" and state.contingency is not None \
                and state.contingency.capex_pct is not None:
            # Percentage rule: preserve pct + basis + lineage, never freeze
            # the derived amount as a primary cost. Applicability (A9): the
            # item's default_active mirrors the authority active flag —
            # INACTIVE retains the configured pct but is not applied.
            capex_items.append(CapexTemplateItem(
                item_id=f"capex.{f.field_name}",
                parent_code=f.parent_code,
                label=f.label,
                driver=CostDriver.PERCENT_OF_ELIGIBLE_CAPEX,
                driver_value=float(state.contingency.capex_pct),
                amount_keur=float(f.amount_keur),   # recorded derived amount (lineage)
                y0_share=f.y0_share,
                spending_profile=f.spending_profile,
                asset_class=f.asset_class,
                useful_life_override=f.useful_life_override,
                is_depreciable=f.is_depreciable,
                scaling_basis=ScalingBasis.EXACT_SNAPSHOT,
                source=TemplateSource.CLIENT_EXTRACT,
                source_ref=state.project_ref,
                default_active=bool(state.contingency.capex_active),
            ))
            continue
        capex_items.append(CapexTemplateItem(
            item_id=f"capex.{f.field_name}",
            parent_code=f.parent_code,
            label=f.label,
            driver=CostDriver.ABSOLUTE_KEUR,
            amount_keur=float(f.amount_keur),
            y0_share=f.y0_share,
            spending_profile=f.spending_profile,
            asset_class=f.asset_class,
            useful_life_override=f.useful_life_override,
            is_depreciable=f.is_depreciable,
            scaling_basis=ScalingBasis.EXACT_SNAPSHOT,
            source=TemplateSource.CLIENT_EXTRACT,
            source_ref=state.project_ref,
            # Correction D (defect 1): exact-snapshot applicability — the
            # source project row's active state is preserved, never inferred.
            default_active=bool(f.is_active),
        ))
        if f.parent_code in sub_parents:
            continue  # children fully decompose this field; captured below
    # Child rows verbatim (persistent identities preserved; presentation
    # codes carried as-is; PER_MW never inferred). Correction A (defect 2):
    # approved CAPEX scalar metadata is sanitized with the existing FINCO
    # authority and carried losslessly. Correction A (defect 3): C.NN.NN
    # presentation rows DECOMPOSE/REPLACE their canonical parent (existing
    # reference-seed replacement semantics); Correction B: C.NN.U### user
    # rows participate in the SAME replacement/breakdown semantics.
    from app.persistence.capex_sub_lines import sanitize_scalar_capex_metadata

    for s in state.capex_sub_lines:
        # Correction B (defect 1): EVERY CAPEX sub-line participates in the
        # existing replacing-base breakdown (zero base + fold), including
        # user-created C.NN.U### rows - they are never additive CAPEX
        # economics. Applicability addendum (A10): is_active is preserved.
        capex_items.append(CapexTemplateItem(
            item_id=f"capex.subline.{s.business_code}",
            parent_code=s.parent_category_code,
            child_code=s.business_code,
            label=s.label,
            driver=CostDriver.ABSOLUTE_KEUR,
            amount_keur=float(s.amount_keur),
            schedule_json=s.schedule_json or "{}",
            scaling_basis=ScalingBasis.EXACT_SNAPSHOT,
            source=TemplateSource.CLIENT_EXTRACT,
            source_ref=state.project_ref,
            replaces_parent=True,
            scalar_metadata=sanitize_scalar_capex_metadata(s.scalar_metadata),
            default_active=bool(s.is_active),
        ))

    opex_items: list[OpexTemplateItem] = []
    opex_sub_parents = {s.parent_group_code for s in state.opex_sub_lines}
    for o in state.opex_items:
        # Correction C (defect 2): the TYPED contingency authority is
        # PRIMARY. When state.contingency.opex_pct exists, B.13 is
        # PERCENT_OF_OPEX with that EXACT value regardless of the active
        # flag - INACTIVE retains economics, it never forgets them (and
        # 6.0% inactive stays 6.0%, never the runtime OpexItem fraction).
        # The core OpexItem fraction is only a backward-compatible fallback
        # when the typed authority is genuinely absent.
        typed_pct = (state.contingency.opex_pct
                     if state.contingency is not None else None)
        if o.parent_code == "B.13" and typed_pct is not None:
            opex_items.append(OpexTemplateItem(
                item_id=f"opex.{o.name}",
                parent_code=o.parent_code,
                label=o.name,
                driver=CostDriver.PERCENT_OF_OPEX,
                driver_value=float(typed_pct),
                scaling_basis=ScalingBasis.EXACT_SNAPSHOT,
                source=TemplateSource.CLIENT_EXTRACT,
                source_ref=state.project_ref,
                # Applicability (A9): item applicability mirrors the typed
                # authority active flag; INACTIVE retains the percentage.
                default_active=bool(state.contingency.opex_active),
            ))
            continue
        pct_fraction = float(o.percentage_of_opex or 0.0)
        if pct_fraction > 0:
            opex_items.append(OpexTemplateItem(
                item_id=f"opex.{o.name}",
                parent_code=o.parent_code,
                label=o.name,
                driver=CostDriver.PERCENT_OF_OPEX,
                driver_value=pct_fraction * 100.0,
                scaling_basis=ScalingBasis.EXACT_SNAPSHOT,
                source=TemplateSource.CLIENT_EXTRACT,
                source_ref=state.project_ref,
            ))
            continue
        opex_items.append(OpexTemplateItem(
            item_id=f"opex.{o.name}",
            parent_code=o.parent_code,
            label=o.name,
            driver=CostDriver.ABSOLUTE_KEUR,
            y1_amount_keur=float(o.y1_amount_keur),
            annual_inflation=float(o.annual_inflation),
            step_changes=tuple(o.step_changes),
            scaling_basis=ScalingBasis.EXACT_SNAPSHOT,
            source=TemplateSource.CLIENT_EXTRACT,
            source_ref=state.project_ref,
            # Correction D (defect 1): exact-snapshot applicability.
            default_active=bool(o.is_active),
        ))
    import re as _re
    for s in state.opex_sub_lines:
        is_detail = bool(_re.match(r"^B\.\d{2}\.\d{2}$", s.business_code))
        opex_items.append(OpexTemplateItem(
            item_id=f"opex.subline.{s.business_code}",
            parent_code=s.parent_group_code,
            child_code=s.business_code,
            label=s.label,
            driver=CostDriver.ABSOLUTE_KEUR,
            y1_amount_keur=float(s.amount_keur),
            # Persistence stores percent; the template stores the fraction
            # (OpexItem.annual_inflation unit) — divide by 100 exactly once.
            annual_inflation=float(s.inflation_pct) / 100.0,
            scaling_basis=ScalingBasis.EXACT_SNAPSHOT,
            source=TemplateSource.CLIENT_EXTRACT,
            source_ref=state.project_ref,
            replaces_parent=is_detail,
            # Correction B (defect 5): replacement provenance survives
            # extraction. User B.NN.U### rows are ADDITIVE (both unset).
            canonical_parent_key=s.canonical_parent_key if is_detail else None,
            reference_seed=bool(s.reference_seed) if is_detail else False,
            # Correction D (defect 5): additive U-rows carry the explicit
            # additive persisted source; replacement rows keep the original
            # persisted runtime row source.
            persisted_source=(
                s.persisted_source or s.source
            ) if is_detail else "user",
            default_active=bool(s.is_active),
        ))

    return CostTemplate.create(
        template_id=template_id,
        version=version,
        name=name or f"Client Cost Template ({state.project_ref})",
        technology="",  # client templates are technology-agnostic snapshots
        kind=TemplateKind.CLIENT,
        capex_items=tuple(capex_items),
        opex_items=tuple(opex_items),
        provenance="Extracted from project cost state (exact snapshot)",
        source_project_ref=state.project_ref,
        # Applicability addendum (A9): INACTIVE retains the configured
        # percentage but the authority is not applied.
        capex_contingency_active=(
            state.contingency.capex_active if state.contingency else True),
        opex_contingency_active=(
            state.contingency.opex_active if state.contingency else True),
    )
