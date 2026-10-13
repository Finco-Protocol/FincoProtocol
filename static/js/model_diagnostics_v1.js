// Delegated once: safe across repeated HTMX replacements. No numerical calculations or writes.
(function () {
  'use strict';
  var generation = 0, refreshRequests = new WeakMap();
  function root() { return document.getElementById('v2-sheet-diagnostics'); }
  function payload() {
    var r = root(), node = r && r.querySelector('[data-md-payload]');
    return node ? JSON.parse(node.textContent) : null;
  }
  function filters() {
    var r = root(); if (!r || !r.querySelector('[data-md-status]')) return;
    var status = r.querySelector('[data-md-status]').value;
    var category = r.querySelector('[data-md-category]').value;
    var search = r.querySelector('[data-md-search]').value.toLowerCase().trim(), count = 0;
    r.querySelectorAll('[data-md-row]').forEach(function (row) {
      row.hidden = !!((status && row.dataset.status !== status) || (category && row.dataset.category !== category) || (search && row.dataset.search.indexOf(search) < 0));
      if (!row.hidden) count++;
    });
    r.querySelectorAll('[data-md-group]').forEach(function (group) { group.hidden = !group.querySelector('[data-md-row]:not([hidden])'); });
    r.querySelector('[data-md-filter-count]').textContent = count + ' checks shown';
  }
  // Display-only formatting. Never mutate the original JSON evidence in payload().
  function displayNumber(value) {
    if (typeof value !== 'number' || !Number.isFinite(value)) return 'UNAVAILABLE';
    if (value === 0) return '0';
    if (Math.abs(value) < 0.005) return value.toExponential(3);
    return value.toLocaleString('en-US', {minimumFractionDigits: 2, maximumFractionDigits: 2});
  }
  function displayFact(value) {
    return typeof value === 'number' ? displayNumber(value) :
      value === null || value === undefined ? 'UNAVAILABLE' : String(value);
  }
  function displayObject(value) {
    return JSON.stringify(value, function (_key, nested) {
      return typeof nested === 'number' ? displayNumber(nested) : nested;
    });
  }
  function show(id, period) {
    var r = root(), data = payload(); if (!data) return;
    var check = data.checks.find(function (c) { return c.check_id === id; }); if (!check) return;
    var detail = r.querySelector('[data-md-detail]'), facts = detail.querySelector('[data-md-detail-facts]');
    detail.hidden = false; facts.replaceChildren();
    detail.querySelector('[data-md-detail-title]').textContent = check.check_id + ' · ' + check.title;
    function fact(key, value) {
      var dt = document.createElement('dt'), dd = document.createElement('dd');
      dt.textContent = key; dd.textContent = displayFact(value);
      facts.append(dt, dd);
    }
    fact('Category / class', check.category + ' / ' + check.check_class);
    fact('Overall / severity', check.status + ' / ' + check.severity);
    fact('Explanation', check.description); fact('Reason', check.reason_code || check.detail);
    fact('Evidence source', check.evidence_source); fact('Threshold authority', check.threshold_authority);
    fact('Snapshot', data.identity.snapshot_id); fact('Run time', data.identity.run_at);
    fact('Composite hash', data.identity.composite_hash); fact('Engine', data.identity.engine_version);
    fact('Measured / residual', check.measured_value); fact('Threshold / tolerance', check.threshold_value);
    if (check.global_component) fact('Global / boundary component', displayObject(check.global_component));
    var selected = check.periods.find(function (p) { return String(p.period_index) === String(period); });
    if (selected) {
      fact('Period', 'P' + selected.period_index + ' · ' + (selected.date || 'DATE_UNAVAILABLE'));
      fact('Period status', selected.status); fact('Validation scope', selected.scope);
      fact('Residual (canonical validator)', selected.residual); fact('Tolerance', selected.tolerance);
      fact('Observed', selected.observed); fact('Expected', selected.expected);
      fact('Unit', check.measured_unit); fact('Period reason', selected.reason);
      r.querySelector('[data-md-waterfall]').open = true;
    } else fact('Period evidence', 'Select a timeline cell; aggregate verdict is not a period verdict.');
    r.querySelectorAll('[data-md-column]').forEach(function (cell) { cell.classList.toggle('md-selected-period', !!selected && cell.dataset.mdColumn === String(selected.period_index)); });
    var nav = detail.querySelector('[data-md-schedule]'); nav.setAttribute('data-nav-tab', check.navigation_target);
    detail.focus({preventScroll:true}); detail.scrollIntoView({block:'nearest'});
  }
  document.addEventListener('click', function (event) {
    var button = event.target.closest('[data-md-select],[data-diagnostics-check]'); if (!button) return;
    show(button.dataset.mdSelect || button.dataset.diagnosticsCheck, button.dataset.mdPeriod);
    var url = new URL(location.href); url.searchParams.set('diagnostic_check', button.dataset.mdSelect || button.dataset.diagnosticsCheck);
    if (button.dataset.mdPeriod !== undefined) url.searchParams.set('diagnostic_period', button.dataset.mdPeriod); else url.searchParams.delete('diagnostic_period');
    // Existing tab navigation owns history; only annotate that same entry.
    history.replaceState(history.state, '', url);
  });
  ['input','change'].forEach(function (name) { document.addEventListener(name, function (event) { if (event.target.matches('[data-md-search],[data-md-status],[data-md-category]')) filters(); }); });
  function restore() {
    filters(); var params = new URLSearchParams(location.search);
    var panel = document.getElementById('panel-diagnostics');
    if (panel && !panel.hidden && params.has('diagnostic_check')) show(params.get('diagnostic_check'), params.get('diagnostic_period'));
  }
  document.addEventListener('htmx:afterSettle', restore);
  document.addEventListener('htmx:beforeRequest', function (event) {
    var d = event.detail || {}, request = d.requestConfig || {};
    if (String(request.verb).toLowerCase() === 'post') generation++;
    if (String(request.path || '').indexOf('/v2/workbook/diagnostics?') === 0 && d.xhr) refreshRequests.set(d.xhr, generation);
  });
  document.addEventListener('htmx:beforeOnLoad', function (event) {
    var xhr = (event.detail || {}).xhr;
    if (xhr && refreshRequests.has(xhr) && refreshRequests.get(xhr) !== generation) event.preventDefault();
  });
  document.addEventListener('ig:saved', function () {
    generation++;
    var shell = document.getElementById('v2-workbook-shell');
    if (!shell || !window.htmx) return;
    // Never leave a CURRENT score/threshold on-screen while the canonical refresh is pending.
    ['v2-sheet-diagnostics','v2-model-health'].forEach(function (id) {
      var node = document.getElementById(id); if (!node) return;
      node.dataset.state = 'UNAVAILABLE';
      var message = document.createElement('p'); message.setAttribute('role','status');
      message.textContent = 'Diagnostics refresh pending after Save — committed evidence not yet resolved. Reload if the read cannot complete.';
      node.replaceChildren(message);
    });
    window.htmx.ajax('GET', '/v2/workbook/diagnostics?project=' + encodeURIComponent(shell.dataset.project),
                    {source: document.body, target:'#v2-sheet-diagnostics', swap:'none'});
  });
  window.addEventListener('popstate', restore);
  window.addEventListener('hashchange', restore);
  document.addEventListener('DOMContentLoaded', restore);
  restore();
}());
