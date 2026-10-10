"""Dated, same-period revenue contracts evaluated by the existing plan authority."""
from __future__ import annotations

import json
import math
from dataclasses import dataclass, replace
from datetime import date

from domain.revenue.plan import RevenuePlan, RevenueStream, RevenueStreamType
from domain.revenue.plan_engine import StreamPeriodStatus, evaluate_revenue_plan
from domain.revenue.revenue_config import CfDParams, MerchantParams, PPAParams

SUPPORTED_TYPES = frozenset({"ppa", "merchant", "cfd"})
UNSUPPORTED_TYPES = frozenset({"capacity_market", "ancillary", "rec"})


def _object(value, keys, label, optional=()):
    if not isinstance(value, dict) or set(value) - set(keys) - set(optional) or set(keys) - set(value):
        raise ValueError(f"REVENUE_V2_SCHEMA: {label} requires {sorted(keys)}; unknown keys are rejected")


def _number(value, label, maximum=None):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
        raise ValueError(f"REVENUE_V2_VALUE: {label} must be finite and non-negative")
    if maximum is not None and value > maximum:
        raise ValueError(f"REVENUE_V2_VALUE: {label} exceeds {maximum}")
    return float(value)


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"REVENUE_V2_SCHEMA: duplicate key {key!r}")
        result[key] = value
    return result


@dataclass(frozen=True)
class DatedRevenueStream:
    stream: RevenueStream
    start_date: date
    end_date: date  # exclusive, canonical boundary; no prorating inside a period
    source_ref: str

    def active(self, when):
        return self.start_date <= when < self.end_date


@dataclass(frozen=True)
class MultiStreamRevenue:
    technology: str
    streams: tuple[DatedRevenueStream, ...]
    canonical_json: str

    def plan_at(self, when):
        streams = tuple(replace(s.stream, enabled=s.active(when)) for s in self.streams)
        plan = RevenuePlan.create(streams)
        # CfD volume must be backed by the referenced physical merchant sale.
        for merchant in streams:
            if merchant.stream_type is not RevenueStreamType.MERCHANT:
                continue
            overlays = [s for s in streams if s.enabled and s.reference_stream_id == merchant.stream_id]
            if not overlays:
                continue
            if not merchant.enabled:
                raise ValueError("REVENUE_V2_CFD_COVERAGE: referenced merchant must be active")
            allocated = sum(s.volume_share for s in streams if s.enabled
                            and s.stream_type in (RevenueStreamType.PPA, RevenueStreamType.MERCHANT)
                            and s.volume_share is not None)
            share = 1.0 - allocated if merchant.volume_share is None else merchant.volume_share
            if sum(s.volume_share for s in overlays) > share + 1e-9:
                raise ValueError("REVENUE_V2_CFD_COVERAGE: settlement volume exceeds merchant volume")
        return plan

    def validate_axis(self, periods):
        operating = tuple(p for p in periods if p.is_operation)
        boundaries = {p.start_date for p in operating} | {p.end_date for p in operating}
        if not operating:
            raise ValueError("REVENUE_V2_AXIS: operating periods required")
        for dated in self.streams:
            if dated.start_date not in boundaries or dated.end_date not in boundaries:
                raise ValueError("REVENUE_V2_AXIS: contract dates must match canonical operating boundaries")
            for p in operating:
                if dated.start_date < p.end_date and dated.end_date > p.start_date:
                    if not (dated.start_date <= p.start_date and p.end_date <= dated.end_date):
                        raise ValueError("REVENUE_V2_AXIS: partial-period contracts are unsupported")

    def evaluate(self, period, generation_mwh):
        result = evaluate_revenue_plan(self.plan_at(period.start_date), period.year_index,
                                       generation_mwh, technology=self.technology)
        states = {s.stream.stream_id: s for s in self.streams}
        rows = tuple(replace(r, status=StreamPeriodStatus.NOT_STARTED
                     if period.start_date < states[r.stream_id].start_date else StreamPeriodStatus.EXPIRED)
                     if not states[r.stream_id].active(period.start_date) else r
                     for r in result.stream_results)
        if result.total_revenue_keur is None:
            raise ValueError("REVENUE_V2_UNAVAILABLE: a stream has no authoritative price")
        if not math.isfinite(result.total_revenue_keur):
            raise ValueError("REVENUE_V2_VALUE: period revenue must be finite")
        return replace(result, stream_results=rows)


