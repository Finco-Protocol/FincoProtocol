"""Unmounted BESS02 preparation of explicit inputs for isolated financial review.

This module never creates a project, saves a draft, runs finance, chooses a
price/cost/tax policy, or grants product capability. The native engine and the
existing canonical financial authority remain the only calculators. A reviewed
input candidate is not an approved merchant lender case or a released product.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, fields, replace
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
import hashlib
import json
import re
from typing import Any

from domain.bess.contracts import BessInputError, _unique, exact, number, text
from finco_core.inputs._models import AssetClass, PeriodFrequency, ProjectInputs, TechnicalParams
from finco_core.inputs.bess_native import NativeBessTechnicalParams, parse_native_contract
from finco_core.inputs.senior_rate_schedule import SeniorDayCountConvention, SeniorRateMode

SCHEMA = "BESS02_EXPLICIT_STANDALONE_CANDIDATE_V1"
MAX_DECLARATION_BYTES = 32_000
POLICY_REFERENCES = frozenset({"asset_cost", "book_depreciation", "tax_jurisdiction", "funding", "merchant_case"})
RELEASE_BLOCKERS = (
    "BESS_FINANCIAL_ACTIVATION_RELEASE_CLOSED",
    "BESS_NEW_USER_PROJECT_CREATOR_NOT_RELEASED",
    "BESS_USER_DECLARATIONS_ARE_NOT_OWNER_FINANCIAL_APPROVAL",
    "BESS_CANONICAL_CREATE_SAVE_SCENARIO_RUN_NOT_PROVEN",
)


class BessStandaloneCandidateError(BessInputError):
    """Bounded explicit candidate cannot attest the requested handoff."""


def _json_default(value: Any):
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise BessStandaloneCandidateError("BESS02_NONFINITE_INPUT")
        return str(value)
    raise TypeError("unsupported candidate input type")


def _canonical(value: Any) -> str:
    return json.dumps(value, default=_json_default, sort_keys=True, separators=(",", ":"), allow_nan=False)


def input_fingerprint(project_inputs: ProjectInputs) -> str:
    """Bind the complete supplied typed input, including zero costs and policies.

    This is a candidate-content fingerprint, never a workspace content hash or
    a committed Run identity. No absent source field is supplied by this method.
    """
    if type(project_inputs) is not ProjectInputs:
        raise BessStandaloneCandidateError("BESS02_EXPLICIT_PROJECT_INPUTS_REQUIRED")
    try:
        return hashlib.sha256(_canonical(asdict(project_inputs)).encode()).hexdigest()
    except (TypeError, ValueError, RecursionError, OverflowError) as exc:
        raise BessStandaloneCandidateError("BESS02_PROJECT_INPUTS_INVALID") from exc


def _asset_document(project_inputs: ProjectInputs) -> dict:
    """Expose the actual typed cost basis for an explicit declaration, no totals."""
    return {name: asdict(getattr(project_inputs.capex, name)) for name in project_inputs.capex._CAPEX_ITEM_FIELDS}


def declaration_basis(project_inputs: ProjectInputs, native_json: str) -> dict:
    """Return source facts for review, never an approval or an inferred cost.

    The caller must separately supply all required policy source references and
    explicitly select MANUAL_DECLARED_KEUR before this can become a declaration.
    """
    contract = parse_native_contract(native_json)
    battery = contract.configuration.battery
    return {
        "base_inputs_sha256": input_fingerprint(project_inputs),
        "native_inputs_sha256": hashlib.sha256(contract.canonical_json.encode()).hexdigest(),
        "battery_basis": {
            "discharge_power_mw": float(battery.discharge_power_mw),
            "installed_energy_mwh": float(battery.installed_energy_mwh),
            "usable_energy_mwh": float(battery.usable_energy_mwh),
        },
        "asset_costs": json.loads(_canonical(_asset_document(project_inputs))),
    }


@dataclass(frozen=True)
class StandaloneCandidate:
    """Pure, isolated input handoff; never a persisted project or financial Run."""
    project_inputs: ProjectInputs
    native_input_sha256: str
    base_input_sha256: str
    declaration_sha256: str
    period_axis: tuple[tuple[int, str, str, int], ...]
    policy_references: tuple[tuple[str, str], ...]

    def review(self) -> dict:
        return {
            "schema": SCHEMA,
            "state": "BESS02_PARTIAL_CANDIDATE_WITH_EXACT_GAPS",
            "native_input_sha256": self.native_input_sha256,
            "base_input_sha256": self.base_input_sha256,
            "declaration_sha256": self.declaration_sha256,
            "identity_scope": "CANDIDATE_CONTENT_ONLY_NOT_RUN_OR_WORKSPACE_IDENTITY",
            "period_axis": [{"period_index": i, "start": start, "end_exclusive": end, "hours": hours}
                            for i, start, end, hours in self.period_axis],
            "policy_reference_scope": "USER_DECLARED_PROVENANCE_NOT_FINANCIAL_OWNER_APPROVAL",
            "policy_references": dict(self.policy_references),
            "financial_authority": _financial_authority_review(self.project_inputs),
            "capability": capability(),
        }


def _financial_authority_review(project_inputs: ProjectInputs) -> dict:
    """Read the supplied authority gaps without interpreting them as approval.

    A country code or policy reference alone does not prove the missing
    capitalization, reserve or tax contract. No absent field becomes zero or
    an approved generic policy, even when another recorded field is present.
    """
    policy = project_inputs.accounting_policy_config
    authorities = {}
    for field in ("book_capitalization_authority", "legal_reserve_authority", "cash_interest_authority"):
        authority = getattr(policy, field, None)
        value = authority.value if isinstance(authority, Enum) else None
        authorities[field] = {
            "source": "ProjectInputs.accounting_policy_config." + field,
            "value": value,
            "availability": "RECORDED" if value is not None else "NOT_AVAILABLE",
        }
    tax_id = project_inputs.tax.country_tax_policy_id
    return {
        "owner_approval": "NOT_PROVEN",
        "scope": "RECORDED_INPUT_AUTHORITY_ONLY_NOT_STATUTORY_OR_RELEASE_APPROVAL",
        "accounting": authorities,
        "tax_country_policy": {
            "source": "ProjectInputs.tax.country_tax_policy_id",
            "value": tax_id,
            "availability": "RECORDED" if tax_id is not None else "NOT_AVAILABLE",
        },
    }


def capability() -> dict:
    """Literal release closure; environment, payload and input readiness cannot grant it."""
    return {"create_supported": False, "save_supported": False, "run_supported": False,
            "persisted": False, "financial_calculation_count": 0,
            "release_state": "ACTIVATION_BLOCKED", "blockers": list(RELEASE_BLOCKERS)}


def create_standalone_project(*_args, **_kwargs):
    """Deliberately refuse before any owner lookup, factory or persistence call.

    A future creator requires a separately approved canonical project-store and
    financial-owner contract. This is not a test-mode writer or hidden route.
    """
    raise BessStandaloneCandidateError("BESS02_CANONICAL_CREATOR_RELEASE_CLOSED")


def _declaration(raw: str) -> dict:
    if not isinstance(raw, str) or len(raw.encode()) > MAX_DECLARATION_BYTES:
        raise BessStandaloneCandidateError("BESS02_DECLARATION_SIZE")
    try:
        obj = json.loads(raw, object_pairs_hook=_unique)
        exact(obj, {"version", "cost_basis", "source_ref", "base_inputs_sha256", "native_inputs_sha256",
                    "battery_basis", "asset_costs", "policy_references"}, "standalone declaration")
        if type(obj["version"]) is not int or obj["version"] != 1 or obj["cost_basis"] != "MANUAL_DECLARED_KEUR":
            raise BessStandaloneCandidateError("BESS02_DECLARATION_VERSION_OR_COST_BASIS")
        text(obj["source_ref"], "cost declaration source")
        for key in ("base_inputs_sha256", "native_inputs_sha256"):
            if not isinstance(obj[key], str) or re.fullmatch(r"[0-9a-f]{64}", obj[key]) is None:
                raise BessStandaloneCandidateError("BESS02_DECLARATION_BINDING")
        exact(obj["battery_basis"], {"discharge_power_mw", "installed_energy_mwh", "usable_energy_mwh"}, "battery cost basis")
        for key, value in obj["battery_basis"].items():
            number(value, key, positive=True)
        exact(obj["policy_references"], POLICY_REFERENCES, "explicit policy references")
        for value in obj["policy_references"].values():
            text(value, "policy source reference")
        if not isinstance(obj["asset_costs"], dict):
            raise BessStandaloneCandidateError("BESS02_ASSET_COSTS_REQUIRED")
        return obj
    except (TypeError, ValueError, RecursionError, OverflowError) as exc:
        if isinstance(exc, BessStandaloneCandidateError):
            raise
        raise BessStandaloneCandidateError("BESS02_DECLARATION_INVALID") from exc


def prepare_candidate(project_inputs: ProjectInputs, native_json: str, declaration_json: str) -> StandaloneCandidate:
    """Validate an explicitly supplied candidate without I/O, finance or defaults.

    The native parser owns physical/schema rules. This boundary pins those facts
    to the caller's complete cost and policy basis, checks the real clean period
    axis, and creates only the existing typed native operating-input subclass.
    Any actual isolated calculation must use the existing canonical authority.
    """
    base_hash = input_fingerprint(project_inputs)
    contract = parse_native_contract(native_json)
    declaration = _declaration(declaration_json)
    config, battery = contract.configuration, contract.configuration.battery
    native_hash = hashlib.sha256(contract.canonical_json.encode()).hexdigest()
    if declaration["base_inputs_sha256"] != base_hash or declaration["native_inputs_sha256"] != native_hash:
        raise BessStandaloneCandidateError("BESS02_DECLARATION_BINDING_MISMATCH")
    expected_basis = declaration_basis(project_inputs, contract.canonical_json)
    if declaration["battery_basis"] != expected_basis["battery_basis"]:
        raise BessStandaloneCandidateError("BESS02_BATTERY_COST_BASIS_MISMATCH")
    # Exact metadata comparison binds spending, class, book life, non-depreciable
    # treatment and every explicit zero, rather than only matching a total.
    if _canonical(declaration["asset_costs"]) != _canonical(expected_basis["asset_costs"]):
        raise BessStandaloneCandidateError("BESS02_ASSET_COST_BASIS_MISMATCH")
    positive_assets = []
    for name in project_inputs.capex._CAPEX_ITEM_FIELDS:
        item = getattr(project_inputs.capex, name)
        amount = number(item.amount_keur, "declared asset kEUR")
        if amount:
            positive_assets.append(item)
            if item.is_depreciable and (type(item.useful_life_override) is not int or item.useful_life_override <= 0):
                raise BessStandaloneCandidateError("BESS02_EXPLICIT_ASSET_BOOK_LIFE_REQUIRED")
    if not positive_assets or not any(item.asset_class is AssetClass.BESS_CELLS for item in positive_assets):
        raise BessStandaloneCandidateError("BESS02_EXPLICIT_BATTERY_CAPEX_REQUIRED")
    tech, rev, fin, info = project_inputs.technical, project_inputs.revenue, project_inputs.financing, project_inputs.info
    if tech.bess_enabled is not True or tech.bess is not None or tech.operating_hours_p50 or tech.operating_hours_p90_10y:
        raise BessStandaloneCandidateError("BESS02_STANDALONE_NATIVE_ONLY_REQUIRED")
    if number(tech.capacity_mw, "declared discharge MW", positive=True) != battery.discharge_power_mw:
        raise BessStandaloneCandidateError("BESS02_DECLARED_POWER_MISMATCH")
    if config.events:
        raise BessStandaloneCandidateError("BESS_POST_COD_ACCOUNTING_RELEASE_CLOSED")
    if battery.initial_energy_mwh or battery.terminal_energy_mwh:
        raise BessStandaloneCandidateError("BESS_INVENTORY_FINANCIAL_BASIS_UNRESOLVED")
    if (rev.ppa_base_tariff or rev.ppa_term_years or rev.ppa_production_share or rev.co2_enabled
            or getattr(rev, "multistream_config_json", "")):
        raise BessStandaloneCandidateError("BESS_DUPLICATE_REVENUE_AUTHORITY")
    if project_inputs.accounting_policy_config is None or project_inputs.tax.clean_cash_tax_timing_enabled is not True:
        raise BessStandaloneCandidateError("BESS02_EXPLICIT_ACCOUNTING_AND_CASH_TAX_REQUIRED")
    if (not isinstance(info.country_iso, str) or re.fullmatch(r"[A-Z]{2}", info.country_iso) is None
            or not declaration["policy_references"]["tax_jurisdiction"]):
        raise BessStandaloneCandidateError("BESS02_TAX_JURISDICTION_REQUIRED")
    if info.period_frequency is not PeriodFrequency.SEMESTRIAL or type(info.horizon_years) is not int or info.horizon_years < 2:
        raise BessStandaloneCandidateError("BESS02_COMPLETE_TWO_YEAR_SEMIANNUAL_AXIS_REQUIRED")
    rates = fin.senior_debt_interest_config
    if (rates is None or rates.enabled is not True or rates.rate_schedule.mode is not SeniorRateMode.EXPLICIT_ALL_IN_SCHEDULE
            or rates.day_count not in {SeniorDayCountConvention.ACT_360, SeniorDayCountConvention.ACT_365}
            or type(fin.senior_tenor_years) is not int or fin.senior_tenor_years <= 0
            or len(rates.rate_schedule.explicit_all_in_rates) != 2 * fin.senior_tenor_years):
        raise BessStandaloneCandidateError("BESS02_EXPLICIT_ALL_IN_RATE_CONTRACT_REQUIRED")
    for rate in rates.rate_schedule.explicit_all_in_rates:
        number(rate, "explicit annual all-in ratio", maximum=.20)
    # Native subclass carries the exact submitted dispatch; no price, CAPEX,
    # depreciation, tax, funding, PPA or reserve value is rewritten here.
    native_tech = NativeBessTechnicalParams(**{f.name: getattr(tech, f.name) for f in fields(TechnicalParams)},
                                           bess_native_config_json=contract.canonical_json)
    candidate_inputs = replace(project_inputs, technical=native_tech)
    from financial_engine.adapters.project_inputs import from_project_inputs
    from financial_engine.orchestrator import _build_period_engine
    operating = tuple(p for p in _build_period_engine(from_project_inputs(candidate_inputs)).periods() if p.is_operation)
    if not operating or config.start.date() != operating[0].start_date or config.end.date() != operating[-1].end_date:
        raise BessStandaloneCandidateError("BESS_FINANCE_AXIS")
    axis = tuple((p.index, p.start_date.isoformat(), p.end_date.isoformat(), (p.end_date - p.start_date).days * 24)
                 for p in operating)
    if sum(row[3] for row in axis) != int((config.end - config.start).total_seconds() // 3600):
        raise BessStandaloneCandidateError("BESS_FINANCE_AXIS")
    return StandaloneCandidate(candidate_inputs, native_hash, base_hash,
                               hashlib.sha256(_canonical(declaration).encode()).hexdigest(), axis,
                               tuple(sorted(declaration["policy_references"].items())))


MAX_DOCUMENT_BYTES = 6_000_000
_DOCUMENT_KEYS = frozenset({"version", "scope", "base_inputs", "native_json", "declaration_json", "identity"})


def _document_identity(candidate: StandaloneCandidate) -> dict:
    return {"base_inputs_sha256": candidate.base_input_sha256,
            "native_inputs_sha256": candidate.native_input_sha256,
            "declaration_sha256": candidate.declaration_sha256}


def export_candidate_document(project_inputs: ProjectInputs, native_json: str, declaration_json: str) -> str:
    """Serialize explicit base inputs losslessly for private review, never Save.

    The core serializer cannot carry native technical subclasses. Native JSON
    therefore travels separately; any original field lost by that serializer
    is refused rather than defaulted or silently omitted.
    """
    from finco_core.inputs.serialization import project_inputs_from_dict, project_inputs_to_dict
    prepared = prepare_candidate(project_inputs, native_json, declaration_json)
    try:
        base = project_inputs_to_dict(project_inputs)
        restored = project_inputs_from_dict(base)
        if asdict(project_inputs) != asdict(restored) or input_fingerprint(project_inputs) != input_fingerprint(restored):
            raise BessStandaloneCandidateError("BESS02_DOCUMENT_INPUT_LOSS")
        result = _canonical({"version": 1, "scope": "CANDIDATE_REVIEW_ONLY", "base_inputs": base,
                             "native_json": parse_native_contract(native_json).canonical_json,
                             "declaration_json": _canonical(_declaration(declaration_json)),
                             "identity": _document_identity(prepared)})
        if len(result.encode("utf-8")) > MAX_DOCUMENT_BYTES:
            raise BessStandaloneCandidateError("BESS02_DOCUMENT_SIZE")
        return result
    except BessInputError:
        raise
    except (ValueError, TypeError, KeyError, AttributeError, RecursionError, OverflowError) as exc:
        raise BessStandaloneCandidateError("BESS02_DOCUMENT_INVALID") from exc


def import_candidate_document(raw: str) -> StandaloneCandidate:
    """Revalidate a bounded review document. Grants no lifecycle capability."""
    from finco_core.inputs.serialization import project_inputs_from_dict, project_inputs_to_dict
    if not isinstance(raw, str) or len(raw.encode("utf-8")) > MAX_DOCUMENT_BYTES:
        raise BessStandaloneCandidateError("BESS02_DOCUMENT_SIZE")
    try:
        obj = json.loads(raw, object_pairs_hook=_unique)
        if (not isinstance(obj, dict) or set(obj) != _DOCUMENT_KEYS
                or type(obj["version"]) is not int or obj["version"] != 1
                or obj["scope"] != "CANDIDATE_REVIEW_ONLY"
                or not isinstance(obj["base_inputs"], dict)
                or not isinstance(obj["native_json"], str)
                or not isinstance(obj["declaration_json"], str)):
            raise BessStandaloneCandidateError("BESS02_DOCUMENT_SCHEMA")
        restored = project_inputs_from_dict(obj["base_inputs"])
        # Refuse unknown fields, omitted defaults and type-changing coercions.
        if _canonical(project_inputs_to_dict(restored)) != _canonical(obj["base_inputs"]):
            raise BessStandaloneCandidateError("BESS02_DOCUMENT_INPUT_LOSS")
        prepared = prepare_candidate(restored, obj["native_json"], obj["declaration_json"])
        if obj["identity"] != _document_identity(prepared):
            raise BessStandaloneCandidateError("BESS02_DOCUMENT_IDENTITY")
        return prepared
    except BessInputError:
        raise
    except (ValueError, TypeError, KeyError, AttributeError, RecursionError, OverflowError) as exc:
        raise BessStandaloneCandidateError("BESS02_DOCUMENT_INVALID") from exc
