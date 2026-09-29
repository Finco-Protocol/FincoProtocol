/**
 * R-LIVE landing table client-side data population.
 *
 * Fetches each approved asset's snapshot from /api/v1.1/radar/r-live/{canonical_id}
 * and populates the row. Identity authority is canonical_id from the row's
 * data-canonical-id attribute — never resolved from symbol or ticker.
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

  function fmt_range(points, hours) {
    // Compute the bps range over the last `hours` from history points.
    // Canonical field: reference_premium_bps (not premium_bps).
    // Returns "lo / hi bps" string or null if < 2 valid observations in window.
    var cutoff = Date.now() - hours * 3600 * 1000;
    var vals = [];
    for (var i = 0; i < points.length; i++) {
      var p = points[i];
      if (p.reference_premium_bps == null) continue;
      var t = p.observed_at ? new Date(p.observed_at).getTime() : 0;
      if (t < cutoff) continue;
      var v = parseFloat(p.reference_premium_bps);
      if (!isNaN(v)) vals.push(v);
    }
    if (vals.length < 2) return null;
    var lo = Math.min.apply(null, vals);
    var hi = Math.max.apply(null, vals);
    var sign = function(v) { return (v >= 0 ? "+" : "") + v.toFixed(1); };
    return sign(lo) + " / " + sign(hi) + " bps";
  }

  function populate_row(row_el, snap_data, hist_points) {
    // snap_data is the `data` sub-object from /api/v1.1/radar/r-live/{uid}
    // hist_points is the array from data.points in the history response
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

    // 1h / 24h ranges from B1.3 history
    if (hist_points && hist_points.length) {
      set_cell(row_el, "range_1h", fmt_range(hist_points, 1));
      set_cell(row_el, "range_24h", fmt_range(hist_points, 24));
    }

    // Freshness — observed_at from snapshot
    var freshness_txt = null;
    if (snap_data.observed_at) {
      var age_ms = Date.now() - new Date(snap_data.observed_at).getTime();
      var age_s = Math.round(age_ms / 1000);
      freshness_txt = fmt_age(age_s);
    }
    set_cell(row_el, "freshness", freshness_txt);
  }

  function load_row(row_el) {
    var canonical_id = row_el.getAttribute("data-canonical-id");
    if (!canonical_id) return;

    var snap_url = "/api/v1.1/radar/r-live/" + encodeURIComponent(canonical_id);
    var hist_url = "/api/v1.1/radar/r-live/" + encodeURIComponent(canonical_id) + "/history?limit=100";

    Promise.all([
      fetch(snap_url).then(function(r) {
        if (!r.ok) { throw new Error("TRANSPORT_ERROR_" + r.status); }
        return r.json();
      }),
      fetch(hist_url).then(function(r) {
        if (!r.ok) { return null; }
        return r.json();
      }).catch(function() { return null; })
    ]).then(function(results) {
      var snap_env = results[0];
      var hist_env = results[1];
      var snap_data = (snap_env && snap_env.data) ? snap_env.data : {};
      // Wrap state into data if top-level
      if (!snap_data.state && snap_env && snap_env.state) {
        snap_data = Object.assign({state: snap_env.state}, snap_data);
      }
      var hist_points = (hist_env && hist_env.data && Array.isArray(hist_env.data.points))
        ? hist_env.data.points : [];
      populate_row(row_el, snap_data, hist_points);
    }).catch(function(err) {
      set_badge(row_el, "UNAVAILABLE");
      if (err && err.message && err.message.indexOf("TRANSPORT_ERROR_") === 0) {
        row_el.setAttribute("data-transport-error", err.message);
      }
    });
  }

  function init() {
    var table = document.querySelector("[data-testid='rlive-table']");
    if (!table) return;
    var rows = table.querySelectorAll("[data-canonical-id]");
    for (var i = 0; i < rows.length; i++) {
      load_row(rows[i]);
    }
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
