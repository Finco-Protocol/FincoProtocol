"""Model V2 Assumption Register - typed, deterministic, read-only foundation.

Workflow 04 scope. The register is an observability / explainability layer
over the EXISTING canonical input authority (``finco_core.inputs.ProjectInputs``
and the Model V2 RevenuePlan contracts). It is NOT a second financial engine:

  - it never computes, derives, infers or defaults a financial value;
  - it exposes only real input authorities that exist on the canonical input
    objects (explicit collectors - never a blind dataclass dump);
  - MISSING is represented distinctly from ZERO (``ValuePresence``);
  - NaN/Inf fail closed and are never serialized;
  - provenance is never guessed: when it cannot be proved it is UNKNOWN;
  - display labels never become identity (``assumption_id`` is a stable
    canonical path independent of labels);
  - scenario overrides are marked only when the caller proves them.

Working Copy vs Last Run is preserved explicitly: a register is built for
exactly one ``AssumptionContextKind``. A RUN_BOUND register REQUIRES a
complete ``RunIdentity`` (snapshot id + composite hash + workbook/engine
versions) supplied by the caller from committed run authority; the register
never labels current Working Copy assumptions as historical Last Run inputs.

Deterministic identity: the same canonical input state produces a
byte-identical serialized register with a stable sha256 fingerprint. The
fingerprint is a content-integrity helper only - it never replaces run
identity (``CompositeWorkbookIdentity.composite_hash`` /
``last_runtime_snapshot_id``), workbook identity or project identity, which
are linked (not replaced) via ``RegisterContext``.

Provenance vocabulary is grounded in the repository: ``USER_INPUT`` /
``FACTORY_DEFAULT`` reuse the F10 canonical vocabulary
(app/v2/provenance.py); ``REFERENCE_SEED`` reuses the reference-seed service
vocabulary; ``SCENARIO_OVERRIDE`` reuses the canonical scenario-override
state concept; everything else is UNKNOWN.

Derived construction-layer values on ``CapexStructure`` (idc_keur,
commitment_fees_keur, bank_fees_keur, other_financial_keur, vat_costs_keur,
reserve_accounts_keur) and ``FinancingParams.shl_idc_keur``, and the derived
tax object ``TaxParams.construction_pl``, are deliberately NOT exposed: the
canonical dataclasses document them as derived outputs, not primary
assumptions. Deprecated non-authorities (``target_min_dscr``,
``flat_dscr_target``, ``shl_cap_applies``) are likewise excluded.

Governance: this module is an exact-path authorized support file under
docs/model_v2/ACTIVE_EPIC_SCOPE.json. No engine, persistence, or Workflow 02
RevenuePlan code is modified (RevenuePlan is READ through its public
contracts).
"""
from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from enum import Enum
from typing import Any, Iterable, Mapping

from domain.inputs import ProjectInputs
from domain.revenue.plan import RevenuePlan

ASSUMPTION_REGISTER_SCHEMA_ID = "finco.model-v2.assumption-register"
ASSUMPTION_REGISTER_SCHEMA_VERSION = 1


def engine_version() -> str:
    """Canonical engine version (financial_engine.version authority)."""
    from financial_engine.version import ENGINE_VERSION

    return str(ENGINE_VERSION)


def workbook_version() -> str:
    """Canonical workbook version (app.workbook.registry authority)."""
    from app.workbook.registry import WORKBOOK

    return str(getattr(WORKBOOK, "version", "unknown"))


class AssumptionSourceKind(str, Enum):
    """Typed provenance classification grounded in repository vocabulary."""

    USER_INPUT = "USER_INPUT"                # F10 vocabulary (app/v2/provenance.py)
    FACTORY_DEFAULT = "FACTORY_DEFAULT"      # F10 vocabulary
    REFERENCE_SEED = "REFERENCE_SEED"        # reference-seed service vocabulary
    SCENARIO_OVERRIDE = "SCENARIO_OVERRIDE"  # proven scenario-override state
    UNKNOWN = "UNKNOWN"                      # provenance could not be proved


class AssumptionContextKind(str, Enum):
    """Working Copy vs Last Run - FINCO's central product contract."""

    WORKING_COPY = "WORKING_COPY"
    RUN_BOUND = "RUN_BOUND"


class ValuePresence(str, Enum):
    """MISSING must remain distinct from ZERO."""

    PRESENT = "PRESENT"
    MISSING = "MISSING"


_STATE_PROVENANCE_ALLOWED = frozenset(
    {
        AssumptionSourceKind.USER_INPUT,
        AssumptionSourceKind.FACTORY_DEFAULT,
        AssumptionSourceKind.REFERENCE_SEED,
        AssumptionSourceKind.UNKNOWN,
    }
)


def canonical_json(payload: Any) -> str:
    """Deterministic JSON text: sorted keys, ASCII, no NaN/Inf, explicit None."""
    return json.dumps(
        payload,
        sort_keys=True,
        ensure_ascii=True,
        allow_nan=False,
        separators=(",", ":"),
    )


__all__ = [
    "ASSUMPTION_REGISTER_SCHEMA_VERSION",
    "ASSUMPTION_REGISTER_SCHEMA_ID",
    "AssumptionContextKind",
    "AssumptionEntry",
    "AssumptionRegister",
    "AssumptionSourceKind",
    "ContingencyAuthorityRef",
    "RegisterContext",
    "RunIdentity",
    "ValuePresence",
    "build_assumption_register",
    "canonical_json",
    "engine_version",
    "entry_from_dict",
    "enum_text",
    "run_identity_from_dict",
    "workbook_version",
]

# ---------------------------------------------------------------------------
# Entry contract
# ---------------------------------------------------------------------------

_ENTRY_FIELDS = (
    "assumption_id",
    "section",
    "canonical_path",
    "label",
    "value",
    "value_presence",
    "value_type",
    "unit",
    "source_kind",
    "source_ref",
    "snapshot_key",
    "override_proven",
    "lineage_ref",
    "notes",
)


@dataclass(frozen=True)
class AssumptionEntry:
    """One exposed input authority. Immutable; deterministically ordered."""

    assumption_id: str
    section: str
    canonical_path: str
    label: str
    value: str | int | float | bool | list | dict | None
    value_presence: ValuePresence
    value_type: str
    unit: str
    source_kind: AssumptionSourceKind
    source_ref: str | None = None
    snapshot_key: str | None = None
    override_proven: bool | None = None
    lineage_ref: str | None = None
    notes: str | None = None

    def __post_init__(self) -> None:
        _validate_entry(self)

    def to_dict(self) -> dict:
        return {name: getattr(self, name) for name in _ENTRY_FIELDS}


def _check_finite(assumption_id: str, value: Any) -> None:
    """Reject non-finite floats anywhere inside a value (never serialize NaN)."""
    if value is None or isinstance(value, bool):
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError(
                f"ASSUMPTION_VALUE_NOT_FINITE: {assumption_id} = {value!r}; "
                "NaN/Inf never enter the register."
            )
    elif isinstance(value, (list, tuple)):
        for item in value:
            _check_finite(assumption_id, item)
    elif isinstance(value, dict):
        for item in value.values():
            _check_finite(assumption_id, item)


def _scalar_type(value: Any) -> str:
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, int):
        return "int"
    if isinstance(value, float):
        return "float"
    if isinstance(value, str):
        return "str"
    raise ValueError(f"ASSUMPTION_VALUE_TYPE_UNSUPPORTED: {type(value).__name__}")


def enum_text(value: Any) -> str | None:
    """Canonical text of an enum member; None passes through."""
    if value is None:
        return None
    return value.value if isinstance(value, Enum) else str(value)


