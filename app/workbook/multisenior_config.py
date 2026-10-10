"""Versioned, scope-bound F3 proposal/activation bridge for the existing CAS."""
from __future__ import annotations

from dataclasses import replace
import json
import math
import re
from uuid import NAMESPACE_URL, uuid5

from finco_core.inputs.financing_instruments import (
    FinancingCollection, FinancingError, FinancingInstrument, InstrumentType,
    DrawdownEntry, InterestTerms, RateMode, RepaymentTerms, RepaymentMode, MaturityAuthority,
)
from finco_core.inputs.multisenior import AUTHORITY, activate_collection, validate_effective_collection

FIELD_ID = "debt.financing.instruments"
SNAPSHOT_KEY = "financing_instruments_json"
SCHEMA = "f3-workspace-1.0"
# Release only after the complete financial, lifecycle and browser acceptance.
ACTIVATION_ENABLED = True
_SCOPE = re.compile(r"^(base|[0-9a-f]{16}|[0-9a-f]{32}|[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12})$")
ACTIVATION_KEYS = {"authority", "proposal_digest", "sponsor_funding_mode", "reserve_support_mode"}


def _unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise FinancingError("F3_DUPLICATE_JSON_KEY", key)
        result[key] = value
    return result


def parse_state(raw):
    if raw in (None, ""):
        return {"schema_version": SCHEMA, "scopes": {}}
    if not isinstance(raw, str) or len(raw) > 100000:
        raise FinancingError("F3_WORKSPACE_JSON_INVALID")
    try:
        state = json.loads(raw, object_pairs_hook=_unique)
    except (TypeError, json.JSONDecodeError) as exc:
        raise FinancingError("F3_WORKSPACE_JSON_INVALID") from exc
    if not isinstance(state, dict) or set(state) != {"schema_version", "scopes"} or state["schema_version"] != SCHEMA:
        raise FinancingError("F3_WORKSPACE_VERSION_UNSUPPORTED")
    scopes = state["scopes"]
    if not isinstance(scopes, dict) or len(scopes) > 100:
        raise FinancingError("F3_WORKSPACE_SCOPES_INVALID")
    canonical = {}
    for scope, entry in scopes.items():
        if not isinstance(scope, str) or not _SCOPE.fullmatch(scope) or not isinstance(entry, dict) or set(entry) != {"proposal", "activation"}:
            raise FinancingError("F3_WORKSPACE_SCOPE_INVALID")
        collection = FinancingCollection.from_dict(entry["proposal"])
        activation = entry["activation"]
        if activation is not None:
            if not isinstance(activation, dict) or set(activation) != ACTIVATION_KEYS or activation != {
                "authority": AUTHORITY, "proposal_digest": collection.content_digest(),
                "sponsor_funding_mode": "EQUITY_ONLY", "reserve_support_mode": "NONE",
            }:
                raise FinancingError("F3_ACTIVATION_AUTHORITY_INVALID")
            validate_effective_collection(collection)
        canonical[scope] = {"proposal": collection.to_dict(), "activation": activation}
    return {"schema_version": SCHEMA, "scopes": canonical}


def canonical_json(raw):
    # The write request may ask the server to bind its explicit activation to
    # this proposal. Persisted/read-side state always requires the actual hash.
    if isinstance(raw, str) and len(raw) <= 100000:
        try:
            request = json.loads(raw, object_pairs_hook=_unique)
            if isinstance(request, dict) and isinstance(request.get("scopes"), dict):
                for entry in request["scopes"].values():
                    activation = entry.get("activation") if isinstance(entry, dict) else None
                    if isinstance(activation, dict) and activation.get("proposal_digest") == "BIND_ON_SAVE":
                        activation["proposal_digest"] = FinancingCollection.from_dict(entry["proposal"]).content_digest()
                raw = json.dumps(request)
        except (TypeError, json.JSONDecodeError):
            pass  # The strict parser below returns the typed error.
    return json.dumps(parse_state(raw), sort_keys=True, separators=(",", ":"))


def validate_transition(old_raw, new_raw, scope):
    """Called with the live selected scope INSIDE the workspace CAS transaction."""
    old, new = parse_state(old_raw), parse_state(new_raw)
    previous, incoming = old["scopes"], new["scopes"]
    for key in set(previous) | set(incoming):
        if key != scope and previous.get(key) != incoming.get(key):
            raise FinancingError("F3_CROSS_SCENARIO_WRITE_REJECTED", key)
    old_entry, new_entry = previous.get(scope), incoming.get(scope)
    if old_entry is not None:
        if new_entry is None:
            raise FinancingError("F3_INSTRUMENT_ID_REMOVAL_REJECTED", "Deactivate instead of deleting stable IDs.")
        old_ids = {i["instrument_id"] for i in old_entry["proposal"]["instruments"]}
        new_ids = {i["instrument_id"] for i in new_entry["proposal"]["instruments"]}
        if old_ids != new_ids:
            raise FinancingError("F3_INSTRUMENT_ID_MUTATION_REJECTED")


def scope_for_workspace(ws):
    if not getattr(ws, "active_scenario_id", None):
        return "base"
    from app.persistence.scenarios_repository import get_scenario
    record = get_scenario(ws.active_scenario_id, ws.user_id)
    if record is None or record.archived or record.project_id != ws.project_id:
        raise FinancingError("F3_SELECTED_SCENARIO_UNAVAILABLE")
    return "base" if record.is_base_case else record.scenario_id


