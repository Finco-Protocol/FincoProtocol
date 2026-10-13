"""Two-driver sensitivity matrix — canonical input construction (M3).

Every cell starts from the SAME resolved scenario input state and applies BOTH shocks to canonical INPUTS:

  1. FIELD drivers  -> ``ProjectInputSet.with_value`` (the exact mechanism of the existing one-driver workbook run);
  2. materialise complete typed ``ProjectInputs`` and fold the user CAPEX / OPEX sub-lines (as Run does);
  3. TYPED drivers  -> the existing ``sensitivity_service._apply_shock`` (CAPEX, OPEX, merchant price);
  4. financing materialisation (fee authority + F3 state), exactly as the one-driver route;
  5. the original ``run_project`` in the bounded model executor (``run_sensitivity_points``).

A shock is never applied to a computed output, and two single-driver deltas are never added.  A shock that does not
change the typed inputs is reported as a typed failure rather than silently producing the unshocked result.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any, Mapping, Optional

from app.v2.sensitivity_matrix_projection import (
    ABS, FIELD, PCT, TYPED, TYPED_ORDER, DriverSpec, MatrixRequestError,
)

RUNTIME_KEYS = {"solar": "Solar", "wind": "Wind", "data_center": "Generic Data Center Reference"}


class CellBuildError(ValueError):
    """One cell cannot be constructed; carries a short typed code (never a traceback)."""

    def __init__(self, code: str, detail: str = ""):
        super().__init__(f"{code}: {detail}" if detail else code)
        self.code = code


@dataclass(frozen=True)
class Basis:
    """Resolved, immutable starting state for every cell of one matrix request."""

    pis_base: Any
    project_id: str
    scenario_overrides: Optional[Mapping[str, Any]]
    f3_scope: str
    scenario_display: str
    scenario_id: Optional[str]


def resolve_basis(*, workspace_owner: str, project_record: Any, ws: Any, scenario_id: Optional[str]) -> Basis:
    """Same scenario resolution as the existing one-driver route: saved scenario snapshot or Working Copy draft."""
    from app.persistence.scenarios_repository import resolve_active_scenario_runtime_snapshot
    from app.workbook.service import WorkbookService

    if scenario_id:
        try:
            record, snapshot, _warning = resolve_active_scenario_runtime_snapshot(
                workspace_owner, project_record.project_id, scenario_id)
        except ValueError as exc:
            raise MatrixRequestError("MATRIX_SCENARIO_INPUT_UNAVAILABLE", str(exc)) from exc
        if record is None or record.project_id != project_record.project_id or record.archived:
            raise MatrixRequestError("MATRIX_SCENARIO_NOT_FOUND", "Scenario not found, archived or inaccessible.")
        if snapshot is None:
            raise MatrixRequestError("MATRIX_SCENARIO_INPUT_UNAVAILABLE",
                                     "Could not resolve the scenario inputs. Re-run the scenario and retry.")
        return Basis(WorkbookService.build_input_set(snapshot), project_record.project_id, record.overrides,
                     "base" if record.is_base_case else scenario_id, record.scenario_name, scenario_id)
    return Basis(WorkbookService.build_draft_input_set_from_workspace(ws), project_record.project_id, None,
                 "base", "Base Case", None)


def _field_value(pis: Any, spec: DriverSpec) -> tuple[str, Any]:
    field_id = spec.field_id
    value = pis.values.get(field_id)
    if value is None and spec.fallback_field_id:
        value = pis.values.get(spec.fallback_field_id)
        if value is not None:
            field_id = spec.fallback_field_id
    return field_id, value


def _senior_rate_percent(pis: Any) -> float:
    """Current Senior all-in rate in HUMAN PERCENT, from the typed Senior pricing authority.

    The snapshot value of ``debt.senior.interest_rate_pct`` is stored as a ratio in seeded projects (0.055 = 5.5 %)
    while ``with_value`` / the Save path take percent (9.0 == 9 %).  Adding basis points to the raw snapshot value
    would therefore shift the rate by 100x too little (a "+100 bps" shock would give 1.055 %).  The typed authority is
    unambiguous; a calibrated non-uniform schedule cannot be shocked by a scalar and fails closed.
    """
    from app.input_adapter import senior_rate_authority
    from app.workbook.service import WorkbookService

    mode, ratio, _periods = senior_rate_authority(WorkbookService.to_projectinputs(pis))
    if mode != "FLAT" or ratio is None:
        raise CellBuildError("SENIOR_RATE_SCHEDULE_CALIBRATED", "a calibrated rate schedule is not a single scalar")
    return ratio * 100.0


def assert_interest_rate_shockable(basis: Basis) -> None:
    """Same gate as the Save path: refuse a scalar rate shock the bankability configuration or schedule owns."""
    from app.input_adapter import assert_debt_scalar_edit_allowed

    try:
        assert_debt_scalar_edit_allowed(basis.pis_base, "debt.senior.interest_rate_pct")
    except ValueError as exc:
        raise MatrixRequestError("MATRIX_DRIVER_NOT_APPLICABLE", str(exc)[:160]) from exc


def _shocked_field_value(spec: DriverSpec, original: float, level: float) -> float:
    if spec.mode == PCT:
        return original * (1.0 + level / 100.0)
    return original + level * spec.field_scale        # ABS: level in the displayed unit -> field units


def pre_financing_inputs(basis: Basis, shocks: list[tuple[DriverSpec, float]]) -> tuple[Any, Any, dict]:
    """Complete typed ProjectInputs with every non-zero shock applied, BEFORE financing materialisation."""
    from app.services.capex_sub_lines_integration import apply_user_sub_lines_replacing_base
    from app.services.opex_sub_lines_integration import apply_user_sub_lines_to_opex
    from app.services.sensitivity_service import _apply_shock
    from app.workbook.service import WorkbookService

    pis = basis.pis_base
    info: dict[str, dict[str, Any]] = {}
    active = [(spec, level) for spec, level in shocks if level != 0]
    for spec, level in active:
        if spec.apply != FIELD:
            continue
        if spec.key == "interest_rate":
            field_id, original = spec.field_id, _senior_rate_percent(pis)
        else:
            field_id, original = _field_value(pis, spec)
        if original is None:
            raise CellBuildError("BASE_VALUE_MISSING", f"{spec.key}: no base value in the resolved inputs")
        try:
            original_f = float(original)
        except (TypeError, ValueError):
            raise CellBuildError("BASE_VALUE_NOT_NUMERIC", spec.key) from None
        shocked = _shocked_field_value(spec, original_f, level)
        pis = pis.with_value(field_id, str(shocked))
        info[spec.key] = {"field_id": field_id, "original": original_f, "shocked": shocked}

    pi = WorkbookService.to_projectinputs(pis)
    folded = apply_user_sub_lines_replacing_base(pi.capex, project_id=basis.project_id,
                                                 scenario_overrides=basis.scenario_overrides)
    if folded is not pi.capex:
        pi = replace(pi, capex=folded)
    folded_opex = apply_user_sub_lines_to_opex(pi.opex, project_id=basis.project_id,
                                               scenario_overrides=basis.scenario_overrides)
    if folded_opex is not pi.opex:
        pi = replace(pi, opex=folded_opex)

    if any(spec.key == "tariff" for spec, _ in active) and getattr(pi.revenue, "multistream_config_json", ""):
        raise CellBuildError("REVENUE_V2_CONTRACTS_UNSUPPORTED",
                             "explicit revenue contracts have no scalar tariff authority; use scenario contracts")

    typed = {spec.typed_shock: (spec, level) for spec, level in active if spec.apply == TYPED}
    for name in TYPED_ORDER:
        if name in typed:
            spec, level = typed[name]
            try:
                pi = _apply_shock(pi, name, level)
            except ValueError as exc:
                raise CellBuildError("SHOCK_REJECTED", str(exc)[:100]) from exc
            info[spec.key] = {"factor": 1.0 + level / 100.0}
    return pi, pis, info


def materialise_financing(basis: Basis, pi: Any, pis: Any) -> Any:
    """Fee authority + F3 financing state, exactly as the one-driver route applies them."""
    from app.workbook.bankability_config import SNAPSHOT_KEY, assert_materialized_fee_authority
    from app.workbook.multisenior_config import SNAPSHOT_KEY as F3_KEY, apply_state

    assert_materialized_fee_authority(pi, pis.snapshot_origin.get(SNAPSHOT_KEY))
    return apply_state(pi, pis.snapshot_origin.get(F3_KEY), basis.f3_scope,
                       bankability_raw=pis.snapshot_origin.get(SNAPSHOT_KEY))


def build_cell(basis: Basis, spec_a: DriverSpec, level_a: float, spec_b: DriverSpec, level_b: float,
               *, unshocked_pre: Any, single_guard: dict) -> tuple[Any, dict]:
    """(ProjectInputs for the runner, tooltip evidence) for one cell, or raises CellBuildError."""
    pi_pre, pis, info = pre_financing_inputs(basis, [(spec_a, level_a), (spec_b, level_b)])
    for spec, level in ((spec_a, level_a), (spec_b, level_b)):
        if level == 0:
            continue
        guard_key = (spec.key, level)
        if guard_key not in single_guard:
            single_pre, _p, _i = pre_financing_inputs(basis, [(spec, level)])
            single_guard[guard_key] = single_pre != unshocked_pre
        if not single_guard[guard_key]:
            raise CellBuildError("SHOCK_NOT_APPLIED", f"{spec.key} {level:g} did not change the model inputs")
    return materialise_financing(basis, pi_pre, pis), {
        "A": _describe(spec_a, level_a, info), "B": _describe(spec_b, level_b, info)}


def _describe(spec: DriverSpec, level: float, info: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    entry = dict(info.get(spec.key, {}))
    entry.update(driver=spec.key, label=spec.label, level=level, unit=spec.unit_label)
    if "original" in entry:
        entry["text"] = f"{spec.label}: {entry['original']:g} → {entry['shocked']:g}"
    elif "factor" in entry:
        entry["text"] = f"{spec.label}: × {entry['factor']:.4f} on the model inputs"
    else:
        entry["text"] = f"{spec.label}: base (unchanged)"
    return entry


def build_all(basis: Basis, spec_a: DriverSpec, levels_a, spec_b: DriverSpec, levels_b):
    """Ordered (index, ProjectInputs) work list, per-cell build failures and the base ProjectInputs (if separate)."""
    if "interest_rate" in (spec_a.key, spec_b.key):
        assert_interest_rate_shockable(basis)
    unshocked_pre, base_pis, _ = pre_financing_inputs(basis, [])
    guard: dict = {}
    work: list[tuple[tuple[int, int], Any]] = []
    failures: dict[tuple[int, int], dict] = {}
    evidence: dict[tuple[int, int], dict] = {}
    for j, lb in enumerate(levels_b):
        for i, la in enumerate(levels_a):
            try:
                pi, inputs = build_cell(basis, spec_a, la, spec_b, lb, unshocked_pre=unshocked_pre, single_guard=guard)
            except CellBuildError as exc:
                failures[(i, j)] = {"error": exc.code, "inputs": {}}
                continue
            except Exception as exc:  # noqa: BLE001 - one bad cell must not abort the grid
                failures[(i, j)] = {"error": f"CELL_BUILD_FAILED: {str(exc)[:80]}", "inputs": {}}
                continue
            work.append(((i, j), pi))
            evidence[(i, j)] = {"inputs": inputs}
    has_zero_cell = 0 in levels_a and 0 in levels_b
    base_pi = None
    if not has_zero_cell:
        base_pi = materialise_financing(basis, unshocked_pre, base_pis)
    return work, failures, evidence, base_pi, has_zero_cell


def run_matrix_points(project_type: str, project_inputs) -> list[dict]:
    """Worker (module level so it can run in a spawned process): the original ``run_project`` per point, in order.

    Same call as ``sensitivity_execution.run_sensitivity_points``; additionally projects the catalog metrics whose
    authoritative source is the debt or sponsor schedule SUMMARY of the SAME run, through the existing source-key
    mapping (identical to ``run_history_projection._enriched_kpis``).  No value is computed or inferred here.
    """
    from app.api.project_runner import run_project

    outputs: list[dict] = []
    for pi in project_inputs:
        try:
            result = run_project(project_type, "Base", project_inputs_override=pi)
            outputs.append({"kpis": enrich_kpis(result)})
        except Exception as exc:  # noqa: BLE001 - one failed point must not abort the grid
            outputs.append({"error": str(exc)[:120]})
    return outputs


def enrich_kpis(result: Mapping[str, Any]) -> dict[str, Any]:
    from app.v2.output_metric_projection import SPONSOR_SUMMARY_SOURCE_KEYS

    kpis = dict(result.get("kpis", {}))
    debt_summary = (result.get("debt_schedule") or {}).get("summary", {}) or {}
    for key in ("min_llcr", "target_dscr"):
        if kpis.get(key) is None and debt_summary.get(key) is not None:
            kpis[key] = debt_summary.get(key)
    sponsor_summary = (result.get("sponsor_schedule") or {}).get("summary", {}) or {}
    for catalog_key, field in SPONSOR_SUMMARY_SOURCE_KEYS.items():
        if kpis.get(catalog_key) is None:
            kpis[catalog_key] = sponsor_summary.get(field)
    return kpis