def _validate_entry(entry: AssumptionEntry) -> None:
    _check_finite(entry.assumption_id, entry.value)
    if entry.value is None and entry.value_presence is not ValuePresence.MISSING:
        raise ValueError(
            f"ASSUMPTION_ENTRY_INVALID: {entry.assumption_id} has no value but "
            "is not marked MISSING - MISSING must remain distinct from ZERO."
        )
    if entry.value is not None and entry.value_presence is not ValuePresence.PRESENT:
        raise ValueError(
            f"ASSUMPTION_ENTRY_INVALID: {entry.assumption_id} has a value but "
            "is not marked PRESENT."
        )


def entry_from_dict(raw: Mapping[str, Any]) -> AssumptionEntry:
    """Fail-closed deserialization: exact field set, canonical enums only."""
    keys = set(raw)
    expected = set(_ENTRY_FIELDS)
    if keys != expected:
        raise ValueError(
            "ASSUMPTION_ENTRY_INVALID: field mismatch for "
            f"{raw.get('assumption_id')!r} "
            f"(missing={sorted(expected - keys)}, unknown={sorted(keys - expected)})"
        )
    try:
        presence = ValuePresence(raw["value_presence"])
        source_kind = AssumptionSourceKind(raw["source_kind"])
    except ValueError as exc:
        raise ValueError(
            "ASSUMPTION_ENTRY_INVALID: unknown enum value in entry "
            f"{raw.get('assumption_id')!r} ({exc})"
        ) from None
    kwargs = {name: raw[name] for name in _ENTRY_FIELDS}
    kwargs["value_presence"] = presence
    kwargs["source_kind"] = source_kind
    return AssumptionEntry(**kwargs)


# ---------------------------------------------------------------------------
# Run identity + contingency authority ref
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RunIdentity:
    """Committed run authority supplied by the caller - never inferred.

    Mirrors the committed Last Run identity family on workspace_states:
    ``last_runtime_snapshot_id`` + ``last_runtime_composite_hash`` plus the
    workbook/engine versions carried in ``last_runtime_identity``.
    """

    snapshot_id: str
    composite_hash: str
    workbook_version: str
    engine_version: str
    project_id: str | None = None
    scenario_id: str | None = None

    def to_dict(self) -> dict:
        return {
            "snapshot_id": self.snapshot_id,
            "composite_hash": self.composite_hash,
            "workbook_version": self.workbook_version,
            "engine_version": self.engine_version,
            "project_id": self.project_id,
            "scenario_id": self.scenario_id,
        }


_IDENTITY_REQUIRED_FIELDS = (
    "snapshot_id",
    "composite_hash",
    "workbook_version",
    "engine_version",
)


def _validate_run_identity(identity: RunIdentity) -> None:
    for name in _IDENTITY_REQUIRED_FIELDS:
        value = getattr(identity, name)
        if not isinstance(value, str) or not value.strip():
            raise ValueError(
                f"RUN_IDENTITY_INCOMPLETE: {name} must be a non-empty string; "
                "a run-bound register cannot be built without committed run "
                "authority."
            )


def run_identity_from_dict(raw: Mapping[str, Any]) -> RunIdentity:
    try:
        identity = RunIdentity(
            snapshot_id=raw["snapshot_id"],
            composite_hash=raw["composite_hash"],
            workbook_version=raw["workbook_version"],
            engine_version=raw["engine_version"],
            project_id=raw.get("project_id"),
            scenario_id=raw.get("scenario_id"),
        )
    except KeyError as exc:
        raise ValueError(
            f"RUN_IDENTITY_INCOMPLETE: missing {exc.args[0]!r}"
        ) from None
    _validate_run_identity(identity)
    return identity


@dataclass(frozen=True)
class ContingencyAuthorityRef:
    """Typed contingency authority read by the caller from replay metadata.

    Percentages are FRACTIONS (0.02 = 2%), matching the typed authority in
    app/contingency_authority.py; entry units state this explicitly so that
    percentage semantics never collapse into percent-scaled or absolute
    values.
    """

    capex_pct: float | None
    opex_pct: float | None
    source_ref: str


# ---------------------------------------------------------------------------
# Register context
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RegisterContext:
    """Where this register comes from. Never mixes Working Copy and Last Run."""

    context_kind: AssumptionContextKind
    state_provenance: AssumptionSourceKind = AssumptionSourceKind.UNKNOWN
    run_identity: RunIdentity | None = None
    workbook_composite_hash: str | None = None
    scenario_override_ids: frozenset[str] | None = None
    revenue_plan: RevenuePlan | None = None
    revenue_plan_source_ref: str | None = None
    contingency_authority: ContingencyAuthorityRef | None = None
    notes: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.context_kind, AssumptionContextKind):
            raise ValueError(
                "REGISTER_CONTEXT_INVALID: context_kind must be an "
                "AssumptionContextKind"
            )
        if self.state_provenance not in _STATE_PROVENANCE_ALLOWED:
            raise ValueError(
                "REGISTER_CONTEXT_INVALID: state_provenance describes the input "
                "STATE (USER_INPUT / FACTORY_DEFAULT / REFERENCE_SEED / UNKNOWN); "
                "SCENARIO_OVERRIDE can only mark individual entries proven via "
                "scenario_override_ids."
            )
        if self.context_kind is AssumptionContextKind.RUN_BOUND:
            if self.run_identity is None:
                raise ValueError(
                    "RUN_IDENTITY_INCOMPLETE: a RUN_BOUND register requires a "
                    "complete RunIdentity from committed run authority."
                )
            _validate_run_identity(self.run_identity)
        elif self.run_identity is not None:
            raise ValueError(
                "REGISTER_CONTEXT_INVALID: a WORKING_COPY register must not "
                "carry run identity - Working Copy is not Last Run."
            )
        if self.scenario_override_ids is not None and not isinstance(
            self.scenario_override_ids, frozenset
        ):
            object.__setattr__(
                self,
                "scenario_override_ids",
                frozenset(self.scenario_override_ids),
            )
        if self.revenue_plan is not None and not isinstance(
            self.revenue_plan, RevenuePlan
        ):
            raise ValueError(
                "REGISTER_CONTEXT_INVALID: revenue_plan must be a "
                "domain.revenue.plan.RevenuePlan (the public Workflow 02 "
                "authority)."
            )
        if self.contingency_authority is not None:
            for name in ("capex_pct", "opex_pct"):
                pct = getattr(self.contingency_authority, name)
                if pct is None:
                    continue
                if isinstance(pct, bool) or not math.isfinite(float(pct)):
                    raise ValueError(
                        "REGISTER_CONTEXT_INVALID: contingency "
                        f"{name} must be None or a finite fraction."
                    )

    @classmethod
    def for_working_copy(
        cls,
        *,
        state_provenance: AssumptionSourceKind = AssumptionSourceKind.UNKNOWN,
        workbook_composite_hash: str | None = None,
        scenario_override_ids: Iterable[str] | None = None,
        revenue_plan: RevenuePlan | None = None,
        revenue_plan_source_ref: str | None = None,
        contingency_authority: ContingencyAuthorityRef | None = None,
        notes: str | None = None,
    ) -> "RegisterContext":
        """Working Copy register context (current draft/saved state)."""
        return cls(
            context_kind=AssumptionContextKind.WORKING_COPY,
            state_provenance=state_provenance,
            workbook_composite_hash=workbook_composite_hash,
            scenario_override_ids=(
                None
                if scenario_override_ids is None
                else frozenset(scenario_override_ids)
            ),
            revenue_plan=revenue_plan,
            revenue_plan_source_ref=revenue_plan_source_ref,
            contingency_authority=contingency_authority,
            notes=notes,
        )

    @classmethod
    def for_run_bound(
        cls,
        *,
        run_identity: RunIdentity,
        state_provenance: AssumptionSourceKind = AssumptionSourceKind.UNKNOWN,
        revenue_plan: RevenuePlan | None = None,
        revenue_plan_source_ref: str | None = None,
        contingency_authority: ContingencyAuthorityRef | None = None,
        notes: str | None = None,
    ) -> "RegisterContext":
        """Run-bound register context (assumptions bound to one committed run)."""
        return cls(
            context_kind=AssumptionContextKind.RUN_BOUND,
            state_provenance=state_provenance,
            run_identity=run_identity,
            revenue_plan=revenue_plan,
            revenue_plan_source_ref=revenue_plan_source_ref,
            contingency_authority=contingency_authority,
            notes=notes,
        )

    def to_dict(self) -> dict:
        return {
            "context_kind": self.context_kind.value,
            "state_provenance": self.state_provenance.value,
            "run_identity": (
                self.run_identity.to_dict() if self.run_identity is not None else None
            ),
            "workbook_composite_hash": self.workbook_composite_hash,
            "scenario_override_proof_supplied": self.scenario_override_ids is not None,
            "revenue_plan_lineage": self.revenue_plan_source_ref,
            "contingency_authority_source_ref": (
                self.contingency_authority.source_ref
                if self.contingency_authority is not None
                else None
            ),
            "notes": self.notes,
        }


