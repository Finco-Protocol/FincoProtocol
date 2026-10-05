"""Model V2 Cost Template — typed immutable envelope contracts.

A CostTemplate is an ASSUMPTION PACKAGE: a reusable, versioned, immutable
representation of a project's cost structure that MATERIALIZES into the
existing FINCO CAPEX/OPEX authorities. It is NOT a financial engine and it
never replaces the typed `CapexItem` / `CapexStructure` / `OpexItem`
authorities — CAPEX and OPEX keep separate typed template items because
their semantics differ materially.

Design invariants:

- HIERARCHY PRESERVED: parent C.NN / B.NN groups and child C.NN.NN /
  B.NN.NN rows remain first-class; nothing is flattened. Presentation codes
  never become financial identity — persistent user identities
  (C.NN.U### / B.NN.U###) are carried separately.
- C.17 FINANCING COSTS and C.18 RESERVE ACCOUNTS are runtime-derived
  authorities: they can appear on a template ONLY as
  `ItemClassification.DERIVED_RUNTIME` metadata and can never be
  materialized as editable project inputs.
- DRIVERS: an active driver must map exactly onto an existing FINCO
  authority or resolve deterministically into one without new financial
  mathematics. Unsupported drivers are reserved and fail closed.
- CLIENT templates default to EXACT_SNAPSHOT scaling; PER_MW scaling is
  never inferred from amount/capacity — it is an explicit classification.
- VERSIONS IMMUTABLE: a template version is immutable once created; edits
  produce a new version. Validation is fail-closed (duplicates, unknown
  parents, non-finite/negative economics, illegal driver/class combos).
- MISSING != ZERO: an absent optional amount stays `None`; zero is only
  ever an explicit economic zero.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

# ---------------------------------------------------------------------------
# Parent-code vocabularies (mirror the existing C./B. authorities)
# ---------------------------------------------------------------------------

# Editable CAPEX parents: C.01–C.16 (C.13 contingency, C.15 acquisition /
# development, C.16 rights are ordinary economic parents). C.17 Financing
# Costs and C.18 Reserve Accounts are runtime-derived authorities.
EDITABLE_CAPEX_PARENTS = frozenset(f"C.{i:02d}" for i in range(1, 17))
DERIVED_CAPEX_PARENTS = frozenset({"C.17", "C.18"})
KNOWN_CAPEX_PARENTS = EDITABLE_CAPEX_PARENTS | DERIVED_CAPEX_PARENTS

# Editable OPEX parents: B.01–B.13 (B.13 OPEX contingency).
EDITABLE_OPEX_PARENTS = frozenset(f"B.{i:02d}" for i in range(1, 14))
KNOWN_OPEX_PARENTS = EDITABLE_OPEX_PARENTS

_PRESENTATION_CHILD_RE_TEMPLATE = "{parent}.{idx:02d}"


class TemplateKind(str, Enum):
    GENERIC = "generic"
    CLIENT = "client"


class TemplateStatus(str, Enum):
    ACTIVE = "active"
    RETIRED = "retired"


class CostDriver(str, Enum):
    """Template cost drivers. Active drivers map exactly onto existing
    FINCO authorities; reserved drivers fail closed on materialization."""

    EUR_PER_MW = "eur_per_mw"                      # active: seed V0 PER_MW
    ABSOLUTE_KEUR = "absolute_keur"                # active: exact kEUR amount
    PERCENT_OF_ELIGIBLE_CAPEX = "percent_of_eligible_capex"  # C.13 contingency
    PERCENT_OF_OPEX = "percent_of_opex"            # B.13 contingency
    # Reserved — fail closed at materialization (future runtime capability):
    EUR_PER_MWH = "eur_per_mwh"                    # generation-dependent OPEX
    DERIVED_RUNTIME = "derived_runtime"            # C.17/C.18-style authorities


ACTIVE_CAPEX_DRIVERS = frozenset({
    CostDriver.EUR_PER_MW,
    CostDriver.ABSOLUTE_KEUR,
    CostDriver.PERCENT_OF_ELIGIBLE_CAPEX,
})
ACTIVE_OPEX_DRIVERS = frozenset({
    CostDriver.EUR_PER_MW,
    CostDriver.ABSOLUTE_KEUR,
    CostDriver.PERCENT_OF_OPEX,
})
RESERVED_DRIVERS = frozenset({CostDriver.EUR_PER_MWH, CostDriver.DERIVED_RUNTIME})


class ScalingBasis(str, Enum):
    """How a template item scales when materialized into a different-size
    project. CLIENT items default to EXACT_SNAPSHOT; PER_MW is an explicit
    classification, never inferred from amount / capacity."""

    EXACT_SNAPSHOT = "exact_snapshot"
    PER_MW = "per_mw"
    DERIVED = "derived"


class ItemClassification(str, Enum):
    ACTIVE = "active"
    DERIVED_RUNTIME = "derived_runtime"


class TemplateSource(str, Enum):
    GENERIC_TEMPLATE = "generic_template"
    CLIENT_EXTRACT = "client_extract"
    USER = "user"


def _finite_non_negative(value: float, code: str, label: str) -> float:
    if not isinstance(value, (int, float)) or isinstance(value, bool) \
            or not math.isfinite(float(value)) or float(value) < 0.0:
        raise ValueError(f"{code}: {label} must be finite and non-negative, got {value!r}")
    return float(value)


@dataclass(frozen=True)
class CapexTemplateItem:
    """One CAPEX assumption row on a CostTemplate.

    Identity: `item_id` is the stable template identity across versions.
    `parent_code` (C.NN) + `child_code` preserve the existing hierarchy;
    `child_code` may be a presentation detail code (C.NN.NN), a persistent
    user identity (C.NN.U###), or None for a parent-level row.
    """

    item_id: str
    parent_code: str
    label: str
    driver: CostDriver
    child_code: Optional[str] = None
    # Rate for EUR_PER_MW (kEUR per MW — the seed V0 unit); the percentage
    # for PERCENT_OF_ELIGIBLE_CAPEX (fraction 0..1). None otherwise.
    driver_value: Optional[float] = None
    # Absolute/reference amount (kEUR) for ABSOLUTE_KEUR rows; the recorded
    # reference amount on rate rows. None = absent (MISSING != ZERO).
    amount_keur: Optional[float] = None
    # CAPEX timing (existing authorities; never a second IDC model).
    y0_share: float = 0.0
    spending_profile: tuple[float, ...] = ()
    schedule_json: str = "{}"
    # Accounting metadata (roundtripped; calculation stays with existing
    # authorities).
    asset_class: Optional[str] = None       # AssetClass value
    useful_life_override: Optional[int] = None
    is_depreciable: bool = True
    # Scaling / classification / provenance.
    scaling_basis: ScalingBasis = ScalingBasis.EXACT_SNAPSHOT
    classification: ItemClassification = ItemClassification.ACTIVE
    source: TemplateSource = TemplateSource.GENERIC_TEMPLATE
    source_ref: str = ""                    # project / template lineage note
    # Inactive Development-Costs migration seam (C.15). Never active here.
    devex_candidate: bool = False

    def validate(self) -> None:
        sid = self.item_id or "<missing-id>"
        if not self.item_id or not self.item_id.strip():
            raise ValueError("COST_TEMPLATE_ITEM_ID_REQUIRED: every CAPEX item needs a non-empty id")
        if self.parent_code not in KNOWN_CAPEX_PARENTS:
            raise ValueError(
                f"COST_TEMPLATE_PARENT_UNKNOWN: {self.parent_code!r} is not a known "
                f"CAPEX parent code (item {sid!r})"
            )
        if self.driver not in CostDriver:
            raise ValueError(f"COST_TEMPLATE_DRIVER_UNKNOWN: {self.driver!r} on {sid!r}")
        if self.child_code is not None:
            if not self.child_code.startswith(self.parent_code + "."):
                raise ValueError(
                    f"COST_TEMPLATE_CHILD_PARENT_MISMATCH: child {self.child_code!r} "
                    f"does not belong to parent {self.parent_code!r} (item {sid!r})"
                )
        _finite_non_negative(self.y0_share, "COST_TEMPLATE_VALUE_INVALID",
                             f"item {sid!r} y0_share")
        for i, share in enumerate(self.spending_profile):
            _finite_non_negative(share, "COST_TEMPLATE_VALUE_INVALID",
                                 f"item {sid!r} spending_profile[{i}]")
        if self.amount_keur is not None:
            _finite_non_negative(self.amount_keur, "COST_TEMPLATE_VALUE_INVALID",
                                 f"item {sid!r} amount_keur")
        if self.driver_value is not None:
            _finite_non_negative(self.driver_value, "COST_TEMPLATE_VALUE_INVALID",
                                 f"item {sid!r} driver_value")
        if self.classification is ItemClassification.DERIVED_RUNTIME:
            if self.driver is not CostDriver.DERIVED_RUNTIME:
                raise ValueError(
                    f"COST_TEMPLATE_DRIVER_CLASS_ILLEGAL: DERIVED_RUNTIME item "
                    f"{sid!r} must use the DERIVED_RUNTIME driver"
                )
            return  # derived metadata rows carry no editable economics
        # Active rows: driver/class and driver/value consistency.
        if self.driver not in ACTIVE_CAPEX_DRIVERS:
            raise ValueError(
                f"COST_TEMPLATE_DRIVER_RESERVED: driver {self.driver.value!r} on "
                f"active item {sid!r} is reserved and cannot materialize"
            )
        if self.driver is CostDriver.PERCENT_OF_ELIGIBLE_CAPEX:
            if self.parent_code != "C.13":
                raise ValueError(
                    f"COST_TEMPLATE_DRIVER_CLASS_ILLEGAL: PERCENT_OF_ELIGIBLE_CAPEX "
                    f"is a C.13 contingency driver, used on {sid!r} "
                    f"({self.parent_code})"
                )
            if self.driver_value is None or not (0.0 < self.driver_value <= 1.0):
                raise ValueError(
                    f"COST_TEMPLATE_VALUE_INVALID: item {sid!r} contingency "
                    "driver_value must be a fraction within (0, 1]"
                )
        elif self.driver is CostDriver.EUR_PER_MW:
            if self.driver_value is None:
                raise ValueError(
                    f"COST_TEMPLATE_DRIVER_VALUE_REQUIRED: EUR_PER_MW item {sid!r} "
                    "needs driver_value (kEUR per MW)"
                )
        elif self.driver is CostDriver.ABSOLUTE_KEUR:
            if self.amount_keur is None:
                raise ValueError(
                    f"COST_TEMPLATE_AMOUNT_REQUIRED: ABSOLUTE_KEUR item {sid!r} "
                    "needs amount_keur (MISSING is not ZERO)"
                )
        if self.parent_code in DERIVED_CAPEX_PARENTS:
            raise ValueError(
                f"COST_TEMPLATE_DERIVED_PARENT_NOT_EDITABLE: item {sid!r} under "
                f"{self.parent_code} must be classified DERIVED_RUNTIME; C.17/"
                "C.18 are runtime-derived authorities"
            )


@dataclass(frozen=True)
class OpexTemplateItem:
    """One OPEX assumption row on a CostTemplate (Y1 + per-line inflation +
    step changes preserved exactly)."""

    item_id: str
    parent_code: str
    label: str
    driver: CostDriver
    child_code: Optional[str] = None
    driver_value: Optional[float] = None    # kEUR per MW for EUR_PER_MW
    # Exact Y1 amount (kEUR). None = absent (MISSING != ZERO).
    y1_amount_keur: Optional[float] = None
    annual_inflation: float = 0.0
    step_changes: tuple[tuple[int, float], ...] = ()
    scaling_basis: ScalingBasis = ScalingBasis.EXACT_SNAPSHOT
    classification: ItemClassification = ItemClassification.ACTIVE
    source: TemplateSource = TemplateSource.GENERIC_TEMPLATE
    source_ref: str = ""

    def validate(self) -> None:
        sid = self.item_id or "<missing-id>"
        if not self.item_id or not self.item_id.strip():
            raise ValueError("COST_TEMPLATE_ITEM_ID_REQUIRED: every OPEX item needs a non-empty id")
        if self.parent_code not in KNOWN_OPEX_PARENTS:
            raise ValueError(
                f"COST_TEMPLATE_PARENT_UNKNOWN: {self.parent_code!r} is not a known "
                f"OPEX parent code (item {sid!r})"
            )
        if self.child_code is not None and not self.child_code.startswith(self.parent_code + "."):
            raise ValueError(
                f"COST_TEMPLATE_CHILD_PARENT_MISMATCH: child {self.child_code!r} "
                f"does not belong to parent {self.parent_code!r} (item {sid!r})"
            )
        if self.driver not in CostDriver:
            raise ValueError(f"COST_TEMPLATE_DRIVER_UNKNOWN: {self.driver!r} on {sid!r}")
        if self.classification is ItemClassification.DERIVED_RUNTIME:
            if self.driver is not CostDriver.DERIVED_RUNTIME:
                raise ValueError(
                    f"COST_TEMPLATE_DRIVER_CLASS_ILLEGAL: DERIVED_RUNTIME item "
                    f"{sid!r} must use the DERIVED_RUNTIME driver"
                )
            return
        if self.driver not in ACTIVE_OPEX_DRIVERS:
            raise ValueError(
                f"COST_TEMPLATE_DRIVER_RESERVED: driver {self.driver.value!r} on "
                f"active item {sid!r} is reserved and cannot materialize"
            )
        if self.driver is CostDriver.PERCENT_OF_OPEX:
            if self.parent_code != "B.13":
                raise ValueError(
                    f"COST_TEMPLATE_DRIVER_CLASS_ILLEGAL: PERCENT_OF_OPEX is a "
                    f"B.13 contingency driver, used on {sid!r} ({self.parent_code})"
                )
        elif self.driver is CostDriver.EUR_PER_MW and self.driver_value is None:
            raise ValueError(
                f"COST_TEMPLATE_DRIVER_VALUE_REQUIRED: EUR_PER_MW item {sid!r} "
                "needs driver_value (kEUR per MW)"
            )
        elif self.driver is CostDriver.ABSOLUTE_KEUR and self.y1_amount_keur is None:
            raise ValueError(
                f"COST_TEMPLATE_AMOUNT_REQUIRED: ABSOLUTE_KEUR item {sid!r} needs "
                "y1_amount_keur (MISSING is not ZERO)"
            )
        _finite_non_negative(self.y1_amount_keur if self.y1_amount_keur is not None else 0.0,
                             "COST_TEMPLATE_VALUE_INVALID", f"item {sid!r} y1_amount_keur")
        _finite_non_negative(self.annual_inflation, "COST_TEMPLATE_VALUE_INVALID",
                             f"item {sid!r} annual_inflation")
        if self.driver_value is not None:
            _finite_non_negative(self.driver_value, "COST_TEMPLATE_VALUE_INVALID",
                                 f"item {sid!r} driver_value")
        for step_year, step_amount in self.step_changes:
            if not isinstance(step_year, int) or isinstance(step_year, bool) or step_year < 1:
                raise ValueError(
                    f"COST_TEMPLATE_STEP_INVALID: item {sid!r} step year must be a "
                    f"positive integer, got {step_year!r}"
                )
            _finite_non_negative(step_amount, "COST_TEMPLATE_VALUE_INVALID",
                                 f"item {sid!r} step_changes[{step_year}]")


@dataclass(frozen=True)
class CostTemplate:
    """Immutable, versioned cost assumption package.

    `version` is immutable once created; editing a template produces a new
    CostTemplate with the same `template_id` and an incremented version.
    """

    template_id: str
    version: int
    name: str
    technology: str                      # "solar" | "wind" | …
    kind: TemplateKind
    capex_items: tuple[CapexTemplateItem, ...] = ()
    opex_items: tuple[OpexTemplateItem, ...] = ()
    status: TemplateStatus = TemplateStatus.ACTIVE
    provenance: str = ""
    created_at: str = ""                 # ISO timestamp (informational)
    reference_capacity_mw: Optional[float] = None   # GENERIC templates
    source_project_ref: Optional[str] = None        # CLIENT templates
    _schema: str = "finco-cost-template-1"

    def validate(self) -> None:
        if not self.template_id or not self.template_id.strip():
            raise ValueError("COST_TEMPLATE_ID_REQUIRED: template_id is required")
        if not isinstance(self.version, int) or isinstance(self.version, bool) or self.version < 1:
            raise ValueError(
                f"COST_TEMPLATE_VERSION_INVALID: version must be an integer >= 1, "
                f"got {self.version!r}"
            )
        if self.kind is TemplateKind.CLIENT and self.source_project_ref is None:
            raise ValueError(
                "COST_TEMPLATE_CLIENT_SOURCE_REQUIRED: a CLIENT template must "
                "record its source project reference"
            )
        if self.reference_capacity_mw is not None:
            _finite_non_negative(self.reference_capacity_mw, "COST_TEMPLATE_VALUE_INVALID",
                                 "reference_capacity_mw")
        seen: set[str] = set()
        for item in self.capex_items:
            item.validate()
            if item.item_id in seen:
                raise ValueError(
                    f"COST_TEMPLATE_ITEM_ID_DUPLICATE: CAPEX item id "
                    f"{item.item_id!r} appears more than once"
                )
            seen.add(item.item_id)
        seen_opex: set[str] = set()
        for item in self.opex_items:
            item.validate()
            if item.item_id in seen_opex:
                raise ValueError(
                    f"COST_TEMPLATE_ITEM_ID_DUPLICATE: OPEX item id "
                    f"{item.item_id!r} appears more than once"
                )
            if item.item_id in seen:
                raise ValueError(
                    f"COST_TEMPLATE_ITEM_ID_DUPLICATE: item id {item.item_id!r} is "
                    "used across CAPEX and OPEX"
                )
            seen_opex.add(item.item_id)
            seen.add(item.item_id)

    @staticmethod
    def create(
        *,
        template_id: str,
        version: int,
        name: str,
        technology: str,
        kind: TemplateKind,
        capex_items: tuple[CapexTemplateItem, ...] | list[CapexTemplateItem] = (),
        opex_items: tuple[OpexTemplateItem, ...] | list[OpexTemplateItem] = (),
        **kwargs,
    ) -> "CostTemplate":
        template = CostTemplate(
            template_id=template_id,
            version=version,
            name=name,
            technology=technology,
            kind=kind,
            capex_items=tuple(capex_items),
            opex_items=tuple(opex_items),
            **kwargs,
        )
        template.validate()
        return template

    def ordered_capex_items(self) -> tuple[CapexTemplateItem, ...]:
        return tuple(sorted(self.capex_items, key=lambda i: (i.parent_code, i.child_code or "", i.item_id)))

    def ordered_opex_items(self) -> tuple[OpexTemplateItem, ...]:
        return tuple(sorted(self.opex_items, key=lambda i: (i.parent_code, i.child_code or "", i.item_id)))
