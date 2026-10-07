"""Append-only B1.3 intelligence history, scoped to exact UID and deployment.

R5 uses canonical JSON plus SHA-256 for deterministic evidence identity.  This
store follows that convention and the existing Radar SQLite snapshot ledger;
it is not a replacement for either authority.
"""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from threading import RLock

from finco_radar.assets.contracts import AssetKey, normalize_asset_uid
from finco_radar.authority.cross_chain import CrossChainIdentityBinding
from finco_radar.authority.contracts import AuthoritySnapshot, AuthorityState
from finco_radar.authority.r_live_onchain import OnchainReferenceObservation


DEFAULT_DB_PATH = str(Path(__file__).resolve().parents[1] / "data" / "radar_bnb_intelligence.db")
MAX_RLIVE_RANGE_POINTS = 5000


def _source_collection_time(evidence: dict) -> str | None:
    """Use only the on-chain acquisition clock, never a synthetic read time."""
    raw = evidence.get("retrievedAt")
    if not isinstance(raw, str):
        return None
    try:
        timestamp = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if timestamp.tzinfo is None or timestamp.utcoffset() is None:
        return None
    return timestamp.astimezone(timezone.utc).isoformat()


def _range_result(values: list[Decimal]) -> dict:
    return {"state": "AVAILABLE" if len(values) >= 2 else "UNAVAILABLE",
            "low_bps": str(min(values)) if len(values) >= 2 else None,
            "high_bps": str(max(values)) if len(values) >= 2 else None,
            "observation_count": len(values)}


def _range_summary_from_rows(rows, latest, *, now: datetime,
                             include_series: bool = False,
                             max_series_points: int = 48) -> dict:
    """Pure post-processing for B1.3 range summaries.

    ``rows`` are the bounded (digest, payload) window rows newest-first for
    ONE exact identity pair; ``latest`` is that pair's newest AVAILABLE row
    (or None). Digest verification, canonical timestamps and filters are
    identical to the per-asset read path — this helper exists so the batch
    read produces byte-identical summaries.

    ``include_series`` additionally returns a bounded, deterministic,
    display-only 24h premium series (``series_24h``) extracted from the SAME
    digest-verified, already-filtered window points: oldest-first
    ``[{"collected_at", "premium_bps"}]`` LTTB-downsampled to at most
    ``max_series_points`` (first and last canonical points always preserved;
    visually material spikes survive). No interpolation, no synthetic
    points, no canonical data change — pure visual selection.
    """
    last_available = None
    if latest is not None:
        latest_digest, latest_payload = latest
        if hashlib.sha256(latest_payload.encode("utf-8")).hexdigest() != latest_digest:
            raise ValueError("history digest does not reconstruct")
        point = json.loads(latest_payload)
        basis = point.get("robinhood_basis") or {}
        reference = point.get("independent_token_reference") or {}
        legacy_evidence = reference.get("evidence")
        legacy_collection_time = (_source_collection_time(legacy_evidence)
                                  if isinstance(legacy_evidence, dict) else None)
        if (basis.get("price_usd_per_token") is not None
                and reference.get("priceUsdPerToken") is not None
                and point.get("reference_premium_bps") is not None):
            last_available = {
                # Legacy B1.3 rows predate collected_at but retain the
                # source-proven acquisition timestamp inside token evidence.
                # Never substitute observed_at or the current read time.
                "collected_at": point.get("collected_at") or legacy_collection_time,
                "effective_evidence_at": point.get("observed_at"),
                "basis_price_usd_per_token": basis["price_usd_per_token"],
                "token_price_usd_per_token": reference["priceUsdPerToken"],
                "premium_bps": point["reference_premium_bps"],
            }
    if len(rows) > MAX_RLIVE_RANGE_POINTS:
        result = {"range_1h": _range_result([]), "range_24h": _range_result([]),
                  "last_available": last_available, "reason": "HISTORY_WINDOW_CAP_EXCEEDED"}
        if include_series:
            result["series_24h"] = []
        return result
    one_hour = []
    one_day = []
    series: list[tuple[datetime, str]] = []
    hour_cutoff = now - timedelta(hours=1)
    for digest, payload in rows:
        if hashlib.sha256(payload.encode("utf-8")).hexdigest() != digest:
            raise ValueError("history digest does not reconstruct")
        point = json.loads(payload)
        if point.get("state") != "AVAILABLE":
            continue
        try:
            collected = datetime.fromisoformat(point["collected_at"])
            value = Decimal(point["reference_premium_bps"])
        except (KeyError, TypeError, ValueError, InvalidOperation):
            continue
        if collected.tzinfo is None or collected.utcoffset() is None:
            continue
        collected = collected.astimezone(timezone.utc)
        if not value.is_finite() or collected > now or collected < now - timedelta(hours=24):
            continue
        one_day.append(value)
        if collected >= hour_cutoff:
            one_hour.append(value)
        if include_series:
            series.append((collected, point["reference_premium_bps"]))
    result = {"range_1h": _range_result(one_hour), "range_24h": _range_result(one_day),
              "last_available": last_available}
    if include_series:
        series.sort(key=lambda item: item[0])
        result["series_24h"] = _downsample_series(series, max_series_points)
    return result


