"""FINCO Yield Market View — movers, stability and benchmark context.

A DERIVED READ MODEL over the canonical history + the active registry.  It
reads canonical history ONCE per request (one ``read_all``), groups it by
opportunity locally, and derives every per-pool statistic from that single
loaded history.  No second store, no interpolation, no synthetic points;
missing comparisons are UNAVAILABLE, never zero.

Movers currentness gate
-----------------------
A pool enters 24h/7d mover rankings only when its LATEST canonical
observation is CURRENT under the existing canonical Yield freshness policy
(``freshness.evaluate_freshness`` -- no second classifier).  Stale/invalid
observations keep their historically derivable deltas internally but are
never presented as current movers.

Movers TVL floor
----------------
No product TVL policy existed, so one is introduced here explicitly:
``MOVER_MIN_TVL_USD``.  Pools below the floor (or with unavailable TVL) are
excluded from mover rankings entirely -- tiny/dead pools must not dominate
movers purely through extreme percentages.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any

from .alerts_eval import _source_ref_from_row
from .freshness import evaluate_freshness
from .history import YieldHistoryStore, _row_time

MOVER_MIN_TVL_USD = Decimal("1000000")   # explicit product policy (introduced V1)
MOVER_HORIZONS = (("24h", timedelta(hours=24)), ("7d", timedelta(days=7)))
SIGMA_MIN_OBSERVATIONS = 10
SPARKLINE_MAX_POINTS = 48
_BPS = Decimal(10000)


class _RequestHistory(YieldHistoryStore):
    """The canonical store with ONE file read shared by the whole request."""

    def __init__(self, path):
        super().__init__(path)
        self._rows: list[dict[str, Any]] | None = None

    def read_all(self) -> list[dict[str, Any]]:
        if self._rows is None:
            self._rows = super().read_all()
        return self._rows

    def rows_by_uid(self) -> dict[str, list[dict[str, Any]]]:
        grouped: dict[str, list[dict[str, Any]]] = {}
        for row in self.read_all():
            grouped.setdefault(row.get("opportunity_uid"), []).append(row)
        return grouped


def read_rows_by_uid(store: YieldHistoryStore) -> dict[str, list[dict[str, Any]]]:
    """Read canonical history ONCE and group by opportunity uid."""
    if isinstance(store, _RequestHistory):
        return store.rows_by_uid()
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in store.read_all():
        grouped.setdefault(row.get("opportunity_uid"), []).append(row)
    return grouped


def _dec(value: Any) -> Decimal | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = Decimal(str(value))
    except InvalidOperation:
        return None
    return number if number.is_finite() else None


def _sorted_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    ordered = [( _row_time(r), r) for r in rows]
    ordered = [(t, r) for t, r in ordered if t is not None]
    ordered.sort(key=lambda item: item[0])
    return [r for _t, r in ordered]


@dataclass(frozen=True)
class ValueBinding:
    """One economic value bound to the EXACT canonical observation that
    supplied it.  A newer observation that does not carry the value can never
    refresh it -- and can never lend its own freshness to it."""

    value: Decimal | None
    observed_at: datetime | None
    currentness: str            # freshness of the SUPPLYING observation


def _value_binding(sorted_rows: list[dict[str, Any]], field: str,
                   now: datetime) -> ValueBinding:
    """Newest canonical observation carrying a numeric ``field``, bound to its
    own timestamp and freshness.  Missing values are UNAVAILABLE, never
    zero-filled, and never refreshed by a later value-less observation."""
    for row in reversed(sorted_rows):
        value = _dec((row.get("payload") or {}).get(field))
        if value is None:
            continue
        moment = _row_time(row)
        source = _source_ref_from_row(row)
        state = (evaluate_freshness(source, now=now).state
                 if source is not None and moment is not None else "UNAVAILABLE")
        return ValueBinding(value, moment, state)
    return ValueBinding(None, None, "UNAVAILABLE")


def _latest_values(sorted_rows: list[dict[str, Any]]) -> tuple[Decimal | None, Decimal | None]:
    """Latest numeric APY/TVL: the NEWEST canonical observation carrying each
    value (values are missing-annotated, never zero-filled).  APY and TVL are
    resolved independently -- a missing TVL on the newest APY observation does
    not hide an older TVL."""
    now = datetime.now(timezone.utc)
    apy = _value_binding(sorted_rows, "apy_total", now)
    tvl = _value_binding(sorted_rows, "tvl_usd", now)
    return apy.value, tvl.value


def _baseline_apy(sorted_rows: list[dict[str, Any]], cutoff: datetime) -> Decimal | None:
    """Most recent numeric APY at or before ``cutoff`` (exact; no interpolation).
    ``None`` = no baseline in the window (UNAVAILABLE)."""
    baseline = None
    for row in sorted_rows:
        moment = _row_time(row)
        if moment is None or moment > cutoff:
            continue
        value = _dec((row.get("payload") or {}).get("apy_total"))
        if value is not None:
            baseline = value
    return baseline


def _sigma(sorted_rows: list[dict[str, Any]], window: timedelta,
           now: datetime) -> Decimal | None:
    values = []
    lower = now - window
    for row in sorted_rows:
        moment = _row_time(row)
        if moment is None or moment < lower or moment > now:
            continue
        value = _dec((row.get("payload") or {}).get("apy_total"))
        if value is not None:
            values.append(value)
    if len(values) < SIGMA_MIN_OBSERVATIONS:
        return None
    count = Decimal(len(values))
    mean = sum(values, Decimal(0)) / count
    variance = sum(((v - mean) ** 2 for v in values), Decimal(0)) / count
    return variance.sqrt()


def _sparkline(sorted_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Most recent SPARKLINE_MAX_POINTS canonical APY points, oldest-first.
    Exact canonical observations only — the ORIGINAL stored timestamp string
    is passed through untouched; an empty list is the typed empty."""
    points = []
    for row in sorted_rows:
        moment = _row_time(row)
        value = _dec((row.get("payload") or {}).get("apy_total"))
        if moment is None or value is None:
            continue
        points.append({"t": str(row.get("observed_at") or ""), "v": str(value)})
    return points[-SPARKLINE_MAX_POINTS:]


