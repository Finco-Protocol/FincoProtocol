/**
 * R-LIVE landing table client-side data population.
 *
 * Makes exactly TWO requests per page load:
 *   1. GET /api/v1.1/radar/r-live/current  — NDJSON stream; rows populate as each
 *      asset completes (completion order, not registry order).
 *   2. GET /api/v1.1/radar/r-live/history/ranges  — bulk 1h/24h ranges for all
 *      approved assets; applies after the stream finishes.
 *
 * Identity authority is canonical_id from the row's data-canonical-id attribute —
 * never resolved from symbol or ticker.
 *
 * Read-only: never writes R-LIVE history, never modifies authority state.
 * STALE/UNAVAILABLE numeric values are suppressed (missing != 0).
 * No raw innerHTML used for API response data.
 */
(function () {
  "use strict";

  function fmt_age(secs) {
    if (secs == null) return "—";
    if (secs < 60) return secs + "s ago";
    if (secs < 3600) return Math.floor(secs / 60) + "m ago";
    return Math.floor(secs / 3600) + "h ago";
  }

  function fmt_bps(bps_str) {
    if (bps_str == null) return null;
    var bps = parseFloat(bps_str);
    if (isNaN(bps)) return null;
    return (bps >= 0 ? "+" : "") + bps.toFixed(1) + " bps";
  }

  function fmt_usd(price_str) {
    if (price_str == null) return null;
    var n = parseFloat(price_str);
    if (isNaN(n)) return null;
    return "$" + n.toFixed(4);
  }

  function set_cell(row_el, field, text) {
    var cell = row_el.querySelector("[data-field='" + field + "']");
    if (!cell) return;
    cell.textContent = text != null ? text : "—";
  }

  function set_badge(row_el, state) {
    var badge = row_el.querySelector("[data-testid^='rlive-status-']");
    if (!badge) return;
    badge.className = "rlive-badge rlive-badge--" + state.toLowerCase();
    badge.textContent = state;
  }

  function populate_row(row_el, snap_data) {
    // snap_data must have .state at top level (merged before calling).
    var snap_state = (snap_data.state || "UNAVAILABLE").toUpperCase();
    set_badge(row_el, snap_state);

    var is_current = (snap_state === "AVAILABLE");

    // Economic basis (numeric) — robinhood_basis.price_usd_per_token
    var basis = snap_data.robinhood_basis;
    var basis_txt = null;
    if (is_current && basis) basis_txt = fmt_usd(basis.price_usd_per_token);
    set_cell(row_el, "basis_price", basis_txt);

    // Independent token reference
    var token_ref = snap_data.token_reference;
    var ref_txt = null;
    if (is_current && token_ref) ref_txt = fmt_usd(token_ref.price_usd_per_token);
    set_cell(row_el, "reference_price", ref_txt);

    // Premium/discount
    var prem = snap_data.b1_0_premium;
    var prem_txt = null;
    if (is_current && prem) prem_txt = fmt_bps(prem.value_bps);
    set_cell(row_el, "premium_bps", prem_txt);

    // Freshness — observed_at from snapshot
    var freshness_txt = null;
    if (snap_data.observed_at) {
      var age_ms = Date.now() - new Date(snap_data.observed_at).getTime();
      var age_s = Math.round(age_ms / 1000);
      freshness_txt = fmt_age(age_s);
    }
    set_cell(row_el, "freshness", freshness_txt);
  }

  function apply_ranges(row_map, ranges) {
    // ranges: {canonical_id: {range_1h, range_24h}}
    for (var id in ranges) {
      var row_el = row_map[id];
      if (!row_el) continue;
      var r = ranges[id];
      if (r && r.range_1h != null) set_cell(row_el, "range_1h", r.range_1h);
      if (r && r.range_24h != null) set_cell(row_el, "range_24h", r.range_24h);
    }
  }

  function init() {
    var table = document.querySelector("[data-testid='rlive-table']");
    if (!table) return;

    // Build canonical_id → row element map
    var row_map = {};
    var rows = table.querySelectorAll("[data-canonical-id]");
    for (var i = 0; i < rows.length; i++) {
      row_map[rows[i].getAttribute("data-canonical-id")] = rows[i];
    }

    // Request 1: batch ranges (parallel, non-streaming)
    var ranges_promise = fetch("/api/v1.1/radar/r-live/history/ranges")
      .then(function(r) { return r.ok ? r.json() : null; })
      .catch(function() { return null; });

    // Request 2: current NDJSON stream — populates rows as assets complete
    fetch("/api/v1.1/radar/r-live/current")
      .then(function(response) {
        if (!response.ok || !response.body) {
          for (var id in row_map) { set_badge(row_map[id], "UNAVAILABLE"); }
          return ranges_promise;
        }

        var reader = response.body.getReader();
        var decoder = new TextDecoder();
        var buffer = "";

        function pump() {
          return reader.read().then(function(chunk) {
            if (chunk.done) return;
            buffer += decoder.decode(chunk.value, {stream: true});
            var lines = buffer.split("\n");
            buffer = lines.pop(); // incomplete last line stays in buffer
            for (var i = 0; i < lines.length; i++) {
              var line = lines[i].trim();
              if (!line) continue;
              try {
                var row_data = JSON.parse(line);
                var canonical_id = row_data.canonical_id;
                var row_el = row_map[canonical_id];
                if (!row_el) continue;
                // Merge top-level state into data for populate_row contract
                var snap_data = row_data.data || {};
                if (!snap_data.state && row_data.state) {
                  snap_data = Object.assign({state: row_data.state}, snap_data);
                }
                populate_row(row_el, snap_data);
              } catch (e) { /* skip malformed line */ }
            }
            return pump();
          });
        }

        return pump().then(function() { return ranges_promise; });
      })
      .then(function(ranges_env) {
        if (!ranges_env || !ranges_env.data || !ranges_env.data.ranges) return;
        apply_ranges(row_map, ranges_env.data.ranges);
      })
      .catch(function() {
        for (var id in row_map) { set_badge(row_map[id], "UNAVAILABLE"); }
      });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
