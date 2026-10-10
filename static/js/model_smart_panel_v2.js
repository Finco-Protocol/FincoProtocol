/* Q2 Smart Panel V2 — read-only DOM projection over canonical server-rendered evidence.
   Delegated listeners survive HTMX OOB replacement; no API, no finance maths, no writes. */
(function () {
  'use strict';
  if (window.__fincoSmartPanelV2) return;
  window.__fincoSmartPanelV2 = true;

  var mode = 'solutions';
  var selected = '';
  var previousTab = '';
  var previousFieldId = '';
  var navigating = false; // true while the panel itself moves focus; never rewrites the return origin

  function panel() { return document.getElementById('model-smart-panel'); }
  // Rows whose server-rendered data-register-path EXACTLY equals the canonical register path.
  // Exactly one row is a proven mapping; zero or several fail closed (never a guess).
  function rowsForPath(path) {
    var found = [];
    if (!path) return found;
    var rows = document.querySelectorAll('.v2-field-row[data-register-path][data-field-id]');
    for (var i = 0; i < rows.length; i++) {
      if (rows[i].getAttribute('data-register-path') === path) found.push(rows[i]);
    }
    return found;
  }
  function elementByAttr(p, selector, key, value) {
    var nodes = p.querySelectorAll(selector);
    for (var i = 0; i < nodes.length; i++) {
      if (nodes[i].getAttribute(key) === value) return nodes[i];
    }
    return null;
  }
  function put(p, key, value) {
    var node = p.querySelector('[data-sp-' + key + ']');
    if (node) node.textContent = String(value == null ? '' : value);
  }
  function definition(list, label, value) {
    var dt = document.createElement('dt'); dt.textContent = label;
    var dd = document.createElement('dd'); dd.textContent = value == null || value === '' ? 'UNAVAILABLE' : String(value);
    list.appendChild(dt); list.appendChild(dd);
  }
  function action(parent, label, tab, field) {
    var b = document.createElement('button');
    b.type = 'button'; b.className = 'v2-sp-action'; b.textContent = label;
    if (field) b.setAttribute('data-jump-field', field);
    else if (tab) b.setAttribute('data-nav-tab', tab);
    else return;
    parent.appendChild(b);
  }
  function currentTab() {
    var selectedTab = document.querySelector('#v2-sheet-tabs [role="tab"][aria-selected="true"]');
    return selectedTab ? selectedTab.id : '';
  }
  function setMode(next, rememberTab) {
    var p = panel();
    if (!p || ['solutions','inspector','changes'].indexOf(next) < 0) return;
    if (rememberTab && next === 'inspector' && mode !== 'inspector') previousTab = currentTab();
    mode = next;
    Array.prototype.forEach.call(p.querySelectorAll('[data-sp-mode]'), function (b) {
      var active = b.getAttribute('data-sp-mode') === next;
      b.setAttribute('aria-selected', active ? 'true' : 'false');
      b.setAttribute('tabindex', active ? '0' : '-1');
    });
    Array.prototype.forEach.call(p.querySelectorAll('[data-sp-view]'), function (v) {
      v.hidden = v.getAttribute('data-sp-view') !== next;
    });
    if (next === 'inspector') inspect(p);
    if (next === 'changes') changes(p);
  }
  function inspect(p) {
    var picker = p.querySelector('[data-sp-select]');
    if (!picker) return;
    var value = selected;
    var optionExists = Array.prototype.some.call(picker.options, function (o) { return o.value === value; });
    if (!optionExists) value = '';
    picker.value = value;
    var target = p.querySelector('[data-sp-inspector-result]');
    if (!target) return;
    target.textContent = '';
    if (!value) { target.textContent = 'Select an assumption or an existing Last Run KPI. Selecting a source on the sheet can also open Explore.'; return; }
    var kind = value.slice(0, 2), key = value.slice(2);
    var facts = document.createElement('dl'); facts.className = 'v2-sp-facts';
    if (kind === 'f:') {
      var meta = elementByAttr(p, '[data-sp-field-meta]', 'data-path', key);
      var matches = rowsForPath(key);
      var row = matches.length === 1 ? matches[0] : null;
      definition(facts, 'Field', meta && meta.getAttribute('data-label'));
      definition(facts, 'Canonical path', key);
      definition(facts, 'Current effective value (Working Copy register)', meta && meta.getAttribute('data-value'));
      definition(facts, 'Unit', meta && meta.getAttribute('data-unit'));
      definition(facts, 'Source / provenance (register)', meta && meta.getAttribute('data-source'));
      definition(facts, 'Editability authority', row ? (row.classList.contains('v2-field-editable') ? 'Editable on owning sheet' : 'Read-only on owning sheet') : (matches.length > 1 ? 'UNAVAILABLE — ambiguous field mapping' : 'UNAVAILABLE — no proven workbook row mapping'));
      definition(facts, 'Assumption ID', 'UNAVAILABLE — not exposed by current register view');
      definition(facts, 'Related canonical KPIs', 'UNAVAILABLE — no proven field-to-KPI map');
      definition(facts, 'Calculation Trace', 'UNAVAILABLE — not persisted as a complete formula graph');
      target.appendChild(facts);
      if (row) action(target, 'Go to field', null, row.getAttribute('data-field-id'));
      else {
        var off = document.createElement('button');
        off.type = 'button'; off.className = 'v2-sp-action'; off.disabled = true;
        off.setAttribute('aria-disabled', 'true');
        off.textContent = 'Go to field (UNAVAILABLE)';
        target.appendChild(off);
        action(target, 'Open Assumption Register', 'tab-trust', null);
      }
      if (row && row.querySelector('.v2-field-input[data-pending="true"]')) {
        var note = document.createElement('p'); note.className = 'v2-sp-context';
        note.textContent = 'An edit is pending on the sheet; the value above is the register value, not an unsaved result.';
        target.appendChild(note);
      }
    } else if (kind === 'k:') {
      var metric = elementByAttr(p, '[data-sp-kpi-meta]', 'data-key', key);
      if (!metric) { target.textContent = 'KPI evidence is UNAVAILABLE for this selection.'; return; }
      var state = p.getAttribute('data-run-state') || 'NOT_RUN';
      var available = metric.getAttribute('data-available') === 'true' && state !== 'NOT_RUN';
      definition(facts, 'KPI', metric.getAttribute('data-label'));
      definition(facts, 'Last Run value', available ? metric.getAttribute('data-value') : 'UNAVAILABLE');
      definition(facts, 'Unit', metric.getAttribute('data-unit'));
      definition(facts, 'Source', metric.getAttribute('data-source'));
      definition(facts, 'Freshness', state === 'STALE' ? 'STALE — value belongs to prior Last Run' : state);
      definition(facts, 'Last Run timestamp', p.getAttribute('data-sp-run-at'));
      definition(facts, 'Last Run scenario', p.getAttribute('data-sp-run-scenario'));
      definition(facts, 'Calculation Trace completeness', 'UNAVAILABLE — clean run formula tree is not persisted');
      definition(facts, 'Linked assumptions', 'UNAVAILABLE — no stored validated map');
      definition(facts, 'Methodology', 'Trust Pack provides existing methodology; not a field-level formula tree');
      if (!available) definition(facts, 'Availability reason', metric.getAttribute('data-note'));
      target.appendChild(facts);
      action(target, 'Open owning sheet', metric.getAttribute('data-tab'), null);
      action(target, 'Open methodology in Trust Pack', 'tab-trust', null);
    } else { target.textContent = 'Selection unavailable.'; return; }
    if (previousTab && document.getElementById(previousTab)) {
      var back = document.createElement('button');
      back.type = 'button'; back.className = 'v2-sp-action';
      back.setAttribute('data-sp-return', previousTab);
      back.textContent = 'Return to previous sheet';
      target.appendChild(back);
    }
  }
  function changes(p) {
    if (!p) return;
    var state = p.getAttribute('data-run-state') || 'NOT_RUN';
    var project = document.querySelector('.v2-toolbar-name');
    var scenario = document.querySelector('#v2-toolbar-scenario-label strong');
    put(p, 'working-project', project ? project.textContent.trim() : 'UNAVAILABLE');
    put(p, 'working-scenario', scenario ? scenario.textContent.trim() : 'UNAVAILABLE');
    put(p, 'change-state', state);
    var pending = document.querySelectorAll('.v2-field-input[data-pending="true"]');
    put(p, 'change-run-required', pending.length ?
      'PENDING — save local edits first, then reassess the Run requirement' :
      state === 'STALE' ? 'YES — saved Working Copy differs from Last Run' :
      state === 'NOT_RUN' ? 'YES — no Last Run exists' : 'NO — saved Working Copy matches Last Run');
    put(p, 'change-summary', state === 'STALE' ?
      'Aggregate saved-input change is proven by freshness. Individual saved field history is not available.' :
      state === 'NOT_RUN' ? 'No committed Last Run exists for comparison.' :
      'No aggregate difference to Last Run is reported by the canonical freshness authority.');
    put(p, 'unsaved-count', pending.length ? pending.length + ' local pending input(s)' : 'No local pending editor values detected');
    var list = p.querySelector('[data-sp-pending-list]');
    if (list) {
      list.textContent = '';
      Array.prototype.forEach.call(pending, function (input) {
        var row = input.closest('.v2-field-row[data-field-id]');
        if (!row) return;
        var li = document.createElement('li');
        action(li, row.getAttribute('data-field-label') || row.getAttribute('data-field-id'), null, row.getAttribute('data-field-id'));
        list.appendChild(li);
      });
    }
  }
  function refresh() {
    var p = panel();
    if (!p) return;
    setMode(mode, false);
  }
  document.addEventListener('click', function (event) {
    var go = event.target.closest && event.target.closest('#model-smart-panel [data-jump-field]');
    if (go && !go.disabled) { navigating = true; setTimeout(function () { navigating = false; }, 0); }
  }, true);
  document.addEventListener('click', function (event) {
    var p = panel();
    if (!p) return;
    var tab = event.target.closest && event.target.closest('#model-smart-panel [data-sp-mode]');
    if (tab) {
      event.preventDefault();
      setMode(tab.getAttribute('data-sp-mode'), true);
      return;
    }
    var jumpMode = event.target.closest && event.target.closest('#model-smart-panel [data-sp-jump-mode]');
    if (jumpMode) {
      event.preventDefault();
      setMode(jumpMode.getAttribute('data-sp-jump-mode'), false);
      return;
    }
    var back = event.target.closest && event.target.closest('#model-smart-panel [data-sp-return]');
    if (back) {
      navigating = true;
      var dest = document.getElementById(back.getAttribute('data-sp-return'));
      if (dest) dest.click();
      if (previousFieldId && window.v2FieldValidationUx && window.v2FieldValidationUx.jump) {
        window.v2FieldValidationUx.jump(previousFieldId);
      }
      setTimeout(function () { navigating = false; }, 0);
      return;
    }
  });
  document.addEventListener('change', function (event) {
    var p = panel();
    if (!p || !event.target.matches || !event.target.matches('#model-smart-panel [data-sp-select]')) return;
    selected = event.target.value;
    if (mode !== 'inspector') previousTab = currentTab();
    setMode('inspector', false);
  });
  document.addEventListener('keydown', function (event) {
    var b = event.target.closest && event.target.closest('#model-smart-panel [data-sp-mode]');
    if (!b || (event.key !== 'ArrowLeft' && event.key !== 'ArrowRight')) return;
    var buttons = Array.prototype.slice.call(panel().querySelectorAll('[data-sp-mode]'));
    var idx = buttons.indexOf(b);
    if (idx < 0) return;
    event.preventDefault();
    var next = buttons[(idx + (event.key === 'ArrowRight' ? 1 : buttons.length - 1)) % buttons.length];
    next.focus();
    setMode(next.getAttribute('data-sp-mode'), true);
  });
  document.addEventListener('focusin', function (event) {
    var p = panel();
    if (navigating || !p || p.contains(event.target)) return;
    var row = event.target.closest && event.target.closest('.v2-field-row[data-field-id]');
    if (!row) return;
    var id = row.getAttribute('data-field-id');
    var path = row.getAttribute('data-register-path');
    if (!path || rowsForPath(path).length !== 1) return; // absent or ambiguous: never guess
    var meta = elementByAttr(p, '[data-sp-field-meta]', 'data-path', path);
    if (!meta) return;
    selected = 'f:' + path;
    previousTab = currentTab();
    previousFieldId = id;
    if (mode === 'inspector') inspect(p);
  });
  document.addEventListener('htmx:afterSwap', refresh);
  document.addEventListener('htmx:afterSettle', refresh);
  document.addEventListener('input', function (event) {
    if (event.target && event.target.classList && event.target.classList.contains('v2-field-input') && mode === 'changes') changes(panel());
  });
  document.addEventListener('DOMContentLoaded', refresh);
  refresh();
}());