def _downsample_series(series: list[tuple[datetime, str]],
                       max_points: int) -> list[dict]:
    """Deterministic display-only downsample of verified canonical points.

    Series within the budget render directly (exact canonical points). Longer
    series are reduced with LTTB (Largest Triangle Three Buckets, adapted
    from the MIT lttb-py reference as a dependency-light primitive): the
    visually material excursions — short-lived premium spikes and
    dislocations — survive, which a first-of-bucket sampler would silently
    discard. First and last canonical points are always preserved and every
    selected point is an ACTUAL canonical observation: no interpolation, no
    generated values, no rewritten timestamps.
    """
    if max_points <= 0 or len(series) <= max_points:
        return [{"collected_at": collected.isoformat(), "premium_bps": value}
                for collected, value in series]
    selected = _lttb_select(series, max_points)
    return [{"collected_at": series[i][0].isoformat(), "premium_bps": series[i][1]}
            for i in selected]


def _lttb_select(series: list[tuple[datetime, str]], max_points: int) -> list[int]:
    """LTTB index selection over (timestamp, value) canonical points.

    Deterministic: bucket boundaries are fixed fractions of the series
    length and ties resolve to the first maximal-area point. The first
    point seeds the running anchor and the last point is always kept.
    """
    n = len(series)
    if n <= max_points or max_points < 3:
        return list(range(n))
    xs = [float(collected.timestamp()) for collected, _value in series]
    ys = [float(Decimal(value)) for _collected, value in series]
    kept = [0]
    bucket_count = max_points - 2
    bucket_size = (n - 2) / bucket_count
    anchor = 0
    for i in range(1, bucket_count + 1):
        # Average of the NEXT bucket is the far triangle edge; for the final
        # bucket it is exactly the last canonical point.
        if i < bucket_count:
            nxt_start = 1 + int(i * bucket_size)
            nxt_end = 1 + int((i + 1) * bucket_size)
            nxt = range(nxt_start, max(nxt_end, nxt_start + 1))
            avg_x = sum(xs[j] for j in nxt) / len(nxt)
            avg_y = sum(ys[j] for j in nxt) / len(nxt)
        else:
            avg_x, avg_y = xs[-1], ys[-1]
        start = 1 + int((i - 1) * bucket_size)
        end = 1 + int(i * bucket_size)
        best_index, best_area = start, -1.0
        ax, ay = xs[anchor], ys[anchor]
        for j in range(start, max(end, start + 1)):
            area = abs((ax - avg_x) * (ys[j] - ay) - (ax - xs[j]) * (avg_y - ay)) * 0.5
            if area > best_area:
                best_area, best_index = area, j
        kept.append(best_index)
        anchor = best_index
    kept.append(n - 1)
    return kept


_RANGE_WINDOW_SQL = (
    "SELECT economic_asset_uid, asset_key, digest, payload "
    "FROM bnb_intelligence_history "
    "WHERE ({pairs}) "
    "AND json_extract(payload, '$.collected_at') >= ? "
    "AND json_extract(payload, '$.collected_at') <= ? "
    "ORDER BY json_extract(payload, '$.collected_at') DESC"
)

_RANGE_LATEST_SQL = (
    "SELECT economic_asset_uid, asset_key, "
    "MAX(COALESCE(json_extract(payload, '$.collected_at'), "
    "json_extract(payload, '$.independent_token_reference.evidence.retrievedAt'), "
    "observed_at)) AS clock, digest, payload "
    "FROM bnb_intelligence_history "
    "WHERE ({pairs}) "
    "AND json_extract(payload, '$.state') = 'AVAILABLE' "
    "GROUP BY economic_asset_uid, asset_key"
)