def _currentness(sorted_rows: list[dict[str, Any]], now: datetime) -> str:
    """Canonical freshness of the pool's LATEST observation, evaluated by the
    existing canonical Yield freshness policy (no second classifier)."""
    if not sorted_rows:
        return "UNAVAILABLE"
    source = _source_ref_from_row(sorted_rows[-1])
    if source is None:
        return "UNAVAILABLE"
    return evaluate_freshness(source, now=now).state


@dataclass(frozen=True)
class MoverRow:
    uid: str
    name: str
    horizon: str
    apy_total: Decimal | None
    delta_bps: Decimal | None
    direction: str            # UP | DOWN | UNCHANGED
    tvl_usd: Decimal | None
    rank: int


@dataclass(frozen=True)
class PoolIntel:
    uid: str
    latest_apy: Decimal | None
    latest_tvl: Decimal | None
    currentness: str = "UNAVAILABLE"       # freshness of the newest row overall
    latest_apy_observed_at: datetime | None = None   # APY-bearing observation
    latest_apy_currentness: str = "UNAVAILABLE"      # ITS freshness
    latest_tvl_observed_at: datetime | None = None   # TVL-bearing observation
    latest_tvl_currentness: str = "UNAVAILABLE"      # ITS freshness
    deltas: dict[str, Decimal | None] = field(default_factory=dict)   # horizon -> bps
    directions: dict[str, str] = field(default_factory=dict)
    sigma_30d: Decimal | None = None
    sigma_source: str | None = None      # FINCO_HISTORICAL when present
    sparkline: list[dict[str, Any]] = field(default_factory=list)
    spread_bps: Decimal | None = None
    spread_source: str | None = None


@dataclass(frozen=True)
class MarketView:
    as_of: datetime
    tvl_floor: Decimal
    pools_observed: int
    pools_above_floor: int
    movers: dict[str, list[MoverRow]]          # horizon -> ranked rows
    pools: dict[str, PoolIntel]
    median_apy: Decimal | None
    best_apy: dict[str, Any] | None            # {uid, name, apy}
    treasury: Any | None = None                # treasury.TreasuryObservation


def _baseline_delta(sorted_rows: list[dict[str, Any]], latest_apy: Decimal | None,
                    span: timedelta, *, anchor: datetime | None = None,
) -> tuple[Decimal | None, str]:
    """Delta of the current APY against the newest canonical observation at or
    before ``anchor - span``.  ``anchor`` is the APY-BEARING observation's own
    timestamp (the same observation-anchored convention as
    ``intelligence.build_intelligence``) -- a later TVL-only row never moves
    the cutoff.  ``None`` = no baseline in the window (UNAVAILABLE, never
    zero)."""
    if latest_apy is None:
        return None, "LATEST_APY_MISSING"
    if not sorted_rows:
        return None, "NO_BASELINE"
    if anchor is None:
        anchor = _row_time(sorted_rows[-1])
    if anchor is None:
        return None, "NO_BASELINE"
    baseline = _baseline_apy(sorted_rows, anchor - span)
    if baseline is None:
        return None, "NO_BASELINE"
    return (latest_apy - baseline) * _BPS, "AVAILABLE"