# ---------------------------------------------------------------------------
# Collector (enforces unique, stable, deterministic identity)
# ---------------------------------------------------------------------------


class _Section:
    """Section-bound thin wrapper over :class:`_Collector`.

    Reduces per-entry token surface so each collector line states only what
    is semantically meaningful.
    """

    def __init__(self, collector: "_Collector", section: str) -> None:
        self._collector = collector
        self._section = section

    def add(
        self,
        assumption_id: str,
        value: Any,
        *,
        path: str,
        label: str,
        unit: str,
        value_type: str | None = None,
        source_ref: str | None = None,
        snapshot_key: str | None = None,
        lineage_ref: str | None = None,
        notes: str | None = None,
    ) -> None:
        self._collector.add(
            assumption_id=assumption_id,
            value=value,
            section=self._section,
            canonical_path=path,
            label=label,
            unit=unit,
            value_type=value_type,
            source_ref=source_ref,
            snapshot_key=snapshot_key,
            lineage_ref=lineage_ref,
            notes=notes,
        )

    def enum_add(self, assumption_id: str, value: Any, *, path: str, label: str) -> None:
        self.add(assumption_id, enum_text(value), path=path, label=label, unit="n/a")


class _Collector:
    """Accumulates entries with fail-closed normalization."""

    def __init__(self, context: RegisterContext) -> None:
        self._context = context
        self._entries: list[AssumptionEntry] = []
        self._ids: set[str] = set()

    def section(self, name: str) -> _Section:
        return _Section(self, name)

    def add(
        self,
        *,
        assumption_id: str,
        value: Any,
        section: str,
        canonical_path: str,
        label: str,
        unit: str,
        value_type: str | None = None,
        source_ref: str | None = None,
        snapshot_key: str | None = None,
        lineage_ref: str | None = None,
        notes: str | None = None,
    ) -> None:
        if assumption_id in self._ids:
            raise ValueError(
                f"ASSUMPTION_ID_DUPLICATE: {assumption_id} emitted twice - "
                "register identity must be unique."
            )
        self._ids.add(assumption_id)
        if value is None:
            presence = ValuePresence.MISSING
            resolved: Any = None
            resolved_type = value_type or "str"
        elif isinstance(value, (list, tuple)):
            if len(value) == 0:
                presence = ValuePresence.MISSING
                resolved = None
                resolved_type = value_type or "array"
            else:
                presence = ValuePresence.PRESENT
                resolved = list(value)
                resolved_type = value_type or "array"
        elif isinstance(value, (int, float)) and not isinstance(value, bool):
            presence = ValuePresence.PRESENT
            resolved = value
            resolved_type = value_type or ("int" if isinstance(value, int) else "float")
        else:
            presence = ValuePresence.PRESENT
            resolved = value
            resolved_type = value_type or _scalar_type(value)
        _check_finite(assumption_id, resolved)
        if resolved_type not in ("bool", "int", "float", "str", "array", "object"):
            raise ValueError(
                f"ASSUMPTION_VALUE_TYPE_INVALID: {assumption_id} type "
                f"{resolved_type!r}"
            )
        source_kind = self._context.state_provenance
        override_proven: bool | None = None
        if self._context.scenario_override_ids is not None:
            override_proven = assumption_id in self._context.scenario_override_ids
            if override_proven:
                source_kind = AssumptionSourceKind.SCENARIO_OVERRIDE
        self._entries.append(
            AssumptionEntry(
                assumption_id=assumption_id,
                section=section,
                canonical_path=canonical_path,
                label=label,
                value=resolved,
                value_presence=presence,
                value_type=resolved_type,
                unit=unit,
                source_kind=source_kind,
                source_ref=source_ref,
                snapshot_key=snapshot_key,
                override_proven=override_proven,
                lineage_ref=lineage_ref,
                notes=notes,
            )
        )

    def finish(self) -> tuple[AssumptionEntry, ...]:
        return tuple(sorted(self._entries, key=lambda e: e.assumption_id))


# ---------------------------------------------------------------------------
# Explicit collectors - semantic mapping, never blind reflection
# ---------------------------------------------------------------------------

_CAPEX_ITEM_SLOTS: tuple[tuple[str, str], ...] = (
    ("epc_contract", "EPC Contract"),
    ("production_units", "Production Units"),
    ("epc_other", "EPC Other"),
    ("grid_connection", "Grid Connection"),
    ("ops_prep", "Operations Preparation"),
    ("insurances", "Insurances"),
    ("lease_tax", "Lease Tax"),
    ("construction_mgmt_a", "Construction Management A"),
    ("commissioning", "Commissioning"),
    ("audit_legal", "Audit & Legal"),
    ("construction_mgmt_b", "Construction Management B"),
    ("contingencies", "Contingencies"),
    ("taxes", "Taxes (CAPEX)"),
    ("project_acquisition", "Project Acquisition"),
    ("project_rights", "Project Rights"),
)


def _collect_project(inputs: ProjectInputs, sec) -> None:
    info = inputs.info
    sec.add("project.country_iso", info.country_iso,
            path="info.country_iso", label="Country (ISO)", unit="n/a")
    sec.add("project.financial_close", info.financial_close.isoformat()
            if info.financial_close is not None else None,
            path="info.financial_close", label="Financial Close",
            unit="date", value_type="str")
    sec.add("project.cod_date", info.cod_date.isoformat()
            if info.cod_date is not None else None,
            path="info.cod_date", label="Commercial Operation Date",
            unit="date", value_type="str")
    sec.add("project.construction_months", info.construction_months,
            path="info.construction_months", label="Construction Period",
            unit="months")
    sec.add("project.horizon_years", info.horizon_years,
            path="info.horizon_years", label="Model Horizon", unit="years")
    sec.enum_add("project.period_frequency", info.period_frequency,
                 path="info.period_frequency", label="Period Frequency")
    sec.enum_add("project.period_axis_convention", info.period_axis_convention,
                 path="info.period_axis_convention", label="Period Axis Convention")
    # Project identity (name/company/code) is deliberately NOT exposed:
    # identity must never masquerade as an input authority.


