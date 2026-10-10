/* Statements & Debt output workspace: display formatting only. Raw persisted values live in data-raw; this script
   never recalculates, aggregates or writes anything — it re-renders the same numbers in another unit/precision. */
(function () {
  'use strict';
  var KEY = 'finco.outputs.display.v1';
  function load() { try { return JSON.parse(window.localStorage.getItem(KEY) || '{}') || {}; } catch (e) { return {}; } }
  function save(v) { try { window.localStorage.setItem(KEY, JSON.stringify(v)); } catch (e) { /* storage may be blocked */ } }
  function apply(root, prefs) {
    var unit = prefs.unit === 'eur' ? 'eur' : 'keur';
    var dec = [0, 1, 2, 3].indexOf(Number(prefs.decimals)) >= 0 ? Number(prefs.decimals) : 2;
    var fmt = new Intl.NumberFormat('en-US', { minimumFractionDigits: dec, maximumFractionDigits: dec });
    var ratio = new Intl.NumberFormat('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
    root.querySelectorAll('[data-raw]').forEach(function (cell) {
      var raw = cell.getAttribute('data-raw');
      if (raw === '' || raw === null) { return; }
      var n = Number(raw);
      if (!isFinite(n)) { return; }
      var u = cell.getAttribute('data-unit');
      var text = u === 'x' ? ratio.format(n) : fmt.format(unit === 'eur' ? n * 1000 : n);
      var small = cell.querySelector('small');
      if (small) { cell.firstChild.nodeValue = text + ' '; } else { cell.textContent = text; }
    });
    root.querySelectorAll('[data-year0]').forEach(function (cell) { cell.hidden = !prefs.year0; });
    root.setAttribute('data-out-unit-active', unit);
    root.querySelectorAll('.out-caption-unit').forEach(function (e) { e.textContent = unit === 'eur' ? 'EUR' : 'kEUR'; });
  }
  function init() {
    var root = document.getElementById('v2-sheet-outputs');
    if (!root || root.getAttribute('data-out-ready') === '1') { return; }
    root.setAttribute('data-out-ready', '1');
    var prefs = Object.assign({ unit: 'keur', decimals: 2, year0: true }, load());
    var unitInputs = root.querySelectorAll('[data-out-unit]');
    var prec = root.querySelector('[data-out-precision]');
    var y0 = root.querySelector('[data-out-year0]');
    unitInputs.forEach(function (i) { i.checked = i.value === prefs.unit; });
    if (prec) { prec.value = String(prefs.decimals); }
    if (y0) { y0.checked = !!prefs.year0; }
    function update() {
      var checked = root.querySelector('[data-out-unit]:checked');
      prefs.unit = checked ? checked.value : 'keur';
      prefs.decimals = prec ? Number(prec.value) : 2;
      prefs.year0 = y0 ? y0.checked : true;
      save(prefs); apply(root, prefs);
    }
    unitInputs.forEach(function (i) { i.addEventListener('change', update); });
    if (prec) { prec.addEventListener('change', update); }
    if (y0) { y0.addEventListener('change', update); }
    root.addEventListener('keydown', function (e) {
      var region = e.target.closest && e.target.closest('[data-out-scroll]');
      if (!region || e.target !== region) { return; }
      var step = 120;
      if (e.key === 'ArrowRight') { region.scrollLeft += step; e.preventDefault(); }
      else if (e.key === 'ArrowLeft') { region.scrollLeft -= step; e.preventDefault(); }
      else if (e.key === 'Home') { region.scrollLeft = 0; e.preventDefault(); }
      else if (e.key === 'End') { region.scrollLeft = region.scrollWidth; e.preventDefault(); }
    });
    apply(root, prefs);
  }
  if (document.readyState === 'loading') { document.addEventListener('DOMContentLoaded', init); } else { init(); }
  document.addEventListener('htmx:afterSwap', init);
})();