def read_r_live_range_summary_readonly(uid: str, key: AssetKey, *,
                                       as_of: datetime | None = None,
                                       path: str | None = None) -> dict:
    """Complete bounded 24h B1.3 summary without opening a history writer."""
    if key.chain_id != 4663:
        raise ValueError("exact Robinhood key required")
    identity = normalize_asset_uid(uid)
    now = as_of or datetime.now(timezone.utc)
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("range clock must be timezone-aware")
    now = now.astimezone(timezone.utc)
    empty = {"range_1h": _range_result([]), "range_24h": _range_result([]),
             "last_available": None}
    location = path or os.getenv("RADAR_BNB_INTELLIGENCE_DB_PATH", DEFAULT_DB_PATH)
    if location == ":memory:" or not Path(location).is_file():
        return empty
    cutoff = (now - timedelta(hours=24)).isoformat()
    with sqlite3.connect(Path(location).resolve().as_uri() + "?mode=ro", uri=True, timeout=5) as conn:
        rows = conn.execute(
            "SELECT digest, payload FROM bnb_intelligence_history "
            "WHERE economic_asset_uid = ? AND asset_key = ? "
            "AND json_extract(payload, '$.collected_at') >= ? "
            "AND json_extract(payload, '$.collected_at') <= ? "
            "ORDER BY json_extract(payload, '$.collected_at') DESC LIMIT ?",
            (identity, key.canonical_id, cutoff, now.isoformat(), MAX_RLIVE_RANGE_POINTS + 1),
        ).fetchall()
        latest = conn.execute(
            "SELECT digest, payload FROM bnb_intelligence_history "
            "WHERE economic_asset_uid = ? AND asset_key = ? "
            "AND json_extract(payload, '$.state') = 'AVAILABLE' "
            "ORDER BY COALESCE(json_extract(payload, '$.collected_at'), "
            "json_extract(payload, '$.independent_token_reference.evidence.retrievedAt'), "
            "observed_at) DESC LIMIT 1",
            (identity, key.canonical_id),
        ).fetchone()
    return _range_summary_from_rows(rows, latest, now=now)


def read_r_live_ranges_batch_readonly(pairs, *, as_of: datetime | None = None,
                                      path: str | None = None,
                                      include_series: bool = False,
                                      max_series_points: int = 48) -> dict:
    """Single-pass read-only 24h range summaries for MANY exact pairs.

    One store open and two grouped queries replace the per-asset store reads
    on the all-assets landing surface. Row selection, ordering, digest
    verification and filtering are identical to
    ``read_r_live_range_summary_readonly``: each pair's window rows are the
    newest-first bounded set that pair's own LIMIT query would return, and
    each pair's latest row is that pair's newest AVAILABLE point.

    With ``include_series`` each summary additionally carries the bounded
    display-only ``series_24h`` premium series extracted from the same
    digest-verified window points (see ``_range_summary_from_rows``) — no
    extra store reads, no interpolation, no synthetic points.

    Returns ``{canonical_id: summary}``. Per-pair computation failures map
    to ``{"reason": "HISTORY_UNAVAILABLE"}`` exactly like the router-level
    per-asset try/except on the single read.
    """
    checked: list[tuple[str, str]] = []
    for uid, key in pairs:
        if key.chain_id != 4663:
            raise ValueError("exact Robinhood key required")
        checked.append((normalize_asset_uid(uid), key.canonical_id))
    now = as_of or datetime.now(timezone.utc)
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("range clock must be timezone-aware")
    now = now.astimezone(timezone.utc)
    empty = {"range_1h": _range_result([]), "range_24h": _range_result([]),
             "last_available": None}
    if include_series:
        empty["series_24h"] = []
    location = path or os.getenv("RADAR_BNB_INTELLIGENCE_DB_PATH", DEFAULT_DB_PATH)
    if not checked:
        return {}
    if location == ":memory:" or not Path(location).is_file():
        return {canonical_id: dict(empty) for _, canonical_id in checked}
    cutoff = (now - timedelta(hours=24)).isoformat()
    pair_clause = " OR ".join(
        "(economic_asset_uid = ? AND asset_key = ?)" for _ in checked)
    pair_params = [value for pair in checked for value in pair]

    windows: dict[tuple[str, str], list] = {pair: [] for pair in checked}
    latest: dict[tuple[str, str], tuple] = {}
    with sqlite3.connect(Path(location).resolve().as_uri() + "?mode=ro", uri=True, timeout=5) as conn:
        # Newest-first across all requested pairs; per-pair newest-first order
        # is preserved, so slicing per pair reproduces each pair's LIMIT query.
        for uid, asset_key, digest, payload in conn.execute(
                _RANGE_WINDOW_SQL.format(pairs=pair_clause),
                [*pair_params, cutoff, now.isoformat()]):
            rows = windows.get((uid, asset_key))
            if rows is not None:
                rows.append((digest, payload))
        # One grouped query returns each pair's newest AVAILABLE row (SQLite
        # bare columns with MAX() come from the max-clock row), matching the
        # per-pair ORDER BY clock DESC LIMIT 1.
        for uid, asset_key, _clock, digest, payload in conn.execute(
                _RANGE_LATEST_SQL.format(pairs=pair_clause), pair_params):
            if (uid, asset_key) in windows:
                latest[(uid, asset_key)] = (digest, payload)

    # Enforce the per-pair window cap after grouping (same bound as the
    # per-pair SQL LIMIT MAX_RLIVE_RANGE_POINTS + 1).
    for rows in windows.values():
        del rows[MAX_RLIVE_RANGE_POINTS + 1:]

    out: dict[str, dict] = {}
    for pair in checked:
        try:
            out[pair[1]] = _range_summary_from_rows(
                windows.get(pair, []), latest.get(pair), now=now,
                include_series=include_series, max_series_points=max_series_points)
        except Exception:
            out[pair[1]] = {"reason": "HISTORY_UNAVAILABLE"}
    return out



