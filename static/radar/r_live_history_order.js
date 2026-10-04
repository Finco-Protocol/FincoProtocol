/*
 * R-LIVE history presentation ordering (presentation only).
 *
 * The canonical history API returns records without a display-order promise. Two surfaces need two
 * DIFFERENT, explicit orders:
 *
 *   tableOrder(points)  -> NEWEST first   (inspection table: the latest observation is on top)
 *   chartOrder(points)  -> OLDEST first   (natural left-to-right time axis)
 *
 * Time key (canonical timestamps only, never the browser clock, never mutated):
 *   1. collected_at when it parses
 *   2. otherwise observed_at when it parses
 *   3. otherwise the point has NO time key and sorts LAST on both surfaces
 * Equal keys keep a stable, deterministic order from the original input index:
 *   table: input order is preserved; chart: input order is reversed (the API is newest-first, so the
 *   chart's chronological axis reads oldest -> newest among equal times).
 * Economic values are never touched; the helpers return the same point objects in a new array.
 */
(function (root) {
  "use strict";

  function timeKey(point) {
    var collected = Date.parse((point && point.collected_at) || "");
    if (!isNaN(collected)) return collected;
    var observed = Date.parse((point && point.observed_at) || "");
    return isNaN(observed) ? null : observed;
  }

  function decorate(points) {
    return (points || []).map(function (point, index) {
      return { point: point, index: index, time: timeKey(point) };
    });
  }

  // Total order (transitive): points without a time key always go last.
  function ordered(points, newestFirst) {
    var rows = decorate(points);
    rows.sort(function (a, b) {
      var aMissing = a.time === null, bMissing = b.time === null;
      if (aMissing !== bMissing) return aMissing ? 1 : -1;
      if (!aMissing && a.time !== b.time) return newestFirst ? b.time - a.time : a.time - b.time;
      return newestFirst ? a.index - b.index : b.index - a.index;
    });
    return rows.map(function (row) { return row.point; });
  }

  var api = {
    timeKey: timeKey,
    tableOrder: function (points) { return ordered(points, true); },
    chartOrder: function (points) { return ordered(points, false); }
  };

  if (typeof module !== "undefined" && module.exports) module.exports = api;
  root.FincoRLiveHistoryOrder = api;
})(typeof window !== "undefined" ? window : this);
