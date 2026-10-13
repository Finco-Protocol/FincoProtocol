"""Release-closed non-energy contracts composed with the existing energy book."""
from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass
from datetime import date
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from domain.revenue.multistream_runtime import MultiStreamRevenue

# Candidate content is not released authority. Only isolated acceptance fixtures
# enable this gate; no environment variable or customer payload can enable it.
ACTIVATION_ENABLED = False
PRODUCT_TYPES = frozenset({"capacity_market", "ancillary", "rec"})


def require_release():
    if not ACTIVATION_ENABLED:
        raise ValueError("REVENUE_V3_RELEASE_CLOSED: independent financial release approval required")


def _shape(value, keys, label):
    if not isinstance(value, dict) or set(value) != set(keys):
        raise ValueError(f"REVENUE_V3_SCHEMA: {label} requires exactly {sorted(keys)}")


def _text(value, label):
    if not isinstance(value, str) or not value.strip() or value != value.strip() or len(value) > 200:
        raise ValueError(f"REVENUE_V3_IDENTITY: explicit bounded {label} required")
    return value


def _num(value, label, maximum=None):
    try:
        valid = type(value) in (int, float) and math.isfinite(value) and value >= 0
    except OverflowError:
        valid = False
    if not valid:
        raise ValueError(f"REVENUE_V3_VALUE: {label} must be finite and non-negative")
    if maximum is not None and value > maximum:
        raise ValueError(f"REVENUE_V3_VALUE: {label} exceeds {maximum}")
    return float(value)


def _date(value):
    if not isinstance(value, str) or len(value) != 10:
        raise ValueError("REVENUE_V3_DATE: exact ISO date required")
    try:
        parsed = date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError("REVENUE_V3_DATE: exact ISO date required") from exc
    if parsed.isoformat() != value:
        raise ValueError("REVENUE_V3_DATE: exact ISO date required")
    return parsed


def _finite_sum(values):
    try:
        result = math.fsum(values)
    except OverflowError as exc:
        raise ValueError("REVENUE_V3_VALUE: nonfinite aggregate") from exc
    if not math.isfinite(result):
        raise ValueError("REVENUE_V3_VALUE: nonfinite aggregate")
    return result


@dataclass(frozen=True)
class ProductPeriod:
    start: date
    end: date
    settlement: date
    certified_mwh: float | None


@dataclass(frozen=True)
class ProductContract:
    identity: str
    kind: str
    entitlement_id: str
    source_ref: str
    eligibility_ref: str
    start: date
    end: date
    price: float
    price_unit: str
    indexation: float
    periods: tuple[ProductPeriod, ...]
    pool_id: str | None = None
    pool_source_ref: str | None = None
    pool_capacity_mw: float | None = None
    eligible_mw: float | None = None
    derating: float | None = None
    availability: float | None = None
    performance: float | None = None
    day_count: str | None = None
    energy_stream_id: str | None = None
    certification_ref: str | None = None


@dataclass(frozen=True)
class ProductEvidence:
    id: str
    type: str
    status: str
    quantity: float
    quantity_unit: str
    price: float
    price_unit: str
    revenue_keur: float
    entitlement_id: str
    source_ref: str
    eligibility_ref: str
    start_date: str
    end_date: str
    settlement_date: str | None
    period_fraction: float
    adjustment_factor: float
    certification_ref: str | None