def _verified_last_canonical_r_live_point(
    row, uid: str, key: AssetKey,
) -> dict | None:
    """Digest-check one complete canonical R-LIVE observation for fallback.

    This is deliberately stricter than a chart/range row: the outer B1.3
    identity, embedded token identity, component prices, component clocks and
    premium sources must all belong to the same persisted AVAILABLE snapshot.
    Nothing is recomputed or borrowed from a newer source.
    """
    if row is None:
        return None
    digest, payload = row
    if hashlib.sha256(payload.encode("utf-8")).hexdigest() != digest:
        raise ValueError("history digest does not reconstruct")
    try:
        point = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise ValueError("history payload is invalid JSON") from exc

    try:
        point_uid = normalize_asset_uid(point.get("economic_asset_uid"))
    except (TypeError, ValueError):
        return None
    if (point_uid != uid or point.get("asset_key") != key.canonical_id
            or point.get("state") != "AVAILABLE"):
        return None

    basis = point.get("robinhood_basis")
    reference = point.get("independent_token_reference")
    if not isinstance(basis, dict) or not isinstance(reference, dict):
        return None
    if (reference.get("state") != "AVAILABLE"
            or reference.get("assetKey") != key.canonical_id
            or reference.get("assetUid") != uid):
        return None

    evidence = reference.get("evidence")
    if not isinstance(evidence, dict):
        return None
    if (evidence.get("assetKey") != key.canonical_id
            or evidence.get("registryAssetUid") != uid):
        return None

    try:
        token_price = Decimal(str(reference["priceUsdPerToken"]))
        basis_price = Decimal(str(basis["price_usd_per_token"]))
        premium = Decimal(str(point["reference_premium_bps"]))
    except (KeyError, TypeError, ValueError, InvalidOperation):
        return None
    if (not token_price.is_finite() or token_price <= 0
            or not basis_price.is_finite() or basis_price <= 0
            or not premium.is_finite()):
        return None

    def aware_iso(value) -> datetime | None:
        if not isinstance(value, str):
            return None
        try:
            parsed = datetime.fromisoformat(value)
        except ValueError:
            return None
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            return None
        return parsed.astimezone(timezone.utc)

    token_at = aware_iso(reference.get("observedAt"))
    basis_at = aware_iso(basis.get("observed_at"))
    effective_at = aware_iso(point.get("observed_at"))
    if token_at is None or basis_at is None or effective_at is None:
        return None
    if token_at != effective_at:
        return None

    sources = point.get("premium_sources")
    clocks = point.get("premium_evidence_at")
    if (not isinstance(sources, list) or len(sources) != 2
            or not all(isinstance(source, str) and source for source in sources)
            or sources[0] != basis.get("source")
            or not isinstance(clocks, list) or len(clocks) != 2
            or aware_iso(clocks[0]) != basis_at
            or aware_iso(clocks[1]) != token_at):
        return None

    collection_clock = _history_collection_datetime(point)
    if collection_clock is None:
        return None
    return {
        "digest": digest,
        "point": point,
        "collection_clock": collection_clock.isoformat(),
    }