def parse_config(raw: str | None) -> MultiStreamRevenue | None:
    if raw is None or raw == "":
        return None
    if not isinstance(raw, str) or len(raw) > 100_000:
        raise ValueError("REVENUE_V2_SCHEMA: expected bounded JSON text")
    try:
        payload = json.loads(raw, object_pairs_hook=_unique_object)
    except (ValueError, TypeError) as exc:
        raise ValueError(f"REVENUE_V2_SCHEMA: {exc}") from exc
    _object(payload, {"version", "technology", "indexation_basis", "streams"}, "configuration")
    if type(payload["version"]) is not int or payload["version"] != 1:
        raise ValueError("REVENUE_V2_VERSION: expected version 1")
    if payload["technology"] not in ("solar", "wind"):
        raise ValueError("REVENUE_V2_TECHNOLOGY: only Solar/Wind are supported")
    if payload["indexation_basis"] != "OPERATING_YEAR":
        raise ValueError("REVENUE_V2_INDEXATION: only canonical operating-year pricing is supported")
    if not isinstance(payload["streams"], list) or not 1 <= len(payload["streams"]) <= 24:
        raise ValueError("REVENUE_V2_STREAMS: expected 1-24 explicit contracts")
    dated_streams = []
    for row in payload["streams"]:
        _object(row, {"id", "type", "start_date", "end_date", "volume_share", "price_eur_mwh",
                      "indexation_rate", "settlement", "source_ref"}, "stream",
                {"capture_rate", "reference_stream_id"})
        if not isinstance(row["type"], str) or row["type"] not in SUPPORTED_TYPES:
            raise ValueError(f"REVENUE_V2_UNSUPPORTED_STREAM: {row['type']!r}")
        for key in ("id", "source_ref"):
            if not isinstance(row[key], str) or not row[key].strip() or len(row[key]) > 200:
                raise ValueError(f"REVENUE_V2_IDENTITY: explicit {key} required")
        try:
            start, end = date.fromisoformat(row["start_date"]), date.fromisoformat(row["end_date"])
        except (ValueError, TypeError) as exc:
            raise ValueError("REVENUE_V2_DATE: ISO contract dates required") from exc
        if end <= start:
            raise ValueError("REVENUE_V2_DATE: end_date must follow start_date")
        if row["settlement"] != "SAME_PERIOD":
            raise ValueError("REVENUE_V2_SETTLEMENT: lagged settlement needs a working-capital authority")
        price = _number(row["price_eur_mwh"], "price_eur_mwh")
        index = _number(row["indexation_rate"], "indexation_rate", 1.0)
        share = None if row["volume_share"] is None else _number(row["volume_share"], "volume_share", 1.0)
        kind = RevenueStreamType(row["type"])
        options = {}
        if kind is RevenueStreamType.PPA:
            options["ppa"] = PPAParams(ppa_enabled=True, ppa_base_price_eur_mwh=price,
                                       ppa_price_index=index, balancing_cost_pct=0.0)
        elif kind is RevenueStreamType.MERCHANT:
            capture = _number(row.get("capture_rate", 1.0), "capture_rate", 1.0)
            options["merchant"] = MerchantParams(merchant_enabled=True, base_price_eur_mwh=price,
                price_escalation_annual=index, capture_rate_solar=capture, capture_rate_wind=capture)
        else:
            if index != 0:
                raise ValueError("REVENUE_V2_CFD_INDEXATION: indexed strikes are unsupported")
            if not isinstance(row.get("reference_stream_id"), str) or not row["reference_stream_id"]:
                raise ValueError("REVENUE_V2_CFD_REFERENCE: explicit merchant reference required")
            options["cfd"] = CfDParams(cfd_enabled=True, strike_price_eur_mwh=price, two_way_cfd=True)
            options["reference_stream_id"] = row["reference_stream_id"]
        if kind is not RevenueStreamType.MERCHANT and "capture_rate" in row:
            raise ValueError("REVENUE_V2_SCHEMA: capture_rate belongs only to merchant")
        if kind is not RevenueStreamType.CFD and "reference_stream_id" in row:
            raise ValueError("REVENUE_V2_SCHEMA: reference_stream_id belongs only to CfD")
        stream = RevenueStream(stream_id=row["id"], stream_type=kind, volume_share=share, **options)
        dated_streams.append(DatedRevenueStream(stream, start, end, row["source_ref"]))
    config = MultiStreamRevenue(payload["technology"], tuple(dated_streams),
                                json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False))
    for when in sorted({s.start_date for s in dated_streams} | {s.end_date for s in dated_streams}):
        config.plan_at(when)
    return config
