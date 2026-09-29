/**
 * R-LIVE landing table client-side data population.
 *
 * Read-only: fetches reference data from the AAPL snapshot endpoint and
 * populates the AAPL row in the R-LIVE landing table.
 * Never writes R-LIVE history. Never modifies authority state.
 * STALE/UNAVAILABLE numeric values are suppressed (missing != 0).
 */
(function () {
  "use strict";

  var SNAP_URL = "/radar/crypto/rwa/r-live/aapl/snapshot";

  function fmt_age(secs) {
    if (secs == null) return "—";
    if (secs < 60) return secs + "s ago";
    if (secs < 3600) return Math.floor(secs / 60) + "m ago";
    return Math.floor(secs / 3600) + "h ago";
  }

  function fmt_bps(bps_str) {
    if (bps_str == null) return "—";
    var bps = parseFloat(bps_str);
    if (isNaN(bps)) return "—";
    return (bps >= 0 ? "+" : "") + bps.toFixed(1) + " bps";
  }

  function set_badge(el, state) {
    if (!el) return;
    el.className = "rlive-badge rlive-badge--" + state.toLowerCase();
    el.textContent = state;
  }

  function populate_row(row_el, data) {
    var state = (data.state || "UNAVAILABLE").toUpperCase();
    var status_el = row_el.querySelector("[data-field='status']") ||
                    row_el.querySelector("[data-testid^='rlive-status-']");
    // status badge is in its own td — find by data-testid pattern
    var badge_el = row_el.querySelector("[data-testid^='rlive-status-']");
    set_badge(badge_el, state);

    // Only populate numeric cells when AVAILABLE — missing != 0.
    if (state !== "AVAILABLE") {
      ["reference_price", "premium_bps", "change_1h", "change_24h"].forEach(function (f) {
        var cell = row_el.querySelector("[data-field='" + f + "']");
        if (cell) cell.textContent = "—";
      });
      var fresh_cell = row_el.querySelector("[data-field='freshness']");
      if (fresh_cell) fresh_cell.textContent = state === "STALE" ? "STALE" : "—";
      return;
    }

    // Reference price
    var ref = data.reference;
    var ref_cell = row_el.querySelector("[data-field='reference_price']");
    if (ref_cell && ref && ref.price_usd_per_token != null) {
      ref_cell.textContent = "$" + parseFloat(ref.price_usd_per_token).toFixed(4);
    } else if (ref_cell) {
      ref_cell.textContent = "—";
    }

    // Premium/discount in bps
    var prem_cell = row_el.querySelector("[data-field='premium_bps']");
    if (prem_cell) {
      var prem = data.reference_premium;
      prem_cell.textContent = (prem && prem.value_bps != null)
        ? fmt_bps(prem.value_bps)
        : "—";
    }

    // 1h / 24h changes are not available from snapshot — suppress.
    ["change_1h", "change_24h"].forEach(function (f) {
      var cell = row_el.querySelector("[data-field='" + f + "']");
      if (cell) cell.textContent = "—";
    });

    // Freshness
    var fresh_cell = row_el.querySelector("[data-field='freshness']");
    if (fresh_cell) {
      fresh_cell.textContent = fmt_age(data.observation_age_seconds);
    }
  }

  function init() {
    var table = document.querySelector("[data-testid='rlive-table']");
    if (!table) return;

    // Find approved rows (those with data-asset-uid set).
    var aapl_row = table.querySelector("[data-asset-uid='AAPL']");
    if (!aapl_row) return;

    fetch(SNAP_URL)
      .then(function (r) { return r.json(); })
      .then(function (data) { populate_row(aapl_row, data); })
      .catch(function () {
        // On any network/parse error, show UNAVAILABLE — never show stale numeric values.
        var badge = aapl_row.querySelector("[data-testid^='rlive-status-']");
        set_badge(badge, "UNAVAILABLE");
      });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