def read_latest_r_live_observations_batch_readonly(
    pairs, *, as_of: datetime | None = None, path: str | None = None,
) -> dict[str, dict]:
    """Latest complete canonical R-LIVE snapshot for each exact UID/AssetKey.

    This is the read-time last-price authority. It opens the existing B1.3
    append-only ledger read-only, verifies the row digest and exact embedded
    identity, and returns the original persisted snapshot unchanged. It never
    creates a database, appends history, refreshes a timestamp, or combines
    evidence from different observations.
    """
    checked: list[tuple[str, str, AssetKey]] = []
    for uid, key in pairs:
        if key.chain_id != 4663:
            raise ValueError("exact Robinhood key required")
        checked.append((normalize_asset_uid(uid), key.canonical_id, key))
    if not checked:
        return {}

    now = as_of or datetime.now(timezone.utc)
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("last-price read clock must be timezone-aware")
    now = now.astimezone(timezone.utc)

    location = path or os.getenv("RADAR_BNB_INTELLIGENCE_DB_PATH", DEFAULT_DB_PATH)
    if location == ":memory:" or not Path(location).is_file():
        return {}

    pair_clause = " OR ".join(
        "(economic_asset_uid = ? AND asset_key = ?)" for _ in checked)
    pair_params = [value for uid, asset_key, _key in checked
                   for value in (uid, asset_key)]
    clock_sql = (
        "COALESCE(json_extract(payload, '$.collected_at'), "
        "json_extract(payload, '$.independent_token_reference.evidence.retrievedAt'), "
        "observed_at)"
    )
    query = (
        "SELECT economic_asset_uid, asset_key, digest, payload FROM ("
        " SELECT economic_asset_uid, asset_key, digest, payload,"
        " ROW_NUMBER() OVER (PARTITION BY economic_asset_uid, asset_key "
        f"ORDER BY {clock_sql} DESC, digest DESC) AS rn "
        " FROM bnb_intelligence_history "
        f" WHERE ({pair_clause}) "
        " AND json_extract(payload, '$.state') = 'AVAILABLE' "
        f" AND {clock_sql} IS NOT NULL AND {clock_sql} <= ?"
        ") WHERE rn = 1"
    )

    uri = Path(location).resolve().as_uri() + "?mode=ro"
    with sqlite3.connect(uri, uri=True, timeout=5) as conn:
        rows = conn.execute(query, [*pair_params, now.isoformat()]).fetchall()

    keys = {(uid, asset_key): key for uid, asset_key, key in checked}
    out: dict[str, dict] = {}
    for uid, asset_key, digest, payload in rows:
        key = keys.get((uid, asset_key))
        if key is None:
            continue
        verified = _verified_last_canonical_r_live_point(
            (digest, payload), uid, key)
        if verified is not None:
            out[key.canonical_id] = verified
    return out


def _history_collection_datetime(point: dict) -> datetime | None:
    """Return source acquisition time only; never synthesize a history clock."""
    raw = point.get("collected_at")
    if not isinstance(raw, str):
        reference = point.get("independent_token_reference")
        evidence = reference.get("evidence") if isinstance(reference, dict) else None
        raw = _source_collection_time(evidence) if isinstance(evidence, dict) else None
    if not isinstance(raw, str):
        return None
    try:
        value = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if value.tzinfo is None or value.utcoffset() is None:
        return None
    return value.astimezone(timezone.utc)


def _verified_basis_history_point(row, uid: str, key: AssetKey) -> dict | None:
    """Digest-check and exact-bind one existing B1.3 history row."""
    if row is None:
        return None
    digest, payload = row
    if hashlib.sha256(payload.encode("utf-8")).hexdigest() != digest:
        raise ValueError("history digest does not reconstruct")
    try:
        point = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise ValueError("history payload is invalid JSON") from exc
    try:
        point_uid = normalize_asset_uid(point.get("economic_asset_uid"))
    except (TypeError, ValueError):
        return None
    if point_uid != uid or point.get("asset_key") != key.canonical_id:
        return None
    if point.get("state") != "AVAILABLE":
        return None
    try:
        premium = Decimal(str(point["reference_premium_bps"]))
    except (KeyError, TypeError, ValueError, InvalidOperation):
        return None
    if not premium.is_finite():
        return None
    collected = _history_collection_datetime(point)
    if collected is None:
        return None
    basis = point.get("robinhood_basis")
    reference = point.get("independent_token_reference")
    if not isinstance(basis, dict) or not isinstance(reference, dict):
        return None

    liquidity = None
    evidence = reference.get("evidence")
    if isinstance(evidence, dict):
        try:
            raw_liquidity = Decimal(str(evidence.get("liquidity")))
        except (InvalidOperation, TypeError, ValueError):
            raw_liquidity = None
        if raw_liquidity is not None and raw_liquidity.is_finite() and raw_liquidity >= 0:
            liquidity = {
                "value": str(raw_liquidity),
                "unit": "UNISWAP_V3_ACTIVE_LIQUIDITY_RAW",
                "source": "UNISWAP_V3_POOL_STATE",
            }

    return {
        "collected_at": collected.isoformat(),
        "effective_evidence_at": point.get("observed_at"),
        "basis_price_usd_per_token": basis.get("price_usd_per_token"),
        "token_price_usd_per_token": reference.get("priceUsdPerToken"),
        "premium_bps": str(premium),
        "liquidity": liquidity,
        "_premium": premium,
        "_collected": collected,
    }