def activation_financing_params(fin):
    """Two explicit activation policies; shared by Run and Working presentation."""
    from finco_core.inputs import SponsorFundingMode, DebtServiceReserveSupportMode
    from financial_engine.dsra.target import DsraTargetPolicy
    # NONE plus legacy months alone is inert. Explicit support, amounts or a
    # dynamic target are independent authority, not consent to erase reserves.
    neutral_amounts = all(
        not isinstance(value, bool) and isinstance(value, (int, float))
        and math.isfinite(value) and value == 0.
        for value in (fin.debt_service_reserve_requirement_keur,
                      fin.dsrf_commitment_keur, fin.dsrf_commitment_fee_rate_pa)
    )
    if (fin.dsra_support_mode is not DebtServiceReserveSupportMode.NONE
        or not neutral_amounts
        or fin.dsra_target_policy not in (None, DsraTargetPolicy.FIXED_AMOUNT.value)):
        raise FinancingError("F3_EXISTING_RESERVE_AUTHORITY_CONFLICT",
            "Existing reserve support, amounts or targets cannot be discarded by two-Senior activation.")
    return replace(fin, sponsor_funding_mode=SponsorFundingMode.EQUITY_ONLY,
        dsra_support_mode=DebtServiceReserveSupportMode.NONE, dsra_months=0,
        debt_service_reserve_requirement_keur=0., dsra_target_policy=None,
        dsrf_commitment_keur=0., dsrf_commitment_fee_rate_pa=0.)


def apply_state(pi, raw, scope, *, enforce_release=True, bankability_raw=None):
    entry = parse_state(raw)["scopes"].get(scope)
    if entry is None or entry["activation"] is None:
        return pi
    if enforce_release and not ACTIVATION_ENABLED:
        raise FinancingError("F3_ACTIVATION_ACCEPTANCE_BLOCKED")
    if bankability_raw:
        from app.workbook.bankability_config import parse_config
        if any(value is not None for key, value in parse_config(bankability_raw).items() if key != "version"):
            raise FinancingError("F3_BANKABILITY_AUTHORITY_CONFLICT", "Reset the single-Senior configuration before activation.")
    if pi.financing.construction_financing is not None or pi.capex.reserve_accounts_keur:
        raise FinancingError("F3_EXISTING_CONSTRUCTION_OR_RESERVE_AUTHORITY_CONFLICT")
    # These two policies are explicit mandatory activation terms, not defaults
    # guessed from project identity, a missing SHL input or a prior Run output.
    fin = activation_financing_params(pi.financing)
    active = activate_collection(replace(pi, financing=fin), FinancingCollection.from_dict(entry["proposal"]))
    from financial_engine.financing.multisenior import validate_project_boundary
    validate_project_boundary(active)
    return active


def build_view(pi, raw, scope, runtime_summary, *, owner_id, project_id):
    if pi is None:
        return {"available": False, "active": False, "reason": "Project inputs are unavailable."}
    state = parse_state(raw)
    entry = state["scopes"].get(scope)
    if entry is None:
        if not isinstance(owner_id, str) or not owner_id or not isinstance(project_id, str) or not project_id:
            raise FinancingError("F3_PROPOSAL_SCOPE_REQUIRED")
        from financial_engine.adapters.project_inputs import from_project_inputs
        from financial_engine.orchestrator import _build_period_engine
        # Calendar metadata only: opening this sheet never runs a model.
        periods = _build_period_engine(from_project_inputs(pi)).periods()
        op = [p for p in periods if p.is_operation]
        construction = [p for p in periods if p.is_construction]
        if not op or not construction:
            return {"available": False, "active": False, "reason": "Construction and operating calendars are required."}
        # An unsaved editor is repeatable presentation, not a database write.
        # Once saved, the persisted IDs above remain authoritative unchanged.
        collection = FinancingCollection(tuple(FinancingInstrument(
            instrument_id="senior-" + uuid5(NAMESPACE_URL, json.dumps(
                ["finco-f3-proposal-v1", owner_id, project_id, scope, label],
                separators=(",", ":"))).hex, instrument_type=InstrumentType.SENIOR_TERM_LOAN,
            name=f"Senior {label}", commitment_keur=0.,
            drawdowns=(DrawdownEntry(construction[min(i, len(construction) - 1)].start_date, 0.),),
            interest=InterestTerms(RateMode.FIXED, fixed_rate=0.),
            repayment=RepaymentTerms(RepaymentMode.LEVEL_PRINCIPAL,
                maturity_authority=MaturityAuthority.EXPLICIT_DATE,
                maturity_date=op[min((i + 1) * 10, len(op)) - 1].end_date)) for i, label in enumerate(("A", "B"))))
        entry = {"proposal": collection.to_dict(), "activation": None}
    return {"available": True, "state": state, "scope": scope, "entry": entry, "active": entry["activation"] is not None,
        "release_enabled": ACTIVATION_ENABLED,
        "last_run": (runtime_summary or {}).get("financing_evidence", {}).get("facility_schedules"),
        "last_construction": (runtime_summary or {}).get("financing_evidence", {}).get("construction_funding", {}).get("periods", ()),
        "authority": AUTHORITY}