def _collect_technical(inputs: ProjectInputs, sec) -> None:
    tech = inputs.technical
    sec.add("technical.capacity_mw", tech.capacity_mw,
            path="technical.capacity_mw", label="Installed Capacity", unit="MW")
    sec.add("technical.yield_scenario", tech.yield_scenario,
            path="technical.yield_scenario", label="Yield Scenario", unit="n/a")
    sec.add("technical.operating_hours_p50", tech.operating_hours_p50,
            path="technical.operating_hours_p50", label="Operating Hours (P50)",
            unit="hours")
    sec.add("technical.operating_hours_p90_1y", tech.operating_hours_p90_1y,
            path="technical.operating_hours_p90_1y",
            label="Operating Hours (P90 1-year)", unit="hours")
    sec.add("technical.operating_hours_p90_10y", tech.operating_hours_p90_10y,
            path="technical.operating_hours_p90_10y",
            label="Operating Hours (P90 10-year)", unit="hours")
    sec.add("technical.operating_hours_p99_1y", tech.operating_hours_p99_1y,
            path="technical.operating_hours_p99_1y",
            label="Operating Hours (P99 1-year)", unit="hours")
    sec.add("technical.pv_degradation", tech.pv_degradation,
            path="technical.pv_degradation", label="Degradation (PV)",
            unit="fraction_per_year")
    sec.add("technical.bess_degradation", tech.bess_degradation,
            path="technical.bess_degradation", label="Degradation (BESS)",
            unit="fraction_per_year")
    sec.add("technical.plant_availability", tech.plant_availability,
            path="technical.plant_availability", label="Plant Availability",
            unit="fraction")
    sec.add("technical.grid_availability", tech.grid_availability,
            path="technical.grid_availability", label="Grid Availability",
            unit="fraction")
    sec.add("technical.bess_enabled", tech.bess_enabled,
            path="technical.bess_enabled", label="BESS Enabled", unit="bool")
    if tech.bess is not None:
        bess = tech.bess
        _BESS_SLOTS = (
            ("power_mw", "BESS Power", "MW"),
            ("energy_mwh", "BESS Energy", "MWh"),
            ("cycles_per_year", "BESS Cycles per Year", "cycles/year"),
            ("round_trip_efficiency", "BESS Round-Trip Efficiency", "fraction"),
            ("availability", "BESS Availability", "fraction"),
            ("annual_degradation", "BESS Annual Degradation", "fraction_per_year"),
            ("arbitrage_spread_eur_mwh", "BESS Arbitrage Spread", "EUR/MWh"),
            ("augmentation_capex_keur", "BESS Augmentation CAPEX", "kEUR"),
            ("depth_of_discharge", "BESS Depth of Discharge", "fraction"),
            ("cycle_life", "BESS Cycle Life", "cycles"),
            ("replacement_year", "BESS Replacement Year", "year"),
        )
        for slot, label, unit in _BESS_SLOTS:
            sec.add(f"technical.bess.{slot}", getattr(bess, slot),
                    path=f"technical.bess.{slot}", label=label, unit=unit)


def _collect_revenue(inputs: ProjectInputs, sec) -> None:
    revenue = inputs.revenue
    sec.add("revenue.ppa_base_tariff", revenue.ppa_base_tariff,
            path="revenue.ppa_base_tariff", label="PPA Base Tariff",
            unit="EUR/MWh", snapshot_key="rev_ppa_base_tariff")
    sec.add("revenue.ppa_term_years", revenue.ppa_term_years,
            path="revenue.ppa_term_years", label="PPA Term", unit="years",
            snapshot_key="rev_ppa_term_years")
    sec.add("revenue.ppa_index", revenue.ppa_index,
            path="revenue.ppa_index", label="PPA Indexation",
            unit="fraction_per_year", snapshot_key="rev_ppa_index")
    sec.add("revenue.ppa_production_share", revenue.ppa_production_share,
            path="revenue.ppa_production_share", label="PPA Production Share",
            unit="fraction", snapshot_key="rev_ppa_production_share")
    sec.add("revenue.ppa_indexation_start_policy",
            revenue.ppa_indexation_start_policy,
            path="revenue.ppa_indexation_start_policy",
            label="PPA Indexation Start Policy", unit="n/a")
    sec.add("revenue.ppa_indexation_start_date",
            (revenue.ppa_indexation_start_date.isoformat()
             if revenue.ppa_indexation_start_date is not None else None),
            path="revenue.ppa_indexation_start_date",
            label="PPA Indexation Start Date", unit="date", value_type="str")
    sec.add("revenue.market_scenario", revenue.market_scenario,
            path="revenue.market_scenario", label="Merchant Market Scenario",
            unit="n/a", snapshot_key="rev_market_scenario")
    sec.add("revenue.market_prices_curve", list(revenue.market_prices_curve),
            path="revenue.market_prices_curve", label="Merchant Price Curve",
            unit="EUR/MWh", snapshot_key="rev_market_prices_curve")
    sec.add("revenue.market_inflation", revenue.market_inflation,
            path="revenue.market_inflation", label="Merchant Price Inflation",
            unit="fraction_per_year", snapshot_key="rev_market_inflation")
    sec.add("revenue.market_price_calendar_start_year",
            revenue.market_price_calendar_start_year,
            path="revenue.market_price_calendar_start_year",
            label="Merchant Calendar Start Year", unit="year")
    sec.add("revenue.market_prices_by_calendar_year",
            list(revenue.market_prices_by_calendar_year_eur_mwh),
            path="revenue.market_prices_by_calendar_year_eur_mwh",
            label="Merchant Prices by Calendar Year", unit="EUR/MWh")
    sec.add("revenue.ppa_tariff_by_operating_period",
            list(revenue.ppa_tariff_by_operating_period),
            path="revenue.ppa_tariff_by_operating_period",
            label="PPA Tariff by Operating Period", unit="EUR/MWh")
    sec.add("revenue.balancing_cost_pv", revenue.balancing_cost_pv,
            path="revenue.balancing_cost_pv", label="Balancing Cost (PV)",
            unit="fraction", snapshot_key="rev_balancing_cost_pv")
    sec.add("revenue.balancing_cost_bess", revenue.balancing_cost_bess,
            path="revenue.balancing_cost_bess", label="Balancing Cost (BESS)",
            unit="fraction", snapshot_key="rev_balancing_cost_bess")
    sec.add("revenue.balancing_cost_wind", revenue.balancing_cost_wind_eur_mwh,
            path="revenue.balancing_cost_wind_eur_mwh",
            label="Balancing Cost (Wind)", unit="EUR/MWh")
    sec.add("revenue.balancing_cost_explicit", revenue.balancing_cost_eur_per_mwh,
            path="revenue.balancing_cost_eur_per_mwh",
            label="Balancing Cost (explicit)", unit="EUR/MWh")
    sec.add("revenue.co2_enabled", revenue.co2_enabled,
            path="revenue.co2_enabled", label="CO2 Certificates Enabled",
            unit="bool")
    sec.add("revenue.co2_price", revenue.co2_price_eur,
            path="revenue.co2_price_eur", label="CO2 Price", unit="EUR/MWh")
    sec.add("revenue.co2_certificate_price", revenue.co2_certificate_price_eur_per_mwh,
            path="revenue.co2_certificate_price_eur_per_mwh",
            label="CO2 Certificate Price", unit="EUR/MWh")
    sec.add("revenue.first_merchant_operating_period",
            revenue.first_merchant_operating_period_index,
            path="revenue.first_merchant_operating_period_index",
            label="First Merchant Operating Period", unit="period")