def read_r_live_basis_history_summary_readonly(
    uid: str,
    key: AssetKey,
    *,
    as_of: datetime | None = None,
    max_24h_baseline_skew_seconds: int,
    path: str | None = None,
) -> dict:
    """Derived exact-history view over the existing B1.3 ledger.

    No interpolation or synthetic backfill is permitted. 24h change exists
    only when the latest exact observation is current to the requested clock
    and an exact observation exists inside the caller-supplied window around
    T-24h. The actual observation gap is always exposed.
    """
    if key.chain_id != 4663:
        raise ValueError("exact Robinhood key required")
    if max_24h_baseline_skew_seconds <= 0:
        raise ValueError("positive 24h baseline skew required")
    identity = normalize_asset_uid(uid)
    now = as_of or datetime.now(timezone.utc)
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("history summary clock must be timezone-aware")
    now = now.astimezone(timezone.utc)
    ranges = read_r_live_range_summary_readonly(identity, key, as_of=now, path=path)
    result = {
        "latest_observation": None,
        "prior_observation": None,
        "range_24h": ranges["range_24h"],
        "change_24h": {
            "state": "UNAVAILABLE",
            "change_bps": None,
            "latest_collected_at": None,
            "baseline_collected_at": None,
            "observation_gap_seconds": None,
            "reason": "HISTORY_POINTS_UNAVAILABLE",
        },
        "interpolation": False,
    }
    location = path or os.getenv("RADAR_BNB_INTELLIGENCE_DB_PATH", DEFAULT_DB_PATH)
    if location == ":memory:" or not Path(location).is_file():
        return result

    target = now - timedelta(hours=24)
    tolerance = timedelta(seconds=max_24h_baseline_skew_seconds)
    clock_sql = (
        "COALESCE(json_extract(payload, '$.collected_at'), "
        "json_extract(payload, '$.independent_token_reference.evidence.retrievedAt'))"
    )
    uri = Path(location).resolve().as_uri() + "?mode=ro"
    with sqlite3.connect(uri, uri=True, timeout=5) as conn:
        latest_rows = conn.execute(
            "SELECT digest, payload FROM bnb_intelligence_history "
            "WHERE economic_asset_uid = ? AND asset_key = ? "
            "AND json_extract(payload, '$.state') = 'AVAILABLE' "
            f"AND {clock_sql} IS NOT NULL AND {clock_sql} <= ? "
            f"ORDER BY {clock_sql} DESC, digest DESC LIMIT 2",
            (identity, key.canonical_id, now.isoformat()),
        ).fetchall()
        before = conn.execute(
            "SELECT digest, payload FROM bnb_intelligence_history "
            "WHERE economic_asset_uid = ? AND asset_key = ? "
            "AND json_extract(payload, '$.state') = 'AVAILABLE' "
            f"AND {clock_sql} >= ? AND {clock_sql} <= ? "
            f"ORDER BY {clock_sql} DESC, digest DESC LIMIT 1",
            (identity, key.canonical_id, (target - tolerance).isoformat(), target.isoformat()),
        ).fetchone()
        after = conn.execute(
            "SELECT digest, payload FROM bnb_intelligence_history "
            "WHERE economic_asset_uid = ? AND asset_key = ? "
            "AND json_extract(payload, '$.state') = 'AVAILABLE' "
            f"AND {clock_sql} >= ? AND {clock_sql} <= ? "
            f"ORDER BY {clock_sql} ASC, digest ASC LIMIT 1",
            (identity, key.canonical_id, target.isoformat(), (target + tolerance).isoformat()),
        ).fetchone()

    latest = _verified_basis_history_point(latest_rows[0], identity, key) if latest_rows else None
    prior = _verified_basis_history_point(latest_rows[1], identity, key) if len(latest_rows) > 1 else None
    if latest is not None:
        result["latest_observation"] = {
            key_name: value for key_name, value in latest.items() if not key_name.startswith("_")
        }
    if prior is not None:
        result["prior_observation"] = {
            key_name: value for key_name, value in prior.items() if not key_name.startswith("_")
        }
    if latest is None:
        return result

    latest_age = (now - latest["_collected"]).total_seconds()
    if latest_age < 0 or latest_age > max_24h_baseline_skew_seconds:
        result["change_24h"]["reason"] = "LATEST_HISTORY_POINT_OUTSIDE_CURRENT_WINDOW"
        return result

    candidates = []
    for candidate_row in (before, after):
        candidate = _verified_basis_history_point(candidate_row, identity, key)
        if candidate is not None:
            candidates.append(candidate)
    if not candidates:
        result["change_24h"]["reason"] = "EXACT_24H_BASELINE_UNAVAILABLE"
        return result
    baseline = min(candidates, key=lambda item: abs((item["_collected"] - target).total_seconds()))
    target_skew = abs((baseline["_collected"] - target).total_seconds())
    if target_skew > max_24h_baseline_skew_seconds:
        result["change_24h"]["reason"] = "EXACT_24H_BASELINE_OUTSIDE_WINDOW"
        return result

    change = latest["_premium"] - baseline["_premium"]
    result["change_24h"] = {
        "state": "AVAILABLE",
        "change_bps": str(change),
        "latest_collected_at": latest["collected_at"],
        "baseline_collected_at": baseline["collected_at"],
        "observation_gap_seconds": int(
            abs((latest["_collected"] - baseline["_collected"]).total_seconds())
        ),
        "reason": None,
    }
    return result


