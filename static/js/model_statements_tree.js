/* Statements V2 drill-down: presentation only.  This script never reads a number to calculate with, never sums rows, never
   writes to the model and never changes a displayed value; it shows/hides rows the server already rendered from the
   persisted Run, keeps ARIA state in step, and remembers the reading context so browser Back can restore it. */
(function () {
  'use strict';
  var STATE_KEY = 'fincoStmt';

  function roots() { return all(document, '#v2-sheet-outputs, #v2-run-statements'); }
  function all(el, sel) { return Array.prototype.slice.call(el.querySelectorAll(sel)); }
  function identity(root) {
    return { project: root.getAttribute('data-out-project') || '', snapshot: root.getAttribute('data-out-snapshot') || '',
             scenario: root.getAttribute('data-out-scenario') || '' };
  }
  function sameRun(a, b) { return !!a && !!b && a.project === b.project && a.snapshot === b.snapshot && a.scenario === b.scenario; }

  function rowsOf(table) { return all(table, 'tr[data-st-row]'); }
  function parentOf(row, byKey) { var k = row.getAttribute('data-st-parent'); return k ? byKey[k] : null; }
  function keyMap(table) { var m = {}; rowsOf(table).forEach(function (r) { m[r.getAttribute('data-st-key')] = r; }); return m; }
  function isExpanded(row) { return row.getAttribute('aria-expanded') === 'true'; }

  function refreshVisibility(table) {
    var byKey = keyMap(table);
    rowsOf(table).forEach(function (row) {
      var p = parentOf(row, byKey), visible = true;
      while (p) { if (!isExpanded(p)) { visible = false; break; } p = parentOf(p, byKey); }
      row.hidden = !visible;
    });
  }
  function setRowExpanded(row, expanded) {
    if (!row.hasAttribute('aria-expanded')) { return; }
    row.setAttribute('aria-expanded', expanded ? 'true' : 'false');
    var btn = row.querySelector('[data-st-toggle]');
    if (btn) {
      var name = (row.querySelector('.st-link, .st-name') || {}).textContent || 'line';
      btn.setAttribute('aria-expanded', expanded ? 'true' : 'false');
      btn.setAttribute('aria-label', (expanded ? 'Collapse ' : 'Expand ') + name.trim() + ' detail');
    }
  }
  function statementOf(table) { return table.getAttribute('data-st-tree'); }
  function treesFor(root, statement) { return all(root, 'table[data-st-tree="' + statement + '"]'); }
  function applyExpansion(root, statement, key, expanded) {
    treesFor(root, statement).forEach(function (t) {
      var row = keyMap(t)[key];
      if (row) { setRowExpanded(row, expanded); refreshVisibility(t); }
    });
  }
  function setAll(root, statement, expanded) {
    treesFor(root, statement).forEach(function (t) {
      rowsOf(t).forEach(function (r) { setRowExpanded(r, expanded); });
      refreshVisibility(t);
    });
  }
  function expandedKeys(root, statement) {
    var t = treesFor(root, statement)[0], out = [];
    if (t) { rowsOf(t).forEach(function (r) { if (r.hasAttribute('aria-expanded') && isExpanded(r)) { out.push(r.getAttribute('data-st-key')); } }); }
    return out;
  }
  function visibleRows(table) { return rowsOf(table).filter(function (r) { return !r.hidden; }); }

  function setRoving(table, row) {
    rowsOf(table).forEach(function (r) {
      var on = r === row;
      r.tabIndex = on ? 0 : -1;
      all(r, '[data-st-toggle], [data-st-link]').forEach(function (c) { c.tabIndex = on ? 0 : -1; });
    });
  }
  function focusRow(table, row) { if (row) { setRoving(table, row); row.focus(); } }

  function selectPeriod(root, date) {
    all(root, '.st-period').forEach(function (b) { b.setAttribute('aria-pressed', b.getAttribute('data-st-period') === date && date ? 'true' : 'false'); });
    all(root, 'table[data-st-tree] [data-col]').forEach(function (c) { c.classList.remove('st-col-selected'); });
    if (!date) { return; }
    all(root, 'table[data-st-tree]').forEach(function (t) {
      var btn = all(t, '.st-period').filter(function (b) { return b.getAttribute('data-st-period') === date; })[0];
      if (!btn) { return; }
      var col = btn.closest('th').getAttribute('data-col');
      all(t, '[data-col="' + col + '"]').forEach(function (c) { c.classList.add('st-col-selected'); });
    });
  }
  function selectedPeriod(root) { var b = root.querySelector('.st-period[aria-pressed="true"]'); return b ? b.getAttribute('data-st-period') : ''; }

  function setView(root, statement, view) {
    var bar = root.querySelector('[data-st-viewbar="' + statement + '"]');
    var section = bar ? bar.parentNode : null;
    if (!section) { return; }
    var tree = view === 'tree';
    var flat = section.querySelector('[data-st-pane="flat"]'), pane = section.querySelector('[data-st-pane="tree"]');
    if (flat) { flat.hidden = tree; }
    if (pane) { pane.hidden = !tree; }
    all(bar, '[data-st-view]').forEach(function (b) { b.setAttribute('aria-pressed', b.getAttribute('data-st-view') === view ? 'true' : 'false'); });
    all(bar, '[data-st-expand-all], [data-st-collapse-all]').forEach(function (b) { b.hidden = !tree; });
  }
  function currentView(root, statement) {
    var bar = root.querySelector('[data-st-viewbar="' + statement + '"]');
    if (bar && !bar.querySelector('[data-st-view]')) { return 'tree'; }      // tree-only view (historical Run)
    var on = bar && bar.querySelector('[data-st-view][aria-pressed="true"]');
    return on ? on.getAttribute('data-st-view') : 'flat';
  }

  function capture(root) {
    var statements = {};
    all(root, '[data-st-viewbar]').forEach(function (bar) {
      var id = bar.getAttribute('data-st-viewbar');
      statements[id] = { view: currentView(root, id), expanded: expandedKeys(root, id) };
    });
    var focused = document.activeElement && document.activeElement.closest ? document.activeElement.closest('tr[data-st-row]') : null;
    var focusTable = focused ? focused.closest('table[data-st-tree]') : null;
    var scroll = {};
    all(root, '[data-st-region]').forEach(function (r) {
      var t = r.querySelector('table[data-st-tree]');
      if (t) { scroll[statementOf(t) + ':' + t.getAttribute('data-st-basis')] = { left: r.scrollLeft, top: r.scrollTop }; }
    });
    return { run: identity(root), statements: statements, period: selectedPeriod(root),
             focus: focused ? { statement: statementOf(focusTable), basis: focusTable.getAttribute('data-st-basis'), key: focused.getAttribute('data-st-key') } : null,
             scroll: scroll, windowY: window.pageYOffset || 0 };
  }
  function storeKey(root) { return 'finco.stmt.hist.' + (root.getAttribute('data-out-project') || '') + '.' + (root.getAttribute('data-history-id') || ''); }
  function persist(root) {
    if (root.getAttribute('data-st-historical') !== '1') { return; }
    try { window.sessionStorage.setItem(storeKey(root), JSON.stringify(capture(root))); } catch (e) { /* storage may be blocked */ }
  }
  function stored(root) {
    if (root.getAttribute('data-st-historical') !== '1') { return null; }
    try { return JSON.parse(window.sessionStorage.getItem(storeKey(root)) || 'null'); } catch (e) { return null; }
  }
  function remember(root) {
    var ctx = capture(root);
    try { var s = Object.assign({}, window.history.state || {}); s[STATE_KEY] = ctx; window.history.replaceState(s, '', window.location.href); } catch (e) { /* history may be unavailable */ }
    return ctx;
  }
  function restore(root, ctx) {
    if (!ctx || !sameRun(ctx.run, identity(root))) { return false; }
    Object.keys(ctx.statements || {}).forEach(function (id) {
      var st = ctx.statements[id];
      setAll(root, id, false);
      (st.expanded || []).forEach(function (k) { applyExpansion(root, id, k, true); });
      setView(root, id, st.view === 'tree' ? 'tree' : 'flat');
    });
    selectPeriod(root, ctx.period || '');
    // Restoration belongs to the old navigation, never to a new interaction.
    // Both deferred passes must stop once the user focuses/uses this root.
    var cancelled = false, applying = false;
    var interactionEvents = ['focusin', 'keydown', 'pointerdown'];
    function cancelRestore() { if (!applying) { cancelled = true; } }
    interactionEvents.forEach(function (name) { root.addEventListener(name, cancelRestore, true); });
    function settle() {
      if (!root.isConnected || cancelled) { return; }
      applying = true;
      try {
        Object.keys(ctx.scroll || {}).forEach(function (k) {
          var parts = k.split(':');
          var t = root.querySelector('table[data-st-tree="' + parts[0] + '"][data-st-basis="' + parts[1] + '"]');
          var region = t ? t.closest('[data-st-region]') : null;
          if (region) { region.scrollLeft = ctx.scroll[k].left; region.scrollTop = ctx.scroll[k].top; }
        });
        if (typeof ctx.windowY === 'number') { window.scrollTo(0, ctx.windowY); }
        if (ctx.focus) {
          var t2 = root.querySelector('table[data-st-tree="' + ctx.focus.statement + '"][data-st-basis="' + ctx.focus.basis + '"]');
          var row = t2 ? keyMap(t2)[ctx.focus.key] : null;
          if (row && !row.hidden) { setRoving(t2, row); row.focus({ preventScroll: true }); }
        }
      } finally { applying = false; }
    }
    // layout settles after the unit/basis controls have applied; run twice so a late reflow cannot undo it
    window.requestAnimationFrame(function () {
      settle();
      window.setTimeout(function () {
        settle();
        interactionEvents.forEach(function (name) { root.removeEventListener(name, cancelRestore, true); });
      }, 60);
    });
    return true;
  }

  function initTable(table) {
    var rows = rowsOf(table);
    if (rows.length && !table.querySelector('tr[tabindex="0"]')) { setRoving(table, rows[0]); }
  }

  function onKeydown(root, e) {
    var table = e.target.closest && e.target.closest('table[data-st-tree]');
    if (!table) {
      var region = e.target.closest && e.target.closest('[data-st-region]');
      if (region && e.target === region) {
        var step = 120;
        if (e.key === 'ArrowRight') { region.scrollLeft += step; e.preventDefault(); }
        else if (e.key === 'ArrowLeft') { region.scrollLeft -= step; e.preventDefault(); }
        else if (e.key === 'Home') { region.scrollLeft = 0; e.preventDefault(); }
        else if (e.key === 'End') { region.scrollLeft = region.scrollWidth; e.preventDefault(); }
      }
      return;
    }
    if (e.target.closest('thead')) { return; }               // ordinary header/period-button keyboard behaviour
    var row = e.target.closest('tr[data-st-row]');
    if (!row) { return; }
    var byKey = keyMap(table), vis = visibleRows(table), i = vis.indexOf(row);
    var expandable = row.hasAttribute('aria-expanded');
    var onToggle = !!(e.target.closest && e.target.closest('[data-st-toggle]'));
    var onLink = !!(e.target.closest && e.target.closest('[data-st-link]'));
    if (e.key === 'ArrowDown') { focusRow(table, vis[Math.min(vis.length - 1, i + 1)]); e.preventDefault(); }
    else if (e.key === 'ArrowUp') { focusRow(table, vis[Math.max(0, i - 1)]); e.preventDefault(); }
    else if (e.key === 'Home' && !e.ctrlKey) { focusRow(table, vis[0]); e.preventDefault(); }
    else if (e.key === 'End' && !e.ctrlKey) { focusRow(table, vis[vis.length - 1]); e.preventDefault(); }
    else if (e.key === 'ArrowRight') {
      if (expandable && !isExpanded(row)) { applyExpansion(root, statementOf(table), row.getAttribute('data-st-key'), true); }
      else if (expandable) { var kids = visibleRows(table).filter(function (r) { return r.getAttribute('data-st-parent') === row.getAttribute('data-st-key'); }); focusRow(table, kids[0]); }
      e.preventDefault();
    } else if (e.key === 'ArrowLeft') {
      if (expandable && isExpanded(row)) { applyExpansion(root, statementOf(table), row.getAttribute('data-st-key'), false); }
      else { var p = parentOf(row, byKey); if (p) { focusRow(table, p); } }
      e.preventDefault();
    } else if ((e.key === 'Enter' || e.key === ' ') && e.target === row && expandable) {
      applyExpansion(root, statementOf(table), row.getAttribute('data-st-key'), !isExpanded(row)); e.preventDefault();
    } else if (e.key === ' ' && (onToggle || onLink)) {
      if (onToggle) { e.preventDefault(); e.target.click(); }
    }
  }

  function init() { roots().forEach(initRoot); }
  function initRoot(root) {
    if (!root || root.getAttribute('data-st-ready') === '1') { return; }
    root.setAttribute('data-st-ready', '1');
    all(root, 'table[data-st-tree]').forEach(function (t) {
      initTable(t);
    });
    // Default reading state: every parent collapsed, flat view.  (Without this script every line stays visible.)
    all(root, '[data-st-viewbar]').forEach(function (bar) { var id = bar.getAttribute('data-st-viewbar'); setAll(root, id, false); setView(root, id, currentView(root, id) === 'tree' && !bar.querySelector('[data-st-view]') ? 'tree' : 'flat'); });
    var state = (window.history.state && window.history.state[STATE_KEY]) || stored(root);
    restore(root, state);
    if (root.getAttribute('data-st-historical') === '1' && !state) {
      var title = root.querySelector('#rh-stmt-title');
      if (title) { title.focus({ preventScroll: true }); }
    }

    root.addEventListener('click', function (e) {
      var t = e.target;
      var toggle = t.closest && t.closest('[data-st-toggle]');
      if (toggle) {
        var row = toggle.closest('tr'), table = row.closest('table');
        applyExpansion(root, statementOf(table), row.getAttribute('data-st-key'), !isExpanded(row));
        setRoving(table, row); toggle.focus(); persist(root); return;
      }
      var link = t.closest && t.closest('[data-st-link]');
      if (link) { remember(root); return; }                       // navigation proceeds natively; Back returns here
      var period = t.closest && t.closest('.st-period');
      if (period) { var date = period.getAttribute('data-st-period'); selectPeriod(root, selectedPeriod(root) === date ? '' : date); persist(root); return; }
      var v = t.closest && t.closest('[data-st-view]');
      if (v) { var bar = v.closest('[data-st-viewbar]'); setView(root, bar.getAttribute('data-st-viewbar'), v.getAttribute('data-st-view')); return; }
      var ex = t.closest && t.closest('[data-st-expand-all]');
      if (ex) { setAll(root, ex.closest('[data-st-viewbar]').getAttribute('data-st-viewbar'), true); persist(root); return; }
      var co = t.closest && t.closest('[data-st-collapse-all]');
      if (co) { setAll(root, co.closest('[data-st-viewbar]').getAttribute('data-st-viewbar'), false); persist(root); return; }
      var cellRow = t.closest && t.closest('tr[data-st-row]');
      if (cellRow) { setRoving(cellRow.closest('table'), cellRow); }
    });
    root.addEventListener('focusin', function (e) {
      var r = e.target.closest && e.target.closest('tr[data-st-row]');
      if (r) { setRoving(r.closest('table'), r); persist(root); }
    });
    root.addEventListener('scroll', function () { persist(root); }, true);
    root.addEventListener('keydown', function (e) { onKeydown(root, e); window.setTimeout(function () { persist(root); }, 0); });
    window.__fincoStatements = { capture: function () { return capture(root); }, remember: function () { return remember(root); } };
  }
  if (document.readyState === 'loading') { document.addEventListener('DOMContentLoaded', init); } else { init(); }
  document.addEventListener('htmx:afterSwap', init);
})();