def _collect_revenue_plan(context, sec) -> None:
    plan = context.revenue_plan
    if plan is None:
        return
    lineage = (context.revenue_plan_source_ref
               or "caller-supplied RevenuePlan authority")
    plan.validate()

    def add(sid, name, label, value, unit):
        sec.add(f"revenue.plan.stream.{sid}.{name}", value,
                path=f"revenue_plan.streams[{sid}].{name}",
                label=label, unit=unit, lineage_ref=lineage)

    for stream in plan.ordered_streams():
        sid = stream.stream_id
        add(sid, "stream_type", f"Revenue Stream Type ({sid})",
            enum_text(stream.stream_type), "n/a")
        add(sid, "contract_role", f"Revenue Stream Contract Role ({sid})",
            enum_text(stream.contract_role), "n/a")
        add(sid, "enabled", f"Revenue Stream Enabled ({sid})",
            stream.enabled, "bool")
        add(sid, "start_year", f"Revenue Stream Start Year ({sid})",
            stream.start_year, "year")
        add(sid, "term_years", f"Revenue Stream Term ({sid})",
            stream.term_years, "years")
        add(sid, "allocation_group", f"Revenue Stream Allocation Group ({sid})",
            stream.allocation_group, "n/a")
        add(sid, "volume_share", f"Revenue Stream Volume Share ({sid})",
            stream.volume_share, "fraction")
        add(sid, "reference_stream_id", f"Revenue Stream Reference ({sid})",
            stream.reference_stream_id, "n/a")
        add(sid, "lender_eligible", f"Revenue Stream Lender Eligible ({sid})",
            stream.lender_eligible, "bool")
        price_authority = (
            "ppa" if stream.ppa is not None
            else "merchant" if stream.merchant is not None
            else "fit" if stream.fit is not None
            else "cfd" if stream.cfd is not None
            else "indexed_fit"
            if stream.indexed_fit_base_tariff_eur_mwh is not None
            else None
        )
        add(sid, "price_authority", f"Revenue Stream Price Authority ({sid})",
            price_authority, "n/a")
        if stream.ppa is not None:
            add(sid, "ppa_base_price", f"Stream PPA Base Price ({sid})",
                stream.ppa.ppa_base_price_eur_mwh, "EUR/MWh")
            add(sid, "ppa_price_index", f"Stream PPA Indexation ({sid})",
                stream.ppa.ppa_price_index, "fraction_per_year")
            add(sid, "ppa_term_years", f"Stream PPA Term ({sid})",
                stream.ppa.ppa_term_years, "years")
        if stream.merchant is not None:
            add(sid, "merchant_base_price", f"Stream Merchant Base Price ({sid})",
                stream.merchant.base_price_eur_mwh, "EUR/MWh")
            add(sid, "merchant_price_scenario",
                f"Stream Merchant Price Scenario ({sid})",
                stream.merchant.price_scenario, "n/a")
            add(sid, "merchant_price_escalation",
                f"Stream Merchant Price Escalation ({sid})",
                stream.merchant.price_escalation_annual, "fraction_per_year")
        if stream.fit is not None:
            add(sid, "fit_type", f"Stream FiT Type ({sid})",
                enum_text(stream.fit.fit_type), "n/a")
            add(sid, "fit_price", f"Stream FiT Price ({sid})",
                stream.fit.fit_price_eur_mwh, "EUR/MWh")
            add(sid, "fit_term_years", f"Stream FiT Term ({sid})",
                stream.fit.fit_term_years, "years")
            add(sid, "fit_index", f"Stream FiT Indexation ({sid})",
                stream.fit.fit_index, "fraction_per_year")
        if stream.cfd is not None:
            add(sid, "cfd_strike_price", f"Stream CfD Strike Price ({sid})",
                stream.cfd.strike_price_eur_mwh, "EUR/MWh")
            add(sid, "cfd_reference_price_type",
                f"Stream CfD Reference Price Type ({sid})",
                enum_text(stream.cfd.reference_price_type), "n/a")
            add(sid, "cfd_term_years", f"Stream CfD Term ({sid})",
                stream.cfd.cfd_term_years, "years")
        if stream.indexed_fit_base_tariff_eur_mwh is not None:
            add(sid, "indexed_fit_base_tariff",
                f"Stream Indexed FiT Base Tariff ({sid})",
                stream.indexed_fit_base_tariff_eur_mwh, "EUR/MWh")
            add(sid, "indexed_fit_index_factors",
                f"Stream Indexed FiT Index Factors ({sid})",
                list(stream.indexed_fit_index_factors), "factor")
    if plan.market_price is not None:
        market = plan.market_price
        sec.add("revenue.plan.market_price.base_price",
                market.base_price_eur_mwh,
                path="revenue_plan.market_price.base_price_eur_mwh",
                label="Plan Market Reference Base Price", unit="EUR/MWh",
                lineage_ref=lineage)
        sec.add("revenue.plan.market_price.price_scenario",
                market.price_scenario,
                path="revenue_plan.market_price.price_scenario",
                label="Plan Market Reference Scenario", unit="n/a",
                lineage_ref=lineage)


def _collect_capex(inputs, context, sec) -> None:
    capex = inputs.capex
    for slot, label in _CAPEX_ITEM_SLOTS:
        item = getattr(capex, slot)
        prefix = f"capex.{slot}"
        sec.add(f"{prefix}.amount_keur", item.amount_keur,
                      path=f"capex_{slot}_amount_keur",
                      label=f"{label} Amount", unit="kEUR")
        sec.add(f"{prefix}.y0_share", item.y0_share,
                      path=f"capex_{slot}_y0_share",
                      label=f"{label} Y0 Spending Share", unit="fraction")
        sec.add(f"{prefix}.spending_profile", list(item.spending_profile),
                      path=f"capex_{slot}_spending_profile",
                      label=f"{label} Spending Profile", unit="fraction")
        sec.enum_add(f"{prefix}.asset_class", item.asset_class,
                           path=f"capex_{slot}_asset_class",
                           label=f"{label} Asset Class")
        sec.add(f"{prefix}.useful_life_override", item.useful_life_override,
                      path=f"capex_{slot}_useful_life_override",
                      label=f"{label} Useful Life Override", unit="years")
        sec.add(f"{prefix}.is_depreciable", item.is_depreciable,
                      path=f"capex_{slot}_is_depreciable",
                      label=f"{label} Book Depreciable", unit="bool")
    # DERIVED construction-layer values on CapexStructure (idc_keur,
    # commitment_fees_keur, bank_fees_keur, other_financial_keur,
    # vat_costs_keur, vat_facility_*_keur, reserve_accounts_keur) are
    # deliberately NOT exposed: the canonical dataclass documents them as
    # derived outputs of the construction-financing layer, not primary
    # assumptions.
    authority = context.contingency_authority
    if authority is not None:
        sec.add("capex.contingency.pct", authority.capex_pct,
                path="contingency_authority.capex_pct",
                label="Contingency (CAPEX pct authority)",
                unit="fraction_of_capex", source_ref=authority.source_ref)


def _collect_opex(inputs, context, sec) -> None:
    authority = context.contingency_authority
    if authority is not None:
        sec.add("opex.contingency.pct", authority.opex_pct,
                path="contingency_authority.opex_pct",
                label="Contingency (OPEX pct authority)",
                unit="fraction_of_opex", source_ref=authority.source_ref)
    for index, item in enumerate(inputs.opex):
        prefix = f"opex.items[{index}]"
        sec.add(f"{prefix}.name", item.name,
                     path=f"opex[{index}].name",
                     label=f"OPEX Line {index} Name", unit="n/a")
        sec.add(f"{prefix}.y1_amount_keur", item.y1_amount_keur,
                     path=f"opex[{index}].y1_amount_keur",
                     label=f"OPEX Line {index} Y1 Amount", unit="kEUR")
        sec.add(f"{prefix}.annual_inflation", item.annual_inflation,
                     path=f"opex[{index}].annual_inflation",
                     label=f"OPEX Line {index} Inflation",
                     unit="fraction_per_year")
        sec.add(f"{prefix}.percentage_of_opex", item.percentage_of_opex,
                     path=f"opex[{index}].percentage_of_opex",
                     label=f"OPEX Line {index} Percentage-of-OPEX",
                     unit="fraction_of_opex")
        sec.add(f"{prefix}.step_changes",
                     [[year, amount] for year, amount in item.step_changes],
                     path=f"opex[{index}].step_changes",
                     label=f"OPEX Line {index} Step Changes",
                     unit="[year, kEUR]")


