"""Model V2 Working Copy persistence — typed, versioned, fail-closed.

Workflow 07 turns the Model V2 composition contracts (Workflow 02
RevenuePlan, Workflow 03 CostTemplate materialization, Workflow 05
selection wrappers) from an in-memory architecture into a durable run
lifecycle:

    Working Copy → persisted V2 selections → reload → canonical
    composition → canonical engine run → successful Last Run binding →
    staleness detection after Working Copy edits.

This module owns THREE authorities:

1. TYPED SERIALIZATION. ``working_state_to_json`` / ``working_state_from_json``
   round-trip a ``ModelV2WorkingState`` through deterministic, versioned,
   JSON-compatible payloads. Round-trip is exact for economically
   authoritative data: MISSING stays MISSING (``None`` never becomes
   ``0.0``), explicit ZERO stays ZERO, ``False`` stays ``False``, empty
   tuples stay empty tuples, enums restore to the same typed meaning and
   ordering is deterministic. Unknown schema versions, unknown payload
   keys, malformed numerics, NaN/Infinity and bool-as-number all fail
   closed (``ModelV2PersistenceError``). Raw pickle and arbitrary Python
   object representations are never stored.

2. RUN BINDING. ``build_run_binding_payload`` captures, at run time, the
   identity of the V2 Working Copy economic state that produced a
   successful canonical run. The payload is embedded under the ``"model_v2"``
   key of the run identity written atomically by
   ``app.persistence.workspace_repository.v2_atomic_run_commit`` — the
   canonical run id / snapshot id / workbook composite hash remain THE run
   identity; the Model V2 payload binds that run to the exact composed
   input state (``composition_hash`` plus the scenario-independent
   ``economic_identity``). The composition hash is never treated as the
   run identity itself.

3. STALENESS. ``resolve_workspace_model_v2_staleness`` deterministically
   compares the CURRENT Working Copy V2 economic state against the bound run
   identity — but only after verifying the binding still describes the
   CURRENT Last Run (``snapshot_id`` correlation): a later run that did not
   pass a binding forward (e.g. a legacy run) must never be misattributed to
   an older V2-bound run's economic state. The comparison reuses
   ``ModelV2WorkingState.selection_digest()`` — the existing Workflow 05
   economic identity authority — as the comparison basis, so staleness
   semantics follow the canonical identity (cost labels and other
   non-economic metadata excluded by that authority cannot create a false
   STALE; the plan-level metadata fields the authority includes do).

Absence semantics: an empty persistence payload means "no Model V2
state" — exactly the legacy state. A legacy project never silently
acquires V2 state by loading, saving or re-saving. Absence of a selection
is represented by an explicit ``None`` in the payload, never by a zeroed
placeholder (MISSING != ZERO).
"""
from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass
from enum import Enum
from typing import Any, Mapping, Optional

from app.services.model_v2_composition.contracts import (
    MODEL_V2_COMPOSITION_SCHEMA,
    CostTemplateSelection,
    ModelV2WorkingState,
    RevenuePlanSelection,
)
from app.services.cost_template.materialize import (
    CapexFieldPlan,
    CapexSubLinePlan,
    ContingencyPlan,
    MaterializationPlan,
    OpexItemPlan,
    OpexSubLinePlan,
)
from domain.revenue.plan import (
    RevenueAllocationGroup,
    RevenuePlan,
    RevenueStream,
    RevenueStreamType,
)
from domain.revenue.revenue_config import (
    CfDParams,
    FeedInTariffParams,
    MerchantParams,
    PPAParams,
)

# ---------------------------------------------------------------------------
# Schema identity
# ---------------------------------------------------------------------------

#: Versioned persistence payload for the V2 Working Copy selection state.
MODEL_V2_WORKING_STATE_SCHEMA = "finco.model-v2.working-state"
MODEL_V2_WORKING_STATE_SCHEMA_VERSION = 1

#: Versioned payload of a typed RevenuePlan (embedded in the working state).
MODEL_V2_REVENUE_PLAN_SCHEMA = "finco.model-v2.revenue-plan"
MODEL_V2_REVENUE_PLAN_SCHEMA_VERSION = 1

#: Versioned payload of a Workflow 03 MaterializationPlan.
MODEL_V2_MATERIALIZATION_PLAN_SCHEMA = "finco.model-v2.materialization-plan"
MODEL_V2_MATERIALIZATION_PLAN_SCHEMA_VERSION = 1

#: Versioned run-bound identity of the V2 economic state behind a
#: successful canonical run (embedded in ``last_runtime_identity_json``).
MODEL_V2_RUN_BINDING_SCHEMA = "finco.model-v2.run-binding"
MODEL_V2_RUN_BINDING_SCHEMA_VERSION = 1

_HEX64 = re.compile(r"^[0-9a-f]{64}$")


class ModelV2PersistenceError(Exception):
    """Raised when Model V2 persistence input/output is malformed or from
    an unsupported schema version (fail closed — nothing is silently
    coerced, dropped or defaulted)."""


# ---------------------------------------------------------------------------
# Strict primitive validation (decode side)
# ---------------------------------------------------------------------------


def _fail(where: str, expected: str, value: Any) -> "ModelV2PersistenceError":
    return ModelV2PersistenceError(
        f"MODEL_V2_PERSISTENCE_MALFORMED: {where} must be {expected}, "
        f"got {type(value).__name__} {value!r}"
    )


def _strict_bool(value: Any, where: str) -> bool:
    if type(value) is not bool:
        raise _fail(where, "a strict boolean", value)
    return value


def _strict_int(value: Any, where: str) -> int:
    # bool is an int subclass in Python — reject it explicitly so a JSON
    # `true` can never masquerade as a year/version/count.
    if type(value) is not int:
        raise _fail(where, "an integer", value)
    return value


def _optional_str(value: Any, where: str) -> Optional[str]:
    if value is None:
        return None
    if not isinstance(value, str):
        raise _fail(where, "a string or null", value)
    return value


def _strict_str(value: Any, where: str) -> str:
    if not isinstance(value, str):
        raise _fail(where, "a string", value)
    return value


