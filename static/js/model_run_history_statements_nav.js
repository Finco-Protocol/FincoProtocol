/* Run History <-> historical Statements navigation.  Presentation only: no data is read or written here.
   Opening the statements records one history entry, so the browser's Back returns to the Run detail and Forward
   returns to the statements; the in-page "Back to Run detail" button simply drives that same Back.  Keyboard focus is
   returned to the control that opened the statements. */
(function () {
  'use strict';
  if (window.__fincoRhStatementsNav) { return; }
  window.__fincoRhStatementsNav = true;
  var KEY = 'fincoRhStmt';
  var returnFocus = '';

  function current() {
    var s = document.getElementById('v2-run-statements');
    if (s) { return { kind: 'statements', project: s.getAttribute('data-out-project'), id: s.getAttribute('data-history-id') }; }
    var d = document.getElementById('v2-run-detail');
    var b = d && d.querySelector('[data-rh-statements]');
    if (b) { return { kind: 'detail', project: (b.getAttribute('hx-get').match(/project=([^&]*)/) || [])[1], id: b.getAttribute('data-history-id') }; }
    return null;
  }
  function detailUrl(project, id) { return '/v2/workbook/run-history/detail?project=' + project + '&history_id=' + encodeURIComponent(id); }
  function statementsUrl(project, id) { return '/v2/workbook/run-history/statements?project=' + project + '&history_id=' + encodeURIComponent(id); }

  document.addEventListener('click', function (e) {
    var open = e.target.closest && e.target.closest('[data-rh-statements]');
    if (open) {
      var c = current();
      try { var st = Object.assign({}, window.history.state || {}); st[KEY] = { view: 'statements', id: open.getAttribute('data-history-id') }; window.history.pushState(st, '', window.location.href); } catch (err) { /* history unavailable */ }
      returnFocus = 'run-detail-open-statements';
      return;
    }
    var back = e.target.closest && e.target.closest('[data-rh-back-detail]');
    if (back && window.history.state && window.history.state[KEY]) {
      e.preventDefault(); e.stopImmediatePropagation();      // drive the browser Back so history and view stay in step
      window.history.back();
    }
  }, true);

  window.addEventListener('popstate', function (e) {
    var cur = current();
    var entry = e.state && e.state[KEY];
    if (!cur || !window.htmx) { return; }
    if (cur.kind === 'statements' && !entry) {
      returnFocus = 'run-detail-open-statements';
      window.htmx.ajax('GET', detailUrl(cur.project, cur.id), { target: '#v2-run-statements', swap: 'outerHTML' });
    } else if (cur.kind === 'detail' && entry && entry.view === 'statements') {
      window.htmx.ajax('GET', statementsUrl(cur.project, entry.id || cur.id), { target: '#v2-run-detail', swap: 'outerHTML' });
    }
  });

  document.addEventListener('htmx:afterSwap', function () {
    if (!returnFocus) { return; }
    var target = document.querySelector('[data-testid="' + returnFocus + '"]');
    if (target) { target.focus(); returnFocus = ''; }
  });
})();