def _collect_financing(inputs, sec) -> None:
    fin = inputs.financing

    def add(slot, label, value, unit, **kw):
        sec.add(f"financing.{slot}", value,
                 path=f"financing.{slot}", label=label, unit=unit, **kw)

    add("share_capital_keur", "Share Capital", fin.share_capital_keur, "kEUR")
    add("share_premium_keur", "Share Premium", fin.share_premium_keur, "kEUR")
    add("shl_amount_keur", "Shareholder Loan Principal",
        fin.shl_amount_keur, "kEUR")
    add("shl_rate", "Shareholder Loan Rate", fin.shl_rate, "fraction_per_year")
    add("gearing_ratio", "Gearing Ratio (sizing)", fin.gearing_ratio, "fraction")
    add("sponsor_funding_mode", "Sponsor Funding Mode",
        enum_text(fin.sponsor_funding_mode), "n/a")
    add("gearing_basis_mode", "Gearing Basis Mode",
        enum_text(fin.gearing_basis_mode), "n/a")
    add("junior_or_other_project_funding_keur",
        "Junior / Other Project Funding",
        fin.junior_or_other_project_funding_keur, "kEUR")
    add("other_equity_funding_before_shl_keur",
        "Other Equity Funding before SHL",
        fin.other_equity_funding_before_shl_keur, "kEUR")
    add("senior_debt_amount_keur", "Senior Debt Amount (sizing input)",
        fin.senior_debt_amount_keur, "kEUR")
    add("senior_tenor_years", "Senior Debt Tenor", fin.senior_tenor_years,
        "years")
    add("base_rate", "Senior Debt Base Rate", fin.base_rate,
        "fraction_per_year")
    add("margin_bps", "Senior Debt Margin", fin.margin_bps, "bps")
    add("floating_share", "Floating Rate Share", fin.floating_share,
        "fraction")
    add("fixed_share", "Fixed Rate Share", fin.fixed_share, "fraction")
    add("hedge_coverage", "Hedge Coverage", fin.hedge_coverage, "fraction")
    add("commitment_fee", "Commitment Fee", fin.commitment_fee,
        "fraction_per_year")
    add("arrangement_fee", "Arrangement Fee", fin.arrangement_fee, "fraction")
    add("structuring_fee", "Structuring Fee", fin.structuring_fee, "fraction")
    add("target_dscr", "Target DSCR (sizing policy)", fin.target_dscr, "ratio")
    add("lockup_dscr", "Lockup DSCR", fin.lockup_dscr, "ratio")
    add("min_llcr", "Minimum LLCR Covenant", fin.min_llcr, "ratio")
    add("amortisation_type", "Amortisation Type", fin.amortization_type, "n/a")
    add("fixed_debt_service_keur", "Fixed Debt Service",
        fin.fixed_ds_keur, "kEUR")
    add("dsra_months", "DSRA Coverage Months", fin.dsra_months, "months")
    add("dsra_target_policy", "DSRA Target Policy", fin.dsra_target_policy,
        "n/a")
    add("dsra_support_mode", "Debt Service Reserve Support Mode",
        enum_text(fin.dsra_support_mode), "n/a")
    add("debt_service_reserve_requirement_keur",
        "Debt Service Reserve Requirement",
        fin.debt_service_reserve_requirement_keur, "kEUR")
    add("dsrf_commitment_keur", "DSRF Facility Commitment",
        fin.dsrf_commitment_keur, "kEUR")
    add("dsrf_commitment_fee_rate_pa", "DSRF Commitment Fee Rate",
        fin.dsrf_commitment_fee_rate_pa, "fraction_per_year")
    add("dsrf_fee_expires_at_senior_maturity",
        "DSRF Fee Expires at Senior Maturity",
        fin.dsrf_fee_expires_at_senior_maturity, "bool")
    add("dsrf_day_count", "DSRF Day Count", enum_text(fin.dsrf_day_count),
        "n/a")
    add("dsrf_fee_treatment", "DSRF Fee Treatment",
        enum_text(fin.dsrf_fee_treatment), "n/a")
    add("equity_irr_method", "Equity IRR Method", fin.equity_irr_method, "n/a")
    add("debt_sizing_method", "Debt Sizing Method", fin.debt_sizing_method,
        "n/a")
    add("debt_sizing_mode", "Debt Sizing Mode",
        enum_text(fin.debt_sizing_mode), "n/a")
    add("use_frozen_excel_senior_debt_schedule",
        "Frozen Excel Senior DS Schedule Flag",
        fin.use_frozen_excel_senior_debt_schedule, "bool")
    add("frozen_schedule_note", "Frozen Schedule Note",
        fin.frozen_schedule_note, "n/a")
    add("fixed_debt_keur", "Fixed Senior Debt Amount", fin.fixed_debt_keur,
        "kEUR")
    add("dscr_schedule", "DSCR Schedule (frozen input)",
        None if fin.dscr_schedule is None else list(fin.dscr_schedule),
        "ratio")
    add("shl_repayment_method", "SHL Repayment Method (legacy contract)",
        fin.shl_repayment_method, "n/a")
    add("shl_pik_switch_period", "SHL PIK Switch Period",
        fin.shl_pik_switch_period, "period")
    add("shl_tenor_years", "SHL Tenor", fin.shl_tenor_years, "years")
    add("clean_shl_principal_keur", "Clean SHL Principal",
        fin.clean_shl_principal_keur, "kEUR")
    add("clean_shl_repayment_method", "Clean SHL Repayment Method",
        enum_text(fin.clean_shl_repayment_method), "n/a")
    add("shl_day_count_convention", "SHL Day Count Convention",
        fin.shl_day_count_convention, "n/a")
    add("shl_construction_day_count_fraction",
        "SHL Construction Day-Count Fraction",
        fin.shl_construction_day_count_fraction, "fraction")
    add("shl_construction_day_count_convention",
        "SHL Construction Day-Count Convention",
        enum_text(fin.shl_construction_day_count_convention), "n/a")
    add("shl_construction_interest_method",
        "SHL Construction Interest Method",
        enum_text(fin.shl_construction_interest_method), "n/a")
    add("sponsor_funding_timing_policy", "Sponsor Funding Timing Policy",
        enum_text(fin.sponsor_funding_timing_policy), "n/a")
    add("construction_period_uses_keur", "Construction Period Uses",
        list(fin.construction_period_uses_keur), "kEUR")
    add("gearing_cap_repayment_method", "Gearing Cap Repayment Method",
        enum_text(fin.gearing_cap_repayment_method), "n/a")
    interest = fin.senior_debt_interest_config
    add("senior_interest_schedule.enabled",
        "Senior Interest Schedule Enabled", interest.enabled, "bool")
    add("senior_interest_schedule.day_count",
        "Senior Interest Day Count", enum_text(interest.day_count), "n/a")
    add("senior_rate_schedule.mode", "Senior Rate Schedule Mode",
        enum_text(interest.rate_schedule.mode), "n/a")
    add("senior_rate_schedule.flat_all_in_rate", "Senior Flat All-In Rate",
        interest.rate_schedule.flat_all_in_rate, "fraction_per_year")
    add("senior_rate_schedule.fixed_base_rate", "Senior Fixed Base Rate",
        interest.rate_schedule.fixed_base_rate, "fraction_per_year")
    add("senior_rate_schedule.margin_rate", "Senior Margin Rate",
        interest.rate_schedule.margin_rate, "fraction_per_year")
    sculpting = fin.senior_sculpting_config
    add("senior_sculpting_config.enabled", "Senior Sculpting Enabled",
        sculpting.enabled, "bool")
    add("senior_sculpting_config.mode", "Senior Sculpting Mode",
        enum_text(sculpting.mode), "n/a")
    add("senior_sculpting_config.target_dscr_schedule",
        "Senior Sculpting Target DSCR Schedule",
        list(sculpting.target_dscr_schedule), "ratio")
    add("senior_sculpting_config.final_repayment_policy",
        "Senior Final Repayment Policy",
        enum_text(sculpting.final_repayment_policy), "n/a")
    sizing_case = fin.debt_sizing_case
    add("debt_sizing_case.production_yield_scenario",
        "Bank Case Yield Scenario",
        enum_text(sizing_case.production_yield_scenario), "n/a")
    add("debt_sizing_case.merchant_price_calendar_start_year",
        "Bank Case Merchant Calendar Start Year",
        sizing_case.merchant_price_calendar_start_year, "year")
    add("debt_sizing_case.merchant_prices_by_calendar_year",
        "Bank Case Merchant Prices by Calendar Year",
        list(sizing_case.merchant_prices_by_calendar_year_eur_mwh),
        "EUR/MWh")
    add("debt_sizing_case.market_prices_curve", "Bank Case Market Prices Curve",
        list(sizing_case.market_prices_curve_eur_mwh), "EUR/MWh")
    # NOTE: fin.shl_idc_keur is a DERIVED construction-layer value and is
    # deliberately NOT exposed as an assumption.


