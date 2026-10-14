// Diagnostics V2: read-only selection/detail rendering over the committed payload. No calculation, no writes.
(function () {
  'use strict';
  function root() { return document.getElementById('v2-sheet-diagnostics'); }
  function payload() {
    var r = root(), node = r && r.querySelector('[data-md-payload]');
    return node ? JSON.parse(node.textContent) : null;
  }
  function num(value) {
    if (typeof value !== 'number' || !Number.isFinite(value)) return value === null || value === undefined ? 'UNAVAILABLE' : String(value);
    if (value === 0) return '0';
    if (Math.abs(value) < 0.005) return value.toExponential(3);
    return value.toLocaleString('en-US', {minimumFractionDigits: 2, maximumFractionDigits: 2});
  }
  function el(tag, text, cls) { var n = document.createElement(tag); if (text !== undefined) n.textContent = text; if (cls) n.className = cls; return n; }
  function componentsTable(components) {
    var names = Object.keys(components || {});
    if (!names.length) return null;
    var table = el('table', undefined, 'md2-components'), head = el('tr');
    ['Component', 'Value (kEUR unless stated)', 'Source', 'Basis'].forEach(function (h) { head.append(el('th', h)); });
    table.append(head);
    names.forEach(function (name) {
      var c = components[name], row = el('tr');
      var value = c && typeof c === 'object' ? c.value : c;
      row.append(el('th', name), el('td', typeof value === 'boolean' ? String(value) : num(value)), el('td', c && c.source ? c.source : ''), el('td', c && c.basis ? c.basis : ''));
      table.append(row);
    });
    return table;
  }
  function rootCauseBlock(rcs) {
    var box = el('div');
    if (!rcs.length) return box;
    box.append(el('h3', 'Root-cause relationship evidence'));
    rcs.forEach(function (rc) {
      box.append(el('p', 'Overall confidence: ' + rc.confidence + ' · cause established: ' + (rc.cause_established ? 'yes' : 'no') +
        (rc.period_index !== null ? ' · P' + rc.period_index + ' ' + (rc.date || '') : ' · aggregate')));
      var list = el('ul', undefined, 'md2-items');
      rc.items.forEach(function (item) {
        var li = el('li');
        li.append(el('span', item.confidence, 'md2-confidence'), document.createTextNode(item.statement));
        list.append(li);
      });
      box.append(list, el('p', rc.explanation, 'md-note'));
    });
    return box;
  }
  function rootCausesFor(data, id, period) {
    return ((data.v2 && data.v2.root_causes) || []).filter(function (rc) {
      return rc.check_id === id && (period === undefined || period === null || String(rc.period_index) === String(period));
    });
  }
  function showDx(id, period) {
    var r = root(), data = payload(); if (!data || !data.v2) return;
    var check = (data.v2.advanced_checks || []).find(function (c) { return c.check_id === id; }); if (!check) return;
    var panel = r.querySelector('[data-md2-detail]'), facts = panel.querySelector('[data-md2-detail-facts]');
    panel.hidden = false; facts.replaceChildren();
    panel.querySelector('[data-md2-detail-title]').textContent = check.check_id + ' · ' + check.title;
    function fact(k, v) { facts.append(el('dt', k), el('dd', typeof v === 'number' ? num(v) : (v === null || v === undefined ? 'UNAVAILABLE' : String(v)))); }
    fact('Overall / severity', check.status + ' / ' + check.severity); fact('Reason', check.reason_code || 'evaluated');
    fact('Classification', check.classification + ' (not part of the Quality score)');
    fact('Coverage', check.coverage.evaluated_periods + ' of ' + check.coverage.applicable_periods + ' applicable periods evaluated' + (check.coverage.complete ? '' : ' (partial)'));
    fact('Definition', check.definition); fact('Evidence prerequisites', check.prerequisites.join(' · '));
    fact('Tolerance source', check.tolerance_source); fact('Evidence source', check.evidence_source);
    fact('Run', (data.identity.snapshot_id || 'UNAVAILABLE') + ' · ' + (data.identity.composite_hash || 'UNAVAILABLE'));
    fact('Related assumptions', check.related_assumptions.join(', ') || 'none registered');
    fact('Related checks', check.related_checks.join(', ') || 'none');
    if (check.global_component) fact('Global component', JSON.stringify(check.global_component));
    var selected = check.periods.find(function (p) { return String(p.period_index) === String(period); });
    var box = panel.querySelector('[data-md2-components]'); box.replaceChildren();
    if (selected) {
      fact('Period', 'P' + selected.period_index + ' · ' + (selected.date || 'DATE_UNAVAILABLE'));
      fact('Period status / scope', selected.status + ' / ' + selected.scope); fact('Period reason', selected.reason || 'evaluated');
      fact('Observed', selected.observed); fact('Expected', selected.expected); fact('Residual (observed - expected)', selected.residual);
      fact('Tolerance', selected.tolerance);
      var t = componentsTable(selected.components); if (t) box.append(el('h3', 'Committed components'), t);
    } else { fact('Period evidence', 'Select a timeline cell; the overall verdict is not a period verdict.'); }
    panel.querySelector('[data-md2-rootcause]').replaceChildren(rootCauseBlock(rootCausesFor(data, id, selected ? selected.period_index : undefined)));
    r.querySelectorAll('[data-md-column]').forEach(function (cell) { cell.classList.toggle('md-selected-period', !!selected && cell.dataset.mdColumn === String(selected.period_index)); });
    panel.focus({preventScroll: true}); panel.scrollIntoView({block: 'nearest'});
  }
  function showPeriod(period) {
    var r = root(), data = payload(); if (!data || !data.v2) return;
    var cell = (data.v2.heatmap.cells || []).find(function (c) { return String(c.index) === String(period); });
    var host = r.querySelector('[data-md2-period-detail]'); if (!cell || !host) return;
    host.hidden = false; host.replaceChildren();
    host.append(el('h3', cell.label + ' — ' + cell.proven_fail + ' failed · ' + cell.warning + ' warning · ' + cell.unavailable + ' unavailable · ' + cell.pass + ' passed of ' + cell.applicable + ' applicable checks' + (cell.highest ? ' · highest severity ' + cell.highest : '')));
    var list = el('ul', undefined, 'md2-period-list');
    if (!cell.failed_checks.length) list.append(el('li', 'No proven failed or warning check in this period.'));
    cell.failed_checks.forEach(function (f) {
      var li = el('li'), b = el('button', f.check_id + ' · ' + f.group + ' · ' + f.status + ' · ' + f.severity);
      b.type = 'button';
      if (f.check_id.indexOf('DX-') === 0) { b.setAttribute('data-md2-select', f.check_id); b.setAttribute('data-md2-period', String(cell.index)); }
      else { b.setAttribute('data-md-select', f.check_id); b.setAttribute('data-md-period', String(cell.index)); }
      li.append(b); list.append(li);
    });
    host.append(list);
    r.querySelectorAll('[data-md-column]').forEach(function (c) { c.classList.toggle('md-selected-period', c.dataset.mdColumn === String(cell.index)); });
    host.focus({preventScroll: true});
  }
  document.addEventListener('click', function (event) {
    var dx = event.target.closest('[data-md2-select]');
    if (dx) { showDx(dx.dataset.md2Select, dx.dataset.md2Period); return; }
    var heat = event.target.closest('[data-md2-period]');
    if (heat) { showPeriod(heat.dataset.md2Period); return; }
    var v1 = event.target.closest('[data-md-select]');
    if (v1 && v1.dataset.mdSelect) {
      // After V1 renders its own detail, append the root-cause relationship evidence for the same selection.
      var id = v1.dataset.mdSelect, period = v1.dataset.mdPeriod;
      setTimeout(function () {
        var r = root(), data = payload(); if (!r || !data || !data.v2) return;
        var detail = r.querySelector('[data-md-detail]'); if (!detail || detail.hidden) return;
        var old = detail.querySelector('[data-md2-v1-rootcause]'); if (old) old.remove();
        var rcs = rootCausesFor(data, id, period); if (!rcs.length) return;
        var wrap = rootCauseBlock(rcs); wrap.setAttribute('data-md2-v1-rootcause', ''); detail.append(wrap);
      }, 0);
    }
  });
}());
