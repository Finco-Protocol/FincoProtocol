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


def _finite(value: float, code: str, label: str) -> float:
    """Finite numeric check (signed allowed).

    Correction A (defect 8): existing FINCO cost authorities accept finite
    signed amounts / inflation (e.g. the OPEX sub-line persistence authority
    validates numeric type only), so the template layer must not invent a
    blanket non-negative rule that would break exact client roundtrip.
    Percentage drivers keep their canonical bounds; capacity keeps its
    strict positive-finite bound.
    """
    if not isinstance(value, (int, float)) or isinstance(value, bool) \
            or not math.isfinite(float(value)):
        raise ValueError(f"{code}: {label} must be a finite number, got {value!r}")
    return float(value)


def _percent_points(value: float, code: str, label: str) -> float:
    """Percentage-point validation mirroring the canonical contingency
    authority: strict finite 0..100 (6.0 means 6%)."""
    v = _finite(value, code, label)
    if v < 0.0 or v > 100.0:
        raise ValueError(
            f"{code}: {label} must be within 0..100 percent points, got {value!r}"
        )
    return v


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
    # Correction A (defect 3): detail rows that DECOMPOSE / REPLACE their
    # canonical parent (presentation codes C.NN.NN / B.NN.NN) carry this
    # flag so materialization represents ONE economic amount and reuses the
    # existing reference-seed replacement semantics. User-added persistent
    # rows (C.NN.U###) are additive and never set it.
    replaces_parent: bool = False
    # Correction A (defect 2): approved CAPEX scalar metadata (VAT / WHT /
    # depreciation vocabulary of APPROVED_SCALAR_CAPEX_METADATA_KEYS).
    # Correction B (defect 6): re-validated through the existing sanitizer
    # authority at EVERY consumption boundary (create / validate / serialize
    # / resolve) - unknown or invalid keys always fail closed, and an
    # in-place mutation of this dict can never reach serialization or
    # materialization.
    scalar_metadata: dict = field(default_factory=dict)
    # Applicability addendum (A2): template default applicability. TRUE by
    # default; projects own their post-materialization is_active state.
    default_active: bool = True
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
        _finite(self.y0_share, "COST_TEMPLATE_VALUE_INVALID",
                f"item {sid!r} y0_share")
        for i, share in enumerate(self.spending_profile):
            _finite(share, "COST_TEMPLATE_VALUE_INVALID",
                    f"item {sid!r} spending_profile[{i}]")
        if self.amount_keur is not None:
            _finite(self.amount_keur, "COST_TEMPLATE_VALUE_INVALID",
                    f"item {sid!r} amount_keur")
        if self.driver_value is not None:
            _finite(self.driver_value, "COST_TEMPLATE_VALUE_INVALID",
                    f"item {sid!r} driver_value")
        if self.replaces_parent:
            if self.child_code is None:
                raise ValueError(
                    f"COST_TEMPLATE_REPLACEMENT_NEEDS_CHILD: item {sid!r} marks "
                    "replaces_parent but carries no child row code"
                )
            import re as _re
            # Correction B (defect 1): the CAPEX runtime treats EVERY active
            # sub-line as a breakdown/replacement of the canonical field
            # (zero base + fold), including user-created C.NN.U### rows.
            if not _re.match(r"^C\.\d{2}\.(?:\d{2}|U\d{3})$", self.child_code):
                raise ValueError(
                    f"COST_TEMPLATE_REPLACEMENT_CODE_INVALID: item {sid!r} marks "
                    f"replaces_parent with unrecognized child code "
                    f"{self.child_code!r}; expected C.NN.NN or C.NN.U###"
                )
        # Correction B (defect 6): fail closed on unknown/invalid scalar
        # metadata using the EXISTING FINCO sanitizer authority.
        if self.scalar_metadata:
            from app.persistence.capex_sub_lines import sanitize_scalar_capex_metadata
            object.__setattr__(
                self, "scalar_metadata",
                sanitize_scalar_capex_metadata(self.scalar_metadata),
            )
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
            # Correction A (defect 5): canonical FINCO percent points
            # (6.0 means 6%), strict 0..100 like the contingency authority.
            if self.driver_value is None:
                raise ValueError(
                    f"COST_TEMPLATE_VALUE_INVALID: item {sid!r} contingency "
                    "driver_value is required (MISSING is not ZERO)"
                )
            _percent_points(self.driver_value, "COST_TEMPLATE_VALUE_INVALID",
                            f"item {sid!r} contingency driver_value")
        elif self.driver is CostDriver.EUR_PER_MW:
            if self.driver_value is None:
                raise ValueError(
                    f"COST_TEMPLATE_DRIVER_VALUE_REQUIRED: EUR_PER_MW item {sid!r} "
                    "needs driver_value (kEUR per MW)"
                )
            _finite(self.driver_value, "COST_TEMPLATE_VALUE_INVALID",
                    f"item {sid!r} driver_value")
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
    # Correction A (defect 3): detail rows that DECOMPOSE / REPLACE their
    # canonical parent OpexItem (presentation codes B.NN.NN); user rows
    # (B.NN.U###) are additive and never set it.
    replaces_parent: bool = False
    # Correction B (defect 3): the CANONICAL OpexItem identity (its exact
    # name) that a decomposition row replaces - never the B.NN group code.
    # Required by the existing OPEX replacement fold
    # (source in {reference_seed, user_override} + reference_seed=True +
    # canonical_key=<canonical name>).
    canonical_parent_key: Optional[str] = None
    # Correction B (defect 3): mirrors the runtime replacement vocabulary
    # (source in {reference_seed, user_override} + reference_seed=True).
    reference_seed: bool = False
    # Applicability addendum (A2).
    default_active: bool = True

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
            # Correction A (defect 6): an explicit percentage value is
            # REQUIRED — None never collapses to zero. Canonical FINCO
            # percent points (6.0 means 6%); explicit 0 is a valid zero.
            if self.driver_value is None:
                raise ValueError(
                    f"COST_TEMPLATE_VALUE_REQUIRED: PERCENT_OF_OPEX item {sid!r} "
                    "needs driver_value in percent points (MISSING is not ZERO)"
                )
            _percent_points(self.driver_value, "COST_TEMPLATE_VALUE_INVALID",
                            f"item {sid!r} percentage driver_value")
        elif self.driver is CostDriver.EUR_PER_MW:
            if self.driver_value is None:
                raise ValueError(
                    f"COST_TEMPLATE_DRIVER_VALUE_REQUIRED: EUR_PER_MW item {sid!r} "
                    "needs driver_value (kEUR per MW)"
                )
            _finite(self.driver_value, "COST_TEMPLATE_VALUE_INVALID",
                    f"item {sid!r} driver_value")
        elif self.driver is CostDriver.ABSOLUTE_KEUR and self.y1_amount_keur is None:
            raise ValueError(
                f"COST_TEMPLATE_AMOUNT_REQUIRED: ABSOLUTE_KEUR item {sid!r} needs "
                "y1_amount_keur (MISSING is not ZERO)"
            )
        # Correction A (defect 8): finite-only for amounts / inflation /
        # steps — existing FINCO authorities accept finite signed values
        # (e.g. negative inflation), so no blanket non-negative rule.
        if self.y1_amount_keur is not None:
            _finite(self.y1_amount_keur, "COST_TEMPLATE_VALUE_INVALID",
                    f"item {sid!r} y1_amount_keur")
        _finite(self.annual_inflation, "COST_TEMPLATE_VALUE_INVALID",
                f"item {sid!r} annual_inflation")
        for step_year, step_amount in self.step_changes:
            if not isinstance(step_year, int) or isinstance(step_year, bool) or step_year < 1:
                raise ValueError(
                    f"COST_TEMPLATE_STEP_INVALID: item {sid!r} step year must be a "
                    f"positive integer, got {step_year!r}"
                )
            _finite(step_amount, "COST_TEMPLATE_VALUE_INVALID",
                    f"item {sid!r} step_changes[{step_year}]")
        if self.replaces_parent:
            if self.child_code is None:
                raise ValueError(
                    f"COST_TEMPLATE_REPLACEMENT_NEEDS_CHILD: item {sid!r} marks "
                    "replaces_parent but carries no child row code"
                )
            import re as _re
            if not _re.match(r"^B\.\d{2}\.\d{2}$", self.child_code):
                raise ValueError(
                    f"COST_TEMPLATE_REPLACEMENT_CODE_INVALID: item {sid!r} marks "
                    f"replaces_parent with non-presentation child code "
                    f"{self.child_code!r}; only B.NN.NN detail rows decompose a "
                    "canonical parent (user B.NN.U### rows are additive)"
                )
            # Correction B (defect 3): the replacement fold keys on the
            # CANONICAL OpexItem identity (its exact name), never on the
            # B.NN group presentation code.
            if not self.canonical_parent_key or not self.canonical_parent_key.strip():
                raise ValueError(
                    f"COST_TEMPLATE_CANONICAL_PARENT_KEY_REQUIRED: decomposition "
                    f"item {sid!r} must name the canonical OpexItem it replaces "
                    "(canonical_parent_key), not the B.NN group code"
                )
            if self.canonical_parent_key.startswith("B.") and "." in self.canonical_parent_key:
                raise ValueError(
                    f"COST_TEMPLATE_CANONICAL_PARENT_KEY_INVALID: item {sid!r} "
                    f"canonical_parent_key {self.canonical_parent_key!r} looks like "
                    "a group code; use the exact canonical OpexItem name"
                )


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
    # Applicability addendum (A9): contingency applicability. INACTIVE
    # retains the configured percentage but the authority is not applied —
    # never conflated with an explicit 0.0% authority. C.17/C.18 have no
    # user applicability at all (runtime-derived).
    capex_contingency_active: bool = True
    opex_contingency_active: bool = True
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
            _finite(self.reference_capacity_mw, "COST_TEMPLATE_VALUE_INVALID",
                    "reference_capacity_mw")
            if self.reference_capacity_mw <= 0:
                raise ValueError(
                    f"COST_TEMPLATE_VALUE_INVALID: reference_capacity_mw must be "
                    f"strictly positive, got {self.reference_capacity_mw!r}"
                )
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
