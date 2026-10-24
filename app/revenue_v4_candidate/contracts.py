"""Advanced Revenue V4 candidate — typed contracts and validators.

RELEASE-CLOSED CANDIDATE (WF-04A / Harvest V4 follow-up). The content of
this package is NOT released financial authority: every public entry point
is gated behind :data:`ACTIVATION_ENABLED` (a module-level literal
``False``). Only isolated acceptance fixtures may enable the gate in
memory; no environment variable, customer payload or product surface can
enable it, and no production code path reads this package.

Scope (Harvest V4 observed reference behaviour — NOT automatic approval):

1. Negative-price-hours policies (SETTLE_NORMALLY / NO_SETTLEMENT /
   CURTAIL) at PLANT or SINGLE_STREAM scope. The released authorities
   fail closed on negative prices (``REVENUE_V2_VALUE: ... must be finite
   and non-negative``) and that production rule is NOT changed here.
2. PPA contracted-volume modes beyond the released share-of-output:
   FIXED_ANNUAL_MWH and MONTHLY_MW_SHAPE (typed, with explicit units,
   declared hours and UTC-only shape timezone in V1).
3. Merchant price modes: MARKET_FLOOR / MARKET_CAP / FLOOR_AND_CAP and
   REVENUE_SHARING (the released runtime has no merchant floor/cap and no
   sharing concept).
4. Route-to-market fee with up-only annual escalation and an exact review
   month.

Everything not in this list is typed UNSUPPORTED and fails closed — never
a silent zero, never a fallback. Policy choices that the reference harvest
does not pin down are listed in
``docs/model_v2/REVENUE_V4_CANDIDATE_OWNER_DECISION_PACKET.md`` and marked
``OWNER DECISION REQUIRED``; this module implements only the deterministic
core each decision would operate on.

Naming: "Revenue V3" is already taken on main (the release-closed
Capacity/Ancillary/REC candidate, ``domain/revenue/advanced_products.py``,
``REVENUE_V3_*`` codes). This candidate therefore uses the next free
version family ``REVENUE_V4_*`` throughout.
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from typing import Optional, Tuple

#: Release-closure flag (house convention, cf. domain/revenue/advanced_products.py).
#: Candidate content is not released authority. Only isolated acceptance
#: fixtures enable this gate; no environment variable or customer payload
#: can enable it.
ACTIVATION_ENABLED = False


def require_release() -> None:
    if not ACTIVATION_ENABLED:
        raise ValueError(
            "REVENUE_V4_RELEASE_CLOSED: independent financial release "
            "approval required")


# ── Typed vocabularies (closed sets; unknown members fail closed) ───────────

NPH_SCOPES = ("PLANT", "SINGLE_STREAM")
NPH_ACTIONS = ("SETTLE_NORMALLY", "NO_SETTLEMENT", "CURTAIL")
VOLUME_MODES = ("SHARE_OF_OUTPUT", "FIXED_ANNUAL_MWH", "MONTHLY_MW_SHAPE")
PRICE_MODES = ("FIXED", "MARKET_FLOOR", "MARKET_CAP", "FLOOR_AND_CAP",
               "REVENUE_SHARING")
FEE_BASES = ("EUR_PER_MWH", "PERCENT_OF_REVENUE")
ESCALATION_TIMINGS = ("NO_ESCALATION", "ANNUAL_REVIEW")

_ERROR = "REVENUE_V4_VALUE"


def _num(value, label: str, *, minimum: Optional[float] = None,
         maximum: Optional[float] = None, exclusive_min: bool = False) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) \
            or not math.isfinite(float(value)):
        raise ValueError(f"{_ERROR}: {label} must be a finite number")
    v = float(value)
    if minimum is not None:
        if exclusive_min and v <= minimum:
            raise ValueError(f"{_ERROR}: {label} must be strictly positive")
        if not exclusive_min and v < minimum:
            raise ValueError(f"{_ERROR}: {label} must be at least {minimum}")
    if maximum is not None and v > maximum:
        raise ValueError(f"{_ERROR}: {label} must be at most {maximum}")
    return v


def _choice(value, label: str, allowed) -> str:
    if not isinstance(value, str) or value not in allowed:
        raise ValueError(
            f"REVENUE_V4_UNSUPPORTED: {label} {value!r} is not supported "
            f"(supported: {sorted(allowed)})")
    return value


# ── Contracts ────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class NegativePriceHoursPolicy:
    """Typed negative-price-hours policy for one candidate book.

    ``scope`` PLANT applies the action to the whole plant's settlement of
    negative-priced energy; SINGLE_STREAM applies it to exactly one
    declared stream (``stream_id`` required, validated at book level).
    The action decides what happens to energy delivered in hours whose
    market price is negative:

    - SETTLE_NORMALLY: the negative settlement is kept (revenue reduced);
    - NO_SETTLEMENT: the energy is still DELIVERED but the negative-priced
      settlement is waived (physical MWh unchanged, revenue floor at zero
      for the negative-priced portion);
    - CURTAIL: the energy is not delivered at all (physical MWh removed).

    HOUR-LEVEL identification is an evidence question: the canonical
    engine's period axis does not carry hourly prices. The pure helper in
    ``pure.py`` therefore accepts either explicit hourly price evidence or
    a period-declared negative-priced energy share — the accounting basis
    itself is OWNER DECISION REQUIRED (see the decision packet, D-01).
    """

    scope: str
    action: str
    stream_id: Optional[str] = None

    def validate(self) -> None:
        _choice(self.scope, "negative_price_hours.scope", NPH_SCOPES)
        _choice(self.action, "negative_price_hours.action", NPH_ACTIONS)
        if self.scope == "SINGLE_STREAM":
            if not isinstance(self.stream_id, str) or not self.stream_id.strip():
                raise ValueError(
                    "REVENUE_V4_SCHEMA: negative_price_hours SINGLE_STREAM "
                    "scope requires the target stream_id")
        elif self.stream_id is not None:
            raise ValueError(
                "REVENUE_V4_SCHEMA: negative_price_hours PLANT scope must "
                "not carry a stream_id")


@dataclass(frozen=True)
class ContractedVolume:
    """Typed contracted-volume mode for one candidate stream.

    The released Revenue V2 runtime supports SHARE_OF_OUTPUT only; the
    fixed-MWh and shaped modes are candidates with explicit units:

    - FIXED_ANNUAL_MWH: ``fixed_annual_mwh`` is a positive annual energy
      quantity. Its allocation across operating periods (pro-rata by
      declared period hours, post-COD periods only) and any
      shortfall/buyback treatment are OWNER DECISION REQUIRED (D-02/D-03);
      this module only converts deterministically.
    - MONTHLY_MW_SHAPE: ``monthly_mw`` is the contracted capacity per
      calendar month (MW), converted to MWh with explicitly DECLARED month
      hours (``pure.convert_monthly_mw``); timezone/DST and day-count
      conventions are OWNER DECISION REQUIRED (D-04) and V1 accepts only
      an explicitly UTC-declared shape.
    """

    mode: str
    share: Optional[float] = None
    fixed_annual_mwh: Optional[float] = None
    monthly_mw: Optional[Tuple[float, ...]] = None
    shape_timezone: Optional[str] = None

    def validate(self) -> None:
        _choice(self.mode, "contracted_volume.mode", VOLUME_MODES)
        if self.mode == "SHARE_OF_OUTPUT":
            if self.share is None:
                raise ValueError(
                    "REVENUE_V4_SCHEMA: SHARE_OF_OUTPUT requires share")
            _num(self.share, "contracted_volume.share", minimum=0.0, maximum=1.0)
            self._no_extras(require={"share"})
        elif self.mode == "FIXED_ANNUAL_MWH":
            if self.fixed_annual_mwh is None:
                raise ValueError(
                    "REVENUE_V4_SCHEMA: FIXED_ANNUAL_MWH requires "
                    "fixed_annual_mwh")
            _num(self.fixed_annual_mwh, "contracted_volume.fixed_annual_mwh",
                 minimum=0.0, exclusive_min=True)
            self._no_extras(require={"fixed_annual_mwh"})
        else:  # MONTHLY_MW_SHAPE
            if self.monthly_mw is None or len(self.monthly_mw) != 12:
                raise ValueError(
                    "REVENUE_V4_SCHEMA: MONTHLY_MW_SHAPE requires exactly "
                    "12 monthly_mw values (January..December)")
            for i, mw in enumerate(self.monthly_mw):
                _num(mw, f"contracted_volume.monthly_mw[{i}]", minimum=0.0)
            if self.shape_timezone != "UTC":
                raise ValueError(
                    "REVENUE_V4_UNSUPPORTED: MONTHLY_MW_SHAPE in V1 accepts "
                    "only shape_timezone='UTC'; local-time/DST shaping is "
                    "OWNER DECISION REQUIRED (decision packet D-04)")
            self._no_extras(require={"monthly_mw", "shape_timezone"})

    def _no_extras(self, require) -> None:
        values = {"share": self.share,
                  "fixed_annual_mwh": self.fixed_annual_mwh,
                  "monthly_mw": self.monthly_mw,
                  "shape_timezone": self.shape_timezone}
        strays = sorted(k for k, v in values.items()
                        if k not in require and v is not None)
        if strays:
            raise ValueError(
                f"REVENUE_V4_SCHEMA: contracted_volume mode {self.mode} must "
                f"not carry {strays}")


@dataclass(frozen=True)
class PriceModeRule:
    """Typed merchant price mode for one candidate stream.

    FIXED keeps an explicit nominal price. MARKET_FLOOR / MARKET_CAP /
    FLOOR_AND_CAP resolve the stream price from the market price with an
    explicit floor and/or cap (both non-negative in V1 — a negative floor
    would reopen the negative-price question and is OWNER DECISION
    REQUIRED, D-05). REVENUE_SHARING splits the market price with the
    offtaker: the project receives ``market_price * project_share``.

    The released PPA-contract floor/cap authority
    (``PPAParams.ppa_price_floor/cap``) is a DIFFERENT mechanism (contract
    price, post-indexation) whose runtime analytic seam is explicitly
    missing (``RUNTIME_PPA_FLOOR_CAP_SEAM_MISSING``); this candidate does
    not touch it.
    """

    mode: str
    fixed_price_eur_mwh: Optional[float] = None
    floor_eur_mwh: Optional[float] = None
    cap_eur_mwh: Optional[float] = None
    project_share: Optional[float] = None

    def validate(self) -> None:
        _choice(self.mode, "price_mode.mode", PRICE_MODES)
        if self.mode == "FIXED":
            if self.fixed_price_eur_mwh is None:
                raise ValueError(
                    "REVENUE_V4_SCHEMA: FIXED requires fixed_price_eur_mwh")
            # The released authorities fail closed on negative prices; the
            # candidate keeps that rule (zero is a legitimate FIXED price).
            _num(self.fixed_price_eur_mwh, "price_mode.fixed_price_eur_mwh",
                 minimum=0.0)
            self._no_extras(require={"fixed_price_eur_mwh"})
        elif self.mode in ("MARKET_FLOOR", "FLOOR_AND_CAP"):
            if self.floor_eur_mwh is None:
                raise ValueError(
                    f"REVENUE_V4_SCHEMA: {self.mode} requires floor_eur_mwh")
            _num(self.floor_eur_mwh, "price_mode.floor_eur_mwh", minimum=0.0)
        if self.mode in ("MARKET_CAP", "FLOOR_AND_CAP"):
            if self.cap_eur_mwh is None:
                raise ValueError(
                    f"REVENUE_V4_SCHEMA: {self.mode} requires cap_eur_mwh")
            _num(self.cap_eur_mwh, "price_mode.cap_eur_mwh", minimum=0.0)
        if self.mode == "FLOOR_AND_CAP" and self.floor_eur_mwh > self.cap_eur_mwh:
            raise ValueError(
                "REVENUE_V4_VALUE: price_mode floor exceeds cap")
        if self.mode == "REVENUE_SHARING":
            if self.project_share is None:
                raise ValueError(
                    "REVENUE_V4_SCHEMA: REVENUE_SHARING requires "
                    "project_share")
            _num(self.project_share, "price_mode.project_share",
                 minimum=0.0, maximum=1.0)
        allowed = {
            "FIXED": {"fixed_price_eur_mwh"},
            "MARKET_FLOOR": {"floor_eur_mwh"},
            "MARKET_CAP": {"cap_eur_mwh"},
            "FLOOR_AND_CAP": {"floor_eur_mwh", "cap_eur_mwh"},
            "REVENUE_SHARING": {"project_share"},
        }[self.mode]
        self._no_extras(require=allowed)

    def _no_extras(self, require) -> None:
        values = {"fixed_price_eur_mwh": self.fixed_price_eur_mwh,
                  "floor_eur_mwh": self.floor_eur_mwh,
                  "cap_eur_mwh": self.cap_eur_mwh,
                  "project_share": self.project_share}
        strays = sorted(k for k, v in values.items()
                        if k not in require and v is not None)
        if strays:
            raise ValueError(
                f"REVENUE_V4_SCHEMA: price_mode {self.mode} must not carry "
                f"{strays}")


@dataclass(frozen=True)
class RouteToMarketFee:
    """Typed route-to-market fee with up-only annual escalation.

    ``fee_basis`` EUR_PER_MWH charges the fee on delivered MWh;
    PERCENT_OF_REVENUE charges a fraction of gross revenue. Escalation is
    UP-ONLY: a negative ``escalation_rate`` fails closed (the harvest
    records an up-only indexation expectation; a decrease is not a
    supported term). ``review_month`` (1..12) is the EXACT calendar month
    of each annual review; the review DAY inside the month is not pinned
    by the reference harvest and is OWNER DECISION REQUIRED (D-06) — this
    module counts reviews at the first day of the review month and never
    interpolates. Escalation is applied AFTER the fee is resolved and
    BEFORE any contractual price rounding question (order vs the released
    PPA-01 rounding authority is OWNER DECISION REQUIRED, D-07).
    """

    fee_basis: str
    fee_value: float
    escalation_rate: float = 0.0
    escalation_timing: str = "NO_ESCALATION"
    review_month: Optional[int] = None

    def validate(self) -> None:
        _choice(self.fee_basis, "route_to_market.fee_basis", FEE_BASES)
        _num(self.fee_value, "route_to_market.fee_value", minimum=0.0)
        if self.fee_basis == "PERCENT_OF_REVENUE" and self.fee_value > 1.0:
            raise ValueError(
                "REVENUE_V4_VALUE: route_to_market PERCENT_OF_REVENUE "
                "fee_value is a fraction and must be at most 1.0")
        _choice(self.escalation_timing, "route_to_market.escalation_timing",
                ESCALATION_TIMINGS)
        _num(self.escalation_rate, "route_to_market.escalation_rate",
             minimum=0.0)
        if self.escalation_timing == "ANNUAL_REVIEW":
            if not isinstance(self.review_month, int) \
                    or isinstance(self.review_month, bool) \
                    or not 1 <= self.review_month <= 12:
                raise ValueError(
                    "REVENUE_V4_SCHEMA: ANNUAL_REVIEW requires review_month "
                    "as an integer 1..12 (the exact review month)")
        elif self.review_month is not None:
            raise ValueError(
                "REVENUE_V4_SCHEMA: review_month requires "
                "escalation_timing='ANNUAL_REVIEW'")


@dataclass(frozen=True)
class StreamCandidate:
    """Per-stream candidate terms bound to one declared stream id."""

    stream_id: str
    source_ref: str = ""
    negative_price_hours: Optional[NegativePriceHoursPolicy] = None
    contracted_volume: Optional[ContractedVolume] = None
    price_mode: Optional[PriceModeRule] = None
    route_to_market: Optional[RouteToMarketFee] = None

    def validate(self) -> None:
        if not isinstance(self.stream_id, str) or not self.stream_id.strip():
            raise ValueError("REVENUE_V4_SCHEMA: stream_id is required")
        if len(self.stream_id) > 200 or len(self.source_ref) > 200:
            raise ValueError(
                "REVENUE_V4_IDENTITY: stream_id/source_ref must be at most "
                "200 characters")
        for component in (self.negative_price_hours, self.contracted_volume,
                          self.price_mode, self.route_to_market):
            if component is not None:
                component.validate()
        if all(component is None for component in
               (self.negative_price_hours, self.contracted_volume,
                self.price_mode, self.route_to_market)):
            raise ValueError(
                "REVENUE_V4_SCHEMA: at least one candidate term is required "
                "per stream (MISSING is not ZERO)")


@dataclass(frozen=True)
class AdvancedRevenueV4Candidate:
    """The composed candidate book: per-stream terms plus at most one
    plant-scope negative-price policy.

    This is a CANDIDATE description only — it is never evaluated by the
    canonical engine, never persisted by any production writer, and never
    read by any product surface.
    """

    streams: Tuple[StreamCandidate, ...] = field(default=())
    plant_negative_price_hours: Optional[NegativePriceHoursPolicy] = None

    def validate(self) -> None:
        if not self.streams:
            raise ValueError(
                "REVENUE_V4_SCHEMA: at least one stream candidate is "
                "required")
        seen = set()
        for stream in self.streams:
            stream.validate()
            if stream.stream_id in seen:
                raise ValueError(
                    f"REVENUE_V4_IDENTITY: duplicate stream candidate "
                    f"{stream.stream_id!r}")
            seen.add(stream.stream_id)
        if self.plant_negative_price_hours is not None:
            self.plant_negative_price_hours.validate()
            if self.plant_negative_price_hours.scope != "PLANT":
                raise ValueError(
                    "REVENUE_V4_SCHEMA: plant_negative_price_hours must be "
                    "PLANT scope")
        for stream in self.streams:
            nph = stream.negative_price_hours
            if nph is not None and nph.scope == "SINGLE_STREAM" \
                    and nph.stream_id != stream.stream_id:
                raise ValueError(
                    "REVENUE_V4_SCHEMA: a stream-level negative-price policy "
                    "must target its own stream_id")
        if self.plant_negative_price_hours is not None and any(
                s.negative_price_hours is not None for s in self.streams):
            raise ValueError(
                "REVENUE_V4_SCHEMA: plant-scope and stream-scope "
                "negative-price policies cannot be combined (no double "
                "policy; OWNER DECISION REQUIRED for a mixed book, D-01)")

    # ── Deterministic serialization ─────────────────────────────────────────

    def to_payload(self) -> dict:
        def _nph(p: Optional[NegativePriceHoursPolicy]) -> Optional[dict]:
            if p is None:
                return None
            return {"scope": p.scope, "action": p.action,
                    "stream_id": p.stream_id}

        def _vol(v: Optional[ContractedVolume]) -> Optional[dict]:
            if v is None:
                return None
            return {"mode": v.mode, "share": v.share,
                    "fixed_annual_mwh": v.fixed_annual_mwh,
                    "monthly_mw": (list(v.monthly_mw)
                                   if v.monthly_mw is not None else None),
                    "shape_timezone": v.shape_timezone}

        def _pm(p: Optional[PriceModeRule]) -> Optional[dict]:
            if p is None:
                return None
            return {"mode": p.mode,
                    "fixed_price_eur_mwh": p.fixed_price_eur_mwh,
                    "floor_eur_mwh": p.floor_eur_mwh,
                    "cap_eur_mwh": p.cap_eur_mwh,
                    "project_share": p.project_share}

        def _rtm(r: Optional[RouteToMarketFee]) -> Optional[dict]:
            if r is None:
                return None
            return {"fee_basis": r.fee_basis, "fee_value": r.fee_value,
                    "escalation_rate": r.escalation_rate,
                    "escalation_timing": r.escalation_timing,
                    "review_month": r.review_month}

        return {
            "_schema": "finco.revenue-v4-candidate",
            "schema_version": 1,
            "activation": "RELEASE_CLOSED" if not ACTIVATION_ENABLED
            else "ENABLED_FOR_ISOLATED_ACCEPTANCE_ONLY",
            # canonical form is stream-id ordered: the same book serializes
            # to the same bytes regardless of declaration order
            "streams": [
                {"stream_id": s.stream_id, "source_ref": s.source_ref,
                 "negative_price_hours": _nph(s.negative_price_hours),
                 "contracted_volume": _vol(s.contracted_volume),
                 "price_mode": _pm(s.price_mode),
                 "route_to_market": _rtm(s.route_to_market)}
                for s in sorted(self.streams, key=lambda s: s.stream_id)
            ],
            "plant_negative_price_hours": _nph(self.plant_negative_price_hours),
        }

    def canonical_json(self) -> str:
        self.validate()
        return json.dumps(self.to_payload(), sort_keys=True,
                          ensure_ascii=True, allow_nan=False,
                          separators=(",", ":"))


# ── Parse (fail closed, exact key sets) ──────────────────────────────────────

_NPH_KEYS = frozenset({"scope", "action", "stream_id"})
_VOLUME_KEYS = frozenset({"mode", "share", "fixed_annual_mwh", "monthly_mw",
                          "shape_timezone"})
_PRICE_KEYS = frozenset({"mode", "fixed_price_eur_mwh", "floor_eur_mwh",
                         "cap_eur_mwh", "project_share"})
_RTM_KEYS = frozenset({"fee_basis", "fee_value", "escalation_rate",
                       "escalation_timing", "review_month"})
_STREAM_KEYS = frozenset({"stream_id", "source_ref", "negative_price_hours",
                          "contracted_volume", "price_mode",
                          "route_to_market"})
_BOOK_KEYS = frozenset({"_schema", "schema_version", "activation",
                        "streams", "plant_negative_price_hours"})
_CANDIDATE_SCHEMA = "finco.revenue-v4-candidate"


def _object(raw, label: str, keys: frozenset) -> dict:
    if not isinstance(raw, dict):
        raise ValueError(f"REVENUE_V4_SCHEMA: {label} must be an object")
    unknown = sorted(set(raw) - set(keys))
    if unknown:
        raise ValueError(
            f"REVENUE_V4_SCHEMA: {label} carries unsupported key(s) "
            f"{unknown}")
    return raw


def _optional(raw: dict, key: str):
    return raw.get(key)


def parse_negative_price_hours(raw) -> NegativePriceHoursPolicy:
    require_release()
    raw = _object(raw, "negative_price_hours", _NPH_KEYS)
    policy = NegativePriceHoursPolicy(
        scope=_optional(raw, "scope"),
        action=_optional(raw, "action"),
        stream_id=_optional(raw, "stream_id"),
    )
    policy.validate()
    return policy


def parse_contracted_volume(raw) -> ContractedVolume:
    require_release()
    raw = _object(raw, "contracted_volume", _VOLUME_KEYS)
    monthly = _optional(raw, "monthly_mw")
    if monthly is not None:
        if not isinstance(monthly, list) or len(monthly) != 12:
            raise ValueError(
                "REVENUE_V4_SCHEMA: monthly_mw must be an array of exactly "
                "12 numbers")
        monthly = tuple(monthly)
    volume = ContractedVolume(
        mode=_optional(raw, "mode"),
        share=_optional(raw, "share"),
        fixed_annual_mwh=_optional(raw, "fixed_annual_mwh"),
        monthly_mw=monthly,
        shape_timezone=_optional(raw, "shape_timezone"),
    )
    volume.validate()
    return volume


def parse_price_mode(raw) -> PriceModeRule:
    require_release()
    raw = _object(raw, "price_mode", _PRICE_KEYS)
    rule = PriceModeRule(
        mode=_optional(raw, "mode"),
        fixed_price_eur_mwh=_optional(raw, "fixed_price_eur_mwh"),
        floor_eur_mwh=_optional(raw, "floor_eur_mwh"),
        cap_eur_mwh=_optional(raw, "cap_eur_mwh"),
        project_share=_optional(raw, "project_share"),
    )
    rule.validate()
    return rule


def parse_route_to_market(raw) -> RouteToMarketFee:
    require_release()
    raw = _object(raw, "route_to_market", _RTM_KEYS)
    fee = RouteToMarketFee(
        fee_basis=_optional(raw, "fee_basis"),
        fee_value=_optional(raw, "fee_value"),
        escalation_rate=_optional(raw, "escalation_rate") or 0.0,
        escalation_timing=_optional(raw, "escalation_timing")
        or "NO_ESCALATION",
        review_month=_optional(raw, "review_month"),
    )
    fee.validate()
    return fee


def parse_stream_candidate(raw) -> StreamCandidate:
    require_release()
    raw = _object(raw, "stream candidate", _STREAM_KEYS)
    nph_raw = _optional(raw, "negative_price_hours")
    nph = None if nph_raw is None else parse_negative_price_hours(nph_raw)
    vol_raw = _optional(raw, "contracted_volume")
    vol = None if vol_raw is None else parse_contracted_volume(vol_raw)
    price_raw = _optional(raw, "price_mode")
    price = None if price_raw is None else parse_price_mode(price_raw)
    rtm_raw = _optional(raw, "route_to_market")
    rtm = None if rtm_raw is None else parse_route_to_market(rtm_raw)
    candidate = StreamCandidate(
        stream_id=_optional(raw, "stream_id"),
        source_ref=_optional(raw, "source_ref") or "",
        negative_price_hours=nph,
        contracted_volume=vol,
        price_mode=price,
        route_to_market=rtm,
    )
    candidate.validate()
    return candidate


def parse_candidate(raw) -> AdvancedRevenueV4Candidate:
    """Parse and validate a full candidate book payload (fail closed).

    Accepts the exact serialized form produced by
    :meth:`AdvancedRevenueV4Candidate.to_payload`; an unknown ``_schema``
    fails closed exactly like the released authorities."""
    require_release()
    raw = _object(raw, "candidate book", _BOOK_KEYS)
    schema = raw.get("_schema")
    if schema is not None and schema != _CANDIDATE_SCHEMA:
        raise ValueError(
            f"REVENUE_V4_UNSUPPORTED: candidate _schema {schema!r} is not "
            f"{_CANDIDATE_SCHEMA!r}")
    streams_raw = raw.get("streams")
    if not isinstance(streams_raw, list) or not streams_raw:
        raise ValueError(
            "REVENUE_V4_SCHEMA: streams must be a non-empty array")
    streams = tuple(parse_stream_candidate(s) for s in streams_raw)
    plant_raw = _optional(raw, "plant_negative_price_hours")
    plant = None if plant_raw is None else parse_negative_price_hours(plant_raw)
    book = AdvancedRevenueV4Candidate(streams=streams,
                                      plant_negative_price_hours=plant)
    book.validate()
    return book