@dataclass(frozen=True)
class AdvancedRevenueBook:
    energy: MultiStreamRevenue
    products: tuple[ProductContract, ...]
    environmental_rights: tuple[tuple[str, str, str], ...]
    canonical_json: str

    @property
    def technology(self):
        return self.energy.technology

    @property
    def streams(self):
        return self.energy.streams

    @property
    def has_rec(self):
        return any(p.kind == "rec" for p in self.products)

    def plan_at(self, when):
        return self.energy.plan_at(when)

    def validate_axis(self, periods):
        require_release()
        periods = tuple(periods)
        self.energy.validate_axis(periods)
        operating = tuple(p for p in periods if p.is_operation)
        for contract in self.products:
            active = tuple(p for p in operating if contract.start <= p.start_date < contract.end)
            expected = tuple((p.start_date, p.end_date, p.end_date) for p in active)
            actual = tuple((p.start, p.end, p.settlement) for p in contract.periods)
            if not active or active[0].start_date != contract.start or active[-1].end_date != contract.end or actual != expected:
                raise ValueError("REVENUE_V3_AXIS: exact complete canonical periods and period-end settlement required")
            if contract.kind == "rec":
                source = next(s for s in self.streams if s.stream.stream_id == contract.energy_stream_id)
                if not source.start_date <= contract.start < contract.end <= source.end_date:
                    raise ValueError("REVENUE_V3_REC_VOLUME: certificate tenor exceeds energy entitlement")
        for period in operating:
            self._validate_pools(period.start_date)

    def _validate_pools(self, when):
        pools = {}
        for product in self.products:
            if product.kind != "rec" and product.start <= when < product.end:
                pools.setdefault(product.pool_id, []).append(product)
        for contracts in pools.values():
            if len({p.kind for p in contracts}) != 1:
                raise ValueError("REVENUE_V3_OVERLAP: capacity and ancillary cannot simultaneously reuse a pool")
            if _finite_sum(p.eligible_mw for p in contracts) > contracts[0].pool_capacity_mw:
                raise ValueError("REVENUE_V3_CAPACITY: commitments exceed explicit entitlement pool MW")

    def evaluate(self, period, generation_mwh):
        require_release()
        return self.energy.evaluate(period, generation_mwh)

    def evaluate_products(self, period, generation_mwh, energy_result):
        require_release()
        if not math.isfinite(generation_mwh) or generation_mwh < 0:
            raise ValueError("REVENUE_V3_GENERATION: finite non-negative energy required")
        active = [p for p in self.products if p.start <= period.start_date < p.end]
        self._validate_pools(period.start_date)
        physical = {r.stream_id: r.allocated_generation_mwh for r in energy_result.stream_results
                    if r.stream_type.value in ("ppa", "merchant") and r.status.value == "active"}
        rights = {sid: status for sid, status, _ in self.environmental_rights}
        certificates = {}
        evidence = []
        for product in self.products:
            status = "not_started" if period.start_date < product.start else "expired"
            quantity = fraction = adjustment = revenue = 0.0
            point = None
            try:
                price = product.price * (1 + product.indexation) ** (period.year_index - 1)
            except OverflowError as exc:
                raise ValueError("REVENUE_V3_VALUE: nonfinite indexed price") from exc
            if product in active:
                status = "active"
                point = next((p for p in product.periods if p.start == period.start_date), None)
                if point is None or point.end != period.end_date or point.settlement != period.end_date:
                    raise ValueError("REVENUE_V3_AXIS: missing exact settlement period")
                if product.kind == "rec":
                    if rights.get(product.energy_stream_id) != "RETAINED_UNBUNDLED":
                        raise ValueError("REVENUE_V3_REC_OWNERSHIP: bundled or transferred attributes cannot be resold")
                    quantity = point.certified_mwh
                    certificates[product.energy_stream_id] = certificates.get(product.energy_stream_id, 0.0) + quantity
                    if certificates[product.energy_stream_id] > physical.get(product.energy_stream_id, 0.0):
                        raise ValueError("REVENUE_V3_REC_VOLUME: certificates exceed eligible allocated energy")
                    fraction = adjustment = 1.0
                else:
                    quantity = product.eligible_mw
                    adjustment = product.derating * product.availability * product.performance
                    fraction = (period.end_date - period.start_date).days / 365.0 if product.kind == "capacity_market" else 1.0
                unit_factor = 1000.0 if product.price_unit == "EUR_KW_YEAR" else 1.0
                revenue = quantity * price * unit_factor * fraction * adjustment / 1000.0
            if not all(math.isfinite(v) for v in (price, revenue)):
                raise ValueError("REVENUE_V3_VALUE: nonfinite product output")
            evidence.append(ProductEvidence(product.identity, product.kind, status, quantity,
                "CERTIFICATE_MWH" if product.kind == "rec" else "MW", price, product.price_unit,
                revenue, product.entitlement_id, product.source_ref, product.eligibility_ref,
                product.start.isoformat(), product.end.isoformat(), point.settlement.isoformat() if point else None,
                fraction, adjustment, product.certification_ref))
        if _finite_sum(certificates.values()) > generation_mwh:
            raise ValueError("REVENUE_V3_REC_VOLUME: certificates exceed project generation")
        _finite_sum(row.revenue_keur for row in evidence)
        return tuple(asdict(row) for row in evidence)


