/**
 * BNB RWA observation filters — exact definitions, presentation only.
 *
 *   ALL OBSERVED : every valid observed RWA market row (the table itself).
 *   BOUND        : rows where an exact source-proven economic identity
 *                  binding to the canonical registry exists
 *                  (data-cap-bound="1" — derived ONLY from authority
 *                  evidence, never from ticker/symbol/name matching).
 *   ACTIONABLE   : rows where a separately defined execution capability
 *                  actually exists (data-cap-actionable="1"). A BNB
 *                  contract alone NEVER classifies a row as actionable.
 *
 * Read-only UI: no fetch, no writes, no identity inference.
 */
(function () {
  "use strict";

  var FILTERS = {
    all: function () { return true; },
    bound: function (row) { return row.getAttribute("data-cap-bound") === "1"; },
    actionable: function (row) { return row.getAttribute("data-cap-actionable") === "1"; },
  };

  function init() {
    var bar = document.querySelector("[data-testid='bnb-filter-bar']");
    var table = document.querySelector("[data-testid='bnb-rwa-table']");
    if (!bar || !table) return;
    var rows = Array.prototype.slice.call(table.querySelectorAll("tr[data-provider-id]"));
    var buttons = bar.querySelectorAll(".bnb-filter");

    buttons.forEach(function (button) {
      button.addEventListener("click", function () {
        var predicate = FILTERS[button.getAttribute("data-filter")] || FILTERS.all;
        buttons.forEach(function (b) { b.classList.toggle("is-active", b === button); });
        rows.forEach(function (row) {
          row.style.display = predicate(row) ? "" : "none";
        });
      });
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
