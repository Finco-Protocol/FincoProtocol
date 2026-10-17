// Credit Decision workspace: presentation behaviour only. No financial calculation, no network write, no Run.
// - limits the Run picker to the maximum selection,
// - keyboard period navigation + a period detail read out of the committed server payload,
// - findings class filter.
(function () {
  'use strict';

  function payload() {
    var node = document.querySelector('[data-cd-payload]');
    if (!node) return null;
    try { return JSON.parse(node.textContent); } catch (e) { return null; }
  }
  function el(tag, text, cls) { var n = document.createElement(tag); if (text !== undefined) n.textContent = text; if (cls) n.className = cls; return n; }

  // ── Run picker: at most N selections ────────────────────────────────────────────────────────────────────────────
  function initPicker() {
    var form = document.querySelector('[data-cd-select]');
    if (!form) return;
    var max = parseInt(form.getAttribute('data-max'), 10) || 3;
    var boxes = Array.prototype.slice.call(form.querySelectorAll('input[type=checkbox][name=run]'));
    var status = form.querySelector('[data-cd-limit]');
    function sync() {
      var on = boxes.filter(function (b) { return b.checked; }).length;
      boxes.forEach(function (b) { b.disabled = !b.checked && on >= max; });
      if (status) status.textContent = on >= max ? 'Maximum of ' + max + ' Runs selected.' : (on + ' of ' + max + ' selected.');
    }
    boxes.forEach(function (b) { b.addEventListener('change', sync); });
    form.addEventListener('submit', function (ev) {
      if (!boxes.some(function (b) { return b.checked; })) { ev.preventDefault(); if (status) status.textContent = 'Select at least one committed Run.'; }
    });
    sync();
  }

  // ── Timeline: keyboard navigation + detail ──────────────────────────────────────────────────────────────────────
  function initTimeline() {
    var data = payload();
    document.querySelectorAll('[data-cd-matrix]').forEach(function (matrix) {
      var runIndex = parseInt(matrix.getAttribute('data-run'), 10);
      var buttons = Array.prototype.slice.call(matrix.querySelectorAll('button.cd-period'));
      var detail = document.querySelector('[data-cd-detail][data-run="' + runIndex + '"]');
      function select(button) {
        var period = button.getAttribute('data-period');
        matrix.querySelectorAll('[data-period].is-selected').forEach(function (n) { n.classList.remove('is-selected'); });
        matrix.querySelectorAll('td[data-period="' + period + '"]').forEach(function (n) { n.classList.add('is-selected'); });
        button.classList.add('is-selected');
        if (!detail || !data) return;
        var run = data.runs[runIndex], tl = run.timeline;
        var col = tl.columns.findIndex(function (c) { return String(c.index) === period; });
        if (col < 0) return;
        detail.hidden = false;
        detail.textContent = '';
        detail.append(el('h4', 'Period P' + period + (tl.columns[col].date ? ' · ' + tl.columns[col].date : '') + ' — committed values'));
        var list = el('dl', undefined, 'cd-detail-list');
        tl.rows.forEach(function (row) {
          var cell = row.cells[col];
          list.append(el('dt', row.label), el('dd', cell.d + (cell.reason && cell.v === null ? ' — ' + cell.reason : '')));
        });
        detail.append(list);
        var links = el('p');
        [['statements', 'Statements'], ['financing', 'Financing'], ['diagnostics', 'Diagnostics']].forEach(function (pair) {
          var a = el('a', pair[1]); a.href = run.links[pair[0]]; links.append(a, document.createTextNode(' · '));
        });
        detail.append(links);
      }
      buttons.forEach(function (button, i) {
        button.addEventListener('click', function () { select(button); });
        button.addEventListener('keydown', function (ev) {
          var next = null;
          if (ev.key === 'ArrowRight') next = buttons[Math.min(i + 1, buttons.length - 1)];
          else if (ev.key === 'ArrowLeft') next = buttons[Math.max(i - 1, 0)];
          else if (ev.key === 'Home') next = buttons[0];
          else if (ev.key === 'End') next = buttons[buttons.length - 1];
          if (next) { ev.preventDefault(); next.focus(); next.scrollIntoView({ block: 'nearest', inline: 'nearest' }); }
        });
      });
    });
  }

  // ── Findings filter ─────────────────────────────────────────────────────────────────────────────────────────────
  function initFilters() {
    var group = document.querySelector('[data-cd-filters]');
    if (!group) return;
    var rows = Array.prototype.slice.call(document.querySelectorAll('.cd-findings tbody tr'));
    group.querySelectorAll('button[data-class]').forEach(function (chip) {
      chip.addEventListener('click', function () {
        var klass = chip.getAttribute('data-class');
        group.querySelectorAll('button[data-class]').forEach(function (c) { var on = c === chip; c.classList.toggle('is-on', on); c.setAttribute('aria-pressed', on ? 'true' : 'false'); });
        rows.forEach(function (r) { r.hidden = !(klass === 'ALL' || r.getAttribute('data-class') === klass); });
      });
    });
  }

  function init() { initPicker(); initTimeline(); initFilters(); }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init); else init();
})();
