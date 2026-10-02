"""RWA Basis / Tokenized Market Monitor V1 derived read contract.

Composes existing exact R-LIVE identity, B1.0 basis, read-time freshness and
B1.3 history. It creates no identity/market authority and performs no network I/O.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from enum import Enum
from typing import Any, Mapping

from app.radar_rwa.bnb_history import read_r_live_basis_history_summary_readonly
from app.radar_rwa.r_live_service import R_LIVE_AUTHORITY_POLICY
from app.radar_rwa.r_live_snapshot_view import build_snapshot_view
from finco_radar.assets.contracts import normalize_asset_uid
from finco_radar.authority.r_live_policy import APPROVED_RLIVE_ASSETS

SCHEMA_VERSION = "finco-rwa-basis-v1"
CURRENCY = "USD"
UNIT = "USD_PER_TOKEN"
HISTORY_24H_TARGET_SECONDS = 86400
HISTORY_24H_MAX_SKEW_SECONDS = 3600


class BasisStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    STALE = "STALE"
    UNAVAILABLE = "UNAVAILABLE"
    UNBOUND = "UNBOUND"


@dataclass(frozen=True)
class BasisComputation:
    status: BasisStatus
    basis_fraction: Decimal | None = None
    basis_bps: Decimal | None = None
    direction: str | None = None
    reason: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "status": self.status.value,
            "basis_fraction": str(self.basis_fraction) if self.basis_fraction is not None else None,
            "basis_bps": str(self.basis_bps) if self.basis_bps is not None else None,
            "premium_discount": self.direction,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class PriceObservation:
    value: Decimal | None
    observed_at: datetime | None
    source: str | None
    freshness_state: str
    currency: str = CURRENCY
    unit: str = UNIT

    def as_dict(self) -> dict[str, Any]:
        return {
            "value": str(self.value) if self.value is not None else None,
            "currency": self.currency,
            "unit": self.unit,
            "observed_at": self.observed_at.isoformat() if self.observed_at else None,
            "source": self.source,
            "freshness_state": self.freshness_state,
        }


@dataclass(frozen=True)
class MarketMetric:
    value: Decimal
    unit: str
    source: str

    def __post_init__(self) -> None:
        if not self.value.is_finite() or self.value < 0 or not self.unit or not self.source:
            raise ValueError("invalid market metric")

    def as_dict(self) -> dict[str, str]:
        return {"value": str(self.value), "unit": self.unit, "source": self.source}

    def to_dict(self) -> dict[str, str]:
        return self.as_dict()


def _aware(value: datetime | None) -> datetime:
    value = value or datetime.now(timezone.utc)
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("evaluation time must be timezone-aware")
    return value.astimezone(timezone.utc)


def _time(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if result.tzinfo is None or result.utcoffset() is None:
        return None
    return result.astimezone(timezone.utc)


def _decimal(value: Any, *, allow_zero: bool = True, signed: bool = False) -> Decimal | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None
    if not result.is_finite() or (not signed and result < 0) or (not allow_zero and result == 0):
        return None
    return result


def _label(bps: Decimal) -> str:
    return "PREMIUM" if bps > 0 else "DISCOUNT" if bps < 0 else "PAR"


def compute_basis(*, reference_value: Decimal | None, tokenized_value: Decimal | None,
                  reference_currency: str = CURRENCY, tokenized_currency: str = CURRENCY,
                  reference_unit: str = UNIT, tokenized_unit: str = UNIT,
                  identity_bound: bool = True, reference_freshness: str = "AVAILABLE",
                  tokenized_freshness: str = "AVAILABLE") -> BasisComputation:
    """Decimal-only descriptive basis. Missing is never coerced to zero."""
    if not identity_bound:
        return BasisComputation(BasisStatus.UNBOUND, reason="IDENTITY_UNBOUND")
    states = {reference_freshness, tokenized_freshness}
    if "STALE" in states:
        return BasisComputation(BasisStatus.STALE, reason="SOURCE_STALE")
    if states != {"AVAILABLE"}:
        return BasisComputation(BasisStatus.UNAVAILABLE, reason="SOURCE_UNAVAILABLE")
    if reference_value is None:
        return BasisComputation(BasisStatus.UNAVAILABLE, reason="REFERENCE_VALUE_UNAVAILABLE")
    if tokenized_value is None:
        return BasisComputation(BasisStatus.UNAVAILABLE, reason="TOKENIZED_VALUE_UNAVAILABLE")
    if not reference_value.is_finite() or reference_value <= 0:
        return BasisComputation(BasisStatus.UNAVAILABLE, reason="REFERENCE_VALUE_NONPOSITIVE")
    if not tokenized_value.is_finite() or tokenized_value < 0:
        return BasisComputation(BasisStatus.UNAVAILABLE, reason="TOKENIZED_VALUE_INVALID")
    if reference_currency.upper() != tokenized_currency.upper():
        return BasisComputation(BasisStatus.UNAVAILABLE, reason="CURRENCY_MISMATCH")
    if reference_unit.upper() != tokenized_unit.upper():
        return BasisComputation(BasisStatus.UNAVAILABLE, reason="UNIT_MISMATCH")
    fraction = (tokenized_value / reference_value) - Decimal("1")
    bps = fraction * Decimal("10000")
    return BasisComputation(BasisStatus.AVAILABLE, fraction, bps, _label(bps))


def _policies_by_uid() -> dict[str, Any]:
    out: dict[str, Any] = {}
    for policy in APPROVED_RLIVE_ASSETS.values():
        uid = normalize_asset_uid(policy.economic_asset_uid)
        if uid in out:
            raise RuntimeError("duplicate R-LIVE economic_asset_uid")
        out[uid] = policy
    return out


def resolve_policy_by_uid(economic_asset_uid: str):
    """Exact canonical UID only; ticker/name/display metadata is never accepted."""
    try:
        uid = normalize_asset_uid(economic_asset_uid)
    except (TypeError, ValueError):
        return None
    return _policies_by_uid().get(uid)


def _metric(value: Any) -> MarketMetric | None:
    if not isinstance(value, Mapping):
        return None
    number = _decimal(value.get("value"))
    unit, source = value.get("unit"), value.get("source")
    if number is None or not isinstance(unit, str) or not isinstance(source, str):
        return None
    try:
        return MarketMetric(number, unit, source)
    except ValueError:
        return None


def _empty_history(reason: str) -> dict[str, Any]:
    return {
        "prior_observation": None,
        "range_24h": {"state": "UNAVAILABLE", "low_bps": None, "high_bps": None, "observation_count": 0},
        "change_24h": {"state": "UNAVAILABLE", "change_bps": None, "reason": reason},
        "interpolation": False,
    }


def _unbound(policy, now: datetime, reason: str) -> dict[str, Any]:
    blank = PriceObservation(None, None, None, "UNAVAILABLE").as_dict()
    return {
        "economic_asset_uid": policy.economic_asset_uid,
        "canonical_asset_id": policy.asset_key.canonical_id,
        "display_symbol": policy.symbol,
        "reference_observation": blank,
        "tokenized_observation": {**blank, "chain_id": policy.asset_key.chain_id,
                                  "contract_address": policy.asset_key.contract_address,
                                  "market_state": "UNAVAILABLE", "liquidity": None, "volume_24h": None},
        "basis": BasisComputation(BasisStatus.UNBOUND, reason=reason).as_dict(),
        "evaluation_status": "UNBOUND", "evaluation_time": now.isoformat(),
        "observation_age_difference_seconds": None, "timing_relationship": "UNAVAILABLE",
        "comparison_window_seconds": R_LIVE_AUTHORITY_POLICY.max_evidence_skew_seconds,
        "provenance": {"identity_authority": "R_LIVE_REVIEWED_EXACT_BINDING",
                       "authority_version": policy.authority_version, "reason": reason},
        "history": _empty_history("IDENTITY_UNBOUND"),
    }


def build_basis_record(row: Mapping[str, Any], policy, *, evaluation_time: datetime,
                       history: Mapping[str, Any] | None = None) -> dict[str, Any]:
    now = _aware(evaluation_time)
    data = row.get("data") if isinstance(row.get("data"), Mapping) else {}
    if row.get("canonical_id") != policy.asset_key.canonical_id:
        return _unbound(policy, now, "EXACT_IDENTITY_MISMATCH")
    if data:
        key = data.get("exact_asset_key") if isinstance(data.get("exact_asset_key"), Mapping) else {}
        if (key.get("canonical_id") != policy.asset_key.canonical_id
                or key.get("chain_id") != policy.asset_key.chain_id
                or str(key.get("contract_address") or "").lower() != policy.asset_key.contract_address
                or data.get("economic_asset_uid") != policy.economic_asset_uid):
            return _unbound(policy, now, "EXACT_IDENTITY_MISMATCH")

    row_state = str(row.get("state") or "UNAVAILABLE").upper()
    ref = data.get("robinhood_basis") if isinstance(data.get("robinhood_basis"), Mapping) else {}
    tok = data.get("token_reference") if isinstance(data.get("token_reference"), Mapping) else {}
    premium = data.get("b1_0_premium") if isinstance(data.get("b1_0_premium"), Mapping) else {}
    metrics = data.get("market_metrics") if isinstance(data.get("market_metrics"), Mapping) else {}
    ref_state, tok_state = str(ref.get("state") or "UNAVAILABLE").upper(), str(tok.get("state") or "UNAVAILABLE").upper()
    if row_state == "STALE":
        ref_state = "STALE" if ref_state == "AVAILABLE" else ref_state
        tok_state = "STALE" if tok_state == "AVAILABLE" else tok_state
    elif row_state != "AVAILABLE":
        ref_state = "UNAVAILABLE" if ref_state == "AVAILABLE" else ref_state
        tok_state = "UNAVAILABLE" if tok_state == "AVAILABLE" else tok_state

    ref_obs = PriceObservation(_decimal(ref.get("price_usd_per_token"), allow_zero=False), _time(ref.get("observed_at")),
                               ref.get("source") if isinstance(ref.get("source"), str) else None, ref_state)
    tok_obs = PriceObservation(_decimal(tok.get("price_usd_per_token")), _time(tok.get("observed_at")),
                               tok.get("source") if isinstance(tok.get("source"), str) else None, tok_state)
    calc = compute_basis(reference_value=ref_obs.value, tokenized_value=tok_obs.value,
                         reference_freshness=ref_state, tokenized_freshness=tok_state)

    gap, timing = None, "TIMING_UNAVAILABLE"
    if ref_obs.observed_at and tok_obs.observed_at:
        gap = int(abs((tok_obs.observed_at - ref_obs.observed_at).total_seconds()))
        timing = ("WITHIN_CANONICAL_COMPARISON_WINDOW" if gap <= R_LIVE_AUTHORITY_POLICY.max_evidence_skew_seconds
                  else "OUTSIDE_CANONICAL_COMPARISON_WINDOW")
    if calc.status is BasisStatus.AVAILABLE and timing != "WITHIN_CANONICAL_COMPARISON_WINDOW":
        calc = BasisComputation(BasisStatus.UNAVAILABLE, reason="OBSERVATION_TIME_GAP_EXCEEDS_POLICY")
    authority_bps = _decimal(premium.get("value_bps"), signed=True)
    if calc.status is BasisStatus.AVAILABLE:
        if premium.get("state") != "AVAILABLE" or authority_bps is None:
            calc = BasisComputation(BasisStatus.UNAVAILABLE, reason="AUTHORITATIVE_BASIS_UNAVAILABLE")
        elif authority_bps != calc.basis_bps:
            calc = BasisComputation(BasisStatus.UNAVAILABLE, reason="AUTHORITATIVE_BASIS_MISMATCH")

    status = calc.status
    if row_state == "STALE" and status is not BasisStatus.UNBOUND:
        status = BasisStatus.STALE
    elif row_state not in ("AVAILABLE", "STALE") and status is not BasisStatus.UNBOUND:
        status = BasisStatus.UNAVAILABLE
    liquidity, volume = _metric(metrics.get("liquidity")), _metric(metrics.get("volume_24h"))
    hist = dict(history) if history is not None else _empty_history("HISTORY_UNAVAILABLE")
    hist["interpolation"] = False
    return {
        "economic_asset_uid": policy.economic_asset_uid, "canonical_asset_id": policy.asset_key.canonical_id,
        "display_symbol": policy.symbol, "reference_observation": ref_obs.as_dict(),
        "tokenized_observation": {**tok_obs.as_dict(), "chain_id": policy.asset_key.chain_id,
                                  "contract_address": policy.asset_key.contract_address, "market_state": tok_state,
                                  "liquidity": liquidity.as_dict() if liquidity else None,
                                  "volume_24h": volume.as_dict() if volume else None},
        "basis": calc.as_dict(), "evaluation_status": status.value, "evaluation_time": now.isoformat(),
        "observation_age_difference_seconds": gap, "timing_relationship": timing,
        "comparison_window_seconds": R_LIVE_AUTHORITY_POLICY.max_evidence_skew_seconds,
        "provenance": {"identity_authority": "R_LIVE_REVIEWED_EXACT_BINDING",
                       "authority_version": policy.authority_version,
                       "registry_source": "ROBINHOOD_STOCK_TOKEN_ASSETS_API",
                       "reference_source": ref_obs.source, "tokenized_source": tok_obs.source,
                       "chain_id": policy.asset_key.chain_id, "contract_address": policy.asset_key.contract_address,
                       "policy_provenance": [list(item) for item in policy.provenance]},
        "history": hist,
    }


def build_rwa_basis_monitor(*, evaluation_time: datetime | None = None,
                            snapshot_path: str | None = None, history_path: str | None = None) -> dict[str, Any]:
    now = _aware(evaluation_time)
    snapshot = build_snapshot_view(path=snapshot_path, now=now)
    rows = {row.get("canonical_id"): row for row in snapshot.get("rows", [])}
    records = []
    for policy in APPROVED_RLIVE_ASSETS.values():
        row = rows.get(policy.asset_key.canonical_id, {"canonical_id": policy.asset_key.canonical_id,
                                                       "state": "UNAVAILABLE", "data": {}})
        try:
            history = read_r_live_basis_history_summary_readonly(
                policy.economic_asset_uid, policy.asset_key, as_of=now,
                max_24h_baseline_skew_seconds=HISTORY_24H_MAX_SKEW_SECONDS, path=history_path)
        except Exception:
            history = _empty_history("HISTORY_UNAVAILABLE")
        records.append(build_basis_record(row, policy, evaluation_time=now, history=history))
    return {
        "schema_version": SCHEMA_VERSION, "state": snapshot.get("state", "UNAVAILABLE"),
        "evaluation_time": now.isoformat(),
        "comparison_policy": {"max_observation_age_difference_seconds": R_LIVE_AUTHORITY_POLICY.max_evidence_skew_seconds,
                              "history_24h_target_seconds": HISTORY_24H_TARGET_SECONDS,
                              "history_24h_max_skew_seconds": HISTORY_24H_MAX_SKEW_SECONDS,
                              "history_interpolation": False},
        "formula": {"basis_fraction": "(tokenized_value / reference_value) - 1",
                    "basis_bps": "basis_fraction * 10000"},
        "records": records,
    }


def get_rwa_basis_record(economic_asset_uid: str, **kwargs) -> tuple[BasisStatus, dict[str, Any]]:
    policy = resolve_policy_by_uid(economic_asset_uid)
    if policy is None:
        return BasisStatus.UNBOUND, {"schema_version": SCHEMA_VERSION, "economic_asset_uid": economic_asset_uid,
                                     "evaluation_status": "UNBOUND", "reason": "ECONOMIC_ASSET_UID_UNBOUND"}
    for record in build_rwa_basis_monitor(**kwargs)["records"]:
        if record["economic_asset_uid"] == policy.economic_asset_uid:
            return BasisStatus(record["evaluation_status"]), record
    return BasisStatus.UNAVAILABLE, {"schema_version": SCHEMA_VERSION, "economic_asset_uid": policy.economic_asset_uid,
                                     "evaluation_status": "UNAVAILABLE", "reason": "CANONICAL_RECORD_UNAVAILABLE"}
