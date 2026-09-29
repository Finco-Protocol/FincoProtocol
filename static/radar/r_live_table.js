/**
 * R-LIVE landing table client-side data population.
 *
 * One streaming current request plus one read-only historical summary request.
 * Identity authority is canonical_id from registry-rendered rows, never symbol.
 *
 * Read-only: never writes R-LIVE history, never modifies authority state.
 * STALE/UNAVAILABLE numeric values are suppressed (missing != 0).
 * No raw innerHTML used for API response data.
 */
(function () {
  "use strict";

  function fmt_age(secs) {
    if (typeof secs !== "number" || !isFinite(secs) || secs < 0) return null;
    if (secs < 60) return secs + "s";
    if (secs < 3600) return Math.floor(secs / 60) + "m";
    return Math.floor(secs / 3600) + "h";
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

  function set_historical_cell(row_el, field, text, collected_at) {
    var cell = row_el.querySelector("[data-field='" + field + "']");
    if (!cell || text == null) return;
    cell.textContent = "";
    var value = document.createElement("span");
    value.className = "rlive-historical-value";
    value.textContent = text;
    var note = document.createElement("small");
    note.className = "rlive-historical-label";
    var time = collected_at ? new Date(collected_at).getTime() : NaN;
    var age = isFinite(time) ? fmt_age(Math.max(0, Math.floor((Date.now() - time) / 1000))) : null;
    note.textContent = "HISTORICAL · Last available" + (age ? " · " + age + " ago" : " · time unavailable");
    cell.appendChild(value);
    cell.appendChild(note);
  }

  function set_badge(row_el, state) {
    var badge = row_el.querySelector("[data-testid^='rlive-status-']");
    if (!badge) return;
    badge.className = "rlive-badge rlive-badge--" + state.toLowerCase();
    badge.textContent = state;
  }

  function fmt_range(summary) {
    // The server has checked the complete bounded collection-time window.
    if (!summary || summary.state !== "AVAILABLE" || summary.observation_count < 2) return null;
    var lo = parseFloat(summary.low_bps);
    var hi = parseFloat(summary.high_bps);
    if (!isFinite(lo) || !isFinite(hi)) return null;
    var sign = function(v) { return (v >= 0 ? "+" : "") + v.toFixed(1); };
    return sign(lo) + " / " + sign(hi) + " bps";
  }

  function populate_row(row_el, snap_data, ranges) {
    // snap_data is the `data` sub-object from /api/v1.1/radar/r-live/{uid}
    // ranges are read-only B1.3 summaries and never determine current state.
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

    // Display-only fallback for an exact-key STALE market. Never change the
    // current badge or feed historical values into current calculations.
    var last = ranges && ranges.last_available;
    if (snap_state === "STALE" && last) {
      set_historical_cell(row_el, "basis_price", fmt_usd(last.basis_price_usd_per_token), last.collected_at);
      set_historical_cell(row_el, "reference_price", fmt_usd(last.token_price_usd_per_token), last.collected_at);
      set_historical_cell(row_el, "premium_bps", fmt_bps(last.premium_bps), last.collected_at);
    }

    set_cell(row_el, "range_1h", fmt_range(ranges && ranges.range_1h));
    set_cell(row_el, "range_24h", fmt_range(ranges && ranges.range_24h));

    // Market activity and oracle ages are distinct. observed_at is the
    // conservative oldest evidence timestamp, not market-activity age.
    var freshness_txt = null;
    var freshness = snap_data.freshness;
    if (freshness) {
      var market = fmt_age(freshness.market_activity_age_seconds);
      var oracle = fmt_age(freshness.quote_feed_age_seconds);
      if (market !== null && oracle !== null) {
        freshness_txt = "Market " + market + " · Oracle " + oracle;
      }
    }
    set_cell(row_el, "freshness", freshness_txt);
  }

  function init() {
    var table = document.querySelector("[data-testid='rlive-table']");
    if (!table) return;
    var rows = table.querySelectorAll("[data-canonical-id]");
    var byId = Object.create(null), snapshots = Object.create(null);
    var history = Object.create(null);
    for (var i = 0; i < rows.length; i++) {
      byId[rows[i].getAttribute("data-canonical-id")] = rows[i];
    }

    function sort_rows() {
      var body = table.querySelector("tbody");
      if (!body) return;
      var ordered = Array.prototype.slice.call(rows);
      var rank = function(row) {
        var snap = snapshots[row.getAttribute("data-canonical-id")];
        if (!snap) return 1; // LOADING is UI-only, not an authority state.
        return snap.state === "AVAILABLE" ? 0 : snap.state === "STALE" ? 2 : 3;
      };
      ordered.sort(function(a, b) {
        var ra = rank(a), rb = rank(b);
        if (ra !== rb) return ra - rb;
        if (ra === 0) {
          var premium_a = snapshots[a.getAttribute("data-canonical-id")].b1_0_premium;
          var premium_b = snapshots[b.getAttribute("data-canonical-id")].b1_0_premium;
          var pa = premium_a ? Math.abs(parseFloat(premium_a.value_bps)) : NaN;
          var pb = premium_b ? Math.abs(parseFloat(premium_b.value_bps)) : NaN;
          if (isFinite(pa) && isFinite(pb) && pa !== pb) return pb - pa;
        }
        return a.getAttribute("data-original-order") - b.getAttribute("data-original-order");
      });
      ordered.forEach(function(row) { body.appendChild(row); });
    }
    for (var j = 0; j < rows.length; j++) rows[j].setAttribute("data-original-order", j);

    fetch("/api/v1.1/radar/r-live/history/ranges", {cache: "no-store"})
      .then(function(r) { return r.ok ? r.json() : null; })
      .then(function(env) {
        history = (env && env.state === "AVAILABLE" && env.data && env.data.assets)
          ? env.data.assets : Object.create(null);
        Object.keys(snapshots).forEach(function(key) {
          populate_row(byId[key], snapshots[key], history[key]);
        });
      }).catch(function() { /* Ranges remain unavailable, never zero. */ });

    fetch("/api/v1.1/radar/r-live/current", {cache: "no-store"})
      .then(function(response) {
        if (!response.ok || !response.body) throw new Error("CURRENT_TRANSPORT_ERROR");
        var reader = response.body.getReader(), decoder = new TextDecoder();
        var buffer = "";
        function consume(line) {
          if (!line.trim()) return;
          var item = JSON.parse(line);
          var row = byId[item.canonical_id];
          if (!row) return;
          var snap = Object.assign({state: item.state}, item.data || {});
          snapshots[item.canonical_id] = snap;
          populate_row(row, snap, history[item.canonical_id]);
          sort_rows();
        }
        function pump() {
          return reader.read().then(function(chunk) {
            if (chunk.done) {
              buffer += decoder.decode();
              if (buffer.trim()) consume(buffer);
              Object.keys(byId).forEach(function(key) {
                if (!snapshots[key]) {
                  snapshots[key] = {state: "UNAVAILABLE", reason: "CURRENT_RESPONSE_INCOMPLETE"};
                  populate_row(byId[key], snapshots[key], history[key]);
                }
              });
              sort_rows();
              return;
            }
            buffer += decoder.decode(chunk.value, {stream: true});
            var newline;
            while ((newline = buffer.indexOf("\n")) !== -1) {
              consume(buffer.slice(0, newline));
              buffer = buffer.slice(newline + 1);
            }
            return pump();
          });
        }
        return pump();
      }).catch(function() {
        // Loading is neutral until transport actually fails. Current numeric
        // values are never supplied by historical ranges.
        Object.keys(byId).forEach(function(key) {
          if (!snapshots[key]) {
            snapshots[key] = {state: "UNAVAILABLE", reason: "CURRENT_TRANSPORT_ERROR"};
            populate_row(byId[key], snapshots[key], history[key]);
            byId[key].setAttribute("data-transport-error", "CURRENT_TRANSPORT_ERROR");
          }
        });
        sort_rows();
      });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