def _collect_tax(inputs, sec) -> None:
    tax = inputs.tax

    def add(slot, label, value, unit, **kw):
        sec.add(f"tax.{slot}", value, path=f"tax.{slot}",
                 label=label, unit=unit, **kw)

    add("corporate_rate", "Corporate Tax Rate", tax.corporate_rate,
        "fraction")
    add("loss_carryforward_years", "Tax Loss Carryforward Period",
        tax.loss_carryforward_years, "years")
    add("loss_carryforward_cap", "Tax Loss Carryforward Cap",
        tax.loss_carryforward_cap, "fraction")
    add("prior_tax_loss_keur", "Opening Tax Loss (legacy scalar)",
        tax.prior_tax_loss_keur, "kEUR")
    add("legal_reserve_cap", "Legal Reserve Cap", tax.legal_reserve_cap,
        "fraction")
    add("thin_cap_enabled", "Thin Capitalisation Enabled",
        tax.thin_cap_enabled, "bool")
    add("thin_cap_de_ratio", "Thin Cap Debt-to-Equity Ratio",
        tax.thin_cap_de_ratio, "ratio")
    add("atad_enabled", "ATAD Interest Limitation Enabled",
        tax.atad_enabled, "bool")
    add("atad_ebitda_limit", "ATAD EBITDA Limit", tax.atad_ebitda_limit,
        "fraction")
    add("atad_min_interest_keur", "ATAD Minimum Interest Threshold",
        tax.atad_min_interest_keur, "kEUR")
    add("wht_sponsor_dividends", "WHT on Sponsor Dividends",
        tax.wht_sponsor_dividends, "fraction")
    add("wht_sponsor_shl_interest", "WHT on Sponsor SHL Interest",
        tax.wht_sponsor_shl_interest, "fraction")
    add("shl_interest_deductibility", "SHL Interest Deductibility Mode",
        enum_text(tax.shl_interest_deductibility), "n/a")
    add("shl_interest_deductible_share", "SHL Interest Deductible Fraction",
        tax.shl_interest_deductible_pct, "fraction")
    add("foreign_shl_interest_cap_enabled",
        "Foreign SHL Interest Cap Enabled",
        tax.foreign_shl_interest_cap_enabled, "bool")
    add("tax_loss_utilisation_gate", "Tax Loss Utilisation Gate",
        enum_text(tax.tax_loss_utilisation_gate), "n/a")
    add("tax_periodisation_mode", "Tax Periodisation Mode",
        enum_text(tax.tax_periodisation_mode), "n/a")
    add("shl_construction_accounting", "SHL Construction Accounting",
        enum_text(tax.shl_construction_accounting), "n/a")
    add("shl_construction_payment", "SHL Construction Payment Method",
        enum_text(tax.shl_construction_payment), "n/a")
    add("cit_cash_tax_start_operating_index",
        "CIT Cash Tax Start Operating Index",
        tax.cit_cash_tax_start_operating_index, "period")
    add("tax_depreciation_mode", "Tax Depreciation Mode",
        enum_text(tax.tax_depreciation_mode), "n/a")
    add("tax_deductible_book_dep_share",
        "Tax-Deductible Book Depreciation Fraction",
        tax.tax_deductible_book_dep_pct, "fraction")
    add("tax_dep_basis_source_owned", "Book-Basis Tax Depreciation Opt-In",
        tax.tax_dep_basis_source_owned, "bool")
    add("clean_cash_tax_timing_enabled", "Clean Cash-Tax Timing Opt-In",
        tax.clean_cash_tax_timing_enabled, "bool")
    add("country_tax_policy_id", "Country Tax Policy ID",
        tax.country_tax_policy_id, "n/a")
    add("corporate_rate_override", "Corporate Rate Override",
        tax.corporate_rate_override, "fraction")
    add("opening_tax_loss_vintages",
        [{
            "origin_tax_year": vintage.origin_tax_year,
            "opening_amount_keur": vintage.opening_amount_keur,
        } for vintage in tax.opening_tax_loss_vintages],
        "Opening Tax Loss Vintages", "[vintage]",
        value_type="array")
    add("interest_limitation_policy_enabled",
        "Typed Interest Limitation Policy Enabled",
        (tax.interest_limitation_policy.enabled
         if tax.interest_limitation_policy is not None else None),
        "bool")
    # NOTE: tax.construction_pl is a derived opening P&L object and
    # tax.shl_cap_applies is a deprecated non-authority flag: neither is an
    # input authority, neither is exposed.


_VALUATION_PROJECT_SLOTS = (
    ("valuation.project.annual_discount_rate",
     "valuation.project.annual_discount_rate",
     "Project NPV Annual Discount Rate", "fraction_per_year"),
    ("valuation.project.valuation_date_policy",
     "valuation.project.valuation_date_policy",
     "Project Valuation Date Policy", "n/a"),
    ("valuation.project.discount_convention",
     "valuation.project.discount_convention",
     "Project Discount Convention", "n/a"),
    ("valuation.project.authority_label",
     "valuation.project.authority_label",
     "Project Valuation Authority Label", "n/a"),
)

_VALUATION_COVERAGE_SLOTS = (
    ("valuation.coverage.annual_discount_rate",
     "valuation.coverage.annual_discount_rate",
     "Coverage (LLCR/PLCR) Annual Discount Rate", "fraction_per_year"),
    ("valuation.coverage.cfads_case", "valuation.coverage.cfads_case",
     "Coverage CFADS Case", "n/a"),
    ("valuation.coverage.llcr_cashflow_basis",
     "valuation.coverage.llcr_cashflow_basis", "LLCR Cashflow Basis", "n/a"),
    ("valuation.coverage.plcr_cashflow_basis",
     "valuation.coverage.plcr_cashflow_basis", "PLCR Cashflow Basis", "n/a"),
    ("valuation.coverage.authority_label",
     "valuation.coverage.authority_label",
     "Coverage Valuation Authority Label", "n/a"),
)