def build_market_view(store: YieldHistoryStore, registry, *, as_of: datetime,
                      tvl_floor: Decimal = MOVER_MIN_TVL_USD,
                      treasury: Any | None = None,
                      rows_by_uid: dict[str, list[dict[str, Any]]] | None = None) -> MarketView:
    """One canonical history read -> movers, stability, spread, sparklines.

    ``registry`` is the active YieldRegistry (current APY/TVL observations
    overlay canonical history at the collection boundary); ``treasury`` is an
    optional ``treasury.TreasuryObservation``.  ``rows_by_uid`` lets a caller
    that already grouped the canonical history (e.g. the Explore route, which
    needs the same rows for its own summaries) reuse it so the file is read
    exactly once per request.
    """
    if as_of.tzinfo is None:
        raise ValueError("as_of must be timezone-aware")
    grouped = rows_by_uid if rows_by_uid is not None else read_rows_by_uid(store)

    pools: dict[str, PoolIntel] = {}
    names = {opportunity.uid: opportunity.name for opportunity in registry.all()}
    for uid in sorted(set(names) | set(grouped)):
        rows = _sorted_rows(grouped.get(uid, []))
        # Canonical history is the ONLY economic observation authority here:
        # REFERENCE_FIXTURE registry values never become market-current data.
        # Each value is bound to the exact observation that supplied it: a
        # newer APY-missing observation never refreshes an older APY (and
        # never lends the APY its own freshness), and vice versa for TVL.
        apy_binding = _value_binding(rows, "apy_total", as_of)
        tvl_binding = _value_binding(rows, "tvl_usd", as_of)
        apy, tvl = apy_binding.value, tvl_binding.value
        currentness = _currentness(rows, as_of)
        deltas, directions = {}, {}
        for horizon, span in MOVER_HORIZONS:
            # The horizon anchor is the APY-BEARING observation's own
            # timestamp -- never a later TVL-only / APY-missing row.
            delta, _reason = _baseline_delta(rows, apy, span,
                                             anchor=apy_binding.observed_at)
            deltas[horizon] = delta
            directions[horizon] = ("UP" if delta is not None and delta > 0
                                   else "DOWN" if delta is not None and delta < 0
                                   else "UNCHANGED" if delta is not None
                                   else "UNAVAILABLE")
        sigma = _sigma(rows, timedelta(days=30), as_of)
        # Spread requires BOTH sides current: a fresh Treasury observation AND
        # a CURRENT canonical APY-bearing yield observation.  Stale yield,
        # stale treasury or missing evidence -> unavailable (never zero).
        spread = None
        spread_source = None
        if (apy is not None and apy_binding.currentness == "CURRENT"
                and treasury is not None and treasury.usable):
            spread = _spread_bps(apy, treasury.yield_percent)
            spread_source = f"APY_VS_{treasury.source}" if spread is not None else None
        pools[uid] = PoolIntel(
            uid=uid,
            latest_apy=apy,
            latest_tvl=tvl,
            currentness=currentness,
            latest_apy_observed_at=apy_binding.observed_at,
            latest_apy_currentness=apy_binding.currentness,
            latest_tvl_observed_at=tvl_binding.observed_at,
            latest_tvl_currentness=tvl_binding.currentness,
            deltas=deltas,
            directions=directions,
            sigma_30d=sigma,
            sigma_source="FINCO_HISTORICAL" if sigma is not None else None,
            sparkline=_sparkline(rows),
            spread_bps=spread,
            spread_source=spread_source,
        )

    def _current_candidate(uid: str) -> bool:
        intel = pools[uid]
        return (intel.latest_tvl is not None and intel.latest_tvl >= tvl_floor
                and intel.latest_tvl_currentness == "CURRENT"
                and intel.latest_apy is not None
                and intel.latest_apy_currentness == "CURRENT")

    above_floor = {uid for uid in pools if _current_candidate(uid)}
    movers: dict[str, list[MoverRow]] = {}
    for horizon, _span in MOVER_HORIZONS:
        ranked = []
        for uid, intel in pools.items():
            delta = intel.deltas.get(horizon)
            if delta is None or uid not in above_floor:
                continue
            ranked.append((abs(delta), uid, delta))
        ranked.sort(key=lambda item: (-item[0], item[1]))
        movers[horizon] = [
            MoverRow(uid=uid, name=names.get(uid, uid), horizon=horizon,
                     apy_total=pools[uid].latest_apy, delta_bps=delta,
                     direction=pools[uid].directions.get(horizon, "UNAVAILABLE"),
                     tvl_usd=pools[uid].latest_tvl, rank=rank + 1)
            for rank, (_abs, uid, delta) in enumerate(ranked)
        ]

    eligible_apys = sorted(pools[uid].latest_apy for uid in above_floor)
    median = None
    if eligible_apys:
        mid = len(eligible_apys) // 2
        median = (eligible_apys[mid] if len(eligible_apys) % 2
                  else (eligible_apys[mid - 1] + eligible_apys[mid]) / 2)
    best = None
    if eligible_apys:
        top = max(above_floor, key=lambda uid: pools[uid].latest_apy)
        best = {"uid": top, "name": names.get(top, top),
                "apy": pools[top].latest_apy}
    return MarketView(
        as_of=as_of,
        tvl_floor=tvl_floor,
        pools_observed=sum(1 for intel in pools.values() if intel.latest_apy is not None),
        pools_above_floor=len(above_floor),
        movers=movers,
        pools=pools,
        median_apy=median,
        best_apy=best,
        treasury=treasury,
    )


def _spread_bps(apy_fraction: Decimal, treasury_percent: Decimal) -> Decimal | None:
    try:
        return (apy_fraction * Decimal(100) - Decimal(treasury_percent)) * Decimal(100)
    except InvalidOperation:
        return None
