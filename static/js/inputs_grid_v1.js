/*
 * WF-05 — Hybrid Inputs hub + grid editing (presentation layer only).
 *
 * 1. Hybrid navigation: INPUTS | SCENARIOS | OUTPUTS | ANALYSIS | TRUST group the EXISTING tabs.
 *    Group buttons click the real tab buttons; nothing is hidden, removed or re-implemented.
 * 2. Input grid: keyboard-first staging of registry-bound category inputs.
 *      Enter  commit the cell (stage it) and move down (Shift+Enter: up)
 *      Esc    cancel the cell edit (back to its last committed value)
 *      Tab / ArrowUp / ArrowDown   move between editable cells (the edit is committed on leave)
 *      Paste  multi-cell paste: a column of values, or "label<TAB>value" rows; validated by the
 *             canonical validator BEFORE anything is staged (all-or-nothing)
 *      Ctrl+S one ATOMIC batch Save through the C0 canonical writer; the model is never run.
 *    The browser holds no financial authority: values are only strings handed to the server.
 *    After a Save the grid panel is re-rendered in place and the focused cell, scroll position and
 *    open/closed sections are restored — Save never moves the user.
 */
(function () {
  'use strict';
  if (window.__igV1Init) return;
  window.__igV1Init = true;

  // ── Hybrid navigation ────────────────────────────────────────────────────────────────
  var HYBRID_GROUPS = {
    inputs:    ['tab-project-setup', 'tab-inputs', 'tab-input-grid', 'tab-revenue', 'tab-capex', 'tab-opex',
                'tab-investor', 'tab-debt', 'tab-tax'],
    scenarios: ['tab-scenarios'],
    outputs:   ['tab-outputs', 'tab-overview', 'tab-fs', 'tab-returns'],
    analysis:  ['tab-compare', 'tab-sensitivity', 'tab-goal-seek', 'tab-run-history'],
    trust:     ['tab-trust']
  };
  var GROUP_DEFAULT = {
    inputs: 'tab-input-grid', scenarios: 'tab-scenarios', outputs: 'tab-outputs',
    analysis: 'tab-sensitivity', trust: 'tab-trust'
  };
  var lastTabOfGroup = {};

  function groupOfTab(tabId) {
    for (var g in HYBRID_GROUPS) { if (HYBRID_GROUPS[g].indexOf(tabId) >= 0) return g; }
    return null;
  }
  function selectedTab() {
    var bar = document.getElementById('v2-sheet-tabs');
    return bar && bar.querySelector('[role="tab"][aria-selected="true"]');
  }
  function syncHybrid() {
    var tab = selectedTab();
    var group = tab ? groupOfTab(tab.id) : null;
    if (group && tab) lastTabOfGroup[group] = tab.id;
    Array.prototype.forEach.call(document.querySelectorAll('[data-hy-group]'), function (b) {
      var on = b.getAttribute('data-hy-group') === group;
      b.setAttribute('aria-selected', on ? 'true' : 'false');
      b.classList.toggle('hy-group--active', on);
    });
    Array.prototype.forEach.call(document.querySelectorAll('#v2-sheet-tabs .v2-tab'), function (t) {
      var inGroup = group && HYBRID_GROUPS[group].indexOf(t.id) >= 0;
      t.classList.toggle('v2-tab--in-group', !!inGroup);
    });
  }
  function initHybrid() {
    var bar = document.getElementById('v2-hybrid-bar');
    if (!bar) return;
    bar.addEventListener('click', function (evt) {
      var btn = evt.target.closest('[data-hy-group]');
      if (!btn) return;
      var g = btn.getAttribute('data-hy-group');
      var target = document.getElementById(lastTabOfGroup[g] || GROUP_DEFAULT[g]);
      if (target) target.click();
    });
    var tabs = document.getElementById('v2-sheet-tabs');
    if (tabs && window.MutationObserver) {
      new MutationObserver(function () { syncHybrid(); if (gridTabSelected()) scheduleRefresh(); }).observe(tabs, {
        attributes: true, subtree: true, attributeFilter: ['aria-selected']
      });
    }
    syncHybrid();
  }

  // ── Grid helpers ─────────────────────────────────────────────────────────────────────
  function root() { return document.getElementById('v2-input-grid'); }
  function allInputs() {
    var g = root();
    return g ? Array.prototype.slice.call(g.querySelectorAll('.ig-input')) : [];
  }
  function visibleInputs() {
    return allInputs().filter(function (i) { return i.offsetParent !== null; });
  }
  function rowOf(i) { return i.closest('[data-ig-row]'); }

  // Accept "1 234.5", "1,234.5", "1.234,5", "12,5". Everything else is left for the server.
  function norm(raw) {
    var s = String(raw == null ? '' : raw).replace(/[\s  ]/g, '');
    if (/^[+-]?\d{1,3}(\.\d{3})+(,\d+)?$/.test(s)) return s.replace(/\./g, '').replace(',', '.');
    if (/^[+-]?\d+,\d+$/.test(s)) return s.replace(',', '.');
    if (/^[+-]?\d{1,3}(,\d{3})+(\.\d+)?$/.test(s)) return s.replace(/,/g, '');
    return s;
  }
  function sameNumber(a, b) {
    var x = Number(norm(a)), y = Number(norm(b));
    if (norm(a) !== '' && norm(b) !== '' && isFinite(x) && isFinite(y)) return x === y;
    return norm(a) === norm(b);
  }
  function committedOf(i) { return i.getAttribute('data-committed') != null ? i.getAttribute('data-committed') : i.getAttribute('data-original'); }
  function isStaged(i) { return !i.hasAttribute('data-error') && !sameNumber(committedOf(i), i.getAttribute('data-original')); }
  function stagedInputs() { return allInputs().filter(isStaged); }

  var busy = { validating: 0, saving: false };

  function setMsg(text, kind) {
    var g = root(); if (!g) return;
    var m = g.querySelector('[data-ig-msg]'); if (!m) return;
    m.textContent = text || '';
    m.setAttribute('data-kind', kind || '');
  }
  function paintRow(i) {
    var row = rowOf(i); if (!row) return;
    var staged = isStaged(i), err = i.getAttribute('data-error');
    row.classList.toggle('ig-row--edited', staged);
    row.classList.toggle('ig-row--error', !!err);
    var e = row.querySelector('[data-ig-flag-edited]'); if (e) e.hidden = !staged;
    var f = row.querySelector('[data-ig-flag-error]');
    if (f) { f.hidden = !err; f.textContent = err || ''; }
    if (err) { i.setAttribute('aria-invalid', 'true'); i.setAttribute('title', err); }
    else { i.removeAttribute('aria-invalid'); i.removeAttribute('title'); }
  }
  function refreshBar() {
    var g = root(); if (!g) return;
    var n = stagedInputs().length;
    // Optimistic-concurrency base: the identity the user was looking at when the FIRST edit was staged.
    // If any other editor (legacy field form, cost line, Run) writes meanwhile, Save is refused as stale
    // instead of silently overwriting that write with an older staged value.
    if (n > 0 && !g.hasAttribute('data-stage-hash')) {
      var idn = liveIdentity(g);
      g.setAttribute('data-stage-hash', idn.hash); g.setAttribute('data-stage-version', idn.version);
    } else if (n === 0) {
      g.removeAttribute('data-stage-hash'); g.removeAttribute('data-stage-version');
    }
    var errs = allInputs().filter(function (i) { return i.hasAttribute('data-error'); }).length;
    var count = g.querySelector('[data-ig-count]');
    if (count) {
      count.textContent = (n ? n + ' unsaved edit' + (n === 1 ? '' : 's') : 'No unsaved edits')
        + (errs ? ' · ' + errs + ' with errors' : '');
      count.classList.toggle('ig-count--dirty', n > 0);
    }
    var save = g.querySelector('[data-ig-save]');
    if (save) save.disabled = !(n > 0) || errs > 0 || busy.validating > 0 || busy.saving || g.getAttribute('data-editable') !== 'true';
    var disc = g.querySelector('[data-ig-discard]');
    if (disc) disc.disabled = !(n > 0 || errs > 0) || busy.saving;
    var chip = document.querySelector('[data-hy-unsaved]');
    if (chip) { chip.hidden = n === 0; chip.textContent = n + ' unsaved'; }
    g.classList.toggle('ig--dirty', n > 0);
    g.setAttribute('aria-busy', busy.saving ? 'true' : 'false');
  }
  function paintAll() { allInputs().forEach(paintRow); refreshBar(); }

  // ── Validation (canonical server validator; local numeric pre-check) ─────────────────
  function postJSON(url, body) {
    return fetch(url, {
      method: 'POST', credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json', 'Accept': 'application/json' },
      body: JSON.stringify(body)
    }).then(function (r) {
      return r.json().catch(function () { return { ok: false, code: 'BAD_RESPONSE' }; })
        .then(function (j) { j.__status = r.status; return j; });
    });
  }
  function localCheck(i, v) {
    if (v === '') return 'A value is required.';
    if (!/^[+-]?(\d+\.?\d*|\.\d+)([eE][+-]?\d+)?$/.test(v)) return 'Enter a number.';
    var n = Number(v);
    var lo = i.getAttribute('data-min'), hi = i.getAttribute('data-max');
    if (lo != null && lo !== '' && n < Number(lo)) return 'Minimum is ' + lo + '.';
    if (hi != null && hi !== '' && n > Number(hi)) return 'Maximum is ' + hi + '.';
    return '';
  }
  function validateRemote(items) {
    var g = root();
    return postJSON('/v2/workbook/grid/validate', {
      project: g.getAttribute('data-project'), csrf_token: g.getAttribute('data-csrf'),
      cells: items.map(function (it) { return { field_id: it.input.getAttribute('data-ig-field'), value: it.value }; })
    });
  }

  // Commit one cell into the staged batch.  Returns a Promise<boolean> (true = accepted).
  function commit(i, opts) {
    opts = opts || {};
    var v = norm(i.value);
    if (sameNumber(v, committedOf(i)) && !i.hasAttribute('data-error')) { i.value = committedOf(i); return Promise.resolve(true); }
    var local = localCheck(i, v);
    if (local) { i.setAttribute('data-error', local); paintRow(i); refreshBar(); return Promise.resolve(false); }
    i.removeAttribute('data-error');
    // optimistic stage; the canonical validator has the last word
    var previous = committedOf(i);
    i.setAttribute('data-committed', v); i.value = v;
    paintRow(i); refreshBar();
    busy.validating++; refreshBar();
    return validateRemote([{ input: i, value: v }]).then(function (res) {
      busy.validating--;
      var verdict = res && res.cells && res.cells[0];
      if (res && res.ok) { paintRow(i); refreshBar(); return true; }
      i.setAttribute('data-committed', previous);
      i.setAttribute('data-error', (verdict && verdict.message) || (res && res.message) || 'Rejected by the model validator.');
      paintRow(i); refreshBar(); return false;
    }).catch(function () {
      busy.validating--;
      i.setAttribute('data-committed', previous);
      i.setAttribute('data-error', 'Could not validate (network). Try again.');
      paintRow(i); refreshBar(); return false;
    });
  }
  function cancelCell(i) {
    i.value = committedOf(i);
    i.removeAttribute('data-error');
    paintRow(i); refreshBar();
  }

  function focusInput(i) {
    if (!i) return;
    i.focus({ preventScroll: false });
    try { i.select(); } catch (e) { /* ignore */ }
  }
  function neighbour(i, dir) {
    var list = visibleInputs(), at = list.indexOf(i);
    return at < 0 ? null : list[at + dir] || null;
  }

  // ── Events ───────────────────────────────────────────────────────────────────────────
  function inGrid(e) { return e.target && e.target.classList && e.target.classList.contains('ig-input') ? e.target : null; }

  document.addEventListener('keydown', function (e) {
    var i = inGrid(e);
    if ((e.ctrlKey || e.metaKey) && (e.key === 's' || e.key === 'S') && root() && root().offsetParent !== null) {
      e.preventDefault();
      save();
      return;
    }
    if (!i || e.isComposing) return;
    if (busy.saving) { e.preventDefault(); return; }
    if (e.key === 'Enter') {
      e.preventDefault();
      var dir = e.shiftKey ? -1 : 1, next = neighbour(i, dir);
      commit(i); focusInput(next || i);
    } else if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
      e.preventDefault();
      var nx = neighbour(i, e.key === 'ArrowDown' ? 1 : -1);
      commit(i); focusInput(nx || i);
    } else if (e.key === 'Escape') {
      e.preventDefault(); e.stopPropagation();
      cancelCell(i); try { i.select(); } catch (x) { /* ignore */ }
    }
  }, true);

  document.addEventListener('focusin', function (e) {
    var i = inGrid(e);
    if (i) { try { i.select(); } catch (x) { /* ignore */ } }
  });
  document.addEventListener('focusout', function (e) {
    var i = inGrid(e);
    if (i && !busy.saving && norm(i.value) !== norm(committedOf(i))) commit(i);
  });
  document.addEventListener('input', function (e) {
    var i = inGrid(e);
    if (i && i.hasAttribute('data-error')) { i.removeAttribute('data-error'); paintRow(i); refreshBar(); }
  });

  // Multi-cell paste.
  function parsePaste(text) {
    var rows = String(text).replace(/\r/g, '').split('\n');
    while (rows.length && rows[rows.length - 1].trim() === '') rows.pop();
    return rows.map(function (r) { return r.split('\t'); });
  }
  function key(s) { return String(s).toLowerCase().replace(/[^a-z0-9]+/g, ' ').trim(); }

  document.addEventListener('paste', function (e) {
    var i = inGrid(e);
    if (!i || busy.saving) return;
    var text = (e.clipboardData || window.clipboardData).getData('text');
    var rows = parsePaste(text);
    if (rows.length <= 1 && (rows[0] || []).length <= 1) return;       // single value: native paste
    e.preventDefault();
    var g = root(), list = visibleInputs();
    var byLabel = {};
    list.forEach(function (inp) {
      var row = rowOf(inp);
      var code = row.querySelector('.ig-code'), label = row.querySelector('.ig-label');
      if (label) byLabel[key(label.textContent)] = inp;
      if (code) byLabel[key(code.textContent)] = inp;
    });
    var labelled = rows.every(function (r) { return r.length >= 2; })
      && rows.some(function (r) { return byLabel[key(r[0])]; });
    var plan = [], problems = [];
    if (labelled) {
      rows.forEach(function (r, n) {
        var inp = byLabel[key(r[0])];
        if (!inp) { problems.push('Row ' + (n + 1) + ': “' + r[0].trim() + '” matches no editable category.'); return; }
        plan.push({ input: inp, value: norm(r[r.length - 1]) });
      });
    } else {
      var start = list.indexOf(i);
      if (rows.length > list.length - start) {
        problems.push('Paste has ' + rows.length + ' values but only ' + (list.length - start) + ' editable cells from here.');
      } else {
        rows.forEach(function (r, n) { plan.push({ input: list[start + n], value: norm(r[r.length - 1]) }); });
      }
    }
    var seen = {};
    plan.forEach(function (p) {
      var id = p.input.getAttribute('data-ig-field');
      if (seen[id]) problems.push('“' + (p.input.getAttribute('data-label') || id) + '” appears more than once in the paste.');
      seen[id] = true;
      var bad = localCheck(p.input, p.value);
      if (bad) problems.push((p.input.getAttribute('data-label') || id) + ': ' + bad);
    });
    if (problems.length || !plan.length) {
      setMsg('Paste rejected — nothing applied. ' + (problems.slice(0, 3).join(' ') || 'No usable values.'), 'error');
      return;
    }
    busy.validating++; refreshBar();
    validateRemote(plan).then(function (res) {
      busy.validating--;
      if (!res || !res.ok) {
        var bads = ((res && res.cells) || []).filter(function (c) { return !c.ok; });
        setMsg('Paste rejected — nothing applied. ' + (bads.length
          ? bads.slice(0, 3).map(function (c) { return c.field_id + ': ' + c.message; }).join(' ')
          : ((res && res.message) || 'Validation failed.')), 'error');
        refreshBar(); return;
      }
      plan.forEach(function (p) {
        p.input.value = p.value; p.input.setAttribute('data-committed', p.value);
        p.input.removeAttribute('data-error');
        paintRow(p.input);
      });
      setMsg('Pasted ' + plan.length + ' cell' + (plan.length === 1 ? '' : 's') + ' — unsaved until you Save changes.', 'ok');
      refreshBar();
    }).catch(function () {
      busy.validating--; setMsg('Paste could not be validated (network). Nothing applied.', 'error'); refreshBar();
    });
  });

  // ── Save (atomic batch through C0) ───────────────────────────────────────────────────
  function captureView() {
    var ae = document.activeElement, g = root();
    return {
      field: ae && ae.classList && ae.classList.contains('ig-input') ? ae.getAttribute('data-ig-field') : null,
      caret: ae && ae.selectionStart != null ? [ae.selectionStart, ae.selectionEnd] : null,
      scrollX: window.scrollX, scrollY: window.scrollY,
      sections: g ? Array.prototype.map.call(g.querySelectorAll('[data-ig-section]'),
        function (d) { return [d.getAttribute('data-ig-section'), d.open]; }) : [],
      tableScroll: g ? Array.prototype.map.call(g.querySelectorAll('.ig-table'), function (t) { return t.parentElement ? t.parentElement.scrollLeft : 0; }) : []
    };
  }
  function restoreView(v) {
    var g = root(); if (!g || !v) return;
    v.sections.forEach(function (s) {
      var d = g.querySelector('[data-ig-section="' + s[0] + '"]'); if (d) d.open = s[1];
    });
    window.scrollTo(v.scrollX, v.scrollY);
    if (v.field) {
      var el = g.querySelector('.ig-input[data-ig-field="' + v.field.replace(/"/g, '\\"') + '"]');
      if (el) {
        el.focus({ preventScroll: true });
        if (v.caret) { try { el.setSelectionRange(v.caret[0], v.caret[1]); } catch (x) { /* ignore */ } }
      }
    }
    window.scrollTo(v.scrollX, v.scrollY);
  }
  function applyIdentity(hash, version, runState) {
    if (hash) {
      Array.prototype.forEach.call(document.querySelectorAll('input[name="content_hash"]'), function (n) { n.value = hash; });
      var shell = document.getElementById('v2-workbook-shell');
      if (shell) shell.setAttribute('data-content-hash', hash);
    }
    if (version) {
      Array.prototype.forEach.call(document.querySelectorAll('input[name="workbook_version"]'), function (n) { n.value = version; });
    }
    if (runState) setRunState(runState);
  }
  function setRunState(runState) {
    var label = { CURRENT: 'CURRENT', STALE: 'STALE', NOT_RUN: 'NOT RUN' }[runState];
    if (!label) return;
    Array.prototype.forEach.call(document.querySelectorAll('[data-hy-run-state]'), function (c) {
      c.className = 'hy-chip hy-chip--' + runState.toLowerCase(); c.textContent = label;
    });
    Array.prototype.forEach.call(document.querySelectorAll('.v2-ws-header-state-chip'), function (c) {
      c.className = 'v2-ws-header-state-chip v2-ws-header-state--' + runState.toLowerCase(); c.textContent = label;
    });
  }
  // The toolbar runtime chip is refreshed out-of-band by every cost-line save, field save and
  // Run: mirror it so the persistent strip never disagrees with it.
  function followToolbarState() {
    var toolbar = document.querySelector('.v2-toolbar');
    if (!toolbar || !window.MutationObserver) return;
    function read() {
      var chip = toolbar.querySelector('[data-testid="toolbar-runtime-state"]');
      var t = chip ? chip.textContent.trim().toLowerCase() : '';
      var map = { 'stale': 'STALE', 'current': 'CURRENT', 'not run': 'NOT_RUN' };
      if (map[t]) setRunState(map[t]);
      scheduleRefresh();
    }
    new MutationObserver(read).observe(toolbar, { childList: true, subtree: true, characterData: true });
  }
  function refreshDependentSheets(project) {
    if (!window.htmx) return;
    // Every legacy single-field editor of a saved field must show the new value and the new CAS hash,
    // so the two editing surfaces can never silently write conflicting values.
    ['capex', 'opex', 'revenue', 'project_setup', 'tax'].forEach(function (sheet) {
      var id = 'v2-sheet-' + sheet.replace('_', '-');
      if (!document.getElementById(id)) return;
      window.htmx.ajax('GET', '/v2/workbook/grid/sheet?project=' + encodeURIComponent(project) + '&sheet=' + sheet,
        // own `source` per sheet: htmx queues requests per source element, so a shared source would
        // silently drop all but the first and last refresh
        { source: '#' + id, target: '#' + id, swap: 'outerHTML' });
    });
  }

  // The composite identity moves on EVERY write (cost-line saves, field saves, Runs).  The Run form's
  // hidden inputs are refreshed out-of-band by all of them, so they are the live authority; the grid
  // root's own attributes are only the fallback (initial render / right after a grid Save).
  function liveIdentity(g) {
    var form = document.getElementById('v2-canonical-run-form') || document.querySelector('#v2-run-controls form');
    function pick(name, fallback) {
      var el = form && form.querySelector('input[name="' + name + '"]');
      return el && el.value ? el.value : fallback;
    }
    return { hash: pick('content_hash', g.getAttribute('data-content-hash')),
             version: pick('workbook_version', g.getAttribute('data-workbook-version')) };
  }

  // Re-render the grid panel in place from the server (fresh totals / Last Run markers) while keeping the
  // focused cell, scroll and open sections.  Never while edits are staged, saving, or the user is typing.
  var lastRefresh = 0, refreshTimer = null;
  function refreshPanel(force) {
    var g = root();
    if (!g || busy.saving || busy.validating || stagedInputs().length) return Promise.resolve(false);
    if (!force && g.contains(document.activeElement) && document.activeElement.classList.contains('ig-input')) return Promise.resolve(false);
    var view = captureView();
    return fetch('/v2/workbook/grid/panel?project=' + encodeURIComponent(g.getAttribute('data-project')), { credentials: 'same-origin' })
      .then(function (r) { return r.ok ? r.text() : Promise.reject(new Error('panel')); })
      .then(function (html) {
        if (stagedInputs().length || busy.saving) return false;       // the user started editing meanwhile
        root().outerHTML = html; restoreView(view); paintAll(); lastRefresh = Date.now(); return true;
      }).catch(function () { return false; });
  }
  function gridTabSelected() { var t = selectedTab(); return !!t && t.id === 'tab-input-grid'; }
  function scheduleRefresh() {
    clearTimeout(refreshTimer);
    refreshTimer = setTimeout(function () { if (gridTabSelected()) refreshPanel(false); }, 350);
  }

  var saveStartedAt = 0;
  function save() {
    var g = root();
    if (!g || busy.saving || g.getAttribute('data-editable') !== 'true') return Promise.resolve(false);
    var staged = stagedInputs();
    if (!staged.length) return Promise.resolve(false);
    if (allInputs().some(function (i) { return i.hasAttribute('data-error'); }) || busy.validating) {
      setMsg('Fix or discard the cells with errors before saving.', 'error'); return Promise.resolve(false);
    }
    busy.saving = true;
    allInputs().forEach(function (i) { i.readOnly = true; });
    refreshBar();
    setMsg('Saving ' + staged.length + ' edit' + (staged.length === 1 ? '' : 's') + '…', 'busy');
    saveStartedAt = performance.now();
    var project = g.getAttribute('data-project');
    var view = captureView();
    var cells = staged.map(function (i) { return { field_id: i.getAttribute('data-ig-field'), value: committedOf(i) }; });
    var identity = g.hasAttribute('data-stage-hash')
      ? { hash: g.getAttribute('data-stage-hash'), version: g.getAttribute('data-stage-version') }
      : liveIdentity(g);
    return postJSON('/v2/workbook/grid/save', {
      project: project, csrf_token: g.getAttribute('data-csrf'),
      workbook_version: identity.version,
      content_hash: identity.hash,
      scenario_id: g.getAttribute('data-scenario-id') || null,
      cells: cells
    }).then(function (res) {
      if (res && res.ok) {
        applyIdentity(res.content_hash, res.workbook_version, res.run_state);
        g.setAttribute('data-content-hash', res.content_hash);
        g.setAttribute('data-workbook-version', res.workbook_version);
        return fetch('/v2/workbook/grid/panel?project=' + encodeURIComponent(project), { credentials: 'same-origin' })
          .then(function (r) { return r.ok ? r.text() : Promise.reject(new Error('panel')); })
          .then(function (html) {
            var current = root();
            current.outerHTML = html;
            restoreView(view);
            paintAll();
            refreshDependentSheets(project);
            var ms = Math.round(performance.now() - saveStartedAt);
            window.__igLastSaveMs = ms;
            setMsg('Saved ' + cells.length + ' edit' + (cells.length === 1 ? '' : 's') + ' atomically · '
              + (res.run_state === 'STALE' ? 'Last Run is now STALE — run the model to refresh results.' : 'model not run.'), 'ok');
            document.dispatchEvent(new CustomEvent('ig:saved', { detail: { count: cells.length, ms: ms, runState: res.run_state } }));
            return true;
          }).catch(function () {
            // The batch IS committed; only the in-place refresh failed. Say so — never "not saved".
            busy.saving = false;
            allInputs().forEach(function (i) { i.readOnly = false; });
            setMsg('Saved atomically, but the view could not refresh. Reload the page to continue.', 'error');
            refreshBar();
            return true;
          });
      }
      busy.saving = false;
      allInputs().forEach(function (i) { i.readOnly = false; });
      if (res && res.cells) {
        res.cells.forEach(function (c) {
          if (c.ok) return;
          var el = g.querySelector('.ig-input[data-ig-field="' + c.field_id.replace(/"/g, '\\"') + '"]');
          if (el) { el.setAttribute('data-error', c.message || 'Rejected.'); paintRow(el); }
        });
      }
      setMsg((res && res.message) || ('Save failed (' + ((res && res.code) || 'error') + '). Nothing was saved; your edits are kept.'), 'error');
      refreshBar();
      return false;
    }).catch(function () {
      busy.saving = false;
      allInputs().forEach(function (i) { i.readOnly = false; });
      setMsg('Save could not be completed (network). Nothing was confirmed saved; your edits are kept.', 'error');
      refreshBar();
      return false;
    }).then(function (ok) { busy.saving = false; refreshBar(); return ok; });
  }

  document.addEventListener('click', function (e) {
    var g = root(); if (!g) return;
    if (e.target.closest('[data-ig-save]')) { save(); return; }
    if (e.target.closest('[data-ig-discard]')) {
      allInputs().forEach(function (i) {
        i.value = i.getAttribute('data-original'); i.removeAttribute('data-committed'); i.removeAttribute('data-error'); paintRow(i);
      });
      setMsg('Discarded.', 'ok'); refreshBar(); return;
    }
    if (e.target.closest('[data-ig-expand]') || e.target.closest('[data-ig-collapse]')) {
      var open = !!e.target.closest('[data-ig-expand]');
      Array.prototype.forEach.call(g.querySelectorAll('[data-ig-section]'), function (d) { d.open = open; });
      return;
    }
    var nav = e.target.closest('#v2-input-grid [data-nav-tab]');
    if (nav) {
      e.preventDefault();
      var tab = document.getElementById(nav.getAttribute('data-nav-tab'));
      if (tab) tab.click();
    }
  });

  // Never run on top of unsaved grid edits, and never silently: the user is told why.
  function blockRun(e) {
    var n = stagedInputs().length;
    if (!n) return false;
    e.preventDefault();
    if (e.stopImmediatePropagation) e.stopImmediatePropagation();
    setMsg(n + ' unsaved edit' + (n === 1 ? '' : 's') + ' — Save changes (or Discard) before running the model.', 'error');
    var tab = document.getElementById('tab-input-grid'); if (tab) tab.click();
    return true;
  }
  document.addEventListener('submit', function (e) {
    var f = e.target;
    if (f && f.classList && (f.classList.contains('v2-run-form') || f.id === 'v2-canonical-run-form')) blockRun(e);
  }, true);
  document.addEventListener('htmx:confirm', function (e) {
    var el = e.detail && e.detail.elt;
    if (el && el.classList && el.classList.contains('v2-run-form') && stagedInputs().length) {
      e.preventDefault(); blockRun(e);
    }
  });
  window.addEventListener('beforeunload', function (e) {
    if (stagedInputs().length) { e.preventDefault(); e.returnValue = ''; }
  });

  window.FincoInputGrid = {
    stagedCount: function () { return stagedInputs().length; },
    save: save,
    hybridGroups: HYBRID_GROUPS
  };

  // Sticky stack: toolbar → persistent strip → sheet tabs → grid action bar.  Measured, never assumed,
  // because the toolbar wraps on narrow screens.  On phones the strip scrolls with the page.
  function measureStack() {
    var toolbar = document.querySelector('.v2-toolbar'), hy = document.getElementById('v2-hybrid-bar');
    var tabs = document.getElementById('v2-sheet-tabs'), st = document.documentElement.style;
    if (!hy) return;
    st.setProperty('--hy-top', (toolbar ? toolbar.offsetHeight : 0) + 'px');
    var sticky = getComputedStyle(hy).position === 'sticky';
    st.setProperty('--hy-h', (sticky ? hy.offsetHeight : 0) + 'px');
    st.setProperty('--hy-tabs-h', (tabs ? tabs.offsetHeight : 0) + 'px');
  }
  window.addEventListener('resize', measureStack);

  function boot() { measureStack(); initHybrid(); followToolbarState(); paintAll(); }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', boot); else boot();
})();