def _collect_valuation(inputs, sec) -> None:
    project = inputs.valuation.project
    if project is None:
        for assumption_id, path, label, unit in _VALUATION_PROJECT_SLOTS:
            sec.add(assumption_id, None, path=path, label=label, unit=unit,
                    notes="no project valuation policy authority attached")
    if project is not None:
        sec.add("valuation.project.annual_discount_rate",
                 project.annual_discount_rate,
                 path="valuation.project.annual_discount_rate",
                 label="Project NPV Annual Discount Rate",
                 unit="fraction_per_year")
        sec.enum_add("valuation.project.valuation_date_policy",
                      project.valuation_date_policy,
                      path="valuation.project.valuation_date_policy",
                      label="Project Valuation Date Policy")
        sec.enum_add("valuation.project.discount_convention",
                      project.discount_convention,
                      path="valuation.project.discount_convention",
                      label="Project Discount Convention")
        sec.add("valuation.project.authority_label", project.authority_label,
                 path="valuation.project.authority_label",
                 label="Project Valuation Authority Label", unit="n/a")
    coverage = inputs.valuation.coverage
    if coverage is None:
        for assumption_id, path, label, unit in _VALUATION_COVERAGE_SLOTS:
            sec.add(assumption_id, None, path=path, label=label, unit=unit,
                    notes="no coverage valuation policy authority attached")
    if coverage is not None:
        sec.add("valuation.coverage.annual_discount_rate",
                 coverage.annual_discount_rate,
                 path="valuation.coverage.annual_discount_rate",
                 label="Coverage (LLCR/PLCR) Annual Discount Rate",
                 unit="fraction_per_year")
        sec.enum_add("valuation.coverage.cfads_case", coverage.cfads_case,
                      path="valuation.coverage.cfads_case",
                      label="Coverage CFADS Case")
        sec.enum_add("valuation.coverage.llcr_cashflow_basis",
                      coverage.llcr_cashflow_basis,
                      path="valuation.coverage.llcr_cashflow_basis",
                      label="LLCR Cashflow Basis")
        sec.enum_add("valuation.coverage.plcr_cashflow_basis",
                      coverage.plcr_cashflow_basis,
                      path="valuation.coverage.plcr_cashflow_basis",
                      label="PLCR Cashflow Basis")
        sec.add("valuation.coverage.authority_label", coverage.authority_label,
                 path="valuation.coverage.authority_label",
                 label="Coverage Valuation Authority Label", unit="n/a")


# ---------------------------------------------------------------------------
# Public builder + register container
# ---------------------------------------------------------------------------



def build_assumption_register(inputs, context):
    """Build the immutable Assumption Register for one canonical input state.

    Pure function: no I/O, no mutation, no engine execution. Raises
    ValueError (typed codes) on non-finite values, incomplete run identity,
    duplicate identity paths or invalid enum states.
    """
    if not isinstance(inputs, ProjectInputs):
        raise ValueError(
            "ASSUMPTION_REGISTER_INPUT_INVALID: expected finco_core "
            "ProjectInputs"
        )
    if not isinstance(context, RegisterContext):
        raise ValueError(
            "ASSUMPTION_REGISTER_CONTEXT_INVALID: expected RegisterContext"
        )
    collector = _Collector(context)
    project_sec = collector.section("PROJECT")
    technical_sec = collector.section("TECHNICAL")
    revenue_sec = collector.section("REVENUE")
    _collect_project(inputs, project_sec)
    _collect_technical(inputs, technical_sec)
    _collect_revenue(inputs, revenue_sec)
    _collect_revenue_plan(context, revenue_sec)
    _collect_capex(inputs, context, collector.section("CAPEX"))
    _collect_opex(inputs, context, collector.section("OPEX"))
    _collect_financing(inputs, collector.section("FINANCING"))
    _collect_tax(inputs, collector.section("TAX"))
    _collect_valuation(inputs, collector.section("VALUATION"))
    entries = collector.finish()
    register = AssumptionRegister(
        context=context,
        entries=entries,
        engine_version=engine_version(),
        workbook_version=workbook_version(),
    )
    return register


@dataclass(frozen=True)
class AssumptionRegister:
    """Immutable, deterministically ordered collection of assumption entries."""

    context: RegisterContext
    entries: tuple[AssumptionEntry, ...]
    engine_version: str
    workbook_version: str

    @property
    def fingerprint(self) -> str:
        """Deterministic content fingerprint (sha256 of canonical JSON)."""
        digest = hashlib.sha256(
            canonical_json(self.to_dict()).encode("utf-8")
        )
        return f"sha256:{digest.hexdigest()}"

    def entry(self, assumption_id):
        for candidate in self.entries:
            if candidate.assumption_id == assumption_id:
                return candidate
        raise KeyError(assumption_id)

    def section(self, section):
        return tuple(e for e in self.entries if e.section == section)

    def to_dict(self):
        return {
            "schema_id": ASSUMPTION_REGISTER_SCHEMA_ID,
            "schema_version": ASSUMPTION_REGISTER_SCHEMA_VERSION,
            "context": self.context.to_dict(),
            "engine_version": self.engine_version,
            "workbook_version": self.workbook_version,
            "entries": [entry.to_dict() for entry in self.entries],
            "entry_count": len(self.entries),
        }

    def to_json(self):
        return canonical_json(self.to_dict())

    @classmethod
    def from_dict(cls, raw):
        if raw.get("schema_id") != ASSUMPTION_REGISTER_SCHEMA_ID:
            raise ValueError(
                "SCHEMA_ID_MISMATCH: expected "
                f"{ASSUMPTION_REGISTER_SCHEMA_ID!r}, got {raw.get('schema_id')!r}"
            )
        if raw.get("schema_version") != ASSUMPTION_REGISTER_SCHEMA_VERSION:
            raise ValueError(
                "SCHEMA_VERSION_UNSUPPORTED: expected "
                f"{ASSUMPTION_REGISTER_SCHEMA_VERSION}, "
                f"got {raw.get('schema_version')!r}"
            )
        context_raw = raw.get("context")
        if not isinstance(context_raw, dict):
            raise ValueError("REGISTER_DESERIALIZE_INVALID: context missing")
        try:
            context_kind = AssumptionContextKind(context_raw["context_kind"])
            state_provenance = AssumptionSourceKind(context_raw["state_provenance"])
        except (KeyError, ValueError) as exc:
            raise ValueError(
                f"REGISTER_DESERIALIZE_INVALID: unknown context enum ({exc})"
            ) from None
        run_identity = None
        if context_raw.get("run_identity") is not None:
            run_identity = RunIdentity(**{
                key: value
                for key, value in context_raw["run_identity"].items()
                if key in RunIdentity.__dataclass_fields__
            })
            _validate_run_identity(run_identity)
        entries_raw = raw.get("entries")
        if not isinstance(entries_raw, list):
            raise ValueError("REGISTER_DESERIALIZE_INVALID: entries missing")
        entries = tuple(entry_from_dict(entry) for entry in entries_raw)
        return cls(
            context=RegisterContext(
                context_kind=context_kind,
                state_provenance=state_provenance,
                run_identity=run_identity,
                workbook_composite_hash=context_raw.get(
                    "workbook_composite_hash"
                ),
                notes=context_raw.get("notes"),
            ),
            entries=entries,
            engine_version=str(raw.get("engine_version", "unknown")),
            workbook_version=str(raw.get("workbook_version", "unknown")),
        )

    @classmethod
    def from_json(cls, text):
        def _reject(name):
            raise ValueError(
                f"ASSUMPTION_VALUE_NOT_FINITE: JSON literal {name!r} is not "
                "representable in a register."
            )

        return cls.from_dict(json.loads(text, parse_constant=_reject))