def _strict_number(value: Any, where: str) -> Any:
    """Numeric passthrough that only rejects non-numeric garbage. The
    encoded numeric type (int vs float) is preserved verbatim so an
    explicitly encoded 0 survives as ZERO and 9000 stays 9000."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise _fail(where, "a finite number", value)
    if isinstance(value, float) and not math.isfinite(value):
        raise _fail(where, "a finite number", value)
    return value

def _optional_number(value: Any, where: str) -> Any:
    """None stays None (MISSING); a number is validated but its exact
    numeric representation (int vs float) is preserved verbatim — the
    canonical composition identity is int/float sensitive, so coercion
    would silently change economics identity."""
    if value is None:
        return None
    return _strict_number(value, where)


def _expect_object(value: Any, where: str, keys: frozenset) -> dict:
    if not isinstance(value, dict):
        raise _fail(where, "an object", value)
    actual = set(value.keys())
    unknown = actual - keys
    if unknown:
        raise ModelV2PersistenceError(
            f"MODEL_V2_PERSISTENCE_MALFORMED: {where} carries unsupported "
            f"key(s) {sorted(unknown)}; this decoder only understands schema "
            f"version {MODEL_V2_WORKING_STATE_SCHEMA_VERSION} exactly"
        )
    missing = keys - actual
    if missing:
        raise ModelV2PersistenceError(
            f"MODEL_V2_PERSISTENCE_MALFORMED: {where} is missing required "
            f"key(s) {sorted(missing)}"
        )
    return value


def _reject_constant(name: str) -> Any:
    raise ModelV2PersistenceError(
        f"MODEL_V2_PERSISTENCE_MALFORMED: payload contains the non-finite "
        f"JSON constant {name!r} (NaN/Infinity are not valid economics)"
    )


def _reject_unserializable(value: Any) -> Any:
    raise ModelV2PersistenceError(
        f"MODEL_V2_PERSISTENCE_MALFORMED: value of type "
        f"{type(value).__name__} is not JSON-native and cannot be persisted "
        "(no pickle, no arbitrary Python object representations)"
    )


def _canonical_dumps(payload: Any) -> str:
    try:
        return json.dumps(
            payload,
            sort_keys=True,
            ensure_ascii=True,
            allow_nan=False,
            separators=(",", ":"),
            default=_reject_unserializable,
        )
    except ModelV2PersistenceError:
        raise
    except ValueError as exc:
        # allow_nan=False refuses NaN/Infinity; default= refuses non-JSON
        # objects — both are fail-closed encode rejections (metadata dicts
        # are not domain-validated, so this is the final guard).
        raise ModelV2PersistenceError(
            f"MODEL_V2_PERSISTENCE_MALFORMED: payload cannot be canonically "
            f"serialized ({exc})"
        ) from None


def _schema_header(payload: dict, schema: str, version: int, where: str) -> None:
    if payload.get("_schema") != schema:
        raise ModelV2PersistenceError(
            f"MODEL_V2_PERSISTENCE_UNKNOWN_SCHEMA: {where} carries "
            f"_schema={payload.get('_schema')!r}, expected {schema!r} "
            "(unknown schemas fail closed)"
        )
    found_version = payload.get("schema_version")
    if type(found_version) is not int or isinstance(found_version, bool):
        raise ModelV2PersistenceError(
            f"MODEL_V2_PERSISTENCE_MALFORMED: {where} schema_version must be "
            f"an integer, got {found_version!r}"
        )
    if found_version != version:
        raise ModelV2PersistenceError(
            f"MODEL_V2_PERSISTENCE_UNSUPPORTED_VERSION: {where} schema "
            f"version {found_version} is not supported by this decoder "
            f"(supported: {version}); refusing to guess economics across a "
            "schema change"
        )


# ---------------------------------------------------------------------------
# RevenuePlan codec
# ---------------------------------------------------------------------------


def _encode_ppa_params(ppa: PPAParams) -> dict:
    return {
        "ppa_enabled": bool(ppa.ppa_enabled),
        "ppa_counterparty": ppa.ppa_counterparty,
        "ppa_type": ppa.ppa_type,
        "ppa_base_price_eur_mwh": ppa.ppa_base_price_eur_mwh,
        "ppa_price_index": ppa.ppa_price_index,
        "ppa_price_floor": ppa.ppa_price_floor,
        "ppa_price_cap": ppa.ppa_price_cap,
        "ppa_start_year": ppa.ppa_start_year,
        "ppa_term_years": ppa.ppa_term_years,
        "ppa_volume_share": ppa.ppa_volume_share,
        "ppa_shape_hours": list(ppa.ppa_shape_hours),
        "balancing_cost_pct": ppa.balancing_cost_pct,
        "imbalance_penalty_pct": ppa.imbalance_penalty_pct,
        "offtaker_credit_rating": ppa.offtaker_credit_rating,
        "termination_fee_keur": ppa.termination_fee_keur,
    }


def _decode_ppa_params(payload: Any, where: str) -> PPAParams:
    _expect_object(
        payload, where, frozenset(_encode_ppa_params(PPAParams()).keys()))
    return PPAParams(
        ppa_enabled=_strict_bool(payload["ppa_enabled"], f"{where}.ppa_enabled"),
        ppa_counterparty=_strict_str(payload["ppa_counterparty"], f"{where}.ppa_counterparty"),
        ppa_type=_strict_str(payload["ppa_type"], f"{where}.ppa_type"),
        ppa_base_price_eur_mwh=_strict_number(payload["ppa_base_price_eur_mwh"], f"{where}.ppa_base_price_eur_mwh"),
        ppa_price_index=_strict_number(payload["ppa_price_index"], f"{where}.ppa_price_index"),
        ppa_price_floor=_strict_number(payload["ppa_price_floor"], f"{where}.ppa_price_floor"),
        ppa_price_cap=_strict_number(payload["ppa_price_cap"], f"{where}.ppa_price_cap"),
        ppa_start_year=_strict_int(payload["ppa_start_year"], f"{where}.ppa_start_year"),
        ppa_term_years=_strict_number(payload["ppa_term_years"], f"{where}.ppa_term_years"),
        ppa_volume_share=_strict_number(payload["ppa_volume_share"], f"{where}.ppa_volume_share"),
        ppa_shape_hours=_decode_untyped_tuple(payload["ppa_shape_hours"], f"{where}.ppa_shape_hours"),
        balancing_cost_pct=_strict_number(payload["balancing_cost_pct"], f"{where}.balancing_cost_pct"),
        imbalance_penalty_pct=_strict_number(payload["imbalance_penalty_pct"], f"{where}.imbalance_penalty_pct"),
        offtaker_credit_rating=_strict_str(payload["offtaker_credit_rating"], f"{where}.offtaker_credit_rating"),
        termination_fee_keur=_strict_number(payload["termination_fee_keur"], f"{where}.termination_fee_keur"),
    )


def _encode_merchant_params(mp: MerchantParams) -> dict:
    return {
        "merchant_enabled": bool(mp.merchant_enabled),
        "market_zone": mp.market_zone,
        "base_price_eur_mwh": mp.base_price_eur_mwh,
        "price_escalation_annual": mp.price_escalation_annual,
        "price_volatility_pct": mp.price_volatility_pct,
        "price_cannibalization_pct": mp.price_cannibalization_pct,
        "capture_rate_solar": mp.capture_rate_solar,
        "capture_rate_wind": mp.capture_rate_wind,
        "capture_rate_bess": mp.capture_rate_bess,
        "price_scenario": mp.price_scenario,
        "custom_price_curve": list(mp.custom_price_curve),
    }


def _decode_merchant_params(payload: Any, where: str) -> MerchantParams:
    _expect_object(
        payload, where, frozenset(_encode_merchant_params(MerchantParams()).keys()))
    return MerchantParams(
        merchant_enabled=_strict_bool(payload["merchant_enabled"], f"{where}.merchant_enabled"),
        market_zone=_strict_str(payload["market_zone"], f"{where}.market_zone"),
        base_price_eur_mwh=_strict_number(payload["base_price_eur_mwh"], f"{where}.base_price_eur_mwh"),
        price_escalation_annual=_strict_number(payload["price_escalation_annual"], f"{where}.price_escalation_annual"),
        price_volatility_pct=_strict_number(payload["price_volatility_pct"], f"{where}.price_volatility_pct"),
        price_cannibalization_pct=_strict_number(payload["price_cannibalization_pct"], f"{where}.price_cannibalization_pct"),
        capture_rate_solar=_strict_number(payload["capture_rate_solar"], f"{where}.capture_rate_solar"),
        capture_rate_wind=_strict_number(payload["capture_rate_wind"], f"{where}.capture_rate_wind"),
        capture_rate_bess=_strict_number(payload["capture_rate_bess"], f"{where}.capture_rate_bess"),
        price_scenario=_strict_str(payload["price_scenario"], f"{where}.price_scenario"),
        custom_price_curve=_decode_untyped_tuple(payload["custom_price_curve"], f"{where}.custom_price_curve"),
    )


def _encode_fit_params(fit: FeedInTariffParams) -> dict:
    return {
        "fit_enabled": bool(fit.fit_enabled),
        "fit_type": fit.fit_type,
        "fit_price_eur_mwh": fit.fit_price_eur_mwh,
        "fit_term_years": fit.fit_term_years,
        "fit_index": fit.fit_index,
        "premium_eur_mwh": fit.premium_eur_mwh,
        "premium_cap_eur_mwh": fit.premium_cap_eur_mwh,
        "premium_floor_eur_mwh": fit.premium_floor_eur_mwh,
        "fit_scheme": fit.fit_scheme,
        "eligible_capacity_mw": fit.eligible_capacity_mw,
        "annual_production_cap_mwh": fit.annual_production_cap_mwh,
    }


def _decode_fit_params(payload: Any, where: str) -> FeedInTariffParams:
    _expect_object(
        payload, where, frozenset(_encode_fit_params(FeedInTariffParams()).keys()))
    return FeedInTariffParams(
        fit_enabled=_strict_bool(payload["fit_enabled"], f"{where}.fit_enabled"),
        fit_type=_strict_str(payload["fit_type"], f"{where}.fit_type"),
        fit_price_eur_mwh=_strict_number(payload["fit_price_eur_mwh"], f"{where}.fit_price_eur_mwh"),
        fit_term_years=_strict_int(payload["fit_term_years"], f"{where}.fit_term_years"),
        fit_index=_strict_number(payload["fit_index"], f"{where}.fit_index"),
        premium_eur_mwh=_strict_number(payload["premium_eur_mwh"], f"{where}.premium_eur_mwh"),
        premium_cap_eur_mwh=_strict_number(payload["premium_cap_eur_mwh"], f"{where}.premium_cap_eur_mwh"),
        premium_floor_eur_mwh=_strict_number(payload["premium_floor_eur_mwh"], f"{where}.premium_floor_eur_mwh"),
        fit_scheme=_strict_str(payload["fit_scheme"], f"{where}.fit_scheme"),
        eligible_capacity_mw=_strict_number(payload["eligible_capacity_mw"], f"{where}.eligible_capacity_mw"),
        annual_production_cap_mwh=_strict_number(payload["annual_production_cap_mwh"], f"{where}.annual_production_cap_mwh"),
    )


def _encode_cfd_params(cfd: CfDParams) -> dict:
    return {
        "cfd_enabled": bool(cfd.cfd_enabled),
        "strike_price_eur_mwh": cfd.strike_price_eur_mwh,
        "reference_price_type": cfd.reference_price_type,
        "cfd_term_years": cfd.cfd_term_years,
        "cfd_volume_mwh_annual": cfd.cfd_volume_mwh_annual,
        "two_way_cfd": bool(cfd.two_way_cfd),
        "cfd_counterparty": cfd.cfd_counterparty,
        "cfd_guarantee": cfd.cfd_guarantee,
    }


def _decode_cfd_params(payload: Any, where: str) -> CfDParams:
    _expect_object(
        payload, where, frozenset(_encode_cfd_params(CfDParams()).keys()))
    return CfDParams(
        cfd_enabled=_strict_bool(payload["cfd_enabled"], f"{where}.cfd_enabled"),
        strike_price_eur_mwh=_strict_number(payload["strike_price_eur_mwh"], f"{where}.strike_price_eur_mwh"),
        reference_price_type=_strict_str(payload["reference_price_type"], f"{where}.reference_price_type"),
        cfd_term_years=_strict_int(payload["cfd_term_years"], f"{where}.cfd_term_years"),
        cfd_volume_mwh_annual=_strict_number(payload["cfd_volume_mwh_annual"], f"{where}.cfd_volume_mwh_annual"),
        two_way_cfd=_strict_bool(payload["two_way_cfd"], f"{where}.two_way_cfd"),
        cfd_counterparty=_strict_str(payload["cfd_counterparty"], f"{where}.cfd_counterparty"),
        cfd_guarantee=_strict_str(payload["cfd_guarantee"], f"{where}.cfd_guarantee"),
    )


def _decode_untyped_tuple(value: Any, where: str) -> tuple:
    """Restore an untyped tuple field (``ppa_shape_hours`` /
    ``custom_price_curve``). Encoded as a JSON array; the top level is
    restored as a tuple. An empty list stays an empty tuple (never None).
    The domain contract uses these fields for numeric series (EUR/MWh
    curves, shape hours), so elements must be finite numbers — a numeric
    STRING would silently pass ``float()`` coercion downstream and flip
    the canonical identity, so it fails closed here."""
    if not isinstance(value, list):
        raise _fail(where, "an array", value)
    for i, element in enumerate(value):
        if isinstance(element, bool) or not isinstance(element, (int, float)) \
                or (isinstance(element, float) and not math.isfinite(element)):
            raise _fail(f"{where}[{i}]", "a finite number", element)
    return tuple(value)


_STREAM_KEYS = frozenset({
    "stream_id", "stream_type", "name", "enabled", "start_year", "term_years",
    "allocation_group", "volume_share", "ppa", "merchant", "fit", "cfd",
    "indexed_fit_base_tariff_eur_mwh", "indexed_fit_index_factors",
    "reference_stream_id", "lender_eligible", "counterparty",
})


def _encode_stream(stream: RevenueStream) -> dict:
    return {
        "stream_id": stream.stream_id,
        "stream_type": stream.stream_type.value,
        "name": stream.name,
        "enabled": bool(stream.enabled),
        "start_year": stream.start_year,
        "term_years": stream.term_years,
        "allocation_group": stream.allocation_group,
        "volume_share": stream.volume_share,
        "ppa": None if stream.ppa is None else _encode_ppa_params(stream.ppa),
        "merchant": None if stream.merchant is None else _encode_merchant_params(stream.merchant),
        "fit": None if stream.fit is None else _encode_fit_params(stream.fit),
        "cfd": None if stream.cfd is None else _encode_cfd_params(stream.cfd),
        "indexed_fit_base_tariff_eur_mwh": stream.indexed_fit_base_tariff_eur_mwh,
        "indexed_fit_index_factors": list(stream.indexed_fit_index_factors),
        "reference_stream_id": stream.reference_stream_id,
        "lender_eligible": bool(stream.lender_eligible),
        "counterparty": stream.counterparty,
    }


def _decode_stream(payload: Any, where: str) -> RevenueStream:
    _expect_object(payload, where, _STREAM_KEYS)
    raw_type = payload["stream_type"]
    try:
        stream_type = RevenueStreamType(raw_type)
    except ValueError:
        raise ModelV2PersistenceError(
            f"MODEL_V2_PERSISTENCE_MALFORMED: {where}.stream_type "
            f"{raw_type!r} is not a RevenueStreamType member"
        ) from None
    term_years = payload["term_years"]
    if term_years is not None:
        term_years = _strict_number(term_years, f"{where}.term_years")
    volume_share = payload["volume_share"]
    if volume_share is not None:
        volume_share = _strict_number(volume_share, f"{where}.volume_share")
    indexed_base = payload["indexed_fit_base_tariff_eur_mwh"]
    if indexed_base is not None:
        indexed_base = _strict_number(indexed_base, f"{where}.indexed_fit_base_tariff_eur_mwh")
    factors = payload["indexed_fit_index_factors"]
    if not isinstance(factors, list):
        raise _fail(f"{where}.indexed_fit_index_factors", "an array", factors)
    return RevenueStream(
        stream_id=_strict_str(payload["stream_id"], f"{where}.stream_id"),
        stream_type=stream_type,
        name=_strict_str(payload["name"], f"{where}.name"),
        enabled=_strict_bool(payload["enabled"], f"{where}.enabled"),
        start_year=_strict_int(payload["start_year"], f"{where}.start_year"),
        term_years=term_years,
        allocation_group=_strict_str(payload["allocation_group"], f"{where}.allocation_group"),
        volume_share=volume_share,
        ppa=None if payload["ppa"] is None else _decode_ppa_params(payload["ppa"], f"{where}.ppa"),
        merchant=None if payload["merchant"] is None else _decode_merchant_params(payload["merchant"], f"{where}.merchant"),
        fit=None if payload["fit"] is None else _decode_fit_params(payload["fit"], f"{where}.fit"),
        cfd=None if payload["cfd"] is None else _decode_cfd_params(payload["cfd"], f"{where}.cfd"),
        indexed_fit_base_tariff_eur_mwh=indexed_base,
        indexed_fit_index_factors=tuple(
            _strict_number(f, f"{where}.indexed_fit_index_factors[{i}]")
            for i, f in enumerate(factors)),
        reference_stream_id=_optional_str(payload["reference_stream_id"], f"{where}.reference_stream_id"),
        lender_eligible=_strict_bool(payload["lender_eligible"], f"{where}.lender_eligible"),
        counterparty=_strict_str(payload["counterparty"], f"{where}.counterparty"),
    )


def plan_to_payload(plan: RevenuePlan) -> dict:
    """Encode a typed, validated RevenuePlan into its versioned payload."""
    if not isinstance(plan, RevenuePlan):
        raise ModelV2PersistenceError(
            f"MODEL_V2_PERSISTENCE_TYPE_INVALID: revenue plan persistence "
            f"requires a domain.revenue.plan.RevenuePlan, got "
            f"{type(plan).__name__}"
        )
    plan.validate()
    return {
        "_schema": MODEL_V2_REVENUE_PLAN_SCHEMA,
        "schema_version": MODEL_V2_REVENUE_PLAN_SCHEMA_VERSION,
        "streams": [_encode_stream(s) for s in plan.ordered_streams()],
        "allocation_groups": [
            {"group_id": g.group_id, "description": g.description}
            for g in sorted(plan.allocation_groups, key=lambda g: g.group_id)
        ],
        "market_price": (
            None if plan.market_price is None
            else _encode_merchant_params(plan.market_price)
        ),
    }


def plan_from_payload(payload: Any) -> RevenuePlan:
    """Decode and rebuild a RevenuePlan. Domain validation re-runs on the
    rebuilt plan (fail closed on any economic defect)."""
    where = "revenue_plan"
    _expect_object(
        payload, where, frozenset({
            "_schema", "schema_version", "streams", "allocation_groups",
            "market_price",
        }))
    _schema_header(payload, MODEL_V2_REVENUE_PLAN_SCHEMA,
                   MODEL_V2_REVENUE_PLAN_SCHEMA_VERSION, where)
    streams_raw = payload["streams"]
    if not isinstance(streams_raw, list):
        raise _fail(f"{where}.streams", "an array", streams_raw)
    streams = [
        _decode_stream(s, f"{where}.streams[{i}]")
        for i, s in enumerate(streams_raw)
    ]
    groups_raw = payload["allocation_groups"]
    if not isinstance(groups_raw, list):
        raise _fail(f"{where}.allocation_groups", "an array", groups_raw)
    groups = []
    for i, g in enumerate(groups_raw):
        _expect_object(g, f"{where}.allocation_groups[{i}]",
                       frozenset({"group_id", "description"}))
        groups.append(RevenueAllocationGroup(
            group_id=_strict_str(g["group_id"], f"{where}.allocation_groups[{i}].group_id"),
            description=_strict_str(g["description"], f"{where}.allocation_groups[{i}].description"),
        ))
    market_price = payload["market_price"]
    if market_price is not None:
        market_price = _decode_merchant_params(market_price, f"{where}.market_price")
    return RevenuePlan.create(
        tuple(streams), allocation_groups=tuple(groups), market_price=market_price)


# ---------------------------------------------------------------------------
# MaterializationPlan codec
# ---------------------------------------------------------------------------


def _encode_capex_field(fp: CapexFieldPlan) -> dict:
    # Encode-side strictness mirrors the decoder: a payload this boundary
    # writes must always be decodable (no permanently unreadable rows).
    for i, value in enumerate(fp.spending_profile):
        _strict_number(value, f"capex_fields.spending_profile[{i}]")
    if fp.useful_life_override is not None:
        _strict_int(fp.useful_life_override, "capex_fields.useful_life_override")
    _strict_number(fp.amount_keur, "capex_fields.amount_keur")
    _strict_number(fp.y0_share, "capex_fields.y0_share")
    return {
        "field_name": fp.field_name,
        "parent_code": fp.parent_code,
        "label": fp.label,
        "amount_keur": fp.amount_keur,
        "y0_share": fp.y0_share,
        "spending_profile": list(fp.spending_profile),
        "asset_class": fp.asset_class,
        "useful_life_override": fp.useful_life_override,
        "is_depreciable": bool(fp.is_depreciable),
        "is_active": bool(fp.is_active),
    }


def _decode_capex_field(payload: Any, where: str) -> CapexFieldPlan:
    _expect_object(payload, where, frozenset(_encode_capex_field(CapexFieldPlan(
        field_name="", parent_code="", label="", amount_keur=0.0)).keys()))
    useful_life = payload["useful_life_override"]
    if useful_life is not None:
        useful_life = _strict_int(useful_life, f"{where}.useful_life_override")
    profile = payload["spending_profile"]
    if not isinstance(profile, list):
        raise _fail(f"{where}.spending_profile", "an array", profile)
    return CapexFieldPlan(
        field_name=_strict_str(payload["field_name"], f"{where}.field_name"),
        parent_code=_strict_str(payload["parent_code"], f"{where}.parent_code"),
        label=_strict_str(payload["label"], f"{where}.label"),
        amount_keur=_strict_number(payload["amount_keur"], f"{where}.amount_keur"),
        y0_share=_strict_number(payload["y0_share"], f"{where}.y0_share"),
        spending_profile=tuple(
            _strict_number(v, f"{where}.spending_profile[{i}]")
            for i, v in enumerate(profile)),
        asset_class=_optional_str(payload["asset_class"], f"{where}.asset_class"),
        useful_life_override=useful_life,
        is_depreciable=_strict_bool(payload["is_depreciable"], f"{where}.is_depreciable"),
        is_active=_strict_bool(payload["is_active"], f"{where}.is_active"),
    )


def _encode_capex_sub_line(s: CapexSubLinePlan) -> dict:
    return {
        "parent_category_code": s.parent_category_code,
        "business_code": s.business_code,
        "label": s.label,
        "amount_keur": s.amount_keur,
        "schedule_json": s.schedule_json,
        "source": s.source,
        "replay_metadata": dict(s.replay_metadata),
        "scalar_metadata": dict(s.scalar_metadata),
        "is_active": bool(s.is_active),
    }


def _decode_capex_sub_line(payload: Any, where: str) -> CapexSubLinePlan:
    _expect_object(payload, where, frozenset(_encode_capex_sub_line(CapexSubLinePlan(
        parent_category_code="", business_code="", label="", amount_keur=0.0)).keys()))
    return CapexSubLinePlan(
        parent_category_code=_strict_str(payload["parent_category_code"], f"{where}.parent_category_code"),
        business_code=_strict_str(payload["business_code"], f"{where}.business_code"),
        label=_strict_str(payload["label"], f"{where}.label"),
        amount_keur=_strict_number(payload["amount_keur"], f"{where}.amount_keur"),
        schedule_json=_strict_str(payload["schedule_json"], f"{where}.schedule_json"),
        source=_strict_str(payload["source"], f"{where}.source"),
        replay_metadata=_decode_json_dict(payload["replay_metadata"], f"{where}.replay_metadata"),
        scalar_metadata=_decode_json_dict(payload["scalar_metadata"], f"{where}.scalar_metadata"),
        is_active=_strict_bool(payload["is_active"], f"{where}.is_active"),
    )


def _encode_opex_item(op: OpexItemPlan) -> dict:
    # Encode-side strictness mirrors the decoder (see _encode_capex_field).
    for i, (year, amount) in enumerate(op.step_changes):
        _strict_int(year, f"opex_items.step_changes[{i}].year")
        _strict_number(amount, f"opex_items.step_changes[{i}].amount")
    _strict_number(op.y1_amount_keur, "opex_items.y1_amount_keur")
    _strict_number(op.annual_inflation, "opex_items.annual_inflation")
    _strict_number(op.percentage_of_opex, "opex_items.percentage_of_opex")
    return {
        "parent_code": op.parent_code,
        "name": op.name,
        "y1_amount_keur": op.y1_amount_keur,
        "annual_inflation": op.annual_inflation,
        "step_changes": [[year, amount] for year, amount in op.step_changes],
        "percentage_of_opex": op.percentage_of_opex,
        "is_active": bool(op.is_active),
    }


def _decode_opex_item(payload: Any, where: str) -> OpexItemPlan:
    _expect_object(payload, where, frozenset(_encode_opex_item(OpexItemPlan(
        parent_code="", name="", y1_amount_keur=0.0)).keys()))
    steps = payload["step_changes"]
    if not isinstance(steps, list):
        raise _fail(f"{where}.step_changes", "an array", steps)
    return OpexItemPlan(
        parent_code=_strict_str(payload["parent_code"], f"{where}.parent_code"),
        name=_strict_str(payload["name"], f"{where}.name"),
        y1_amount_keur=_strict_number(payload["y1_amount_keur"], f"{where}.y1_amount_keur"),
        annual_inflation=_strict_number(payload["annual_inflation"], f"{where}.annual_inflation"),
        step_changes=_decode_step_pairs(steps, f"{where}.step_changes"),
        percentage_of_opex=_strict_number(payload["percentage_of_opex"], f"{where}.percentage_of_opex"),
        is_active=_strict_bool(payload["is_active"], f"{where}.is_active"),
    )


def _encode_opex_sub_line(s: OpexSubLinePlan) -> dict:
    return {
        "parent_group_code": s.parent_group_code,
        "business_code": s.business_code,
        "label": s.label,
        "amount_keur": s.amount_keur,
        "inflation_pct": s.inflation_pct,
        "source": s.source,
        "replay_metadata": dict(s.replay_metadata),
        "is_active": bool(s.is_active),
    }


def _decode_opex_sub_line(payload: Any, where: str) -> OpexSubLinePlan:
    _expect_object(payload, where, frozenset(_encode_opex_sub_line(OpexSubLinePlan(
        parent_group_code="", business_code="", label="", amount_keur=0.0)).keys()))
    return OpexSubLinePlan(
        parent_group_code=_strict_str(payload["parent_group_code"], f"{where}.parent_group_code"),
        business_code=_strict_str(payload["business_code"], f"{where}.business_code"),
        label=_strict_str(payload["label"], f"{where}.label"),
        amount_keur=_strict_number(payload["amount_keur"], f"{where}.amount_keur"),
        inflation_pct=_strict_number(payload["inflation_pct"], f"{where}.inflation_pct"),
        source=_strict_str(payload["source"], f"{where}.source"),
        replay_metadata=_decode_json_dict(payload["replay_metadata"], f"{where}.replay_metadata"),
        is_active=_strict_bool(payload["is_active"], f"{where}.is_active"),
    )


def _encode_contingency(c: ContingencyPlan) -> dict:
    return {
        "capex_pct": c.capex_pct,
        "opex_pct": c.opex_pct,
        "eligible_capex_basis_keur": c.eligible_capex_basis_keur,
        "lineage": dict(c.lineage),
        "capex_active": bool(c.capex_active),
        "opex_active": bool(c.opex_active),
    }


def _decode_contingency(payload: Any, where: str) -> ContingencyPlan:
    _expect_object(payload, where, frozenset(
        _encode_contingency(ContingencyPlan()).keys()))
    return ContingencyPlan(
        capex_pct=_optional_number(payload["capex_pct"], f"{where}.capex_pct"),
        opex_pct=_optional_number(payload["opex_pct"], f"{where}.opex_pct"),
        eligible_capex_basis_keur=_optional_number(
            payload["eligible_capex_basis_keur"], f"{where}.eligible_capex_basis_keur"),
        lineage=_decode_json_dict(payload["lineage"], f"{where}.lineage"),
        capex_active=_strict_bool(payload["capex_active"], f"{where}.capex_active"),
        opex_active=_strict_bool(payload["opex_active"], f"{where}.opex_active"),
    )


def _decode_json_dict(value: Any, where: str) -> dict:
    """Restore a free-form metadata dict (replay lineage, scalar metadata).
    The dict is carried verbatim; it must be a JSON object."""
    if not isinstance(value, dict):
        raise _fail(where, "an object", value)
    return dict(value)


def _expect_step_pair(value: Any, where: str) -> Any:
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        raise _fail(where, "a [year, amount] pair", value)
    return value


def _decode_step_pairs(steps: list, where: str) -> tuple:
    decoded = []
    for i, pair in enumerate(steps):
        _expect_step_pair(pair, f"{where}[{i}]")
        decoded.append((
            _strict_int(pair[0], f"{where}[{i}].year"),
            _strict_number(pair[1], f"{where}[{i}].amount"),
        ))
    return tuple(decoded)


def materialization_plan_to_payload(plan: MaterializationPlan) -> dict:
    """Encode a Workflow 03 MaterializationPlan into its versioned payload."""
    if not isinstance(plan, MaterializationPlan):
        raise ModelV2PersistenceError(
            f"MODEL_V2_PERSISTENCE_TYPE_INVALID: cost persistence requires "
            f"an app.services.cost_template.materialize.MaterializationPlan, "
            f"got {type(plan).__name__}"
        )
    return {
        "_schema": MODEL_V2_MATERIALIZATION_PLAN_SCHEMA,
        "schema_version": MODEL_V2_MATERIALIZATION_PLAN_SCHEMA_VERSION,
        "template_id": plan.template_id,
        "template_version": plan.template_version,
        "capex_fields": [_encode_capex_field(fp) for fp in plan.capex_fields],
        "capex_sub_lines": [_encode_capex_sub_line(s) for s in plan.capex_sub_lines],
        "opex_items": [_encode_opex_item(op) for op in plan.opex_items],
        "opex_sub_lines": [_encode_opex_sub_line(s) for s in plan.opex_sub_lines],
        "contingency": (
            None if plan.contingency is None
            else _encode_contingency(plan.contingency)
        ),
    }


def materialization_plan_from_payload(payload: Any) -> MaterializationPlan:
    where = "materialization_plan"
    _expect_object(payload, where, frozenset({
        "_schema", "schema_version", "template_id", "template_version",
        "capex_fields", "capex_sub_lines", "opex_items", "opex_sub_lines",
        "contingency",
    }))
    _schema_header(payload, MODEL_V2_MATERIALIZATION_PLAN_SCHEMA,
                   MODEL_V2_MATERIALIZATION_PLAN_SCHEMA_VERSION, where)

    def _list(key: str) -> list:
        raw = payload[key]
        if not isinstance(raw, list):
            raise _fail(f"{where}.{key}", "an array", raw)
        return raw

    contingency = payload["contingency"]
    if contingency is not None:
        contingency = _decode_contingency(contingency, f"{where}.contingency")
    return MaterializationPlan(
        template_id=_strict_str(payload["template_id"], f"{where}.template_id"),
        template_version=_strict_int(payload["template_version"], f"{where}.template_version"),
        capex_fields=tuple(
            _decode_capex_field(fp, f"{where}.capex_fields[{i}]")
            for i, fp in enumerate(_list("capex_fields"))),
        capex_sub_lines=tuple(
            _decode_capex_sub_line(s, f"{where}.capex_sub_lines[{i}]")
            for i, s in enumerate(_list("capex_sub_lines"))),
        opex_items=tuple(
            _decode_opex_item(op, f"{where}.opex_items[{i}]")
            for i, op in enumerate(_list("opex_items"))),
        opex_sub_lines=tuple(
            _decode_opex_sub_line(s, f"{where}.opex_sub_lines[{i}]")
            for i, s in enumerate(_list("opex_sub_lines"))),
        contingency=contingency,
    )


# ---------------------------------------------------------------------------
# ModelV2WorkingState codec
# ---------------------------------------------------------------------------


def working_state_to_payload(state: ModelV2WorkingState) -> dict:
    """Encode the V2 Working Copy selection state into its versioned
    payload. The state (and any selections) are validated before writing —
    an invalid economic state is never persistable."""
    state.validate()
    revenue = None
    if state.revenue_plan_selection is not None:
        revenue = {
            "source_ref": state.revenue_plan_selection.source_ref,
            "scenario_id": state.revenue_plan_selection.scenario_id,
            "plan": plan_to_payload(state.revenue_plan_selection.plan),
        }
    cost = None
    if state.cost_template_selection is not None:
        cost = {
            "template_id": state.cost_template_selection.template_id,
            "version": state.cost_template_selection.version,
            "source_ref": state.cost_template_selection.source_ref,
            "materialization_plan": materialization_plan_to_payload(
                state.cost_template_selection.materialization_plan),
        }
    return {
        "_schema": MODEL_V2_WORKING_STATE_SCHEMA,
        "schema_version": MODEL_V2_WORKING_STATE_SCHEMA_VERSION,
        "working_copy_ref": state.working_copy_ref,
        "revenue_plan_selection": revenue,
        "cost_template_selection": cost,
    }


def working_state_from_payload(payload: Any) -> ModelV2WorkingState:
    """Decode a versioned payload back into a validated
    ModelV2WorkingState (fail closed on anything unexpected)."""
    where = "working_state"
    _expect_object(payload, where, frozenset({
        "_schema", "schema_version", "working_copy_ref",
        "revenue_plan_selection", "cost_template_selection",
    }))
    _schema_header(payload, MODEL_V2_WORKING_STATE_SCHEMA,
                   MODEL_V2_WORKING_STATE_SCHEMA_VERSION, where)

    revenue_raw = payload["revenue_plan_selection"]
    revenue = None
    if revenue_raw is not None:
        _expect_object(revenue_raw, f"{where}.revenue_plan_selection",
                       frozenset({"source_ref", "scenario_id", "plan"}))
        revenue = RevenuePlanSelection(
            plan=plan_from_payload(revenue_raw["plan"]),
            source_ref=_strict_str(
                revenue_raw["source_ref"], f"{where}.revenue_plan_selection.source_ref"),
            scenario_id=_optional_str(
                revenue_raw["scenario_id"], f"{where}.revenue_plan_selection.scenario_id"),
        )

    cost_raw = payload["cost_template_selection"]
    cost = None
    if cost_raw is not None:
        _expect_object(cost_raw, f"{where}.cost_template_selection",
                       frozenset({"template_id", "version", "source_ref",
                                  "materialization_plan"}))
        cost = CostTemplateSelection(
            template_id=_strict_str(
                cost_raw["template_id"], f"{where}.cost_template_selection.template_id"),
            version=_strict_int(
                cost_raw["version"], f"{where}.cost_template_selection.version"),
            materialization_plan=materialization_plan_from_payload(
                cost_raw["materialization_plan"]),
            source_ref=_strict_str(
                cost_raw["source_ref"], f"{where}.cost_template_selection.source_ref"),
        )

    state = ModelV2WorkingState(
        working_copy_ref=_strict_str(payload["working_copy_ref"], f"{where}.working_copy_ref"),
        revenue_plan_selection=revenue,
        cost_template_selection=cost,
    )
    state.validate()
    return state


def working_state_to_json(state: ModelV2WorkingState) -> str:
    """Canonical, deterministic serialization (sorted keys, ASCII, compact,
    NaN/Inf refused). The same state always yields the same bytes."""
    return _canonical_dumps(working_state_to_payload(state))


def working_state_from_json(text: Optional[str]) -> Optional[ModelV2WorkingState]:
    """Decode a persisted payload. Empty/None means NO Model V2 state —
    the exact legacy absence (never defaulted, never invented). Anything
    else that is not a valid versioned payload fails closed."""
    if text is None:
        return None
    if not str(text).strip():
        return None
    try:
        payload = json.loads(text, parse_constant=_reject_constant)
    except ModelV2PersistenceError:
        raise
    except ValueError as exc:
        raise ModelV2PersistenceError(
            f"MODEL_V2_PERSISTENCE_MALFORMED: working state payload is not "
            f"valid JSON ({exc})"
        ) from None
    return working_state_from_payload(payload)


# ---------------------------------------------------------------------------
# Canonical run binding
# ---------------------------------------------------------------------------


def model_v2_economic_identity(state: ModelV2WorkingState) -> str:
    """The scenario-independent economic identity of a V2 Working Copy
    state. This is the EXISTING Workflow 05 authority
    (``ModelV2WorkingState.selection_digest``) — reused, never reinvented."""
    return state.selection_digest()


def build_run_binding_payload(
    *,
    state: ModelV2WorkingState,
    composition_hash: str,
    snapshot_id: str,
    scenario_id: Optional[str] = None,
) -> dict:
    """Build the run-bound identity payload for a SUCCESSFUL canonical run
    that was produced from ``state``.

    ``composition_hash`` is the Workflow 05 composition identity (which
    INCLUDES the carried scenario context); ``economic_identity`` is the
    scenario-independent selection digest used for staleness comparison.
    Neither is the canonical run identity — the run is identified by the
    existing run/snapshot identity; this payload binds it to the input
    state. ``snapshot_id`` (the run's ``runtime_snapshot_id``) correlates
    the binding with the exact run it belongs to: a later run that does not
    pass the binding forward (e.g. a legacy run) replaces the Last Run
    evidence without the binding, so a stale binding can never be mistaken
    for provenance of the current Last Run. Legacy-passthrough runs carry
    no V2 binding at all (there is no V2 economic state to prove).
    """
    state.validate()
    if not isinstance(composition_hash, str) or not _HEX64.match(composition_hash):
        raise ModelV2PersistenceError(
            f"MODEL_V2_PERSISTENCE_MALFORMED: composition_hash must be a "
            f"SHA-256 hex digest, got {composition_hash!r}"
        )
    if not isinstance(snapshot_id, str) or not snapshot_id.strip():
        raise ModelV2PersistenceError(
            f"MODEL_V2_PERSISTENCE_MALFORMED: snapshot_id is required to "
            f"correlate the binding with its run, got {snapshot_id!r}"
        )
    return {
        "_schema": MODEL_V2_RUN_BINDING_SCHEMA,
        "schema_version": MODEL_V2_RUN_BINDING_SCHEMA_VERSION,
        "working_copy_ref": state.working_copy_ref,
        "composition_hash": composition_hash,
        "economic_identity": model_v2_economic_identity(state),
        "scenario_id": scenario_id,
        "snapshot_id": snapshot_id,
    }


def validate_run_binding_payload(payload: Any) -> dict:
    """Validate a stored run binding payload (fail closed)."""
    where = "model_v2 run binding"
    _expect_object(payload, where, frozenset({
        "_schema", "schema_version", "working_copy_ref", "composition_hash",
        "economic_identity", "scenario_id", "snapshot_id",
    }))
    _schema_header(payload, MODEL_V2_RUN_BINDING_SCHEMA,
                   MODEL_V2_RUN_BINDING_SCHEMA_VERSION, where)
    for key in ("composition_hash", "economic_identity"):
        value = payload[key]
        if not isinstance(value, str) or not _HEX64.match(value):
            raise ModelV2PersistenceError(
                f"MODEL_V2_PERSISTENCE_MALFORMED: {where}.{key} must be a "
                f"SHA-256 hex digest, got {value!r}"
            )
    if not _strict_str(payload["working_copy_ref"], f"{where}.working_copy_ref").strip():
        raise ModelV2PersistenceError(
            f"MODEL_V2_PERSISTENCE_MALFORMED: {where}.working_copy_ref is "
            "required")
    if not _strict_str(payload["snapshot_id"], f"{where}.snapshot_id").strip():
        raise ModelV2PersistenceError(
            f"MODEL_V2_PERSISTENCE_MALFORMED: {where}.snapshot_id is required"
        )
    _optional_str(payload["scenario_id"], f"{where}.scenario_id")
    return dict(payload)


def read_workspace_run_binding(last_runtime_identity: Optional[Mapping[str, Any]]) -> Optional[dict]:
    """Extract + validate the Model V2 run binding from a decoded
    ``last_runtime_identity`` payload. Returns None when the Last Run
    carries no V2 binding (legacy / pre-V2 run)."""
    if not last_runtime_identity:
        return None
    binding = last_runtime_identity.get("model_v2")
    if binding is None:
        return None
    return validate_run_binding_payload(binding)


# ---------------------------------------------------------------------------
# Staleness
# ---------------------------------------------------------------------------


class ModelV2RunStaleness(str, Enum):
    NOT_APPLICABLE = "not_applicable"   # no V2-bound Last Run exists
    CURRENT = "current"                 # Working Copy economics == bound run
    STALE = "stale"                     # Working Copy economics changed


@dataclass(frozen=True)
class ModelV2Staleness:
    """Deterministic result of comparing the current Working Copy V2
    economic state against the V2 identity bound to the Last Run."""

    state: ModelV2RunStaleness
    reason: str
    bound_composition_hash: Optional[str] = None
    bound_economic_identity: Optional[str] = None
    bound_scenario_id: Optional[str] = None
    current_economic_identity: Optional[str] = None

    @property
    def is_stale(self) -> bool:
        return self.state is ModelV2RunStaleness.STALE


def resolve_model_v2_staleness(
    *,
    current_state: Optional[ModelV2WorkingState],
    run_binding: Optional[Mapping[str, Any]],
) -> ModelV2Staleness:
    """Compare the CURRENT Working Copy V2 economic state with the state
    bound to the Last Run.

    - No binding → NOT_APPLICABLE: the existing (legacy) freshness
      authorities remain the only truth; V2 adds nothing.
    - Binding present + no current V2 state → STALE (the selections that
      produced the run were removed).
    - Otherwise → CURRENT iff the scenario-independent economic identity
      (``selection_digest`` — the existing canonical authority) matches.
      Presentation-only metadata excluded by that authority cannot create
      a false STALE.
    """
    if not run_binding:
        return ModelV2Staleness(
            state=ModelV2RunStaleness.NOT_APPLICABLE,
            reason="the committed Last Run carries no Model V2 binding",
        )
    binding = validate_run_binding_payload(dict(run_binding))
    if current_state is None:
        return ModelV2Staleness(
            state=ModelV2RunStaleness.STALE,
            reason="Model V2 selections were removed from the Working Copy "
                   "after the bound run",
            bound_composition_hash=binding["composition_hash"],
            bound_economic_identity=binding["economic_identity"],
            bound_scenario_id=binding["scenario_id"],
        )
    current_state.validate()
    current_identity = model_v2_economic_identity(current_state)
    if current_identity == binding["economic_identity"]:
        return ModelV2Staleness(
            state=ModelV2RunStaleness.CURRENT,
            reason="Working Copy V2 economics match the bound run",
            bound_composition_hash=binding["composition_hash"],
            bound_economic_identity=binding["economic_identity"],
            bound_scenario_id=binding["scenario_id"],
            current_economic_identity=current_identity,
        )
    return ModelV2Staleness(
        state=ModelV2RunStaleness.STALE,
        reason="Working Copy V2 economics changed after the bound run",
        bound_composition_hash=binding["composition_hash"],
        bound_economic_identity=binding["economic_identity"],
        bound_scenario_id=binding["scenario_id"],
        current_economic_identity=current_identity,
    )


def resolve_workspace_model_v2_staleness(
    *,
    workspace_record: Any,
    current_state: Optional[ModelV2WorkingState] = None,
) -> ModelV2Staleness:
    """Workspace-level staleness authority.

    First verifies that the binding still describes the CURRENT Last Run
    (``binding["snapshot_id"] == workspace_record.last_runtime_snapshot_id``).
    A legacy / non-V2 run that replaced the Last Run evidence after a
    V2-bound run leaves the old binding in place but WITHOUT its run: the
    binding then belongs to an older run and must never be reported as the
    provenance of the current Last Run — the result is NOT_APPLICABLE (the
    legacy freshness authorities govern that run).

    Pass ``current_state`` explicitly (or let it be decoded from the
    record's persisted payload via
    ``workspace_repository.get_workspace_model_v2_state``).
    """
    binding = read_workspace_run_binding(
        getattr(workspace_record, "last_runtime_identity", None))
    if binding is None:
        return ModelV2Staleness(
            state=ModelV2RunStaleness.NOT_APPLICABLE,
            reason="the committed Last Run carries no Model V2 binding",
        )
    if binding["snapshot_id"] != getattr(
            workspace_record, "last_runtime_snapshot_id", None):
        return ModelV2Staleness(
            state=ModelV2RunStaleness.NOT_APPLICABLE,
            reason="the Model V2 binding belongs to an older run; the "
                   "current Last Run was not committed from V2 state",
            bound_composition_hash=binding["composition_hash"],
            bound_economic_identity=binding["economic_identity"],
            bound_scenario_id=binding["scenario_id"],
        )
    return resolve_model_v2_staleness(
        current_state=current_state, run_binding=binding)
