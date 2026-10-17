// Request-local presentation lifecycle. Financial freshness comes only from the server.
(function () {
  'use strict';
  var generation = 0, writes = new Set(), gridWrites = 0, active = null, queued = false;
  function root() { return document.getElementById('v2-sheet-diagnostics'); }
  function project() {
    var shell = document.getElementById('v2-workbook-shell');
    return shell ? shell.dataset.project : '';
  }
  function visible() {
    var panel = document.getElementById('panel-diagnostics');
    return panel && !panel.hidden;
  }
  function identity() {
    var input = document.querySelector('#v2-canonical-run-form [name="content_hash"]');
    return project() + ':' + (input ? input.value : '');
  }
  function message(node, text) {
    var p = document.createElement('p'); p.setAttribute('role', 'status'); p.textContent = text;
    var retry = document.createElement('button'); retry.type = 'button';
    retry.dataset.diagnosticsRetry = ''; retry.textContent = 'Load Diagnostics';
    node.replaceChildren(p, retry);
  }
  function invalidate() {
    generation++;
    // A newer read may proceed after the write; the older response remains guarded.
    active = null;
    var node = root();
    if (node) {
      node.dataset.diagnosticsLoadState = 'pending';
      node.dataset.state = 'UNAVAILABLE';
      message(node, 'Checks need refreshing. Previous results are not current.');
    }
  }
  function invalidateHealth() {
    var health = document.getElementById('v2-model-health');
    if (!health) return;
    health.dataset.state = 'UNAVAILABLE';
    var p = document.createElement('p'); p.setAttribute('role', 'status');
    p.textContent = 'Checks need refreshing after Save. Previous results are not current.';
    health.replaceChildren(p);
  }
  function schedule() {
    if (queued) return;
    queued = true;
    queueMicrotask(function () { queued = false; ensure(); });
  }
  function ensure() {
    var node = root();
    if (!node || !visible() || writes.size || gridWrites || !window.htmx) return;
    if (node.dataset.diagnosticsLoadState !== 'pending' || active) return;
    var ticket = {generation: generation, identity: identity(), node: node, xhr: null,
      restoreFocus: node.contains(document.activeElement)};
    active = ticket; node.setAttribute('aria-busy', 'true');
    // HTMX serializes requests per source. A stale pending read must not queue
    // the new snapshot's read behind itself or behind unrelated body requests.
    var source = document.createElement('span'); source.hidden = true;
    document.body.appendChild(source);
    window.htmx.ajax('GET', '/v2/workbook/diagnostics?project=' + encodeURIComponent(project()),
      {source: source, target: '#v2-sheet-diagnostics', swap: 'none'})
      .catch(function () { /* Status and retry are handled by the request lifecycle below. */ });
  }
  document.addEventListener('htmx:beforeRequest', function (event) {
    var detail = event.detail || {}, config = detail.requestConfig || {};
    var path = String(config.path || ''), verb = String(config.verb).toLowerCase();
    if (verb === 'post' && /^\/v2\/(workbook|capex|opex)\//.test(path)) {
      writes.add(detail.xhr);
      detail.xhr.addEventListener('loadend', function () {
        writes.delete(detail.xhr); schedule();
      }, {once: true});
      invalidate(); return;
    }
    if (verb !== 'get' || path.indexOf('/v2/workbook/diagnostics?') !== 0) return;
    var ticket = active;
    if (!ticket) return;
    ticket.xhr = detail.xhr;
    var source = detail.elt || event.target;
    function beforeLoad(loadEvent) {
      if ((loadEvent.detail || {}).xhr !== ticket.xhr) return;
      if (ticket.generation !== generation || ticket.identity !== identity() ||
          ticket.node !== root() || writes.size || gridWrites) loadEvent.preventDefault();
    }
    // The original source may be detached by a concurrent OOB replacement.
    source.addEventListener('htmx:beforeOnLoad', beforeLoad);
    ticket.xhr.addEventListener('loadend', function () {
      source.removeEventListener('htmx:beforeOnLoad', beforeLoad);
      source.remove();
      if (active === ticket) active = null;
      var node = root();
      var currentTicket = ticket.generation === generation && ticket.identity === identity();
      if (node && currentTicket) node.removeAttribute('aria-busy');
      if (node && currentTicket && node.dataset.diagnosticsLoadState === 'loaded') {
        document.dispatchEvent(new CustomEvent('model:diagnostics-loaded'));
        if (ticket.restoreFocus && document.activeElement === document.body && visible()) {
          node.tabIndex = -1; node.focus({preventScroll: true});
        }
      } else if (currentTicket && ticket.node === node) {
        node.dataset.diagnosticsLoadState = 'error';
        node.dataset.state = 'UNAVAILABLE';
        message(node, 'Checks could not be loaded. Try again.');
      }
      schedule();
    }, {once: true});
  });
  document.addEventListener('htmx:afterRequest', function (event) {
    if (writes.delete((event.detail || {}).xhr)) schedule();
  });
  document.addEventListener('model:diagnostics-write-start', function () {
    gridWrites++; invalidate();
  });
  document.addEventListener('model:diagnostics-write-end', function (event) {
    if ((event.detail || {}).saved) invalidateHealth();
    gridWrites = Math.max(0, gridWrites - 1); schedule();
  });
  document.addEventListener('ig:saved', function () {
    invalidate();
    invalidateHealth();
    schedule();
  });
  document.addEventListener('click', function (event) {
    if (!event.target.closest('[data-diagnostics-retry]')) return;
    var node = root(); if (node) node.dataset.diagnosticsLoadState = 'pending';
    schedule();
  });
  document.addEventListener('htmx:afterSettle', schedule);
  window.addEventListener('popstate', schedule);
  window.addEventListener('hashchange', schedule);
  function boot() {
    var panel = document.getElementById('panel-diagnostics');
    if (!panel) return;
    new MutationObserver(schedule).observe(panel, {subtree: true, childList: true,
      attributes: true, attributeFilter: ['hidden']});
    if (new URLSearchParams(location.search).get('sheet') === 'diagnostics') {
      var tab = document.getElementById('tab-diagnostics'); if (tab) tab.click();
    }
    schedule();
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', boot);
  else boot();
}());