def parse_advanced_config(payload):
    require_release()
    from domain.revenue.multistream_runtime import parse_config

    _shape(payload, {"version", "technology", "indexation_basis", "streams", "products", "environmental_rights"}, "book")
    if type(payload["version"]) is not int or payload["version"] != 3:
        raise ValueError("REVENUE_V3_SCHEMA: explicit version 3 required")
    energy_payload = {k: payload[k] for k in ("technology", "indexation_basis", "streams")}
    energy_payload["version"] = 2
    energy = parse_config(json.dumps(energy_payload, allow_nan=False))
    rows = payload["products"]
    if not isinstance(rows, list) or not 1 <= len(rows) <= 24:
        raise ValueError("REVENUE_V3_PRODUCTS: 1-24 explicit products required")
    common = {"id", "type", "entitlement_id", "source_ref", "eligibility_ref", "start_date", "end_date",
              "classification", "price_eur", "price_unit", "indexation_rate", "settlement", "periods"}
    capacity_keys = {"pool_id", "pool_source_ref", "pool_capacity_mw", "eligible_mw", "capacity_basis",
                     "derating_factor", "availability_factor", "performance_factor"}
    rec_keys = {"energy_stream_id", "certification_ref", "certificate_basis", "ownership"}
    products, ids, claims, pools = [], {s.stream.stream_id for s in energy.streams}, set(), {}
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get("type"), str) or row["type"] not in PRODUCT_TYPES:
            raise ValueError("REVENUE_V3_UNSUPPORTED: unknown product")
        kind = row["type"]
        extra = rec_keys if kind == "rec" else capacity_keys | ({"day_count"} if kind == "capacity_market" else {"service", "obligation"})
        _shape(row, common | extra, "product")
        identity = _text(row["id"], "id")
        claim = _text(row["entitlement_id"], "entitlement_id")
        if identity in ids or claim in claims:
            raise ValueError("REVENUE_V3_DUPLICATE: duplicate contract or entitlement")
        ids.add(identity)
        claims.add(claim)
        source, eligibility = _text(row["source_ref"], "source_ref"), _text(row["eligibility_ref"], "eligibility_ref")
        start, end = _date(row["start_date"]), _date(row["end_date"])
        if end <= start or row["classification"] != "CONTRACTED" or row["settlement"] != "SAME_PERIOD":
            raise ValueError("REVENUE_V3_POLICY: contracted, positive tenor, same-period settlement only")
        price = _num(row["price_eur"], "price_eur")
        index = _num(row["indexation_rate"], "indexation_rate", 1)
        options = {}
        if kind == "rec":
            if row["price_unit"] != "EUR_CERTIFICATE" or row["certificate_basis"] != "ONE_PER_MWH" or row["ownership"] != "PROJECT_RETAINED_UNBUNDLED":
                raise ValueError("REVENUE_V3_REC_OWNERSHIP: retained unbundled one-per-MWh certificates only")
            options.update(energy_stream_id=_text(row["energy_stream_id"], "energy_stream_id"),
                           certification_ref=_text(row["certification_ref"], "certification_ref"))
        else:
            if row["capacity_basis"] != "CONTRACTED_ELIGIBLE_MW":
                raise ValueError("REVENUE_V3_CAPACITY: explicit eligible MW, not inferred capacity")
            pool_id = _text(row["pool_id"], "pool_id")
            pool_source = _text(row["pool_source_ref"], "pool_source_ref")
            pool_size = _num(row["pool_capacity_mw"], "pool_capacity_mw")
            eligible = _num(row["eligible_mw"], "eligible_mw", pool_size)
            if pool_size <= 0 or eligible <= 0:
                raise ValueError("REVENUE_V3_CAPACITY: positive pool and eligible MW required")
            declared = (pool_size, pool_source)
            if pool_id in pools and pools[pool_id] != declared:
                raise ValueError("REVENUE_V3_CAPACITY: inconsistent pool authority")
            pools[pool_id] = declared
            options.update(pool_id=pool_id, pool_source_ref=pool_source, pool_capacity_mw=pool_size,
                eligible_mw=eligible, derating=_num(row["derating_factor"], "derating_factor", 1),
                availability=_num(row["availability_factor"], "availability_factor", 1),
                performance=_num(row["performance_factor"], "performance_factor", 1))
            if kind == "capacity_market":
                if row["price_unit"] not in ("EUR_KW_YEAR", "EUR_MW_YEAR") or row["day_count"] != "ACT_365_FIXED":
                    raise ValueError("REVENUE_V3_UNIT: annual capacity units and ACT/365 fixed required")
                options["day_count"] = row["day_count"]
            elif row["price_unit"] != "EUR_MW_PERIOD" or row["obligation"] != "AVAILABILITY_ONLY":
                raise ValueError("REVENUE_V3_ANCILLARY: availability-only EUR/MW/period; no dispatch")
            else:
                _text(row["service"], "service")
        points = row["periods"]
        if not isinstance(points, list) or not 1 <= len(points) <= 600:
            raise ValueError("REVENUE_V3_AXIS: explicit settlement periods required")
        parsed = []
        for point in points:
            _shape(point, {"period_start", "period_end", "settlement_date"} | ({"certified_mwh"} if kind == "rec" else set()), "period")
            a, b, cash = _date(point["period_start"]), _date(point["period_end"]), _date(point["settlement_date"])
            if not start <= a < b <= end or cash != b or (parsed and a <= parsed[-1].start):
                raise ValueError("REVENUE_V3_AXIS: ordered, bounded, period-end settlement required")
            parsed.append(ProductPeriod(a, b, cash, _num(point["certified_mwh"], "certified_mwh") if kind == "rec" else None))
        products.append(ProductContract(identity, kind, claim, source, eligibility, start, end, price,
                                       row["price_unit"], index, tuple(parsed), **options))
    rights = payload["environmental_rights"]
    if not isinstance(rights, list):
        raise ValueError("REVENUE_V3_REC_OWNERSHIP: explicit rights list required")
    physical_ids = {s.stream.stream_id for s in energy.streams if s.stream.stream_type.value in ("ppa", "merchant")}
    parsed_rights, right_ids = [], set()
    for row in rights:
        _shape(row, {"energy_stream_id", "status", "source_ref"}, "environmental right")
        sid = _text(row["energy_stream_id"], "energy_stream_id")
        if sid not in physical_ids or sid in right_ids or row["status"] not in ("RETAINED_UNBUNDLED", "TRANSFERRED_BUNDLED", "TRANSFERRED_OTHER"):
            raise ValueError("REVENUE_V3_REC_OWNERSHIP: duplicate, unsupported or nonphysical right")
        right_ids.add(sid)
        parsed_rights.append((sid, row["status"], _text(row["source_ref"], "source_ref")))
    if any(p.kind == "rec" for p in products):
        if right_ids != physical_ids:
            raise ValueError("REVENUE_V3_REC_OWNERSHIP: all energy sale rights must be explicit")
        statuses = dict((sid, status) for sid, status, _ in parsed_rights)
        if any(p.kind == "rec" and statuses.get(p.energy_stream_id) != "RETAINED_UNBUNDLED" for p in products):
            raise ValueError("REVENUE_V3_REC_OWNERSHIP: bundled/transferred attributes cannot be resold")
    return AdvancedRevenueBook(energy, tuple(products), tuple(parsed_rights),
        json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False))