def read_r_live_points_readonly(uid: str, key: AssetKey, *, limit: int = 30,
                                path: str | None = None) -> list[dict]:
    """Read an existing B1.3 ledger without creating files, schema or a writer."""
    if key.chain_id != 4663 or not 1 <= limit <= 100:
        raise ValueError("exact Robinhood key and bounded limit required")
    identity = normalize_asset_uid(uid)
    location = path or os.getenv("RADAR_BNB_INTELLIGENCE_DB_PATH", DEFAULT_DB_PATH)
    if location == ":memory:":
        return []
    db_path = Path(location)
    if not db_path.is_file():
        return []
    with sqlite3.connect(db_path.resolve().as_uri() + "?mode=ro", uri=True, timeout=5) as conn:
        rows = conn.execute(
            "SELECT digest, payload FROM bnb_intelligence_history "
            "WHERE economic_asset_uid = ? AND asset_key = ? "
            "ORDER BY observed_at DESC, digest DESC LIMIT ?",
            (identity, key.canonical_id, limit),
        ).fetchall()
    points = []
    for digest, payload in rows:
        if hashlib.sha256(payload.encode("utf-8")).hexdigest() != digest:
            raise ValueError("history digest does not reconstruct")
        points.append(json.loads(payload))
    return points


def make_history_point(binding: CrossChainIdentityBinding, intelligence: dict, observed_at: str) -> dict | None:
    """Only an available premium earns a numeric history point."""
    if binding.economic_asset_uid is None or binding.external_asset_key is None:
        return None
    premium = intelligence["reference_premium"]
    if premium["state"] != "AVAILABLE" or premium["value_bps"] is None:
        return None
    gap = intelligence["execution_gap"]
    execution = intelligence["execution"]
    gap_available = gap["state"] == "AVAILABLE"
    return {
        "economic_asset_uid": binding.economic_asset_uid,
        "asset_key": binding.external_asset_key.canonical_id,
        "identity_source": binding.authority_source,
        "identity_observed_at": binding.observed_at.isoformat() if binding.observed_at else None,
        "observed_at": observed_at,
        "state": premium["state"],
        "robinhood_basis": intelligence["robinhood_basis"],
        "independent_token_reference": intelligence["independent_token_reference"],
        "reference_premium_bps": premium["value_bps"],
        "premium_sources": premium["sources"],
        "premium_evidence_at": premium["observed_at"],
        "execution_price_usd_per_token": execution["effective_price_usd_per_token"] if gap_available else None,
        "execution_source": execution["provider"] if gap_available else None,
        "execution_observed_at": execution["observed_at"] if gap_available else None,
        "execution_impact_bps": gap["execution_impact_bps"] if gap_available else None,
        "total_execution_gap_bps": gap["effective_gap_bps"] if gap_available else None,
        "execution_state": gap["state"],
    }


def make_r_live_history_point(snapshot: AuthoritySnapshot,
                              observation: OnchainReferenceObservation) -> dict | None:
    """Use the existing B1.3 digest/append-only history for exact R-LIVE evidence."""
    if (observation.state is not AuthorityState.AVAILABLE
            or snapshot.premium.state is not AuthorityState.AVAILABLE
            or snapshot.premium.value_bps is None
            or snapshot.economic_asset_uid != observation.registry_asset_uid
            or snapshot.canonical_token != observation.asset_key):
        return None
    assert observation.observed_at is not None
    return {
        "economic_asset_uid": snapshot.economic_asset_uid,
        "asset_key": snapshot.canonical_token.canonical_id,
        "identity_source": snapshot.registry_source,
        "identity_observed_at": snapshot.registry_observed_at.isoformat() if snapshot.registry_observed_at else None,
        "observed_at": observation.observed_at.isoformat(),
        "collected_at": _source_collection_time(dict(observation.evidence)),
        "state": snapshot.premium.state.value,
        "robinhood_basis": {
            "price_usd_per_token": str(snapshot.underlying.price_usd_per_token),
            "source": snapshot.underlying.source,
            "observed_at": snapshot.underlying.observed_at.isoformat() if snapshot.underlying.observed_at else None,
        },
        "independent_token_reference": observation.to_evidence_dict(),
        "reference_premium_bps": str(snapshot.premium.value_bps),
        "premium_sources": list(snapshot.premium.sources),
        "premium_evidence_at": [value.isoformat() for value in snapshot.premium.observed_at],
        "execution_state": snapshot.execution.state.value,
    }


