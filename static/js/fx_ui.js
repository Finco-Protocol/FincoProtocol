/* FINCO Model UI layer: Flowbite toast + HTMX re-initialisation (RC-UX Phase 2 / Addendum D).
 *
 * Uses the self-hosted Flowbite bundle (static/vendor/flowbite.min.js) for Accordion / Collapse / Dismiss behaviour. Feedback is presentation only:
 * it reports what the existing Save / Run requests already returned and never changes state or adds a second Run-status authority.
 * Everything is attached once (window guard) and works after HTMX swaps because it listens on `document`.
 */
(function () {
  'use strict';
  if (window.FincoToast) return;
  const KINDS = {
    success: {icon: 'text-green-500 bg-green-100 dark:bg-green-800 dark:text-green-200', path: 'M10 .5a9.5 9.5 0 1 0 9.5 9.5A9.51 9.51 0 0 0 10 .5Zm3.707 8.207-4 4a1 1 0 0 1-1.414 0l-2-2a1 1 0 0 1 1.414-1.414L9 10.586l3.293-3.293a1 1 0 0 1 1.414 1.414Z'},
    error: {icon: 'text-red-500 bg-red-100 dark:bg-red-800 dark:text-red-200', path: 'M10 .5a9.5 9.5 0 1 0 9.5 9.5A9.51 9.51 0 0 0 10 .5Zm3.707 11.793a1 1 0 1 1-1.414 1.414L10 11.414l-2.293 2.293a1 1 0 0 1-1.414-1.414L8.586 10 6.293 7.707a1 1 0 0 1 1.414-1.414L10 8.586l2.293-2.293a1 1 0 0 1 1.414 1.414L11.414 10l2.293 2.293Z'},
    info: {icon: 'text-blue-500 bg-blue-100 dark:bg-blue-800 dark:text-blue-200', path: 'M10 .5a9.5 9.5 0 1 0 9.5 9.5A9.51 9.51 0 0 0 10 .5ZM9.5 4a1.5 1.5 0 1 1 0 3 1.5 1.5 0 0 1 0-3ZM12 15H8a1 1 0 0 1 0-2h1v-3H8a1 1 0 0 1 0-2h2a1 1 0 0 1 1 1v4h1a1 1 0 0 1 0 2Z'}
  };
  let counter = 0;
  function region() {
    let r = document.getElementById('fx-toast-region');
    if (!r) {
      // Utilities are scoped as `.fx-ui .class`, so the fixed region must be a DESCENDANT of the scope element; an unscoped region would sit in the
      // normal page flow and add its height to the document (found by the scroll review of the Inputs grid Save).
      const scope = document.createElement('div');
      scope.className = 'fx-ui';
      r = document.createElement('div');
      r.id = 'fx-toast-region';
      r.className = 'fixed bottom-4 right-4 z-50 flex flex-col gap-2';
      r.setAttribute('aria-live', 'polite');
      scope.appendChild(r);
      document.body.appendChild(scope);
    }
    return r;
  }
  function remove(node) { if (node && node.parentNode) node.parentNode.removeChild(node); }
  function show(options) {
    const kind = KINDS[options.kind] ? options.kind : 'info';
    const id = 'fx-toast-' + (++counter);
    const toast = document.createElement('div');
    toast.id = id;
    toast.dataset.testid = 'toast-' + kind;
    toast.setAttribute('role', kind === 'error' ? 'alert' : 'status');
    toast.className = 'flex items-center w-full max-w-sm p-4 text-gray-600 bg-white border border-gray-200 rounded-lg shadow-lg dark:text-gray-300 dark:bg-gray-800 dark:border-gray-700';
    const icon = document.createElement('div');
    icon.className = 'inline-flex items-center justify-center flex-shrink-0 w-8 h-8 rounded-lg ' + KINDS[kind].icon;
    if (options.loading) {
      icon.innerHTML = '<svg aria-hidden="true" class="w-4 h-4 animate-spin" viewBox="0 0 24 24" fill="none"><circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle><path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 0 1 8-8v4a4 4 0 0 0-4 4H4Z"></path></svg>';
    } else {
      icon.innerHTML = '<svg aria-hidden="true" class="w-4 h-4" fill="currentColor" viewBox="0 0 20 20"><path d="' + KINDS[kind].path + '"></path></svg>';
    }
    const text = document.createElement('div');
    text.className = 'ms-3 text-sm font-normal';
    text.textContent = options.message;                                     // text only: never HTML
    const close = document.createElement('button');
    close.type = 'button';
    close.className = 'ms-auto -mx-1.5 -my-1.5 bg-white text-gray-400 hover:text-gray-900 rounded-lg focus:ring-2 focus:ring-gray-300 p-1.5 hover:bg-gray-100 inline-flex items-center justify-center h-8 w-8 dark:text-gray-500 dark:hover:text-white dark:bg-gray-800 dark:hover:bg-gray-700';
    close.setAttribute('aria-label', 'Close');
    close.setAttribute('data-dismiss-target', '#' + id);
    close.innerHTML = '<svg aria-hidden="true" class="w-3 h-3" fill="none" viewBox="0 0 14 14"><path stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="m1 1 6 6m0 0 6 6M7 7l6-6M7 7l-6 6"/></svg>';
    toast.append(icon, text, close);
    region().appendChild(toast);
    try { if (window.Dismiss) new window.Dismiss(toast, close, {transition: 'transition-opacity', duration: 150, timing: 'ease-out'}); } catch (_) { /* manual fallback below */ }
    close.addEventListener('click', () => remove(toast));
    if (!options.sticky) setTimeout(() => remove(toast), options.ms || (kind === 'error' ? 15000 : 6000));       // errors stay longer, but never indefinitely over the content
    return {id, dismiss: () => remove(toast)};
  }
  window.FincoToast = {show};

  // Flowbite components (Accordion / Collapse / Dismiss) are initialised from data attributes; re-run after every HTMX swap.
  // Flowbite keeps one instance per element id, so repeated calls never attach duplicate listeners.
  function init() { if (typeof window.initFlowbite === 'function') window.initFlowbite(); }
  document.addEventListener('DOMContentLoaded', init);
  document.addEventListener('htmx:afterSettle', init);
  if (document.readyState !== 'loading') init();

  // Run History states the Last Run CURRENT / STALE; after any successful Save it must say STALE like every other surface (UX-001 class).
  // The listing is re-read (read-only GET); a detail or compare view the user is looking at is never replaced.
  function refreshRunHistory() {
    const root = document.getElementById('v2-sheet-run-history'), shell = document.getElementById('v2-workbook-shell');
    if (!root || !shell || !window.htmx) return;
    if (!root.querySelector('[data-testid="run-history-table"], [data-testid="run-history-empty"]')) return;
    window.htmx.ajax('GET', '/v2/workbook/run-history?project=' + encodeURIComponent(shell.dataset.project),
      {source: '#v2-sheet-run-history', target: '#v2-sheet-run-history', swap: 'outerHTML'});
  }
  ['ig:saved', 'ct:saved', 'rc:saved'].forEach((name) => document.addEventListener(name, () => setTimeout(refreshRunHistory, 50)));

  // Long analysis operations (Goal Seek, sensitivity, two-driver matrix): report only states the browser actually knows - request sent and awaiting the
  // server, then completed or failed. No percentage and no invented stages; the solver itself is untouched.
  const ANALYSIS = [
    ['/v2/workbook/goal-seek/run', 'Goal Seek'],
    ['/v2/workbook/goal-seek/apply', 'Applying the solved tariff'],
    ['/v2/workbook/sensitivity/matrix/run', 'Two-driver matrix'],
    ['/v2/workbook/scenarios/sensitivity/run', 'Sensitivity'],
  ];
  const analysisToasts = {};
  const analysisName = (path) => { const hit = ANALYSIS.find(([p]) => String(path || '').indexOf(p) === 0); return hit ? hit[1] : null; };
  document.addEventListener('htmx:beforeRequest', (e) => {
    const path = e.detail && e.detail.requestConfig && e.detail.requestConfig.path, name = analysisName(path);
    if (name && !analysisToasts[path]) analysisToasts[path] = show({kind: 'info', loading: true, sticky: true, message: name + ': request sent, waiting for the model…'});
  });
  document.addEventListener('htmx:afterRequest', (e) => {
    const path = e.detail && e.detail.requestConfig && e.detail.requestConfig.path, name = analysisName(path);
    if (!name) return;
    if (analysisToasts[path]) { analysisToasts[path].dismiss(); delete analysisToasts[path]; }
    const xhr = e.detail.xhr;
    show(e.detail.successful ? {kind: 'success', message: name + ' finished.'}
                             : {kind: 'error', message: name + ' did not complete' + (xhr && xhr.status ? ' (HTTP ' + xhr.status + ')' : '') + '. Nothing was changed.'});
  });

  // Table accessibility (UX-029): every table gets an accessible name and every header cell a scope, without touching the (partly governed) templates.
  // The name comes from the nearest preceding heading in the sheet; the sheet's own tab label is the fallback. Existing names are never replaced.
  const HEADING = 'h1, h2, h3, h4, h5, .v2-section-label, .v2-sheet-section-heading > span, .v2-rh-title, .v2-trust-title, summary';
  function nameFor(table) {
    for (let node = table; node && node.nodeType === 1 && node.getAttribute('role') !== 'tabpanel'; node = node.parentElement) {
      for (let sib = node.previousElementSibling; sib; sib = sib.previousElementSibling) {
        const hit = sib.matches(HEADING) ? sib : sib.querySelector(HEADING);
        const text = hit && (hit.textContent || '').replace(/\s+/g, ' ').trim();
        if (text) return text.slice(0, 80);
      }
    }
    const panel = table.closest('[role="tabpanel"]');
    const tab = panel && panel.getAttribute('aria-labelledby') && document.getElementById(panel.getAttribute('aria-labelledby'));
    return (tab ? tab.textContent.trim() : 'Model') + ' table';
  }
  function enhanceTables(root) {
    (root || document).querySelectorAll('table').forEach((t) => {
      if (!t.querySelector('caption') && !t.getAttribute('aria-label') && !t.getAttribute('aria-labelledby')) t.setAttribute('aria-label', nameFor(t));
      t.querySelectorAll('thead th:not([scope])').forEach((h) => h.setAttribute('scope', 'col'));
      t.querySelectorAll('tbody th:not([scope])').forEach((h) => h.setAttribute('scope', 'row'));
    });
  }
  // The page has exactly one level-1 heading (the project h1 in the shell). A sheet that renders its own h1 (for example Model Diagnostics) keeps its text and
  // markup; it is exposed to assistive technology as a level-2 heading instead.
  function normalizeHeadings(root) {
    (root || document).querySelectorAll('main h1:not(.v2-visually-hidden):not([aria-level])').forEach((h) => { h.setAttribute('role', 'heading'); h.setAttribute('aria-level', '2'); });
  }
  const enhanceAll = (root) => { enhanceTables(root); normalizeHeadings(root); };
  window.FincoEnhanceTables = enhanceAll;
  document.addEventListener('DOMContentLoaded', () => enhanceAll());
  document.addEventListener('htmx:afterSettle', (e) => enhanceAll(e.target && e.target.querySelectorAll ? e.target : document));
  if (document.readyState !== 'loading') enhanceAll();

  // Theme control (UX-009): sets the same `data-theme` attribute every theme-aware stylesheet already reads. "Auto" removes it so the OS preference applies.
  // The choice is a per-browser convenience (localStorage in try/catch); nothing else holds theme state.
  const THEMES = ['auto', 'light', 'dark'];
  const readTheme = () => { try { const v = window.localStorage.getItem('finco-theme'); return THEMES.indexOf(v) >= 0 ? v : 'auto'; } catch (_) { return 'auto'; } };
  const applyTheme = (t) => { if (t === 'auto') document.documentElement.removeAttribute('data-theme'); else document.documentElement.setAttribute('data-theme', t); };
  applyTheme(readTheme());
  function mountThemeControl() {
    const host = document.querySelector('.v2-toolbar');
    if (!host || host.querySelector('[data-testid="theme-toggle"]')) return;
    const b = document.createElement('button');
    b.type = 'button';
    b.className = 'v2-theme-toggle';
    b.setAttribute('data-testid', 'theme-toggle');
    const label = () => { const t = readTheme(); b.textContent = 'Theme: ' + t.charAt(0).toUpperCase() + t.slice(1); b.setAttribute('aria-label', 'Colour theme: ' + t + '. Activate to change.'); };
    b.addEventListener('click', () => {
      const next = THEMES[(THEMES.indexOf(readTheme()) + 1) % THEMES.length];
      try { window.localStorage.setItem('finco-theme', next); } catch (_) { /* the theme still applies for this page */ }
      applyTheme(next); label();
    });
    label();
    host.appendChild(b);
  }
  document.addEventListener('DOMContentLoaded', mountThemeControl);
  if (document.readyState !== 'loading') mountThemeControl();

  // ---- Save / Run feedback driven by events the existing flows already emit -------------------------------------------------
  document.addEventListener('ig:saved', (e) => show({kind: 'success', message: 'Saved ' + e.detail.count + ' edit' + (e.detail.count === 1 ? '' : 's') + (e.detail.runState === 'STALE' ? ' · results are now STALE: run the model' : '')}));
  document.addEventListener('ct:saved', (e) => show({kind: 'success', message: 'Construction timing saved · COD ' + e.detail.cod + (e.detail.runState === 'STALE' ? ' · results are now STALE' : '')}));
  document.addEventListener('rc:saved', () => show({kind: 'success', message: 'Revenue contracts saved · run the model to update results'}));
  document.addEventListener('rc:failed', (e) => show({kind: 'error', message: e.detail && e.detail.message ? e.detail.message : 'Revenue contracts were not saved.'}));
  let runToast = null;
  document.addEventListener('htmx:beforeRequest', (e) => {
    const p = e.detail && e.detail.requestConfig && e.detail.requestConfig.path;
    if (p && String(p).indexOf('/v2/workbook/run') === 0 && !runToast) runToast = show({kind: 'info', message: 'Running the model…', loading: true, sticky: true});
  });
  document.addEventListener('htmx:afterRequest', (e) => {
    const p = e.detail && e.detail.requestConfig && e.detail.requestConfig.path;
    if (!p || String(p).indexOf('/v2/workbook/run') !== 0) return;
    if (runToast) { runToast.dismiss(); runToast = null; }
    if (!e.detail.successful) { show({kind: 'error', message: 'The model run did not complete. Nothing was saved over the previous results.'}); return; }
    // SC-10: the server states the outcome explicitly. A refused Run answers HTTP 200 (HTMX contract), so the status code never decides success.
    if (e.detail.xhr && e.detail.xhr.getResponseHeader('X-Finco-Run-Outcome') === 'FAILED') {
      show({kind: 'error', message: 'The model refused to run. Your previous Last Run is unchanged; see the explanation at the top of the page.'});
      return;
    }
    // The committed state is what the page reports after the response has been applied (toolbar chip, refreshed out of band by the same response).
    setTimeout(() => {
      const chip = document.querySelector('[data-testid="toolbar-runtime-state"]');
      const current = !!chip && /current/i.test(chip.textContent);
      show(current ? {kind: 'success', message: 'Model run complete · results are current'}
                   : {kind: 'error', message: 'The model run did not complete. Nothing was saved over the previous results.'});
    }, 400);
  });
})();
