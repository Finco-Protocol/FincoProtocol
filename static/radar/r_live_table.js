/**
 * R-LIVE landing table client-side data population — SNAPSHOT FIRST,
 * CONTINUOUSLY FRESH.
 *
 * One instant latest-snapshot request (read-only projection; ZERO live
 * chain acquisition on this path) plus one read-only historical summary
 * request. The table then keeps polling the SNAPSHOT endpoint at a fixed
 * cadence for as long as the page is active — regardless of whether the
 * current state is AVAILABLE, STALE or UNAVAILABLE. A stale or
 * unavailable row can become AVAILABLE after a later background-collector
 * cycle; state controls presentation only, never whether the browser
 * keeps checking the canonical snapshot. Polling never triggers
 * blockchain acquisition.
 * Identity authority is canonical_id from registry-rendered rows, never symbol.
 *
 * Read-only: never writes R-LIVE history, never modifies authority state.
 * STALE/UNAVAILABLE numeric values are suppressed (missing != 0).
 * API response data is only ever assigned via textContent — no raw HTML
 * injection path exists in this script.
 */
(function () {
  "use strict";

  var SNAPSHOT_URL = "/api/v1.1/radar/r-live/snapshot";
  var POLL_INTERVAL_MS = 20000;

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

  function chart_cell(row_el, field, cfg) {
    // Fill one chart container (sparkline / range-bar) from canonical data and
    // render via the shared zero-dependency renderer. cfg=null → typed empty.
    var box = row_el.querySelector("[data-field='" + field + "'] [data-chart-type]");
    if (!box || !window.FoCharts) return;
    box.classList.remove("fo-power-skeleton", "fo-power-skeleton--block");
    if (!cfg) { box.textContent = "—"; return; }
    if (cfg.attrs) {
      Object.keys(cfg.attrs).forEach(function (key) { box.dataset[key] = cfg.attrs[key]; });
    }
    window.FoCharts.renderElement(box);
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

  function mark_historical(row_el, fields) {
    // When the CURRENT state is not AVAILABLE, stored 24h trend / range visuals are legitimate history but must not read as
    // current. Presentation only: no value is removed, hidden or recomputed.
    fields.forEach(function (field) {
      var cell = row_el.querySelector("[data-field='" + field + "']");
      if (!cell) return;
      var previous = cell.querySelector(".rlive-historical-flag");
      if (previous) previous.remove();
      var tag = document.createElement("small");
      tag.className = "rlive-historical-label rlive-historical-flag";
      tag.style.display = "block";
      tag.textContent = "Historical";
      cell.appendChild(tag);
    });
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

  function populate_row(row_el, snap_data, ranges, read_time_ages) {
    // snap_data is the `data` sub-object of one snapshot row (identical
    // shape to the /current authority payload); read_time_ages carries the
    // read-time re-evaluated ages from the snapshot view.
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
    set_cell(row_el, "range_24h_text", fmt_range(ranges && ranges.range_24h));

    // Terminal visuals — pure display of the SAME canonical data:
    // trend sparkline from the bounded verified 24h series, and the current
    // position inside the canonical 24h range. No extra requests, no
    // provider calls, gaps stay gaps.
    var series = ranges && Array.isArray(ranges.series_24h) ? ranges.series_24h : null;
    if (series && series.length >= 2) {
      chart_cell(row_el, "trend", { attrs: { points: JSON.stringify(series.map(function (p) {
        return { t: p.collected_at || "", v: p.premium_bps };
      })) } });
    } else {
      chart_cell(row_el, "trend", null);
    }
    var range24 = ranges && ranges.range_24h;
    var current_bps = (is_current && snap_data.b1_0_premium) ? parseFloat(snap_data.b1_0_premium.value_bps) : NaN;
    if (range24 && range24.state === "AVAILABLE" && isFinite(current_bps)) {
      chart_cell(row_el, "range_24h", { attrs: {
        low: range24.low_bps, high: range24.high_bps, current: String(current_bps),
      } });
    } else {
      chart_cell(row_el, "range_24h", null);
    }

    if (!is_current) mark_historical(row_el, ["trend", "range_1h", "range_24h"]);

    // Market activity and oracle ages are distinct. Read-time ages from the
    // snapshot view are preferred; observed_at is the conservative oldest
    // evidence timestamp, not market-activity age.
    var freshness_txt = null;
    var freshness = (read_time_ages && read_time_ages.market_activity_age_seconds != null)
      ? read_time_ages : snap_data.freshness;
    if (freshness) {
      var market = fmt_age(freshness.market_activity_age_seconds);
      var oracle = fmt_age(freshness.quote_feed_age_seconds);
      if (market !== null && oracle !== null) {
        freshness_txt = "Market " + market + " · Oracle " + oracle;
      }
    }
    set_cell(row_el, "freshness", freshness_txt);
    if (is_current && freshness_txt) {
      // AVAILABLE is only ever assigned when every leg is within its reviewed freshness policy.
      var fresh_cell = row_el.querySelector("[data-field='freshness']");
      if (fresh_cell) {
        var policy_note = document.createElement("small");
        policy_note.style.display = "block";
        policy_note.textContent = "each leg within its source freshness policy";
        fresh_cell.appendChild(policy_note);
      }
    }
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
      }).catch(function() {
        // Ranges remain unavailable, never zero. Visual cells resolve to the
        // typed empty state — the skeleton must never shimmer forever.
        history = Object.create(null);
        Object.keys(snapshots).forEach(function(key) {
          populate_row(byId[key], snapshots[key], undefined);
        });
      });

    // One instant snapshot read, then CONTINUOUS snapshot polling while the
    // page is active. Polling is state-independent: it continues through
    // AVAILABLE, STALE and UNAVAILABLE and never stops once warm. The
    // snapshot endpoint is a network-free canonical read — polling never
    // triggers blockchain acquisition; the background collector is the only
    // source-refresh path.
    var poll_timer = null;

    function poll_tick() {
      // Skip only when the page is not visible; the cadence continues for
      // as long as the page is active.
      if (typeof document !== "undefined" && document.hidden) return;
      refresh_snapshot();
    }

    function ensure_polling() {
      if (!poll_timer) poll_timer = setInterval(poll_tick, POLL_INTERVAL_MS);
    }

    function apply_snapshot(payload) {
      var rows_data = (payload && payload.rows) || [];
      rows_data.forEach(function(view_row) {
        var row = byId[view_row.canonical_id];
        if (!row) return;
        var snap = Object.assign({state: view_row.state}, view_row.data || {});
        snapshots[view_row.canonical_id] = snap;
        populate_row(row, snap, history[view_row.canonical_id], view_row.read_time_ages);
      });
      sort_rows();
    }

    function refresh_snapshot() {
      return fetch(SNAPSHOT_URL, {cache: "no-store"})
        .then(function(r) { return r.ok ? r.json() : null; })
        .then(function(env) {
          if (!env) throw new Error("SNAPSHOT_TRANSPORT_ERROR");
          if (env.state === "INITIALIZING") {
            ensure_polling();
            return; // stay neutral-loading; the collector fills the snapshot
          }
          var banner = document.querySelector("[data-testid='rlive-initializing']");
          if (banner && banner.parentNode) banner.parentNode.removeChild(banner);
          apply_snapshot(env.data || {});
          ensure_polling(); // continuous freshness — never stop once warm
        })
        .catch(function() {
          // Loading is neutral until transport actually fails. Current numeric
          // values are never supplied by historical ranges; snapshot retries
          // continue without ever falling back to a live acquisition.
          ensure_polling();
          Object.keys(byId).forEach(function(key) {
            if (!snapshots[key]) {
              byId[key].setAttribute("data-transport-error", "SNAPSHOT_TRANSPORT_ERROR");
            }
          });
        });
    }

    refresh_snapshot();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