def _canonical(point: dict) -> str:
    return json.dumps(point, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _r_live_source_identity(point: dict) -> str:
    """Retrieval time is not a new source observation of the same evidence."""
    stable = json.loads(_canonical(point))
    stable.pop("collected_at", None)
    stable["independent_token_reference"]["evidence"].pop("retrievedAt", None)
    return _canonical(stable)


class BnbIntelligenceHistoryStore:
    """Dedicated durable, append-only ledger; no update/delete operations."""

    def __init__(self, path: str | None = None, *, allowed_chain_id: int = 56) -> None:
        if allowed_chain_id not in (56, 4663):
            raise ValueError("history chain must be BNB or Robinhood")
        self.allowed_chain_id = allowed_chain_id
        location = path or os.getenv("RADAR_BNB_INTELLIGENCE_DB_PATH", DEFAULT_DB_PATH)
        if location != ":memory:":
            Path(location).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(location, timeout=30, isolation_level=None, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA busy_timeout=30000")
        self._conn.executescript("""
            CREATE TABLE IF NOT EXISTS bnb_intelligence_history (
                digest TEXT PRIMARY KEY,
                economic_asset_uid TEXT NOT NULL,
                asset_key TEXT NOT NULL,
                observed_at TEXT NOT NULL,
                payload TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_bnb_intelligence_identity_time
                ON bnb_intelligence_history(economic_asset_uid, asset_key, observed_at);
            CREATE INDEX IF NOT EXISTS idx_bnb_r_live_identity_collection_time
                ON bnb_intelligence_history(
                    economic_asset_uid, asset_key,
                    json_extract(payload, '$.collected_at'));
        """)
        self._lock = RLock()

    def put(self, point: dict) -> str:
        payload = _canonical(point)
        digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
        uid = normalize_asset_uid(point["economic_asset_uid"])
        key = point["asset_key"]
        observed_at = datetime.fromisoformat(point["observed_at"])
        if (not isinstance(key, str) or not key.startswith(f"{self.allowed_chain_id}:")
                or point["state"] != "AVAILABLE" or point["reference_premium_bps"] is None):
            raise ValueError("history requires available exact premium evidence")
        if observed_at.tzinfo is None or observed_at.utcoffset() is None:
            raise ValueError("history observation must be timezone-aware")
        with self._lock:
            try:
                self._conn.execute(
                    "INSERT INTO bnb_intelligence_history VALUES (?, ?, ?, ?, ?)",
                    (digest, uid, key, point["observed_at"], payload),
                )
            except sqlite3.IntegrityError:
                existing = self._conn.execute(
                    "SELECT payload FROM bnb_intelligence_history WHERE digest = ?", (digest,),
                ).fetchone()
                if existing is None or existing["payload"] != payload:
                    raise ValueError("history digest conflicts with existing evidence") from None
        return digest

    def put_r_live(self, point: dict) -> str:
        """Append once per exact source/basis evidence, even after a later retrieval."""
        if self.allowed_chain_id != 4663:
            raise ValueError("R_LIVE_REQUIRES_ROBINHOOD_HISTORY")
        identity = _r_live_source_identity(point)
        uid = normalize_asset_uid(point["economic_asset_uid"])
        key = point["asset_key"]
        with self._lock:
            # Serialize the read/append across independent collector processes.
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                rows = self._conn.execute(
                    "SELECT digest, payload FROM bnb_intelligence_history "
                    "WHERE economic_asset_uid = ? AND asset_key = ? AND observed_at = ?",
                    (uid, key, point["observed_at"]),
                ).fetchall()
                for row in rows:
                    if hashlib.sha256(row["payload"].encode("utf-8")).hexdigest() != row["digest"]:
                        raise ValueError("history digest does not reconstruct")
                    existing = json.loads(row["payload"])
                    if ("independent_token_reference" in existing
                            and _r_live_source_identity(existing) == identity):
                        self._conn.execute("COMMIT")
                        return row["digest"]
                digest = self.put(point)
                self._conn.execute("COMMIT")
                return digest
            except Exception:
                self._conn.execute("ROLLBACK")
                raise

    def read(self, uid: str, key: AssetKey, *, limit: int = 30) -> list[dict]:
        if key.chain_id != self.allowed_chain_id or not 1 <= limit <= 100:
            raise ValueError("exact chain key and bounded limit required")
        with self._lock:
            rows = self._conn.execute(
                "SELECT digest, payload FROM bnb_intelligence_history "
                "WHERE economic_asset_uid = ? AND asset_key = ? "
                "ORDER BY observed_at DESC, digest DESC LIMIT ?",
                (normalize_asset_uid(uid), key.canonical_id, limit),
            ).fetchall()
        result = []
        for row in rows:
            if hashlib.sha256(row["payload"].encode("utf-8")).hexdigest() != row["digest"]:
                raise ValueError("history digest does not reconstruct")
            result.append(json.loads(row["payload"]))
        return result

    def close(self) -> None:
        with self._lock:
            self._conn.close()
